import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from luna_astra.evidence import Evidence
from luna_astra.util import HarnessError

class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.ws=self.base/'work';self.ws.mkdir();(self.ws/'app.py').write_text('answer=42\n')
        (self.ws/'test_app.py').write_text('import app\nassert app.answer==42\n')
        self.ev=Evidence(self.base/'state',self.ws)
        self.task={'task_id':'one','design':'preserve','requirements':['answer is 42'],
            'checks':[{'id':'test','purpose':'behavior','argv':[sys.executable,'-B','test_app.py'],
                'dependencies':['app.py','test_app.py'],'covers':[0],'reusable':True}]}
        self.ev.begin(self.task)
    def test_explicit_deterministic_check_reused(self):
        self.ev.run_all();r=self.ev.run_all();self.assertTrue(r['checks'][0]['reused'])
    def test_default_is_not_reused(self):
        del self.task['checks'][0]['reusable'];self.ev.begin(self.task)
        self.ev.run_all();r=self.ev.run_all();self.assertNotIn('reused',r['checks'][0]);self.assertEqual(r['checks'][0]['attempt'],2)
    def test_force_reexecutes(self):
        self.ev.run_all();r=self.ev.run_all(reuse=False);self.assertEqual(r['checks'][0]['attempt'],2)
    def test_changed_source_rerun_not_reuse(self):
        self.ev.run_all();(self.ws/'app.py').write_text('answer=1\n')
        r=self.ev.run_all();self.assertEqual(r['checks'][0]['status'],'FAIL');self.assertNotIn('reused',r['checks'][0])
    def test_relevant_environment_invalidates(self):
        key='LUNA_ASTRA_TEST_FLAG';old=os.environ.get(key)
        self.addCleanup(lambda:os.environ.pop(key,None) if old is None else os.environ.__setitem__(key,old))
        self.task['checks'][0]['environment_keys']=[key];self.ev.begin(self.task)
        os.environ[key]='A';self.ev.run_all();os.environ[key]='B'
        self.assertFalse(self.ev.status()['passed'])
    def test_bool_reusable_validation(self):
        self.task['checks'][0]['reusable']='yes'
        with self.assertRaises(HarnessError):self.ev.begin(self.task)
    def test_environment_keys_validation(self):
        self.task['checks'][0]['environment_keys']='PATH'
        with self.assertRaises(HarnessError):self.ev.begin(self.task)
    def test_latest_failure_never_reused(self):
        self.ev.run_all();(self.ws/'app.py').write_text('answer=1\n');self.ev.run_all()
        (self.ws/'app.py').write_text('answer=42\n');r=self.ev.run_all();self.assertNotIn('reused',r['checks'][0]);self.assertEqual(r['checks'][0]['status'],'PASS')
    def test_undeclared_external_dependency_not_certified(self):
        self.ev.run_all();self.assertIn('declared',self.ev.status()['limit'])

    def test_reuse_validates_linear_number_of_contexts(self):
        self.task['checks']=[{**self.task['checks'][0],'id':f'test-{i}'} for i in range(4)]
        self.ev.begin(self.task);self.ev.run_all()
        with patch.object(self.ev,'_context',wraps=self.ev._context) as ctx:
            result=self.ev.run_all()
        self.assertTrue(result['status']['passed']);self.assertEqual(ctx.call_count,8)
    def test_batch_rejects_concurrent_assignment_change(self):
        self.task['checks']=[{**self.task['checks'][0],'id':'first'},{**self.task['checks'][0],'id':'second'}]
        self.ev.begin(self.task);original=self.ev.run
        def change(check_id,expected_task_hash=None):
            result=original(check_id,expected_task_hash)
            changed=copy.deepcopy(self.task);changed['task_id']='different';self.ev.begin(changed)
            return result
        with patch.object(self.ev,'run',side_effect=change),self.assertRaises(HarnessError):self.ev.run_all()
