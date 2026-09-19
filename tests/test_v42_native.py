"""Pinned V1/V2 wire-shape tests. Synthetic host events, NOT a live host claim."""
import copy
import json
import unittest
from unittest.mock import patch
from test_fixed_seven import Fixture, PACKAGE
from luna_astra.native import configuration, dispatch, followup_ack, spawn_target, capsule_ready, target
from luna_astra.flow import Flow
from luna_astra.native_flow import NativeFlow
from luna_astra.util import HarnessError
from luna_astra.transport import tool_name


class NativeWireTests(unittest.TestCase):
    def state(self,protocol='v2',context='capsule'):
        return {'run_id':'a'*32,'native':{'protocol':protocol,'context':context,'capacity_total':7}}
    def test_new_default_is_v1_capsule(self):
        self.assertEqual({'protocol':'v1','context':'capsule'},configuration())
    def test_existing_absent_profile_is_full(self):
        self.assertEqual('full',configuration(legacy=True)['context'])
    def test_invalid_protocol_or_override_rejected(self):
        for value in ({'protocol':'v3'},{'context':'guess'},{'model':'x'},[],False):
            with self.subTest(value=value),self.assertRaises(HarnessError):configuration(value)
    def test_v1_capsule_omits_parent_history(self):
        tool,args=dispatch(self.state('v1'),1,'m');self.assertEqual('spawn_agent',tool);self.assertIs(False,args['fork_context'])
    def test_v1_explicit_full_preserved(self):
        self.assertIs(True,dispatch(self.state('v1','full'),1,'m')[1]['fork_context'])
    def test_v2_capsule_has_native_required_fields(self):
        tool,args=dispatch(self.state(),1,'m')
        self.assertEqual({'task_name','message','fork_turns'},set(args));self.assertEqual('none',args['fork_turns'])
    def test_v2_full_uses_all_without_fork_context(self):
        args=dispatch(self.state('v2','full'),1,'m')[1]
        self.assertEqual('all',args['fork_turns']);self.assertNotIn('fork_context',args)
    def test_reuse_is_v1_send_or_v2_followup(self):
        self.assertEqual(('followup_task',{'target':'/root/a','message':'m'}),dispatch(self.state(),1,'m','/root/a'))
        self.assertEqual('send_input',dispatch(self.state('v1'),1,'m','uuid')[0])
    def test_no_model_or_effort_override_generated(self):
        for version in ('v1','v2'):
            for handle in (None,'known'):
                args=dispatch(self.state(version),1,'m',handle)[1]
                self.assertFalse(set(args)&{'model','reasoning_effort','service_tier','agent_type'})
    def test_v2_task_name_not_uuid(self):
        state=self.state();path='/root/la_'+state['run_id'][:12]+'_s1'
        self.assertEqual(path,spawn_target(state,1,{'task_name':path,'nickname':'Synthetic'}))
        self.assertIsNone(spawn_target(state,1,{'agent_id':'uuid'}))
    def test_v2_wrong_slot_and_traversal_rejected(self):
        state=self.state();tail='la_'+state['run_id'][:12]+'_s1'
        for path in ('/root/../'+tail,'/root/wrong',tail,'/root/'+tail+'extra'):
            self.assertIsNone(spawn_target(state,1,{'task_name':path}))
    def test_v2_empty_followup_ack_is_explicit(self):
        for response in ('',[],{'content':[]},{'content':[{'type':'text','text':''}],'isError':False}):
            self.assertTrue(followup_ack(self.state(),response))
    def test_v2_unknown_or_error_ack_rejected(self):
        for response in (None,{},'done',{'content':[],'isError':True},{'content':[{'type':'text','text':'error'}]}):
            self.assertFalse(followup_ack(self.state(),response))
    def test_v1_empty_ack_not_accepted(self):
        self.assertFalse(followup_ack(self.state('v1'),''))
        self.assertTrue(followup_ack(self.state('v1'),{'submission_id':'real-fixture'}))
    def test_only_documented_native_names_normalized(self):
        for name in ('spawn_agent','followup_task','wait_agent','list_agents','send_message','interrupt_agent'):
            self.assertEqual(name,tool_name('multi_agent_v2'+name));self.assertEqual(name,tool_name('functions.'+name))
        self.assertEqual('mcp_fake_spawn_agent',tool_name('mcp_fake_spawn_agent'))


class V2Fixture(Fixture):
    def __init__(self, protocol='v2'):
        super().__init__();self.contract['native']={'protocol':protocol,'context':'capsule','capacity_total':7}
        self.protocol=protocol;self.native_handles={}
    def one(self, call, *, join=True, start_first=False):
        phase=self.crew.status(self.owner)['round'];slot=call['slot'];uid=f'r{phase}-s{slot}'
        before={**self.event,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v2'+call['tool'] if self.protocol=='v2' else call['tool'],
                'tool_input':call['arguments'],'tool_use_id':uid}
        result=self.hooks.handle(before)
        if result.get('hookSpecificOutput',{}).get('permissionDecision')=='deny':raise AssertionError(result)
        agent='observed-'+self.protocol+'-'+str(slot)
        child={**self.event,'session_id':agent,'agent_id':agent,'hook_event_name':'SubagentStart' if phase==1 else 'UserPromptSubmit',
               'prompt':call['arguments']['message']}
        if start_first:self.hooks.handle(child)
        if call['tool']=='spawn_agent':
            if self.protocol=='v2':
                handle='/root/'+call['arguments']['task_name'];self.native_handles[slot]=handle;ack={'task_name':handle}
            else:self.native_handles[slot]=agent;ack={'agent_id':agent}
        else:ack='' if self.protocol=='v2' else {'submission_id':uid}
        self.hooks.handle({**before,'hook_event_name':'PostToolUse','tool_response':ack})
        if join:
            if not start_first:self.hooks.handle(child)
            key=self.store.get('__agent_alias__',agent)['key'];self.keys[slot]=key
            self.crew.join(key,call['ticket'],self.store.get(key,'meta'))
        self.calls.append(call);return before
    def dispatch(self):
        calls=[]
        for _ in range(7):
            batch=self.crew.next(self.owner)['calls']
            if not batch:break
            for call in batch:self.one(call);calls.append(call)
        return calls
    def reports(self,verdict='clear'):
        state=self.crew.status(self.owner)
        for row in state['tasks']:
            slot=int(row['id'][1:]);key=self.keys[slot]
            self.crew.report(key,{'verdict':verdict,'summary':'Original assigned sources inspected',
                'findings':['The declared requirement holds in this fixture'],
                'references':[{'path':'output.txt' if state['phase']=='REVIEW' else 'input.txt'}],'covers':[0]})
            agent='observed-'+self.protocol+'-'+str(slot)
            out=self.hooks.handle({**self.event,'hook_event_name':'SubagentStop','session_id':agent,'agent_id':agent,
                                   'last_assistant_message':'LUNASTRA_STATUS=ANALYSIS'})
            if out.get('decision')=='block' or out.get('continue') is False:raise AssertionError(out)


class NativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.f=V2Fixture();self.addCleanup(self.f.close)
    def wait(self,uid='wait',response=None):
        flow=Flow(self.f.store,PACKAGE);flow.pre_wait(self.f.owner,uid,{'timeout_ms':60000})
        flow.post_wait(self.f.owner,uid,response if response is not None else {'message':'Wait completed.','timed_out':False})
        return flow
    def listed(self,states,uid='list'):
        native=NativeFlow(self.f.store,self.f.crew);native.pre(self.f.owner,uid,'list_agents',{})
        native.post(self.f.owner,uid,'list_agents',{'agents':[{'agent_name':self.f.native_handles[s],'agent_status':v} for s,v in states.items()]})
    def test_complete_v2_three_rounds_same_six(self):
        result=self.f.complete();self.assertTrue(result['complete']);self.assertEqual(6,result['observed_children'])
        self.assertEqual(6,sum(c['tool']=='spawn_agent' for c in self.f.calls))
        self.assertEqual(12,sum(c['tool']=='followup_task' for c in self.f.calls))
        self.assertEqual({},self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop','last_assistant_message':'LUNASTRA_STATUS=TESTED'}))
    def test_complete_v1_capsule_three_rounds(self):
        f=V2Fixture('v1');self.addCleanup(f.close)
        self.assertTrue(f.complete()['complete']);self.assertEqual(6,sum(c['tool']=='spawn_agent' for c in f.calls))
        self.assertTrue(all(c['arguments'].get('fork_context') is False for c in f.calls if c['tool']=='spawn_agent'))
    def test_first_of_six_checks_model_before_other_five(self):
        self.f.start();calls=self.f.crew.next(self.f.owner)['calls'];self.assertEqual(1,len(calls))
        self.f.one(calls[0],join=False)
        self.assertEqual([],self.f.crew.next(self.f.owner)['calls'])
        self.assertEqual('WAIT',Flow(self.f.store,PACKAGE).drive(self.f.owner)['action'])
        self.assertEqual(0,self.f.crew.status(self.f.owner)['observed_children'])
    def test_runtime_id_not_inferred_from_name(self):
        self.f.start();call=self.f.crew.next(self.f.owner)['calls'][0];self.f.one(call,join=False)
        s=self.f.crew.status(self.f.owner);self.assertIsNone(s['members'][0]['agent_id'])
        self.assertTrue(self.f.native_handles[1].startswith('/root/'))
    def test_hook_before_spawn_ack_can_join_after_ack(self):
        self.f.start();call=self.f.crew.next(self.f.owner)['calls'][0];self.f.one(call,start_first=True)
        self.assertEqual(1,self.f.crew.status(self.f.owner)['observed_children'])
        self.assertEqual(5,len(self.f.crew.next(self.f.owner)['calls']))
    def test_no_worker_hook_no_binding(self):
        self.f.start();call=self.f.crew.next(self.f.owner)['calls'][0];self.f.one(call,join=False)
        with self.assertRaises(HarnessError):self.f.crew.join(self.f.owner,call['ticket'],self.f.store.get(self.f.owner,'meta'))
    def test_v2_wait_rejects_v1_targets(self):
        self.f.start();self.f.dispatch()
        with self.assertRaises(HarnessError):Flow(self.f.store,PACKAGE).pre_wait(self.f.owner,'bad',{'targets':['x'],'timeout_ms':1})
    def test_mailbox_wake_never_completes_work(self):
        self.f.start();self.f.dispatch();flow=self.wait()
        self.assertTrue(all(r['state']=='running' for r in self.f.crew.status(self.f.owner)['tasks']))
        self.assertEqual('OBSERVE_NATIVE',flow.drive(self.f.owner)['action'])
    def test_actual_list_terminal_still_requires_report(self):
        self.f.start();self.f.dispatch();self.wait();self.listed({i:{'completed':'not evidence'} for i in range(1,7)})
        row=self.f.crew.status(self.f.owner)['tasks'][0]
        self.assertEqual('UNVERIFIED',row['result']['status'])
        self.assertFalse(self.f.crew.status(self.f.owner).get('complete',False))
        self.assertEqual('RECOVER',Flow(self.f.store,PACKAGE).drive(self.f.owner)['action'])
    def test_v2_recovery_reuses_target_and_ticket(self):
        self.f.start();self.f.dispatch();self.wait();self.listed({i:{'completed':None} for i in range(1,7)})
        flow=Flow(self.f.store,PACKAGE);call=flow.prepare_recovery(self.f.owner,1)
        self.assertEqual('followup_task',call['tool']);self.assertEqual(self.f.native_handles[1],call['arguments']['target'])
        self.assertNotIn('interrupt',call['arguments'])
        self.f.crew.pre_dispatch(self.f.owner,'recover',call['arguments'],self.f.event['model'],call['tool'])
        self.f.crew.post_dispatch(self.f.owner,'recover','')
        self.assertEqual('running',self.f.crew.status(self.f.owner)['tasks'][0]['state'])
    def test_duplicate_wait_receipt_changed_is_rejected(self):
        self.f.start();self.f.dispatch();flow=self.wait()
        with self.assertRaises(HarnessError):flow.post_wait(self.f.owner,'wait',{'message':'changed','timed_out':True})
    def test_missing_pre_observation_does_not_bind_status(self):
        self.f.start();self.f.dispatch()
        NativeFlow(self.f.store,self.f.crew).post(self.f.owner,'unseen','list_agents',{'agents':[{'agent_name':self.f.native_handles[1],'agent_status':{'completed':None}}]})
        self.assertEqual('running',self.f.crew.status(self.f.owner)['tasks'][0]['state'])
    def test_unrelated_agent_not_ours(self):
        self.f.start();self.f.dispatch();native=NativeFlow(self.f.store,self.f.crew)
        native.pre(self.f.owner,'list','list_agents',{})
        native.post(self.f.owner,'list','list_agents',{'agents':[{'agent_name':'/elsewhere','agent_status':{'completed':'no'}}]})
        self.assertTrue(all(r['state']=='running' for r in self.f.crew.status(self.f.owner)['tasks']))
    def test_native_failure_not_fabricated_success(self):
        self.f.start();self.f.dispatch();self.wait();self.listed({1:{'errored':'fixture'}})
        self.assertEqual('BLOCKED',Flow(self.f.store,PACKAGE).drive(self.f.owner)['action'])
    def test_v2_side_channel_and_interrupt_are_blocked(self):
        self.f.start()
        for name in ('send_message','interrupt_agent'):
            out=self.f.hooks.handle({**self.f.event,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v2'+name,
                                   'tool_use_id':name,'tool_input':{'target':'any','message':'bad'}})
            self.assertEqual('deny',out['hookSpecificOutput']['permissionDecision'])
    def test_effort_override_is_rejected(self):
        self.f.start();call=self.f.crew.next(self.f.owner)['calls'][0]
        with self.assertRaises(HarnessError):self.f.crew.pre_dispatch(self.f.owner,'bad',{**call['arguments'],'reasoning_effort':'high'},self.f.event['model'],'spawn_agent')
    def test_canonical_unknown_ack_not_retried_as_new_agent(self):
        self.f.start();call=self.f.crew.next(self.f.owner)['calls'][0]
        self.f.crew.pre_dispatch(self.f.owner,'call',call['arguments'],self.f.event['model'],'spawn_agent')
        self.f.crew.post_dispatch(self.f.owner,'call',{'task_name':'wrong'})
        self.assertEqual('BLOCKED',Flow(self.f.store,PACKAGE).drive(self.f.owner)['action'])
    def test_late_list_from_before_followup_does_not_end_new_work(self):
        self.f.start();self.f.dispatch();native=NativeFlow(self.f.store,self.f.crew)
        native.pre(self.f.owner,'old-list','list_agents',{})
        self.wait();self.listed({i:{'completed':None} for i in range(1,7)},'new-list')
        flow=Flow(self.f.store,PACKAGE);call=flow.prepare_recovery(self.f.owner,1)
        self.f.crew.pre_dispatch(self.f.owner,'followup',call['arguments'],self.f.event['model'],call['tool'])
        self.f.crew.post_dispatch(self.f.owner,'followup','')
        native.post(self.f.owner,'old-list','list_agents',{'agents':[{'agent_name':self.f.native_handles[1],'agent_status':{'completed':'stale'}}]})
        self.assertEqual('running',self.f.crew.status(self.f.owner)['tasks'][0]['state'])

    def test_old_list_does_not_consume_new_wait_request(self):
        self.f.start();self.f.dispatch();n=NativeFlow(self.f.store,self.f.crew)
        n.pre(self.f.owner,'old','list_agents',{})
        self.wait('new-wait')
        n.post(self.f.owner,'old','list_agents',{'agents':[]})
        self.assertEqual('OBSERVE_NATIVE',Flow(self.f.store,PACKAGE).drive(self.f.owner)['action'])
    def test_observed_wait_resets_idle_stop_counter(self):
        self.f.start();self.f.dispatch();flow=Flow(self.f.store,PACKAGE)
        meta=self.f.store.get(self.f.owner,'meta')
        for i in range(5):
            flow.pre_wait(self.f.owner,'elapsed-'+str(i),{'timeout_ms':60000})
            with self.f.store.db(True) as db:
                db.execute('UPDATE native_observations SET started=started-2 WHERE owner=? AND call_id=?',(self.f.owner,'elapsed-'+str(i)))
            flow.post_wait(self.f.owner,'elapsed-'+str(i),{'message':'timeout','timed_out':True})
            self.assertIsNotNone(flow.correction(self.f.owner,meta,'Workers are still pending'))
            self.assertEqual(0,self.f.store.get(self.f.owner,'flow-stop')['idle'])
    def test_malformed_list_does_not_partially_apply_statuses(self):
        self.f.start();self.f.dispatch();n=NativeFlow(self.f.store,self.f.crew)
        n.pre(self.f.owner,'bad-list','list_agents',{})
        n.post(self.f.owner,'bad-list','list_agents',{'agents':[
            {'agent_name':self.f.native_handles[1],'agent_status':{'completed':None}},
            {'agent_name':self.f.native_handles[2],'agent_status':'invented'}]})
        self.assertTrue(all(r['state']=='running' for r in self.f.crew.status(self.f.owner)['tasks']))

if __name__=='__main__':unittest.main()
