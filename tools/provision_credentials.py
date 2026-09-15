#!/usr/bin/env python3
"""Create separate internal trust domains and encrypted automation secrets on Linux.

No SSH credential is accepted or stored. Keep the private directory on a native
Linux filesystem, back it up encrypted, and restrict the controller account.
Existing key material is never replaced implicitly.
"""
import argparse
import datetime as dt
import ipaddress
import os
from pathlib import Path
import secrets
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from ansible.parsing.vault import VaultLib, VaultSecret

ROOT = Path(__file__).resolve().parents[1]


def put(path, data):
    with path.open('xb') as stream:
        stream.write(data)
    path.chmod(0o600)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--private-dir', type=Path, required=True)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--vip')
    p.add_argument('--vip-dns')
    p.add_argument('--direct', action='store_true', help='Node-only database TLS identities; HAProxy/VIP disabled')
    args = p.parse_args()
    if not args.direct and (not args.vip or not args.vip_dns):
        p.error('VIP and VIP DNS are required unless --direct is selected')
    private = args.private_dir.resolve()
    if os.name != 'posix' or str(private).startswith('/mnt/'):
        p.error('Use a protected native Linux filesystem for private key material.')
    os.umask(0o077)
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    if private.stat().st_mode & 0o077 or private.stat().st_uid != os.getuid():
        p.error('Private directory must be owned by the controller user with mode 0700.')
    password_path = private / 'vault-password'
    if not password_path.exists():
        put(password_path, secrets.token_urlsafe(48).encode())
    password = password_path.read_bytes()
    hosts = yaml.safe_load(args.inventory.read_text())['all']['children']['postgres_cluster']['hosts']
    now = dt.datetime.now(dt.timezone.utc)
    roots = {}
    for domain in ['database', 'management', 'dcs', 'backup']:
        keypath, certpath = private / (domain + '-ca.key'), private / (domain + '-ca.pem')
        if keypath.exists() != certpath.exists():
            raise RuntimeError('Incomplete CA creation; inspect protected directory before resuming.')
        if keypath.exists():
            key = serialization.load_pem_private_key(keypath.read_bytes(), password)
            cert = x509.load_pem_x509_certificate(certpath.read_bytes())
        else:
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PG HA ' + domain + ' root')])
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=3650))
                    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                    .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
                    .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                    .sign(key, hashes.SHA256()))
            put(keypath, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password)))
            put(certpath, cert.public_bytes(serialization.Encoding.PEM))
        roots[domain] = (key, cert, certpath)
    for name, host in hosts.items():
        mappings = {}
        for service, domain in {'postgres': 'database', 'pgbouncer': 'database', 'patroni': 'management', 'haproxy': 'management', 'etcd': 'dcs', 'dcs': 'dcs', 'backup': 'backup'}.items():
            ca_key, ca_cert, ca_path = roots[domain]
            keypath, certpath = private / f'{name}-{service}.key', private / f'{name}-{service}.pem'
            if keypath.exists() != certpath.exists():
                raise RuntimeError('Incomplete leaf creation; inspect protected directory before resuming.')
            if not keypath.exists():
                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                sans = [x509.DNSName(host['node']['dns_name']), x509.IPAddress(ipaddress.ip_address(host['node']['address']))]
                if service == 'pgbouncer' and not args.direct:
                    sans += [x509.DNSName(args.vip_dns), x509.IPAddress(ipaddress.ip_address(args.vip))]
                subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name if service == 'backup' else name + '-' + service)])
                usages = [ExtendedKeyUsageOID.CLIENT_AUTH] if service in ['dcs', 'haproxy'] else [ExtendedKeyUsageOID.SERVER_AUTH]
                if service in ['etcd', 'patroni', 'backup']:
                    usages.append(ExtendedKeyUsageOID.CLIENT_AUTH)
                cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_cert.subject)
                        .public_key(key.public_key()).serial_number(x509.random_serial_number())
                        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=365))
                        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                        .add_extension(x509.ExtendedKeyUsage(usages), critical=False)
                        .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
                        .sign(ca_key, hashes.SHA256()))
                put(keypath, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
                put(certpath, cert.public_bytes(serialization.Encoding.PEM))
            mappings[service] = {'ca': str(ca_path), 'cert': str(certpath), 'key': str(keypath)}
        target = args.inventory.parent / 'host_vars' / name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'tls.yml').write_text(yaml.safe_dump({'tls_sources': mappings}, sort_keys=False))
    vault = private / 'secrets.vault.yml'
    if not vault.exists():
        values = {key: secrets.token_urlsafe(48) for key in ['vault_pg_superuser_password', 'vault_pg_replication_password', 'vault_patroni_api_password', 'vault_backup_cipher_pass']}
        values['vault_app_users'] = [{'name': 'app_owner', 'password': secrets.token_urlsafe(48)}]
        lib = VaultLib([('default', VaultSecret(password))])
        put(vault, lib.encrypt(yaml.safe_dump(values).encode()))
    print('Protected credentials provisioned; existing credentials retained. No secret values displayed.')


if __name__ == '__main__':
    main()
