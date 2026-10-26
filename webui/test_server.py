import io
import json
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
import server
from studio import Studio


def test_update_settings(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'ROOT',tmp_path)
    client=TestClient(server.app)
    assert client.get('/api/updates').json()['current']=='1.0.0'
    assert client.post('/api/updates/settings',json={'automatic':'false'}).status_code==400
    assert client.post('/api/updates/settings',json={'automatic':False}).json()['automatic'] is False


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'studio',Studio(tmp_path,'http://127.0.0.1:1'))
    return TestClient(server.app)


def test_queue_accepts_when_model_loading_and_rejects_invalid(client):
    r=client.post('/api/submit',json={'texts':['Hello world.'],'options':{}})
    assert r.status_code==202
    assert client.get('/api/jobs/'+r.json()['id']).json()['status']=='queued'
    for options in ({'mode':[]},{'top_k':'50'},{'variants':0}):
        assert client.post('/api/submit',json={'texts':['test'],'options':options}).status_code==400
    assert client.get('/api/jobs').json()['total']==1


def test_import_quoted_csv_and_utf8_bom_txt(client):
    r=client.post('/api/import',files={'file':('test.csv',b'text\n"Hello, friend.\nWelcome back."\n"Next line."','text/csv')})
    assert r.json()['texts']==['Hello, friend.\nWelcome back.','Next line.']
    r=client.post('/api/import',files={'file':('test.txt',b'\xef\xbb\xbfOne\r\n\r\nTwo')})
    assert r.json()['texts']==['One','Two']
    assert client.post('/api/import',files={'file':('bad.csv',b'wrong\nhello')}).status_code==400
    assert client.post('/api/import',files={'file':('bad.txt',b'\xff\xfe\xff')}).status_code==400


def test_voice_validation_and_library_roundtrip(client):
    for content in (b'not audio',b''):
        assert client.post('/api/voices',data={'name':'test','transcript':'Hello'},files={'audio':('bad.wav',content)}).status_code==400
    wav=io.BytesIO();sf.write(wav,np.zeros(24000),24000,format='WAV')
    r=client.post('/api/voices',data={'name':'English reference','transcript':'Hello, friend.'},files={'audio':('ref.wav',wav.getvalue())})
    assert r.status_code==200
    voice=r.json();assert client.get(voice['url']).content[:4]==b'RIFF'
    assert client.get('/api/voices').json()[0]['transcript']=='Hello, friend.'
    r=client.post('/api/submit',json={'texts':['Another phrase.'],'options':{'mode':'clone','voice_id':voice['id']}})
    assert r.status_code==202
    assert client.get('/api/jobs/'+r.json()['id']).json()['options']['instruction']==''


def test_cancel_retry_pause_resume_and_bulk_cancel(client):
    r=client.post('/api/submit',json={'texts':['One','Two'],'options':{'variants':2}}).json()
    assert client.post('/api/queue/pause').json()['paused']
    assert client.post('/api/jobs/'+r['id']+'/cancel').status_code==200
    assert client.get('/api/jobs/'+r['id']).json()['status']=='cancelled'
    assert client.post('/api/jobs/'+r['id']+'/retry').status_code==200
    assert client.post('/api/queue/cancel-pending').json()['cancelled']==4
    assert client.post('/api/queue/resume').json()['paused'] is False
    assert client.get('/api/jobs?status=cancelled').json()['total']==4
    assert client.get('/api/jobs/'+r['id']+'/live').status_code==409


def test_empty_export_missing_files_and_path_traversal(client):
    assert client.get('/api/export/status').json()['count']==0
    assert client.get('/api/export').status_code==400
    assert client.get('/api/export?batch_id=../../foo').status_code==400
    assert client.get('/audio/not-a-real-file.wav').status_code==404
    assert client.get('/api/jobs/missing').status_code==404


def test_segment_preview_and_pagination(client):
    r=client.post('/api/preview',json={'text':'An English sentence. '*20,'options':{'segment_chars':100}})
    assert r.status_code==200 and len(r.json()['segments'])>1
    assert all(len(s)<=100 for s in r.json()['segments'])
    client.post('/api/submit',json={'texts':['One','Two','Three'],'options':{}})
    r=client.get('/api/jobs?limit=1&offset=1').json()
    assert r['total']==3 and len(r['items'])==1
    assert client.get('/api/jobs?search=Three').json()['total']==1


def test_rejected_voice_keeps_file_but_leaves_recent_results(client):
    response=client.post('/api/submit',json={'texts':['Hello friend.'],'options':{}}).json()
    job_id=response['id']
    path=server.studio.output/(job_id+'.wav')
    sf.write(path,np.sin(np.arange(24000)*.04)*.1,24000)
    server.studio.update(job_id,status='complete',result={'id':job_id,'text':'Hello friend.','url':'/audio/'+path.name})
    assert client.post('/api/jobs/'+job_id+'/reject-voice').status_code==200
    assert client.get('/api/state').json()['history']==[]
    assert path.is_file()
    assert client.get('/api/jobs/'+job_id).json()['quality_feedback']=='avoid_voice'


def test_translate_api_preserves_voice_negation(client):
    r=client.post('/api/translate-description',json={'text':'清亮干净，不要沙哑，不要气泡音。'})
    assert r.status_code==200
    assert 'Avoid vocal fry.' in r.json()['english']
    assert r.json()['source']=='清亮干净，不要沙哑，不要气泡音。'
    assert client.post('/api/translate-description',json={'text':''}).status_code==400
    assert client.post('/api/translate-description',json={'text':'中'*601}).status_code==400
