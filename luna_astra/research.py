"""Persistent local experiment queue, separate from the six native Luna sessions.

Only the observed root in an explicit research contract can configure/start it.
The queue calls user-declared local argv, never a model API. No kill/terminate,
no account access, no automatic promotion of project authority. A failed trial
is retained; a passing verifier is execution evidence, not proof of adequacy.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures, FIRST_COMPLETED
from collections import deque
from decimal import Decimal
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from .util import HarnessError, canonical, strict_json, json_hash, file_hash, inside, no_symlinks
from .paths import covers
from .coordination import overlaps, normalized
from .process_identity import probe

SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_studies(owner TEXT PRIMARY KEY, spec TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_jobs(owner TEXT, id TEXT, spec TEXT NOT NULL, state TEXT NOT NULL,
 record TEXT NOT NULL, PRIMARY KEY(owner,id));
CREATE INDEX IF NOT EXISTS research_jobs_state ON research_jobs(owner,state,id);
CREATE INDEX IF NOT EXISTS research_jobs_ready ON research_jobs(owner,state);
CREATE INDEX IF NOT EXISTS research_jobs_recent ON research_jobs(owner);
CREATE TABLE IF NOT EXISTS research_dependencies(owner TEXT, job_id TEXT, dependency_id TEXT,
 PRIMARY KEY(owner,job_id,dependency_id));
CREATE INDEX IF NOT EXISTS research_dependencies_parent ON research_dependencies(owner,dependency_id);
CREATE TABLE IF NOT EXISTS research_schema(owner TEXT PRIMARY KEY, version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS research_snapshots(owner TEXT,snapshot_id TEXT,context TEXT NOT NULL,
 PRIMARY KEY(owner,snapshot_id));
'''
IDENT = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}')
TERMINAL = {'VERIFIED','FAILED','ERROR','STALE','CANCELLED'}


def _argv(value):
    if (not isinstance(value,list) or not value or len(value)>512 or
        any(not isinstance(x,str) or not x or '\x00' in x for x in value) or
        sum(len(x) for x in value)>256000):
        raise HarnessError('experiment argv must be a bounded string array, not a shell pipeline')
    return value


DEFAULT_WAKE_POLICY = {'completed': 10, 'min_interval': 30, 'queue_low_water': 0,
                       'improvement_absolute': None}


def wake_policy(value=None):
    """Batch notifications, not the lifetime or termination of local work."""
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-set(DEFAULT_WAKE_POLICY):
        raise HarnessError('unknown research wake policy field')
    result={**DEFAULT_WAKE_POLICY,**value}
    for key,minimum,maximum in (('completed',1,10000),('min_interval',0,300),('queue_low_water',0,256)):
        if type(result[key]) is not int or not minimum<=result[key]<=maximum:
            raise HarnessError('invalid wake policy '+key)
    threshold=result['improvement_absolute']
    if threshold is not None:
        if type(threshold) not in (int,float,str):raise HarnessError('invalid improvement threshold')
        try:amount=Decimal(str(threshold))
        except Exception as exc:raise HarnessError('invalid improvement threshold') from exc
        if not amount.is_finite() or amount<=0:raise HarnessError('improvement threshold must be positive')
        result['improvement_absolute']=str(amount)
    return result


def validate_graph(jobs):
    """O(paths * depth + jobs + edges), without recursive dependency traversal."""
    trie={}
    for name,job in jobs.items():
        for path in job['outputs']:
            node=trie
            for part in path.split('/'):
                if None in node and node[None]!=name:
                    raise HarnessError('experiment outputs overlap across immutable jobs')
                node=node.setdefault(part,{})
            stack=[node]
            while stack:
                item=stack.pop()
                if None in item and item[None]!=name:
                    raise HarnessError('experiment outputs overlap across immutable jobs')
                stack.extend(v for k,v in item.items() if k is not None)
            node[None]=name
    parents={name:len(job['depends_on']) for name,job in jobs.items()}
    children={name:[] for name in jobs}
    for name,job in jobs.items():
        for dep in job['depends_on']:
            if dep not in jobs:raise HarnessError('unknown experiment dependency: '+dep)
            children[dep].append(name)
    ready=deque(name for name,count in parents.items() if count==0);seen=0
    while ready:
        name=ready.popleft();seen+=1
        for child in children[name]:
            parents[child]-=1
            if parents[child]==0:ready.append(child)
    if seen!=len(jobs):raise HarnessError('cyclic experiment dependencies')


class Research:
    def __init__(self, store, owner, package):
        self.store=store; self.owner=owner; self.package=Path(package)
        store.ensure_schema('research', SCHEMA)
        # Additive one-time index migration; never rewrite prior job definitions.
        with store.db(True) as db:
            row=db.execute('SELECT version FROM research_schema WHERE owner=?',(owner,)).fetchone()
            if row is not None and row['version']!=1:raise HarnessError('unknown research index schema; preserve the existing store')
            if row is None:
                jobs={r['id']:strict_json(r['spec']) for r in db.execute('SELECT id,spec FROM research_jobs WHERE owner=?',(owner,))}
                validate_graph(jobs)
                for name,job in jobs.items():
                    db.executemany('INSERT OR IGNORE INTO research_dependencies VALUES(?,?,?)',
                                   [(owner,name,dep) for dep in job['depends_on']])
                db.execute('INSERT INTO research_schema VALUES(?,1)',(owner,))

    def _read(self, db):
        row=db.execute('SELECT spec FROM research_studies WHERE owner=?',(self.owner,)).fetchone()
        return strict_json(row[0]) if row else None

    def _save(self, db, spec):
        db.execute('INSERT OR REPLACE INTO research_studies VALUES(?,?)',(self.owner,canonical(spec)))

    def _root(self):
        from .crew import Crew
        crew=Crew(self.store,self.package);state,root=crew._current(self.owner)
        if state.get('mode')!='research':raise HarnessError('research queue requires an explicit mode=research contract')
        if state['phase']!='EXECUTE':raise HarnessError('local experiment launch requires the reviewed EXECUTE phase')
        crew.can_write(self.owner)
        return state,root

    def configure(self, spec):
        contract,root=self._root()
        fields={'project','workers','direction','metric_unit','wake_policy'}
        if not isinstance(spec,dict) or set(spec)-fields or not isinstance(spec.get('project'),str) or not IDENT.fullmatch(spec['project']):
            raise HarnessError('research configuration needs a short project ID, optional workers/direction/metric_unit')
        workers=spec.get('workers',1)
        if type(workers) is not int or not 1<=workers<=6:raise HarnessError('local workers must be 1..6; these are not model sessions')
        if spec.get('direction','max') not in {'max','min'}:raise HarnessError('direction must be max or min')
        policy=wake_policy(spec.get('wake_policy'))
        unit=spec.get('metric_unit','unspecified')
        if not isinstance(unit,str) or len(unit)>80:raise HarnessError('invalid metric unit')
        normalized_spec={'project':spec['project'],'workers':workers,'direction':spec.get('direction','max'),
                         'metric_unit':unit,'workspace':str(root),
                         'contract_run_id':contract['run_id'],'requirements_hash':json_hash(contract['requirements'])}
        with self.store.db(True) as db:
            old=self._read(db)
            if old:
                if old['configuration']==normalized_spec:
                    if 'wake_policy' in spec and wake_policy(old.get('wake_policy'))!=policy:
                        raise HarnessError('use research-policy to change wake policy')
                    return self.status()
                raise HarnessError('research configuration is immutable; preserve the existing study')
            self._save(db,{'id':uuid.uuid4().hex,'configuration':normalized_spec,'state':'PAUSED',
                           'revision':0,'created_at':time.time(),'best_verified_candidate':None,
                           'last_improvement_at':None,'supervisor':None,'authority_promoted':False,
                           'wake_policy':wake_policy(spec.get('wake_policy'))})
        return self.status()

    def enqueue(self, batch):
        _,root=self._root()
        if not isinstance(batch,dict) or set(batch)!={'jobs'} or not isinstance(batch['jobs'],list) or not 1<=len(batch['jobs'])<=256:
            raise HarnessError('enqueue one bounded jobs batch (1..256)')
        registry=self.store.get(self.owner,'resource_registry',{})
        scopes=registry.get('roles',{}).get('working',[])
        if not scopes:raise HarnessError('declare resources.working for experiment outputs; authority outputs are not scratch space')
        protected=registry.get('roles',{}).get('protected',[])
        clean=[]
        for item in batch['jobs']:
            required={'id','argv','verify_argv','dependencies','outputs','result_path','score_key'}
            if not isinstance(item,dict) or not required<=set(item) or set(item)-required-{'cwd','depends_on','environment_keys'}:
                raise HarnessError('job needs id, argv, verify_argv, dependencies, outputs, result_path, score_key')
            if not isinstance(item['id'],str) or not IDENT.fullmatch(item['id']):raise HarnessError('invalid experiment ID')
            argv=_argv(item['argv']); verify=_argv(item['verify_argv'])
            deps=item['dependencies']; outputs=item['outputs']
            for values in (deps,outputs):
                if not isinstance(values,list) or not 1<=len(values)<=100:raise HarnessError('explicit input/output paths required')
            deps=sorted({normalized(root,p) for p in deps}); outputs=sorted({normalized(root,p) for p in outputs})
            for path in deps:
                if not inside(root,path).exists():raise HarnessError('experiment input missing: '+path,code='SOURCE_NOT_FOUND')
            for path in outputs:
                if not any(covers(root,s,path) for s in scopes) or any(overlaps(path,p) for p in protected+deps):
                    raise HarnessError('experiment output must be in working scope and disjoint from inputs/protected files')
            result_path=normalized(root,item['result_path'])
            if not any(covers(root,p,result_path) for p in outputs):raise HarnessError('result_path is outside declared outputs')
            if not isinstance(item['score_key'],str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.]{0,127}',item['score_key']):
                raise HarnessError('score_key must be an explicit dotted JSON field')
            cwd=item.get('cwd','.')
            if not inside(root,cwd,allow_root=True).is_dir():raise HarnessError('experiment cwd must exist')
            depids=item.get('depends_on',[]); env=item.get('environment_keys',[])
            if not isinstance(depids,list) or any(not isinstance(d,str) or not IDENT.fullmatch(d) for d in depids) or len(set(depids))!=len(depids):
                raise HarnessError('invalid experiment dependencies')
            if not isinstance(env,list) or any(not isinstance(e,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',e) for e in env):
                raise HarnessError('invalid environment keys')
            clean.append({**item,'argv':argv,'verify_argv':verify,'dependencies':deps,'outputs':outputs,
                          'result_path':result_path,'cwd':cwd,'depends_on':depids,'environment_keys':sorted(set(env))})
        if len({j['id'] for j in clean})!=len(clean):raise HarnessError('duplicate job in batch')
        with self.store.db() as db:
            known={r[0] for r in db.execute('SELECT id FROM research_jobs WHERE owner=?',(self.owner,))}
        # Register an exact immutable input fingerprint once per unique input set
        # in this batch. After execution AND verification, bytes are rehashed.
        # Metadata equality is never used as proof of unchanged file contents.
        batch_contexts={};job_snapshots={}
        for job in clean:
            if job['id'] in known:continue
            key=json_hash([job['dependencies'],job['argv'][0],job['verify_argv'][0],job['cwd'],job['environment_keys']])
            if key not in batch_contexts:
                observed=self._context(root,job);observed.pop('definition')
                batch_contexts[key]=observed
            context=batch_contexts[key];job_snapshots[job['id']]=(json_hash(context),context)
        with self.store.db(True) as db:
            study=self._read(db)
            if not study or study['state']=='FINISHED':raise HarnessError('configure a nonfinished study first')
            existing={r['id']:strict_json(r['spec']) for r in db.execute('SELECT id,spec FROM research_jobs WHERE owner=?',(self.owner,))}
            all_jobs={**existing}
            for job in clean:
                if job['id'] in existing and existing[job['id']]!=job:
                    raise HarnessError('experiment ID already has a different immutable definition')
                all_jobs[job['id']]=job
            if len(all_jobs)>10000:raise HarnessError('study queue exceeds 10000 experiments')
            validate_graph(all_jobs)
            inserted=0
            for job in clean:
                if job['id'] not in existing:
                    if any(inside(root,p).exists() for p in job['outputs']):
                        raise HarnessError('experiment output exists; preserve it and use a new experiment ID/path')
                    snapshot_id,context=job_snapshots[job['id']]
                    db.execute('INSERT OR IGNORE INTO research_snapshots VALUES(?,?,?)',(self.owner,snapshot_id,canonical(context)))
                    db.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?)',(self.owner,job['id'],canonical(job),'PENDING',canonical({'created_at':time.time(),'definition_hash':json_hash(job),'input_snapshot_id':snapshot_id,'input_snapshot_required':True})))
                    db.executemany('INSERT INTO research_dependencies VALUES(?,?,?)',
                                   [(self.owner,job['id'],d) for d in job['depends_on']])
                    inserted+=1
            study['revision']+=inserted;self._save(db,study)
        return {'enqueued':inserted,'duplicates_reused':len(clean)-inserted,'status':self.status()}

    def _counts(self, db):
        counts={state:0 for state in {'PENDING','RUNNING'}|TERMINAL}
        for row in db.execute('SELECT state,COUNT(*) AS n FROM research_jobs WHERE owner=? GROUP BY state',(self.owner,)):
            if row['state'] not in counts:raise HarnessError('unrecognized research job state')
            counts[row['state']]=row['n']
        return counts

    def _ready_row(self, db, *, signal_only=False):
        columns='1' if signal_only else 'j.*'
        return db.execute("SELECT "+columns+""" FROM research_jobs j INDEXED BY research_jobs_ready WHERE j.owner=? AND j.state='PENDING'
             AND NOT EXISTS (SELECT 1 FROM research_dependencies d
               LEFT JOIN research_jobs parent ON parent.owner=d.owner AND parent.id=d.dependency_id
               WHERE d.owner=j.owner AND d.job_id=j.id AND (parent.state IS NULL OR parent.state!='VERIFIED'))
             ORDER BY j.rowid LIMIT 1""",(self.owner,)).fetchone()

    def _signal(self):
        with self.store.db() as db:
            study=self._read(db)
            if not study:return {'configured':False}
            counts=self._counts(db)
            return {'configured':True,'study_id':study['id'],'state':study['state'],
                    'revision':study['revision'],'counts':counts,'ready':bool(counts['PENDING']) and self._ready_row(db,signal_only=True) is not None,
                    'best':study.get('best_verified_candidate'),
                    'supervisor':study.get('supervisor'), 'policy':wake_policy(study.get('wake_policy'))}

    def controller_health(self, study=None):
        if study is None:
            with self.store.db() as db:study=self._read(db)
        if not study or study['state'] not in {'RUNNING','STARTING','PAUSING'}:
            return {'state':'NOT_ACTIVE','reason':'no_active_controller_claim'}
        supervisor=study.get('supervisor') or {}
        return probe(supervisor.get('pid'),supervisor.get('process_identity'))

    def recover(self):
        """Recover an exited controller, never a slow/live/unknown one.

        Interrupted jobs are retained as ERROR, not retried or promoted. Any live
        or ambiguous direct job process blocks recovery. CAS protects newer state.
        No file deletion, process termination or model call occurs here.
        """
        from .crew import Crew
        Crew(self.store,self.package)._root(self.owner)
        with self.store.db() as db:
            study=self._read(db)
            rows=[dict(r) for r in db.execute("SELECT id,record FROM research_jobs WHERE owner=? AND state='RUNNING'",(self.owner,))]
        health=self.controller_health(study)
        if health['state']!='EXITED':
            return {'recovered':False,'controller':health,'existing_processes_preserved':True}
        observations=[];unresolved=[]
        for row in rows:
            record=strict_json(row['record'])
            # CLAIMED is recorded before any launch intent or Popen operation.
            unlaunched=record.get('stage')=='CLAIMED' and record.get('pid') is None
            observed={'state':'NOT_LAUNCHED','reason':'no_launch_intent'} if unlaunched else probe(record.get('pid'),record.get('process_identity'))
            observations.append({'id':row['id'],'process':observed})
            if observed['state'] not in {'EXITED','NOT_LAUNCHED'}:unresolved.append(row['id'])
        if unresolved:
            return {'recovered':False,'controller':health,'code':'ORPHAN_JOB_UNRESOLVED',
                    'jobs':observations,'unresolved':unresolved,'existing_processes_preserved':True}
        with self.store.db(True) as db:
            current=self._read(db)
            current_rows=[dict(r) for r in db.execute("SELECT id,record FROM research_jobs WHERE owner=? AND state='RUNNING'",(self.owner,))]
            if current!=study or current_rows!=rows:
                return {'recovered':False,'code':'RECOVERY_STATE_CHANGED','existing_processes_preserved':True}
            # A second read-only probe closes races with a late launcher update.
            if self.controller_health(current)['state']!='EXITED':
                return {'recovered':False,'code':'RECOVERY_RECHECK_REQUIRED','existing_processes_preserved':True}
            for row in rows:
                record=strict_json(row['record'])
                record.update(error='Controller exited before a terminal verified receipt; preserved without replay',
                              recovery_class='INTERRUPTED_UNVERIFIED',ended_at=time.time(),authority_promoted=False)
                db.execute("UPDATE research_jobs SET state='ERROR',record=? WHERE owner=? AND id=? AND state='RUNNING'",
                           (canonical(record),self.owner,row['id']))
            history={'supervisor':current.get('supervisor'),'controller_observation':health,
                     'jobs':observations,'at':time.time(),'descendant_processes':'NOT_CENSUSED',
                     'outputs_preserved':True,'jobs_replayed':False}
            nonce=(current.get('supervisor') or {}).get('nonce','unknown')
            db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)',(self.owner,'research-recovery:'+nonce,canonical(history)))
            current.update(state='PAUSED',pause_reason='Exited controller recovered; unfinished jobs retained as unverified errors')
            current['supervisor']={**(current.get('supervisor') or {}),'ended_at':time.time(),'recovered':True}
            current['revision']+=1+len(rows);self._save(db,current)
        return {'recovered':True,'state':'PAUSED','interrupted_jobs':[r['id'] for r in rows],
                'pending_jobs_preserved':True,'jobs_replayed':False,'controller':health}

    def status(self):
        with self.store.db() as db:
            study=self._read(db)
            if not study:return {'configured':False,'authority_promoted':False}
            counts=self._counts(db)
            # Bound both SQL rows and returned text, even after thousands of jobs.
            rows=list(db.execute('SELECT id,state,record FROM research_jobs INDEXED BY research_jobs_recent WHERE owner=? ORDER BY rowid DESC LIMIT 8',(self.owner,)))
        recent=[]
        for row in reversed(rows):
            record=strict_json(row['record'])
            item={'id':row['id'],'state':row['state'],'record_sha256':json_hash(record),
                  'read_command':'research-read '+row['id']}
            for key in ('score','result_sha256','started_at','ended_at','stage','execute_exit_code','verify_exit_code'):
                if key in record:item[key]=record[key]
            if record.get('error'):item['error']=str(record['error'])[:512]
            recent.append(item)
        supervisor=study.get('supervisor') or {};heartbeat=supervisor.get('heartbeat')
        waiting=study['state']=='RUNNING' and counts['RUNNING']==0 and counts['PENDING']==0
        return {'configured':True,**study,'counts':counts,'total':sum(counts.values()),'recent':recent,
                'display_state':'WAITING_FOR_BATCH' if waiting else study['state'],
                'controller_health':self.controller_health(study),
                'supervisor_liveness':'UNCONFIRMED' if study['state']=='RUNNING' and (not heartbeat or time.time()-heartbeat>30) else 'LAST_HEARTBEAT_ONLY',
                'result_validity':'Historical receipts only. Revalidate inputs and outputs before promotion. No authority promotion.',
                'seconds_since_improvement':time.time()-study['last_improvement_at'] if study.get('last_improvement_at') else None}

    def read_job(self, name):
        if not isinstance(name,str) or not IDENT.fullmatch(name):raise HarnessError('invalid experiment ID')
        with self.store.db() as db:
            row=db.execute('SELECT * FROM research_jobs WHERE owner=? AND id=?',(self.owner,name)).fetchone()
        if row is None:raise HarnessError('unknown experiment ID')
        return {'id':name,'state':row['state'],'spec':strict_json(row['spec']),
                'record':strict_json(row['record']),'authority_promoted':False}

    def policy(self, spec):
        self._root();policy=wake_policy(spec)
        with self.store.db(True) as db:
            study=self._read(db)
            if not study:raise HarnessError('configure the research queue first')
            study['wake_policy']=policy;study['revision']+=1;self._save(db,study)
        return {'wake_policy':policy,'running_processes_unchanged':True}

    def start(self):
        self._root()
        recovery=self.recover()
        with self.store.db(True) as db:
            study=self._read(db)
            if not study:raise HarnessError('configure the research queue first')
            if study['state'] in {'RUNNING','STARTING','PAUSING'}:
                return {'existing_controller_preserved':True,'state':study['state'],'recovery':recovery}
            if study['state']!='PAUSED':raise HarnessError('study is not resumable')
            nonce=uuid.uuid4().hex
            study['state']='STARTING';study['supervisor']={'nonce':nonce,'pid':None,'heartbeat':None,'started_at':time.time()};self._save(db,study)
        logdir=self.store.directory/'research'/self.owner;no_symlinks(logdir);logdir.mkdir(parents=True,exist_ok=True)
        argv=[sys.executable,str(self.package/'luna.py'),'--state',str(self.store.directory),'--session',self.owner,'research-worker',nonce]
        try:
            with (logdir/(nonce+'.log')).open('xb') as log:
                options=dict(stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,shell=False)
                if os.name=='nt':options['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
                else:options['start_new_session']=True
                proc=subprocess.Popen(argv,**options)
            import threading
            threading.Thread(target=proc.wait,daemon=True,name='lunastra-research-reaper').start()
            with self.store.db(True) as db:
                current=self._read(db)
                if current['supervisor']['nonce']==nonce:
                    current['supervisor']['pid']=proc.pid
                    current['supervisor']['process_identity']=probe(proc.pid).get('identity');self._save(db,current)
            return {'started':True,'pid':proc.pid,'nonce':nonce,'live_progress_not_yet_verified':True,'recovery':recovery}
        except OSError as exc:
            with self.store.db(True) as db:
                current=self._read(db)
                if (current.get('supervisor') or {}).get('nonce')==nonce:
                    current.update(state='PAUSED',launch_error=str(exc));self._save(db,current)
            raise

    def pause(self, *, finish=False):
        from .crew import Crew
        Crew(self.store,self.package)._root(self.owner)
        if finish:self._root()
        self.recover()
        with self.store.db(True) as db:
            study=self._read(db)
            if not study:raise HarnessError('no study')
            active=db.execute("SELECT 1 FROM research_jobs WHERE owner=? AND state='RUNNING'",(self.owner,)).fetchone()
            pending=db.execute("SELECT 1 FROM research_jobs WHERE owner=? AND state='PENDING'",(self.owner,)).fetchone()
            if finish:
                if active or pending or study['state']!='PAUSED':raise HarnessError('finish requires a paused queue with no pending/running jobs')
                study['state']='FINISHED'
            elif study['state'] in {'RUNNING','STARTING'}:study['state']='PAUSING'
            elif study['state'] not in {'PAUSED','PAUSING'}:raise HarnessError('study cannot pause in this state')
            study['revision']+=1;self._save(db,study)
        return self.status()

    def resume_checkpoint(self, spec):
        from .crew import Crew, fingerprint
        crew=Crew(self.store,self.package);state,root=crew._current(self.owner)
        if state.get('mode')!='research' or state['phase']!='REVIEW':raise HarnessError('resume requires a research checkpoint review')
        study=self.status()
        if not study.get('configured') or study['state']!='PAUSED':raise HarnessError('pause and drain the compute queue first')
        crew._returned(self.owner,state,clear=True)
        evidence,_=crew._root_evidence(self.owner,state)
        if evidence.get('task_hash')!=state['review_task_hash'] or fingerprint(root,state['review_paths'])['sha256']!=state['review_snapshot']['sha256']:
            raise HarnessError('checkpoint review is stale; refresh it before resuming')
        result=crew.execute(self.owner,spec,repair=True)
        self.store.put(self.owner,'research-checkpoint:'+str(state['round']),
                       {'run_id':state['run_id'],'round':state['round'],'snapshot':state['review_snapshot'],
                        'at':time.time(),'task_hash':state['review_task_hash']})
        return {'resumed':True,'crew':result,'compute':'PAUSED; start after dispatching the next reviewed native tasks'}

    def cancel(self, spec):
        self._root()
        if not isinstance(spec,dict) or set(spec)!={'ids','reason'} or not isinstance(spec['ids'],list) or not spec['ids'] or not isinstance(spec['reason'],str) or not spec['reason'].strip():
            raise HarnessError('pending cancellation needs ids and an explicit reason')
        if any(not isinstance(i,str) or not IDENT.fullmatch(i) for i in spec['ids']) or len(spec['reason'])>2000:
            raise HarnessError('invalid cancellation')
        with self.store.db(True) as db:
            study=self._read(db)
            if not study:raise HarnessError('no study')
            rows=[]
            for name in set(spec['ids']):
                row=db.execute('SELECT * FROM research_jobs WHERE owner=? AND id=?',(self.owner,name)).fetchone()
                if not row or row['state'] not in {'PENDING','CANCELLED'}:
                    raise HarnessError('only pending jobs can be cancelled; running processes are protected')
                rows.append(row)
            for row in rows:
                record=strict_json(row['record']);record.update(cancel_reason=spec['reason'],cancelled_at=time.time())
                db.execute("UPDATE research_jobs SET state='CANCELLED',record=? WHERE owner=? AND id=?",(canonical(record),self.owner,row['id']))
            study['revision']+=1;self._save(db,study)
        return self.status()

    def _context(self, root, job):
        from .crew import fingerprint
        cwd=inside(root,job['cwd'],allow_root=True);programs={}
        for argv in (job['argv'],job['verify_argv']):
            exe=argv[0]
            resolved=str((cwd/exe).resolve()) if ('/' in exe or '\\' in exe) and not Path(exe).is_absolute() else shutil.which(exe)
            if not resolved or not Path(resolved).is_file():raise HarnessError('experiment executable unavailable')
            if resolved not in programs:programs[resolved]=file_hash(Path(resolved))
        return {'source':fingerprint(root,job['dependencies'])['sha256'],'programs':programs,
                'environment':json_hash({k:os.environ.get(k) for k in job['environment_keys']}),
                'definition':json_hash(job),'platform':sys.platform,'python':sys.version}

    def _claim(self, nonce):
        with self.store.db(True) as db:
            study=self._read(db)
            if study['state']!='RUNNING' or study['supervisor']['nonce']!=nonce:return None
            from .crew import _get
            contract=_get(db,self.owner)
            request=db.execute("SELECT value FROM kv WHERE scope=? AND name='request_hash'",(self.owner,)).fetchone()
            interrupted=db.execute("SELECT value FROM kv WHERE scope=? AND name='interrupted'",(self.owner,)).fetchone()
            valid=bool(contract and contract['run_id']==study['configuration']['contract_run_id'] and
                       json_hash(contract['requirements'])==study['configuration']['requirements_hash'] and
                       contract['phase']=='EXECUTE' and (not request or strict_json(request[0])==contract['request_hash']) and
                       not (interrupted and strict_json(interrupted[0])))
            if not valid:
                study.update(state='PAUSING',pause_reason='contract/request/interruption changed; active work retained')
                self._save(db,study);return None
            row=self._ready_row(db)
            if row:
                job=strict_json(row['spec'])
                record=strict_json(row['record'])
                actual_deps={r[0] for r in db.execute('SELECT dependency_id FROM research_dependencies WHERE owner=? AND job_id=?',(self.owner,job['id']))}
                if actual_deps!=set(job['depends_on']) or record.get('definition_hash')!=json_hash(job):
                    raise HarnessError('research definition/index is corrupt; do not launch')
                record.update(claim_nonce=nonce,started_at=time.time(),pid=None,stage='CLAIMED')
                db.execute("UPDATE research_jobs SET state='RUNNING',record=? WHERE owner=? AND id=? AND state='PENDING'",(canonical(record),self.owner,job['id']))
                return job
        return None

    def _record(self, job_id, fields, nonce):
        with self.store.db(True) as db:
            row=db.execute('SELECT record,state FROM research_jobs WHERE owner=? AND id=?',(self.owner,job_id)).fetchone()
            if not row or row['state']!='RUNNING':raise HarnessError('experiment is no longer running')
            value=strict_json(row['record'])
            if value.get('claim_nonce')!=nonce:raise HarnessError('experiment ownership changed before recording progress')
            value.update(fields)
            db.execute('UPDATE research_jobs SET record=? WHERE owner=? AND id=?',(canonical(value),self.owner,job_id))

    def _input_context(self, root, job):
        with self.store.db() as db:
            row=db.execute('SELECT record FROM research_jobs WHERE owner=? AND id=?',(self.owner,job['id'])).fetchone()
            record=strict_json(row[0]);ident=record.get('input_snapshot_id')
            if 'input_snapshot_id' in record and (not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{64}',ident)):
                raise HarnessError('invalid input snapshot identity; do not reinterpret corrupt data as legacy')
            stored=db.execute('SELECT context FROM research_snapshots WHERE owner=? AND snapshot_id=?',(self.owner,ident)).fetchone() if ident else None
        if 'input_snapshot_id' not in record:
            if record.get('input_snapshot_required') is True:raise HarnessError('required input snapshot identity is missing')
            return self._context(root,job)  # Explicit legacy record lacking enqueue identity.
        if not stored:raise HarnessError('missing input snapshot; preserve the job')
        context=strict_json(stored[0])
        if json_hash(context)!=ident:raise HarnessError('changed input snapshot; execution refused')
        return {**context,'definition':json_hash(job)}

    def _execute(self, job, nonce):
        with self.store.db() as db:study=self._read(db)
        root=Path(study['configuration']['workspace']);logdir=self.store.directory/'research'/self.owner/job['id']
        no_symlinks(logdir);logdir.mkdir(parents=True,exist_ok=True)
        record={'claim_nonce':nonce,'definition_hash':json_hash(job),'started_at':time.time(),'authority_promoted':False}
        state='ERROR'
        try:
            if any(inside(root,p).exists() for p in job['outputs']):raise HarnessError('output appeared before execution; preserved without overwrite')
            before=self._input_context(root,job)
            record['input_context']=before
            if before!=self._context(root,job):
                state='STALE';record['stage']='PREFLIGHT';record['compute_started']=False
                raise HarnessError('Input/executable/environment changed since enqueue; computation was not started',code='INPUT_CHANGED_BEFORE_EXECUTION')
            def run(argv,label):
                self._record(job['id'],{'stage':label+'_LAUNCHING','pid':None,'process_identity':None},nonce)
                with (logdir/(label+'.stdout')).open('xb') as stdout, (logdir/(label+'.stderr')).open('xb') as stderr:
                    env=os.environ.copy();env['PYTHONDONTWRITEBYTECODE']='1'
                    proc=subprocess.Popen(argv,cwd=inside(root,job['cwd'],allow_root=True),stdin=subprocess.DEVNULL,
                                          stdout=stdout,stderr=stderr,shell=False,env=env)
                    try:
                        self._record(job['id'],{'pid':proc.pid,'process_identity':probe(proc.pid).get('identity'),'stage':label,'process_started_at':time.time(),'claim_nonce':nonce},nonce)
                    finally:
                        # A future owns a successfully started process until exit,
                        # even if the subsequent metadata write fails.
                        code=proc.wait()
                record[label+'_exit_code']=code
                record[label+'_stdout_sha256']=file_hash(logdir/(label+'.stdout'))
                record[label+'_stderr_sha256']=file_hash(logdir/(label+'.stderr'))
                self._record(job['id'],{label+'_exit_code':code,label+'_ended_at':time.time()},nonce)
                return code
            from .crew import fingerprint
            if run(job['argv'],'execute')!=0:state='FAILED'
            elif before!=self._context(root,job):state='STALE'
            elif any(not inside(root,p).exists() for p in job['outputs']):
                state='FAILED';record['error']='declared output missing'
            else:
                outputs=fingerprint(root,job['outputs'])
                if run(job['verify_argv'],'verify')!=0:state='FAILED'
                else:
                    result_file=inside(root,job['result_path'])
                    if not result_file.is_file() or result_file.stat().st_size>4*1024*1024:raise HarnessError('result JSON missing or oversized')
                    with result_file.open('rb') as stream:data=stream.read(4*1024*1024+1)
                    if len(data)>4*1024*1024:raise HarnessError('result JSON exceeds 4 MiB')
                    value=strict_json(data.decode('utf-8-sig'))
                    for key in job['score_key'].split('.'):
                        if not isinstance(value,dict) or key not in value:raise HarnessError('score field missing')
                        value=value[key]
                    if type(value) not in {int,float} or not Decimal(str(value)).is_finite():raise HarnessError('score is not a finite JSON number')
                    # Bind parsing to the same output snapshot used by verification.
                    from .util import digest
                    parsed_sha=digest(data)
                    from .paths import relative_id
                    expected_result=next((entry.get('sha256') for name,entry in outputs['entries'].items() if relative_id(name)==relative_id(job['result_path'])),None)
                    if parsed_sha!=expected_result or fingerprint(root,job['outputs'])!=outputs or before!=self._context(root,job):
                        state='STALE'
                        raise HarnessError('result or input changed while ingesting')
                    record.update(score=str(value),outputs_fingerprint=outputs['sha256'],result_path=job['result_path'],
                                  result_sha256=parsed_sha,metric_unit=study['configuration']['metric_unit'])
                    state='VERIFIED'
        except (OSError,ValueError,KeyError,TypeError,RecursionError) as exc:record['error']=type(exc).__name__+': '+str(exc)
        record['ended_at']=time.time()
        with self.store.db(True) as db:
            row=db.execute('SELECT state,record FROM research_jobs WHERE owner=? AND id=?',(self.owner,job['id'])).fetchone()
            old=strict_json(row['record'])
            if row['state']!='RUNNING' or old.get('claim_nonce')!=nonce:raise HarnessError('experiment ownership changed')
            record={**old,**record};db.execute('UPDATE research_jobs SET state=?,record=? WHERE owner=? AND id=?',(state,canonical(record),self.owner,job['id']))
            current=self._read(db);current['revision']+=1
            if state=='VERIFIED':
                best=current.get('best_verified_candidate')
                score=Decimal(record['score']);better=best is None or (score>Decimal(best['score']) if current['configuration']['direction']=='max' else score<Decimal(best['score']))
                if better:
                    current['best_verified_candidate']={'id':job['id'],'score':record['score'],'result_sha256':record['result_sha256'],
                                                        'outputs_fingerprint':record['outputs_fingerprint'],'authority_promoted':False}
                    current['last_improvement_at']=time.time()
            self._save(db,current)
        return {'id':job['id'],'state':state,**record}

    def worker(self, nonce):
        if not isinstance(nonce,str) or not re.fullmatch('[a-f0-9]{32}',nonce):raise HarnessError('invalid supervisor nonce')
        with self.store.db(True) as db:
            study=self._read(db)
            if not study or study['state'] not in {'STARTING','PAUSING'} or study['supervisor']['nonce']!=nonce:
                raise HarnessError('controller already claimed or belongs to another study')
            if study['state']=='STARTING':study['state']='RUNNING'
            study['supervisor'].update(pid=os.getpid(),process_identity=probe(os.getpid()).get('identity'),heartbeat=time.time());self._save(db,study)
        running=[]
        with ThreadPoolExecutor(max_workers=study['configuration']['workers']) as pool:
            while True:
                for future in tuple(running):
                    if future.done():future.result();running.remove(future)
                with self.store.db(True) as db:
                    current=self._read(db)
                    if current['supervisor']['nonce']!=nonce:raise HarnessError('controller identity changed; do not start replacement work')
                    current['supervisor']['heartbeat']=time.time()
                    if current['state']=='PAUSING' and not running:
                        current['state']='PAUSED';current['supervisor']['ended_at']=time.time();self._save(db,current);break
                    self._save(db,current)
                if current['state']=='RUNNING':
                    while len(running)<study['configuration']['workers']:
                        job=self._claim(nonce)
                        if job is None:break
                        running.append(pool.submit(self._execute,job,nonce))
                elif current['state']!='PAUSING':raise HarnessError('unexpected study state; active processes are not terminated')
                if running:
                    # Event-driven local completion. Keep a bounded timeout for
                    # pause/new work/heartbeat; this does not wake the model.
                    wait_futures(running, timeout=1.0, return_when=FIRST_COMPLETED)
                else:
                    time.sleep(1.0)  # idle only; active completions wake immediately
        return self.status()

    @staticmethod
    def _wake_reason(current, previous, elapsed):
        if not current.get('configured'):return 'UNCONFIGURED'
        if current['state'] in {'PAUSED','FINISHED','PAUSING'}:return current['state']
        counts=current['counts'];old=previous.get('counts',{})
        if any(counts[k]>old.get(k,0) for k in ('FAILED','ERROR','STALE')):return 'NEW_FAILURE'
        if counts['RUNNING']==0 and not current['ready']:
            return 'DEPENDENCY_BLOCKED' if counts['PENDING'] else 'QUEUE_DRAINED'
        policy=current['policy']
        completed=sum(counts[k]-old.get(k,0) for k in TERMINAL)
        if completed>=policy['completed']:return 'BATCH_READY'
        # Single job/revision changes are not an LLM wake signal.
        if elapsed>=policy['min_interval']:
            if counts['PENDING']<=policy['queue_low_water'] and counts['PENDING']<old.get('PENDING',0):
                return 'QUEUE_LOW'
            now=current.get('best');before=previous.get('best')
            threshold=policy['improvement_absolute']
            if threshold is not None and now and before and now['id']!=before['id']:
                if abs(Decimal(now['score'])-Decimal(before['score']))>=Decimal(threshold):return 'SIGNIFICANT_IMPROVEMENT'
        return None

    def wait(self, timeout=60):
        if type(timeout) is not int or not 1<=timeout<=300:raise HarnessError('wait timeout must be 1..300 seconds')
        started=time.monotonic();initial=self._signal()
        previous=self.store.get(self.owner,'research-wait-cursor',{})
        if previous.get('study_id')!=initial.get('study_id'):
            previous={**initial,'counts':{**initial.get('counts',{}),**{k:0 for k in TERMINAL}}}
        elapsed_before=max(0,time.time()-previous.get('delivered_at',time.time()))
        current=initial;reason=None;last_health_check=-5.0
        notified_exit=previous.get('controller_exit_notified')
        while True:
            elapsed=time.monotonic()-started
            reason=self._wake_reason(current,previous,elapsed+elapsed_before)
            if not reason and elapsed-last_health_check>=5:
                last_health_check=elapsed
                if self.controller_health()['state']=='EXITED':
                    nonce=(current.get('supervisor') or {}).get('nonce')
                    if notified_exit!=nonce:
                        notified_exit=nonce;reason='CONTROLLER_EXITED'
            if reason or elapsed>=timeout:break
            time.sleep(min(.5,timeout-elapsed));current=self._signal()
        elapsed=time.monotonic()-started
        counts=current.get('counts',{});old=previous.get('counts',{})
        delta={key:counts.get(key,0)-old.get(key,0) for key in sorted(set(counts)|set(old))}
        self.store.put(self.owner,'research-wait-cursor',{**current,'delivered_at':time.time(),'controller_exit_notified':notified_exit})
        self.store.put(self.owner,'research-last-wait',{'ended_at':time.time(),'elapsed':elapsed})
        return {'timed_out':reason is None,'wake_reason':reason or 'TIMEOUT','delta_counts':delta,
                'status':self.status(),'elapsed_seconds':elapsed}
