"""Luna-only adapters for documented Codex lifecycle events."""
from __future__ import annotations
import json
import re
import sys
import time
from pathlib import Path
from . import __version__, __build__
from .util import HarnessError, strict_json, digest, canonical, json_hash, no_symlinks
from .store import Store, evidence_directory
from .coordination import Coordinator, Conflict, edit_paths, assigned_edit_input
from .codemap import CodeMap
from .evidence import Evidence
from .team import Team
from .crew import Crew
from .scan import observe, changes
from .jobs import Jobs
from .transport import tool_name, helper_command, worker_shell_input, literal_argv, literal_shell_input

MAX_INPUT=2*1024*1024
EVENTS={'SessionStart','SubagentStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop','SubagentStop','PostCompact','Interrupt'}
LUNA_MODEL=re.compile(r'^gpt-\d+(?:\.\d+)*-luna(?:-[a-z0-9][a-z0-9._-]*)?$')

def is_luna(value):
    return isinstance(value,str) and (value == 'gpt-reserve' or bool(LUNA_MODEL.fullmatch(value)))

def identity(event):
    session=event.get('session_id');agent=event.get('agent_id')
    if not isinstance(session,str) or not 1<=len(session)<=4096:raise HarnessError('missing actual session_id')
    if agent is not None and (not isinstance(agent,str) or not 1<=len(agent)<=4096):raise HarnessError('invalid actual agent_id')
    if event.get('hook_event_name','').startswith('Subagent') and agent is None:raise HarnessError('Subagent event has no actual agent_id')
    cwd=event.get('cwd')
    if not isinstance(cwd,str) or not Path(cwd).is_dir():raise HarnessError('workspace unavailable')
    root=Path(cwd).absolute();no_symlinks(root);root=root.resolve()
    return json_hash([session,agent,str(root),event['model']]),('worker' if agent else 'root'),root

def outcome(response):
    # Recognize concrete status fields only. Never label arbitrary text 'PASS'.
    if isinstance(response,dict):
        if response.get('isError') is True or response.get('is_error') is True: return 'FAIL'
        for name in ('exit_code','exitCode','returncode'):
            if type(response.get(name)) is int: return 'SUCCESS' if response[name]==0 else 'FAIL'
        if response.get('status') in ('running','RUNNING','in_progress'): return 'RUNNING'
    return 'UNKNOWN'

class Hooks:
    def __init__(self,package:Path,state:Path, *, fixed_seven=False):
        self.fixed_seven=fixed_seven
        self.package=Path(package).resolve();self.state=Path(state).absolute();no_symlinks(self.state)

    def _prompt(self,name):
        path=self.package/'prompts'/name
        no_symlinks(path)
        if path.stat().st_size>16000:raise HarnessError('prompt exceeds package budget')
        return path.read_text(encoding='utf-8').strip()

    def _core(self,key,role):
        prefix=[sys.executable,str(self.package/'luna.py'),'--state',str(self.state),'--session',key]
        role_file=('FIXED_'+role.upper()+'.md') if self.fixed_seven else (role.upper()+'.md')
        return self._prompt('CORE.md')+'\n\n'+self._prompt(role_file)+'\n\n'+(
            'LUNA_ASTRA_VERSION='+__version__+'\nLUNASTRA_BUILD='+__build__+'\nLOCAL_HELPER_ARGV='+json.dumps(prefix,ensure_ascii=False)+'\nLOCAL_HELPER_COMMAND='+helper_command(prefix)+'\n'+
            ("Fixed seven: use help.fixed_seven and crew-start/next/execute/review/complete. The team-* commands are retained for migration and checked integration only. " if self.fixed_seven else "Use help for the legacy team protocol. ")+
            "Use read/context for bounded source navigation; maps never replace reading. After compaction run context --recover. "
            "Local helpers make no model calls and never change the selected Luna or reasoning setting.")


    def _module(self,store,key,name,generation):
        if store.once(key,'module:'+name,generation):return self._prompt('modules/'+name+'.md')
        return ''

    def handle(self,event):
        # Diagnostics are separate from task control and never certify a host.
        tracked=(isinstance(event,dict) and isinstance(event.get('hook_event_name'),str)
                 and event['hook_event_name'] in EVENTS and is_luna(event.get('model')))
        try:
            output=self._handle(event)
        except Exception:
            if tracked:self._record_connection(event,None,failed=True)
            raise
        if tracked:self._record_connection(event,output)
        return output

    def _record_connection(self,event,output,failed=False):
        from .connection import record_hook
        try:record_hook(self.state,self.package,event,output,failed=failed)
        except (OSError,ValueError,TypeError,KeyError,AttributeError,__import__('sqlite3').Error):
            # A diagnostic write must not change an existing allow/deny/stop
            # decision or interrupt an otherwise successful task operation.
            print('LunAstra connection diagnostics unavailable; do not infer a verified connection.',file=sys.stderr)

    def _handle(self,event):
        if not isinstance(event,dict):raise HarnessError('hook input must be a JSON object')
        kind=event.get('hook_event_name')
        if not isinstance(kind, str):raise HarnessError('hook_event_name must be a string')
        if kind not in EVENTS or not is_luna(event.get('model')):return {}  # No state creation for other models.
        for field in ('turn_id','tool_use_id','tool_name'):
            if field in event and (not isinstance(event[field],str) or not event[field]):
                raise HarnessError('invalid '+field)
        for field in ('prompt','last_assistant_message'):
            if field in event and event[field] is not None and not isinstance(event[field],str):
                raise HarnessError('invalid '+field)
        if 'stop_hook_active' in event and type(event['stop_hook_active']) is not bool:
            raise HarnessError('stop_hook_active must be boolean')
        # Some hosts use the child's own session id on tool events. Resolve only
        # an alias previously observed in a genuine SubagentStart payload.
        store=Store(self.state)
        alias_id=event.get('agent_id') or event.get('session_id')
        alias=store.get('__agent_alias__',alias_id) if isinstance(alias_id,str) else None
        if alias is not None and (not isinstance(alias,dict) or not all(isinstance(alias.get(n),str) for n in ('parent','key','model'))):
            raise HarnessError('invalid persisted agent alias')
        if alias and event.get('session_id') in {alias['parent'],alias_id} and alias.get('model')==event['model']:
            event={**event,'session_id':alias['parent'],'agent_id':alias_id}
        key,role,root=identity(event)
        if alias and alias.get('model')==event['model'] and alias.get('key') and event['session_id']==alias['parent']:
            known=store.get(alias['key'],'meta',{})
            legitimate={known.get('workspace'),known.get('assigned_workspace')}
            if str(root) in legitimate:key=alias['key']
        if kind=='SubagentStart':store.put('__agent_alias__',event['agent_id'],{'parent':event['session_id'],'key':key,'model':event['model']})
        store=Store(self.state); meta=store.get(key,'meta')
        if meta is not None and not isinstance(meta,dict):raise HarnessError('invalid persisted session metadata')
        new=not meta
        meta=meta or {'key':key,'role':role,'workspace':str(root),'model':event['model'],'created_at':time.time(),
                     'context_emitted':False,'helper_used':False,'actual_model_parity':'NOT_MEASURED'}
        if new and role=='root' and self.fixed_seven:meta['crew_enabled']=True
        if new and role=='worker' and self.fixed_seven:
            team=Team(store)
            with store.db() as db:
                bound=db.execute('SELECT owner FROM work WHERE agent_id=? ORDER BY rowid DESC LIMIT 1',(event.get('agent_id'),)).fetchone()
            meta['crew_enabled']=bool(store.get(bound['owner'],'meta',{}).get('crew_enabled')) if bound else True
        meta['version']=__version__;meta['build']=__build__;meta['last_event']=kind
        meta.update(session_id=event['session_id'],agent_id=event.get('agent_id'))
        # Native SubagentStart.session_id is the CHILD session, not its parent.
        # The parent is bound by an observed native spawn result in Team.join.
        if role=='root':
            meta['parent_session_id']=None
        elif event['session_id'] != event.get('agent_id'):
            meta['parent_session_id']=event['session_id']  # legacy host contract
        elif meta.get('parent_session_id') == event.get('agent_id'):
            meta['parent_session_id']=None  # migrate the old self-parent record
        if meta.get('assigned_workspace'):root=Path(meta['assigned_workspace'])
        if kind=='Interrupt':
            store.put(key,'interrupted',True)
            return {}
        store.put(key,'meta',meta)
        generation=str(event.get('turn_id') or store.get(key,'generation','startup'))
        store.put(key,'generation',generation)
        parts=[];emitted_core=False;tool_update=None;coordinator=Coordinator(store,root)
        if new and kind not in {'Stop','SubagentStop'}:
            store.put(key,'source_baseline',observe(root))
        if kind=='PostCompact':
            # This native event cannot return additionalContext. Mark a restore,
            # then emit once on SessionStart(compact) or the next context-capable event.
            meta['restore_pending']=True
            store.put(key,'meta',meta)
            return {}
        restore=bool(meta.get('restore_pending')) or meta.get('kernel_release')!=str(self.package)
        if not emitted_core and kind not in {'Stop','SubagentStop'} and (kind in {'SessionStart','SubagentStart'} or new or restore or not meta.get('context_emitted') or meta.get('kernel_version')!=__version__ or meta.get('kernel_build')!=__build__):
            first_core=store.once(key,'start_core',__version__+'+'+__build__)
            if restore or first_core or not meta.get('context_emitted') or meta.get('kernel_version')!=__version__ or meta.get('kernel_build')!=__build__ or event.get('source') in {'resume','clear','compact','fork'}:
                parts.append(Hooks(self.package,self.state,fixed_seven=bool(meta.get('crew_enabled')))._core(key,role));emitted_core=True
                note=store.get(key,'note')
                if note:parts.append('Saved working note (historical; recheck changed source): '+canonical(note))
                if restore and role=='root':
                    parts.append('Saved team state: '+canonical(Crew(store,self.package).summary(key) if meta.get('crew_enabled') else self._team_summary(Team(store).status(key))))
        if kind=='UserPromptSubmit':
            prompt=event.get('prompt','')
            if role=='root' and meta.get('crew_enabled') and not prompt.startswith('LUNASTRA_CONTINUE:'):
                store.put(key,'request_hash',json_hash(prompt))
            store.put(key,'current_turn',generation)
            store.put(key,'interrupted',False)
            if store.once(key,'baseline_turn',generation):store.put(key,'source_baseline',observe(root))
            if isinstance(prompt,str) and re.search(r'\.(py|ts|js|rs|go)\b|\uCF54\uB4DC|\uCF54\uB529|\uBC84\uADF8|\uAD6C\uD604|\uC624\uB958|\uD14C\uC2A4\uD2B8|\b(fix|implement|debug|refactor|test)\b',prompt,re.I):
                # A bounded on-demand map, not a full source dump or a new model call.
                if store.once(key,'prompt_map',generation):
                    parts.extend(self._map(root,prompt,[]))
                if re.search(r'\uB370\uC774\uD130|\uC2DC\uAC04|\uCE90\uC2DC|\uB3D9\uC2DC|\b(data|cache|concurr|timestamp|state)\b',prompt,re.I):
                    parts.append(self._module(store,key,'DATA',generation))
        elif kind=='PreToolUse':
            tool=str(event.get('tool_name',''));payload=event.get('tool_input');uid=event.get('tool_use_id')
            if not isinstance(uid,str) or not uid:raise HarnessError('missing tool_use_id')
            name=tool_name(tool)
            if name=='spawn_agent':
                try:
                    if role!='root':raise HarnessError('no nested model workers; report the need to the leader')
                    if meta.get('crew_enabled'):Crew(store,self.package).pre_dispatch(key,uid,payload,event['model'],'spawn_agent')
                    else:Team(store).pre_spawn(key,uid,payload,event['model'])
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if name in {'followup_task','send_input'} and role=='root':
                try:
                    if meta.get('crew_enabled'):Crew(store,self.package).pre_dispatch(key,uid,payload,event['model'],'send_input')
                    else:Team(store).pre_followup(key,payload)
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if name=='resume_agent' and role=='root' and meta.get('crew_enabled'):
                target=payload.get('id') if isinstance(payload,dict) else None
                members=Crew(store,self.package).status(key).get('members',[])
                if not target or target not in {m['agent_id'] for m in members}:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'Resume only an already-bound member of this fixed crew.'})
            if name=='close_agent' and role=='root':
                try:
                    if meta.get('crew_enabled'):raise HarnessError('keep the six native sessions for reuse; do not close or replace crew members')
                    Team(store).pre_close(key,payload)
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            paths=edit_paths(tool,payload)
            if role=='root' and meta.get('crew_enabled'):
                try:
                    crew=Crew(store,self.package)
                    if paths:coordinator.enforce_task(paths,{'allowed_paths':crew.can_write(key)})
                    if name in {'Bash','exec_command','shell_command'}:
                        phase=crew.status(key).get('phase')
                        command=payload.get('command',payload.get('cmd')) if isinstance(payload,dict) else None
                        prefix=[sys.executable,str(self.package/'luna.py'),'--state',str(self.state),'--session',key]
                        try:argv=literal_argv(command)
                        except HarnessError:
                            if phase!='EXECUTE':raise
                            argv=[]  # Ordinary execution commands remain subject to native host controls.
                        own_helper=argv[:len(prefix)]==prefix
                        if phase!='EXECUTE':
                            rest=argv[len(prefix):]
                            if not own_helper:raise HarnessError('planning/review is read-only; use the local helper read/context and crew commands')
                            if rest[:1] in (['--input-json'],['--input-ref']):rest=rest[2:]
                            if not rest or rest[0] not in {'help','input-append','read','context','risk','status','note','trace','jobs','begin','run','run-all','start-check','finish','crew-start','crew-revise','crew-continue','crew-next','crew-state','crew-report-read','crew-execute','crew-review','crew-repair','crew-complete'}:raise HarnessError('unsupported helper during planning/review')
                        if own_helper and name=='Bash':
                            tool_update=literal_shell_input(command,prefix)
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if role=='worker' and meta.get('crew_enabled') and name in {'send_input','followup_task','resume_agent','close_agent'}:
                return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'Only the root dispatches the six crew members.'})
            native_unjoined=(role=='worker' and event['session_id']==event.get('agent_id') and not meta.get('team_ticket'))
            if native_unjoined and paths:
                return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'Join the assigned LunAstra ticket before editing; the child session ID is not parent identity.'})
            if role=='worker' and name=='Bash' and (meta.get('team_ticket') or native_unjoined):
                try:
                    if not isinstance(payload,dict) or not isinstance(payload.get('command'),str):
                        raise HarnessError('native Bash hook requires command')
                    prefix=[sys.executable,str(self.package/'luna.py'),'--state',str(self.state),'--session',key]
                    tool_update=worker_shell_input(payload['command'],prefix,joined=bool(meta.get('team_ticket')),read_only=bool(meta.get('read_only')))
                except HarnessError as exc:
                    message=str(exc)+'. Use LOCAL_HELPER_COMMAND + worker-exec --argv-json <JSON array>; choose the executable/shell explicitly. Use --input-json <JSON> before begin/finish/note instead of a shell pipe.'
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':message})
            if paths and meta.get('assigned_workspace') and not meta.get('read_only'):
                try:
                    payload=assigned_edit_input(tool,payload,root)
                    tool_update=payload
                    paths=edit_paths(tool,payload)
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if meta.get('assigned_workspace') and name=='exec_command' and isinstance(payload,dict):
                # These recognized shell shapes accept an explicit workdir/cwd.
                # Do not silently rewrite unknown shell tools or shell contents.
                field='workdir'
                if field:
                    value=payload.get(field)
                    if value:
                        candidate=Path(value)
                        if not candidate.is_absolute():candidate=root/candidate
                        try:candidate.resolve().relative_to(root.resolve())
                        except ValueError:
                            return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'Worker command cwd is outside its assigned checkout.'})
                        no_symlinks(candidate)
                    else:tool_update={**payload,field:str(root)}

            if paths and meta.get('read_only'):
                return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'This worker is read-only. Return evidence or a proposed patch to the leader.'})
            if paths:
                evidence_dir=evidence_directory(self.state,key,meta)
                task=None
                if (evidence_dir/'evidence.sqlite3').is_file():
                    ev=Evidence(evidence_dir)
                    with ev._db() as db:task=ev._get(db,'task')
                try:
                    if meta.get('assigned_paths'):
                        coordinator.enforce_task(paths,{'allowed_paths':meta['assigned_paths']})
                    coordinator.enforce_task(paths,task)
                    normalized_paths=coordinator.claim(key,paths,'tool:'+uid)
                except HarnessError as e:
                    return self._output(store,key,kind,parts,emitted_core,{
                        'permissionDecision':'deny',
                        'permissionDecisionReason':str(e)+'. Preserve other work; use an isolated patch or resolve ownership.'})
                parts.append(self._module(store,key,'EDIT',generation))
                parts.append(self._module(store,key,'VERIFY',generation))
                if store.once(key,'edit_map',generation):parts.extend(self._map(root,' '.join(normalized_paths),normalized_paths))
                store.put(key,'edited_in_turn',generation)
            store.event(key,'pre:'+uid,'tool_start',{'tool':tool,'input_sha256':json_hash(payload),'edit_paths':paths,
                                                     'outcome':'RUNNING','turn':generation})
        elif kind=='PostToolUse':
            uid=event.get('tool_use_id');tool=str(event.get('tool_name',''));payload=event.get('tool_input')
            if not isinstance(uid,str) or not uid:raise HarnessError('missing tool_use_id')
            if tool_name(tool) in {'spawn_agent','send_input','followup_task'} and role=='root':
                if meta.get('crew_enabled'):Crew(store,self.package).post_dispatch(key,uid,event.get('tool_response'))
                elif tool_name(tool)=='spawn_agent':Team(store).post_spawn(key,uid,event.get('tool_response'))
            if tool_name(tool)=='wait_agent' and role=='root':Team(store).observed_statuses(key,event.get('tool_response'))
            result=outcome(event.get('tool_response'));fingerprint=json_hash([tool,payload])
            recorded=store.event(key,'post:'+uid,'tool_result',{'tool':tool,'input_sha256':fingerprint,
                                   'response_sha256':json_hash(event.get('tool_response')),'outcome':result,'turn':generation})
            # Post means the call returned, including failure. Pending background work is not a completed write.
            if result!='RUNNING':coordinator.release(key,'tool:'+uid)
            if result=='FAIL' and recorded:
                count=store.get(key,'failure:'+fingerprint,0)+1;store.put(key,'failure:'+fingerprint,count)
                parts.append(self._module(store,key,'DEBUG',generation))
                if count>1 and store.once(key,'repeat:'+fingerprint,generation):
                    parts.append('Repeated failed tool input observed. Check changed source/environment before retrying; this is a hint, not a forced pivot.')
        elif kind in {'Stop','SubagentStop'}:
            return self._stop(store,key,event,coordinator)
        return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'allow','updatedInput':tool_update} if tool_update is not None else None)

    def _output(self,store,key,kind,parts,emitted_core=False,extra=None):
        content='\n\n'.join(p for p in parts if p)
        specific={'hookEventName':kind,**(extra or {})}
        if content:
            specific['additionalContext']=content
            # Count only context present in this response, including a guarded denial.
            with store.db(True) as db:
                row=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(key,'emitted_chars')).fetchone()
                old=strict_json(row[0]) if row else 0
                db.execute('INSERT INTO kv VALUES(?,?,?) ON CONFLICT(scope,name) DO UPDATE SET value=excluded.value',(key,'emitted_chars',canonical(old+len(content))))
                if emitted_core:
                    row=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(key,'meta')).fetchone()
                    meta=strict_json(row[0]);meta.update(context_emitted=True,kernel_version=__version__,kernel_build=__build__,kernel_release=str(self.package),restore_pending=False)
                    db.execute('UPDATE kv SET value=? WHERE scope=? AND name=?',(canonical(meta),key,'meta'))
        return {'hookSpecificOutput':specific} if content or extra else {}

    def _map(self,root,query,hints):
        try:
            mapper=CodeMap(root,self.state/'maps');index=mapper.build(max_seconds=2.5)
            return [mapper.select(index,query,hints,max_chars=2200)['text']]
        except (OSError,ValueError,RecursionError):
            return ['Local map unavailable. Inspect relevant source using existing tools; do not assume complete coverage.']

    @staticmethod
    def _team_summary(status):
        return {'configured':status['configured'],'active':status['active'],'complete':status['complete'],
                'tasks':[{'id':r['id'],'state':r['state']} for r in status['tasks']]}

    def _stop(self,store,key,event,coordinator):
        meta=store.get(key,'meta',{})
        if store.get(key,'interrupted',False):return {}
        problem=None
        if meta.get('crew_enabled'):
            crew=Crew(store,self.package)
            if meta.get('role')=='root':
                if store.get(key,'request_hash') or crew.status(key)['configured']:
                    problem=crew.completion_problem(key)
            elif meta.get('team_ticket'):
                with store.db() as db:
                    row=db.execute('SELECT worker_key FROM crew_reports WHERE ticket=?',(meta['team_ticket'],)).fetchone()
                if not row or row['worker_key']!=key:problem='submit a current source-linked crew-report before returning'
            else:problem='join the current fixed-crew ticket before returning'
        if problem:
            # An explicit limited handback may stop without becoming completion.
            d=evidence_directory(self.state,key,meta)
            if (d/'evidence.sqlite3').is_file():
                status=Evidence(d).status();claim=status.get('finish') or {}
                if claim.get('valid') and claim.get('kind') in {'partial','blocked'} and claim.get('limitations') and store.get(key,'finish_generation')==store.get(key,'generation'):
                    return self._legacy_stop(store,key,event,coordinator)
            handback={'status':'UNVERIFIED','reason':problem,'worker_key':key}
            store.put(key,'last_handback',handback)
            token=str(store.get(key,'generation','startup'))
            if not event.get('stop_hook_active') and store.once(key,'crew_stop_reminder',token):
                return {'decision':'block','reason':'LUNASTRA_CONTINUE: '+problem+'. Continue the same six sessions, inspect crew-state, and finish current evidence. If the host cannot continue, record an explicit partial/blocked result; do not fabricate workers or success.'}
            if meta.get('role')=='worker' and meta.get('team_ticket'):
                Team(store).returned(meta['team_ticket'],handback)
            return {'continue':False,'stopReason':'LunAstra: UNVERIFIED fixed-seven result.',
                    'systemMessage':problem+'. Work and evidence retained; no process was killed.'}
        return self._legacy_stop(store,key,event,coordinator)

    def _legacy_stop(self,store,key,event,coordinator):
        if store.get(key,'interrupted',False):return {}
        meta=store.get(key,'meta',{})
        root=Path(meta.get('assigned_workspace',meta['workspace']))
        current_generation=str(event.get('turn_id') or store.get(key,'generation','startup'))
        before=store.get(key,'source_baseline')
        after=observe(root);changed=changes(before,after) if before else []
        before=before or {'files':{},'complete':False}
        edit_attempt=store.get(key,'edited_in_turn')==current_generation
        if meta.get('crew_enabled') and meta.get('read_only') and not edit_attempt:
            # Changes by the root/other workers in a shared read-only checkout
            # are not evidence that this reader wrote them. Final snapshots bind reviews.
            changed=[]
        message=event.get('last_assistant_message') or ''
        tags=re.findall(r'(?m)^(?:LUNA_ASTRA_STATUS|LUNASTRA_STATUS)=(TESTED|ANALYSIS|PARTIAL|BLOCKED)\s*$',message)
        evidence_dir=evidence_directory(self.state,key,meta)
        status=None;problem=None;claim=None;covered=set()
        if (evidence_dir/'evidence.sqlite3').is_file():
            try:
                evidence=Evidence(evidence_dir);status=evidence.status();claim=status.get('finish')
                with evidence._db() as db:
                    task=evidence._get(db,'task',{})
                for spec in task.get('checks',[]):
                    for n in changed:
                        if any(n==d or n.startswith(d.rstrip('/')+'/') for d in spec['dependencies']+spec.get('expected_absent',[])):covered.add(n)
            except (OSError,ValueError,TypeError,KeyError, __import__('sqlite3').Error):
                problem='verification record unreadable; no success can be asserted'
        if meta.get('read_only') and changed:problem='read-only worker modified files; leader must review and restore its own changes safely'
        matching=store.get(key,'finish_generation')==current_generation
        tested=bool(claim and matching and claim['kind']=='tested' and claim.get('valid') and status and status.get('passed'))
        if tested and set(changed)-covered:
            tested=False;problem='changed files are outside declared verification dependencies'
        team=Team(store)
        team_status=team.status(key) if meta.get('role')=='root' else {'configured':False,'active':0,'complete':True,'tasks':[]}
        active_jobs=Jobs(store,key,self.package).active()
        outstanding=bool((team_status['configured'] and not team_status['complete']) or active_jobs)
        current_jobs=any(j.get('generation',current_generation)==current_generation for j in active_jobs)
        # Any observed modification requires a handback, even when the model
        # completely omits our tag. This closes the old marker-omission path.
        coding=bool(changed or edit_attempt or (claim and matching and claim.get('kind')!='analysis'))
        explicit_partial=bool(claim and matching and claim.get('valid') and claim['kind'] in {'partial','blocked'} and claim.get('limitations'))
        expected_tested='TESTED' in tags or bool(claim and matching and claim['kind']=='tested')
        bad=bool(problem or (expected_tested and not tested) or (coding and not tested and not explicit_partial) or
                 (coding and ('ANALYSIS' in tags or (claim and matching and claim['kind']=='analysis'))) or
                 (outstanding and (coding or expected_tested or current_jobs or team_status.get('generation')==current_generation) and not explicit_partial) or len(tags)>1)
        if bad:
            explanation=problem or ('delegated work is still outstanding' if outstanding else 'changed code has no current checked handback')
            handback={'at':time.time(),'status':'UNVERIFIED','reason':explanation,'changed_paths':changed}
            store.put(key,'last_handback',handback)
            if not event.get('stop_hook_active') and store.once(key,'stop_reminder',current_generation):
                return {'decision':'block','reason':'LunAstra: '+explanation+'. Complete the missing implementation/checks and finish with current evidence. If genuinely blocked, record PARTIAL/BLOCKED with the exact limitation. Do not spawn replacement teams, repeat valid checks, or stop protected jobs.'}
            # A bounded failure exit is not a certified completion. Never buy an
            # infinite retry loop by pretending repeated stop feedback is free.
            if meta.get('team_ticket'):team.returned(meta['team_ticket'],{**handback,'worker_key':key})
            if not status or not status.get('active'):coordinator.release(key)
            return {'continue':False,'stopReason':'LunAstra: UNVERIFIED; correction did not produce current evidence.',
                    'systemMessage':'LunAstra: this result is NOT verified. Incomplete work and evidence are preserved; no process was terminated.'}
        accepted='TESTED' if tested else (claim['kind'].upper() if claim and matching else 'ANALYSIS')
        if outstanding and accepted=='TESTED':accepted='PARTIAL'
        handback={'at':time.time(),'status':accepted,'changed_paths':changed,'worker_key':key,
                  'observation_complete':before.get('complete',False) and after.get('complete',False),
                  'task_hash':claim.get('task_hash') if claim else None}
        store.put(key,'last_handback',handback)
        if meta.get('team_ticket'):team.returned(meta['team_ticket'],handback)
        if not status or not status.get('active'):coordinator.release(key)
        if outstanding and accepted=='ANALYSIS':
            return {'systemMessage':'LunAstra: existing work remains outstanding; this reply is not completion of that work.'}
        if accepted in {'PARTIAL','BLOCKED'}:
            return {'systemMessage':'LunAstra: '+accepted+' — '+str(claim.get('limitations','Verification remains incomplete.'))[:500]}
        return {}

    def doctor(self):
        if not (self.state/'runtime.sqlite3').is_file():return {'version':__version__,'build':__build__,'sessions':[],'live_status':'NO_OBSERVED_EVENTS','model_parity':'NOT_MEASURED'}
        store=Store(self.state)
        with store.db() as db:rows=db.execute("SELECT scope,value FROM kv WHERE name='meta' ORDER BY scope").fetchall()
        records=[]
        for row in rows:
            meta=strict_json(row['value']);key=row['scope'];d=evidence_directory(self.state,key,meta)
            try:ev=Evidence(d).status() if (d/'evidence.sqlite3').is_file() else None
            except (OSError,ValueError,TypeError,KeyError,__import__('sqlite3').Error):ev={'passed':False,'error':'evidence unreadable'}
            team_state=Team(store).status(key) if meta.get('role')=='root' else {'complete':True}
            jobs=Jobs(store,key,self.package)
            crew_problem=Crew(store,self.package).completion_problem(key) if meta.get('crew_enabled') and meta.get('role')=='root' else None
            records.append({**meta,'emitted_characters':store.get(key,'emitted_chars',0),'evidence':ev,'check_jobs':Jobs(store,key,self.package).all(),'crew':Crew(store,self.package).summary(key) if meta.get('crew_enabled') and meta.get('role')=='root' else None,'team':self._team_summary(Team(store).status(key)) if meta.get('role')=='root' else None,
                            'handback_history':store.get(key,'last_handback'),
                            'current_tested':bool(not crew_problem and ev and ev.get('finish',{}) and ev['finish'].get('kind')=='tested' and ev['finish'].get('valid') and ev['passed'] and store.get(key,'finish_generation')==store.get(key,'generation') and team_state['complete'] and not jobs.active() and store.get(key,'last_handback',{}).get('status') not in {'UNVERIFIED','PARTIAL','BLOCKED'})})
        return {'version':__version__,'build':__build__,'sessions':records,'model_parity':'NOT_MEASURED','trust':'NOT_CHANGED_OR_CERTIFIED',
                'limit':'Hook events are observed metadata, not independent proof of model compliance or a real Codex session in a synthetic test.'}
