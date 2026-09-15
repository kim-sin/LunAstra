"""Fixed-crew continuation and round-bound native observations.

This module returns instructions for the existing Codex tools. It does not
call a model, launch a controller, read transcripts, or change host settings.
A model timeout is not a completed report. Recovery reuses an observed,
terminated native member, the same ticket and the same evidence directory.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from .crew import Crew, _get
from .store import evidence_directory
from .team import unpack_response
from .transport import helper_command
from .util import HarnessError, canonical, json_hash, strict_json

SCHEMA = '''
CREATE TABLE IF NOT EXISTS crew_waits (
 owner TEXT, call_id TEXT, plan_id TEXT, input_hash TEXT, snapshot TEXT,
 started REAL, finished REAL, result_hash TEXT, valid INTEGER DEFAULT 0,
 PRIMARY KEY(owner,call_id));
'''
# Limits concern failed correction attempts, not total model/work duration.
MAX_RECOVERIES = 2
MAX_IDLE_CORRECTIONS = 3


def _epoch(db, ticket):
    return [r[0] for r in db.execute('SELECT call_id FROM dispatches WHERE ticket=? ORDER BY rowid', (ticket,))]


def _kv(db, owner, name, value):
    db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)', (owner, name, canonical(value)))


def _value(db, owner, name, default=None):
    row=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(owner,name)).fetchone()
    return strict_json(row[0]) if row else default


class Flow:
    def __init__(self, store, package):
        self.store=store; self.package=Path(package); self.crew=Crew(store,package)
        with store.db() as db: db.executescript(SCHEMA)

    def prefix(self, key):
        return [sys.executable,str(self.package/'luna.py'),'--state',str(self.store.directory),'--session',key]

    def pre_wait(self, owner, call_id, payload):
        s,_=self.crew._current(owner)
        targets=payload.get('targets') if isinstance(payload,dict) else None
        if (not isinstance(targets,list) or not targets or len(targets)>6 or
                any(not isinstance(x,str) or not x for x in targets) or len(set(targets))!=len(targets)):
            raise HarnessError('wait_agent requires targets: a nonempty list of bound native IDs')
        if set(payload)-{'targets','timeout_ms'}: raise HarnessError('unrecognized native wait arguments')
        if 'timeout_ms' in payload and (type(payload['timeout_ms']) is not int or payload['timeout_ms']<=0):
            raise HarnessError('wait timeout must be a positive integer')
        with self.store.db(True) as db:
            if _get(db,owner)['plan_id']!=s['plan_id']: raise HarnessError('crew round changed')
            old=db.execute('SELECT * FROM crew_waits WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if old:
                if old['input_hash']!=json_hash(payload): raise HarnessError('wait call ID reused with different input')
                return
            snapshot={}
            for agent in targets:
                row=db.execute('SELECT * FROM work WHERE owner=? AND plan_id=? AND agent_id=?',
                               (owner,s['plan_id'],agent)).fetchone()
                if not row or not row['ticket']: raise HarnessError('wait only on the current six bound members')
                snapshot[agent]={'ticket':row['ticket'],'epoch':_epoch(db,row['ticket'])}
            db.execute('INSERT INTO crew_waits(owner,call_id,plan_id,input_hash,snapshot,started) VALUES(?,?,?,?,?,?)',
                       (owner,call_id,s['plan_id'],json_hash(payload),canonical(snapshot),time.time()))

    def post_wait(self, owner, call_id, response):
        result=unpack_response(response); states=result.get('status')
        error=isinstance(response,dict) and (response.get('isError') is True or response.get('is_error') is True)
        with self.store.db(True) as db:
            wait=db.execute('SELECT * FROM crew_waits WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if not wait: return  # no pre-observation: never bind a late result by ID alone
            digest=json_hash(response)
            if wait['finished'] is not None:
                if wait['result_hash']!=digest: raise HarnessError('native wait result changed for the same call')
                return
            current=_get(db,owner); snapshot=strict_json(wait['snapshot'])
            active=bool(current and current['plan_id']==wait['plan_id'])
            valid=active and not error and isinstance(states,dict)
            if valid and not states: valid=result.get('timed_out') is True
            matched=0
            if valid:
                for target,status in states.items():
                    agent=target
                    # Codex V1 may key statuses by its internal agent path, not
                    # UUID. Only a singleton native request/result is unambiguous.
                    if agent not in snapshot and len(snapshot)==len(states)==1 and isinstance(agent,str) and agent.startswith('/'):
                        agent=next(iter(snapshot))
                    saved=snapshot.get(agent)
                    if not saved or _epoch(db,saved['ticket'])!=saved['epoch']: continue
                    row=db.execute('SELECT * FROM work WHERE ticket=?',(saved['ticket'],)).fetchone()
                    if not row or row['plan_id']!=wait['plan_id'] or row['agent_id']!=agent: continue
                    state=None
                    if isinstance(status,dict) and set(status)=={'completed'} and (status['completed'] is None or isinstance(status['completed'],str)):
                        state='completed'
                    elif isinstance(status,dict) and set(status)=={'errored'} and isinstance(status['errored'],str): state='errored'
                    elif isinstance(status,str) and status in {'interrupted','shutdown','not_found','running','pending_init'}: state=status
                    if state is None: continue
                    matched+=1
                    observation={'state':state,'agent_id':agent,'ticket':saved['ticket'],'epoch':saved['epoch'],
                                 'plan_id':wait['plan_id'],'call_id':call_id,'at':time.time()}
                    # Store status/identity only, not potentially sensitive model text.
                    _kv(db,owner,'flow-native:'+saved['ticket'],observation)
                    terminal_error=state in {'errored','interrupted','shutdown','not_found'}
                    if ((state=='completed' and row['state'] in {'running','reserved'}) or
                            (terminal_error and row['state'] in {'running','reserved','returned','accepted'})):
                        terminal='returned' if state=='completed' else 'failed'
                        handback={'status':'UNVERIFIED','native_status':state,
                                  'reason':'Native terminal state observed; a current checked handback is still required',
                                  'previous_handback':strict_json(row['result']) if row['result'] else None}
                        db.execute('UPDATE work SET state=?,result=? WHERE ticket=?',(terminal,canonical(handback),saved['ticket']))
                        db.execute('UPDATE dispatches SET state=? WHERE ticket=?',(terminal,saved['ticket']))
            valid=bool(valid and (not states or matched==len(states)))
            db.execute('UPDATE crew_waits SET finished=?,result_hash=?,valid=? WHERE owner=? AND call_id=?',
                       (time.time(),digest,int(valid),owner,call_id))

    def _native(self, owner, row):
        observation=self.store.get(owner,'flow-native:'+str(row['ticket']))
        if not observation: return None
        with self.store.db() as db: epoch=_epoch(db,row['ticket'])
        if observation.get('epoch')!=epoch or observation.get('plan_id')!=row['plan_id']: return None
        return observation

    def drive(self, owner):
        """Read state, return one actionable next step; never reserve or run it."""
        self.crew._root(owner)
        s=self.crew.status(owner)
        if not s['configured']: return {'action':'START','helper':'crew-start','complete':False}
        base={'phase':s['phase'],'round':s['round'],'reports_received':len(s['reports']),
              'observed_children':s['observed_children'],'complete':False}
        if s['request_hash']!=self.store.get(owner,'request_hash',s['request_hash']):
            return {**base,'action':'ACKNOWLEDGE_REQUEST','helper':'crew-continue for unchanged scope; crew-revise only for a real changed requirement'}
        if s['phase']=='COMPLETE':
            problem=self.crew.completion_problem(owner)
            return {**base,'action':'BLOCKED' if problem else 'COMPLETE','complete':not problem,'reason':problem}
        with self.store.db() as db:
            unsettled={r['ticket']:r['state'] for r in db.execute(
                "SELECT d.ticket,d.state FROM dispatches d JOIN work w ON d.ticket=w.ticket WHERE w.owner=? AND w.plan_id=? AND d.state IN ('pending','unknown')",
                (owner,s['plan_id']))}
        for row in s['tasks']:
            if row['ticket'] in unsettled:
                return {**base,'action':'BLOCKED','reason':'Native dispatch acknowledgement unresolved; retain this call and all six sessions, never spawn replacements',
                        'slot':row['id'],'dispatch_state':unsettled[row['ticket']]}
        if any(r['state']=='reserved' for r in s['tasks']): return {**base,'action':'DISPATCH','helper':'crew-next'}
        done={r['id'] for r in s['tasks'] if r['state']=='accepted'}
        for row in s['tasks']:
            native=self._native(owner,row)
            if native and native['state'] in {'errored','interrupted','shutdown','not_found'}:
                return {**base,'action':'BLOCKED','slot':row['id'],'native_state':native['state'],'reason':'Observed native failure; preserve the same sessions and the actual failure, not a fabricated report'}
            if row['state'] in {'returned','accepted'} and s['reports'].get(row['ticket'],{}).get('verdict')=='blocked':
                return {**base,'action':'BLOCKED','slot':row['id'],'reason':'Inspect the concrete source-linked blocker in crew-report-read '+row['id'][1:]}
        # If any work is still running, wait first. This also avoids executing
        # dependency plans before readers and writers finish their current turn.
        for row in s['tasks']:
            report=s['reports'].get(row['ticket']); handback=row['result'] or {}
            native=self._native(owner,row)
            needs_handback=not report or handback.get('status') not in {'ANALYSIS','TESTED'}
            if (row['state']=='running' or (row['state']=='returned' and needs_handback and not native)) and row['agent_id']:
                return {**base,'action':'WAIT','slot':row['id'],
                        'native_call':{'tool':'wait_agent','arguments':{'targets':[row['agent_id']],'timeout_ms':60000}},
                        'after':'Run crew-drive again. A timeout is not failure; keep waiting on these same six IDs. Do not return to the user merely because they are running.'}
        for row in s['tasks']:
            report=s['reports'].get(row['ticket']); handback=row['result'] or {}; native=self._native(owner,row)
            if row['state'] in {'returned','failed'} and (not report or handback.get('status') not in {'ANALYSIS','TESTED'}):
                if handback.get('status') in {'PARTIAL','BLOCKED'} or (report and report['verdict']=='blocked'):
                    return {**base,'action':'BLOCKED','slot':row['id'],'reason':'Worker returned an explicit limited handback; inspect its source-linked report, do not certify completion'}
                count=self.store.get(owner,'flow-recovery-count:'+row['ticket'],0)
                if native and native['state']=='completed' and count<MAX_RECOVERIES:
                    return {**base,'action':'RECOVER','slot':row['id'],'helper':'crew-recover '+row['id'][1:],
                            'reason':'Same completed native member must submit its missing report/checked handback; no replacement and no new ticket'}
                return {**base,'action':'BLOCKED','slot':row['id'],'reason':'Native member failed or report recovery exhausted; preserve exact status and existing work',
                        'native_state':native['state'] if native else 'NOT_OBSERVED','recoveries':count}
        for row in s['tasks']:
            if row['state']=='returned' and row['spec']['kind']=='implement' and not (row['result'] or {}).get('integrated'):
                return {**base,'action':'INTEGRATE','helper':'team-integrate '+row['id'],'after':'Inspect the patch and team-accept; do not reset user edits'}
        if any(r['state']=='pending' for r in s['tasks']):
            if any(r['state']=='pending' and set(r['spec']['depends_on'])<=done for r in s['tasks']):
                return {**base,'action':'DISPATCH','helper':'crew-next'}
            returned=next((r for r in s['tasks'] if r['state']=='returned'),None)
            if returned: return {**base,'action':'ACCEPT','helper':'team-accept '+returned['id'],'after':'Review the actual result before acceptance, then crew-next'}
            return {**base,'action':'BLOCKED','reason':'No runnable dependency; inspect current work without replacing the crew'}
        return {**base,'action':'ADVANCE','helper':{'PLAN':'crew-execute','EXECUTE':'finish current root implementation and checks, then crew-review',
                   'REVIEW':'crew-repair if issues remain; otherwise finish current evidence and crew-complete'}[s['phase']],
                'after':'Read all six actual crew-report-read results before deciding; next-phase helpers revalidate them'}

    def prepare_recovery(self, owner, slot):
        if type(slot) is not int or not 1<=slot<=6: raise HarnessError('recovery slot must be 1..6')
        s,_=self.crew._current(owner); row=next(r for r in s['tasks'] if r['id']==f's{slot}')
        native=self._native(owner,row)
        if not native or native['state']!='completed' or row['state']!='returned':
            raise HarnessError('recover only a native-completed member; wait for running/unknown members first')
        if (row['result'] or {}).get('status') in {'PARTIAL','BLOCKED'}:
            raise HarnessError('inspect the genuine blocked result instead of retrying it blindly')
        if s['reports'].get(row['ticket'],{}).get('verdict')=='blocked': raise HarnessError('inspect the blocked report')
        if s['reports'].get(row['ticket']) and (row['result'] or {}).get('status') in {'ANALYSIS','TESTED'}:
            raise HarnessError('this member already has its checked report; do not repeat it')
        count=self.store.get(owner,'flow-recovery-count:'+row['ticket'],0)
        if count>=MAX_RECOVERIES: raise HarnessError('same-ticket report recovery exhausted; preserve the failure')
        message=('LUNASTRA_TICKET='+row['ticket']+'\nLUNASTRA_RECOVER='+str(count+1)+
                 '\nYour same assigned turn ended without a valid crew-report/handback. Do not repeat successful work. '
                 'Use your own latest LOCAL_HELPER_COMMAND (not the inherited parent command) to crew-join '+row['ticket']+
                 '. Read your current assignment and source, submit --input-json <report JSON> crew-report, then return '
                 'LUNASTRA_STATUS=ANALYSIS for read-only evidence or finish tested for a writer. '
                 'No crew-state, no other agents, no replacement, and no invented reports. '
                 'If genuinely unable, report the exact blocker with actual references.')
        payload={'target':row['agent_id'],'message':message,'interrupt':False}
        self.store.put(owner,'flow-recovery:'+row['ticket'],{'count':count+1,'payload_hash':json_hash(payload),'plan_id':s['plan_id'],
                      'native_call_id':native['call_id'],'epoch':native['epoch']})
        return {'tool':'send_input','arguments':payload,'slot':slot,'ticket':row['ticket'],'reuse_same_session':True}

    @staticmethod
    def authorize_recovery(db, owner, s, row, payload, kind):
        """Inside Crew's dispatch transaction, so failure never half-reopens work."""
        request=_value(db,owner,'flow-recovery:'+row['ticket'])
        native=_value(db,owner,'flow-native:'+row['ticket'])
        count=_value(db,owner,'flow-recovery-count:'+row['ticket'],0)
        if (kind!='send_input' or row['state']!='returned' or not request or not native or
                native['state']!='completed' or request['plan_id']!=s['plan_id'] or
                request['epoch']!=_epoch(db,row['ticket']) or request['native_call_id']!=native['call_id'] or
                request['payload_hash']!=json_hash(payload) or request['count']!=count+1 or count>=MAX_RECOVERIES):
            raise HarnessError('same-ticket recovery requires a fresh crew-recover instruction and an observed native completion')
        handback=strict_json(row['result'] or '{}')
        report=db.execute('SELECT body FROM crew_reports WHERE ticket=?',(row['ticket'],)).fetchone()
        report=strict_json(report[0]) if report else None
        if handback.get('status') in {'PARTIAL','BLOCKED'} or (report and (report.get('verdict')=='blocked' or handback.get('status') in {'ANALYSIS','TESTED'})):
            raise HarnessError('member result changed; do not repeat a checked or explicitly blocked handback')
        _kv(db,owner,'flow-handback-history:'+row['ticket']+':'+str(count),handback)
        _kv(db,owner,'flow-recovery-count:'+row['ticket'],count+1)
        db.execute("UPDATE work SET state='reserved',result=NULL WHERE ticket=?",(row['ticket'],))

    def progress(self, key, meta):
        if meta.get('role')=='root':
            s=self.crew.status(key)
            if not s['configured']: return json_hash([False,self.store.get(key,'request_hash')])
            rows=[]
            for row in s['tasks']:
                member=next((m for m in s['members'] if m['slot']==int(row['id'][1:])),{})
                rows.append([row['id'],row['state'],row['agent_id'],member.get('worker_key'),
                             json_hash(row['result']),json_hash(s['reports'].get(row['ticket']))])
            value=[s['run_id'],s['round'],s['phase'],s['request_hash'],self.store.get(key,'request_hash'),rows]
        else:
            ticket=meta.get('team_ticket')
            with self.store.db() as db:
                report=db.execute('SELECT body FROM crew_reports WHERE ticket=?',(ticket,)).fetchone()
            value=[ticket,meta.get('crew_round'),report[0] if report else None]
        # Test/evidence progress can legitimately require a further correction.
        path=evidence_directory(self.store.directory,key,meta)/'evidence.sqlite3'
        if path.is_file():
            from .evidence import Evidence
            ev=Evidence(path.parent).status()
            value.append([ev.get('passed'),ev.get('active'),ev.get('task_hash'),ev.get('finish'),ev.get('checks')])
        return json_hash(value)

    def correction(self, key, meta, problem):
        """Progress-aware Stop feedback; stop_hook_active is not a failure flag."""
        now=time.time(); signature=self.progress(key,meta); old=self.store.get(key,'flow-stop',{})
        if old.get('signature')!=signature:
            record={'signature':signature,'since':now,'idle':0,'last_stop':0.0}
        else: record=dict(old)
        if meta.get('role')=='root':
            action=self.drive(key)
            with self.store.db() as db:
                waited=db.execute('SELECT 1 FROM crew_waits WHERE owner=? AND finished>? AND valid=1 AND finished-started>=1 LIMIT 1',
                                  (key,record.get('last_stop',0.0))).fetchone()
            if not waited: record['idle']=record.get('idle',0)+1
            else: record['idle']=0
            allowed=record['idle']<=MAX_IDLE_CORRECTIONS
            text=('LUNASTRA_CONTINUE: '+problem+'. Next step: '+canonical(action)+
                  '\nUse '+helper_command(self.prefix(key)+['crew-drive'])+' to refresh the next action. '
                  'Perform the indicated native wait/send and continue the same six sessions through execution and review. '
                  'Do not finalize because workers are merely running; timeout means wait again. Do not create another crew.')
        else:
            # A join/report is progress. Repeated identical worker failure is
            # bounded and the parent can recover the same native member later.
            record['idle']=record.get('idle',0)+1
            allowed=record['idle']<=1
            ticket=meta.get('team_ticket')
            if not ticket:
                with self.store.db() as db:
                    row=db.execute("SELECT w.ticket FROM work w JOIN plans p ON w.owner=p.owner AND w.plan_id=p.plan_id WHERE w.agent_id=? AND w.state IN ('reserved','running') ORDER BY w.rowid DESC LIMIT 1",(meta.get('agent_id'),)).fetchone()
                if row: ticket=row[0]
            own=helper_command(self.prefix(key))
            text=('LUNASTRA_CONTINUE: '+problem+'. You are the worker, not the parent. Your own LOCAL_HELPER_COMMAND='+own+
                  '. First '+('crew-join '+ticket if ticket else 'recover your assigned LUNASTRA_TICKET from the native task message')+
                  '. Inspect the assigned source with this helper read/context. Submit '+own+
                  ' --input-json <JSON with verdict,summary,findings,references,covers> crew-report. '
                  'Use real source references; do not invent findings. For a read-only assignment finish with LUNASTRA_STATUS=ANALYSIS; '
                  'for an implementation finish current tested evidence. Do not call root coordination commands or launch agents.')
        record['last_stop']=now; self.store.put(key,'flow-stop',record)
        return {'decision':'block','reason':text} if allowed else None
