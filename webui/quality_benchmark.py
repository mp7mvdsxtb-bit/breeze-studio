"""Opt-in 20-script, blinded listening comparison using the local queue.

Usage: python webui/quality_benchmark.py submit [--count 20]
       python webui/quality_benchmark.py status PATH_TO_MANIFEST
       python webui/quality_benchmark.py cancel PATH_TO_MANIFEST
The local manifest includes a private answer key; the status command prints
only anonymised A/B links and feedback until the user explicitly uses --reveal.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import random
import time
import uuid
import httpx

SCRIPTS=[
    'Small gaps can cause big headaches. Here is a simple fix.',
    'This sealing tape sticks firmly to a clean, dry surface.',
    'A foil backing covers the flexible self-adhesive layer.',
    'Look how easily it fits around the edge of the sink.',
    'Wait until you see what is inside this little ball.',
    'These duck treats have a soft surprise in the middle.',
    'My dog knows exactly when it is time for a treat.',
    'This is a small change that makes mornings feel easier.',
    'The soft fabric feels comfortable against your skin.',
    'Let me show you how I use this in my daily routine.',
    'Dry heels? This is my little bedtime ritual.',
    'Apply a small amount, then let it absorb naturally.',
    'The bottle is easy to hold and simple to refill.',
    'See the clear glass and the gold details up close.',
    'Every curve gives the light somewhere beautiful to go.',
    'This tool helps keep everything neat and within reach.',
    'A thoughtful gift can make an ordinary day feel special.',
    'Here are three things I noticed after trying it at home. First, it is simple to use and fits comfortably in my hand. Second, the materials feel smooth and easy to clean. I also like how it keeps everything neatly organized in one place. After a busy day, those small details make the whole routine feel easier. If you want a closer look, I will show you exactly how it works and why I keep it nearby. Take your time and decide whether it fits your own routine.',
    '(laugh) That was a nice surprise. Let me show you.',
    '(sigh) What a relief. Everything is finally in place.',
]

BASELINE='A cheerful young American woman sharing a useful find with a friend. Bright smiling voice, spontaneous conversational rhythm, expressive pitch changes and playful emphasis. Enthusiastic but believable, not a formal announcer.'
CANDIDATE='A clear American English woman speaking to one listener, natural, fully voiced and smooth. Relaxed close conversational delivery, crisp intelligible words and gentle natural expression. No whispering, vocal fry or coarse texture.'
BASELINE_MALE='A confident American English male narrator with a warm lower register. Conversational, grounded and trustworthy. Clear pronunciation, subtle expressive emphasis and a natural unhurried pace.'
CANDIDATE_MALE='A clear American English man speaking to one listener, natural, fully voiced and smooth. Relaxed close conversational delivery, crisp intelligible words and gentle natural expression. No whispering, vocal fry or coarse texture.'
ROOT=Path(__file__).resolve().parents[1]


def submit(count):
    if not 1<=count<=len(SCRIPTS):raise ValueError('count must be 1–20')
    root=ROOT/'outputs'/'studio'/'benchmarks';root.mkdir(parents=True,exist_ok=True)
    manifest=root/(uuid.uuid4().hex+'.json')
    record={'created':time.time(),'pairs':[],'completed_submission':False}
    with httpx.Client(base_url='http://127.0.0.1:7861',timeout=20,trust_env=False) as client:
        for index,text in enumerate(SCRIPTS[:count]):
            pair=[]
            male=index%5==0
            for name,instruction in [('baseline',BASELINE_MALE if male else BASELINE),('candidate',CANDIDATE_MALE if male else CANDIDATE)]:
                response=client.post('/api/submit',json={'texts':[text],'options':{'instruction':instruction,'seed':42+index,'temperature':.9,'variants':1}})
                response.raise_for_status();pair.append({'system':name,'id':response.json()['id']})
                record.setdefault('submitted_ids',[]).append(pair[-1]['id'])
                manifest.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            random.SystemRandom().shuffle(pair)
            record['pairs'].append({'number':index+1,'text':text,'voice':'male' if male else 'female','A':pair[0],'B':pair[1]})
            manifest.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    record['completed_submission']=True;manifest.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('已加入',count*2,'个任务。盲听页面：http://127.0.0.1:7861/benchmark?id='+manifest.stem)
    print('状态命令：python webui/quality_benchmark.py status',manifest)


def status(path,reveal):
    data=json.loads(Path(path).read_text(encoding='utf-8'));totals={'baseline':{'rated':0,'satisfied':0,'raspy':0,'hollow':0},'candidate':{'rated':0,'satisfied':0,'raspy':0,'hollow':0}}
    with httpx.Client(base_url='http://127.0.0.1:7861',timeout=20,trust_env=False) as client:
        for pair in data['pairs']:
            print(f"\n{pair['number']}. {pair['text']}")
            for label in ('A','B'):
                item=pair[label];job=client.get('/api/jobs/'+item['id']);job.raise_for_status();job=job.json()
                feedback=job.get('subjective_feedback',[])
                if feedback:
                    totals[item['system']]['rated']+=1
                    for score in ('satisfied','raspy','hollow'):totals[item['system']][score]+=score in feedback
                identity=(' '+item['system']) if reveal else ''
                print(f"  {label}{identity}: {job['status']}  http://127.0.0.1:7861/audio/{item['id']}.wav  反馈: {feedback}")
    if reveal:print('\n人工反馈汇总:',json.dumps(totals,ensure_ascii=False))
    else:print('\n在工作室任务历史中试听并保存反馈；评分完成后可加 --reveal 查看对应方案与汇总。')


def cancel(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'));cancelled=0
    with httpx.Client(base_url='http://127.0.0.1:7861',timeout=20,trust_env=False) as client:
        for job_id in data.get('submitted_ids',[]):
            job=client.get('/api/jobs/'+job_id);job.raise_for_status()
            if job.json()['status'] in ('queued','running'):
                response=client.post('/api/jobs/'+job_id+'/cancel');response.raise_for_status();cancelled+=1
    print('已取消或请求取消',cancelled,'个评测任务；完成的音频保留。')


if __name__=='__main__':
    parser=argparse.ArgumentParser();commands=parser.add_subparsers(dest='action',required=True)
    start=commands.add_parser('submit');start.add_argument('--count',type=int,default=20)
    report=commands.add_parser('status');report.add_argument('manifest');report.add_argument('--reveal',action='store_true')
    stop=commands.add_parser('cancel');stop.add_argument('manifest')
    args=parser.parse_args()
    if args.action=='submit':submit(args.count)
    elif args.action=='status':status(args.manifest,args.reveal)
    else:cancel(args.manifest)
