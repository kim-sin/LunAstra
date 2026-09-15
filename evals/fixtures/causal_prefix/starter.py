def features(events, t):
    values = [value for timestamp,value in events if timestamp <= t]
    return len(values), sum(values)/len(values) if values else 0
