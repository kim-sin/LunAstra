import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from luna_astra.gitspace import Workspaces
from luna_astra.util import HarnessError

@unittest.skipUnless(shutil.which('git'),'Git is required for isolated-workspace tests')
class WorkspacesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.root=self.base/'repo';self.root.mkdir();self.git('init','-q');self.git('config','user.name','Test Author');self.git('config','user.email','test@example.invalid')
        (self.root/'a.py').write_text('answer = 1\n');(self.root/'b.py').write_text('value = 2\n')
        self.git('add','a.py','b.py');self.git('commit','-qm','fixture')
        self.spaces=Workspaces(self.base/'state'/'trees');self.ticket='a'*32
    def git(self,*args):
        r=subprocess.run(['git','-C',str(self.root),*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True);return r.stdout
    def prepare(self):return self.spaces.prepare(self.ticket,self.root,['a.py'])
    def test_detached_workspace_has_same_baseline(self):
        info=self.prepare();tree=Path(info['tree'])
        self.assertEqual((tree/'a.py').read_bytes(),(self.root/'a.py').read_bytes())
        r=subprocess.run(['git','-C',str(tree),'symbolic-ref','-q','HEAD'],capture_output=True);self.assertNotEqual(r.returncode,0)
    def test_existing_workspace_is_reused(self):
        a=self.prepare();b=self.prepare();self.assertEqual(a,b)
    def test_dirty_root_never_stashed_or_reset(self):
        (self.root/'a.py').write_text('user work\n')
        with self.assertRaises(HarnessError):self.prepare()
        self.assertEqual((self.root/'a.py').read_text(),'user work\n')
    def test_untracked_root_never_omitted(self):
        (self.root/'untracked.py').write_text('important\n')
        with self.assertRaises(HarnessError):self.prepare()
        self.assertTrue((self.root/'untracked.py').exists())
    def test_only_owned_change_integrates(self):
        info=self.prepare();(Path(info['tree'])/'a.py').write_text('answer = 3\n')
        result=self.spaces.integrate(self.ticket)
        self.assertTrue(result['integrated']);self.assertEqual(result['changed_paths'],['a.py'])
        self.assertEqual((self.root/'a.py').read_text(),'answer = 3\n');self.assertEqual((self.root/'b.py').read_text(),'value = 2\n')
    def test_user_edit_after_prepare_blocks_integration(self):
        info=self.prepare();(Path(info['tree'])/'a.py').write_text('candidate\n');(self.root/'a.py').write_text('user edit\n')
        with self.assertRaises(HarnessError):self.spaces.integrate(self.ticket)
        self.assertEqual((self.root/'a.py').read_text(),'user edit\n')
    def test_worker_out_of_scope_edit_blocks_integration(self):
        info=self.prepare();(Path(info['tree'])/'b.py').write_text('wrong\n')
        with self.assertRaises(HarnessError):self.spaces.integrate(self.ticket)
        self.assertEqual((self.root/'b.py').read_text(),'value = 2\n')
    def test_new_assigned_file_integrates(self):
        info=self.spaces.prepare(self.ticket,self.root,['new.py']);(Path(info['tree'])/'new.py').write_text('new = True\n')
        self.spaces.integrate(self.ticket);self.assertTrue((self.root/'new.py').is_file())
    def test_deletion_integrates_without_reset(self):
        info=self.prepare();(Path(info['tree'])/'a.py').unlink();self.spaces.integrate(self.ticket)
        self.assertFalse((self.root/'a.py').exists());self.assertTrue((self.root/'b.py').is_file())
    def test_second_integration_does_not_overwrite_later_edits(self):
        info=self.prepare();(Path(info['tree'])/'a.py').write_text('candidate\n');self.spaces.integrate(self.ticket)
        (self.root/'a.py').write_text('later\n');self.spaces.integrate(self.ticket)
        self.assertEqual((self.root/'a.py').read_text(),'later\n')
    def test_checkouts_remain_for_recovery(self):
        info=self.prepare();(Path(info['tree'])/'a.py').write_text('candidate\n');self.spaces.integrate(self.ticket)
        self.assertTrue(Path(info['tree']).is_dir());self.assertTrue((Path(info['tree']).parent/'result.patch').is_file())
    def test_no_commit_is_created_by_integration(self):
        before=self.git('rev-parse','HEAD');info=self.prepare();(Path(info['tree'])/'a.py').write_text('candidate\n');self.spaces.integrate(self.ticket)
        self.assertEqual(before,self.git('rev-parse','HEAD'));self.assertEqual(self.git('diff','--cached'),b'')
    def test_checkout_filters_are_not_executed(self):
        self.git('config','filter.example.smudge','echo unsafe')
        with self.assertRaises(HarnessError):self.prepare()
    def test_foreign_ticket_path_rejected(self):
        with self.assertRaises(HarnessError):self.spaces.integrate('../outside')
    def test_storage_cannot_be_inside_source(self):
        with self.assertRaises(HarnessError):Workspaces(self.root/'generated').prepare(self.ticket,self.root,['a.py'])
    def test_unrelated_user_change_can_coexist(self):
        info=self.prepare();(Path(info['tree'])/'a.py').write_text('candidate\n');(self.root/'b.py').write_text('user\n')
        self.spaces.integrate(self.ticket);self.assertEqual((self.root/'b.py').read_text(),'user\n')
    def test_parallel_disjoint_changes_merge_without_reset(self):
        a=self.prepare();b=self.spaces.prepare('b'*32,self.root,['b.py'])
        (Path(a['tree'])/'a.py').write_text('first\n');(Path(b['tree'])/'b.py').write_text('second\n')
        self.spaces.integrate(self.ticket);self.spaces.integrate('b'*32)
        self.assertEqual((self.root/'a.py').read_text(),'first\n');self.assertEqual((self.root/'b.py').read_text(),'second\n')
    def test_merge_lock_never_broken_automatically(self):
        self.prepare()
        with self.spaces._lock(self.root):
            with self.assertRaises(HarnessError):self.spaces.integrate(self.ticket)
