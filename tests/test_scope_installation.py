"""Targeted installation and lifecycle routing. No user's Codex home is touched."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from luna_astra import gate_trace
from luna_astra.install import Installer,definition,payload
from luna_astra.hooks import Hooks
from luna_astra.model_gate import EVENTS

ROOT=Path(__file__).resolve().parents[1]

class ScopeInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.home=self.base/"codex home 'quote'";self.home.mkdir();self.inst=Installer(ROOT,self.home)
        self.foreign={'type':'command','command':'echo foreign-kept','statusMessage':'other extension'}
        (self.home/'hooks.json').write_text(json.dumps({'hooks':{'Stop':[{'hooks':[self.foreign]}]}}))
        for name,data in [('config.toml','model="untouched"\n'),('auth.json','{"private":"retain"}'),('AGENTS.md','keep')]:
            (self.home/name).write_text(data)
        self.original={p.name:p.read_bytes() for p in self.home.iterdir() if p.name!='hooks.json'}
        self.env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
    def cli(self,*args,json_mode=True,home=True,env=None):
        command=[sys.executable,str(ROOT/'install.py'),*args]
        if home:command+=['--codex-home',str(self.home)]
        if json_mode:command+=['--json']
        return subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30,env=env or self.env)
    def hook(self,receipt,event):
        handler=json.loads((self.home/'hooks.json').read_text())['hooks'][event['hook_event_name']][-1]['hooks'][0]
        cmd=handler['commandWindows'] if os.name=='nt' else handler['command']
        cp=subprocess.run(cmd,input=json.dumps(event),shell=True,text=True,encoding='utf-8',capture_output=True,timeout=30,env=self.env)
        self.assertEqual(0,cp.returncode,cp.stdout+cp.stderr)
        return json.loads(cp.stdout)
    def test_trace_start_cannot_register_hooks(self):
        before=(self.home/'hooks.json').read_bytes();cp=self.cli('gate-trace')
        self.assertNotEqual(0,cp.returncode);self.assertEqual(before,(self.home/'hooks.json').read_bytes())
        self.assertFalse((self.home/'luna-astra').exists())
    def test_register_doctor_separates_layers(self):
        self.inst.apply();cp=self.cli('doctor');self.assertEqual(0,cp.returncode,cp.stderr);r=json.loads(cp.stdout)
        self.assertEqual(9,r['registration']['owned_handlers']);self.assertTrue(r['registration']['HOOKS_REGISTERED'])
        self.assertFalse(r['activation_layers']['LUNA_EVENT_ACCEPTED']);self.assertFalse(r['activation_layers']['KERNEL_EMITTED'])
        self.assertEqual('UNKNOWN',r['activation_layers']['HOST_EFFECTIVE_CODEX_HOME'])
        self.assertFalse(r['model_gate_trace']['armed'])
    def test_trace_enable_export_stop_without_models(self):
        receipt=self.inst.apply();state=Path(receipt['state'])
        cp=self.cli('gate-trace','--trace-seconds','20','--trace-events','4');self.assertEqual(0,cp.returncode,cp.stderr)
        self.assertTrue(json.loads(cp.stdout)['armed']);self.assertFalse(state.exists())
        event={'hook_event_name':'SessionStart','model':'gpt-6-astra','session_id':'synthetic','cwd':str(self.base/'unread')}
        self.assertEqual({},self.hook(receipt,event));self.assertFalse(state.exists())
        cp=self.cli('gate-report');self.assertEqual(0,cp.returncode,cp.stderr);report=Path(json.loads(cp.stdout)['report_path'])
        self.assertEqual(1,json.loads(report.read_text())['events_recorded'])
        cp=self.cli('gate-stop');self.assertEqual(0,cp.returncode);self.assertTrue(report.exists())
        self.assertFalse(gate_trace.status(state)['armed'])
    def test_unregistered_new_astra_and_reregister_luna_routing(self):
        receipt=self.inst.apply();state=Path(receipt['state']);ws=self.base/'project';ws.mkdir()
        a={'hook_event_name':'SessionStart','model':'gpt-6-astra','session_id':'astra','cwd':str(ws)}
        self.assertEqual({},self.hook(receipt,a));self.assertFalse(state.exists())
        cp=self.cli('unregister');self.assertEqual(0,cp.returncode,cp.stderr)
        self.assertFalse(self.inst.registration_status()['HOOKS_REGISTERED']);self.assertFalse(state.exists())
        # No hook invocation is possible through these removed definitions.
        receipt=self.inst.apply();self.assertEqual(9,self.inst.registration_status()['owned_handlers'])
        self.assertEqual({},self.hook(receipt,{**a,'session_id':'astra-2'}));self.assertFalse(state.exists())
        out=self.hook(receipt,{**a,'session_id':'luna','model':'gpt-5.6-luna'})
        self.assertIn('LUNASTRA_APPLICABILITY',out['hookSpecificOutput']['additionalContext'])
        self.assertIn('Use exactly six',out['hookSpecificOutput']['additionalContext'])
    def test_unregister_removes_only_owned_and_preserves_data(self):
        receipt=self.inst.apply();state=Path(receipt['state']);state.mkdir(parents=True);(state/'sentinel').write_bytes(b'v4-kept')
        old=self.home/'luna-astra'/'state-v3';old.mkdir();(old/'sentinel').write_bytes(b'v3-kept')
        gate_trace.enable(state,20,4)
        cp=self.cli('unregister',json_mode=False);self.assertEqual(0,cp.returncode,cp.stderr)
        self.assertIn('NOT RETRACTED',cp.stdout);self.assertIn('new conversation',cp.stdout)
        self.assertEqual(b'v4-kept',(state/'sentinel').read_bytes());self.assertEqual(b'v3-kept',(old/'sentinel').read_bytes())
        self.assertTrue(Path(receipt['release']).is_dir());self.assertFalse(gate_trace.status(state)['armed'])
        self.assertTrue(list(gate_trace.directory(state).glob('capture-*')))
        handlers=[h for groups in json.loads((self.home/'hooks.json').read_text())['hooks'].values() for g in groups for h in g['hooks']]
        self.assertEqual([self.foreign],handlers)
        self.assertEqual(self.original,{n:(self.home/n).read_bytes() for n in self.original})
    def test_reinstall_after_unregister_does_not_duplicate_handlers(self):
        self.inst.apply();self.inst.remove();self.inst.apply();self.inst.apply()
        self.assertEqual(9,self.inst.registration_status()['owned_handlers'])
        self.assertEqual(self.original,{n:(self.home/n).read_bytes() for n in self.original})
    def test_installed_false_positive_prompt_does_not_activate(self):
        receipt=self.inst.apply();e={'hook_event_name':'SessionStart','model':'gpt-6-astra','session_id':'negative',
                           'cwd':str(self.base/'nonexistent'),'prompt':'gpt-5.6-luna gpt-reserve Luna'}
        self.assertEqual({},self.hook(receipt,e));self.assertFalse(Path(receipt['state']).exists())
    def test_installed_malformed_and_unknown_models_inert(self):
        receipt=self.inst.apply()
        for model in (None,[],'gpt-reserve',123,'unknown'):
            self.assertEqual({},self.hook(receipt,{'hook_event_name':'SessionStart','model':model,
                                          'session_id':'fixture','cwd':str(self.base/'nonexistent')}))
        self.assertFalse(Path(receipt['state']).exists())
    def test_substring_fast_path_can_avoid_python_entirely(self):
        state=self.base/'not-created'/'state-v4'
        d=definition(self.base/'python-that-does-not-exist',self.base/'release',state,'SessionStart')['hooks'][0]
        cmd=d['commandWindows'] if os.name=='nt' else d['command']
        cp=subprocess.run(cmd,input='{"model":"other","hook_event_name":"SessionStart"}',text=True,capture_output=True,shell=True,timeout=20)
        self.assertEqual(0,cp.returncode,cp.stdout+cp.stderr);self.assertEqual({},json.loads(cp.stdout));self.assertFalse(state.exists())
    def test_windows_trace_command_is_literal_scoped_and_bounded(self):
        state=self.home/'luna-astra'/'state-v4';d=definition(Path(sys.executable),ROOT,state,'SessionStart')['hooks'][0]
        script=base64.b64decode(d['commandWindows'].split()[-1]).decode('utf-16-le')
        self.assertIn('[System.IO.File]::Exists(',script);self.assertNotIn('Test-Path',script);self.assertIn('--trace-model-gate',script)
        self.assertIn("''quote''",script);self.assertNotIn('Invoke-Expression',script)
        self.assertLess(len(d['commandWindows']),8000)
    def test_isolated_plan_is_readonly_and_does_not_inherit_default_home(self):
        fake=self.base/'fake-profile';fake.mkdir();default=fake/'.codex';default.mkdir();(default/'auth.json').write_text('private')
        env={**self.env,'HOME':str(fake),'USERPROFILE':str(fake),'CODEX_HOME':str(self.home)}
        cp=self.cli('plan','--isolated',home=False,env=env);self.assertEqual(0,cp.returncode,cp.stderr);r=json.loads(cp.stdout)
        self.assertEqual(str(fake/'.codex-lunastra'),r['codex_home']);self.assertFalse((fake/'.codex-lunastra').exists())
        self.assertIn('UNVERIFIED',r['home_mode']);self.assertEqual('private',(default/'auth.json').read_text())
    def test_isolated_apply_does_not_copy_credentials_or_change_default(self):
        fake=self.base/'fake-profile';fake.mkdir();default=fake/'.codex';default.mkdir()
        (default/'auth.json').write_text('private');(default/'hooks.json').write_text('{"hooks":{}}')
        env={**self.env,'HOME':str(fake),'USERPROFILE':str(fake),'CODEX_HOME':str(self.home)}
        before={p.name:p.read_bytes() for p in default.iterdir()}
        cp=self.cli('apply','--isolated',home=False,env=env);self.assertEqual(0,cp.returncode,cp.stderr)
        isolated=fake/'.codex-lunastra';self.assertTrue((isolated/'hooks.json').is_file())
        self.assertFalse((isolated/'auth.json').exists());self.assertFalse((isolated/'config.toml').exists())
        self.assertEqual(before,{p.name:p.read_bytes() for p in default.iterdir()})
        cp=self.cli('unregister','--isolated',home=False,env=env);self.assertEqual(0,cp.returncode,cp.stderr)
        self.assertEqual(before,{p.name:p.read_bytes() for p in default.iterdir()})
    def test_invalid_or_ignored_trace_flags_are_errors_without_registration(self):
        before=(self.home/'hooks.json').read_bytes()
        for args in (('plan','--trace-model-gate'),('doctor','--trace-seconds','20'),('apply','--trace-events','20')):
            cp=self.cli(*args);self.assertNotEqual(0,cp.returncode)
        self.assertEqual(before,(self.home/'hooks.json').read_bytes())
    def test_diagnostic_arm_does_not_change_registered_definitions(self):
        self.inst.apply();before=(self.home/'hooks.json').read_bytes()
        cp=self.cli('doctor','--trace-model-gate','--trace-seconds','20','--trace-events','4')
        self.assertEqual(0,cp.returncode,cp.stderr);self.assertTrue(json.loads(cp.stdout)['model_gate_trace']['armed'])
        self.assertEqual(before,(self.home/'hooks.json').read_bytes())
    def test_diagnostic_capture_remains_owned_but_active_purge_is_blocked(self):
        from luna_astra.removal import purge_plan
        receipt=self.inst.apply();state=Path(receipt['state']);gate_trace.enable(state,20,4)
        plan=purge_plan(self.inst)
        self.assertTrue(any('diagnostic' in b for b in plan['blockers']))
        gate_trace.disable(state);self.assertEqual([],purge_plan(self.inst)['blockers'])
    def test_explicit_idle_removal_handles_diagnostics_without_project_changes(self):
        from luna_astra.removal import purge,CONFIRMATION
        receipt=self.inst.apply();state=Path(receipt['state']);gate_trace.enable(state,20,4);gate_trace.disable(state)
        result=purge(self.inst,confirm=CONFIRMATION,confirm_idle=True)
        self.assertTrue(result['removed']);self.assertFalse((self.home/'luna-astra').exists())
        self.assertEqual(self.original,{n:(self.home/n).read_bytes() for n in self.original})
        self.assertIn('foreign-kept',(self.home/'hooks.json').read_text())
    def test_launcher_targets_and_no_model_switch_commands(self):
        expected={'CHECK_MODEL_GATE.cmd':'gate-trace','MODEL_GATE_REPORT.cmd':'gate-report','STOP_MODEL_GATE.cmd':'gate-stop',
                  'INSTALL_LUNA_HOME.cmd':'apply --isolated','CHECK_LUNA_HOME.cmd':'doctor --isolated','UNREGISTER_LUNA_HOME.cmd':'unregister --isolated'}
        for name,command in expected.items():
            raw=(ROOT/name).read_bytes();self.assertIn(b'\r\n',raw)
            self.assertIn(('install.py '+command+' %*').encode(),raw);self.assertNotIn(b'taskkill',raw.lower())
            self.assertNotIn(b'--model',raw);self.assertNotIn(b'reasoning_effort',raw)
