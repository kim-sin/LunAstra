"""Batchflow.4 boundary tests: actual files/DB/processes, simulated host events."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_fixed_seven import Fixture, PACKAGE
from test_v42_native import V2Fixture
from luna_astra.controller import Controller
from luna_astra.flow import Flow
from luna_astra.native import task_name
from luna_astra.native_flow import NativeFlow
from luna_astra.native_receipts import reconcile
from luna_astra.hook_policy import relevant, canonical_tool
from luna_astra.scan import observe
from luna_astra.crew import fingerprint
from luna_astra.research import Research
from luna_astra.util import HarnessError, file_hash, canonical
from tools.release import collect, distribution_bytes, build, verify


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close);self.f.start()
        self.call=self.f.crew.next(self.f.owner)['calls'][0];self.uid='receipt-call'
        self.path=self.f.base/'host.jsonl'
        self.append({'type':'session_meta','payload':{'id':self.f.event['session_id']}})
    def append(self, obj):
        with self.path.open('a',encoding='utf-8') as out:out.write(json.dumps(obj)+'\n')
    def prepare(self, *, namespace=None, turn=None):
        if turn:self.append({'type':'turn_context','payload':{'turn_id':turn}})
        body={'type':'function_call','name':self.call['tool'],'call_id':self.uid,'arguments':canonical(self.call['arguments'])}
        if namespace:body['namespace']=namespace
        self.append({'type':'response_item','payload':body})
        event={**self.f.event,'hook_event_name':'PreToolUse','tool_name':self.call['tool'],
               'tool_input':self.call['arguments'],'tool_use_id':self.uid,'transcript_path':str(self.path)}
        result=self.f.hooks.handle(event)
        self.assertNotEqual('deny',result.get('hookSpecificOutput',{}).get('permissionDecision'))
        return event
    def output(self, data, call_id=None):
        self.append({'type':'response_item','payload':{'type':'function_call_output','call_id':call_id or self.uid,
                    'output':json.dumps(data) if not isinstance(data,str) else data}})
    def state(self):
        with self.f.store.db() as db:return db.execute('SELECT state FROM dispatches WHERE owner=? AND call_id=?',(self.f.owner,self.uid)).fetchone()[0]
    def test_missing_post_success_restores_exact_agent(self):
        self.prepare();self.output({'agent_id':'observed-native-child'})
        r=reconcile(self.f.crew,self.f.owner)
        self.assertEqual('ACK_RECOVERED',r['restored'][0]['state']);self.assertEqual('running',self.state())
        self.assertEqual('observed-native-child',self.f.crew.status(self.f.owner)['members'][0]['agent_id'])
        self.assertEqual(0,r['models_started']);self.assertEqual(0,r['models_replaced'])
    def test_dotted_namespace_receipt_is_recognized(self):
        self.prepare(namespace='multi_agent_v1');self.output({'agent_id':'native-a'})
        self.assertEqual(1,len(reconcile(self.f.crew,self.f.owner)['restored']))
    def test_controller_step_recovers_without_manual_command(self):
        self.prepare();self.output({'agent_id':'native-a'})
        r=Controller(self.f.store,PACKAGE).step(self.f.owner)
        self.assertEqual(1,len(r['recovered_native_receipts']['restored']))
    def test_missing_output_remains_unresolved(self):
        self.prepare();self.assertEqual([self.uid],reconcile(self.f.crew,self.f.owner)['unresolved']);self.assertEqual('pending',self.state())
    def test_other_call_output_is_not_ours(self):
        self.prepare();self.output({'agent_id':'not-ours'},'different-call')
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
    def test_prose_in_assistant_message_is_not_a_receipt(self):
        self.prepare();self.append({'type':'event_msg','payload':{'type':'function_call_output','call_id':self.uid,'output':'{"agent_id":"fake"}'}})
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
    def test_generic_error_does_not_authorize_respawn(self):
        self.prepare();self.output({'isError':True,'message':'unknown error'})
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored']);self.assertEqual('unknown',self.state())
        with self.assertRaises(HarnessError):self.f.crew.retry_native(self.f.owner,1,'try again')
    def test_timeout_text_does_not_authorize_respawn(self):
        self.prepare();self.output('request timed out')
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored']);self.assertEqual('unknown',self.state())
    def test_known_prestart_refusal_requires_cause_addressed_retry(self):
        self.prepare();self.output('collab spawn failed: agent thread limit reached')
        r=reconcile(self.f.crew,self.f.owner);self.assertEqual('REJECTED_BEFORE_START',r['restored'][0]['state'])
        self.assertEqual('failed',self.state());self.assertIsNone(self.f.crew.status(self.f.owner)['members'][0]['agent_id'])
        self.assertEqual('HOST_CAPABILITY',Flow(self.f.store,PACKAGE).drive(self.f.owner)['kind'])
        result=self.f.crew.retry_native(self.f.owner,1,'Host capacity has been corrected; retry the same reservation')
        self.assertEqual(self.call['ticket'],result['ticket']);self.assertFalse(result['new_agent_started'])
        self.assertEqual(self.call['ticket'],self.f.crew.next(self.f.owner)['calls'][0]['ticket'])
    def test_rejection_substring_or_suffix_is_not_a_safe_refusal(self):
        self.prepare();self.output('collab spawn failed: agent thread limit reached; but child might exist')
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored']);self.assertEqual('unknown',self.state())
    def test_result_with_error_and_agent_id_is_not_accepted(self):
        self.prepare();self.output({'agent_id':'bad','isError':True})
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored']);self.assertEqual('unknown',self.state())
    def test_incomplete_line_retries_after_append(self):
        self.prepare();line=canonical({'type':'response_item','payload':{'type':'function_call_output','call_id':self.uid,'output':'{"agent_id":"native-a"}'}})
        with self.path.open('a') as f:f.write(line[:40])
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
        with self.path.open('a') as f:f.write(line[40:]+'\n')
        self.assertEqual(1,len(reconcile(self.f.crew,self.f.owner)['restored']))
    def test_replaced_transcript_never_binds(self):
        self.prepare();other=self.path.with_suffix('.replacement');other.write_bytes(self.path.read_bytes());other.replace(self.path)
        self.output({'agent_id':'fake'});self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
    def test_changed_session_header_never_binds(self):
        self.prepare();self.path.write_text(self.path.read_text().replace('root-native','wrong-owner'));self.output({'agent_id':'fake'})
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
    def test_other_turn_call_never_binds(self):
        self.prepare(turn='wrong-turn');self.output({'agent_id':'fake'})
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
    def test_changed_call_input_never_binds(self):
        self.prepare();text=self.path.read_text().replace('LUNASTRA_TICKET','CHANGED_TICKET');self.path.write_text(text);self.output({'agent_id':'fake'})
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
    def test_unobserved_transcript_is_not_read(self):
        self.prepare();self.f.store.put(self.f.owner,'native-transcript:'+self.uid,None);self.output({'agent_id':'fake'})
        self.assertFalse(reconcile(self.f.crew,self.f.owner)['restored'])
    def test_successful_receipt_is_idempotent(self):
        self.prepare();self.output({'agent_id':'a'});reconcile(self.f.crew,self.f.owner)
        self.assertEqual([],reconcile(self.f.crew,self.f.owner)['restored'])
    def test_no_unknown_call_can_be_retried(self):
        self.prepare()
        with self.assertRaises(HarnessError):self.f.crew.retry_native(self.f.owner,1,'No outcome is known')
    def test_no_root_impersonation(self):
        self.prepare()
        with self.assertRaises(HarnessError):reconcile(self.f.crew,'not-an-owner')


class OpaqueV2Tests(unittest.TestCase):
    def setUp(self):self.f=V2Fixture();self.addCleanup(self.f.close);self.f.start()
    def test_current_emitted_opaque_spawn_has_same_slot(self):
        c=self.f.crew.next(self.f.owner)['calls'][0];c['arguments']['message']='opaque-host-ciphertext';self.f.one(c)
        self.assertEqual(1,self.f.crew.status(self.f.owner)['observed_children'])
    def test_opaque_wrong_task_name_rejected(self):
        c=self.f.crew.next(self.f.owner)['calls'][0];args={**c['arguments'],'message':'opaque','task_name':'not_issued'}
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',args,self.f.event['model'],'spawn_agent')
    def test_unissued_reserved_slot_is_not_implicitly_authorized(self):
        c=self.f.crew.next(self.f.owner)['calls'][0];args={**c['arguments'],'message':'opaque','task_name':task_name(self.f.crew.status(self.f.owner),2)}
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',args,self.f.event['model'],'spawn_agent')
    def test_opaque_call_does_not_bypass_override_gate(self):
        c=self.f.crew.next(self.f.owner)['calls'][0];args={**c['arguments'],'message':'opaque','model':'another-model'}
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',args,self.f.event['model'],'spawn_agent')
    def test_empty_opaque_message_is_rejected(self):
        c=self.f.crew.next(self.f.owner)['calls'][0];args={**c['arguments'],'message':''}
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',args,self.f.event['model'],'spawn_agent')
    def test_old_plan_route_not_reused(self):
        c=self.f.crew.next(self.f.owner)['calls'][0];intent=self.f.store.get(self.f.owner,'native-intent:'+c['ticket']);intent['plan_id']='old';self.f.store.put(self.f.owner,'native-intent:'+c['ticket'],intent)
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',{**c['arguments'],'message':'opaque'},self.f.event['model'],'spawn_agent')
    def test_opaque_followup_reuses_actual_native_target(self):
        self.f.dispatch();self.f.reports();self.f.execute()
        for c in self.f.crew.next(self.f.owner)['calls']:
            self.assertEqual('followup_task',c['tool']);c['arguments']['message']='opaque-followup';self.f.one(c)
        self.assertEqual(6,self.f.crew.status(self.f.owner)['observed_children'])
    def test_opaque_recovery_requires_native_completion(self):
        self.f.dispatch();state=self.f.crew.status(self.f.owner)
        flow=Flow(self.f.store,PACKAGE);flow.pre_wait(self.f.owner,'wait-1',{'timeout_ms':60000});flow.post_wait(self.f.owner,'wait-1',{'message':'done','timed_out':False})
        nf=NativeFlow(self.f.store,self.f.crew);nf.pre(self.f.owner,'list-1','list_agents',{});nf.post(self.f.owner,'list-1','list_agents',{'agents':[{'agent_name':self.f.native_handles[i],'agent_status':{'completed':None}} for i in range(1,7)]})
        call=flow.prepare_recovery(self.f.owner,1);args={**call['arguments'],'message':'opaque-recovery'}
        self.f.crew.pre_dispatch(self.f.owner,'recover',args,self.f.event['model'],'followup_task')
        self.assertEqual('reserved',self.f.crew.status(self.f.owner)['tasks'][0]['state'])
    def test_v1_still_requires_plain_ticket(self):
        f=Fixture();self.addCleanup(f.close);f.start();call=f.crew.next(f.owner)['calls'][0]
        with self.assertRaises(HarnessError):f.crew.pre_dispatch(f.owner,'x',{**call['arguments'],'message':'opaque'},f.event['model'],'spawn_agent')
    def test_dotted_host_names_do_not_skip_hooks(self):
        for name in ('spawn_agent','send_input','wait_agent','followup_task'):
            for prefix in ('multi_agent_v1.','multi_agent_v2.'):
                event={'hook_event_name':'PreToolUse','tool_name':prefix+name}
                self.assertTrue(relevant(event));self.assertEqual(name,canonical_tool(event['tool_name']))
        self.assertFalse(relevant({'hook_event_name':'PreToolUse','tool_name':'mcp__fake__multi_agent_v1.spawn_agent'}))


class StreamingObservationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'project';self.root.mkdir()
    def test_large_file_full_observation_and_bounded_preview(self):
        p=self.root/'data.bin'
        with p.open('wb') as f:f.truncate(33*1024*1024)
        self.assertFalse(observe(self.root)['complete']);result=observe(self.root,full=True)
        self.assertTrue(result['complete']);self.assertEqual(file_hash(p),result['files']['data.bin'])
    def test_more_than_5000_files_are_fully_observed(self):
        for i in range(5003):(self.root/f'f{i}').write_text('x')
        self.assertFalse(observe(self.root,max_seconds=60)['complete']);r=observe(self.root,full=True)
        self.assertTrue(r['complete']);self.assertEqual(5003,len(r['files']))
    def test_review_fingerprint_streams_beyond_old_64m_limit(self):
        with (self.root/'big.bin').open('wb') as f:f.truncate(65*1024*1024)
        r=fingerprint(self.root,['big.bin']);self.assertEqual(file_hash(self.root/'big.bin'),r['entries']['big.bin']['sha256'])
    def test_overlapping_paths_hash_only_once(self):
        (self.root/'data').mkdir();(self.root/'data/a').write_text('x')
        with patch('luna_astra.crew.file_hash',wraps=file_hash) as hashed:fingerprint(self.root,['data','data/a']);self.assertEqual(1,hashed.call_count)
    def test_walk_permission_error_is_not_complete(self):
        def broken(root,followlinks,onerror):
            onerror(PermissionError('denied'))
            yield str(root),[],[]
        with patch('luna_astra.scan.os.walk',broken):self.assertFalse(observe(self.root,full=True)['complete'])
    def test_added_file_during_scan_invalidates_observation(self):
        (self.root/'a').write_text('original')
        def changed(path):
            result=file_hash(path);(self.root/'late').write_text('late');return result
        with patch('luna_astra.scan.file_hash',changed):self.assertFalse(observe(self.root,full=True)['complete'])
    def test_symlink_root_is_not_laundered_by_resolve(self):
        link=self.root.with_name('alias')
        try:link.symlink_to(self.root,target_is_directory=True)
        except OSError:
            with patch('luna_astra.scan.no_symlinks',side_effect=HarnessError('symlink')):
                with self.assertRaises(HarnessError):observe(link,full=True)
        else:
            with self.assertRaises(HarnessError):observe(link,full=True)
    def test_declared_large_input_can_complete_fixed_seven(self):
        f=Fixture();self.addCleanup(f.close)
        with (f.root/'large-input.bin').open('wb') as b:b.truncate(3*1024*1024)
        f.contract['evidence_paths'].append('large-input.bin');f.store.put(f.owner,'source_baseline',observe(f.root))
        self.assertTrue(f.complete()['complete'])
        self.assertEqual({},f.hooks.handle({**f.event,'hook_event_name':'Stop','last_assistant_message':'LUNASTRA_STATUS=TESTED'}))
    def test_full_preflight_does_not_hold_sqlite_writer_lock(self):
        f=Fixture();self.addCleanup(f.close);f.store.put(f.owner,'source_baseline',{'files':{},'complete':False,'reason':'scan_budget'})
        def check(root,**kwargs):
            self.assertFalse(f.store._shared is not None and f.store._shared.in_transaction)
            return observe(root,**kwargs)
        with patch('luna_astra.crew.observe',check):f.start()
        self.assertTrue(f.store.get(f.owner,'source_baseline')['complete'])
    def test_explicit_entry_budget_still_refuses_partial_fingerprint(self):
        (self.root/'a').mkdir();(self.root/'a/x').write_text('x')
        with self.assertRaises(HarnessError):fingerprint(self.root,['a'],max_entries=1)


class PackagingCorrectionTests(unittest.TestCase):
    def test_lf_launchers_are_canonicalized_without_source_write(self):
        self.assertEqual(b'@echo off\r\nexit /b 0\r\n',distribution_bytes('INSTALL.cmd',b'@echo off\nexit /b 0\n'))
    def test_crlf_normalization_is_idempotent(self):
        raw=b'@echo off\r\nexit /b 0\r\n';self.assertEqual(raw,distribution_bytes('CHECK.cmd',raw))
    def test_other_source_bytes_are_not_modified(self):
        raw=b'a\r\nb\n';self.assertEqual(raw,distribution_bytes('test.py',raw))
    def test_bare_carriage_return_is_rejected(self):
        with self.assertRaises(ValueError):distribution_bytes('bad.cmd',b'echo x\recho y')
    def test_git_checkout_recovers_crlf_from_lf_blobs(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);subprocess.run(['git','init','-q'],cwd=p,check=True)
            (p/'.gitattributes').write_bytes((PACKAGE/'.gitattributes').read_bytes());(p/'INSTALL.cmd').write_bytes(b'@echo off\nexit /b 0\n')
            subprocess.run(['git','-c','core.autocrlf=false','add','.'],cwd=p,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            (p/'INSTALL.cmd').unlink();subprocess.run(['git','checkout-index','-f','--','INSTALL.cmd'],cwd=p,check=True)
            self.assertEqual(b'@echo off\r\nexit /b 0\r\n',(p/'INSTALL.cmd').read_bytes())
    def test_build_from_lf_source_has_canonical_launchers_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'src';shutil.copytree(PACKAGE,root,ignore=shutil.ignore_patterns('.git','__pycache__','*.pyc'))
            for cmd in root.glob('*.cmd'):cmd.write_bytes(cmd.read_bytes().replace(b'\r\n',b'\n'))
            before=(root/'INSTALL.cmd').read_bytes();zip_path=Path(d)/'release.zip';result=build(zip_path,root)
            self.assertEqual('PASS',result['manifest']);self.assertEqual(before,(root/'INSTALL.cmd').read_bytes());self.assertEqual(result,verify(zip_path))


class ResearchRoundtripTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close)
        (self.f.root/'compute.py').write_text("from pathlib import Path\nPath('scratch').mkdir(exist_ok=True)\nPath('scratch/result.json').write_text('{\"score\":7}')\n")
        (self.f.root/'verify.py').write_text('pass\n')
        self.f.contract.update(mode='research',resources={'working':['scratch']})
        self.f.planning();self.f.dispatch();self.f.reports()
        self.r=Research(self.f.store,self.f.owner,PACKAGE);self.r.configure({'project':'correction'})
        self.job={'id':'case','argv':[sys.executable,'compute.py'],'verify_argv':[sys.executable,'verify.py'],
                  'dependencies':['input.txt','compute.py','verify.py'],'outputs':['scratch'],
                  'result_path':'scratch/result.json','score_key':'score','environment_keys':[]}
        self.nonce='c'*32
    def run_job(self):
        self.r.enqueue({'jobs':[self.job]})
        with self.f.store.db(True) as db:
            study=self.r._read(db);study.update(state='RUNNING',supervisor={'nonce':self.nonce});self.r._save(db,study)
        job=self.r._claim(self.nonce)
        return self.r._execute(job,self.nonce)
    def test_three_byte_backed_input_passes_after_enqueue(self):
        # enqueue + precompute + postcompute + final ingest, without the old
        # redundant verifier/ingest duplicate. No metadata-only persistent cache.
        with patch.object(self.r,'_context',wraps=self.r._context) as context:
            result=self.run_job()
        self.assertEqual('VERIFIED',result['state']);self.assertEqual(4,context.call_count)
        self.assertEqual(file_hash(self.f.root/'scratch/result.json'),result['result_sha256'])
    def test_verifier_mutation_of_result_is_stale(self):
        (self.f.root/'verify.py').write_text("from pathlib import Path\nPath('scratch/result.json').write_text('{\"score\":99}')\n")
        result=self.run_job();self.assertEqual('STALE',result['state']);self.assertIsNone(self.r.status()['best_verified_candidate'])
    def test_verifier_mutation_of_input_is_stale(self):
        (self.f.root/'verify.py').write_text("from pathlib import Path\nPath('input.txt').write_text('7,8')\n")
        self.assertEqual('STALE',self.run_job()['state'])
    def test_failed_verifier_is_not_promoted(self):
        (self.f.root/'verify.py').write_text('raise SystemExit(1)\n')
        self.assertEqual('FAILED',self.run_job()['state']);self.assertIsNone(self.r.status()['best_verified_candidate'])


class SnapshotBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'a').write_text('first');(self.root/'z').write_text('last')
    def changed(self,path):
        result=file_hash(path)
        if Path(path).name=='z':(self.root/'a').write_text('later mutation')
        return result
    def test_review_detects_late_modification_of_earlier_file(self):
        with patch('luna_astra.crew.file_hash',self.changed):
            with self.assertRaises(HarnessError):fingerprint(self.root,['a','z'])
    def test_dependency_detects_late_modification_of_earlier_file(self):
        from luna_astra.util import snapshot
        with patch('luna_astra.util.file_hash',self.changed):
            with self.assertRaises(HarnessError):snapshot(self.root,['a','z'])
    def test_missing_output_appearing_during_review_is_rejected(self):
        def changed(path):
            result=file_hash(path);(self.root/'output').write_text('appeared');return result
        with patch('luna_astra.crew.file_hash',changed):
            with self.assertRaises(HarnessError):fingerprint(self.root,['output','z'])
    def test_dependencies_hash_overlapping_paths_once(self):
        from luna_astra.util import snapshot
        (self.root/'data').mkdir();(self.root/'data/x').write_text('same')
        with patch('luna_astra.util.file_hash',wraps=file_hash) as hashed:
            result=snapshot(self.root,['data','data/x','data']);self.assertEqual(1,hashed.call_count)
        self.assertEqual({'data/':'DIRECTORY','data/x':file_hash(self.root/'data/x')},result)
    def test_dependency_walk_error_is_not_silently_certified(self):
        from luna_astra.util import snapshot
        (self.root/'data').mkdir()
        def broken(path,followlinks,onerror):
            onerror(PermissionError('cannot walk'));yield str(path),[],[]
        with patch('luna_astra.util.os.walk',broken):
            with self.assertRaises(HarnessError):snapshot(self.root,['data'])


class InstalledReceiptTests(unittest.TestCase):
    def setUp(self):
        import test_fixed_seven_integration as fixtures
        self.host=fixtures.InstalledFixedSevenTests(methodName='runTest')
        self.addCleanup(self.host.doCleanups);self.host.setUp()
        self.host.cli(['crew-start'],self.host.contract)
        self.call=self.host.cli(['crew-next'])['calls'][0]
        self.path=self.host.base/'transcript.jsonl';self.uid='installed-receipt'
        self.append({'type':'session_meta','payload':{'id':self.host.event['session_id']}})
    def append(self,record):
        with self.path.open('a',encoding='utf-8') as out:out.write(json.dumps(record)+'\n')
    def receipt(self,response):
        self.append({'type':'response_item','payload':{'type':'function_call','name':self.call['tool'],
                    'call_id':self.uid,'arguments':canonical(self.call['arguments'])}})
        out=self.host.hook({**self.host.event,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v1.'+self.call['tool'],
                 'tool_use_id':self.uid,'tool_input':self.call['arguments'],'transcript_path':str(self.path)})
        self.assertNotEqual('deny',out.get('hookSpecificOutput',{}).get('permissionDecision'),out)
        self.append({'type':'response_item','payload':{'type':'function_call_output','call_id':self.uid,'output':json.dumps(response)}})
    def helper(self,args):
        from luna_astra.transport import helper_command
        out=self.host.hook({**self.host.event,'hook_event_name':'PreToolUse','tool_name':'Bash','tool_use_id':'helper-'+args[0],
                           'tool_input':{'command':helper_command(self.host.prefix+args)}})
        self.assertNotEqual('deny',out.get('hookSpecificOutput',{}).get('permissionDecision'),out)
        return self.host.cli(args)
    def test_installed_reconcile_is_allowed_and_recovers_receipt(self):
        self.receipt({'agent_id':'real-fixture-id'})
        result=self.helper(['crew-reconcile']);self.assertEqual('ACK_RECOVERED',result['restored'][0]['state'])
        self.assertIn('crew-reconcile',self.host.cli(['help'])['commands'])
        for name,value in self.host.original.items():self.assertEqual(value,(self.host.home/name).read_bytes())
    def test_installed_retry_uses_same_ticket_after_exact_rejection(self):
        self.receipt('collab spawn failed: agent thread limit reached')
        self.helper(['crew-reconcile'])
        result=self.helper(['crew-retry','1','--reason','Observed capacity corrected'])
        self.assertEqual(self.call['ticket'],result['ticket']);self.assertFalse(result['new_agent_started'])
    def test_worker_cannot_run_root_receipt_commands(self):
        child={**self.host.event,'session_id':'a-child','agent_id':'a-child','hook_event_name':'SubagentStart'}
        prefix=self.host.get_prefix(self.host.hook(child))
        result=self.host.cli(['crew-reconcile'],prefix=prefix,code=1)
        self.assertIn('root',str(result))

class CertificationTimeoutTests(unittest.TestCase):
    def test_only_terminal_certification_gets_large_file_budget(self):
        from luna_astra.install import definition
        with tempfile.TemporaryDirectory() as d:
            for event in ('Stop','SubagentStop','PreToolUse','PostToolUse','SessionStart','Interrupt'):
                result=definition(Path(sys.executable),PACKAGE,Path(d),event)
                expected=300 if event in {'Stop','SubagentStop'} else 3 if event=='Interrupt' else 10
                self.assertEqual(expected,result['hooks'][0]['timeout'])
