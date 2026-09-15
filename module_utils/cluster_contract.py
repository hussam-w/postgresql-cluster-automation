"""Pure input validation shared by the Ansible filter and offline tests.

Reject incomplete policy before any host mutation. Do not include input values
in failures: this function can encounter mistaken secret placement.
"""
import ipaddress
import re
try:
    from ansible.module_utils.network_policy import resolve_ports
    from ansible.module_utils.postgres_version import resolve_major
except ImportError:
    from module_utils.network_policy import resolve_ports
    from module_utils.postgres_version import resolve_major


def validate_contract(cluster, nodes, etcd_members, routers):
    errors = []
    if not isinstance(cluster, dict):
        return ["cluster must be a mapping"]
    try:
        resolve_ports(cluster.get('ports'))
    except ValueError as error:
        errors.append(str(error))

    modular = cluster.get('architecture') == 'modular'
    routing = cluster.get('components', {}).get('haproxy', True)
    archive = cluster.get('components', {}).get('wal_archive', True)
    if type(routing) is not bool or type(archive) is not bool:
        errors.append('Cluster component switches must be Boolean')

    def required(path):
        value = cluster
        for part in path.split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None or value == '' or value == [] or value == {}:
            errors.append(f"cluster.{path} is required")
        return value

    def integer(path, minimum=1, maximum=None):
        value = required(path)
        if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
            errors.append(f"cluster.{path} must be an integer within its documented bounds")
            return None
        return value

    for path in ['name', 'bootstrap_host', 'etcd_token', 'vip', 'vip_dns_name',
                 'data_dir', 'etcd_data_dir', 'postgres_mount', 'etcd_mount',
                 'allowed_filesystems', 'locale', 'watchdog_device', 'client_cidrs', 'admin_cidrs',
                 'backup.archive_executable', 'backup.restore_executable',
                 'backup.destination_description', 'backup.retention_description']:
        if (routing or path not in ['vip', 'vip_dns_name']) and (archive or not path.startswith('backup.')):
            required(path)
    for key in ['network_and_vrrp', 'firewall_policy', 'fencing_test', 'backup_restore_test',
                'repository_provenance', 'monitoring_and_alerts', 'exclusive_change_lock']:
        if (routing or key != 'network_and_vrrp') and (archive or key != 'backup_restore_test'):
            required('evidence.' + key)
    for key in ['patroni', 'etcd', 'haproxy', 'pgbouncer', 'keepalived']:
        if not routing and key in ['haproxy', 'keepalived']:
            continue
        value = required('expected_versions.' + key)
        if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', value):
            errors.append('expected_versions.' + key + ' must be an explicit numeric release')
        else:
            version = tuple(int(part) for part in value.split('.'))
            minimum = {'patroni': (4, 0), 'etcd': (3, 5), 'haproxy': (2, 4), 'pgbouncer': (1, 24), 'keepalived': (2, 2)}[key]
            if version < minimum:
                errors.append('expected_versions.' + key + ' is below the required feature baseline')
            if key == 'etcd' and version[:2] != (3, 5):
                errors.append('This initial implementation requires etcd 3.5.x; qualify other families separately')
    packages = required('packages')
    try:
        major = resolve_major(packages=packages if isinstance(packages, dict) else {})
    except ValueError as error:
        errors.append(str(error))
        major = 'SELECTED_MAJOR'
    package_names = ['postgresql-common', 'postgresql-' + major, 'postgresql-client-' + major, 'patroni',
                     'haproxy', 'pgbouncer', 'keepalived',
                     'python3-psycopg2', 'python3-etcd3gw']
    if not routing:
        package_names = [key for key in package_names if key not in ['haproxy', 'keepalived']]
    for key in package_names:
        value = required('packages.' + key)
        if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9.+:~_-]+', value):
            errors.append('packages.' + key + ' must be an exact apt version, without wildcards')
    if isinstance(packages, dict) and set(packages) != set(package_names):
        errors.append('packages must contain exactly the documented package names')
    artifact_url = required('etcd_artifact.url')
    artifact_checksum = required('etcd_artifact.sha256')
    if not isinstance(artifact_url, str) or not artifact_url.startswith('https://'):
        errors.append('etcd_artifact.url must use HTTPS')
    if not isinstance(artifact_checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', artifact_checksum):
        errors.append('etcd_artifact.sha256 must pin the verified release archive')
    for path in ['min_free_bytes', 'min_ram_mb', 'min_vcpus',
                 'replication.maximum_lag_on_failover', 'replication.read_lag_bytes',
                 'replication.max_slot_wal_keep_size_mb', 'replication.max_wal_senders',
                 'replication.max_replication_slots', 'postgres.max_connections',
                 'postgres.superuser_reserved_connections', 'postgres.shared_buffers_mb',
                 'postgres.max_wal_size_mb', 'pool.max_client_conn', 'pool.default_pool_size',
                 'pool.reserve_pool_size', 'pool.max_db_connections',
                 'timeouts.connect_seconds', 'timeouts.client_seconds', 'timeouts.server_seconds',
                 'etcd.heartbeat_ms', 'etcd.election_ms', 'etcd.quota_bytes',
                 'backup.rpo_seconds', 'backup.rto_seconds']:
        if not archive and path.startswith('backup.'):
            continue
        integer(path, 0 if path in ['replication.maximum_lag_on_failover', 'replication.read_lag_bytes',
                                  'backup.rpo_seconds', 'pool.reserve_pool_size'] else 1)
    if routing:
        integer('vip_prefix', 1, 32)
        integer('vrid', 1, 255)
    ttl = integer('replication.ttl', 20)
    loop = integer('replication.loop_wait')
    retry = integer('replication.retry_timeout')
    if ttl and loop and retry and (loop + 2 * retry > ttl or loop + retry >= ttl // 2):
        errors.append('Patroni timers must satisfy loop+2*retry<=ttl and loop+retry<ttl/2 for watchdog')
    sync_count = integer('replication.synchronous_node_count', 0)
    mode = required('replication.mode')
    if mode not in ['strict_sync', 'async']:
        errors.append('replication.mode must be strict_sync or async')
    if mode == 'async' and cluster.get('replication', {}).get('acknowledge_async_data_loss') is not True:
        errors.append('async replication requires acknowledge_async_data_loss: true')
    if mode == 'strict_sync' and (sync_count is None or not 1 <= sync_count < len(nodes)):
        errors.append('strict_sync requires 1..N-1 synchronous nodes')
    if mode == 'async' and sync_count != 0:
        errors.append('async requires synchronous_node_count: 0')
    if required('pool.mode') not in ['session', 'transaction']:
        errors.append('pool.mode must be session or transaction')
    if not isinstance(nodes, dict) or len(nodes) < (1 if modular else 3):
        errors.append('At least three PostgreSQL nodes are required')
        return errors
    if (len(etcd_members) not in (1, 3, 5) if modular else len(etcd_members) != 3) or len(set(etcd_members)) != len(etcd_members) or not set(etcd_members) <= set(nodes):
        errors.append('Exactly three distinct initial etcd members must be PostgreSQL nodes')
    if (not modular and set(routers) != set(etcd_members)) or (modular and ((routing and (not routers or not set(routers) <= set(etcd_members))) or (not routing and routers))):
        errors.append('Type A requires the three core nodes to be the routers')
    if cluster.get('bootstrap_host') not in etcd_members:
        errors.append('bootstrap_host must be one of the initial core nodes')
    for field in ['name', 'etcd_token', 'locale']:
        if not isinstance(cluster.get(field), str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', cluster[field]):
            errors.append(f'cluster.{field} contains invalid characters')
    addresses, dns_names, domains, priorities = [], [], [], []
    for name, node in nodes.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
            errors.append('Inventory node names must be safe service identifiers')
        if not isinstance(node, dict):
            errors.append(f'node mapping missing for {name}')
            continue
        try:
            address = ipaddress.IPv4Address(node.get('address'))
            if address.is_loopback or address.is_multicast or address.is_unspecified:
                raise ValueError()
            addresses.append(str(address))
        except (ValueError, TypeError):
            errors.append(f'node.address must be a usable IPv4 address for {name}')
        dns = node.get('dns_name')
        if not isinstance(dns, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', dns):
            errors.append(f'node.dns_name is invalid for {name}')
        dns_names.append(dns)
        if name in routers:
            if not isinstance(node.get('interface'), str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', node['interface']):
                errors.append(f'node.interface is required for {name}')
            priority = node.get('priority')
            if type(priority) is not int or not 1 <= priority <= 254:
                errors.append(f'node.priority must be 1..254 for {name}')
            priorities.append(priority)
        if name in etcd_members:
            domains.append(node.get('failure_domain'))
    if len(set(addresses)) != len(nodes) or len(set(dns_names)) != len(nodes):
        errors.append('Node addresses and DNS names must be unique')
    if None in domains or '' in domains or len(set(domains)) != len(etcd_members):
        errors.append('Core nodes require three distinct declared failure domains')
    if len(set(priorities)) != len(routers):
        errors.append('Router priorities must be unique')
    if routing:
        try:
            vip = ipaddress.IPv4Address(cluster.get('vip'))
            network = ipaddress.IPv4Network(f"{vip}/{cluster.get('vip_prefix')}", strict=False)
            if str(vip) in addresses or vip.is_multicast or vip.is_loopback or vip.is_unspecified:
                raise ValueError()
            if vip in [network.network_address, network.broadcast_address]:
                raise ValueError()
            if any(ipaddress.IPv4Address(nodes[n]['address']) not in network for n in routers):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            errors.append('VIP must be a distinct usable address in the routers\' declared subnet')
        if not isinstance(cluster.get('vip_dns_name'), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', cluster['vip_dns_name']):
            errors.append('vip_dns_name must be a DNS name')
    for key in ['client_cidrs', 'admin_cidrs']:
        values = cluster.get(key)
        if not isinstance(values, list) or not values:
            errors.append(key + ' must be a nonempty CIDR list')
            continue
        for cidr in values:
            try:
                if ipaddress.IPv4Network(cidr, strict=True).prefixlen == 0:
                    raise ValueError()
            except (ValueError, TypeError):
                errors.append(key + ' must contain explicit IPv4 networks narrower than /0')
    if not isinstance(cluster.get('allowed_filesystems'), list) or not cluster['allowed_filesystems'] or any(x not in ['ext4', 'xfs'] for x in cluster['allowed_filesystems']):
        errors.append('allowed_filesystems must be a nonempty list drawn from ext4 and xfs')
    paths = ['data_dir', 'etcd_data_dir', 'postgres_mount', 'etcd_mount',
             'watchdog_device', 'backup.archive_executable', 'backup.restore_executable']
    if not archive:
        paths = [path for path in paths if not path.startswith('backup.')]
    if 'wal_dir' in cluster:
        paths.append('wal_dir')
        wal = cluster['wal_dir']
        for key in ['data_dir', 'etcd_data_dir']:
            other = cluster.get(key)
            if isinstance(wal, str) and isinstance(other, str) and (wal == other or wal.startswith(other.rstrip('/') + '/') or other.startswith(wal.rstrip('/') + '/')):
                errors.append('External WAL must not overlap PostgreSQL or etcd data')
    for key in paths:
        value = cluster
        for part in key.split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        if not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value) or '..' in value.split('/'):
            errors.append(key + ' must be an absolute path without shell metacharacters or traversal')
    for data, mount in [('data_dir', 'postgres_mount'), ('etcd_data_dir', 'etcd_mount')]:
        if isinstance(cluster.get(data), str) and isinstance(cluster.get(mount), str):
            if cluster[data] == cluster[mount] or not cluster[data].startswith(cluster[mount].rstrip('/') + '/'):
                errors.append(data + ' must be a dedicated subdirectory of the declared mount')
    a, b = cluster.get('data_dir'), cluster.get('etcd_data_dir')
    if isinstance(a, str) and isinstance(b, str) and (a == b or a.startswith(b.rstrip('/') + '/') or b.startswith(a.rstrip('/') + '/')):
        errors.append('PostgreSQL and etcd data directories must not overlap')
    try:
        if cluster['etcd']['election_ms'] < 5 * cluster['etcd']['heartbeat_ms']:
            errors.append('etcd election_ms must be at least five heartbeat intervals')
        if cluster['postgres']['shared_buffers_mb'] >= cluster['min_ram_mb']:
            errors.append('shared_buffers_mb must leave RAM for all co-located services')
        if cluster['replication']['max_wal_senders'] < len(nodes) or cluster['replication']['max_replication_slots'] < len(nodes):
            errors.append('WAL senders and slots must cover replicas plus maintenance headroom')
    except (KeyError, TypeError):
        pass  # Required/type diagnostics above are more actionable.
    return errors
