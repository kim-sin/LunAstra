"""Idempotent bounded JSON staging for native Windows command-line limits.

Stored only under the caller's local session. No arbitrary filesystem paths,
command evaluation, network I/O, or model calls. Offsets prevent retry duplication.
"""
from __future__ import annotations
import re
from .util import HarnessError, strict_json, canonical
MAX_BYTES=2*1024*1024

def _name(name):
    if not isinstance(name,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,47}',name):
        raise HarnessError('input reference must be a short lowercase name')
    return 'input:'+name

def append(store,key,name,offset,chunk):
    name=_name(name)
    if type(offset) is not int or offset<0 or not isinstance(chunk,str) or not chunk or len(chunk)>1000:
        raise HarnessError('input chunks require a nonnegative character offset and 1..1000 characters')
    with store.db(True) as db:
        row=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(key,name)).fetchone()
        old=strict_json(row[0]) if row else ''
        if not isinstance(old,str):raise HarnessError('corrupt input buffer')
        if offset<len(old) and old[offset:offset+len(chunk)]==chunk:
            return {'characters':len(old),'retry_reused':True}
        if offset!=len(old):raise HarnessError('input offset mismatch; do not duplicate or overwrite a staged request')
        new=old+chunk
        if len(new.encode('utf-8'))>MAX_BYTES:raise HarnessError('input buffer exceeds 2 MiB')
        db.execute('INSERT INTO kv VALUES(?,?,?) ON CONFLICT(scope,name) DO UPDATE SET value=excluded.value',(key,name,canonical(new)))
    return {'characters':len(new),'retry_reused':False}

def read(store,key,name):
    if isinstance(name,str) and name.startswith('sha256:'):
        from .requests import read as read_request
        return read_request(store.directory,key,name)
    raw=store.get(key,_name(name))
    if not isinstance(raw,str) or len(raw.encode('utf-8'))>MAX_BYTES:raise HarnessError('missing or corrupt input buffer')
    try:
        strict_json(raw)
    except (ValueError, RecursionError) as exc:
        raise HarnessError('staged input is not complete valid JSON') from exc
    return raw
