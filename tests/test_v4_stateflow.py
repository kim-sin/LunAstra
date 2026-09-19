"""4.0 local behavior/security regressions. Native model events are simulated."""
from __future__ import annotations
import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout,redirect_stderr
from test_fixed_seven import Fixture,PACKAGE
from luna_astra import requests
from luna_astra.paths import relative_id,covers,uncovered
from luna_astra.prepare import prepare,registered_read
from luna_astra.transport import helper_command,literal_shell_input,literal_argv,read_source,read_bytes
from luna_astra.evidence import Evidence
from luna_astra.store import Store,evidence_directory
from luna_astra.util import HarnessError,canonical,json_hash
from luna_astra.flow import Flow
from luna_astra.controller import Controller
from luna_astra.blockers import freshness
from luna import main

class TempTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'project';self.root.mkdir();self.state=self.base/'state'
        self.owner='a'*64

class PathTests(TempTest):
    def test_windows_spelling_and_separator(self):
        self.assertEqual(relative_id('Project\\APP.js',windows=True),relative_id('project/app.js',windows=True))
    def test_posix_distinguishes_case(self):self.assertNotEqual(relative_id('APP.js',windows=False),relative_id('app.js',windows=False))
    def test_scope_segment_not_prefix(self):self.assertFalse(covers(self.root,'src','src-other/app.js'))
    def test_root_scope(self):self.assertTrue(covers(self.root,'.','src/app.js'))
    def test_relative_normalization(self):self.assertEqual('src/app.py',relative_id('./src//app.py',windows=False))
    def test_reject_escape_forms(self):
        for p in ('../a','a/../b','/a','C:/a','a\x00b','a\\b'):
            with self.subTest(p=p),self.assertRaises(HarnessError):relative_id(p,windows=False)
    def test_missing_output_can_be_scoped(self):self.assertEqual([],uncovered(self.root,['src/new.py'],['src']))
    def test_symlink_scope_is_not_access(self):
        outside=self.base/'outside';outside.mkdir();(self.root/'link').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(HarnessError):covers(self.root,'link','link/a')

class RequestTests(TempTest):
    def test_large_json_one_owner_bound_blob(self):
        raw=canonical({'text':'한글' * 30000});ref=requests.put(self.state,self.owner,raw)
        self.assertEqual(raw,requests.read(self.state,self.owner,ref));self.assertEqual(ref,requests.put(self.state,self.owner,raw))
    def test_64k_windows_single_short_command(self):
        prefix=[sys.executable,str(PACKAGE/'luna.py'),'--state',str(self.state),'--session',self.owner]
        raw=canonical({'text':'x'*65536})
        out=literal_shell_input(helper_command(prefix+['--input-json',raw,'note'],windows=True),prefix,windows=True)
        self.assertLess(len(out['command']),8000)
        decoded=base64.b64decode(out['command'].split('EncodedCommand ')[1]).decode('utf-16-le')
        self.assertIn('--input-ref sha256:',decoded);self.assertNotIn('input-append',decoded)
        self.assertEqual(1,len(list((self.state/'requests'/self.owner).glob('*.json'))))
    def test_posix_stages_once(self):
        prefix=[sys.executable,'luna.py','--state',str(self.state),'--session',self.owner]
        out=literal_shell_input(helper_command(prefix+['--input-json',canonical({'x':'y'*5000}),'note'],windows=False),prefix,windows=False)
        self.assertEqual('--input-ref',literal_argv(out['command'])[len(prefix)])
    def test_cross_owner_not_readable(self):
        ref=requests.put(self.state,self.owner,'{"a":1}')
        with self.assertRaises(HarnessError):requests.read(self.state,'b'*64,ref)
    def test_tampered_blob_rejected(self):
        ref=requests.put(self.state,self.owner,'{"a":1}')
        (self.state/'requests'/self.owner/(ref[7:]+'.json')).write_text('{}')
        with self.assertRaises(HarnessError):requests.read(self.state,self.owner,ref)
        with self.assertRaises(HarnessError):requests.put(self.state,self.owner,'{"a":1}')
    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):requests.put(self.state,self.owner,'{"a":1,"a":2}')
    def test_nonfinite_json_rejected(self):
        with self.assertRaises(ValueError):requests.put(self.state,self.owner,'{"a":NaN}')
    def test_oversize_rejected(self):
        with self.assertRaises(HarnessError):requests.put(self.state,self.owner,'x'*(requests.MAX_BYTES+1))
    def test_digest_traversal_rejected(self):
        with self.assertRaises(HarnessError):requests.read(self.state,self.owner,'sha256:../../data')
    def test_shell_operators_still_rejected(self):
        prefix=['python','luna.py','--state',str(self.state),'--session',self.owner]
        with self.assertRaises(HarnessError):literal_shell_input(helper_command(prefix,windows=True)+' status; echo x',prefix,windows=True)

class SourceTests(TempTest):
    def test_large_file_continued_read(self):
        (self.root/'large.txt').write_text(('a'*1000+'\n')*5000)
        result=read_source(self.root,'large.txt',4999,2)
        self.assertTrue(result['eof']);self.assertEqual(5000,result['total_lines'])
    def test_missing_code(self):
        with self.assertRaises(HarnessError) as caught:read_source(self.root,'missing.txt')
        self.assertEqual('SOURCE_NOT_FOUND',caught.exception.code)
    def test_directory_code(self):
        (self.root/'dir').mkdir()
        with self.assertRaises(HarnessError) as caught:read_source(self.root,'dir')
        self.assertEqual('SOURCE_NOT_REGULAR',caught.exception.code)
    def test_binary_not_silently_replaced(self):
        (self.root/'bad.txt').write_bytes(b'\xff')
        with self.assertRaises(HarnessError) as caught:read_source(self.root,'bad.txt')
        self.assertEqual('SOURCE_ENCODING_ERROR',caught.exception.code)
    def test_long_line_has_byte_fallback(self):
        content=b'x'*150000;(self.root/'long.txt').write_bytes(content)
        with self.assertRaises(HarnessError):read_source(self.root,'long.txt')
        a=read_bytes(self.root,'long.txt',0,64000);self.assertFalse(a['eof']);self.assertEqual(64000,a['next_offset'])
    def test_read_scope_escape(self):
        with self.assertRaises(HarnessError):read_source(self.root,'../outside.txt')
    def test_partial_read_not_claim_full_line_count(self):
        (self.root/'a').write_text('a\nb\nc\n');out=read_source(self.root,'a',1,1)
        self.assertFalse(out['eof']);self.assertIsNone(out['total_lines']);self.assertEqual(2,out['next_start_line'])

class PrepareTests(TempTest):
    def test_missing_outputs_valid(self):
        (self.root/'input.txt').write_text('source')
        r=prepare(self.root,{'required_inputs':['input.txt'],'outputs':['later.json']})
        self.assertFalse(r['source_content_read_by_model']);self.assertFalse(next(e for e in r['entries'] if e['role']=='outputs')['exists'])
    def test_missing_required_input_rejected(self):
        with self.assertRaises(HarnessError) as caught:prepare(self.root,{'required_inputs':['later.json'],'outputs':['later.json']})
        self.assertTrue(caught.exception.details['also_declared_output'])
    def test_optional_input_absent_valid(self):self.assertTrue(prepare(self.root,{'optional_inputs':['missing']})['registry_hash'])
    def test_wrong_workspace_rejected(self):
        with self.assertRaises(HarnessError) as caught:prepare(self.root,{},expected_workspace=str(self.base))
        self.assertEqual('WORKSPACE_MISMATCH',caught.exception.code)
    def test_protected_working_overlap_rejected(self):
        with self.assertRaises(HarnessError):prepare(self.root,{'working':['data'],'protected':['data/best.json']})
    def test_narrow_root_required(self):
        with self.assertRaises(HarnessError):prepare(self.root,{'working':['.']})
    def test_prepare_fails_before_native_reservation(self):
        f=Fixture();self.addCleanup(f.close);f.contract['evidence_paths']=['missing']
        with self.assertRaises(HarnessError):f.start()
        self.assertFalse(f.crew.status(f.owner)['configured'])
    def test_changed_mode_not_implicit_reuse(self):
        f=Fixture();self.addCleanup(f.close);f.start()
        with self.assertRaises(HarnessError):f.crew.start(f.owner,{**f.contract,'mode':'research'})
    def test_worker_source_registry_stays_scoped(self):
        f=Fixture();self.addCleanup(f.close);f.start();f.dispatch()
        registry=f.store.get(f.owner,'resource_registry');output=next(e for e in registry['entries'] if e['role']=='outputs')
        with self.assertRaises(HarnessError):registered_read(f.store,f.keys[1],output['id'])

class CacheTests(TempTest):
    def setUp(self):
        super().setUp();(self.root/'app.py').write_text('n=5\n');(self.root/'check.py').write_text('import app\nassert app.n==5\n')
        self.ev=Evidence(self.state,self.root)
        self.task={'task_id':'test','design':'check actual integer','requirements':['n is 5'],'checks':[
            {'id':'unit','purpose':'n assertion','argv':[sys.executable,'check.py'],'dependencies':['app.py','check.py'],'covers':[0],'reusable':True,'environment_keys':['LUNASTRA_TEST_ENV']}]}
        self.ev.begin(self.task);self.assertEqual('PASS',self.ev.run('unit')['status'])
    def test_display_metadata_reuses_execution(self):
        self.task['design']='same algorithm, spelling correction';self.ev.begin(self.task)
        out=self.ev.run_all();self.assertTrue(out['status']['passed']);self.assertTrue(out['status']['checks'][0]['reused_execution_from_task'])
        with self.ev._db() as db:self.assertEqual(1,db.execute('SELECT count(*) FROM attempts').fetchone()[0])
    def test_new_requirement_invalidates_cache(self):
        self.task['requirements']=['n is exactly 5 with a new contract'];self.ev.begin(self.task);self.assertFalse(self.ev.status()['passed'])
    def test_new_dependency_invalidates_cache(self):
        (self.root/'data').write_text('x');self.task['checks'][0]['dependencies'].append('data');self.ev.begin(self.task);self.assertFalse(self.ev.status()['passed'])
    def test_environment_invalidates_cache(self):
        with patch.dict(os.environ,{'LUNASTRA_TEST_ENV':'changed'}):self.assertFalse(self.ev.status()['passed'])
    def test_modified_log_invalidates_cache(self):
        with self.ev._db() as db:row=db.execute('SELECT stdout_path FROM attempts').fetchone()
        (self.state/row[0]).write_text('tampered');self.task['design']='display';self.ev.begin(self.task);self.assertFalse(self.ev.status()['passed'])
    def test_force_reexecutes(self):
        self.ev.run_all(reuse=False)
        with self.ev._db() as db:self.assertEqual(2,db.execute('SELECT count(*) FROM attempts').fetchone()[0])
    def test_newer_failure_not_reused_as_pass(self):
        (self.root/'app.py').write_text('n=4\n');self.ev.run('unit');(self.root/'app.py').write_text('n=5\n')
        self.task['design']='new label';self.ev.begin(self.task);self.assertFalse(self.ev.status()['passed'])

class CrewStepTests(unittest.TestCase):
    def setUp(self):self.f=Fixture();self.addCleanup(self.f.close);self.driver=Controller(self.f.store,PACKAGE)
    def test_step_start_is_not_model_launch(self):
        out=self.driver.step(self.f.owner);self.assertEqual('START',out['next']['action']);self.assertEqual([],out['calls'])
    def test_step_reserves_six_without_inventing_ack(self):
        self.f.start();out=self.driver.step(self.f.owner);self.assertEqual(6,len(out['calls']))
        self.assertEqual(0,self.f.crew.status(self.f.owner)['observed_children'])
    def test_batch_wait_same_six(self):
        self.f.start();self.f.dispatch();out=self.driver.step(self.f.owner)
        self.assertEqual(6,len(out['calls'][0]['arguments']['targets']));self.assertEqual('WAIT',out['next']['action'])
    def test_all_reports_one_response(self):
        self.f.start();self.f.dispatch();self.f.reports();out=self.driver.step(self.f.owner)
        self.assertEqual(6,len(out['reports']));self.assertFalse(out['automatic_semantic_approval'])
    def test_investigate_never_integrate(self):
        self.f.planning();self.f.dispatch();self.f.reports();out=self.driver.step(self.f.owner)
        self.assertNotIn('team-integrate',' '.join(out['legal_actions']))
    def test_review_repeat_same_snapshot_no_new_tickets(self):
        self.f.reviewing();before=self.f.crew.status(self.f.owner)
        out=self.f.crew.review(self.f.owner,'Rechecking identical reviewed snapshot')
        self.assertTrue(out['review_reused']);after=self.f.crew.status(self.f.owner)
        self.assertEqual(before['round'],after['round']);self.assertEqual([r['ticket'] for r in before['tasks']],[r['ticket'] for r in after['tasks']])
    def test_complete_repeat_is_idempotent(self):
        self.f.complete();out=self.f.crew.complete(self.f.owner,'same valid result');self.assertTrue(out['completion_reused'])
    def test_uncovered_change_blocks_before_complete(self):
        self.f.planning();self.f.dispatch();self.f.reports();self.f.checked_output();(self.f.root/'not-covered.txt').write_text('new')
        with self.assertRaises(HarnessError) as caught:self.f.crew.review(self.f.owner,'review requested')
        self.assertEqual('CHANGED_PATH_UNVERIFIED',caught.exception.code)
    def test_stale_blocker_rechecks_same_worker_not_all(self):
        self.f.planning();self.f.dispatch()
        state=self.f.crew.status(self.f.owner);row=state['tasks'][1]
        self.f.crew.report(self.f.keys[2],{'verdict':'blocked','blocker_kind':'INTERNAL_RECOVERABLE',
           'summary':'Output not generated yet','findings':['Waiting for actual output'],
           'references':[{'missing_path':'output.txt'}],'covers':[0]})
        for slot in range(1,7):
            if slot!=2:self.f.crew.report(self.f.keys[slot],{'verdict':'clear','summary':'Source checked',
                 'findings':['Input exists'],'references':[{'path':'input.txt'}],'covers':[0]})
            self.f.hooks.handle({**self.f.event,'session_id':f'child-{slot}','agent_id':f'child-{slot}',
                 'hook_event_name':'SubagentStop','last_assistant_message':'LUNASTRA_STATUS=ANALYSIS'})
        flow=Flow(self.f.store,PACKAGE)
        flow.pre_wait(self.f.owner,'native-finish',{'targets':['child-2']})
        flow.post_wait(self.f.owner,'native-finish',{'status':{'child-2':{'completed':'done'}}})
        report=self.f.crew.status(self.f.owner)['reports'][row['ticket']]
        self.assertEqual('CURRENT',freshness(self.f.store,row['ticket'],report,state['requirements'])['state'])
        self.assertEqual('BLOCKED',flow.drive(self.f.owner)['action'])
        (self.f.root/'output.txt').write_text('5')
        out=self.driver.step(self.f.owner);self.assertEqual('REASSESS',out['next']['action']);self.assertEqual('child-2',out['calls'][0]['arguments']['target'])
        call=out['calls'][0];self.f.crew.pre_dispatch(self.f.owner,'reassess',call['arguments'],self.f.event['model'],call['tool'])
        self.f.crew.post_dispatch(self.f.owner,'reassess',{'submission_id':'same-worker'})
        self.assertNotIn(row['ticket'],self.f.crew.status(self.f.owner)['reports'])
        with self.f.store.db() as db:self.assertTrue(db.execute("SELECT 1 FROM blocker_history WHERE state='RECHECKING'").fetchone())
        self.assertFalse(self.f.crew.summary(self.f.owner)['complete'])
    def test_missing_reference_cannot_be_forged(self):
        self.f.start();self.f.dispatch()
        with self.assertRaises(HarnessError):self.f.crew.report(self.f.keys[1],{'verdict':'blocked','summary':'False absence','findings':[], 'references':[{'missing_path':'input.txt'}],'covers':[0]})
    def test_legacy_opaque_batch_status_falls_back_without_guess(self):
        self.f.start();self.f.dispatch();flow=Flow(self.f.store,PACKAGE)
        flow.pre_wait(self.f.owner,'batch',{'targets':['child-1','child-2']})
        flow.post_wait(self.f.owner,'batch',{'status':{'/a':{'completed':'x'},'/b':{'completed':'y'}}})
        self.assertEqual(['child-1'],flow.drive(self.f.owner)['native_call']['arguments']['targets'])
        self.assertEqual('running',self.f.crew.status(self.f.owner)['tasks'][0]['state'])
    def test_cli_workspace_mismatch(self):
        self.f.start();out=io.StringIO()
        with redirect_stdout(out),redirect_stderr(out):code=main(['--state',str(self.f.state),'--session',self.f.owner,'--workspace',str(self.f.base),'crew-state'])
        self.assertEqual(1,code);self.assertIn('WORKSPACE_MISMATCH',out.getvalue())

if __name__=='__main__':unittest.main()
