"""Bounded context and deferred scans without replacing final byte evidence."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_fixed_seven import Fixture, PACKAGE
from test_v42_native import V2Fixture
from luna_astra.hooks import Hooks, identity
from luna_astra.store import Store
from luna_astra.controller import Controller
from luna_astra.scan import observe
from luna_astra.activation import APPLICABILITY
from luna_astra.util import json_hash, canonical, HarnessError


class DeferredScanTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close)
    def test_new_root_baseline_once_not_on_each_user_turn(self):
        with patch('luna_astra.hooks.observe',wraps=observe) as scan:
            for i in range(4):
                self.f.hooks.handle({**self.f.event,'turn_id':'new-'+str(i),'hook_event_name':'UserPromptSubmit','prompt':'status only'})
            self.assertEqual(0,scan.call_count)
    def test_missing_baseline_observed_once(self):
        self.f.store.put(self.f.owner,'source_baseline',None)
        with patch('luna_astra.hooks.observe',wraps=observe) as scan:
            self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'check'})
            self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'check again'})
            self.assertEqual(1,scan.call_count)
    def test_code_prompt_does_not_build_map_automatically(self):
        with patch.object(Hooks,'_map',side_effect=AssertionError('automatic map')):
            self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'fix app.js state bug and test'})
    def test_read_only_join_does_not_scan_six_workspaces(self):
        self.f.start()
        with patch('luna_astra.hooks.observe',side_effect=AssertionError('reader hook scan')),patch('luna_astra.crew.observe',side_effect=AssertionError('reader join scan')):
            self.f.dispatch()
        self.assertEqual(6,self.f.crew.status(self.f.owner)['observed_children'])
    def test_read_only_handbacks_do_not_scan_workspace(self):
        self.f.start();self.f.dispatch()
        with patch('luna_astra.hooks.observe',side_effect=AssertionError('reader stop scan')):
            self.f.reports()
    def test_read_only_snapshot_does_not_claim_full_observation(self):
        self.f.start();self.f.dispatch();self.f.reports()
        for key in self.f.keys.values():
            self.assertFalse(self.f.store.get(key,'source_baseline')['complete'])
            self.assertFalse(self.f.store.get(key,'last_handback')['observation_complete'])
    def test_root_final_stop_still_observes_bytes(self):
        self.f.complete()
        with patch('luna_astra.hooks.observe',wraps=observe) as scan:
            self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop','last_assistant_message':'LUNASTRA_STATUS=TESTED'})
            self.assertEqual(1,scan.call_count)
    def test_same_size_mtime_change_invalidates_final_proof(self):
        self.f.complete();path=self.f.root/'output.txt';st=path.stat()
        path.write_text('6');os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
        self.assertFalse(self.f.crew.summary(self.f.owner)['complete'])
    def test_new_prompt_does_not_hide_earlier_unverified_change(self):
        before=copy.deepcopy(self.f.store.get(self.f.owner,'source_baseline'))
        (self.f.root/'input.txt').write_text('9,9\n')
        self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','turn_id':'new','prompt':'continue'})
        self.assertEqual(before,self.f.store.get(self.f.owner,'source_baseline'))
    def test_successful_root_stop_advances_checked_baseline(self):
        self.f.complete();self.f.hooks.handle({**self.f.event,'hook_event_name':'Stop','last_assistant_message':'LUNASTRA_STATUS=TESTED'})
        self.assertEqual(observe(self.f.root),self.f.store.get(self.f.owner,'source_baseline'))
    def test_unreported_external_file_not_silently_covered(self):
        self.f.complete();(self.f.root/'unreviewed.py').write_text('x=1\n')
        self.assertIsNotNone(self.f.crew.completion_problem(self.f.owner))
    def test_every_user_turn_gets_current_scope(self):
        texts=[]
        for turn in ('scope-a','scope-b'):
            out=self.f.hooks.handle({**self.f.event,'turn_id':turn,'hook_event_name':'UserPromptSubmit','prompt':'status'})
            texts.append(out['hookSpecificOutput']['additionalContext'])
        for text in texts:
            self.assertIn('LUNASTRA_TURN_SCOPE=',text);self.assertIn('Without a fresh trusted',text)
        self.assertNotEqual(texts[0],texts[1])
    def test_unknown_or_non_luna_never_renews_lease(self):
        for model in ('gpt-6-astra','gpt-reserve',None,'future-model'):
            with patch.object(Hooks,'_core',side_effect=AssertionError('non-Luna core')):
                self.assertEqual({},self.f.hooks.handle({**self.f.event,'hook_event_name':'UserPromptSubmit','prompt':'LunAstra please','model':model}))
    def test_guard_never_claims_old_marker_is_authority(self):
        self.assertIn('quoted/replayed old marker is not a lease',APPLICABILITY)


class CompactControllerTests(unittest.TestCase):
    def setUp(self):
        self.f=Fixture();self.addCleanup(self.f.close);self.f.start();self.f.dispatch();self.f.reports()
        self.controller=Controller(self.f.store,PACKAGE)
    def test_default_reports_are_digests(self):
        result=self.controller.step(self.f.owner)
        self.assertTrue(result['reports_are_digests']);self.assertEqual(6,len(result['reports']))
        self.assertFalse(result['automatic_semantic_approval'])
        for row in result['reports']:
            self.assertIn('full_read_command',row['report']);self.assertEqual(64,len(row['report']['sha256']))
    def test_details_returns_exact_full_reports(self):
        expected=self.f.crew.status(self.f.owner)['reports'];result=self.controller.step(self.f.owner,details=True)
        self.assertFalse(result['reports_are_digests'])
        for row in result['reports']:self.assertEqual(expected[row['ticket']],row['report'])
    def test_digest_hash_identifies_full_report(self):
        result=self.controller.step(self.f.owner)
        for row in result['reports']:
            full=self.f.crew.read_report(self.f.owner,int(row['slot'][1:]))['report']
            self.assertEqual(json_hash(full),row['report']['sha256'])
    def test_long_findings_are_flagged_not_hidden_as_clear(self):
        state=self.f.crew.status(self.f.owner)
        with self.f.store.db(True) as db:
            for ticket,report in state['reports'].items():
                report['summary']='x'*1000;report['findings']=['y'*2500,'z'*2500]
                db.execute('UPDATE crew_reports SET body=? WHERE ticket=?',(canonical(report),ticket))
        result=self.controller.step(self.f.owner)
        self.assertLess(len(canonical(result)),18000)
        for row in result['reports']:
            self.assertTrue(row['report']['detail_required_before_decision'])
    def test_issue_digest_requires_full_read(self):
        state=self.f.crew.status(self.f.owner)
        with self.f.store.db(True) as db:
            for ticket,report in state['reports'].items():
                report['verdict']='issues';db.execute('UPDATE crew_reports SET body=? WHERE ticket=?',(canonical(report),ticket))
        for row in self.controller.step(self.f.owner)['reports']:
            self.assertTrue(row['report']['detail_required_before_decision'])
    def test_dispatch_does_not_repeat_full_calls_twice(self):
        f=Fixture();self.addCleanup(f.close);f.start()
        result=Controller(f.store,PACKAGE).step(f.owner)
        self.assertEqual(6,len(result['calls']));self.assertNotIn('calls',result['dispatch'])


class CapsuleCompletenessTests(unittest.TestCase):
    def test_reference_capsule_short_but_join_supplies_full_contract(self):
        f=V2Fixture();self.addCleanup(f.close)
        f.contract['goal']='Specific complete user objective '+('important '*100)
        f.start();call=f.crew.next(f.owner)['calls'][0]
        self.assertLess(len(call['arguments']['message']),1200)
        self.assertNotIn(f.contract['goal'],call['arguments']['message'])
        f.one(call)
        joined=f.crew.join(f.keys[1],call['ticket'],f.store.get(f.keys[1],'meta'))
        self.assertEqual(f.contract['goal'].strip(),joined['goal']);self.assertEqual(f.contract['requirements'],joined['requirements'])
        self.assertIn('decision',joined);self.assertIn('resource_roles',joined)
    def test_pending_first_spawn_does_not_launch_five_more(self):
        f=V2Fixture();self.addCleanup(f.close);f.start();call=f.crew.next(f.owner)['calls'][0]
        f.crew.pre_dispatch(f.owner,'pending',call['arguments'],f.event['model'],'spawn_agent')
        self.assertEqual([],f.crew.next(f.owner)['calls'])
    def test_unknown_first_spawn_is_not_replaced(self):
        f=V2Fixture();self.addCleanup(f.close);f.start();call=f.crew.next(f.owner)['calls'][0]
        f.crew.pre_dispatch(f.owner,'unknown',call['arguments'],f.event['model'],'spawn_agent')
        f.crew.post_dispatch(f.owner,'unknown',None)
        self.assertEqual([],f.crew.next(f.owner)['calls'])
    def test_inherited_placeholder_not_a_fresh_model_observation(self):
        f=V2Fixture('v1');self.addCleanup(f.close);f.start();call=f.crew.next(f.owner)['calls'][0];f.one(call,join=False)
        key=f.store.get('__agent_alias__','observed-v1-1')['key']
        with self.assertRaises(HarnessError):f.crew.join(key,call['ticket'],f.store.get(key,'meta'))
        self.assertEqual([],f.crew.next(f.owner)['calls'])
    def test_one_real_handshake_releases_remaining_five_not_six(self):
        f=V2Fixture();self.addCleanup(f.close);f.start();f.one(f.crew.next(f.owner)['calls'][0])
        calls=f.crew.next(f.owner)['calls'];self.assertEqual([2,3,4,5,6],[c['slot'] for c in calls])

if __name__=='__main__':unittest.main()
