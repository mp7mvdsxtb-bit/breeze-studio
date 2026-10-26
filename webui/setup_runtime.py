"""Windows bootstrap, resumable official model downloads and environment checks."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse


def run(command):
    print('Running:', ' '.join(map(str,command)),flush=True)
    subprocess.run(list(map(str,command)),check=True)


def valid_file(path,entry):
    if not path.is_file() or path.stat().st_size!=entry['size']:return False
    lfs=entry.get('lfs')
    digest=hashlib.sha256() if lfs else hashlib.sha1()
    if not lfs:digest.update(f"blob {entry['size']}\0".encode())
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()==(lfs['sha256'] if lfs else entry['blobId'])


def safe_target(root,name):
    if '\\' in name or ':' in name or PurePosixPath(name).is_absolute() or '..' in name.split('/'):raise ValueError('Unsafe model path')
    target=root/name
    if not target.resolve().is_relative_to(root.resolve()):raise ValueError('Model path escapes target')
    if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [target,*target.parents] if p.is_relative_to(root)):raise ValueError('Model path contains a link')
    return target


def download(url,path,entry,attempts=5):
    if valid_file(path,entry):
        print('Verified:',path.name,flush=True);return
    path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_name(path.name+'.part')
    for attempt in range(attempts):
        try:
            offset=partial.stat().st_size if partial.exists() else 0
            if offset>entry['size']:partial.unlink();offset=0
            if offset<entry['size']:
                fresh_url=url+('&' if '?' in url else '?')+'breeze_setup='+str(time.time_ns())
                request=urllib.request.Request(fresh_url,headers={'Range':f'bytes={offset}-','User-Agent':'Breeze-Studio-Setup/1.0'})
                with urllib.request.urlopen(request,timeout=90) as response:
                    status=response.status
                    if status==206:
                        content_range=response.headers.get('Content-Range','')
                        if not content_range.startswith(f'bytes {offset}-') or not content_range.endswith('/'+str(entry['size'])):raise ValueError('Invalid download range')
                    elif status==200:offset=0
                    else:raise ValueError(f'Unexpected download status: {status}')
                    mode='ab' if offset else 'wb'
                    with partial.open(mode) as output:
                        last=time.monotonic()
                        while chunk:=response.read(1024*1024):
                            output.write(chunk);offset+=len(chunk)
                            if offset>entry['size']:raise ValueError('Download larger than expected')
                            if time.monotonic()-last>3:
                                print(f'{path.name}: {offset/entry["size"]:.0%}',flush=True);last=time.monotonic()
            if not valid_file(partial,entry):
                if partial.exists() and partial.stat().st_size>=entry['size']:partial.unlink()
                raise ValueError('Download incomplete or checksum mismatch')
            os.replace(partial,path)
            print('Downloaded and verified:',path.name,flush=True);return
        except Exception:
            if attempt+1==attempts:raise
            print(f'Download interrupted; retry {attempt+1}/{attempts-1}',flush=True)
            time.sleep(min(2**attempt,10))


def install_models(root,verify_only=False):
    spec=json.loads((root/'webui/model-downloads.json').read_text(encoding='utf-8'))
    missing=[]
    for model in spec['models']:
        destination=root.parent/'models/Breeze-TTS-2' if model['kind']=='tts' else root/'translation-model'
        for entry in model['files']:
            target=safe_target(destination,entry['rfilename'])
            if verify_only:
                if not valid_file(target,entry):missing.append(str(target))
            else:
                name=urllib.parse.quote(entry['rfilename'],safe='/')
                download(f'https://huggingface.co/{model["repo"]}/resolve/{model["revision"]}/{name}',target,entry)
    if missing:raise RuntimeError('Missing or invalid model files:\n'+'\n'.join(missing))


def verify_environment(python):
    run([python,'-m','pip','check'])
    run([python,'-c',"import torch,torchaudio,transformers,qwen_tts,fastapi,uvicorn,sentencepiece,sacremoses,numpy,soundfile; assert torch.cuda.is_available(), 'CUDA unavailable: update NVIDIA driver'; assert transformers.__version__=='4.57.3'; x=torch.ones(1,device='cuda'); print('CUDA verified:',torch.cuda.get_device_name(0)); print('VRAM GiB:',round(torch.cuda.get_device_properties(0).total_memory/2**30,1))"])


def setup(root,verify_only=False):
    if sys.version_info[:2]!=(3,12) or sys.maxsize<=2**32:raise RuntimeError('Requires Python 3.12 x64')
    python=root/'venv/Scripts/python.exe'
    if python.exists():
        run([python,'-c','import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize(chr(80))==8, "Existing venv must use Python 3.12 x64; move it aside and rerun setup"'])
    if verify_only:
        if not python.exists():raise RuntimeError('Virtual environment missing')
        verify_environment(python);install_models(root,True);print('INSTALLATION_VERIFIED');return
    if not shutil.which('nvidia-smi'):raise RuntimeError('NVIDIA driver not found. Install the NVIDIA driver first; then rerun setup.')
    run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'])
    for directory in ('tmp','outputs','tools'): (root/directory).mkdir(exist_ok=True)
    spec=json.loads((root/'webui/model-downloads.json').read_text())
    required=0
    for model in spec['models']:
        destination=root.parent/'models/Breeze-TTS-2' if model['kind']=='tts' else root/'translation-model'
        required+=sum(e['size'] for e in model['files'] if not (destination/e['rfilename']).exists())
    space_needed=max(required+8*1024**3,25*1024**3 if not python.exists() else 0)
    if shutil.disk_usage(root).free<space_needed:raise RuntimeError('Not enough disk space. Keep at least 25 GB free for a fresh installation.')
    if not python.exists():run([sys.executable,'-m','venv',root/'venv'])
    run([python,'-m','pip','install','--upgrade','pip'])
    run([python,'-m','pip','install','--index-url','https://download.pytorch.org/whl/cu128','torch==2.9.1+cu128','torchaudio==2.9.1+cu128'])
    run([python,'-m','pip','install','-r',root/'requirements-lock.txt','--extra-index-url','https://download.pytorch.org/whl/cu128'])
    verify_environment(python)
    install_models(root)
    print('INSTALLATION_VERIFIED. Double-click the studio launcher.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    try:
        root=args.root.resolve()
        print('Breeze-TTS-2: research/non-commercial model license. Initial download ~11 GB; allow 25 GB disk space.',flush=True)
        # Windows file lock is released automatically, including after errors.
        with (root/'setup.lock').open('a+b') as lock:
            if os.name=='nt':
                import msvcrt
                lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            setup(root,args.verify_only)
    except Exception as exc:
        print('SETUP FAILED:',exc,file=sys.stderr,flush=True);sys.exit(1)
