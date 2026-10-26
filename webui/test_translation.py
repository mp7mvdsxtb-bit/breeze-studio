import pytest
from translation import LocalTranslator, TranslationBusy, split_description


def test_split_preserves_characters():
    text='清亮自然的声音，语气欢快。'*40
    chunks=split_description(text)
    assert chunks and all(len(c)<=160 for c in chunks)
    assert ''.join(chunks)==text


@pytest.mark.parametrize('text',['',None,123,{},'中'*601])
def test_invalid_inputs_preserve_model_unloaded(tmp_path,text):
    translator=LocalTranslator(tmp_path)
    with pytest.raises(ValueError):translator.translate(text)
    assert translator.model is None


def test_english_passes_through_without_loading(tmp_path):
    translator=LocalTranslator(tmp_path)
    assert translator.translate('A clear, bright American voice.')=='A clear, bright American voice.'
    assert translator.model is None


def test_concurrent_request_reports_busy(tmp_path):
    translator=LocalTranslator(tmp_path);translator.lock.acquire()
    try:
        with pytest.raises(TranslationBusy):translator.translate('欢快自然的女声')
    finally:translator.lock.release()


def test_missing_model_releases_lock(tmp_path):
    translator=LocalTranslator(tmp_path)
    with pytest.raises(RuntimeError):translator.translate('像一位在海边长大的旅行博主')
    assert not translator.lock.locked()


def test_voice_terms_and_negation_are_not_mistranslated(tmp_path):
    translator=LocalTranslator(tmp_path)
    result=translator.translate('清亮干净，语气欢快自然。不要沙哑，不要气泡音，要清晰、有活力。')
    assert 'Avoid rasp or hoarseness.' in result
    assert 'Avoid vocal fry.' in result
    assert 'Clear and articulate.' in result and 'Energetic.' in result
    assert 'bubbles' not in result and 'dummies' not in result
    assert translator.model is None


@pytest.mark.parametrize('text',['不沙哑','没有沙哑','不想有气泡音','低沉但不沙哑'])
def test_voice_negation_variants(tmp_path,text):
    result=LocalTranslator(tmp_path).translate(text)
    assert 'Avoid ' in result
