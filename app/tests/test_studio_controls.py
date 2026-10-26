import json
from types import SimpleNamespace
import numpy as np
from fastapi.testclient import TestClient
from breeze_infer import api
from models.fast_streaming import FastStreamingConfig


def configure(monkeypatch):
    runtime=SimpleNamespace(config=FastStreamingConfig(),sample_rate=24000)
    for name,value in {'runtime':runtime,'tokenizer':None,'audio_tokenizer':None,'model':None}.items():
        monkeypatch.setattr(api.app.state,name,value,raising=False)
    monkeypatch.setattr(api,'prepare_inputs',lambda *args,**kwargs:{})
    monkeypatch.setattr(api,'set_all_seeds',lambda seed:None)
    return runtime


def test_controls_apply_only_to_current_request(monkeypatch):
    runtime=configure(monkeypatch);original=runtime.config;seen=[]
    def chunks(runtime,inputs,**kwargs):
        seen.append(runtime.config)
        yield SimpleNamespace(audio=np.ones(240,dtype=np.float32)*.1)
    monkeypatch.setattr(api,'_iter_seeded_audio_chunks',chunks)
    client=TestClient(api.app)
    result=client.post('/v1/audio/speech',data={'text':'Hello','instruction':'Friendly English voice','controls':json.dumps({'temperature':.65,'top_p':.8,'top_k':30,'max_new_tokens':80,'repetition_penalty':1.2,'do_sample':False})})
    assert result.status_code==200
    assert seen[0].temperature==.65 and seen[0].max_new_tokens==80 and seen[0].top_k==30
    assert seen[0].do_sample is False
    assert runtime.config is original
    result=client.post('/v1/audio/speech',data={'text':'Hello','instruction':'Friendly English voice'})
    assert result.status_code==200 and seen[1] is original


def test_invalid_controls_release_lock_and_restore_config(monkeypatch):
    runtime=configure(monkeypatch);original=runtime.config
    client=TestClient(api.app)
    for invalid in ({'top_k':2.5},{'temperature':float('nan')},{'foo':1},{'max_new_tokens':2000}):
        result=client.post('/v1/audio/speech',data={'text':'Hello','controls':json.dumps(invalid)})
        assert result.status_code==400 and runtime.config is original
        assert not api._request_lock.locked()
