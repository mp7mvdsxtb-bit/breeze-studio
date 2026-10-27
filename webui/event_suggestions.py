"""Conservative, transparent English event placement suggestions."""
import re

MARKER=re.compile(r'\((?:laugh|sigh|cough|clears throat)\)|\[(?:笑|叹气|咳嗽|清嗓子)\]',re.I)
RULES=[
    (re.compile(r"\b(?:that(?:'s| is| was) (?:so )?funny|(?:i|we) (?:can(?:'t|not) stop|couldn(?:'t| not) stop) laughing|(?:i|we) (?:laughed|couldn(?:'t| not) help laughing))\b",re.I),'(laugh)','这里直接表达了发笑，可尝试加一声轻笑。'),
    (re.compile(r"\b(?:what a relief|such a relief|a sigh of relief|(?:i|we) can finally relax|phew)\b",re.I),'(sigh)','这里表达松了一口气，可尝试加一声轻叹。'),
]


def suggest(text):
    if not isinstance(text,str) or not text.strip() or len(text)>30000:raise ValueError('请填写不超过 30000 字的文案。')
    # These are heuristics, not emotion recognition; ordinary product claims
    # and neutral sentences intentionally receive no proposed vocal events.
    cap=min(3,max(1,len(re.findall(r'\b[\w\']+\b',text))//100+1))
    suggestions=[]
    for sentence in re.finditer(r'[^.!?\n]+(?:[.!?]+|(?=\n|$))',text):
        raw=sentence.group(); stripped=raw.lstrip(); start=sentence.start()+len(raw)-len(stripped)
        if not stripped or MARKER.search(raw):continue
        for pattern,tag,reason in RULES:
            if pattern.search(raw):
                suggestions.append({'tag':tag,'reason':reason,'sentence':stripped.strip()[:200],'position':start})
                break
        if len(suggestions)>=cap:break
    proposed=text
    for item in reversed(suggestions):
        pos=item['position'];proposed=proposed[:pos]+item['tag']+' '+proposed[pos:]
    return {'suggestions':suggestions,'proposed':proposed}
