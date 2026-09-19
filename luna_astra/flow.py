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
from .native import is_v2, target, dispatch, capsule_ready
from .native_flow import NativeFlow, wait_call

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
        store.ensure_schema('flow', SCHEMA)

    def prefix(self, key):
        return [sys.executable,str(self.package/'luna.py'),'--state',str(self.store.directory),'--session',key]

    def pre_wait(self, owner, call_id, payload):
        s,_=self.crew._current(owner)
        if is_v2(s):return NativeFlow(self.store,self.crew).pre(owner,call_id,'wait_agent',payload)
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
        state=self.crew.status(owner)
        if state.get('configured') and is_v2(state):return NativeFlow(self.store,self.crew).post(owner,call_id,'wait_agent',response)
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
            if active and isinstance(states,dict) and states and len(snapshot)>1 and any(
                    isinstance(t,str) and t.startswith('/') and t not in snapshot for t in states):
                _kv(db,owner,'flow-singleton-wait',True)
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
        due=self.store.get(owner,'native-list-due')
        if is_v2(s) and due and due.get('plan_id')==s['plan_id']:
            return {**base,'action':'OBSERVE_NATIVE','native_call':{'tool':'list_agents','arguments':{}},
                    'reason':'V2 mailbox wake is not completion; observe canonical task statuses'}
        if not capsule_ready(self.store,owner,s):
            first=next((r for r in s['tasks'] if target(self.store,owner,int(r['id'][1:]),r['agent_id'])),None)
            if first:
                native=self._native(owner,first)
                count=self.store.get(owner,'flow-recovery-count:'+str(first['ticket']),0)
                if native and native['state']=='completed' and first['state']=='returned' and count<MAX_RECOVERIES:
                    return {**base,'action':'RECOVER','slot':first['id'],'helper':'crew-recover '+first['id'][1:],
                            'reason':'First capsule member must join with an actual Luna hook before the remaining five are dispatched'}
                if native and native['state'] in {'completed','errored','interrupted','shutdown','not_found'}:
                    return {**base,'action':'BLOCKED','slot':first['id'],'reason':'Capsule model/identity handshake failed; no extra models or replacement crew',
                            'native_state':native['state']}
                return {**base,'action':'WAIT','slot':first['id'],'slots':[first['id']],
                        'native_call':wait_call(s,[first['agent_id']]),
                        'reason':'Await the first actual Luna hook/crew-join before dispatching the other five; effort remains unmeasured'}
        from .native import capacity_problem
        capacity=capacity_problem(s)
        if capacity:return {**base,'action':'BLOCKED','kind':'HOST_CAPABILITY','reason':capacity['message'],'capacity':capacity}
        if any(r['state']=='reserved' for r in s['tasks']):return {**base,'action':'DISPATCH','helper':'crew-next'}
        done={r['id'] for r in s['tasks'] if r['state']=='accepted'}
        for row in s['tasks']:
            native=self._native(owner,row)
            if native and native['state'] in {'errored','interrupted','shutdown','not_found'}:
                return {**base,'action':'BLOCKED','slot':row['id'],'native_state':native['state'],'reason':'Observed native failure; preserve the same sessions and the actual failure, not a fabricated report'}
            report=s['reports'].get(row['ticket'],{})
            if row['state'] in {'returned','accepted'} and report.get('verdict')=='blocked':
                from .blockers import freshness
                observed=freshness(self.store,row['ticket'],report,s['requirements'])
                if observed['state']=='STALE' and row['state']=='returned' and s['phase']!='REVIEW':
                    if not native or native['state']!='completed':
                        return {**base,'action':'WAIT','slot':row['id'],
                                'native_call':wait_call(s,[row['agent_id']]),
                                'reason':'Changed blocker needs actual native completion before same-member recheck'}
                    return {**base,'action':'REASSESS','slot':row['id'],'helper':'crew-recover '+row['id'][1:],
                            'reason':'Blocked report is stale; recheck this member only, preserving all other work','freshness':observed}
                # A blocked dependency does not prevent already-dispatched,
                # independent work from returning. Final promotion stays gated.
                if any(r['state']=='running' for r in s['tasks']):continue
                return {**base,'action':'BLOCKED','slot':row['id'],'kind':report.get('blocker_kind','VERIFICATION_INCOMPLETE'),
                        'result_preserved':True,'freshness':observed,
                        'reason':'Inspect the concrete source-linked blocker in crew-report-read '+row['id'][1:]}
        # If any work is still running, wait first. This also avoids executing
        # dependency plans before readers and writers finish their current turn.
        waiting=[]
        for row in s['tasks']:
            report=s['reports'].get(row['ticket']); handback=row['result'] or {}
            native=self._native(owner,row)
            needs_handback=not report or handback.get('status') not in {'ANALYSIS','TESTED'}
            if (row['state']=='running' or (row['state']=='returned' and needs_handback and not native)) and target(self.store,owner,int(row['id'][1:]),row['agent_id']):
                waiting.append(row)
        if waiting:
            # Some older native hosts key results by opaque paths. After such a
            # response, ask one identity at a time rather than guessing a mapping.
            if self.store.get(owner, 'flow-singleton-wait', False): waiting=waiting[:1]
            return {**base,'action':'WAIT','slot':waiting[0]['id'],'slots':[r['id'] for r in waiting],
                    'native_call':wait_call(s,[r['agent_id'] for r in waiting]),
                    'after':'Use this native wait, then crew-step. A timeout is not completion; retain the same six IDs.'}
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
        details=self.crew.pending_report_details(owner,s)
        if details:
            return {**base,'action':'READ_REPORTS','slots':details,'helper':'crew-step --details',
                    'reason':'Current issue/truncated reports must be retrieved in full before a semantic transition'}
        for row in s['tasks']:
            if row['state']=='returned' and row['spec']['kind']=='implement' and not (row['result'] or {}).get('integrated'):
                return {**base,'action':'INTEGRATE','helper':'team-integrate '+row['id'],'after':'Inspect the patch and team-accept; do not reset user edits'}
        if any(r['state']=='pending' for r in s['tasks']):
            if any(r['state']=='pending' and set(r['spec']['depends_on'])<=done for r in s['tasks']):
                return {**base,'action':'DISPATCH','helper':'crew-next'}
            returned=next((r for r in s['tasks'] if r['state']=='returned'),None)
            if returned: return {**base,'action':'ACCEPT','helper':'team-accept '+returned['id'],'after':'Review the actual result before acceptance, then crew-next'}
            return {**base,'action':'BLOCKED','reason':'No runnable dependency; inspect current work without replacing the crew'}
        if s.get('mode')=='research' and s['phase']=='EXECUTE':
            from .research import Research
            research=Research(self.store,owner,self.package).status()
            if research.get('configured') and research['state']!='FINISHED':
                return {**base,'action':'RESEARCH','helper':'research-status; use research-recover on an exited controller; otherwise enqueue/wait or pause for a checkpoint',
                        'research':{k:research.get(k) for k in ('state','counts','revision','best_verified_candidate','seconds_since_improvement','controller_health')},
                        'semantic_decision_required':True}
        return {**base,'action':'ADVANCE','helper':{'PLAN':'crew-execute','EXECUTE':'finish current root implementation and checks, then crew-review',
                   'REVIEW':'crew-repair if issues remain; otherwise finish current evidence and crew-complete'}[s['phase']],
                'after':'Inspect all six current findings via crew-step; read full reports flagged for detail before deciding. Next-phase helpers revalidate source-linked records'}

    def prepare_recovery(self, owner, slot):
        if type(slot) is not int or not 1<=slot<=6: raise HarnessError('recovery slot must be 1..6')
        s,_=self.crew._current(owner); row=next(r for r in s['tasks'] if r['id']==f's{slot}')
        native=self._native(owner,row)
        if not native or native['state']!='completed' or row['state']!='returned':
            raise HarnessError('recover only a native-completed member; wait for running/unknown members first')
        report=s['reports'].get(row['ticket'])
        from .blockers import freshness
        observation=freshness(self.store,row['ticket'],report,s['requirements'])
        stale=bool(report and report.get('verdict')=='blocked' and observation['state']=='STALE' and s['phase']!='REVIEW')
        if (row['result'] or {}).get('status') in {'PARTIAL','BLOCKED'} and not stale:
            raise HarnessError('inspect the genuine blocked result instead of retrying it blindly')
        if report and report.get('verdict')=='blocked' and not stale:raise HarnessError('inspect the blocked report')
        if report and (row['result'] or {}).get('status') in {'ANALYSIS','TESTED'} and not stale:
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
        if stale:
            message=('LUNASTRA_TICKET='+row['ticket']+'\nLUNASTRA_REASSESS: Your earlier blocked report used dependencies that have now changed. '
                     'Keep the same assignment and session; re-read its current sources, recheck that precise blocker and replace your report. '
                     'Do not repeat unrelated implementation, delete old results, weaken requirements or report success merely because a file appeared. '
                     'Use your own helper crew-join, then crew-report and the appropriate checked handback.')
        tool,payload=dispatch(s,slot,message,target(self.store,owner,slot,row['agent_id']))
        self.store.put(owner,'flow-recovery:'+row['ticket'],{'count':count+1,'payload_hash':json_hash(payload),'plan_id':s['plan_id'],
                      'native_call_id':native['call_id'],'epoch':native['epoch'],
                      'mode':'reassess' if stale else 'missing-report','source_observation':observation if stale else None})
        return {'tool':tool,'arguments':payload,'slot':slot,'ticket':row['ticket'],'reuse_same_session':True}

    @staticmethod
    def authorize_recovery(db, owner, s, row, payload, kind):
        """Inside Crew's dispatch transaction, so failure never half-reopens work."""
        request=_value(db,owner,'flow-recovery:'+row['ticket'])
        native=_value(db,owner,'flow-native:'+row['ticket'])
        count=_value(db,owner,'flow-recovery-count:'+row['ticket'],0)
        if (kind!=('followup_task' if is_v2(s) else 'send_input') or row['state']!='returned' or not request or not native or
                native['state']!='completed' or request['plan_id']!=s['plan_id'] or
                request['epoch']!=_epoch(db,row['ticket']) or request['native_call_id']!=native['call_id'] or
                request['payload_hash']!=json_hash(payload) or request['count']!=count+1 or count>=MAX_RECOVERIES):
            raise HarnessError('same-ticket recovery requires a fresh crew-recover instruction and an observed native completion')
        handback=strict_json(row['result'] or '{}')
        report=db.execute('SELECT body FROM crew_reports WHERE ticket=?',(row['ticket'],)).fetchone()
        report=strict_json(report[0]) if report else None
        reassess=request.get('mode')=='reassess'
        if reassess:
            source=db.execute('SELECT * FROM crew_report_sources WHERE ticket=?',(row['ticket'],)).fetchone()
            from .crew import fingerprint
            if not source or not report or report.get('verdict')!='blocked' or source['report_hash']!=json_hash(report):
                raise HarnessError('stale report identity changed before recovery')
            current=fingerprint(Path(source['workspace']),strict_json(source['paths']))['sha256']
            observed=request.get('source_observation') or {}
            if (source['fingerprint']==current or observed.get('current_fingerprint')!=current or
                    observed.get('report_hash')!=json_hash(report)):
                raise HarnessError('dependency recheck no longer matches the prepared recovery')
            from .blockers import archive_recheck
            archive_recheck(db,owner,row['ticket'],report,observed)
            # Remove it from CURRENT reports only after archiving; this is a
            # stale report, never a deleted failure or an invented clear report.
            db.execute('DELETE FROM crew_reports WHERE ticket=?',(row['ticket'],))
        elif handback.get('status') in {'PARTIAL','BLOCKED'} or (report and (report.get('verdict')=='blocked' or handback.get('status') in {'ANALYSIS','TESTED'})):
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
        if meta.get('role')=='root':
            with self.store.db() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='research_studies'").fetchone():
                    row=db.execute('SELECT spec FROM research_studies WHERE owner=?',(key,)).fetchone()
                    if row:
                        study=strict_json(row[0]);value.append([study['state'],study['revision']])
        return json_hash(value)

    def correction(self, key, meta, problem):
        """Progress-aware Stop feedback; stop_hook_active is not a failure flag."""
        now=time.time(); signature=self.progress(key,meta); old=self.store.get(key,'flow-stop',{})
        if old.get('signature')!=signature:
            record={'signature':signature,'since':now,'idle':0,'last_stop':0.0}
        else: record=dict(old)
        if meta.get('role')=='root':
            action=self.drive(key)
            if action.get('complete') and problem:
                action={'action':'REPAIR_VERIFICATION','complete':False,'reason':problem,
                        'helper':'Inspect uncovered paths and the current proof; do not loop on crew-drive or discard the result.'}
            with self.store.db() as db:
                waited=db.execute('SELECT 1 FROM crew_waits WHERE owner=? AND finished>? AND valid=1 AND finished-started>=1 LIMIT 1',
                                  (key,record.get('last_stop',0.0))).fetchone()
            if not waited and meta.get('crew_enabled'):
                with self.store.db() as db:
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name='native_observations'").fetchone():
                        waited=db.execute("SELECT 1 FROM native_observations WHERE owner=? AND kind='wait_agent' AND finished>? AND valid=1 AND started>0 AND finished-started>=1 LIMIT 1",(key,record.get('last_stop',0.0))).fetchone()
            research_wait=self.store.get(key,'research-last-wait',{})
            if research_wait.get('ended_at',0)>record.get('last_stop',0.0) and research_wait.get('elapsed',0)>=1:waited=True
            if not waited: record['idle']=record.get('idle',0)+1
            else: record['idle']=0
            allowed=record['idle']<=MAX_IDLE_CORRECTIONS
            text=('LUNASTRA_CONTINUE: '+problem+'. Next step: '+canonical(action)+
                  '\nUse '+helper_command(self.prefix(key)+['crew-step'])+' to refresh the next action. '
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
