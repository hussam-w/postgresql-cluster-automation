"""Additive preload policy shared by planning and tests."""
import re


def merge_preloads(current, required):
    existing = [s.strip() for s in current.split(',') if s.strip()]
    if any(not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', v) for v in existing + required):
        raise ValueError('Complex preload paths/quoting require reviewed manual configuration')
    return list(dict.fromkeys(existing + required))

def native_extension_order(requested, available):
    """Resolve control-file dependencies without upgrading already installed extensions."""
    ordered, active = [], set()
    def visit(name):
        if name in ordered:
            return
        if name in active:
            raise ValueError('Cyclic native extension dependency')
        active.add(name)
        info = available.get(name, {})
        if not info.get('installed_version'):
            for dependency in info.get('requires') or []:
                visit(dependency)
        active.remove(name)
        ordered.append(name)
    for name in requested:
        visit(name)
    return ordered


def health_errors(responses, members, expected_hosts, system_id, max_lag):
    errors = []
    if type(max_lag) is not int or max_lag < 0:
        return ['Replication lag threshold must be a nonnegative integer']
    identities = [r.get('json', {}) for r in responses]
    if len(identities) != len(expected_hosts):
        errors.append('Incomplete live member coverage')
    if sum(v.get('role') in ('primary', 'master') for v in identities) != 1:
        errors.append('Exactly one live primary required')
    for value in identities:
        if str(value.get('database_system_identifier')) != system_id or value.get('state') not in ('running', 'streaming') or value.get('pause', False):
            errors.append('Unhealthy, paused or foreign live member')
    if sorted(m.get('name', '') for m in members) != sorted(expected_hosts):
        errors.append('Cluster membership differs from inventory')
    for member in members:
        if member.get('state') not in ('running', 'streaming'):
            errors.append('Non-running cluster member')
        if member.get('role') not in ('leader', 'primary', 'master'):
            lag = member.get('lag')
            if type(lag) is not int or lag < 0 or lag > max_lag:
                errors.append('Missing or excessive replication lag')
    return errors
