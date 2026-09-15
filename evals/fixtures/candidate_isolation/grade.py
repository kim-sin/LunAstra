import candidate
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import shared
specs=[{'name':'a','multiplier':2},{'name':'b','multiplier':7}]
before=deepcopy(specs); default=deepcopy(shared.DEFAULT_CONTEXT); run=shared.run
with ThreadPoolExecutor(max_workers=4) as pool:
    results=list(pool.map(lambda i: candidate.run_batch(specs,i), range(8)))
assert results==[[2*i,7*i] for i in range(8)]
assert specs==before and shared.DEFAULT_CONTEXT==default and shared.run is run
assert shared.CALLS>=16, 'existing engine was not reused'
try: candidate.run_batch([specs[0],specs[0]],1)
except ValueError: pass
else: raise AssertionError('duplicate accepted')
assert candidate.run_batch([],3)==[]
