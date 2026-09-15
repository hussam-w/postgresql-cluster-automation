import copy
import unittest
from fixture import ROOT
from module_utils.deployment_model import extension_plan, validate_model
from module_utils.extension_lifecycle import merge_preloads, native_extension_order, health_errors
from tools.controller_config import extension_names


class ExtensionLifecycleTests(unittest.TestCase):
    def test_native_unknown_names_are_observed_without_guessing_packages(self):
        plan = extension_plan(['third_party_local'], '17')
        self.assertEqual(['plpgsql', 'third_party_local'], plan['extensions'])
        self.assertEqual(['postgresql-17'], plan['packages'])

    def test_alias_and_major_dependent_package_mapping(self):
        for major in ('14', '17', '18', '19'):
            plan = extension_plan(['pgvector', 'timescaledb'], major)
            self.assertIn('vector', plan['extensions'])
            self.assertNotIn('pgvector', plan['extensions'])
            self.assertIn('postgresql-' + major + '-pgvector', plan['packages'])
            self.assertIn('timescaledb-2-loader-postgresql-' + major, plan['packages'])
            self.assertEqual(['timescaledb'], plan['preload'])
        with self.assertRaises(ValueError):
            extension_plan(['vector', 'pgvector'], '17')

    def test_third_party_can_declare_multiple_system_dependencies(self):
        plan = extension_plan(['custom_ext'], '17', {'custom_ext': {
            'packages': ['postgresql-{major}-custom', 'libexample1'],
            'preload': [], 'requires': ['pgcrypto']}})
        self.assertEqual(['plpgsql', 'pgcrypto', 'custom_ext'], plan['extensions'])
        self.assertIn('libexample1', plan['packages'])
        for packages in ('not-a-list', [None], ['x;touch /tmp/bad']):
            with self.assertRaises(ValueError):
                extension_plan(['custom_ext'], '17', {'custom_ext': {
                    'packages': packages, 'preload': [], 'requires': []}})

    def test_additive_preloads_preserve_order_and_are_idempotent(self):
        before = 'pg_stat_statements, auto_explain'
        desired = merge_preloads(before, ['timescaledb', 'pg_stat_statements'])
        self.assertEqual(['pg_stat_statements', 'auto_explain', 'timescaledb'], desired)
        self.assertEqual(desired, merge_preloads(','.join(desired), ['timescaledb']))
        for current in ('"quoted,name"', '/unreviewed/library', 'x;drop'):
            with self.assertRaises(ValueError):
                merge_preloads(current, [])

    def test_native_dependencies_order_cycles_and_installed_preservation(self):
        catalog = {'a': {'requires': ['b']}, 'b': {'requires': ['c']}, 'c': {}}
        self.assertEqual(['c', 'b', 'a'], native_extension_order(['a'], catalog))
        catalog['c']['requires'] = ['a']
        with self.assertRaises(ValueError):
            native_extension_order(['a'], catalog)
        catalog['a']['installed_version'] = 'old'
        self.assertEqual(['a'], native_extension_order(['a'], catalog))

    def test_health_refuses_foreign_paused_lagged_missing_and_dual_primary(self):
        responses = [{'json': {'role': role, 'state': 'running', 'database_system_identifier': '123'}}
                     for role in ('primary', 'replica', 'replica')]
        members = [{'name': name, 'state': 'running', 'role': role, 'lag': 0}
                   for name, role in [('a', 'leader'), ('b', 'replica'), ('c', 'sync_standby')]]
        self.assertFalse(health_errors(responses, members, ['a', 'b', 'c'], '123', 1024))
        for key, value in [('role', 'primary'), ('pause', True), ('database_system_identifier', 'other'), ('state', 'stopped')]:
            bad = copy.deepcopy(responses); bad[1]['json'][key] = value
            self.assertTrue(health_errors(bad, members, ['a', 'b', 'c'], '123', 1024))
        for lag in (-1, 'unknown', 1025, None):
            bad = copy.deepcopy(members); bad[1]['lag'] = lag
            self.assertTrue(health_errors(responses, bad, ['a', 'b', 'c'], '123', 1024))
        self.assertTrue(health_errors(responses, members[:-1], ['a', 'b', 'c'], '123', 1024))

    def test_environment_list_is_literal_and_clearable(self):
        self.assertEqual([], extension_names(''))
        self.assertEqual(['pgcrypto', 'pgvector'], extension_names('pgcrypto, pgvector'))
        for value in ('a,a', 'a,', '$(command)', 'pgcrypto;DROP'):
            with self.assertRaises(ValueError):
                extension_names(value)

    def test_primary_count_is_an_explicit_single_writer_assertion(self):
        model = {'mode': 'standalone', 'major': '17', 'topology': {'primary': 'a', 'primary_count': 1}}
        self.assertFalse(validate_model(model, ['a'])['errors'])
        model['topology']['primary_count'] = 2
        self.assertTrue(validate_model(model, ['a'])['errors'])
