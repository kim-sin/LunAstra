from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from luna_astra.store import Store
from luna_astra.coordination import Coordinator,Conflict,edit_paths,normalized
from luna_astra.util import HarnessError

class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.ws=self.base/'project';self.ws.mkdir();self.c=Coordinator(Store(self.base/'state'),self.ws)
    def test_distinct_paths_can_parallel(self):
        self.c.claim('a',['src/a.py'],'manual');self.c.claim('b',['src/b.py'],'manual');self.assertEqual(len(self.c.status()),2)
    def test_same_path_blocked(self):
        self.c.claim('a',['a.py'],'manual')
        with self.assertRaises(Conflict):self.c.claim('b',['a.py'],'manual')
    def test_directory_blocks_child(self):
        self.c.claim('a',['src'],'manual')
        with self.assertRaises(Conflict):self.c.claim('b',['src/a.py'],'manual')
    def test_child_blocks_directory(self):
        self.c.claim('a',['src/a.py'],'manual')
        with self.assertRaises(Conflict):self.c.claim('b',['src'],'manual')
    def test_similar_prefix_not_conflict(self):self.c.claim('a',['src'],'manual');self.c.claim('b',['src2/a.py'],'manual')
    def test_manual_lease_allows_own_tool(self):self.c.claim('a',['src'],'manual');self.c.claim('a',['src/a.py'],'tool:1')
    def test_same_owner_parallel_tool_conflict(self):
        self.c.claim('a',['a.py'],'tool:1')
        with self.assertRaises(Conflict):self.c.claim('a',['a.py'],'tool:2')
    def test_duplicate_tool_claim_is_idempotent(self):
        self.c.claim('a',['a.py'],'tool:1');self.c.claim('a',['a.py'],'tool:1');self.assertEqual(len(self.c.status()),1)
    def test_release_does_not_release_sibling(self):
        self.c.claim('a',['a.py'],'manual');self.c.claim('b',['b.py'],'manual');self.c.release('a');self.assertEqual(self.c.status()[0]['owner'],'b')
    def test_no_partial_claim_on_conflict(self):
        self.c.claim('a',['z.py'],'manual')
        with self.assertRaises(Conflict):self.c.claim('b',['a.py','z.py'],'manual')
        self.assertEqual(len(self.c.status()),1)
    def test_concurrent_claim_has_one_winner(self):
        def run(owner):
            try:self.c.claim(owner,['a.py'],'manual');return True
            except Conflict:return False
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,['a','b','c','d']))
        self.assertEqual(results.count(True),1)
    def test_moves_include_source_destination(self):
        patch='*** Begin Patch\n*** Update File: a.py\n*** Move to: b.py\n*** End Patch'
        self.assertEqual(edit_paths('apply_patch',patch),['a.py','b.py'])
    def test_shell_not_claimed_fully_enforced(self):self.assertEqual(edit_paths('Bash',{'cmd':'echo x > a.py'}),[])
    def test_path_escape_refused(self):
        for path in ('../other.py','/etc/passwd','C:/escape','a/../../escape'):
            with self.subTest(path=path),self.assertRaises(HarnessError):self.c.claim('a',[path],'manual')
    def test_task_boundaries_enforced(self):
        task={'allowed_paths':['src'],'protected_paths':['src/frozen.py']}
        self.c.enforce_task(['src/a.py'],task)
        for p in ('other.py','src/frozen.py'):
            with self.assertRaises(Conflict):self.c.enforce_task([p],task)
