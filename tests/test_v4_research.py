"""Actual local queue subprocess tests; no native model/API execution."""
from __future__ import annotations
import copy
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from contextlib import redirect_stdout,redirect_stderr
from test_fixed_seven import Fixture,PACKAGE
from luna_astra.research import Research
from luna_astra.flow import Flow
from luna_astra.util import HarnessError,canonical
from luna_astra.removal import _active_records
from luna import main

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close)
        (self.f.root/'compute.py').write_text("from pathlib import Path\nimport json,sys,time\ntime.sleep(float(sys.argv[3]) if len(sys.argv)>3 else 0)\np=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'score':int(sys.argv[2])}))\n")
        (self.f.root/'verify.py').write_text("from pathlib import Path\nimport json,sys\nassert json.loads(Path(sys.argv[1]).read_text())['score']>=5\n")
        self.f.contract.update(mode='research',resources={'required_inputs':['input.txt'],'outputs':['output.txt'],'working':['scratch']})
        self.f.planning();self.f.dispatch();self.f.reports()
        self.r=Research(self.f.store,self.f.owner,PACKAGE)
        self.r.configure({'project':'test','workers':2,'direction':'max','metric_unit':'ticks'})
        self.addCleanup(self.drain)
    def drain(self):
        s=self.r.status()
        if s.get('state') in {'STARTING','RUNNING','PAUSING'}:
            # This test cleanup only requests cooperative pause and waits for real exit.
            with self.r.store.db(True) as db:
                value=self.r._read(db);value['state']='PAUSING';self.r._save(db,value)
            limit=time.monotonic()+15
            while time.monotonic()<limit and self.r.status()['state']!='PAUSED':time.sleep(.1)
            if self.r.status()['state']!='PAUSED':raise AssertionError('test controller did not drain')
    def job(self,name='first',score=5,delay=0):
        output='scratch/'+name+'.json'
        return {'id':name,'argv':[sys.executable,'compute.py',output,str(score),str(delay)],
                'verify_argv':[sys.executable,'verify.py',output], 'dependencies':['input.txt','compute.py','verify.py'],
                'outputs':[output],'result_path':output,'score_key':'score'}
    def wait_terminal(self,n=1):
        limit=time.monotonic()+15
        while time.monotonic()<limit:
            s=self.r.status()
            if sum(s['counts'][k] for k in ('VERIFIED','FAILED','STALE','ERROR'))>=n:return s
            time.sleep(.1)
        self.fail('local jobs did not finish: '+str(self.r.status()))
    def direct(self,job):
        self.r.enqueue({'jobs':[job]});nonce='c'*32
        with self.f.store.db(True) as db:
            s=self.r._read(db);s.update(state='RUNNING',supervisor={'nonce':nonce,'heartbeat':time.time()});self.r._save(db,s)
        claimed=self.r._claim(nonce);self.assertIsNotNone(claimed)
        result=self.r._execute(claimed,nonce)
        with self.f.store.db(True) as db:s=self.r._read(db);s['state']='PAUSED';self.r._save(db,s)
        return result
    def test_explicit_mode_required(self):
        f=Fixture();self.addCleanup(f.close);f.planning()
        with self.assertRaises(HarnessError):Research(f.store,f.owner,PACKAGE).configure({'project':'other'})
    def test_actual_compute_and_independent_verifier(self):
        out=self.direct(self.job());self.assertEqual('VERIFIED',out['state']);self.assertEqual('5',out['score'])
        self.assertEqual(0,out['execute_exit_code']);self.assertEqual(0,out['verify_exit_code']);self.assertFalse(out['authority_promoted'])
    def test_failed_verifier_not_promoted(self):
        out=self.direct(self.job(score=4));self.assertEqual('FAILED',out['state']);self.assertIsNone(self.r.status()['best_verified_candidate'])
    def test_persistent_queue_pause_resume_real_process(self):
        self.r.enqueue({'jobs':[self.job('one',5),self.job('two',8)]});first=self.r.start()
        second=self.r.start();self.assertTrue(second['existing_controller_preserved'])
        out=self.wait_terminal(2);self.assertEqual('two',out['best_verified_candidate']['id'])
        self.r.pause();self.drain();self.assertEqual('PAUSED',self.r.status()['state'])
        self.r.enqueue({'jobs':[self.job('three',7)]});resumed=self.r.start();self.assertNotEqual(first['nonce'],resumed['nonce'])
        out=self.wait_terminal(3);self.assertEqual('two',out['best_verified_candidate']['id'])
        self.r.pause();self.drain();self.assertEqual('FINISHED',self.r.pause(finish=True)['state'])
    def test_failure_does_not_stop_independent_job(self):
        self.r.enqueue({'jobs':[self.job('bad',1),self.job('good',9)]});self.r.start();out=self.wait_terminal(2)
        self.assertEqual(1,out['counts']['FAILED']);self.assertEqual(1,out['counts']['VERIFIED'])
    def test_protect_existing_output(self):
        (self.f.root/'scratch').mkdir();(self.f.root/'scratch/first.json').write_text('original')
        with self.assertRaises(HarnessError):self.r.enqueue({'jobs':[self.job()]})
        self.assertEqual('original',(self.f.root/'scratch/first.json').read_text())
    def test_protect_output_that_appears_after_enqueue(self):
        self.r.enqueue({'jobs':[self.job()]});(self.f.root/'scratch').mkdir();(self.f.root/'scratch/first.json').write_text('original')
        self.r.start();out=self.wait_terminal();self.assertEqual(1,out['counts']['ERROR']);self.assertEqual('original',(self.f.root/'scratch/first.json').read_text())
    def test_retry_enqueue_same_id_is_not_duplicate(self):
        self.r.enqueue({'jobs':[self.job()]});out=self.r.enqueue({'jobs':[self.job()]})
        self.assertEqual(0,out['enqueued']);self.assertEqual(1,out['duplicates_reused'])
    def test_same_id_changed_definition_rejected(self):
        self.r.enqueue({'jobs':[self.job()]})
        with self.assertRaises(HarnessError):self.r.enqueue({'jobs':[self.job(score=6)]})
    def test_overlapping_outputs_rejected(self):
        first=self.job();second={**self.job('second'),'outputs':first['outputs'],'result_path':first['result_path']}
        with self.assertRaises(HarnessError):self.r.enqueue({'jobs':[first,second]})
    def test_wrong_output_scope_rejected(self):
        job=self.job();job.update(outputs=['input.txt'],result_path='input.txt')
        with self.assertRaises(HarnessError):self.r.enqueue({'jobs':[job]})
    def test_cycle_rejected(self):
        a=self.job('a');b=self.job('b');a['depends_on']=['b'];b['depends_on']=['a']
        with self.assertRaises(HarnessError):self.r.enqueue({'jobs':[a,b]})
    def test_missing_dependency_rejected(self):
        a=self.job();a['dependencies'].append('missing')
        with self.assertRaises(HarnessError):self.r.enqueue({'jobs':[a]})
    def test_cancel_only_pending(self):
        self.r.enqueue({'jobs':[self.job()]});self.r.cancel({'ids':['first'],'reason':'explicit plan changed'})
        self.assertEqual(1,self.r.status()['counts']['CANCELLED'])
        self.assertEqual('FINISHED',self.r.pause(finish=True)['state'])
    def test_no_finish_pending_queue(self):
        self.r.enqueue({'jobs':[self.job()]})
        with self.assertRaises(HarnessError):self.r.pause(finish=True)
    def test_active_pause_drains_not_kills(self):
        self.r.enqueue({'jobs':[self.job(delay=.5)]});self.r.start()
        limit=time.monotonic()+10
        while time.monotonic()<limit and not self.r.status()['counts']['RUNNING']:time.sleep(.05)
        self.r.pause();self.drain();out=self.r.status();self.assertEqual(1,out['counts']['VERIFIED']);self.assertEqual('PAUSED',out['state'])
    def test_changed_request_pauses_without_launch(self):
        self.r.enqueue({'jobs':[self.job()]})
        with self.f.store.db(True) as db:
            s=self.r._read(db);s.update(state='RUNNING',supervisor={'nonce':'c'*32});self.r._save(db,s)
        self.f.store.put(self.f.owner,'request_hash','new-request')
        self.assertIsNone(self.r._claim('c'*32))
        with self.f.store.db(True) as db:s=self.r._read(db);self.assertEqual('PAUSING',s['state']);s['state']='PAUSED';self.r._save(db,s)
    def test_wrong_supervisor_never_claims(self):
        self.r.enqueue({'jobs':[self.job()]})
        self.assertIsNone(self.r._claim('wrong'))
    def test_ui_state_identifies_research(self):
        self.assertEqual('RESEARCH',Flow(self.f.store,PACKAGE).drive(self.f.owner)['action'])
    def test_cli_root_only(self):
        out=io.StringIO()
        with redirect_stdout(out),redirect_stderr(out):code=main(['--state',str(self.f.state),'--session',self.f.keys[1],'research-start'])
        self.assertEqual(1,code);self.assertIn('only the observed root',out.getvalue())
    def test_checkpoint_review_resumes_same_six(self):
        ev=self.f.checked_output()
        with ev._db() as db:task=ev._get(db,'task')
        # These fixture scripts were created after the initial source baseline;
        # bind them to the checkpoint instead of ignoring unverified changes.
        task['checks'][0]['dependencies']+=['compute.py','verify.py']
        task['checks'][0]['argv'][2]+="; import ast; ast.parse(Path('compute.py').read_text()); ast.parse(Path('verify.py').read_text())"
        ev.begin(task);self.assertTrue(ev.run_all()['status']['passed'])
        self.f.crew.review(self.f.owner,'Review current research checkpoint')
        self.f.dispatch();self.f.reports()
        before=self.f.crew.status(self.f.owner)
        out=self.r.resume_checkpoint({'decision':'Continue the same study after verified checkpoint','tasks':self.f.tasks()})
        self.assertTrue(out['resumed'])
        after=self.f.crew.status(self.f.owner)
        self.assertEqual('EXECUTE',after['phase']);self.assertEqual(before['run_id'],after['run_id'])
        self.assertEqual([m['agent_id'] for m in before['members']],[m['agent_id'] for m in after['members']])
    def test_review_while_controller_running_refused(self):
        self.r.enqueue({'jobs':[self.job(delay=.1)]});self.r.start();self.f.checked_output()
        with self.assertRaises(HarnessError) as caught:self.f.crew.review(self.f.owner,'Premature review')
        self.assertEqual('RESEARCH_ACTIVE',caught.exception.code)
    def test_pause_allowed_after_new_user_request(self):
        self.f.store.put(self.f.owner,'request_hash','user-stop')
        self.assertEqual('PAUSED',self.r.pause()['state'])

    def test_nan_is_not_result(self):
        (self.f.root/'compute.py').write_text("from pathlib import Path\nimport sys\np=Path(sys.argv[1]);p.parent.mkdir(exist_ok=True);p.write_text('{\"score\":NaN}')\n")
        (self.f.root/'verify.py').write_text('pass\n')
        out=self.direct(self.job());self.assertEqual('ERROR',out['state']);self.assertIsNone(self.r.status()['best_verified_candidate'])
    def test_stable_large_integer_not_rounded(self):
        out=self.direct(self.job(score=9007199254740993));self.assertEqual('9007199254740993',out['score'])

if __name__=='__main__':unittest.main()
