"""Real installed shell/CLI boundaries; native callbacks are synthetic fixtures."""
import unittest
import test_fixed_seven_integration as fixture_module

class InstalledCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.host=fixture_module.InstalledFixedSevenTests(methodName='runTest')
        self.addCleanup(self.host.doCleanups);self.host.setUp()
    def verify_profile(self,protocol):
        host=self.host;host.contract['native']={'protocol':protocol,'context':'capsule','capacity_total':7}
        host.cli(['crew-start'],host.contract)
        step=host.cli(['crew-step']);self.assertEqual(1,len(step['calls']));call=step['calls'][0]
        event={**host.event,'hook_event_name':'PreToolUse','tool_name':'multi_agent_'+protocol+call['tool'],
               'tool_input':call['arguments'],'tool_use_id':'installed-first'}
        out=host.hook(event);self.assertNotEqual('deny',out.get('hookSpecificOutput',{}).get('permissionDecision'),out)
        ack={'agent_id':'installed-child'} if protocol=='v1' else {'task_name':'/root/'+call['arguments']['task_name']}
        host.hook({**event,'hook_event_name':'PostToolUse','tool_response':ack})
        pending=host.cli(['crew-step']);self.assertEqual('WAIT',pending['next']['action'])
        if protocol=='v2':self.assertNotIn('targets',pending['calls'][0]['arguments'])
        child={**host.event,'session_id':'installed-child','agent_id':'installed-child','hook_event_name':'SubagentStart'}
        prefix=host.get_prefix(host.hook(child));joined=host.cli(['crew-join',call['ticket']],prefix=prefix)
        self.assertEqual(host.contract['requirements'],joined['requirements']);self.assertEqual(host.contract['goal'],joined['goal'])
        step=host.cli(['crew-step']);self.assertEqual(5,len(step['calls']))
        self.assertEqual(1,step['next']['observed_children'])
        for name,raw in host.original.items():self.assertEqual(raw,(host.home/name).read_bytes())
    def test_installed_v1_capsule_identity_and_remaining_dispatch(self):self.verify_profile('v1')
    def test_installed_v2_canonical_ack_runtime_hook_and_dispatch(self):self.verify_profile('v2')

if __name__=='__main__':unittest.main()
