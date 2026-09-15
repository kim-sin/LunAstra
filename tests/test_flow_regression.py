"""Regression of premature fixed-crew return; no real model is invoked."""
import unittest
from test_fixed_seven import Fixture

class PrematureReturnRegression(unittest.TestCase):
    def setUp(self):
        self.f=Fixture(); self.addCleanup(self.f.close)
    def stop(self, **kw):
        return self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop',
            'last_assistant_message':'The six children are still running; cannot finish.', **kw})
    def test_active_stop_flag_is_not_an_automatic_failure_exit(self):
        self.f.start(); self.f.dispatch()
        result=self.stop(stop_hook_active=True)
        self.assertEqual('block', result.get('decision'), result)
    def test_next_empty_calls_explains_native_wait_not_user_return(self):
        self.f.start(); self.f.dispatch()
        result=self.f.crew.next(self.f.owner)
        self.assertEqual([],result['calls'])
        self.assertEqual('WAIT',result.get('flow',{}).get('action'),result)
        self.assertEqual('wait_agent',result['flow']['native_call']['tool'])
        self.assertEqual(['child-1'],result['flow']['native_call']['arguments']['targets'])
    def test_worker_correction_is_worker_specific_not_parent_coordination(self):
        self.f.start(); self.f.dispatch()
        result=self.f.hooks.handle({**self.f.event,'session_id':'child-1','agent_id':'child-1',
            'hook_event_name':'SubagentStop','last_assistant_message':'Done without submitting'})
        reason=result.get('reason','')
        self.assertNotIn('inspect crew-state',reason)
        self.assertIn(self.f.keys[1],reason)
        self.assertIn('crew-report',reason)
    def test_parent_continues_after_children_make_real_progress(self):
        self.f.start();self.f.dispatch()
        self.assertEqual('block',self.stop().get('decision'))
        self.f.reports()
        result=self.stop(stop_hook_active=True)
        self.assertEqual('block',result.get('decision'),result)
        self.assertIn('crew-execute',result['reason'])

if __name__=='__main__':unittest.main()
