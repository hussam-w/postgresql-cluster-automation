#!/usr/bin/python
"""Use OpenSSL for cryptographic key/cert and trust-boundary validation."""
import hashlib
import subprocess
from pathlib import Path
from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(argument_spec={'core': {'type': 'bool', 'required': True}, 'router': {'type': 'bool', 'default': None}}, supports_check_mode=True)
    router = module.params['core'] if module.params['router'] is None else module.params['router']
    names = ['postgres', 'patroni', 'dcs', 'pgbouncer'] + (['etcd'] if module.params['core'] else []) + (['haproxy'] if router else [])
    def openssl(args):
        result = subprocess.run(['/usr/bin/openssl'] + args, capture_output=True, timeout=15)
        if result.returncode:
            module.fail_json(msg='TLS cryptographic validation failed; inspect certificate/key material privately')
        return result.stdout
    trust = {}
    for name in names:
        path = '/etc/pg-ha/' + name + '/'
        public_cert = openssl(['x509', '-in', path + 'cert.pem', '-pubkey', '-noout'])
        public_key = openssl(['pkey', '-in', path + 'key.pem', '-pubout'])
        if public_cert != public_key:
            module.fail_json(msg='TLS certificate and private key do not match for ' + name)
        openssl(['x509', '-in', path + 'cert.pem', '-checkend', '2592000', '-noout'])
        if Path(path + 'ca.pem').read_text().count('-----BEGIN CERTIFICATE-----') != 1:
            module.fail_json(msg='Use one dedicated root CA per trust domain; intermediate chains belong in cert.pem')
        trust[name] = hashlib.sha256(openssl(['x509', '-in', path + 'ca.pem', '-outform', 'DER'])).hexdigest()
        if name in ['etcd', 'patroni', 'dcs', 'haproxy']:
            openssl(['verify', '-CAfile', path + 'ca.pem', '-untrusted', path + 'cert.pem', '-purpose', 'sslclient', path + 'cert.pem'])
        if name not in ['dcs', 'haproxy']:
            openssl(['verify', '-CAfile', path + 'ca.pem', '-untrusted', path + 'cert.pem', '-purpose', 'sslserver', path + 'cert.pem'])
    if len({trust['postgres'], trust['patroni'], trust['dcs']}) != 3:
        module.fail_json(msg='Database, Patroni management, and DCS require separate issuing CA bundles')
    if trust['pgbouncer'] != trust['postgres']:
        module.fail_json(msg='Pooler and PostgreSQL must use the declared database CA bundle')
    if (module.params['core'] and trust['etcd'] != trust['dcs']) or (router and trust['haproxy'] != trust['patroni']):
        module.fail_json(msg='DCS and HAProxy client trust bundles must match their respective servers')
    module.exit_json(changed=False)


if __name__ == '__main__':
    main()
