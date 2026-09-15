#!/usr/bin/env python3
"""Collect public SSH identities without authenticating or trusting new keys."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--inventory', type=Path, required=True, help='Explicit discovery inventory with target_vms')
    args = parser.parse_args()
    inventory = yaml.safe_load(args.inventory.read_text())
    hosts = inventory['all']['children']['target_vms']['hosts']
    def scan(item):
        label, host = item
        ip = host['management_ip']
        result = subprocess.run(['ssh-keyscan', '-T', '5', '-p', str(args.port), '-t', 'ed25519', ip],
                                capture_output=True, text=True, timeout=10)
        lines = [line for line in result.stdout.splitlines() if len(line.split()) == 3 and line.split()[1] == 'ssh-ed25519']
        if len(lines) != 1:
            return {'target': label, 'address': ip, 'status': 'identity_unavailable'}, ''
        identity = subprocess.run(['ssh-keygen', '-lf', '-'], input=lines[0] + '\n',
                                  capture_output=True, text=True, check=True)
        return {'target': label, 'address': ip, 'port': args.port,
                'fingerprint': identity.stdout.split()[1], 'status': 'observed_not_trusted'}, lines[0]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(scan, hosts.items()))
    output = ROOT / 'artifacts/discovery'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate = output / 'known_hosts.candidate'
    candidate.write_text(''.join(line + '\n' for _, line in results if line))
    os.chmod(candidate, 0o600)
    report = {'authenticated': False, 'host_keys_trusted': False, 'observations': [record for record, _ in results]}
    (output / 'ssh-identities.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
