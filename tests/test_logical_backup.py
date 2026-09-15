"""Filesystem/control-flow tests with simulated PostgreSQL tools; not restore qualification."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from fixture import ROOT


@unittest.skipUnless(os.name == 'posix', 'Backup locking/durability uses Linux filesystem APIs')
class LogicalBackupTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('logical_backup', ROOT / 'roles/logical_backup/files/logical_backup.py')
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {'target': str(self.root), 'major': '17', 'socket': '/run/test', 'port': 5432, 'system_id': '123'}
        self.recovery, self.fail_dump, self.change_identity = False, False, False
        self.identities = 0
        self.databases = ['postgres', "odd'= db/../name"]
        self.commands = []

    def backend(self, argv, **kwargs):
        self.commands.append(argv)
        tool = Path(argv[0]).name
        output, rc = '', 0
        if tool == 'psql':
            if 'pg_control_system' in argv[-1]:
                self.identities += 1
                output = json.dumps({'id': '456' if self.change_identity and self.identities > 1 else '123',
                                     'recovery': self.recovery, 'started': 'stable', 'major': 17})
            else:
                output = json.dumps(self.databases)
        elif tool in ('pg_dumpall', 'pg_dump'):
            path = Path(next(arg[7:] for arg in argv if arg.startswith('--file=')))
            path.write_bytes(b'synthetic dump')
            rc = 1 if tool == 'pg_dump' and self.fail_dump else 0
        return subprocess.CompletedProcess(argv, rc, output, '')

    def run_backup(self):
        with patch.object(self.runner.subprocess, 'run', side_effect=self.backend), contextlib.redirect_stdout(io.StringIO()):
            self.runner.run(self.config)

    def test_complete_manifests_and_repeated_runs_preserve_history(self):
        (self.root / 'existing.txt').write_text('preserve')
        self.run_backup()
        self.run_backup()
        runs = [p for p in self.root.iterdir() if p.is_dir()]
        self.assertEqual(2, len(runs))
        for run in runs:
            manifest = json.loads((run / 'manifest.json').read_text())
            self.assertEqual(set(self.databases), set(manifest['databases']))
            for name, checksum in manifest['sha256'].items():
                self.assertEqual(checksum, hashlib.sha256((run / name).read_bytes()).hexdigest())
            self.assertFalse(run.name.endswith('.partial'))
        self.assertEqual('preserve', (self.root / 'existing.txt').read_text())
        dumps = [cmd for cmd in self.commands if Path(cmd[0]).name == 'pg_dump']
        self.assertTrue(any("\\'" in next(arg for arg in cmd if arg.startswith('--dbname=')) for cmd in dumps))

    def test_replicas_skip_without_creating_archives(self):
        self.recovery = True
        self.run_backup()
        self.assertFalse(any(p.is_dir() for p in self.root.iterdir()))
        self.assertFalse(any(Path(cmd[0]).name == 'pg_dumpall' for cmd in self.commands))

    def test_failed_dump_and_failover_retain_only_incomplete_output(self):
        for fail, changed in ((True, False), (False, True)):
            self.fail_dump, self.change_identity, self.identities = fail, changed, 0
            with self.assertRaises(RuntimeError):
                self.run_backup()
        self.assertEqual(2, len(list(self.root.glob('*.partial'))))
        self.assertFalse(any((p / 'manifest.json').exists() for p in self.root.iterdir() if p.is_dir()))

    def test_wrong_lineage_refused_before_dump(self):
        self.config['system_id'] = 'other'
        with self.assertRaises(RuntimeError):
            self.run_backup()
        self.assertFalse(any(p.is_dir() for p in self.root.iterdir()))
