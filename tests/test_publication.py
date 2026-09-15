"""Public-installation and release-boundary regressions; no model calls."""
from __future__ import annotations

import copy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from jsonschema import Draft7Validator
from luna_astra.compatibility import version_status, inspect_host, configuration_hints
from luna_astra.install import Installer
from luna_astra.removal import purge_plan, purge, CONFIRMATION
from luna_astra.hooks import Hooks, identity
from luna_astra.store import Store
from luna_astra.team import Team
from luna_astra.transport import helper_command
from luna_astra.evidence import Evidence
from luna_astra.util import HarnessError, load_json, write_json
from tools import release

ROOT = Path(__file__).resolve().parents[1]


class HostChecks(unittest.TestCase):
    def test_stable_baseline(self):
        self.assertEqual(version_status('codex-cli 0.154.0')['status'], 'REVIEWED')

    def test_older_cli_is_advisory_not_an_installation_gate(self):
        for text in ('codex-cli 0.153.9', 'codex 0.152.0'):
            with self.subTest(text=text):
                self.assertEqual(version_status(text)['status'], 'UNREVIEWED')

    def test_newer_is_not_silently_certified(self):
        self.assertEqual(version_status('codex-cli 0.155.0')['status'], 'UNREVIEWED')

    def test_preview_is_distinct(self):
        self.assertEqual(version_status('codex-cli 0.155.0-alpha.1')['status'], 'PREVIEW')

    def test_build_metadata_is_not_a_prerelease(self):
        self.assertEqual(version_status('codex-cli 0.154.0+vendor')['status'], 'REVIEWED')

    def test_unknown_is_not_a_pass(self):
        for text in ('', 'not codex 0.154.0', 'codex-cli 0.154.0\nother version'):
            self.assertEqual(version_status(text)['status'], 'UNKNOWN')

    def test_no_cli_desktop_is_unknown(self):
        with patch('luna_astra.compatibility.shutil.which', return_value=None):
            result = inspect_host()
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertFalse(result['live_verified'])

    def test_read_only_probe_arguments(self):
        with patch('luna_astra.compatibility.subprocess.run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, 'codex-cli 0.154.0\n', '')
            self.assertEqual(inspect_host('/example/codex')['status'], 'REVIEWED')
            args, kwargs = run.call_args
            self.assertEqual(args[0][-1], '--version')
            self.assertFalse(kwargs['shell'])

    def test_probe_failure(self):
        with patch('luna_astra.compatibility.subprocess.run', side_effect=OSError('fixture failure')):
            self.assertEqual(inspect_host('/example/codex')['status'], 'UNKNOWN')

    def test_v2_disabled_does_not_disable_v1(self):
        if sys.version_info < (3, 11):
            # This version explicitly reports absent TOML inspection.
            with tempfile.TemporaryDirectory() as d:
                home=Path(d); (home/'config.toml').write_text('[features]\nmulti_agent_v2 = false\n')
                self.assertEqual(configuration_hints(home)['config_parse'], 'NOT_INSPECTED_PYTHON_310')
            return
        with tempfile.TemporaryDirectory() as d:
            home=Path(d); (home/'config.toml').write_text('[features]\nmulti_agent_v2 = false\n')
            result=configuration_hints(home)
            self.assertEqual(result['native_agent_setting'], 'NO_EXPLICIT_DISABLE')

    def test_current_keys_override_legacy_keys(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d); (home/'config.toml').write_text('[features]\nhooks = true\ncodex_hooks = false\nmulti_agent = true\ncollab = false\n')
            result=configuration_hints(home)
            self.assertFalse(result['hooks_explicitly_disabled'])
            self.assertNotEqual(result['native_agent_setting'], 'EXPLICITLY_DISABLED')

    def test_old_path_cli_does_not_block_apply(self):
        spec=importlib.util.spec_from_file_location('lunastra_install_public_test', ROOT/'install.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d, patch.object(module, 'inspect_host', return_value={'status':'UNREVIEWED','message':'old PATH CLI (advisory)'}):
            home=Path(d)/'not-created'
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code=module.main(['apply','--codex-home',str(home),'--json'])
            self.assertEqual(code,0)
            self.assertTrue((home/'hooks.json').is_file())


    def _doctor_output_for_config_state(self, state):
        spec=importlib.util.spec_from_file_location('lunastra_human_test',ROOT/'install.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        result={'payload_sha256':'0'*64, 'installed_payload_matches_package':True,
                'hook_definition_matches_package':True, 'runtime':{'sessions':[]},
                'configuration':{'config_parse':state,'native_agent_setting':'NOT_INSPECTED','git_found':True}}
        output=io.StringIO()
        with redirect_stdout(output): module.human('doctor', result)
        return output.getvalue()

    def test_human_doctor_reports_unavailable_toml_inspection(self):
        output=self._doctor_output_for_config_state('NOT_INSPECTED_PYTHON_310')
        self.assertIn('cannot inspect TOML',output)
        self.assertIn('Confirm hook and agent availability',output)

    def test_human_doctor_reports_unreadable_toml(self):
        output=self._doctor_output_for_config_state('UNREADABLE')
        self.assertIn('could not be parsed',output)
        self.assertIn('unconfirmed',output)


class RemovalChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name); self.home=self.base/'home'; self.home.mkdir()
        self.project=self.base/'project'; self.project.mkdir(); (self.project/'keep.txt').write_text('keep')
        for name in ('config.toml','auth.json','AGENTS.md'):
            (self.home/name).write_text('preserve '+name)
        write_json(self.home/'hooks.json', {'hooks':{'Stop':[{'hooks':[{'type':'command','command':'echo fixture'}]}]}})
        self.inst=Installer(ROOT,self.home); self.receipt=self.inst.apply()
        self.original={name:(self.home/name).read_bytes() for name in ('config.toml','auth.json','AGENTS.md')}

    def remove(self, **kwargs):
        return purge(self.inst, confirm=CONFIRMATION, confirm_idle=True, **kwargs)

    def test_plan_is_read_only(self):
        before={str(p):p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        result=purge_plan(self.inst)
        self.assertTrue(result['exists'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_confirmation_is_required(self):
        with self.assertRaises(HarnessError): purge(self.inst)
        with self.assertRaises(HarnessError): purge(self.inst,confirm=CONFIRMATION)
        self.assertTrue(Path(self.receipt['release']).is_dir())

    def test_owned_data_removed_external_files_preserved(self):
        result=self.remove()
        self.assertTrue(result['removed']); self.assertFalse((self.home/'luna-astra').exists())
        self.assertEqual(self.original,{name:(self.home/name).read_bytes() for name in self.original})
        self.assertEqual((self.project/'keep.txt').read_text(),'keep')
        self.assertEqual(load_json(self.home/'hooks.json'),{'hooks':{'Stop':[{'hooks':[{'type':'command','command':'echo fixture'}]}]}})

    def test_repeated_purge_is_safe(self):
        self.remove(); self.assertFalse(self.remove()['removed'])

    def test_unregistered_data_can_be_removed(self):
        self.inst.remove(); self.assertTrue(self.remove()['removed'])

    def test_missing_receipt_refused(self):
        (self.home/'luna-astra'/'installation.json').unlink()
        with self.assertRaises(HarnessError): self.remove()

    def test_modified_hook_refused(self):
        hooks=load_json(self.home/'hooks.json'); hooks['hooks']['Stop'][-1]['hooks'][0]['command']='echo locally-modified'
        write_json(self.home/'hooks.json',hooks)
        with self.assertRaises(HarnessError): self.remove()
        self.assertEqual(load_json(self.home/'hooks.json'),hooks)

    def test_external_receipt_target_refused(self):
        receipt=load_json(self.home/'luna-astra'/'installation.json'); receipt['state']=str(self.project)
        write_json(self.home/'luna-astra'/'installation.json',receipt)
        with self.assertRaises(HarnessError): self.remove()
        self.assertTrue((self.project/'keep.txt').is_file())

    def test_unknown_top_level_data_refused(self):
        (self.home/'luna-astra'/'unexpected-project').mkdir()
        with self.assertRaises(HarnessError): self.remove()

    def test_active_job_refused(self):
        store=Store(Path(self.receipt['state'])); store.put('session','job:fixture',{'id':'a'*32,'check_id':'c','task_hash':'h','status':'RUNNING'})
        self.assertIn('an active or unknown check controller',purge_plan(self.inst)['blockers'])
        with self.assertRaises(HarnessError): self.remove()

    def test_unfinished_check_refused(self):
        ev=Evidence(Path(self.receipt['state'])/'sessions'/'test',self.project)
        with ev._db() as db:
            db.execute("INSERT INTO attempts(check_id,task_hash,spec_hash,status,started) VALUES('x','x','x','RUNNING',0)")
        with self.assertRaises(HarnessError): self.remove()

    def test_corrupt_job_is_not_treated_as_finished(self):
        Store(Path(self.receipt['state'])).put('session','job:fixture',{'status':'FINISHED'})
        with self.assertRaises(HarnessError): self.remove()

    def test_custom_hook_reference_preserved(self):
        hooks=load_json(self.home/'hooks.json')
        hooks['hooks']['Stop'].append({'hooks':[{'type':'command','command':str(Path(self.receipt['release'])/'luna.py')+' help'}]})
        write_json(self.home/'hooks.json',hooks)
        with self.assertRaises(HarnessError): self.remove()
        self.assertTrue(Path(self.receipt['release']).is_dir())

    def test_completed_database_handles_are_closed(self):
        store=Store(Path(self.receipt['state'])); store.put('session','job:fixture',{'id':'a'*32,'check_id':'c','task_hash':'h','status':'FINISHED','result':{}})
        self.assertTrue(self.remove()['removed'])

    def test_workspaces_require_separate_consent(self):
        tree=Path(self.receipt['state'])/'worktrees'/'a'/'tree'; tree.mkdir(parents=True); (tree/'patch.txt').write_text('private copy')
        self.assertEqual(purge_plan(self.inst)['workspaces'],1)
        with self.assertRaises(HarnessError): self.remove()
        self.assertTrue(self.remove(include_workspaces=True)['removed'])
        self.assertTrue((self.project/'keep.txt').exists())

    def test_symlink_refused_without_touching_target(self):
        path=self.home/'luna-astra'/'backups'/'link'; path.parent.mkdir(exist_ok=True)
        path.symlink_to(self.project,target_is_directory=True)
        with self.assertRaises(HarnessError): self.remove()
        self.assertEqual((self.project/'keep.txt').read_text(),'keep')

    def test_install_lock_is_never_broken(self):
        lock=self.home/'luna-astra'/'install.lock'; lock.write_text('another installer')
        with self.assertRaises(HarnessError): self.remove()
        self.assertEqual(lock.read_text(),'another installer')

    def test_partial_removal_retains_receipt_for_retry(self):
        with patch('luna_astra.removal.shutil.rmtree',side_effect=OSError('fixture disk error')):
            with self.assertRaises(OSError): self.remove()
        self.assertTrue((self.home/'luna-astra'/'installation.json').exists())
        self.assertTrue(self.remove()['removed'])


class StableFallbackChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name); self.ws=self.base/'project'; self.ws.mkdir(); (self.ws/'a.py').write_text('x=1\n')
        self.state=self.base/'state'; self.hooks=Hooks(ROOT,self.state); self.store=Store(self.state)
        self.root=dict(hook_event_name='SessionStart',session_id='parent',cwd=str(self.ws),model='gpt-5.6-luna',turn_id='p',permission_mode='default',transcript_path=None)
        self.hooks.handle(self.root); self.owner=identity(self.root)[0]; self.team=Team(self.store)
        self.team.plan(self.owner,self.ws,dict(goal='inspect',tasks=[dict(id='review',kind='investigate',description='Review a.py',paths=['a.py'],depends_on=[],done_when=['return findings'],why_parallel='independent inspection')]))
        self.ticket=self.team.reserve(self.owner)['reserved'][0]['ticket']
        self.spawn={**self.root,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v1spawn_agent','tool_use_id':'s', 'tool_input':{'fork_context':True,'message':'LUNASTRA_TICKET='+self.ticket}}
        self.hooks.handle(self.spawn)
        self.child={**self.root,'session_id':'child','agent_id':'child','agent_type':'default','turn_id':'c','hook_event_name':'UserPromptSubmit','prompt':'LUNASTRA_TICKET='+self.ticket}
        self.key=identity(self.child)[0]

    def observed(self, agent='child'):
        self.hooks.handle({**self.spawn,'hook_event_name':'PostToolUse','tool_response':json.dumps({'agent_id':agent})})

    def test_prompt_fallback_matches_official_stable_schema(self):
        schema=json.loads((ROOT/'tests/codex_contract/user-prompt-submit.command.input.schema.json').read_text())
        Draft7Validator(schema).validate(self.child)

    def test_stable_schema_is_exact_upstream_blob(self):
        raw=(ROOT/'tests/codex_contract/user-prompt-submit.command.input.schema.json').read_bytes()
        blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        self.assertEqual(blob,'6a10a9f75c19720b0863d11d7d7d80f190e8eacd')

    def test_missing_start_initializes_worker_kernel(self):
        output=self.hooks.handle(self.child)
        self.assertIn('Role: delegated Luna worker',output['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.store.get(self.key,'meta')['role'],'worker')

    def test_missing_start_join_and_following_tool(self):
        self.observed(); self.hooks.handle(self.child)
        self.team.join(self.key,self.ticket,self.store.get(self.key,'meta'))
        prefix=[sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--session',self.key]
        output=self.hooks.handle({**self.child,'hook_event_name':'PreToolUse','tool_name':'Bash','tool_use_id':'read','tool_input':{'command':helper_command(prefix+['read','a.py'])}})
        self.assertNotEqual(output.get('hookSpecificOutput',{}).get('permissionDecision'),'deny')
        self.assertEqual(self.store.get(self.key,'meta')['parent_session_id'],'parent')

    def test_missing_start_does_not_guess_parent(self):
        self.hooks.handle(self.child)
        with self.assertRaisesRegex(HarnessError,'not registered yet'):
            self.team.join(self.key,self.ticket,self.store.get(self.key,'meta'))
        self.observed(); self.team.join(self.key,self.ticket,self.store.get(self.key,'meta'))

    def test_missing_start_still_refuses_foreign_child(self):
        self.observed('other-child'); self.hooks.handle(self.child)
        with self.assertRaisesRegex(HarnessError,'another agent'):
            self.team.join(self.key,self.ticket,self.store.get(self.key,'meta'))

    def test_tool_first_fallback_remains_guarded(self):
        child={k:v for k,v in self.child.items() if k!='prompt'}
        output=self.hooks.handle({**child,'hook_event_name':'PreToolUse','tool_name':'Bash','tool_use_id':'first','tool_input':{'command':'echo raw'}})
        self.assertEqual(output['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertEqual(self.store.get(self.key,'meta')['role'],'worker')


class PublicArchiveChecks(unittest.TestCase):
    def test_manifest_not_in_repository_source(self):
        self.assertNotIn('MANIFEST.sha256.json',release.collect())
        self.assertIn('/MANIFEST.sha256.json',(ROOT/'.gitignore').read_text())

    def test_source_and_release_have_identical_payloads(self):
        with tempfile.TemporaryDirectory() as d:
            a,b=Path(d)/'source.zip',Path(d)/'release.zip'
            release.build_source(a); release.build(b)
            with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
                left={n:za.read(n) for n in za.namelist()}
                right={n:zb.read(n) for n in zb.namelist() if not n.endswith('/MANIFEST.sha256.json')}
                self.assertEqual(left,right)

    def test_recomputed_manifest_does_not_hide_private_files(self):
        with tempfile.TemporaryDirectory() as d:
            good,bad=Path(d)/'good.zip',Path(d)/'bad.zip'; release.build(good)
            with zipfile.ZipFile(good) as z: values={n:z.read(n) for n in z.namelist()}
            name='LunAstra/tests/state-v3/private.json'; values[name]=b'{}'
            m=json.loads(values['LunAstra/MANIFEST.sha256.json']); m['files'][name.removeprefix('LunAstra/')]=hashlib.sha256(b'{}').hexdigest()
            values['LunAstra/MANIFEST.sha256.json']=json.dumps(m).encode()
            with zipfile.ZipFile(bad,'w') as z:
                for n,raw in values.items(): z.writestr(n,raw)
            with self.assertRaisesRegex(ValueError,'private/runtime'):
                release.verify(bad)

    def test_recomputed_manifest_does_not_hide_credential(self):
        with tempfile.TemporaryDirectory() as d:
            good,bad=Path(d)/'good.zip',Path(d)/'bad.zip'; release.build(good)
            with zipfile.ZipFile(good) as z: values={n:z.read(n) for n in z.namelist()}
            name='LunAstra/docs/fixture.md'; raw=('github_'+'pat_'+'A'*50).encode(); values[name]=raw
            m=json.loads(values['LunAstra/MANIFEST.sha256.json']); m['files'][name.removeprefix('LunAstra/')]=hashlib.sha256(raw).hexdigest()
            values['LunAstra/MANIFEST.sha256.json']=json.dumps(m).encode()
            with zipfile.ZipFile(bad,'w') as z:
                for n,raw in values.items(): z.writestr(n,raw)
            with self.assertRaisesRegex(ValueError,'credential'):
                release.verify(bad)

    def test_windows_reserved_filenames_refused(self):
        for name in ('docs/CON.md','docs/aux.txt','docs/trailing. /a.md'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.validate_files({**release.collect(),name:b'synthetic'})

    def test_public_docs_links_resolve(self):
        release.check_links(release.collect())

    def test_source_zip_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'source.zip'; path.write_bytes(b'preserve')
            with self.assertRaises(ValueError): release.build_source(path)
            self.assertEqual(path.read_bytes(),b'preserve')


class ValidatorChecks(unittest.TestCase):
    def run_fixture(self, body):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); tree=base/'src'; (tree/'tools').mkdir(parents=True); (tree/'tests').mkdir()
            (tree/'tools'/'validate.py').write_bytes((ROOT/'tools'/'validate.py').read_bytes())
            (tree/'tests'/'test_fixture.py').write_text(body)
            result=subprocess.run([sys.executable,str(tree/'tools'/'validate.py'),'--output',str(base/'out')],capture_output=True,text=True)
            return result.returncode,json.loads((base/'out'/'result.json').read_text())

    def test_zero_tests_is_not_success(self):
        code,result=self.run_fixture('')
        self.assertNotEqual(code,0); self.assertFalse(result['successful'])

    def test_skipped_test_is_not_release_success(self):
        code,result=self.run_fixture("import unittest\nclass T(unittest.TestCase):\n @unittest.skip('fixture')\n def test_x(self): pass\n")
        self.assertNotEqual(code,0); self.assertEqual(result['skipped'],1)

    def test_expected_failure_is_not_release_success(self):
        code,result=self.run_fixture("import unittest\nclass T(unittest.TestCase):\n @unittest.expectedFailure\n def test_x(self): self.fail('fixture')\n")
        self.assertNotEqual(code,0); self.assertEqual(result['expected_failures'],1)

    def test_normal_success(self):
        code,result=self.run_fixture("import unittest\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(1,1)\n")
        self.assertEqual(code,0); self.assertTrue(result['successful'])
