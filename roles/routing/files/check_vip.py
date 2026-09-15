#!/usr/bin/python3
"""Exit zero only when HAProxy has one write backend and at least one replica.

Root-owned script and root-only socket. No shell, credentials or writable search
path. Keepalived tracks failure as FAULT (weight zero), not a soft priority loss.
"""
import csv
import io
import socket
import sys
import json
from pathlib import Path


def usable(text, require_replicas=True):
    if not text.startswith('# '):
        return False
    rows = list(csv.DictReader(io.StringIO(text[2:])))
    def count(backend):
        return sum(row.get('pxname') == backend and row.get('svname') not in ['BACKEND', 'FRONTEND']
                   and row.get('status') == 'UP' for row in rows)
    opened = {r.get('pxname') for r in rows if r.get('svname') == 'FRONTEND' and r.get('status') == 'OPEN'}
    return count('primary') == 1 and 'postgres_write' in opened and (not require_replicas or (count('replicas') >= 1 and 'postgres_read' in opened))


def main():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(1)
        stream.connect('/run/pg-ha-haproxy/admin.sock')
        stream.sendall(b'show stat\n')
        stream.shutdown(socket.SHUT_WR)
        chunks, size = [], 0
        while True:
            data = stream.recv(65536)
            if not data:
                break
            size += len(data)
            if size > 1024 * 1024:
                return False
            chunks.append(data)
    policy = Path('/etc/pg-ha/routing.json')
    require_replicas = json.loads(policy.read_text())['require_replicas'] if policy.exists() else True
    if type(require_replicas) is not bool:
        return False
    return usable(b''.join(chunks).decode('utf-8'), require_replicas)


if __name__ == '__main__':
    try:
        sys.exit(0 if main() else 1)
    except (OSError, ValueError, UnicodeError, csv.Error):
        sys.exit(1)
