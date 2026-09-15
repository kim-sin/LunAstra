import math
def overlay(base,start,width,replacement):
    if type(start) is not int or type(width) is not int or start<0 or width<0 or start+width>len(base):
        raise ValueError('invalid bounds')
    values=list(replacement)
    if len(values)!=width or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):
        raise ValueError('invalid replacement')
    result=list(base);result[start:start+width]=values
    return result
