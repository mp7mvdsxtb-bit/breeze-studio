import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient
import server
from studio import Studio


def test_preview_name_validation_and_legacy_default(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'studio',Studio(tmp_path,'http://127.0.0.1:1'))
    client=TestClient(server.app)
    job=server.studio.submit(['Hello there.'],{})['id']
    sf.write(server.studio.output/(job+'.wav'),np.sin(np.arange(24000)*.06)*.1,24000)
    server.studio.update(job,status='complete',result={'warnings':[]})
    url='/api/voice-preview/'+job+'/choose'
    assert client.post(url,json={'name':'  '}).status_code==400
    assert client.post(url,json={'name':123}).status_code==400
    named=client.post(url,json={'name':'  美国女声  '} )
    assert named.status_code==200 and named.json()['name']=='美国女声'
    assert client.patch('/api/voices/'+named.json()['id'],json={'name':'新名称'}).json()['name']=='新名称'
    assert client.post(url,json={}).json()['name']=='已选英语音色 '+job[:8]
