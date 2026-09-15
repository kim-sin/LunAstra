import candidate
import math
base=[1,2,3,4,5];values=[9,10]
assert candidate.overlay(base,1,2,values)==[1,9,10,4,5]
assert base==[1,2,3,4,5] and values==[9,10]
assert candidate.overlay(base,5,0,[])==base
for start,width,vals in [(-1,1,[0]),(5,1,[0]),(1,2,[0]),(0,1,[math.nan]),(True,1,[0]),(0,1,[True])]:
    try:candidate.overlay(base,start,width,vals)
    except ValueError:pass
    else:raise AssertionError('invalid overlay accepted')
