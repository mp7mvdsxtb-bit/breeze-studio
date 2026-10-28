import io
import json
import zipfile

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient
import server
from studio import Studio
from audio_quality import compare_segment_levels


def test_batch_review_feedback_and_export(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'studio',Studio(tmp_path,'http://127.0.0.1:1'))
    client=TestClient(server.app)
    result=client.post('/api/submit',json={'texts':['One.','Two.'],'options':{}}).json()
    first,second=result['ids']
    for job in (first,second):
        sf.write(server.studio.output/(job+'.wav'),np.zeros(2400),24000)
        server.studio.update(job,status='complete',result={'url':'/audio/'+job+'.wav'})
    assert client.post('/api/voice-feedback/'+first,json={'labels':['mispronounced']}).status_code==200
    review=client.get('/api/batches/'+result['batch_id']).json()['items']
    assert [j['id'] for j in review]==[first,second]
    status=client.get('/api/export/status',params={'batch_id':result['batch_id']}).json()
    assert status=={'count':2,'unreviewed':1,'unsatisfied':1}
    response=client.get('/api/export',params={'batch_id':result['batch_id'],'name_prefix':'../../Product'})
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert manifest[0]['feedback']==['mispronounced']
        assert all('/' not in item['filename'] and item['filename'].endswith('.wav') for item in manifest)
        assert all(item['filename'] in z.namelist() for item in manifest)


def test_segment_level_difference_is_a_listening_cue(tmp_path):
    paths=[tmp_path/'a.wav',tmp_path/'b.wav']
    sf.write(paths[0],np.ones(2400)*0.1,24000)
    sf.write(paths[1],np.ones(2400)*0.5,24000)
    assert len(compare_segment_levels(paths))==1
    assert compare_segment_levels([paths[0]])==[]
