import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
import yaml
from fixture import fixture
from render_templates import render
from module_utils.postgres_version import validate_major, resolve_major, check_data_major
from module_utils.deployment_model import validate_model, extension_plan
from module_utils.cluster_contract import validate_contract


class VersionMatrixTests(unittest.TestCase):
    def test_existing_data_never_accepts_a_major_change(self):
        for major in ('14', '15', '16', '17', '18', '19'):
            check_data_major(major, None)
            check_data_major(major, major + '\n')
            with self.assertRaises(ValueError):
                check_data_major(major, str(int(major) + 1))
        with self.assertRaises(ValueError):
            check_data_major('17', '')
    def test_selection_rejects_minor_versions_tags_and_ambiguous_pins(self):
        for invalid in ('13', '17.2', 'latest', '18beta1', '017', 17, True, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_major(invalid)
        with self.assertRaises(ValueError):
            resolve_major({'major': '16'}, {'postgresql-17': 'x'})
        with self.assertRaises(ValueError):
            resolve_major(packages={'postgresql-14': 'x', 'postgresql-client-15': 'x'})
        with self.assertRaises(ValueError):
            resolve_major()

    def test_model_packages_and_legacy_contract_matrix(self):
        for major in ('14', '15', '16', '17', '18', '19', '20'):
            with self.subTest(major=major):
                model = {'mode': 'standalone', 'major': major, 'topology': {'primary': 'pg1'}}
                self.assertFalse(validate_model(model, ['pg1'])['errors'])
                plan = extension_plan(['pg_stat_kcache', 'pgaudit'], major)
                self.assertIn('postgresql-' + major + '-pgaudit', plan['packages'])
                self.assertIn('postgresql-' + major + '-pg-stat-kcache', plan['packages'])
                c, nodes = fixture()
                c['packages'] = {key.replace('-17', '-' + major): value for key, value in c['packages'].items()}
                self.assertEqual(major, resolve_major(packages=c['packages']))
                self.assertFalse(validate_contract(c, nodes, list(nodes), list(nodes)))

    def test_both_service_types_and_wal_template_matrix(self):
        for major in ('14', '15', '16', '17', '18', '19'):
            with self.subTest(major=major), tempfile.TemporaryDirectory() as directory:
                model = {'mode': 'cluster', 'major': major, 'topology': {'replicas': []}, 'extensions': ['pg_stat_statements']}
                with contextlib.redirect_stdout(io.StringIO()):
                    render(Path(directory), model=model, storage_root='/srv/version-test')
                patroni = yaml.safe_load((Path(directory) / 'patroni.yml').read_text())
                self.assertEqual('/usr/lib/postgresql/' + major + '/bin', patroni['postgresql']['bin_dir'])
                self.assertIn('data-checksums', patroni['bootstrap']['initdb'])
                self.assertEqual('/srv/version-test/wal/pg_wal', patroni['postgresql']['basebackup']['waldir'])
                service = (Path(directory) / 'postgresql.service').read_text()
                self.assertIn('/usr/lib/postgresql/' + major + '/bin/postgres', service)
