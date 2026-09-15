"""Conservative, version-aware PostgreSQL reload planning (no I/O)."""
import hashlib
import copy
import json
import re
from decimal import Decimal, InvalidOperation

# Deliberately exclude authentication, replication, durability, paths and SQL hooks.
# Reloadability alone does not establish that a setting is safe to automate.
RELOAD_SETTINGS = frozenset({
    'log_checkpoints', 'log_lock_waits', 'log_min_duration_statement',
    'log_temp_files', 'deadlock_timeout', 'checkpoint_completion_target',
})
UNITS = {'B': Decimal(1), 'kB': Decimal(1024), 'MB': Decimal(1024**2),
         'GB': Decimal(1024**3), 'TB': Decimal(1024**4), '8kB': Decimal(8192),
         'us': Decimal('0.001'), 'ms': Decimal(1), 's': Decimal(1000),
         'min': Decimal(60000), 'h': Decimal(3600000), 'd': Decimal(86400000)}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def dynamic_candidate(original, changes):
    candidate = copy.deepcopy(original)
    candidate.setdefault('postgresql', {}).setdefault('parameters', {}).update(
        {name: entry['after'] for name, entry in changes.items()})
    return candidate


def normalized(value, setting):
    text = str(value).strip()
    kind = setting['vartype']
    if kind == 'bool':
        if text.lower() in ('on', 'true', 'yes', '1'):
            return 'on'
        if text.lower() in ('off', 'false', 'no', '0'):
            return 'off'
        raise ValueError('Expected a complete Boolean value')
    if kind in ('integer', 'real'):
        match = re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([A-Za-z]+)?', text)
        if not match:
            raise ValueError('Expected a numeric value with an optional PostgreSQL unit')
        number = Decimal(match[1])
        unit = match[2]
        base = setting.get('unit')
        if unit:
            memory = {'B', 'kB', 'MB', 'GB', 'TB', '8kB'}
            if unit not in UNITS or base not in UNITS or ((unit in memory) != (base in memory)):
                raise ValueError('Unit is incompatible with this setting')
            number = number * UNITS[unit] / UNITS[base]
        if kind == 'integer' and number != number.to_integral_value():
            raise ValueError('Fractional base units require manual review')
        if setting.get('min_val') is not None and number < Decimal(setting['min_val']):
            raise ValueError('Value is below the server minimum')
        if setting.get('max_val') is not None and number > Decimal(setting['max_val']):
            raise ValueError('Value exceeds the server maximum')
        return format(number.normalize(), 'f')
    raise ValueError('This parameter type has no approved reconciliation implementation')


def plan_settings(desired, settings, version):
    changes, compliant, blockers = {}, [], []
    if int(version) < 140000:
        blockers.append('Settings reconciliation requires PostgreSQL 14 or above; preserve this version.')
    for name, value in sorted(desired.items()):
        current = settings.get(name)
        if name not in RELOAD_SETTINGS:
            blockers.append(name + ': outside the approved reload scope; use a reviewed maintenance procedure')
            continue
        if not current or current['context'] not in ('sighup', 'superuser', 'user'):
            blockers.append(name + ': unavailable or requires a restart/new backend; no automatic restart')
            continue
        if current.get('pending_restart'):
            blockers.append(name + ': an existing pending restart must be investigated')
            continue
        if current.get('source', 'default') not in ('default', 'configuration file'):
            blockers.append(name + ': session/role/database/command-line override requires ownership review')
            continue
        try:
            wanted = normalized(value, current)
            actual = normalized(current['setting'], current)
        except (ValueError, InvalidOperation) as error:
            blockers.append(name + ': ' + str(error))
            continue
        if wanted == actual:
            compliant.append(name)
        else:
            changes[name] = {'before': actual, 'after': wanted, 'unit': current.get('unit'),
                             'sourcefile': current.get('sourcefile')}
    return {'changes': changes, 'compliant': compliant, 'blockers': blockers}
