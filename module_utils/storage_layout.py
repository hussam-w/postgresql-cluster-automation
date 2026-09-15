"""Canonical, opt-in storage layout. No shell expansion or filesystem mutation."""
import re
from pathlib import PurePosixPath


def resolve_layout(config, home=None):
    if not isinstance(config, dict) or set(config) - {'root', 'home_user'}:
        raise ValueError('storage_layout accepts only root or home_user')
    if bool(config.get('root')) == bool(config.get('home_user')):
        raise ValueError('Choose exactly one absolute root or target home_user')
    if config.get('home_user') and (not isinstance(config['home_user'], str) or not re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?', config['home_user'])):
        raise ValueError('home_user must be an existing target account name')
    base = config.get('root') or (str(home).rstrip('/') + '/data' if home else '')
    if (not isinstance(base, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', base)
            or str(PurePosixPath(base)) != base or '..' in PurePosixPath(base).parts
            or base in ['/', '/home', '/root', '/srv', '/var', '/var/lib', '/etc', '/usr', '/tmp', '/run']
            or any(base.startswith(p + '/') for p in ['/etc', '/usr', '/tmp', '/run', '/proc', '/sys', '/dev'])):
        raise ValueError('Use a dedicated canonical absolute storage root; shell variables, tilde, relative paths and temporary/system trees are refused')
    return {'root': base, 'data_mount': base + '/data', 'data_dir': base + '/data/pgdata',
            'wal_mount': base + '/wal', 'wal_dir': base + '/wal/pg_wal',
            'backup_mount': base + '/backups', 'backup_dir': base + '/backups/repository'}
