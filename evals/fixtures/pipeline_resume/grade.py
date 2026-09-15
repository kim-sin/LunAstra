import candidate
from copy import deepcopy
stages=[('prepare','v1'),('transform','v2'),('publish','v1')]
old={'prepare':{'identity':'v1','result':1},'transform':{'identity':'old','result':2}}
before=deepcopy(old);called=[]
def run(name):
    called.append(name)
    return {'ok':False,'value':9} if name=='transform' else {'ok':True,'value':10}
r=candidate.advance(stages,old,run)
assert r=={'completed':old,'failed':'transform'} and called==['transform'] and old==before
called=[]
r=candidate.advance(stages,old,lambda name: called.append(name) or {'ok':True,'value':name})
assert called==['transform','publish'] and r['failed'] is None and old==before
assert r['completed']['transform']=={'identity':'v2','result':'transform'}
assert candidate.advance([],{},run)=={'completed':{},'failed':None}
try:candidate.advance([('x','1'),('x','2')],{},run)
except ValueError:pass
else:raise AssertionError('duplicate accepted')
