"""4.1 model boundary regressions. All event/model values are synthetic fixtures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from luna_astra import __version__,__build__
from luna_astra.activation import APPLICABILITY,header,scope_metadata
from luna_astra.model_gate import accepts_event,classify,is_luna,parse_hook_input,EVENTS,MAX_INPUT
from luna_astra.hooks import Hooks,identity
from luna_astra.store import Store
from luna_astra.connection import record_hook,connection_status,activation_layers

ROOT=Path(__file__).resolve().parents[1]
LUNA='gpt-5.6-luna'
# These names are negative test inputs, NOT captured host identifiers.
NEGATIVE=['gpt-6-astra','gpt-5.6-sol','gpt-6-pro','arbitrary-model','gpt-reserve',
          '',None,12,False,[],{},'GPT-5.6-LUNA',' gpt-5.6-luna','gpt-5.6-luna\n',
          'gpt-5.6-luna/../../','gpt-5.6-luna;echo SECRET','gpt-5.6-lunatic','gpt-5.6-luna--']


def snapshot(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class GateUnit(unittest.TestCase):
    def test_luna_model_is_accepted(self):self.assertEqual('LUNA',classify(LUNA))
    def test_luna_variant_is_accepted(self):
        for model in ('gpt-5-luna','gpt-5.6-luna-reserve','gpt-5.6-luna-2026-09-10'):
            self.assertTrue(is_luna(model))
    def test_non_luna_sol_is_noop(self):self.assertFalse(is_luna('gpt-5.6-sol'))
    def test_non_luna_astra_fixture_is_noop(self):self.assertFalse(is_luna('gpt-6-astra'))
    def test_non_luna_pro_is_noop(self):self.assertFalse(is_luna('gpt-6-pro'))
    def test_unknown_model_is_noop(self):self.assertFalse(is_luna('unknown'))
    def test_missing_model_is_noop(self):self.assertEqual('UNKNOWN',classify(None))
    def test_reserve_only_when_contract_is_proven(self):
        self.assertEqual('UNKNOWN',classify('gpt-reserve'))
        self.assertFalse(accepts_event({'hook_event_name':'SessionStart','model':'gpt-reserve',
                                      'model_family':'luna','selected_model':LUNA,'prompt':LUNA}))
    def test_early_gate_and_hooks_gate_have_identical_classification(self):
        from luna_astra.hooks import is_luna as second
        self.assertIs(second,is_luna)
        for model in NEGATIVE+[LUNA,'gpt-5.6-luna-reserve']:
            self.assertEqual(is_luna(model),second(model))
    def test_malformed_events_do_not_raise(self):
        for e in (None,[],False,1,'bad',{}, {'hook_event_name':[],'model':LUNA},
                  {'hook_event_name':{},'model':LUNA},{'hook_event_name':'Unknown','model':LUNA}):
            self.assertFalse(accepts_event(e))
    def test_prompt_model_words_never_authorize(self):
        self.assertFalse(accepts_event({'hook_event_name':'SessionStart','model':'gpt-6-astra',
                          'prompt':LUNA,'tool_input':{'model':LUNA},'config':{'model':LUNA}}))
    def test_json_duplicate_keys_cannot_authorize(self):
        for raw in (b'{"model":"gpt-6-astra","model":"gpt-5.6-luna","hook_event_name":"SessionStart"}',
                    b'{"model":"gpt-5.6-luna","prompt":{"a":1,"a":2}}'):
            self.assertIsNone(parse_hook_input(raw))
    def test_json_malformed_oversized_nonfinite_inert(self):
        for raw in (b'{',b'[]',b'null',b'"text"',b'\xff',b'{"x":NaN}', b' '* (MAX_INPUT+1),None):
            self.assertIsNone(parse_hook_input(raw))
    def test_escaped_exact_model_is_accepted(self):
        event=parse_hook_input(b'{"hook_event_name":"SessionStart","model":"gpt-5.6-l\\u0075na"}')
        self.assertTrue(accepts_event(event))
    def test_model_classifier_has_no_task_engine_imports(self):
        code="from luna_astra.model_gate import is_luna; import sys; assert not any(n in sys.modules for n in ['luna_astra.hooks','luna_astra.store','luna_astra.team','luna_astra.gate_trace'])"
        cp=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,timeout=20,
                          env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        self.assertEqual(0,cp.returncode,cp.stderr.decode())


class NoSideEffects(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        self.ws=self.base/'workspace';self.ws.mkdir();(self.ws/'file.py').write_text('value=1\n')
        self.state=self.base/'private'/'state-v4';self.h=Hooks(ROOT,self.state,fixed_seven=True)
        self.event={'hook_event_name':'SessionStart','model':LUNA,'session_id':'actual-fixture',
                    'turn_id':'turn-1','cwd':str(self.ws)}
    def test_all_nine_non_luna_events_have_no_side_effects(self):
        before=snapshot(self.base)
        with patch('luna_astra.hooks.Store',side_effect=AssertionError('task state')), \
             patch.object(Hooks,'_prompt',side_effect=AssertionError('prompt read')), \
             patch('luna_astra.hooks.observe',side_effect=AssertionError('workspace scan')), \
             patch('luna_astra.hooks.identity',side_effect=AssertionError('identity path scan')), \
             patch('luna_astra.hooks.CodeMap',side_effect=AssertionError('code map')), \
             patch('subprocess.Popen',side_effect=AssertionError('child process')):
            for model in NEGATIVE:
                for event in EVENTS:
                    e={**self.event,'model':model,'hook_event_name':event,'agent_id':'negative-child',
                       'prompt':'LunAstra '+LUNA,'tool_name':'apply_patch','tool_input':{'content':'secret'},
                       'tool_use_id':'call','last_assistant_message':'LUNASTRA_STATUS=TESTED'}
                    self.assertEqual({},self.h.handle(e),(model,event))
        self.assertEqual(before,snapshot(self.base));self.assertFalse(self.state.exists())
    def test_non_luna_does_not_change_permission_decision(self):
        for event in EVENTS:
            result=self.h.handle({**self.event,'model':'gpt-6-astra','hook_event_name':event,
                                  'tool_name':'apply_patch','tool_input':'x','tool_use_id':'t'})
            self.assertEqual({},result)
    def test_non_luna_creates_no_agent_alias(self):
        for kind in ('SubagentStart','SubagentStop','PreToolUse','PostToolUse'):
            self.assertEqual({},self.h.handle({**self.event,'model':'gpt-6-pro','hook_event_name':kind,'agent_id':'worker'}))
        self.assertFalse(self.state.exists())
    def test_non_luna_does_not_load_fixed_prompt(self):
        with patch.object(Hooks,'_prompt',side_effect=AssertionError('read')):
            self.assertEqual({},Hooks(self.base/'missing-package',self.state,fixed_seven=True).handle({'model':None}))
    def test_non_luna_does_not_resolve_or_scan_missing_workspace(self):
        with patch.object(Path,'resolve',side_effect=AssertionError('resolve')):
            self.assertEqual({},self.h.handle({**self.event,'model':'gpt-6-astra','cwd':'missing'}))
    def test_same_conversation_switch_does_not_touch_prior_state(self):
        self.h.handle(self.event);before=snapshot(self.base)
        for kind in EVENTS:
            self.assertEqual({},self.h.handle({**self.event,'hook_event_name':kind,'turn_id':'turn-2','model':'gpt-6-astra'}))
        self.assertEqual(before,snapshot(self.base))
    def test_switch_back_retains_roster_contract_and_new_scope(self):
        self.h.handle(self.event)
        self.h.handle({**self.event,'model':'gpt-6-astra','turn_id':'turn-2'})
        out=self.h.handle({**self.event,'hook_event_name':'UserPromptSubmit','prompt':'status','turn_id':'turn-3'})
        text=out['hookSpecificOutput']['additionalContext']
        self.assertIn(APPLICABILITY,text);self.assertIn('LUNASTRA_TURN_SCOPE=',text)
        self.assertTrue(Store(self.state).get(identity(self.event)[0],'meta')['crew_enabled'])
    def test_direct_connection_record_ignores_non_luna(self):
        record_hook(self.state,ROOT,{**self.event,'model':'gpt-6-astra'},{'hookSpecificOutput':{'additionalContext':'fake'}})
        self.assertFalse(self.state.exists())
    def test_early_cli_rejects_before_importing_engine(self):
        code="""import sys,runpy,importlib.abc
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in ('luna_astra.hooks','luna_astra.store','luna_astra.flow','luna_astra.connection','luna_astra.gate_trace'): raise AssertionError('heavy import '+fullname)
sys.meta_path.insert(0,Deny())
sys.argv=['luna.py','--state',sys.argv[1],'hook']
runpy.run_path('luna.py',run_name='__main__')
"""
        before=snapshot(self.base)
        for raw in (json.dumps({**self.event,'model':'gpt-6-astra','prompt':LUNA}).encode(),b'{',b'null',
                    json.dumps({**self.event,'model':'gpt-reserve'}).encode(),b'{"model":[],"hook_event_name":[]}'):
            cp=subprocess.run([sys.executable,'-c',code,str(self.state)],input=raw,cwd=ROOT,capture_output=True,timeout=20)
            self.assertEqual(0,cp.returncode,cp.stderr.decode());self.assertEqual(b'{}\n',cp.stdout)
        self.assertEqual(before,snapshot(self.base))
    def test_early_hook_creates_no_package_bytecode(self):
        import shutil
        package=self.base/'copy';package.mkdir();(package/'luna_astra').mkdir()
        for relative in ('luna.py','luna_astra/__init__.py','luna_astra/model_gate.py'):
            shutil.copyfile(ROOT/relative,package/relative)
        before=snapshot(package);env=os.environ.copy();env.pop('PYTHONDONTWRITEBYTECODE',None)
        cp=subprocess.run([sys.executable,str(package/'luna.py'),'--state',str(self.state),'hook'],input=b'{}',capture_output=True,env=env,timeout=20)
        self.assertEqual(0,cp.returncode,cp.stderr.decode());self.assertEqual(b'{}\n',cp.stdout)
        self.assertEqual(before,snapshot(package));self.assertFalse(list(package.rglob('*.pyc')))
    def test_explicit_trace_without_arm_remains_noop(self):
        cp=subprocess.run([sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--trace-model-gate','hook'],
                           input=json.dumps({**self.event,'model':'gpt-6-astra'}).encode(),capture_output=True,timeout=20)
        self.assertEqual(0,cp.returncode);self.assertEqual(b'{}\n',cp.stdout);self.assertFalse(self.state.parent.exists())


class LifetimeTests(unittest.TestCase):
    setUp=NoSideEffects.setUp
    def test_injected_protocol_contains_luna_only_expiry_guard(self):
        out=self.h.handle(self.event)['hookSpecificOutput']['additionalContext']
        self.assertIn(APPLICABILITY,out);self.assertEqual(1,out.count(APPLICABILITY))
        self.assertIn('INACTIVE',out);self.assertIn('disabled/unregistered',out)
    def test_fixed_root_scope_guard_precedes_obligation(self):
        text=(ROOT/'prompts/FIXED_ROOT.md').read_text();self.assertTrue(text.startswith(APPLICABILITY))
        self.assertLess(text.index(APPLICABILITY),text.index('Use exactly six'))
    def test_fixed_worker_scope_guard_precedes_ticket(self):
        text=(ROOT/'prompts/FIXED_WORKER.md').read_text();self.assertTrue(text.startswith(APPLICABILITY))
        self.assertLess(text.index(APPLICABILITY),text.index('LUNASTRA_TICKET'))
    def test_core_and_legacy_prompts_are_scoped(self):
        for name in ('CORE','ROOT','WORKER'):
            self.assertTrue((ROOT/'prompts'/f'{name}.md').read_text().startswith(APPLICABILITY))
    def test_activation_scope_changes_with_model_role_turn(self):
        a=scope_metadata('key','root',LUNA,'one');b=scope_metadata('key','root',LUNA,'two')
        self.assertEqual(a['activation_id'],b['activation_id']);self.assertNotEqual(a['activation_turn'],b['activation_turn'])
        self.assertNotEqual(a['activation_id'],scope_metadata('key','worker',LUNA,'one')['activation_id'])
        self.assertNotEqual(a['activation_id'],scope_metadata('key','root',LUNA+'-reserve','one')['activation_id'])
        with self.assertRaises(ValueError):scope_metadata('key','root','gpt-6-astra')
    def test_scope_preserves_existing_version_and_build_markers(self):
        text=self.h.handle(self.event)['hookSpecificOutput']['additionalContext']
        self.assertIn('LUNA_ASTRA_VERSION='+__version__+'\n',text)
        self.assertIn('LUNASTRA_BUILD='+__build__+'\n',text)
        self.assertEqual(1,text.count('LUNA_ASTRA_VERSION='));self.assertEqual(1,text.count('LUNASTRA_BUILD='))
    def test_activation_metadata_is_persisted_without_raw_session_in_header(self):
        text=self.h.handle(self.event)['hookSpecificOutput']['additionalContext']
        key=identity(self.event)[0];meta=Store(self.state).get(key,'meta')
        self.assertEqual(LUNA,meta['activated_model']);self.assertEqual('LUNA_ONLY',meta['activation_scope'])
        self.assertIn('LUNASTRA_ACTIVATION_ID='+meta['activation_id'],text)
        self.assertNotIn(self.event['session_id'],text)
    def test_persisted_model_mismatch_preserves_prior_meta(self):
        self.h.handle(self.event);store=Store(self.state);key=identity(self.event)[0];meta=store.get(key,'meta')
        meta['model']='gpt-6-astra';store.put(key,'meta',meta)
        with self.assertRaises(ValueError):self.h.handle(self.event)
        self.assertEqual(meta,store.get(key,'meta'))
    def test_worker_alias_model_mismatch_is_not_rebound(self):
        self.h.handle(self.event);store=Store(self.state)
        alias={'parent':'actual-fixture','key':'old','model':LUNA+'-reserve'}
        store.put('__agent_alias__','child',alias)
        with self.assertRaises(ValueError):self.h.handle({**self.event,'hook_event_name':'SubagentStart','agent_id':'child'})
        self.assertEqual(alias,store.get('__agent_alias__','child'))
    def test_stop_feedback_keeps_marker_and_scopes_old_obligations(self):
        from test_fixed_seven import Fixture
        fixture=Fixture();self.addCleanup(fixture.close);fixture.start()
        result=fixture.hooks.handle({**fixture.event,'hook_event_name':'Stop','last_assistant_message':'done'})
        self.assertIn('LUNASTRA_CONTINUE:',json.dumps(result))
        self.assertIn(APPLICABILITY,json.dumps(result))
        reason=result['reason'];self.assertTrue(reason.startswith('LUNASTRA_CONTINUE:'))
        self.assertLess(reason.index(APPLICABILITY),reason.index('Use '))
    def test_post_compact_still_emits_no_context(self):
        self.h.handle(self.event);self.assertEqual({},self.h.handle({**self.event,'hook_event_name':'PostCompact'}))
    def test_doctor_separates_registration_activation_and_current_liveness(self):
        self.h.handle(self.event);runtime=connection_status(self.state,ROOT)
        layers=activation_layers(self.state,ROOT,runtime)
        self.assertTrue(layers['LUNA_EVENT_ACCEPTED']);self.assertTrue(layers['KERNEL_EMITTED'])
        self.assertEqual('NOT_MEASURED',layers['CREW_ACTIVE_CURRENT']);self.assertEqual('UNKNOWN',layers['ACTUAL_HOST_KIND'])
