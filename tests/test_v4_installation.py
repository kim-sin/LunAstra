"""Installed 4.0 transport, migration and active-job preservation."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from luna_astra.install import Installer
from luna_astra.hooks import Hooks,identity
from luna_astra.store import Store
from luna_astra.transport import helper_command,literal_argv
from luna_astra.util import HarnessError,write_json

PACKAGE=Path(__file__).resolve().parents[1]
class V4InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.home=self.base/'home';self.home.mkdir()
        self.workspace=self.base/'project';self.workspace.mkdir();(self.workspace/'app.py').write_text('n=5\n')
        (self.home/'config.toml').write_text('model = "retained-by-user"\n')
        self.installer=Installer(PACKAGE,self.home);self.receipt=self.installer.apply()
    def test_new_state_separate_old_bytes_untouched(self):
        old=self.home/'luna-astra/state-v3';old.mkdir();(old/'keep.txt').write_bytes(b'old original')
        receipt=self.installer.apply()
        self.assertTrue(receipt['state'].endswith('state-v4'));self.assertEqual(b'old original',(old/'keep.txt').read_bytes())
        self.assertEqual('model = "retained-by-user"\n',(self.home/'config.toml').read_text())
    def test_installed_long_begin_single_rewrite_cli(self):
        release=Path(self.receipt['release']);state=Path(self.receipt['state'])
        event={'session_id':'root','cwd':str(self.workspace),'model':'gpt-5.6-luna','turn_id':'one'}
        hooks=Hooks(release,state,fixed_seven=True);hooks.handle({**event,'hook_event_name':'SessionStart'})
        hooks.handle({**event,'hook_event_name':'UserPromptSubmit','prompt':'inspect actual app'})
        owner=identity(event)[0];prefix=[sys.executable,str(release/'luna.py'),'--state',str(state),'--session',owner]
        data={'task_id':'long','design':'Actual test registration','requirements':['n equals five'],
              'checks':[{'id':'one','purpose':'Semantic assertion '+('long transport fixture '*3000),
                         'argv':[sys.executable,'-c','import app; assert app.n==5'],
                         'dependencies':['app.py'],'covers':[0]}]}
        command=helper_command(prefix+['--input-json',json.dumps(data),'begin'])
        response=hooks.handle({**event,'hook_event_name':'PreToolUse','tool_use_id':'one','tool_name':'Bash','tool_input':{'command':command}})
        output=response['hookSpecificOutput'];self.assertEqual('allow',output['permissionDecision'])
        rewritten=output['updatedInput']['command'];self.assertIn('--input-ref',rewritten)
        # This subprocess uses the actual installed code. On Windows the exact
        # safe rewritten PowerShell is the public transport; POSIX uses argv.
        run=subprocess.run(rewritten if sys.platform=='win32' else literal_argv(rewritten),shell=sys.platform=='win32',cwd=self.workspace,
                           text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(0,run.returncode,run.stdout+run.stderr);self.assertTrue(json.loads(run.stdout)['task_hash'])
        self.assertEqual(1,len(list((state/'requests'/owner).glob('*.json'))))
    def test_active_research_refuses_payload_replacement(self):
        state=Store(Path(self.receipt['state']))
        with state.db() as db:
            db.execute('CREATE TABLE research_studies(owner TEXT PRIMARY KEY,spec TEXT NOT NULL)')
            db.execute('INSERT INTO research_studies VALUES(?,?)',('a'*64,json.dumps({'state':'RUNNING'})))
        # A different legitimate package payload must not replace hooks of an
        # active/unknown process. No fabricated PID or automatic process kill.
        copy=self.base/'copy';shutil.copytree(PACKAGE,copy,ignore=shutil.ignore_patterns('__pycache__'))
        with (copy/'prompts/CORE.md').open('a') as stream:stream.write('\nNew inspected package.\n')
        before=(self.home/'hooks.json').read_bytes()
        with self.assertRaises(HarnessError) as caught:Installer(copy,self.home).apply()
        self.assertEqual('UPGRADE_ACTIVE_WORK',caught.exception.code);self.assertEqual(before,(self.home/'hooks.json').read_bytes())
    def test_current_helper_uses_no_extra_model_api(self):
        run=subprocess.run([sys.executable,str(Path(self.receipt['release'])/'luna.py'),'help'],capture_output=True,text=True)
        self.assertEqual(0,run.returncode);info=json.loads(run.stdout)
        self.assertEqual(__import__('luna_astra').__version__,info['version']);self.assertIn('crew-step',info['commands']);self.assertEqual(6,info['fixed_seven']['children'])

if __name__=='__main__':unittest.main()
