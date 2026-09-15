#!/usr/bin/python
"""Read-only mount and existing-data guard; never formats, moves or chmods."""
import json
import os
import subprocess
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(argument_spec={
        'paths': {'type': 'dict', 'required': True},
        'backup_required': {'type': 'bool', 'default': True},
        'min_free_bytes': {'type': 'int', 'default': 10737418240},
    }, supports_check_mode=True)
    p = module.params['paths']
    observations = {}
    try:
        for key in ['data_mount', 'wal_mount'] + (['backup_mount'] if module.params['backup_required'] else []):
            path = Path(p[key])
            if not path.is_dir() or str(path.resolve()) != str(path):
                raise ValueError(key + ': prepare an existing canonical directory first')
            # data/backups must be actual mount points; WAL may use its parent filesystem.
            result = subprocess.run(['findmnt', '-J', '-M' if key != 'wal_mount' else '-T', str(path),
                                     '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS,UUID'], capture_output=True, text=True, timeout=10)
            if result.returncode:
                raise ValueError(key + ': expected storage is not mounted; refusing root-filesystem fallback')
            fs = json.loads(result.stdout)['filesystems'][0]
            if fs['fstype'] not in ['ext4', 'xfs'] or 'ro' in fs['options'].split(','):
                raise ValueError(key + ': require writable ext4 or XFS')
            v = os.statvfs(path)
            if v.f_bavail * v.f_frsize < module.params['min_free_bytes']:
                raise ValueError(key + ': insufficient free storage')
            observations[key] = fs
        data = Path(p['data_dir'])
        if (data / 'PG_VERSION').exists():
            wal = data / 'pg_wal'
            if not wal.is_symlink() or not wal.is_dir() or str(wal.resolve()) != p['wal_dir']:
                raise ValueError('Existing PostgreSQL WAL layout differs; stop for a backed-up, offline migration')
        else:
            for key in ['data_dir', 'wal_dir']:
                path = Path(p[key])
                if path.exists() or path.is_symlink():
                    raise ValueError(key + ': existing partial/foreign state is preserved; no reinitialization')
        marker = Path('/var/lib/pg-ha/identity.json')
        if marker.exists() and json.loads(marker.read_text())['cluster']['data_dir'] != p['data_dir']:
            raise ValueError('Completed HA ownership uses another data path; automatic relocation is prohibited')
        module.exit_json(changed=False, mounts=observations)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        module.fail_json(changed=False, msg=str(error))


if __name__ == '__main__':
    main()
