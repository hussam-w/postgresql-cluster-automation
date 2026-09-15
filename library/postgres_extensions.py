#!/usr/bin/python
"""Add explicitly requested extensions; never upgrade/drop or alter preloads."""
import hashlib
import json
import re
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.deployment_model import extension_plan
from ansible.module_utils.extension_lifecycle import native_extension_order
from ansible.module_utils.local_postgres import LocalPostgres, literal, identifier


def unsafe_schema_sql(schema):
    # A non-superuser owner can grant CREATE again even when its ACL is revoked.
    trusted = "coalesce((SELECT rolsuper FROM pg_roles WHERE oid=CASE WHEN %s=(SELECT oid FROM pg_roles WHERE rolname='pg_database_owner') THEN (SELECT datdba FROM pg_database WHERE datname=current_database()) ELSE %s END), false)"
    return ("SELECT 1 FROM pg_namespace n WHERE nspname=" + literal(schema) +
            " AND (NOT " + (trusted % ('n.nspowner', 'n.nspowner')) +
            " OR EXISTS (SELECT 1 FROM aclexplode(coalesce(n.nspacl, acldefault('n', n.nspowner))) a "
            "WHERE a.privilege_type='CREATE' AND NOT " + (trusted % ('a.grantee', 'a.grantee')) + "))")


def main():
    module = AnsibleModule(argument_spec={
        'socket_dir': {'type': 'path', 'required': True},
        'port': {'type': 'int', 'default': 5432},
        'owner': {'type': 'str', 'default': 'postgres'},
        'major': {'type': 'str', 'required': True},
        'optional': {'type': 'list', 'elements': 'str', 'default': []},
        'registry': {'type': 'dict', 'default': {}},
        'databases': {'type': 'list', 'elements': 'str', 'default': ['postgres']},
        'schema': {'type': 'str', 'default': 'postgres_extensions'},
        'operation': {'type': 'str', 'choices': ['plan', 'apply'], 'default': 'plan'},
        'expected_system_id': {'type': 'str', 'default': ''},
        'expected_plan_sha256': {'type': 'str', 'default': ''},
        'allow_create': {'type': 'bool', 'default': False},
    }, supports_check_mode=True)
    p, changed, completed = module.params, False, []
    try:
        desired = extension_plan(p['optional'], p['major'], p['registry'])
        if not p['databases'] or len(set(p['databases'])) != len(p['databases']):
            raise ValueError('Supply a nonempty unique database list')
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,62}', p['schema']) or p['schema'].startswith('pg_'):
            raise ValueError('Supply an ordinary extension schema name')
        db = LocalPostgres(p['socket_dir'], p['port'], p['owner'])
        identity = db.query("SELECT json_build_object('system_id', system_identifier::text, 'major', "
                            "current_setting('server_version_num')::int / 10000, 'recovery', pg_is_in_recovery(), "
                            "'data_dir', current_setting('data_directory'), 'started', pg_postmaster_start_time(), 'preload', current_setting('shared_preload_libraries')) "
                            "FROM pg_control_system();")
        blockers = []
        if str(identity['major']) != p['major']:
            blockers.append('Detected PostgreSQL major differs from the declared major; no upgrade is performed')
        preloaded = {n.strip().strip('"').split('/')[-1].removesuffix('.so') for n in identity['preload'].split(',')}
        for library in desired['preload']:
            if library not in preloaded:
                blockers.append(library + ': shared_preload_libraries requires separately approved configuration and restart')
        plans = {}
        for database in p['databases']:
            available = db.query("SELECT coalesce(json_object_agg(name, row_to_json(e)), '{}'::json) FROM "
                                 "(SELECT a.name, a.default_version, a.installed_version, v.requires FROM pg_available_extensions a LEFT JOIN pg_available_extension_versions v ON v.name=a.name AND v.version=a.default_version) e;", database)
            missing, targets = [], {}
            order = native_extension_order(desired['extensions'], available)
            for name in order:
                if name not in available or not available[name]['default_version']:
                    blockers.append(database + ': extension unavailable for the running server: ' + name)
                elif not available[name]['installed_version']:
                    missing.append(name)
                    fixed = db.query("SELECT coalesce(json_agg(schema), '[]'::json) FROM pg_available_extension_versions "
                                     "WHERE name=" + literal(name) + ' AND version=' + literal(available[name]['default_version']) + ';', database)
                    targets[name] = fixed[0] if fixed and fixed[0] else p['schema']
                    if targets[name] not in (p['schema'], 'pg_catalog'):
                        blockers.append(database + ': extension requires a different schema: ' + name)
            schema = db.query("SELECT to_json(EXISTS (SELECT FROM pg_namespace WHERE nspname=" + literal(p['schema']) + '));', database)
            unsafe = db.query('SELECT to_json(EXISTS (' + unsafe_schema_sql(p['schema']) + '));', database)
            if missing and unsafe:
                blockers.append(database + ': extension schema permits untrusted CREATE; preserve ACLs and choose a secure schema')
            plans[database] = {'missing': missing, 'available': {n: available.get(n) for n in order}, 'order': order,
                               'schema_exists': bool(schema), 'targets': targets}
        report = {'identity': identity, 'desired': desired, 'schema': p['schema'], 'databases': plans, 'blockers': blockers}
        token = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        report['plan_sha256'] = token
        needed = any(plan['missing'] for plan in plans.values())
        if p['operation'] == 'plan' or module.check_mode:
            module.exit_json(changed=False, report=report, would_change=needed)
        if blockers or p['expected_system_id'] != identity['system_id']:
            module.fail_json(changed=False, msg='Extension admission failed; no DDL executed', report=report)
        if not needed:
            module.exit_json(changed=False, report=report, message='All requested extensions already exist; versions preserved')
        if identity['recovery'] or not p['allow_create'] or token != p['expected_plan_sha256']:
            raise ValueError('Extension creation needs a writable primary, explicit approval and the exact current plan')
        for database, plan in plans.items():
            if not plan['missing']:
                continue
            commands = ["BEGIN; SELECT pg_advisory_xact_lock(174318, 17);"]
            if not plan['schema_exists'] and p['schema'] in plan['targets'].values():
                commands.append('CREATE SCHEMA IF NOT EXISTS ' + identifier(p['schema']) + ';')
            commands.append("DO $guard$ BEGIN IF EXISTS (" + unsafe_schema_sql(p['schema']) +
                            ") THEN RAISE EXCEPTION 'Unsafe extension schema ownership or CREATE permissions'; END IF; END $guard$;")
            for name in plan['missing']:
                version = plan['available'][name]['default_version']
                target_schema = plan['targets'][name]
                commands.append('CREATE EXTENSION IF NOT EXISTS ' + identifier(name) + ' WITH SCHEMA ' +
                                identifier(target_schema) + ' VERSION ' + literal(version) + ';')
                commands.append("DO $guard$ BEGIN IF NOT EXISTS (SELECT FROM pg_extension WHERE extname=" + literal(name) +
                                ' AND extversion=' + literal(version) + ") THEN RAISE EXCEPTION 'Concurrent extension version conflict'; "
                                'END IF; END $guard$;')
            commands.append('COMMIT;')
            changed = True  # A lost connection at commit has an uncertain outcome; never drop to retry.
            db.sql('\n'.join(commands), database)
            completed.append(database)
        module.exit_json(changed=changed, report=report, completed_databases=completed,
                         message='Extensions added transactionally per database; existing extensions and versions retained')
    except Exception as error:
        module.fail_json(changed=changed, completed_databases=completed,
                         msg=str(error) if type(error) is ValueError else type(error).__name__ + ': inspect protected diagnostics')


if __name__ == '__main__':
    main()
