#!/usr/bin/python
"""Read-only Ubuntu host inspection. Commands query OS state unavailable in facts."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.network_policy import nft_fingerprint, nft_has_filter_rules, resolve_ports
from ansible.module_utils.bootstrap_state import empty_transport_home


def main():
    module = AnsibleModule(argument_spec={
        'cluster': {'type': 'dict', 'required': True},
        'node': {'type': 'dict', 'required': True},
        'nodes': {'type': 'dict', 'required': True},
        'mode': {'type': 'str', 'choices': ['audit', 'bootstrap', 'resume', 'verify'], 'required': True},
        'core': {'type': 'bool', 'required': True},
        'router': {'type': 'bool', 'default': False},
    }, supports_check_mode=True)
    c, n = module.params['cluster'], module.params['node']
    errors, observations = [], {}

    def query(argv):
        try:
            result = subprocess.run(argv, text=True, capture_output=True, timeout=15, check=False)
            if result.returncode:
                errors.append('Read-only preflight query failed: ' + argv[0])
                return ''
            return result.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            errors.append('Required preflight executable missing or timed out: ' + argv[0])
            return ''

    if os.geteuid() != 0:
        errors.append('Privilege escalation must provide root for preflight')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != '22.04':
        errors.append('Supported target is Ubuntu 22.04 only')
    if not Path('/run/systemd/system').exists():
        errors.append('A systemd host is required')
    if (os.cpu_count() or 0) < c['min_vcpus']:
        errors.append('Insufficient online CPUs')
    mem = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:'))) // 1024
    if mem < c['min_ram_mb']:
        errors.append('Insufficient RAM')
    observations['ram_mb'] = mem
    for key in ['data_dir', 'etcd_data_dir', 'postgres_mount', 'etcd_mount'] + (['wal_dir'] if 'wal_dir' in c else []):
        if Path(c[key]).resolve() != Path(c[key]):
            errors.append(key + ' must not traverse symlinks')
    if socket.gethostname().split('.')[0].lower() != n['dns_name'].split('.')[0].lower():
        errors.append('System hostname must match the first label of node.dns_name')
    for key in ['postgres_mount', 'etcd_mount'] if module.params['core'] else ['postgres_mount']:
        path = c[key]
        if not os.path.ismount(path):
            errors.append(key + ' must be an already mounted filesystem')
            continue
        info = json.loads(query(['findmnt', '-J', '-T', path, '-o', 'TARGET,FSTYPE,OPTIONS']) or '{}')
        fs = info.get('filesystems', [{}])[0]
        if fs.get('fstype') not in c['allowed_filesystems'] or 'ro' in fs.get('options', '').split(','):
            errors.append(key + ' has an unapproved or read-only filesystem')
        stat = os.statvfs(path)
        free = stat.f_bavail * stat.f_frsize
        observations[key + '_free_bytes'] = free
        if free < c['min_free_bytes']:
            errors.append(key + ' has insufficient free bytes')
    watchdog = Path(c['watchdog_device'])
    if not watchdog.is_char_device():
        errors.append('A provisioned watchdog character device is required; never open it during preflight')
    if query(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value']) != 'yes':
        errors.append('Time synchronization is not confirmed by timedatectl')
    locales = {line.lower().replace('-', '') for line in query(['locale', '-a']).splitlines()}
    if c['locale'].lower().replace('-', '') not in locales:
        errors.append('cluster.locale must already be generated on the host')
    needed_fds = max(c['pool']['max_client_conn'] * 2 + 2048,
                     c['pool']['max_client_conn'] + c['postgres']['max_connections'] + 1024, 65536)
    if int(Path('/proc/sys/fs/nr_open').read_text()) < needed_fds:
        errors.append('Kernel fs.nr_open is below the configured service file-descriptor limits')
    observations['apparmor'] = query(['aa-status', '--enabled']) == ''
    firewall = query(['nft', '-j', 'list', 'ruleset'])
    parsed_firewall = json.loads(firewall or '{}')
    observations['firewall_sha256'] = nft_fingerprint(parsed_firewall)
    if not nft_has_filter_rules(parsed_firewall):
        errors.append('An inspectable nftables ingress chain and rules are required; metadata alone is not a firewall')
    if not n.get('firewall_sha256') or n['firewall_sha256'] != observations['firewall_sha256']:
        errors.append('node.firewall_sha256 must match the reviewed normalized nftables policy fingerprint')
    addr = json.loads(query(['ip', '-j', '-4', 'address', 'show']) or '[]')
    local = {a['local'] for i in addr for a in i.get('addr_info', [])}
    if n['address'] not in local:
        errors.append('Declared node address is not assigned locally')
    if module.params['router'] and c.get('components', {}).get('haproxy', True):
        iface = next((i for i in addr if i['ifname'] == n['interface']), {})
        networks = [ipaddress.ip_interface(f"{a['local']}/{a['prefixlen']}").network for a in iface.get('addr_info', [])]
        if not networks or not any(ipaddress.ip_address(c['vip']) in network for network in networks):
            errors.append('VIP is outside the actual interface subnet')
    for other in module.params['nodes'].values():
        try:
            found = {item[4][0] for item in socket.getaddrinfo(other['dns_name'], None, socket.AF_INET)}
            if found != {other['address']}:
                errors.append('A node DNS name does not resolve exclusively to its declared address')
        except socket.gaierror:
            errors.append('Node DNS resolution failed')
        query(['ip', '-j', 'route', 'get', other['address']])
    if c.get('components', {}).get('haproxy', True):
        try:
            vip_addresses = {item[4][0] for item in socket.getaddrinfo(c['vip_dns_name'], None, socket.AF_INET)}
            if vip_addresses != {c['vip']}:
                errors.append('VIP DNS must resolve exclusively to the VIP')
        except socket.gaierror:
            errors.append('VIP DNS does not resolve')
    if c.get('components', {}).get('wal_archive', True):
        for key in ['archive_executable', 'restore_executable']:
            path = Path(c['backup'][key])
            if not path.is_file() or not os.access(path, os.X_OK) or path.stat().st_mode & 0o022:
                errors.append('backup.' + key + ' must be installed, executable and not group/world writable')
    service_ports = resolve_ports(c.get('ports'))
    ports = {service_ports[key] for key in ['postgres', 'pgbouncer', 'patroni']}
    if module.params['core']:
        ports.update(service_ports[key] for key in ['etcd_client', 'etcd_peer'])
        if c.get('components', {}).get('haproxy', True):
            ports.update(service_ports[key] for key in ['write', 'read'])
    if module.params['mode'] == 'bootstrap':
        if Path('/var/lib/pg-ha-bootstrap.json').exists():
            errors.append('A recorded bootstrap plan exists; use explicit resume after inspecting partial state')
        # Inspect all vendor data locations as well as the requested destinations.
        paths = [c['data_dir'], '/var/lib/postgresql', '/etc/pg-ha', '/var/lib/pg-ha']
        if 'wal_dir' in c:
            paths.append(c['wal_dir'])
        if module.params['core']:
            paths += [c['etcd_data_dir'], '/var/lib/etcd']
        for path in paths:
            p = Path(path)
            if path == '/var/lib/postgresql' and empty_transport_home(path):
                observations['postgres_home'] = 'empty Ansible transport directories only'
                continue
            if p.is_symlink() or (p.exists() and (not p.is_dir() or any(p.iterdir()))):
                errors.append('Existing state prevents bootstrap at ' + path)
        listeners = query(['ss', '-H', '-lnt'])
        for line in listeners.splitlines():
            parts = line.split()
            if len(parts) > 3 and parts[3].rsplit(':', 1)[-1].isdigit():
                if int(parts[3].rsplit(':', 1)[-1]) in ports:
                    errors.append('A required service port is already listening')
        if c.get('components', {}).get('haproxy', True) and c['vip'] in local:
            errors.append('VIP is already locally assigned')
        for service in ['postgresql', 'patroni', 'etcd', 'haproxy', 'pgbouncer', 'keepalived']:
            result = subprocess.run(['systemctl', 'is-active', service], capture_output=True, text=True, timeout=10)
            if result.stdout.strip() == 'active':
                errors.append('A vendor service is already active: ' + service)
    if module.params['mode'] == 'resume':
        marker = Path('/var/lib/pg-ha-bootstrap.json')
        expected = {'cluster': c, 'nodes': module.params['nodes']}
        if not marker.is_file() or json.loads(marker.read_text()) != expected:
            errors.append('Resume requires the exact recorded bootstrap plan and node identities')
        if Path('/var/lib/pg-ha/identity.json').exists():
            errors.append('Completed clusters require verify or controlled maintenance, not bootstrap resume')
    if module.params['mode'] == 'verify':
        marker = Path('/var/lib/pg-ha/identity.json')
        expected = {'cluster': c, 'nodes': module.params['nodes']}
        if not marker.is_file() or json.loads(marker.read_text()) != expected:
            errors.append('Managed identity/policy differs or is absent; use reviewed change/recovery procedure')
    if errors:
        module.fail_json(msg='Host preflight failed; no deployment changes made by this module', errors=errors, observations=observations)
    module.exit_json(changed=False, observations=observations)


if __name__ == '__main__':
    main()
