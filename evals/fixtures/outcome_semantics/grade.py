import candidate, math
assert candidate.bucket({'action':'SKIP','score':99})=='NOT_APPLICABLE'
assert candidate.bucket({'status':'cancelled','elapsed':0})=='CANCELLED'
assert candidate.bucket({'status':'pending','score':99})=='UNKNOWN'
for value,expected in [(-1,'NEGATIVE'),(0,'ZERO'),(0.5,'UNDER'),(1,'EXACT'),(2,'OVER')]:
    row={'status':'finished','elapsed':value,'budget':1,'score':-999}
    assert candidate.bucket(row)==expected
for update in [{'elapsed':math.nan},{'budget':0},{'budget':None},{'elapsed':True}]:
    row={'status':'finished','elapsed':1,'budget':100};row.update(update)
    assert candidate.bucket(row)=='UNKNOWN'
