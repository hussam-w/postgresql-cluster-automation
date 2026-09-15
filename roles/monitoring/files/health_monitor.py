#!/usr/bin/python3
"""Functional node/endpoint checks; emits only nonsecret status and error categories."""
import datetime
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import urllib.request
import psycopg2


def main():
    config = json.loads(Path('/etc/pg-ha/monitor.json').read_text())
    errors = []
    for path in config['mounts']:
        usage = shutil.disk_usage(path)
        if usage.free / usage.total < 0.15:
            errors.append('disk_capacity:' + path)
    context = ssl.create_default_context(cafile='/etc/pg-ha/patroni/ca.pem')
    context.load_cert_chain('/etc/pg-ha/patroni/cert.pem', '/etc/pg-ha/patroni/key.pem')
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        with opener.open(config['patroni_url'] + '/cluster', timeout=5) as response:
            members = json.load(response)['members']
        if sum(m['role'] == 'leader' for m in members) != 1:
            errors.append('patroni_leader_count')
        if sorted(m['name'] for m in members) != sorted(config['members']):
            errors.append('patroni_membership')
        with opener.open(config['patroni_url'] + '/patroni', timeout=5) as response:
            local = json.load(response)
        if local.get('watchdog_failed') or local.get('state') != 'running' or local.get('timeline') is None:
            errors.append('patroni_local_safety')
        if local.get('pending_restart'):
            errors.append('postgresql_pending_restart')
    except Exception:
        errors.append('patroni_authenticated_health')
    try:
        with psycopg2.connect(host='/run/pg-ha-patroni', port=config['pg_port'], dbname='postgres', user='postgres',
                             connect_timeout=5, options='-c statement_timeout=5000') as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_is_in_recovery()')
                if cursor.fetchone()[0]:
                    cursor.execute("SELECT count(*) FROM pg_stat_wal_receiver WHERE status='streaming'")
                    if cursor.fetchone()[0] != 1:
                        errors.append('replication_receiver')
                else:
                    cursor.execute("SELECT count(*), count(*) FILTER (WHERE sync_state='sync') FROM pg_stat_replication WHERE state='streaming'")
                    total, synchronous = cursor.fetchone()
                    if total < len(config['members']) - 1 or synchronous < config['sync_count']:
                        errors.append('replication_senders')
                    cursor.execute("SELECT last_failed_time IS NOT NULL AND (last_archived_time IS NULL OR last_failed_time > last_archived_time) AND last_failed_time < now() - interval '120 seconds' FROM pg_stat_archiver")
                    if cursor.fetchone()[0]:
                        errors.append('wal_archiving_failure')
    except Exception:
        errors.append('local_database_health')
    try:
        clock = subprocess.run(['timedatectl', 'show', '--property=NTPSynchronized', '--value'], capture_output=True, text=True, timeout=5)
        if clock.returncode or clock.stdout.strip() != 'yes':
            errors.append('time_synchronization')
    except Exception:
        errors.append('time_synchronization')
    try:
        import os
        env = dict(os.environ, ETCDCTL_API='3', ETCDCTL_ENDPOINTS=config['etcd_url'],
                   ETCDCTL_CACERT='/etc/pg-ha/dcs/ca.pem', ETCDCTL_CERT='/etc/pg-ha/dcs/cert.pem',
                   ETCDCTL_KEY='/etc/pg-ha/dcs/key.pem')
        result = subprocess.run([config['etcdctl'], 'endpoint', 'health'], env=env, capture_output=True, timeout=10)
        if result.returncode:
            errors.append('etcd_consensus_health')
    except Exception:
        errors.append('etcd_consensus_health')
    for port, recovery in [(config['write_port'], False), (config['read_port'], True)]:
        try:
            with psycopg2.connect(host=config['vip_dns'], hostaddr=config['vip'], port=port,
                                 dbname=config['database'], user=config['user'], password=config['password'],
                                 sslmode='verify-full', sslrootcert='/etc/pg-ha/postgres/ca.pem',
                                 connect_timeout=5) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SET statement_timeout=5000')
                    cursor.execute('SELECT pg_is_in_recovery()')
                    if cursor.fetchone()[0] != recovery:
                        errors.append('endpoint_role:' + str(port))
        except Exception:
            errors.append('endpoint_sql:' + str(port))
    for name in ['postgres', 'patroni', 'dcs']:
        result = subprocess.run(['openssl', 'x509', '-in', '/etc/pg-ha/' + name + '/cert.pem', '-checkend', '2592000', '-noout'], capture_output=True, timeout=10)
        if result.returncode:
            errors.append('certificate_expiry:' + name)
    if config['repository_host']:
        try:
            result = subprocess.run(['pgbackrest', '--stanza=' + config['stanza'], '--output=json', 'info'], capture_output=True, text=True, timeout=30, check=True)
            info = json.loads(result.stdout)[0]
            latest = max(b['timestamp']['stop'] for b in info['backup'])
            if info['status']['code'] != 0 or datetime.datetime.now().timestamp() - latest > 93600:
                errors.append('backup_age_or_status')
        except Exception:
            errors.append('backup_unavailable')
    state = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'healthy': not errors, 'errors': errors}
    path = Path('/var/lib/pg-ha-monitor/status.json')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(path)
    print(json.dumps(state))
    return bool(errors)


if __name__ == '__main__':
    sys.exit(main())
