#!/usr/bin/python
"""Observe existing PostgreSQL; narrowly reconcile explicitly approved reload settings.

No provisioning, role/database DDL, service management, package or network writes.
Uses installed psql with local peer authentication; credentials are never exported.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile
import time

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.reconcile_policy import RELOAD_SETTINGS, fingerprint, plan_settings, dynamic_candidate


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def file_state(path):
    p = Path(path)
    if not p.exists():
        return {'path': str(p), 'exists': False}
    info = p.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
        raise ValueError('Configuration must be a bounded regular file: ' + str(p))
    return {'path': str(p), 'resolved_path': str(p.resolve()), 'exists': True, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
            'uid': info.st_uid, 'gid': info.st_gid, 'mode': stat.S_IMODE(info.st_mode)}


def atomic_restore(path, data, metadata):
    fd, temporary = tempfile.mkstemp(prefix='.pg-ha-restore-', dir=str(Path(path).parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, metadata['uid'], metadata['gid'])
        os.chmod(temporary, metadata['mode'])
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    module = AnsibleModule(argument_spec={
        'socket_dir': {'type': 'path', 'required': True},
        'port': {'type': 'int', 'default': 5432},
        'owner': {'type': 'str', 'default': 'postgres'},
        'database': {'type': 'str', 'default': 'postgres'},
        'parameters': {'type': 'dict', 'default': {}},
        'operation': {'type': 'str', 'choices': ['plan', 'apply'], 'default': 'plan'},
        'expected_system_id': {'type': 'str', 'default': ''},
        'expected_plan_sha256': {'type': 'str', 'default': ''},
        'allow_reload': {'type': 'bool', 'default': False},
        'manager': {'type': 'str', 'choices': ['observe', 'standalone', 'patroni'], 'default': 'observe'},
        'patroni_config': {'type': 'path', 'default': '/etc/pg-ha/patroni/patroni.yml'},
        'backup_root': {'type': 'path', 'default': '/var/lib/pg-ha-reconcile'},
    }, supports_check_mode=True)
    p = module.params
    changed = False
    backup = None
    try:
        if os.geteuid() != 0:
            raise ValueError('Root observation is required; SQL executes as the declared local database owner')
        if not Path(p['socket_dir']).is_absolute() or not 1 <= p['port'] <= 65535:
            raise ValueError('Use an absolute Unix socket directory and a valid local port')
        account = pwd.getpwnam(p['owner'])
        psql = module.get_bin_path('psql', required=True)
        runuser = module.get_bin_path('runuser', required=True)

        def sql(statement, database=None):
            # No shell, password, inherited libpq options, startup files or unbounded waits.
            argv = [runuser, '-u', p['owner'], '--', psql, '-X', '-A', '-t', '-w',
                    '-v', 'ON_ERROR_STOP=1', '-h', p['socket_dir'], '-p', str(p['port']),
                    '-U', p['owner'], '-d', "dbname='" + str(database or p['database']).replace('\\', '\\\\').replace("'", "\\'") + "'"]
            env = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                   'PGCONNECT_TIMEOUT': '5', 'PGOPTIONS': '-c statement_timeout=10000 -c lock_timeout=2000 -c search_path=pg_catalog',
                   'PGAPPNAME': 'pg-ha-reconcile'}
            result = subprocess.run(argv, input=statement, text=True, capture_output=True, env=env, timeout=20)
            if result.returncode:
                # SQL errors can include configuration contents; do not include raw stderr.
                raise ValueError('Local SQL observation/validation failed; inspect protected PostgreSQL logs')
            return result.stdout.strip()

        def query(statement, database=None):
            return json.loads(sql(statement, database))

        version = int(sql('SHOW server_version_num;'))
        if version < 100000:
            raise ValueError('Pre-10 PostgreSQL requires manual catalog discovery; no changes attempted')
        identity = query("SELECT json_build_object('system_id', system_identifier::text, "
                         "'version', current_setting('server_version_num'), "
                         "'data_dir', current_setting('data_directory'), "
                         "'config_file', current_setting('config_file'), "
                         "'hba_file', current_setting('hba_file'), "
                         "'ident_file', current_setting('ident_file'), "
                         "'in_recovery', pg_is_in_recovery(), 'started', pg_postmaster_start_time(), "
                         "'superuser', current_setting('is_superuser')) FROM pg_control_system();")
        if identity['superuser'] != 'on':
            raise ValueError('Complete catalog/configuration inspection needs the local database administrator')
        settings = query("SELECT coalesce(json_object_agg(name, row_to_json(s)), '{}'::json) FROM "
                         "(SELECT name, setting, unit, context, vartype, min_val, max_val, source, "
                         "sourcefile, pending_restart FROM pg_settings WHERE name IN (" +
                         ','.join(literal(name) for name in sorted(RELOAD_SETTINGS)) + ')) s;')
        plan = plan_settings(p['parameters'], settings, version) if p['parameters'] else {
            'changes': {}, 'compliant': [], 'blockers': []}
        errors = query("SELECT coalesce(json_agg(json_build_object('file', sourcefile, 'line', sourceline)), "
                       "'[]'::json) FROM pg_file_settings WHERE error IS NOT NULL;")
        if errors:
            plan['blockers'].append('Existing configuration errors or pending file changes require review')
        catalog = query("SELECT json_build_object('roles', (SELECT coalesce(json_agg(r), '[]'::json) FROM "
                        "(SELECT rolname, rolsuper, rolreplication, rolcanlogin FROM pg_roles ORDER BY rolname) r), "
                        "'databases', (SELECT coalesce(json_agg(d), '[]'::json) FROM (SELECT datname, "
                        "pg_get_userbyid(datdba) AS owner, datallowconn FROM pg_database ORDER BY datname) d), "
                        "'tablespaces', (SELECT coalesce(json_agg(t), '[]'::json) FROM (SELECT spcname, "
                        "pg_tablespace_location(oid) AS location FROM pg_tablespace) t), "
                        "'replication', (SELECT coalesce(json_agg(r), '[]'::json) FROM (SELECT application_name, "
                        "client_addr, state, sync_state FROM pg_stat_replication) r), "
                        "'slots', (SELECT coalesce(json_agg(s), '[]'::json) FROM (SELECT slot_name, slot_type, "
                        "database, active FROM pg_replication_slots) s));")
        catalog['extensions'] = {}
        catalog['replication_settings'] = query("SELECT coalesce(json_object_agg(name, setting), '{}'::json) "
                                               "FROM pg_settings WHERE name IN ('wal_level', 'hot_standby', "
                                               "'synchronous_commit', 'synchronous_standby_names', 'max_wal_senders', "
                                               "'max_replication_slots', 'archive_mode');")
        catalog['role_database_setting_names'] = query("SELECT coalesce(json_agg(s), '[]'::json) FROM "
                                                      "(SELECT setdatabase, setrole, split_part(unnest(setconfig), '=', 1) "
                                                      "AS parameter FROM pg_db_role_setting) s;")
        databases = [d['datname'] for d in catalog['databases'] if d['datallowconn']]
        if len(databases) > 100:
            plan['blockers'].append('More than 100 connectable databases: extension coverage requires a scoped audit')
        for database in databases[:100]:
            catalog['extensions'][database] = query("SELECT coalesce(json_agg(e), '[]'::json) FROM "
                                                    "(SELECT extname, extversion FROM pg_extension ORDER BY extname) e;", database)
        data = Path(identity['data_dir'])
        auto = data / 'postgresql.auto.conf'
        files = {identity[key] for key in ['config_file', 'hba_file', 'ident_file']}
        files.update(row['sourcefile'] for row in settings.values() if row.get('sourcefile'))
        files.add(str(auto))
        # Fingerprint every included configuration file, without reporting its contents.
        files.update(query("SELECT coalesce(json_agg(DISTINCT sourcefile), '[]'::json) FROM pg_file_settings;"))
        certs = query("SELECT coalesce(json_object_agg(name, setting), '{}'::json) FROM pg_settings "
                      "WHERE name IN ('ssl', 'ssl_cert_file', 'ssl_ca_file', 'ssl_key_file');")
        for key in ['ssl_cert_file', 'ssl_ca_file', 'ssl_key_file']:
            if certs.get(key):
                path = Path(certs[key])
                files.add(str(path if path.is_absolute() else data / path))
        managed_marker = data / 'patroni.dynamic.json'
        dcs = None
        dynamic = None
        patroni_members = []
        local_overrides = []
        if p['manager'] == 'patroni':
            from patroni.config import Config
            from patroni.dcs import get_dcs
            local = Config(p['patroni_config'], validator=None).copy()
            local_overrides = sorted(local.get('postgresql', {}).get('parameters', {}))
            if Path(local.get('postgresql', {}).get('data_dir', '')).resolve() != data.resolve():
                raise ValueError('Patroni configuration does not identify the inspected data directory')
            for name in plan['changes']:
                if name in local.get('postgresql', {}).get('parameters', {}):
                    plan['blockers'].append(name + ': local Patroni override must be maintained separately')
                if settings[name].get('sourcefile') == str(auto):
                    plan['blockers'].append(name + ': ALTER SYSTEM override would mask the DCS change')
            dcs = get_dcs(local)
            dcs_cluster = dcs.get_cluster()
            dynamic = dcs_cluster.config
            patroni_members = sorted(member.name for member in dcs_cluster.members)
            if not dynamic or not dynamic.data:
                raise ValueError('Existing DCS configuration is unavailable; never initialize it here')
            files.add(p['patroni_config'])
        elif p['manager'] == 'standalone':
            if managed_marker.exists():
                plan['blockers'].append('Patroni ownership detected; never use ALTER SYSTEM to compete with it')
            if identity['in_recovery']:
                plan['blockers'].append('Standalone standby changes require a replication-aware maintenance procedure')
        elif plan['changes']:
            plan['blockers'].append('Configuration ownership is observe-only; explicitly select and review a manager')
        states = [file_state(path) for path in sorted(files)]
        if plan['changes'] and any(s.get('resolved_path', s['path']) != s['path'] for s in states):
            plan['blockers'].append('Symlinked configuration/certificates require a reviewed maintenance procedure')
        signature = fingerprint({'identity': identity, 'files': states,
                                 'desired': p['parameters'], 'settings': settings,
                                 'dynamic': dynamic.data if dynamic else None, 'manager': p['manager']})
        report = {'identity': identity, 'catalog': catalog, 'certificates': certs,
                  'files': states, 'settings': settings, 'plan': plan, 'plan_sha256': signature,
                  'configuration_errors': errors, 'manager': p['manager'],
                  'patroni_members': patroni_members, 'local_overrides': local_overrides}
        if p['operation'] == 'plan' or module.check_mode:
            module.exit_json(changed=False, report=report, would_change=bool(plan['changes']))
        if plan['blockers']:
            module.fail_json(msg='Reconciliation blocked; preserve existing state', report=report, changed=False)
        if p['parameters'] and p['expected_system_id'] != identity['system_id']:
            raise ValueError('The declared expected_system_id must match even for an already-compliant instance')
        if not plan['changes']:
            module.exit_json(changed=False, report=report, skipped_reason='Already compliant; no file write or reload')
        if not p['allow_reload'] or p['expected_system_id'] != identity['system_id']:
            raise ValueError('Changes require allow_reload and the discovered exact expected_system_id')
        if p['expected_plan_sha256'] != signature:
            raise ValueError('Plan changed or was not approved; inspect a fresh plan before applying')
        root = Path(p['backup_root'])
        if not root.is_absolute() or root.resolve() != root or root in (Path('/'), data):
            raise ValueError('Use a dedicated absolute backup_root without symlinks')
        if root.exists() and (root.stat().st_uid != 0 or root.stat().st_mode & 0o077):
            raise ValueError('Existing backup_root must be root-owned and private')
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        lockfd = os.open(str(root / (identity['system_id'] + '.lock')), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another local reconciliation holds the configuration lock')
        # Another configuration tool may not honor our lock. Recheck every observed file.
        if states != [file_state(path) for path in sorted(files)]:
            raise ValueError('Configuration changed after planning; nothing applied')
        backup = tempfile.mkdtemp(prefix=identity['system_id'] + '-', dir=str(root))
        os.chmod(backup, 0o700)
        Path(backup, 'plan.json').write_text(json.dumps(report, indent=2))
        os.chmod(Path(backup, 'plan.json'), 0o600)
        if dcs:
            before = copy.deepcopy(dynamic.data)
            candidate = dynamic_candidate(before, plan['changes'])
            saved = Path(backup, 'dynamic-config.json')
            saved.write_text(json.dumps(before))
            os.chmod(saved, 0o600)
            # etcd compare-and-swap: an intervening writer causes refusal, never overwrite.
            changed = True  # A transport failure can leave the write outcome uncertain.
            if not dcs.set_config_value(json.dumps(candidate), dynamic.version):
                changed = False
                raise ValueError('DCS compare-and-swap refused a concurrent change; nothing overwritten')
        else:
            original = file_state(str(auto))
            if not original['exists'] or original['uid'] != account.pw_uid:
                raise ValueError('Standalone auto.conf must already exist and belong to the database owner')
            original_bytes = auto.read_bytes()
            saved = Path(backup, 'postgresql.auto.conf')
            saved.write_bytes(original_bytes)
            os.chmod(saved, 0o600)
            expected_auto = original
            try:
                for name, entry in plan['changes'].items():
                    if file_state(str(auto)) != expected_auto:
                        raise ValueError('Concurrent auto.conf change detected')
                    changed = True
                    sql('ALTER SYSTEM SET ' + name + ' = ' + literal(entry['after']) + ';')
                    expected_auto = file_state(str(auto))
                if sql('SELECT count(*) FROM pg_file_settings WHERE error IS NOT NULL;') != '0':
                    raise ValueError('PostgreSQL rejected candidate configuration')
                if sql('SELECT pg_reload_conf();') != 't':
                    raise ValueError('PostgreSQL refused reload')
            except Exception:
                if file_state(str(auto)) == expected_auto:
                    atomic_restore(str(auto), original_bytes, original)
                    if changed:
                        sql('SELECT pg_reload_conf();')
                raise
        # New SQL connections observe reloaded defaults; no restart is ever issued.
        for attempt in range(30):
            current = query("SELECT json_object_agg(name, row_to_json(s)) FROM (SELECT name, setting, unit, "
                            "context, vartype, min_val, max_val, source, sourcefile, pending_restart FROM pg_settings "
                            "WHERE name IN (" + ','.join(literal(n) for n in sorted(RELOAD_SETTINGS)) + ')) s;')
            remaining = plan_settings(p['parameters'], current, version)
            if not remaining['changes'] and not remaining['blockers']:
                break
            time.sleep(2)
        else:
            raise ValueError('Convergence timed out. Stop further changes; inspect the preserved backup and manager state')
        if sql('SELECT pg_postmaster_start_time()::text;') != sql(
                'SELECT ' + literal(identity['started']) + '::timestamptz::text;'):
            raise ValueError('PostgreSQL start identity changed during reconciliation; investigate before continuing')
        module.exit_json(changed=True, report=report, backup_directory=backup,
                         message='Only approved parameters changed; local SQL convergence verified without a restart')
    except Exception as error:
        # Third-party exceptions can carry connection strings. Only expose our own diagnostics.
        safe = str(error) if type(error) is ValueError else type(error).__name__ + ': inspect protected local diagnostics'
        module.fail_json(msg=safe, changed=changed, backup_directory=backup,
                         intervention='Inspect current configuration before retrying; a failed transport can leave write outcome uncertain' if changed else 'No managed configuration write was admitted or confirmed')


if __name__ == '__main__':
    main()
