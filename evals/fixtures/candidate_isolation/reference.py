import shared
def run_batch(specs, value):
    if len({s['name'] for s in specs}) != len(specs):
        raise ValueError('duplicate name')
    return [shared.run(dict(spec), value) for spec in specs]
