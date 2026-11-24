"""Regression test: route by thread ID regardless of client label."""
from contextlib import ExitStack
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bindings import Bindings
from relay import Relay


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.seen.append((self.headers.get('thread-id'), self.headers.get('originator'), self.headers.get('Authorization')))
        body = json.dumps({'id': 'fixture', 'object': 'response', 'status': 'completed', 'output': []}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(server, stack):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stack.callback(server.server_close)
    stack.callback(server.shutdown)


def request(port, secret, headers):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        conn.request('POST', '/v1/responses', body=b'{}', headers={
            'Content-Type': 'application/json',
            'X-Thread-Provider-Card': secret,
            **headers,
        })
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def main():
    with tempfile.TemporaryDirectory(prefix='thread-provider-route-') as temp, ExitStack() as stack:
        home = Path(temp)
        default = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        default.seen = []
        custom = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        custom.seen = []
        serve(default, stack); serve(custom, stack)
        (home / 'config.toml').write_text(f'''model_provider = "fixture"
[model_providers.fixture]
name = "Fixture"
base_url = "http://127.0.0.1:{default.server_port}/v1"
wire_api = "responses"
experimental_bearer_token = "default-key"
requires_openai_auth = false
''', encoding='utf-8')
        bindings = Bindings('ThreadProviderCard/TestRoute/' + uuid.uuid4().hex + '/')
        relay = Relay(home, bindings)
        stack.callback(relay.server_close)
        thread = str(uuid.uuid4())
        bindings.save(thread, f'http://127.0.0.1:{custom.server_port}/v1', 'custom-key')
        stack.callback(bindings.clear, thread)
        relay.start()
        stack.callback(relay.shutdown)
        assert request(relay.server_port, relay.secret, {'thread-id': thread, 'originator': 'codex_vscode'})[0] == 200
        assert request(relay.server_port, relay.secret, {'thread-id': thread, 'originator': 'codex_desktop'})[0] == 200
        assert request(relay.server_port, relay.secret, {'thread-id': thread, 'originator': 'codex_cli_rs'})[0] == 200
        assert len(default.seen) == 0, default.seen
        assert len(custom.seen) == 3, custom.seen
        assert all(item[0] == thread and item[2] == 'Bearer custom-key' for item in custom.seen)
        print('PASS: one bound thread routes through the custom provider for App, VS Code, and CLI labels.')


if __name__ == '__main__':
    main()
