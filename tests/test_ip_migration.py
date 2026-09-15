"""Transition invariants: maintain access across mixed old/new node states."""
import unittest
import yaml
from tools.ip_migration_node import candidate, MAPPING


class AddressTransitionTests(unittest.TestCase):
    def setUp(self):
        MAPPING.update({'198.51.100.21': '192.0.2.21', '198.51.100.22': '192.0.2.22', '198.51.100.23': '192.0.2.23'})
        self.addCleanup(MAPPING.clear)

    def test_replication_admission_precedes_reject(self):
        source = yaml.safe_dump({'restapi': {'listen': '198.51.100.21:8008'},
            'postgresql': {'listen': '198.51.100.21,127.0.0.1:5432', 'pg_hba': [
                'hostssl replication replicator 198.51.100.22/32 scram-sha-256',
                'host replication all 0.0.0.0/0 reject']}})
        actual = yaml.safe_load(candidate('/etc/pg-ha/patroni/patroni.yml', 'bridge', source, '198.51.100.21'))
        hba = actual['postgresql']['pg_hba']
        self.assertIn('192.0.2.22', hba[1])
        self.assertTrue(hba[-1].endswith('reject'))
        self.assertEqual(actual['postgresql']['listen'], '198.51.100.21,192.0.2.21,127.0.0.1:5432')

    def test_vrrp_accepts_mixed_sources_until_cleanup(self):
        original = 'unicast_src_ip 198.51.100.21\nunicast_peer {\n 198.51.100.22\n 198.51.100.23\n}\n'
        bridge = candidate('/etc/pg-ha/keepalived.conf', 'bridge', original, '198.51.100.21')
        final = candidate('/etc/pg-ha/keepalived.conf', 'final', original, '198.51.100.21')
        for peer in ['198.51.100.22', '198.51.100.23', '192.0.2.22', '192.0.2.23']:
            self.assertIn(peer, bridge)
            self.assertIn(peer, final)
        self.assertIn('unicast_src_ip 192.0.2.21', final)
        cleanup = candidate('/etc/pg-ha/keepalived.conf', 'cleanup', original, '198.51.100.21')
        self.assertFalse(any(old in cleanup for old in MAPPING))

    def test_firewall_transition_preserves_unrelated_acl(self):
        original = 'ip saddr { 198.51.100.21, 198.51.100.22, 198.51.100.23 } tcp dport 2379 accept\nip saddr 10.0.0.0/24 tcp dport 22 accept\n'
        bridge = candidate('/var/lib/pg-ha-platform/firewall.nft', 'bridge', original, '198.51.100.21')
        for value in list(MAPPING) + list(MAPPING.values()):
            self.assertIn(value, bridge)
        self.assertIn('ip saddr 10.0.0.0/24 tcp dport 22 accept', bridge)


if __name__ == '__main__':
    unittest.main()
