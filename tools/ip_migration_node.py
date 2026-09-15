#!/usr/bin/python3
"""Explicitly scoped address migration; protected original files, exact drift checks.

No database/DCS data is copied, deleted or initialized. Service orchestration lives
in the playbook. Run as root only; never prints configuration contents.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import yaml

MAPPING = {}
NODES = {}
ROOT = None # Explicit protected journal directory from the reviewed configuration.
FILES = ['/etc/pg-ha/patroni/patroni.yml', '/etc/pg-ha/etcd/etcd.yml',
 '/etc/pg-ha/pgbouncer/pgbouncer.ini', '/etc/pg-ha/haproxy/haproxy.cfg',
 '/etc/pg-ha/keepalived.conf', '/etc/pgbackrest/pgbackrest.conf',
 '/etc/hosts', '/etc/netplan/90-pg-ha-service.yaml',
 '/var/lib/pg-ha-platform/firewall.nft', '/etc/pg-ha/monitor.json']

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def replace(text):
    for old, new in MAPPING.items():
        text = text.replace(old, new)
    return text

def candidate(path, phase, text, old):
    new = MAPPING[old]
    if path.endswith('/keepalived.conf') and phase in ['bridge', 'final']:
        # Both old and new VRRP sources must be accepted across the rolling move.
        # Otherwise mixed peer lists can elect two VIP owners during transition.
        lines = text.splitlines()
        peers = False
        result = []
        for line in lines:
            if 'unicast_peer {' in line:
                peers = True
            elif peers and '}' in line:
                peers = False
            result.append(line.replace(old, new) if phase == 'final' and 'unicast_src_ip' in line else line)
            if peers and line.strip() in MAPPING:
                result.append(line.replace(line.strip(), MAPPING[line.strip()]))
        return '\n'.join(result) + '\n'
    if phase == 'bridge':
        if path.endswith('/patroni.yml'):
            c = yaml.safe_load(text)
            c['restapi']['listen'] = '0.0.0.0:8008'
            c['postgresql']['listen'] = old + ',' + new + ',127.0.0.1:5432'
            c['postgresql']['pg_hba'] = [entry for h in c['postgresql']['pg_hba'] for entry in ([h, replace(h)] if any(x in h for x in MAPPING) else [h])]
            return yaml.safe_dump(c, sort_keys=False)
        if path.endswith('/etcd.yml'):
            c = yaml.safe_load(text)
            c['listen-peer-urls'] += ',https://' + new + ':2380'
            c['listen-client-urls'] += ',https://' + new + ':2379'
            return yaml.safe_dump(c, sort_keys=False)
        if path.endswith('/pgbouncer.ini'):
            return text.replace('listen_addr = ' + old, 'listen_addr = ' + old + ',' + new)
        if path.endswith('/pgbackrest.conf'):
            return text.replace('tls-server-address=' + old, 'tls-server-address=0.0.0.0')
        if path.endswith('/firewall.nft'):
            # Broaden only the exact peer address sets; preserve all other rules.
            for address, target in MAPPING.items():
                text = text.replace(address + ',', address + ', ' + target + ',').replace(address + ' }', address + ', ' + target + ' }')
            return text
    if phase == 'dns' and path == '/etc/hosts':
        return replace(text)
    if phase == 'final' and path not in ['/etc/netplan/90-pg-ha-service.yaml', '/var/lib/pg-ha-platform/firewall.nft']:
        return replace(text)
    if phase == 'cleanup':
        if path.endswith('/keepalived.conf'):
            return replace(text)
        if path == '/etc/netplan/90-pg-ha-service.yaml':
            # Reserved DHCP is retained, plus the same address configured persistently.
            # This ensures the listener address is present before lease acquisition.
            return replace(text)
        if path.endswith('/firewall.nft'):
            return replace(text)
    return None

def main():
    global MAPPING, NODES, ROOT
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='/etc/pg-ha/ip-migration.json', help='Reviewed node mapping; no implicit network targets')
    p.add_argument('phase', choices=['snapshot', 'bridge', 'dns', 'final', 'cleanup', 'commit'])
    p.add_argument('--firewall-sha')
    args = p.parse_args()
    import ipaddress
    specification = json.loads(Path(args.config).read_text())
    import re
    journal = specification['state_dir']
    if not re.fullmatch(r'/var/lib/pg-ha-migrations/[A-Za-z0-9_-]+', journal):
        raise ValueError('Use a dedicated /var/lib/pg-ha-migrations/<change-id> journal')
    ROOT = Path(journal)
    if ROOT.resolve() != ROOT:
        raise ValueError('Migration journal must not traverse a symlink')
    entries = specification['nodes']
    if not isinstance(entries, dict) or len(entries) != 3:
        raise ValueError('Legacy migration supports exactly three explicitly named core nodes')
    for name, addresses in entries.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name) or set(addresses) != {'old', 'new'}:
            raise ValueError('Each migration node requires old and new IPv4 addresses')
        for address in addresses.values():
            ipaddress.IPv4Address(address)
    NODES = {name: value['old'] for name, value in entries.items()}
    MAPPING = {value['old']: value['new'] for value in entries.values()}
    if len(MAPPING) != 3 or len(set(MAPPING.values())) != 3 or set(MAPPING) & set(MAPPING.values()):
        raise ValueError('Migration addresses must be unique and disjoint')
    if os.geteuid() or socket.gethostname().split('.')[0] not in NODES:
        raise RuntimeError('Unsupported identity or privilege')
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = ROOT / 'manifest.json'
    old = NODES[socket.gethostname().split('.')[0]]
    if args.phase == 'snapshot':
        if manifest.exists():
            raise RuntimeError('Existing migration snapshot; inspect rather than overwrite')
        state = {}
        for path in FILES + ['/var/lib/pg-ha/files.json', '/var/lib/pg-ha/identity.json']:
            src = Path(path)
            if src.is_symlink() or not src.is_file():
                raise RuntimeError('Unexpected source file type')
            dest = ROOT / path.lstrip('/')
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            dest.write_bytes(src.read_bytes())
            st = src.stat()
            state[path] = {'sha256': digest(src), 'uid': st.st_uid, 'gid': st.st_gid, 'mode': st.st_mode & 0o777}
        manifest.write_text(json.dumps(state))
        print('Protected original configuration captured')
        return
    state = json.loads(manifest.read_text())
    # Reject out-of-band edits before each operation, including baseline markers.
    for path, meta in state.items():
        st = Path(path).stat()
        if digest(path) != meta['sha256'] or (st.st_uid, st.st_gid, st.st_mode & 0o777) != (meta['uid'], meta['gid'], meta['mode']):
            raise RuntimeError('Unrecorded concurrent file change: ' + path)
    if args.phase == 'commit':
        baseline_path = Path('/var/lib/pg-ha/files.json')
        baseline = json.loads((ROOT / 'var/lib/pg-ha/files.json').read_text())
        for path, meta in baseline.items():
            st = Path(path).stat()
            if path not in FILES and digest(path) != meta['sha256']:
                raise RuntimeError('Unrelated baseline drift: ' + path)
            meta.update(sha256=digest(path), uid=st.st_uid, gid=st.st_gid, mode=format(st.st_mode & 0o777, '04o'))
        baseline_path.write_text(json.dumps(baseline, indent=2))
        identity_path = Path('/var/lib/pg-ha/identity.json')
        if not args.firewall_sha or len(args.firewall_sha) != 64:
            raise RuntimeError('Verified effective firewall digest required')
        identity = json.loads(replace((ROOT / 'var/lib/pg-ha/identity.json').read_text()))
        for node in identity['nodes'].values():
            node['firewall_sha256'] = args.firewall_sha
        identity_path.write_text(json.dumps(identity, indent=2))
        print('Only approved address-related baseline and firewall policy advanced')
        return
    changed = []
    for path in FILES:
        original = (ROOT / path.lstrip('/')).read_text()
        value = candidate(path, args.phase, original, old)
        if value is None or value == Path(path).read_text():
            continue
        staged = ROOT / ('candidate-' + Path(path).name)
        staged.write_text(value)
        command = None
        if path.endswith('/patroni.yml'):
            command = ['patroni', '--validate-config', '--ignore-listen-port', str(staged)]
        elif path.endswith('/haproxy.cfg'):
            command = ['haproxy', '-c', '-f', str(staged)]
        elif path.endswith('/keepalived.conf'):
            command = ['keepalived', '--config-test', '-f', str(staged)]
        elif path.endswith('/firewall.nft'):
            command = ['nft', '--check', '--file', str(staged)]
        elif path.endswith('/etcd.yml'):
            yaml.safe_load(value)
        if command:
            result = subprocess.run(command, capture_output=True)
            if result.returncode:
                raise RuntimeError('Native validation failed for ' + path + '; inspect restricted candidate privately')
        meta = state[path]
        temporary = Path(path + '.ip-migration-tmp')
        temporary.write_text(value)
        os.chown(temporary, meta['uid'], meta['gid'])
        temporary.chmod(meta['mode'])
        temporary.replace(path)
        state[path]['sha256'] = digest(path)
        changed.append(path)
        manifest.write_text(json.dumps(state))
    print(json.dumps({'phase': args.phase, 'changed_paths': changed}))

if __name__ == '__main__':
    main()
