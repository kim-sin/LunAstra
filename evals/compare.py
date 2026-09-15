#!/usr/bin/env python3
"""Offline paired real-task comparison. Records are operator supplied, not model calls."""
from __future__ import annotations
import argparse
import math
import random
import statistics
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from luna_astra.util import HarnessError, canonical, file_hash, inside, load_json

ARMS={'luna_stock','luna_astra'}

def compare(records, trace_root: Path, reference='luna_stock'):
    if reference not in {'luna_stock','astra_reference'}:raise HarnessError('invalid reference arm')
    arms={reference,'luna_astra'}
    if not isinstance(records,list):raise HarnessError('records must be a list')
    grouped={}
    required={'task_id','trial_id','arm','condition_id','model_id','reasoning_setting','success','source_trace','source_trace_sha256'}
    optional={'wall_seconds','credits','input_tokens','output_tokens','caller_rework','user_interventions','failure_category'}
    for r in records:
        if not isinstance(r,dict) or set(r)-required-optional or not required<=set(r):raise HarnessError('invalid comparison record fields')
        for k in required-{'success'}:
            if not isinstance(r[k],str) or not r[k]:raise HarnessError('invalid record string: '+k)
        if r['arm'] not in arms or type(r['success']) is not bool:raise HarnessError('invalid arm or success')
        for k in optional-{'failure_category'}:
            v=r.get(k)
            if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v<0):raise HarnessError('invalid metric: '+k)
        if 'failure_category' in r and not isinstance(r['failure_category'],str):raise HarnessError('invalid failure category')
        trace=inside(trace_root,r['source_trace'])
        if file_hash(trace)!=r['source_trace_sha256']:raise HarnessError('trace identity mismatch')
        key=(r['task_id'],r['trial_id'])
        pair=grouped.setdefault(key,{})
        if r['arm'] in pair:raise HarnessError('duplicate arm for task/trial')
        pair[r['arm']]=r
    pairs=[];unmatched=[]
    for key,pair in grouped.items():
        if set(pair)!=arms:unmatched.append(list(key));continue
        a,b=pair[reference],pair['luna_astra']
        for field in (('model_id','reasoning_setting','condition_id') if reference=='luna_stock' else ('condition_id',)):
            if a[field]!=b[field]:raise HarnessError('unmatched comparison condition: '+field)
        pairs.append((a,b))
    n=len(pairs);deltas=[int(b['success'])-int(a['success']) for a,b in pairs]
    metrics={}
    for key in ('wall_seconds','credits','input_tokens','output_tokens','caller_rework','user_interventions'):
        common=[(a[key],b[key]) for a,b in pairs if a.get(key) is not None and b.get(key) is not None]
        metrics[key]={'paired_observations':len(common),'reference_sum':sum(a for a,b in common) if common else None,'stock_sum':sum(a for a,b in common) if common and reference=='luna_stock' else None,
                      'enhanced_sum':sum(b for a,b in common) if common else None,
                      'median_pair_difference':statistics.median(b-a for a,b in common) if common else None}
    categories={}
    for a,b in pairs:
        if not b['success']:
            category=b.get('failure_category','unclassified');categories[category]=categories.get(category,0)+1
    return {'reference_arm':reference,'comparison_type':'same-model ablation' if reference=='luna_stock' else 'different-model system comparison','paired_tasks':n,'unmatched_tasks':unmatched,
            'reference_successes':sum(a['success'] for a,b in pairs),'stock_successes':sum(a['success'] for a,b in pairs) if reference=='luna_stock' else None,'enhanced_successes':sum(b['success'] for a,b in pairs),
            'enhanced_only_successes':deltas.count(1),'stock_only_successes':deltas.count(-1),
            'paired_success_difference':sum(deltas)/n if n else None,'metrics':metrics,'enhanced_failure_categories':categories,
            'parity':'NOT_ESTABLISHED','automatic_prompt_updates':False,
            'evidence_limit':'Numbers/labels are operator-supplied and bound to trace files by hash, not independently verified interpretations. Require unseen tasks, fixed acceptance tests and blinded review. Missing measurements are not zero.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('records',type=Path);p.add_argument('--trace-root',type=Path,required=True)
    p.add_argument('--reference',choices=['luna_stock','astra_reference'],default='luna_stock')
    a=p.parse_args()
    try:print(canonical(compare(load_json(a.records),a.trace_root.resolve(),a.reference)));return 0
    except (OSError,ValueError,TypeError,KeyError) as e:print(canonical({'error':str(e)}),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
