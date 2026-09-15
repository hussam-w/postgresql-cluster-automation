#!/usr/bin/python
"""Read-only major/data compatibility and initdb capability admission."""
from pathlib import Path
import re
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.postgres_version import validate_major, check_data_major


def main():
    module = AnsibleModule(argument_spec={
        'major': {'type': 'str', 'required': True},
        'data_dir': {'type': 'path', 'required': True},
        'require_binaries': {'type': 'bool', 'default': True},
    }, supports_check_mode=True)
    try:
        major = validate_major(module.params['major'])
        marker = Path(module.params['data_dir']) / 'PG_VERSION'
        check_data_major(major, marker.read_text() if marker.exists() else None)
        binaries = Path('/usr/lib/postgresql') / major / 'bin'
        if not module.params['require_binaries']:
            module.exit_json(changed=False, major=major, data_version_checked=marker.exists())
        for executable in ('postgres', 'initdb', 'pg_ctl', 'pg_basebackup'):
            rc, output, _ = module.run_command([str(binaries / executable), '--version'])
            match = re.search(r'\(PostgreSQL\) ([0-9]+)(?:\.|\b)', output)
            if rc or not match or match[1] != major:
                raise ValueError('Selected PostgreSQL executable is unavailable or reports a different major: ' + executable)
        rc, output, _ = module.run_command([str(binaries / 'initdb'), '--help'])
        if rc or any(option not in output for option in ('--data-checksums', '--auth-local', '--auth-host', '--waldir')):
            raise ValueError('Selected initdb lacks required checksum/authentication/WAL options; no initialization performed')
        module.exit_json(changed=False, major=major, binary_dir=str(binaries), capabilities_verified=True)
    except (ValueError, OSError) as error:
        module.fail_json(changed=False, msg=str(error))


if __name__ == '__main__':
    main()
