"""Failure-first checks for controller state and the actual delivered archive."""
import importlib.util
import json
import os
import shutil
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

from luna_astra.evidence import Evidence
from luna_astra.hooks import Hooks, identity
from luna_astra.jobs import Jobs
from luna_astra.store import Store
from luna_astra.util import HarnessError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_v32', ROOT / 'tools' / 'release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ControllerIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ws = self.base / 'repo'
        self.ws.mkdir()
        (self.ws / 'app.py').write_text('answer=2\n')
        self.state = self.base / 'state'
        self.event = dict(hook_event_name='SessionStart', model='gpt-5.6-luna',
                          session_id='root', cwd=str(self.ws), turn_id='t')
        self.hooks = Hooks(ROOT, self.state)
        self.hooks.handle(self.event)
        self.key = identity(self.event)[0]
        self.store = Store(self.state)
        self.jobs = Jobs(self.store, self.key, ROOT)

    def save_job(self, value):
        self.store.put(self.key, 'job:' + 'a' * 32, value)

    def test_unknown_controller_status_cannot_disappear(self):
        self.save_job(dict(id='a' * 32, check_id='test', task_hash='h', status='SUCESS'))
        with self.assertRaises(HarnessError):
            self.jobs.active()

    def test_non_object_controller_is_not_ignored(self):
        self.save_job([])
        with self.assertRaises(HarnessError):
            self.jobs.all()

    def test_finished_controller_requires_a_result(self):
        self.save_job(dict(id='a' * 32, check_id='test', task_hash='h', status='FINISHED'))
        with self.assertRaises(HarnessError):
            self.jobs.all()

    def test_corrupt_controller_produces_controlled_hook_failure(self):
        self.save_job(dict(id='a' * 32, check_id='test', task_hash='h', status='SUCESS'))
        event = {**self.event, 'hook_event_name': 'Stop', 'last_assistant_message': 'done'}
        result = subprocess.run([sys.executable, str(ROOT / 'luna.py'), '--state',
                                 str(self.state), 'hook'], input=json.dumps(event),
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['continue'])
        self.assertNotIn('Traceback', result.stderr)

    def test_stale_partial_record_is_not_valid_handback(self):
        ev = Evidence(self.state / 'sessions' / self.key, self.ws)
        task = dict(task_id='task', design='Keep behavior', requirements=['answer=2'],
                    allowed_paths=['app.py'], checks=[dict(id='check', purpose='behavior',
                    argv=[sys.executable, '-c', 'print(2)'], dependencies=['app.py'], covers=[0])])
        ev.begin(task)
        ev.finish('partial', 'Changed app', 'Review performed', 'Execution unavailable')
        with ev._transaction() as db:
            finish = ev._get(db, 'finish')
            finish['task_hash'] = 'wrong'
            ev._set(db, 'finish', finish)
        self.store.put(self.key, 'finish_generation', 't')
        (self.ws / 'app.py').write_text('answer=3\n')
        out = self.hooks.handle({**self.event, 'hook_event_name': 'Stop',
                                 'last_assistant_message': 'done'})
        self.assertEqual(out['decision'], 'block')


    def test_bad_install_ownership_never_overwrites_hooks(self):
        from luna_astra.install import Installer
        from luna_astra.util import write_json
        home=self.base/'codex';(home/'luna-astra').mkdir(parents=True)
        original=b'{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"original"}]}]}}'
        (home/'hooks.json').write_bytes(original)
        write_json(home/'luna-astra'/'installation.json',{'version':'3.1.0','owned_handlers':[]})
        with self.assertRaises(HarnessError):Installer(ROOT,home).apply()
        self.assertEqual((home/'hooks.json').read_bytes(),original)

    def test_corrupt_doctor_metadata_has_controlled_exit(self):
        from luna_astra.install import Installer
        home=self.base/'codex';receipt=Installer(ROOT,home).apply()
        store=Store(Path(receipt['state']));store.put('invalid','meta',[])
        result=subprocess.run([sys.executable,str(ROOT/'install.py'),'doctor','--json','--codex-home',str(home)],text=True,capture_output=True,timeout=20)
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('Traceback',result.stderr)
        self.assertEqual(json.loads(result.stdout)['runtime']['status'],'DIAGNOSTICS_UNREADABLE')


class ArchiveIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.good = cls.root / 'good.zip'
        release.build(cls.good)
        with zipfile.ZipFile(cls.good) as z:
            cls.data = {n: z.read(n) for n in z.namelist()}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def mutated(self, label, changes=None, symlink=None):
        path = self.root / (label + '.zip')
        data = {**self.data, **(changes or {})}
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, value in data.items():
                info = zipfile.ZipInfo(name)
                info.external_attr = ((stat.S_IFLNK | 0o777) if name == symlink else (stat.S_IFREG | 0o644)) << 16
                z.writestr(info, value)
        return path

    @unittest.skipUnless(shutil.which('git'), 'Git required for source-byte preservation')
    def test_git_stores_exact_public_source_bytes(self):
        files=release.collect(ROOT)
        with tempfile.TemporaryDirectory(prefix='source-byte-check-') as t:
            repo=Path(t)
            for name,raw in files.items():
                path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            def git(*args):
                return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True).stdout
            git('init','-q')
            git('-c','core.autocrlf=true','add','-A')
            tracked={n.decode('utf-8') for n in git('ls-files','-z').split(b'\0') if n}
            self.assertEqual(tracked,set(files))
            checkout=repo/'checked-out'
            checkout.mkdir()
            git('checkout-index','--all','--force','--prefix='+checkout.as_posix()+'/')
            for name,raw in files.items():
                with self.subTest(path=name):
                    indexed=git('show',':'+name)
                    # Git stores canonical LF for text; CMD checkouts/distributions
                    # must still contain exactly the CRLF bytes we certified.
                    expected=raw.replace(b'\r\n',b'\n') if name.lower().endswith('.cmd') else raw
                    self.assertEqual(indexed,expected)
                    self.assertEqual(release.distribution_bytes(name,indexed),raw)
                    self.assertEqual((checkout/name).read_bytes(),raw)
            git('diff','--cached','--check')
            # Intentional CRLF is valid, actual trailing spaces must still fail.
            (repo/'INVALID.cmd').write_bytes(b'@echo off   \r\n')
            git('add','--','INVALID.cmd')
            bad=subprocess.run(['git','-C',str(repo),'diff','--cached','--check'],capture_output=True)
            self.assertNotEqual(bad.returncode,0)

    def test_same_source_produces_byte_identical_archives(self):
        other = self.root / 'same.zip'
        release.build(other)
        self.assertEqual(self.good.read_bytes(), other.read_bytes())

    def test_version_in_manifest_cannot_lie(self):
        name = 'LunAstra/MANIFEST.sha256.json'
        manifest = json.loads(self.data[name]); manifest['version'] = '999.0.0'
        with self.assertRaises(ValueError):
            release.verify(self.mutated('version', {name: json.dumps(manifest).encode()}))

    def test_manifest_duplicate_keys_rejected(self):
        name = 'LunAstra/MANIFEST.sha256.json'
        raw = self.data[name].decode().replace('"format": 1,', '"format": 1, "format": 1,')
        with self.assertRaises(ValueError):
            release.verify(self.mutated('duplicate-json', {name: raw.encode()}))

    def test_source_symlinks_in_zip_rejected(self):
        with self.assertRaises(ValueError):
            release.verify(self.mutated('symlink', symlink='LunAstra/luna.py'))

    def test_unsafe_windows_stream_name_rejected(self):
        with self.assertRaises(ValueError):
            release.verify(self.mutated('stream', {'LunAstra/luna.py:extra': b'bad'}))

    def test_case_colliding_members_rejected(self):
        with self.assertRaises(ValueError):
            release.verify(self.mutated('case-collision', {'LunAstra/LUNA.py': b'bad'}))

    def test_invalid_manifest_is_controlled_cli_failure(self):
        name = 'LunAstra/MANIFEST.sha256.json'
        archive = self.mutated('bad-manifest', {name: b'null'})
        result = subprocess.run([sys.executable, str(ROOT / 'tools' / 'release.py'), '--verify',
                                 str(archive)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
