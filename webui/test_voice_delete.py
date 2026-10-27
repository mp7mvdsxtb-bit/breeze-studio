import io
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from studio import Studio
import server


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'studio',Studio(tmp_path,'http://127.0.0.1:1'))
    return TestClient(server.app)


def voice():
    stream=io.BytesIO();sf.write(stream,np.sin(np.arange(24000)*.04)*.1,24000,format='WAV');stream.seek(0)
    return server.studio.save_voice('Delete test','Hello world.',stream)


def test_delete_removes_reference_preserves_output(client):
    v=voice();result=server.studio.output/'existing.wav';result.write_bytes(b'old output')
    assert client.delete('/api/voices/'+v['id']).status_code==200
    assert server.studio.voice(v['id']) is None
    assert not (server.studio.voices/(v['id']+'.wav')).exists()
    assert result.read_bytes()==b'old output'
    assert client.get(v['url']).status_code==404
    assert client.delete('/api/voices/'+v['id']).status_code==404


@pytest.mark.parametrize('status',['queued','running','cancelling'])
def test_busy_voice_cannot_be_deleted(client,status):
    v=voice();j=server.studio.submit(['Hello'],{'mode':'clone','voice_id':v['id']})
    server.studio.update(j['id'],status=status)
    assert client.delete('/api/voices/'+v['id']).status_code==409
    assert server.studio.voice(v['id'])


def test_retry_deleted_reference_fails_instead_of_designing_new_voice(client):
    v=voice();j=server.studio.submit(['Hello'],{'mode':'clone','voice_id':v['id']})
    server.studio.update(j['id'],status='error')
    assert client.delete('/api/voices/'+v['id']).status_code==200
    with pytest.raises(ValueError,match='已删除'):server.studio.retry(j['id'])
