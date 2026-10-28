import io
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from studio import Studio
from script_check import check
import server


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'studio',Studio(tmp_path,'http://127.0.0.1:1'))
    return TestClient(server.app)


def add_voice():
    buffer=io.BytesIO();sf.write(buffer,np.sin(np.arange(24000)*.06)*.1,24000,format='WAV');buffer.seek(0)
    return server.studio.save_voice('Test voice','Hello there.',buffer)


def test_voice_profile_updates_without_losing_audio_or_reference(client):
    voice=add_voice();voice_id=voice['id'];path=server.studio.voices/(voice_id+'.wav');audio=path.read_bytes()
    response=client.patch('/api/voices/'+voice_id,json={'name':'Warm','category':'American','notes':'Good for products','style_description':'Natural','favorite':True,'recommended_options':{'mode':'design'}})
    assert response.status_code==200
    profile=response.json();assert profile['favorite'] and profile['category']=='American'
    assert profile['transcript']=='Hello there.' and path.read_bytes()==audio
    assert client.patch('/api/voices/'+voice_id,json={'favorite':'yes'}).status_code==400
    assert client.patch('/api/voices/'+voice_id,json={'transcript':'changed silently'}).status_code==400
    assert client.get('/api/voices').json()[0]['notes']=='Good for products'


def test_default_voice_persists_and_deleted_default_is_cleared(client):
    voice=add_voice();vid=voice['id']
    assert client.put('/api/default-voice',json={'voice_id':vid}).status_code==200
    assert client.get('/api/config').json()['default_voice_id']==vid
    reloaded=Studio(server.studio.root,server.studio.backend)
    assert reloaded.setting('default_voice_id','')==vid
    assert client.delete('/api/voices/'+vid).status_code==200
    assert client.get('/api/config').json()['default_voice_id']==''
    assert client.put('/api/default-voice',json={'voice_id':vid}).status_code==400


def test_blocked_voice_cannot_become_default(client):
    voice=add_voice();server.studio.set_setting('blocked_voice_ids',[voice['id']])
    assert client.put('/api/default-voice',json={'voice_id':voice['id']}).status_code==400


def test_english_suggestions_are_optional_and_offsets_handle_unicode(client):
    text='😀 Now $89.90 for 750 ml, with 50% off.'
    data=client.post('/api/script-check',json={'text':text}).json()
    by_original={item['original']:item for item in data['suggestions']}
    assert by_original['$89.90']['replacement']=='eighty-nine dollars and ninety cents'
    assert by_original['750 ml']['replacement']=='seven hundred fifty milliliters'
    assert by_original['50%']['replacement']=='fifty percent'
    assert all(text[s['start']:s['end']]==s['original'] for s in data['suggestions'])
    assert text=='😀 Now $89.90 for 750 ml, with 50% off.'


def test_unknown_number_or_symbols_are_not_silently_rewritten():
    result=check('Item 89.90 and \ufffd')
    assert result['suggestions']==[]
    assert len(result['issues'])>=2


def test_price_with_ambiguous_separators_is_flagged_without_guessing():
    result=check('Save $1,234.56 today.')
    assert not result['suggestions']
    assert any('数字' in issue for issue in result['issues'])


def test_large_units_and_percentages_are_not_partially_rewritten():
    result=check('Contains 1,234 ml and increases by 1,250%.')
    assert not result['suggestions']
    assert any('数字' in issue for issue in result['issues'])
