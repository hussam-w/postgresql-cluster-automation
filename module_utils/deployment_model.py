"""Architecture/extension registry and pure validation. Never infer authorization."""
import re

try:
    from ansible.module_utils.postgres_version import validate_major, RELEASED_BASELINE
    from ansible.module_utils.deployment_components import component_plan
except ImportError:
    from module_utils.postgres_version import validate_major, RELEASED_BASELINE
    from module_utils.deployment_components import component_plan
EXTENSIONS = {
    'plpgsql': {'package': 'postgresql-{major}', 'preload': [], 'requires': []},
    'pgcrypto': {'package': 'postgresql-{major}', 'preload': [], 'requires': []},
    'pg_stat_statements': {'package': 'postgresql-{major}', 'preload': ['pg_stat_statements'], 'requires': []},
    'pg_stat_kcache': {'package': 'postgresql-{major}-pg-stat-kcache',
                      'preload': ['pg_stat_statements', 'pg_stat_kcache'], 'requires': ['pg_stat_statements']},
    'pgaudit': {'package': 'postgresql-{major}-pgaudit', 'preload': ['pgaudit'], 'requires': []},
}
EXTENSIONS.update({name: {'package': 'postgresql-{major}', 'preload': [], 'requires': []}
                   for name in ('hstore', 'pg_trgm', 'citext', 'uuid-ossp', 'btree_gin', 'btree_gist')})
EXTENSIONS.update({
    'vector': {'package': 'postgresql-{major}-pgvector', 'preload': [], 'requires': []},
    'timescaledb': {'package': 'timescaledb-2-postgresql-{major}', 'packages': ['timescaledb-2-loader-postgresql-{major}'], 'preload': ['timescaledb'], 'requires': []},
})
BASELINE_EXTENSIONS = ('plpgsql',)


def extension_plan(optional, major, custom=None):
    validate_major(major)
    registry = dict(EXTENSIONS)
    if custom is not None:
        if not isinstance(custom, dict):
            raise ValueError('extension_registry must be a mapping')
        for name, spec in custom.items():
            if isinstance(name, str) and name in registry and spec == registry[name]:
                continue  # Preserve previously valid identical custom descriptors.
            if not isinstance(name, str) or name in registry or not re.fullmatch(r'[a-z][a-z0-9_-]*', name) or not isinstance(spec, dict) or (set(spec) - {'package', 'packages', 'preload', 'requires'} or not {'preload', 'requires'} <= set(spec) or not ('package' in spec or 'packages' in spec)):
                raise ValueError('Custom extensions require unique names and package/preload/requires fields; built-ins cannot be overridden')
            packages = ([spec['package']] if 'package' in spec else []) + spec.get('packages', []) if isinstance(spec.get('packages', []), list) else [None]
            if any(not isinstance(package, str) or not re.fullmatch(r'[a-z0-9+.-]+', package.replace('{major}', major)) for package in packages):
                raise ValueError('Extension package must be an apt name with optional {major}')
            for field in ('preload', 'requires'):
                if not isinstance(spec[field], list) or any(not isinstance(v, str) or not re.fullmatch(r'[a-z][a-z0-9_-]*', v) for v in spec[field]):
                    raise ValueError('Extension dependencies/preloads must be safe name lists')
            registry[name] = spec
    if isinstance(optional, list):
        optional = ['vector' if n == 'pgvector' else n for n in optional]
        for name in optional:
            if isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9_-]*', name) and name not in registry:
                # Unknown native/preinstalled extensions can be discovered by control files.
                # Never guess a third-party repository or execute downloaded installers.
                registry[name] = {'packages': [], 'preload': [], 'requires': []}
    if not isinstance(optional, list) or any(not isinstance(n, str) or n not in registry for n in optional):
        raise ValueError('Optional extensions must be a list of registered extension names')
    if len(set(optional)) != len(optional):
        raise ValueError('Optional extensions contain duplicates')
    ordered, visiting = [], set()
    def visit(name):
        if name not in registry or name in visiting:
            raise ValueError('Extension dependency is missing or cyclic')
        if name in ordered:
            return
        visiting.add(name)
        for dependency in registry[name]['requires']:
            visit(dependency)
        visiting.remove(name)
        if name not in ordered:
            ordered.append(name)
    for name in list(BASELINE_EXTENSIONS) + optional:
        visit(name)
    return {'extensions': ordered,
            'packages': sorted({package.replace('{major}', major) for n in ordered for package in ([registry[n]['package']] if 'package' in registry[n] else []) + registry[n].get('packages', [])}),
            'preload': list(dict.fromkeys(p for n in ordered for p in registry[n]['preload']))}


def validate_model(model, hosts, etcd=(), routers=()):
    errors, roles = [], {}
    if not isinstance(model, dict):
        return {'errors': ['postgresql_deployment must be a mapping'], 'roles': {}}
    if set(model) - {'mode', 'major', 'architecture', 'topology', 'extensions', 'extension_databases', 'extension_registry', 'components', 'allow_degraded_topology'}:
        errors.append('Unknown postgresql_deployment keys; check spelling and supported model fields')
    mode, major = model.get('mode'), model.get('major')
    try:
        components = component_plan(model)
    except ValueError as error:
        errors.append(str(error))
        components = {'backup': False, 'haproxy': True}
    degraded = model.get('allow_degraded_topology', False)
    if type(degraded) is not bool:
        errors.append('allow_degraded_topology must be Boolean')
    if mode not in ('standalone', 'cluster'):
        errors.append('mode must be explicitly standalone or cluster')
    try:
        validate_major(major)
    except ValueError as error:
        errors.append(str(error))
    topology = model.get('topology', {})
    if not isinstance(topology, dict):
        return {'errors': errors + ['topology must be a mapping'], 'roles': {}}
    if set(topology) - {'primary', 'primary_count', 'replicas', 'standby', 'total_nodes', 'replica_count', 'standby_count'}:
        errors.append('Unknown topology keys; check spelling and supported roles')
    primary = topology.get('primary')
    replicas, standby = topology.get('replicas', []), topology.get('standby', [])
    if not isinstance(primary, str) or not primary:
        errors.append('topology.primary must name one inventory host (initial primary for HA)')
    if any(not isinstance(items, list) or any(not isinstance(n, str) for n in items) for items in [replicas, standby]):
        return {'errors': errors + ['replicas and standby must be host-name lists'], 'roles': {}}
    assigned = ([primary] if isinstance(primary, str) else []) + replicas + standby
    if len(set(assigned)) != len(assigned):
        errors.append('Every host must have exactly one role; duplicate/conflicting assignments found')
    if set(assigned) != set(hosts):
        errors.append('Topology must assign every postgres_cluster inventory host exactly once and reference no unknown hosts')
    for key, actual in [('primary_count', 1), ('total_nodes', len(assigned)), ('replica_count', len(replicas)), ('standby_count', len(standby))]:
        if key in topology and (type(topology[key]) is not int or topology[key] != actual):
            errors.append('topology.' + key + ' must match declared membership')
    if mode == 'standalone' and (len(hosts) != 1 or replicas or standby or etcd or routers):
        errors.append('Standalone requires one host, no replica/standby roles, and no etcd_cluster/routers members')
    if mode == 'standalone' and 'architecture' in model:
        errors.append('architecture applies only to cluster mode')
    if mode == 'cluster':
        architecture = model.get('architecture', 'type_a')
        if architecture not in ('type_a', 'modular'):
            errors.append('Cluster architecture must be type_a or modular')
        if architecture == 'type_a' and not components['haproxy']:
            errors.append('Disabling HAProxy requires architecture: modular; legacy Type A routing is preserved')
        if architecture == 'type_a' and (len(hosts) < 3 or len(etcd) != 3 or len(set(etcd)) != 3 or set(routers) != set(etcd) or not set(etcd) <= set(hosts)):
            errors.append('Type A requires at least three database nodes and exactly three colocated etcd/router core nodes')
        if primary not in etcd:
            errors.append('Type A initial primary must belong to the core etcd/router inventory')
        if architecture == 'modular':
            if not hosts or len(etcd) not in (1, 3, 5) or len(set(etcd)) != len(etcd) or not set(etcd) <= set(hosts):
                errors.append('Modular cluster requires 1, 3 or 5 distinct colocated etcd voters')
            if components['haproxy'] and (not routers or not set(routers) <= set(etcd)):
                errors.append('Enabled HAProxy requires router members selected from etcd core nodes')
            if not components['haproxy'] and routers:
                errors.append('Disabled HAProxy requires an empty routers group')
            if (len(etcd) < 3 or not standby) and not degraded:
                errors.append('No quorum redundancy or eligible standby: set allow_degraded_topology explicitly; this is not HA')
        if not standby and architecture != 'modular':
            errors.append('HA requires at least one explicitly eligible standby; read replicas cannot be promoted automatically')
    roles = {name: 'replica' for name in replicas}
    roles.update({name: 'standby' for name in standby})
    if isinstance(primary, str):
        roles[primary] = 'primary'
    try:
        extensions = extension_plan(model.get('extensions', []), major, model.get('extension_registry'))
    except ValueError as error:
        errors.append(str(error))
        extensions = {}
    databases = model.get('extension_databases', ['postgres'])
    if not isinstance(databases, list) or not databases or any(not isinstance(n, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,62}', n) for n in databases):
        errors.append('extension_databases must be a nonempty list of explicit database names')
    elif len(set(databases)) != len(databases):
        errors.append('extension_databases contains duplicate database names')
    return {'errors': errors, 'roles': roles, 'extensions': extensions,
            'components': components,
            'automatic_failover_available': mode == 'cluster' and len(etcd) >= 3 and bool(standby),
            'compatibility': 'future major: verify upstream components and qualify before workloads' if isinstance(major, str) and major.isdigit() and int(major) > RELEASED_BASELINE else 'requires destination package and runtime validation',
            'initial_primary': primary, 'mode': mode, 'major': major,
            'counts': {'total': len(assigned), 'replicas': len(replicas), 'standby': len(standby)}}
