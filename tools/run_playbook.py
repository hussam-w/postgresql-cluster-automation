#!/usr/bin/env python3
"""Run a selected project playbook using protected interactive SSH prompts."""
import argparse
import os
from pathlib import Path
import sys
import fcntl
from controller_config import load, file_path, ssh_options, boolean, extension_names

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('playbook')
    parser.add_argument('--env-file', help='Non-executable controller settings file; defaults to project .env')
    parser.add_argument('--inventory')
    parser.add_argument('--postgres-version', help='PostgreSQL major; models must reference postgresql_version')
    parser.add_argument('--extensions', help='Comma-separated PostgreSQL extension names')
    parser.add_argument('--enable-backup', choices=['true', 'false'])
    parser.add_argument('--enable-haproxy', choices=['true', 'false'])
    parser.add_argument('--backup-target-path')
    parser.add_argument('--extra-vars', action='append', default=[])
    parser.add_argument('--vault-password-file')
    parser.add_argument('--syntax-check', action='store_true')
    parser.add_argument('--check', action='store_true', help='Predict supported reconciliation changes without applying them')
    parser.add_argument('--verbose', action='count', default=0)
    parser.add_argument('--known-hosts')
    parser.add_argument('--ssh-auth', choices=['password', 'key'])
    parser.add_argument('--become-auth', choices=['password', 'passwordless'])
    parser.add_argument('--read-only-diagnostics', action='store_true')
    args = parser.parse_args()
    if args.read_only_diagnostics and args.playbook != 'playbooks/diagnose-platform.yml':
        parser.error('Concurrent diagnostics are restricted to the read-only platform diagnostic playbook.')
    try:
        config = load(args.env_file)
        component_overrides = {}
        extension_value = args.extensions if args.extensions is not None else config.get('POSTGRES_EXTENSIONS')
        if extension_value is not None:
            component_overrides['postgresql_extensions'] = extension_names(extension_value)
        for argument, key, variable in [(args.enable_backup, 'ENABLE_BACKUP', 'enable_backup'), (args.enable_haproxy, 'ENABLE_HAPROXY', 'enable_haproxy')]:
            value = argument if argument is not None else config.get(key)
            if value is not None:
                component_overrides[variable] = boolean(value)
        backup_path = args.backup_target_path or config.get('BACKUP_TARGET_PATH')
        if backup_path is not None:
            component_overrides['backup_target_path'] = backup_path
        selected_major = args.postgres_version or config.get('POSTGRES_VERSION')
        if selected_major is not None:
            sys.path.insert(0, str(ROOT))
            from module_utils.postgres_version import validate_major
            validate_major(selected_major)
        args.inventory = str(file_path(args.inventory or config.get('PGHA_INVENTORY'), 'Inventory'))
        known = file_path(args.known_hosts or config.get('PGHA_KNOWN_HOSTS'), 'Verified known-hosts file')
        args.ssh_auth = args.ssh_auth or config.get('PGHA_SSH_AUTH', 'key')
        args.become_auth = args.become_auth or config.get('PGHA_BECOME_AUTH', 'password')
        if args.ssh_auth not in ('password', 'key') or args.become_auth not in ('password', 'passwordless'):
            raise ValueError('Invalid SSH or become authentication mode')
    except ValueError as error:
        parser.error(str(error))
    env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / 'ansible.cfg'),
               ANSIBLE_NOCOLOR='true', ANSIBLE_STDOUT_CALLBACK='default',
               ANSIBLE_CACHE_PLUGIN='memory', ANSIBLE_HOST_KEY_CHECKING='true',
               ANSIBLE_DISPLAY_ARGS_TO_STDOUT='false', ANSIBLE_KEEP_REMOTE_FILES='false')
    env['ANSIBLE_COLLECTIONS_PATH'] = str((ROOT / Path(config.get('PGHA_COLLECTIONS_PATH', '~/.local/share/pg-ha/collections')).expanduser()).resolve())
    for key in ['ANSIBLE_LOG_PATH', 'ANSIBLE_CALLBACKS_ENABLED']:
        env.pop(key, None)
    import json
    argv = ['ansible-playbook', '-i', args.inventory, args.playbook, '-e', json.dumps({
        'ansible_ssh_common_args': ssh_options(known)
    })]
    if args.syntax_check:
        argv.append('--syntax-check')
    else:
        if (args.ssh_auth == 'password' or args.become_auth == 'password') and not sys.stdin.isatty():
            sys.exit('A terminal is required for hidden credential prompts.')
        if args.ssh_auth == 'password':
            argv.append('--ask-pass')
        if args.become_auth == 'password':
            argv.append('--ask-become-pass')
    if args.check:
        argv.append('--check')
    if args.verbose:
        argv.append('-' + 'v' * min(args.verbose, 3))
    for value in args.extra_vars:
        argv += ['-e', value]
    # Apply the runner's explicit selection after model files containing example defaults.
    if selected_major is not None:
        argv += ['-e', json.dumps({'postgresql_version': selected_major})]
    if component_overrides:
        argv += ['-e', json.dumps(component_overrides)]
    if args.vault_password_file:
        argv += ['--vault-password-file', args.vault_password_file]
    os.chdir(ROOT)
    lock_path = (ROOT / Path(config.get('PGHA_STATE_DIR', '~/.local/share/pg-ha')).expanduser()).resolve() / 'controller-change.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    if not args.read_only_diagnostics:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('Another project playbook holds the controller change lock.')
    os.set_inheritable(lock, True)
    os.execvpe(argv[0], argv, env)


if __name__ == '__main__':
    main()
