import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('evaluate',ROOT/'evals'/'evaluate.py')
evaluate=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluate)

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.output=Path(self.temp.name)/'evaluation'
        evaluate.prepare(self.output)
        self.mapping=json.loads((self.output/'controller'/'mapping.json').read_text())['jobs']
    def test_twenty_four_isolated_jobs_but_no_models_run(self):
        self.assertEqual(len(self.mapping),24)
        for job in self.mapping:
            files={p.name for p in (self.output/'jobs'/job).iterdir()}
            self.assertNotIn('grade.py',files);self.assertNotIn('reference.py',files)
            self.assertEqual(evaluate.grade_one(self.output,job)['status'],'NOT_SUBMITTED')
        self.assertEqual(evaluate.summarize(self.output)['parity_verdict'],'NOT_ESTABLISHED')
    def test_each_fixture_reference_passes_and_starter_fails(self):
        seen=set()
        for job,record in self.mapping.items():
            if record['fixture'] in seen:continue
            seen.add(record['fixture'])
            same=[j for j,r in self.mapping.items() if r['fixture']==record['fixture']]
            bad,good=same[:2]
            with self.subTest(fixture=record['fixture'],variant='starter'):
                evaluate.submit(self.output,bad)
                self.assertEqual(evaluate.grade_one(self.output,bad)['status'],'FAIL')
            with self.subTest(fixture=record['fixture'],variant='reference'):
                shutil.copyfile(ROOT/'evals'/'fixtures'/record['fixture']/'reference.py',self.output/'jobs'/good/'candidate.py')
                evaluate.submit(self.output,good)
                result=evaluate.grade_one(self.output,good)
                self.assertEqual(result['status'],'PASS',result['stderr'])
                self.assertIsNone(result['model_wall_seconds'])
    def test_submission_mutation_refused(self):
        job=next(iter(self.mapping));evaluate.submit(self.output,job)
        (self.output/'jobs'/job/'candidate.py').write_text('# edited after submission')
        self.assertEqual(evaluate.grade_one(self.output,job)['status'],'STALE_SUBMISSION')
    def test_protected_task_change_refused(self):
        job=next(iter(self.mapping));(self.output/'jobs'/job/'TASK.md').write_text('weakened')
        evaluate.submit(self.output,job)
        self.assertEqual(evaluate.grade_one(self.output,job)['status'],'SCOPE_VIOLATION')
    def test_second_submission_and_existing_output_refused(self):
        job=next(iter(self.mapping));evaluate.submit(self.output,job)
        with self.assertRaises(ValueError):evaluate.submit(self.output,job)
        with self.assertRaises(ValueError):evaluate.prepare(self.output)
    def test_invalid_job_and_metric_refused(self):
        with self.assertRaises(ValueError):evaluate.submit(self.output,'../escape')
        with self.assertRaises(ValueError):evaluate.submit(self.output,next(iter(self.mapping)),{'wall_seconds':-1})
        with self.assertRaises(ValueError):evaluate.submit(self.output,next(iter(self.mapping)),{'unknown':1})
