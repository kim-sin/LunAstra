#!/usr/bin/env python3
"""Prepare blinded workspaces and grade explicit submissions; never call a model.

Fixtures are public synthetic diagnostics, not a hidden production benchmark.
Run candidate code only in an appropriate isolated evaluation environment.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from luna_astra.util import HarnessError, atomic_write, file_hash, inside, load_json, no_symlinks

ARMS = ('astra_reference','luna_stock','luna_astra')
CATALOG = load_json(ROOT/'fixtures.json')['cases']

def prepare(output: Path, seed: int=41, arms=ARMS) -> dict:
    output=output.absolute(); no_symlinks(output)
    if output.exists():raise HarnessError('output exists; do not overwrite an evaluation')
    output.mkdir(parents=True)
    controller=output/'controller';controller.mkdir()
    jobs=output/'jobs'; jobs.mkdir()
    definitions=[(case,arm) for case in CATALOG for arm in arms]
    random.Random(seed).shuffle(definitions)
    mapping={}
    for case,arm in definitions:
        job_id='job-'+uuid.uuid4().hex[:12]
        job=jobs/job_id;job.mkdir()
        source=ROOT/'fixtures'/case['id']
        files={'candidate.py':'starter.py','TASK.md':'TASK.md'}
        files.update({name:name for name in case['support']})
        for target,origin in files.items():shutil.copyfile(source/origin,job/target)
        mapping[job_id]={'fixture':case['id'],'arm':arm,'support':case['support'],
                         'initial_hashes':{name:file_hash(job/name) for name in files}}
    record={'schema':1,'created_at':time.time(),'seed':seed,'jobs':mapping,
            'model_execution':'NOT_RUN',
            'blindness':'IDs mask arms for graders; controller metadata and fixtures must not be exposed to workers.'}
    atomic_write(controller/'mapping.json',(json.dumps(record,indent=2)+'\n').encode())
    return {'jobs':len(mapping),'output':str(output),'model_execution':'NOT_RUN'}

def _job(output:Path,job_id:str):
    if not job_id.startswith('job-') or len(job_id)!=16 or any(c not in '0123456789abcdef' for c in job_id[4:]):
        raise HarnessError('invalid job id')
    mapping=load_json(output/'controller'/'mapping.json')
    if job_id not in mapping['jobs']:raise HarnessError('unknown job')
    return output/'jobs'/job_id,mapping['jobs'][job_id]

def submit(output:Path,job_id:str,metrics:dict|None=None)->dict:
    job,record=_job(output,job_id)
    metrics=metrics or {}
    fields={'model_id','reasoning_setting','wall_seconds','input_tokens','output_tokens',
            'user_interventions','caller_rework','repeated_failed_approach','source_trace'}
    if set(metrics)-fields:raise HarnessError('unknown metrics field')
    for key,value in metrics.items():
        if key in {'model_id','reasoning_setting','source_trace'}:
            if not isinstance(value,str) or not value:raise HarnessError('invalid metric text')
        elif type(value) not in (int,float) or value<0 or not __import__('math').isfinite(value):
            raise HarnessError('invalid numeric metric')
    names=['candidate.py','TASK.md']+record['support']
    hashes={name:file_hash(inside(job,name)) for name in names}
    directory=output/'controller'/'submissions';directory.mkdir(exist_ok=True)
    target=directory/(job_id+'.json')
    if target.exists():raise HarnessError('submission already sealed; prepare a new evaluation for another attempt')
    receipt={'job':job_id,'at':time.time(),'hashes':hashes,'metrics':metrics,
             'metrics_source':'operator-supplied; independently verify against raw execution trace'}
    atomic_write(target,(json.dumps(receipt,indent=2)+'\n').encode())
    return receipt

def grade_one(output:Path,job_id:str)->dict:
    job,record=_job(output,job_id)
    submission=output/'controller'/'submissions'/(job_id+'.json')
    if not submission.exists():return {'job':job_id,'status':'NOT_SUBMITTED'}
    sealed=load_json(submission)
    try:
        for name,sha in sealed['hashes'].items():
            if file_hash(inside(job,name))!=sha:
                return {'job':job_id,'status':'STALE_SUBMISSION'}
        for name in ['TASK.md']+record['support']:
            if file_hash(inside(job,name))!=record['initial_hashes'][name]:
                return {'job':job_id,'status':'SCOPE_VIOLATION','file':name}
    except (OSError,ValueError) as exc:
        return {'job':job_id,'status':'INVALID_SUBMISSION','error':str(exc)}
    # Grading runs in a copy, so it cannot mutate the supplied task workspace.
    # This is process isolation, NOT a security sandbox for malicious code.
    with tempfile.TemporaryDirectory(prefix='luna-eval-') as temp:
        directory=Path(temp)
        for name in ['candidate.py']+record['support']:shutil.copyfile(job/name,directory/name)
        shutil.copyfile(ROOT/'fixtures'/record['fixture']/'grade.py',directory/'grade.py')
        start=time.monotonic()
        try:
            run=subprocess.run([sys.executable,'-B','grade.py'],cwd=directory,
                               stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
            status='PASS' if run.returncode==0 else 'FAIL'
            code=run.returncode; stdout=run.stdout.decode('utf-8',errors='replace'); stderr=run.stderr.decode('utf-8',errors='replace')
        except subprocess.TimeoutExpired:
            # Only this freshly-created grader process is timed out, never an existing job.
            status='GRADER_TIMEOUT';code=None;stdout='';stderr='Owned grader exceeded 30 seconds.'
        except OSError as exc:
            status='GRADER_ERROR';code=None;stdout='';stderr=str(exc)
        elapsed=time.monotonic()-start
    # A concurrent edit is not accepted as the sealed submitted artifact.
    for name,sha in sealed['hashes'].items():
        if not (job/name).is_file() or file_hash(inside(job,name))!=sha:status='STALE_SUBMISSION'
    result={'job':job_id,'status':status,'exit_code':code,'grader_wall_seconds':elapsed,
            'stdout':stdout,'stderr':stderr,'metrics':sealed['metrics'],
            'model_wall_seconds':sealed['metrics'].get('wall_seconds'),
            'scope':'Only public synthetic checks; not proof of overall task success or model parity.'}
    result_dir=output/'controller'/'results';result_dir.mkdir(exist_ok=True)
    atomic_write(result_dir/(job_id+'.json'),(json.dumps(result,indent=2)+'\n').encode())
    return result

def summarize(output:Path)->dict:
    mapping=load_json(output/'controller'/'mapping.json')['jobs']
    arms={arm:{'assigned':0,'graded':0,'passed':0,'not_run':0,'missing_model_metrics':0} for arm in ARMS}
    for job_id,record in mapping.items():
        arm=arms[record['arm']];arm['assigned']+=1
        path=output/'controller'/'results'/(job_id+'.json')
        if not path.exists():arm['not_run']+=1;continue
        result=load_json(path);arm['graded']+=1;arm['passed']+=result['status']=='PASS'
        if not result.get('metrics',{}).get('source_trace'):arm['missing_model_metrics']+=1
    return {'arms':arms,'parity_verdict':'NOT_ESTABLISHED',
            'reason':'Requires verified real-model runs, fresh real-task holdouts and matched conditions; fixture checks alone cannot establish parity.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','submit','grade','summary'])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--job')
    parser.add_argument('--metrics',type=Path)
    parser.add_argument('--seed',type=int,default=41)
    parser.add_argument('--luna-only',action='store_true',help='Prepare stock/enhanced Luna only; no Astra placeholder')
    args=parser.parse_args()
    try:
        if args.command=='prepare':result=prepare(args.output,args.seed,('luna_stock','luna_astra') if args.luna_only else ARMS)
        elif args.command=='summary':result=summarize(args.output)
        elif args.command=='submit':
            if not args.job:raise HarnessError('--job required')
            result=submit(args.output,args.job,load_json(args.metrics) if args.metrics else None)
        else:
            jobs=[args.job] if args.job else list(load_json(args.output/'controller'/'mapping.json')['jobs'])
            result=[grade_one(args.output,job) for job in jobs]
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (OSError,ValueError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
if __name__=='__main__':raise SystemExit(main())
