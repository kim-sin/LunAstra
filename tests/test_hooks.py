import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from luna_astra.hooks import Hooks,identity,is_luna,outcome
from luna_astra.store import Store
from luna_astra.evidence import Evidence
from luna_astra.util import HarnessError
ROOT=Path(__file__).resolve().parents[1]

class HooksTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.ws=self.base/'project';self.ws.mkdir();(self.ws/'a.py').write_text('def f(): return 1\n')
        self.state=self.base/'state';self.h=Hooks(ROOT,self.state)
        self.event={'hook_event_name':'SubagentStart','model':'gpt-5.6-luna','session_id':'parent','agent_id':'child','cwd':str(self.ws),'turn_id':'t1'}
    def pre(self,uid='tool1',path='a.py'):
        return {**self.event,'hook_event_name':'PreToolUse','tool_name':'apply_patch','tool_use_id':uid,'tool_input':'*** Begin Patch\n*** Update File: '+path+'\n@@\n-a\n+b\n*** End Patch'}
    def post(self,pre,code=0):return {**pre,'hook_event_name':'PostToolUse','tool_response':{'exit_code':code}}
    def test_non_luna_does_nothing(self):
        for model in ('gpt-6-astra','gpt-5.6-sol',None,'luna'):
            self.assertEqual(self.h.handle({**self.event,'model':model}),{})
        self.assertFalse(self.state.exists())
    def test_root_and_worker_both_supported(self):
        a=self.h.handle(self.event)['hookSpecificOutput']['additionalContext']
        ev={**self.event,'hook_event_name':'SessionStart'};ev.pop('agent_id')
        b=self.h.handle(ev)['hookSpecificOutput']['additionalContext']
        self.assertIn('delegated Luna worker',a);self.assertIn('direct Luna session',b)
    def test_model_filter_not_nickname(self):
        self.assertFalse(is_luna('astra-luna'));self.assertTrue(is_luna('gpt-5.6-luna-2026-09-10'))
    def test_parent_scopes_child_identity(self):
        a=identity(self.event)[0];b=identity({**self.event,'session_id':'another'})[0];self.assertNotEqual(a,b)
    def test_missing_agent_in_child_rejected(self):
        ev=self.event.copy();ev.pop('agent_id')
        with self.assertRaises(HarnessError):self.h.handle(ev)
    def test_missing_session_rejected(self):
        with self.assertRaises(HarnessError):self.h.handle({**self.event,'session_id':None})
    def test_unknown_event_no_state(self):
        self.assertEqual(self.h.handle({**self.event,'hook_event_name':'Unknown'}),{});self.assertFalse(self.state.exists())
    def test_core_is_bounded(self):
        text=self.h.handle(self.event)['hookSpecificOutput']['additionalContext']
        from luna_astra.activation import APPLICABILITY,header
        scope=header(identity(self.event)[0],'worker',self.event['model'],'t1')
        # Preserve the original 4300-character body budget; account explicitly
        # for the new required lifetime header instead of hiding its cost.
        self.assertEqual(1,text.count(APPLICABILITY))
        self.assertLess(len(text)-len(scope)-len(APPLICABILITY)-2,4300)
        self.assertLess(len(text),4300+len(scope)+len(APPLICABILITY)+2)
    def test_no_workspace_files_written(self):
        before={p.name:p.read_bytes() for p in self.ws.iterdir()};self.h.handle(self.event)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.ws.iterdir()})
    def test_edit_module_only_once_per_turn(self):
        self.h.handle(self.event);a=self.h.handle(self.pre());self.h.handle(self.post(self.pre()))
        b=self.h.handle(self.pre('tool2'));self.assertIn('Before editing',a['hookSpecificOutput']['additionalContext']);self.assertEqual(b,{})
    def test_conflicting_parallel_patch_denied(self):
        self.h.handle(self.event);self.h.handle(self.pre())
        b=self.h.handle({**self.pre('sibling1'),'agent_id':'sibling'})
        self.assertEqual(b['hookSpecificOutput']['permissionDecision'],'deny')
    def test_post_releases_transient_lock(self):
        self.h.handle(self.event);pre=self.pre();self.h.handle(pre);self.h.handle(self.post(pre))
        b=self.h.handle({**self.pre('sibling1'),'agent_id':'sibling'})
        self.assertNotIn('permissionDecision',b.get('hookSpecificOutput',{}))
    def test_failure_gets_diagnosis_once(self):
        self.h.handle(self.event);p={**self.pre(),'tool_name':'Bash','tool_input':{'cmd':'false'}}
        a=self.h.handle(self.post(p,1));b=self.h.handle(self.post({**p,'tool_use_id':'tool2'},1))
        self.assertIn('Diagnosis',a['hookSpecificOutput']['additionalContext'])
        self.assertIn('Repeated failed',b['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('Diagnosis',b['hookSpecificOutput']['additionalContext'])
    def test_duplicate_post_not_double_counted(self):
        self.h.handle(self.event);p=self.pre();a=self.h.handle(self.post(p,1));b=self.h.handle(self.post(p,1));self.assertEqual(b,{})
    def test_no_raw_tool_secrets_in_trace(self):
        self.h.handle(self.event);ev={**self.pre(),'tool_name':'Bash','tool_input':{'cmd':'echo PRIVATE_SECRET_098765'}}
        self.h.handle(ev);self.h.handle(self.post(ev))
        text=json.dumps(Store(self.state).recent(identity(ev)[0]));self.assertNotIn('PRIVATE_SECRET',text)
    def test_simple_stop_no_forced_retry(self):
        self.h.handle(self.event);self.assertEqual(self.h.handle({**self.event,'hook_event_name':'SubagentStop','last_assistant_message':'Explanation only'}),{})
    def test_fake_tested_claim_one_reminder(self):
        self.h.handle(self.event);ev={**self.event,'hook_event_name':'SubagentStop','last_assistant_message':'LUNA_ASTRA_STATUS=TESTED'}
        self.assertEqual(self.h.handle(ev)['decision'],'block');self.assertNotIn('decision',self.h.handle(ev))
    def test_doctor_not_model_parity(self):
        self.h.handle(self.event);r=self.h.doctor();self.assertEqual(r['model_parity'],'NOT_MEASURED');self.assertFalse(r['sessions'][0]['helper_used'])
    def test_no_ledger_for_explanation(self):
        self.h.handle(self.event);self.assertEqual(list(self.state.rglob('evidence.sqlite3')),[])
    def test_structured_outcome_is_conservative(self):
        self.assertEqual(outcome('everything PASS'),'UNKNOWN');self.assertEqual(outcome({'exit_code':True}),'UNKNOWN')
        self.assertEqual(outcome({'status':'running'}),'RUNNING');self.assertEqual(outcome({'exit_code':1}),'FAIL')
    def test_protected_path_guard(self):
        self.h.handle(self.event);key=identity(self.event)[0];ev=Evidence(self.state/'sessions'/key,self.ws)
        ev.begin({'task_id':'one','design':'preserve','requirements':['preserve'],'allowed_paths':['a.py'],'protected_paths':['a.py'],'checks':[]})
        out=self.h.handle(self.pre());self.assertEqual(out['hookSpecificOutput']['permissionDecision'],'deny')

    def test_duplicate_start_does_not_repeat_core(self):
        self.h.handle(self.event);self.assertEqual(self.h.handle(self.event),{})
    def test_new_turn_has_fresh_modules(self):
        self.h.handle(self.event);self.h.handle(self.pre());self.h.handle(self.post(self.pre()))
        out=self.h.handle({**self.pre('next'),'turn_id':'t2'})
        self.assertIn('Before editing',out['hookSpecificOutput']['additionalContext'])
    def test_failed_claim_final_return_releases_only_own_lease(self):
        self.h.handle(self.event);pre=self.pre();self.h.handle(pre)
        ev={**self.event,'hook_event_name':'SubagentStop','last_assistant_message':'LUNA_ASTRA_STATUS=TESTED'}
        self.h.handle(ev);self.h.handle({**ev,'stop_hook_active':True})
        out=self.h.handle({**pre,'agent_id':'other','tool_use_id':'other-tool'})
        self.assertNotIn('permissionDecision',out.get('hookSpecificOutput',{}))
    def test_old_finish_cannot_certify_new_turn(self):
        self.h.handle(self.event);key=identity(self.event)[0];store=Store(self.state)
        with patch('luna_astra.hooks.Evidence.status',return_value={'finish':{'kind':'tested','valid':True},'passed':True}):
            # Marker ensures the status reader is used; no checks/model are run.
            d=self.state/'sessions'/key;Evidence(d,self.ws)
            store.put(key,'finish_generation','t1');store.put(key,'generation','t2')
            self.assertFalse(self.h.doctor()['sessions'][0]['current_tested'])
            ev={**self.event,'turn_id':'t2','hook_event_name':'SubagentStop','last_assistant_message':'LUNA_ASTRA_STATUS=TESTED'}
            self.assertEqual(self.h.handle(ev)['decision'],'block')

    def test_first_observed_stop_does_not_claim_kernel_was_emitted(self):
        ev={**self.event,'hook_event_name':'SubagentStop','last_assistant_message':'ordinary return'}
        self.h.handle(ev);key=identity(ev)[0];store=Store(self.state)
        self.assertFalse(store.get(key,'meta')['context_emitted']);self.assertEqual(store.get(key,'emitted_chars',0),0)
        out=self.h.handle(self.pre());self.assertIn('engineering kernel',out['hookSpecificOutput']['additionalContext'])
    def test_first_denied_tool_preserves_actual_kernel_emission(self):
        from luna_astra.coordination import Coordinator
        store=Store(self.state);Coordinator(store,self.ws).claim('other',['a.py'],'manual')
        out=self.h.handle(self.pre());specific=out['hookSpecificOutput'];key=identity(self.pre())[0]
        self.assertEqual(specific['permissionDecision'],'deny');self.assertIn('engineering kernel',specific['additionalContext'])
        self.assertEqual(store.get(key,'emitted_chars'),len(specific['additionalContext']))
        self.assertTrue(store.get(key,'meta')['context_emitted'])
    def test_changed_kernel_version_recovers_on_existing_session_tool(self):
        self.h.handle(self.event);store=Store(self.state);key=identity(self.event)[0];meta=store.get(key,'meta')
        meta['kernel_version']='older';store.put(key,'meta',meta)
        out=self.h.handle(self.pre());self.assertIn('engineering kernel',out['hookSpecificOutput']['additionalContext'])
