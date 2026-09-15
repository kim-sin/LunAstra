import time
DEFAULT_CONTEXT={'name':'baseline','multiplier':1}
CALLS=0
def run(context, value):
    global CALLS
    CALLS += 1
    time.sleep(0.003)
    return context['multiplier']*value
