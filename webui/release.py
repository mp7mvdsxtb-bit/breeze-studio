"""Build a source-only release; never package private audio, models or credentials."""
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile
from updater import managed


def source_files(root):
    candidates=[root/name for name in ('version.json','requirements-lock.txt','启动语音工作室.bat','停止语音工作室.bat','使用说明.md','README.md','NOTICE.md')]
    for folder in ('app','webui'):
        for directory,dirs,files in os.walk(root/folder):
            dirs[:]=[d for d in dirs if d not in ('__pycache__','backup-v1','.git','.pytest_cache') and not (Path(directory)/d).is_symlink()]
            candidates.extend(Path(directory)/name for name in files)
    for path in sorted(candidates):
        if not path.is_file() or path.is_symlink():continue
        name=path.relative_to(root).as_posix()
        if not managed(name):continue
        if path.suffix.lower() not in {'.py','.js','.css','.html','.ps1','.bat','.json','.txt','.md','.toml','.yml','.yaml'} and path.name!='LICENSE':continue
        if any(x in name for x in ('verify_','check_reference','verification-report')):continue
        yield name,path


def build(root,destination):
    root=Path(root);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    archive=destination/'breeze-studio-update.zip'
    manifest={'version':json.loads((root/'version.json').read_text(encoding='utf-8-sig'))['version'],'files':{}}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,path in source_files(root):
            data=path.read_bytes();manifest['files'][name]=hashlib.sha256(data).hexdigest();z.writestr(name,data)
        z.writestr('release-manifest.json',json.dumps(manifest))
    (destination/'breeze-studio-update.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    return manifest


if __name__=='__main__':
    result=build(Path(__file__).resolve().parents[1],sys.argv[1] if len(sys.argv)>1 else 'dist')
    print('Release files:',len(result['files']))
