import shared
def run_batch(specs, value):
    result=[]
    for spec in specs:
        shared.DEFAULT_CONTEXT.update(spec)
        result.append(shared.run(shared.DEFAULT_CONTEXT, value))
    return result
