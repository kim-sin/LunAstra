"""Explicitly armed, bounded model-gate diagnostics, outside task storage.

The normal non-Luna route never imports this module. Only a generated wrapper
seeing the private arm marker opts in. Each capture has a time/count budget and
its own file; disabling/unregistering preserves captures. These are hook-argument
observations, not authenticated proof of host identity or model compliance.
"""
from __future__ import annotations
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from . import __version__, __build__
from .model_gate import EVENTS, MODEL_TEXT, classify
from .util import no_symlinks, atomic_write

DEFAULT_SECONDS = 300
DEFAULT_EVENTS = 128
MAX_SECONDS = 900
MAX_EVENTS = 512
_CAPTURE = re.compile(r'[a-f0-9]{32}')
LIMITATION = ('Local hook input/output observations only. No raw prompt, command, file content, '
              'credential or transcript is recorded. This cannot authenticate Desktop/IDE, '
              'prove model-switch compliance, or retract previously injected context.')


def directory(state):
    return Path(state).absolute().parent / 'model-gate-trace'


def marker(state):
    return directory(state) / 'active.json'


def _read_marker(path):
    no_symlinks(path)
    if not path.is_file():return None
    if path.stat().st_size > 512:raise ValueError('invalid diagnostic marker')
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or set(value)!={'capture_id'} or not isinstance(value['capture_id'],str) or not _CAPTURE.fullmatch(value['capture_id']):
        raise ValueError('invalid diagnostic capture identity')
    return value['capture_id']


def _path(state,capture):
    if not isinstance(capture,str) or not _CAPTURE.fullmatch(capture):raise ValueError('invalid diagnostic identity')
    path=directory(state)/('capture-'+capture+'.sqlite3');no_symlinks(path)
    return path


@contextmanager
def _control(state):
    """Serialize explicit start/stop without breaking another operator's lock."""
    root=directory(state);no_symlinks(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=root/'control.lock';no_symlinks(path)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        os.close(fd)
        yield
    finally:path.unlink()


def _disarm(state,capture):
    # Marker changes are serialized with operator start/stop. Never remove a new capture.
    with _control(state):
        if _read_marker(marker(state))==capture:marker(state).unlink()


def enable(state,seconds=DEFAULT_SECONDS,max_events=DEFAULT_EVENTS):
    if type(seconds) is not int or not 1<=seconds<=MAX_SECONDS:raise ValueError('trace seconds must be 1..900')
    if type(max_events) is not int or not 1<=max_events<=MAX_EVENTS:raise ValueError('trace events must be 1..512')
    with _control(state):
        old=_read_marker(marker(state))
        if old:
            previous=status(state,capture=old)
            if previous['armed']:return {**previous,'already_armed':True}
        capture=uuid.uuid4().hex;path=_path(state,capture)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        now=time.time()
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1), started REAL, expires REAL, max_events INTEGER, salt TEXT, stopped INTEGER)')
            db.execute('INSERT INTO settings VALUES(1,?,?,?,?,0)',(now,now+seconds,max_events,os.urandom(32).hex()))
            db.execute('CREATE TABLE observations (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL)')
            db.commit()
        raw=(json.dumps({'capture_id':capture})+'\n').encode('utf-8')
        atomic_write(directory(state)/'latest.json',raw)
        atomic_write(marker(state),raw)
    return status(state,capture=capture)


def disable(state):
    if not directory(state).exists():return {'armed':False,'captures_preserved':True}
    with _control(state):
        capture=_read_marker(marker(state))
        if capture:
            path=_path(state,capture)
            if path.is_file():
                with closing(sqlite3.connect(path,timeout=0.2)) as db:
                    db.execute('UPDATE settings SET stopped=1 WHERE id=1');db.commit()
            marker(state).unlink()
    return {'armed':False,'capture_id':capture,'captures_preserved':True}


def _settings(db):
    row=db.execute('SELECT started,expires,max_events,salt,stopped FROM settings WHERE id=1').fetchone()
    if (not row or any(type(v) not in (int,float) or not math.isfinite(v) for v in row[:2])
            or not 0<row[1]-row[0]<=MAX_SECONDS or type(row[2]) is not int or not 1<=row[2]<=MAX_EVENTS
            or not isinstance(row[3],str) or not re.fullmatch('[a-f0-9]{64}',row[3]) or row[4] not in (0,1)):
        raise ValueError('invalid diagnostic limits')
    return row


def _identifier(salt,value):
    if not isinstance(value,str) or not 1<=len(value)<=4096:return None
    return hmac.new(bytes.fromhex(salt),value.encode('utf-8'),hashlib.sha256).hexdigest()[:32]


def record(state,event,output,*,state_created=False,failed=False):
    """Never creates task storage. Caller ignores errors without altering output."""
    capture=_read_marker(marker(state))
    if not capture:return
    path=_path(state,capture)
    if not path.is_file():return
    done=False
    with closing(sqlite3.connect(path,timeout=0.05,isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            started,expires,limit,salt,stopped=_settings(db)
            count=db.execute('SELECT count(*) FROM observations').fetchone()[0]
            now=time.time()
            if stopped or now<started or now>=expires or count>=limit:
                done=True
            else:
                e=event if isinstance(event,dict) else {}
                model=e.get('model')
                model=model if isinstance(model,str) and MODEL_TEXT.fullmatch(model) else None
                specific=output.get('hookSpecificOutput',{}) if isinstance(output,dict) else {}
                content=specific.get('additionalContext') if isinstance(specific,dict) else None
                agent=e.get('agent_id');session=e.get('session_id')
                kind=e.get('hook_event_name')
                kind=kind if isinstance(kind,str) and kind in EVENTS else 'UNKNOWN'
                item={'timestamp':now,'hook_event_name':kind,
                      'model':model,'session_hash':_identifier(salt,session),'agent_hash':_identifier(salt,agent),
                      'role':'worker' if isinstance(agent,str) and agent else ('root' if agent is None and isinstance(session,str) and session else 'UNKNOWN'),
                      'classifier':classify(e.get('model')),
                      'additional_context_emitted':bool(isinstance(content,str) and content),
                      'kernel_emitted':bool(isinstance(content,str) and 'LOCAL_HELPER_ARGV=' in content),
                      'state_created':bool(state_created),'handler_failed':bool(failed),
                      'version':__version__,'build':__build__}
                db.execute('INSERT INTO observations(data) VALUES(?)',(json.dumps(item,separators=(',',':')),))
                done=count+1>=limit
            if done:db.execute('UPDATE settings SET stopped=1 WHERE id=1')
            db.commit()
        except BaseException:
            db.rollback();raise
    if done:
        # A failed cleanup can only cause an extra diagnostic startup; DB budget still holds.
        try:_disarm(state,capture)
        except (OSError,ValueError,sqlite3.Error):pass


_RECORD_FIELDS={'timestamp','hook_event_name','model','session_hash','agent_hash','role','classifier',
                'additional_context_emitted','kernel_emitted','state_created','handler_failed','version','build'}


def _observation(raw):
    """Refuse corrupt records instead of exporting attacker-chosen free text."""
    if not isinstance(raw,str) or len(raw)>4096:raise ValueError('invalid diagnostic observation')
    from .util import strict_json
    value=strict_json(raw)
    if not isinstance(value,dict) or set(value)!=_RECORD_FIELDS:raise ValueError('invalid diagnostic fields')
    if type(value['timestamp']) not in (int,float) or not math.isfinite(value['timestamp']):raise ValueError('invalid diagnostic timestamp')
    if not isinstance(value['hook_event_name'],str) or value['hook_event_name'] not in EVENTS|{'UNKNOWN'}:raise ValueError('invalid diagnostic event')
    model=value['model']
    if model is not None and (not isinstance(model,str) or not MODEL_TEXT.fullmatch(model)):raise ValueError('invalid diagnostic model')
    for name in ('session_hash','agent_hash'):
        if value[name] is not None and (not isinstance(value[name],str) or not re.fullmatch('[a-f0-9]{32}',value[name])):raise ValueError('invalid diagnostic hash')
    if not isinstance(value['role'],str) or value['role'] not in {'root','worker','UNKNOWN'}:raise ValueError('invalid diagnostic role')
    if value['classifier']!=classify(model):raise ValueError('inconsistent diagnostic classification')
    for name in ('additional_context_emitted','kernel_emitted','state_created','handler_failed'):
        if type(value[name]) is not bool:raise ValueError('invalid diagnostic boolean')
    if not isinstance(value['version'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',value['version']):raise ValueError('invalid diagnostic version')
    if not isinstance(value['build'],str) or not re.fullmatch('[A-Za-z0-9._-]{1,80}',value['build']):raise ValueError('invalid diagnostic build')
    return value


def status(state,*,capture=None,include_records=False):
    """Read-only, including after expiry. No directory, database or marker creation."""
    result={'armed':False,'capture_id':None,'events_recorded':0,'observations':[],
            'scope':LIMITATION,'live_host_verified':False,'actual_host_kind':'UNKNOWN'}
    if capture is None:capture=_read_marker(directory(state)/'latest.json')
    if not capture:return result
    path=_path(state,capture)
    if not path.is_file():return {**result,'status':'CAPTURE_UNAVAILABLE'}
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=0.1)) as db:
        db.execute('PRAGMA query_only=ON')
        started,expires,limit,salt,stopped=_settings(db)
        rows=db.execute('SELECT data FROM observations ORDER BY seq LIMIT ?',(MAX_EVENTS+1,)).fetchall()
    if len(rows)>limit:raise ValueError('diagnostic count exceeds capture limit')
    records=[_observation(row[0]) for row in rows]
    now=time.time()
    armed=not stopped and started<=now<expires and len(records)<limit and _read_marker(marker(state))==capture
    result.update(armed=armed,capture_id=capture,events_recorded=len(records),max_events=limit,
                  started_at=started,expires_at=expires,
                  status='ARMED' if armed else 'STOPPED_OR_EXPIRED',
                  classifications={c:sum(r.get('classifier')==c for r in records) for c in ('LUNA','NON_LUNA','UNKNOWN')},
                  observed_models=sorted({r['model'] for r in records if r.get('model')}),
                  diagnostic_directory=str(directory(state)),
                  non_luna_task_side_effect_seen=any(r.get('classifier')!='LUNA' and (r.get('state_created') or r.get('additional_context_emitted')) for r in records))
    if include_records:
        # Allowlist output again; never export arbitrary fields from a modified capture DB.
        fields=_RECORD_FIELDS
        result['observations']=[{k:v for k,v in r.items() if k in fields} for r in records]
    return result


def export_report(state):
    result=status(state,include_records=True)
    result.pop('diagnostic_directory',None)  # Export carries no personal filesystem path.
    if not result.get('capture_id'):raise ValueError('no model-gate capture exists')
    path=directory(state)/('report-'+result['capture_id']+'.json')
    no_symlinks(path)
    atomic_write(path,(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    return {'report_path':str(path),'events_recorded':result['events_recorded'],
            'armed':result['armed'],'scope':LIMITATION,'live_host_verified':False}
