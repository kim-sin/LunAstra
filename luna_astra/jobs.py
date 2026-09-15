"""Non-destructive check runners. No model calls, no termination of any process.

A launched process is not proof of progress. Only the recorded check result can
finish a job. An interrupted controller remains unknown/pending, never PASS.
"""
from __future__ import annotations
import json
import re
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import uuid
from .store import Store, evidence_directory
from .evidence import Evidence
from .util import HarnessError, strict_json, canonical, json_hash, no_symlinks

def job_record(raw):
    """Reject corrupt controller state rather than treating it as finished."""
    value = strict_json(raw)
    states = {'PENDING','RUNNING','UNKNOWN','FINISHED','ERROR'}
    if not isinstance(value, dict) or not isinstance(value.get('status'), str) or value['status'] not in states:
        raise HarnessError('invalid check controller state; no completion can be asserted')
    if not isinstance(value.get('id'), str) or not re.fullmatch('[a-f0-9]{32}', value['id']):
        raise HarnessError('invalid check controller identity')
    if not all(isinstance(value.get(k), str) and value[k] for k in ('check_id','task_hash')):
        raise HarnessError('invalid check controller assignment')
    if value['status'] == 'FINISHED' and not isinstance(value.get('result'), dict):
        raise HarnessError('finished check controller has no recorded result')
    return value

class Jobs:
    def __init__(self,store:Store,key:str,package:Path):
        self.store=store;self.key=key;self.package=package
    def all(self):
        with self.store.db() as db:
            return [job_record(r[0]) for r in db.execute("SELECT value FROM kv WHERE scope=? AND name LIKE 'job:%'",(self.key,))]
    def active(self):return [j for j in self.all() if j['status'] in {'PENDING','RUNNING','UNKNOWN'}]
    def start(self,check_id):
        ev=Evidence(evidence_directory(self.store.directory,self.key))
        with ev._db() as db:
            if not db.execute('SELECT 1 FROM checks WHERE id=?',(check_id,)).fetchone():raise HarnessError('unknown check')
            task_hash=ev._get(db,'task_hash')
        with self.store.db(True) as db:
            for r in db.execute("SELECT value FROM kv WHERE scope=? AND name LIKE 'job:%'",(self.key,)):
                old=job_record(r[0])
                if old['check_id']==check_id and old['task_hash']==task_hash and old['status'] in {'PENDING','RUNNING','UNKNOWN'}:return old
            job_id=uuid.uuid4().hex
            job={'generation':self.store.get(self.key,'generation','startup'),'id':job_id,'check_id':check_id,'task_hash':task_hash,'evidence_key':str(ev.directory.name),'status':'PENDING','created_at':time.time(),'pid':None}
            db.execute('INSERT INTO kv VALUES(?,?,?)',(self.key,'job:'+job_id,canonical(job)))
            db.execute("DELETE FROM kv WHERE scope=? AND name='finish_generation'",(self.key,))
        argv=[sys.executable,str(self.package/'luna.py'),'--state',str(self.store.directory),'--session',self.key,'job-worker',job_id]
        logdir=self.store.directory/'sessions'/self.key/'job-launch';no_symlinks(logdir);logdir.mkdir(parents=True,exist_ok=True)
        try:
            with (logdir/(job_id+'.log')).open('xb') as log:
                options={'stdin':subprocess.DEVNULL,'stdout':log,'stderr':log,'close_fds':True,'shell':False}
                if os.name=='nt':options['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
                else:options['start_new_session']=True
                process=subprocess.Popen(argv,**options)
            # Reap only this owned child when it exits; never kill or wait-block the caller.
            threading.Thread(target=process.wait,daemon=True,name="lunastra-check-reaper").start()
            with self.store.db(True) as db:
                current=job_record(db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(self.key,'job:'+job_id)).fetchone()[0])
                current['pid']=process.pid
                db.execute('UPDATE kv SET value=? WHERE scope=? AND name=?',(canonical(current),self.key,'job:'+job_id))
            return current
        except OSError as exc:
            job.update(status='ERROR',error=str(exc))
            self.store.put(self.key,'job:'+job_id,job)
            return job
    def run_worker(self,job_id):
        import re
        if not re.fullmatch('[a-f0-9]{32}',job_id):raise HarnessError('invalid check job identity')
        name='job:'+job_id
        with self.store.db(True) as db:
            r=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(self.key,name)).fetchone()
            if not r:raise HarnessError('unknown check job')
            job=job_record(r[0])
            if job['status']!='PENDING':raise HarnessError('check controller already claimed')
            job['status']='RUNNING'
            db.execute('UPDATE kv SET value=? WHERE scope=? AND name=?',(canonical(job),self.key,name))
        try:
            ev=Evidence(evidence_directory(self.store.directory,self.key))
            if job.get('evidence_key',ev.directory.name)!=ev.directory.name:raise HarnessError('check controller belongs to another evidence context')
            result=ev.run(job['check_id'],expected_task_hash=job['task_hash'])
            job.update(status='FINISHED',result=result,ended_at=time.time())
        except BaseException as exc:
            # Never translate an exception into passing checks. Existing evidence
            # attempts remain RUNNING when their exit result cannot be established.
            job.update(status='ERROR',error=type(exc).__name__+': '+str(exc),ended_at=time.time())
        with self.store.db(True) as db:
            current=job_record(db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(self.key,name)).fetchone()[0])
            if current.get('pid'):job['pid']=current['pid']
            db.execute('UPDATE kv SET value=? WHERE scope=? AND name=?',(canonical(job),self.key,name))
        return job
