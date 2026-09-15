from pathlib import Path
def publish(path,payload,validate):
    Path(path).write_bytes(payload)
    if not validate(payload):
        raise ValueError('invalid payload')
