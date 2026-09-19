"""Regressions from the actual Codex hook wire contract, not old test fixtures.

Source: openai/codex 4d205c7a4dc36b719679a0356a45b23133732265.
Native payloads are replayed locally. This is not a live model evaluation.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft7Validator
from luna_astra import __build__
from luna_astra.hooks import Hooks, identity, is_luna
from luna_astra.store import Store
from luna_astra.team import Team, unpack_response
from luna_astra.transport import helper_command, literal_argv, tool_name, validate_worker_shell, worker_shell_input, worker_exec, read_source
from luna_astra.util import HarnessError

ROOT=Path(__file__).resolve().parents[1]
SCHEMAS=ROOT/'tests'/'codex_contract'


def validate_pre_output(output):
    schema=json.loads((SCHEMAS/'pre-tool-use.command.output.schema.json').read_text())
    Draft7Validator(schema).validate(output)
    # These are semantic restrictions in the Rust parser, not JSON Schema.
    specific=output.get('hookSpecificOutput',{})
    if 'updatedInput' in specific:
        if specific.get('permissionDecision')!='allow':
            raise ValueError('updatedInput without permissionDecision:allow')
    elif specific.get('permissionDecision')=='allow':
        raise ValueError('allow without rewrite is unsupported')
    if output.get('continue') is False or 'stopReason' in output or output.get('suppressOutput'):
        raise ValueError('unsupported PreToolUse control output')


class NativeContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.ws=self.base/'project';self.ws.mkdir()
        (self.ws/'app.py').write_text('value = 1\n')
        self.state=self.base/'state';self.hooks=Hooks(ROOT,self.state);self.store=Store(self.state)
        self.root={'session_id':'native-parent','cwd':str(self.ws),'hook_event_name':'SessionStart',
                   'model':'gpt-5.6-luna','turn_id':'parent-turn','permission_mode':'default','transcript_path':None}
        self.hooks.handle(self.root);self.owner=identity(self.root)[0];self.team=Team(self.store)
        spec={'goal':'inspect actual source','tasks':[{'id':'inspect','kind':'investigate','description':'inspect app.py',
              'paths':['app.py'],'depends_on':[],'done_when':['return source evidence'],'why_parallel':'independent inspection'}]}
        self.team.plan(self.owner,self.ws,spec);self.ticket=self.team.reserve(self.owner)['reserved'][0]['ticket']
        self.spawn={**self.root,'hook_event_name':'PreToolUse','tool_name':'spawn_agent','tool_use_id':'spawn-native',
                    'tool_input':{'message':'LUNASTRA_TICKET='+self.ticket,'fork_context':True}}
        self.hooks.handle(self.spawn)
        self.child={**self.root,'session_id':'native-child','agent_id':'native-child','agent_type':'default',
                    'turn_id':'child-turn','hook_event_name':'SubagentStart'}
        self.key=identity(self.child)[0]

    def observe_spawn(self,agent='native-child',response=None):
        self.hooks.handle({**self.spawn,'hook_event_name':'PostToolUse',
                           'tool_response':response if response is not None else json.dumps({'agent_id':agent,'nickname':'Worker'})})

    def join(self):
        self.hooks.handle(self.child)
        return self.team.join(self.key,self.ticket,self.store.get(self.key,'meta'))

    def pre(self,tool,payload):
        return {**self.child,'hook_event_name':'PreToolUse','tool_use_id':'work-call','tool_name':tool,'tool_input':payload}

    def test_official_input_shape_is_native_child_session(self):
        schema=json.loads((SCHEMAS/'subagent-start.command.input.schema.json').read_text())
        Draft7Validator(schema).validate(self.child)
        self.assertEqual(self.child['session_id'],self.child['agent_id'])

    def test_join_after_native_spawn_result(self):
        self.observe_spawn();self.join()
        self.assertEqual(self.store.get(self.key,'meta')['parent_session_id'],'native-parent')

    def test_child_can_start_before_parent_result(self):
        self.hooks.handle(self.child)
        with self.assertRaisesRegex(HarnessError,'not registered yet'):self.join()
        self.observe_spawn();self.join()
        self.assertEqual(self.team.lookup(self.ticket)['agent_id'],'native-child')

    def test_self_parent_is_not_persisted(self):
        self.hooks.handle(self.child)
        self.assertIsNone(self.store.get(self.key,'meta').get('parent_session_id'))

    def test_bound_parent_survives_later_native_tool(self):
        self.observe_spawn();self.join();self.hooks.handle(self.pre('read_file',{'path':'app.py'}))
        self.assertEqual(self.store.get(self.key,'meta')['parent_session_id'],'native-parent')

    def test_bound_parent_survives_duplicate_start(self):
        self.observe_spawn();self.join();self.hooks.handle(self.child)
        self.assertEqual(self.store.get(self.key,'meta')['parent_session_id'],'native-parent')

    def test_wrong_native_agent_cannot_take_ticket(self):
        self.observe_spawn('some-other-child')
        with self.assertRaisesRegex(HarnessError,'another agent'):self.join()

    def test_wrong_model_cannot_join_bound_ticket(self):
        self.observe_spawn();self.hooks.handle(self.child);meta=self.store.get(self.key,'meta')
        with self.assertRaisesRegex(HarnessError,'model differs'):
            self.team.join(self.key,self.ticket,{**meta,'model':'gpt-5.7-luna'})

    def test_no_native_write_before_join(self):
        self.hooks.handle(self.child)
        output=self.hooks.handle(self.pre('apply_patch',{'command':'*** Begin Patch\n*** Update File: app.py\n@@\n-value = 1\n+value = 2\n*** End Patch'}))
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny');validate_pre_output(output)
        self.assertEqual((self.ws/'app.py').read_text(),'value = 1\n')

    def test_raw_native_shell_denied_for_joined_worker(self):
        self.observe_spawn();self.join()
        output=self.hooks.handle(self.pre('Bash',{'command':'echo unsafe'}))
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny');validate_pre_output(output)

    def test_helper_native_shell_accepted(self):
        self.observe_spawn();self.join()
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--session',self.key]
        output=self.hooks.handle(self.pre('Bash',{'command':helper_command(prefix+['status'])}))
        self.assertNotEqual(output.get('hookSpecificOutput',{}).get('permissionDecision'),'deny');validate_pre_output(output)

    def test_foreign_session_helper_denied(self):
        self.observe_spawn();self.join()
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--session',self.owner]
        output=self.hooks.handle(self.pre('Bash',{'command':helper_command(prefix+['status'])}))
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')

    def test_json_helper_input_needs_no_pipeline(self):
        self.observe_spawn();self.join()
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--session',self.key]
        note={'task_id':'inspect','facts':['read app.py'],'unresolved':[],'next_action':'return findings'}
        command=helper_command(prefix+['--input-json',json.dumps(note),'note'])
        output=self.hooks.handle(self.pre('Bash',{'command':command}));validate_pre_output(output)
        self.assertNotEqual(output.get('hookSpecificOutput',{}).get('permissionDecision'),'deny')
        effective=output.get('hookSpecificOutput',{}).get('updatedInput',{}).get('command',command)
        result=subprocess.run(effective,shell=True,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['saved'])

    def test_native_shell_without_command_is_denied(self):
        self.observe_spawn();self.join();output=self.hooks.handle(self.pre('Bash',{'cmd':'echo not-native'}))
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')

    def test_updated_input_has_native_permission_field(self):
        self.observe_spawn();self.join();tree=self.base/'assigned';tree.mkdir();(tree/'app.py').write_text('value = 1\n')
        meta=self.store.get(self.key,'meta');meta.update(assigned_workspace=str(tree),read_only=False);self.store.put(self.key,'meta',meta)
        output=self.hooks.handle(self.pre('apply_patch',{'command':'*** Begin Patch\n*** Update File: app.py\n@@\n-value = 1\n+value = 2\n*** End Patch'}))
        validate_pre_output(output)
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'allow')
        self.assertIn(str(tree/'app.py'),output['hookSpecificOutput']['updatedInput']['command'])

    def test_old_invalid_rewrite_fails_independent_contract_check(self):
        with self.assertRaisesRegex(ValueError,'without permissionDecision'):
            validate_pre_output({'hookSpecificOutput':{'hookEventName':'PreToolUse','updatedInput':{'command':'x'}}})

    def test_namespaced_wait_observes_native_result(self):
        self.observe_spawn();self.join()
        self.hooks.handle({**self.root,'hook_event_name':'PostToolUse','tool_name':'multi_agent_v1wait_agent',
                           'tool_use_id':'wait-native','tool_input':{'targets':['native-child']},
                           'tool_response':json.dumps({'status':{'native-child':{'completed':'done'}},'timed_out':False})})
        self.assertEqual(self.team.lookup(self.ticket)['state'],'returned')
        self.assertEqual(json.loads(self.team.lookup(self.ticket)['result'])['status'],'UNVERIFIED')

    def test_namespaced_interrupt_followup_is_denied(self):
        self.observe_spawn();self.join()
        output=self.hooks.handle({**self.root,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v1send_input',
                   'tool_use_id':'followup-native','tool_input':{'target':'native-child','message':'replace work','interrupt':True}})
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')

    def test_same_version_old_kernel_is_refreshed(self):
        meta=self.store.get(self.owner,'meta');meta.pop('kernel_build',None);self.store.put(self.owner,'meta',meta)
        output=self.hooks.handle({**self.root,'hook_event_name':'PreToolUse','tool_use_id':'inspect','tool_name':'read_file','tool_input':{}})
        self.assertEqual({},output)  # Read-only tools intentionally do not load task storage.
        self.assertNotIn('kernel_build',self.store.get(self.owner,'meta'))
        output=self.hooks.handle({**self.root,'hook_event_name':'SessionStart','source':'resume'})
        self.assertIn(__build__,output['hookSpecificOutput']['additionalContext'])
        self.assertEqual(__build__,self.store.get(self.owner,'meta')['kernel_build'])

    def test_ambiguous_reserve_is_inert_without_switch(self):
        # 4.1 deliberately withdraws unproven bare-reserve authorization.
        self.assertFalse(is_luna('gpt-reserve'))
        output=self.hooks.handle({**self.root,'session_id':'reserve','model':'gpt-reserve'})
        self.assertEqual({},output)

    def test_unrelated_models_still_do_not_create_state(self):
        h=Hooks(ROOT,self.base/'untouched')
        for model in ('gpt-6-astra','gpt-5.6-sol','reserve','unknown-luna'):
            self.assertEqual(h.handle({**self.root,'model':model}),{})
        self.assertFalse((self.base/'untouched').exists())

    def test_native_content_array_spawn_response(self):
        self.observe_spawn(response=[{'type':'text','text':'{"agent_id":"native-child"}'}]);self.join()

    def test_read_only_helper_cannot_execute(self):
        self.observe_spawn();self.join()
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--session',self.key]
        command=helper_command(prefix+['worker-exec','--argv-json',json.dumps([sys.executable,'-c','pass'])])
        output=self.hooks.handle(self.pre('Bash',{'command':command}))
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')
        result=subprocess.run(prefix+['worker-exec','--argv-json',json.dumps([sys.executable,'-c','pass'])],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)

    def test_read_only_delegate_can_read_full_source(self):
        self.observe_spawn();self.join()
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--session',self.key]
        command=helper_command(prefix+['read','app.py'])
        output=self.hooks.handle(self.pre('Bash',{'command':command}))
        self.assertNotEqual(output.get('hookSpecificOutput',{}).get('permissionDecision'),'deny')
        effective=output.get('hookSpecificOutput',{}).get('updatedInput',{}).get('command',command)
        result=subprocess.run(effective,shell=True,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)['eof'])

    def test_unknown_result_does_not_certify_or_release(self):
        self.observe_spawn(response='finished without a structured identity')
        with self.assertRaisesRegex(HarnessError,'not registered yet'):self.join()
        self.assertEqual(self.team.lookup(self.ticket)['state'],'reserved')

    def test_later_structured_result_resolves_same_call(self):
        self.observe_spawn(response='temporarily unknown');self.observe_spawn();self.join()


class LiteralCommandTests(unittest.TestCase):
    def test_posix_roundtrip(self):
        values=['/tmp/space folder/python',"apostrophe's path",'--input-json','{"x":"$HOME; `x`"}','note']
        self.assertEqual(literal_argv(helper_command(values,windows=False)),values)

    def test_powershell_roundtrip(self):
        values=[r'C:\Space Folder\python.exe',"apostrophe's path",'--input-json','{"x":"$HOME; `x`"}','note']
        self.assertEqual(literal_argv(helper_command(values,windows=True)),values)

    def test_pipelines_and_substitutions_rejected(self):
        for text in ('python helper.py; echo bad','python helper.py | echo bad','$(echo python) helper.py','python helper.py > out',"& 'python' 'helper.py'; echo bad"):
            with self.subTest(text=text),self.assertRaises(HarnessError):literal_argv(text)

    def test_no_unknown_worker_helper(self):
        with self.assertRaises(HarnessError):validate_worker_shell('python helper.py doctor',['python','helper.py'],joined=True)

    def test_worker_before_join_cannot_execute(self):
        with self.assertRaises(HarnessError):validate_worker_shell('python helper.py worker-exec',['python','helper.py'],joined=False)

    def test_exact_native_namespace_only(self):
        self.assertEqual(tool_name('multi_agent_v1wait_agent'),'wait_agent')
        self.assertEqual(tool_name('mcp__other__wait_agent'),'mcp__other__wait_agent')


class ExecutionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name).resolve()
        self.tree=self.base/'assigned';self.tree.mkdir()
        self.meta={'role':'worker','team_ticket':'ticket','assigned_workspace':str(self.tree)}

    def test_real_process_uses_assigned_directory(self):
        result=worker_exec(self.meta,[sys.executable,'-c','import os;print(os.getcwd())'])
        self.assertEqual(result['stdout'].strip(),str(self.tree));self.assertEqual(result['exit_code'],0)

    def test_relative_write_does_not_touch_caller_directory(self):
        result=worker_exec(self.meta,[sys.executable,'-c',"from pathlib import Path;Path('result.txt').write_text('owned')"])
        self.assertEqual(result['exit_code'],0);self.assertEqual((self.tree/'result.txt').read_text(),'owned')
        self.assertFalse((self.base/'result.txt').exists())

    def test_failed_process_is_not_success(self):
        self.assertEqual(worker_exec(self.meta,[sys.executable,'-c','raise SystemExit(7)'])['exit_code'],7)

    def test_no_receipt_from_command_exit(self):
        self.assertFalse(worker_exec(self.meta,[sys.executable,'-c','pass'])['verification_receipt'])

    def test_cwd_escape_rejected(self):
        with self.assertRaises(HarnessError):worker_exec(self.meta,[sys.executable,'-c','pass'],'..')

    def test_unjoined_execution_rejected(self):
        with self.assertRaises(HarnessError):worker_exec({'role':'worker'},[sys.executable,'-c','pass'])

    def test_shell_text_not_argv_rejected(self):
        with self.assertRaises(HarnessError):worker_exec(self.meta,'echo bad')

    def test_large_output_memory_is_bounded(self):
        result=worker_exec(self.meta,[sys.executable,'-c',"print('x'*100000)"])
        self.assertTrue(result['output_truncated']);self.assertLessEqual(len(result['stdout']),64000)

    def test_read_only_exec_cannot_modify_parent(self):
        with self.assertRaises(HarnessError):
            worker_exec({**self.meta,'read_only':True},[sys.executable,'-c',"open('corrupt.txt','w').write('bad')"])
        self.assertFalse((self.tree/'corrupt.txt').exists())

    def test_read_continuation_and_eof(self):
        (self.tree/'src.py').write_text('a\nb\nc\n')
        first=read_source(self.tree,'src.py',1,2);self.assertFalse(first['eof']);self.assertEqual(first['next_start_line'],3)
        last=read_source(self.tree,'src.py',3,2);self.assertTrue(last['eof']);self.assertEqual(last['lines'],['c'])

    def test_read_does_not_escape_root(self):
        with self.assertRaises(HarnessError):read_source(self.tree,'../secret.txt')

    def test_read_limits_validate(self):
        for start,limit in ((0,2),(1,0),(True,2),(1,5000)):
            with self.subTest(start=start,limit=limit),self.assertRaises(HarnessError):read_source(self.tree,'a',start,limit)
class WindowsArgumentBoundaryTests(unittest.TestCase):
    def test_windows_wrapper_preserves_literal_json_and_quotes(self):
        import base64
        prefix=[r"C:\Program Files\Python\python.exe",r"C:\Tools\LunAstra\luna.py",'--state',r"C:\Work\state",'--session','key']
        argv=prefix+['--input-json',json.dumps({'task_id':'read','facts':['café "quote" $value %PATH% O\'Brien']},ensure_ascii=False),'note']
        result=worker_shell_input(helper_command(argv,windows=True),prefix,joined=True,windows=True)
        script=base64.b64decode(result['command'].split(' -EncodedCommand ',1)[1]).decode('utf-16-le')
        expected="'"+subprocess.list2cmdline(argv[1:]).replace("'","''")+"'"
        self.assertIn('$p.StartInfo.Arguments='+expected+';',script)
        self.assertIn('$p.StartInfo.UseShellExecute=$false;',script)
        self.assertNotIn('Invoke-Expression',script)
        validate_pre_output({'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'allow','updatedInput':result}})

    def test_normal_unquoted_powershell_subcommand_is_literal(self):
        prefix=['python','luna.py','--state','state','--session','key']
        command=helper_command(prefix,windows=True)+' read app.py --max-lines 20'
        self.assertEqual(literal_argv(command),prefix+['read','app.py','--max-lines','20'])
        self.assertEqual(validate_worker_shell(command,prefix,joined=True,read_only=True),'read')

    def test_posix_helper_does_not_gain_extra_shell(self):
        prefix=['python','luna.py','--state','state','--session','key']
        self.assertIsNone(worker_shell_input(helper_command(prefix+['status'],windows=False),prefix,joined=True,windows=False))

    def test_windows_wrapper_rejects_operators_before_launch(self):
        prefix=['python','luna.py','--state','state','--session','key']
        command=helper_command(prefix,windows=True)+' status; echo injected'
        with self.assertRaises(HarnessError):worker_shell_input(command,prefix,joined=True,windows=True)

    def test_windows_wrapper_has_explicit_command_budget(self):
        prefix=['python','luna.py','--state','state','--session','key']
        command=helper_command(prefix+['read','x'*20000],windows=True)
        with self.assertRaisesRegex(HarnessError,'safe command limit'):
            worker_shell_input(command,prefix,joined=True,windows=True)
