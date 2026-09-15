import candidate
import math
args=[b'ab',{'cols':['x','y'],'version':1},'policy-a',12,{'counter':5,'queued':0}]
base=candidate.key(*args)
assert isinstance(base,str) and len(base)==64
assert candidate.key(*args)==base
assert candidate.key(b'ab',{'version':1,'cols':['x','y']},'policy-a',12,{'queued':0,'counter':5})==base
for i,replacement in enumerate([b'ac',{'cols':['y','x'],'version':1},'policy-b',13,{'counter':5,'queued':1}]):
    changed=list(args); changed[i]=replacement
    assert candidate.key(*changed)!=base
try: candidate.key(b'x',{},'p',1,{'x':math.nan})
except (TypeError,ValueError): pass
else: raise AssertionError('nonfinite accepted')
try: candidate.key('x',{},'p',1,{})
except TypeError: pass
else: raise AssertionError('source str accepted')
