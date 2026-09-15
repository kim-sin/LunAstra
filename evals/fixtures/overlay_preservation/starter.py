def overlay(base,start,width,replacement):
    base[start:start+width]=replacement
    return base
