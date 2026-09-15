"""Simulate DCS/SQL while exercising real backup files and compare-and-swap handling."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from fixture import ROOT
from module_utils import extension_lifecycle


class Finished(BaseException):
    def __init__(self, result):
        self.result = result


@unittest.skipUnless(os.name == 'posix', 'Linux file locking and ownership checks')
class PreloadModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.params = dict(socket_dir='/run/test', port=5432, major='17', expected_system_id='123',
                           required=['bar'], manager='patroni', patroni_config='/etc/pg-ha/patroni.yml',
                           standalone_name='main', operation='plan', expected_plan_sha256='', allow_restart=False)
        self.active = 'foo'
        self.dynamic = {'ttl': 30, 'postgresql': {'parameters': {'shared_preload_libraries': 'foo', 'work_mem': '4MB'}}}
        self.writes = []
        self.cas_ok = True
        for name in ('foo', 'bar'):
            path = self.path('/usr/lib/postgresql/17/lib/' + name + '.so')
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture')
        config = self.path('/etc/pg-ha/patroni.yml')
        config.parent.mkdir(parents=True, exist_ok=True); config.write_text('owned')
        manifest = self.path('/var/lib/pg-ha/files.json')
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({'/etc/pg-ha/patroni.yml': hashlib.sha256(config.read_bytes()).hexdigest()}))
        manifest.chmod(0o600)
        self.path('/srv/postgres/data').mkdir(parents=True)

    def path(self, *parts):
        value = Path(*parts)
        return value if str(value).startswith(str(self.root)) else self.root / str(value).lstrip('/')

    def query(self, statement, database='postgres'):
        if 'json_build_object' in statement:
            return {'id': '123', 'major': 17, 'data': '/srv/postgres/data', 'started': 'stable', 'recovery': False, 'active': self.active}
        return 0

    def execute(self):
        test = self
        class Module:
            params = test.params
            check_mode = False
            def __init__(self, **kwargs): pass
            def exit_json(self, **value): raise Finished(value)
            def fail_json(self, **value): raise Finished(dict(value, failed=True))
        class DB:
            def __init__(self, *args): pass
            query = staticmethod(test.query)
            sql = staticmethod(lambda statement: None)
        class DCS:
            def get_cluster(self):
                return types.SimpleNamespace(config=types.SimpleNamespace(data=copy.deepcopy(test.dynamic), version=7))
            def set_config_value(self, value, version):
                test.writes.append((json.loads(value), version)); return test.cas_ok
        class Config:
            def __init__(self, *args, **kwargs): pass
            def copy(self): return {'postgresql': {'data_dir': '/srv/postgres/data', 'parameters': {}}}
        basic = types.ModuleType('ansible.module_utils.basic'); basic.AnsibleModule = Module
        local = types.ModuleType('ansible.module_utils.local_postgres'); local.LocalPostgres = DB; local.literal = lambda v: "'" + v + "'"
        patroni_config = types.ModuleType('patroni.config'); patroni_config.Config = Config
        patroni_dcs = types.ModuleType('patroni.dcs'); patroni_dcs.get_dcs = lambda local: DCS()
        modules = {'ansible.module_utils.basic': basic, 'ansible.module_utils.local_postgres': local,
                   'ansible.module_utils.extension_lifecycle': extension_lifecycle,
                   'patroni.config': patroni_config, 'patroni.dcs': patroni_dcs}
        actual_stat = Path.stat
        def root_stat(path, *args, **kwargs):
            state = list(actual_stat(path, *args, **kwargs)); state[4] = 0
            return os.stat_result(state)
        with patch.dict('sys.modules', modules), patch.object(Path, 'stat', root_stat):
            spec = importlib.util.spec_from_file_location('preload_under_test', ROOT / 'library/postgres_preload.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            with patch.object(module, 'Path', self.path), patch.object(module.os, 'geteuid', return_value=0):
                try: module.main()
                except Finished as result: return result.result
        self.fail('Module returned without a result')

    def test_plan_preserves_files_and_apply_uses_cas_and_private_backup(self):
        planned = self.execute()
        self.assertNotIn('failed', planned)
        self.assertFalse(self.writes)
        self.params.update(operation='apply', allow_restart=True, expected_plan_sha256=planned['report']['plan_sha256'])
        result = self.execute()
        self.assertNotIn('failed', result)
        self.assertTrue(result['changed'])
        candidate, version = self.writes[0]
        self.assertEqual(7, version)
        self.assertEqual('4MB', candidate['postgresql']['parameters']['work_mem'])
        self.assertEqual('foo,bar', candidate['postgresql']['parameters']['shared_preload_libraries'])
        saved = Path(result['backup_directory']) / 'before.json'
        self.assertEqual(self.dynamic, json.loads(saved.read_text()))
        self.assertEqual(0o600, saved.stat().st_mode & 0o777)

    def test_concurrent_change_and_missing_permission_are_refused(self):
        plan = self.execute()
        self.params.update(operation='apply', expected_plan_sha256=plan['report']['plan_sha256'])
        self.assertTrue(self.execute()['failed']); self.assertFalse(self.writes)
        self.params['allow_restart'] = True
        self.params['expected_plan_sha256'] = 'stale'
        self.assertTrue(self.execute()['failed']); self.assertFalse(self.writes)
        self.params['expected_plan_sha256'] = plan['report']['plan_sha256']; self.cas_ok = False
        result = self.execute()
        self.assertTrue(result['failed']); self.assertFalse(result['changed'])

    def test_compliance_missing_library_and_wrong_identity(self):
        self.params['required'] = ['foo']
        self.assertFalse(self.execute()['report']['needs_restart'])
        self.params['operation'] = 'apply'
        self.assertFalse(self.execute()['changed']); self.assertFalse(self.writes)
        self.params['expected_system_id'] = 'other'
        self.assertTrue(self.execute()['failed'])
        self.params['expected_system_id'] = '123'; self.params['required'] = ['missing']
        self.assertTrue(self.execute()['failed']); self.assertFalse(self.writes)
