"""Transactional work plans for a Luna-led Codex session.

This module NEVER calls a model. Codex performs the real spawn/wait calls.
Reservations are not agents, returned work is not accepted work, and accepted
work is not proof that the integrated result meets the user's requirements.
"""
from __future__ import annotations
import json
import re
import time
import uuid
from pathlib import Path
from .store import Store
from .util import HarnessError, strict_json, canonical
from .coordination import overlaps, normalized

MAX_PARALLEL = 6
MAX_LAUNCHES = 8  # a safety budget, NOT a claim of model equivalence
SCHEMA = '''
CREATE TABLE IF NOT EXISTS plans (owner TEXT PRIMARY KEY, plan_id TEXT, spec TEXT, created REAL);
CREATE TABLE IF NOT EXISTS work (
 owner TEXT, plan_id TEXT, id TEXT, spec TEXT, state TEXT, ticket TEXT UNIQUE,
 agent_id TEXT, workspace TEXT, result TEXT, launched INTEGER DEFAULT 0,
 PRIMARY KEY(owner,plan_id,id));
CREATE TABLE IF NOT EXISTS dispatches (
 owner TEXT, call_id TEXT, ticket TEXT, state TEXT, PRIMARY KEY(owner,call_id));
'''
IDENT = re.compile(r'^[a-z][a-z0-9_-]{0,47}$')
TICKET = re.compile(r'(?m)^LUNASTRA_TICKET=([a-f0-9]{32})\s*$')

def text(value, label, maximum=12000):
    if not isinstance(value, str) or not value.strip() or '\x00' in value or len(value)>maximum:
        raise HarnessError('invalid '+label)
    return value.strip()

def unpack_response(value):
    """Read documented structured results, never infer success from prose."""
    if isinstance(value, str):
        try: value=strict_json(value)
        except (ValueError, TypeError): return {}
    if isinstance(value,list):
        for item in value:
            if isinstance(item,dict) and item.get('type') in {'text','output_text'}:
                found=unpack_response(item.get('text'))
                if found:return found
        return {}
    if not isinstance(value, dict): return {}
    if value.get('isError') or value.get('is_error'): return {}
    if isinstance(value.get('agent_id'),str): return value
    for item in value.get('content',[]) if isinstance(value.get('content'),list) else []:
        if isinstance(item,dict) and item.get('type')=='text':
            found=unpack_response(item.get('text'))
            if found: return found
    return value

def plan_definition(root: Path, spec: dict, generation: str):
    if not isinstance(spec,dict) or set(spec)-{'goal','tasks','parallel_limit','launch_limit'}:
        raise HarnessError('invalid plan fields')
    goal=text(spec.get('goal'),'goal')
    cap=spec.get('parallel_limit',MAX_PARALLEL)
    budget=spec.get('launch_limit',MAX_LAUNCHES)
    if type(cap) is not int or not 1<=cap<=MAX_PARALLEL: raise HarnessError('parallel_limit must be 1..6')
    if type(budget) is not int or not 1<=budget<=MAX_LAUNCHES: raise HarnessError('launch_limit must be 1..8')
    tasks=spec.get('tasks')
    if not isinstance(tasks,list) or len(tasks)>32: raise HarnessError('tasks must be a list of at most 32 units')
    clean=[]; ids=set(); descriptions=set()
    for t in tasks:
        if not isinstance(t,dict) or set(t)-{'id','kind','description','paths','depends_on','done_when','why_parallel'}:
            raise HarnessError('invalid task fields')
        name=t.get('id');kind=t.get('kind')
        if not isinstance(name,str) or not IDENT.fullmatch(name) or name in ids: raise HarnessError('invalid/duplicate task id')
        if kind not in {'investigate','implement','verify'}: raise HarnessError('invalid task kind')
        description=text(t.get('description'),'task description')
        normalized_description=' '.join(re.findall(r'\w+',description.casefold()))
        if normalized_description in descriptions: raise HarnessError('duplicate task description; do not duplicate work')
        descriptions.add(normalized_description);ids.add(name)
        paths=t.get('paths',[])
        if not isinstance(paths,list) or not paths or len(paths)>100: raise HarnessError('explicit task paths required')
        paths=sorted(set(normalized(root,p) for p in paths))
        if kind=='implement' and '.' in paths: raise HarnessError('implementation requires a narrow file/directory scope')
        if any(p.split('/')[0] in {'.git','.codex','.agents'} for p in paths): raise HarnessError('do not delegate repository control files')
        deps=t.get('depends_on',[])
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps): raise HarnessError('invalid dependencies')
        done=t.get('done_when')
        if not isinstance(done,list) or not done: raise HarnessError('observable done_when required')
        done=[text(x,'acceptance condition',3000) for x in done]
        why=text(t.get('why_parallel'),'why parallel work saves time or resolves uncertainty',3000)
        clean.append(dict(id=name,kind=kind,description=description,paths=paths,depends_on=deps,done_when=done,why_parallel=why))
    by_id={t['id']:t for t in clean};visiting=set();visited=set()
    def visit(name):
        if name in visiting: raise HarnessError('cyclic task dependency')
        if name in visited: return
        visiting.add(name)
        for dep in by_id[name]['depends_on']:
            if dep not in by_id: raise HarnessError('unknown dependency: '+dep)
            visit(dep)
        visiting.remove(name);visited.add(name)
    for name in by_id:visit(name)
    obj=dict(generation=generation,goal=goal,tasks=clean,parallel_limit=cap,launch_limit=budget,workspace=str(root.resolve()))
    return obj

class Team:
    def __init__(self, store: Store):
        self.store=store
        store.ensure_schema('team', SCHEMA)

    def plan(self, owner: str, root: Path, spec: dict):
        obj=plan_definition(root,spec,str(self.store.get(owner,'generation','startup')))
        clean=obj['tasks']
        with self.store.db(True) as db:
            old=db.execute('SELECT * FROM plans WHERE owner=?',(owner,)).fetchone()
            if old and strict_json(old['spec'])==obj:return self._status(db,owner)
            if old:
                unfinished=db.execute("SELECT 1 FROM work WHERE owner=? AND plan_id=? AND state NOT IN ('accepted','abandoned') LIMIT 1",(owner,old['plan_id'])).fetchone()
                if unfinished:
                    started=db.execute("SELECT 1 FROM work WHERE owner=? AND plan_id=? AND state NOT IN ('pending','abandoned') LIMIT 1",(owner,old['plan_id'])).fetchone()
                    unresolved=db.execute("SELECT 1 FROM dispatches d JOIN work w ON w.ticket=d.ticket WHERE w.owner=? AND w.plan_id=? AND d.state IN ('pending','running','unknown') LIMIT 1",(owner,old['plan_id'])).fetchone()
                    if started or unresolved:
                        raise HarnessError('preserve active/returned work; only a wholly undispatched plan may be replaced')
                    # Keep the abandoned plan as history, retaining turn-scoped launch accounting.
                    db.execute("UPDATE work SET state='abandoned',result=? WHERE owner=? AND plan_id=? AND state='pending'",(canonical({'reason':'superseded before dispatch'}),owner,old['plan_id']))
            pid=uuid.uuid4().hex
            db.execute('INSERT INTO plans VALUES(?,?,?,?) ON CONFLICT(owner) DO UPDATE SET plan_id=excluded.plan_id,spec=excluded.spec,created=excluded.created',(owner,pid,canonical(obj),time.time()))
            for task in clean:db.execute('INSERT INTO work(owner,plan_id,id,spec,state) VALUES(?,?,?,?,?)',(owner,pid,task['id'],canonical(task),'pending'))
            return self._status(db,owner)

    def _status(self,db,owner):
        plan=db.execute('SELECT * FROM plans WHERE owner=?',(owner,)).fetchone()
        if not plan:return {'configured':False,'tasks':[],'complete':True,'active':0}
        rows=[dict(r) for r in db.execute('SELECT * FROM work WHERE owner=? AND plan_id=? ORDER BY rowid',(owner,plan['plan_id']))]
        for row in rows:
            row['spec']=strict_json(row['spec']);row['result']=strict_json(row['result']) if row['result'] else None
        definition=strict_json(plan['spec']);generation=definition.get('generation','startup')
        used=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(owner,'launch_budget:'+generation)).fetchone()
        return {'configured':True,'plan_id':plan['plan_id'],'goal':definition['goal'],'generation':generation,
                'tasks':rows,'active':sum(r['state'] in {'reserved','running'} for r in rows),
                'launches':int(strict_json(used[0])) if used else 0,'plan_launches':sum(r['launched'] for r in rows),'complete':all(r['state']=='accepted' for r in rows),
                'terminal':all(r['state'] in {'accepted','abandoned'} for r in rows),
                'limit':'An accepted work unit is not final integrated-test evidence.'}

    def status(self,owner):
        with self.store.db() as db:return self._status(db,owner)

    def reserve(self,owner):
        with self.store.db(True) as db:
            status=self._status(db,owner)
            if not status['configured']:raise HarnessError('register the work plan first')
            plan=strict_json(db.execute('SELECT spec FROM plans WHERE owner=?',(owner,)).fetchone()[0])
            slots=max(0,min(plan['parallel_limit']-status['active'],plan['launch_limit']-status['launches']))
            occupied=[r['spec'] for r in status['tasks'] if r['state'] in {'reserved','running','returned'}]
            done={r['id'] for r in status['tasks'] if r['state']=='accepted'}
            chosen=[]
            for row in status['tasks']:
                t=row['spec']
                if not slots:break
                if row['state']!='pending' or not set(t['depends_on'])<=done:continue
                # Independent checkouts still need interface/merge ownership. Serialize overlapping writers.
                if t['kind']=='implement' and any(o['kind']=='implement' and any(overlaps(a,b) for a in t['paths'] for b in o['paths']) for o in occupied):continue
                ticket=uuid.uuid4().hex
                db.execute("UPDATE work SET state='reserved',ticket=?,launched=launched+1 WHERE owner=? AND plan_id=? AND id=?",(ticket,owner,status['plan_id'],row['id']))
                chosen.append({**t,'ticket':ticket});occupied.append(t);slots-=1
            budget_name='launch_budget:'+plan.get('generation','startup')
            db.execute('INSERT INTO kv VALUES(?,?,?) ON CONFLICT(scope,name) DO UPDATE SET value=excluded.value',(owner,budget_name,canonical(status['launches']+len(chosen))))
            return {'reserved':chosen,'no_new_workers':not chosen,'budget_exhausted':status['launches']>=plan['launch_limit'],
                    'note':'Reservations are not spawned models. Use available native Codex tools; unavailable work stays with the leader.'}

    def set_workspace(self,owner,ticket,path):
        with self.store.db(True) as db:
            r=db.execute('SELECT * FROM work WHERE owner=? AND ticket=?',(owner,ticket)).fetchone()
            if not r or r['state']!='reserved':raise HarnessError('not an owned reservation')
            db.execute('UPDATE work SET workspace=? WHERE ticket=?',(str(path),ticket))

    def lookup(self,ticket):
        with self.store.db() as db:
            row=db.execute('SELECT * FROM work WHERE ticket=?',(ticket,)).fetchone()
        return dict(row) if row else None

    def pre_spawn(self,owner,call_id,payload,model):
        if not isinstance(payload,dict):raise HarnessError('unrecognized native spawn input')
        message=payload.get('message','')
        matches=TICKET.findall(message) if isinstance(message,str) else []
        if len(matches)!=1:raise HarnessError('use a reserved LunAstra task ticket, not an untracked additional worker')
        ticket=matches[0]
        if payload.get('model') is not None and payload.get('model')!=model:raise HarnessError('LunAstra may not switch the selected Luna model')
        if payload.get('service_tier') is not None:raise HarnessError('do not override the current service tier')
        if payload.get('reasoning_effort') is not None:raise HarnessError('inherit the current reasoning setting; do not override it')
        if payload.get('agent_type') is not None:raise HarnessError('custom agent roles may override Luna; use the default inherited role')
        # Full forks inherit model/effort; fresh/partial contexts are not an accepted fallback.
        full=(payload.get('fork_context') is True or ('task_name' in payload and payload.get('fork_turns','all')=='all'))
        if not full:raise HarnessError('use a full-history inherited fork; fresh-context role/default settings cannot be assumed to preserve the selected model and effort')
        with self.store.db(True) as db:
            old=db.execute('SELECT * FROM dispatches WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if old:
                if old['ticket']!=ticket:raise HarnessError('tool call identity was reused for another task')
                return ticket
            row=db.execute('SELECT * FROM work WHERE owner=? AND ticket=?',(owner,ticket)).fetchone()
            if not row or row['state']!='reserved':raise HarnessError('task is not reserved by this leader')
            if db.execute("SELECT 1 FROM dispatches WHERE ticket=? AND state IN ('pending','running')",(ticket,)).fetchone():raise HarnessError('task already dispatched')
            db.execute('INSERT INTO dispatches VALUES(?,?,?,?)',(owner,call_id,ticket,'pending'))
        return ticket

    def post_spawn(self,owner,call_id,response):
        result=unpack_response(response);agent=result.get('agent_id')
        with self.store.db(True) as db:
            row=db.execute('SELECT * FROM dispatches WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if not row:return
            if row['state'] not in {'pending','unknown'}:return
            if isinstance(response,dict) and (response.get('isError') is True or response.get('is_error') is True):
                db.execute("UPDATE dispatches SET state='failed' WHERE owner=? AND call_id=?",(owner,call_id))
                db.execute("UPDATE work SET state='failed' WHERE ticket=?",(row['ticket'],))
                return
            if not isinstance(agent,str) or not agent:
                db.execute("UPDATE dispatches SET state='unknown' WHERE owner=? AND call_id=?",(owner,call_id))
                # Do not release an unknown possibly-running worker or spawn a duplicate.
                return
            work=db.execute('SELECT * FROM work WHERE ticket=?',(row['ticket'],)).fetchone()
            if work['agent_id'] and work['agent_id']!=agent:raise HarnessError('native worker identity mismatch')
            if db.execute('SELECT 1 FROM work WHERE agent_id=? AND ticket<>?',(agent,row['ticket'])).fetchone():
                raise HarnessError('native worker is already bound to another ticket')
            db.execute("UPDATE dispatches SET state='running' WHERE owner=? AND call_id=?",(owner,call_id))
            db.execute("UPDATE work SET agent_id=?,state=CASE WHEN state='reserved' THEN 'running' ELSE state END WHERE ticket=?",(agent,row['ticket']))

    def join(self,key,ticket,meta):
        if meta.get('role')!='worker':raise HarnessError('only the actual delegated worker can join')
        with self.store.db(True) as db:
            row=db.execute('SELECT * FROM work WHERE ticket=?',(ticket,)).fetchone()
            if not row or row['state'] not in {'reserved','running'}:raise HarnessError('unknown/inactive ticket')
            rootmeta=self.store.get(row['owner'],'meta',{})
            parent=meta.get('parent_session_id')
            if parent is None and meta.get('session_id') != meta.get('agent_id'):
                parent=meta.get('session_id')  # legacy host, not the native child ID
            if parent is not None and parent!=rootmeta.get('session_id'):
                raise HarnessError('ticket belongs to another parent session')
            if row['agent_id'] and row['agent_id']!=meta.get('agent_id'):raise HarnessError('ticket is bound to another agent')
            if meta.get('model')!=rootmeta.get('model'):
                raise HarnessError('worker model differs from the observed leader model')
            if parent is None and (not row['agent_id'] or not db.execute(
                    "SELECT 1 FROM dispatches WHERE owner=? AND ticket=? AND state='running'",
                    (row['owner'],ticket)).fetchone()):
                raise HarnessError('native spawn result not registered yet; retry this same ticket after the leader observes it; do not create a replacement worker')
            task=strict_json(row['spec'])
            if task['kind']=='implement' and not row['workspace']:raise HarnessError('implementation checkout is not prepared')
            db.execute("UPDATE work SET state='running',agent_id=? WHERE ticket=?",(meta.get('agent_id'),ticket))
        meta.update(parent_session_id=rootmeta['session_id'],team_owner=row['owner'],team_ticket=ticket,assigned_workspace=row['workspace'] or meta['workspace'],
                    assigned_paths=task['paths'],read_only=task['kind']!='implement')
        self.store.put(key,'meta',meta)
        return {'task':task,'workspace':meta['assigned_workspace'],'read_only':meta['read_only'],
                'instructions':'Use this workspace explicitly in each tool. Do not edit the leader checkout. Return evidence and unresolved issues; do not spawn workers.'}

    def returned(self,ticket,handback):
        with self.store.db(True) as db:
            row=db.execute('SELECT state FROM work WHERE ticket=?',(ticket,)).fetchone()
            if row and row['state'] in {'reserved','running','returned'}:
                db.execute("UPDATE work SET state='returned',result=? WHERE ticket=?",(canonical(handback),ticket))
                db.execute("UPDATE dispatches SET state='returned' WHERE ticket=?",(ticket,))

    def accept(self,owner,task_id,review):
        review=text(review,'leader review',4000)
        with self.store.db(True) as db:
            pid=db.execute('SELECT plan_id FROM plans WHERE owner=?',(owner,)).fetchone()
            row=db.execute('SELECT * FROM work WHERE owner=? AND plan_id=? AND id=?',(owner,pid[0] if pid else '',task_id)).fetchone()
            if not row or row['state']!='returned':raise HarnessError('only returned work may be accepted')
            result=strict_json(row['result'] or '{}');task=strict_json(row['spec'])
            if task['kind']=='implement' and (result.get('status')!='TESTED' or not result.get('integrated')):
                raise HarnessError('implementation requires current tested handback and checked integration')
            if result.get('status') not in {'ANALYSIS','TESTED'}:raise HarnessError('partial or unverified work cannot be accepted as complete')
            result['leader_review']=review
            db.execute("UPDATE work SET state='accepted',result=? WHERE owner=? AND plan_id=? AND id=?",(canonical(result),owner,row['plan_id'],task_id))
        return {'accepted':task_id,'final_integrated_tests_still_required':True}

    def abandon(self,owner,task_id,reason):
        reason=text(reason,'abandon reason')
        with self.store.db(True) as db:
            pid=db.execute('SELECT plan_id FROM plans WHERE owner=?',(owner,)).fetchone()
            row=db.execute('SELECT * FROM work WHERE owner=? AND plan_id=? AND id=?',(owner,pid[0] if pid else '',task_id)).fetchone()
            if not row or row['state'] in {'running','accepted'}:raise HarnessError('cannot abandon a running or accepted worker')
            if db.execute("SELECT 1 FROM dispatches WHERE ticket=? AND state IN ('pending','running','unknown')",(row['ticket'],)).fetchone():
                raise HarnessError('resolve the actual worker state before abandoning; no process is terminated')
            db.execute("UPDATE work SET state='abandoned',result=? WHERE owner=? AND plan_id=? AND id=?",(canonical({'reason':reason}),owner,row['plan_id'],task_id))
        return {'abandoned':task_id,'goal_complete':False}

    def resolve_locally(self,owner,task_id,review,evidence):
        text(review,'local resolution review')
        if not evidence.get('passed') or not evidence.get('finish') or not evidence['finish'].get('valid') or evidence['finish'].get('kind')!='tested':
            raise HarnessError('local resolution requires current integrated test evidence')
        with self.store.db(True) as db:
            plan=db.execute('SELECT plan_id FROM plans WHERE owner=?',(owner,)).fetchone()
            row=db.execute('SELECT * FROM work WHERE owner=? AND plan_id=? AND id=?',(owner,plan[0] if plan else '',task_id)).fetchone()
            if not row or row['state'] not in {'abandoned','pending','failed'}:raise HarnessError('local resolution cannot replace a running worker')
            result={'resolved_by':'leader','review':review,'task_hash':evidence.get('task_hash'),'status':'TESTED'}
            db.execute("UPDATE work SET state='accepted',result=? WHERE owner=? AND plan_id=? AND id=?",(canonical(result),owner,row['plan_id'],task_id))
        return {'accepted':task_id,'resolved_by':'leader'}

    def pre_followup(self,owner,payload):
        if not isinstance(payload,dict):raise HarnessError('unrecognized follow-up input')
        if payload.get('interrupt'):raise HarnessError('do not interrupt running work to send routine follow-ups')
        target=payload.get('target') or payload.get('id')
        with self.store.db() as db:
            plan=db.execute('SELECT plan_id FROM plans WHERE owner=?',(owner,)).fetchone()
            row=db.execute('SELECT state FROM work WHERE owner=? AND plan_id=? AND agent_id=?',(owner,plan[0] if plan else '',target)).fetchone()
        if not row or row['state']!='running':
            raise HarnessError('follow-up work must belong to a running tracked task; inspect its result or finish the remaining work locally instead of starting replacement waves')

    def observed_statuses(self,owner,response):
        """Apply explicit native V1 terminal statuses; unknown formats remain unknown."""
        result=unpack_response(response);states=result.get('status',{})
        if not isinstance(states,dict):return
        with self.store.db(True) as db:
            for agent,status in states.items():
                row=db.execute("SELECT * FROM work WHERE owner=? AND agent_id=? AND state IN ('reserved','running')",(owner,agent)).fetchone()
                if not row:continue
                if status in ('interrupted','shutdown','not_found') or (isinstance(status,dict) and 'errored' in status):
                    db.execute("UPDATE work SET state='failed',result=? WHERE ticket=?",(canonical({'native_status':status,'status':'UNVERIFIED'}),row['ticket']))
                    db.execute("UPDATE dispatches SET state='failed' WHERE ticket=?",(row['ticket'],))
                elif isinstance(status,dict) and 'completed' in status:
                    db.execute("UPDATE work SET state='returned',result=? WHERE ticket=?",(canonical({'status':'UNVERIFIED','reason':'Native completion observed without a checked worker handback'}),row['ticket']))
                    db.execute("UPDATE dispatches SET state='returned' WHERE ticket=?",(row['ticket'],))

    def pre_close(self,owner,payload):
        if not isinstance(payload,dict):raise HarnessError('unrecognized close input')
        target=payload.get('target') or payload.get('id')
        with self.store.db() as db:
            row=db.execute("SELECT * FROM work WHERE owner=? AND agent_id=? AND state IN ('returned','accepted') ORDER BY rowid DESC LIMIT 1",(owner,target)).fetchone()
        if not row:raise HarnessError('close only an observed completed worker whose result is retained; do not close running workers')
        result=strict_json(row['result'] or '{}')
        key=result.get('worker_key')
        if not key:raise HarnessError('worker check-controller state is unknown; keep its session open')
        from .jobs import Jobs
        if Jobs(self.store,key,Path(__file__).resolve().parents[1]).active():raise HarnessError('worker has an outstanding check controller; preserve it')
