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
from .evidence import Evidence
from .team import Team
from .crew import Crew
from .flow import Flow
from .scan import observe, changes
from .paths import covers
from .jobs import Jobs
from .transport import tool_name, helper_command, worker_shell_input, literal_argv, literal_shell_input

from .model_gate import MAX_INPUT, EVENTS, LUNA_MODEL, is_luna, accepts_event
from .hook_policy import relevant
from .activation import APPLICABILITY, header as scope_header, scope_metadata

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
    def __init__(self,package:Path,state:Path, *, fixed_seven=False, trace_model_gate=False):
        self.fixed_seven=fixed_seven
        self.package=Path(package);self.state=Path(state)
        self.trace_model_gate=trace_model_gate
        self._state_created=False  # Task storage, not diagnostic storage.

    def _prompt(self,name):
        path=self.package/'prompts'/name
        no_symlinks(path)
        if path.stat().st_size>16000:raise HarnessError('prompt exceeds package budget')
        return path.read_text(encoding='utf-8').strip()

    def _core(self,key,role,model,generation='startup'):
        prefix=[sys.executable,str(self.package/'luna.py'),'--state',str(self.state),'--session',key]
        role_file=('FIXED_'+role.upper()+'.md') if self.fixed_seven else (role.upper()+'.md')
        role_text=self._prompt(role_file)
        if role_text.startswith(APPLICABILITY):role_text=role_text[len(APPLICABILITY):].lstrip()
        return scope_header(key,role,model,generation)+self._prompt('CORE.md')+'\n\n'+role_text+'\n\n'+(
            'LOCAL_HELPER_ARGV='+json.dumps(prefix,ensure_ascii=False,separators=(',',':'))+'\nLOCAL_HELPER_COMMAND='+helper_command(prefix)+'\n'+
            (("Fixed seven parent: use help.fixed_seven and crew-start/next/execute/review/complete. The team-* commands are retained for migration and checked integration only. " if role=="root" else "Fixed seven worker: use your own helper crew-join and crew-report; do not run parent coordination commands. ") if self.fixed_seven else "")+
            "After compaction: context --recover.")


    def _recovery_core(self, key, role, model, generation):
        if not self.fixed_seven:
            return self._core(key,role,model,generation)  # Legacy roles must not acquire a six-member obligation.
        prefix=[sys.executable,str(self.package/'luna.py'),'--state',str(self.state),'--session',key]
        return (scope_header(key,role,model,generation)+APPLICABILITY+'\n\n'+
                self._prompt('RECOVERY.md')+'\nLOCAL_HELPER_ARGV='+canonical(prefix)+
                '\nLOCAL_HELPER_COMMAND='+helper_command(prefix))


    def _module(self,store,key,name,generation):
        if store.once(key,'module:'+name,generation):return self._prompt('modules/'+name+'.md')
        return ''

    def handle(self,event):
        # Never inspect workspace, aliases or task storage before parsed model authorization.
        self._state_created=False
        if accepts_event(event) and not relevant(event):return {}
        tracked=accepts_event(event)
        try:
            output=self._handle(event)
        except Exception:
            if tracked:self._record_connection(event,None,failed=True)
            self._record_gate(event,None,failed=True)
            raise
        if tracked:self._record_connection(event,output)
        self._record_gate(event,output)
        return output

    def _record_gate(self,event,output,failed=False):
        if not self.trace_model_gate:return
        try:
            from .gate_trace import record
            record(self.state,event,output,state_created=self._state_created,failed=failed)
        except Exception:pass  # Advisory tracing must not affect task decisions.

    def _record_connection(self,event,output,failed=False):
        from .connection import record_hook
        try:record_hook(self.state,self.package,event,output,failed=failed)
        except (OSError,ValueError,TypeError,KeyError,AttributeError,__import__('sqlite3').Error):
            # A diagnostic write must not change an existing allow/deny/stop
            # decision or interrupt an otherwise successful task operation.
            print('LunAstra connection diagnostics unavailable; do not infer a verified connection.',file=sys.stderr)

    def _handle(self,event):
        if not accepts_event(event) or not relevant(event):return {}  # All untrusted/malformed/other model input is inert.
        self.package=self.package.resolve();self.state=self.state.absolute();no_symlinks(self.state)
        kind=event['hook_event_name']
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
        self._state_created=not (self.state/'runtime.sqlite3').is_file()
        store=Store(self.state)
        with store.connection():
            return self._handle_stored(event, store)

    def _handle_stored(self, event, store):
        kind = event['hook_event_name']
        alias_id=event.get('agent_id') or event.get('session_id')
        alias=store.get('__agent_alias__',alias_id) if isinstance(alias_id,str) else None
        if alias is not None and (not isinstance(alias,dict) or not all(isinstance(alias.get(n),str) for n in ('parent','key','model'))):
            raise HarnessError('invalid persisted agent alias')
        if alias and alias.get('model')!=event['model']:
            raise HarnessError('persisted worker model mismatch; do not reuse the old activation or ticket')
        if alias and event.get('session_id') in {alias['parent'],alias_id} and alias.get('model')==event['model']:
            event={**event,'session_id':alias['parent'],'agent_id':alias_id}
        key,role,root=identity(event)
        if alias and alias.get('model')==event['model'] and alias.get('key') and event['session_id']==alias['parent']:
            known=store.get(alias['key'],'meta',{})
            legitimate=set()
            for value in (known.get('workspace'),known.get('assigned_workspace')):
                if value is None:continue
                if not isinstance(value,str) or not value:raise HarnessError('invalid stored workspace')
                candidate=Path(value).absolute();no_symlinks(candidate)
                legitimate.add(candidate.resolve())
            if root in legitimate:key=alias['key']
        if kind=='SubagentStart':store.put('__agent_alias__',event['agent_id'],{'parent':event['session_id'],'key':key,'model':event['model']})
        meta=store.get(key,'meta')
        if meta is not None and not isinstance(meta,dict):raise HarnessError('invalid persisted session metadata')
        if meta and (meta.get('model')!=event['model'] or meta.get('role')!=role or meta.get('key')!=key):
            raise HarnessError('persisted activation model/role/key mismatch; preserve existing state')
        new=not meta
        self._state_created=self._state_created or new
        meta=meta or {'key':key,'role':role,'workspace':str(root),'model':event['model'],'created_at':time.time(),
                     'context_emitted':False,'helper_used':False,'actual_model_parity':'NOT_MEASURED'}
        if new and role=='root' and self.fixed_seven:meta['crew_enabled']=True
        if new and role=='worker' and self.fixed_seven:
            team=Team(store)
            with store.db() as db:
                bound=db.execute('SELECT owner FROM work WHERE agent_id=? ORDER BY rowid DESC LIMIT 1',(event.get('agent_id'),)).fetchone()
            meta['crew_enabled']=bool(store.get(bound['owner'],'meta',{}).get('crew_enabled')) if bound else True
        generation=str(event.get('turn_id') or store.get(key,'generation','startup'))
        meta.update(scope_metadata(key,role,event['model'],generation))
        meta['version']=__version__;meta['build']=__build__;meta['last_event']=kind
        meta.update(session_id=event['session_id'],agent_id=event.get('agent_id'))
        if kind=='SubagentStart':meta['native_start_observed']=True
        if role=='worker':meta['native_model_observed']=event['model']
        # Native SubagentStart.session_id is the CHILD session, not its parent.
        # The parent is bound by an observed native spawn result in Team.join.
        if role=='root':
            meta['parent_session_id']=None
        elif event['session_id'] != event.get('agent_id'):
            meta['parent_session_id']=event['session_id']  # legacy host contract
        elif meta.get('parent_session_id') == event.get('agent_id'):
            meta['parent_session_id']=None  # migrate the old self-parent record
        if meta.get('assigned_workspace'):
            root=Path(meta['assigned_workspace']).absolute();no_symlinks(root);root=root.resolve()
        if kind=='Interrupt':
            store.put(key,'interrupted',True)
            return {}
        store.put(key,'meta',meta)
        generation=str(event.get('turn_id') or store.get(key,'generation','startup'))
        store.put(key,'generation',generation)
        parts=[];emitted_core=False;tool_update=None;coordinator=Coordinator(store,root)
        if new and kind not in {'Stop','SubagentStop'}:
            # A fixed worker has no write authority until a joined assignment.
            # Readers use the root's immutable scope identity, not six whole-tree scans.
            if role=='worker' and meta.get('crew_enabled'):
                store.put(key,'source_baseline',{'files':{},'complete':False,'reason':'unjoined_read_only'})
            else:store.put(key,'source_baseline',observe(root))
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
                parts.append(Hooks(self.package,self.state,fixed_seven=bool(meta.get('crew_enabled')))._recovery_core(key,role,event['model'],generation) if restore and meta.get('context_emitted') else Hooks(self.package,self.state,fixed_seven=bool(meta.get('crew_enabled')))._core(key,role,event['model'],generation));emitted_core=True
                note=store.get(key,'note')
                if note:
                    note_text=canonical(note)
                    if len(note_text.encode('utf-8'))<=1000:
                        parts.append('Saved note (historical, recheck against current sources): '+note_text)
                    else:parts.append('A saved working note exists. Retrieve context --recover; it is historical, not current authority.')
                if restore and role=='root' and meta.get('crew_enabled'):
                    state=Crew(store,self.package).status(key)
                    if state.get('configured'):
                        compact={'phase':state['phase'],'round':state['round'],
                                 'members':[{'slot':m['slot'],'agent_id':m['agent_id']} for m in state['members']]}
                        parts.append('Fixed-seven saved state (historical, not completion): '+canonical(compact))
                    parts.append('Use crew-step for current legal actions and context --recover for the retained full contract; do not restart the team.')
        if kind=='UserPromptSubmit':
            if not emitted_core:
                parts.append(APPLICABILITY)
            prompt=event.get('prompt','')
            if role=='root' and meta.get('crew_enabled') and not prompt.startswith('LUNASTRA_CONTINUE:'):
                store.put(key,'request_hash',json_hash(prompt))
            store.put(key,'current_turn',generation)
            store.put(key,'interrupted',False)
            # Keep the last checked byte baseline. A new prompt is not a new
            # certificate and must not hide an unverified earlier modification.
            if store.get(key,'source_baseline') is None:store.put(key,'source_baseline',observe(root))
            if isinstance(prompt,str) and re.search(r'\.(py|ts|js|rs|go)\b|\uCF54\uB4DC|\uCF54\uB529|\uBC84\uADF8|\uAD6C\uD604|\uC624\uB958|\uD14C\uC2A4\uD2B8|\b(fix|implement|debug|refactor|test)\b',prompt,re.I):
                # A bounded on-demand map, not a full source dump or a new model call.
                # Code maps are explicitly requested through context/risk, not
                # rebuilt on every coding prompt or mutation.
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
                    if meta.get('crew_enabled'):Crew(store,self.package).pre_dispatch(key,uid,payload,event['model'],name)
                    else:Team(store).pre_followup(key,payload)
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if name=='wait_agent' and role=='root' and meta.get('crew_enabled'):
                try: Flow(store,self.package).pre_wait(key,uid,payload)
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if name=='list_agents' and role=='root' and meta.get('crew_enabled'):
                try:
                    from .native_flow import NativeFlow
                    NativeFlow(store,Crew(store,self.package)).pre(key,uid,name,payload)
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if name in {'send_message','interrupt_agent'} and meta.get('crew_enabled'):
                return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'Use the current fixed-crew dispatch/checked handback; no side-channel task or interruption.'})
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
                        field='cmd' if name=='exec_command' else 'command'
                        command=payload.get(field) if isinstance(payload,dict) else None
                        prefix=[sys.executable,str(self.package/'luna.py'),'--state',str(self.state),'--session',key]
                        argv=literal_argv(command)
                        own_helper=argv[:len(prefix)]==prefix
                        if not own_helper:
                            raise HarnessError('Fixed-seven shell: use this session helper for registered checks/research; use scoped edit tools for source writes. Raw shell write targets cannot be verified before execution.')
                        if phase!='EXECUTE':
                            rest=argv[len(prefix):]
                            if not own_helper:raise HarnessError('planning/review is read-only; use the local helper read/context and crew commands')
                            if rest[:1] in (['--input-json'],['--input-ref']):rest=rest[2:]
                            if not rest or rest[0] not in {'help','input-append','read','read-bytes','read-source','resources','context','risk','status','note','trace','jobs','begin','run','run-all','start-check','finish','crew-step','research-status','research-read','research-recover','research-pause','research-resume','crew-start','crew-capacity','crew-revise','crew-continue','crew-next','crew-state','crew-drive','crew-reconcile','crew-retry','crew-recover','crew-report-read','crew-execute','crew-review','crew-repair','crew-complete'}:raise HarnessError('unsupported helper during planning/review')
                        if own_helper:
                            rewrite=literal_shell_input(command,prefix)
                            if rewrite is not None:tool_update={**payload,field:rewrite['command']}
                except HarnessError as exc:
                    return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':str(exc)})
            if role=='worker' and meta.get('crew_enabled') and name in {'send_input','followup_task','resume_agent','close_agent','wait_agent','list_agents'}:
                return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'Only the root dispatches the six crew members.'})
            native_unjoined=(role=='worker' and event['session_id']==event.get('agent_id') and not meta.get('team_ticket'))
            if native_unjoined and paths:
                return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'deny','permissionDecisionReason':'Join the assigned LunAstra ticket before editing; the child session ID is not parent identity.'})
            if role=='worker' and name in {'Bash','exec_command','shell_command'} and (meta.get('team_ticket') or native_unjoined):
                prefix=[sys.executable,str(self.package/'luna.py'),'--state',str(self.state),'--session',key]
                try:
                    field='command' if name in {'Bash','shell_command'} else 'cmd'
                    if not isinstance(payload,dict) or not isinstance(payload.get(field),str):
                        raise HarnessError('native '+name+' hook requires '+field)
                    rewrite=worker_shell_input(payload[field],prefix,joined=bool(meta.get('team_ticket')),read_only=bool(meta.get('read_only')))
                    if rewrite is not None:tool_update={**payload,field:rewrite['command']}
                except HarnessError as exc:
                    message=str(exc)+'. Your worker LOCAL_HELPER_COMMAND='+helper_command(prefix)+'. '
                    message+=('Join your current ticket first with crew-join; do not use the inherited parent helper. ' if not meta.get('team_ticket') else '')
                    message+=('This assignment is read-only: use read/context/risk and --input-json <report JSON> crew-report. ' if meta.get('read_only') else 'For an assigned implementation use worker-exec --argv-json <JSON array> with an explicit executable. ')
                    message+='Use --input-json <JSON> before the intended helper instead of a shell pipe.'
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
                    else:tool_update={**payload,**(tool_update or {}),field:str(root)}

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
                store.put(key,'changed-path-hints',sorted(set(store.get(key,'changed-path-hints',[]))|set(normalized_paths)))
                store.put(key,'edited_in_turn',generation)
            if role=='root' and meta.get('crew_enabled') and name in {'spawn_agent','send_input','followup_task'}:
                from .native_receipts import remember
                remember(store,key,event)
            store.event(key,'pre:'+uid,'tool_start',{'tool':tool,'input_sha256':json_hash(payload),'edit_paths':paths,
                                                     'outcome':'RUNNING','turn':generation})
        elif kind=='PostToolUse':
            uid=event.get('tool_use_id');tool=str(event.get('tool_name',''));payload=event.get('tool_input')
            if not isinstance(uid,str) or not uid:raise HarnessError('missing tool_use_id')
            if tool_name(tool) in {'spawn_agent','send_input','followup_task'} and role=='root':
                if meta.get('crew_enabled'):Crew(store,self.package).post_dispatch(key,uid,event.get('tool_response'))
                elif tool_name(tool)=='spawn_agent':Team(store).post_spawn(key,uid,event.get('tool_response'))
            if tool_name(tool)=='wait_agent' and role=='root':
                if meta.get('crew_enabled'):Flow(store,self.package).post_wait(key,uid,event.get('tool_response'))
                else:Team(store).observed_statuses(key,event.get('tool_response'))
            if tool_name(tool)=='list_agents' and role=='root' and meta.get('crew_enabled'):
                from .native_flow import NativeFlow
                NativeFlow(store,Crew(store,self.package)).post(key,uid,'list_agents',event.get('tool_response'))
            if role=='root' and meta.get('crew_enabled') and tool_name(tool) in {'spawn_agent','send_input','followup_task','wait_agent','list_agents'}:
                parts.append('LunAstra next action (not task completion): '+canonical(Flow(store,self.package).drive(key)))
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
            return self._scoped_feedback(store,key,self._stop(store,key,event,coordinator))
        return self._output(store,key,kind,parts,emitted_core,{'permissionDecision':'allow','updatedInput':tool_update} if tool_update is not None else None)

    def _output(self,store,key,kind,parts,emitted_core=False,extra=None):
        content='\n\n'.join(p for p in parts if p)
        specific={'hookEventName':kind,**(extra or {})}
        if content:
            meta=store.get(key,'meta',{})
            if not content.startswith('LUNASTRA_ACTIVATION_ID='):
                content=scope_header(key,meta['role'],meta['model'],store.get(key,'generation','startup'))+APPLICABILITY+'\n\n'+content
            if len(content.encode('utf-8'))>12000:
                content=self._recovery_core(key,meta['role'],meta['model'],store.get(key,'generation','startup'))
                content+='\nFull protocol/context retained; use context --recover before acting. No omitted context is certified as read.'
                if len(content.encode('utf-8'))>12000:
                    raise HarnessError('helper path exceeds bounded hook recovery; use a shorter install path',code='HOOK_CONTEXT_TOO_LARGE')
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

    def _scoped_feedback(self,store,key,output):
        if not output:return output
        meta=store.get(key,'meta',{})
        scope=scope_header(key,meta['role'],meta['model'],store.get(key,'generation','startup'))+APPLICABILITY
        result=dict(output)
        for field in ('reason','systemMessage','stopReason'):
            text=result.get(field)
            if not isinstance(text,str) or not text:continue
            # Retain routing recognition; lifetime precedes any renewed obligation.
            marker='LUNASTRA_CONTINUE:'
            result[field]=(marker+' '+scope+'\n'+text[len(marker):].lstrip()) if text.startswith(marker) else scope+'\n'+text
        return result

    @staticmethod
    def _team_summary(status):
        return {'configured':status['configured'],'active':status['active'],'complete':status['complete'],
                'tasks':[{'id':r['id'],'state':r['state']} for r in status['tasks']]}

    def _stop(self,store,key,event,coordinator):
        meta=store.get(key,'meta',{})
        if store.get(key,'interrupted',False):return {}
        coordinator.release_finished_edits(key)
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
                    # Merely waiting for still-running native work is not an
                    # external blocker. Genuine blocked state remains explicit.
                    flow=Flow(store,self.package)
                    recoverable=(meta.get('role')=='root' and flow.drive(key)['action'] in {'WAIT','OBSERVE_NATIVE','DISPATCH','RECOVER','REASSESS','RESEARCH','READ_REPORTS','ADVANCE','INTEGRATE','ACCEPT'})
                    if not recoverable:return self._legacy_stop(store,key,event,coordinator)
            handback={'status':'UNVERIFIED','reason':problem,'worker_key':key}
            store.put(key,'last_handback',handback)
            correction=Flow(store,self.package).correction(key,meta,problem)
            if correction:return correction
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
        edit_attempt=store.get(key,'edited_in_turn')==current_generation
        reader=meta.get('crew_enabled') and meta.get('read_only') and not edit_attempt
        # Only read-only crew handbacks skip this observation; their final
        # references/snapshots are still byte-validated by the crew engine.
        after=({'files':{},'complete':False,'reason':'read_only_shared_scope'} if reader else observe(root,full=True) if meta.get('crew_enabled') else observe(root))
        changed=changes(before,after) if before else []
        before=before or {'files':{},'complete':False}
        if reader:
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
                        if any(covers(root,d,n) for d in spec['dependencies']+spec.get('expected_absent',[])):covered.add(n)
            except (OSError,ValueError,TypeError,KeyError, __import__('sqlite3').Error):
                problem='verification record unreadable; no success can be asserted'
        if meta.get('read_only') and changed:problem='read-only worker modified files; leader must review and restore its own changes safely'
        matching=store.get(key,'finish_generation')==current_generation
        tested=bool(claim and matching and claim['kind']=='tested' and claim.get('valid') and status and status.get('passed'))
        if tested and not (meta.get('crew_enabled') and meta.get('read_only') and not edit_attempt):
            from .scan import completeness_problem
            coverage_problem=completeness_problem(before,after)
            if coverage_problem:tested=False;problem=coverage_problem
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
            if meta.get('crew_enabled'):
                correction=Flow(store,self.package).correction(key,meta,explanation)
                if correction:return correction
            elif not event.get('stop_hook_active') and store.once(key,'stop_reminder',current_generation):
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
        if not outstanding and accepted in {'TESTED','ANALYSIS'} and not reader:
            store.put(key,'source_baseline',after)
            store.put(key,'changed-path-hints',[])
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
