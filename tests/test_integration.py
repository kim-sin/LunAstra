import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from luna_astra.install import Installer
from luna_astra.util import load_json
ROOT=Path(__file__).resolve().parents[1]

class IntegrationTests(unittest.TestCase):
    def test_installed_root_helper_real_checks_reuse_and_stale_gate(self):
        self._exercise(False)
    def test_installed_worker_helper_real_checks_reuse_and_stale_gate(self):
        self._exercise(True)
    def _exercise(self,worker):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);home=base/'codex';ws=base/'project';ws.mkdir()
            (ws/'app.py').write_text('def add(x,y): return x+y\n')
            (ws/'test_app.py').write_text('from app import add\nassert add(2,3)==5\nassert add(-2,2)==0\n')
            installer=Installer(ROOT,home);receipt=installer.apply();config=load_json(home/'hooks.json')['hooks']
            def hook(event):
                handler=config[event['hook_event_name']][-1]['hooks'][0]
                run=subprocess.run(handler['command'],shell=True,input=json.dumps(event),text=True,capture_output=True,timeout=15)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr);return json.loads(run.stdout)
            event={'hook_event_name':'SessionStart','model':'gpt-5.6-luna','session_id':'root-session','cwd':str(ws),'source':'startup'}
            if worker:event.update(hook_event_name='SubagentStart',agent_id='child-worker')
            # Existing pre-upgrade sessions keep their original protocol.
            from luna_astra.hooks import Hooks
            Hooks(Path(receipt['release']),Path(receipt['state'])).handle(event)
            output=hook({**event,'source':'resume'})['hookSpecificOutput']['additionalContext']
            prefix=json.loads(output.split('LOCAL_HELPER_ARGV=',1)[1].splitlines()[0])
            def helper(args,data=None,code=0):
                run=subprocess.run(prefix+args,input=json.dumps(data) if data is not None else None,text=True,capture_output=True,timeout=15)
                self.assertEqual(run.returncode,code,run.stdout+run.stderr);return json.loads(run.stdout if run.stdout else run.stderr)
            prompt={**event,'hook_event_name':'UserPromptSubmit','turn_id':'turn1','prompt':'Implement add in app.py'};hook(prompt)
            task={'task_id':'add','design':'preserve addition','requirements':['addition works'],'allowed_paths':['app.py'],
                  'checks':[{'id':'behavior','purpose':'actual addition','argv':[sys.executable,'-B','test_app.py'],
                   'dependencies':['app.py','test_app.py'],'covers':[0],'reusable':True}]}
            helper(['begin'],task);self.assertTrue(helper(['run-all'])['status']['passed'])
            self.assertTrue(helper(['run-all'])['checks'][0]['reused'])
            helper(['finish'],{'kind':'tested','summary':'addition correct','review':'positive and negative inputs','limitations':'synthetic local fixture'})
            stop={**event,'hook_event_name':'SubagentStop' if worker else 'Stop','turn_id':'turn1','last_assistant_message':'LUNA_ASTRA_STATUS=TESTED'}
            self.assertEqual(hook(stop),{})
            (ws/'app.py').write_text('def add(x,y): return x-y\n')
            self.assertEqual(hook(stop)['decision'],'block')
            self.assertNotIn('decision',hook({**stop,'stop_hook_active':True}))
            self.assertFalse(helper(['doctor'])['sessions'][0]['current_tested'])
            installer.remove();self.assertTrue(Path(receipt['release']).is_dir())
    def test_installed_other_model_is_noop_and_creates_no_state(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);home=base/'codex';ws=base/'work';ws.mkdir();receipt=Installer(ROOT,home).apply()
            handler=load_json(home/'hooks.json')['hooks']['SessionStart'][0]['hooks'][0]
            run=subprocess.run(handler['command'],shell=True,input=json.dumps({'hook_event_name':'SessionStart','model':'gpt-6-astra','cwd':str(ws)}),text=True,capture_output=True,timeout=15)
            self.assertEqual(json.loads(run.stdout),{});self.assertFalse(Path(receipt['state']).exists())
    def test_installed_non_luna_gate_skips_python_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);home=base/'codex';ws=base/'project';ws.mkdir()
            receipt=Installer(ROOT,home).apply();config=load_json(home/'hooks.json')['hooks']
            handler=config['SessionStart'][-1]['hooks'][0]
            # Prove the outer gate can return for Astra without loading the installed Python helper.
            helper=Path(receipt['release'])/'luna.py';backup=helper.with_suffix('.disabled');helper.rename(backup)
            try:
                event={'hook_event_name':'SessionStart','model':'gpt-6-astra','session_id':'root-session','cwd':str(ws)}
                run=subprocess.run(handler['command'],shell=True,input=json.dumps(event),text=True,capture_output=True,timeout=15)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr);self.assertEqual(json.loads(run.stdout),{})
            finally:
                backup.rename(helper)

    def test_cli_invalid_json_and_opaque_key_refused(self):
        for args,data in [(['hook'],'{'),(['--session','../escape','status'],None)]:
            run=subprocess.run([sys.executable,str(ROOT/'luna.py')]+args,input=data,text=True,capture_output=True,timeout=15)
            self.assertNotEqual(run.returncode,0)
