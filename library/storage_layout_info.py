#!/usr/bin/python
"""Resolve a named TARGET account home and inspect canonical storage paths only."""
import os
import pwd
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.storage_layout import resolve_layout


def main():
    module = AnsibleModule(argument_spec={'layout': {'type': 'dict', 'required': True}}, supports_check_mode=True)
    try:
        config = module.params['layout']
        home = pwd.getpwnam(config['home_user']).pw_dir if isinstance(config.get('home_user'), str) and config['home_user'] else None
        paths = resolve_layout(config, home)
        for path in paths.values():
            if str(Path(path).resolve()) != path:
                raise ValueError('Storage path traverses a symlink; preserve it and review the mount layout')
        module.exit_json(changed=False, paths=paths,
                         mounted={k: os.path.ismount(v) for k, v in paths.items() if k.endswith('_mount')})
    except (ValueError, KeyError) as error:
        module.fail_json(changed=False, msg=str(error))


if __name__ == '__main__':
    main()
