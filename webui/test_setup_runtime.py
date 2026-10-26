import hashlib
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from setup_runtime import valid_file,safe_target,download,install_models


def entry(data):return {'size':len(data),'lfs':{'sha256':hashlib.sha256(data).hexdigest()}}


def test_git_blob_and_lfs_verification(tmp_path):
    data=b'model data';path=tmp_path/'model';path.write_bytes(data)
    assert valid_file(path,entry(data))
    assert valid_file(path,{'size':len(data),'blobId':hashlib.sha1(b'blob 10\0'+data).hexdigest()})
    path.write_bytes(b'x'*len(data));assert not valid_file(path,entry(data))


@pytest.mark.parametrize('name',['../escape','a/../../escape','C:/escape','a\\escape','/escape'])
def test_unsafe_model_paths(tmp_path,name):
    with pytest.raises(ValueError):safe_target(tmp_path,name)


@pytest.mark.parametrize('supports_range',[True,False])
def test_resume_or_restart_when_server_ignores_range(tmp_path,supports_range):
    data=b'0123456789'*1000;requested=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            offset=int(self.headers['Range'].split('=')[1].split('-')[0]);requested.append(offset)
            if supports_range:
                self.send_response(206);self.send_header('Content-Range',f'bytes {offset}-{len(data)-1}/{len(data)}')
            else:self.send_response(200);offset=0
            self.end_headers();self.wfile.write(data[offset:])
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        path=tmp_path/'model.bin';path.with_suffix('.bin.part').write_bytes(data[:100])
        download(f'http://127.0.0.1:{server.server_port}/model',path,entry(data),attempts=1)
        assert path.read_bytes()==data and requested==[100]
        download('invalid-url',path,entry(data)) # Verified file skips network.
    finally:server.shutdown();server.server_close();thread.join()


def test_verify_only_reports_missing_without_network(tmp_path):
    (tmp_path/'webui').mkdir();(tmp_path/'webui/model-downloads.json').write_text(json.dumps({'models':[{'kind':'translation','files':[dict(entry(b'abc'),rfilename='model.bin')]}]}))
    with pytest.raises(RuntimeError,match='Missing or invalid'):install_models(tmp_path,True)
