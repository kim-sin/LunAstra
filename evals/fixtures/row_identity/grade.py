import candidate
from copy import deepcopy
rows = [{'group':'b','position':0}, {'group':'a','position':0}, {'group':'b','position':1}]
outcomes = [{'group':'a','position':0,'outcome':0}, {'group':'b','position':0,'outcome':-3}]
before=deepcopy((rows,outcomes))
assert [r['outcome'] for r in candidate.join_rows(rows,outcomes)] == [-3,0,None]
assert (rows,outcomes)==before
assert candidate.join_rows([],[])==[]
for a,b in [(rows+[rows[0]],outcomes),(rows,outcomes+[outcomes[0]])]:
    try: candidate.join_rows(a,b)
    except ValueError: pass
    else: raise AssertionError('duplicate accepted')
