"""Non-destructive English reading suggestions. Human approval required."""
import re

ONES=['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen']
TENS=['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety']


def number(value):
    n=int(value)
    if not 0<=n<=999:raise ValueError('number out of range')
    if n<20:return ONES[n]
    if n<100:return TENS[n//10]+('-'+ONES[n%10] if n%10 else '')
    return ONES[n//100]+' hundred'+(' '+number(n%100) if n%100 else '')


def check(text):
    if not isinstance(text,str) or not text.strip() or len(text)>30000:raise ValueError('请填写不超过 30000 字的文案。')
    issues=[];suggestions=[]
    if '\ufffd' in text:issues.append('发现替换字符 �，原文可能存在编码损坏，请检查。')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',text):issues.append('发现不可见控制字符，请检查导入文本。')
    sentences=re.split(r'(?<=[.!?。！？])\s+|\n+',text)
    if any(len(s.strip())>250 for s in sentences):issues.append('有句子超过 250 个字符，建议检查标点或适当拆句。')
    if re.search(r'[A-Za-z0-9]["\'”’)]?\s*$',text):issues.append('结尾没有句号、问号或感叹号，可检查语气。')
    if re.search(r'(?<![\w$])\d{1,6}\.\d+(?!\w)',text):issues.append('发现没有明确单位的小数，请确认是价格、小数还是编号，再决定读法。')
    patterns=[
        (re.compile(r'(?<![\w$])\$(\d{1,3})\.(\d{2})(?!\d)'), 'price'),
        (re.compile(r'(?<![\w.,])(\d{1,3})\s*(ml|mL|ML)\b'), 'unit'),
        (re.compile(r'(?<![\w.,])(\d{1,3})\s*%(?!\w)'), 'percent'),
    ]
    for pattern,kind in patterns:
        for m in pattern.finditer(text):
            if kind=='price':
                dollars=int(m.group(1));cents=int(m.group(2))
                spoken=number(dollars)+(' dollar' if dollars==1 else ' dollars')
                if cents:spoken+=' and '+number(cents)+(' cent' if cents==1 else ' cents')
                reason='按美元金额读法建议；请确认币种和价格。'
            elif kind=='unit':
                n=int(m.group(1));spoken=number(n)+(' milliliter' if n==1 else ' milliliters');reason='毫升的美式英语读法，请核对数值。'
            else:spoken=number(m.group(1))+' percent';reason='百分比读法，请核对数值。'
            suggestions.append({'start':m.start(),'end':m.end(),'original':m.group(),'replacement':spoken,'reason':reason})
    suggestions.sort(key=lambda x:x['start'])
    for match in re.finditer(r'(?<![\w])\d+(?:[.,]\d+)*(?![\w])',text):
        if not any(item['start']<=match.start() and item['end']>=match.end() for item in suggestions):
            issues.append('存在未自动展开的数字，请核对年份、型号、价格或编号的实际读法。')
            break
    return {'issues':issues,'suggestions':suggestions[:100]}
