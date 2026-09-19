"""Single-step local orchestration; model judgments and native calls stay explicit.

Reads all six current reports together, validates the next legal action, reserves
ready native calls or prepares same-member recovery in one helper invocation.
It never manufactures a native acknowledgment, semantic approval or test result.
"""
from __future__ import annotations
import time
from pathlib import Path
from .flow import Flow
from .util import json_hash, canonical
from .report_access import detail_required

class Controller:
    def __init__(self, store, package):
        self.store=store;self.package=Path(package);self.flow=Flow(store,package)

    def step(self, owner, *, details=False):
        with self.store.connection():
            return self._step(owner, details=details)

    def _step(self, owner, *, details=False):
        started=time.monotonic()
        action=self.flow.drive(owner);kind=action['action']
        result={'schema':1,'next':action,'calls':[],'automatic_semantic_approval':False,
                'settings_changed':False,'native_calls_must_be_acknowledged':True}
        if kind=='DISPATCH':
            dispatch=self.flow.crew.next(owner)
            result['calls']=dispatch.get('calls',[])
            result['dispatch']={k:v for k,v in dispatch.items() if k not in {'calls','flow'}}
        elif kind in {'WAIT','OBSERVE_NATIVE'}:result['calls']=[action['native_call']]
        elif kind in {'RECOVER','REASSESS'}:
            recovery=self.flow.prepare_recovery(owner,int(action['slot'][1:]))
            result['recovery']=recovery
            result['calls']=[{'tool':recovery['tool'],'arguments':recovery['arguments']}]
        state=self.flow.crew.status(owner)
        if state.get('configured'):
            result['contract']={k:state.get(k) for k in ('run_id','phase','round','mode')}
            result['elapsed_seconds']=max(0,time.time()-state['created_at'])
            result['workers']=[{'slot':r['id'],'state':r['state'],'kind':r['spec']['kind'],
                                'agent_id':r['agent_id']} for r in state['tasks']]
            if kind in {'ADVANCE','ACCEPT','INTEGRATE','BLOCKED','REASSESS','RESEARCH','READ_REPORTS'}:
                result['reports']=[]
                for row in state['tasks']:
                    report=state['reports'].get(row['ticket'])
                    digest=None if not report else {
                        'verdict':report['verdict'],'summary':report.get('summary','')[:512],
                        'summary_truncated':len(report.get('summary',''))>512,
                        'findings_count':len(report.get('findings',[])),
                        'findings':report.get('findings',[]) if sum(len(f) for f in report.get('findings',[]))<=2000 else [f[:300] for f in report.get('findings',[])[:3]],
                        'references_count':len(report.get('references',[])),
                        'references':[{k:(v[:256] if isinstance(v,str) else v) for k,v in r.items() if k in {'path','missing_path','requirement'}} for r in report.get('references',[])[:4]],
                        'covers':report.get('covers',[]),'sha256':json_hash(report),
                        'full_read_command':'crew-report-read '+row['id'][1:],
                        'detail_required_before_decision':detail_required(report)}
                    result['reports'].append({'slot':row['id'],'ticket':row['ticket'],
                                              'report':report if details else digest})
                if details:
                    # Never acknowledge a report hidden behind a giant response.
                    # Deliver a bounded full-content batch; the next identical
                    # command supplies outstanding reports, without new agents.
                    pending=set(self.flow.crew.pending_report_details(owner,state))
                    candidates=[v for v in result['reports'] if v['slot'] in pending] if pending else result['reports']
                    selected=[];used=0
                    for value in candidates:
                        size=len(canonical(value))
                        if selected and used+size>14000:break
                        selected.append(value);used+=size
                    result['reports']=selected
                    selected_ids={v['slot'] for v in selected}
                    self.flow.crew.deliver_reports(owner,state,[v for v in state['tasks'] if v['id'] in selected_ids])
                    remaining=self.flow.crew.pending_report_details(owner,state)
                    result['remaining_required_reports']=remaining
                    result['next_report_command']='crew-step --details' if remaining else None
                    result['model_comprehension']='NOT_MEASURED; receipts record full-content retrieval only'
                result['reports_are_digests']=not details
                result['report_policy']='Inspect all six finding digests. Read the actual full report whenever detail_required_before_decision or an uncertainty is present; digests are not test executions.'
            result['action_token']=json_hash([state['run_id'],state['round'],state['plan_id'],kind,
                                              [[r['id'],r['state'],r['ticket']] for r in state['tasks']]])
        # legal_actions is a schema, not a grant of permission beyond the host.
        legal={
            'START':['crew-start'], 'ACKNOWLEDGE_REQUEST':['crew-continue','crew-revise'],
            'DISPATCH':['execute returned native calls','crew-step'],
            'WAIT':['execute returned wait_agent','crew-step'],
            'OBSERVE_NATIVE':['execute returned list_agents','crew-step'],
            'RECOVER':['execute returned native followup','crew-step'],
            'REASSESS':['execute returned native followup','crew-step'],
            'INTEGRATE':[action.get('helper'),'team-accept after patch review'],
            'READ_REPORTS':['crew-step --details','crew-report-read SLOT'],
            'ACCEPT':[str(action.get('helper') or 'team-accept TASK')+' --review ACTUAL_DECISION'],
            'RESEARCH':['research-enqueue','research-wait','research-status','research-pause','research-recover','research-finish','crew-review after drain'],
            'COMPLETE':['deliver current verified result'],
            'BLOCKED':['inspect concrete error and its source','repair within authorized scope','record truthful limitation'],
        }
        if kind=='ADVANCE':
            legal[kind]={'PLAN':['crew-execute'], 'EXECUTE':['begin','run-all','crew-review'],
                         'REVIEW':['finish','crew-complete','crew-repair','research-resume when research checkpoint']}[state['phase']]
        result['legal_actions']=[a for a in legal.get(kind,[]) if a]
        previous=self.store.get(owner,'step-metrics',{'calls':0,'local_seconds':0,'actions':{}})
        previous['calls']+=1;previous['local_seconds']+=time.monotonic()-started
        previous['actions'][kind]=previous['actions'].get(kind,0)+1
        self.store.put(owner,'step-metrics',previous)
        result['local_metrics']=previous
        return result
