def advance(stages, completed, run):
    if len({x[0] for x in stages})!=len(stages):raise ValueError('duplicate stage')
    result=dict(completed)
    for name,identity in stages:
        if name in result and result[name].get('identity')==identity:continue
        value=run(name)
        if value.get('ok') is not True:return {'completed':result,'failed':name}
        result[name]={'identity':identity,'result':value.get('value')}
    return {'completed':result,'failed':None}
