"""Batch boundaries, indexed queue and byte-backed input snapshots (no models)."""
import copy
import json
import os
import time
import unittest
from unittest.mock import patch
import test_v4_research as fixtures
from luna_astra.research import Research, wake_policy, validate_graph, TERMINAL
from luna_astra.util import HarnessError, canonical


def signal(completed=0,pending=20,running=2,failed=0,revision=1):
    counts={s:0 for s in {'PENDING','RUNNING'}|TERMINAL}
    counts.update(VERIFIED=completed,PENDING=pending,RUNNING=running,FAILED=failed)
    return {'configured':True,'study_id':'test','state':'RUNNING','revision':revision,
            'counts':counts,'ready':pending>0,'policy':wake_policy(), 'best':None}


class WakePolicyTests(unittest.TestCase):
    def test_one_completion_is_not_a_wake(self):
        self.assertIsNone(Research._wake_reason(signal(1),signal(),3))
    def test_revision_only_does_not_wake(self):
        self.assertIsNone(Research._wake_reason(signal(revision=999),signal(),60))
    def test_batch_boundary_wakes(self):
        self.assertEqual('BATCH_READY',Research._wake_reason(signal(10),signal(),1))
    def test_failure_wakes_without_min_interval(self):
        self.assertEqual('NEW_FAILURE',Research._wake_reason(signal(failed=1),signal(),0))
    def test_old_failure_does_not_repeat(self):
        self.assertIsNone(Research._wake_reason(signal(failed=1),signal(failed=1),60))
    def test_drain_does_not_wait_for_tenth_job(self):
        self.assertEqual('QUEUE_DRAINED',Research._wake_reason(signal(3,0,0),signal(),1))
    def test_blocked_dependency_has_distinct_signal(self):
        cur=signal(1,5,0);cur['ready']=False
        self.assertEqual('DEPENDENCY_BLOCKED',Research._wake_reason(cur,signal(),1))
    def test_pausing_is_immediate(self):
        cur=signal();cur['state']='PAUSING';self.assertEqual('PAUSING',Research._wake_reason(cur,signal(),0))
    def test_paused_is_immediate(self):
        cur=signal();cur['state']='PAUSED';self.assertEqual('PAUSED',Research._wake_reason(cur,signal(),0))
    def test_finished_is_immediate(self):
        cur=signal();cur['state']='FINISHED';self.assertEqual('FINISHED',Research._wake_reason(cur,signal(),0))
    def test_queue_low_is_coalesced(self):
        self.assertIsNone(Research._wake_reason(signal(1,0,2),signal(),3))
        self.assertEqual('QUEUE_LOW',Research._wake_reason(signal(1,0,2),signal(),30))
    def test_improvement_requires_explicit_threshold(self):
        old=signal();old['best']={'id':'one','score':'5'}
        cur=signal(1);cur['best']={'id':'two','score':'1000'}
        self.assertIsNone(Research._wake_reason(cur,old,60))
    def test_significant_improvement_is_coalesced(self):
        old=signal();old['best']={'id':'one','score':'5'}
        cur=signal(1);cur['best']={'id':'two','score':'8'};cur['policy']=wake_policy({'improvement_absolute':'2'})
        self.assertIsNone(Research._wake_reason(cur,old,1))
        self.assertEqual('SIGNIFICANT_IMPROVEMENT',Research._wake_reason(cur,old,30))
    def test_tiny_improvement_does_not_wake(self):
        old=signal();old['best']={'id':'one','score':'5'}
        cur=signal(1);cur['best']={'id':'two','score':'5.01'};cur['policy']=wake_policy({'improvement_absolute':'1'})
        self.assertIsNone(Research._wake_reason(cur,old,60))
    def test_invalid_wake_parameters_rejected(self):
        for value in ({'completed':True},{'completed':0},{'min_interval':-1},{'queue_low_water':999},
                      {'improvement_absolute':'NaN'},{'improvement_absolute':0},{'improvement_absolute':False}, {'typo':1}):
            with self.subTest(value=value),self.assertRaises(HarnessError):wake_policy(value)
    def test_no_config_reports_unconfigured(self):
        self.assertEqual('UNCONFIGURED',Research._wake_reason({},signal(),0))
    def test_deep_graph_is_not_recursive(self):
        jobs={str(i):{'outputs':['scratch/'+str(i)],'depends_on':[str(i-1)] if i else []} for i in range(10000)}
        validate_graph(jobs)
    def test_output_ancestors_conflict(self):
        for paths in [('x','x/y'),('x/y','x'),('x/y','x/y')]:
            with self.subTest(paths=paths),self.assertRaises(HarnessError):
                validate_graph({'a':{'outputs':[paths[0]],'depends_on':[]},'b':{'outputs':[paths[1]],'depends_on':[]}})
    def test_sibling_prefix_does_not_conflict(self):
        validate_graph({'a':{'outputs':['x/a'],'depends_on':[]},'b':{'outputs':['x/ab'],'depends_on':[]}})
    def test_dependency_cycle_is_rejected(self):
        with self.assertRaises(HarnessError):validate_graph({'a':{'outputs':['a'],'depends_on':['b']},'b':{'outputs':['b'],'depends_on':['a']}})


class BatchQueueTests(unittest.TestCase):
    setUp=fixtures.ResearchTests.setUp
    drain=fixtures.ResearchTests.drain
    job=fixtures.ResearchTests.job
    direct=fixtures.ResearchTests.direct
    wait_terminal=fixtures.ResearchTests.wait_terminal

    def test_input_snapshot_is_shared_once_per_batch(self):
        jobs=[self.job('n'+str(i)) for i in range(20)]
        with patch.object(self.r,'_context',wraps=self.r._context) as observed:
            self.r.enqueue({'jobs':jobs});self.assertEqual(1,observed.call_count)
        with self.f.store.db() as db:
            self.assertEqual(1,db.execute('SELECT count(*) FROM research_snapshots WHERE owner=?',(self.f.owner,)).fetchone()[0])
        self.assertEqual(20,self.r.status()['total'])
    def test_duplicate_enqueue_does_not_rehash_or_overwrite(self):
        self.r.enqueue({'jobs':[self.job()]})
        with patch.object(self.r,'_context',side_effect=AssertionError('duplicate rehash')):
            self.assertEqual(1,self.r.enqueue({'jobs':[self.job()]})['duplicates_reused'])
    def test_changed_input_same_size_and_mtime_is_not_success(self):
        self.r.enqueue({'jobs':[self.job()]});path=self.f.root/'input.txt';st=path.stat()
        path.write_text('9,9\n');os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
        result=self.direct(self.job());self.assertEqual('STALE',result['state'])
        self.assertIsNone(self.r.status()['best_verified_candidate'])
    def test_corrupt_snapshot_cannot_certify(self):
        self.r.enqueue({'jobs':[self.job()]})
        with self.f.store.db(True) as db:db.execute("UPDATE research_snapshots SET context='{}' WHERE owner=?",(self.f.owner,))
        result=self.direct(self.job());self.assertEqual('ERROR',result['state'])
    def test_status_is_bounded_and_full_receipt_is_explicit(self):
        self.direct(self.job())
        text=canonical(self.r.status());self.assertLess(len(text),7000)
        self.assertNotIn('input_context',text)
        self.assertIn('input_context',self.r.read_job('first')['record'])
    def test_read_job_rejects_foreign_or_unsafe_id(self):
        for ident in ('../x','missing',None):
            with self.subTest(ident=ident),self.assertRaises(HarnessError):self.r.read_job(ident)
    def test_additive_dependency_migration_preserves_records(self):
        first=self.job('a');second=self.job('b');second['depends_on']=['a']
        self.r.enqueue({'jobs':[first,second]})
        with self.f.store.db(True) as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM research_jobs WHERE owner=? ORDER BY id',(self.f.owner,))]
            db.execute('DELETE FROM research_schema WHERE owner=?',(self.f.owner,))
            db.execute('DELETE FROM research_dependencies WHERE owner=?',(self.f.owner,))
        Research(self.f.store,self.f.owner,fixtures.PACKAGE)
        with self.f.store.db() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM research_jobs WHERE owner=? ORDER BY id',(self.f.owner,))])
            self.assertEqual([('b','a')],[tuple(r) for r in db.execute('SELECT job_id,dependency_id FROM research_dependencies WHERE owner=?',(self.f.owner,))])
    def test_changed_dependency_index_blocks_claim(self):
        a=self.job('a');b=self.job('b');b['depends_on']=['a'];self.r.enqueue({'jobs':[a,b]})
        with self.f.store.db(True) as db:
            s=self.r._read(db);s.update(state='RUNNING',supervisor={'nonce':'c'*32});self.r._save(db,s)
            db.execute("UPDATE research_jobs SET state='CANCELLED' WHERE owner=? AND id='a'",(self.f.owner,))
            db.execute('DELETE FROM research_dependencies WHERE owner=?',(self.f.owner,))
        with self.assertRaises(HarnessError):self.r._claim('c'*32)
        with self.f.store.db(True) as db:s=self.r._read(db);s['state']='PAUSED';self.r._save(db,s)
    def test_real_wait_delivers_a_batch_not_each_job(self):
        self.r.policy({'completed':3,'min_interval':30})
        self.r.enqueue({'jobs':[self.job('j'+str(i),5,.05) for i in range(3)]});self.r.start()
        result=self.r.wait(12)
        self.assertIn(result['wake_reason'],{'BATCH_READY','QUEUE_DRAINED'})
        self.assertEqual(3,result['status']['counts']['VERIFIED'])
        self.assertEqual(3,result['delta_counts']['VERIFIED'])
    def test_wait_does_not_repeat_an_old_failure(self):
        self.r.policy({'completed':10})
        initial=signal(failed=1);initial['study_id']='id'
        self.f.store.put(self.f.owner,'research-wait-cursor',{**initial,'delivered_at':time.time()})
        with patch.object(self.r,'_signal',return_value=initial):
            result=self.r.wait(1)
        self.assertTrue(result['timed_out']);self.assertEqual('TIMEOUT',result['wake_reason'])
    def test_first_wait_notices_failure_before_wait_started(self):
        failed=signal(failed=1);failed['study_id']='id'
        with patch.object(self.r,'_signal',return_value=failed):result=self.r.wait(1)
        self.assertEqual('NEW_FAILURE',result['wake_reason'])
    def test_configure_policy_validation_before_write(self):
        with self.assertRaises(HarnessError):self.r.policy({'completed':0})
        self.assertEqual(10,self.r.status()['wake_policy']['completed'])
    def test_ready_dependency_uses_verified_state_not_receipt_prose(self):
        a=self.job('a');b=self.job('b');b['depends_on']=['a'];self.r.enqueue({'jobs':[a,b]})
        with self.f.store.db(True) as db:
            s=self.r._read(db);s.update(state='RUNNING',supervisor={'nonce':'c'*32});self.r._save(db,s)
        self.assertEqual('a',self.r._claim('c'*32)['id']);self.assertIsNone(self.r._claim('c'*32))
        with self.f.store.db(True) as db:
            db.execute("UPDATE research_jobs SET state='VERIFIED' WHERE owner=? AND id='a'",(self.f.owner,))
        self.assertEqual('b',self.r._claim('c'*32)['id'])
        with self.f.store.db(True) as db:
            db.execute("UPDATE research_jobs SET state='CANCELLED' WHERE owner=? AND state='RUNNING'",(self.f.owner,))
            s=self.r._read(db);s['state']='PAUSED';self.r._save(db,s)

    def test_ready_sql_does_not_sort_entire_pending_queue(self):
        self.r.enqueue({'jobs':[self.job()]})
        with self.f.store.db() as db:
            queries=[];db.set_trace_callback(queries.append);self.r._ready_row(db);db.set_trace_callback(None)
            sql=next(q for q in queries if 'SELECT j.*' in q)
            plan=[row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql)]
            self.assertFalse(any('TEMP B-TREE' in p for p in plan),plan)
    def test_signal_does_not_fetch_full_job_body(self):
        self.r.enqueue({'jobs':[self.job()]})
        with self.f.store.db() as db:
            self.assertEqual([1],list(self.r._ready_row(db,signal_only=True)))
    def test_unknown_index_schema_is_not_silently_loaded(self):
        with self.f.store.db(True) as db:db.execute('UPDATE research_schema SET version=99 WHERE owner=?',(self.f.owner,))
        with self.assertRaises(HarnessError):Research(self.f.store,self.f.owner,fixtures.PACKAGE)

if __name__=='__main__':unittest.main()
