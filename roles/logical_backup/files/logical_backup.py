#!/usr/bin/python3
"""Primary-only logical backups. Exclusive new outputs; never expires or deletes data."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def connection(config, database):
    def quote(value):
        return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"
    return ' '.join(key + '=' + quote(value) for key, value in {
        'host': config['socket'], 'port': config['port'], 'dbname': database,
        'user': 'postgres', 'connect_timeout': 10}.items())


def run(config):
    os.umask(0o077)
    root = Path(config['target'])
    binaries = Path('/usr/lib/postgresql') / config['major'] / 'bin'
    environment = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'PGAPPNAME': 'pg-ha-logical-backup'}
    def command(name, args):
        result = subprocess.run([str(binaries / name)] + args, env=environment,
                                capture_output=True, text=True, timeout=3600)
        if result.returncode:
            raise RuntimeError(name + ' failed; partial backup retained for diagnosis')
        return result.stdout
    def query(sql):
        return json.loads(command('psql', ['-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                          '--dbname=' + connection(config, 'postgres'), '-c', sql]))
    with (root / '.logical-backup.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Backup already running; skipped')
            return
        identity_sql = "SELECT json_build_object('id', system_identifier::text, 'recovery', pg_is_in_recovery(), 'started', pg_postmaster_start_time(), 'major', current_setting('server_version_num')::int / 10000) FROM pg_control_system()"
        identity = query(identity_sql)
        if identity['recovery']:
            print('Replica detected; primary-only backup skipped')
            return
        if str(identity['major']) != config['major'] or identity['id'] != config['system_id']:
            raise RuntimeError('Server major or system identifier differs; no backup started')
        database_sql = "SELECT coalesce(json_agg(datname ORDER BY datname),'[]'::json) FROM pg_database WHERE datallowconn AND NOT datistemplate"
        databases = query(database_sql)
        identifier = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
        staging = root / (identifier + '.partial')
        staging.mkdir(mode=0o700)
        command('pg_dumpall', ['--globals-only', '--dbname=' + connection(config, 'postgres'), '--file=' + str(staging / 'globals.sql')])
        manifest = {'identity': identity, 'format': 'logical-per-database', 'databases': {}, 'sha256': {}}
        for database in databases:
            filename = hashlib.sha256(database.encode()).hexdigest() + '.dump'
            command('pg_dump', ['--format=custom', '--create', '--dbname=' + connection(config, database), '--file=' + str(staging / filename)])
            command('pg_restore', ['--list', str(staging / filename)])
            manifest['databases'][database] = filename
        if query(identity_sql) != identity or query(database_sql) != databases:
            raise RuntimeError('Server identity/start/role changed during backup; partial result retained')
        for path in staging.iterdir():
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
                os.fsync(stream.fileno())
            manifest['sha256'][path.name] = digest.hexdigest()
        with (staging / 'manifest.json').open('x') as stream:
            json.dump(manifest, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        staging.rename(root / identifier)
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        print('Logical backup completed and checksummed: ' + identifier)


if __name__ == '__main__':
    try:
        run(json.loads(Path(sys.argv[1]).read_text()))
    except Exception as error:
        print('Backup failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
