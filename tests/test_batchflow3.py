"""Regression counterexamples for batchflow.3. No real model calls.

Tests exercise actual SQLite, source files and hook code. Timings are measured
separately: scheduling speed is not asserted using fragile wall-clock limits.
"""
from concurrent.futures import ThreadPoolExecutor, Future
from contextlib import contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import test_fixed_seven as fixed
from luna_astra.activation import APPLICABILITY
from luna_astra.coordination import Coordinator, Conflict
from luna_astra.hook_policy import MATCHER, NATIVE, EDIT, SHELL, relevant, canonical_tool
from luna_astra.hooks import Hooks, identity
from luna_astra.store import Store
from luna_astra.transport import helper_command, tool_name
from luna_astra.util import HarnessError, file_hash, canonical

ROOT=Path(__file__).resolve().parents[1]

class SelectorTests(unittest.TestCase):
    def event(self,name):return {'hook_event_name':'PreToolUse','tool_name':name}
    def test_all_supported_native_names_match(self):
        for name in NATIVE:
            for full in (name,'functions.'+name,'multi_agent_v1'+name,'multi_agent_v2'+name):
                with self.subTest(full=full):
                    self.assertIsNotNone(re.fullmatch(MATCHER,full));self.assertTrue(relevant(self.event(full)))
                    self.assertEqual(name,tool_name(full));self.assertEqual(name,canonical_tool(full))
    def test_edit_and_shell_names_share_the_same_normalization(self):
        for name in EDIT|SHELL:
            for full in (name,'functions.'+name):
                with self.subTest(full=full):
                    self.assertTrue(relevant(self.event(full)));self.assertEqual(name,tool_name(full))
    def test_read_search_and_lookalike_mcp_names_are_not_claimed(self):
        for name in ('read_file','search','mcp__foo__apply_patch','evilspawn_agent','functions.read_file','multi_agent_v2_bad'):
            with self.subTest(name=name):self.assertFalse(relevant(self.event(name)))
    def test_lifecycle_events_do_not_require_a_tool_name(self):
        for kind in ('SessionStart','UserPromptSubmit','Stop','Interrupt','PostCompact','SubagentStart','SubagentStop'):
            self.assertTrue(relevant({'hook_event_name':kind}))
    def test_malformed_names_are_inert(self):
        for name in (None,[],{},0,True,''):
            self.assertFalse(relevant(self.event(name)))
    def test_luna_read_hook_never_opens_store_or_reads_prompts(self):
        with tempfile.TemporaryDirectory() as d:
            h=Hooks(ROOT,Path(d)/'untouched',fixed_seven=True)
            event={**self.event('read_file'),'model':'gpt-5.6-luna','cwd':d,'session_id':'r'}
            with patch('luna_astra.hooks.Store',side_effect=AssertionError('unnecessary DB')):
                with patch.object(h,'_prompt',side_effect=AssertionError('unnecessary prompt')):
                    self.assertEqual({},h.handle(event))
            self.assertFalse(h.state.exists())
    def test_early_luna_read_needs_no_orchestration_modules_or_bytecode(self):
        # This miniature package deliberately has no hooks/crew/sqlite module.
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);(base/'luna_astra').mkdir()
            for name in ('luna.py','luna_astra/__init__.py','luna_astra/model_gate.py','luna_astra/hook_policy.py'):
                (base/name).write_bytes((ROOT/name).read_bytes())
            ev={**self.event('read_file'),'model':'gpt-5.6-luna','session_id':'r','cwd':d}
            env=os.environ.copy();env.pop('PYTHONDONTWRITEBYTECODE',None)
            result=subprocess.run([sys.executable,str(base/'luna.py'),'--state',str(base/'state'),'hook'],
                                  input=json.dumps(ev).encode(),capture_output=True,env=env)
            self.assertEqual(0,result.returncode,result.stderr);self.assertEqual(b'{}\n',result.stdout)
            self.assertFalse((base/'state').exists());self.assertEqual([],list(base.rglob('*.pyc')))

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name)/'state')
    def test_one_operation_reuses_connection_without_value_cache(self):
        real=sqlite3.connect;calls=[]
        def track(*args,**kw):calls.append(args);return real(*args,**kw)
        with patch('sqlite3.connect',side_effect=track),self.store.connection():
            self.store.put('s','n',1);self.assertEqual(1,self.store.get('s','n'))
            self.store.put('s','n',2);self.assertEqual(2,self.store.get('s','n'))
        self.assertEqual(1,len(calls))
    def test_nested_rollback_does_not_erase_outer_transaction(self):
        with self.store.db(True):
            self.store.put('s','outer','retained')
            with self.assertRaisesRegex(RuntimeError,'inner'):
                with self.store.db(True):self.store.put('s','inner','removed');raise RuntimeError('inner')
            self.assertEqual('retained',self.store.get('s','outer'));self.assertIsNone(self.store.get('s','inner'))
        self.assertEqual('retained',self.store.get('s','outer'))
    def test_outer_rollback_includes_successful_inner_writes(self):
        with self.assertRaises(RuntimeError):
            with self.store.connection(),self.store.db(True):
                self.store.put('s','inner',1);raise RuntimeError('outer')
        self.assertIsNone(self.store.get('s','inner'))
    def test_schema_creation_does_not_commit_outer_write(self):
        with self.store.connection():
            with self.assertRaises(RuntimeError):
                with self.store.db(True):
                    self.store.put('s','before',1)
                    self.store.ensure_schema('probe','CREATE TABLE IF NOT EXISTS probe(n INTEGER);')
                    raise RuntimeError('rollback')
            self.assertIsNone(self.store.get('s','before'))
            with self.store.db() as db:self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='probe'").fetchone())
            self.store.ensure_schema('probe','CREATE TABLE IF NOT EXISTS probe(n INTEGER);')
            with self.store.db() as db:self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='probe'").fetchone())
    def test_threads_sharing_store_never_share_sqlite_handles(self):
        barrier=threading.Barrier(4)
        def thread(i):
            with self.store.connection():
                handle=id(self.store._shared);barrier.wait()
                for n in range(10):self.store.put(str(i),'n',n)
                return handle,self.store.get(str(i),'n')
        with ThreadPoolExecutor(max_workers=4) as pool:values=list(pool.map(thread,range(4)))
        self.assertEqual(4,len({x[0] for x in values}));self.assertTrue(all(x[1]==9 for x in values))
    def test_independent_store_writes_are_visible_in_same_connection(self):
        other=Store(self.store.directory)
        with self.store.connection():
            self.assertIsNone(self.store.get('s','a'));other.put('s','a',3)
            self.assertEqual(3,self.store.get('s','a'))
    def test_context_exit_closes_handle_after_body_error(self):
        with self.assertRaises(RuntimeError):
            with self.store.connection():db=self.store._shared;raise RuntimeError('body')
        with self.assertRaises(sqlite3.ProgrammingError):db.execute('SELECT 1')
        self.assertIsNone(self.store._shared)
    def test_event_index_and_bounded_trace_keep_latest(self):
        with self.store.connection():
            for n in range(1003):self.store.event('s',str(n),'fixture',{'n':n})
            with self.store.db() as db:
                self.assertEqual(1000,db.execute('SELECT COUNT(*) FROM events').fetchone()[0])
                self.assertIn('events_scope_seq',{r[1] for r in db.execute('PRAGMA index_list(events)')})
        self.assertEqual(1002,self.store.recent('s',1)[0]['n'])

class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'project';self.root.mkdir();(self.root/'a.txt').write_text('old')
        self.store=Store(Path(self.tmp.name)/'state');self.c=Coordinator(self.store,self.root)
    def pre(self,owner,uid,tool='apply_patch',paths=None):
        self.c.claim(owner,paths or ['a.txt'],'tool:'+uid)
        self.store.event(owner,'pre:'+uid,'tool_start',{'tool':tool,'edit_paths':paths or ['a.txt']})
    def test_missing_post_edit_is_released_at_stop_not_success(self):
        self.pre('a','first');self.assertEqual(['first'],self.c.release_finished_edits('a'))
        self.assertEqual([],self.c.status());last=self.store.recent('a',1)[0]
        self.assertEqual('UNKNOWN',last['outcome']);self.assertEqual('edit_reconciled',last['kind'])
    def test_another_pre_never_steals_an_inflight_edit(self):
        self.pre('a','first')
        with self.assertRaises(Conflict):self.c.claim('a',['a.txt'],'tool:next')
        self.assertEqual(1,len(self.c.status()))
    def test_other_owner_and_manual_leases_remain(self):
        self.pre('a','one');self.c.claim('a',['manual'],'manual');self.pre('b','two',paths=['b.txt'])
        self.c.release_finished_edits('a')
        self.assertEqual({'manual','tool:two'},{r['token'] for r in self.c.status()})
    def test_explicit_running_post_and_nonedit_tokens_remain(self):
        self.pre('a','running');self.store.event('a','post:running','tool_result',{'outcome':'RUNNING'})
        self.pre('a','native',tool='spawn_agent',paths=['native'])
        self.assertEqual([],self.c.release_finished_edits('a'));self.assertEqual(2,len(self.c.status()))
    def test_a_lease_without_recorded_edit_is_not_guessed(self):
        self.c.claim('a',['a.txt'],'tool:unknown')
        self.assertEqual([],self.c.release_finished_edits('a'));self.assertEqual(1,len(self.c.status()))
    def test_one_edit_touching_two_files_is_reconciled_once(self):
        self.pre('a','one',paths=['a.txt','b.txt'])
        self.assertEqual(['one'],self.c.release_finished_edits('a'))
        self.assertEqual([],self.c.release_finished_edits('a'))

class CrewRepairTests(unittest.TestCase):
    def setUp(self):self.f=fixed.Fixture();self.addCleanup(self.f.close)
    def pre(self,name,payload,uid='edit',event=None):
        return {**(event or self.f.event),'hook_event_name':'PreToolUse','tool_name':name,'tool_input':payload,'tool_use_id':uid}
    def test_stop_clears_failed_edit_even_when_crew_is_incomplete(self):
        self.f.planning()
        event=self.pre('Write',{'path':'output.txt','content':'5'})
        self.f.hooks.handle(event);c=Coordinator(self.f.store,self.f.root)
        self.assertTrue(c.status())
        out=self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop','last_assistant_message':'Not finished'})
        self.assertEqual([],c.status());self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
        self.assertFalse(self.f.crew.status(self.f.owner)['complete'])
    def test_native_call_without_ack_is_not_released_or_respawned(self):
        self.f.start();call=self.f.crew.next(self.f.owner)['calls'][0]
        self.f.hooks.handle(self.pre(call['tool'],call['arguments'],'native'))
        self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop','last_assistant_message':'unconfirmed'})
        with self.f.store.db() as db:
            self.assertEqual('pending',db.execute("SELECT state FROM dispatches WHERE call_id='native'").fetchone()[0])
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'replacement',call['arguments'],'gpt-5.6-luna','spawn_agent')
    def test_root_raw_shell_cannot_bypass_scoped_edit_tools(self):
        self.f.planning()
        for name,field in (('Bash','command'),('exec_command','cmd'),('shell_command','command')):
            with self.subTest(name=name):
                command=helper_command([sys.executable,'-c',"open('outside.txt','w').write('bad')"])
                out=self.f.hooks.handle(self.pre(name,{field:command},name))
                self.assertEqual('deny',out['hookSpecificOutput']['permissionDecision'])
        self.assertFalse((self.f.root/'outside.txt').exists())
    def test_root_registered_check_path_still_allowed(self):
        self.f.planning()
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.f.state),'--session',self.f.owner]
        out=self.f.hooks.handle(self.pre('Bash',{'command':helper_command(prefix+['run-all'])}))
        self.assertNotEqual('deny',out.get('hookSpecificOutput',{}).get('permissionDecision'))
        ev=self.f.checked_output();self.assertTrue(ev.status()['passed'])
    def test_direct_root_shell_stages_large_payload_in_cmd_field(self):
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.f.state),'--session',self.f.owner]
        data=json.dumps({'facts':['bounded staging '+('x'*5000)]})
        out=self.f.hooks.handle(self.pre('exec_command',{'cmd':helper_command(prefix+['--input-json',data,'note'])}))
        changed=out['hookSpecificOutput']['updatedInput']
        self.assertIn('--input-ref',changed['cmd']);self.assertNotIn('command',changed)
        self.assertEqual(1,len(list((self.f.state/'requests'/self.f.owner).glob('*.json'))))
    def test_namespaced_write_cannot_bypass_protected_scope(self):
        self.f.planning()
        out=self.f.hooks.handle(self.pre('functions.Write',{'path':'outside.txt','content':'bad'}))
        self.assertEqual('deny',out['hookSpecificOutput']['permissionDecision'])
    def test_readonly_worker_direct_shell_alias_is_denied(self):
        self.f.start();self.f.dispatch()
        worker={**self.f.event,'session_id':'child-1','agent_id':'child-1'}
        for name,field in (('Bash','command'),('exec_command','cmd'),('shell_command','command')):
            with self.subTest(name=name):
                out=self.f.hooks.handle(self.pre(name,{field:'echo not-readonly'},name,worker))
                self.assertEqual('deny',out['hookSpecificOutput']['permissionDecision'])
    def test_compact_restore_is_bounded_and_retains_actual_six(self):
        self.f.start();self.f.dispatch();before=self.f.crew.status(self.f.owner)
        self.f.store.put(self.f.owner,'note',{'facts':['한글 large note '*12000]})
        self.f.hooks.handle({**self.f.event,'hook_event_name':'PostCompact'})
        text=self.f.hooks.handle({**self.f.event,'hook_event_name':'SessionStart','source':'compact'})['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(len(text.encode()),12000);self.assertEqual(1,text.count(APPLICABILITY))
        for n in range(1,7):self.assertIn('child-'+str(n),text)
        self.assertIn('PLAN',text);self.assertIn('context --recover',text)
        self.assertEqual(before,self.f.crew.status(self.f.owner))
        self.assertEqual(12000,self.f.store.get(self.f.owner,'note')['facts'][0].count('한글'))
    def test_cold_kernel_keeps_obligations_without_oversize_fallback(self):
        text=self.f.hooks._core(self.f.owner,'root','gpt-5.6-luna','x')
        self.assertLess(len(text.encode()),12000)
        for value in ('Use exactly six','s5/s6','crew-step','crew-report-read','RESEARCH','read-only','no'):
            self.assertIn(value,text)
    def test_legacy_restore_does_not_inject_fixed_six(self):
        h=Hooks(ROOT,self.f.base/'legacy')
        text=h._recovery_core('a'*64,'worker','gpt-5.6-luna','x')
        self.assertIn('delegated Luna worker',text);self.assertNotIn('same six',text)
    def test_hook_context_budget_includes_scope_header(self):
        out=self.f.hooks._output(self.f.store,self.f.owner,'PreToolUse',['a'*11800])
        text=out['hookSpecificOutput']['additionalContext']
        self.assertLessEqual(len(text.encode()),12000);self.assertIn(APPLICABILITY,text)
        self.assertIn('context --recover',text)
    def test_recover_reads_saved_protocol_without_rebuilding_codemap(self):
        import luna
        self.f.store.put(self.f.owner,'note',{'facts':['verified entry point']})
        args=['--state',str(self.f.state),'--session',self.f.owner,'context','--recover']
        out=io.StringIO()
        with patch.object(luna.CodeMap,'build',side_effect=AssertionError('unrequested full scan')),redirect_stdout(out):
            self.assertEqual(0,luna.main(args))
        result=json.loads(out.getvalue());self.assertIn('verified entry point',out.getvalue())
        self.assertIn('Use exactly six',out.getvalue())

class HashConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'data';self.path.write_bytes(b'a'*2000000)
    def test_static_streamed_hash_matches_standard_sha(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),file_hash(self.path))
    def test_replace_between_path_stat_and_open_is_detected(self):
        original=Path.open;replacement=self.path.with_name('other');replacement.write_bytes(b'b'*2000000)
        done=False
        def swapped(path,*args,**kwargs):
            nonlocal done
            if path==self.path and not done:done=True;os.replace(replacement,self.path)
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',new=swapped),self.assertRaises(HarnessError):file_hash(self.path)
    def test_source_read_checks_the_opened_file_identity(self):
        from luna_astra.transport import read_source
        original=Path.open;other=self.path.with_name('replacement');other.write_text('new source')
        replaced=False
        def opened(path,*args,**kw):
            nonlocal replaced
            if path==self.path and not replaced:replaced=True;os.replace(other,self.path)
            return original(path,*args,**kw)
        with patch.object(Path,'open',new=opened),self.assertRaises(HarnessError) as caught:
            read_source(self.path.parent,self.path.name)
        self.assertEqual('SOURCE_CHANGED',caught.exception.code)
    def test_byte_read_checks_the_opened_file_identity(self):
        from luna_astra.transport import read_bytes
        original=Path.open;other=self.path.with_name('replacement');other.write_bytes(b'new source')
        replaced=False
        def opened(path,*args,**kw):
            nonlocal replaced
            if path==self.path and not replaced:replaced=True;os.replace(other,self.path)
            return original(path,*args,**kw)
        with patch.object(Path,'open',new=opened),self.assertRaises(HarnessError) as caught:
            read_bytes(self.path.parent,self.path.name)
        self.assertEqual('SOURCE_CHANGED',caught.exception.code)
    def test_inplace_write_with_restored_mtime_is_detected(self):
        original=Path.open;before=self.path.stat();changed=False
        class Reader:
            def __init__(inner,stream):inner.stream=stream
            def __enter__(inner):return inner
            def __exit__(inner,*a):inner.stream.close()
            def fileno(inner):return inner.stream.fileno()
            def read(inner,n):
                nonlocal changed
                data=inner.stream.read(n)
                if data and not changed:
                    changed=True
                    with original(self.path,'r+b') as writer:writer.seek(1500000);writer.write(b'z');writer.flush();os.fsync(writer.fileno())
                    os.utime(self.path,ns=(before.st_atime_ns,before.st_mtime_ns))
                return data
        def opened(path,*a,**kw):
            stream=original(path,*a,**kw)
            return Reader(stream) if path==self.path and a==('rb',) else stream
        # Windows ctime denotes creation time on some Python/filesystem versions;
        # the byte comparison remains mandatory there, but this fixture tests POSIX change time.
        if os.name=='nt':
            # Do not skip: use a real changed mtime, which has the same invalidation requirement.
            real_utime=os.utime
            def changed_time(path,*,ns):return real_utime(path,ns=(ns[0],ns[1]+1000000000))
            with patch.object(Path,'open',new=opened),patch('os.utime',side_effect=changed_time),self.assertRaises(HarnessError):file_hash(self.path)
        else:
            with patch.object(Path,'open',new=opened),self.assertRaises(HarnessError):file_hash(self.path)

if __name__=='__main__':unittest.main()
