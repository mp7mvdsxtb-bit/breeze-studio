"""Breeze Studio local UI and production API."""
from __future__ import annotations
import asyncio
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from studio import Studio, PRESETS, DEFAULTS, split_text, validate_options
from translation import LocalTranslator, TranslationBusy
from updater import Updater
from event_suggestions import suggest

ROOT=Path(__file__).resolve().parents[1]
BACKEND="http://127.0.0.1:7860"
STATIC=Path(__file__).resolve().parent/"static"
studio=Studio(ROOT,BACKEND)
translator=LocalTranslator(ROOT/'translation-model')
model_state="loading";model_error="";backend_process=None;backend_log=None


async def monitor_model():
    global model_state,model_error,backend_process,backend_log
    async with httpx.AsyncClient(timeout=3,trust_env=False) as client:
        try:
            r=await client.get(BACKEND+"/health")
            if r.is_success and r.json().get("status")=="ok":model_state="ready"
        except httpx.HTTPError:pass
        if model_state!="ready":
            import socket
            with socket.socket() as sock:occupied=sock.connect_ex(("127.0.0.1",7860))==0
            if not occupied:
                env=dict(os.environ,BREEZE_LOW_VRAM="1",HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",OMP_NUM_THREADS="4",PYTHONUTF8="1",HF_HOME=str(ROOT/"hf-cache"),TEMP=str(ROOT/"tmp"),TMP=str(ROOT/"tmp"))
                backend_log=(ROOT/"model-server.log").open("w",encoding="utf-8")
                backend_process=subprocess.Popen([sys.executable,"-u","-m","breeze_infer.api",str(ROOT.parent/"models"/"Breeze-TTS-2"),"--host","127.0.0.1","--port","7860","--no-fast-all"],cwd=ROOT/"app",env=env,stdout=backend_log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
        failures=0
        while True:
            if backend_process is not None and backend_process.poll() is not None:
                model_state="error";model_error="模型进程已退出，请检查 model-server.log 并重启工作室。";return
            try:
                r=await client.get(BACKEND+"/health")
                if r.is_success and r.json().get("status")=="ok":model_state="ready";model_error="";failures=0
                else:model_state="loading"
            except (httpx.HTTPError,ValueError):
                failures+=1;model_state="loading"
                if failures>120:model_state="error";model_error="模型加载超时，请查看 model-server.log。"
            await asyncio.sleep(3)


@asynccontextmanager
async def lifespan(app):
    task=asyncio.create_task(monitor_model());studio.start(lambda:model_state=="ready")
    yield
    studio.stop.set();studio.wake.set()
    if studio.thread:await asyncio.to_thread(studio.thread.join,10)
    task.cancel()
    if backend_process is not None and backend_process.poll() is None:
        if os.name=="nt":subprocess.run(["taskkill","/PID",str(backend_process.pid),"/T","/F"],capture_output=True)
        else:backend_process.terminate()
    if backend_log:backend_log.close()


app=FastAPI(title="Breeze Studio",lifespan=lifespan)
app.mount("/static",StaticFiles(directory=STATIC),name="static")

@app.post('/api/event-suggestions')
def event_suggestions(payload:dict):
    try:return suggest(payload.get('text'))
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc



@app.get('/api/updates')
def updates(check:bool=False):
    return Updater(ROOT).status(check)


@app.post('/api/updates/settings')
def update_settings(payload:dict):
    try:Updater(ROOT).configure(payload.get('automatic'))
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    return Updater(ROOT).status()


@app.get("/")
def index():return FileResponse(STATIC/"index.html",headers={"Cache-Control":"no-cache"})


@app.get("/api/state")
def state():
    jobs=studio.list_jobs(limit=50)["items"]
    with studio.lock,studio.connect() as db:
        row=db.execute("SELECT data FROM jobs WHERE status IN ('running','cancelling') LIMIT 1").fetchone()
    return {"app":"breeze-studio","version":2,"model":model_state,"error":model_error,"active_job":json.loads(row[0]) if row else None,"counts":studio.counts(),"paused":studio.setting("paused"),"history":[j["result"] for j in jobs if j["status"]=="complete" and j['result'].get('quality_feedback')!='avoid_voice']}


@app.get("/api/config")
def config():return {"presets":PRESETS,"defaults":DEFAULTS,"voices":studio.list_voices(),"events":["(laugh)","(sigh)","(cough)","(clears throat)"],"hardware":"本地串行低显存模式"}


@app.post('/api/translate-description')
def translate_description(payload:dict):
    source=payload.get('text','')
    try:return {'source':source,'english':translator.translate(source),'engine':'local-cpu'}
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    except TranslationBusy as exc:raise HTTPException(429,str(exc)) from exc
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception('Local translation failed')
        raise HTTPException(503,'本地翻译暂时不可用，请查看 webui-error.log；你的原文已保留。') from exc


@app.get("/api/jobs")
def job_list(limit:int=50,offset:int=0,search:str="",status:str=""):
    return studio.list_jobs(min(max(limit,1),100),max(offset,0),search[:200],status)


@app.get("/api/jobs/{job_id}")
def job_get(job_id:str):
    job=studio.get(job_id)
    if not job:raise HTTPException(404,"任务不存在")
    return job


@app.post("/api/jobs/{job_id}/{action}")
def job_action(job_id:str,action:str):
    try:
        if action=="cancel":studio.cancel(job_id)
        elif action=="retry":studio.retry(job_id)
        elif action=="reject-voice":studio.reject_voice(job_id)
        else:raise ValueError("未知操作")
        return {"ok":True}
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@app.post("/api/queue/{action}")
def queue_action(action:str):
    if action=="cancel-pending":
        with studio.lock,studio.connect() as db:
            rows=db.execute("SELECT id FROM jobs WHERE status='queued'").fetchall()
            for row in rows:
                studio.cancel(row[0])
        return {"cancelled":len(rows)}
    if action not in {"pause","resume"}:raise HTTPException(400,"未知操作")
    studio.set_setting("paused",action=="pause")
    return {"paused":action=="pause"}


async def read_upload(upload:UploadFile,limit:int):
    content=bytearray()
    try:
        while chunk:=await upload.read(1024*1024):
            content.extend(chunk)
            if len(content)>limit:raise HTTPException(400,"文件过大")
        return bytes(content)
    finally:await upload.close()


@app.post("/api/voices")
async def save_voice(name:str=Form(...),transcript:str=Form(...),audio:UploadFile=File(...)):
    content=await read_upload(audio,30*1024*1024)
    try:return studio.save_voice(name,transcript,io.BytesIO(content))
    except (ValueError,RuntimeError) as exc:raise HTTPException(400,str(exc)) from exc


@app.get("/api/voices")
def voices():return studio.list_voices()


@app.delete('/api/voices/{voice_id}')
def delete_voice(voice_id:str):
    try:return studio.delete_voice(voice_id)
    except KeyError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    except OSError as exc:raise HTTPException(409,'无法删除参考音频，请停止播放后再试。') from exc


@app.post("/api/import")
async def import_text(file:UploadFile=File(...)):
    filename=file.filename or "";content=await read_upload(file,2*1024*1024)
    try:text=content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:raise HTTPException(400,"请保存为 UTF-8 编码的 TXT 或 CSV") from exc
    if filename.lower().endswith(".csv"):
        reader=csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or "text" not in reader.fieldnames:raise HTTPException(400,"CSV 需要 text 列，可包含带换行的引号字段")
        texts=[row.get("text","").strip() for row in reader if row.get("text","").strip()]
    else:texts=[line.strip() for line in text.splitlines() if line.strip()]
    if not 1<=len(texts)<=200:raise HTTPException(400,"文件需包含 1–200 条非空文本")
    return {"texts":texts}


@app.post("/api/preview")
def preview(payload:dict):
    try:
        o=validate_options(payload.get("options",{}));text=payload.get("text","")
        if not isinstance(text,str) or len(text)>30000:raise ValueError("文本过长")
        return {"segments":split_text(text,o["segment_chars"]),"words":len(text.split())}
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@app.post("/api/submit",status_code=202)
def submit(payload:dict):
    try:return studio.submit(payload.get("texts"),payload.get("options",{}))
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


@app.post("/api/generate",status_code=202)
async def legacy_generate(text:str=Form(...),mode:str=Form("design"),instruction:str=Form(""),cfg_scale:float=Form(4),seed:int=Form(42),ref_text:str=Form(""),ref_audio:UploadFile|None=File(None)):
    opts={"mode":mode,"instruction":instruction,"cfg_scale":cfg_scale,"seed":seed}
    if mode!="design":
        if ref_audio is None or not ref_text:raise HTTPException(400,"需要参考音频和准确文字")
        content=await read_upload(ref_audio,30*1024*1024)
        try:opts["voice_id"]=studio.save_voice("临时导入声音",ref_text,io.BytesIO(content))["id"]
        except (ValueError,RuntimeError) as exc:raise HTTPException(400,str(exc)) from exc
    try:return studio.submit([text],opts)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc


def wav_path(name,folder):
    if not re.fullmatch(r"[0-9a-f]{32}\.wav",name):raise HTTPException(404)
    path=folder/name
    if not path.is_file():raise HTTPException(404)
    return path


@app.get("/audio/{name}")
def audio(name:str):return FileResponse(wav_path(name,studio.output),media_type="audio/wav",filename="Breeze-"+name[:8]+".wav",content_disposition_type="inline")


@app.get("/voices/{name}")
def voice_audio(name:str):return FileResponse(wav_path(name,studio.voices),media_type="audio/wav")


@app.get("/api/export")
def export(batch_id:str|None=None):
    if batch_id is not None and not re.fullmatch(r"[0-9a-f]{32}|legacy",batch_id):raise HTTPException(400,"批次 ID 错误")
    try:path=studio.export(batch_id)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    return FileResponse(path,media_type="application/zip",filename="Breeze-audio.zip",background=BackgroundTask(path.unlink,missing_ok=True))


@app.get("/api/export/status")
def export_status(batch_id:str|None=None):
    with studio.lock,studio.connect() as db:
        count=db.execute("SELECT COUNT(*) FROM jobs WHERE status='complete'"+(" AND batch_id=?" if batch_id else ""),(batch_id,) if batch_id else ()).fetchone()[0]
    return {"count":count}


@app.get("/api/jobs/{job_id}/live")
def live(job_id:str):
    job=studio.get(job_id)
    if not job:raise HTTPException(404,"任务不存在")
    if job["status"] not in {"running","complete"}:raise HTTPException(409,"任务尚未开始或已停止")
    async def frames():
        for i in range(job.get("segment_count",1)):
            base=studio.output/(job_id+"_parts")/f"{i:04d}";position=44
            while True:
                current=studio.get(job_id);done=current["status"] in {"complete","error","cancelled","interrupted"}
                part=base.with_suffix(".wav");partial=base.with_suffix(".partial");source=part if part.exists() else partial
                if source.exists() and source.stat().st_size>position:
                    with source.open("rb") as f:f.seek(position);pcm=f.read(16384)
                    pcm=pcm[:len(pcm)//2*2]
                    if pcm:position+=len(pcm);yield pcm;continue
                if part.exists():break
                if done:return
                await asyncio.sleep(.1)
            if i+1<job.get("segment_count",1):yield b'\0\0'*int(24*job["options"]["pause_ms"])
    return StreamingResponse(frames(),media_type="application/octet-stream",headers={"X-Sample-Rate":"24000","Cache-Control":"no-store"})


if __name__=="__main__":uvicorn.run(app,host="127.0.0.1",port=7861,log_level="info")
