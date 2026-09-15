import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import yaml
from render_templates import render


class ModelTemplateTests(unittest.TestCase):
    def test_external_wal_applies_to_initialization_replicas_and_units(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory)
            render(output, storage_root='/srv/site-b')
            patroni = yaml.safe_load((output / 'patroni.yml').read_text())
            self.assertIn({'waldir': '/srv/site-b/wal/pg_wal'}, patroni['bootstrap']['initdb'])
            self.assertEqual({'checkpoint': 'spread', 'waldir': '/srv/site-b/wal/pg_wal'}, patroni['postgresql']['basebackup'])
            for name in ['postgresql.service', 'pg-ha-patroni.service']:
                unit = (output / name).read_text()
                self.assertIn('AssertPathIsMountPoint=/srv/site-b/data', unit)
                self.assertIn('RequiresMountsFor=/srv/site-b/wal/pg_wal', unit)

    def test_role_policy_and_preloads_survive_full_template_render(self):
        model = {'mode': 'cluster', 'major': '17', 'topology': {
            'primary': 'pg1', 'replicas': ['pg2'], 'standby': ['pg3']},
            'extensions': ['pg_stat_kcache', 'pgaudit']}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory)
            for name, excluded in [('pg1', False), ('pg2', True), ('pg3', False)]:
                render(output, model, name)
                patroni = yaml.safe_load((output / 'patroni.yml').read_text())
                self.assertEqual(excluded, patroni['tags']['nofailover'])
                self.assertEqual(excluded, patroni['tags']['nosync'])
                self.assertEqual('/usr/lib/postgresql/17/bin', patroni['postgresql']['bin_dir'])
                self.assertEqual('pg_stat_statements,pg_stat_kcache,pgaudit',
                                 patroni['postgresql']['parameters']['shared_preload_libraries'])

    def test_standalone_output_has_no_ha_service_dependency(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory)
            render(output, {'mode': 'standalone', 'major': '17', 'topology': {'replicas': []}})
            unit = (output / 'postgresql.service').read_text()
            self.assertIn('/usr/lib/postgresql/17/bin/postgres', unit)
            for component in ['patroni', 'etcd', 'haproxy', 'keepalived']:
                self.assertNotIn(component, unit.lower())
            config = (output / 'postgresql.conf').read_text()
            self.assertIn("listen_addresses = ''", config)
            self.assertIn('max_wal_senders = 0', config)
