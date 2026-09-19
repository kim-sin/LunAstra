"""V2 wait/list observation ledger. Mailbox wake != completed checked work."""
from __future__ import annotations
import time
from .util import HarnessError, canonical, strict_json, json_hash
from .team import unpack_response
from .native import target_in, is_v2

SCHEMA='''CREATE TABLE IF NOT EXISTS native_observations (
 owner TEXT,call_id TEXT,kind TEXT,plan_id TEXT,input_hash TEXT,snapshot TEXT,
 finished REAL,result_hash TEXT,valid INTEGER,started REAL NOT NULL DEFAULT 0,PRIMARY KEY(owner,call_id));'''


def wait_call(state, agents):
    return {'tool':'wait_agent','arguments':{'timeout_ms':60000} if is_v2(state) else
            {'targets':agents,'timeout_ms':60000}}


class NativeFlow:
    def __init__(self, store, crew):
        self.store=store;self.crew=crew
        store.ensure_schema('native_observations', SCHEMA)
        with store.db(True) as db:
            if 'started' not in {row[1] for row in db.execute('PRAGMA table_info(native_observations)')}:
                db.execute('ALTER TABLE native_observations ADD COLUMN started REAL NOT NULL DEFAULT 0')

    def pre(self, owner, call_id, kind, payload):
        from .flow import _epoch
        state,_=self.crew._current(owner)
        if not is_v2(state):raise HarnessError('V2 observation used on a V1 crew')
        if not isinstance(payload,dict):raise HarnessError('invalid native observation input')
        if kind=='wait_agent':
            if set(payload)-{'timeout_ms'}:raise HarnessError('V2 wait accepts timeout_ms only; targets are not supported')
            value=payload.get('timeout_ms',60000)
            if type(value) is not int or not 1<=value<=300000:raise HarnessError('invalid native timeout')
        elif kind=='list_agents':
            if set(payload)-{'path_prefix'}:raise HarnessError('invalid list_agents input')
            value=payload.get('path_prefix')
            if value is not None and (not isinstance(value,str) or not value.startswith('/') or '..' in value.split('/')):
                raise HarnessError('invalid agent path prefix')
        else:raise HarnessError('unsupported native observation')
        with self.store.db(True) as db:
            old=db.execute('SELECT * FROM native_observations WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if old:
                if old['input_hash']!=json_hash(payload) or old['kind']!=kind:raise HarnessError('native observation call identity reused')
                return
            snapshot={}
            for row in state['tasks']:
                if not row['ticket']:continue
                handle=target_in(db,owner,int(row['id'][1:]),row['agent_id'])
                if handle:
                    snapshot[handle]={'ticket':row['ticket'],'agent_id':row['agent_id'],'epoch':_epoch(db,row['ticket'])}
            db.execute('INSERT INTO native_observations(owner,call_id,kind,plan_id,input_hash,snapshot,finished,result_hash,valid,started) VALUES(?,?,?,?,?,?,NULL,NULL,0,?)',
                       (owner,call_id,kind,state['plan_id'],json_hash(payload),canonical(snapshot),time.time()))

    def post(self, owner, call_id, kind, response):
        from .crew import _get
        from .flow import _epoch, _kv
        result=unpack_response(response)
        error=isinstance(response,dict) and (response.get('isError') is True or response.get('is_error') is True)
        with self.store.db(True) as db:
            call=db.execute('SELECT * FROM native_observations WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
            if not call:return
            digest=json_hash(response)
            if call['kind']!=kind:raise HarnessError('native observation kind mismatch')
            if call['finished'] is not None:
                if call['result_hash']!=digest:raise HarnessError('native observation changed for same call')
                return
            state=_get(db,owner);active=bool(state and state['plan_id']==call['plan_id'])
            valid=False
            if active and not error and kind=='wait_agent':
                valid=type(result.get('timed_out')) is bool and isinstance(result.get('message'),str)
                if valid:
                    # A mailbox result supplies no status. Observe actual names next.
                    _kv(db,owner,'native-list-due',{'plan_id':state['plan_id'],'after_wait':call_id})
            elif active and not error and kind=='list_agents':
                agents=result.get('agents');snapshot=strict_json(call['snapshot'])
                valid=isinstance(agents,list) and len(agents)<=1024
                seen=set();observations=[]
                if valid:
                    for item in agents:
                        if not isinstance(item,dict) or not isinstance(item.get('agent_name'),str):valid=False;break
                        name=item['agent_name']
                        if name in seen:valid=False;break
                        seen.add(name)
                        if name not in snapshot:continue  # Unrelated host agents are never ours.
                        status=item.get('agent_status');native=None
                        if isinstance(status,dict) and set(status)=={'completed'} and (status['completed'] is None or isinstance(status['completed'],str)):
                            native='completed'
                        elif isinstance(status,dict) and set(status)=={'errored'} and isinstance(status['errored'],str):native='errored'
                        elif isinstance(status,str) and status in {'running','pending_init','interrupted','shutdown','not_found'}:native=status
                        if native is None:valid=False;break
                        observations.append((name,native,snapshot[name]))
                if valid:
                    for name,native,saved in observations:
                        row=db.execute('SELECT * FROM work WHERE ticket=?',(saved['ticket'],)).fetchone()
                        if not row or row['plan_id']!=state['plan_id'] or _epoch(db,saved['ticket'])!=saved['epoch']:continue
                        _kv(db,owner,'flow-native:'+saved['ticket'],
                            {'state':native,'agent_id':row['agent_id'],'native_target':name,'ticket':saved['ticket'],
                             'epoch':saved['epoch'],'plan_id':state['plan_id'],'call_id':call_id,'at':time.time()})
                        failure=native in {'errored','interrupted','shutdown','not_found'}
                        if ((native=='completed' and row['state'] in {'running','reserved'}) or
                            (failure and row['state'] in {'running','reserved','returned','accepted'})):
                            terminal='failed' if failure else 'returned'
                            handback={'status':'UNVERIFIED','native_status':native,
                                      'reason':'Native terminal observation is not a checked report',
                                      'previous_handback':strict_json(row['result']) if row['result'] else None}
                            db.execute('UPDATE work SET state=?,result=? WHERE ticket=?',(terminal,canonical(handback),saved['ticket']))
                            db.execute('UPDATE dispatches SET state=? WHERE ticket=?',(terminal,saved['ticket']))
                    # Do not consume a newer wait request with an older list receipt.
                    due=self.store_value(db,owner,'native-list-due')
                    current_epochs=all(_epoch(db,v['ticket'])==v['epoch'] for v in snapshot.values())
                    newer_wait=False
                    if due and due.get('after_wait'):
                        waiter=db.execute('SELECT rowid FROM native_observations WHERE owner=? AND call_id=?',(owner,due['after_wait'])).fetchone()
                        listed=db.execute('SELECT rowid FROM native_observations WHERE owner=? AND call_id=?',(owner,call_id)).fetchone()
                        newer_wait=bool(waiter and listed and waiter[0]>listed[0])
                    if current_epochs and not newer_wait:_kv(db,owner,'native-list-due',None)
            db.execute('UPDATE native_observations SET finished=?,result_hash=?,valid=? WHERE owner=? AND call_id=?',
                       (time.time(),digest,int(valid),owner,call_id))

    @staticmethod
    def store_value(db,owner,name):
        row=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(owner,name)).fetchone()
        return strict_json(row[0]) if row else None
