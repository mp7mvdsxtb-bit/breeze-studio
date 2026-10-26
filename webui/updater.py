"""Private GitHub Release updates. Apply only before the web server starts."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'version.json','requirements-lock.txt','启动语音工作室.bat','停止语音工作室.bat','使用说明.md','README.md','NOTICE.md'}


def managed(name):
    p=PurePosixPath(name)
    return (not p.is_absolute() and '\\' not in name and ':' not in name
            and all(x not in ('..','.','') for x in name.split('/'))
            and (name in ROOT_FILES or (p.parts[0] in ('webui','app') and len(p.parts)>1))
            and not any(x in ('__pycache__','.git','backup-v1','outputs','venv') for x in p.parts)
            and p.suffix.lower() not in ('.wav','.mp3','.flac','.bin','.pt','.safetensors','.log','.png','.jpg','.pyc'))


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):
        raise ValueError('版本号必须是 x.y.z')
    return tuple(map(int,value.split('.')))


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


class Updater:
    def __init__(self,root=ROOT):
        self.root=Path(root)

    def settings(self):
        return read_json(self.root/'update-settings.json',{'automatic':True})

    def configure(self,automatic):
        if type(automatic) is not bool:raise ValueError('automatic 必须是布尔值')
        path=self.root/'update-settings.json'
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps({'automatic':automatic}),encoding='utf-8')
        os.replace(temp,path)

    def gh(self,*args):
        local=self.root/'tools/github-cli/bin/gh.exe'
        exe=str(local) if local.exists() else shutil.which('gh')
        if not exe:raise RuntimeError('请安装 GitHub CLI 并执行 gh auth login，私有仓库更新需要登录。')
        result=subprocess.run([exe,*args],capture_output=True,text=True,encoding='utf-8',timeout=90,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:raise RuntimeError('GitHub 请求失败，请检查网络、gh auth login 和仓库读取权限。')
        return result.stdout

    def status(self,check=False):
        current=read_json(self.root/'version.json',{'version':'1.0.0','repository':''})
        state={'current':current['version'],'repository':current.get('repository',''),
               'automatic':self.settings()['automatic'],'available':False,
               'message':'启动时检查并安装更新；运行中的配音不会被打断。'}
        if not state['repository']:
            state['message']='待创建 GitHub 私有仓库并发布首个版本后启用更新。'
            return state
        if check:
            try:
                repo=state['repository']
                if not re.fullmatch(r'[\w.-]+/[\w.-]+',repo):raise ValueError('仓库地址无效')
                release=json.loads(self.gh('api',f'repos/{repo}/releases/latest'))
                latest=release['tag_name'].removeprefix('v')
                state.update(latest=latest,available=version(latest)>version(state['current']))
                state['message']='有新版本，下次启动时自动安装。' if state['available'] else '当前已是最新版本。'
            except Exception as exc:state['message']=str(exc)
        return state

    def startup(self):
        if not self.settings()['automatic']:return
        state=self.status(True)
        if not state['available']:return
        with tempfile.TemporaryDirectory(prefix='breeze-update-') as directory:
            self.gh('release','download','v'+state['latest'],'--repo',state['repository'],
                    '--pattern','breeze-studio-update.*','--dir',directory)
            archive=Path(directory)/'breeze-studio-update.zip'
            checksum=(Path(directory)/'breeze-studio-update.sha256').read_text().split()[0]
            if hashlib.sha256(archive.read_bytes()).hexdigest()!=checksum:raise ValueError('更新包校验失败')
            self.apply(archive,state['latest'])

    def apply(self,archive,expected):
        """Verify entire archive before touching code; backup and rollback copy failures."""
        root=self.root.resolve()
        with zipfile.ZipFile(archive) as z:
            names=z.namelist()
            if len(names)!=len(set(names)) or len(names)>3000:raise ValueError('更新包重复文件或文件过多')
            if sum(i.file_size for i in z.infolist())>50*1024*1024:raise ValueError('更新包过大')
            manifest=json.loads(z.read('release-manifest.json'))
            files=manifest['files']
            if set(names)!=set(files)|{'release-manifest.json'}:raise ValueError('更新包文件清单不匹配')
            if manifest['version']!=expected or version(expected)<=version(read_json(root/'version.json',{})['version']):raise ValueError('更新版本无效')
            content={}
            for name,digest in files.items():
                path=root/name
                if not managed(name) or not path.resolve().is_relative_to(root):raise ValueError('更新包路径无效')
                if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in [path,*path.parents] if p.is_relative_to(root)):raise ValueError('不允许通过链接更新文件')
                info=z.getinfo(name)
                if (info.external_attr>>16)&0o170000==0o120000:raise ValueError('不允许符号链接')
                data=z.read(name)
                if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('更新文件校验失败')
                if name.endswith('.py'):compile(data,name,'exec')
                content[name]=data
            if 'version.json' not in content or json.loads(content['version.json'])['version']!=expected:raise ValueError('缺少版本文件')
            if json.loads(content['version.json']).get('repository','')!=read_json(root/'version.json',{}).get('repository',''):raise ValueError('更新包仓库不匹配')
            if (root/'requirements-lock.txt').exists() and content.get('requirements-lock.txt')!=(root/'requirements-lock.txt').read_bytes():raise ValueError('此版本需要更新运行环境，请手动安装后再升级。')
            backup=root/'.update-backups'/str(time.time_ns())
            backup.mkdir(parents=True)
            previous={name:(root/name).read_bytes() if (root/name).exists() else None for name in content}
            for name,data in previous.items():
                if data is not None:
                    target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            changed=[]
            try:
                for name,data in content.items():
                    target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
                    temp=target.with_name(target.name+'.update-tmp');temp.write_bytes(data)
                    os.replace(temp,target);changed.append(name)
            except Exception:
                for name in reversed(changed):
                    target=root/name
                    if previous[name] is None:target.unlink(missing_ok=True)
                    else:target.write_bytes(previous[name])
                raise
            (backup/'rollback.json').write_text(json.dumps({'files':list(content),'new_files':[n for n,v in previous.items() if v is None]}),encoding='utf-8')


if __name__=='__main__':
    try:
        # Prevent two launcher windows from applying releases simultaneously.
        with (ROOT/'update.lock').open('a+b') as lock:
            if os.name=='nt':
                import msvcrt
                lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            Updater().startup()
    except Exception as exc:print('更新未完成，继续使用当前版本：'+str(exc))
