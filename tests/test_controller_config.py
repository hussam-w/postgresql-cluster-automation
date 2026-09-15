import shlex
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.controller_config import load, file_path, ssh_options


class ControllerConfigTests(unittest.TestCase):
    def read(self, text, environ=None):
        with patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'read_text', return_value=text):
            return load('chosen.env', environ={} if environ is None else environ)

    def test_environment_overrides_file_and_quotes_are_literal(self):
        result = self.read('PGHA_INVENTORY="inventories/customer a/hosts.yml"\nPGHA_SSH_AUTH=key', {'PGHA_SSH_AUTH': 'password'})
        self.assertEqual(result['PGHA_INVENTORY'], 'inventories/customer a/hosts.yml')
        self.assertEqual(result['PGHA_SSH_AUTH'], 'password')

    def test_no_implicit_inventory(self):
        with patch.object(Path, 'is_file', return_value=False):
            self.assertEqual(load(environ={}), {})
        with self.assertRaises(ValueError):
            file_path(None, 'Inventory')

    def test_typo_secret_and_duplicate_keys_fail(self):
        for value in ('ANSIBLE_PASSWORD=hidden', 'PGHA_INVENTORY=a\nPGHA_INVENTORY=b', 'export PGHA_INVENTORY=a'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read(value)

    def test_no_shell_expansion_or_commands(self):
        for value in ('$(touch sentinel)', '`command`', '$HOME/hosts.yml', '"unclosed'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read('PGHA_INVENTORY=' + value)

    def test_explicit_missing_file_is_an_error(self):
        with patch.object(Path, 'is_file', return_value=False), self.assertRaises(ValueError):
            load('missing.env', environ={})

    def test_known_hosts_with_spaces_is_one_option(self):
        path = Path('/controller/customer a/known_hosts')
        self.assertEqual(shlex.split(ssh_options(path)), ['-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(path)])

    def test_discovery_never_selects_a_site_implicitly(self):
        from tools.run_discovery import command
        with self.assertRaises(ValueError):
            command(22, False)
