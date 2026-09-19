"""Recover missing post hooks from a host-supplied local transcript.

Only exact native call/output pairs from the observed root session are used.
Timeout, missing output, prose and generic handler errors never authorize a
replacement agent. This is an additive receipt reader, not a model launcher.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from .util import HarnessError, canonical, strict_json, json_hash, no_symlinks
from .transport import tool_name

MAX_LINE = 2 * 1024 * 1024
MAX_READ = 8 * 1024 * 1024
# This exact V1 response is emitted when reserve_spawn_slot refuses the call.
# It is not a generic 'error' substring and is never inferred from a timeout.
NO_START = frozenset({'collab spawn failed: agent thread limit reached'})


def _body(value):
    if isinstance(value, str):
        try:
            return strict_json(value)
        except (ValueError, TypeError):
            return value
    return value


def definitely_not_started(kind, response):
    return kind == 'spawn_agent' and isinstance(response, str) and response.strip() in NO_START


def remember(store, owner, event):
    """Keep only location/identity and the call digest, not the command text."""
    path = event.get('transcript_path')
    if not isinstance(path, str) or not path or not Path(path).is_absolute():
        return
    call_id = event.get('tool_use_id')
    if not isinstance(call_id, str) or not call_id:
        return
    with store.db() as db:
        call = db.execute('SELECT * FROM crew_calls WHERE owner=? AND call_id=?', (owner, call_id)).fetchone()
    if not call or store.get(owner, 'native-transcript:' + call_id):
        return
    try:
        source = Path(path); no_symlinks(source)
        st = source.stat()
        if not stat.S_ISREG(st.st_mode):
            return
        with source.open('rb') as stream:
            first = stream.readline(MAX_LINE + 1)
        if len(first) > MAX_LINE:
            return
        record = strict_json(first.decode('utf-8-sig'))
        payload = record.get('payload', {})
        if record.get('type') != 'session_meta' or payload.get('id') != event.get('session_id'):
            return
        # Calls are small and the pre hook runs at dispatch. Keep a bounded
        # look-behind for hosts which persist the function_call before the hook.
        offset = max(len(first), st.st_size - MAX_LINE)
        store.put(owner, 'native-transcript:' + call_id, {
            'path': str(source), 'device': st.st_dev, 'inode': st.st_ino,
            'session': event['session_id'], 'turn': event.get('turn_id'),
            'header_sha256': json_hash(record), 'offset': offset,
            'at_line_boundary': offset == len(first), 'matched_call': False,
            'kind': call['kind'], 'input_hash': call['input_hash'],
            'ticket': call['ticket'],
        })
    except (OSError, ValueError, UnicodeError, AttributeError):
        return  # The absence of an authentic receipt is never success.


def _read_receipt(saved, call_id):
    path = Path(saved['path']); no_symlinks(path)
    with path.open('rb') as stream:
        st = os.fstat(stream.fileno())
        if (st.st_dev, st.st_ino) != (saved['device'], saved['inode']) or st.st_size < saved['offset']:
            raise HarnessError('native transcript replaced or truncated')
        header = stream.readline(MAX_LINE + 1)
        if len(header) > MAX_LINE or not header.endswith(b'\n'):
            raise HarnessError('incomplete native transcript header')
        first = strict_json(header.decode('utf-8-sig'))
        if first.get('type') != 'session_meta' or first.get('payload', {}).get('id') != saved['session'] or json_hash(first) != saved['header_sha256']:
            raise HarnessError('native transcript session changed')
        stream.seek(saved['offset'])
        if not saved['at_line_boundary']:
            stream.readline(MAX_LINE + 1)  # discard the bounded look-behind fragment
        read = 0; matched = saved['matched_call']; turn = saved.get('observed_turn')
        while read < MAX_READ:
            start = stream.tell(); line = stream.readline(MAX_LINE + 1)
            if not line or not line.endswith(b'\n'):
                break  # partial append: retry from the start of this line
            if len(line) > MAX_LINE:
                raise HarnessError('native transcript record exceeds receipt budget')
            read += len(line)
            obj = strict_json(line.decode('utf-8'))
            body = obj.get('payload', {})
            if obj.get('type') == 'turn_context':
                turn = body.get('turn_id')
            if obj.get('type') == 'response_item' and isinstance(body, dict) and body.get('call_id') == call_id:
                if body.get('type') == 'function_call':
                    args = _body(body.get('arguments'))
                    actual_name = body.get('name', '')
                    namespace = body.get('namespace')
                    name = tool_name((namespace + '.' if isinstance(namespace,str) else '') + actual_name)
                    if name != saved['kind'] or json_hash(args) != saved['input_hash']:
                        raise HarnessError('native transcript input does not match the recorded call')
                    if turn is not None and saved.get('turn') is not None and turn != saved['turn']:
                        raise HarnessError('native transcript call belongs to another turn')
                    matched = True
                elif body.get('type') == 'function_call_output' and matched:
                    raw = body.get('output')
                    receipt = {'source': 'HOST_TRANSCRIPT_CALL_OUTPUT', 'call_id': call_id,
                               'line_sha256': json_hash(obj), 'offset': start,
                               'input_hash': saved['input_hash']}
                    return _body(raw), receipt, {**saved, 'offset': stream.tell(), 'matched_call': matched, 'at_line_boundary': True}
            saved = {**saved, 'offset': stream.tell(), 'matched_call': matched, 'at_line_boundary': True, 'observed_turn': turn}
        return None, None, saved


def reconcile(crew, owner):
    """Restore acknowledged identities; release only proven pre-start refusal."""
    store = crew.store; crew._root(owner)
    with store.db() as db:
        pending = [dict(r) for r in db.execute(
            "SELECT c.* FROM crew_calls c JOIN dispatches d ON c.owner=d.owner AND c.call_id=d.call_id "
            "WHERE c.owner=? AND d.state IN ('pending','unknown') ORDER BY c.rowid", (owner,))]
    restored = []; unresolved = []
    for call in pending:
        saved = store.get(owner, 'native-transcript:' + call['call_id'])
        if not isinstance(saved, dict):
            unresolved.append(call['call_id']); continue
        try:
            response, receipt, cursor = _read_receipt(saved, call['call_id'])
            if receipt is not None:
                if definitely_not_started(call['kind'], response):
                    with store.db(True) as db:
                        dispatch = db.execute('SELECT * FROM dispatches WHERE owner=? AND call_id=?', (owner,call['call_id'])).fetchone()
                        row = db.execute('SELECT * FROM work WHERE ticket=?', (call['ticket'],)).fetchone()
                        from .crew import _get
                        current = _get(db,owner)
                        if not dispatch or dispatch['state'] not in {'pending','unknown'} or not row or not current or row['plan_id'] != current['plan_id'] or row['agent_id']:
                            raise HarnessError('native rejection no longer matches an unstarted current assignment')
                        db.execute("UPDATE dispatches SET state='failed' WHERE owner=? AND call_id=?", (owner,call['call_id']))
                        db.execute("INSERT OR REPLACE INTO kv VALUES(?,?,?)", (owner,'native-rejected:'+call['ticket'],canonical({**receipt,'reason':response})))
                    restored.append({'call_id':call['call_id'],'state':'REJECTED_BEFORE_START','retry':'crew-retry after addressing the observed host capacity'})
                else:
                    crew.post_dispatch(owner, call['call_id'], response)
                    with store.db() as db:
                        state = db.execute('SELECT state FROM dispatches WHERE owner=? AND call_id=?',(owner,call['call_id'])).fetchone()[0]
                    if state == 'running':
                        restored.append({'call_id':call['call_id'],'state':'ACK_RECOVERED'})
                    else:
                        unresolved.append(call['call_id'])
                store.put(owner,'native-receipt:'+call['call_id'],receipt)
            else:
                unresolved.append(call['call_id'])
            store.put(owner,'native-transcript:'+call['call_id'],cursor)
        except (OSError, ValueError, KeyError, TypeError, UnicodeError, AttributeError) as exc:
            unresolved.append(call['call_id'])
            store.put(owner,'native-receipt-error:'+call['call_id'],{'code':'RECEIPT_UNCONFIRMED','reason':str(exc)[:500]})
    return {'restored':restored,'unresolved':unresolved,'models_started':0,'models_replaced':0}
