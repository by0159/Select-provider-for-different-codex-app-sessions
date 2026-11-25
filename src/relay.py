"""HTTP/SSE transport for the lifetime of one Codex app-server child."""
import hmac
import http.client
import http.server
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import tomllib
from urllib.parse import urlsplit
from bindings import Bindings, address, route_id
from speed import BODY_LIMIT, SpeedPayloadError, SpeedStore, prepare, shared_tier

AUTH = 'X-Thread-Provider-Card'
SAFE = {'content-type', 'accept', 'user-agent', 'openai-beta'}
META = {'thread-id', 'thread_id', 'session-id', 'session_id', 'x-codex-thread-id', 'x-codex-session-id', 'originator', 'x-codex-beta-features'}
RESERVED = {'authorization', 'host', 'connection', 'content-length', 'transfer-encoding', 'accept-encoding', 'proxy-authorization', AUTH.lower()}


def configuration(home):
    cfg = tomllib.loads((home / 'config.toml').read_text(encoding='utf-8-sig'))
    name = cfg.get('model_provider')
    provider = cfg.get('model_providers', {}).get(name, {})
    if not name or not re.fullmatch(r'[a-zA-Z0-9_-]+', name) or provider.get('wire_api', 'responses') != 'responses':
        raise ValueError('Configure a named Responses API provider first.')
    if provider.get('requires_openai_auth') or provider.get('query_params') or provider.get('auth'):
        raise ValueError('This release supports Bearer API key providers without URL query parameters.')
    key = provider.get('experimental_bearer_token') or os.environ.get(provider.get('env_key', ''))
    if not key:
        raise ValueError('The configured Responses provider needs an API key or env_key.')
    url = address(provider.get('base_url'))
    hdr = dict(provider.get('http_headers') or {})
    hdr.update({k: os.environ[v] for k,v in (provider.get('env_http_headers') or {}).items() if v in os.environ})
    return name, url, key, {k:v for k,v in hdr.items() if k.lower() not in RESERVED}, shared_tier(cfg)


def origin(url):
    u = urlsplit(url)
    return u.scheme, u.hostname, u.port or (443 if u.scheme=='https' else 80)


class Relay(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, home, bindings=None):
        self.home = home
        self.provider = configuration(home)[0]
        self.bindings = bindings or Bindings()
        self.speed = SpeedStore(home)
        self.secret = secrets.token_hex(32)
        super().__init__(('127.0.0.1', 0), Handler)

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def fail(self, status, text):
        raw = json.dumps({'error': {'message': text, 'type': 'thread_provider_card'}}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(raw)

    def relay(self):
        self.close_connection = True
        if not hmac.compare_digest(self.headers.get(AUTH, ''), self.server.secret):
            return self.fail(401, 'Local relay authorization required.')
        if self.path not in ('/v1/responses','/v1/responses/compact','/v1/models'):
            return self.fail(404, 'Unsupported Responses API path.')
        if self.headers.get('Transfer-Encoding'):
            return self.fail(411, 'Content-Length required.')
        connection = None
        started = False
        try:
            name, url, key, configured, configured_tier = configuration(self.server.home)
            if name != self.server.provider:
                return self.fail(409, 'Default provider changed. Restart Codex to reload.')
            tid = route_id(self.headers)
            if not tid and self.command=='POST':
                return self.fail(400, 'Missing Codex thread ID. Check add-on compatibility.')
            selected = self.server.bindings.get(tid) if tid else None
            if selected:
                target = address(selected['url'])
                if origin(target) != origin(url):
                    configured = {k:v for k,v in configured.items() if k.lower() in SAFE}
                url, key = target, selected['key']
            scheme, host, port = origin(url)
            if host in ('127.0.0.1', 'localhost', '::1') and port == self.server.server_port:
                return self.fail(400, 'Provider URL points back at the relay.')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 <= size <= BODY_LIMIT:
                return self.fail(413, 'Request body is too large.')
            body = self.rfile.read(size) if self.command=='POST' else None
            generation = self.command == 'POST' and self.path == '/v1/responses'
            if generation:
                try:
                    mode = self.server.speed.mode(tid)
                except (sqlite3.Error, OSError):
                    # An unreadable optional store must not stop a running chat.
                    mode = 'inherit'
                body, sent_tier = prepare(body, self.headers.get('Content-Encoding'),
                                          configured_tier if mode == 'inherit' else mode)
            headers = {k:v for k,v in self.headers.items() if k.lower() in SAFE | META | {'content-encoding'}}
            headers.update(configured)
            headers.update(Authorization='Bearer '+key, **{'Accept-Encoding':'identity'})
            factory = http.client.HTTPSConnection if scheme=='https' else http.client.HTTPConnection
            connection = factory(host, port, timeout=30)
            connection.connect()
            connection.sock.settimeout(None)  # Codex owns the configured stream idle deadline.
            if generation: sent = time.time_ns()
            connection.request(self.command, urlsplit(url).path.rstrip('/') + self.path[3:], body=body, headers=headers)
            upstream = connection.getresponse()
            if generation: self.server.speed.record(tid, sent, sent_tier, upstream.status)
            if 300 <= upstream.status < 400:
                return self.fail(502, 'Use the final API URL. Upstream redirects are disabled.')
            started = True
            self.send_response(upstream.status)
            for field in ('Content-Type','Content-Length','Content-Encoding','Retry-After','X-Request-Id','Request-Id'):
                if upstream.getheader(field): self.send_header(field, upstream.getheader(field))
            self.send_header('Connection','close')
            self.end_headers()
            while chunk := upstream.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except SpeedPayloadError as exc:
            if not started: self.fail(exc.status, str(exc))
        except (OSError, TypeError, ValueError, KeyError, http.client.HTTPException):
            if not started: self.fail(502, 'Could not read the provider configuration or reach its endpoint.')
        finally:
            if connection is not None: connection.close()

    do_POST = do_GET = relay
