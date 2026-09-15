"""Independent maintenance regressions; no model calls or user configuration."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from luna_astra.gitspace import Workspaces
from luna_astra.hooks import Hooks, identity
from luna_astra.store import Store
from luna_astra.util import HarnessError, json_hash

ROOT = Path(__file__).resolve().parents[1]

class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'repo'
        self.root.mkdir()
        (self.root / 'nested').mkdir()
        self.spaces = Workspaces(self.base / 'trees')
        self.spaces.directory.mkdir()

    def alias(self):
        return self.root / 'nested' / '..'

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def test_alias_cannot_acquire_same_root_lock(self):
        with self.spaces._lock(self.root):
            with self.assertRaises(HarnessError):
                with self.spaces._lock(self.alias()):
                    self.fail('equivalent root acquired a second lock')
            self.assertEqual(len(list(self.spaces.directory.glob('merge-*.lock'))), 1)
        self.assertEqual(list(self.spaces.directory.glob('merge-*.lock')), [])

    def test_reverse_alias_cannot_acquire_same_root_lock(self):
        with self.spaces._lock(self.alias()):
            with self.assertRaises(HarnessError):
                with self.spaces._lock(self.root):
                    self.fail('canonical root acquired a second lock')

    def test_distinct_roots_can_hold_distinct_locks(self):
        other = self.base / 'other'
        other.mkdir()
        with self.spaces._lock(self.root), self.spaces._lock(other):
            self.assertEqual(len(list(self.spaces.directory.glob('merge-*.lock'))), 2)

    def test_lock_releases_own_file_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
            with self.spaces._lock(self.root):
                raise RuntimeError('fixture failure')
        with self.spaces._lock(self.root):
            self.assertEqual(len(list(self.spaces.directory.glob('merge-*.lock'))), 1)

    def test_platform_canonical_lock_name(self):
        if os.name == 'nt':
            with self.spaces._lock(self.root):
                with self.assertRaises(HarnessError):
                    with self.spaces._lock(Path(str(self.root).upper())):
                        self.fail('case alias acquired a second Windows lock')
        else:
            with self.spaces._lock(self.alias()):
                expected = self.spaces.directory/('merge-'+json_hash(str(self.root))+'.lock')
                self.assertTrue(expected.is_file())

    def test_alias_lock_blocks_real_integration_and_preserves_work(self):
        self.git('init', '-q')
        self.git('config', 'user.name', 'Maintenance fixture')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        (self.root/'a.py').write_text('value = 1\n', encoding='utf-8')
        self.git('add', 'a.py'); self.git('commit', '-qm', 'fixture')
        ticket = 'c'*32
        info = self.spaces.prepare(ticket, self.root, ['a.py'])
        tree = Path(info['tree'])
        (tree/'a.py').write_text('value = 2\n', encoding='utf-8')
        with self.spaces._lock(self.alias()):
            with self.assertRaises(HarnessError):
                self.spaces.integrate(ticket)
            self.assertEqual((self.root/'a.py').read_text(), 'value = 1\n')
            self.assertEqual((tree/'a.py').read_text(), 'value = 2\n')
        self.spaces.integrate(ticket)
        self.assertEqual((self.root/'a.py').read_text(), 'value = 2\n')

    def test_symlink_root_is_rejected_before_resolution(self):
        link = self.base/'linked-root'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(HarnessError, 'symlink|junction'):
            self.spaces.prepare('d'*32, link, ['a.py'])

    def test_plain_luna_prompt_activates_fixed_seven(self):
        state = self.base/'state'
        event = {'session_id':'new-root', 'model':'gpt-5.6-luna', 'cwd':str(self.root),
                 'turn_id':'one', 'hook_event_name':'UserPromptSubmit', 'prompt':'Read the local file.'}
        result = Hooks(ROOT, state, fixed_seven=True).handle(event)
        key = identity(event)[0]
        self.assertTrue(Store(state).get(key, 'meta')['crew_enabled'])
        self.assertIn('Fixed seven', result['hookSpecificOutput']['additionalContext'])
        self.assertEqual(Store(state).get(key, 'request_hash'), json_hash(event['prompt']))

    def test_astra_prompt_does_not_create_lunastra_state(self):
        state = self.base/'never-created'
        event = {'session_id':'astra', 'model':'gpt-6-astra', 'cwd':str(self.root),
                 'turn_id':'one', 'hook_event_name':'UserPromptSubmit', 'prompt':'Read the local file.'}
        self.assertEqual(Hooks(ROOT, state, fixed_seven=True).handle(event), {})
        self.assertFalse(state.exists())


    def test_validation_temp_alias_is_canonical_in_parent_and_child(self):
        from unittest.mock import patch
        from tools.validate import canonical_test_temp
        alias = self.base/'temporary-alias'
        alias.symlink_to(self.base, target_is_directory=True)
        env = {key: str(alias) for key in ('TMPDIR', 'TMP', 'TEMP')}
        with patch.object(tempfile, 'tempdir', str(alias)), patch.dict(os.environ, env):
            with canonical_test_temp():
                self.assertEqual(tempfile.gettempdir(), str(self.base))
                for key in env:
                    self.assertEqual(os.environ[key], str(self.base))
                with tempfile.TemporaryDirectory() as d:
                    self.assertEqual(Path(d), Path(d).resolve())
                import sys
                child = subprocess.run([sys.executable, '-c',
                    'import tempfile; print(tempfile.gettempdir())'],
                    capture_output=True, text=True, check=True)
                self.assertEqual(child.stdout.strip(), str(self.base))
            self.assertEqual(tempfile.tempdir, str(alias))
            self.assertTrue(all(os.environ[key] == str(alias) for key in env))

    def test_validation_temp_restores_state_after_exception(self):
        from unittest.mock import patch
        from tools.validate import canonical_test_temp
        with patch.dict(os.environ):
            for key in ('TMPDIR', 'TMP', 'TEMP'):
                os.environ.pop(key, None)
            with patch.object(tempfile, 'tempdir', str(self.base)):
                before = dict(os.environ)
                with self.assertRaisesRegex(RuntimeError, 'fixture interruption'):
                    with canonical_test_temp():
                        raise RuntimeError('fixture interruption')
                self.assertEqual(os.environ, before)
                self.assertEqual(tempfile.tempdir, str(self.base))

    def test_validation_temp_preserves_canonical_root(self):
        from unittest.mock import patch
        from tools.validate import canonical_test_temp
        with patch.object(tempfile, 'tempdir', str(self.base)):
            before = dict(os.environ)
            with canonical_test_temp():
                self.assertEqual(tempfile.tempdir, str(self.base))
            self.assertEqual(os.environ, before)


    def test_database_setup_failure_closes_connection(self):
        import sqlite3
        from unittest.mock import MagicMock, patch
        from luna_astra.evidence import Evidence
        for cls, method, statements in ((Evidence, '_db', 2), (Store, 'db', 1)):
            for failed_step in range(statements):
                with self.subTest(owner=cls.__name__, failed_step=failed_step):
                    owner=object.__new__(cls);owner.path=self.base/'unused.sqlite3'
                    db=MagicMock()
                    db.execute.side_effect=[None]*failed_step+[sqlite3.DatabaseError('setup failure')]
                    with patch('sqlite3.connect', return_value=db):
                        with self.assertRaisesRegex(sqlite3.DatabaseError, 'setup failure'):
                            with getattr(owner, method)():
                                self.fail('failed setup yielded a connection')
                    db.close.assert_called_once_with()

    def test_corrupt_database_closes_real_handle_without_gc(self):
        import sqlite3
        from unittest.mock import patch
        from luna_astra.evidence import Evidence
        real_connect=sqlite3.connect
        opened=[]
        class TrackingConnection(sqlite3.Connection):
            closed=False
            def close(self):
                self.closed=True
                return super().close()
        def connect(*args, **kwargs):
            db=real_connect(*args, factory=TrackingConnection, **kwargs)
            opened.append(db)
            self.addCleanup(db.close)
            return db
        for cls, filename in ((Evidence,'evidence.sqlite3'),(Store,'runtime.sqlite3')):
            with self.subTest(owner=cls.__name__):
                directory=self.base/cls.__name__;directory.mkdir()
                path=directory/filename;path.write_bytes(b'broken database')
                with patch('sqlite3.connect', side_effect=connect):
                    with self.assertRaises(sqlite3.DatabaseError):
                        cls(directory, self.root) if cls is Evidence else cls(directory)
                self.assertTrue(opened[-1].closed)
                with self.assertRaises(sqlite3.ProgrammingError):
                    opened[-1].execute('SELECT 1')
                self.assertEqual(path.read_bytes(), b'broken database')
                path.unlink()
                self.assertFalse(path.exists())

    def test_database_body_exception_closes_real_handle(self):
        import sqlite3
        from luna_astra.evidence import Evidence
        for cls, method in ((Evidence, '_db'), (Store, 'db')):
            with self.subTest(owner=cls.__name__):
                owner=object.__new__(cls);owner.path=self.base/(cls.__name__+'-body.sqlite3')
                with self.assertRaisesRegex(RuntimeError, 'body failure'):
                    with getattr(owner, method)() as db:
                        db.execute('CREATE TABLE fixture(value INTEGER)')
                        raise RuntimeError('body failure')
                with self.assertRaises(sqlite3.ProgrammingError):
                    db.execute('SELECT 1')
                owner.path.unlink()

if __name__ == '__main__':
    unittest.main()
