"""Exercise the exact distributable using the registered Store app-server and local fixtures."""
import contextlib
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


class Upstream(BaseHTTPRequestHandler):
    def log_message(self,*args): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.visits.append((self.headers['Thread-Id'], self.headers['Authorization'], self.headers.get('X-Account-Fixture'), body['model'], self.headers.get('X-Thread-Provider-Card')))
        result = dict(id='resp_'+uuid.uuid4().hex, object='response', status='in_progress', created_at=int(time.time()),model=body['model'],output=[])
        item = dict(id='msg_'+uuid.uuid4().hex,type='message',role='assistant',status='completed',content=[dict(type='output_text',text='fixture OK',annotations=[])])
        events = [dict(type='response.created',response=result), dict(type='response.output_item.done',output_index=0,item=item), dict(type='response.completed',response={**result,'status':'completed','output':[item],'usage':dict(input_tokens=10,output_tokens=2,total_tokens=12)})]
        data=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
        self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)


class Client:
    def __init__(self, program, cwd, env):
        self.process = subprocess.Popen([str(program),'app-server'],cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.messages = queue.Queue(); self.index=0
        def reader():
            for line in self.process.stdout: self.messages.put(json.loads(line))
            self.messages.put(None)
        threading.Thread(target=reader, daemon=True).start()

    def send(self,message):
        self.process.stdin.write((json.dumps(message)+'\n').encode()); self.process.stdin.flush()

    def until(self,condition):
        end = time.monotonic()+30
        while True:
            message=self.messages.get(timeout=max(.01,end-time.monotonic()))
            if message is None: raise RuntimeError('app-server closed')
            if condition(message): return message

    def rpc(self, name, params):
        self.index+=1; self.send(dict(id=self.index,method=name,params=params))
        reply=self.until(lambda m:m.get('id')==self.index); assert 'error' not in reply,reply.get('error'); return reply['result']

    def ask(self,tid):
        self.rpc('turn/start',dict(threadId=tid,input=[dict(type='text',text='fixture')]))
        assert self.until(lambda m:m.get('method')=='turn/completed')['params']['turn']['status']=='completed'

    def close(self):
        self.process.stdin.close(); self.process.wait(timeout=25); self.process.stdout.close()


def run():
    with tempfile.TemporaryDirectory(prefix='provider-card-') as name, contextlib.ExitStack() as stack:
        work=Path(name); package=work/'release'; cfg_home=work/'fixture-home'; cfg_home.mkdir(); dest=work/'CodexThreadProviderCard'
        with ZipFile(next((ROOT/'out').glob('*windows-x64.zip'))) as z: z.extractall(package)
        def serve():
            server=ThreadingHTTPServer(('127.0.0.1',0),Upstream); server.visits=[]; threading.Thread(target=server.serve_forever,daemon=True).start();stack.callback(server.server_close);stack.callback(server.shutdown);return server
        first,second=serve(),serve(); model='gpt-6-astra'; cfg=f'''model_provider="fixture"
model="{model}"
approval_policy="never"
sandbox_mode="read-only"
[model_providers.fixture]
name="Fixture"
wire_api="responses"
base_url="http://127.0.0.1:{first.server_port}/v1"
experimental_bearer_token="default-fixture"
requires_openai_auth=false
request_max_retries=0
stream_max_retries=0
[model_providers.fixture.http_headers]
X-Account-Fixture="default-origin"
'''; config=cfg_home/'config.toml'; config.write_text(cfg,encoding='utf-8'); env=dict(os.environ,CODEX_HOME=str(cfg_home),THREAD_PROVIDER_CARD_HEADLESS='1')
        for k in ('CODEX_CLI_PATH','CODEX_THREAD_ID','CODEX_SESSION_ID','OPENAI_API_KEY','CODEX_API_KEY','CODEX_APP_RUNTIME_CLI_PATH'):env.pop(k,None)
        def manage(action,extra=None,check=True):
            return subprocess.run(['powershell','-NoProfile','-File',str(package/'Manage.ps1'),'-Action',action,'-SandboxRoot',str(work)],env=env if extra is None else dict(env,**extra),check=check,timeout=55)
        manage('Install'); broken=dest/'relay.py'; broken.write_text('# damaged fixture'); manage('Repair');assert broken.read_bytes()==(package/'payload/relay.py').read_bytes()
        foreign=manage('Install',{'CODEX_CLI_PATH':'fixture-other-launcher.exe'},check=False); assert foreign.returncode!=0
        client=Client(dest/'Backend.exe',work,env); stack.callback(client.close)
        client.rpc('initialize',{'clientInfo':{'name':'codex_desktop','version':'fixture'},'capabilities':{'experimentalApi':True}});client.send({'method':'initialized','params':{}})
        def start():return client.rpc('thread/start',dict(model=model,cwd=str(work)))['thread']['id']
        a,b=start(),start(); client.ask(a);client.ask(b)
        client.rpc('thread/name/set',dict(threadId=a,name='Panel smoke fixture'))
        def store(op):
            obj=dict(op=op,id=a,label='Panel smoke fixture',url=f'http://127.0.0.1:{second.server_port}/v1',key='other-fixture')
            result=subprocess.run([str(dest/'runtime/python.exe'),'-I','-B',str(dest/'native_store.py')],input=json.dumps(obj).encode(),capture_output=True,env=env,check=True)
            data=json.loads(result.stdout); assert data.get('id')==a,data; assert 'key' not in data
        try:
            store('save'); client.ask(a); client.ask(b)
        finally: store('clear')
        client.ask(a);stack.close()
        assert first.visits==[(t,'Bearer default-fixture','default-origin',model,None) for t in (a,b,b,a)],first.visits
        assert second.visits==[(a,'Bearer other-fixture',None,model,None)],second.visits
        assert config.read_bytes().decode('utf8').splitlines()==cfg.splitlines()
        manage('Uninstall');assert not dest.exists()
        print('PASS: install, damaged-file repair, launcher conflict, real app-server, five requests, native credential store, thread isolation, restore and uninstall.')

if __name__=='__main__':run()
