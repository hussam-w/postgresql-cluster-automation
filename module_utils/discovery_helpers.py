"""Allowlist-only parsers for infrastructure discovery; no configuration dumps."""
import re

COMPONENT = re.compile(r'(postgres|patroni|etcd|haproxy|pgbouncer|keepalived|pg-ha)', re.I)
SSH_FIELDS = {
    'permitrootlogin', 'passwordauthentication', 'pubkeyauthentication',
    'kbdinteractiveauthentication', 'authenticationmethods', 'usepam',
    'allowusers', 'allowgroups', 'denyusers', 'denygroups', 'maxauthtries',
    'maxsessions', 'loglevel', 'port', 'listenaddress',
}
CONTROL_FIELDS = {
    'Database system identifier', 'Database cluster state',
    "Latest checkpoint's TimeLineID", "Latest checkpoint's REDO location",
}


def selected_settings(text, allowed, separator=' '):
    result = {}
    for line in text.splitlines():
        key, found, value = line.partition(separator)
        if found and key.strip() in allowed:
            result[key.strip()] = value.strip()
    return result


def relevant_packages(text):
    result = []
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) == 2 and COMPONENT.search(parts[0]):
            result.append({'name': parts[0], 'version': parts[1]})
    return result


def sanitize_mount_metadata(value):
    """Retain topology while removing possible credentials embedded in mount metadata."""
    if isinstance(value, dict):
        return {key: sanitize_mount_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_mount_metadata(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r'(?i)\b(password|passwd|pass|token|secret|credentials|key)=([^,\s]+)',
                       r'\1=[REDACTED]', value)
        return re.sub(r'(//)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', value)
    return value


def existing_state_detected(packages, units, configurations, markers):
    return bool(packages or units or any(item.get('exists') for item in configurations) or markers)
