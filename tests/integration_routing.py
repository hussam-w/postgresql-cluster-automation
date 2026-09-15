"""Isolated HAProxy behavior test. Simulated HTTPS Patroni + TCP pool listeners.

No PostgreSQL, etcd or VIP is deployed. Does not certify SQL or HA failover.
"""
import csv
import http.server
import importlib.util
import io
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from fixture import ROOT
from render_templates import render

spec = importlib.util.spec_from_file_location('vip', ROOT / 'roles/routing/files/check_vip.py')
vip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vip)


class Pool(socketserver.BaseRequestHandler):
    def handle(self):
        pass


class Api(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        valid = (self.path == '/primary' and self.server.role == 'primary') or (self.path.startswith('/replica?lag=') and self.server.role == 'replica')
        self.send_response(200 if valid else 503)
        self.end_headers()

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as stream:
        stream.bind(('127.0.0.1', 0))
        return stream.getsockname()[1]


def stats(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(1)
        stream.connect(str(path))
        stream.sendall(b'show stat\n')
        stream.shutdown(socket.SHUT_WR)
        result = b''
        while chunk := stream.recv(65536):
            result += chunk
    return result.decode()


def eventually(predicate, label):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if predicate():
                print('PASS: ' + label)
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise AssertionError(label)


def main():
    with tempfile.TemporaryDirectory(prefix='pg-ha-routing-') as directory:
        out = Path(directory)
        render(out)
        cert, key = out / 'test.crt', out / 'test.key'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-subj', '/CN=pg1.example.test', '-addext',
                        'subjectAltName=DNS:pg1.example.test,DNS:pg2.example.test,DNS:pg3.example.test',
                        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
        bundle = out / 'client.pem'
        bundle.write_text(cert.read_text() + key.read_text())
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        context.load_verify_locations(cert)
        context.verify_mode = ssl.CERT_REQUIRED
        api_port, pool_port, write_port, read_port = [free_port() for _ in range(4)]
        apis, pools, process = [], [], None
        try:
            for index in range(1, 4):
                address = f'127.0.0.{index}'
                api = http.server.ThreadingHTTPServer((address, api_port), Api)
                api.role = 'primary' if index == 1 else 'replica'
                api.socket = context.wrap_socket(api.socket, server_side=True)
                apis.append(api)
                pool = socketserver.ThreadingTCPServer((address, pool_port), Pool)
                pools.append(pool)
                for server in [api, pool]:
                    threading.Thread(target=server.serve_forever, daemon=True).start()
            config = (out / 'haproxy.cfg').read_text()
            for index in range(1, 4):
                config = config.replace(f'192.0.2.{20+index}', f'127.0.0.{index}')
            for before, after in [('/etc/pg-ha/haproxy/ca.pem', str(cert)),
                                  ('/etc/pg-ha/haproxy/client.pem', str(bundle)),
                                  ('/run/pg-ha-haproxy/admin.sock', str(out / 'admin.sock')),
                                  ('port 8008', f'port {api_port}'),
                                  ('port 6432', f'port {pool_port}'),
                                  (':6432', f':{pool_port}'),
                                  ('0.0.0.0:5000', f'127.0.0.1:{write_port}'),
                                  ('0.0.0.0:5001', f'127.0.0.1:{read_port}'),
                                  ('    user haproxy\n', ''), ('    group haproxy\n', '')]:
                config = config.replace(before, after)
            path = out / 'haproxy.cfg'
            path.write_text(config)
            with (out / 'haproxy.log').open('w+') as log:
                process = subprocess.Popen(['/usr/sbin/haproxy', '-db', '-f', str(path)], stdout=log, stderr=log)
                try:
                    snapshot = lambda: stats(out / 'admin.sock')
                    eventually(lambda: vip.usable(snapshot()), 'verified mTLS primary + replicas become usable')
                    pools[0].shutdown()
                    pools[0].server_close()
                    eventually(lambda: not vip.usable(snapshot()), 'pool listener loss blocks VIP eligibility despite healthy primary API')
                    pools[0] = socketserver.ThreadingTCPServer(('127.0.0.1', pool_port), Pool)
                    threading.Thread(target=pools[0].serve_forever, daemon=True).start()
                    eventually(lambda: vip.usable(snapshot()), 'pool listener recovery restores eligibility')
                    apis[1].role = 'primary'
                    eventually(lambda: not vip.usable(snapshot()), 'two reported primaries fail VIP single-primary gate')
                    apis[0].role = 'replica'
                    eventually(lambda: vip.usable(snapshot()), 'role change leaves one primary and usable replicas')
                except Exception:
                    log.flush()
                    log.seek(0)
                    print(log.read()[-4000:])
                    print(stats(out / 'admin.sock')[-4000:])
                    raise
        finally:
            if process is not None:
                process.terminate()
                process.wait(timeout=10)
            for server in apis + pools:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()
