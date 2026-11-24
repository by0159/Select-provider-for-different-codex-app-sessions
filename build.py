"""Build only explicitly listed source and release files. Run on Windows x64."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'out'
VERSION = '0.1.2'
PY = '3.13.13'
RUNTIME = f'python-{PY}-embed-amd64.zip'
SHA = '8766a8775746235e23cf5aee5027ab1060bb981d93110577adcf3508aa0cbd55'
SCRIPTS = ['native_store.py','bridge.py','relay.py','bindings.py']
TOP = ['README.md','LICENSE','Manage.ps1','Install.cmd','Repair.cmd','Uninstall.cmd']
SOURCE = TOP + ['.gitignore','build.py','tests/smoke.py','tests/test_route_identity.py','tests/NativeCardCheck.cs'] + ['src/'+x for x in SCRIPTS+['NativeCard.cs','Backend.cs']]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zipper(path, entries):
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as out:
        for file, name in entries: out.write(file, name)


def main():
    OUT.mkdir(exist_ok=True)
    archive = OUT / RUNTIME
    if not archive.exists():
        with urlopen(f'https://www.python.org/ftp/python/{PY}/{RUNTIME}', timeout=60) as response:
            archive.write_bytes(response.read())
    if digest(archive) != SHA: raise SystemExit('Embedded runtime SHA-256 mismatch')
    fw = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319'
    with tempfile.TemporaryDirectory(prefix='card-build-') as work:
        payload = Path(work)/'payload'; runtime = payload/'runtime'; runtime.mkdir(parents=True)
        with ZipFile(archive) as z: z.extractall(runtime)
        for name in SCRIPTS: shutil.copyfile(ROOT/'src'/name, payload/name)
        refs=['System.Drawing.dll','System.Windows.Forms.dll','System.Web.Extensions.dll']+[str(fw/'WPF'/x) for x in ['UIAutomationClient.dll','UIAutomationTypes.dll','WindowsBase.dll']]
        for name,cs,kind,includes in [('ProviderCard','NativeCard','winexe',refs),('Backend','Backend','exe',[])]:
            subprocess.run([str(fw/'csc.exe'),'/nologo','/optimize+','/platform:x64','/target:'+kind,'/out:'+str(payload/(name+'.exe')),*['/r:'+r for r in includes],str(ROOT/'src'/(cs+'.cs'))],check=True)
        files=sorted(x for x in payload.rglob('*') if x.is_file())
        manifest={'product':'CodexThreadProviderCard','version':VERSION,'files':[{'path':f.relative_to(payload).as_posix(),'sha256':digest(f)} for f in files]}
        (payload/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
        package=OUT/f'ThreadProviderCard-{VERSION}-windows-x64.zip'
        zipper(package,[(ROOT/n,n) for n in TOP]+[(f,'payload/'+f.relative_to(payload).as_posix()) for f in files+[payload/'manifest.json']])
    source=OUT/f'ThreadProviderCard-{VERSION}-source.zip'
    zipper(source,[(ROOT/n,n) for n in SOURCE])
    (OUT/'SHA256SUMS.txt').write_text(''.join(digest(f)+'  '+f.name+'\n' for f in (source,package)),encoding='ascii')
    print(package,source,sep='\n')

if __name__=='__main__': main()
