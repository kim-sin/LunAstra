import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from luna_astra.install import Installer
from luna_astra.util import load_json
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('git'),'Git required')
class TeamIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name).resolve()
        self.ws=self.base/'repo';self.ws.mkdir();self.home=self.base/'codex'
        def git(*args):subprocess.run(['git','-C',str(self.ws),*args],check=True,capture_output=True)
        git('init','-q');git('config','user.name','Test Author');git('config','user.email','test@example.invalid')
        (self.ws/'app.py').write_text('def add(x,y): return x-y\n')
        (self.ws/'test_app.py').write_text('from app import add\nassert add(2,3)==5\nassert add(-2,2)==0\n')
        git('add','app.py','test_app.py');git('commit','-qm','fixture')
        self.installer=Installer(ROOT,self.home);self.receipt=self.installer.apply()
        self.hooks=load_json(self.home/'hooks.json')['hooks']
        self.event={'hook_event_name':'SessionStart','model':'gpt-5.6-luna','session_id':'leader','cwd':str(self.ws),'turn_id':'root-turn'}
        # Simulate an existing 3.2 dynamic session during upgrade. New sessions
        # use fixed seven (covered by test_fixed_seven_integration), while this
        # retained session must keep its original task and safety behavior.
        from luna_astra.hooks import Hooks
        Hooks(Path(self.receipt['release']),Path(self.receipt['state'])).handle(self.event)
        self.root_prefix=self.prefix(self.hook({**self.event,'source':'resume'}))
    def hook(self,event):
        handler=self.hooks[event['hook_event_name']][-1]['hooks'][0]
        r=subprocess.run(handler['command'],shell=True,input=json.dumps(event),text=True,capture_output=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);return json.loads(r.stdout)
    def prefix(self,output):return json.loads(output['hookSpecificOutput']['additionalContext'].split('LOCAL_HELPER_ARGV=',1)[1].splitlines()[0])
    def helper(self,prefix,args,data=None,code=0):
        r=subprocess.run(prefix+args,input=json.dumps(data) if data is not None else None,text=True,capture_output=True,timeout=15)
        self.assertEqual(r.returncode,code,r.stdout+r.stderr);return json.loads(r.stdout or r.stderr)
    def plan(self):
        spec={'goal':'Repair addition without changing public names','tasks':[{'id':'repair','kind':'implement','description':'Implement addition in app.py and validate it with test_app.py','paths':['app.py'],'depends_on':[],'done_when':['positive and negative additions pass'],'why_parallel':'Independent implementation while leader reviews interface compatibility'}]}
        self.helper(self.root_prefix,['team-plan'],spec)
        return self.helper(self.root_prefix,['team-next'])['reserved'][0]
    def checked(self,prefix):
        task={'task_id':'addition','design':'preserve add interface','requirements':['positive and negative addition'],'allowed_paths':['app.py'],
              'checks':[{'id':'behavior','purpose':'addition cases','argv':[sys.executable,'-B','test_app.py'],'dependencies':['app.py','test_app.py'],'covers':[0]}]}
        self.helper(prefix,['begin'],task);self.assertTrue(self.helper(prefix,['run-all'])['status']['passed'])
        self.helper(prefix,['finish'],{'kind':'tested','summary':'Corrected addition','review':'Checked input signs and callers','limitations':'local behavioral tests'})
    def spawn(self,t):
        p={**self.event,'hook_event_name':'PreToolUse','tool_use_id':'spawn-1','tool_name':'spawn_agent','tool_input':{'message':t['message'],'fork_context':True}}
        self.assertNotIn('permissionDecision',self.hook(p).get('hookSpecificOutput',{}))
        self.hook({**p,'hook_event_name':'PostToolUse','tool_response':json.dumps({'agent_id':'worker-1','nickname':'Worker'})})
        # Codex hook_runtime uses the child's session, not the parent's.
        e={**self.event,'hook_event_name':'SubagentStart','session_id':'worker-1','agent_id':'worker-1','agent_type':'default',
           'permission_mode':'default','transcript_path':None,'turn_id':'worker-turn'}
        prefix=self.prefix(self.hook(e));assigned=self.helper(prefix,['team-join',t['ticket']]);return e,prefix,Path(assigned['workspace'])
    def test_installed_full_team_flow_with_real_git_and_checks(self):
        t=self.plan();e,prefix,tree=self.spawn(t)
        self.assertNotEqual(tree,self.ws);(tree/'app.py').write_text('def add(x,y): return x+y\n')
        self.assertIn('x-y',(self.ws/'app.py').read_text())
        self.checked(prefix)
        self.assertEqual(self.hook({**e,'hook_event_name':'SubagentStop','last_assistant_message':'Implemented and checked.'}),{})
        self.helper(self.root_prefix,['team-integrate','repair'])
        self.assertIn('x+y',(self.ws/'app.py').read_text())
        self.helper(self.root_prefix,['team-accept','repair','--review','Reviewed behavior and the assigned diff'])
        self.checked(self.root_prefix)
        self.assertEqual(self.hook({**self.event,'hook_event_name':'Stop','last_assistant_message':'Ready.'}),{})
        state=self.helper(self.root_prefix,['team-status']);self.assertTrue(state['complete']);self.assertEqual(state['active'],0)
        self.installer.remove();self.assertTrue(tree.is_dir());self.assertTrue(Path(self.receipt['release']).is_dir())
    def test_unchecked_worker_never_integrates(self):
        t=self.plan();e,prefix,tree=self.spawn(t);(tree/'app.py').write_text('def add(x,y): return x+y\n')
        stop={**e,'hook_event_name':'SubagentStop','last_assistant_message':'done'}
        self.assertEqual(self.hook(stop)['decision'],'block');self.hook({**stop,'stop_hook_active':True})
        self.helper(self.root_prefix,['team-integrate','repair'],code=1)
        self.assertIn('x-y',(self.ws/'app.py').read_text())
    def test_late_user_edit_prevents_integration(self):
        t=self.plan();e,prefix,tree=self.spawn(t);(tree/'app.py').write_text('def add(x,y): return x+y\n');self.checked(prefix)
        self.hook({**e,'hook_event_name':'SubagentStop','last_assistant_message':'done'})
        (self.ws/'app.py').write_text('USER_CHANGED_THIS\n');self.helper(self.root_prefix,['team-integrate','repair'],code=1)
        self.assertEqual((self.ws/'app.py').read_text(),'USER_CHANGED_THIS\n')
    def test_dirty_repo_fallback_is_explicit_and_preserves_edits(self):
        (self.ws/'draft.txt').write_text('not committed')
        t=self.plan();self.assertTrue(t['not_dispatched']);self.assertTrue((self.ws/'draft.txt').exists())
        self.assertEqual(self.helper(self.root_prefix,['team-status'])['tasks'][0]['state'],'abandoned')

    def test_installed_native_bash_command_routes_to_owned_checkout(self):
        from luna_astra.transport import helper_command
        t=self.plan();e,prefix,tree=self.spawn(t)
        argv=[sys.executable,'-c',"from pathlib import Path;Path('app.py').write_text('def add(x,y): return x+y\\n')"]
        command=helper_command(prefix+['worker-exec','--argv-json',json.dumps(argv)])
        pre={**e,'hook_event_name':'PreToolUse','tool_name':'Bash','tool_use_id':'write-native','tool_input':{'command':command}}
        output=self.hook(pre)
        self.assertNotEqual(output.get('hookSpecificOutput',{}).get('permissionDecision'),'deny')
        effective=output.get('hookSpecificOutput',{}).get('updatedInput',{}).get('command',command)
        r=subprocess.run(effective,cwd=self.ws,shell=True,text=True,encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertEqual(json.loads(r.stdout)['cwd'],str(tree))
        self.assertIn('x-y',(self.ws/'app.py').read_text());self.assertIn('x+y',(tree/'app.py').read_text())
        self.hook({**pre,'hook_event_name':'PostToolUse','tool_response':{'exit_code':0,'stdout':r.stdout}})
        self.checked(prefix)
        self.hook({**e,'hook_event_name':'SubagentStop','last_assistant_message':'implemented with actual commands'})
        self.helper(self.root_prefix,['team-integrate','repair'])
        self.assertIn('x+y',(self.ws/'app.py').read_text())

    def test_installed_gate_recognizes_reserve_without_changing_model(self):
        output=self.hook({**self.event,'model':'gpt-reserve','session_id':'reserve'})
        prefix=self.prefix(output)
        result=self.helper(prefix,['status']);self.assertEqual(result['session']['model'],'gpt-reserve')

    def test_same_version_update_preserves_foreign_hooks_and_state(self):
        # A content-addressed same-version reinstall is idempotent and retains
        # unrelated hooks even after a LunAstra runtime session has started.
        path=self.home/'hooks.json';data=load_json(path)
        foreign={'hooks':[{'type':'command','command':'echo retained','statusMessage':'foreign'}]}
        data['hooks'].setdefault('Stop',[]).insert(0,foreign);path.write_text(json.dumps(data))
        before=Path(self.receipt['release'])/'luna.py';raw=before.read_bytes()
        again=self.installer.apply()
        from luna_astra import __build__
        self.assertEqual(again['build'],__build__)
        self.assertEqual(again['release'],self.receipt['release']);self.assertEqual(before.read_bytes(),raw)
        self.assertIn(foreign,load_json(path)['hooks']['Stop'])
        self.assertTrue(Path(again['state']).is_dir())
