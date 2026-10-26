"""Offline Chinese-to-English translation for voice descriptions (CPU only).

Model: Helsinki-NLP/opus-mt-zh-en, University of Helsinki, CC-BY-4.0.
https://huggingface.co/Helsinki-NLP/opus-mt-zh-en
"""
from __future__ import annotations
import re
import threading
from collections import OrderedDict
from pathlib import Path


class TranslationBusy(Exception): pass


# Domain terms take precedence over the general translator: "气泡音" is
# vocal fry rather than bubbles, and negation must remain local to its clause.
VOICE_TERMS={
    '美式英语口音':'a standard American English accent','美式口音':'an American English accent','美式':'an American English accent',
    '英式英语口音':'a standard British English accent','英式口音':'a British English accent','英式':'a British English accent',
    '澳洲口音':'an Australian English accent','澳大利亚口音':'an Australian English accent',
    '年轻女性':'a young female voice','年轻男性':'a young male voice','女声':'a female voice','男声':'a male voice',
    '女性':'a female voice','男性':'a male voice','年轻':'youthful','成熟':'mature','中年':'middle-aged',
    '清晰':'clear and articulate','清楚':'clear and articulate','清亮':'clear and bright','干净':'clean',
    '通透':'clear and resonant','平滑':'smooth','圆润':'rounded and smooth','饱满':'full and resonant',
    '欢快':'cheerful and upbeat','活泼':'lively','有活力':'energetic','活力':'energy','温柔':'gentle',
    '亲切':'friendly','自然':'natural and conversational','自信':'confident','沉稳':'calm and grounded',
    '放松':'relaxed','轻松':'relaxed','专业':'professional','惊喜':'a sense of pleasant surprise',
    '太低沉':'an overly low or heavy register','低沉':'a low register','稍慢':'a slightly slower pace',
    '稍快':'a slightly faster pace','语速慢':'a slower speaking pace','语速快':'a brisk speaking pace',
    '语速中等':'a moderate speaking pace','吐字清晰':'clear articulation',
    '沙哑':'rasp or hoarseness','嘶哑':'hoarseness','烟嗓':'a husky or gravelly texture',
    '气泡音':'vocal fry','气声':'breathiness','耳语':'whispering','机械感':'robotic delivery',
    '太机械':'an overly mechanical delivery','机械':'robotic delivery','机器人':'robotic delivery','AI感':'an artificial-sounding delivery',
    '夸张':'exaggerated delivery','粗糙':'a rough vocal texture','有力量':'strong and confident',
}
PHRASES={
    '像向朋友推荐好物':'Speak conversationally, as if recommending a useful product to a friend.',
    '像给朋友推荐好物':'Speak conversationally, as if recommending a useful product to a friend.',
    '强调产品优势':"Emphasize the product's benefits.",
    '没有口音':'Use a neutral, standard English accent.',
}
TERM_PATTERN=re.compile('|'.join(re.escape(k) for k in sorted(VOICE_TERMS,key=len,reverse=True)))


def voice_clause(text):
    text=text.strip(' ，,。.!！?？；;\n')
    if text in PHRASES:return PHRASES[text]
    negative=re.match(r'^(?:声音|音色|声线|语气|并且|而且|也|请|尽量|希望)*(不要|避免|不带|不想要|不想有|不希望有|不需要|没有|不能|不用|别|无|不)(.*)$',text)
    body=negative[2] if negative else text
    matches=list(TERM_PATTERN.finditer(body))
    residue=TERM_PATTERN.sub('',body)
    residue=re.sub(r'一位|一个|说话|声音|音色|声线|语气|语速|表达|请|希望|要|可以|偏|比较|一点|一些|稍微|很|非常|并且|而且|且|和|的|有|带|但|更|尽量|[\s，,。.!！?？；;]','',residue)
    if matches and not residue:
        words=list(dict.fromkeys(VOICE_TERMS[m[0]] for m in matches))
        translated=', '.join(words)
        return ('Avoid '+translated if negative else translated[0].upper()+translated[1:])+'.'
    return None


def split_description(text,limit=160):
    chunks=[];current=''
    for sentence in re.split(r'(?<=[。！？；;\n])',text):
        sentence=sentence.strip()
        if not sentence:continue
        if current and len(current)+len(sentence)>limit:
            chunks.append(current);current=''
        if len(sentence)>limit:
            # Prefer punctuation for long descriptions before character boundaries.
            for piece in re.split(r'(?<=[，,])',sentence):
                if current and len(current)+len(piece)>limit:chunks.append(current);current=''
                while len(piece)>limit:
                    if current:chunks.append(current);current=''
                    chunks.append(piece[:limit]);piece=piece[limit:]
                current+=piece
        else:current+=sentence
    if current:chunks.append(current)
    return chunks


class LocalTranslator:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.Lock();self.model=None;self.tokenizer=None
        self.cache=OrderedDict()

    def _load(self):
        if self.model is not None:return
        if not (self.path/'pytorch_model.bin').is_file():
            raise RuntimeError('本地翻译模型尚未安装，请检查 translation-model 文件夹。')
        import torch
        from transformers import MarianMTModel, MarianTokenizer
        torch.set_num_threads(2)
        self.tokenizer=MarianTokenizer.from_pretrained(self.path,local_files_only=True)
        self.model=MarianMTModel.from_pretrained(self.path,local_files_only=True,dtype=torch.float32).to('cpu').eval()

    def translate(self,text):
        if not isinstance(text,str) or not text.strip():raise ValueError('请先填写中文声音描述。')
        text=text.strip()
        if len(text)>600:raise ValueError('中文声音描述最多 600 个字符，请精简后翻译。')
        if not re.search(r'[\u3400-\u9fff]',text):return text
        if not self.lock.acquire(blocking=False):raise TranslationBusy('已有翻译正在处理，请稍后再试。')
        try:
            if text in self.cache:
                self.cache.move_to_end(text);return self.cache[text]
            output=[]
            # Commas delimit independent requirements; do not let a preceding
            # "不要" invert a later positive requirement such as "要清晰".
            clauses=re.split(r'[，,、。；;\n]+',re.sub(r'(?:但是|但)(?=不|避免|别)','，',text))
            for clause in clauses:
                if not clause.strip():continue
                glossary=voice_clause(clause)
                if glossary:
                    output.append(glossary);continue
                self._load()
                import torch
                for chunk in split_description(clause):
                  with torch.inference_mode():
                    tokens=self.tokenizer(chunk,return_tensors='pt',truncation=False)
                    if tokens['input_ids'].shape[1]>512:raise ValueError('描述中的某一段过长，请增加标点或缩短内容。')
                    generated=self.model.generate(**tokens,num_beams=4,max_new_tokens=256,early_stopping=True)
                    if len(generated[0])>=257 and generated[0][-1].item()!=self.tokenizer.eos_token_id:
                        raise ValueError('译文可能过长，请拆短声音描述后再试。')
                    output.append(self.tokenizer.decode(generated[0],skip_special_tokens=True).strip())
            english=' '.join(output).strip()
            if not english or re.search(r'[\u3400-\u9fff]',english):
                raise RuntimeError('翻译结果不完整，请缩短或换一种中文描述后重试。')
            if len(english)>1500:raise ValueError('英文译文超过 1500 字符，请缩短中文描述后重试。')
            self.cache[text]=english
            while len(self.cache)>128:self.cache.popitem(last=False)
            return english
        finally:self.lock.release()
