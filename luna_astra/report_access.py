"""Current full-report delivery receipts; never evidence of model comprehension."""
from __future__ import annotations
import time
from .util import HarnessError, json_hash, canonical, strict_json


def detail_required(report):
    return bool(report) and (report['verdict']!='clear' or
        len(report.get('summary',''))>512 or
        sum(len(f) for f in report.get('findings',[]))>2000 or
        len(report.get('references',[]))>4 or
        any(isinstance(v,str) and len(v)>256 for ref in report.get('references',[]) for v in ref.values()))


def _identity(state, ticket, report):
    return {'run_id':state['run_id'],'plan_id':state['plan_id'],'round':state['round'],
            'ticket':ticket,'report_sha256':json_hash(report)}


def delivered(db, owner, state, ticket, report):
    if report is None:return
    current=db.execute('SELECT body FROM crew_reports WHERE ticket=?',(ticket,)).fetchone()
    if current is None or strict_json(current[0])!=report:
        raise HarnessError('report changed during retrieval; request its current full content',code='REPORT_CHANGED')
    identity=_identity(state,ticket,report)
    db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)',
               (owner,'report-delivered:'+ticket,canonical({**identity,'delivered_at':time.time()})))


def missing(db, owner, state, tasks=None):
    result=[]
    for row in state['tasks'] if tasks is None else tasks:
        report=state['reports'].get(row['ticket'])
        current=db.execute('SELECT body FROM crew_reports WHERE ticket=?',(row['ticket'],)).fetchone()
        if (strict_json(current[0]) if current else None)!=report:
            raise HarnessError('report changed before the decision; refresh the current crew state',code='REPORT_CHANGED')
        if not detail_required(report):continue
        receipt=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',
                           (owner,'report-delivered:'+row['ticket'])).fetchone()
        value=strict_json(receipt[0]) if receipt else {}
        identity=_identity(state,row['ticket'],report)
        if any(value.get(k)!=v for k,v in identity.items()):result.append(row['id'])
    return result


def require(db, owner, state, tasks=None):
    slots=missing(db,owner,state,tasks)
    if slots:
        raise HarnessError('Read the current full issue/truncated reports before deciding: '+', '.join(slots),
                           code='REPORT_DETAILS_REQUIRED',
                           details={'slots':slots,'read_all_command':'crew-step --details',
                                    'receipt_attests':'delivery, not model understanding'})
