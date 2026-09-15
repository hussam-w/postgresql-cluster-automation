#!/usr/bin/python
"""Observe Linux infrastructure without applying configuration or starting services.

No shell, process argument dump, full config content, SQL mutation, authentication
change, package install, certificate generation or host-key acceptance is used.
Ansible/SSH may create normal temporary transport files and authentication logs.
"""
import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import time

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.discovery_helpers import (
    COMPONENT, CONTROL_FIELDS, SSH_FIELDS, existing_state_detected,
    relevant_packages, selected_settings, sanitize_mount_metadata,
)
from ansible.module_utils.network_policy import nft_fingerprint, nft_has_filter_rules


def main():
    module = AnsibleModule(argument_spec={
        'management_ip': {'type': 'str', 'required': True},
        'expected_hostname': {'type': 'str', 'default': None},
        'peers': {'type': 'list', 'elements': 'str', 'required': True},
        'ssh_port': {'type': 'int', 'required': True},
        'admin_user': {'type': 'str', 'required': True},
        'additional_data_roots': {'type': 'list', 'elements': 'path', 'default': []},
        'scan_roots': {'type': 'list', 'elements': 'path', 'default': []},
    }, supports_check_mode=True)
    params = module.params
    try:
        for address in [params['management_ip']] + params['peers']:
            ipaddress.IPv4Address(address)
        if not 1 <= params['ssh_port'] <= 65535:
            raise ValueError()
    except ValueError:
        module.fail_json(msg='Supply valid IPv4 management addresses and SSH port')
    issues, queries = [], []
    started = time.monotonic()

    def query(argv, optional=False, timeout=12):
        executable = shutil.which(argv[0])
        if not executable:
            queries.append({'command': argv[0], 'status': 'not_installed'})
            if not optional:
                issues.append('Required observation tool is unavailable: ' + argv[0])
            return None
        try:
            result = subprocess.run([executable] + argv[1:], capture_output=True, text=True,
                                    timeout=timeout, check=False, env=dict(os.environ, LC_ALL='C'))
        except (OSError, subprocess.TimeoutExpired):
            queries.append({'command': argv[0], 'status': 'failed_or_timed_out'})
            if not optional:
                issues.append('Observation query could not complete: ' + argv[0])
            return None
        queries.append({'command': argv[0], 'status': 'ok' if result.returncode == 0 else 'failed',
                        'returncode': result.returncode})
        if result.returncode != 0:
            if not optional:
                issues.append('Observation query failed or needs privileges: ' + argv[0])
            return None
        return result.stdout

    def json_query(argv, optional=False):
        value = query(argv, optional)
        if value is None:
            return None
        try:
            return json.loads(value)
        except ValueError:
            issues.append('Observation tool returned unparseable structured output: ' + argv[0])
            return None

    def read_text(path, limit=65536):
        try:
            with open(path, encoding='utf-8', errors='replace') as stream:
                return stream.read(limit)
        except OSError:
            issues.append('Cannot inspect required file: ' + str(path))
            return ''

    def metadata(path):
        try:
            info = os.lstat(path)
            return {'path': str(path), 'exists': True, 'mode': oct(stat.S_IMODE(info.st_mode)),
                    'uid': info.st_uid, 'gid': info.st_gid,
                    'kind': 'symlink' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'file'}
        except FileNotFoundError:
            return {'path': str(path), 'exists': False}
        except OSError:
            issues.append('Permission or I/O error inspecting path: ' + str(path))
            return {'path': str(path), 'exists': None}

    os_release = selected_settings(read_text('/etc/os-release'),
                                   {'ID', 'VERSION_ID', 'PRETTY_NAME', 'VERSION_CODENAME'}, '=')
    os_release = {key: value.strip('"') for key, value in os_release.items()}
    memory = selected_settings(read_text('/proc/meminfo'), {'MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'}, ':')
    addresses = json_query(['ip', '-j', 'address', 'show'])
    routes = json_query(['ip', '-j', 'route', 'show', 'table', 'all'])
    mounts = json_query(['findmnt', '-J', '-l', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'])
    disks = json_query(['lsblk', '-J', '-b', '-o', 'NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,RO'])
    hostname = socket.gethostname()
    if params['expected_hostname'] and hostname != params['expected_hostname']:
        issues.append('Observed hostname does not match expected_hostname')
    local_addresses = [a.get('local') for i in addresses or [] for a in i.get('addr_info', [])]
    local_management_match = params['management_ip'] in local_addresses
    if not local_management_match:
        issues.append('Management IP is not locally assigned; investigate NAT/address mapping before assigning service addresses')

    peers = []
    for address in params['peers']:
        if address == params['management_ip']:
            continue
        before = time.monotonic()
        try:
            with socket.create_connection((address, params['ssh_port']), timeout=3):
                reachable = True
        except OSError:
            reachable = False
            issues.append('Peer SSH-port TCP connectivity failed from this node to ' + address)
        peers.append({'destination': address, 'port': params['ssh_port'], 'tcp_reachable': reachable,
                      'elapsed_ms': round((time.monotonic() - before) * 1000),
                      'application_port_reachability_proven': False})

    if shutil.which('dpkg-query'):
        package_output = query(['dpkg-query', '-W', '-f', '${binary:Package}\t${Version}\n'])
    elif shutil.which('rpm'):
        package_output = query(['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\n'])
    else:
        package_output = None
        issues.append('No supported package inventory tool; manual package inspection required')
    packages = relevant_packages(package_output or '')
    unit_output = query(['systemctl', 'list-unit-files', '--no-legend', '--no-pager']) or ''
    unit_names = [line.split()[0] for line in unit_output.splitlines() if line.split() and COMPONENT.search(line.split()[0])]
    active_output = query(['systemctl', 'list-units', '--all', '--no-legend', '--no-pager', '--plain']) or ''
    unit_names += [line.split()[0] for line in active_output.splitlines() if line.split() and COMPONENT.search(line.split()[0])]
    unit_fields = {'Id', 'ActiveState', 'SubState', 'UnitFileState', 'FragmentPath', 'DropInPaths', 'User', 'MainPID'}
    units = []
    for unit in sorted(set(unit_names))[:100]:
        if '@.' in unit:
            units.append({'Id': unit, 'ActiveState': 'template', 'SubState': 'not-an-instance'})
            continue
        value = query(['systemctl', 'show', unit, '--property=' + ','.join(sorted(unit_fields))])
        if value is not None:
            units.append(selected_settings(value, unit_fields, '='))

    config_roots = ['/etc/postgresql', '/etc/patroni', '/etc/etcd', '/etc/haproxy',
                    '/etc/pgbouncer', '/etc/keepalived', '/etc/pg-ha',
                    '/etc/patroni.yml', '/etc/patroni.yaml', '/etc/etcd.conf',
                    '/etc/default/etcd', '/etc/default/patroni', '/var/lib/pg-ha']
    configurations = [metadata(root) for root in config_roots]
    config_children = []
    for root in config_roots:
        if os.path.isdir(root) and not os.path.islink(root):
            try:
                for entry in sorted(os.scandir(root), key=lambda entry: entry.name)[:50]:
                    config_children.append(metadata(entry.path))
            except OSError:
                issues.append('Cannot list existing configuration directory: ' + root)

    data_roots = ['/var/lib/postgresql', '/var/lib/pgsql', '/var/lib/etcd', '/srv', '/data', '/pgdata', '/opt']
    for mount in (mounts or {}).get('filesystems', []):
        target = mount.get('target', '')
        if target not in ['/', '/boot', '/boot/efi'] and mount.get('fstype') in ['ext4', 'xfs', 'btrfs', 'zfs']:
            data_roots.append(target)
    data_roots += params['additional_data_roots']
    if params['scan_roots']:
        data_roots = params['scan_roots'] + params['additional_data_roots']
    markers, visited, searched = [], set(), []
    count = 0
    limit_reached = False
    for root in sorted(set(data_roots)):
        if not os.path.isabs(root) or os.path.realpath(root) != root:
            issues.append('Data search root skipped because it is relative or traverses symlinks: ' + root)
            continue
        if not os.path.isdir(root):
            continue
        searched.append(root)
        for directory, dirs, files in os.walk(root, followlinks=False,
                                             onerror=lambda error: issues.append('Data search permission/I/O gap: ' + str(error.filename))):
            if directory in visited:
                dirs[:] = []
                continue
            visited.add(directory)
            count += len(dirs) + len(files)
            if count > 10000 or time.monotonic() - started > 90:
                dirs[:] = []
                limit_reached = True
                break
            if len(Path(directory).relative_to(root).parts) >= 6:
                if dirs:
                    limit_reached = True
                dirs[:] = []
            for filename in files:
                if filename in ['PG_VERSION', 'patroni.dynamic.json', 'postmaster.pid', 'standby.signal', 'recovery.signal', 'identity.json']:
                    marker = metadata(os.path.join(directory, filename))
                    if filename == 'PG_VERSION':
                        major = read_text(marker['path'], 32).strip()
                        if re.fullmatch(r'\d+(?:\.\d+)?', major):
                            marker['postgres_major'] = major
                            executable = f'/usr/lib/postgresql/{major}/bin/pg_controldata'
                            if os.path.isfile(executable):
                                control = query([executable, directory], optional=True)
                                marker['control_metadata'] = selected_settings(control or '', CONTROL_FIELDS, ':')
                    markers.append(marker)
            if os.path.basename(directory) == 'member' and ('wal' in dirs or 'snap' in dirs):
                markers.append({'path': directory, 'kind': 'possible_etcd_member_data', 'exists': True})
            # PostgreSQL relation files are not relevant to discovering cluster identity.
            if 'PG_VERSION' in files:
                dirs[:] = []
        if count > 10000 or time.monotonic() - started > 90:
            break
    if limit_reached:
        issues.append('Bounded data scan reached a depth, entry or time limit; review and supply narrower scan_roots for scoped reconciliation')

    filesystems = []
    for mount in (mounts or {}).get('filesystems', []):
        target = mount.get('target')
        if target:
            try:
                usage = os.statvfs(target)
                filesystems.append({'mount': target, 'total_bytes': usage.f_blocks * usage.f_frsize,
                                    'available_bytes': usage.f_bavail * usage.f_frsize,
                                    'available_inodes': usage.f_favail, 'read_only': bool(usage.f_flag & os.ST_RDONLY)})
            except OSError:
                issues.append('Filesystem availability cannot be inspected: ' + target)

    privileged = os.geteuid() == 0
    sudo_result = 'already_root_via_requested_privilege_escalation' if privileged else 'not_verified'
    if not privileged:
        sudo_probe = query(['sudo', '-n', 'id', '-u'], optional=True)
        sudo_result = 'noninteractive_root_command_succeeded' if (sudo_probe or '').strip() == '0' else 'password_required_or_not_authorized'
        issues.append('Privileged coverage not performed; rerun with discovery_privileged=true and approved sudo credentials')
    # timedatectl does not share systemctl's comma-separated property behavior.
    ntp = query(['timedatectl', 'show', '-p', 'NTPSynchronized', '-p', 'NTP', '-p', 'Timezone'])
    time_state = selected_settings(ntp or '', {'NTPSynchronized', 'NTP', 'Timezone'}, '=')
    if time_state.get('NTPSynchronized') != 'yes':
        issues.append('Time synchronization is not confirmed')
    nft = query(['nft', '-j', 'list', 'ruleset'], optional=True)
    iptables = query(['iptables-save'], optional=True)
    firewall = {'nft_inspected': nft is not None, 'iptables_inspected': iptables is not None,
                'nft_sha256': nft_fingerprint(json.loads(nft)) if nft is not None else None,
                'host_ingress_filter_present': nft_has_filter_rules(json.loads(nft)) if nft is not None else None,
                'iptables_sha256': hashlib.sha256(iptables.strip().encode()).hexdigest() if iptables is not None else None,
                'external_firewall_policy': 'unknown', 'effective_reachability': 'only peer SSH TCP probes performed'}
    if nft is None and iptables is None:
        issues.append('Neither nftables nor iptables policy could be inspected')
    resolver = []
    for line in read_text('/etc/resolv.conf').splitlines():
        parts = line.split()
        if parts and parts[0] in ['nameserver', 'search', 'domain']:
            resolver.append({'setting': parts[0], 'values': parts[1:]})
    ssh_config = query(['sshd', '-T'], optional=True)
    ssh_policy = selected_settings(ssh_config or '', SSH_FIELDS)
    if ssh_config is None:
        issues.append('sshd effective base configuration could not be inspected')
    apparmor = query(['aa-status', '--json'], optional=True)
    selinux = query(['getenforce'], optional=True)
    listeners = query(['ss', '-H', '-lntu'])
    report = {
        'observed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'management_ip': params['management_ip'], 'management_ip_assigned_locally': local_management_match,
        'hostname': hostname, 'os': os_release, 'kernel': os.uname().release,
        'cpu_count': os.cpu_count(), 'memory': memory, 'disks': disks, 'mounts': sanitize_mount_metadata(mounts),
        'filesystem_availability': filesystems, 'interfaces': addresses, 'routes': routes,
        'resolver': resolver, 'peer_ssh_tcp_probes': peers,
        'listeners': (listeners or '').splitlines(), 'component_packages': packages,
        'component_units': units, 'configuration_paths': configurations,
        'configuration_directory_entries': config_children,
        'data_state_markers': markers, 'data_roots_searched': searched,
        'data_search_scope': 'explicit roots' if params['scan_roots'] else 'standard roots and mounted filesystems',
        'data_search_exhaustive': False, 'data_search_limit_reached': limit_reached,
        'privileged': privileged, 'sudo': sudo_result, 'time': time_state,
        'virtualization': (query(['systemd-detect-virt'], optional=True) or '').strip() or None,
        'watchdog_devices': [metadata('/dev/watchdog'), metadata('/dev/watchdog0')],
        'lvm_volume_groups': json_query(['vgs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'vg_name,vg_size,vg_free'], optional=True),
        'ssh_base_policy': ssh_policy,
        'ssh_match_blocks_validated': False,
        'security_modules': {'apparmor_inspectable': apparmor is not None, 'selinux_mode': (selinux or '').strip() or None},
        'firewall': firewall, 'query_outcomes': queries, 'coverage_issues': issues,
        'coverage_complete': not issues,
        'existing_state_detected': existing_state_detected(packages, units, configurations, markers),
        'cluster_runtime_membership_authenticated': False,
        'intended_roles': 'unknown; no roles assigned from management addresses',
        'decision': 'STOP: review observations and explicitly validate architecture; no bootstrap authorization',
    }
    module.exit_json(changed=False, report=report)


if __name__ == '__main__':
    main()
