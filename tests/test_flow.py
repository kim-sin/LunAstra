"""Round-bound native protocol and adversarial early-stop tests (simulated host)."""
from __future__ import annotations
import copy
import io
import json
import sys
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from test_fixed_seven import Fixture, PACKAGE
from luna_astra.flow import Flow, MAX_IDLE_CORRECTIONS, MAX_RECOVERIES
from luna_astra.store import Store, evidence_directory
from luna_astra.util import HarnessError
from luna_astra.transport import helper_command
from luna import main

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close)
        self.flow=Flow(self.f.store,PACKAGE)
        self.f.start();self.f.dispatch();self.seq=0
    def stop(self, **fields):
        return self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop',
            'last_assistant_message':'Children running; no report yet.',**fields})
    def before_wait(self, targets=None, uid=None):
        self.seq+=1;uid=uid or f'wait-{self.seq}'
        event={**self.f.event,'tool_name':'multi_agent_v1wait_agent','tool_use_id':uid,
               'tool_input':{'targets':targets or ['child-1'],'timeout_ms':60000},'hook_event_name':'PreToolUse'}
        result=self.f.hooks.handle(event)
        self.assertNotEqual('deny',result.get('hookSpecificOutput',{}).get('permissionDecision'),result)
        return event
    def after_wait(self,event,response):
        return self.f.hooks.handle({**event,'hook_event_name':'PostToolUse','tool_response':response})
    def native(self,status,targets=None):
        event=self.before_wait(targets)
        self.after_wait(event,{'status':status,'timed_out':not bool(status)})
        return event
    def rows(self):return self.f.crew.status(self.f.owner)['tasks']
    def recover(self,slot=1):
        call=self.flow.prepare_recovery(self.f.owner,slot)
        self.seq+=1; uid=f'recover-{self.seq}'
        self.f.crew.pre_dispatch(self.f.owner,uid,call['arguments'],self.f.event['model'],call['tool'])
        self.f.crew.post_dispatch(self.f.owner,uid,{'submission_id':uid})
        key=self.f.keys[slot];self.f.crew.join(key,call['ticket'],self.f.store.get(key,'meta'))
        return call
    def report_one(self,slot=1,verdict='clear'):
        self.f.crew.report(self.f.keys[slot],{'verdict':verdict,'summary':'Inspected actual input',
            'findings':['Input contains two integers'],'references':[{'path':'input.txt'}],'covers':[0]})
        return self.f.hooks.handle({**self.f.event,'session_id':f'child-{slot}','agent_id':f'child-{slot}',
                'hook_event_name':'SubagentStop','last_assistant_message':'LUNASTRA_STATUS=ANALYSIS'})
    def test_wait_timeout_is_not_failure_or_report(self):
        self.native({})
        self.assertEqual('running',self.rows()[0]['state'])
        self.assertEqual(0,len(self.f.crew.status(self.f.owner)['reports']))
        self.assertEqual('WAIT',self.flow.drive(self.f.owner)['action'])
    def test_wait_returns_all_exact_pending_ids(self):
        self.report_one()
        action=self.flow.drive(self.f.owner)
        self.assertEqual([f'child-{i}' for i in range(2,7)],action['native_call']['arguments']['targets'])
    def test_native_completion_is_not_a_fabricated_report(self):
        self.native({'child-1':{'completed':'some prose, NOT a submitted report'}})
        self.assertEqual('returned',self.rows()[0]['state'])
        self.assertEqual('UNVERIFIED',self.rows()[0]['result']['status'])
        self.assertEqual({},self.f.crew.status(self.f.owner)['reports'])
    def test_six_native_completions_choose_same_session_recovery(self):
        self.native({f'child-{i}':{'completed':'missing reports'} for i in range(1,7)},[f'child-{i}' for i in range(1,7)])
        action=self.flow.drive(self.f.owner)
        self.assertEqual('RECOVER',action['action']);self.assertEqual('crew-recover 1',action['helper'])
    def test_singleton_native_agent_path_is_correlated_by_wait_call(self):
        self.native({'/root/member':{'completed':'finished'}})
        self.assertEqual('returned',self.rows()[0]['state'])
        self.assertEqual('child-1',self.flow._native(self.f.owner,self.rows()[0])['agent_id'])
    def test_multiple_unknown_native_paths_are_not_guessed(self):
        self.native({'/root/a':{'completed':'a'},'/root/b':{'completed':'b'}},['child-1','child-2'])
        self.assertEqual(['running','running'],[r['state'] for r in self.rows()[:2]])
    def test_foreign_native_id_cannot_complete_a_singleton_wait(self):
        self.native({'foreign-id':{'completed':'not ours'}})
        self.assertEqual('running',self.rows()[0]['state'])
    def test_unpaired_wait_cannot_change_state(self):
        self.flow.post_wait(self.f.owner,'never-observed',{'status':{'child-1':{'completed':'x'}}})
        self.assertEqual('running',self.rows()[0]['state'])
    def test_wait_foreign_target_denied(self):
        with self.assertRaises(HarnessError):self.flow.pre_wait(self.f.owner,'x',{'targets':['foreign']})
    def test_wait_rejects_ambiguous_or_invalid_schema(self):
        for payload in ({'ids':['child-1']},{'targets':[]},{'targets':['child-1','child-1']},
                        {'targets':['child-1'],'timeout_ms':True},{'targets':['child-1'],'extra':1}):
            with self.subTest(payload=payload),self.assertRaises(HarnessError):self.flow.pre_wait(self.f.owner,'x',payload)
    def test_wait_call_id_conflict_is_rejected(self):
        self.flow.pre_wait(self.f.owner,'x',{'targets':['child-1']})
        with self.assertRaises(HarnessError):self.flow.pre_wait(self.f.owner,'x',{'targets':['child-2']})
    def test_wait_duplicate_response_is_idempotent(self):
        event=self.before_wait();response={'status':{'child-1':{'completed':'done'}},'timed_out':False}
        self.after_wait(event,response);before=self.rows();self.after_wait(event,response);self.assertEqual(before,self.rows())
    def test_wait_changed_response_is_rejected(self):
        event=self.before_wait();self.after_wait(event,{'status':{},'timed_out':True})
        with self.assertRaises(HarnessError):self.after_wait(event,{'status':{'child-1':{'completed':'different'}}})
    def test_native_error_is_explicit_not_infinite_running(self):
        self.native({'child-1':{'errored':'host error'}})
        self.assertEqual('failed',self.rows()[0]['state']);self.assertEqual('BLOCKED',self.flow.drive(self.f.owner)['action'])
    def test_native_error_does_not_hide_behind_a_prior_report(self):
        self.f.reports();self.native({'child-1':{'errored':'host error'}})
        self.assertEqual('BLOCKED',self.flow.drive(self.f.owner)['action'])
    def test_native_error_cannot_bypass_phase_gate_with_old_reports(self):
        self.f.reports();self.native({'child-1':{'errored':'host error'}})
        with self.assertRaises(HarnessError):self.f.execute()
        self.assertEqual('PLAN',self.f.crew.status(self.f.owner)['phase'])
    def test_mutated_current_handback_invalidates_completed_proof(self):
        self.f.reports();self.f.execute();self.f.dispatch();self.f.reports();ev=self.f.checked_output()
        self.f.crew.review(self.f.owner,'Review output');self.f.dispatch();self.f.reports()
        ev.finish('tested','Exact output','Checked all reports','Synthetic test')
        self.f.store.put(self.f.owner,'finish_generation',self.f.store.get(self.f.owner,'generation'))
        self.f.crew.complete(self.f.owner,'All checks and artifact match')
        with self.f.store.db(True) as db:db.execute("UPDATE work SET state='failed' WHERE ticket=?",(self.rows()[0]['ticket'],))
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
    def test_unknown_native_format_cannot_mark_completion(self):
        self.native({'child-1':{'success':True}})
        self.assertEqual('running',self.rows()[0]['state'])
    def test_late_wait_cannot_modify_reused_ids_in_new_round(self):
        event=self.before_wait();self.f.reports();self.f.execute();self.f.dispatch()
        tickets=[r['ticket'] for r in self.rows()]
        self.after_wait(event,{'status':{'child-1':'not_found'},'timed_out':False})
        self.assertEqual(['running']*6,[r['state'] for r in self.rows()])
        self.assertEqual(tickets,[r['ticket'] for r in self.rows()])
    def test_late_wait_cannot_modify_same_ticket_after_recovery(self):
        late=self.before_wait();self.native({'child-1':{'completed':'missing'}});self.recover()
        self.after_wait(late,{'status':{'child-1':'not_found'},'timed_out':False})
        self.assertEqual('running',self.rows()[0]['state'])
    def test_recovery_keeps_same_six_ids_ticket_and_evidence(self):
        before=self.rows();key=self.f.keys[1];directory=evidence_directory(self.f.state,key)
        directory.mkdir(parents=True,exist_ok=True);(directory/'retained.txt').write_text('preserved')
        self.native({'child-1':{'completed':'missing'}});call=self.recover()
        self.assertEqual('send_input',call['tool']);self.assertEqual('child-1',call['arguments']['target'])
        self.assertFalse(call['arguments']['interrupt']);self.assertEqual(before[0]['ticket'],call['ticket'])
        self.assertEqual([r['agent_id'] for r in before],[r['agent_id'] for r in self.rows()])
        self.assertEqual(directory,evidence_directory(self.f.state,key));self.assertEqual('preserved',(directory/'retained.txt').read_text())
        self.assertNotIn('decision',self.report_one());self.assertEqual('ANALYSIS',self.rows()[0]['result']['status'])
    def test_recovery_cannot_resubmit_to_running_worker(self):
        with self.assertRaises(HarnessError):self.flow.prepare_recovery(self.f.owner,1)
    def test_recovery_cannot_substitute_foreign_target_or_model(self):
        self.native({'child-1':{'completed':'missing'}});call=self.flow.prepare_recovery(self.f.owner,1)
        for bad in ({**call['arguments'],'target':'child-2'},{**call['arguments'],'reasoning_effort':'high'},
                    {**call['arguments'],'interrupt':True},{**call['arguments'],'message':call['arguments']['message']+' tampered'}):
            with self.subTest(),self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',bad,self.f.event['model'],'send_input')
        self.assertEqual('returned',self.rows()[0]['state'])
        self.assertEqual(0,self.f.store.get(self.f.owner,'flow-recovery-count:'+call['ticket'],0))
    def test_recovery_never_spawns_replacement(self):
        self.native({'child-1':{'completed':'missing'}});call=self.flow.prepare_recovery(self.f.owner,1)
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',{**call['arguments'],'fork_context':True},self.f.event['model'],'spawn_agent')
    def test_recovery_pending_ack_cannot_be_repeated(self):
        self.native({'child-1':{'completed':'missing'}});call=self.flow.prepare_recovery(self.f.owner,1)
        self.f.crew.pre_dispatch(self.f.owner,'r',call['arguments'],self.f.event['model'],'send_input')
        self.f.crew.post_dispatch(self.f.owner,'r',{'text':'not an ack'})
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'r2',call['arguments'],self.f.event['model'],'send_input')
        self.assertEqual('BLOCKED',self.flow.drive(self.f.owner)['action'])
    def test_recovery_bound_is_enforced(self):
        for _ in range(MAX_RECOVERIES):self.native({'child-1':{'completed':'missing'}});self.recover()
        self.native({'child-1':{'completed':'still missing'}})
        with self.assertRaises(HarnessError):self.flow.prepare_recovery(self.f.owner,1)
    def test_recovery_cannot_repeat_a_successful_result(self):
        self.report_one();self.native({'child-1':{'completed':'already checked'}})
        with self.assertRaises(HarnessError):self.flow.prepare_recovery(self.f.owner,1)
    def test_recovery_race_rechecks_changed_handback(self):
        self.native({'child-1':{'completed':'missing'}});call=self.flow.prepare_recovery(self.f.owner,1)
        from luna_astra.team import Team
        Team(self.f.store).returned(call['ticket'],{'status':'BLOCKED','worker_key':self.f.keys[1]})
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'r',call['arguments'],self.f.event['model'],'send_input')
    def test_parent_does_not_bypass_wait_with_a_partial_finish(self):
        from luna_astra.evidence import Evidence
        ev=Evidence(evidence_directory(self.f.state,self.f.owner),self.f.root)
        ev.begin({'task_id':'p','design':'retained','requirements':self.f.contract['requirements'],'allowed_paths':['output.txt'],
                  'checks':[{'id':'not-run','purpose':'actual output','argv':[sys.executable,'-c','assert False'],'dependencies':['input.txt'],'covers':[0]}]})
        ev.finish('partial','Not yet finished','Workers running','Six workers have not submitted reports')
        self.f.store.put(self.f.owner,'finish_generation',self.f.store.get(self.f.owner,'generation'))
        self.assertEqual('block',self.stop(stop_hook_active=True).get('decision'))
    def test_real_source_linked_blocker_is_distinct_from_waiting(self):
        self.report_one(verdict='blocked')
        self.assertEqual('WAIT',self.flow.drive(self.f.owner)['action'])
        for slot in range(2,7):self.report_one(slot=slot)
        self.assertEqual('BLOCKED',self.flow.drive(self.f.owner)['action'])
        self.assertEqual('blocked',self.f.crew.status(self.f.owner)['reports'][self.rows()[0]['ticket']]['verdict'])
    def test_no_progress_repeated_immediate_stops_are_bounded(self):
        for _ in range(MAX_IDLE_CORRECTIONS):self.assertEqual('block',self.stop(stop_hook_active=True).get('decision'))
        result=self.stop(stop_hook_active=True);self.assertFalse(result['continue'])
        self.assertEqual(['running']*6,[r['state'] for r in self.rows()])
    def test_a_real_blocking_wait_allows_parent_to_keep_waiting(self):
        for _ in range(MAX_IDLE_CORRECTIONS):self.stop(stop_hook_active=True)
        event=self.before_wait()
        with self.f.store.db(True) as db:
            db.execute('UPDATE crew_waits SET started=started-2 WHERE owner=? AND call_id=?',(self.f.owner,event['tool_use_id']))
        self.after_wait(event,{'status':{},'timed_out':True})
        self.assertEqual('block',self.stop(stop_hook_active=True).get('decision'))
    def test_fast_fake_poll_does_not_extend_stop_budget(self):
        for _ in range(MAX_IDLE_CORRECTIONS):self.stop(stop_hook_active=True)
        event=self.before_wait();self.after_wait(event,{'status':{},'timed_out':True})
        self.assertFalse(self.stop(stop_hook_active=True)['continue'])
    def test_interrupt_is_always_respected(self):
        self.f.hooks.handle({**self.f.event,'hook_event_name':'Interrupt'})
        self.assertEqual({},self.stop(stop_hook_active=True))
        self.assertEqual(['running']*6,[r['state'] for r in self.rows()])
    def test_worker_cannot_run_root_drive_or_recovery(self):
        for args in (['crew-drive'],['crew-recover','1']):
            with redirect_stderr(io.StringIO()):
                code=main(['--state',str(self.f.state),'--session',self.f.keys[1],*args])
            self.assertEqual(1,code)
    def test_root_drive_cli_and_hook_literal_command(self):
        command=helper_command(self.flow.prefix(self.f.owner)+['crew-drive'])
        result=self.f.hooks.handle({**self.f.event,'hook_event_name':'PreToolUse','tool_name':'Bash',
              'tool_use_id':'drive','tool_input':{'command':command}})
        self.assertNotEqual('deny',result.get('hookSpecificOutput',{}).get('permissionDecision'))
        out=io.StringIO()
        with redirect_stdout(out):code=main(['--state',str(self.f.state),'--session',self.f.owner,'crew-drive'])
        self.assertEqual(0,code);self.assertEqual('WAIT',json.loads(out.getvalue())['action'])
    def test_post_dispatch_immediately_supplies_continuation_action(self):
        c=self.f.calls[0]
        result=self.f.hooks.handle({**self.f.event,'hook_event_name':'PostToolUse','tool_name':'spawn_agent',
            'tool_use_id':'r1-s1','tool_input':c['arguments'],'tool_response':{'agent_id':'child-1'}})
        self.assertIn('wait_agent',result['hookSpecificOutput']['additionalContext'])
    def test_current_request_and_roster_survive_hook_feedback(self):
        before=self.f.crew.status(self.f.owner);response=self.stop()
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':response['reason']})
        after=self.f.crew.status(self.f.owner)
        self.assertEqual(before['run_id'],after['run_id']);self.assertEqual(before['plan_id'],after['plan_id'])
        self.assertEqual(before['request_hash'],self.f.store.get(self.f.owner,'request_hash'))
    def test_single_user_request_can_complete_all_phases_after_early_stops(self):
        ids=[r['agent_id'] for r in self.rows()]
        for phase in ('PLAN','EXECUTE','REVIEW'):
            self.assertEqual(phase,self.f.crew.status(self.f.owner)['phase'])
            first=self.stop(stop_hook_active=True);self.assertEqual('block',first.get('decision'))
            self.f.reports()
            self.assertEqual('block',self.stop(stop_hook_active=True).get('decision'))
            if phase=='PLAN':self.f.execute();self.f.dispatch()
            elif phase=='EXECUTE':
                ev=self.f.checked_output();self.f.crew.review(self.f.owner,'Review exact checked output');self.f.dispatch()
            else:
                ev.finish('tested','Wrote checked result','All six reports checked','Synthetic host test, no model calls')
                self.f.store.put(self.f.owner,'finish_generation',self.f.store.get(self.f.owner,'generation'))
                self.f.crew.complete(self.f.owner,'Requirements and actual output match')
            self.assertEqual(ids,[r['agent_id'] for r in self.rows()])
        self.assertTrue(self.f.crew.status(self.f.owner)['complete'])
        self.assertNotIn('decision',self.stop(last_assistant_message='LUNASTRA_STATUS=TESTED'))
        self.assertEqual(6,sum(c['tool']=='spawn_agent' for c in self.f.calls))
        self.assertEqual(12,sum(c['tool']=='send_input' for c in self.f.calls))
    def test_state_output_distinguishes_native_observation_from_local_running(self):
        state=self.f.crew.inspect(self.f.owner)
        self.assertEqual(0,state['reports_received']);self.assertEqual('WAIT',state['flow']['action'])
        self.assertTrue(all(item['observation'] is None for item in state['native_observations']))
    def test_explicit_native_failure_never_invents_replacement(self):
        self.native({'child-1':'not_found'})
        with self.assertRaises(HarnessError):self.flow.prepare_recovery(self.f.owner,1)
        self.assertEqual(6,self.f.crew.status(self.f.owner)['observed_children'])

if __name__=='__main__':unittest.main()
