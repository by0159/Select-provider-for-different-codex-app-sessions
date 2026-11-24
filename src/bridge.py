"""Locate the registered App on every launch so Store versioned paths never go stale."""
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from relay import AUTH, Relay, configuration


def native_binary():
    ps = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    # Explicit UTF-8 also supports non-ASCII Store library paths.
    query = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); (Get-AppxPackage -Name OpenAI.Codex | Select-Object -First 1).InstallLocation"
    result = subprocess.run([str(ps), '-NoProfile','-NonInteractive','-Command',query], capture_output=True, timeout=15, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    install = result.stdout.decode('utf-8-sig').strip()
    if install:
        binary = Path(install)/'app/resources/codex.exe'
        if binary.is_file(): return binary
    raise RuntimeError('Cannot locate the registered Windows Codex App backend.')


def main(args):
    home = Path(os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve()
    native = native_binary()
    if args == ['--card-doctor']:
        print('Packaged Codex backend found.')
        configuration(home)
        status = subprocess.run([str(native),'--version'],timeout=12,check=True).returncode
        print('Provider configuration is supported. Open an existing chat with its right sidebar visible to show the card.')
        return status
    if args == ['--card-check-config']:
        configuration(home)
        return 0
    if 'app-server' not in args or any(x in args for x in ('generate-ts','generate-json-schema','--help','-h')):
        return subprocess.call([str(native), *args])
    try:
        relay = Relay(home)
    except (ValueError,OSError,KeyError,TypeError):
        print('Thread Provider Card inactive: run Repair.cmd to check the selected provider.',file=sys.stderr)
        return subprocess.call([str(native), *args])
    # The daemon would otherwise reuse a backend with a stale ephemeral relay port.
    prefix = 'model_providers.'+relay.provider
    options = ['--no-daemon','-c',prefix+'.base_url="http://127.0.0.1:%d/v1"'%relay.server_port,
               '-c',prefix+'.http_headers.'+AUTH+'='+json.dumps(relay.secret),
               '-c',prefix+'.supports_websockets=false','-c','features.responses_websockets=false','-c','features.responses_websockets_v2=false']
    relay.start()
    try:
        if os.environ.get('THREAD_PROVIDER_CARD_HEADLESS')!='1':
            subprocess.Popen([str(HERE/'ProviderCard.exe')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        return subprocess.call([str(native), *options, *args])
    finally:
        relay.shutdown()
        relay.server_close()

if __name__=='__main__':
    try: sys.exit(main(sys.argv[1:]))
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print('Thread Provider Card: '+(str(exc) if isinstance(exc,(RuntimeError,ValueError)) and type(exc) is not UnicodeDecodeError else type(exc).__name__),file=sys.stderr)
        sys.exit(1)

