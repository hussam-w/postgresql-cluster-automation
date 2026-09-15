import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_utils.deployment_model import validate_model, extension_plan


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.hosts = ['pg01', 'pg02', 'pg03', 'pg04', 'pg05']
        self.core = ['pg01', 'pg04', 'pg05']
        self.model = {'mode': 'cluster', 'major': '17', 'topology': {
            'primary': 'pg01', 'replicas': ['pg02', 'pg03'], 'standby': ['pg04', 'pg05'],
            'total_nodes': 5, 'replica_count': 2, 'standby_count': 2}, 'extensions': []}

    def check(self, model=None):
        return validate_model(model or self.model, self.hosts, self.core, self.core)

    def test_five_node_role_mapping(self):
        result = self.check()
        self.assertFalse(result['errors'])
        self.assertEqual('replica', result['roles']['pg02'])
        self.assertEqual('standby', result['roles']['pg04'])

    def test_unknown_fields_fail_instead_of_silently_disabling_intent(self):
        model = copy.deepcopy(self.model)
        model['extensons'] = ['pgaudit']
        self.assertTrue(self.check(model)['errors'])
        model = copy.deepcopy(self.model)
        model['topology']['replica'] = ['pg02']
        self.assertTrue(self.check(model)['errors'])

    def test_standalone_has_no_ha_components(self):
        model = {'mode': 'standalone', 'major': '17', 'topology': {'primary': 'db'}}
        self.assertFalse(validate_model(model, ['db'])['errors'])
        self.assertTrue(validate_model(model, ['db'], ['db'], ['db'])['errors'])

    def test_missing_unknown_conflicting_and_duplicate_hosts_fail(self):
        for replicas in [['pg02'], ['pg02', 'unknown'], ['pg01', 'pg02'], ['pg02', 'pg02']]:
            model = copy.deepcopy(self.model)
            model['topology']['replicas'] = replicas
            self.assertTrue(self.check(model)['errors'])

    def test_counts_are_checked_and_booleans_are_not_counts(self):
        for key in ['total_nodes', 'replica_count', 'standby_count']:
            for value in [99, True, '2']:
                model = copy.deepcopy(self.model)
                model['topology'][key] = value
                self.assertTrue(self.check(model)['errors'])

    def test_unqualified_versions_modes_and_architectures_fail(self):
        for key, value in [('major', '13'), ('major', '18.1'), ('major', 17), ('mode', 'multi-primary'), ('architecture', 'unknown')]:
            model = copy.deepcopy(self.model)
            model[key] = value
            self.assertTrue(self.check(model)['errors'])

    def test_ha_needs_an_eligible_standby(self):
        model = copy.deepcopy(self.model)
        model['topology']['replicas'] += model['topology'].pop('standby')
        self.assertTrue(self.check(model)['errors'])

    def test_baseline_and_dependencies_are_automatic(self):
        plan = extension_plan(['pg_stat_kcache', 'pgcrypto'], '17')
        self.assertEqual(['plpgsql', 'pg_stat_statements', 'pg_stat_kcache', 'pgcrypto'], plan['extensions'])
        self.assertEqual(['pg_stat_statements', 'pg_stat_kcache'], plan['preload'])
        self.assertIn('postgresql-17-pg-stat-kcache', plan['packages'])

    def test_no_optional_extensions_imposed(self):
        self.assertEqual(['plpgsql'], extension_plan([], '17')['extensions'])
        self.assertEqual([], extension_plan(['pgcrypto'], '17')['preload'])

    def test_unsafe_or_duplicate_extensions_fail(self):
        for extensions in [['pgcrypto', 'pgcrypto'], ['pgcrypto; DROP DATABASE postgres'], 'pgaudit']:
            with self.assertRaises(ValueError):
                extension_plan(extensions, '17')

    def test_optional_count_fields_can_be_derived(self):
        for key in ['total_nodes', 'replica_count', 'standby_count']:
            self.model['topology'].pop(key)
        self.assertFalse(self.check()['errors'])


if __name__ == '__main__':
    unittest.main()
