def advance(stages, completed, run):
    for name,identity in stages:
        if name not in completed:
            result=run(name)
            completed[name]={'identity':identity,'result':result.get('value')}
    return {'completed':completed,'failed':None}
