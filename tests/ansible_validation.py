"""Parse every YAML file, syntax-check entry points, and prove example rejection."""
import os
import json
import subprocess
from pathlib import Path
import yaml
from fixture import ROOT


class UniqueKeys(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError('Duplicate YAML key')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def main():
    for directory, children, names in os.walk(ROOT):
        children[:] = [name for name in children if name not in {'artifacts', '.git', '.venv', '__pycache__'}]
        for name in names:
            if name.endswith('.yml'):
                yaml.load((Path(directory) / name).read_text(), Loader=UniqueKeys)
    print('PASS: YAML parsing with duplicate-key rejection')
    env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / 'ansible.cfg'),
               ANSIBLE_COLLECTIONS_PATH=str(Path.home() / '.local/share/pg-ha/collections'))
    base = ['ansible-playbook', '-i', 'inventories/example/hosts.yml']
    for name in sorted(path.stem for path in (ROOT / 'playbooks').glob('*.yml')):
        result = subprocess.run(base + [f'playbooks/{name}.yml', '--syntax-check'],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        print('PASS: syntax ' + name)
    result = subprocess.run(base + ['playbooks/validate-inputs.yml'], cwd=ROOT, env=env,
                            text=True, capture_output=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'is required' in result.stdout
    assert 'unreachable=0' in result.stdout
    print('PASS: incomplete example rejected locally before SSH or host mutations')
    for selected in [[], ['pgcrypto', 'pgvector', 'timescaledb'], ['third_party_preinstalled']]:
        result = subprocess.run(base + ['playbooks/model-validate.yml', '-e', '@examples/onprem.yml',
                                       '-e', json.dumps({'postgresql_extensions': selected})],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        print('PASS: on-premise declarative extension selection ' + str(selected))
    # Resolve the actual Jinja model and version variable through Ansible, locally only.
    version_inventory = ROOT / 'artifacts/version-matrix-inventory.yml'
    version_inventory.parent.mkdir(parents=True, exist_ok=True)
    version_inventory.write_text('all:\n  children:\n    postgres_cluster:\n      hosts:\n        pg01: {}\n')
    for major in ['14', '15', '16', '17', '18', '19']:
        result = subprocess.run(['ansible-playbook', '-i', str(version_inventory),
                                 'playbooks/model-validate.yml', '-e', '@examples/standalone.yml',
                                 '-e', json.dumps({'postgresql_version': major})],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'changed=0' in result.stdout and 'unreachable=0' in result.stdout
        print('PASS: Ansible version selection ' + major)
    for count, routing, backup in [(1, False, False), (1, True, True), (2, False, True), (3, False, False), (3, True, True), (5, True, False)]:
        hosts = ['pg' + str(i) for i in range(1, count+1)]
        core = hosts[:3] if count >= 3 else hosts[:1]
        inventory = {'all': {'children': {'postgres_cluster': {'hosts': dict.fromkeys(hosts, {})},
                                          'etcd_cluster': {'hosts': dict.fromkeys(core, {})},
                                          'routers': {'hosts': dict.fromkeys(core if routing else [], {})}}}}
        version_inventory.write_text(yaml.safe_dump(inventory))
        overrides = {'standby_nodes': hosts[1:], 'standby_count': count-1,
                     'allow_degraded_topology': count < 3, 'enable_haproxy': routing, 'enable_backup': backup}
        result = subprocess.run(['ansible-playbook', '-i', str(version_inventory), 'playbooks/model-validate.yml',
                                 '-e', '@examples/modular-ha.yml', '-e', json.dumps(overrides)],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'changed=0' in result.stdout and 'unreachable=0' in result.stdout
        print('PASS: modular topology/component resolution ' + str((count, routing, backup)))
    for invalid in [
        {'mode': 'standalone', 'major': '17', 'topology': {'primary': 'unknown'}},
        {'mode': 'cluster', 'major': '16', 'topology': {'primary': 'unknown'}},
        {'mode': 'cluster', 'major': '17', 'topology': {'primary': ['pg01', 'pg02']}},
    ]:
        result = subprocess.run(base + ['playbooks/postgresql.yml', '-e', json.dumps({'postgresql_deployment': invalid})],
                                cwd=ROOT, env=env, text=True, capture_output=True)
        assert result.returncode == 2, result.stdout + result.stderr
        assert 'unreachable=0' in result.stdout and 'changed=0' in result.stdout
        assert 'Discover existing infrastructure' not in result.stdout
    print('PASS: invalid deployment modes/topologies/versions refused before SSH')
    for name in ['platform', 'deploy', 'provision-cluster', 'ip-migration']:
        result = subprocess.run(base + [f'playbooks/{name}.yml'], cwd=ROOT, env=env,
                                text=True, capture_output=True)
        assert result.returncode == 2, result.stdout + result.stderr
        assert 'opt-in maintenance operation' in result.stdout, result.stdout + result.stderr
        assert 'unreachable=0' in result.stdout and 'changed=0' in result.stdout
        print('PASS: unapproved ' + name + ' refused before SSH or mutation')


if __name__ == '__main__':
    main()
