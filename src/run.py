"""Sequential real requests; raw responses are retained, never repaired/retried."""
import argparse
import csv
import hashlib
import json
import os
import platform
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from src.score import score
from src.cost import api_cost

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ['role','model','resolved_model','item_id','abbreviation','expected','output','parsed',
          'correct','status','latency_ms','input_tokens','output_tokens','thinking_tokens',
          'cached_tokens','api_cost_usd','eval_count','eval_duration_ns','timestamp_utc','error']


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def load_data(split):
    path=ROOT/'data'/('items.jsonl' if split=='test' else 'dev.jsonl')
    items=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    vocab=read_json(ROOT/'data/word_list.json')
    assert len({r['id'] for r in items})==len(items), 'Duplicate item ID'
    assert len({r['abbreviation'] for r in items})==len(items), 'Duplicate abbreviation'
    assert all(r['expected'] in vocab for r in items), 'Label outside fixed vocabulary'
    if split=='test':
        assert len(items)>=50, 'Teacher requires at least 50 test items'
    return items, vocab


def prompt_for(item, vocab):
    return (ROOT/'src/prompt.txt').read_text(encoding='utf-8').format(
        word_list='\n'.join(vocab),context=item['context'],abbreviation=item['abbreviation'])


def request_json(url, payload=None, headers=None, timeout=180):
    data=None if payload is None else json.dumps(payload).encode('utf-8')
    req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json',**(headers or {})})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        return json.load(response)


def call_model(model, prompt, cfg):
    if model['provider']=='gemini':
        # API key is a header: it never appears in the URL or saved artefacts.
        url='https://generativelanguage.googleapis.com/v1beta/models/'+urllib.parse.quote(model['model'],safe='')+':generateContent'
        return request_json(url,{'contents':[{'role':'user','parts':[{'text':prompt}]}],
            'generationConfig':{'temperature':cfg['temperature'],'maxOutputTokens':cfg['max_output_tokens']}},
            {'x-goog-api-key':os.environ['GEMINI_API_KEY']},cfg['timeout_seconds'])
    return request_json('http://localhost:11434/api/chat',{'model':model['model'],
        'messages':[{'role':'user','content':prompt}],'stream':False,'keep_alive':'30m',
        'options':{'temperature':cfg['temperature'],'num_predict':cfg['max_output_tokens'],'num_ctx':8192}},
        timeout=cfg['timeout_seconds'])


def decode_response(raw, model):
    if model['provider']=='gemini':
        candidates=raw.get('candidates',[])
        candidate=candidates[0] if candidates else {}
        output=''.join(part.get('text','') for part in candidate.get('content',{}).get('parts',[])
                       if not part.get('thought',False))
        reason=candidate.get('finishReason','')
        blocked=raw.get('promptFeedback',{}).get('blockReason')
        status='refusal' if blocked or reason in {'SAFETY','RECITATION','BLOCKLIST','PROHIBITED_CONTENT','SPII'} else ''
        if reason=='MAX_TOKENS': status='truncated'
        u=raw.get('usageMetadata',{})
        return output,status,{'resolved_model':raw.get('modelVersion',model['model']),
            'input_tokens':u.get('promptTokenCount',''),'output_tokens':u.get('candidatesTokenCount',0),
            'thinking_tokens':u.get('thoughtsTokenCount',0),'cached_tokens':u.get('cachedContentTokenCount',0),
            'api_cost_usd':api_cost(u,model)}
    return raw.get('message',{}).get('content',''),('truncated' if raw.get('done_reason')=='length' else ''),{
        'resolved_model':raw.get('model',model['model']),'input_tokens':raw.get('prompt_eval_count',''),
        'output_tokens':raw.get('eval_count',''),'thinking_tokens':0,'cached_tokens':0,
        'api_cost_usd':'','eval_count':raw.get('eval_count',''),'eval_duration_ns':raw.get('eval_duration','')}


def fingerprint():
    files=['config.json','data/items.jsonl','data/dev.jsonl','data/word_list.json',
           'src/prompt.txt','src/run.py','src/score.py','src/cost.py']
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}


def reviews_ready(items):
    with (ROOT/'data/label_reviews.csv').open(encoding='utf-8',newline='') as f:
        reviews={row['id']:row for row in csv.DictReader(f)}
    return all((r:=reviews.get(item['id'],{})).get('reviewer_1','').strip() and
               r.get('reviewer_2','').strip() and r['reviewer_1'].strip().casefold()!=r['reviewer_2'].strip().casefold()
               and r.get('checked_date') and r.get('expected')==item['expected'] for item in items)


def preflight(cfg):
    if not os.environ.get('GEMINI_API_KEY'):
        raise ValueError('GEMINI_API_KEY is missing. Follow START_HERE.md. Do not put the key in config.json.')
    tags=request_json('http://localhost:11434/api/tags',timeout=10)
    name=next(m['model'] for m in cfg['models'] if m['provider']=='ollama')
    match=next((m for m in tags.get('models',[]) if m.get('name')==name),None)
    if not match:
        raise ValueError('Local model missing. Run: ollama pull '+name)
    return {'model':match,'version':request_json('http://localhost:11434/api/version',timeout=10),
            'os':platform.platform(),'cpu':platform.processor(),'python':platform.python_version()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',choices=['dev','test'],default='test')
    parser.add_argument('--check',action='store_true',help='Offline dataset and scorer validation; no API calls')
    args=parser.parse_args()
    cfg=read_json(ROOT/'config.json');items,vocab=load_data(args.split)
    if args.check:
        assert all(score(r['expected'],r['expected'],vocab)[0]==1 for r in items)
        assert cfg['temperature']==0
        print(f'PASS: {len(items)} {args.split} items; fixed vocabulary; exact scorer; temperature 0.')
        print('Two-person label review:', 'complete' if reviews_ready(items) else 'PENDING')
        print('No model requests made. This is NOT a benchmark result.')
        return
    if cfg['temperature']!=0: raise ValueError('Teacher requires temperature 0.')
    if args.split=='test' and not reviews_ready(items):
        raise ValueError('Complete data/label_reviews.csv with two real reviewers per item before the frozen test run. Use --split dev for practice.')
    hardware=preflight(cfg)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination=ROOT/'results'/'runs'/(args.split+'-'+stamp)
    destination.mkdir(parents=True)
    metadata={'started_utc':stamp,'split':args.split,'settings':cfg,'sha256':fingerprint(),
              'hardware':hardware,'item_ids':[r['id'] for r in items],'complete':False,
              'latency_policy':'Full wall time for all attempts, first local cold load included; pauses excluded.',
              'retries':0}
    (destination/'metadata.json').write_text(json.dumps(metadata,indent=2))
    # Copy the exact experimental inputs for auditability, without secrets.
    (destination/'items.json').write_text(json.dumps(items,indent=2))
    (destination/'prompts.json').write_text(json.dumps([prompt_for(r,vocab) for r in items],indent=2))
    with (destination/'per_item.csv').open('w',newline='',encoding='utf-8') as f, (destination/'raw.jsonl').open('w',encoding='utf-8') as rawfile:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
        for model in cfg['models']:
            for item in items:
                row={key:'' for key in FIELDS}
                row.update(role=model['role'],model=model['model'],item_id=item['id'],
                    abbreviation=item['abbreviation'],expected=item['expected'],correct=0,
                    timestamp_utc=datetime.now(timezone.utc).isoformat())
                start=time.perf_counter();raw=None
                try:
                    raw=call_model(model,prompt_for(item,vocab),cfg)
                    row['latency_ms']=(time.perf_counter()-start)*1000
                    output,forced,usage=decode_response(raw,model)
                    correct,status,parsed=score(output,item['expected'],vocab)
                    row.update(output=output,parsed=parsed,correct=0 if forced else correct,status=forced or status,**usage)
                except urllib.error.HTTPError as exc:
                    row.update(status='api_error',error='HTTP '+str(exc.code))
                except (TimeoutError,socket.timeout):
                    row.update(status='timeout',error='Request deadline exceeded')
                except urllib.error.URLError as exc:
                    row.update(status='timeout' if isinstance(exc.reason,(TimeoutError,socket.timeout)) else 'connection_error',error=type(exc.reason).__name__)
                except (ValueError,KeyError,TypeError) as exc:
                    row.update(status='response_error',error=type(exc).__name__)
                if row['latency_ms']=='':row['latency_ms']=(time.perf_counter()-start)*1000
                writer.writerow(row);f.flush()
                rawfile.write(json.dumps({'role':model['role'],'item_id':item['id'],'response':raw,'error':row['error']})+'\n');rawfile.flush()
                print(model['role'],item['id'],row['status'],f"{row['latency_ms']:.0f} ms",flush=True)
                time.sleep(cfg['pause_seconds'])
    metadata['complete']=True
    (destination/'metadata.json').write_text(json.dumps(metadata,indent=2))
    from src.report import generate
    generate(destination, publish=args.split=='test')
    print('Saved:',destination)
    if args.split=='dev':print('Practice only. Do not include dev outcomes in the final test results.')


if __name__=='__main__':
    try:main()
    except (ValueError,urllib.error.URLError) as exc:
        raise SystemExit(str(exc))
