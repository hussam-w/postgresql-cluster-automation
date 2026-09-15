"""Bounded local psql transport without a shell, startup files or inherited secrets."""
import json
import os
import pwd
import shutil
import subprocess


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def identifier(value):
    return '"' + str(value).replace('"', '""') + '"'


class LocalPostgres:
    def __init__(self, socket_dir, port, owner='postgres'):
        if not socket_dir.startswith('/') or not 1 <= port <= 65535:
            raise ValueError('A local absolute Unix socket directory and valid port are required')
        psql = shutil.which('psql')
        if not psql:
            raise ValueError('psql is not installed; no package installation was attempted')
        account = pwd.getpwnam(owner)
        prefix = []
        if os.geteuid() != account.pw_uid:
            if os.geteuid() != 0:
                raise ValueError('Run as the database owner or use approved sudo')
            prefix = [shutil.which('runuser') or '/usr/sbin/runuser', '-u', owner, '--']
        self.argv = prefix + [psql, '-X', '-A', '-t', '-w', '-v', 'ON_ERROR_STOP=1',
                              '-h', socket_dir, '-p', str(port), '-U', owner]

    def sql(self, statement, database='postgres'):
        connection = "dbname='" + database.replace('\\', '\\\\').replace("'", "\\'") + "'"
        result = subprocess.run(self.argv + ['-d', connection], input=statement, capture_output=True,
                                text=True, timeout=60, env={
                                    'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C',
                                    'PGCONNECT_TIMEOUT': '5', 'PGAPPNAME': 'pg-ha-extensions',
                                    'PGOPTIONS': '-c statement_timeout=30000 -c lock_timeout=3000 -c search_path=pg_catalog'})
        if result.returncode:
            raise ValueError('SQL validation/change failed; inspect protected PostgreSQL logs. No unsafe retry was attempted')
        return result.stdout.strip()

    def query(self, statement, database='postgres'):
        return json.loads(self.sql(statement, database))
