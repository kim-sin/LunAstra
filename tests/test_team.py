import copy
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from luna_astra.store import Store
from luna_astra.team import Team,unpack_response
from luna_astra.util import HarnessError

class TeamTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'repo';self.root.mkdir()
        self.store=Store(self.base/'state');self.team=Team(self.store)
        self.store.put('root','meta',{'role':'root','workspace':str(self.root),'session_id':'parent','model':'gpt-5.6-luna'})
    def task(self,i=0,kind='investigate',paths=None,deps=None):
        return {'id':'task'+str(i),'kind':kind,'description':'Inspect component '+str(i),'paths':paths or ['src'+str(i)],'depends_on':deps or [],'done_when':['Provide a source-backed outcome'],'why_parallel':'Independent component with separate evidence'}
    def plan(self,tasks=None,**kw):
        return self.team.plan('root',self.root,{'goal':'Complete the requested change','tasks':tasks if tasks is not None else [self.task()],**kw})
    def ticket(self):self.plan();return self.team.reserve('root')['reserved'][0]['ticket']
    def payload(self,ticket):return {'message':'LUNASTRA_TICKET='+ticket+'\nInspect','fork_context':True}
    def worker(self,agent='child'):
        return {'role':'worker','workspace':str(self.root),'session_id':'parent','parent_session_id':'parent','agent_id':agent,'model':'gpt-5.6-luna'}
    def test_zero_delegation_valid(self):self.assertTrue(self.plan([])['complete'])
    def test_cap_not_always_six(self):
        self.plan([self.task(i) for i in range(8)],parallel_limit=2)
        self.assertEqual(len(self.team.reserve('root')['reserved']),2)
    def test_six_is_hard_maximum(self):
        self.plan([self.task(i) for i in range(12)])
        self.assertEqual(len(self.team.reserve('root')['reserved']),6)
        self.assertFalse(self.team.reserve('root')['reserved'])
    def test_invalid_caps(self):
        for cap in (True,0,7,'6'):
            with self.subTest(cap=cap),self.assertRaises(HarnessError):self.plan(parallel_limit=cap)
    def test_invalid_budgets(self):
        for limit in (0,9,True):
            with self.subTest(limit=limit),self.assertRaises(HarnessError):self.plan(launch_limit=limit)
    def test_reservations_are_not_agents(self):
        self.ticket();r=self.team.status('root')['tasks'][0]
        self.assertEqual(r['state'],'reserved');self.assertIsNone(r['agent_id'])
    def test_duplicate_plan_is_idempotent(self):
        a=self.plan();b=self.plan();self.assertEqual(a['plan_id'],b['plan_id'])
    def test_different_unfinished_plan_rejected(self):
        self.plan();self.team.reserve('root')
        with self.assertRaises(HarnessError):self.plan([self.task(1)])
    def test_duplicate_ids_rejected(self):
        with self.assertRaises(HarnessError):self.plan([self.task(),self.task()])
    def test_duplicate_descriptions_rejected(self):
        second=self.task(1);second['description']=self.task()['description']
        with self.assertRaises(HarnessError):self.plan([self.task(),second])
    def test_dependency_cycle_rejected(self):
        with self.assertRaises(HarnessError):self.plan([self.task(0,deps=['task1']),self.task(1,deps=['task0'])])
    def test_unknown_dependency_rejected(self):
        with self.assertRaises(HarnessError):self.plan([self.task(deps=['missing'])])
    def test_dependencies_wait_for_acceptance(self):
        self.plan([self.task(),self.task(1,deps=['task0'])]);a=self.team.reserve('root')['reserved'];self.assertEqual(len(a),1)
        self.team.returned(a[0]['ticket'],{'status':'ANALYSIS'});self.assertFalse(self.team.reserve('root')['reserved'])
        self.team.accept('root','task0','Checked references');self.assertEqual(len(self.team.reserve('root')['reserved']),1)
    def test_overlapping_writers_are_serialized(self):
        self.plan([self.task(0,'implement',['src']),self.task(1,'implement',['src/a.py'])])
        self.assertEqual(len(self.team.reserve('root')['reserved']),1)
    def test_disjoint_writers_can_run_in_parallel(self):
        self.plan([self.task(0,'implement',['a.py']),self.task(1,'implement',['b.py'])]);self.assertEqual(len(self.team.reserve('root')['reserved']),2)
    def test_whole_repo_write_scope_rejected(self):
        with self.assertRaises(HarnessError):self.plan([self.task(0,'implement',['.'])])
    def test_escape_scope_rejected(self):
        with self.assertRaises(HarnessError):self.plan([self.task(paths=['../outside'])])
    def test_control_file_scope_rejected(self):
        with self.assertRaises(HarnessError):self.plan([self.task(paths=['.git/config'])])
    def test_observable_completion_required(self):
        t=self.task();t['done_when']=[]
        with self.assertRaises(HarnessError):self.plan([t])
    def test_parallel_reason_required(self):
        t=self.task();t['why_parallel']=''
        with self.assertRaises(HarnessError):self.plan([t])
    def test_concurrent_reservation_cannot_exceed_cap(self):
        self.plan([self.task(i) for i in range(12)],parallel_limit=3)
        with ThreadPoolExecutor(max_workers=4) as pool:items=list(pool.map(lambda _:self.team.reserve('root'),range(4)))
        self.assertEqual(sum(len(r['reserved']) for r in items),3)
    def test_fork_spawn_preserves_model_effort(self):
        ticket=self.ticket();self.assertEqual(self.team.pre_spawn('root','call',self.payload(ticket),'gpt-5.6-luna'),ticket)
    def test_foreign_model_denied(self):
        ticket=self.ticket()
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','call',{**self.payload(ticket),'model':'gpt-6-astra'},'gpt-5.6-luna')
    def test_effort_override_denied(self):
        ticket=self.ticket()
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','call',{**self.payload(ticket),'reasoning_effort':'max'},'gpt-5.6-luna')
    def test_custom_role_override_denied(self):
        ticket=self.ticket()
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','call',{**self.payload(ticket),'agent_type':'custom'},'gpt-5.6-luna')
    def test_untracked_spawn_denied(self):
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','call',{'message':'do more'},'gpt-5.6-luna')
    def test_fresh_spawn_requires_same_model(self):
        ticket=self.ticket()
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','call',{'message':'LUNASTRA_TICKET='+ticket},'gpt-5.6-luna')
    def test_v2_full_fork_supported(self):
        ticket=self.ticket();self.team.pre_spawn('root','call',{'message':'LUNASTRA_TICKET='+ticket,'task_name':'inspection'},'gpt-5.6-luna')
    def test_double_dispatch_denied(self):
        ticket=self.ticket();p=self.payload(ticket);self.team.pre_spawn('root','one',p,'gpt-5.6-luna')
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','two',p,'gpt-5.6-luna')
    def test_identical_tool_event_is_idempotent(self):
        ticket=self.ticket();p=self.payload(ticket)
        self.assertEqual(self.team.pre_spawn('root','one',p,'gpt-5.6-luna'),self.team.pre_spawn('root','one',p,'gpt-5.6-luna'))
    def test_unknown_spawn_result_keeps_reservation(self):
        t=self.ticket();self.team.pre_spawn('root','one',self.payload(t),'gpt-5.6-luna');self.team.post_spawn('root','one',{'text':'done'})
        self.assertEqual(self.team.status('root')['active'],1)
        with self.assertRaises(HarnessError):self.team.abandon('root','task0','unknown is not stopped')
    def test_explicit_failed_spawn_can_be_abandoned(self):
        t=self.ticket();self.team.pre_spawn('root','one',self.payload(t),'gpt-5.6-luna');self.team.post_spawn('root','one',{'isError':True})
        self.team.abandon('root','task0','host rejected launch');self.assertFalse(self.team.status('root')['complete'])
    def test_worker_identity_bound_to_actual_result(self):
        t=self.ticket();self.team.pre_spawn('root','one',self.payload(t),'gpt-5.6-luna');self.team.post_spawn('root','one',{'agent_id':'child'})
        self.team.join('worker',t,self.worker());self.assertEqual(self.team.lookup(t)['agent_id'],'child')
    def test_wrong_worker_cannot_join(self):
        t=self.ticket();self.team.pre_spawn('root','one',self.payload(t),'gpt-5.6-luna');self.team.post_spawn('root','one',{'agent_id':'child'})
        with self.assertRaises(HarnessError):self.team.join('other',t,self.worker('other'))
    def test_foreign_parent_cannot_join(self):
        t=self.ticket()
        with self.assertRaises(HarnessError):self.team.join('worker',t,{**self.worker(),'parent_session_id':'foreign'})
    def test_root_cannot_join_worker_ticket(self):
        t=self.ticket()
        with self.assertRaises(HarnessError):self.team.join('root',t,{**self.worker(),'role':'root'})
    def test_running_worker_cannot_be_abandoned(self):
        t=self.ticket();self.team.join('worker',t,self.worker())
        with self.assertRaises(HarnessError):self.team.abandon('root','task0','do not kill it')
    def test_returned_is_not_accepted(self):
        t=self.ticket();self.team.returned(t,{'status':'ANALYSIS'});self.assertFalse(self.team.status('root')['complete'])
    def test_unverified_work_cannot_be_accepted(self):
        t=self.ticket();self.team.returned(t,{'status':'UNVERIFIED'})
        with self.assertRaises(HarnessError):self.team.accept('root','task0','looks okay')
    def test_implementation_requires_integration(self):
        self.plan([self.task(0,'implement',['a.py'])]);t=self.team.reserve('root')['reserved'][0]['ticket'];self.team.returned(t,{'status':'TESTED'})
        with self.assertRaises(HarnessError):self.team.accept('root','task0','looks okay')
    def test_review_is_required(self):
        t=self.ticket();self.team.returned(t,{'status':'ANALYSIS'})
        with self.assertRaises(HarnessError):self.team.accept('root','task0','')
    def test_local_fallback_needs_checked_evidence(self):
        self.plan()
        with self.assertRaises(HarnessError):self.team.resolve_locally('root','task0','done',{'passed':False})
    def test_local_fallback_closes_abandoned_task(self):
        self.ticket();self.team.abandon('root','task0','dirty checkout retained')
        self.team.resolve_locally('root','task0','implemented locally',{'passed':True,'finish':{'kind':'tested','valid':True}})
        self.assertTrue(self.team.status('root')['complete'])
    def test_followup_cannot_restart_completed_work(self):
        t=self.ticket();self.team.join('worker',t,self.worker());self.team.pre_followup('root',{'target':'child','message':'clarification'})
        self.team.returned(t,{'status':'ANALYSIS'})
        with self.assertRaises(HarnessError):self.team.pre_followup('root',{'target':'child','message':'new work'})
    def test_native_structured_text_response(self):
        self.assertEqual(unpack_response({'content':[{'type':'text','text':'{"agent_id":"child"}'}]})['agent_id'],'child')
    def test_replacing_a_completed_plan_does_not_reset_turn_budget(self):
        self.plan([self.task(i) for i in range(8)])
        first=self.team.reserve('root')['reserved']
        for t in first:self.team.returned(t['ticket'],{'status':'ANALYSIS'});self.team.accept('root',t['id'],'references checked')
        second=self.team.reserve('root')['reserved']
        for t in second:self.team.returned(t['ticket'],{'status':'ANALYSIS'});self.team.accept('root',t['id'],'references checked')
        self.plan([self.task(20)]);self.assertFalse(self.team.reserve('root')['reserved']);self.assertEqual(self.team.status('root')['launches'],8)
    def test_new_turn_has_its_own_budget(self):
        self.plan([]);self.store.put('root','generation','new-turn');self.plan([self.task()])
        self.assertEqual(len(self.team.reserve('root')['reserved']),1)
    def test_native_terminal_failure_is_not_permanent_running_state(self):
        t=self.ticket();self.team.join('worker',t,self.worker());self.team.observed_statuses('root',{'status':{'child':{'errored':'native failure'}}})
        self.assertEqual(self.team.lookup(t)['state'],'failed');self.team.abandon('root','task0','native failure recorded')
    def test_native_unchecked_completion_is_unverified(self):
        t=self.ticket();self.team.join('worker',t,self.worker());self.team.observed_statuses('root',{'status':{'child':{'completed':'done'}}})
        self.assertEqual(self.team.lookup(t)['state'],'returned')
        with self.assertRaises(HarnessError):self.team.accept('root','task0','not enough evidence')
    def test_cannot_close_running_worker(self):
        t=self.ticket();self.team.join('worker',t,self.worker())
        with self.assertRaises(HarnessError):self.team.pre_close('root',{'target':'child'})
    def test_completed_retained_worker_can_close(self):
        t=self.ticket();self.team.join('worker',t,self.worker());self.team.returned(t,{'status':'ANALYSIS','worker_key':'worker'})
        self.team.pre_close('root',{'target':'child'})
    def test_service_tier_override_denied(self):
        t=self.ticket()
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','one',{**self.payload(t),'service_tier':'priority'},'gpt-5.6-luna')
    def test_fresh_same_model_does_not_assume_effort_inheritance(self):
        t=self.ticket()
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','one',{'message':'LUNASTRA_TICKET='+t,'model':'gpt-5.6-luna'},'gpt-5.6-luna')
    def test_even_default_role_is_not_forced_over_full_fork(self):
        t=self.ticket()
        with self.assertRaises(HarnessError):self.team.pre_spawn('root','one',{**self.payload(t),'agent_type':'default'},'gpt-5.6-luna')
