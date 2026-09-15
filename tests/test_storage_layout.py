import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_utils.storage_layout import resolve_layout


class StorageLayoutTests(unittest.TestCase):
    def test_explicit_environment_root(self):
        p = resolve_layout({'root': '/srv/customer-a'})
        self.assertEqual('/srv/customer-a/data/pgdata', p['data_dir'])
        self.assertEqual('/srv/customer-a/wal/pg_wal', p['wal_dir'])
        self.assertEqual('/srv/customer-a/backups/repository', p['backup_dir'])
        self.assertEqual('/srv/customer-a/data', p['data_mount'])

    def test_target_home_not_controller_home(self):
        self.assertEqual('/home/alice/data', resolve_layout({'home_user': 'alice'}, '/home/alice')['root'])
        self.assertEqual('/var/lib/postgresql/data', resolve_layout({'home_user': 'postgres'}, '/var/lib/postgresql')['root'])

    def test_ambiguous_unsafe_or_unresolved_input_refused(self):
        for config in [{}, {'root': '/srv/db', 'home_user': 'alice'}, {'root': '$HOME/data'},
                       {'root': '~/data'}, {'root': '../data'}, {'root': '/srv/../etc/db'},
                       {'root': '/etc/db'}, {'root': '/srv'}, {'root': '/srv/db/'},
                       {'root': '/srv//db'}, {'root': '/srv/a b'}, {'home_user': 2},
                       {'home_user': 'alice'}, {'root': '/srv/db', 'format': True}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                resolve_layout(config)

    def test_idempotent_resolution(self):
        self.assertEqual(resolve_layout({'root': '/srv/db'}), resolve_layout({'root': '/srv/db'}))
