"""Linux-only native parser validation using disposable synthetic certificates.

Runs no system service and writes only under ignored artifacts/. Does not prove
cluster startup, networking, fencing, replication, failover or recovery.
"""
from pathlib import Path
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from fixture import ROOT
from render_templates import render


def run(argv):
    result = subprocess.run(argv, text=True, capture_output=True)
    if result.returncode:
        print(result.stdout + result.stderr)
        raise SystemExit(result.returncode)
    print('PASS: ' + ' '.join(argv[:2]))


def validate(out):
    render(out)
    cert, key = out / 'test.crt', out / 'test.key'
    run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
         '-subj', '/CN=pg1.example.test', '-keyout', str(key), '-out', str(cert)])
    bundle = out / 'test.pem'
    bundle.write_text(cert.read_text() + key.read_text())
    hap = out / 'haproxy.cfg'
    text = hap.read_text().replace('/etc/pg-ha/haproxy/ca.pem', str(cert)).replace('/etc/pg-ha/haproxy/client.pem', str(bundle))
    text = text.replace('/run/pg-ha-haproxy/admin.sock', str(out / 'admin.sock'))
    hap.write_text(text)
    run(['/usr/sbin/haproxy', '-c', '-f', str(hap)])
    keep = out / 'keepalived.conf'
    script = out / 'check-vip'
    shutil.copyfile(ROOT / 'roles/routing/files/check_vip.py', script)
    script.chmod(0o755)
    # A user-owned temporary script must not be configured to execute as root.
    # This parser fixture uses its actual owner; production retains script_user root.
    keep.write_text(keep.read_text().replace('/usr/local/libexec/pg-ha/check-vip', str(script))
                    .replace('script_user root', 'script_user ' + pwd.getpwuid(os.geteuid()).pw_name))
    run(['/usr/sbin/keepalived', '--config-test', '-f', str(keep)])
    for kind, name in [('etcd', 'etcd.yml'), ('pgbouncer', 'pgbouncer.ini')]:
        run([sys.executable, str(ROOT / 'roles/prepare/files/validate_config.py'), kind, str(out / name)])


def main():
    with tempfile.TemporaryDirectory(prefix='pg-ha-validate-') as directory:
        validate(Path(directory))


if __name__ == '__main__':
    main()
