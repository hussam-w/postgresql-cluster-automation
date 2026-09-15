import copy
import sys
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from module_utils.reconcile_policy import normalized, plan_settings, fingerprint, dynamic_candidate
from filter_plugins.reconciliation import reconciliation_errors


def settings():
    return {
        'log_min_duration_statement': dict(setting='1000', unit='ms', vartype='integer', context='superuser',
                                           min_val='-1', max_val='2147483647', pending_restart=False),
        'log_checkpoints': dict(setting='on', unit=None, vartype='bool', context='sighup', pending_restart=False),
        'checkpoint_completion_target': dict(setting='0.9', unit=None, vartype='real', context='sighup',
                                             min_val='0', max_val='1', pending_restart=False),
    }


class ParameterPlanningTests(unittest.TestCase):
    def test_dynamic_merge_preserves_foreign_keys_and_original(self):
        original = {'ttl': 60, 'synchronous_mode': True, 'postgresql': {
            'use_slots': True, 'parameters': {'archive_command': 'owned by another procedure', 'fsync': 'on'}}}
        saved = copy.deepcopy(original)
        result = dynamic_candidate(original, {'log_checkpoints': {'after': 'on'}})
        self.assertEqual(saved, original)
        self.assertEqual('owned by another procedure', result['postgresql']['parameters']['archive_command'])
        self.assertTrue(result['synchronous_mode'])
        self.assertEqual('on', result['postgresql']['parameters']['log_checkpoints'])
    def test_equivalent_units_are_noop(self):
        result = plan_settings({'log_min_duration_statement': '1s'}, settings(), 170011)
        self.assertEqual({}, result['changes'])
        self.assertEqual(['log_min_duration_statement'], result['compliant'])

    def test_repeated_desired_state_is_noop(self):
        desired = {'log_min_duration_statement': '2s'}
        first = plan_settings(desired, settings(), 170011)
        current = settings()
        current['log_min_duration_statement']['setting'] = first['changes']['log_min_duration_statement']['after']
        self.assertFalse(plan_settings(desired, current, 170011)['changes'])

    def test_boolean_and_float_equivalence(self):
        self.assertFalse(plan_settings({'log_checkpoints': True, 'checkpoint_completion_target': '0.900'}, settings(), 170000)['changes'])

    def test_unsafe_restart_unknown_and_sql_parameters_refused(self):
        for name in ['shared_buffers', 'fsync', 'archive_command', 'primary_conninfo', 'port', 'bad; DROP DATABASE x']:
            self.assertTrue(plan_settings({name: 'off'}, settings(), 170000)['blockers'])

    def test_version_and_context_are_detected_not_assumed(self):
        for version in [90600, 120000, 130000]:
            self.assertTrue(plan_settings({'log_checkpoints': False}, settings(), version)['blockers'])
        for context in ['postmaster', 'internal', 'backend', 'superuser-backend']:
            current = settings()
            current['log_checkpoints']['context'] = context
            self.assertTrue(plan_settings({'log_checkpoints': False}, current, 170000)['blockers'])

    def test_invalid_units_range_and_fractional_values_fail(self):
        for value in ['2MB', '1ms; SELECT 1', '-2', '2147483648', '0.1ms', 'NaN']:
            self.assertTrue(plan_settings({'log_min_duration_statement': value}, settings(), 170000)['blockers'])

    def test_pending_restart_not_hidden(self):
        current = settings()
        current['log_checkpoints']['pending_restart'] = True
        self.assertTrue(plan_settings({'log_checkpoints': True}, current, 170000)['blockers'])

    def test_role_and_command_line_overrides_are_not_mistaken_for_server_defaults(self):
        for source in ['user', 'database', 'database user', 'session', 'command line']:
            current = settings()
            current['log_checkpoints']['source'] = source
            self.assertTrue(plan_settings({'log_checkpoints': True}, current, 170000)['blockers'])

    def test_fingerprint_changes_on_identity_policy_or_configuration(self):
        before = {'system_id': '123', 'files': {'a': 'sha'}, 'desired': {'log_checkpoints': True}}
        for key in before:
            after = copy.deepcopy(before)
            after[key] = 'different'
            self.assertNotEqual(fingerprint(before), fingerprint(after))
        self.assertEqual(fingerprint(before), fingerprint(dict(reversed(list(before.items())))))

    def test_replica_nonconvergence_and_observation_failure_fail(self):
        record = {'item': {'parameters': {'log_min_duration_statement': '2s'}}, 'report': {
            'manager': 'patroni', 'identity': {'system_id': '123', 'version': 170000},
            'settings': settings(), 'plan': {'blockers': []}}}
        replica = copy.deepcopy(record)
        replica['item']['parameters'] = {}
        self.assertTrue(reconciliation_errors([{'results': [record, replica]}], True))
        self.assertTrue(reconciliation_errors([{'results': [{'failed': True}]}]))


class EntrypointTests(unittest.TestCase):
    def test_default_site_only_plans(self):
        plays = yaml.safe_load((ROOT / 'playbooks/site.yml').read_text())
        for play in plays:
            target = play.get('ansible.builtin.import_playbook')
            if target and target != 'postgresql.yml':
                self.assertIn("execution_mode | default('plan')", play['when'])
        self.assertFalse(any('roles' in play for play in plays))

    def test_all_legacy_mutators_start_with_guard(self):
        safe = {'site', 'inspect', 'reconcile', 'maintenance-gate', 'validate-inputs', 'preflight',
                'verify', 'discover', 'diagnose-platform', 'ip-migration-discover', 'ip-migration-diagnose', 'postgresql', 'extensions', 'model-validate', 'storage-resolve'}
        for path in (ROOT / 'playbooks').glob('*.yml'):
            if path.stem not in safe:
                with self.subTest(path=path.name):
                    play = yaml.safe_load(path.read_text())[0]
                    self.assertEqual('maintenance-gate.yml', play.get('ansible.builtin.import_playbook'))
                    self.assertEqual(path.stem, play['vars']['guarded_operation'])

    def test_platform_management_is_opt_in(self):
        defaults = yaml.safe_load((ROOT / 'roles/platform/defaults/main.yml').read_text())
        for scope in ['storage', 'network', 'hosts', 'firewall', 'watchdog']:
            self.assertIs(defaults['platform_manage_' + scope], False)


if __name__ == '__main__':
    unittest.main()
