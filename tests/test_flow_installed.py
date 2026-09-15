"""Installed subprocess boundary; native model messages remain simulated."""
import json
import unittest
import test_fixed_seven_integration as fixture_module

class InstalledFlowTests(unittest.TestCase):
    def setUp(self):
        self.host=fixture_module.InstalledFixedSevenTests(methodName='runTest')
        self.addCleanup(self.host.doCleanups)
        self.host.setUp()
        self.host.cli(['crew-start'],self.host.contract)
        self.host.dispatch(1)
    def wait(self,uid='native-wait'):
        event={**self.host.event,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v1wait_agent',
               'tool_input':{'targets':['native-child-1'],'timeout_ms':60000},'tool_use_id':uid}
        result=self.host.hook(event)
        self.assertNotEqual('deny',result.get('hookSpecificOutput',{}).get('permissionDecision'))
        self.host.hook({**event,'hook_event_name':'PostToolUse','tool_response':{
            'status':{'native-child-1':{'completed':'Finished without a submitted report'}},'timed_out':False}})
    def test_installed_helper_and_active_stop_keep_parent_turn_open(self):
        result=self.host.cli(['crew-drive'])
        self.assertEqual('WAIT',result['action'])
        self.assertEqual(['native-child-1'],result['native_call']['arguments']['targets'])
        stopped=self.host.hook({**self.host.event,'hook_event_name':'Stop',
             'last_assistant_message':'Not done; the six children are running.','stop_hook_active':True})
        self.assertEqual('block',stopped.get('decision'),stopped)
        self.assertIn('wait_agent',stopped['reason'])
    def test_installed_same_member_recovery_submits_real_file_references(self):
        self.wait()
        call=self.host.cli(['crew-recover','1'])
        self.assertEqual('native-child-1',call['arguments']['target'])
        event={**self.host.event,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v1send_input',
               'tool_input':call['arguments'],'tool_use_id':'native-recovery'}
        self.assertNotEqual('deny',self.host.hook(event).get('hookSpecificOutput',{}).get('permissionDecision'))
        self.host.hook({**event,'hook_event_name':'PostToolUse','tool_response':{'submission_id':'ack-recovery'}})
        child=self.host.children[1]
        self.host.cli(['crew-join',call['ticket']],prefix=child['prefix'])
        self.assertTrue(self.host.report(1,['app.py'])['recorded'])
        stopped=self.host.hook({**child['event'],'hook_event_name':'SubagentStop',
            'last_assistant_message':'LUNASTRA_STATUS=ANALYSIS','stop_hook_active':True})
        self.assertNotIn('decision',stopped);self.assertNotIn('stopReason',stopped)
        state=self.host.cli(['crew-state'])
        self.assertEqual(1,state['reports_received']);self.assertEqual(6,state['observed_children'])
        self.assertEqual('returned',state['tasks'][0]['state'])
        self.assertEqual(6,sum(c['tool']=='spawn_agent' for c in self.host.native))
    def test_installed_worker_rejects_parent_helper_with_own_command(self):
        from luna_astra.transport import helper_command
        child=self.host.children[1]
        command=helper_command(self.host.prefix+['crew-state'])
        out=self.host.hook({**child['event'],'hook_event_name':'PreToolUse','tool_name':'Bash',
            'tool_input':{'command':command},'tool_use_id':'wrong-inherited-prefix'})
        result=out['hookSpecificOutput']
        self.assertEqual('deny',result['permissionDecision'])
        self.assertIn(child['prefix'][-1],result['permissionDecisionReason'])
        self.assertIn('crew-report',result['permissionDecisionReason'])

    def test_installed_worker_malformed_bash_receives_owned_helper(self):
        child=self.host.children[1]
        for index,payload in enumerate(({}, {'cmd':'not the native field'}, {'command':None})):
            with self.subTest(payload=payload):
                out=self.host.hook({**child['event'],'hook_event_name':'PreToolUse','tool_name':'Bash',
                    'tool_input':payload,'tool_use_id':'malformed-'+str(index)})
                result=out['hookSpecificOutput']
                self.assertEqual('deny',result['permissionDecision'])
                self.assertIn(child['prefix'][-1],result['permissionDecisionReason'])
                self.assertIn('requires command',result['permissionDecisionReason'])

    def test_installed_worker_kernel_has_worker_footer(self):
        child=self.host.children[1]
        out=self.host.hook({**child['event'],'hook_event_name':'SessionStart','source':'resume'})
        text=out['hookSpecificOutput']['additionalContext']
        self.assertIn('Fixed seven worker: use your own helper crew-join and crew-report',text)
        self.assertNotIn('Fixed seven parent:',text)
        self.assertNotIn('Fixed seven: use help.fixed_seven and crew-start',text)

if __name__=='__main__':unittest.main()
