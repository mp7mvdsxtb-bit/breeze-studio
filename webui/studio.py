"""Durable sequential production queue; no GPU imports in the web process."""
from __future__ import annotations
import csv
import io
import hashlib
import json
import math
import re
import sqlite3
import threading
import time
import uuid
import wave
import zipfile
from contextlib import contextmanager
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

PRESETS = [
    {"id":"ugc", "name":"美式 UGC · 欢快推荐", "instruction":"A cheerful young American woman sharing a useful find with a friend. Bright smiling voice, spontaneous conversational rhythm, expressive pitch changes and playful emphasis. Enthusiastic but believable, not a formal announcer."},
    {"id":"friendly", "name":"美式女声 · 自然介绍", "instruction":"A friendly American English woman speaking naturally to one listener. Warm clear voice, relaxed connected speech, varied emphasis and an easy conversational pace."},
    {"id":"male", "name":"美式男声 · 沉稳可信", "instruction":"A confident American English male narrator with a warm lower register. Conversational, grounded and trustworthy. Clear pronunciation, subtle expressive emphasis and a natural unhurried pace."},
    {"id":"british", "name":"英式英语 · 优雅讲述", "instruction":"A warm British English woman with a contemporary standard Southern British accent. Understated, articulate and conversational, with gentle melodic phrasing and a relaxed pace."},
    {"id":"demo", "name":"产品演示 · 清楚利落", "instruction":"An approachable American English product demonstrator. Explain each step clearly with natural connected speech, purposeful pauses and lively emphasis on practical details. Friendly and helpful."},
    {"id":"story", "name":"故事旁白 · 生动温暖", "instruction":"An expressive American English storyteller. Warm intimate voice, varied pacing, thoughtful pauses, vivid emotional phrasing and a conversational storytelling rhythm."},
    {"id":"energetic", "name":"活力男声 · 明亮有劲", "instruction":"An upbeat young American English man with an energetic smiling voice. Playful conversational emphasis, lively pitch variation and brisk but clear connected speech."},
    {"id":"calm", "name":"舒缓女声 · 轻柔自然", "instruction":"A gentle American English woman speaking calmly and warmly. Soft clear tone, unhurried pacing, subtle natural expression, like a reassuring conversation."},
]
DEFAULTS = {"mode":"design", "instruction":PRESETS[0]["instruction"], "cfg_scale":4,
            "seed":42, "temperature":0.9, "top_p":1.0, "top_k":50,
            "repetition_penalty":1.1, "max_new_tokens":750, "segment_chars":350,
            "pause_ms":180, "variants":1, "voice_id":"", "normalize":False,"do_sample":True,"tone_profile":"clear"}
TERMINAL = {"complete", "error", "cancelled", "interrupted"}


def vocal_event_instruction(text):
    """Only request the model's documented inline events, at their marked positions."""
    events=[(r'\(laugh\)|\[笑\]', 'At each (laugh) or [笑] marker, produce a clearly audible short natural laugh or chuckle, not only a smiling speaking tone.'),
            (r'\(sigh\)|\[叹气\]', 'At each (sigh) or [叹气] marker, produce a clearly audible relaxed exhaled sigh before continuing the words.'),
            (r'\(cough\)|\[咳嗽\]', 'At each (cough) or [咳嗽] marker, produce a short audible cough.'),
            (r'\(clears throat\)|\[清嗓子\]', 'At each (clears throat) or [清嗓子] marker, audibly clear the throat briefly.')]
    instructions=[instruction for pattern,instruction in events if re.search(pattern,text,re.I)]
    if not instructions:return ''
    return ('Vocal event direction: Keep the same speaker identity and accent. '+ ' '.join(instructions)+
            ' Perform only the marked events, in order, as nonverbal sounds; do not speak the tag names. Resume the same clear speaking voice after each event.')


def effective_instruction(options, text):
    event_direction=vocal_event_instruction(text)
    if options['mode']=='clone': return event_direction
    profile=options.get('tone_profile','clear')
    english=len(re.findall('[A-Za-z]',text))>=len(re.findall('[\u4e00-\u9fff]',text))
    if english:
        quality=("Voice quality priority: a clean, clear, smooth, fully voiced and bright tone, with easy phonation and crisp articulation. "
                 if profile=='clear' else
                 "Voice quality priority: a clean, smooth, rounded, fully voiced and resonant tone, with easy phonation and clear articulation. ")
        quality+="Keep the delivery lively and natural. "
        quality+=("For spoken words only: " if event_direction else '')+"Avoid rasp, hoarseness, gravelly texture, creaky vocal fry, whispering and excessive breathiness."
    else:
        quality='音色优先要求：清亮干净、平滑通透、自然实声、吐字清楚；保持生动自然，避免沙哑、烟嗓、粗粝、气泡音、耳语和过多气声。'
        if profile=='full':quality=quality.replace('清亮干净、平滑通透','圆润饱满、干净平滑')
        if event_direction:quality='以下音质限制仅用于正常说话，不限制标记处的笑声、叹气、咳嗽或清嗓子：'+quality
    if event_direction:quality+=' Tagged nonverbal events may use their natural breath and texture. '+event_direction
    return options['instruction'].strip()+'\n\n'+quality


def audio_signature(path):
    samples,rate=sf.read(path,dtype='int16',always_2d=True)
    return hashlib.sha256(str(rate).encode()+str(samples.shape[1]).encode()+samples.tobytes()).hexdigest()


def split_text(text: str, limit: int = 350) -> list[str]:
    """Sentence boundaries first; preserve decimals, abbreviations and event tags."""
    text = text.strip()
    if not text:
        return []
    # Protect common English abbreviations and decimals before sentence detection.
    protected = re.sub(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e)\.",
                       lambda m: m[0].replace('.', '\ue000'), text, flags=re.I)
    protected = re.sub(r"(?<=\d)\.(?=\d)", '\ue000', protected)
    protected = re.sub(r"\b[A-Z]\.(?=[A-Z]\.)", lambda m:m[0].replace('.', '\ue000'), protected)
    pieces = re.split(r"(?<=[.!?。！？])\s+|\n+", protected)
    output, current = [], ""
    for piece in pieces:
        piece = piece.replace('\ue000', '.').strip()
        # Event markers stay intact. Extremely long words are split as a last resort.
        tokens = re.findall(r"\([^)]*\)|\[[^\]]*\]|\S+", piece)
        for token in tokens:
            if len(token) > limit:
                if current:
                    output.append(current); current = ""
                output.extend(token[i:i+limit] for i in range(0, len(token), limit))
            elif len(current) + len(token) + bool(current) > limit:
                output.append(current); current = token
            else:
                current = (current + " " + token).strip()
        if current and len(current) >= limit * .55:
            output.append(current); current = ""
    if current:
        output.append(current)
    return output


def validate_options(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("参数必须为对象")
    if set(raw) - set(DEFAULTS):
        raise ValueError("存在不支持的参数")
    options = {**DEFAULTS, **raw}
    ranges = {"cfg_scale":(1,6),"seed":(0,2147483647),"temperature":(.1,2),
              "top_p":(.05,1),"top_k":(1,1000),"repetition_penalty":(1,2),
              "max_new_tokens":(1,1500),"segment_chars":(100,500),"pause_ms":(0,2000),"variants":(1,4)}
    integers = {"seed","top_k","max_new_tokens","segment_chars","pause_ms","variants"}
    for key,(low,high) in ranges.items():
        v=options[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not low<=v<=high:
            raise ValueError(f"{key} 必须在 {low}–{high} 之间")
        if key in integers:
            if int(v)!=v: raise ValueError(f"{key} 必须是整数")
            options[key]=int(v)
    if not isinstance(options["mode"],str) or options["mode"] not in {"design","clone","direction"}:
        raise ValueError("生成模式不正确")
    if not isinstance(options["instruction"],str) or len(options["instruction"])>1500:
        raise ValueError("声音描述过长或格式不正确")
    options["instruction"]=options["instruction"].strip()
    if options["mode"]!="clone" and not options["instruction"]:
        raise ValueError("请填写声音描述或选择英语预设")
    if not isinstance(options["voice_id"],str) or (options["voice_id"] and not re.fullmatch(r"[0-9a-f]{32}",options["voice_id"])):
        raise ValueError("参考声音 ID 不正确")
    if not isinstance(options["normalize"],bool): raise ValueError("normalize 必须为布尔值")
    if not isinstance(options["do_sample"],bool): raise ValueError("do_sample 必须为布尔值")
    if options['tone_profile'] not in ('clear','full'): raise ValueError('请选择清亮或圆润音色')
    if options["mode"]=="clone": options.update(instruction="",cfg_scale=1)
    if options["mode"]=="design": options["voice_id"]=""
    return options


class Studio:
    def __init__(self, root: Path, backend: str):
        self.root, self.backend = Path(root), backend
        self.output=self.root/"outputs"/"studio"; self.output.mkdir(parents=True,exist_ok=True)
        self.voices=self.output/"voices"; self.voices.mkdir(exist_ok=True)
        self.db=self.output/"studio.sqlite3"
        self.lock=threading.RLock(); self.wake=threading.Event(); self.stop=threading.Event()
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,batch_id TEXT,status TEXT,created REAL,data TEXT);
            CREATE TABLE IF NOT EXISTS voices(id TEXT PRIMARY KEY,data TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);""")
            for row in db.execute("SELECT id,data FROM jobs WHERE status IN ('running','cancelling')").fetchall():
                data=json.loads(row[1]); data.update(status="interrupted",error="服务已重启，点击重试可从已完成分段继续。")
                db.execute("UPDATE jobs SET status='interrupted',data=? WHERE id=?",(json.dumps(data,ensure_ascii=False),row[0]))
            legacy=self.output/"history.json"
            if legacy.exists():
                for r in json.loads(legacy.read_text("utf-8")):
                    data={"id":r["id"],"batch_id":"legacy","status":"complete","created":r["created"],
                          "title":r["text"][:70],"text":r["text"],"result":r,"options":{**DEFAULTS,**{k:r[k] for k in DEFAULTS if k in r}}}
                    db.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?)",(r["id"],"legacy","complete",r["created"],json.dumps(data,ensure_ascii=False)))
        self.thread=None

    def connect(self):
        db=sqlite3.connect(self.db,timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def setting(self,key,default=False):
        with self.lock,self.connect() as db:
            row=db.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        with self.lock,self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",(key,json.dumps(value)))
        self.wake.set()

    def get(self,job_id):
        with self.lock,self.connect() as db:
            row=db.execute("SELECT data FROM jobs WHERE id=?",(job_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def update(self,job_id,**changes):
        with self.lock,self.connect() as db:
            row=db.execute("SELECT data FROM jobs WHERE id=?",(job_id,)).fetchone()
            data=json.loads(row[0]); data.update(changes)
            db.execute("UPDATE jobs SET status=?,data=? WHERE id=?",(data["status"],json.dumps(data,ensure_ascii=False),job_id))
            return data

    def list_jobs(self,limit=50,offset=0,search="",status=""):
        clauses=[]; args=[]
        if search: clauses.append("json_extract(data,'$.text') LIKE ?"); args.append('%'+search+'%')
        if status: clauses.append("status=?"); args.append(status)
        where=" WHERE "+" AND ".join(clauses) if clauses else ""
        with self.lock,self.connect() as db:
            total=db.execute("SELECT COUNT(*) FROM jobs"+where,args).fetchone()[0]
            rows=db.execute("SELECT data FROM jobs"+where+" ORDER BY created DESC LIMIT ? OFFSET ?",args+[limit,offset]).fetchall()
        return {"items":[json.loads(r[0]) for r in rows],"total":total}

    def counts(self):
        with self.lock,self.connect() as db:
            return dict(db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))

    def voice(self,voice_id):
        with self.lock,self.connect() as db:
            row=db.execute("SELECT data FROM voices WHERE id=?",(voice_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def list_voices(self):
        with self.lock,self.connect() as db:
            voices=[json.loads(r[0]) for r in db.execute("SELECT data FROM voices ORDER BY rowid DESC")]
        for voice in voices:voice['blocked']=self.voice_blocked(voice['id'])
        return voices

    def delete_voice(self,voice_id):
        if not re.fullmatch(r'[0-9a-f]{32}',voice_id):raise ValueError('声音编号无效')
        with self.lock,self.connect() as db:
            if not db.execute('SELECT 1 FROM voices WHERE id=?',(voice_id,)).fetchone():
                raise KeyError('声音不存在或已删除')
            pending=db.execute("SELECT data FROM jobs WHERE status IN ('queued','running','cancelling')").fetchall()
            if any(json.loads(row[0])['options'].get('voice_id')==voice_id for row in pending):
                raise ValueError('排队中或正在运行的任务正在使用这个声音，请等待完成或取消任务后再删除。')
            (self.voices/(voice_id+'.wav')).unlink(missing_ok=True)
            db.execute('DELETE FROM voices WHERE id=?',(voice_id,))
        return {'deleted':True,'id':voice_id}

    def voice_blocked(self,voice_id):
        if voice_id in self.setting('blocked_voice_ids',[]):return True
        blocked=self.setting('blocked_audio_signatures',[])
        path=self.voices/(voice_id+'.wav')
        return bool(blocked and path.exists() and audio_signature(path) in blocked)

    def reject_voice(self,job_id):
        with self.lock:
            job=self.get(job_id)
            if not job or job['status']!='complete':raise ValueError('请选择已生成的音频')
            blocked=set(self.setting('blocked_audio_signatures',[]))
            paths=[self.output/(job_id+'.wav')]
            voice_id=job['options'].get('voice_id','')
            if voice_id:
                ids=set(self.setting('blocked_voice_ids',[]));ids.add(voice_id)
                self.set_setting('blocked_voice_ids',sorted(ids))
                paths.append(self.voices/(voice_id+'.wav'))
            for path in paths:
                if path.exists():blocked.add(audio_signature(path))
            self.set_setting('blocked_audio_signatures',sorted(blocked))
            result={**job['result'],'quality_feedback':'avoid_voice'}
            self.update(job_id,result=result,quality_feedback='avoid_voice')

    def save_voice(self,name,transcript,source):
        if not name.strip() or len(name)>80 or not transcript.strip() or len(transcript)>3000:
            raise ValueError("请填写声音名称和准确参考文字（最多 3000 字）")
        samples,rate=sf.read(source,always_2d=True,dtype="float32")
        duration=len(samples)/rate
        if not .5<=duration<=60 or not np.isfinite(samples).all():
            raise ValueError("参考音频长度须为 0.5–60 秒，且无损坏数据")
        voice_id=uuid.uuid4().hex
        # Save a canonical mono WAV, independent of uploaded extension.
        target=self.voices/(voice_id+".wav")
        sf.write(target,samples.mean(axis=1),rate,subtype="PCM_16")
        if audio_signature(target) in self.setting('blocked_audio_signatures',[]):
            target.unlink(missing_ok=True)
            raise ValueError('这份音频已被标记为不喜欢的音色，请换用清亮的参考声音。')
        data={"id":voice_id,"name":name.strip(),"transcript":transcript.strip(),"duration":round(duration,2),"created":time.time(),"url":"/voices/"+voice_id+".wav"}
        try:
            with self.lock,self.connect() as db: db.execute("INSERT INTO voices VALUES(?,?)",(voice_id,json.dumps(data,ensure_ascii=False)))
        except BaseException:
            target.unlink(missing_ok=True); raise
        return data

    def submit(self,texts,options):
        options=validate_options(options)
        if not isinstance(texts,list) or not 1<=len(texts)<=200:
            raise ValueError("每批支持 1–200 条文本")
        if any(not isinstance(t,str) or not t.strip() or len(t)>30000 for t in texts):
            raise ValueError("每条文本须为 1–30000 个字符")
        if sum(map(len,texts))>200000: raise ValueError("单批总文本不能超过 200000 字符")
        if options["mode"]!="design" and not self.voice(options["voice_id"]):
            raise ValueError("请选择已保存的参考声音")
        if options['voice_id'] and self.voice_blocked(options['voice_id']):
            raise ValueError('这份参考声音已标记为不再复用，请更换参考声音，或使用清亮声音设计。')
        batch_id=uuid.uuid4().hex; ids=[]
        with self.lock,self.connect() as db:
            if options['mode']!='design' and not self.voice(options['voice_id']):
                raise ValueError('参考声音已删除，请重新选择声音。')
            pending=db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running','cancelling')").fetchone()[0]
            if pending+len(texts)*options["variants"]>1000: raise ValueError("待处理队列上限为 1000 项")
            for i,text in enumerate(texts):
                for variant in range(options["variants"]):
                    job_id=uuid.uuid4().hex; ids.append(job_id)
                    opts={**options,"seed":(options["seed"]+variant)%2147483648}
                    data={"id":job_id,"batch_id":batch_id,"status":"queued","created":time.time(),"text":text.strip(),
                          "title":f"{i+1:03d}"+(f" · V{variant+1}" if options['variants']>1 else '')+" · "+text.strip()[:60],
                          "options":opts,"segment_count":len(split_text(text,opts["segment_chars"])),"segments_done":0,"audio_seconds":0,"attempts":0}
                    db.execute("INSERT INTO jobs VALUES(?,?,?,?,?)",(job_id,batch_id,"queued",data["created"],json.dumps(data,ensure_ascii=False)))
        self.wake.set()
        return {"id":ids[0],"ids":ids,"batch_id":batch_id,"count":len(ids)}

    def cancel(self,job_id):
        with self.lock:
            job=self.get(job_id)
            if not job: raise ValueError("任务不存在")
            if job["status"] in {"queued","running","cancelling"}:
                self.update(job_id,status="cancelling" if job["status"]!="queued" else "cancelled")

    def retry(self,job_id):
        with self.lock:
            job=self.get(job_id)
            if not job or job["status"] not in {"error","cancelled","interrupted"}:
                raise ValueError("只有失败、取消或中断的任务可以重试")
            if job['options']['mode']!='design' and not self.voice(job['options']['voice_id']):
                raise ValueError('任务使用的参考声音已删除，请选择其他声音后新建任务。')
            self.update(job_id,status="queued",error="",audio_seconds=0)
        self.wake.set()

    def start(self,ready):
        self.ready=ready
        self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start()

    def run(self):
        while not self.stop.is_set():
            job=None
            if self.ready() and not self.setting("paused"):
                with self.lock,self.connect() as db:
                    row=db.execute("SELECT id,data FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                    if row:
                        job=json.loads(row[1]);job.update(status="running",started=time.time(),attempts=job.get("attempts",0)+1)
                        db.execute("UPDATE jobs SET status='running',data=? WHERE id=?",(json.dumps(job,ensure_ascii=False),row[0]))
            if job:
                self.process(job)
            else:
                self.wake.wait(1); self.wake.clear()

    def cancelled(self,job_id):
        return self.stop.is_set() or self.get(job_id)["status"]=="cancelling"

    @contextmanager
    def speech_response(self,client,data,files,reference,job_id):
        # A disconnected stream may still be finishing its current GPU step.
        # Retry only the explicitly rejected request, never a partially streamed one.
        for _ in range(240):
            if self.cancelled(job_id): raise InterruptedError()
            if reference: reference.seek(0)
            with client.stream("POST",self.backend+"/v1/audio/speech",data=data,files=files) as response:
                if response.status_code!=409:
                    self.update(job_id,waiting_model=False)
                    yield response
                    return
                response.read()
            self.update(job_id,waiting_model=True)
            if self.stop.wait(.5): raise InterruptedError()
        raise RuntimeError("模型持续忙碌超过两分钟，请停止其他模型请求后重试。")

    def process(self,job):
        started=time.monotonic(); job_id=job["id"]; o=job["options"]
        parts_dir=self.output/(job_id+"_parts");parts_dir.mkdir(exist_ok=True)
        chunks=split_text(job["text"],o["segment_chars"]); warnings=[]; parts=[]
        target=self.output/(job_id+".wav"); temporary=target.with_suffix(".wav.partial")
        try:
            if o.get('voice_id') and self.voice_blocked(o['voice_id']):
                raise ValueError('参考声音已被标记为不再复用，请更换声音后新建任务。')
            if vocal_event_instruction(job['text']) and job.get('vocal_event_guidance')!=1:
                for index in range(len(chunks)):
                    legacy=parts_dir/f'{index:04d}.wav'
                    if legacy.exists():legacy.rename(parts_dir/f'{index:04d}.before-event-guidance.{time.time_ns()}.wav')
                self.update(job_id,vocal_event_guidance=1,segments_done=0)
            lock_designed_voice=o['mode']=='design' and len(chunks)>1
            if lock_designed_voice and job.get('segment_voice_lock')!=1:
                # Legacy retries may contain independently designed later segments.
                # Keep the original first segment and archive the incompatible rest.
                for index in range(1,len(chunks)):
                    legacy=parts_dir/f'{index:04d}.wav'
                    if legacy.exists():legacy.rename(parts_dir/f'{index:04d}.before-voice-lock.{time.time_ns()}.wav')
                self.update(job_id,segment_voice_lock=1,segments_done=0)
            for i,text in enumerate(chunks):
                if self.cancelled(job_id): raise InterruptedError()
                part=parts_dir/f"{i:04d}.wav"
                if not part.exists():
                    previous_seconds=sum(sf.info(p).duration for p in parts)
                    tuning={key:o.get(key,DEFAULTS[key]) for key in ("temperature","top_p","top_k","repetition_penalty","max_new_tokens","do_sample")}
                    data={"text":text,"instruction":effective_instruction(o,text),"cfg_scale":str(o["cfg_scale"]),
                          "seed":str(o["seed"]),"controls":json.dumps(tuning)}
                    event_direction=vocal_event_instruction(text)
                    if o['mode']=='clone' and event_direction:data['cfg_scale']='2'
                    voice=self.voice(o["voice_id"]) if o["voice_id"] else None
                    ref_file=None
                    try:
                        files=None
                        if voice:
                            ref_file=(self.voices/(voice['id']+".wav")).open("rb")
                            files={"ref_audio":("reference.wav",ref_file,"audio/wav")};data["ref_text"]=voice["transcript"]
                        elif lock_designed_voice and i>0:
                            # Always anchor to the same first segment, never chain
                            # the preceding segment: chaining accumulates voice drift.
                            anchor=parts_dir/'0000.wav'
                            duration=sf.info(anchor).duration
                            if not .5<=duration<=60:
                                raise ValueError('首段音频须为 0.5–60 秒才能固定音色，请调整分段长度后新建任务。')
                            if duration>=o['max_new_tokens']/12.5-.16:
                                raise ValueError('首段可能达到生成长度上限，无法可靠用作声音参考；请缩短分段或提高生成长度上限。')
                            ref_file=anchor.open('rb')
                            files={'ref_audio':('first-segment.wav',ref_file,'audio/wav')}
                            data.update(ref_text=chunks[0],instruction=event_direction,cfg_scale='2' if event_direction else '1')
                        with httpx.Client(timeout=httpx.Timeout(900,connect=10),trust_env=False) as client:
                            with self.speech_response(client,data,files,ref_file,job_id) as response:
                                if response.status_code!=200:
                                    response.read();raise RuntimeError(f"模型返回 HTTP {response.status_code}：{response.text[:400]}")
                                count=0; part_tmp=part.with_suffix(".partial")
                                with wave.open(str(part_tmp),"wb") as out:
                                    out.setparams((1,2,24000,0,"NONE","not compressed"))
                                    for pcm in response.iter_bytes():
                                        if self.cancelled(job_id): raise InterruptedError()
                                        out.writeframesraw(pcm);count+=len(pcm)
                                        self.update(job_id,audio_seconds=round(previous_seconds+count/48000,2),current_segment=i+1)
                                if count<480 or count%2: raise RuntimeError("模型返回了空或不完整的音频")
                                part_tmp.replace(part)
                    finally:
                        if ref_file: ref_file.close()
                info=sf.info(part)
                if info.duration>=o["max_new_tokens"]/12.5-.16:
                    warnings.append(f"第 {i+1} 段可能达到长度上限，请试听检查结尾，缩短分段后重新生成。")
                parts.append(part);self.update(job_id,segments_done=i+1)
            if self.cancelled(job_id): raise InterruptedError()
            with wave.open(str(temporary),"wb") as output:
                output.setparams((1,2,24000,0,"NONE","not compressed"))
                for i,path in enumerate(parts):
                    with wave.open(str(path),"rb") as source:
                        while pcm:=source.readframes(24000*8): output.writeframesraw(pcm)
                    if i+1<len(parts): output.writeframesraw(b'\0\0'*int(24*o["pause_ms"]))
            if o["normalize"]:
                audio,rate=sf.read(temporary,dtype="float32");peak=float(np.max(np.abs(audio)))
                if peak>1e-6: sf.write(temporary,audio*(.89125/peak),rate,format="WAV",subtype="PCM_16")
            if self.cancelled(job_id): raise InterruptedError()
            temporary.replace(target)
            info=sf.info(target)
            record={"id":job_id,"text":job["text"],"instruction":o["instruction"],"mode":o["mode"],
                    "seed":o["seed"],"cfg_scale":o["cfg_scale"],"duration":round(info.duration,2),
                    "elapsed":round(time.monotonic()-started,1),"created":time.time(),"url":"/audio/"+target.name,
                    "warnings":warnings,"segments":len(parts),"options":o,
                    "voice_consistency":"first_segment_reference" if lock_designed_voice else "saved_reference" if o.get('voice_id') else "single_segment",
                    "vocal_event_guidance":bool(vocal_event_instruction(job['text'])),
                    "effective_instruction":effective_instruction(o,job['text'])}
            self.update(job_id,status="complete",result=record,error="",audio_seconds=record["duration"])
        except InterruptedError:
            self.update(job_id,status="interrupted" if self.stop.is_set() else "cancelled",error="已停止；已完成分段保留，可重试续作。")
        except Exception as exc:
            message=str(exc)
            if "out of memory" in message.lower(): message="显存不足，请关闭其他 GPU 程序，降低分段长度，然后重试。"
            self.update(job_id,status="error",error=message)
        finally:
            temporary.unlink(missing_ok=True)

    def export(self,batch_id=None):
        with self.lock,self.connect() as db:
            rows=db.execute("SELECT data FROM jobs WHERE status='complete'"+(" AND batch_id=?" if batch_id else "")+" ORDER BY created",(batch_id,) if batch_id else ()).fetchall()
        records=[json.loads(r[0]) for r in rows]
        if not records: raise ValueError("没有可导出的已完成任务")
        archive=self.output/("export-"+uuid.uuid4().hex+".zip")
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            manifest=[]
            for index,j in enumerate(records):
                path=self.output/(j['id']+'.wav')
                if not path.exists(): continue
                filename=f"{index+1:04d}_{j['id'][:8]}.wav"
                z.write(path,filename)
                manifest.append({"filename":filename,"text":j["text"],"options":j["options"],"result":j["result"]})
            z.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
        return archive
