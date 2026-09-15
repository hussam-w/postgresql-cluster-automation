#!/usr/bin/python
"""Read only nonsecret Patroni identity and eligibility tags."""
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(argument_spec={'path': {'type': 'path', 'required': True}}, supports_check_mode=True)
    path = Path(module.params['path'])
    if not path.exists():
        module.exit_json(changed=False, exists=False)
    try:
        import yaml
        data = yaml.safe_load(path.read_text())
        tags = data.get('tags', {})
        module.exit_json(changed=False, exists=True, name=data.get('name'), scope=data.get('scope'),
                         data_dir=data.get('postgresql', {}).get('data_dir'),
                         nofailover=tags.get('nofailover', False), nosync=tags.get('nosync', False))
    except Exception:
        module.fail_json(msg='Cannot inspect Patroni role metadata; preserve configuration and investigate')


if __name__ == '__main__':
    main()
