"""Shared port contract and stable firewall-policy fingerprinting."""
import hashlib
import json

DEFAULT_PORTS = {'postgres': 5432, 'pgbouncer': 6432, 'patroni': 8008,
                 'etcd_client': 2379, 'etcd_peer': 2380, 'write': 5000, 'read': 5001}


def resolve_ports(overrides=None):
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict) or set(overrides) - set(DEFAULT_PORTS):
        raise ValueError('cluster.ports contains unsupported keys or is not a mapping')
    ports = dict(DEFAULT_PORTS, **overrides)
    if any(type(value) is not int or not 1024 <= value <= 65535 for value in ports.values()):
        raise ValueError('All service ports must be integers in 1024..65535')
    if len(set(ports.values())) != len(ports):
        raise ValueError('Service ports must be distinct on co-located nodes')
    return ports


def normalize_nft(value):
    if isinstance(value, list):
        return [normalize_nft(item) for item in value if not (isinstance(item, dict) and 'metainfo' in item)]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == 'handle':
                continue
            if key == 'counter' and isinstance(item, dict):
                result[key] = {field: (0 if field in ['packets', 'bytes'] else normalize_nft(data)) for field, data in item.items()}
            else:
                result[key] = normalize_nft(item)
        return result
    return value


def nft_fingerprint(value):
    return hashlib.sha256(json.dumps(normalize_nft(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def nft_has_filter_rules(value):
    entries = value.get('nftables', []) if isinstance(value, dict) else []
    return any('rule' in item for item in entries) and any(
        item.get('chain', {}).get('hook') == 'input' for item in entries)
