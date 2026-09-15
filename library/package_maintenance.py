#!/usr/bin/python
"""Request documented graceful updater cancellation; never kill dpkg or delete locks."""
import fcntl
import os
from pathlib import Path
import signal
from ansible.module_utils.basic import AnsibleModule

module = AnsibleModule(argument_spec={'cancel_updater': {'type': 'bool', 'default': False},
                                      'cancel_stalled_downloads': {'type': 'bool', 'default': False}}, supports_check_mode=True)
signaled = []
if module.params['cancel_updater'] and not module.check_mode:
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / 'cmdline').read_bytes().split(b'\0')
            if b'/usr/bin/unattended-upgrade' not in argv:
                continue
            if b'--no-minimal-upgrade-steps' in argv:
                module.fail_json(msg='Updater explicitly disables safe minimal steps; wait for completion.')
            descriptor = os.pidfd_open(int(proc.name))
            try:
                if (proc / 'cmdline').read_bytes().split(b'\0') == argv:
                    signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                    signaled.append(int(proc.name))
            finally:
                os.close(descriptor)
        except (FileNotFoundError, ProcessLookupError):
            pass
    if module.params['cancel_stalled_downloads']:
        # APT authenticates resumed archives before installing them. Canceling only
        # a known updater-owned HTTP fetcher leaves partial downloads for APT;
        # it never interrupts dpkg or modifies the package database.
        processes = []
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                executable = str((proc / 'exe').readlink())
                status = (proc / 'status').read_text().splitlines()
                parent = int(next(line.split()[1] for line in status if line.startswith('PPid:')))
                processes.append((proc, executable, parent))
            except (FileNotFoundError, ProcessLookupError):
                pass
        if any(executable == '/usr/bin/dpkg' for _, executable, _ in processes):
            module.fail_json(msg='dpkg is active; no download workers were interrupted.')
        for proc, executable, parent in processes:
            if parent not in signaled or executable != '/usr/lib/apt/methods/http':
                continue
            try:
                descriptor = os.pidfd_open(int(proc.name))
                try:
                    if str((proc / 'exe').readlink()) == executable:
                        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                finally:
                    os.close(descriptor)
            except (FileNotFoundError, ProcessLookupError):
                pass
locked = []
for path in ['/var/lib/dpkg/lock-frontend', '/var/lib/dpkg/lock', '/var/lib/apt/lists/lock', '/var/cache/apt/archives/lock']:
    if not Path(path).exists():
        continue
    with open(path, 'r+b') as stream:
        try:
            fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(stream, fcntl.LOCK_UN)
        except BlockingIOError:
            locked.append(path)
module.exit_json(changed=bool(signaled), cancellation_requested=len(signaled), locks_held=locked)
