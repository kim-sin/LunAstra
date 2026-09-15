import os
import tempfile
from pathlib import Path
def publish(path,payload,validate):
    path=Path(path)
    if not validate(payload):
        raise ValueError('invalid payload')
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.publish-')
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
