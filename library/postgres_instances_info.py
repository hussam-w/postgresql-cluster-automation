#!/usr/bin/python
"""Resolve local instance connection hints without starting offline clusters."""
import json
from pathlib import Path
import subprocess
from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(argument_spec={
        'markers': {'type': 'list', 'elements': 'dict', 'default': []},
        'instances': {'type': 'list', 'elements': 'dict', 'default': []},
    }, supports_check_mode=True)
    found, gaps, offline = {}, [], []
    for marker in module.params['markers']:
        path = Path(marker.get('path', '/'))
        if path.name != 'PG_VERSION':
            continue
        pidfile = path.parent / 'postmaster.pid'
        if not pidfile.is_file():
            offline.append(str(path.parent))
            continue
        try:
            lines = pidfile.read_text()[:8192].splitlines()
            port, socket = int(lines[3]), lines[4].split(',')[0]
            import pwd
            owner = pwd.getpwuid(path.stat().st_uid).pw_name
            if not socket.startswith('/'):
                raise ValueError()
            found[(socket, port)] = {'socket_dir': socket, 'port': port, 'owner': owner,
                                     'manager': 'observe', 'detected_data_dir': str(path.parent)}
        except (OSError, ValueError, IndexError, KeyError):
            gaps.append('Cannot resolve local SQL endpoint for ' + str(path.parent))
    tool = module.get_bin_path('pg_lsclusters')
    if tool:
        try:
            result = subprocess.run([tool, '--json'], capture_output=True, text=True, timeout=10)
            if result.returncode:
                raise ValueError()
            for row in json.loads(result.stdout):
                if not str(row.get('status', '')).startswith('online'):
                    offline.append(row.get('pgdata', row.get('name', 'unknown registered cluster')))
                # Running instances are resolved from their PID files above, never guessed ports.
        except (ValueError, subprocess.TimeoutExpired, OSError):
            gaps.append('Installed pg_lsclusters could not provide JSON; inspect registered clusters manually')
    declared = set()
    for instance in module.params['instances']:
        key = (instance.get('socket_dir'), instance.get('port', 5432))
        if key in declared or not isinstance(key[0], str) or not key[0].startswith('/'):
            module.fail_json(msg='Each declared instance needs a unique absolute socket_dir and port')
        declared.add(key)
        found[key] = dict(found.get(key, {}), **instance)
    module.exit_json(changed=False, instances=list(found.values()),
                     offline_data_directories=sorted(set(offline)), coverage_gaps=gaps)


if __name__ == '__main__':
    main()
