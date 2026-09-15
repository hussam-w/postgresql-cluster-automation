"""Synthetic documentation-only TEST-NET policy, never a deployment inventory."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    c = yaml.safe_load((ROOT / 'inventories/example/group_vars/all.yml').read_text())['cluster']
    c.update(name='test_cluster', bootstrap_host='pg1', etcd_token='test-token', vip='192.0.2.10',
             vip_prefix=24, vip_dns_name='db.example.test', vrid=42,
             data_dir='/srv/postgres/data', etcd_data_dir='/srv/etcd/data',
             postgres_mount='/srv/postgres', etcd_mount='/srv/etcd',
             allowed_filesystems=['ext4', 'xfs'], min_free_bytes=10737418240,
             min_ram_mb=8192, min_vcpus=4, locale='C.UTF-8', watchdog_device='/dev/watchdog',
             client_cidrs=['198.51.100.0/24'], admin_cidrs=['203.0.113.0/24'])
    c['packages'] = {key: '1.2.3-test' for key in c['packages']}
    c['etcd_artifact'] = {'url': 'https://example.test/etcd.tar.gz', 'sha256': 'a' * 64}
    c['expected_versions'] = dict(patroni='4.0.0', etcd='3.5.0', haproxy='2.8.0', pgbouncer='1.24.0', keepalived='2.2.8')
    c['replication'].update(mode='strict_sync', synchronous_node_count=1, maximum_lag_on_failover=1048576,
                            read_lag_bytes=1048576, ttl=60, loop_wait=5, retry_timeout=5,
                            max_slot_wal_keep_size_mb=4096, max_wal_senders=8, max_replication_slots=8)
    c['postgres'].update(max_connections=200, superuser_reserved_connections=5, shared_buffers_mb=1024, max_wal_size_mb=1024)
    c['pool'].update(mode='transaction', max_client_conn=500, default_pool_size=10, reserve_pool_size=5, max_db_connections=50)
    c['timeouts'].update(connect_seconds=5, client_seconds=300, server_seconds=300)
    c['etcd'].update(heartbeat_ms=100, election_ms=1000, quota_bytes=2147483648)
    c['backup'].update(archive_executable='/opt/test/archive', restore_executable='/opt/test/restore',
                       destination_description='test only', retention_description='test only', rpo_seconds=0, rto_seconds=300)
    c['evidence'] = {key: 'TEST-EVIDENCE-NOT-PRODUCTION' for key in c['evidence']}
    nodes = {f'pg{i}': dict(address=f'192.0.2.{20+i}', dns_name=f'pg{i}.example.test', interface='eth0',
                            priority=160-i*10, failure_domain=f'test-domain-{i}', firewall_sha256='test') for i in range(1, 4)}
    return c, nodes
