"""Small non-executable controller configuration; never accepts credentials."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = {'PGHA_INVENTORY', 'PGHA_KNOWN_HOSTS', 'PGHA_COLLECTIONS_PATH',
        'PGHA_STATE_DIR', 'PGHA_SSH_AUTH', 'PGHA_BECOME_AUTH', 'POSTGRES_VERSION', 'ENABLE_BACKUP', 'ENABLE_HAPROXY', 'BACKUP_TARGET_PATH', 'POSTGRES_EXTENSIONS'}


def boolean(value):
    if value not in ('true', 'false'):
        raise ValueError('Component environment switches must be exactly true or false')
    return value == 'true'


def load(path=None, environ=None):
    environ = os.environ if environ is None else environ
    selected = ROOT / Path(path).expanduser() if path else ROOT / '.env'
    result = {}
    if path and not selected.is_file():
        raise ValueError('The selected environment file does not exist')
    if selected.is_file():
        for number, raw in enumerate(selected.read_text(encoding='utf-8').splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not separator or key not in KEYS or key in result:
                raise ValueError(f'Invalid or duplicate controller key on line {number}')
            if value[:1] in ('"', "'"):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError(f'Unclosed quote on line {number}')
                value = value[1:-1]
            # Values are literal: no shell interpolation, commands, or secrets.
            if any(c in value for c in ('$', '`', '\x00')):
                raise ValueError(f'Use literal values or ~/ paths on line {number}')
            result[key] = value
    result.update({key: environ[key] for key in KEYS if key in environ})
    return result


def file_path(value, label):
    if not value:
        raise ValueError(f'{label} is required; set a CLI option or PGHA configuration')
    path = Path(value).expanduser()
    path = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file():
        raise ValueError(f'{label} must name an existing file')
    return path


def ssh_options(path):
    # OpenSSH receives this string through Ansible's argument splitting.
    import shlex
    return '-o StrictHostKeyChecking=yes -o ' + shlex.quote('UserKnownHostsFile=' + str(path))


def extension_names(value):
    import re
    result = [] if not value.strip() else [name.strip() for name in value.split(',')]
    if len(result) != len(set(result)) or any(not re.fullmatch(r'[a-z][a-z0-9_-]*', name) for name in result):
        raise ValueError('POSTGRES_EXTENSIONS must be unique comma-separated extension names')
    return result
