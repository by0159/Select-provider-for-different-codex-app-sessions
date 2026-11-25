"""Exercise request fidelity, compaction and HTTP errors over the real relay on loopback."""
import gzip
import http.client
import json
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from relay import AUTH, Relay
from speed import SpeedStore


class Endpoint(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        self.server.last = (self.path, self.headers.get('Content-Encoding'), raw)
        self.send_response(self.server.status)
        self.send_header('Retry-After', '17')
        self.end_headers()
        self.wfile.write(b'{}')


class NoBindings:
    def get(self, tid): return None


class SpeedTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack(); self.addCleanup(stack.close)
        self.home = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.up = stack.enter_context(ThreadingHTTPServer(('127.0.0.1', 0), Endpoint))
        self.up.status = 200
        threading.Thread(target=self.up.serve_forever,daemon=True).start();stack.callback(self.up.shutdown)
        self.config = self.home/'config.toml'
        self.config.write_text(f'''model_provider="fixture"
[model_providers.fixture]
base_url="http://127.0.0.1:{self.up.server_port}/v1"
experimental_bearer_token="fixture-only"
''', encoding='utf-8')
        self.relay=stack.enter_context(Relay(self.home, NoBindings()));self.relay.start();stack.callback(self.relay.shutdown)
        self.tid=str(uuid.uuid4());self.speed=SpeedStore(self.home)

    def post(self, path, raw, **headers):
        c=http.client.HTTPConnection('127.0.0.1', self.relay.server_port, timeout=5)
        try:
            c.request('POST', path, raw, {AUTH:self.relay.secret,'Thread-Id':self.tid,'Content-Type':'application/json',**headers})
            r=c.getresponse();return r.status,r.getheader('Retry-After'),r.read()
        finally: c.close()

    def test_gzip_edit_full_history_and_forward_rate_limit(self):
        body={'input':[{'role':'user','content':'你好'}, {'type':'function_call_output','call_id':'call_fixture','output':'example'}],
              'reasoning':{'effort':'high'},'model':'fixture','service_tier':'default','stream':True}
        raw=gzip.compress(json.dumps(body,ensure_ascii=False).encode('utf-8'))
        self.speed.choose(self.tid,'priority');self.up.status=429
        self.assertEqual(self.post('/v1/responses',raw,**{'Content-Encoding':'gzip'}),(429,'17',b'{}'))
        path,enc,sent=self.up.last;self.assertEqual((path,enc),('/v1/responses','gzip'))
        self.assertEqual(json.loads(gzip.decompress(sent)),dict(body,service_tier='priority'))
        receipt=self.speed.snapshot(self.tid);self.assertEqual((receipt['mode'],receipt['lastTier'],receipt['lastStatus']),('priority','priority',429))
        self.assertEqual(self.post('/v1/responses/compact',raw,**{'Content-Encoding':'gzip'})[0],429)
        self.assertEqual(self.up.last,('/v1/responses/compact','gzip',raw))

    def test_inherit_preserves_client_bytes_and_live_config(self):
        raw=b'{ "model": "fixture", "service_tier": "flex", "input": [] }'
        self.assertEqual(self.post('/v1/responses',raw)[0],200);self.assertEqual(self.up.last[2],raw)
        self.config.write_text('service_tier="fast"\n'+self.config.read_text('utf-8'),encoding='utf-8')
        self.assertEqual(self.post('/v1/responses',raw)[0],200);self.assertEqual(json.loads(self.up.last[2])['service_tier'],'priority')

    def test_other_chat_and_older_response_do_not_overwrite_selection_or_receipt(self):
        other=str(uuid.uuid4());self.speed.choose(self.tid,'priority');self.speed.choose(other,'default')
        self.speed.record(self.tid,200,'priority',200);self.speed.record(self.tid,100,'default',503)
        self.speed.choose(self.tid,'inherit');s=SpeedStore(self.home)
        self.assertEqual((s.mode(other),s.mode(self.tid)),('default','inherit'))
        self.assertEqual((s.snapshot(self.tid)['lastTier'],s.snapshot(self.tid)['lastStatus']),('priority',200))


if __name__=='__main__': unittest.main()
