import copy
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import yaml
from fixture import fixture
from render_templates import render
from module_utils.deployment_components import component_plan, cluster_components
from module_utils.deployment_model import validate_model, extension_plan
from module_utils.cluster_contract import validate_contract
from tools.controller_config import boolean


class ComponentTests(unittest.TestCase):
    def model(self, hosts, standby=(), replicas=(), routing=False, degraded=False):
        return {'mode': 'cluster', 'architecture': 'modular', 'major': '17',
                'components': {'backup': False, 'haproxy': routing},
                'allow_degraded_topology': degraded,
                'topology': {'primary': hosts[0], 'standby': list(standby), 'replicas': list(replicas)}}

    def test_boolean_options_never_treat_false_string_as_true(self):
        self.assertFalse(boolean('false'))
        self.assertTrue(boolean('true'))
        for value in ('False', '', 'yes', '1', False):
            with self.assertRaises(ValueError):
                boolean(value)
        with self.assertRaises(ValueError):
            component_plan({'mode': 'cluster', 'components': {'backup': 'false'}})

    def test_zero_optional_components_on_standalone(self):
        model = {'mode': 'standalone', 'major': '17', 'topology': {'primary': 'pg1'}, 'extensions': []}
        plan = validate_model(model, ['pg1'])
        self.assertFalse(plan['errors'])
        self.assertEqual({'backup': False, 'haproxy': False}, plan['components'])
        self.assertFalse(plan['automatic_failover_available'])

    def test_topology_sizes_and_explicit_non_ha_acknowledgment(self):
        for count in (1, 2, 3, 5, 7):
            hosts = ['pg' + str(i) for i in range(1, count+1)]
            core = hosts[:3] if count >= 3 else hosts[:1]
            model = self.model(hosts, standby=hosts[1:], degraded=count < 3)
            result = validate_model(model, hosts, core, [])
            self.assertFalse(result['errors'], result['errors'])
            self.assertEqual(count >= 3, result['automatic_failover_available'])
        model = self.model(['pg1'], degraded=False)
        self.assertTrue(validate_model(model, ['pg1'], ['pg1'], [])['errors'])

    def test_zero_eligible_standbys_requires_acknowledgment(self):
        hosts = ['pg1', 'pg2', 'pg3']
        model = self.model(hosts, replicas=hosts[1:])
        self.assertTrue(validate_model(model, hosts, hosts, [])['errors'])
        model['allow_degraded_topology'] = True
        self.assertFalse(validate_model(model, hosts, hosts, [])['errors'])

    def test_disabled_router_and_backup_contract_has_no_phantom_dependencies(self):
        cluster, nodes = fixture()
        original = copy.deepcopy(cluster)
        model = self.model(list(nodes), standby=['pg2', 'pg3'])
        selected = cluster_components(cluster, model)
        self.assertEqual(original, cluster)
        for key in ('vip', 'vip_dns_name', 'vip_prefix', 'vrid', 'backup'):
            selected.pop(key)
        for key in ('haproxy', 'keepalived'):
            selected['expected_versions'].pop(key)
            self.assertNotIn(key, selected['packages'])
        self.assertFalse(validate_contract(selected, nodes, list(nodes), []))
        self.assertEqual(selected, cluster_components(selected, model))

    def test_router_membership_and_counts_must_match(self):
        hosts = ['pg1', 'pg2', 'pg3']
        model = self.model(hosts, standby=hosts[1:])
        self.assertTrue(validate_model(model, hosts, hosts, hosts)['errors'])
        model['components']['haproxy'] = True
        self.assertFalse(validate_model(model, hosts, hosts, hosts)['errors'])
        model['topology']['standby_count'] = 1
        self.assertTrue(validate_model(model, hosts, hosts, hosts)['errors'])

    def test_custom_extension_dependencies_and_missing_cycles(self):
        registry = {'pg_trgm': {'package': 'postgresql-{major}', 'requires': [], 'preload': []},
                    'example_ext': {'package': 'postgresql-{major}-example', 'requires': ['pg_trgm'], 'preload': ['example_ext']}}
        plan = extension_plan(['example_ext'], '18', registry)
        self.assertEqual(['plpgsql', 'pg_trgm', 'example_ext'], plan['extensions'])
        self.assertIn('postgresql-18-example', plan['packages'])
        registry['pg_trgm']['requires'] = ['example_ext']
        with self.assertRaises(ValueError):
            extension_plan(['example_ext'], '18', registry)
        registry['pg_trgm']['requires'] = ['missing']
        with self.assertRaises(ValueError):
            extension_plan(['example_ext'], '18', registry)

    def test_direct_database_template_and_one_node_routing(self):
        for count, routing in ((1, True), (3, False), (3, True)):
            hosts = ['pg' + str(i) for i in range(1, count+1)]
            model = self.model(hosts, standby=hosts[1:], routing=routing, degraded=count == 1)
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                render(Path(directory), model=model, node_count=count)
                patroni = yaml.safe_load((Path(directory) / 'patroni.yml').read_text())
                self.assertEqual('off', patroni['bootstrap']['dcs']['postgresql']['parameters']['archive_mode'])
                self.assertNotIn('recovery_conf', patroni['bootstrap']['dcs']['postgresql'])
                if not routing:
                    self.assertTrue(any('198.51.100.0/24' in row for row in patroni['postgresql']['pg_hba']))
                haproxy = (Path(directory) / 'haproxy.cfg').read_text()
                self.assertEqual(count > 1, 'frontend postgres_read' in haproxy)
