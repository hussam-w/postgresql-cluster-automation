import sys
import unittest
import importlib.util
import json
import jinja2
from fixture import ROOT

sys.path.insert(0, str(ROOT))
from module_utils.discovery_helpers import (
    CONTROL_FIELDS, SSH_FIELDS, existing_state_detected, relevant_packages, selected_settings, sanitize_mount_metadata,
)

spec = importlib.util.spec_from_file_location('discovery_runner', ROOT / 'tools/run_discovery.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class DiscoveryTests(unittest.TestCase):
    def test_ssh_output_is_allowlisted(self):
        result = selected_settings('passwordauthentication yes\npermitrootlogin no\nprivate_setting SECRET_SENTINEL', SSH_FIELDS)
        self.assertEqual(result, {'passwordauthentication': 'yes', 'permitrootlogin': 'no'})
        self.assertNotIn('SECRET_SENTINEL', str(result))

    def test_control_metadata_does_not_export_unselected_fields(self):
        result = selected_settings('Database system identifier: 12345\nHidden setting: SECRET_SENTINEL', CONTROL_FIELDS, ':')
        self.assertEqual(result, {'Database system identifier': '12345'})

    def test_only_relevant_packages_are_reported(self):
        result = relevant_packages('postgresql-17\t17.0\nopenssl\t3.0\nhaproxy\t2.8\nmalformed')
        self.assertEqual([item['name'] for item in result], ['postgresql-17', 'haproxy'])

    def test_existing_config_is_not_treated_as_fresh(self):
        self.assertTrue(existing_state_detected([], [], [{'exists': True}], []))
        self.assertTrue(existing_state_detected([], [], [], [{'kind': 'possible_etcd_member_data'}]))
        self.assertFalse(existing_state_detected([], [], [{'exists': False}], []))

    def test_runner_uses_hidden_prompts_without_password_variables(self):
        argv = runner.command(22, True, inventory='explicit.yml')
        self.assertIn('--ask-pass', argv)
        self.assertIn('--ask-become-pass', argv)
        values = json.loads(argv[argv.index('-e') + 1])
        self.assertNotIn('ansible_password', values)
        self.assertNotIn('ansible_become_password', values)
        self.assertIn('StrictHostKeyChecking=yes', values['ansible_ssh_common_args'])

    def test_runner_does_not_assume_sudo_when_unprivileged(self):
        self.assertNotIn('--ask-become-pass', runner.command(22, False, inventory='explicit.yml'))
        with self.assertRaises(ValueError):
            runner.command(0, False)

    def test_mount_credentials_are_redacted(self):
        value = {'source': '//user:SECRET_SENTINEL@server/share', 'options': 'rw,password=SECRET_SENTINEL,credentials=/private/file'}
        output = sanitize_mount_metadata(value)
        self.assertNotIn('SECRET_SENTINEL', str(output))
        self.assertNotIn('/private/file', str(output))
        self.assertIn('server/share', output['source'])

    def test_unreachable_report_does_not_copy_raw_failure_messages(self):
        environment = jinja2.Environment(undefined=jinja2.ChainableUndefined)
        environment.filters['to_json'] = json.dumps
        environment.filters['to_nice_json'] = json.dumps
        template = environment.from_string((ROOT / 'roles/discovery/templates/report.json.j2').read_text())
        output = template.render(groups={'target_vms': ['vm1']}, hostvars={
            'vm1': {'management_ip': '192.0.2.1', 'intended_roles': {'postgresql': None},
                    'discovery_observation': {'failed': True, 'msg': 'SECRET_SENTINEL'}}})
        report = json.loads(output)
        self.assertIsNone(report['targets']['vm1']['report'])
        self.assertNotIn('SECRET_SENTINEL', output)
        self.assertFalse(report['bootstrap_approved'])


if __name__ == '__main__':
    unittest.main()
