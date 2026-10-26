import io
import json
import threading
import time
import wave
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from email.parser import BytesParser
from urllib.parse import parse_qs

import numpy as np
import pytest
import soundfile as sf
from studio import Studio, split_text, validate_options, effective_instruction, DEFAULTS


def reference():
    buffer=io.BytesIO()
    sf.write(buffer,.1*np.sin(np.arange(24000)*.04),24000,format="WAV")
    buffer.seek(0)
    return buffer


@pytest.fixture
def engine(tmp_path):
    return Studio(tmp_path,"http://127.0.0.1:1")


@pytest.fixture
def backend():
    class Handler(BaseHTTPRequestHandler):
        slow=False
        calls=0
        fail=False
        busy=0
        requests=[]
        def log_message(self,*args): pass
        def do_POST(self):
            Handler.calls+=1
            body=self.rfile.read(int(self.headers['Content-Length']))
            if 'multipart/' in self.headers.get('Content-Type',''):
                message=BytesParser().parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
                fields={part.get_param('name',header='content-disposition'):part.get_payload(decode=True) for part in message.get_payload()}
            else:fields={k:v[0].encode() for k,v in parse_qs(body.decode(),keep_blank_values=True).items()}
            Handler.requests.append(fields)
            if Handler.busy:
                Handler.busy-=1;self.send_error(409,"previous stream cleanup");return
            if Handler.fail:
                self.send_error(500,"test failure"); return
            self.send_response(200);self.send_header('Content-Length','48000');self.end_headers()
            try:
                for _ in range(10):
                    self.wfile.write((np.sin(np.arange(2400)*.04)*3000).astype('<i2').tobytes());self.wfile.flush()
                    if Handler.slow:time.sleep(.03)
            except (ConnectionError,OSError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',Handler
    server.shutdown();server.server_close()


def wait(engine,job_id,status='complete'):
    for _ in range(150):
        job=engine.get(job_id)
        if job['status']==status:return job
        if job['status']=='error' and status!='error':raise AssertionError(job['error'])
        time.sleep(.02)
    raise AssertionError(engine.get(job_id))


@pytest.mark.parametrize('text',["Dr. Smith paid $2.50. It works! A friendly voice.","First line.\nSecond line!","Hello (clears throat), this is a test. "*30,"长文分段测试。"*100])
def test_segment_preserves_text(text):
    parts=split_text(text,100)
    assert parts and all(0<len(p)<=100 for p in parts)
    assert ''.join(''.join(parts).split())==''.join(text.split())


@pytest.mark.parametrize('options',[{'seed':1.2},{'top_k':True},{'top_p':float('nan')},{'temperature':0},{'mode':'unknown'},{'normalize':'yes'},{'variants':5},{'voice_id':'../../file'},{'bogus':1}])
def test_reject_invalid_parameters(options):
    with pytest.raises(ValueError):validate_options(options)


def test_clone_removes_instruction():
    opts=validate_options({'mode':'clone','instruction':'ignored','cfg_scale':5})
    assert opts['instruction']=='' and opts['cfg_scale']==1


def test_clear_profile_applies_to_old_recipes_but_not_pure_clone():
    options=validate_options({'instruction':'An upbeat American woman.'})
    assert options['tone_profile']=='clear'
    assert 'clean, clear, smooth' in effective_instruction(options,'Hello, friend.')
    assert 'Avoid rasp' in effective_instruction(options,'Hello, friend.')
    assert effective_instruction({**options,'mode':'clone'},'Hello')==''
    assert '圆润饱满' in effective_instruction({**options,'tone_profile':'full'},'你好，欢迎使用。')


def test_disliked_reference_cannot_be_reused_or_reuploaded(engine):
    voice=engine.save_voice('Reference','Hello, friend.',reference())
    j=engine.submit(['Hello, friend.'],{'mode':'direction','voice_id':voice['id']})
    audio=reference();(engine.output/(j['id']+'.wav')).write_bytes(audio.read())
    engine.update(j['id'],status='complete',result={'id':j['id'],'text':'Hello, friend.'})
    engine.reject_voice(j['id'])
    assert engine.list_voices()[0]['blocked']
    with pytest.raises(ValueError):engine.submit(['Again'],{'mode':'clone','voice_id':voice['id']})
    with pytest.raises(ValueError):engine.save_voice('Duplicate','Hello, friend.',reference())
    reloaded=Studio(engine.root,engine.backend)
    assert reloaded.voice_blocked(voice['id'])


def test_transaction_rejects_partial_batches(engine):
    with pytest.raises(ValueError):engine.submit(['hello',''],{})
    assert engine.list_jobs()['total']==0


def test_thousand_job_capacity_is_persistent_and_atomic(engine):
    assert engine.submit(['English script.']*200,{'variants':4})['count']==800
    assert engine.submit(['Another script.']*200,{})['count']==200
    with pytest.raises(ValueError):engine.submit(['Over capacity'],{})
    assert engine.counts()['queued']==1000
    reloaded=Studio(engine.root,engine.backend)
    assert reloaded.list_jobs(limit=25,offset=975)['total']==1000
    assert len(reloaded.list_jobs(limit=25,offset=975)['items'])==25


def test_simultaneous_bulk_submissions_cannot_overfill_queue(engine):
    from concurrent.futures import ThreadPoolExecutor
    def submit():
        try:return engine.submit(['English script.']*200,{'variants':3})['count']
        except ValueError:return 0
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(lambda _:submit(),range(2)))
    assert sorted(results)==[0,600]
    assert engine.counts()['queued']==600


def test_persistent_queue_and_interruption(engine):
    ids=engine.submit(['First','Second'],{'variants':2})['ids']
    assert len(ids)==4
    engine.update(ids[0],status='running')
    reloaded=Studio(engine.root,engine.backend)
    assert reloaded.get(ids[0])['status']=='interrupted'
    assert reloaded.get(ids[1])['status']=='queued'
    reloaded.retry(ids[0]);assert reloaded.get(ids[0])['status']=='queued'
    assert reloaded.get(ids[1])['options']['seed']==43


def test_voice_library(engine):
    voice=engine.save_voice('English voice','Hello world.',reference())
    reloaded=Studio(engine.root,engine.backend)
    assert reloaded.voice(voice['id'])['transcript']=='Hello world.'
    j=reloaded.submit(['A new sentence'],{'mode':'clone','voice_id':voice['id']})
    assert reloaded.get(j['id'])['options']['cfg_scale']==1


def test_sequential_queue_export_and_normalization(engine,backend):
    engine.backend,handler=backend
    submission=engine.submit(['Hello world. '*25,'Another example.'],{'segment_chars':100,'normalize':True,'pause_ms':200})
    engine.start(lambda:True)
    try:
        jobs=[wait(engine,i) for i in submission['ids']]
        assert jobs[0]['result']['segments']>1
        audio,rate=sf.read(engine.output/(jobs[0]['id']+'.wav'))
        assert rate==24000 and abs(np.max(np.abs(audio))-.89125)<.0001
        expected=jobs[0]['segment_count']+(jobs[0]['segment_count']-1)*.2
        assert abs(len(audio)/rate-expected)<.001
        archive=engine.export(submission['batch_id'])
        with zipfile.ZipFile(archive) as z:
            manifest=json.loads(z.read('manifest.json'));assert len(manifest)==2
            assert len([n for n in z.namelist() if n.endswith('.wav')])==2
        assert jobs[1]['started']>=jobs[0]['started']
    finally:engine.stop.set();engine.wake.set();engine.thread.join(3)


def test_design_later_segments_clone_same_first_segment(engine,backend):
    engine.backend,handler=backend
    j=engine.submit(['A cheerful introduction for your home. '*12],{'segment_chars':100})
    job=engine.get(j['id']);engine.process(job)
    assert engine.get(j['id'])['status']=='complete'
    requests=handler.requests
    assert len(requests)>2 and 'ref_audio' not in requests[0]
    anchor=(engine.output/(j['id']+'_parts')/'0000.wav').read_bytes()
    first=split_text(job['text'],100)[0].encode()
    for request in requests[1:]:
        assert request['ref_audio']==anchor and request['ref_text']==first
        assert request['instruction']==b'' and request['cfg_scale']==b'1'
    assert engine.get(j['id'])['result']['voice_consistency']=='first_segment_reference'


def test_legacy_retry_keeps_first_but_regenerates_later_segments(engine,backend):
    engine.backend,handler=backend
    j=engine.submit(['An introduction to a useful home product. '*8],{'segment_chars':100})
    parts=engine.output/(j['id']+'_parts');parts.mkdir()
    anchor=reference().read();(parts/'0000.wav').write_bytes(anchor)
    (parts/'0001.wav').write_bytes(anchor)
    engine.process(engine.get(j['id']))
    assert engine.get(j['id'])['status']=='complete'
    assert len(handler.requests)==engine.get(j['id'])['segment_count']-1
    assert list(parts.glob('0001.before-voice-lock.*.wav'))
    assert all(r['ref_audio']==anchor for r in handler.requests)
    calls=handler.calls
    engine.process(engine.get(j['id']))
    assert handler.calls==calls # New retries reuse the locked segments.


@pytest.mark.parametrize('mode',['clone','direction'])
def test_saved_reference_remains_same_for_all_segments(engine,backend,mode):
    engine.backend,handler=backend
    voice=engine.save_voice('Reference','Hello world.',reference())
    j=engine.submit(['A natural introduction to a useful home product. '*8],{'mode':mode,'voice_id':voice['id'],'segment_chars':100})
    engine.process(engine.get(j['id']))
    assert engine.get(j['id'])['status']=='complete'
    saved=(engine.voices/(voice['id']+'.wav')).read_bytes()
    assert all(r['ref_audio']==saved and r['ref_text']==b'Hello world.' for r in handler.requests)


def test_cancel_running_and_retry_reuses_finished_segments(engine,backend):
    engine.backend,handler=backend;handler.slow=True
    j=engine.submit(['One sentence. '*25],{'segment_chars':100})
    engine.start(lambda:True)
    try:
        wait(engine,j['id'],'running');engine.cancel(j['id']);wait(engine,j['id'],'cancelled')
        engine.set_setting('paused',True);engine.retry(j['id']);time.sleep(.1)
        assert engine.get(j['id'])['status']=='queued'
        engine.set_setting('paused',False);wait(engine,j['id'])
        calls=handler.calls
        # Keep completed parts but model a service restart before final completion.
        engine.update(j['id'],status='error');engine.retry(j['id']);wait(engine,j['id'])
        assert handler.calls==calls
    finally:engine.stop.set();engine.wake.set();engine.thread.join(3)


def test_failed_request_does_not_block_next_task(engine,backend):
    engine.backend,handler=backend;handler.fail=True
    j=engine.submit(['A failed example'],{})
    engine.start(lambda:True)
    try:
        wait(engine,j['id'],'error');handler.fail=False;engine.retry(j['id']);wait(engine,j['id'])
    finally:engine.stop.set();engine.wake.set();engine.thread.join(3)


def test_busy_after_cancellation_is_retried_without_failing(engine,backend):
    engine.backend,handler=backend;handler.busy=2
    j=engine.submit(['A request after cancellation'],{})
    engine.start(lambda:True)
    try:
        assert wait(engine,j['id'])['status']=='complete'
        assert handler.calls==3
    finally:engine.stop.set();engine.wake.set();engine.thread.join(3)
