"""Opt-in diagnostics: budgets, privacy, corrupt data, and inert non-Luna hooks."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from luna_astra import gate_trace as trace
from luna_astra.hooks import Hooks
from luna_astra.model_gate import EVENTS

ROOT=Path(__file__).resolve().parents[1]
SECRET='PRIVATE_PROMPT_DO_NOT_RECORD_0987654321'

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.state=self.base/'home'/'luna-astra'/'state-v4'
        self.event={'hook_event_name':'UserPromptSubmit','model':'gpt-6-astra','session_id':'raw-session-'+SECRET,
                    'cwd':str(self.base/'never-read-workspace'),'prompt':SECRET,'auth':SECRET,
                    'tool_input':{'command':SECRET},'account_token':SECRET}
    def db(self,capture):return trace.directory(self.state)/('capture-'+capture+'.sqlite3')
    def test_status_without_arm_creates_nothing(self):
        self.assertFalse(trace.status(self.state)['armed']);self.assertFalse(self.state.parent.exists())
    def test_record_without_arm_creates_nothing(self):
        trace.record(self.state,self.event,{});self.assertFalse(self.state.parent.exists())
    def test_arm_does_not_create_task_state(self):
        result=trace.enable(self.state,30,8);self.assertTrue(result['armed']);self.assertFalse(self.state.exists())
    def test_enable_is_idempotent_while_armed(self):
        a=trace.enable(self.state,30,8);b=trace.enable(self.state,60,12)
        self.assertEqual(a['capture_id'],b['capture_id']);self.assertEqual(a['expires_at'],b['expires_at']);self.assertTrue(b['already_armed'])
    def test_invalid_budget_does_not_write(self):
        for seconds,events in ((0,8),(901,8),(True,8),(5,0),(5,513),(5,False)):
            with self.assertRaises(ValueError):trace.enable(self.state,seconds,events)
        self.assertFalse(self.state.parent.exists())
    def test_count_cap_auto_disarms(self):
        trace.enable(self.state,30,3)
        for _ in range(8):trace.record(self.state,self.event,{})
        status=trace.status(self.state);self.assertEqual(3,status['events_recorded']);self.assertFalse(status['armed'])
        self.assertFalse(trace.marker(self.state).exists());self.assertFalse(self.state.exists())
    def test_ttl_expiry_stops_without_new_record(self):
        a=trace.enable(self.state,10,8)
        with patch('luna_astra.gate_trace.time.time',return_value=a['expires_at']+1):
            trace.record(self.state,self.event,{});self.assertFalse(trace.status(self.state)['armed'])
        self.assertEqual(0,trace.status(self.state)['events_recorded']);self.assertFalse(trace.marker(self.state).exists())
    def test_clock_rollback_does_not_extend_capture(self):
        a=trace.enable(self.state,10,8)
        with patch('luna_astra.gate_trace.time.time',return_value=a['started_at']-1):trace.record(self.state,self.event,{})
        self.assertFalse(trace.status(self.state)['armed']);self.assertEqual(0,trace.status(self.state)['events_recorded'])
    def test_stop_preserves_capture(self):
        a=trace.enable(self.state,30,8);trace.record(self.state,self.event,{})
        trace.disable(self.state);self.assertFalse(trace.status(self.state)['armed'])
        self.assertTrue(self.db(a['capture_id']).exists());self.assertEqual(1,trace.status(self.state)['events_recorded'])
    def test_capture_private_fields_are_allowlisted(self):
        a=trace.enable(self.state,30,8);trace.record(self.state,self.event,{})
        report=trace.export_report(self.state);raw=Path(report['report_path']).read_text()
        self.assertNotIn(SECRET,raw);self.assertNotIn(self.event['cwd'],raw)
        self.assertNotIn(SECRET.encode(),self.db(a['capture_id']).read_bytes())
        data=json.loads(raw);r=data['observations'][0]
        self.assertEqual(set(r),trace._RECORD_FIELDS);self.assertEqual('NON_LUNA',r['classifier'])
        self.assertRegex(r['session_hash'],r'^[a-f0-9]{32}$');self.assertFalse(data['live_host_verified'])
        self.assertEqual('UNKNOWN',data['actual_host_kind'])
    def test_session_hash_correlates_switch_only_inside_capture(self):
        a=trace.enable(self.state,30,8)
        trace.record(self.state,self.event,{})
        trace.record(self.state,{**self.event,'model':'gpt-5.6-luna'}, {})
        rows=trace.status(self.state,include_records=True)['observations']
        self.assertEqual(rows[0]['session_hash'],rows[1]['session_hash'])
        trace.disable(self.state);b=trace.enable(self.state,30,8);trace.record(self.state,self.event,{})
        self.assertNotEqual(a['capture_id'],b['capture_id'])
        self.assertNotEqual(rows[0]['session_hash'],trace.status(self.state,include_records=True)['observations'][0]['session_hash'])
    def test_malformed_models_events_and_roles_are_sanitized(self):
        trace.enable(self.state,30,12)
        for event in (None,[],{}, {**self.event,'model':{'secret':SECRET},'hook_event_name':[]},
                      {**self.event,'model':123,'agent_id':[]}, {**self.event,'model':'line\n'+SECRET}):
            trace.record(self.state,event,{})
        text=json.dumps(trace.status(self.state,include_records=True));self.assertNotIn(SECRET,text)
        self.assertEqual(6,trace.status(self.state)['events_recorded'])
    def test_non_luna_hook_records_no_task_side_effects(self):
        trace.enable(self.state,30,32);h=Hooks(ROOT,self.state,fixed_seven=True,trace_model_gate=True)
        for kind in EVENTS:
            self.assertEqual({},h.handle({**self.event,'hook_event_name':kind}))
        report=trace.status(self.state,include_records=True)
        self.assertEqual(9,report['events_recorded']);self.assertFalse(report['non_luna_task_side_effect_seen'])
        self.assertFalse(self.state.exists())
    def test_luna_scope_emission_is_distinguished(self):
        trace.enable(self.state,30,8);ws=self.base/'work';ws.mkdir()
        e={**self.event,'model':'gpt-5.6-luna','hook_event_name':'SessionStart','cwd':str(ws),'turn_id':'t1'}
        out=Hooks(ROOT,self.state,fixed_seven=True,trace_model_gate=True).handle(e)
        self.assertIn('hookSpecificOutput',out)
        row=trace.status(self.state,include_records=True)['observations'][0]
        self.assertTrue(row['kernel_emitted']);self.assertTrue(row['additional_context_emitted']);self.assertTrue(row['state_created'])
    def test_cli_opt_in_non_luna_does_not_load_task_stack(self):
        trace.enable(self.state,30,8)
        cp=subprocess.run([sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--trace-model-gate','hook'],
                          input=json.dumps(self.event).encode(),capture_output=True,timeout=20)
        self.assertEqual(0,cp.returncode,cp.stderr.decode());self.assertEqual(b'{}\n',cp.stdout)
        self.assertEqual(1,trace.status(self.state)['events_recorded']);self.assertFalse(self.state.exists())
    def test_trace_failure_never_changes_non_luna_output(self):
        with patch('luna_astra.gate_trace.record',side_effect=OSError('unavailable')):
            self.assertEqual({},Hooks(ROOT,self.state,trace_model_gate=True).handle(self.event))
        self.assertFalse(self.state.exists())
    def test_trace_import_failure_cannot_block_non_luna(self):
        import builtins
        real=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name.endswith('gate_trace'):raise ImportError('diagnostic unavailable')
            return real(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=guarded):
            self.assertEqual({},Hooks(ROOT,self.state,trace_model_gate=True).handle(self.event))
        self.assertFalse(self.state.exists())
    def test_export_omits_personal_paths(self):
        trace.enable(self.state,30,8);trace.record(self.state,self.event,{})
        report=trace.export_report(self.state)
        data=json.loads(Path(report['report_path']).read_text())
        self.assertNotIn('diagnostic_directory',data)
        self.assertNotIn(str(self.base),json.dumps(data))
    def test_report_is_readonly_before_export(self):
        trace.enable(self.state,30,8);trace.record(self.state,self.event,{})
        before={p.name:p.read_bytes() for p in trace.directory(self.state).iterdir() if p.is_file()}
        trace.status(self.state,include_records=True)
        self.assertEqual(before,{p.name:p.read_bytes() for p in trace.directory(self.state).iterdir() if p.is_file()})
    def test_concurrent_recorders_never_exceed_cap(self):
        trace.enable(self.state,30,5)
        def run(_):
            try:trace.record(self.state,self.event,{})
            except (OSError,sqlite3.Error):pass  # Bounded diagnostic loss is allowed, side effects are not.
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(run,range(20)))
        status=trace.status(self.state);self.assertEqual(5,status['events_recorded']);self.assertFalse(status['armed'])
    def test_corrupt_capture_limits_fail_closed(self):
        a=trace.enable(self.state,30,8)
        with closing(sqlite3.connect(self.db(a['capture_id']))) as db:db.execute('UPDATE settings SET max_events=99999');db.commit()
        with self.assertRaises(ValueError):trace.record(self.state,self.event,{})
        self.assertEqual({},Hooks(ROOT,self.state,trace_model_gate=True).handle(self.event));self.assertFalse(self.state.exists())
    def test_modified_capture_free_text_is_not_exported(self):
        a=trace.enable(self.state,30,8);trace.record(self.state,self.event,{})
        with closing(sqlite3.connect(self.db(a['capture_id']))) as db:
            row=json.loads(db.execute('SELECT data FROM observations').fetchone()[0]);row['session_hash']=SECRET
            db.execute('UPDATE observations SET data=?',(json.dumps(row),));db.commit()
        with self.assertRaises(ValueError):trace.export_report(self.state)
        self.assertFalse(list(trace.directory(self.state).glob('report-*')))
    def test_extra_fields_are_rejected_not_exported(self):
        a=trace.enable(self.state,30,8);trace.record(self.state,self.event,{})
        with closing(sqlite3.connect(self.db(a['capture_id']))) as db:
            row=json.loads(db.execute('SELECT data FROM observations').fetchone()[0]);row['raw_prompt']=SECRET
            db.execute('UPDATE observations SET data=?',(json.dumps(row),));db.commit()
        with self.assertRaises(ValueError):trace.export_report(self.state)
    def test_symlink_capture_root_is_rejected(self):
        target=self.base/'other';target.mkdir();self.state.parent.mkdir(parents=True)
        trace.directory(self.state).symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):trace.enable(self.state,30,8)
        self.assertEqual([],list(target.iterdir()))
    def test_disarm_cannot_remove_new_capture_marker(self):
        first=trace.enable(self.state,30,8);trace.disable(self.state);second=trace.enable(self.state,30,8)
        trace._disarm(self.state,first['capture_id']);self.assertEqual(second['capture_id'],trace.status(self.state)['capture_id'])
        self.assertTrue(trace.status(self.state)['armed'])
