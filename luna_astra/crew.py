"""Fixed seven-session protocol built on the existing local work/evidence engine.

Exactly one native root and six observed child IDs. Planning, execution and
review reuse those IDs; a reservation is never called a running model. No model
API client, hidden model selection, automatic native calls or OS sandbox.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from .store import Store, evidence_directory
from .team import Team, TICKET, text, plan_definition, unpack_response
from .util import HarnessError, canonical, strict_json, json_hash, inside, file_hash, no_symlinks
from .coordination import normalized, overlaps
from .evidence import Evidence
from .jobs import Jobs
from .scan import observe
from .gitspace import Workspaces

SLOTS = 6
STATE = 'fixed_seven'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS crew_members (
 owner TEXT, slot INTEGER, agent_id TEXT UNIQUE, worker_key TEXT,
 PRIMARY KEY(owner,slot), CHECK(slot BETWEEN 1 AND 6));
CREATE TABLE IF NOT EXISTS crew_reports (
 ticket TEXT PRIMARY KEY, worker_key TEXT, body TEXT, at REAL);
CREATE TABLE IF NOT EXISTS crew_calls (
 owner TEXT, call_id TEXT, ticket TEXT, kind TEXT, input_hash TEXT,
 PRIMARY KEY(owner,call_id));
'''
PLAN_LENSES = (
    'Map the goal, requirements, input sources and dependencies. Identify missing authority or input.',
    'Develop a concrete solution and the smallest credible implementation path.',
    'Develop an independent alternative. Find evidence that would favor it over the obvious path.',
    'Try to falsify the initial assumptions. Return reproducible counterexamples, not a vote.',
    'Design independent acceptance checks, including numerical, format and boundary checks as applicable.',
    'Review the requested deliverable, usability, omissions, resource cost and a simpler route.',
)
REVIEW_LENSES = (
    'Review output structure and interface consistency against the locked requirements.',
    'Review calculations, transformations and data provenance against the source.',
    'Look for boundary cases and contradictions in the assembled output.',
    'Review regressions and preservation of protected content.',
    'Independently check every acceptance requirement against the assembled artifact and current test evidence.',
    'Independently attack the final deliverable: omissions, incorrect claims, usability and unresolved failure cases.',
)


def _get(db, owner):
    r = db.execute('SELECT value FROM kv WHERE scope=? AND name=?', (owner, STATE)).fetchone()
    if not r:
        return None
    s = strict_json(r[0])
    if (not isinstance(s, dict) or s.get('schema') != 1 or
            s.get('phase') not in {'PLAN', 'EXECUTE', 'REVIEW', 'COMPLETE'} or
            not isinstance(s.get('round'), int) or s['round'] < 1 or
            not re.fullmatch('[a-f0-9]{32}', str(s.get('run_id', '')))):
        raise HarnessError('invalid fixed-seven state; preserve it for recovery')
    return s


def _put(db, owner, s):
    db.execute('INSERT INTO kv VALUES(?,?,?) ON CONFLICT(scope,name) DO UPDATE SET value=excluded.value',
               (owner, STATE, canonical(s)))


def fingerprint(root: Path, paths: list[str]):
    """Bounded byte/mode identity, including binary files and absent outputs.

    Exceeding bounds is a visible blocker, never silent partial coverage.
    """
    root = Path(root).absolute(); no_symlinks(root); root = root.resolve()
    result = {}; count = 0; total = 0
    for name in paths:
        p = inside(root, name)
        pending = [p]
        if not p.exists():
            result[name] = {'missing': True}
            continue
        while pending:
            p = pending.pop(); no_symlinks(p)
            rel = p.relative_to(root).as_posix()
            if rel in result:
                continue
            count += 1
            if count > 20000:
                raise HarnessError('review snapshot exceeds 20000 entries; narrow declared scopes')
            if p.is_dir():
                result[rel] = {'directory': True}
                pending.extend(sorted(p.iterdir(), reverse=True))
            elif p.is_file():
                stat = p.stat(); total += stat.st_size
                if stat.st_size > 64*1024*1024 or total > 512*1024*1024:
                    raise HarnessError('review snapshot exceeds byte budget; narrow declared scopes')
                result[rel] = {'sha256': file_hash(p), 'mode': stat.st_mode & 0o777}
            else:
                raise HarnessError('special file in review scope: '+rel)
    return {'sha256': json_hash(result), 'entries': result}


class Crew:
    def __init__(self, store: Store, package: Path):
        self.store = store; self.package = Path(package)
        self.team = Team(store)
        with store.db() as db:
            db.executescript(SCHEMA)

    def _root(self, owner):
        meta = self.store.get(owner, 'meta', {})
        if meta.get('role') != 'root':
            raise HarnessError('only the observed root Luna coordinates the fixed crew')
        return Path(meta['workspace']), meta

    def status(self, owner):
        with self.store.db() as db:
            s = _get(db, owner)
            members = [dict(r) for r in db.execute('SELECT * FROM crew_members WHERE owner=? ORDER BY slot', (owner,))]
        if not s:
            return {'configured': False, 'required_total': 7, 'observed_children': 0, 'complete': False}
        work = self.team.status(owner)
        with self.store.db() as db:
            reports = {r['ticket']: strict_json(r['body']) for r in db.execute(
                'SELECT r.* FROM crew_reports r JOIN work w ON r.ticket=w.ticket WHERE w.owner=? AND w.plan_id=?',
                (owner, work['plan_id']))}
        return {**s, 'configured': True, 'required_total': 7, 'members': members,
                'observed_children': sum(bool(m['agent_id']) for m in members),
                'tasks': work['tasks'], 'reports': reports,
                'complete': s['phase'] == 'COMPLETE', 'actual_model_parity': 'NOT_MEASURED'}

    def summary(self, owner):
        s = self.status(owner)
        if not s['configured']:
            return s
        result={k: s[k] for k in ('run_id','phase','round','goal','requirements','required_total','observed_children','complete')} | {
            'tasks': [{'id': r['id'], 'state': r['state'], 'agent_id': r['agent_id']} for r in s['tasks']],
            'pending_request_change': s['request_hash'] != self.store.get(owner, 'request_hash'),
            'next': {'PLAN': 'crew-execute after six reports', 'EXECUTE': 'integrate implementations, then crew-review',
                     'REVIEW': 'crew-complete or crew-repair', 'COMPLETE': 'deliver the verified artifact'}[s['phase']]}
        if s['phase']=='COMPLETE':
            problem=self.completion_problem(owner)
            result['complete']=problem is None
            result['current_completion_problem']=problem
            if problem:result['next']='Preserve the historical proof; revise and reverify the changed work.'
        return result

    def inspect(self, owner):
        s=self.status(owner);result=self.summary(owner)
        if not s['configured']:return result
        result['reports']=[{'slot':r['id'],'verdict':s['reports'].get(r['ticket'],{}).get('verdict'),
            'summary':s['reports'].get(r['ticket'],{}).get('summary','')[:700],
            'report_command':'crew-report-read '+r['id'][1:]} for r in s['tasks']]
        result['output_paths']=s['output_paths']
        result['review_snapshot_sha256']=s.get('review_snapshot',{}).get('sha256')
        result['actual_model_parity']='NOT_MEASURED'
        return result

    def read_report(self, owner, slot):
        if type(slot) is not int or not 1<=slot<=6:raise HarnessError('slot must be 1..6')
        s=self.status(owner)
        if not s['configured']:raise HarnessError('no fixed crew')
        row=next(r for r in s['tasks'] if r['id']==f's{slot}')
        return {'task':row['spec'],'handback':row['result'],'report':s['reports'].get(row['ticket'])}

    def _definition(self, owner, root, goal, tasks):
        return plan_definition(root, {'goal': goal, 'parallel_limit': 6, 'launch_limit': 6, 'tasks': tasks},
                               str(self.store.get(owner, 'generation', 'startup')))

    @staticmethod
    def _tasks(lenses, paths):
        return [{'id': f's{i+1}', 'kind': 'investigate', 'description': lens, 'paths': paths,
                 'depends_on': [], 'done_when': ['Submit a source-linked crew-report and a checked handback.'],
                 'why_parallel': 'Distinct fixed-crew perspective; do not read peer conclusions before independent work.'}
                for i, lens in enumerate(lenses)]

    def _round(self, db, owner, s, definition):
        for task in definition['tasks']:
            capsule={'goal':s['goal'],'requirements':s['requirements'],'job':task,'decision':s.get('decision')}
            if len(canonical(capsule))>22000:raise HarnessError('work capsule exceeds its context budget; use concise obligations and source paths')
        pid = uuid.uuid4().hex
        definition['generation'] = str(self.store.get(owner,'generation','startup'))
        db.execute('INSERT INTO plans VALUES(?,?,?,?) ON CONFLICT(owner) DO UPDATE SET plan_id=excluded.plan_id,spec=excluded.spec,created=excluded.created',
                   (owner, pid, canonical(definition), time.time()))
        for task in definition['tasks']:
            db.execute('INSERT INTO work(owner,plan_id,id,spec,state) VALUES(?,?,?,?,?)',
                       (owner, pid, task['id'], canonical(task), 'pending'))
        s['plan_id'] = pid; s.pop('blocked', None); s.pop('proof', None)
        _put(db, owner, s)

    def start(self, owner, spec, *, revise=False):
        root, meta = self._root(owner)
        if not isinstance(spec,dict) or set(spec) != {'goal','requirements','evidence_paths','output_paths'}:
            raise HarnessError('crew-start needs goal, requirements, evidence_paths, output_paths')
        goal = text(spec['goal'], 'goal')
        requirements = spec['requirements']
        if not isinstance(requirements,list) or not 1 <= len(requirements) <= 64:
            raise HarnessError('1..64 explicit requirements required')
        requirements = [text(r, 'requirement', 3000) for r in requirements]
        if len(set(requirements)) != len(requirements):
            raise HarnessError('duplicate requirements')
        scopes = {}
        for field in ('evidence_paths','output_paths'):
            value = spec[field]
            if not isinstance(value,list) or not 1 <= len(value) <= 100:
                raise HarnessError(field+' requires explicit paths; outputs may be a local analysis report')
            scopes[field] = sorted(set(normalized(root,n) for n in value))
            if any(n == '.' or n.split('/')[0] in {'.git','.codex','.agents'} for n in scopes[field]):
                raise HarnessError('declare narrow non-control file or directory scopes')
            for n in scopes[field]:inside(root,n)
        definition = self._definition(owner,root,goal,self._tasks(PLAN_LENSES,scopes['evidence_paths']))
        request_hash = self.store.get(owner,'request_hash')
        if not request_hash:
            request_hash=json_hash(goal);self.store.put(owner,'request_hash',request_hash)
        s = {'schema':1,'run_id':uuid.uuid4().hex,'phase':'PLAN','round':1,'goal':goal,
             'requirements':requirements,**scopes,'request_hash':request_hash,'model':meta['model'],
             'created_at':time.time(),'ever_wrote':[]}
        self._idle(owner)
        with self.store.db(True) as db:
            old = _get(db,owner)
            if old and old['phase'] != 'COMPLETE' and not revise:
                if all(old[k]==s[k] for k in ('goal','requirements','evidence_paths','output_paths','request_hash')):
                    return self.summary(owner)
                raise HarnessError('active contract exists; settle running work and use crew-revise explicitly')
            plan = self.team._status(db,owner)
            if plan['configured'] and any(r['state'] in {'reserved','running'} for r in plan['tasks']):
                raise HarnessError('preserve running workers before starting/revising')
            if old:
                db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)',(owner,'crew-history:'+old['run_id'],canonical(old)))
                db.execute("UPDATE work SET state='abandoned' WHERE owner=? AND plan_id=? AND state NOT IN ('accepted','abandoned')",(owner,old['plan_id']))
            elif plan['configured'] and not plan['complete']:
                raise HarnessError('finish the previous dynamic team before enabling fixed seven')
            for i in range(1,7):
                db.execute('INSERT OR IGNORE INTO crew_members(owner,slot) VALUES(?,?)',(owner,i))
            self._round(db,owner,s,definition)
        return self.summary(owner)

    def _idle(self, owner):
        keys = [owner]
        with self.store.db() as db:
            keys += [r[0] for r in db.execute('SELECT worker_key FROM crew_members WHERE owner=? AND worker_key IS NOT NULL',(owner,))]
            pending = db.execute("SELECT 1 FROM dispatches WHERE owner=? AND state IN ('pending','running','unknown') LIMIT 1",(owner,)).fetchone()
        if pending:
            raise HarnessError('native work is active or unresolved; wait for the same sessions')
        for key in keys:
            if Jobs(self.store,key,self.package).active():
                raise HarnessError('check controller still active; preserve the running check')
            d = evidence_directory(self.store.directory,key)
            if (d/'evidence.sqlite3').is_file() and Evidence(d).status().get('active'):
                raise HarnessError('verification attempt still running')

    def acknowledge_unchanged(self, owner, decision):
        """Acknowledge a status/clarification turn without replacing active work.

        The root, not a keyword classifier, must determine that no requirement
        changed. A real goal/scope change still requires an explicit revision.
        """
        _,meta=self._root(owner)
        decision=text(decision,'why the current user message leaves the contract unchanged',4000)
        request_hash=self.store.get(owner,'request_hash')
        if not request_hash:raise HarnessError('no observed user request to acknowledge')
        with self.store.db(True) as db:
            current=_get(db,owner)
            if not current:raise HarnessError('register a crew contract first')
            if meta['model']!=current['model']:raise HarnessError('root model changed')
            previous=current['request_hash']
            if previous!=request_hash:
                db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)',
                    (owner,'crew-request:'+request_hash,canonical({'previous_hash':previous,'request_hash':request_hash,
                     'run_id':current['run_id'],'decision':decision,'requirements_changed':False,'at':time.time()})))
                current['request_hash']=request_hash
                _put(db,owner,current)
        return self.summary(owner)

    def _current(self, owner):
        s = self.status(owner)
        if not s['configured']:
            raise HarnessError('register the fixed-seven contract with crew-start first')
        root,meta = self._root(owner)
        if meta['model'] != s['model']:
            raise HarnessError('root model changed; keep the original crew model')
        if s['request_hash'] != self.store.get(owner,'request_hash',s['request_hash']):
            raise HarnessError('new user message requires crew-revise for changed requirements or crew-continue for an unchanged status/clarification request')
        return s,root

    def next(self, owner):
        s, root = self._current(owner)
        if s['phase']=='COMPLETE':
            problem=self.completion_problem(owner)
            return {'calls':[], 'complete':problem is None, 'current_completion_problem':problem}
        reserved=[]
        with self.store.db(True) as db:
            current=_get(db,owner)
            if current['plan_id']!=s['plan_id']:raise HarnessError('crew round changed; reload state')
            rows=db.execute('SELECT * FROM work WHERE owner=? AND plan_id=? ORDER BY id',(owner,s['plan_id'])).fetchall()
            done={r['id'] for r in rows if r['state']=='accepted'}
            # Returned implementation owns its paths until integrated and accepted.
            occupied=[strict_json(r['spec']) for r in rows if r['state'] in {'reserved','running','returned'}]
            for row in rows:
                task=strict_json(row['spec'])
                if row['state']!='pending' or not set(task['depends_on'])<=done:continue
                if task['kind']=='implement' and any(t['kind']=='implement' and any(overlaps(a,b) for a in task['paths'] for b in t['paths']) for t in occupied):continue
                ticket=uuid.uuid4().hex
                db.execute("UPDATE work SET state='reserved',ticket=?,launched=1 WHERE owner=? AND plan_id=? AND id=?",(ticket,owner,s['plan_id'],row['id']))
                reserved.append({**task,'ticket':ticket});occupied.append(task)
        # Resume any previously reserved-but-unprepared checkout too. The SQLite
        # writer lock serializes preparers; immutable Git records make a retry
        # after a crash safe. A missing/incomplete record is never fabricated.
        with self.store.db(True) as db:
            current=_get(db,owner)
            if current['plan_id']!=s['plan_id']:raise HarnessError('crew round changed')
            rows=db.execute("SELECT * FROM work WHERE owner=? AND plan_id=? AND state='reserved' AND workspace IS NULL",(owner,s['plan_id'])).fetchall()
            for row in rows:
                task=strict_json(row['spec'])
                if task['kind']!='implement':continue
                try:
                    info=Workspaces(self.store.directory/'worktrees').prepare(row['ticket'],root,task['paths'])
                    db.execute('UPDATE work SET workspace=? WHERE ticket=?',(info['tree'],row['ticket']))
                except (OSError,ValueError,__import__('subprocess').SubprocessError) as exc:
                    fallback={**task,'kind':'investigate'}
                    fallback['description']='ROOT-WRITER FALLBACK: provide an evidence-backed implementation proposal; do not edit. '+fallback['description']
                    db.execute('UPDATE work SET spec=? WHERE ticket=?',(canonical(fallback),row['ticket']))
                    db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)',(owner,'crew-fallback:'+row['ticket'],canonical(str(exc)[:1000])))
        s=self.status(owner);calls=[]
        members={m['slot']:m for m in s['members']}
        for row in s['tasks']:
            if row['state']!='reserved':continue
            with self.store.db() as db:
                exists=db.execute("SELECT 1 FROM dispatches WHERE ticket=? AND state IN ('pending','running','unknown')",(row['ticket'],)).fetchone()
            if exists:continue
            slot=int(row['id'][1:]);member=members[slot]
            task=row['spec']
            capsule={'goal':s['goal'],'requirements':s['requirements'],'phase':s['phase'],'round':s['round'],
                     'slot':slot,'job':task,'decision':s.get('decision'),'review_snapshot':s.get('review_snapshot',{}).get('sha256')}
            message='LUNASTRA_TICKET='+row['ticket']+'\n'+canonical(capsule)+'\nFirst run LOCAL_HELPER_COMMAND + crew-join '+row['ticket']+'. Do not act on a previous ticket. Use crew-report for source-linked findings, then finish your handback. No new model workers.'
            if len(message)>24000:raise HarnessError('task capsule exceeds 24000 characters; use concise obligations and source paths')
            name='send_input' if member['agent_id'] else 'spawn_agent'
            args={'target':member['agent_id'],'message':message,'interrupt':False} if member['agent_id'] else {'message':message,'fork_context':True}
            calls.append({'slot':slot,'ticket':row['ticket'],'tool':name,'arguments':args,
                          'native_schema_note':'Use the matching native tool actually exposed by the host; never model/effort/role overrides.',
                          'fallback':self.store.get(owner,'crew-fallback:'+row['ticket'])})
        return {'calls':calls,'required_total':7,'observed_children':s['observed_children'],
                'note':'Only native tool results prove dispatch. Reuse these six IDs; wait on unresolved calls, never replace them.'}

    def pre_dispatch(self, owner, call_id, payload, model, kind):
        s,_=self._current(owner)
        if s['phase']=='COMPLETE':raise HarnessError('crew is complete; register the next contract')
        if model!=s['model']:raise HarnessError('dispatch model differs from the original root Luna')
        if not isinstance(payload,dict):raise HarnessError('invalid native dispatch input')
        matches=TICKET.findall(payload.get('message','')) if isinstance(payload.get('message'),str) else []
        if len(matches)!=1:raise HarnessError('fixed crew dispatch requires exactly one current ticket')
        ticket=matches[0]
        if any(payload.get(n) is not None for n in ('model','reasoning_effort','service_tier','agent_type')):
            raise HarnessError('inherit selected Luna and effort; no model/effort/custom-role override')
        if payload.get('interrupt'):raise HarnessError('do not interrupt fixed-crew work')
        if kind=='spawn_agent' and not (payload.get('fork_context') is True or ('task_name' in payload and payload.get('fork_turns','all')=='all')):
            raise HarnessError('initial workers require a full inherited fork')
        with self.store.db(True) as db:
            current=_get(db,owner)
            if current['plan_id']!=s['plan_id']:raise HarnessError('crew round changed')
            row=db.execute('SELECT * FROM work WHERE owner=? AND plan_id=? AND ticket=?',(owner,s['plan_id'],ticket)).fetchone()
            if not row:raise HarnessError('ticket is not in the current fixed crew')
            member=db.execute('SELECT * FROM crew_members WHERE owner=? AND slot=?',(owner,int(row['id'][1:]))).fetchone()
            old=db.execute('SELECT * FROM crew_calls WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if old:
                if old['input_hash']!=json_hash(payload) or old['kind']!=kind or old['ticket']!=ticket:
                    raise HarnessError('native call ID was reused with different input')
                return ticket
            if row['state']!='reserved':raise HarnessError('ticket is already active or returned')
            if strict_json(row['spec'])['kind']=='implement' and not row['workspace']:raise HarnessError('prepare the assigned checkout with crew-next before dispatch')
            if db.execute("SELECT 1 FROM dispatches WHERE ticket=? AND state IN ('pending','running','unknown')",(ticket,)).fetchone():
                raise HarnessError('native dispatch unresolved; do not duplicate it')
            if member['agent_id']:
                if kind!='send_input' or payload.get('target')!=member['agent_id'] or 'id' in payload:
                    raise HarnessError('reuse the bound native ID with send_input; no replacement agent')
            elif kind!='spawn_agent':raise HarnessError('this slot has no observed native agent yet')
            if member['agent_id']:db.execute('UPDATE work SET agent_id=? WHERE ticket=?',(member['agent_id'],ticket))
            db.execute('INSERT INTO crew_calls VALUES(?,?,?,?,?)',(owner,call_id,ticket,kind,json_hash(payload)))
            db.execute('INSERT INTO dispatches VALUES(?,?,?,?)',(owner,call_id,ticket,'pending'))
        return ticket

    def post_dispatch(self, owner, call_id, response):
        result=unpack_response(response)
        with self.store.db(True) as db:
            call=db.execute('SELECT * FROM crew_calls WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if not call:return
            dispatch=db.execute('SELECT * FROM dispatches WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if dispatch['state'] not in {'pending','unknown'}:return
            row=db.execute('SELECT * FROM work WHERE ticket=?',(call['ticket'],)).fetchone()
            current=_get(db,owner)
            if not current or row['plan_id']!=current['plan_id']:raise HarnessError('late dispatch result belongs to a prior round')
            member=db.execute('SELECT * FROM crew_members WHERE owner=? AND slot=?',(owner,int(row['id'][1:]))).fetchone()
            if call['kind']=='spawn_agent':
                agent=result.get('agent_id')
                good=isinstance(agent,str) and 0<len(agent)<=4096
            else:
                agent=member['agent_id']
                # Codex send_input returns a submission ID. A prose response is not acknowledgement.
                good=bool(agent and isinstance(result.get('submission_id'),str) and result['submission_id'])
            error=isinstance(response,dict) and (response.get('isError') is True or response.get('is_error') is True)
            if not good or error:
                db.execute("UPDATE dispatches SET state='unknown' WHERE owner=? AND call_id=?",(owner,call_id))
                return
            if call['kind']=='spawn_agent':
                taken=db.execute('SELECT owner,slot FROM crew_members WHERE agent_id=?',(agent,)).fetchone()
                if taken and (taken['owner']!=owner or taken['slot']!=member['slot']):
                    raise HarnessError('one native agent cannot occupy two crew slots')
                if member['agent_id'] and member['agent_id']!=agent:raise HarnessError('native roster identity changed')
                db.execute('UPDATE crew_members SET agent_id=? WHERE owner=? AND slot=?',(agent,owner,member['slot']))
            db.execute("UPDATE work SET agent_id=?,state='running' WHERE ticket=?",(agent,call['ticket']))
            db.execute("UPDATE dispatches SET state='running' WHERE owner=? AND call_id=?",(owner,call_id))
        # A confirmed spawn can establish native-child identity even on a host
        # that does not emit SubagentStart. Actual worker model is rechecked on join.
        root,meta=self._root(owner)
        alias=self.store.get('__agent_alias__',agent)
        if not alias:
            key=json_hash([agent,agent,str(root.resolve()),meta['model']])
            self.store.put('__agent_alias__',agent,{'parent':agent,'key':key,'model':meta['model']})
            self.store.put(key,'meta',{'key':key,'role':'worker','workspace':str(root.resolve()),'model':meta['model'],
                           'session_id':agent,'agent_id':agent,'parent_session_id':meta['session_id'],
                           'created_at':time.time(),'context_emitted':False,'helper_used':False,'crew_enabled':True})

    def join(self, key, ticket, meta):
        row=self.team.lookup(ticket)
        if not row:raise HarnessError('unknown crew ticket')
        s=self.status(row['owner'])
        if not s['configured'] or row['plan_id']!=s['plan_id']:raise HarnessError('stale crew ticket')
        with self.store.db() as db:
            member=db.execute('SELECT * FROM crew_members WHERE owner=? AND slot=?',(row['owner'],int(row['id'][1:]))).fetchone()
        if not member or not member['agent_id'] or member['agent_id']!=meta.get('agent_id'):
            raise HarnessError('wait for the actual dispatch acknowledgement; retry this same ticket')
        with self.store.db() as db:
            ack=db.execute("SELECT 1 FROM dispatches WHERE owner=? AND ticket=? AND state='running'",(row['owner'],ticket)).fetchone()
        if not ack:raise HarnessError('current native acknowledgement is pending; retry the same ticket after it is observed')
        same_assignment=(meta.get('team_ticket')==ticket and meta.get('crew_round')==s['round'] and
                         meta.get('evidence_key')==json_hash([key,ticket]))
        if not same_assignment:
            if Jobs(self.store,key,self.package).active():raise HarnessError('previous worker check is still active')
            old=evidence_directory(self.store.directory,key,meta)
            if (old/'evidence.sqlite3').is_file() and Evidence(old).status().get('active'):
                raise HarnessError('previous evidence attempt is still running')
        result=self.team.join(key,ticket,meta)
        meta=self.store.get(key,'meta');meta.update(crew_enabled=True,crew_slot=member['slot'],
              crew_round=s['round'],evidence_key=json_hash([key,ticket]))
        self.store.put(key,'meta',meta)
        if not same_assignment:
            self.store.put(key,'source_baseline',observe(Path(result['workspace'])))
            self.store.put(key,'finish_generation',None)
        with self.store.db(True) as db:
            db.execute('UPDATE crew_members SET worker_key=? WHERE owner=? AND slot=?',(key,row['owner'],member['slot']))
        return {**result,'phase':s['phase'],'goal':s['goal'],'requirements':s['requirements'],
                'review_snapshot':{'sha256':s.get('review_snapshot',{}).get('sha256'),'paths':s.get('review_paths',[])},'report_schema':{
                    'verdict':'clear | issues | blocked','summary':'Concise evidence-based conclusion',
                    'findings':['Specific issue, or explicit no issue within the inspected scope'],
                    'references':[{'path':'actual relative source/output path'}], 'covers':[0]},
                'independent': member['slot'] in (5,6), 'reuse_same_session':True}

    def report(self, key, data):
        meta=self.store.get(key,'meta',{});ticket=meta.get('team_ticket')
        row=self.team.lookup(ticket)
        if not row or row['state']!='running' or row['agent_id']!=meta.get('agent_id'):
            raise HarnessError('report requires your current joined running assignment')
        s,root=self._current(row['owner'])
        if row['plan_id']!=s['plan_id']:raise HarnessError('old assignment report')
        if not isinstance(data,dict) or set(data)!={'verdict','summary','findings','references','covers'}:
            raise HarnessError('invalid crew-report fields')
        if data['verdict'] not in {'clear','issues','blocked'}:raise HarnessError('invalid report verdict')
        summary=text(data['summary'],'report summary',4000)
        findings=data['findings']
        if not isinstance(findings,list) or not 1<=len(findings)<=30:raise HarnessError('bounded explicit findings required')
        findings=[text(v,'finding',2000) for v in findings]
        covers=data['covers']
        if not isinstance(covers,list) or not covers or any(type(i) is not int or not 0<=i<len(s['requirements']) for i in covers) or len(set(covers))!=len(covers):
            raise HarnessError('report must identify valid requirement indices')
        references=data['references'];checked=[]
        if not isinstance(references,list) or not 1<=len(references)<=100:raise HarnessError('source references required')
        ws=Path(meta['assigned_workspace'])
        for ref in references:
            if not isinstance(ref,dict):raise HarnessError('invalid source reference')
            if set(ref)=={'requirement'}:
                i=ref['requirement']
                if type(i) is not int or not 0<=i<len(s['requirements']):raise HarnessError('invalid requirement reference')
                checked.append({'requirement':i,'sha256':json_hash(s['requirements'][i])})
            elif set(ref)=={'path'}:
                p=inside(ws,ref['path'])
                if not p.is_file():raise HarnessError('source reference must be an existing regular file')
                scopes=row and strict_json(row['spec'])['paths']
                if not any(ref['path']==n or ref['path'].startswith(n.rstrip('/')+'/') for n in scopes):
                    raise HarnessError('reference is outside the assigned source scope')
                checked.append({'path':ref['path'],'sha256':file_hash(p)})
            else:raise HarnessError('reference accepts path or requirement index only')
        if s['phase']=='REVIEW':
            if fingerprint(root,s['review_paths'])['sha256']!=s['review_snapshot']['sha256']:
                raise HarnessError('final artifact changed; start a fresh review round')
            if not any('path' in r for r in checked):raise HarnessError('final review needs actual artifact references, not just requirements')
            if member_slot(meta) in (5,6) and set(covers)!=set(range(len(s['requirements']))):
                raise HarnessError('independent acceptance reviewers must cover all locked requirements')
        body={'ticket':ticket,'worker_key':key,'run_id':s['run_id'],'round':s['round'],'phase':s['phase'],
              'verdict':data['verdict'],'summary':summary,'findings':findings,'references':checked,'covers':covers,
              'snapshot':s.get('review_snapshot',{}).get('sha256'),'model_review_is_not_test_execution':True}
        if len(canonical(body))>12000:raise HarnessError('report exceeds 12000 characters; retain full evidence in files and reference it')
        with self.store.db(True) as db:
            cur=_get(db,row['owner'])
            if cur['plan_id']!=s['plan_id']:raise HarnessError('crew round changed')
            db.execute('INSERT INTO crew_reports VALUES(?,?,?,?) ON CONFLICT(ticket) DO UPDATE SET body=excluded.body,at=excluded.at',
                       (ticket,key,canonical(body),time.time()))
        return {'recorded':True,'native_handback_still_required':True,'phase':s['phase']}

    def _returned(self, owner, s, *, clear=False, repairing=False):
        self._idle(owner)
        if s['observed_children']!=6 or len({m['agent_id'] for m in s['members']})!=6:
            raise HarnessError('all six distinct native children are required; no smaller-crew success')
        if len(s['tasks'])!=6:raise HarnessError('invalid six-slot round')
        for row in s['tasks']:
            report=s['reports'].get(row['ticket']);hb=row['result'] or {}
            if repairing:
                if row['state'] not in {'returned','accepted','failed'}:raise HarnessError('settle all six native tasks before targeted repair')
                continue
            if row['state'] not in {'returned','accepted'} or hb.get('status') not in {'ANALYSIS','TESTED'}:
                raise HarnessError('all six current checked handbacks are required')
            if not report or report['round']!=s['round'] or report['run_id']!=s['run_id']:
                raise HarnessError('missing current crew-report')
            member=next(m for m in s['members'] if m['slot']==int(row['id'][1:]))
            meta=self.store.get(member['worker_key'],'meta',{})
            if (hb.get('worker_key')!=member['worker_key'] or report.get('worker_key')!=member['worker_key'] or
                    row['agent_id']!=member['agent_id'] or meta.get('team_ticket')!=row['ticket'] or
                    meta.get('model')!=s['model'] or meta.get('crew_round')!=s['round']):
                raise HarnessError('worker/report/round identity mismatch')
            if s['phase']=='PLAN':
                ws=Path(meta['assigned_workspace'])
                for ref in report['references']:
                    if 'path' in ref and file_hash(inside(ws,ref['path']))!=ref['sha256']:
                        raise HarnessError('planning source changed; revise the contract before execution')

            if report['verdict']=='blocked' or (clear and report['verdict']!='clear'):
                raise HarnessError('unresolved reviewer findings; target a repair before completion')
            if row['spec']['kind']=='implement' and not (hb.get('status')=='TESTED' and hb.get('integrated')):
                raise HarnessError('checked implementation integration is still required')

    def _accept_round(self, db, owner, s, decision, repairing=False):
        for row in s['tasks']:
            hb={**(row['result'] or {}),'leader_review':decision}
            state='abandoned' if repairing and (hb.get('status') not in {'ANALYSIS','TESTED'} or s['reports'].get(row['ticket'],{}).get('verdict')!='clear' or (row['spec']['kind']=='implement' and not hb.get('integrated'))) else 'accepted'
            db.execute('UPDATE work SET state=?,result=? WHERE ticket=?',(state,canonical(hb),row['ticket']))
        db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)',(owner,f"crew-round:{s['run_id']}:{s['round']}",canonical(s)))

    def execute(self, owner, data, *, repair=False):
        s,root=self._current(owner)
        if s['phase'] not in ({'EXECUTE','REVIEW'} if repair else {'PLAN'}):raise HarnessError('wrong phase for execution transition')
        if not isinstance(data,dict) or set(data)!={'decision','tasks'}:raise HarnessError('execution needs decision and six bounded tasks')
        decision=text(data['decision'],'evidence-based root decision',8000)
        definition=self._definition(owner,root,s['goal'],data['tasks'])
        tasks=definition['tasks']
        if {t['id'] for t in tasks}!={f's{i}' for i in range(1,7)}:raise HarnessError('execution requires exactly s1..s6, reused across rounds')
        for t in tasks:
            if t['id'] in {'s5','s6'} and t['kind']=='implement':raise HarnessError('slots 5 and 6 remain independent read-only reviewers')
            if t['kind']=='implement' and any(not any(p==o or p.startswith(o.rstrip('/')+'/') for o in s['output_paths']) for p in t['paths']):
                raise HarnessError('implementation exceeds the locked output scope')
        self._returned(owner,s,repairing=repair)
        with self.store.db(True) as db:
            if _get(db,owner)['plan_id']!=s['plan_id']:raise HarnessError('crew round changed')
            self._accept_round(db,owner,s,decision,repairing=repair)
            clean=_get(db,owner);clean.update(phase='EXECUTE',round=s['round']+1,decision=decision)
            clean['ever_wrote']=sorted(set(clean['ever_wrote'])|{int(t['id'][1:]) for t in tasks if t['kind']=='implement'})
            self._round(db,owner,clean,definition)
        return self.summary(owner)

    def _root_evidence(self, owner, s, require_finish=False):
        if Jobs(self.store,owner,self.package).active():raise HarnessError('root check controller is active')
        ev=Evidence(evidence_directory(self.store.directory,owner));status=ev.status()
        with ev._db() as db:task=ev._get(db,'task')
        if not task or task['requirements']!=s['requirements']:
            raise HarnessError('root checks must cover the exact locked requirement list')
        if not status.get('passed'):raise HarnessError('current root acceptance checks are required')
        dependencies=sorted(set(p for c in task['checks'] for p in c['dependencies']+c.get('expected_absent',[])))
        for output in s['output_paths']:
            if not any(output==d or output.startswith(d.rstrip('/')+'/') for d in dependencies):
                raise HarnessError('declared output lacks root verification coverage: '+output)
        if require_finish:
            finish=status.get('finish') or {}
            if finish.get('kind')!='tested' or not finish.get('valid') or self.store.get(owner,'finish_generation')!=self.store.get(owner,'generation'):
                raise HarnessError('finish the current root checks as tested before crew-complete')
        return status,dependencies

    def review(self, owner, decision):
        s,root=self._current(owner)
        if s['phase'] not in {'EXECUTE','REVIEW'}:raise HarnessError('review follows execution')
        decision=text(decision,'review decision',8000)
        self._returned(owner,s)
        evidence,deps=self._root_evidence(owner,s)
        paths=sorted(set(s['evidence_paths']+s['output_paths']+deps))
        snap=fingerprint(root,paths)
        definition=self._definition(owner,root,s['goal'],self._tasks(REVIEW_LENSES,paths))
        with self.store.db(True) as db:
            if _get(db,owner)['plan_id']!=s['plan_id']:raise HarnessError('crew round changed')
            self._accept_round(db,owner,s,decision)
            clean=_get(db,owner);clean.update(phase='REVIEW',round=s['round']+1,decision=decision,
                 review_paths=paths,review_snapshot=snap,review_task_hash=evidence.get('task_hash'))
            self._round(db,owner,clean,definition)
        return self.summary(owner)

    def complete(self, owner, decision):
        s,root=self._current(owner)
        if s['phase']!='REVIEW':raise HarnessError('six independent final reports are required before completion')
        decision=text(decision,'final evidence-based synthesis',8000)
        self._returned(owner,s,clear=True)
        evidence,_=self._root_evidence(owner,s,require_finish=True)
        if evidence.get('task_hash')!=s['review_task_hash']:raise HarnessError('check definitions changed after review')
        snap=fingerprint(root,s['review_paths'])
        if snap['sha256']!=s['review_snapshot']['sha256']:raise HarnessError('reviewed artifact is stale')
        with self.store.db(True) as db:
            if _get(db,owner)['plan_id']!=s['plan_id']:raise HarnessError('crew round changed')
            self._accept_round(db,owner,s,decision)
            clean=_get(db,owner);clean.update(phase='COMPLETE',decision=decision,
                proof={'artifact_sha256':snap['sha256'],'task_hash':evidence.get('task_hash'),
                       'native_children':[m['agent_id'] for m in s['members']], 'at':time.time(),
                       'actual_model_parity':'NOT_MEASURED'})
            _put(db,owner,clean)
        return self.summary(owner)

    def completion_problem(self, owner):
        try:
            s,root=self._current(owner)
            if s['phase']!='COMPLETE':return 'fixed-seven phase '+s['phase']+' is not complete'
            evidence,_=self._root_evidence(owner,s,require_finish=True)
            if evidence.get('task_hash')!=s['proof']['task_hash']:return 'acceptance definitions changed after certification'
            if fingerprint(root,s['review_paths'])['sha256']!=s['proof']['artifact_sha256']:return 'final artifact changed after certification'
            self._idle(owner)
            return None
        except (ValueError,OSError,KeyError,TypeError) as exc:
            return str(exc)

    def can_write(self, owner):
        s,_=self._current(owner)
        if s['phase']!='EXECUTE':raise HarnessError('work is read-only until the six-member plan is reviewed, and during final review')
        if s['observed_children']!=6:raise HarnessError('fixed seven requires six observed native child identities')
        return s['output_paths']


def member_slot(meta):
    slot=meta.get('crew_slot')
    if type(slot) is not int or not 1<=slot<=6:raise HarnessError('invalid crew slot')
    return slot
