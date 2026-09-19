"""Fault and recovery coverage; model event traffic is explicitly synthetic."""
from __future__ import annotations
import copy
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from test_fixed_seven import Fixture, PACKAGE
from luna_astra.crew import Crew
from luna_astra.team import Team
from luna_astra.store import evidence_directory
from luna_astra.util import HarnessError, canonical
from luna_astra import input_buffer

class FixedSevenAdversarialTests(unittest.TestCase):
    def setUp(self): self.f=Fixture()
    def tearDown(self): self.f.close()
    def finish_root(self,ev):
        ev.finish('tested','Actual output saved','Current declared checks inspected','Synthetic native-event fixture only')
        self.f.store.put(self.f.owner,'finish_generation',self.f.store.get(self.f.owner,'generation'))
    def test_native_send_uses_target_not_id(self):
        self.f.planning();c=self.f.crew.next(self.f.owner)['calls'][0]
        self.assertEqual('child-1',c['arguments']['target']);self.assertNotIn('id',c['arguments'])
        bad={**c['arguments'],'id':c['arguments']['target']};bad.pop('target')
        with self.assertRaises(HarnessError): self.f.crew.pre_dispatch(self.f.owner,'bad',bad,'gpt-5.6-luna','send_input')
    def test_reused_join_waits_for_current_submission_ack(self):
        self.f.planning();c=self.f.crew.next(self.f.owner)['calls'][0];key=self.f.keys[1]
        self.f.crew.pre_dispatch(self.f.owner,'pending',c['arguments'],'gpt-5.6-luna','send_input')
        with self.assertRaises(HarnessError): self.f.crew.join(key,c['ticket'],self.f.store.get(key,'meta'))
        self.f.crew.post_dispatch(self.f.owner,'pending',{'text':'submitted'})
        with self.assertRaises(HarnessError): self.f.crew.join(key,c['ticket'],self.f.store.get(key,'meta'))
        self.f.crew.post_dispatch(self.f.owner,'pending',{'submission_id':'observed-submission'})
        joined=self.f.crew.join(key,c['ticket'],self.f.store.get(key,'meta'))
        self.assertEqual('EXECUTE',joined['phase'])
    def test_repeat_join_preserves_baseline_and_finish(self):
        self.f.start();calls=self.f.dispatch();key=self.f.keys[1]
        baseline=self.f.store.get(key,'source_baseline');self.f.store.put(key,'finish_generation','retained-generation')
        (self.f.root/'input.txt').write_text('changed')
        self.f.crew.join(key,calls[0]['ticket'],self.f.store.get(key,'meta'))
        self.assertEqual(baseline,self.f.store.get(key,'source_baseline'))
        self.assertEqual('retained-generation',self.f.store.get(key,'finish_generation'))
    def test_changed_planning_source_cannot_be_promoted(self):
        self.f.start();self.f.dispatch();self.f.reports();(self.f.root/'input.txt').write_text('7,8')
        with self.assertRaises(HarnessError): self.f.execute()
    def test_foreign_worker_handback_is_rejected(self):
        self.f.start();self.f.dispatch();self.f.reports();row=self.f.crew.status(self.f.owner)['tasks'][0]
        with self.f.store.db(True) as db:
            hb={**row['result'],'worker_key':'0'*64}
            db.execute('UPDATE work SET result=? WHERE ticket=?',(canonical(hb),row['ticket']))
        with self.assertRaises(HarnessError): self.f.execute()
    def test_dispatch_model_drift_is_rejected(self):
        self.f.start();c=self.f.crew.next(self.f.owner)['calls'][0]
        with self.assertRaises(HarnessError): self.f.crew.pre_dispatch(self.f.owner,'other',c['arguments'],'gpt-5.6-luna-reserve','spawn_agent')
    def test_doctor_never_calls_review_phase_complete(self):
        ev=self.f.reviewing();self.finish_root(ev)
        for i in range(1,7): Team(self.f.store).accept(self.f.owner,f's{i}','Inspected result')
        record=next(r for r in self.f.hooks.doctor()['sessions'] if r['key']==self.f.owner)
        self.assertFalse(record['current_tested'])
        self.f.crew.complete(self.f.owner,'Combined acceptance complete')
        record=next(r for r in self.f.hooks.doctor()['sessions'] if r['key']==self.f.owner)
        self.assertTrue(record['current_tested'])
    def test_issue_requires_repair_then_new_review_with_same_ids(self):
        self.f.planning();self.f.dispatch();self.f.reports();ev=self.f.checked_output()
        self.f.crew.review(self.f.owner,'Inspect assembled output');self.f.dispatch();self.f.reports('issues')
        # The root actually retrieves current issue reports before deciding.
        from luna_astra.controller import Controller
        Controller(self.f.store,PACKAGE).step(self.f.owner,details=True)
        self.finish_root(ev)
        with self.assertRaises(HarnessError): self.f.crew.complete(self.f.owner,'Ignore the issue')
        self.f.crew.execute(self.f.owner,{'decision':'Resolve the reported issue and inspect related obligations','tasks':self.f.tasks()},repair=True)
        self.f.dispatch();self.f.reports();ev=self.f.checked_output()
        self.f.crew.review(self.f.owner,'New acceptance snapshot');self.f.dispatch();self.f.reports();self.finish_root(ev)
        self.f.crew.complete(self.f.owner,'All current findings resolved')
        self.assertEqual(6,sum(c['tool']=='spawn_agent' for c in self.f.calls))
        self.assertEqual(24,sum(c['tool']=='send_input' for c in self.f.calls))
    def test_missing_worker_report_returns_unverified_without_deadlock(self):
        self.f.start();self.f.dispatch();event={**self.f.event,'session_id':'child-1','agent_id':'child-1','hook_event_name':'SubagentStop','last_assistant_message':'done'}
        self.assertEqual('block',self.f.hooks.handle(event)['decision'])
        self.assertFalse(self.f.hooks.handle({**event,'stop_hook_active':True})['continue'])
        row=self.f.crew.status(self.f.owner)['tasks'][0]
        self.assertEqual('returned',row['state']);self.assertEqual('UNVERIFIED',row['result']['status'])
    def test_missing_sixth_native_member_never_certifies_seven(self):
        self.f.start();calls=self.f.crew.next(self.f.owner)['calls']
        for i,c in enumerate(calls[:5]):
            self.f.crew.pre_dispatch(self.f.owner,str(i),c['arguments'],'gpt-5.6-luna','spawn_agent')
            self.f.crew.post_dispatch(self.f.owner,str(i),{'agent_id':f'child-{i+1}'})
        self.assertEqual(5,self.f.crew.status(self.f.owner)['observed_children'])
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
    def test_foreign_resume_and_close_are_blocked(self):
        self.f.start();self.f.dispatch()
        for name,payload in [('resume_agent',{'id':'foreign'}),('close_agent',{'id':'child-1'})]:
            result=self.f.hooks.handle({**self.f.event,'hook_event_name':'PreToolUse','tool_name':name,'tool_input':payload,'tool_use_id':name})
            self.assertEqual('deny',result['hookSpecificOutput']['permissionDecision'])
    def test_no_git_keeps_six_slots_and_one_writer(self):
        self.f.start();self.f.dispatch();self.f.reports();tasks=self.f.tasks();tasks[0].update(kind='implement',paths=['output.txt'])
        self.f.crew.execute(self.f.owner,{'decision':'Implementation with safe fallback','tasks':tasks})
        calls=self.f.crew.next(self.f.owner)['calls'];self.assertEqual(6,len(calls))
        first=self.f.crew.status(self.f.owner)['tasks'][0]
        self.assertEqual('investigate',first['spec']['kind']);self.assertTrue(calls[0]['fallback'])
    def test_reserved_checkout_recovery_is_idempotent(self):
        self.f.start();self.f.dispatch();self.f.reports();tasks=self.f.tasks();tasks[0].update(kind='implement',paths=['output.txt'])
        self.f.crew.execute(self.f.owner,{'decision':'Check a reserved preparation','tasks':tasks})
        with patch('luna_astra.crew.Workspaces.prepare',side_effect=RuntimeError('simulated process crash')):
            with self.assertRaises(RuntimeError):self.f.crew.next(self.f.owner)
        before=self.f.crew.status(self.f.owner)['tasks'][0]['ticket']
        calls=self.f.crew.next(self.f.owner)['calls']
        self.assertEqual(before,calls[0]['ticket']);self.assertEqual(6,len(calls))
    def test_oversized_capsule_fails_before_creating_round(self):
        c=copy.deepcopy(self.f.contract);c['requirements']=['x'*2900+str(i) for i in range(10)]
        with self.assertRaises(HarnessError): self.f.crew.start(self.f.owner,c)
        self.assertFalse(self.f.crew.status(self.f.owner)['configured'])
    def test_new_request_reuses_the_existing_six(self):
        self.f.complete();new=copy.deepcopy(self.f.contract);new['goal']='Repeat with the same input under an explicit new request'
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'Repeat using the same input','turn_id':'turn-2'})
        self.f.crew.start(self.f.owner,new)
        calls=self.f.crew.next(self.f.owner)['calls']
        self.assertEqual(6,len(calls));self.assertTrue(all(c['tool']=='send_input' for c in calls))
    def test_input_buffer_unicode_idempotent_and_isolated(self):
        text=json.dumps({'label':'\ub8e8\ub098'},ensure_ascii=False)
        input_buffer.append(self.f.store,self.f.owner,'request',0,text)
        self.assertTrue(input_buffer.append(self.f.store,self.f.owner,'request',0,text)['retry_reused'])
        self.assertEqual(text,input_buffer.read(self.f.store,self.f.owner,'request'))
        with self.assertRaises(HarnessError):input_buffer.read(self.f.store,'f'*64,'request')
    def test_input_buffer_rejects_conflict_and_malformed_json(self):
        input_buffer.append(self.f.store,self.f.owner,'bad',0,'{')
        with self.assertRaises(HarnessError):input_buffer.read(self.f.store,self.f.owner,'bad')
        with self.assertRaises(HarnessError):input_buffer.append(self.f.store,self.f.owner,'bad',0,'x')
        with self.assertRaises(HarnessError):input_buffer.append(self.f.store,self.f.owner,'bad',5,'x')
        with self.assertRaises(HarnessError):input_buffer.append(self.f.store,self.f.owner,'../escape',0,'{}')
    def test_completed_proof_invalidated_by_changed_check_definition(self):
        self.f.complete()
        from luna_astra.evidence import Evidence
        ev=Evidence(evidence_directory(self.f.state,self.f.owner))
        with ev._db() as db: task=ev._get(db,'task')
        task['checks'][0]['purpose']='A changed acceptance test definition'
        ev.begin(task);ev.run_all();self.finish_root(ev)
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
    def test_root_json_helper_is_encoded_during_execution_on_windows(self):
        self.f.planning()
        import sys
        from luna_astra.transport import helper_command, literal_shell_input
        prefix=[sys.executable,str(PACKAGE/'luna.py'),'--state',str(self.f.state),'--session',self.f.owner]
        raw=json.dumps({'decision':'Quotes: \"keep literal\"; no shell evaluation'})
        command=helper_command(prefix+['--input-json',raw,'crew-review'],windows=True)
        with patch('luna_astra.hooks.literal_shell_input',side_effect=lambda cmd,pre:literal_shell_input(cmd,pre,windows=True)):
            result=self.f.hooks.handle({**self.f.event,'hook_event_name':'PreToolUse','tool_name':'Bash','tool_input':{'command':command},'tool_use_id':'root-json'})
        rewritten=result['hookSpecificOutput']['updatedInput']['command']
        self.assertIn('-EncodedCommand',rewritten)
        import base64
        script=base64.b64decode(rewritten.rsplit(' ',1)[1]).decode('utf-16-le')
        import subprocess
        expected=subprocess.list2cmdline((prefix+['--input-json',raw,'crew-review'])[1:])
        self.assertIn(expected.replace("'","''"),script)
    def test_status_read_does_not_migrate_a_legacy_root(self):
        import io
        from contextlib import redirect_stdout
        from luna import main
        meta=self.f.store.get(self.f.owner,'meta');meta['crew_enabled']=False;self.f.store.put(self.f.owner,'meta',meta)
        with redirect_stdout(io.StringIO()):
            code=main(['--state',str(self.f.state),'--session',self.f.owner,'crew-state'])
        self.assertEqual(0,code);self.assertFalse(self.f.store.get(self.f.owner,'meta')['crew_enabled'])
    def test_failed_start_does_not_migrate_a_legacy_root(self):
        import io
        from contextlib import redirect_stderr
        from luna import main
        meta=self.f.store.get(self.f.owner,'meta');meta['crew_enabled']=False;self.f.store.put(self.f.owner,'meta',meta)
        Team(self.f.store).plan(self.f.owner,self.f.root,{'goal':'Unfinished legacy contract','tasks':self.f.tasks()})
        with redirect_stderr(io.StringIO()):
            code=main(['--state',str(self.f.state),'--session',self.f.owner,'--input-json',json.dumps(self.f.contract),'crew-start'])
        self.assertEqual(1,code);self.assertFalse(self.f.store.get(self.f.owner,'meta')['crew_enabled'])
    def test_status_does_not_present_stale_completion_as_current(self):
        self.f.complete();(self.f.root/'output.txt').write_text('wrong')
        status=self.f.crew.inspect(self.f.owner)
        self.assertEqual('COMPLETE',status['phase']);self.assertFalse(status['complete'])
        self.assertTrue(status['current_completion_problem'])
    def test_new_request_clears_current_completion_without_erasing_proof(self):
        self.f.complete()
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'A different task now','turn_id':'turn-2'})
        status=self.f.crew.inspect(self.f.owner)
        self.assertFalse(status['complete']);self.assertTrue(status['pending_request_change'])
        self.assertTrue(self.f.crew.status(self.f.owner)['proof'])
    def test_status_question_keeps_active_crew_after_explicit_acknowledgement(self):
        self.f.start();self.f.dispatch();before=self.f.crew.status(self.f.owner)
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'What is the current progress?','turn_id':'turn-2'})
        result=self.f.crew.acknowledge_unchanged(self.f.owner,'Status question only; goal, requirements and output scope are unchanged')
        self.assertFalse(result['pending_request_change'])
        after=self.f.crew.status(self.f.owner)
        self.assertEqual(before['run_id'],after['run_id']);self.assertEqual(before['plan_id'],after['plan_id'])
        self.assertEqual([t['ticket'] for t in before['tasks']],[t['ticket'] for t in after['tasks']])
        self.assertEqual(before['requirements'],after['requirements'])
        self.f.reports();self.f.execute()
    def test_worker_cannot_acknowledge_root_goal(self):
        self.f.start();self.f.dispatch()
        with self.assertRaises(HarnessError):self.f.crew.acknowledge_unchanged(self.f.keys[1],'Ignore changes')
        with self.assertRaises(HarnessError):self.f.crew.acknowledge_unchanged(self.f.owner,'')
    def test_cli_continuation_does_not_revise_or_migrate(self):
        import io
        from contextlib import redirect_stdout
        from luna import main
        self.f.start();before=self.f.crew.status(self.f.owner)
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'Status please','turn_id':'turn-2'})
        out=io.StringIO()
        with redirect_stdout(out):
            code=main(['--state',str(self.f.state),'--session',self.f.owner,'--input-json',json.dumps({'decision':'Only a status question; no changed requirement'}),'crew-continue'])
        self.assertEqual(0,code);self.assertFalse(json.loads(out.getvalue())['pending_request_change'])
        self.assertEqual(before['plan_id'],self.f.crew.status(self.f.owner)['plan_id'])
    def test_dispatch_status_rechecks_completed_artifact(self):
        self.f.complete()
        self.assertTrue(self.f.crew.next(self.f.owner)['complete'])
        (self.f.root/'output.txt').write_text('changed after certification')
        result=self.f.crew.next(self.f.owner)
        self.assertEqual([],result['calls']);self.assertFalse(result['complete'])
        self.assertTrue(result['current_completion_problem'])
    def test_input_buffer_enforces_byte_budget(self):
        with patch.object(input_buffer,'MAX_BYTES',8):
            with self.assertRaises(HarnessError):input_buffer.append(self.f.store,self.f.owner,'large',0,'123456789')
        with self.assertRaises(HarnessError):input_buffer.append(self.f.store,self.f.owner,'chunk',0,'a'*1001)

if __name__=='__main__':unittest.main()
