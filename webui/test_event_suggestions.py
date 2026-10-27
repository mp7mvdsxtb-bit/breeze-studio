from event_suggestions import suggest


def test_no_events_for_neutral_product_ad():
    text='Small gaps can cause big headaches. A foil backing covers a self-adhesive butyl layer.'
    assert suggest(text)=={'suggestions':[],'proposed':text}


def test_suggestion_is_conservative_and_preserves_original():
    text="😀 This is the intro. That's so funny! I can finally relax."
    result=suggest(text)
    assert len(result['suggestions'])==1
    assert result['suggestions'][0]['tag']=='(laugh)'
    assert result['proposed'].replace('(laugh) ','',1)==text


def test_does_not_duplicate_existing_tags():
    text="(laugh) That's so funny!"
    assert suggest(text)['suggestions']==[]


def test_sigh_suggestion_for_clear_cue():
    result=suggest('What a relief. The work is done.')
    assert result['proposed']=='(sigh) What a relief. The work is done.'
