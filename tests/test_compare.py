import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from luna_astra.util import HarnessError,file_hash
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('compare',ROOT/'evals'/'compare.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'trace.txt').write_text('Synthetic fixture trace, not an actual model run.\n')
        self.a={'task_id':'task1','trial_id':'1','arm':'luna_stock','condition_id':'fixed','model_id':'same-luna','reasoning_setting':'unchanged',
                'success':False,'source_trace':'trace.txt','source_trace_sha256':file_hash(self.root/'trace.txt'),'wall_seconds':10}
        self.b={**self.a,'arm':'luna_astra','success':True,'wall_seconds':8}
    def test_paired_outcomes(self):
        r=mod.compare([self.a,self.b],self.root);self.assertEqual(r['paired_tasks'],1);self.assertEqual(r['enhanced_only_successes'],1)
        self.assertEqual(r['metrics']['wall_seconds']['median_pair_difference'],-2)
    def test_missing_cost_is_not_zero(self):
        r=mod.compare([self.a,self.b],self.root);self.assertIsNone(r['metrics']['credits']['enhanced_sum'])
    def test_no_parity_claim_from_pass(self):self.assertEqual(mod.compare([self.a,self.b],self.root)['parity'],'NOT_ESTABLISHED')
    def test_unmatched_task_not_failure(self):
        r=mod.compare([self.a],self.root);self.assertEqual(r['paired_tasks'],0);self.assertEqual(len(r['unmatched_tasks']),1)
    def test_duplicate_arm_rejected(self):
        with self.assertRaises(HarnessError):mod.compare([self.a,self.a],self.root)
    def test_setting_change_invalid_comparison(self):
        for k in ('condition_id','model_id','reasoning_setting'):
            with self.subTest(k=k),self.assertRaises(HarnessError):mod.compare([self.a,{**self.b,k:'different'}],self.root)
    def test_trace_change_rejected(self):
        (self.root/'trace.txt').write_text('changed')
        with self.assertRaises(HarnessError):mod.compare([self.a,self.b],self.root)
    def test_nonfinite_metrics_rejected(self):
        for v in (-1,float('nan'),True):
            with self.subTest(v=v),self.assertRaises(HarnessError):mod.compare([{**self.a,'credits':v}],self.root)
    def test_trace_escape_rejected(self):
        with self.assertRaises(HarnessError):mod.compare([{**self.a,'source_trace':'../outside'}],self.root)
    def test_empty_comparison_has_no_success_rate(self):self.assertIsNone(mod.compare([],self.root)['paired_success_difference'])
    def test_astra_comparison_is_explicit_and_does_not_require_identical_model(self):
        reference={**self.a,'arm':'astra_reference','model_id':'reference-model','reasoning_setting':'reference-effort'}
        r=mod.compare([reference,self.b],self.root,reference='astra_reference')
        self.assertEqual(r['reference_arm'],'astra_reference');self.assertEqual(r['paired_tasks'],1);self.assertIsNone(r['stock_successes'])
    def test_astra_comparison_still_requires_same_task_conditions(self):
        reference={**self.a,'arm':'astra_reference','condition_id':'different'}
        with self.assertRaises(HarnessError):mod.compare([reference,self.b],self.root,reference='astra_reference')
