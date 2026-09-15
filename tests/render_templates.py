"""Render synthetic configuration for parser testing; no production inputs."""
import json
from pathlib import Path
import sys
import jinja2
import yaml
import posixpath
from fixture import ROOT, fixture
sys.path.insert(0, str(ROOT))
from module_utils.network_policy import resolve_ports
from module_utils.deployment_model import extension_plan
from ansible_validation import UniqueKeys


def render(output, model=None, hostname='pg1', storage_root=None, node_count=3):
    c, nodes = fixture()
    seed = nodes['pg1']
    nodes = {'pg' + str(i): dict(seed, address='192.0.2.' + str(20+i), dns_name='pg' + str(i) + '.example.test', priority=160-i*10, failure_domain='rack-'+str(i)) for i in range(1,node_count+1)}
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    env.filters['to_json'] = json.dumps
    env.filters['to_nice_json'] = json.dumps
    env.filters['dirname'] = posixpath.dirname
    variables = dict(cluster=c, node=nodes[hostname], inventory_hostname=hostname,
                     groups={'postgres_cluster': list(nodes), 'etcd_cluster': list(nodes), 'routers': list(nodes), 'target_vms': list(nodes)},
                     hostvars={name: {'node': node, 'management_ip': node['address'], 'intended_roles': {}, 'discovery_observation': {'report': None}} for name, node in nodes.items()},
                     vault_pg_superuser_password='TEST-ONLY-NOT-A-PRODUCTION-SECRET',
                     vault_pg_replication_password='TEST-ONLY-NOT-A-PRODUCTION-SECRET',
                     vault_patroni_api_password='TEST-ONLY-NOT-A-PRODUCTION-SECRET',
                     vault_app_users=[{'name': 'test_app'}], application_databases=[{'name': 'test_db', 'owner': 'test_app'}],
                     **yaml.safe_load((ROOT / 'roles/common/defaults/main.yml').read_text()))
    output.mkdir(parents=True, exist_ok=True)
    variables['etcd_binary_dir'] = '/opt/pg-ha/etcd/' + c['expected_versions']['etcd']
    variables['standalone'] = yaml.safe_load((ROOT / 'roles/standalone/defaults/main.yml').read_text())['standalone_defaults']
    variables['postgresql_deployment'] = model or {'mode': 'cluster', 'major': '17', 'topology': {'replicas': []}}
    from module_utils.deployment_components import cluster_components, component_plan
    c.update(cluster_components(c, variables['postgresql_deployment']))
    switches = component_plan(variables['postgresql_deployment'])
    variables['haproxy_enabled'] = switches['haproxy']
    variables['wal_archive_enabled'] = c.get('components', {}).get('wal_archive', True)
    variables['groups']['etcd_cluster'] = list(nodes)[:3] if len(nodes) >= 3 else list(nodes)[:1]
    variables['groups']['routers'] = variables['groups']['etcd_cluster'] if switches['haproxy'] else []
    variables['postgresql_major'] = variables['postgresql_deployment']['major']
    variables['binary_dir'] = '/usr/lib/postgresql/' + variables['postgresql_major'] + '/bin'
    variables['hostvars']['localhost'] = {'deployment_model': {'extensions': extension_plan(variables['postgresql_deployment'].get('extensions', []), variables['postgresql_major'], variables['postgresql_deployment'].get('extension_registry'))}}
    if storage_root:
        from module_utils.storage_layout import resolve_layout
        paths = resolve_layout({'root': storage_root})
        variables['storage_paths'] = paths
        c.update(data_dir=paths['data_dir'], postgres_mount=paths['data_mount'], wal_dir=paths['wal_dir'])
        variables['standalone'].update(data_dir=paths['data_dir'], storage_mount=paths['data_mount'], wal_dir=paths['wal_dir'])
    variables['postgres_archive_command'] = c['backup']['archive_executable'] + ' %p %f' if variables['wal_archive_enabled'] else ''
    ports = resolve_ports(c.get('ports'))
    for variable, key in {'pg_port': 'postgres', 'pool_port': 'pgbouncer', 'patroni_port': 'patroni',
                          'etcd_client_port': 'etcd_client', 'etcd_peer_port': 'etcd_peer',
                          'write_port': 'write', 'read_port': 'read'}.items():
        variables[variable] = ports[key]
    for path in ROOT.glob('roles/*/templates/*.j2'):
        if path.parent.parent.name in ['platform', 'backup', 'logical_backup']:
            continue  # Platform templates are validated by native netplan/nft before activation.
        text = env.from_string(path.read_text()).render(**variables)
        target = output / path.name.removesuffix('.j2')
        target.write_text(text, encoding='utf-8')
        if target.suffix == '.yml':
            yaml.load(text, Loader=UniqueKeys)
        print(target.name)


if __name__ == '__main__':
    render(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'artifacts' / 'rendered')
