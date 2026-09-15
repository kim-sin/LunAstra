import candidate
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as d:
    root=Path(d); p=root/'result'; p.write_bytes(b'old')
    for existing in [True,False]:
        q=p if existing else root/'missing'
        for validate in [lambda _:False, lambda _: (_ for _ in ()).throw(RuntimeError('bad'))]:
            before={x.name:x.read_bytes() for x in root.iterdir()}
            try: candidate.publish(q,b'bad',validate)
            except (ValueError,RuntimeError): pass
            else: raise AssertionError('validation rejected but accepted')
            assert {x.name:x.read_bytes() for x in root.iterdir()}==before
    seen=[]
    candidate.publish(p,b'new',lambda data: seen.append(data) or True)
    assert seen==[b'new'] and p.read_bytes()==b'new'
    assert sorted(x.name for x in root.iterdir())==['result']
