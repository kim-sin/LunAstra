"""Software-only fixed-seven protocol tests. Native tool events are simulated."""
from __future__ import annotations
import json
import tempfile
import unittest
import sys
import copy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from luna_astra.crew import Crew, fingerprint
from luna_astra.hooks import Hooks, identity
from luna_astra.store import Store, evidence_directory
from luna_astra.evidence import Evidence
from luna_astra.team import Team
from luna_astra.util import HarnessError, json_hash

PACKAGE=Path(__file__).resolve().parents[1]

class Fixture:
    def __init__(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name);self.root=self.base/'project';self.root.mkdir()
        (self.root/'input.txt').write_text('2,3\n',encoding='utf-8')
        self.state=self.base/'state';self.hooks=Hooks(PACKAGE,self.state,fixed_seven=True)
        self.event={'session_id':'root-native','cwd':str(self.root),'model':'gpt-5.6-luna','turn_id':'turn-1'}
        self.hooks.handle({**self.event,'hook_event_name':'SessionStart'})
        self.hooks.handle({**self.event,'hook_event_name':'UserPromptSubmit','prompt':'Write the sum of 2 and 3 to output.txt and validate it.'})
        self.owner=identity(self.event)[0];self.store=Store(self.state);self.crew=Crew(self.store,PACKAGE)
        self.contract={'goal':'Compute a checked sum','requirements':['output.txt contains the exact sum 5'],
                       'evidence_paths':['input.txt'],'output_paths':['output.txt'],
                       'native':{'protocol':'v1','context':'full'}}
        self.calls=[];self.keys={}
    def close(self):self.tmp.cleanup()
    def start(self):return self.crew.start(self.owner,self.contract)
    def dispatch(self):
        calls=self.crew.next(self.owner)['calls']
        phase=self.crew.status(self.owner)['round']
        for c in calls:
            uid=f'r{phase}-s{c["slot"]}'
            before={**self.event,'hook_event_name':'PreToolUse','tool_name':c['tool'],'tool_input':c['arguments'],'tool_use_id':uid}
            got=self.hooks.handle(before)
            if got.get('hookSpecificOutput',{}).get('permissionDecision')=='deny':raise AssertionError(got)
            result={'agent_id':f'child-{c["slot"]}'} if c['tool']=='spawn_agent' else {'submission_id':f'sub-{uid}'}
            self.hooks.handle({**before,'hook_event_name':'PostToolUse','tool_response':result})
            agent=f'child-{c["slot"]}'
            child={**self.event,'session_id':agent,'agent_id':agent,'hook_event_name':'SubagentStart' if phase==1 else 'UserPromptSubmit','prompt':c['arguments']['message']}
            self.hooks.handle(child)
            alias=self.store.get('__agent_alias__',agent);key=alias['key'];self.keys[c['slot']]=key
            self.crew.join(key,c['ticket'],self.store.get(key,'meta'))
            self.calls.append(c)
        return calls
    def reports(self,verdict='clear'):
        s=self.crew.status(self.owner)
        for row in s['tasks']:
            slot=int(row['id'][1:]);key=self.keys[slot]
            refs=[{'path':'output.txt'}] if s['phase']=='REVIEW' else [{'path':'input.txt'}]
            self.crew.report(key,{'verdict':verdict,'summary':f'Inspected slot {slot} evidence for {s["phase"]}',
                    'findings':[f'Check {slot} agrees with the explicit requirement'], 'references':refs,'covers':[0]})
            event={**self.event,'session_id':f'child-{slot}','agent_id':f'child-{slot}',
                'hook_event_name':'SubagentStop','last_assistant_message':'LUNASTRA_STATUS=ANALYSIS'}
            result=self.hooks.handle(event)
            if result.get('decision')=='block' or result.get('continue') is False:raise AssertionError(result)
    def tasks(self):
        return [{'id':f's{i}','kind':'investigate','description':f'Inspect independent obligation {i}',
                 'paths':['input.txt','output.txt'],'depends_on':[],
                 'done_when':['Return supported findings for the assigned scope'],'why_parallel':f'Independent angle {i}'} for i in range(1,7)]
    def execute(self):return self.crew.execute(self.owner,{'decision':'Use addition after comparing input and alternative interpretations','tasks':self.tasks()})
    def checked_output(self):
        (self.root/'output.txt').write_text('5',encoding='utf-8')
        ev=Evidence(evidence_directory(self.state,self.owner),self.root)
        ev.begin({'task_id':'sum','design':'Parse two integers and sum them','requirements':self.contract['requirements'],
                  'allowed_paths':['output.txt'],'checks':[{'id':'sum','purpose':'Assert actual output and source match',
                  'argv':[sys.executable,'-c',"from pathlib import Path; a=Path('input.txt').read_text().strip().split(','); assert Path('output.txt').read_text()==str(sum(map(int,a)))"],
                  'dependencies':['input.txt','output.txt'],'covers':[0]}]})
        if not ev.run_all()['status']['passed']:raise AssertionError(ev.status())
        return ev
    def planning(self):self.start();self.dispatch();self.reports();self.execute()
    def reviewing(self):
        self.planning();self.dispatch();self.reports();ev=self.checked_output()
        self.crew.review(self.owner,'All six findings checked; review the combined output');self.dispatch();self.reports()
        return ev
    def complete(self):
        ev=self.reviewing()
        ev.finish('tested','Saved output.txt with the checked sum','Six final reports and execution evidence agree','Only this declared test fixture is certified')
        self.store.put(self.owner,'finish_generation',self.store.get(self.owner,'generation'))
        return self.crew.complete(self.owner,'Inspected the final artifact and all six source-linked reports')

class FixedSevenTests(unittest.TestCase):
    def setUp(self):self.f=Fixture()
    def tearDown(self):self.f.close()
    def test_exact_seven_and_reuse_full_loop(self):
        s=self.f.complete();self.assertTrue(s['complete'])
        self.assertEqual(6,sum(c['tool']=='spawn_agent' for c in self.f.calls))
        self.assertEqual(12,sum(c['tool']=='send_input' for c in self.f.calls))
        self.assertEqual(6,s['observed_children'])
        self.assertIsNone(self.f.crew.completion_problem(self.f.owner))
        end=self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop','last_assistant_message':'LUNASTRA_STATUS=TESTED'})
        self.assertNotIn('decision',end);self.assertNotIn('stopReason',end)
    def test_reservation_is_not_native_agent(self):
        self.f.start();self.assertEqual(6,len(self.f.crew.next(self.f.owner)['calls']))
        self.assertEqual(0,self.f.crew.status(self.f.owner)['observed_children'])
        with self.assertRaises(HarnessError):self.f.execute()
    def test_round_requires_six_reports(self):
        self.f.start();self.f.dispatch()
        with self.assertRaises(HarnessError):self.f.execute()
    def test_no_seventh_child_or_nested_spawn(self):
        self.f.start();calls=self.f.dispatch()
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'extra',{'message':'LUNASTRA_TICKET='+'a'*32,'fork_context':True},'gpt-5.6-luna','spawn_agent')
        child={**self.f.event,'session_id':'child-1','agent_id':'child-1','hook_event_name':'PreToolUse',
               'tool_name':'spawn_agent','tool_input':calls[0]['arguments'],'tool_use_id':'nested'}
        self.assertEqual('deny',self.f.hooks.handle(child)['hookSpecificOutput']['permissionDecision'])
    def test_reused_call_identity_rejects_modified_payload(self):
        self.f.start();c=self.f.crew.next(self.f.owner)['calls'][0]
        self.f.crew.pre_dispatch(self.f.owner,'call',c['arguments'],'gpt-5.6-luna','spawn_agent')
        changed={**c['arguments'],'message':c['arguments']['message']+' altered'}
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'call',changed,'gpt-5.6-luna','spawn_agent')
    def test_unknown_spawn_never_replaced(self):
        self.f.start();c=self.f.crew.next(self.f.owner)['calls'][0]
        self.f.crew.pre_dispatch(self.f.owner,'call',c['arguments'],'gpt-5.6-luna','spawn_agent')
        self.f.crew.post_dispatch(self.f.owner,'call',{'text':'looks successful'})
        self.assertEqual(5,len(self.f.crew.next(self.f.owner)['calls']))
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'retry',c['arguments'],'gpt-5.6-luna','spawn_agent')
    def test_no_model_or_effort_override(self):
        self.f.start();c=self.f.crew.next(self.f.owner)['calls'][0]
        for field in ('model','reasoning_effort','service_tier','agent_type'):
            with self.subTest(field=field),self.assertRaises(HarnessError):
                self.f.crew.pre_dispatch(self.f.owner,field,{**c['arguments'],field:'xhigh'},'gpt-5.6-luna','spawn_agent')
    def test_duplicate_native_identity_rejected(self):
        self.f.start();calls=self.f.crew.next(self.f.owner)['calls']
        for i in range(2):self.f.crew.pre_dispatch(self.f.owner,str(i),calls[i]['arguments'],'gpt-5.6-luna','spawn_agent')
        self.f.crew.post_dispatch(self.f.owner,'0',{'agent_id':'same'})
        with self.assertRaises(HarnessError):self.f.crew.post_dispatch(self.f.owner,'1',{'agent_id':'same'})
    def test_initial_forks_must_inherit_full_context(self):
        # Explicit legacy/full mode remains enforced; 4.2 new default is capsule.
        self.f.contract['native']={'protocol':'v1','context':'full'}
        self.f.start();c=self.f.crew.next(self.f.owner)['calls'][0]
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'call',{**c['arguments'],'fork_context':False},'gpt-5.6-luna','spawn_agent')
    def test_worker_cannot_join_another_slot(self):
        self.f.start();self.f.dispatch();s=self.f.crew.status(self.f.owner)
        with self.assertRaises(HarnessError):self.f.crew.join(self.f.keys[1],s['tasks'][1]['ticket'],self.f.store.get(self.f.keys[1],'meta'))
    def test_final_output_mutation_invalidates_completion(self):
        self.f.complete();(self.f.root/'output.txt').write_text('6',encoding='utf-8')
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
    def test_review_cannot_precede_actual_checks(self):
        self.f.planning();self.f.dispatch();self.f.reports()
        with self.assertRaises((HarnessError,OSError)):self.f.crew.review(self.f.owner,'Ready for review')
    def test_requirements_cannot_be_weakened(self):
        self.f.planning();self.f.dispatch();self.f.reports();self.f.checked_output()
        ev=Evidence(evidence_directory(self.f.state,self.f.owner))
        with ev._db() as db:
            task=ev._get(db,'task');task['requirements']=['different easy condition']
        ev.begin(task);ev.run_all()
        with self.assertRaises(HarnessError):self.f.crew.review(self.f.owner,'Review')
    def test_final_review_needs_artifact_reference(self):
        self.f.planning();self.f.dispatch();self.f.reports();self.f.checked_output()
        self.f.crew.review(self.f.owner,'Review');self.f.dispatch()
        with self.assertRaises(HarnessError):self.f.crew.report(self.f.keys[1],{'verdict':'clear','summary':'Conclusion','findings':['Observed'], 'references':[{'requirement':0}],'covers':[0]})
    def test_final_review_snapshot_change_rejected(self):
        self.f.planning();self.f.dispatch();self.f.reports();self.f.checked_output()
        self.f.crew.review(self.f.owner,'Review');self.f.dispatch();(self.f.root/'output.txt').write_text('6')
        with self.assertRaises(HarnessError):self.f.reports()
    def test_two_slots_are_permanently_independent(self):
        self.f.start();self.f.dispatch();self.f.reports();tasks=self.f.tasks();tasks[4]['kind']='implement';tasks[4]['paths']=['output.txt']
        with self.assertRaises(HarnessError):self.f.crew.execute(self.f.owner,{'decision':'Use writer','tasks':tasks})
    def test_empty_or_seven_task_plan_rejected(self):
        self.f.start();self.f.dispatch();self.f.reports()
        for tasks in ([],self.f.tasks()[:5],self.f.tasks()+[self.f.tasks()[0]]):
            with self.subTest(n=len(tasks)),self.assertRaises(HarnessError):self.f.crew.execute(self.f.owner,{'decision':'Execute','tasks':tasks})
    def test_outside_scope_implementation_rejected(self):
        self.f.start();self.f.dispatch();self.f.reports();tasks=self.f.tasks();tasks[0].update(kind='implement',paths=['input.txt'])
        with self.assertRaises(HarnessError):self.f.crew.execute(self.f.owner,{'decision':'Execute','tasks':tasks})
    def test_source_only_synthesis_is_not_final_completion(self):
        self.f.planning()
        with self.assertRaises(HarnessError):self.f.crew.complete(self.f.owner,'Looks finished')
    def test_worker_must_report_before_native_stop(self):
        self.f.start();self.f.dispatch()
        result=self.f.hooks.handle({**self.f.event,'session_id':'child-1','agent_id':'child-1',
                'hook_event_name':'SubagentStop','last_assistant_message':'done'})
        self.assertEqual('block',result['decision'])
    def test_restart_recovers_exact_roster(self):
        self.f.start();self.f.dispatch();before=self.f.crew.summary(self.f.owner)
        resumed=Crew(Store(self.f.state),PACKAGE).summary(self.f.owner)
        self.assertEqual(before,resumed)
    def test_compaction_restores_fixed_kernel_and_phase(self):
        self.f.start();self.f.dispatch()
        self.f.hooks.handle({**self.f.event,'hook_event_name':'PostCompact'})
        result=self.f.hooks.handle({**self.f.event,'hook_event_name':'SessionStart','source':'compact'})
        content=result['hookSpecificOutput']['additionalContext']
        self.assertIn('Fixed-seven',content);self.assertIn('child-1',content);self.assertIn('PLAN',content)
    def test_new_user_request_invalidates_contract(self):
        self.f.complete()
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'Actually output 9 instead','turn_id':'turn-2'})
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
    def test_hook_continuation_preserves_goal(self):
        self.f.start();digest=self.f.store.get(self.f.owner,'request_hash')
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'LUNASTRA_CONTINUE: finish missing review','turn_id':'turn-2'})
        self.assertEqual(digest,self.f.store.get(self.f.owner,'request_hash'))
    def test_concurrent_next_does_not_duplicate_reservations(self):
        self.f.start()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:Crew(Store(self.f.state),PACKAGE).next(self.f.owner),range(2)))
        tickets={r['ticket'] for result in results for r in result['calls']}
        self.assertEqual(6,len(tickets))
        self.assertEqual(6,len(self.f.crew.status(self.f.owner)['tasks']))
    def test_worker_evidence_context_changes_without_deleting_previous(self):
        self.f.start();self.f.dispatch();key=self.f.keys[1];old=evidence_directory(self.f.state,key)
        old.mkdir(parents=True);(old/'marker.txt').write_text('retained')
        self.f.reports();self.f.execute();self.f.dispatch();new=evidence_directory(self.f.state,key)
        self.assertNotEqual(old,new);self.assertEqual('retained',(old/'marker.txt').read_text())
    def test_binary_snapshot_and_missing_paths(self):
        p=self.f.root/'binary.xlsx';p.write_bytes(b'PK\x03\x04\xff\x00')
        a=fingerprint(self.f.root,['binary.xlsx','future.txt'])
        self.assertTrue(a['entries']['future.txt']['missing'])
        p.write_bytes(b'PK\x03\x04\xff\x01');b=fingerprint(self.f.root,['binary.xlsx','future.txt'])
        self.assertNotEqual(a['sha256'],b['sha256'])
    def test_path_escape_rejected(self):
        for name in ('../outside','/tmp/outside','.git'):
            with self.subTest(path=name),self.assertRaises(HarnessError):
                c=copy.deepcopy(self.f.contract);c['output_paths']=[name];self.f.crew.start(self.f.owner,c)

if __name__=='__main__':unittest.main()
