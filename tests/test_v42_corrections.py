"""Independent failure-boundary regressions for batchflow.2; no model calls."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest
from unittest.mock import patch, MagicMock
from test_fixed_seven import Fixture, PACKAGE
from luna_astra.controller import Controller
from luna_astra.flow import Flow
from luna_astra.native import configuration, dispatch, spawn_target, require_capacity
from luna_astra.process_identity import probe
from luna_astra.research import Research
from luna_astra.scan import observe, require_complete
from luna_astra.util import HarnessError, canonical, json_hash


class NativeCorrectionTests(unittest.TestCase):
    def state(self,capacity=7):
        return {'run_id':'b'*32,'native':{'protocol':'v2','context':'capsule','capacity_total':capacity}}
    def test_generated_name_obeys_independent_host_grammar(self):
        for slot in range(1,7):
            args=dispatch(self.state(),slot,'task')[1]
            self.assertRegex(args['task_name'],r'^[a-z0-9_]+$')
            self.assertNotEqual('root',args['task_name'])
    def test_names_are_distinct_across_slots_and_runs(self):
        a=[dispatch(self.state(),n,'m')[1]['task_name'] for n in range(1,7)]
        b=dispatch({**self.state(),'run_id':'c'*32},1,'m')[1]['task_name']
        self.assertEqual(7,len(set(a+[b])))
    def test_hyphen_ack_and_wrong_canonical_root_rejected(self):
        name=dispatch(self.state(),1,'m')[1]['task_name']
        for value in ('/root/'+name.replace('_','-'),'/other/'+name,'/root/root/'+name,'/root/../'+name):
            self.assertIsNone(spawn_target(self.state(),1,{'task_name':value}))
        self.assertEqual('/root/'+name,spawn_target(self.state(),1,{'task_name':'/root/'+name}))
    def test_unknown_v2_capacity_is_not_assumed(self):
        state=self.state();del state['native']['capacity_total']
        with self.assertRaises(HarnessError) as caught:dispatch(state,1,'m')
        self.assertEqual('NATIVE_CAPACITY_UNKNOWN',caught.exception.code)
    def test_total_capacity_includes_root(self):
        for capacity in (1,3,4,6):
            with self.assertRaises(HarnessError) as caught:dispatch(self.state(capacity),1,'m')
            self.assertEqual('NATIVE_CAPACITY_INSUFFICIENT',caught.exception.code)
            self.assertEqual(7,caught.exception.details['required_total'])
            self.assertFalse(caught.exception.details['settings_changed'])
        self.assertEqual('spawn_agent',dispatch(self.state(7),1,'m')[0])
    def test_invalid_capacity_no_coercion(self):
        for value in (None,True,7.0,'7',0,-1,1025):
            with self.subTest(value=value),self.assertRaises(HarnessError):configuration({'protocol':'v2','capacity_total':value})
    def test_preflight_capacity_does_not_create_a_crew(self):
        f=Fixture();self.addCleanup(f.close);f.contract['native']={'protocol':'v2','context':'capsule','capacity_total':4}
        before=copy.deepcopy(f.store.get(f.owner,'meta'))
        with self.assertRaises(HarnessError):f.start()
        self.assertFalse(f.crew.status(f.owner)['configured']);self.assertEqual(before,f.store.get(f.owner,'meta'))
        self.assertEqual([],f.calls)
    def test_v1_behavior_without_capacity_preserved(self):
        state={'run_id':'a'*32,'native':{'protocol':'v1','context':'capsule'}}
        self.assertFalse(dispatch(state,1,'m')[1]['fork_context'])
        self.assertNotIn('capacity_total',configuration())

    def test_existing_v2_capacity_observation_preserves_roster(self):
        from test_v42_native import V2Fixture
        f=V2Fixture();self.addCleanup(f.close);f.start();f.dispatch()
        before=f.crew.status(f.owner)
        # Simulate a saved pre-fix V2 contract, not an invented live host field.
        with f.store.db(True) as db:
            from luna_astra.crew import _get,_put
            state=_get(db,f.owner);state['native'].pop('capacity_total');_put(db,f.owner,state)
        result=f.crew.capacity(f.owner,{'capacity_total':7,'evidence':'Synthetic host capacity fixture; not a live observation'})
        after=f.crew.status(f.owner)
        self.assertEqual(before['members'],after['members'])
        for key in ('plan_id','run_id','round','phase'):self.assertEqual(before[key],after[key])
        self.assertFalse(result['settings_changed']);self.assertFalse(result['independently_attested'])
    def test_decreased_capacity_blocks_new_dispatch_without_killing_workers(self):
        from test_v42_native import V2Fixture
        f=V2Fixture();self.addCleanup(f.close);f.start();f.dispatch();before=f.crew.status(f.owner)['members']
        result=f.crew.capacity(f.owner,{'capacity_total':4,'evidence':'Synthetic reduced host limit'})
        self.assertEqual('NATIVE_CAPACITY_INSUFFICIENT',result['problem']['code'])
        self.assertEqual(before,f.crew.status(f.owner)['members'])
        with self.assertRaises(HarnessError):dispatch(f.crew.status(f.owner),1,'follow-up','/root/existing')
    def test_capacity_observation_requires_root_and_nonempty_evidence(self):
        from test_v42_native import V2Fixture
        f=V2Fixture();self.addCleanup(f.close);f.start();f.dispatch()
        for data in ({'capacity_total':7},{'capacity_total':7,'evidence':''},{'capacity_total':True,'evidence':'fixture'}):
            with self.subTest(data=data),self.assertRaises(HarnessError):f.crew.capacity(f.owner,data)
        with self.assertRaises(HarnessError):f.crew.capacity(f.keys[1],{'capacity_total':7,'evidence':'fixture'})
    def test_new_helper_names_validate_as_literal_helpers(self):
        from luna_astra.transport import validate_worker_shell,helper_command
        root='/tmp/fake-state';key='a'*64
        base=[sys.executable,str(PACKAGE/'luna.py'),'--state',root,'--session',key]
        for cmd in ('research-recover','crew-capacity'):
            command=helper_command(base+[cmd])
            self.assertEqual(cmd,validate_worker_shell(command,base,joined=True))


class ReportCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close)
        self.f.start();self.f.dispatch();self.f.reports()
    def change(self,slot=1,**fields):
        state=self.f.crew.status(self.f.owner);row=next(r for r in state['tasks'] if r['id']==f's{slot}')
        report={**state['reports'][row['ticket']],**fields}
        with self.f.store.db(True) as db:db.execute('UPDATE crew_reports SET body=? WHERE ticket=?',(canonical(report),row['ticket']))
        return row,report
    def test_issue_report_cannot_skip_full_retrieval(self):
        self.change(verdict='issues')
        with self.assertRaises(HarnessError) as caught:self.f.execute()
        self.assertEqual('REPORT_DETAILS_REQUIRED',caught.exception.code)
        self.assertEqual('PLAN',self.f.crew.status(self.f.owner)['phase'])
    def test_truncated_clear_report_also_requires_full_retrieval(self):
        self.change(summary='x'*513)
        with self.assertRaises(HarnessError):self.f.execute()
    def test_flow_provides_read_action_not_another_wrong_transition(self):
        self.change(verdict='issues')
        self.assertEqual('READ_REPORTS',Flow(self.f.store,PACKAGE).drive(self.f.owner)['action'])
    def test_digest_does_not_count_as_full_read(self):
        self.change(verdict='issues');Controller(self.f.store,PACKAGE).step(self.f.owner)
        self.assertEqual(['s1'],self.f.crew.pending_report_details(self.f.owner))
    def test_current_full_read_unblocks_transition(self):
        self.change(verdict='issues')
        self.f.crew.read_report(self.f.owner,1)
        self.assertEqual('EXECUTE',self.f.execute()['phase'])
    def test_batch_full_details_can_supply_six_short_reports_once(self):
        for n in range(1,7):self.change(n,verdict='issues')
        result=Controller(self.f.store,PACKAGE).step(self.f.owner,details=True)
        self.assertEqual(6,len(result['reports']));self.assertEqual([],result['remaining_required_reports'])
        self.assertEqual('EXECUTE',self.f.execute()['phase'])
    def test_long_full_reports_are_bounded_and_unread_remainder_stays_gated(self):
        for n in range(1,7):self.change(n,summary='s'*3500,findings=['f'*1800]*3)
        result=Controller(self.f.store,PACKAGE).step(self.f.owner,details=True)
        self.assertLess(len(canonical(result['reports'])),14500)
        self.assertTrue(result['remaining_required_reports'])
        with self.assertRaises(HarnessError):self.f.execute()
        for _ in range(6):
            result=Controller(self.f.store,PACKAGE).step(self.f.owner,details=True)
            if not result['remaining_required_reports']:break
        self.assertFalse(result['remaining_required_reports']);self.assertEqual('EXECUTE',self.f.execute()['phase'])
    def test_changed_report_invalidates_old_receipt(self):
        self.change(verdict='issues');self.f.crew.read_report(self.f.owner,1)
        self.change(verdict='issues',summary='new evidence after read')
        with self.assertRaises(HarnessError):self.f.execute()
    def test_wrong_worker_cannot_record_root_retrieval(self):
        self.change(verdict='issues')
        with self.assertRaises(HarnessError):self.f.crew.read_report(self.f.keys[1],1)
        self.assertEqual(['s1'],self.f.crew.pending_report_details(self.f.owner))
    def test_unmodified_short_clear_reports_need_no_extra_read(self):
        self.assertEqual([],self.f.crew.pending_report_details(self.f.owner))
        self.assertEqual('EXECUTE',self.f.execute()['phase'])
    def test_report_change_between_snapshot_and_accept_is_rejected(self):
        snapshot=self.f.crew.status(self.f.owner)
        self.change(summary='changed even though short and clear')
        with self.assertRaises(HarnessError):
            with self.f.store.db(True) as db:self.f.crew._accept_round(db,self.f.owner,snapshot,'accept')
    def test_blocked_report_read_is_not_an_approval(self):
        self.change(verdict='blocked');self.f.crew.read_report(self.f.owner,1)
        with self.assertRaisesRegex(HarnessError,'unresolved reviewer'):self.f.execute()
    def test_targeted_repair_must_read_current_issue(self):
        self.f.execute();self.f.dispatch();self.f.reports()
        self.change(verdict='issues')
        with self.assertRaises(HarnessError):self.f.crew.execute(self.f.owner,{'decision':'repair','tasks':self.f.tasks()},repair=True)
        self.f.crew.read_report(self.f.owner,1)
        self.assertEqual('EXECUTE',self.f.crew.execute(self.f.owner,{'decision':'repair','tasks':self.f.tasks()},repair=True)['phase'])


class ObservationCorrectionTests(unittest.TestCase):
    def setUp(self):self.f=Fixture();self.addCleanup(self.f.close)
    def test_large_unreported_file_invalidates_current_completion(self):
        self.f.complete();(self.f.root/'large.bin').write_bytes(b'x'*(2*1024*1024+1))
        self.assertFalse(observe(self.f.root)['complete'])
        self.assertIn('incomplete',self.f.crew.completion_problem(self.f.owner))
        self.assertFalse(self.f.crew.summary(self.f.owner)['complete'])
    def test_partial_baseline_cannot_be_certified(self):
        self.f.complete();base=self.f.store.get(self.f.owner,'source_baseline');base['complete']=False
        self.f.store.put(self.f.owner,'source_baseline',base)
        self.assertIn('baseline',self.f.crew.completion_problem(self.f.owner))
    def test_missing_baseline_not_silently_accepted(self):
        self.f.complete();self.f.store.put(self.f.owner,'source_baseline',None)
        self.assertIn('baseline',self.f.crew.completion_problem(self.f.owner))
    def test_scan_budget_uncertainty_is_not_success(self):
        self.f.complete()
        with patch('luna_astra.crew.observe',return_value={'files':{},'complete':False,'reason':'scan_budget'}):
            self.assertIn('scan_budget',self.f.crew.completion_problem(self.f.owner))
    def test_false_complete_types_are_rejected(self):
        for value in (None,{}, {'complete':1},{'complete':'true'},{'complete':False}):
            with self.assertRaises(HarnessError):require_complete(value,{'complete':True})
    def test_complete_observations_remain_accepted(self):
        self.assertTrue(self.f.complete()['complete'])
        self.assertIsNone(self.f.crew.completion_problem(self.f.owner))
    def test_explicit_test_results_remain_saved_after_coverage_failure(self):
        self.f.complete();(self.f.root/'large.bin').write_bytes(b'x'*(2*1024*1024+1))
        before=self.f.crew.status(self.f.owner)['proof']
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
        self.assertEqual(before,self.f.crew.status(self.f.owner)['proof'])
    def test_stop_and_complete_agree_on_partial_observation(self):
        self.f.complete();(self.f.root/'large.bin').write_bytes(b'x'*(2*1024*1024+1))
        out=self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop','last_assistant_message':'LUNASTRA_STATUS=TESTED'})
        self.assertTrue(out);self.assertFalse(self.f.crew.summary(self.f.owner)['complete'])


class ResearchCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close)
        (self.f.root/'compute.py').write_text("from pathlib import Path\nPath('scratch').mkdir(exist_ok=True)\nPath('scratch/result.json').write_text('{\"score\":7}')\nPath('scratch/ran').write_text('ran')\n")
        (self.f.root/'verify.py').write_text('pass\n')
        self.f.contract.update(mode='research',resources={'working':['scratch']})
        self.f.planning();self.f.dispatch();self.f.reports()
        self.r=Research(self.f.store,self.f.owner,PACKAGE);self.r.configure({'project':'regression'})
        self.job={'id':'case','argv':[sys.executable,'compute.py'],'verify_argv':[sys.executable,'verify.py'],
                  'dependencies':['input.txt','compute.py','verify.py'],'outputs':['scratch'],
                  'result_path':'scratch/result.json','score_key':'score','environment_keys':['LUNASTRA_TEST_DATA_VERSION']}
        self.r.enqueue({'jobs':[self.job]});self.nonce='d'*32
    def controller(self,pid=None,state='RUNNING',identity=None):
        with self.f.store.db(True) as db:
            study=self.r._read(db)
            study.update(state=state,supervisor={'nonce':self.nonce,'pid':os.getpid() if pid is None else pid,
                                              'process_identity':identity,'heartbeat':time.time()-3600,'started_at':time.time()-4000})
            self.r._save(db,study)
    def dead(self):
        p=subprocess.Popen([sys.executable,'-c','pass']);p.wait();return p.pid
    def execute(self):
        self.controller();job=self.r._claim(self.nonce);return self.r._execute(job,self.nonce)
    def test_stale_source_rejected_before_compute(self):
        (self.f.root/'input.txt').write_text('changed')
        result=self.execute();self.assertEqual('STALE',result['state'])
        self.assertEqual('PREFLIGHT',result['stage']);self.assertFalse((self.f.root/'scratch').exists())
        self.assertIsNone(self.r.status()['best_verified_candidate'])
    def test_same_size_mtime_changed_bytes_rejected_before_compute(self):
        p=self.f.root/'input.txt';st=p.stat();p.write_bytes(b'x'*st.st_size);os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.assertEqual('STALE',self.execute()['state']);self.assertFalse((self.f.root/'scratch').exists())
    def test_changed_compute_program_rejected_before_compute(self):
        p=self.f.root/'compute.py';p.write_text(p.read_text()+'# changed\n')
        self.assertEqual('STALE',self.execute()['state']);self.assertFalse((self.f.root/'scratch').exists())
    def test_changed_environment_rejected_before_compute(self):
        with patch.dict(os.environ,{'LUNASTRA_TEST_DATA_VERSION':'different'}):
            self.assertEqual('STALE',self.execute()['state'])
        self.assertFalse((self.f.root/'scratch').exists())
    def test_unchanged_input_executes_and_verifies(self):
        self.assertEqual('VERIFIED',self.execute()['state']);self.assertTrue((self.f.root/'scratch/ran').exists())
    def test_post_compute_mutation_still_rejected(self):
        # Enqueue a deliberately mutating computation before its snapshot is taken.
        f=Fixture();self.addCleanup(f.close)
        (f.root/'compute.py').write_text("from pathlib import Path\nPath('scratch').mkdir()\nPath('scratch/r.json').write_text('{\"score\":7}')\nPath('input.txt').write_text('changed')\n")
        (f.root/'verify.py').write_text('pass\n');f.contract.update(mode='research',resources={'working':['scratch']})
        f.planning();f.dispatch();f.reports();r=Research(f.store,f.owner,PACKAGE);r.configure({'project':'mutation'})
        r.enqueue({'jobs':[{**self.job,'result_path':'scratch/r.json'}]})
        with f.store.db(True) as db:
            s=r._read(db);s.update(state='RUNNING',supervisor={'nonce':self.nonce,'pid':os.getpid()});r._save(db,s)
        self.assertEqual('STALE',r._execute(r._claim(self.nonce),self.nonce)['state'])
    def test_dead_idle_controller_recovers_pending_without_replay(self):
        self.controller(self.dead());out=self.r.recover()
        self.assertTrue(out['recovered']);self.assertEqual('PAUSED',self.r.status()['state'])
        self.assertEqual(1,self.r.status()['counts']['PENDING']);self.assertFalse(out['jobs_replayed'])
    def test_corrupt_controller_identity_preserves_live_process_and_study(self):
        for value in ('',[],{},5):
            with self.subTest(value=value):
                self.controller(identity=value);out=self.r.recover()
                self.assertFalse(out['recovered']);self.assertEqual('UNKNOWN',out['controller']['state'])
                self.assertEqual('RUNNING',self.r.status()['state'])
    def test_slow_live_controller_is_not_recovered(self):
        self.controller();before=self.r.read_job('case');out=self.r.recover()
        self.assertFalse(out['recovered']);self.assertEqual('ALIVE',out['controller']['state'])
        self.assertEqual(before,self.r.read_job('case'));self.assertEqual('RUNNING',self.r.status()['state'])
    def test_unknown_controller_pid_is_not_assumed_dead(self):
        self.controller()
        with self.f.store.db(True) as db:
            s=self.r._read(db);s['supervisor']['pid']=None;self.r._save(db,s)
        self.assertFalse(self.r.recover()['recovered']);self.assertEqual('RUNNING',self.r.status()['state'])
    def test_dead_controller_with_live_orphan_is_preserved(self):
        self.controller(self.dead());self.r._claim(self.nonce)
        self.r._record('case',{'pid':os.getpid(),'process_identity':probe(os.getpid())['identity'],'stage':'execute'},self.nonce)
        out=self.r.recover();self.assertEqual('ORPHAN_JOB_UNRESOLVED',out['code'])
        self.assertEqual('RUNNING',self.r.read_job('case')['state'])
    def test_dead_controller_and_dead_job_retained_as_error(self):
        self.controller(self.dead());self.r._claim(self.nonce)
        (self.f.root/'scratch').mkdir();(self.f.root/'scratch/preserved.txt').write_text('keep')
        self.r._record('case',{'pid':self.dead(),'stage':'execute'},self.nonce)
        out=self.r.recover();self.assertTrue(out['recovered']);self.assertEqual('ERROR',self.r.read_job('case')['state'])
        self.assertEqual('keep',(self.f.root/'scratch/preserved.txt').read_text())
        self.assertIsNone(self.r.status()['best_verified_candidate'])
        self.assertEqual(1,self.r.status()['counts']['ERROR'])
    def test_never_launched_claim_can_be_closed_without_replay(self):
        self.controller(self.dead());self.r._claim(self.nonce)
        self.assertTrue(self.r.recover()['recovered']);self.assertEqual('ERROR',self.r.read_job('case')['state'])
    def test_launch_gap_unknown_pid_is_not_replayed(self):
        self.controller(self.dead());self.r._claim(self.nonce)
        self.r._record('case',{'pid':None,'stage':'execute_LAUNCHING'},self.nonce)
        self.assertEqual('ORPHAN_JOB_UNRESOLVED',self.r.recover()['code'])
        self.assertEqual('RUNNING',self.r.read_job('case')['state'])
    def test_pause_recovers_dead_controller_instead_of_stuck_pausing(self):
        self.controller(self.dead(),state='PAUSING');self.assertEqual('PAUSED',self.r.pause()['state'])
    def test_stale_progress_nonce_cannot_mutate_job(self):
        self.controller();self.r._claim(self.nonce);before=self.r.read_job('case')
        with self.assertRaises(HarnessError):self.r._record('case',{'pid':123},'wrong')
        self.assertEqual(before,self.r.read_job('case'))
    def test_recovery_is_idempotent(self):
        self.controller(self.dead());self.assertTrue(self.r.recover()['recovered'])
        before=self.r.status();self.assertFalse(self.r.recover()['recovered']);self.assertEqual(before['revision'],self.r.status()['revision'])
    def test_dead_controller_wakes_wait_without_polling_forever(self):
        self.controller(self.dead());self.r._claim(self.nonce)
        self.r._record('case',{'pid':os.getpid(),'stage':'execute'},self.nonce)
        started=time.monotonic();result=self.r.wait(10)
        self.assertEqual('CONTROLLER_EXITED',result['wake_reason']);self.assertLess(time.monotonic()-started,2)

    def corrupt_snapshot(self,value,remove=False):
        with self.f.store.db(True) as db:
            row=db.execute('SELECT record FROM research_jobs WHERE owner=? AND id=?',(self.f.owner,'case')).fetchone()
            record=json.loads(row[0])
            if remove:record.pop('input_snapshot_id')
            else:record['input_snapshot_id']=value
            db.execute('UPDATE research_jobs SET record=? WHERE owner=? AND id=?',(canonical(record),self.f.owner,'case'))
    def test_malformed_snapshot_values_are_rejected_before_database_binding(self):
        for value in ([],{},['bad'],{'bad':1},True,'','not-a-hash'):
            with self.subTest(value=value):
                self.corrupt_snapshot(value)
                with self.assertRaises(HarnessError):self.r._input_context(self.f.root,self.r.read_job('case')['spec'])
        self.assertFalse((self.f.root/'scratch').exists())
    def test_null_snapshot_is_not_reinterpreted_as_legacy(self):
        self.corrupt_snapshot(None);result=self.execute()
        self.assertEqual('ERROR',result['state']);self.assertFalse((self.f.root/'scratch').exists())
    def test_missing_required_snapshot_does_not_fall_back_to_current_input(self):
        self.corrupt_snapshot(None,remove=True);result=self.execute()
        self.assertEqual('ERROR',result['state']);self.assertFalse((self.f.root/'scratch').exists())
    def test_unknown_snapshot_identity_refuses_computation(self):
        self.corrupt_snapshot('a'*64);result=self.execute()
        self.assertEqual('ERROR',result['state']);self.assertFalse((self.f.root/'scratch').exists())
    def test_same_dead_controller_notification_is_coalesced(self):
        self.controller(self.dead());self.r._claim(self.nonce)
        self.r._record('case',{'pid':os.getpid(),'stage':'execute'},self.nonce)
        self.assertEqual('CONTROLLER_EXITED',self.r.wait(1)['wake_reason'])
        self.assertEqual('TIMEOUT',self.r.wait(1)['wake_reason'])
    def test_new_controller_exit_is_not_hidden_by_old_notification(self):
        self.controller(self.dead());self.r._claim(self.nonce)
        self.r._record('case',{'pid':os.getpid(),'stage':'execute'},self.nonce)
        self.assertEqual('CONTROLLER_EXITED',self.r.wait(1)['wake_reason'])
        with self.f.store.db(True) as db:
            state=self.r._read(db);state['supervisor']['nonce']='e'*32;self.r._save(db,state)
        self.assertEqual('CONTROLLER_EXITED',self.r.wait(1)['wake_reason'])
    def test_process_started_before_progress_failure_is_reaped(self):
        self.controller();job=self.r._claim(self.nonce);original=self.r._record;processes=[]
        actual_popen=subprocess.Popen
        def remember(*args,**kwargs):
            process=actual_popen(*args,**kwargs);processes.append(process);return process
        def write(name,fields,nonce):
            if fields.get('stage')=='execute':raise HarnessError('simulated progress-write failure')
            return original(name,fields,nonce)
        with patch('luna_astra.research.subprocess.Popen',side_effect=remember),patch.object(self.r,'_record',side_effect=write):
            result=self.r._execute(job,self.nonce)
        self.assertEqual('ERROR',result['state']);self.assertEqual(1,len(processes))
        self.assertIsNotNone(processes[0].returncode)
        self.assertTrue((self.f.root/'scratch/ran').exists())
        self.assertIsNone(self.r.status()['best_verified_candidate'])


class ProcessIdentityTests(unittest.TestCase):
    def test_malformed_creation_cookie_cannot_certify_original_process_exit(self):
        for value in ('',[],{},5,True,'unstructured-old-cookie'):
            with self.subTest(value=value):self.assertEqual('UNKNOWN',probe(os.getpid(),value)['state'])
    def test_current_pid_is_alive_not_progress_proof(self):
        self.assertEqual('ALIVE',probe(os.getpid())['state'])
    def test_exited_actual_process_is_exited(self):
        p=subprocess.Popen([sys.executable,'-c','pass']);p.wait()
        self.assertEqual('EXITED',probe(p.pid)['state'])
    def test_missing_invalid_pid_is_unknown(self):
        for value in (None,0,-1,True,'123',2**40):self.assertEqual('UNKNOWN',probe(value)['state'])
    def test_creation_cookie_binds_original_pid(self):
        own=probe(os.getpid())
        if own['identity'] is not None:
            self.assertEqual('ALIVE',probe(os.getpid(),own['identity'])['state'])
            self.assertEqual('EXITED',probe(os.getpid(),own['identity'].rsplit(':',1)[0]+':'+str(int(own['identity'].rsplit(':',1)[1])+1))['state'])
        else:self.assertEqual('UNKNOWN',probe(os.getpid(),'unverifiable-cookie')['state'])
    def test_no_process_termination_api_in_recovery(self):
        text=(PACKAGE/'luna_astra/process_identity.py').read_text()
        self.assertNotIn('TerminateProcess(',text);self.assertNotIn('SIGKILL',text)
        self.assertNotIn('.kill(', (PACKAGE/'luna_astra/research.py').read_text())

    def test_hidden_procfs_is_not_treated_as_exited(self):
        from types import SimpleNamespace
        # Simulate the Linux observation boundary on every test platform.
        with patch('luna_astra.process_identity.os',SimpleNamespace(name='posix',kill=MagicMock())),patch('luna_astra.process_identity.sys',SimpleNamespace(platform='linux')),patch('luna_astra.process_identity.Path.read_text',side_effect=FileNotFoundError()):
            result=probe(12345)
        self.assertEqual('UNKNOWN',result['state'])
    def windows_probe(self,*,handle=123,wait=258,times=True,error=0,expected=None):
        import ctypes
        from ctypes import wintypes
        kernel=MagicMock();kernel.OpenProcess.return_value=handle;kernel.WaitForSingleObject.return_value=wait
        def fill(_handle,created,exited,system,user):
            if not times:return False
            value=ctypes.cast(created,ctypes.POINTER(wintypes.FILETIME)).contents
            value.dwHighDateTime=1;value.dwLowDateTime=2;return True
        kernel.GetProcessTimes.side_effect=fill
        with patch('luna_astra.process_identity.os.name','nt'),patch.object(ctypes,'WinDLL',return_value=kernel,create=True),patch.object(ctypes,'get_last_error',return_value=error,create=True):
            result=probe(12345,expected)
        return result,kernel
    def test_windows_creation_cookie_and_handle_cleanup(self):
        result,kernel=self.windows_probe()
        self.assertEqual('ALIVE',result['state']);self.assertEqual('win:4294967298',result['identity'])
        kernel.CloseHandle.assert_called_once_with(123)
    def test_windows_access_denied_is_unknown(self):
        result,kernel=self.windows_probe(handle=0,error=5)
        self.assertEqual('UNKNOWN',result['state']);kernel.CloseHandle.assert_not_called()
    def test_windows_absent_and_signalled_process_are_exited(self):
        self.assertEqual('EXITED',self.windows_probe(handle=0,error=87)[0]['state'])
        result,kernel=self.windows_probe(wait=0)
        self.assertEqual('EXITED',result['state']);kernel.CloseHandle.assert_called_once()
    def test_windows_unavailable_creation_time_preserves_unknown(self):
        result,kernel=self.windows_probe(times=False)
        self.assertEqual('UNKNOWN',result['state']);kernel.CloseHandle.assert_called_once()
    def test_windows_pid_reuse_identifies_original_as_exited(self):
        self.assertEqual('EXITED',self.windows_probe(expected='win:4294967299')[0]['state'])
    def test_windows_wait_failure_is_unknown_and_handle_closed(self):
        result,kernel=self.windows_probe(wait=0xffffffff)
        self.assertEqual('UNKNOWN',result['state']);kernel.CloseHandle.assert_called_once()


class InstalledCorrectionTests(unittest.TestCase):
    def setUp(self):
        import test_fixed_seven_integration as fixture_module
        self.host=fixture_module.InstalledFixedSevenTests(methodName='runTest')
        self.addCleanup(self.host.doCleanups);self.host.setUp()
    def preflight(self,command):
        from luna_astra.transport import helper_command
        out=self.host.hook({**self.host.event,'hook_event_name':'PreToolUse','tool_name':'Bash',
                            'tool_input':{'command':helper_command(self.host.prefix+command)},
                            'tool_use_id':'helper-'+command[0]})
        self.assertNotEqual('deny',out.get('hookSpecificOutput',{}).get('permissionDecision'),out)
    def test_installed_recovery_command_is_allowed_without_launching_a_study(self):
        self.host.cli(['crew-start'],self.host.contract)
        self.preflight(['research-recover'])
        result=self.host.cli(['research-recover'])
        self.assertFalse(result['recovered']);self.assertEqual('NOT_ACTIVE',result['controller']['state'])
    def test_installed_capacity_annotation_routes_through_observed_root(self):
        self.host.contract['native']={'protocol':'v2','context':'capsule','capacity_total':7}
        self.host.cli(['crew-start'],self.host.contract)
        data={'capacity_total':7,'evidence':'Synthetic installed-host fixture; not a live host test'}
        self.preflight(['--input-json',json.dumps(data),'crew-capacity'])
        result=self.host.cli(['crew-capacity'],data)
        self.assertFalse(result['settings_changed']);self.assertFalse(result['independently_attested'])
        self.assertEqual(7,result['capacity_total'])

if __name__=='__main__':unittest.main()
