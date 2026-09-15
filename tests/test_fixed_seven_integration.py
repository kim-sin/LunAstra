"""Installed shell/CLI tests with real Git, files and checks; model events are simulated."""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from luna_astra.install import Installer
from luna_astra.util import load_json, json_hash
from luna_astra.transport import helper_command

PACKAGE=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('git'),'Git required for installed worktree tests')
class InstalledFixedSevenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.ws=self.base/'project';self.ws.mkdir();self.home=self.base/'home';self.home.mkdir()
        (self.ws/'app.py').write_text('def add(a,b): return a-b\n',encoding='utf-8')
        (self.ws/'test_app.py').write_text('from app import add\nassert add(2,3)==5\nassert add(-2,2)==0\n',encoding='utf-8')
        (self.home/'auth.json').write_text('{"retained":"fixture-not-a-token"}',encoding='utf-8')
        (self.home/'config.toml').write_text('model = "gpt-5.6-luna"\nmodel_reasoning_effort = "none"\n',encoding='utf-8')
        self.foreign={'hooks':[{'type':'command','command':'echo retained','statusMessage':'foreign fixture'}]}
        (self.home/'hooks.json').write_text(json.dumps({'hooks':{'Stop':[self.foreign]}}),encoding='utf-8')
        self.original={n:(self.home/n).read_bytes() for n in ('auth.json','config.toml')}
        self.git('init','-q');self.git('config','user.name','Synthetic Test');self.git('config','user.email','test@example.invalid')
        self.git('add','.');self.git('commit','-qm','synthetic fixture')
        self.installer=Installer(PACKAGE,self.home);self.receipt=self.installer.apply()
        self.hooks=load_json(self.home/'hooks.json')['hooks']
        self.event={'session_id':'native-root','model':'gpt-5.6-luna','cwd':str(self.ws),'turn_id':'r1'}
        result=self.hook({**self.event,'hook_event_name':'SessionStart'})
        self.prefix=self.get_prefix(result)
        self.hook({**self.event,'hook_event_name':'UserPromptSubmit','prompt':'Repair add without changing its interface and write a checked report.'})
        self.contract={'goal':'Repair signed addition and deliver a checked report','requirements':['Signed addition is correct','report.txt contains checked result'],
                       'evidence_paths':['app.py','test_app.py'],'output_paths':['app.py','report.txt']}
        self.children={};self.native=[]
    def git(self,*args):
        return subprocess.run(['git','-C',str(self.ws),*args],check=True,capture_output=True,text=True)
    def hook(self,event):
        handler=self.hooks[event['hook_event_name']][-1]['hooks'][0]
        run=subprocess.run(handler['command'],shell=True,input=json.dumps(event),text=True,encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(0,run.returncode,run.stdout+run.stderr)
        return json.loads(run.stdout)
    def get_prefix(self,out):
        return json.loads(out['hookSpecificOutput']['additionalContext'].split('LOCAL_HELPER_ARGV=',1)[1].splitlines()[0])
    def cli(self,args,data=None,prefix=None,code=0):
        prefix=prefix or self.prefix
        run=subprocess.run(prefix+args,input=json.dumps(data) if data is not None else None,text=True,encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(code,run.returncode,run.stdout+run.stderr)
        return json.loads(run.stdout or run.stderr)
    def dispatch(self,round_no):
        calls=self.cli(['crew-next'])['calls'];self.assertEqual(6,len(calls))
        for c in calls:
            uid=f'round-{round_no}-slot-{c["slot"]}';agent=f'native-child-{c["slot"]}'
            event={**self.event,'hook_event_name':'PreToolUse','tool_name':'multi_agent_v1'+c['tool'],
                   'tool_input':c['arguments'],'tool_use_id':uid}
            out=self.hook(event);self.assertNotEqual('deny',out.get('hookSpecificOutput',{}).get('permissionDecision'),out)
            if round_no==1:
                self.assertEqual('spawn_agent',c['tool']);self.assertNotIn('model',c['arguments'])
                result={'agent_id':agent,'nickname':'Fixture'}
            else:
                self.assertEqual('send_input',c['tool']);self.assertEqual(agent,c['arguments']['target'])
                self.assertNotIn('id',c['arguments']);result={'submission_id':uid}
            self.hook({**event,'hook_event_name':'PostToolUse','tool_response':json.dumps(result)})
            ce={**self.event,'session_id':agent,'agent_id':agent,'turn_id':f'{uid}-turn'}
            out=self.hook({**ce,'hook_event_name':'SubagentStart' if round_no==1 else 'SessionStart','source':'resume'})
            prefix=self.get_prefix(out)
            assigned=self.cli(['crew-join',c['ticket']],prefix=prefix)
            self.children[c['slot']]={'event':ce,'prefix':prefix,'assigned':assigned}
            self.native.append(c)
    def report(self,slot,paths,verdict='clear'):
        child=self.children[slot]
        return self.cli(['crew-report'],{'verdict':verdict,'summary':f'Slot {slot} inspected actual fixture files',
             'findings':[f'Independent evidence for obligation {slot}'],'references':[{'path':p} for p in paths],
             'covers':[0,1]},prefix=child['prefix'])
    def finish_readers(self,phase):
        for slot,child in self.children.items():
            if phase=='EXECUTE' and slot==1:continue
            self.report(slot,['app.py','report.txt'] if phase=='REVIEW' else ['app.py'])
            out=self.hook({**child['event'],'hook_event_name':'SubagentStop','last_assistant_message':'LUNASTRA_STATUS=ANALYSIS'})
            self.assertNotIn('decision',out,out);self.assertNotIn('stopReason',out,out)
    def execution_spec(self):
        tasks=[]
        for i in range(1,7):
            tasks.append({'id':f's{i}','kind':'implement' if i==1 else 'investigate',
             'description':f'Implement signed addition' if i==1 else f'Inspect independent risk {i} in the addition interface and report',
             'paths':['app.py'] if i==1 else ['app.py','test_app.py'],'depends_on':[],
             'done_when':['Return source-linked evidence; implementation must pass actual tests'],
             'why_parallel':f'Distinct responsibility {i} for the fixed crew'})
        return {'decision':'Use addition; preserve interface; keep s5/s6 independent','tasks':tasks}
    def begin(self,prefix,root=False):
        checks=[{'id':'signed','purpose':'Actual signed arithmetic checks','argv':[sys.executable,'-B','test_app.py'],
                 'dependencies':['app.py','test_app.py'],'covers':[0]}]
        req=['Signed addition is correct']
        if root:
            req=self.contract['requirements']
            checks.append({'id':'report','purpose':'Check delivered text','argv':[sys.executable,'-c',"from pathlib import Path; assert Path('report.txt').read_text()=='checked: 5'"],
                           'dependencies':['report.txt','app.py'],'covers':[1]})
        self.cli(['begin'],{'task_id':'root-add' if root else 'worker-add','design':'Maintain add signature with arithmetic sum',
                  'requirements':req,'allowed_paths':['app.py','report.txt'] if root else ['app.py'],'checks':checks},prefix=prefix)
        self.assertTrue(self.cli(['run-all'],prefix=prefix)['status']['passed'])
        self.cli(['finish'],{'kind':'tested','summary':'Actual files checked','review':'Signed and zero cases inspected',
                 'limitations':'Software integration fixture; no actual Luna run'},prefix=prefix)
    def full_cycle(self):
        self.cli(['crew-start'],self.contract);self.dispatch(1);self.finish_readers('PLAN')
        self.cli(['crew-execute'],self.execution_spec());self.dispatch(2)
        writer=self.children[1];tree=Path(writer['assigned']['workspace']);self.assertNotEqual(tree,self.ws)
        # Execute the exact installed command after passing through the Bash hook.
        argv=[sys.executable,'-c',"from pathlib import Path;Path('app.py').write_text('def add(a,b): return a+b\\n')"]
        command=helper_command(writer['prefix']+['worker-exec','--argv-json',json.dumps(argv)])
        event={**writer['event'],'hook_event_name':'PreToolUse','tool_name':'Bash','tool_input':{'command':command},'tool_use_id':'write'}
        out=self.hook(event);self.assertNotEqual('deny',out.get('hookSpecificOutput',{}).get('permissionDecision'),out)
        actual=out.get('hookSpecificOutput',{}).get('updatedInput',{}).get('command',command)
        run=subprocess.run(actual,cwd=self.ws,shell=True,text=True,encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(0,run.returncode,run.stdout+run.stderr)
        self.hook({**event,'hook_event_name':'PostToolUse','tool_response':{'exit_code':0,'stdout':run.stdout}})
        self.assertIn('a-b',(self.ws/'app.py').read_text());self.assertIn('a+b',(tree/'app.py').read_text())
        self.begin(writer['prefix']);self.report(1,['app.py'])
        stop=self.hook({**writer['event'],'hook_event_name':'SubagentStop','last_assistant_message':'LUNASTRA_STATUS=TESTED'})
        self.assertNotIn('decision',stop,stop);self.assertNotIn('stopReason',stop,stop)
        self.finish_readers('EXECUTE')
        self.cli(['team-integrate','s1']);self.cli(['team-accept','s1','--review','Inspected the exact checked patch'])
        self.assertIn('a+b',(self.ws/'app.py').read_text())
        (self.ws/'report.txt').write_text('checked: 5',encoding='utf-8')
        self.begin(self.prefix,root=True)
        self.cli(['crew-review'],{'decision':'Verify the combined app and delivered report'})
        self.dispatch(3)
        self.assertEqual(self.ws,Path(self.children[1]['assigned']['workspace']))
        self.finish_readers('REVIEW')
        self.cli(['finish'],{'kind':'tested','summary':'Delivered checked app and report','review':'All six final reports inspected',
                  'limitations':'No live model quality comparison'})
        s=self.cli(['crew-complete'],{'decision':'All requirements, files, six reports and fresh checks agree'})
        self.assertTrue(s['complete']);self.assertEqual(6,s['observed_children'])
        result=self.hook({**self.event,'hook_event_name':'Stop','last_assistant_message':'LUNASTRA_STATUS=TESTED'})
        self.assertNotIn('decision',result,result);self.assertNotIn('stopReason',result,result)
        self.assertEqual(6,sum(c['tool']=='spawn_agent' for c in self.native))
        self.assertEqual(12,sum(c['tool']=='send_input' for c in self.native))
        for name,value in self.original.items():self.assertEqual(value,(self.home/name).read_bytes())
        self.assertIn(self.foreign,load_json(self.home/'hooks.json')['hooks']['Stop'])
        self.assertTrue(self.cli(['doctor'])['sessions'])
        return tree
    def test_installed_fixed_seven_full_reuse_and_real_git_integration(self):
        tree=self.full_cycle();self.installer.remove()
        self.assertTrue(tree.exists());self.assertIn(self.foreign,load_json(self.home/'hooks.json')['hooks']['Stop'])
    def test_new_installed_sessions_cannot_bypass_fixed_protocol(self):
        self.cli(['team-plan'],{'goal':'bypass','tasks':[]},code=1)
        out=self.hook({**self.event,'hook_event_name':'Stop','last_assistant_message':'done'})
        self.assertEqual('block',out['decision'])
    def test_staged_json_roundtrip_and_idempotent_retry(self):
        raw=json.dumps(self.contract,ensure_ascii=False)
        for offset in range(0,len(raw),100):
            chunk=raw[offset:offset+100]
            self.cli(['input-append','contract','--offset',str(offset),'--chunk',chunk])
            again=self.cli(['input-append','contract','--offset',str(offset),'--chunk',chunk])
            self.assertTrue(again['retry_reused'])
        out=self.cli(['--input-ref','contract','crew-start'])
        self.assertEqual(self.contract['requirements'],out['requirements'])
    def test_existing_release_and_configuration_preserved_on_reinstall(self):
        before=(Path(self.receipt['release'])/'luna.py').read_bytes()
        again=self.installer.apply();self.assertEqual(again['release'],self.receipt['release'])
        self.assertEqual(before,(Path(again['release'])/'luna.py').read_bytes())
        for name,value in self.original.items():self.assertEqual(value,(self.home/name).read_bytes())

if __name__=='__main__':unittest.main()
