#!/usr/bin/env python3
"""LunAstra installer. Default: read-only plan. Use --json for machine output."""
from __future__ import annotations
import argparse
import os
import math
import shutil
import shlex
import sqlite3
import sys
from pathlib import Path
if sys.version_info < (3,10):
    print('LunAstra requires Python 3.10 or newer. Nothing was installed.',file=sys.stderr)
    raise SystemExit(1)
from luna_astra import __version__, __build__
from luna_astra.install import Installer, payload
from luna_astra.connection import connection_status, activation_layers
from luna_astra.model_gate import RESERVE_POLICY
from luna_astra.util import canonical, HarnessError
from luna_astra.compatibility import inspect_host, configuration_hints
from luna_astra.removal import CONFIRMATION, purge, purge_plan

def runtime_configuration(home):
    return {**configuration_hints(home), 'codex_cli_found': bool(shutil.which('codex')),
            'git_found': bool(shutil.which('git'))}


def human(command,r):
    print('LunAstra '+__version__)
    if command=='plan':
        print('Installation plan: '+('add or update LunAstra hooks' if r['needs_hook_change'] else 'no hook changes required'))
        print('Release location: '+r['release'])
        print('Account settings, model selection, reasoning effort, permissions, and running tasks are not changed.')
        home=r.get('codex_home')
        if home:
            quoted=("'"+home.replace("'","''")+"'") if os.name=='nt' else shlex.quote(home)
            print('To apply: '+('py -3 install.py apply' if os.name=='nt' else 'python3 install.py apply')+' --codex-home '+quoted)
            print('This command targets the same inspected home; use '+('PowerShell.' if os.name=='nt' else 'a POSIX shell.'))
        else:print('Inspected home is UNKNOWN; no apply command was inferred.')
    elif command=='apply':
        print('Installation: INSTALLED (files and hook definitions).')
        print('Connection: '+r.get('runtime',{}).get('status','WAITING_FOR_LUNA')+'. Installation does not start a model.')
        print('Installed helper self-check: passed (local startup only).')
        print('Release fingerprint: '+r['payload_sha256'][:16])
        print('Next: open /hooks in Codex, review the LunAstra definitions, and approve them.')
        print('Use a new Luna conversation after the hooks are active. Existing running tasks are not restarted.')
    elif command=='doctor':
        print('Release fingerprint: '+r['payload_sha256'][:16])
        print('Installed payload: '+('match' if r['installed_payload_matches_package'] else 'missing or mismatched'))
        print('Hook definitions: '+('match' if r['hook_definition_matches_package'] else 'missing or mismatched'))
        runtime=r['runtime']; sessions=runtime.get('sessions',[])
        print('Connection: '+runtime.get('status','NOT_CHECKED'))
        print('Current-release Luna sessions observed: '+str(runtime.get('session_count',len(sessions))))
        print('Matched tool-call cycles observed: '+str(runtime.get('tool_cycle_sessions',0)))
        print('Worker sessions observed: '+str(runtime.get('worker_sessions',0))+' (not a complete delegation test)')
        if runtime.get('last_observed_at') is not None:
            from datetime import datetime, timezone
            print('Last event (UTC): '+datetime.fromtimestamp(runtime['last_observed_at'],timezone.utc).isoformat())
        if runtime.get('status') in {'WAITING_FOR_LUNA','WAITING_FOR_CURRENT_RELEASE','EVENTS_WITHOUT_KERNEL'}:
            print('Next: review /hooks in the app you actually use, start a new Luna conversation, and ask it to inspect a small file.')
            print('No update is required solely because a separate PATH CLI has an older version.')
        elif runtime.get('status')=='DIAGNOSTICS_UNREADABLE':
            print('Connection records are unreadable. Preserve local data and inspect the Codex hook error; do not purge or reinstall to hide it.')
        elif runtime.get('status')=='HOOK_ERRORS_OBSERVED':
            print('A hook error was observed. Review the error in Codex before treating the connection as healthy.')
        if runtime.get('history_truncated'):print('Only the latest 200 session records are summarized.')
        print('Observed events are historical local records, not proof of a currently running or fully verified host.')
        config_state=r['configuration'].get('config_parse')
        if config_state=='NOT_INSPECTED_PYTHON_310':print('Warning: Python 3.10 cannot inspect TOML settings here. Confirm hook and agent availability in Codex.')
        elif config_state=='UNREADABLE':print('Warning: Codex configuration could not be parsed. Hook and agent availability are unconfirmed.')
        if r['configuration'].get('hooks_explicitly_disabled'):print('Warning: Codex hooks are explicitly disabled in the inspected configuration.')
        if r['configuration']['native_agent_setting']=='EXPLICITLY_DISABLED':print('Warning: native Codex agents are explicitly disabled in the inspected configuration.')
        if not r['configuration']['git_found']:print('Warning: Git was not found; implementation work cannot use isolated worktrees and will fall back to a single writer.')
        layers=r.get('activation_layers',{})
        print('HOOKS_REGISTERED: '+str(r.get('registration',{}).get('HOOKS_REGISTERED','UNKNOWN')))
        print('LUNA_EVENT_ACCEPTED: '+str(layers.get('LUNA_EVENT_ACCEPTED','UNKNOWN')))
        print('KERNEL_EMITTED: '+str(layers.get('KERNEL_EMITTED','UNKNOWN')))
        print('CREW_ACTIVE last recorded: '+str(layers.get('CREW_ACTIVE_LAST_RECORDED',0))+'; current liveness: NOT_MEASURED')
        print('Handler-bound Codex home: '+str(r.get('handler_bound_home') or 'UNKNOWN'))
        print('Actual Desktop/IDE effective CODEX_HOME: UNKNOWN (not inferred from PATH CLI or the handler path).')
        print('Bare gpt-reserve: UNKNOWN / LunAstra inactive until a reliable Luna discriminator is proven.')
        print('Past injected context is not retracted by unregister/model switch. Use a new conversation for clean non-Luna work.')
        print('Model-gate trace: '+r.get('model_gate_trace',{}).get('status','OFF'))
        print('Luna/Astra task quality and account-usage comparison: not measured')
    elif command in {'gate-trace','gate-stop','gate-report'}:
        if command=='gate-report':
            print('Privacy-safe diagnostic report: '+r['report_path'])
            print('Observed events: '+str(r['events_recorded']))
        else:
            print('Model-gate trace: '+('ARMED' if r.get('armed') else 'OFF'))
            if r.get('armed'):
                print('Automatic limit: '+str(r['max_events'])+' events; expiry (Unix): '+str(r['expires_at']))
                print('Try a new Luna and a new Astra conversation in your actual host, then run MODEL_GATE_REPORT.cmd.')
        print('No prompt, command body, file content or credentials are recorded. No model is launched.')
        print('Hook input observations do not prove Desktop routing or same-conversation model compliance.')
    elif command in {'purge-plan', 'purge'}:
        print('Owned data directory: '+r['target'])
        print('Files: '+str(r['files'])+'; bytes: '+str(r['bytes']))
        if r.get('removed'):
            print(r.get('note','Owned local data removed.'))
        else:
            print('No data was deleted.')
            for blocker in r.get('blockers',[]): print('Blocked: '+blocker)
            print('Close Codex sessions and checks, review the target, then use PURGE.cmd or the documented explicit confirmation command.')
    else:
        print('LunAstra hook registrations were removed.' if r['changed'] else 'No owned LunAstra hook registrations were found.')
        print('Future owned LunAstra hook injections are disabled; unrelated hook sources were not changed.')
        print('Existing conversations may still contain previously injected LunAstra context: NOT RETRACTED.')
        print('For a clean non-Luna run, start a new conversation. Switching a model may retain prior context.')
        print('기존 대화에 주입된 지시는 소급 삭제되지 않습니다. 깨끗한 비-Luna 작업은 새 대화에서 시작하세요.')
        print('Installed releases, runtime records, backups, unrelated hooks, project files, and running tasks were preserved.')

def main(argv=None):
    # Keep UTF-8 diagnostics and JSON valid even when stdout is redirected.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['plan','apply','doctor','unregister','purge-plan','purge','gate-trace','gate-stop','gate-report'],nargs='?',default='plan')
    home_args=p.add_mutually_exclusive_group()
    home_args.add_argument('--codex-home',type=Path,default=None)
    home_args.add_argument('--isolated',action='store_true',help='Target ~/.codex-lunastra only; does not launch or reroute Desktop/IDE')
    p.add_argument('--trace-model-gate',action='store_true',help='doctor: explicitly arm bounded model-gate diagnostics, no registration')
    p.add_argument('--trace-seconds',type=int,default=300)
    p.add_argument('--trace-events',type=int,default=128)
    p.add_argument('--json',action='store_true')
    p.add_argument('--codex-bin',help='Optional CLI path for an advisory version probe; it is not assumed to be the desktop/IDE engine')
    p.add_argument('--require-observed',action='store_true',help='doctor: return 3 until this payload has emitted its kernel and observed a matched tool cycle')
    p.add_argument('--since',type=float,default=0.0,help='doctor: restrict observations to this Unix timestamp or later')
    p.add_argument('--confirm',default='',help='Data removal requires DELETE-LUNASTRA-DATA')
    p.add_argument('--confirm-idle',action='store_true',help='Confirm all Codex sessions and local checks are closed')
    p.add_argument('--include-workspaces',action='store_true',help='Also delete owned worktree copies after exporting needed work')
    p.add_argument('--interactive',action='store_true',help='Prompt for explicit purge confirmation')
    a=p.parse_args(argv);root=Path(__file__).resolve().parent
    a.codex_home=a.codex_home or (Path.home()/'.codex-lunastra' if a.isolated else Path(os.environ.get('CODEX_HOME') or str(Path.home()/'.codex')))
    try:
        if not math.isfinite(a.since) or a.since<0:raise HarnessError('--since must be a finite nonnegative timestamp')
        if a.command!='doctor' and (a.require_observed or a.since):raise HarnessError('--require-observed and --since are only for doctor')
        if a.trace_model_gate and a.command!='doctor':raise HarnessError('--trace-model-gate is only for doctor')
        if not (a.command=='gate-trace' or (a.command=='doctor' and a.trace_model_gate)) and (a.trace_seconds!=300 or a.trace_events!=128):raise HarnessError('trace limits apply only to gate-trace or doctor --trace-model-gate')
        installer=Installer(root,a.codex_home)
        from luna_astra import gate_trace
        state=a.codex_home/'luna-astra'/'state-v4'
        if a.trace_model_gate or a.command=='gate-trace':
            plan=installer.plan()
            if plan['needs_hook_change'] or not Path(plan['release']).is_dir() or payload(Path(plan['release']))!=plan['payload_files']:
                raise HarnessError('Register this build yourself before starting diagnostics; no hook registration was changed.')
            gate_trace.enable(state,a.trace_seconds,a.trace_events)
        host = inspect_host(a.codex_bin) if a.command in {'plan','apply','doctor'} else None
        if a.command=='apply':
            # PATH and even an explicitly selected CLI are only observations.
            # Profiles, desktop engines and managed settings can differ.
            result=installer.apply()
            result['configuration']=runtime_configuration(a.codex_home)
            result['runtime']=connection_status(Path(result['state']),Path(result['release']))
        elif a.command=='purge-plan': result=purge_plan(installer,include_workspaces=a.include_workspaces)
        elif a.command=='purge':
            if a.interactive:
                if a.json or not sys.stdin.isatty(): raise HarnessError('Interactive removal requires a terminal without --json.')
                preview=purge_plan(installer,include_workspaces=a.include_workspaces)
                human('purge-plan',preview)
                if preview['workspaces'] and not a.include_workspaces:
                    print('Worktree copies exist. Export needed changes and use the explicit command in docs/REMOVAL.md.')
                    return 2
                if preview['blockers']: raise HarnessError('; '.join(preview['blockers']))
                a.confirm_idle=input('Type CLOSED after closing ALL Codex sessions and local checks: ').strip()=='CLOSED'
                a.confirm=input('Type '+CONFIRMATION+' to permanently remove the listed local data: ').strip()
            result=purge(installer,confirm=a.confirm,confirm_idle=a.confirm_idle,include_workspaces=a.include_workspaces)
        elif a.command=='gate-trace':result=gate_trace.status(state)
        elif a.command=='gate-stop':result=gate_trace.disable(state)
        elif a.command=='gate-report':result=gate_trace.export_report(state)
        elif a.command=='unregister':
            result=installer.remove()
            result.update(future_owned_injections='DISABLED',existing_context='NOT_RETRACTED',clean_non_luna='NEW_CONVERSATION_REQUIRED')
            try:gate_trace.disable(state)
            except (OSError,ValueError,sqlite3.Error):result['trace_stop']='UNCONFIRMED; finite capture expiry remains in effect'
        elif a.command=='doctor':
            plan=installer.plan()
            result={'version':__version__,'build':__build__,
                    'hook_definition_matches_package':not plan['needs_hook_change'],
                    'installed_payload_matches_package':Path(plan['release']).is_dir() and payload(Path(plan['release']))==plan['payload_files'],
                    'runtime':connection_status(Path(plan['state']),Path(plan['release']),since=a.since),
                    'configuration':runtime_configuration(a.codex_home),
                    'payload_sha256':plan['payload_sha256'],
                    'trust':'Review definitions with native /hooks; never bypass trust.',
                    'model_parity':'NOT_MEASURED','user_windows_runtime':'NOT_PROVEN_BY_LOCAL_TESTS'}
        else:result=installer.plan()
        if a.command=='doctor':
            result['registration']=installer.registration_status()
            result['activation_layers']=activation_layers(state,Path(plan['release']),result['runtime'])
            try:result['model_gate_trace']=gate_trace.status(state)
            except (OSError,ValueError,TypeError,sqlite3.Error):result['model_gate_trace']={'status':'UNREADABLE','live_host_verified':False}
            result.update(handler_bound_home=str(installer.home),reserve_policy=RESERVE_POLICY,existing_context='NOT_RETRACTED')
        result['home_mode']='ISOLATED_TARGET_ONLY_HOST_ROUTING_UNVERIFIED' if a.isolated else 'EXPLICIT_OR_DEFAULT_TARGET'
        if host is not None: result['host']=host
        print(canonical(result)) if a.json else human(a.command,result)
        if not a.json and host is not None:
            print('CLI probe (advisory only): '+str(host.get('version') or 'not confirmed')+' ['+host['status']+']')
            print('CLI path: '+str(host.get('executable') or 'not found'))
            print('This CLI is not assumed to be the engine used by your desktop or IDE.')
            print(host['message'])
            print('Codex settings directory: '+str(installer.home))
            if a.command=='apply' and result['configuration'].get('hooks_explicitly_disabled'):
                print('Warning: root config disables hooks. A profile may override it; review the effective setting in your active Codex host.')
        if a.command=='doctor' and not (result['hook_definition_matches_package'] and result['installed_payload_matches_package']):return 2
        if a.command=='doctor' and result['runtime']['status'] in {'DIAGNOSTICS_UNREADABLE','HOOK_ERRORS_OBSERVED'}:return 2
        if a.command=='doctor' and a.require_observed and result['runtime']['status']!='TOOL_CYCLE_OBSERVED':return 3
        return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError,sqlite3.Error, EOFError) as exc:
        if a.json:print(canonical({'error':str(exc),'main_model_changed':False}),file=sys.stderr)
        else:
            print('Operation failed: '+str(exc),file=sys.stderr)
            if a.command=='doctor':
                print('The diagnostic could not complete. It did not modify settings. Preserve the files named above and consult docs/TROUBLESHOOTING.md.',file=sys.stderr)
            else:
                print('Preserve existing files. Read the error above; CHECK.cmd reports installation and connection separately.',file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
