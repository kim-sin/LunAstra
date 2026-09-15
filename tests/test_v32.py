"""Regression tests for 3.2 compatibility, public delivery and evidence boundaries."""
import copy
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from luna_astra.hooks import Hooks, identity
from luna_astra.install import Installer, definition, decoded
from luna_astra.store import Store
from luna_astra.team import Team
from luna_astra.evidence import Evidence
from luna_astra.gitspace import Workspaces
from luna_astra.util import HarnessError, canonical, load_json
from tools.release import source_version

ROOT = Path(__file__).resolve().parents[1]

class V32Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ws = self.base / 'project'; self.ws.mkdir()
        (self.ws/'app.py').write_text('value = 2\n')
        self.state = self.base/'state'
        self.hooks = Hooks(ROOT, self.state)
        self.event = {'hook_event_name':'SessionStart','session_id':'root','model':'gpt-5.6-luna','cwd':str(self.ws),'turn_id':'turn'}
        self.hooks.handle(self.event)
        self.key = identity(self.event)[0]; self.store = Store(self.state)
    def evidence(self):
        ev = Evidence(self.state/'sessions'/self.key,self.ws)
        ev.begin({'task_id':'test','design':'Keep the public result','requirements':['value equals two'],
            'checks':[{'id':'check','purpose':'Check returned value','argv':[sys.executable,'-B','-c','import app; assert app.value==2'],
              'dependencies':['app.py'],'covers':[0],'reusable':True}]})
        return ev
    def task(self, name='read'):
        return {'id':name,'kind':'investigate','description':'Inspect '+name,'paths':['app.py'],'done_when':['Return actual references'],'why_parallel':'Independent evidence'}
    def invoke(self, event, state=None):
        return subprocess.run([sys.executable,str(ROOT/'luna.py'),'--state',str(state or self.state),'hook'],
            input=json.dumps(event),text=True,capture_output=True,timeout=20)
    def test_postcompact_has_only_supported_native_output(self):
        self.assertEqual(self.hooks.handle({**self.event,'hook_event_name':'PostCompact'}),{})
    def test_postcompact_does_not_count_undelivered_context(self):
        before=self.store.get(self.key,'emitted_chars')
        self.hooks.handle({**self.event,'hook_event_name':'PostCompact'})
        self.assertEqual(before,self.store.get(self.key,'emitted_chars'))
    def test_compaction_restores_on_next_tool_without_restart(self):
        self.hooks.handle({**self.event,'hook_event_name':'PostCompact'})
        e={**self.event,'hook_event_name':'PreToolUse','tool_name':'exec_command','tool_use_id':'inspect','tool_input':{'cmd':'pwd'}}
        result=self.hooks.handle(e)
        self.assertIn('LOCAL_HELPER_ARGV',result['hookSpecificOutput']['additionalContext'])
        self.assertFalse(self.store.get(self.key,'meta')['restore_pending'])
        self.assertEqual(self.hooks.handle({**e,'tool_use_id':'inspect2'}),{})
    def test_compaction_retains_note_for_next_context(self):
        self.store.put(self.key,'note',{'facts':['verified entry point']})
        self.hooks.handle({**self.event,'hook_event_name':'PostCompact'})
        text=self.hooks.handle({**self.event,'source':'compact'})['hookSpecificOutput']['additionalContext']
        self.assertIn('verified entry point',text)
    def test_compaction_restores_worker_without_new_root(self):
        e={**self.event,'agent_id':'child','hook_event_name':'SubagentStart'}
        self.hooks.handle(e);self.hooks.handle({**e,'hook_event_name':'PostCompact'})
        e.update(hook_event_name='PreToolUse',tool_use_id='read',tool_name='exec_command',tool_input={'cmd':'pwd'})
        self.assertIn('delegated Luna worker',self.hooks.handle(e)['hookSpecificOutput']['additionalContext'])
    def test_compaction_does_not_install_inapplicable_context_limit(self):
        group=definition(Path(sys.executable),ROOT,self.state,'PostCompact')
        self.assertNotIn('additionalContextLimit',group['hooks'][0])
    def test_wrong_event_type_is_controlled_error(self):
        with self.assertRaises(HarnessError): self.hooks.handle({**self.event,'hook_event_name':[]})
    def test_wrong_turn_type_is_controlled_error(self):
        with self.assertRaises(HarnessError): self.hooks.handle({**self.event,'turn_id':[]})
    def test_wrong_stop_flag_cannot_disable_guard(self):
        with self.assertRaises(HarnessError): self.hooks.handle({**self.event,'hook_event_name':'Stop','stop_hook_active':'false'})
    def test_invalid_assistant_message_is_not_a_regex_crash(self):
        r=self.invoke({**self.event,'hook_event_name':'Stop','last_assistant_message':{'done':True}})
        self.assertEqual(r.returncode,0);self.assertFalse(json.loads(r.stdout)['continue'])
    def test_corrupt_metadata_is_a_controlled_stop(self):
        self.store.put(self.key,'meta',[])
        r=self.invoke({**self.event,'hook_event_name':'Stop'})
        self.assertFalse(json.loads(r.stdout)['continue']);self.assertNotIn('Traceback',r.stderr)
    def test_corrupt_alias_is_rejected(self):
        self.store.put('__agent_alias__','root',[])
        with self.assertRaises(HarnessError):self.hooks.handle(self.event)
    def test_wrong_finish_type_cannot_certify(self):
        ev=self.evidence()
        with ev._transaction() as db: ev._set(db,'finish',[])
        with self.assertRaises(HarnessError):ev.status()
    def test_wrong_task_type_cannot_certify(self):
        ev=self.evidence()
        with ev._transaction() as db: ev._set(db,'task',[1])
        with self.assertRaises(HarnessError):ev.status()
    def test_corrupt_check_cannot_execute(self):
        ev=self.evidence()
        with ev._transaction() as db:db.execute("UPDATE checks SET spec='[]'")
        with patch('luna_astra.evidence.subprocess.Popen') as start:
            with self.assertRaises(HarnessError):ev.run('check')
            start.assert_not_called()
    def test_duplicate_json_in_state_is_rejected(self):
        with self.store.db(True) as db:db.execute('INSERT INTO kv VALUES(?,?,?)',(self.key,'bad','{"a":1,"a":2}'))
        with self.assertRaises(HarnessError):self.store.get(self.key,'bad')
    def test_nonfinite_json_in_state_is_rejected(self):
        with self.store.db(True) as db:db.execute('INSERT INTO kv VALUES(?,?,?)',(self.key,'bad','NaN'))
        with self.assertRaises(HarnessError):self.store.get(self.key,'bad')
    def test_no_second_command_for_running_check(self):
        ev=self.evidence()
        with ev._transaction() as db:
            row=db.execute('SELECT spec_hash FROM checks').fetchone()
            db.execute('INSERT INTO attempts(check_id,task_hash,spec_hash,status,started) VALUES(?,?,?,?,?)',('check',ev._get(db,'task_hash'),row[0],'RUNNING',0))
        with patch('luna_astra.evidence.subprocess.Popen') as start:
            with self.assertRaises(HarnessError):ev.run('check')
            start.assert_not_called()
    def test_success_text_with_failed_exit_is_not_a_pass(self):
        ev=self.evidence();ev.run('check')
        with ev._transaction() as db:db.execute('UPDATE attempts SET exit_code=1')
        self.assertFalse(ev.status()['passed'])
    def test_success_without_end_time_is_not_a_pass(self):
        ev=self.evidence();ev.run('check')
        with ev._transaction() as db:db.execute('UPDATE attempts SET ended=NULL')
        self.assertFalse(ev.status()['passed'])
    def test_old_completion_identity_is_invalid(self):
        ev=self.evidence();ev.run('check');ev.finish('tested','Result','Inspected behavior','Local check')
        with ev._transaction() as db:
            claim=ev._get(db,'finish');claim['task_hash']='wrong';ev._set(db,'finish',claim)
        self.assertFalse(ev.status()['finish']['valid'])
    def test_corrupt_reusable_check_cannot_be_reused(self):
        ev=self.evidence();ev.run('check')
        with ev._transaction() as db:db.execute("UPDATE checks SET spec_hash='wrong'")
        with self.assertRaises(HarnessError):ev.run_all()
    def test_pending_plan_can_change_without_losing_history(self):
        team=Team(self.store);first=team.plan(self.key,self.ws,{'goal':'Investigate','tasks':[self.task()]})
        second=team.plan(self.key,self.ws,{'goal':'Inspect updated request','tasks':[self.task('new')]})
        self.assertNotEqual(first['plan_id'],second['plan_id'])
        with self.store.db() as db:
            row=db.execute('SELECT state FROM work WHERE plan_id=?',(first['plan_id'],)).fetchone()
        self.assertEqual(row[0],'abandoned')
    def test_running_plan_cannot_be_replaced(self):
        team=Team(self.store);team.plan(self.key,self.ws,{'goal':'Investigate','tasks':[self.task()]});team.reserve(self.key)
        with self.assertRaises(HarnessError):team.plan(self.key,self.ws,{'goal':'New','tasks':[self.task('new')]})
    def test_zero_workers_remains_valid(self):
        self.assertTrue(Team(self.store).plan(self.key,self.ws,{'goal':'Answer directly','tasks':[]})['complete'])
    def test_doctor_missing_install_has_failure_exit(self):
        r=subprocess.run([sys.executable,str(ROOT/'install.py'),'doctor','--json','--codex-home',str(self.base/'home')],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,2);self.assertFalse(json.loads(r.stdout)['installed_payload_matches_package'])
    def test_published_version_comes_from_executable_source(self):
        from luna_astra import __version__
        self.assertEqual(source_version(ROOT),__version__)
    def test_windows_prefilter_defers_escaped_json_to_real_parser(self):
        cmd=definition(Path(sys.executable),ROOT,self.state,'SessionStart')['hooks'][0]['commandWindows']
        self.assertIn("$raw.Contains('\\u')",decoded(cmd))
    def test_real_launcher_accepts_escaped_luna_model(self):
        e=json.dumps({**self.event,'session_id':'escaped'}).replace('luna','\\u006cuna')
        cmd=definition(Path(sys.executable),ROOT,self.state,'SessionStart')['hooks'][0]['command']
        result=subprocess.run(cmd,shell=True,input=e,text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('LOCAL_HELPER_ARGV',json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
    def test_real_launcher_keeps_non_luna_fast_path(self):
        cmd=definition(Path('/deliberately-missing-python'),ROOT,self.state,'SessionStart')['hooks'][0]['command']
        result=subprocess.run(cmd,shell=True,input=json.dumps({**self.event,'model':'gpt-6-astra'}),text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout),{})
    def test_update_preserves_prior_runtime_and_release(self):
        home=self.base/'home';ins=Installer(ROOT,home);receipt=ins.apply()
        state=Path(receipt['state']);state.mkdir(parents=True,exist_ok=True);(state/'retained.txt').write_text('preserve me')
        old=Path(receipt['release']);second=ins.apply()
        self.assertTrue(old.exists());self.assertEqual((state/'retained.txt').read_text(),'preserve me')
        self.assertFalse(second['hook_changed'])

@unittest.skipUnless(shutil.which('git'),'Git required')
class V32GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.ws=self.base/'repo';self.ws.mkdir()
        self.git(self.ws,'init','-q');self.git(self.ws,'config','user.name','Test Author');self.git(self.ws,'config','user.email','test@example.invalid')
        for n in ('a.py','b.py'):(self.ws/n).write_text('value=1\n')
        self.git(self.ws,'add','.');self.git(self.ws,'commit','-qm','fixture')
        self.spaces=Workspaces(self.base/'trees');self.ticket='e'*32
    def git(self,root,*args):return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
    def test_hidden_staged_change_cannot_enter_reviewed_patch(self):
        info=self.spaces.prepare(self.ticket,self.ws,['a.py']);tree=Path(info['tree'])
        (tree/'b.py').write_text('secret_change=9\n');self.git(tree,'add','b.py');(tree/'b.py').write_text('value=1\n')
        (tree/'a.py').write_text('value=2\n')
        with self.assertRaises(HarnessError):self.spaces.integrate(self.ticket)
        self.assertEqual((self.ws/'a.py').read_text(),'value=1\n');self.assertEqual((self.ws/'b.py').read_text(),'value=1\n')
    def test_user_permission_change_is_preserved(self):
        info=self.spaces.prepare(self.ticket,self.ws,['a.py']);(Path(info['tree'])/'a.py').write_text('value=2\n')
        mode=0o444 if os.name=='nt' else 0o755
        (self.ws/'a.py').chmod(mode)
        self.addCleanup((self.ws/'a.py').chmod,0o644)
        with self.assertRaises(HarnessError):self.spaces.integrate(self.ticket)
        self.assertEqual(stat.S_IMODE((self.ws/'a.py').stat().st_mode),mode)
