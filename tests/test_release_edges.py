import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from luna_astra.evidence import Evidence
from luna_astra.install import Installer,definition,decoded,legacy_argv
from luna_astra.hooks import Hooks,identity
from luna_astra.store import Store
from luna_astra.util import load_json,write_json
ROOT=Path(__file__).resolve().parents[1]

class ReleaseEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.ws=self.base/'workspace-café';self.ws.mkdir();(self.ws/'app.py').write_text('answer=2\n')
        self.ev=Evidence(self.base/'checks',self.ws)
        self.task={'task_id':'edge','design':'preserve interface','requirements':['answer=2'],'allowed_paths':['app.py'],
                   'checks':[{'id':'check','purpose':'behavior','argv':[sys.executable,'-B','-c','import app; assert app.answer==2'],'dependencies':['app.py'],'covers':[0]}]}
        self.ev.begin(self.task)
    def test_deleted_check_row_invalidates_definition(self):
        self.ev.run('check')
        with self.ev._transaction() as db:db.execute('DELETE FROM checks')
        self.assertFalse(self.ev.status()['passed'])
    def test_mutated_check_row_is_not_certified(self):
        self.ev.run('check')
        with self.ev._transaction() as db:db.execute("UPDATE checks SET spec_hash='tampered'")
        self.assertFalse(self.ev.status()['passed'])
    def test_expected_deletion_is_verified(self):
        self.task['checks'][0]['expected_absent']=['obsolete.py'];self.ev.begin(self.task);self.ev.run('check')
        self.assertTrue(self.ev.status()['passed']);(self.ws/'obsolete.py').write_text('stale=1\n');self.assertFalse(self.ev.status()['passed'])
    def test_unicode_hook_protocol_ignores_legacy_console_encoding(self):
        event={'hook_event_name':'SessionStart','model':'gpt-5.6-luna','session_id':'root','cwd':str(self.ws)}
        env={**os.environ,'PYTHONIOENCODING':'ascii'}
        r=subprocess.run([sys.executable,str(ROOT/'luna.py'),'--state',str(self.base/'state'),'hook'],input=json.dumps(event,ensure_ascii=False).encode('utf-8'),capture_output=True,env=env,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr);data=json.loads(r.stdout.decode('utf-8'));self.assertIn('LOCAL_HELPER_ARGV',data['hookSpecificOutput']['additionalContext'])
    def test_public_installer_json_mode(self):
        r=subprocess.run([sys.executable,str(ROOT/'install.py'),'plan','--codex-home',str(self.base/'codex'),'--json'],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['version'],__import__('luna_astra').__version__)
        self.assertFalse((self.base/'codex').exists())
    def test_public_installer_from_another_directory(self):
        r=subprocess.run([sys.executable,str(ROOT/'install.py'),'plan','--codex-home',str(self.base/'codex')],cwd=self.base,capture_output=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr);self.assertIn(b'LunAstra',r.stdout)
    def test_v2_receipt_migration_preserves_other_handlers(self):
        home=self.base/'codex';home.mkdir();base=home/'luna-astra';base.mkdir()
        legacy={'type':'command','command':'old-command','statusMessage':'Luna Astra v2 / Stop'}
        other={'type':'command','command':'keep-this','statusMessage':'User notification'}
        write_json(home/'hooks.json',{'hooks':{'Stop':[{'hooks':[legacy,other]}]}})
        write_json(base/'installation.json',{'version':'2.0.0-rc1','owned_handlers':{'Stop':[legacy]},'release':str(base/'releases'/'old')})
        old_state=base/'state-v2';old_state.mkdir();(old_state/'saved.txt').write_text('retain')
        receipt=Installer(ROOT,home).apply();obj=load_json(home/'hooks.json')
        flat=[h for g in obj['hooks']['Stop'] for h in g['hooks']]
        self.assertIn(other,flat);self.assertNotIn(legacy,flat);self.assertTrue((old_state/'saved.txt').exists())
        self.assertTrue(Path(receipt['backup']).is_file())
    def test_double_click_scripts_do_not_depend_on_current_directory(self):
        for name in ('INSTALL.cmd','CHECK.cmd','UNREGISTER.cmd'):
            text=(ROOT/name).read_text();self.assertIn('pushd "%~dp0"',text);self.assertNotIn('ExecutionPolicy',text)
    def test_corrupt_runtime_denies_tool_instead_of_silently_skipping_guard(self):
        state=self.base/'state';state.mkdir();(state/'runtime.sqlite3').write_bytes(b'broken')
        event={'hook_event_name':'PreToolUse','model':'gpt-5.6-luna','session_id':'root','cwd':str(self.ws),'tool_name':'spawn_agent','tool_use_id':'one','tool_input':{}}
        r=subprocess.run([sys.executable,str(ROOT/'luna.py'),'--state',str(state),'hook'],input=json.dumps(event),text=True,capture_output=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(json.loads(r.stdout)['hookSpecificOutput']['permissionDecision'],'deny')
    def test_corrupt_runtime_stop_is_explicit_failure(self):
        state=self.base/'state';state.mkdir();(state/'runtime.sqlite3').write_bytes(b'broken')
        event={'hook_event_name':'Stop','model':'gpt-5.6-luna','session_id':'root','cwd':str(self.ws),'last_assistant_message':'done'}
        r=subprocess.run([sys.executable,str(ROOT/'luna.py'),'--state',str(state),'hook'],input=json.dumps(event),text=True,capture_output=True,timeout=15)
        result=json.loads(r.stdout);self.assertFalse(result['continue']);self.assertIn('UNVERIFIED',result['stopReason'])
    def test_kotlin_and_swift_symbol_navigation_is_labeled_as_hint(self):
        from luna_astra.codemap import parse_source,EXTENSIONS
        for name,source,expected in [('a.kt','class Sample { fun calculate() = 2 }','calculate'),('b.swift','struct Shape { func area() -> Int { 2 } }','area')]:
            self.assertIn(Path(name).suffix,EXTENSIONS);r=parse_source(name,source);self.assertEqual(r['confidence'],'lexical_hint')
            self.assertIn(expected,[s['name'] for s in r['symbols']])

    def test_windows_wrapper_uses_utf8_without_changing_profile(self):
        group=definition(Path("C:/Python/python.exe"),Path("C:/Tools/café"),Path("C:/State"),'SessionStart')
        script=decoded(group['hooks'][0]['commandWindows'])
        self.assertIn('[Console]::OutputEncoding=$utf8',script)
        self.assertIn('[Console]::InputEncoding=$utf8',script)
        self.assertIn('$OutputEncoding=$utf8',script)
        self.assertLess(script.index('[Console]::OutputEncoding'),script.index("& '"))
        self.assertNotIn('$PROFILE',script)
        self.assertIn('exit $LASTEXITCODE',script)

    def test_installer_utf8_diagnostics_ignore_ascii_pipe_default(self):
        r=subprocess.run([sys.executable,str(ROOT/'install.py'),'plan','--codex-home',str(self.base/'empty-home')],
                         capture_output=True,env={**os.environ,'PYTHONIOENCODING':'ascii'},timeout=15)
        self.assertEqual(r.returncode,0,r.stderr)
        text=r.stdout.decode('utf-8');self.assertIn('Installation plan',text)
        self.assertIn('To apply: '+('py -3 install.py apply' if os.name=='nt' else 'python3 install.py apply'),text)
        self.assertFalse((self.base/'empty-home').exists())
