#!/usr/bin/env python3
"""Reissue selected service leaves for migrated IPs, preserving CA and keys."""
import datetime
import argparse
import ipaddress
import os
import json
import re
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--services', nargs='+', default=['etcd', 'dcs'], choices=['etcd', 'dcs', 'postgres', 'pgbouncer', 'patroni', 'haproxy', 'backup'])
    parser.add_argument('--private-dir', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--mapping', type=Path, required=True, help='JSON nodes mapping with old/new IPv4 addresses')
    args = parser.parse_args()
    services = args.services
    private = args.private_dir.expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    nodes = json.loads(args.mapping.read_text())['nodes']
    for name, values in nodes.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
            raise ValueError('Invalid node filename identity')
        ipaddress.IPv4Address(values['old'])
        ipaddress.IPv4Address(values['new'])
    os.umask(0o077)
    destination.mkdir(mode=0o700, exist_ok=True)
    password = (private / 'vault-password').read_bytes()
    domains = {'etcd': 'dcs', 'dcs': 'dcs', 'postgres': 'database', 'pgbouncer': 'database', 'patroni': 'management', 'haproxy': 'management', 'backup': 'backup'}
    old_ips = {name: values['old'] for name, values in nodes.items()}
    for name, values in nodes.items():
        address = values['new']
        for service in services:
            ca_key = serialization.load_pem_private_key((private / (domains[service] + '-ca.key')).read_bytes(), password)
            target = destination / f'{name}-{service}.pem'
            if target.exists():
                raise RuntimeError('Existing candidate certificate; inspect instead of replacing')
            original = x509.load_pem_x509_certificate((private / f'{name}-{service}.pem').read_bytes())
            builder = (x509.CertificateBuilder().subject_name(original.subject).issuer_name(original.issuer)
                       .public_key(original.public_key()).serial_number(x509.random_serial_number())
                       .not_valid_before(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=5))
                       .not_valid_after(original.not_valid_after.replace(tzinfo=datetime.timezone.utc)))
            for extension in original.extensions:
                value = extension.value
                if isinstance(value, x509.SubjectAlternativeName):
                    value = x509.SubjectAlternativeName([v for v in value if not (isinstance(v, x509.IPAddress) and str(v.value) == old_ips[name])] + [x509.IPAddress(ipaddress.ip_address(address))])
                builder = builder.add_extension(value, extension.critical)
            target.write_bytes(builder.sign(ca_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))
            target.chmod(0o600)
    print('Selected public leaf certificates staged; original certificates, keys, VIP SANs and CAs retained.')

if __name__ == '__main__':
    main()
