import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from luna_astra.install import Installer,EVENTS,OWNER,definition,payload,strip_owned,powershell_argv,decoded,legacy_argv
from luna_astra.util import HarnessError,load_json,write_json
ROOT=Path(__file__).resolve().parents[1]

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.home=self.base/"codex space 'quoted'";self.home.mkdir();self.inst=Installer(ROOT,self.home)
        for name,data in [('config.toml',b'model="unchanged"\nmodel_reasoning_effort="max"\n'),('AGENTS.md',b'protected commander'),('auth.json',b'{"protected":"account"}')]:
            (self.home/name).write_bytes(data)
        self.original={n:(self.home/n).read_bytes() for n in ('config.toml','AGENTS.md','auth.json')}
    def test_plan_read_only(self):
        before=sorted(str(p) for p in self.home.rglob('*'));self.inst.plan();self.assertEqual(before,sorted(str(p) for p in self.home.rglob('*')))
    def test_main_settings_and_account_preserved(self):
        self.inst.apply();self.assertEqual(self.original,{n:(self.home/n).read_bytes() for n in self.original})
    def test_seven_official_events_installed(self):
        self.inst.apply();self.assertEqual(set(load_json(self.home/'hooks.json')['hooks']),EVENTS)
    def test_apply_idempotent(self):
        self.inst.apply();before=(self.home/'hooks.json').read_bytes();r=self.inst.apply();self.assertFalse(r['hook_changed']);self.assertEqual(before,(self.home/'hooks.json').read_bytes())
    def test_exact_original_backup(self):
        data=b'{ "hooks": {}, "description":"spacing" }\n';(self.home/'hooks.json').write_bytes(data)
        r=self.inst.apply();self.assertEqual(Path(r['backup']).read_bytes(),data)
    def test_foreign_hooks_preserved(self):
        original={'description':'mine','hooks':{'Stop':[{'hooks':[{'type':'command','command':'echo mine'}],'custom':True}]}}
        write_json(self.home/'hooks.json',original);r=self.inst.apply()
        self.assertEqual(strip_owned(load_json(self.home/'hooks.json'),r,self.home),original)
    def test_user_changes_to_owned_handler_not_silently_deleted(self):
        self.inst.apply();obj=load_json(self.home/'hooks.json');obj['hooks']['Stop'][-1]['hooks'][0]['command']='echo my-modification'
        write_json(self.home/'hooks.json',obj)
        with self.assertRaises(HarnessError):self.inst.apply()
        self.assertEqual(obj,load_json(self.home/'hooks.json'))
    def test_malformed_existing_hooks_refused(self):
        for raw in (b'{',b'[]',b'{"hooks":[]}',b'{"hooks":{},"hooks":{}}'):
            (self.home/'hooks.json').write_bytes(raw)
            with self.subTest(raw=raw),self.assertRaises((HarnessError,ValueError)):self.inst.apply()
            self.assertEqual((self.home/'hooks.json').read_bytes(),raw)
    def test_hook_symlink_refused(self):
        out=self.base/'outside';out.write_text('{"hooks":{}}');(self.home/'hooks.json').symlink_to(out)
        with self.assertRaises(HarnessError):self.inst.apply()
    def test_existing_install_lock_preserved(self):
        lock=self.home/'luna-astra'/'install.lock';lock.parent.mkdir();lock.write_text('busy')
        with self.assertRaises(HarnessError):self.inst.apply()
        self.assertEqual(lock.read_text(),'busy')
    def test_tampered_release_not_overwritten(self):
        r=self.inst.apply();p=Path(r['release'])/'prompts'/'CORE.md';p.write_text('user edit')
        with self.assertRaises(HarnessError):self.inst.apply()
        self.assertEqual(p.read_text(),'user edit')
    def test_receipt_failure_rolls_back(self):
        before=b'{"hooks":{},"owner":"original"}\n';(self.home/'hooks.json').write_bytes(before)
        original=write_json
        def fail(path,value):
            if path.name=='installation.json':raise OSError('fixture disk failure')
            return original(path,value)
        with patch('luna_astra.install.write_json',side_effect=fail):
            with self.assertRaises(OSError):self.inst.apply()
        self.assertEqual((self.home/'hooks.json').read_bytes(),before)
    def test_first_install_failure_removes_only_new_hooks(self):
        with patch('luna_astra.install.write_json',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.inst.apply()
        self.assertFalse((self.home/'hooks.json').exists());self.assertTrue((self.home/'auth.json').is_file())
    def test_unregister_preserves_release_and_later_hooks(self):
        r=self.inst.apply();obj=load_json(self.home/'hooks.json');obj['hooks']['Stop'].append({'hooks':[{'type':'command','command':'echo later'}]});write_json(self.home/'hooks.json',obj)
        self.inst.remove();self.assertEqual(payload(Path(r['release'])),payload(ROOT))
        self.assertEqual(load_json(self.home/'hooks.json')['hooks'],{'Stop':[{'hooks':[{'type':'command','command':'echo later'}]}]})
    def test_trust_never_bypassed(self):
        self.inst.apply();text=(self.home/'hooks.json').read_text();self.assertNotIn('bypass-hook-trust',text);self.assertNotIn('"trusted"',text)
    def test_windows_command_quoting_is_data_not_execution(self):
        group=definition(Path('C:/Python/python.exe'),Path("C:/User's files/release"),Path('C:/state'),'SessionStart')
        script=decoded(group['hooks'][0]['commandWindows']);self.assertIn("User''s files",script);self.assertIn("'hook'",script)
    def test_legacy_rc1_receipt_migration(self):
        import shlex
        old=self.home/'luna-astra'/'releases'/'1.0.0-rc1-old';old.mkdir(parents=True);(old/'luna.py').write_text('# existing')
        receipt={'version':'1.0.0-rc1','release':str(old),'state':str(self.base/'oldstate')};write_json(self.home/'luna-astra'/'installation.json',receipt)
        obj={'hooks':{}}
        for e,label in [('SubagentStart','start'),('SubagentStop','stop')]:
            h={'type':'command','command':shlex.join([sys.executable,str(old/'luna.py'),'--state',receipt['state'],'hook']),
               'statusMessage':'Luna Astra / owned worker hook / '+label}
            obj['hooks'][e]=[{'matcher':'*','hooks':[h]}]
        write_json(self.home/'hooks.json',obj);self.inst.apply();new=load_json(self.home/'hooks.json')
        self.assertEqual(len(new['hooks']['SubagentStart']),1);self.assertTrue((old/'luna.py').is_file())
    def test_lost_receipt_does_not_duplicate_hooks(self):
        self.inst.apply();(self.home/'luna-astra'/'installation.json').unlink()
        with self.assertRaises(HarnessError):self.inst.apply()

    def test_legacy_posix_apostrophe_and_operator_rejection(self):
        import shlex
        argv=[sys.executable,"/home/user's/release/luna.py",'--state',"/state x'",'hook']
        self.assertEqual(legacy_argv(shlex.join(argv)),argv)
        self.assertIsNone(legacy_argv(shlex.join(argv)+'; echo injected'))
    def test_legacy_windows_apostrophe_and_operator_rejection(self):
        import base64
        argv=['C:/Python/python.exe',"C:/user's/release/luna.py",'--state','C:/state','hook']
        def encode(script):return 'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '+base64.b64encode(script.encode('utf-16-le')).decode()
        script="$ErrorActionPreference='Stop'; "+powershell_argv(argv)+'; exit $LASTEXITCODE'
        self.assertEqual(legacy_argv(encode(script)),argv)
        self.assertIsNone(legacy_argv(encode(script+'; echo extra')))
    def test_legacy_similar_path_not_owned(self):
        import shlex
        old=self.home/'luna-astra'/'releases'/'1.0.0-rc1-old'
        receipt={'version':'1.0.0-rc1','release':str(old),'state':str(self.base/'oldstate')}
        h={'type':'command','command':shlex.join([sys.executable,str(old/'luna.py.bak'),'--state',receipt['state'],'hook']),
           'statusMessage':'Luna Astra / owned worker hook / start'}
        obj={'hooks':{'SubagentStart':[{'hooks':[h]}]}}
        self.assertEqual(strip_owned(obj,receipt,self.home),obj)
