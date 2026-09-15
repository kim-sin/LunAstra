import math
def features(events, t):
    values=[v for ts,v in events if ts<t and math.isfinite(v)]
    return (len(values), math.fsum(values)/len(values)) if values else (0,None)
