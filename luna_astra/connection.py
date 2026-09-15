"""Bounded hook-traffic observations and read-only connection diagnostics.

These records describe local input and output. They cannot authenticate a host,
prove hook output was consumed, or certify model quality or a security sandbox.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import math
import os
from pathlib import Path
import sqlite3
import time

from .transport import tool_name
from .util import HarnessError, canonical, json_hash, no_symlinks, strict_json

SCHEMA = '''CREATE TABLE IF NOT EXISTS hook_observations (
 release TEXT NOT NULL, identity TEXT NOT NULL, observed_at REAL NOT NULL,
 data TEXT NOT NULL, PRIMARY KEY(release,identity))'''
READ_LIMIT = 200
WRITE_TIMEOUT = 0.05
TOOLS = {'Bash', 'apply_patch', 'exec_command', 'spawn_agent', 'wait_agent'}
EVENTS = {'SessionStart', 'SubagentStart', 'UserPromptSubmit', 'PreToolUse',
          'PostToolUse', 'Stop', 'SubagentStop', 'PostCompact', 'Interrupt'}


def release_identity(package: Path) -> str:
    return os.path.normcase(str(Path(package).resolve()))


@contextmanager
def observation_db(state: Path):
    """Diagnostics must not inherit the task store's longer lock wait."""
    path=Path(state).absolute()/'runtime.sqlite3'
    no_symlinks(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path,timeout=WRITE_TIMEOUT,isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def record_hook(state: Path, package: Path, event: dict, output: dict | None,
                *, failed: bool = False) -> None:
    """Record no prompts, commands, file contents, tokens, or transcript paths."""
    if not isinstance(event, dict) or event.get('hook_event_name') not in EVENTS:
        return
    session, model, agent = event.get('session_id'), event.get('model'), event.get('agent_id')
    if not isinstance(session, str) or not 1 <= len(session) <= 4096:
        return
    if not isinstance(model, str) or len(model) > 200:
        return
    if agent is not None and (not isinstance(agent, str) or not 1 <= len(agent) <= 4096):
        return
    kind = event['hook_event_name']
    release = release_identity(package)
    identity = json_hash([session, agent, event.get('cwd'), model])
    with observation_db(state) as db:
        db.execute(SCHEMA)
        row = db.execute('SELECT data FROM hook_observations WHERE release=? AND identity=?',
                         (release, identity)).fetchone()
        data = strict_json(row[0]) if row else {
            'model': model, 'role': 'worker' if agent else 'root', 'events': [],
            'kernel_emitted': False, 'tool_cycle_seen': False, 'paired_tools': [],
            'pending': {}, 'last_error': False, 'last_error_at': None, 'last_guard_denied': False,
            'kernel_emitted_at': None, 'tool_cycle_started_at': None, 'tool_cycle_at': None}
        if not isinstance(data, dict) or not isinstance(data.get('pending'), dict):
            raise HarnessError('Invalid connection observation record.')
        now = time.time()
        if failed:
            data.update(last_error=True, last_error_at=now, tool_cycle_seen=False,
                        tool_cycle_started_at=None, tool_cycle_at=None, pending={})
        data['events'] = sorted(set(data['events']) | {kind})
        specific = (output or {}).get('hookSpecificOutput', {})
        content = specific.get('additionalContext', '')
        if isinstance(content, str) and 'LOCAL_HELPER_ARGV=' in content:
            data['kernel_emitted'] = True
            data['kernel_emitted_at'] = now
        denied = specific.get('permissionDecision') == 'deny'
        data['last_guard_denied'] = denied
        name = tool_name(event.get('tool_name', ''))
        uid = event.get('tool_use_id')
        if isinstance(uid, str) and uid and name in TOOLS:
            call = json_hash([event.get('turn_id'), uid])
            if failed or (kind == 'PreToolUse' and denied):
                data['pending'].pop(call, None)
            elif kind == 'PreToolUse':
                # Bounded bookkeeping; losing an old unmatched call only makes
                # the diagnostic less conclusive, never falsely successful.
                pending = data['pending']
                if len(pending) >= 32 and call not in pending:
                    pending.pop(next(iter(pending)))
                pending[call] = {'tool': name, 'at': now}
            elif kind == 'PostToolUse':
                before = data['pending'].pop(call, None)
                if isinstance(before,dict) and before.get('tool')==name:
                    data['tool_cycle_seen'] = True
                    data['last_error'] = False
                    data['last_error_at'] = None
                    data['tool_cycle_started_at'] = before['at']
                    data['tool_cycle_at'] = now
                    data['paired_tools'] = sorted(set(data['paired_tools']) | {name})
        db.execute('INSERT INTO hook_observations VALUES(?,?,?,?) '
                   'ON CONFLICT(release,identity) DO UPDATE SET '
                   'observed_at=excluded.observed_at,data=excluded.data',
                   (release, identity, now, canonical(data)))


def connection_status(state: Path, package: Path, *, since: float = 0.0) -> dict:
    """Read only this release's observations. Never create a store or run checks."""
    result = {'status': 'WAITING_FOR_LUNA', 'sessions': [], 'session_count': 0,
              'worker_sessions': 0, 'kernel_sessions': 0, 'tool_cycle_sessions': 0,
              'error_sessions': 0, 'history_truncated': False, 'last_observed_at': None,
              'since': since, 'live_verified': False,
              'scope': 'Local hook traffic for this installed payload; not independent host or model certification.'}
    path = Path(state) / 'runtime.sqlite3'
    no_symlinks(path)
    if not path.is_file():
        return result
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kv'").fetchone():
                for index, (raw,) in enumerate(db.execute("SELECT value FROM kv WHERE name='meta'")):
                    if index>=10000 or not isinstance(strict_json(raw),dict):
                        raise HarnessError('Invalid or oversized session metadata.')
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hook_observations'").fetchone():
                result['status'] = 'WAITING_FOR_CURRENT_RELEASE'
                return result
            release = release_identity(package)
            count = db.execute('SELECT count(*) FROM hook_observations WHERE release=? AND observed_at>=?',
                               (release, since)).fetchone()[0]
            rows = db.execute('SELECT observed_at,data FROM hook_observations '
                              'WHERE release=? AND observed_at>=? ORDER BY observed_at DESC LIMIT ?',
                              (release, since, READ_LIMIT)).fetchall()
            result['session_count'] = count
            result['history_truncated'] = count > READ_LIMIT
        for at, raw in rows:
            data = strict_json(raw)
            if (not isinstance(data, dict) or data.get('role') not in {'root', 'worker'}
                    or not isinstance(data.get('model'), str)
                    or not isinstance(data.get('events'), list)
                    or any(not isinstance(x, str) or x not in EVENTS for x in data['events'])
                    or any(type(data.get(k)) is not bool for k in ('kernel_emitted', 'tool_cycle_seen', 'last_error', 'last_guard_denied'))
                    or type(at) not in (float, int) or not math.isfinite(at) or not 0<=at<=253402300799):
                raise HarnessError('Invalid connection observation record.')
            times=[data.get(k) for k in ('kernel_emitted_at','tool_cycle_started_at','tool_cycle_at','last_error_at')]
            if any(v is not None and (type(v) not in (float,int) or not math.isfinite(v) or not 0<=v<=at) for v in times):
                raise HarnessError('Invalid connection capability timestamps.')
            if data['last_error'] and times[3] is None:
                raise HarnessError('A connection error has no timestamp.')
            data['last_error']=bool(data['last_error'] and times[3]>=since)
            data['kernel_emitted']=bool(data['kernel_emitted'] and times[0] is not None and times[0]>=since)
            data['tool_cycle_seen']=bool(data['tool_cycle_seen'] and times[1] is not None and times[2] is not None
                                         and since<=times[1]<=times[2])
            result['sessions'].append({k: data[k] for k in (
                'model', 'role', 'events', 'kernel_emitted', 'tool_cycle_seen', 'last_error', 'last_guard_denied')})
            result['worker_sessions'] += data['role'] == 'worker'
            result['kernel_sessions'] += data['kernel_emitted']
            result['tool_cycle_sessions'] += data['tool_cycle_seen'] and data['kernel_emitted']
            result['error_sessions'] += data['last_error']
            if result['last_observed_at'] is None:
                result['last_observed_at'] = at
        if result['error_sessions']:
            result['status'] = 'HOOK_ERRORS_OBSERVED'
        elif result['tool_cycle_sessions']:
            result['status'] = 'TOOL_CYCLE_OBSERVED'
        elif result['kernel_sessions']:
            result['status'] = 'LUNA_EVENTS_OBSERVED'
        elif result['sessions']:
            result['status'] = 'EVENTS_WITHOUT_KERNEL'
        else:
            result['status'] = 'WAITING_FOR_CURRENT_RELEASE'
    except (OSError, ValueError, TypeError, sqlite3.Error):
        result.update(status='DIAGNOSTICS_UNREADABLE', sessions=[], session_count=0,
                      worker_sessions=0, kernel_sessions=0, tool_cycle_sessions=0,
                      error_sessions=0, last_observed_at=None)
    return result
