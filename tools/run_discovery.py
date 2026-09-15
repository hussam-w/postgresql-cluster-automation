#!/usr/bin/env python3
"""Linux controller: Ansible native hidden prompts and strict SSH host identity.

No credential in argv, environment variables, inventory or a disk file. Ansible
owns its standard in-memory password and sshpass descriptor handling.
"""
import argparse
import json
import os
from pathlib import Path
import sys
try:
    from .controller_config import load, file_path
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from controller_config import load, file_path

ROOT = Path(__file__).resolve().parents[1]


def command(port, privileged, known_hosts=None, inventory=None):
    if not 1 <= port <= 65535:
        raise ValueError('Invalid SSH port')
    values = {'discovery_ssh_port': port, 'discovery_privileged': privileged}
    ssh_args = ['-o', 'StrictHostKeyChecking=yes', '-o', 'PreferredAuthentications=password',
                '-o', 'NumberOfPasswordPrompts=1', '-o', 'PubkeyAuthentication=no']
    if known_hosts:
        # Reject quoting/metacharacters before creating an OpenSSH argument string.
        path = str(known_hosts.resolve())
        if not known_hosts.is_file():
            raise ValueError('The verified known-hosts file does not exist')
        if any(character in path for character in ['"', "'", '\n', '\r', ' ', '\t']):
            raise ValueError('Use a trusted known-hosts file path without whitespace or quotes')
        ssh_args += ['-o', 'UserKnownHostsFile=' + path]
    values['ansible_ssh_common_args'] = ' '.join(ssh_args)
    if not inventory:
        raise ValueError('An explicit discovery inventory is required')
    argv = ['ansible-playbook', '-i', str(inventory),
            'playbooks/discover.yml', '-e', json.dumps(values), '--ask-pass']
    if privileged:
        argv.append('--ask-become-pass')
    return argv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--privileged', action='store_true')
    parser.add_argument('--known-hosts', type=Path)
    parser.add_argument('--inventory')
    parser.add_argument('--env-file')
    args = parser.parse_args()
    if not sys.stdin.isatty():
        sys.exit('A terminal is required for Ansible hidden password prompts; no plaintext fallback is supported.')
    try:
        config = load(args.env_file)
        inventory = file_path(args.inventory or config.get('PGHA_INVENTORY'), 'Discovery inventory')
        known = file_path(args.known_hosts or config.get('PGHA_KNOWN_HOSTS'), 'Verified known-hosts file')
        argv = command(args.port, args.privileged, known, inventory)
    except ValueError as error:
        sys.exit(str(error))
    env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / 'ansible.cfg'),
               ANSIBLE_STDOUT_CALLBACK='default', ANSIBLE_NOCOLOR='true',
               ANSIBLE_CACHE_PLUGIN='memory', ANSIBLE_DISPLAY_ARGS_TO_STDOUT='false',
               ANSIBLE_HOST_KEY_CHECKING='true', ANSIBLE_KEEP_REMOTE_FILES='false')
    env.pop('ANSIBLE_LOG_PATH', None)
    env.pop('ANSIBLE_CALLBACKS_ENABLED', None)
    env['ANSIBLE_COLLECTIONS_PATH'] = str((ROOT / Path(config.get('PGHA_COLLECTIONS_PATH', '~/.local/share/pg-ha/collections')).expanduser()).resolve())
    os.chdir(ROOT)
    os.execvpe(argv[0], argv, env)


if __name__ == '__main__':
    sys.exit(main())
