import json
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from luna_astra.hooks import Hooks,identity
from luna_astra.store import Store
from luna_astra.evidence import Evidence
from luna_astra.jobs import Jobs
from luna_astra.util import HarnessError
ROOT=Path(__file__).resolve().parents[1]

class JobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.processes=[]
        real_popen=subprocess.Popen
        def owned_popen(*args,**kwargs):
            process=real_popen(*args,**kwargs);self.processes.append(process);return process
        capture=patch('luna_astra.jobs.subprocess.Popen',side_effect=owned_popen)
        capture.start();self.addCleanup(capture.stop);self.addCleanup(self.wait_processes)
        self.ws=self.base/'repo';self.ws.mkdir();(self.ws/'app.py').write_text('answer=2\n')
        (self.ws/'check.py').write_text('import app\nassert app.answer==2\n')
        self.state=self.base/'state';self.h=Hooks(ROOT,self.state)
        self.event={'hook_event_name':'SessionStart','model':'gpt-5.6-luna','session_id':'test','cwd':str(self.ws),'turn_id':'turn'}
        self.h.handle(self.event);self.key=identity(self.event)[0];self.store=Store(self.state)
        self.ev=Evidence(self.state/'sessions'/self.key,self.ws)
        self.task={'task_id':'async','design':'keep correct behavior','requirements':['answer=2'],'allowed_paths':['app.py'],
                   'checks':[{'id':'check','purpose':'behavior','argv':[sys.executable,'-B','check.py'],'dependencies':['app.py','check.py'],'covers':[0]}]}
        self.ev.begin(self.task);self.jobs=Jobs(self.store,self.key,ROOT)
    def wait_processes(self):
        for process in self.processes:process.wait(timeout=30)
    def wait(self):
        deadline=time.monotonic()+12
        while self.jobs.active() and time.monotonic()<deadline:time.sleep(.02)
        self.assertFalse(self.jobs.active(),self.jobs.all());return self.jobs.all()[0]
    def helper(self,args,data=None):
        return subprocess.run([sys.executable,str(ROOT/'luna.py'),'--state',str(self.state),'--session',self.key,*args],input=json.dumps(data) if data else None,text=True,capture_output=True,timeout=15)
    def test_actual_async_check_completes_with_evidence(self):
        job=self.jobs.start('check');self.assertIn(job['status'],{'PENDING','RUNNING','FINISHED'})
        finished=self.wait();self.assertEqual(finished['status'],'FINISHED');self.assertTrue(self.ev.status()['passed'])
    def test_failed_async_check_is_not_pass(self):
        (self.ws/'app.py').write_text('answer=9\n');self.jobs.start('check');self.wait();self.assertFalse(self.ev.status()['passed'])
    def test_duplicate_outstanding_check_reuses_controller(self):
        (self.ws/'check.py').write_text('import time\ntime.sleep(.5)\n')
        a=self.jobs.start('check');b=self.jobs.start('check');self.assertEqual(a['id'],b['id']);self.wait()
    def test_pending_controller_blocks_early_finish(self):
        (self.ws/'check.py').write_text('import time\ntime.sleep(.5)\n')
        self.jobs.start('check')
        try:
            r=self.helper(['finish'],{'kind':'tested','summary':'done','review':'review','limitations':'local'})
            self.assertNotEqual(r.returncode,0)
        finally:self.wait()
    def test_outstanding_check_blocks_new_assignment(self):
        (self.ws/'check.py').write_text('import time\ntime.sleep(.5)\n');self.jobs.start('check')
        try:self.assertNotEqual(self.helper(['begin'],{**self.task,'task_id':'new'}).returncode,0)
        finally:self.wait()
    def test_invalid_check_cannot_launch(self):
        with self.assertRaises(HarnessError):self.jobs.start('missing')
        self.assertEqual(self.jobs.all(),[])
    def test_missing_controller_result_is_never_pass(self):
        self.store.put(self.key,'job:'+'a'*32,{'status':'UNKNOWN','id':'a'*32,'check_id':'check','task_hash':'x','pid':999999})
        result=self.h.handle({**self.event,'hook_event_name':'Stop','last_assistant_message':'done'})
        self.assertEqual(result['decision'],'block');self.assertFalse(self.ev.status()['passed'])
    def test_invalid_job_identity_refused(self):
        with self.assertRaises(HarnessError):self.jobs.run_worker('../outside')
    def test_no_duplicate_controller_claim(self):
        self.jobs.start('check');result=self.wait()
        with self.assertRaises(HarnessError):self.jobs.run_worker(result['id'])
