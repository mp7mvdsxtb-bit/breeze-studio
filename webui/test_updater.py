import hashlib
import json
import zipfile
import pytest
from updater import Updater,managed
from release import build


def package(tmp_path,files):
    path=tmp_path/'update.zip'
    with zipfile.ZipFile(path,'w') as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('release-manifest.json',json.dumps({'version':'1.1.0','files':{n:hashlib.sha256(d).hexdigest() for n,d in files.items()}}))
    return path


def test_apply_preserves_audio_and_backup(tmp_path):
    root=tmp_path/'root';root.mkdir();(root/'version.json').write_text('{"version":"1.0.0"}')
    (root/'outputs').mkdir();(root/'outputs/private.wav').write_bytes(b'private')
    archive=package(tmp_path,{'version.json':b'{"version":"1.1.0"}','webui/new.py':b'x=1'})
    Updater(root).apply(archive,'1.1.0')
    assert (root/'outputs/private.wav').read_bytes()==b'private'
    assert (root/'webui/new.py').exists()
    assert list((root/'.update-backups').glob('*/version.json'))


@pytest.mark.parametrize('name',['../bad.py','webui/../../bad.py','C:/bad.py','webui\\bad.py','outputs/test.py','venv/test.py','webui/outputs/test.py','app/data.safetensors'])
def test_reject_unsafe_paths(name):assert not managed(name)


def test_invalid_python_does_not_change_code(tmp_path):
    (tmp_path/'version.json').write_text('{"version":"1.0.0"}')
    archive=package(tmp_path,{'version.json':b'{"version":"1.1.0"}','webui/new.py':b'invalid syntax !'})
    with pytest.raises(SyntaxError):Updater(tmp_path).apply(archive,'1.1.0')
    assert json.loads((tmp_path/'version.json').read_text())['version']=='1.0.0'


def test_changed_dependencies_require_manual_install(tmp_path):
    (tmp_path/'version.json').write_text('{"version":"1.0.0"}')
    (tmp_path/'requirements-lock.txt').write_bytes(b'old')
    archive=package(tmp_path,{'version.json':b'{"version":"1.1.0"}','requirements-lock.txt':b'new'})
    with pytest.raises(ValueError,match='运行环境'):Updater(tmp_path).apply(archive,'1.1.0')


def test_package_excludes_private_files(tmp_path):
    for name,data in [('version.json','{"version":"1.0.0"}'),('app/models/code.py','x=1'),('webui/static/app.js','x=1'),('outputs/secret.wav','private'),('venv/secret.py','secret'),('webui/backup-v1/old.py','old')]:
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(data)
    manifest=build(tmp_path,tmp_path/'dist')
    assert set(manifest['files'])=={'version.json','app/models/code.py','webui/static/app.js'}


def test_settings_and_unconfigured_state(tmp_path):
    u=Updater(tmp_path);assert not u.status(True)['available']
    u.configure(False);assert not u.status()['automatic']
    with pytest.raises(ValueError):u.configure('false')


def test_copy_failure_restores_old_version(tmp_path,monkeypatch):
    import updater
    (tmp_path/'version.json').write_text('{"version":"1.0.0"}')
    archive=package(tmp_path,{'version.json':b'{"version":"1.1.0"}','webui/new.py':b'x=1'})
    original=updater.os.replace
    def fail(source,target):
        if str(target).endswith('new.py'):raise OSError('simulated disk error')
        return original(source,target)
    monkeypatch.setattr(updater.os,'replace',fail)
    with pytest.raises(OSError):Updater(tmp_path).apply(archive,'1.1.0')
    assert json.loads((tmp_path/'version.json').read_text())['version']=='1.0.0'


def test_tampered_file_rejected(tmp_path):
    (tmp_path/'version.json').write_text('{"version":"1.0.0"}')
    archive=package(tmp_path,{'version.json':b'{"version":"1.1.0"}'})
    with zipfile.ZipFile(archive,'a') as z:z.writestr('webui/extra.py',b'x=1')
    with pytest.raises(ValueError,match='清单'):Updater(tmp_path).apply(archive,'1.1.0')
