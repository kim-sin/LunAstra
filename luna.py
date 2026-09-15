#!/usr/bin/env python3
"""Local Luna helper. No network calls, model calls, or account access."""
from __future__ import annotations

# Hook fast path: reject non-Luna events before importing the orchestration stack.
# This keeps Astra/Sol/other Codex sessions from paying LunAstra's normal startup cost.
import json
import re
import sys

_EARLY_MAX_INPUT = 2 * 1024 * 1024
_EARLY_EVENTS = {
    'SessionStart', 'SubagentStart', 'UserPromptSubmit', 'PreToolUse',
    'PostToolUse', 'Stop', 'SubagentStop', 'PostCompact', 'Interrupt'
}
_EARLY_LUNA_MODEL = re.compile(r'^gpt-\d+(?:\.\d+)*-luna(?:-[a-z0-9][a-z0-9._-]*)?$')
_EARLY_HOOK = bool(sys.argv) and sys.argv[-1] == 'hook'
_EARLY_EVENT = None
_EARLY_ERROR = None
_EARLY_PENDING = False

def _early_pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError('duplicate JSON key: ' + key)
        out[key] = value
    return out

if _EARLY_HOOK:
    try:
        _early_raw = sys.stdin.buffer.read(_EARLY_MAX_INPUT + 1)
        if len(_early_raw) > _EARLY_MAX_INPUT:
            raise ValueError('input exceeds 2 MiB')
        _EARLY_EVENT = json.loads(
            _early_raw.decode('utf-8-sig'),
            object_pairs_hook=_early_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON number')),
        )
        if isinstance(_EARLY_EVENT, dict):
            _early_kind = _EARLY_EVENT.get('hook_event_name')
            _early_model = _EARLY_EVENT.get('model')
            if not isinstance(_early_kind,str):raise ValueError('hook_event_name must be a string')
            if _early_kind not in _EARLY_EVENTS or not (
                isinstance(_early_model, str) and (_early_model=='gpt-reserve' or _EARLY_LUNA_MODEL.fullmatch(_early_model))
            ):
                sys.stdout.buffer.write(b'{}\n')
                raise SystemExit(0)
        _EARLY_PENDING = True
    except SystemExit:
        raise
    except Exception as exc:  # preserve the existing guarded error path after full imports
        _EARLY_ERROR = exc
        _EARLY_PENDING = True

import argparse
import os
from pathlib import Path
import sqlite3
import subprocess
from luna_astra import __version__, __build__
from luna_astra.util import HarnessError, canonical, json_hash, load_json, strict_json
from luna_astra.hooks import Hooks, MAX_INPUT
from luna_astra.store import Store, evidence_directory
from luna_astra.codemap import CodeMap
from luna_astra.coordination import Coordinator
from luna_astra.evidence import Evidence
from luna_astra.team import Team
from luna_astra.crew import Crew
from luna_astra.gitspace import Workspaces
from luna_astra.jobs import Jobs
from luna_astra.scan import observe
from luna_astra.transport import worker_exec, read_source

_CLI_INPUT=None

ROOT=Path(__file__).resolve().parent
DEFAULT_STATE=Path(os.environ.get('CODEX_HOME') or str(Path.home()/'.codex'))/'luna-astra'/'state-v3'
HELP={
 'commands':['context --query TASK [--recover]','risk --files FILE ...','begin','run CHECK','run-all [--force]','status','finish','note','trace','claim --files FILE ...','release','doctor'],
 'begin_stdin':{'task_id':'actual-assignment','design':'Actual approved implementation method','requirements':['observable required behavior'],
     'allowed_paths':['src'],'protected_paths':[],
     'checks':[{'id':'focused','purpose':'Actual behavioral acceptance test','argv':['python','-m','unittest','discover','-s','tests'],
                'dependencies':['src','tests'],'covers':[0],'reusable':False,'environment_keys':[],'identity':{}}]},
 'finish_stdin':{'kind':'tested','summary':'Actual changes','review':'Design fidelity and relevant counterexample checked','limitations':'Scope and unexecuted checks'},
 'note_stdin':{'task_id':'actual-assignment','facts':['Observed fact and source'],'unresolved':['Unresolved issue'],'next_action':'Next authorized action'},
 'rules':['Derive fields from the existing assignment; do not make the caller fill a form.','reusable=true is opt-in for deterministic checks with complete dependency/environment identity.',
          'Run ordinary checks through existing project tools when this helper is unavailable; mark receipt verification unavailable.',
          'No model or reasoning setting is changed. Static maps never replace source reading or mandatory checks.']}

HELP['commands'] += ['team-plan','team-next','team-join TICKET','team-status','team-integrate TASK','team-accept TASK --review TEXT','team-abandon TASK --reason TEXT','team-resolve TASK --review TEXT','start-check CHECK','jobs','worker-exec --argv-json JSON [--cwd RELATIVE_DIR]']
HELP['large_json']='When Windows quoting exceeds the safe command limit, use input-append NAME --offset N --chunk TEXT (at most 1000 characters per chunk), then --input-ref NAME before the intended command. Use a fresh name per request; repeated offsets are idempotent.'
HELP['input_json']='Use --input-json JSON before begin/finish/note/team-plan instead of piping stdin; quote every argument literally.'
HELP['build']=__build__
HELP['version']=__version__
HELP['commands'].append('read PATH [--start-line N] [--max-lines N]')
HELP['team_plan_stdin']={'goal':'Current requested outcome','parallel_limit':6,'tasks':[{'id':'investigate','kind':'investigate','description':'Identify the failure from code and a reproduction','paths':['src'],'depends_on':[],'done_when':['Return the first divergence with source references'],'why_parallel':'Independent investigation while the leader handles another named part'}]}
HELP['team_rules']=['The original Luna chooses the number of useful independent units; 6 is only the concurrency ceiling, not an optimum.','Call team-next once per ready wave, then use native Codex tools; reservations alone launch nothing.','Use separate checkouts for implementation; dirty/non-Git roots require single-writer fallback.','Accept findings only after inspecting their evidence. Accept implementation only after checked integration, then verify the combined result.','No hidden model API and no inference-setting change.']


HELP['commands'] += ['crew-start','crew-revise','crew-continue','crew-next','crew-state','crew-report-read SLOT','input-append NAME --offset N --chunk TEXT','crew-join TICKET','crew-report','crew-execute','crew-review','crew-repair','crew-complete']
HELP['fixed_seven']={'total':7,'root':1,'children':6,'reuse':'same observed native IDs across all phases',
    'start':{'goal':'Requested outcome','requirements':['Observable acceptance requirement'], 'evidence_paths':['input.txt'],'output_paths':['output.txt']},
    'execute':{'decision':'Source-backed choice after all six planning reports','tasks':'Exactly s1..s6 using team task schema; s5/s6 always read-only; implement only locked output paths'},
    'report':{'verdict':'clear','summary':'Evidence-based result','findings':['Actual finding'],'references':[{'path':'input.txt'}],'covers':[0]},
    'review_complete':{'decision':'Actual root synthesis'},
    'sequence':'crew-start -> crew-next -> native calls -> workers crew-join/report/finish -> crew-execute -> reuse -> integrate + root begin/run-all -> crew-review -> reuse -> root finish -> crew-complete',
    'no_silent_fallback':'Fewer than six native children cannot be certified as fixed seven. Preserve the same IDs when the host blocks; do not replace unknown sessions.',
    'model_quality':'NOT_MEASURED; software tests and worker count do not establish Astra Max parity'}

HELP['legacy_team_rules']=HELP.pop('team_rules')
HELP['legacy_team_note']='The dynamic team plan and its launch limits are retained ONLY for pre-upgrade sessions. New sessions use fixed_seven. team-integrate/team-accept remain available during execution.'
HELP={'version':__version__,'build':__build__,'fixed_seven':HELP.pop('fixed_seven'),**HELP}

def stdin_json():
    global _EARLY_PENDING
    if _CLI_INPUT is not None:return strict_json(_CLI_INPUT)
    if _EARLY_PENDING:
        _EARLY_PENDING = False
        if _EARLY_ERROR is not None:
            raise HarnessError(str(_EARLY_ERROR))
        return _EARLY_EVENT
    data=sys.stdin.buffer.read(MAX_INPUT+1)
    if len(data)>MAX_INPUT:raise HarnessError('input exceeds 2 MiB')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise HarnessError('duplicate JSON key: '+k)
            out[k]=v
        return out
    return json.loads(data.decode('utf-8-sig'),object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(HarnessError('nonfinite JSON number')))

def main(argv=None):
    global _CLI_INPUT
    # Native hooks exchange UTF-8 JSON on every OS, including legacy Windows shells.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',type=Path,default=DEFAULT_STATE)
    p.add_argument('--session');p.add_argument('--workspace',type=Path)
    p.add_argument('--input-ref',help='Session-local JSON buffer populated with input-append')
    p.add_argument('--input-json',help='Literal JSON input instead of a stdin pipe')
    commands=p.add_subparsers(dest='command',required=True)
    for cmd in ('hook','help','doctor','begin','status','finish','note','trace','release'):commands.add_parser(cmd)
    sub=commands.add_parser('context');sub.add_argument('--query',default='');sub.add_argument('--recover',action='store_true')
    sub=commands.add_parser('risk');sub.add_argument('--files',nargs='+',required=True)
    sub=commands.add_parser('claim');sub.add_argument('--files',nargs='+',required=True)
    sub=commands.add_parser('run');sub.add_argument('check_id')
    sub=commands.add_parser('run-all');sub.add_argument('--force',action='store_true')
    sub=commands.add_parser('start-check');sub.add_argument('check_id')
    sub=commands.add_parser('job-worker');sub.add_argument('job_id')
    commands.add_parser('jobs')
    sub=commands.add_parser('worker-exec');sub.add_argument('--argv-json',required=True);sub.add_argument('--cwd',default='.')
    sub=commands.add_parser('read');sub.add_argument('path');sub.add_argument('--start-line',type=int,default=1);sub.add_argument('--max-lines',type=int,default=400)
    commands.add_parser('team-plan')
    commands.add_parser('team-next')
    commands.add_parser('team-status')
    sub=commands.add_parser('team-join');sub.add_argument('ticket')
    sub=commands.add_parser('team-integrate');sub.add_argument('task_id')
    sub=commands.add_parser('team-accept');sub.add_argument('task_id');sub.add_argument('--review',required=True)
    sub=commands.add_parser('team-resolve');sub.add_argument('task_id');sub.add_argument('--review',required=True)
    sub=commands.add_parser('team-abandon');sub.add_argument('task_id');sub.add_argument('--reason',required=True)
    for cmd in ('crew-start','crew-revise','crew-continue','crew-next','crew-state','crew-report','crew-execute','crew-repair','crew-review','crew-complete'):commands.add_parser(cmd)
    sub=commands.add_parser('crew-join');sub.add_argument('ticket')
    sub=commands.add_parser('crew-report-read');sub.add_argument('slot',type=int)
    sub=commands.add_parser('input-append');sub.add_argument('name');sub.add_argument('--offset',type=int,required=True);sub.add_argument('--chunk',required=True)
    a=p.parse_args(argv)
    event=None
    try:
        if a.input_ref and a.input_json is not None:raise HarnessError('choose input-ref OR input-json')
        _CLI_INPUT=a.input_json
        if a.input_ref:
            if not a.session or not re.fullmatch('[a-f0-9]{64}',a.session):raise HarnessError('input-ref requires an observed session')
            from luna_astra.input_buffer import read as read_input
            _CLI_INPUT=read_input(Store(a.state),a.session,a.input_ref)
        if _CLI_INPUT is not None and (a.command not in {'begin','finish','note','team-plan','crew-start','crew-revise','crew-continue','crew-report','crew-execute','crew-repair','crew-review','crew-complete'} or len(_CLI_INPUT.encode('utf-8'))>MAX_INPUT):
            raise HarnessError('--input-json is only for bounded begin/finish/note/team-plan input')
        if a.command=='hook':
            event=stdin_json();result=Hooks(ROOT,a.state,fixed_seven=True).handle(event)
        elif a.command=='help': result=HELP
        elif a.command=='doctor':result=Hooks(ROOT,a.state).doctor()
        else:
            if a.session and not re.fullmatch('[a-f0-9]{64}',a.session):raise HarnessError('invalid session key')
            store=Store(a.state)
            key=a.session
            meta=store.get(key,'meta') if key else None
            if meta is not None and not isinstance(meta,dict):raise HarnessError('invalid persisted session metadata')
            if not meta:
                if a.session:raise HarnessError('no matching session metadata')
                if not a.workspace or a.command not in {'context','risk'}:
                    raise HarnessError('use the hook-supplied --session; standalone context/risk needs --workspace')
                ws=a.workspace.resolve()
                key=json_hash(['manual',str(ws)])
                meta={'workspace':str(ws),'role':'root','key':key,'helper_used':True,'model':'UNVERIFIED_MANUAL_CONTEXT','version':__version__}
            root=Path(meta.get('assigned_workspace',meta['workspace']));directory=evidence_directory(a.state,key,meta)
            if meta.get('read_only') and a.command in {'worker-exec','run','run-all','start-check','job-worker'}:
                raise HarnessError('read-only delegate cannot run arbitrary commands; inspect sources with read/context/risk and send executable checks to the leader')
            meta['helper_used']=True;store.put(key,'meta',meta)
            ev=None
            if a.command in {'begin','run','run-all','finish'} or (directory/'evidence.sqlite3').exists():ev=Evidence(directory,root)
            if a.command=='input-append':
                from luna_astra.input_buffer import append
                result=append(store,key,a.name,a.offset,a.chunk)
            elif a.command=='read':
                result=read_source(root,a.path,a.start_line,a.max_lines)
            elif a.command=='worker-exec':
                result=worker_exec(meta,strict_json(a.argv_json),a.cwd)
            elif a.command.startswith('crew-'):
                crew= Crew(store,ROOT)
                if a.command=='crew-join':result=crew.join(key,a.ticket,meta)
                elif a.command=='crew-report':result=crew.report(key,stdin_json())
                else:
                    if meta.get('role')!='root':raise HarnessError('only the root coordinates the fixed seven')
                    if a.command in {'crew-start','crew-revise'}:
                        result=crew.start(key,stdin_json(),revise=a.command=='crew-revise')
                        # Read-only status must not migrate a legacy session.
                        # Promote only after the explicit new contract succeeds.
                        if not meta.get('crew_enabled'):meta['context_emitted']=False
                        meta['crew_enabled']=True;store.put(key,'meta',meta)
                    elif a.command=='crew-next':result=crew.next(key)
                    elif a.command=='crew-state':result=crew.inspect(key)
                    elif a.command=='crew-report-read':result=crew.read_report(key,a.slot)
                    elif a.command in {'crew-execute','crew-repair'}:result=crew.execute(key,stdin_json(),repair=a.command=='crew-repair')
                    else:
                        data=stdin_json()
                        if not isinstance(data,dict) or set(data)!={'decision'}:raise HarnessError('supply decision text only')
                        if a.command=='crew-review':result=crew.review(key,data['decision'])
                        elif a.command=='crew-continue':result=crew.acknowledge_unchanged(key,data['decision'])
                        else:result=crew.complete(key,data['decision'])
            elif a.command.startswith('team-'):
                if meta.get('crew_enabled') and a.command not in {'team-integrate','team-accept','team-status'}:
                    raise HarnessError('use the fixed-seven crew commands; legacy plans cannot bypass the fixed roster')
                team=Team(store)
                if a.command=='team-join':
                    result=team.join(key,a.ticket,meta)
                    store.put(key,'source_baseline',observe(Path(result['workspace'])))
                else:
                    if meta.get('role')!='root':raise HarnessError('only the original Luna leader schedules and integrates workers')
                    if meta.get('crew_enabled') and a.command in {'team-integrate','team-accept'}:Crew(store,ROOT).can_write(key)
                    if a.command=='team-plan':result=team.plan(key,root,stdin_json())
                    elif a.command=='team-status':result=team.status(key)
                    elif a.command=='team-next':
                        result=team.reserve(key)
                        for task in result['reserved']:
                            if task['kind']=='implement':
                                try:
                                    info=Workspaces(a.state/'worktrees').prepare(task['ticket'],root,task['paths'])
                                    team.set_workspace(key,task['ticket'],info['tree']);task['workspace']=info['tree']
                                except (OSError,ValueError,subprocess.SubprocessError) as exc:
                                    team.abandon(key,task['id'],'isolation unavailable: '+str(exc))
                                    task['not_dispatched']=True;task['reason']=str(exc)
                                    task['next']='Leader implements this unit in the existing workspace; do not start a duplicate or discard current user edits.'
                                    continue
                            task['message']='LUNASTRA_TICKET='+task['ticket']+'\n'+task['description']+'\nFirst use LOCAL_HELPER_ARGV + team-join '+task['ticket']+'. Read its assigned workspace and acceptance conditions before acting. Do not spawn any model workers.'
                            task['same_model']=meta['model']
                            task['native_call_note']='Use the tool schema actually exposed by Codex. Use a full-history inherited fork, omitting model/effort/custom-role overrides. Fresh-context inheritance is not assumed.'
                    elif a.command=='team-accept':result=team.accept(key,a.task_id,a.review)
                    elif a.command=='team-abandon':result=team.abandon(key,a.task_id,a.reason)
                    elif a.command=='team-resolve':
                        if not ev:raise HarnessError('local final checks are required before resolving this task')
                        if Jobs(store,key,ROOT).active() or store.get(key,'finish_generation')!=store.get(key,'generation'):raise HarnessError('current finished checks are required')
                        result=team.resolve_locally(key,a.task_id,a.review,ev.status())
                    else:
                        status=team.status(key);row=next((r for r in status['tasks'] if r['id']==a.task_id),None)
                        if not row or row['state']!='returned' or row['spec']['kind']!='implement':raise HarnessError('no returned implementation for integration')
                        handback=row['result'] or {};worker_key=handback.get('worker_key')
                        if handback.get('status')!='TESTED' or not worker_key:raise HarnessError('worker result lacks tested evidence')
                        worker=store.get(worker_key,'meta',{})
                        if worker.get('team_ticket')!=row['ticket']:raise HarnessError('worker evidence belongs to another assignment')
                        current=Evidence(evidence_directory(a.state,worker_key,worker)).status()
                        if not current['passed'] or not current.get('finish') or not current['finish']['valid']:raise HarnessError('worker evidence is stale or incomplete')
                        if store.get(worker_key,'finish_generation')!=store.get(worker_key,'generation') or Jobs(store,worker_key,ROOT).active():raise HarnessError('worker has newer or active work')
                        spaces=Workspaces(a.state/'worktrees')
                        info=load_json(a.state/'worktrees'/row['ticket']/'record.json')
                        if Path(info['tree'])!=Path(worker['assigned_workspace']):raise HarnessError('checkout identity differs from evidence workspace')
                        with Evidence(evidence_directory(a.state,worker_key,worker))._db() as db:
                            definition=Evidence._get(db,'task')
                        dependencies=[p for c in definition['checks'] for p in c['dependencies']+c.get('expected_absent',[])]
                        for name in spaces.changes(info):
                            if not any(name==d or name.startswith(d.rstrip('/')+'/') for d in dependencies):raise HarnessError('unverified worker change: '+name)
                        result=spaces.integrate(row['ticket'])
                        handback.update(integrated=True,changed_paths=result.get('changed_paths',[]))
                        team.returned(row['ticket'],handback)
                        store.put(key,'edited_in_turn',store.get(key,'generation','startup'))
            elif a.command in {'start-check','job-worker','jobs'}:
                jobs=Jobs(store,key,ROOT)
                if a.command=='start-check':result=jobs.start(a.check_id)
                elif a.command=='job-worker':result=jobs.run_worker(a.job_id)
                else:result={'jobs':jobs.all(),'active':len(jobs.active()),'pid_is_not_progress':True}
            elif a.command in {'context','risk'}:
                mapper=CodeMap(root,a.state/'maps');index=mapper.build()
                if a.command=='risk':
                    mandatory=[]
                    if ev:
                        with ev._db() as db:
                            task=ev._get(db,'task') or {};mandatory=[c['id'] for c in task.get('checks',[])]
                    result=mapper.risk(index,a.files,mandatory)
                else:
                    result=mapper.select(index,a.query)
                    result.update(role=meta['role'],saved_note=store.get(key,'note'),recent_operations=store.recent(key,6),
                                  current_evidence=ev.status() if ev else None)
                    if a.recover:result['kernel']=Hooks(ROOT,a.state,fixed_seven=bool(meta.get('crew_enabled')))._core(key,meta['role'])
                    if meta.get('crew_enabled') and meta.get('role')=='root':result['crew']=Crew(store,ROOT).summary(key)
            elif a.command=='begin':
                if Jobs(store,key,ROOT).active():raise HarnessError('a check controller is outstanding; do not replace its assignment')
                result=ev.begin(stdin_json())
                if result['changed']:store.put(key,'note',None)
            elif a.command=='run':result=ev.run(a.check_id)
            elif a.command=='run-all':result=ev.run_all(reuse=not a.force)
            elif a.command=='finish':
                data=stdin_json()
                if not isinstance(data,dict) or set(data)!={'kind','summary','review','limitations'}:raise HarnessError('invalid finish fields')
                if Jobs(store,key,ROOT).active() and data['kind']=='tested':raise HarnessError('check controller is still outstanding')
                result=ev.finish(**data)
                store.put(key,'finish_generation',store.get(key,'generation','startup'))
            elif a.command=='status':result={'session':meta,'evidence':ev.status() if ev else None,'leases':Coordinator(store,root).status()}
            elif a.command=='trace':result={'operations':store.recent(key,100),'stored_raw_prompt':False,'emitted_characters':store.get(key,'emitted_chars',0),'billed_usage':None}
            elif a.command=='note':
                note=stdin_json()
                if not isinstance(note,dict) or set(note)!={'task_id','facts','unresolved','next_action'}:raise HarnessError('invalid note fields')
                if not isinstance(note['task_id'],str) or not note['task_id'] or not isinstance(note['next_action'],str):raise HarnessError('invalid note text')
                if any(not isinstance(note[k],list) or any(not isinstance(t,str) for t in note[k]) for k in ('facts','unresolved')):raise HarnessError('invalid note lists')
                if len(canonical(note))>6000:raise HarnessError('note exceeds 6000 characters')
                if ev:
                    with ev._db() as db:task=ev._get(db,'task')
                    if task and task['task_id']!=note['task_id']:raise HarnessError('note belongs to another task')
                store.put(key,'note',note);result={'saved':True,'not_hidden_reasoning':True}
            elif a.command=='claim':result={'claimed':Coordinator(store,root).claim(key,a.files,'manual')}
            else:
                Coordinator(store,root).release(key,'manual');result={'released_own_manual_claims':True}
        print(canonical(result))
        if a.command=='run' and result['status']!='PASS':return 1
        if a.command=='run-all' and not result['status']['passed']:return 1
        if a.command=='worker-exec' and result['exit_code']!=0:return 1
        return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError,sqlite3.Error,subprocess.SubprocessError) as exc:
        if a.command=='hook':
            warning='LunAstra unavailable; no verification asserted: '+str(exc)[:300]
            if isinstance(event,dict) and event.get('hook_event_name')=='PreToolUse':
                print(canonical({'systemMessage':warning,'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':'LunAstra could not validate this call. Preserve state; resolve the diagnostic before retrying.'}}))
                return 0
            if isinstance(event,dict) and event.get('hook_event_name') in {'Stop','SubagentStop'}:
                print(canonical({'continue':False,'stopReason':'LunAstra: UNVERIFIED due to an unreadable guard state.','systemMessage':warning}))
                return 0
            print(canonical({'systemMessage':warning}))
        else:print(canonical({'error':str(exc),'status':'NOT_VERIFIED'}),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
