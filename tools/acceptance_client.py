#!/usr/bin/env python3
"""Bounded live failover client: verify acknowledged commits survive disruption."""
import argparse
import json
from pathlib import Path
import time
import uuid
import yaml
import psycopg2
from ansible.parsing.vault import VaultLib, VaultSecret

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-dir', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True, help='Explicit environment policy YAML (cluster and application_databases)')
    parser.add_argument('--duration', type=int, default=120)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.duration <= 600:
        parser.error('Use a bounded 10–600 second acceptance window.')
    policy = yaml.safe_load(args.policy.read_text())
    cluster = policy['cluster']
    password = (args.private_dir / 'vault-password').read_bytes()
    vault = VaultLib([('default', VaultSecret(password))])
    credentials = yaml.safe_load(vault.decrypt((args.private_dir / 'secrets.vault.yml').read_bytes()))
    database = policy['application_databases'][0]
    account = next(u for u in credentials['vault_app_users'] if u['name'] == database['owner'])
    parameters = dict(host=cluster['vip_dns_name'], hostaddr=cluster['vip'],
                      port=cluster['ports']['write'], dbname=database['name'],
                      user=account['name'], password=account['password'],
                      sslmode='verify-full', sslrootcert=str(args.private_dir / 'database-ca.pem'),
                      connect_timeout=3)
    with psycopg2.connect(**parameters) as connection:
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS public.pg_ha_failover_acceptance (run_id uuid, sequence integer, PRIMARY KEY(run_id, sequence))')
    run_id = str(uuid.uuid4())
    start = time.monotonic()
    acknowledged, failures = [], 0
    outage_start, maximum_outage = None, 0.0
    print('Acceptance client ready; testing committed writes through the verified TLS VIP.', flush=True)
    sequence = 0
    while time.monotonic() - start < args.duration:
        sequence += 1
        attempted_at = time.monotonic()
        try:
            with psycopg2.connect(**parameters) as connection:
                with connection.cursor() as cursor:
                    cursor.execute('SET statement_timeout=3000')
                    cursor.execute('INSERT INTO public.pg_ha_failover_acceptance VALUES (%s,%s)', (run_id, sequence))
            acknowledged.append(sequence)  # Only after successful COMMIT acknowledgement.
            if outage_start is not None:
                maximum_outage = max(maximum_outage, time.monotonic() - outage_start)
                outage_start = None
        except psycopg2.Error:
            failures += 1
            if outage_start is None:
                outage_start = attempted_at
        time.sleep(0.25)
    if outage_start is not None:
        maximum_outage = max(maximum_outage, time.monotonic() - outage_start)
    with psycopg2.connect(**parameters) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT sequence FROM public.pg_ha_failover_acceptance WHERE run_id=%s', (run_id,))
            persisted = {row[0] for row in cursor.fetchall()}
    lost = sorted(set(acknowledged) - persisted)
    result = {'run_id': run_id, 'acknowledged_commits': len(acknowledged), 'failed_attempts': failures,
              'lost_acknowledged_commits': lost, 'maximum_observed_outage_seconds': round(maximum_outage, 3),
              'duration_seconds': round(time.monotonic() - start, 3)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    if lost or not acknowledged:
        raise SystemExit('Acceptance failed: missing acknowledged commits or no committed writes.')


if __name__ == '__main__':
    main()
