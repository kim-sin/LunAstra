import tempfile
import sys
import unittest
from pathlib import Path
from luna_astra.hooks import Hooks,identity
from luna_astra.store import Store
from luna_astra.evidence import Evidence
from luna_astra.coordination import assigned_edit_input
from luna_astra.team import Team
from luna_astra.util import HarnessError
ROOT=Path(__file__).resolve().parents[1]

class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.ws=self.base/'repo';self.ws.mkdir();(self.ws/'app.py').write_text('answer=1\n')
        self.state=self.base/'state';self.h=Hooks(ROOT,self.state)
        self.event={'hook_event_name':'SessionStart','model':'gpt-5.6-luna','session_id':'parent','cwd':str(self.ws),'turn_id':'one'}
        self.h.handle(self.event);self.key=identity(self.event)[0];self.store=Store(self.state)
    def stop(self,message='Implemented.',**kw):return self.h.handle({**self.event,'hook_event_name':'Stop','last_assistant_message':message,**kw})
    def evidence(self,dependencies=None):
        ev=Evidence(self.state/'sessions'/self.key,self.ws)
        ev.begin({'task_id':'change','design':'Change the answer preserving imports','requirements':['answer is 2'],'allowed_paths':['app.py'],'checks':[{'id':'check','purpose':'Behavior','argv':[sys.executable,'-c','import app; assert app.answer == 2'],'dependencies':dependencies or ['app.py'],'covers':[0]}]})
        return ev
    def test_omitted_marker_after_shell_edit_is_not_success(self):
        (self.ws/'app.py').write_text('answer=2\n');self.assertEqual(self.stop()['decision'],'block')
    def test_missing_marker_second_stop_is_explicit_unverified(self):
        (self.ws/'app.py').write_text('answer=2\n');self.stop();result=self.stop()
        self.assertFalse(result['continue']);self.assertIn('UNVERIFIED',result['stopReason'])
    def test_explanation_does_not_require_ledger(self):self.assertEqual(self.stop('Here is an explanation.'),{})
    def test_fabricated_tested_tag_is_rejected(self):self.assertEqual(self.stop('LUNASTRA_STATUS=TESTED')['decision'],'block')
    def test_analysis_cannot_hide_a_modification(self):
        (self.ws/'app.py').write_text('answer=2\n');self.assertEqual(self.stop('LUNASTRA_STATUS=ANALYSIS')['decision'],'block')
    def test_valid_current_checks_allow_completion(self):
        (self.ws/'app.py').write_text('answer=2\n');ev=self.evidence();ev.run('check');ev.finish('tested','Changed answer','Inspected callers','Declared local behavior')
        self.store.put(self.key,'finish_generation','one');self.assertEqual(self.stop(),{})
        self.assertTrue(self.h.doctor()['sessions'][0]['current_tested'])
    def test_later_uncovered_file_is_not_verified(self):
        (self.ws/'app.py').write_text('answer=2\n');ev=self.evidence();ev.run('check');ev.finish('tested','Changed','Reviewed','Scope')
        self.store.put(self.key,'finish_generation','one');(self.ws/'uncovered.py').write_text('other=3\n')
        self.assertEqual(self.stop()['decision'],'block')
    def test_explicit_partial_is_not_tested(self):
        (self.ws/'app.py').write_text('answer=2\n');ev=self.evidence();ev.finish('partial','Patch saved','Local review','Required server unavailable')
        self.store.put(self.key,'finish_generation','one');self.assertIn('PARTIAL',self.stop()['systemMessage'])
        self.assertEqual(self.store.get(self.key,'last_handback')['status'],'PARTIAL')
    def test_corrupt_sqlite_never_certifies(self):
        self.evidence();p=self.state/'sessions'/self.key/'evidence.sqlite3';p.write_bytes(b'broken database')
        self.assertEqual(self.stop('LUNASTRA_STATUS=TESTED')['decision'],'block')
        self.assertFalse(self.h.doctor()['sessions'][0]['current_tested'])
    def test_unfinished_team_blocks_plain_completion(self):
        t={'id':'inspect','kind':'investigate','description':'Find cause','paths':['app.py'],'done_when':['Evidence'],'why_parallel':'Independent check'}
        Team(self.store).plan(self.key,self.ws,{'goal':'Fix','tasks':[t]})
        self.assertEqual(self.stop()['decision'],'block')
    def test_interrupt_is_not_overruled(self):
        self.h.handle({**self.event,'hook_event_name':'Interrupt'});(self.ws/'app.py').write_text('answer=2\n')
        self.assertEqual(self.stop(),{})
    def test_post_compact_restores_instructions(self):
        self.assertEqual(self.h.handle({**self.event,'hook_event_name':'PostCompact'}),{})
        r=self.h.handle({**self.event,'source':'compact'});self.assertIn('LunAstra',r['hookSpecificOutput']['additionalContext'])
    def test_structured_command_patch_records_modification(self):
        event={**self.event,'hook_event_name':'PreToolUse','tool_use_id':'edit','tool_name':'apply_patch','tool_input':{'command':'*** Begin Patch\n*** Update File: app.py\n@@\n-answer=1\n+answer=2\n*** End Patch'}}
        self.h.handle(event);self.assertEqual(self.stop()['decision'],'block')
    def worker(self,readonly=False):
        event={**self.event,'hook_event_name':'SubagentStart','agent_id':'child'};self.h.handle(event);key=identity(event)[0]
        tree=self.base/'owned';tree.mkdir(exist_ok=True);(tree/'app.py').write_text('answer=1\n')
        meta=self.store.get(key,'meta');meta.update(assigned_workspace=str(tree),assigned_paths=['app.py'],read_only=readonly);self.store.put(key,'meta',meta)
        return event,key,tree
    def test_worker_patch_is_redirected_to_actual_owned_checkout(self):
        e,k,tree=self.worker()
        result=self.h.handle({**e,'hook_event_name':'PreToolUse','tool_use_id':'edit','tool_name':'apply_patch','tool_input':{'command':'*** Begin Patch\n*** Update File: app.py\n@@\n-a\n+b\n*** End Patch'}})
        updated=result['hookSpecificOutput']['updatedInput']['command']
        self.assertIn(str(tree/'app.py'),updated);self.assertNotIn(str(self.ws/'app.py'),updated)
    def test_worker_absolute_original_path_is_refused(self):
        e,k,tree=self.worker();result=self.h.handle({**e,'hook_event_name':'PreToolUse','tool_use_id':'edit','tool_name':'Write','tool_input':{'file_path':str(self.ws/'app.py'),'content':'bad'}})
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')
    def test_worker_shell_defaults_to_owned_cwd(self):
        e,k,tree=self.worker();result=self.h.handle({**e,'hook_event_name':'PreToolUse','tool_use_id':'cmd','tool_name':'exec_command','tool_input':{'cmd':'pwd'}})
        self.assertEqual(result['hookSpecificOutput']['updatedInput']['workdir'],str(tree))
    def test_worker_shell_outside_cwd_refused(self):
        e,k,tree=self.worker();result=self.h.handle({**e,'hook_event_name':'PreToolUse','tool_use_id':'cmd','tool_name':'exec_command','tool_input':{'cmd':'pwd','workdir':str(self.ws)}})
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')
    def test_changed_worker_cwd_retains_original_session_identity(self):
        e,k,tree=self.worker();self.h.handle({**e,'cwd':str(tree),'session_id':'child','hook_event_name':'PostToolUse','tool_use_id':'read','tool_name':'exec_command','tool_input':{'cmd':'pwd'},'tool_response':{'exit_code':0}})
        self.assertEqual(self.store.get(k,'meta')['last_event'],'PostToolUse')
        self.assertEqual(len(self.h.doctor()['sessions']),2)
    def test_readonly_worker_cannot_use_structured_edit(self):
        e,k,tree=self.worker(True);result=self.h.handle({**e,'hook_event_name':'PreToolUse','tool_use_id':'edit','tool_name':'Write','tool_input':{'file_path':'app.py','content':'bad'}})
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')
    def test_nested_spawn_denied(self):
        e,k,tree=self.worker();result=self.h.handle({**e,'hook_event_name':'PreToolUse','tool_use_id':'spawn','tool_name':'spawn_agent','tool_input':{'message':'More workers'}})
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')
    def test_foreign_root_spawn_is_not_affected(self):
        result=self.h.handle({**self.event,'model':'gpt-6-astra','hook_event_name':'PreToolUse','tool_use_id':'spawn','tool_name':'spawn_agent','tool_input':{}})
        self.assertEqual(result,{})
    def test_patch_move_target_is_redirected_too(self):
        patch='*** Begin Patch\n*** Update File: app.py\n*** Move to: moved.py\n@@\n-a\n+b\n*** End Patch'
        result=assigned_edit_input('apply_patch',patch,self.ws)
        self.assertIn(str(self.ws/'app.py'),result);self.assertIn(str(self.ws/'moved.py'),result)
    def test_previous_checked_work_does_not_turn_new_explanation_into_coding(self):
        (self.ws/'app.py').write_text('answer=2\n');ev=self.evidence();ev.run('check');ev.finish('tested','Changed','Reviewed','Scope')
        self.store.put(self.key,'finish_generation','one');self.stop()
        self.h.handle({**self.event,'hook_event_name':'UserPromptSubmit','turn_id':'two','prompt':'Explain the previous result.'})
        self.assertEqual(self.stop('Here is what it means.',turn_id='two'),{})
    def test_status_reply_does_not_restart_previous_outstanding_team(self):
        t={'id':'inspect','kind':'investigate','description':'Find cause','paths':['app.py'],'done_when':['Evidence'],'why_parallel':'Independent check'}
        Team(self.store).plan(self.key,self.ws,{'goal':'Fix','tasks':[t]})
        self.h.handle({**self.event,'hook_event_name':'UserPromptSubmit','turn_id':'two','prompt':'What is the current status?'})
        result=self.stop('The previous task is still pending.',turn_id='two')
        self.assertNotIn('decision',result);self.assertIn('outstanding',result['systemMessage'])
    def test_first_observed_compaction_emits_one_kernel_only(self):
        event={**self.event,'hook_event_name':'PostCompact','session_id':'new-session'}
        self.assertEqual(self.h.handle(event),{})
        result=self.h.handle({**event,'hook_event_name':'SessionStart','source':'compact'})['hookSpecificOutput']['additionalContext']
        self.assertEqual(result.count('LOCAL_HELPER_ARGV='),1)
