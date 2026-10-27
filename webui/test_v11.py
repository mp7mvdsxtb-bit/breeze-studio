import io
import json
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from test_studio import engine,backend,reference
from audio_quality import inspect_audio,gentle_highpass
import server


def test_audio_quality_warnings_and_gentle_filter(tmp_path):
    silent=tmp_path/'silence.wav';sf.write(silent,np.zeros(24000),24000)
    assert any('静音' in w for w in inspect_audio(silent))
    clipped=tmp_path/'clipped.wav';sf.write(clipped,np.ones(24000),24000)
    assert any('削波' in w for w in inspect_audio(clipped))
    t=np.arange(24000)/24000;low=np.sin(2*np.pi*20*t).astype('float32');voice=np.sin(2*np.pi*1000*t).astype('float32')
    assert np.std(gentle_highpass(low,24000))<.15*np.std(low)
    assert np.std(gentle_highpass(voice,24000))>.95*np.std(voice)


def test_preview_candidates_and_select_voice(engine,backend,monkeypatch):
    engine.backend,_=backend;monkeypatch.setattr(server,'studio',engine);client=TestClient(server.app)
    result=client.post('/api/voice-preview',json={'text':'Hello, friend. '*30,'options':{}})
    assert result.status_code==202
    data=result.json();assert len(data['ids'])==3 and len(data['sample'])<=160
    assert [engine.get(i)['options']['seed'] for i in data['ids']]==[42,43,44]
    assert client.post('/api/voice-preview/check',json={'texts':['Hello, friend. '*30],'options':{}}).json()['requires_choice']
    engine.process(engine.get(data['ids'][0]))
    chosen=client.post('/api/voice-preview/'+data['ids'][0]+'/choose')
    assert chosen.status_code==200 and chosen.json()['transcript']==data['sample']
    assert engine.voice(chosen.json()['id'])


@pytest.mark.parametrize('segment',[0,1])
def test_regeneration_produces_new_full_result_without_changing_original(engine,backend,segment):
    engine.backend,handler=backend
    first=engine.submit(['A friendly product introduction. '*14],{'segment_chars':100})['id']
    engine.process(engine.get(first));before=engine.get(first)
    assert before['status']=='complete' and before['segment_count']>1
    original=(engine.output/(first+'.wav')).read_bytes();calls=handler.calls
    revision=engine.regenerate_segment(first,segment)['id']
    engine.process(engine.get(revision))
    after=engine.get(revision)
    assert after['status']=='complete' and after['revision_of']==first and after['revision_segment']==segment
    assert handler.calls==calls+1
    assert (engine.output/(first+'.wav')).read_bytes()==original
    assert len(after['result']['segment_details'])==before['segment_count']
    assert handler.requests[-1]['ref_audio']==(engine.output/(first+'_parts')/'0000.wav').read_bytes()


def test_enhancement_preserves_accessible_original(engine,backend,monkeypatch):
    engine.backend,_=backend;monkeypatch.setattr(server,'studio',engine);client=TestClient(server.app)
    job=engine.submit(['Hello world.'],{'enhance':True})['id'];engine.process(engine.get(job))
    result=engine.get(job)['result'];assert result['original_url']
    assert client.get(result['original_url']).status_code==200
    assert client.get(result['segment_details'][0]['url']).status_code==200
    assert client.get('/api/jobs/'+job+'/segments').status_code==200
    assert client.get('/api/jobs/'+job+'/segments/999/audio').status_code==404
    assert (engine.output/(job+'.raw.wav')).read_bytes()!=(engine.output/(job+'.wav')).read_bytes()


def test_subjective_feedback_is_persisted_and_not_automatically_blacklisted(engine,backend,monkeypatch):
    engine.backend,_=backend;monkeypatch.setattr(server,'studio',engine);client=TestClient(server.app)
    job=engine.submit(['Hello world.'],{})['id'];engine.process(engine.get(job))
    assert client.post('/api/voice-feedback/'+job,json={'labels':['raspy','hollow']}).status_code==200
    assert engine.get(job)['result']['subjective_feedback']==['raspy','hollow']
    assert not engine.setting('blocked_audio_signatures',[])
    assert client.post('/api/voice-feedback/'+job,json={'labels':['invented']}).status_code==400


def test_blind_benchmark_hides_mapping_and_cancels_only_its_own_jobs(engine,monkeypatch):
    monkeypatch.setattr(server,'studio',engine);client=TestClient(server.app)
    one=engine.submit(['First'],{})['id'];two=engine.submit(['First'],{})['id'];other=engine.submit(['Other'],{})['id']
    benchmark_id='a'*32;directory=engine.output/'benchmarks';directory.mkdir()
    (directory/(benchmark_id+'.json')).write_text(json.dumps({'submitted_ids':[one,two],'completed_submission':True,'pairs':[{'number':1,'text':'First','A':{'id':one,'system':'candidate'},'B':{'id':two,'system':'baseline'}}]}))
    blind=client.get('/api/benchmarks/'+benchmark_id).json()
    assert 'system' not in blind['pairs'][0]['A'] and blind['totals'] is None
    revealed=client.get('/api/benchmarks/'+benchmark_id+'?reveal=true').json()
    assert revealed['pairs'][0]['A']['system']=='candidate'
    assert client.post('/api/benchmarks/'+benchmark_id+'/cancel').json()['cancelled']==2
    assert engine.get(one)['status']=='cancelled' and engine.get(two)['status']=='cancelled'
    assert engine.get(other)['status']=='queued'
