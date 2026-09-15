#!/usr/bin/python3
"""Conservative offline validation for services without a native dry-run option.

This does not replace a real startup and authenticated functional health check.
Never print configuration contents because they may contain credentials.
"""
import configparser
import sys
import yaml


def main(kind, path):
    if kind == 'etcd':
        with open(path, encoding='utf-8') as stream:
            value = yaml.safe_load(stream)
        assert value['initial-cluster-state'] == 'new'
        assert len(value['initial-cluster'].split(',')) in (1, 3, 5)
        for key in ['listen-peer-urls', 'listen-client-urls', 'advertise-client-urls', 'initial-advertise-peer-urls']:
            assert value[key].startswith('https://')
        assert value['client-transport-security']['client-cert-auth'] is True
        assert value['peer-transport-security']['client-cert-auth'] is True
    elif kind == 'pgbouncer':
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        assert parser.read(path)
        pool = parser['pgbouncer']
        assert pool['auth_type'] == 'scram-sha-256'
        assert pool['client_tls_sslmode'] == 'require'
        assert pool['server_tls_sslmode'] == 'verify-full'
        assert pool['pool_mode'] in ['session', 'transaction']
        assert len(parser['databases']) > 0
        assert '*' not in parser['databases']
    else:
        raise ValueError('Unknown validator')


if __name__ == '__main__':
    try:
        main(*sys.argv[1:])
    except Exception:
        sys.exit('Candidate configuration rejected; review privately')
