import copy
import importlib.util
import sys
import unittest
from pathlib import Path

from fixture import ROOT, fixture

sys.path.insert(0, str(ROOT))
from module_utils.cluster_contract import validate_contract

spec = importlib.util.spec_from_file_location('vip', ROOT / 'roles/routing/files/check_vip.py')
vip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vip)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.cluster, self.nodes = fixture()

    def errors(self, members=None):
        return validate_contract(self.cluster, self.nodes, members or list(self.nodes), list(self.nodes))

    def test_complete_synthetic_contract(self):
        self.assertEqual([], self.errors())

    def test_missing_vip_is_rejected(self):
        self.cluster['vip'] = None
        self.assertTrue(self.errors())

    def test_even_or_duplicate_etcd_members_rejected(self):
        self.assertTrue(self.errors(['pg1', 'pg2']))
        self.assertTrue(self.errors(['pg1', 'pg1', 'pg2']))

    def test_unsafe_watchdog_timing_rejected(self):
        self.cluster['replication'].update(ttl=30, loop_wait=10, retry_timeout=10)
        self.assertTrue(self.errors())

    def test_async_requires_explicit_data_loss_policy(self):
        self.cluster['replication'].update(mode='async', synchronous_node_count=0)
        self.assertTrue(self.errors())
        self.cluster['replication']['acknowledge_async_data_loss'] = True
        self.assertEqual([], self.errors())

    def test_vip_cannot_be_node_address_or_other_subnet(self):
        for value in ['192.0.2.21', '198.51.100.10', '0.0.0.0', '192.0.2.0']:
            with self.subTest(value=value):
                self.cluster['vip'] = value
                self.assertTrue(self.errors())

    def test_shell_injection_and_path_traversal_rejected(self):
        for value in ['/srv/db;touch /tmp/x', '/srv/../etc', '/srv/$(id)']:
            self.cluster['data_dir'] = value
            self.assertTrue(self.errors())

    def test_wildcard_package_version_rejected(self):
        self.cluster['packages']['postgresql-17'] = '17.*'
        self.assertTrue(self.errors())

    def test_storage_and_failure_domains_must_be_distinct(self):
        self.cluster['etcd_data_dir'] = self.cluster['data_dir']
        self.assertTrue(self.errors())
        self.cluster, self.nodes = fixture()
        self.nodes['pg2']['failure_domain'] = self.nodes['pg1']['failure_domain']
        self.assertTrue(self.errors())

    def test_permissive_network_and_wrong_integer_type_rejected(self):
        self.cluster['client_cidrs'] = ['0.0.0.0/0']
        self.cluster['replication']['ttl'] = True
        self.assertTrue(self.errors())


class VipTests(unittest.TestCase):
    @staticmethod
    def stats(primary=('UP',), replicas=('UP',), frontend='OPEN'):
        text = '# pxname,svname,status\n'
        text += f'postgres_write,FRONTEND,{frontend}\npostgres_read,FRONTEND,{frontend}\n'
        text += ''.join(f'primary,pg{i},{s}\n' for i, s in enumerate(primary))
        text += ''.join(f'replicas,pg{i},{s}\n' for i, s in enumerate(replicas))
        return text + 'primary,BACKEND,UP\nreplicas,BACKEND,UP\n'

    def test_one_primary_and_replica_are_required(self):
        self.assertTrue(vip.usable(self.stats()))
        self.assertFalse(vip.usable(self.stats(primary=())))
        self.assertFalse(vip.usable(self.stats(primary=('UP', 'UP'))))
        self.assertFalse(vip.usable(self.stats(replicas=('DOWN',))))

    def test_transitional_or_maintenance_states_do_not_pass(self):
        for state in ['UP 1/2', 'MAINT', 'DRAIN', 'DOWN', 'NOLB']:
            self.assertFalse(vip.usable(self.stats(primary=(state,))))

    def test_closed_frontend_or_malformed_stats_fail_closed(self):
        self.assertFalse(vip.usable(self.stats(frontend='STOP')))
        self.assertFalse(vip.usable(''))
        self.assertFalse(vip.usable('garbage'))


if __name__ == '__main__':
    unittest.main()
