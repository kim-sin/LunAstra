"""Installer provenance and current-payload observation regressions. No model calls."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from luna_astra.compatibility import inspect_host, version_status
from luna_astra.connection import connection_status, record_hook, release_identity
from luna_astra.hooks import Hooks
from luna_astra.install import Installer, payload
from luna_astra.store import Store
from luna_astra.util import HarnessError, load_json, write_json

ROOT = Path(__file__).resolve().parents[1]


def installer_module():
    spec=importlib.util.spec_from_file_location('lunastra_test_installer',ROOT/'install.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def snapshot(directory):
    return {p.relative_to(directory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


class AdvisoryInstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name); self.home=self.base/'home'
        self.module=installer_module()

    def invoke(self,*args,host=None):
        out,err=io.StringIO(),io.StringIO()
        if host is None:host={'status':'UNREVIEWED','version':'0.153.4','executable':'/fixture/old-cli','message':'Advisory CLI fixture'}
        with patch.object(self.module,'inspect_host',return_value=host),redirect_stdout(out),redirect_stderr(err):
            code=self.module.main([*args,'--codex-home',str(self.home)])
        return code,out.getvalue(),err.getvalue()

    def test_older_cli_installs_once_without_update_instruction(self):
        code,out,err=self.invoke('apply')
        self.assertEqual(code,0,err)
        self.assertIn('INSTALLED',out); self.assertIn('WAITING_FOR_LUNA',out)
        self.assertIn('advisory only',out); self.assertIn('/fixture/old-cli',out)
        self.assertNotIn('Update the host',out+err)
        self.assertEqual(load_json(self.home/'luna-astra/installation.json')['local_helper_startup'],'PASS')

    def test_no_cli_desktop_install_allowed(self):
        code,out,err=self.invoke('apply','--json',host={'status':'UNKNOWN','message':'No CLI'})
        self.assertEqual(code,0,err)
        self.assertEqual(json.loads(out)['activation'],'INSTALLED_NOT_LIVE_VERIFIED')

    def test_failed_cli_probe_does_not_block_installation(self):
        with patch('luna_astra.compatibility.subprocess.run',side_effect=OSError('missing CLI')):
            host=inspect_host('/fixture/codex')
        self.assertEqual(host['status'],'UNKNOWN')
        self.assertEqual(self.invoke('apply','--json',host=host)[0],0)

    def test_oversized_or_nonstring_version_output_is_unknown(self):
        for value in (None, 'codex-cli '+('9'*5000)+'.0.0'):
            with self.subTest(value_type=type(value).__name__):
                self.assertEqual(version_status(value)['status'],'UNKNOWN')

    def test_oversized_probe_output_still_allows_install(self):
        with patch('luna_astra.compatibility.subprocess.run',return_value=subprocess.CompletedProcess([],0,'codex-cli '+('9'*5000)+'.0.0','')):
            host=inspect_host('/fixture/codex')
        self.assertEqual(host['status'],'UNKNOWN')
        self.assertEqual(self.invoke('apply','--json',host=host)[0],0)

    def test_old_version_still_not_accepted_as_live_proof(self):
        self.invoke('apply')
        code,out,_=self.invoke('doctor','--json','--require-observed')
        self.assertEqual(code,3)
        self.assertFalse(json.loads(out)['runtime']['live_verified'])

    def test_root_disabled_setting_is_an_advisory_not_effective_profile(self):
        self.home.mkdir()
        original=b'[features]\nhooks = false\n[profiles.work.features]\nhooks = true\n'
        (self.home/'config.toml').write_bytes(original)
        code,out,err=self.invoke('apply')
        self.assertEqual(code,0,err)
        self.assertEqual((self.home/'config.toml').read_bytes(),original)
        self.assertEqual(self.invoke('doctor','--json')[0],0)
        if sys.version_info>=(3,11):self.assertIn('A profile may override',out)

    def test_plan_does_not_create_home(self):
        self.assertEqual(self.invoke('plan','--json')[0],0)
        self.assertFalse(self.home.exists())

    def test_missing_installation_doctor_does_not_create_home(self):
        code,out,_=self.invoke('doctor','--json')
        self.assertEqual(code,2); self.assertFalse(self.home.exists())
        self.assertFalse(json.loads(out)['installed_payload_matches_package'])

    def test_doctor_is_read_only_after_observation(self):
        receipt=Installer(ROOT,self.home).apply()
        ws=self.base/'project';ws.mkdir()
        Hooks(Path(receipt['release']),Path(receipt['state'])).handle(dict(
            hook_event_name='SessionStart',session_id='parent',model='gpt-5.6-luna',cwd=str(ws)))
        before=snapshot(self.home)
        code,out,err=self.invoke('doctor','--json')
        self.assertEqual(code,0,err)
        self.assertEqual(json.loads(out)['runtime']['status'],'LUNA_EVENTS_OBSERVED')
        self.assertEqual(snapshot(self.home),before)

    def test_malformed_hooks_error_does_not_send_check_back_to_itself(self):
        self.home.mkdir(); (self.home/'hooks.json').write_text('{')
        code,out,err=self.invoke('doctor')
        self.assertEqual(code,1);self.assertNotIn('run CHECK.cmd',err)
        self.assertIn('did not modify settings',err)
        self.assertEqual((self.home/'hooks.json').read_text(),'{')

    def test_helper_startup_failure_leaves_existing_hooks_unchanged(self):
        self.home.mkdir(); original=b'{"hooks":{}}\n';(self.home/'hooks.json').write_bytes(original)
        inst=Installer(ROOT,self.home)
        with patch('luna_astra.install.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','fixture failure')):
            with self.assertRaisesRegex(HarnessError,'could not start'):inst.apply()
        self.assertEqual((self.home/'hooks.json').read_bytes(),original)
        self.assertFalse((self.home/'luna-astra/installation.json').exists())

    def test_helper_startup_timeout_leaves_new_hooks_absent(self):
        inst=Installer(ROOT,self.home)
        with patch('luna_astra.install.subprocess.run',side_effect=subprocess.TimeoutExpired('fixture',10)):
            with self.assertRaises(HarnessError):inst.apply()
        self.assertFalse((self.home/'hooks.json').exists())
        self.assertFalse((self.home/'luna-astra/install.lock').exists())

    def test_invalid_observation_options_fail_without_writes(self):
        for args in [('apply','--require-observed'),('doctor','--since','nan'),('doctor','--since','-1')]:
            with self.subTest(args=args):self.assertEqual(self.invoke(*args,'--json')[0],1)
        self.assertFalse(self.home.exists())

    def test_metadata_and_hooks_protected_during_same_version_update(self):
        old=Installer(ROOT,self.home).apply()
        state=Path(old['state']);Store(state).put('fixture','note',{'facts':['keep']})
        for name in ('config.toml','auth.json','AGENTS.md'):(self.home/name).write_text('keep')
        original={name:(self.home/name).read_bytes() for name in ('config.toml','auth.json','AGENTS.md')}
        self.assertEqual(self.invoke('apply','--json')[0],0)
        self.assertEqual(Store(state).get('fixture','note'),{'facts':['keep']})
        self.assertEqual(original,{name:(self.home/name).read_bytes() for name in original})

    def test_empty_codex_home_environment_uses_normal_default(self):
        with patch.dict(os.environ,{'CODEX_HOME':''}),patch.object(self.module.Path,'home',return_value=self.base),redirect_stdout(io.StringIO()):
            self.assertEqual(self.module.main(['plan','--json']),0)
        self.assertFalse((self.base/'.codex').exists())

    def test_runtime_directory_symlink_refused_before_hook_changes(self):
        self.home.mkdir();(self.home/'luna-astra').mkdir()
        external=self.base/'external';external.mkdir();(external/'keep').write_text('keep')
        (self.home/'luna-astra/state-v4').symlink_to(external,target_is_directory=True)
        with self.assertRaises(HarnessError):Installer(ROOT,self.home).apply()
        self.assertFalse((self.home/'hooks.json').exists())
        self.assertEqual((external/'keep').read_text(),'keep')

    def test_windows_wrappers_probe_before_single_operation(self):
        for name,command in [('INSTALL.cmd','apply'),('CHECK.cmd','doctor'),('UNREGISTER.cmd','unregister'),('PURGE.cmd','purge --interactive')]:
            raw=(ROOT/name).read_bytes();text=raw.decode('ascii')
            self.assertNotIn(b'\n',raw.replace(b'\r\n',b''))
            self.assertIn('DisableDelayedExpansion',text)
            self.assertIn('sys.version_info >= (3,10)',text)
            self.assertIn('goto try_python',text)
            self.assertIn('py -3 install.py '+command+'\r\ngoto done',text)
            self.assertIn('set "RESULT=%ERRORLEVEL%"',text)


class ConnectionObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.state=self.base/'state';self.ws=self.base/'project';self.ws.mkdir()
        self.event=dict(hook_event_name='SessionStart',session_id='parent',model='gpt-5.6-luna',cwd=str(self.ws),turn_id='turn-a')
        self.hooks=Hooks(ROOT,self.state)

    def start(self):return self.hooks.handle(self.event)
    def status(self,**kwargs):return connection_status(self.state,ROOT,**kwargs)
    def tool(self,kind='PreToolUse',uid='one',**kwargs):
        return {**self.event,'hook_event_name':kind,'tool_name':'Bash','tool_use_id':uid,
                'tool_input':{'command':'echo fixture'},'tool_response':{'exit_code':0},**kwargs}

    def test_no_database_or_directories_created_by_check(self):
        self.assertEqual(self.status()['status'],'WAITING_FOR_LUNA')
        self.assertFalse(self.state.exists())

    def test_non_luna_does_not_create_observations(self):
        self.hooks.handle({**self.event,'model':'gpt-6-astra'})
        self.assertFalse(self.state.exists())

    def test_kernel_is_not_full_tool_cycle(self):
        self.start(); r=self.status()
        self.assertEqual(r['status'],'LUNA_EVENTS_OBSERVED');self.assertFalse(r['live_verified'])
        self.assertEqual(r['tool_cycle_sessions'],0)

    def test_matched_cycle_recorded(self):
        self.start();self.hooks.handle(self.tool());self.hooks.handle(self.tool('PostToolUse'))
        self.assertEqual(self.status()['status'],'TOOL_CYCLE_OBSERVED')

    def test_unmatched_post_does_not_certify_cycle(self):
        self.start();self.hooks.handle(self.tool('PostToolUse'))
        self.assertEqual(self.status()['tool_cycle_sessions'],0)

    def test_different_call_ids_do_not_match(self):
        self.start();self.hooks.handle(self.tool());self.hooks.handle(self.tool('PostToolUse',uid='different'))
        self.assertEqual(self.status()['tool_cycle_sessions'],0)

    def test_different_turns_do_not_match(self):
        self.start();self.hooks.handle(self.tool());self.hooks.handle(self.tool('PostToolUse',turn_id='other'))
        self.assertEqual(self.status()['tool_cycle_sessions'],0)

    def test_failed_hook_does_not_reuse_old_success(self):
        self.start();self.hooks.handle(self.tool());self.hooks.handle(self.tool('PostToolUse'))
        bad=self.tool(uid='')
        with self.assertRaises(HarnessError):self.hooks.handle(bad)
        self.assertEqual(self.status()['status'],'HOOK_ERRORS_OBSERVED')
        self.hooks.handle(self.tool(uid='recovered'))
        self.assertEqual(self.status()['status'],'HOOK_ERRORS_OBSERVED')
        self.hooks.handle(self.tool('PostToolUse',uid='recovered'))
        self.assertEqual(self.status()['status'],'TOOL_CYCLE_OBSERVED')

    def test_ordinary_event_does_not_clear_a_hook_error(self):
        self.start();self.hooks.handle(self.tool());self.hooks.handle(self.tool('PostToolUse'))
        with self.assertRaises(HarnessError):self.hooks.handle(self.tool(uid=''))
        self.hooks.handle({**self.event,'hook_event_name':'Interrupt'})
        self.assertEqual(self.status()['status'],'HOOK_ERRORS_OBSERVED')
        self.assertEqual(self.status()['tool_cycle_sessions'],0)

    def test_old_error_does_not_move_into_new_time_window(self):
        with patch('luna_astra.connection.time.time',return_value=100):
            self.start()
            with self.assertRaises(HarnessError):self.hooks.handle(self.tool(uid=''))
        with patch('luna_astra.connection.time.time',return_value=200):
            self.hooks.handle({**self.event,'hook_event_name':'Interrupt'})
        self.assertEqual(self.status(since=150)['error_sessions'],0)
        self.assertEqual(self.status(since=99)['error_sessions'],1)

    def test_post_for_preceding_failed_call_is_not_recovery(self):
        self.start();self.hooks.handle(self.tool())
        with self.assertRaises(HarnessError):self.hooks.handle(self.tool(uid=''))
        self.hooks.handle(self.tool('PostToolUse'))
        self.assertEqual(self.status()['status'],'HOOK_ERRORS_OBSERVED')

    def test_denied_call_does_not_count_as_matched_cycle(self):
        self.start()
        deny={'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny'}}
        record_hook(self.state,ROOT,self.tool(),deny)
        record_hook(self.state,ROOT,self.tool('PostToolUse'),{})
        self.assertEqual(self.status()['tool_cycle_sessions'],0)

    def test_another_payloads_records_do_not_prove_current_connection(self):
        self.start();other=self.base/'other-release'
        self.assertEqual(connection_status(self.state,other)['status'],'WAITING_FOR_CURRENT_RELEASE')

    def test_legacy_records_do_not_prove_connection(self):
        Store(self.state).put('legacy','meta',{'version':'3.2.0','context_emitted':True})
        self.assertEqual(self.status()['status'],'WAITING_FOR_CURRENT_RELEASE')

    def test_time_filter_does_not_accept_old_records(self):
        with patch('luna_astra.connection.time.time',return_value=100):self.start()
        self.assertEqual(self.status(since=101)['kernel_sessions'],0)
        self.assertEqual(self.status(since=99)['kernel_sessions'],1)

    def test_new_heartbeat_does_not_refresh_old_capability_proof(self):
        with patch('luna_astra.connection.time.time',return_value=100):
            self.start();self.hooks.handle(self.tool());self.hooks.handle(self.tool('PostToolUse'))
        with patch('luna_astra.connection.time.time',return_value=200):
            self.hooks.handle({**self.event,'hook_event_name':'Interrupt'})
        self.assertEqual(self.status(since=150)['kernel_sessions'],0)
        self.assertEqual(self.status(since=150)['tool_cycle_sessions'],0)

    def test_pair_started_before_requested_window_is_not_new_evidence(self):
        with patch('luna_astra.connection.time.time',return_value=100):
            self.start();self.hooks.handle(self.tool())
        with patch('luna_astra.connection.time.time',return_value=200):
            self.hooks.handle(self.tool('PostToolUse'))
        self.assertEqual(self.status(since=150)['tool_cycle_sessions'],0)

    def test_denied_repeated_pre_invalidates_prior_pending_call(self):
        self.start();record_hook(self.state,ROOT,self.tool(),{})
        record_hook(self.state,ROOT,self.tool(),{'hookSpecificOutput':{'permissionDecision':'deny'}})
        record_hook(self.state,ROOT,self.tool('PostToolUse'),{})
        self.assertEqual(self.status()['tool_cycle_sessions'],0)

    def test_unrepresentable_timestamp_is_unconfirmed(self):
        self.start()
        with Store(self.state).db(True) as db:db.execute('UPDATE hook_observations SET observed_at=1e300')
        self.assertEqual(self.status()['status'],'DIAGNOSTICS_UNREADABLE')

    def test_corrupt_observations_are_unconfirmed(self):
        self.start()
        with Store(self.state).db(True) as db:db.execute("UPDATE hook_observations SET data='[]'")
        self.assertEqual(self.status()['status'],'DIAGNOSTICS_UNREADABLE')

    def test_corrupt_legacy_meta_is_reported(self):
        Store(self.state).put('bad','meta',[])
        self.assertEqual(self.status()['status'],'DIAGNOSTICS_UNREADABLE')

    def test_corrupt_database_is_not_recreated(self):
        self.state.mkdir();db=self.state/'runtime.sqlite3';db.write_bytes(b'broken database')
        self.assertEqual(self.status()['status'],'DIAGNOSTICS_UNREADABLE')
        self.assertEqual(db.read_bytes(),b'broken database')

    def test_records_do_not_store_commands_prompts_or_transcript_paths(self):
        self.start();event=self.tool()
        event.update(tool_input={'command':'echo PRIVATE_SENTINEL_817'},prompt='PRIVATE_PROMPT_827',transcript_path='/private/transcript-837')
        record_hook(self.state,ROOT,event,{})
        with Store(self.state).db() as db:raw=''.join(r[0] for r in db.execute('SELECT data FROM hook_observations'))
        for value in ('PRIVATE_SENTINEL_817','PRIVATE_PROMPT_827','transcript-837'):self.assertNotIn(value,raw)

    def test_pending_observations_are_bounded(self):
        self.start()
        for index in range(40):record_hook(self.state,ROOT,self.tool(uid=str(index)),{})
        with Store(self.state).db() as db:data=json.loads(db.execute('SELECT data FROM hook_observations').fetchone()[0])
        self.assertLessEqual(len(data['pending']),32)

    def test_same_version_different_package_restores_kernel(self):
        import shutil
        self.start();other=self.base/'new-package';shutil.copytree(ROOT/'prompts',other/'prompts')
        out=Hooks(other,self.state).handle({**self.event,'hook_event_name':'UserPromptSubmit','prompt':'hello'})
        self.assertIn('LOCAL_HELPER_ARGV=',out['hookSpecificOutput']['additionalContext'])

    def test_read_only_query_preserves_every_runtime_file(self):
        self.start();before=snapshot(self.state)
        self.status();self.status()
        self.assertEqual(snapshot(self.state),before)

    def test_busy_diagnostic_uses_short_timeout(self):
        self.start()
        db=sqlite3.connect(self.state/'runtime.sqlite3')
        self.addCleanup(db.close)
        db.execute('BEGIN IMMEDIATE')
        real_connect=sqlite3.connect
        with patch('luna_astra.connection.sqlite3.connect',wraps=real_connect) as connect:
            with self.assertRaises(sqlite3.OperationalError):
                record_hook(self.state,ROOT,self.tool(),{})
        self.assertEqual(connect.call_args.kwargs['timeout'],0.05)
        db.rollback()

    def test_busy_diagnostic_does_not_change_completed_hook_result(self):
        self.start()
        db=sqlite3.connect(self.state/'runtime.sqlite3')
        self.addCleanup(db.close)
        db.execute('BEGIN IMMEDIATE')
        expected={'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':'fixture scope refusal'}}
        with patch.object(self.hooks,'_handle',return_value=expected),redirect_stderr(io.StringIO()) as err:
            actual=self.hooks.handle(self.tool())
        self.assertEqual(actual,expected)
        self.assertIn('diagnostics unavailable',err.getvalue())
        db.rollback()

    def test_diagnostic_write_error_does_not_change_core_output(self):
        with patch('luna_astra.connection.record_hook',side_effect=sqlite3.OperationalError('fixture')),redirect_stderr(io.StringIO()) as err:
            out=self.start()
        self.assertIn('LOCAL_HELPER_ARGV=',out['hookSpecificOutput']['additionalContext'])
        self.assertIn('diagnostics unavailable',err.getvalue())
