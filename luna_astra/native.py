"""Native Codex wire adapters, not model launchers or host-version guesses.

V2 mailbox waits are NOT task completion. Canonical task names and observed
worker IDs are distinct. A successful spawn binds a name; the current one-use
assignment ticket plus a real worker hook binds its runtime ID. Missing or
ambiguous observations never create an imaginary worker or replacement call.
"""
from __future__ import annotations
import re
from .util import HarnessError, canonical, strict_json, json_hash
from .team import unpack_response

_PATH = re.compile(r'/root(?:/[a-z0-9_]+)+')


def configuration(value=None, *, legacy=False):
    if value is None:return {'protocol':'v1','context':'full' if legacy else 'capsule'}
    if not isinstance(value,dict) or set(value)-{'protocol','context','capacity_total'}:
        raise HarnessError('native supports protocol, context and declared capacity_total only; no model/config override')
    result={'protocol':value.get('protocol','v1'),'context':value.get('context','capsule')}
    if result['protocol'] not in {'v1','v2'} or result['context'] not in {'capsule','full'}:
        raise HarnessError('native protocol must be v1/v2 and context capsule/full')
    if 'capacity_total' in value:
        capacity=value['capacity_total']
        if type(capacity) is not int or not 1<=capacity<=1024:
            raise HarnessError('capacity_total must be an integer from 1 to 1024, including the root')
        result['capacity_total']=capacity
    return result


def capacity_problem(state):
    """A declared host capability is not permission to change host configuration.

    V2's configured total includes the root. Persistent identities and currently
    executable/resident agents are not interchangeable. We conservatively require
    enough declared capacity for this fixed roster instead of evicting agents or
    pretending a synthetic host proves an actual host's capacity.
    """
    profile=configuration(state.get('native'),legacy=True)
    if profile['protocol']!='v2':return None
    capacity=profile.get('capacity_total')
    if capacity is None:
        return {'code':'NATIVE_CAPACITY_UNKNOWN',
                'message':'V2 capacity is unconfirmed. Read the actual host limit and supply native.capacity_total for a new contract, or crew-capacity with evidence for an existing one; do not change host settings automatically.',
                'required_total':7,'capacity_total':None,'settings_changed':False}
    if capacity<7:
        return {'code':'NATIVE_CAPACITY_INSUFFICIENT',
                'message':'The declared V2 limit includes the root and is below root 1 + child 6. Preserve work; do not silently reduce the roster or alter host settings.',
                'required_total':7,'capacity_total':capacity,'settings_changed':False}
    return None


def require_capacity(state):
    problem=capacity_problem(state)
    if problem:raise HarnessError(problem['message'],code=problem['code'],details=problem)


def task_name(state, slot):
    if type(slot) is not int or not 1<=slot<=6 or not re.fullmatch('[a-f0-9]{32}',state.get('run_id','')):
        raise HarnessError('invalid fixed-crew native task identity')
    return 'la_'+state['run_id'][:12]+'_s'+str(slot)


def is_v2(state):
    return configuration(state.get('native'),legacy=True)['protocol']=='v2'


def target(store, owner, slot, agent_id=None):
    saved=store.get(owner,'native-target:'+str(slot))
    return saved['target'] if isinstance(saved,dict) else agent_id


def target_in(db, owner, slot, agent_id=None):
    row=db.execute("SELECT value FROM kv WHERE scope=? AND name=?",(owner,'native-target:'+str(slot))).fetchone()
    saved=strict_json(row[0]) if row else None
    return saved['target'] if isinstance(saved,dict) else agent_id


def dispatch(state, slot, message, handle=None):
    profile=configuration(state.get('native'),legacy=True)
    require_capacity(state)
    if handle:
        return ('followup_task',{'target':handle,'message':message}) if profile['protocol']=='v2' else (
            'send_input',{'target':handle,'message':message,'interrupt':False})
    if profile['protocol']=='v2':
        return 'spawn_agent',{'task_name':task_name(state,slot),
                              'message':message,'fork_turns':'none' if profile['context']=='capsule' else 'all'}
    return 'spawn_agent',{'message':message,'fork_context':profile['context']=='full'}


def validate_dispatch(state, slot, kind, payload, handle):
    if not isinstance(payload,dict) or not isinstance(payload.get('message'),str):
        raise HarnessError('invalid native dispatch')
    expected_kind,expected=dispatch(state,slot,payload['message'],handle)
    if kind!=expected_kind or payload!=expected:
        raise HarnessError('native call does not match the selected wire protocol/current slot; use the exact crew-step call')


def spawn_target(state, slot, response):
    result=unpack_response(response)
    if not is_v2(state):
        value=result.get('agent_id')
        return value if isinstance(value,str) and 0<len(value)<=4096 else None
    value=result.get('task_name')
    suffix='/'+task_name(state,slot)
    if not isinstance(value,str) or len(value)>4096 or not _PATH.fullmatch(value) or not value.endswith(suffix):return None
    if any(part=='root' for part in value.split('/')[2:]):return None
    return value


def followup_ack(state, response):
    if not is_v2(state):
        value=unpack_response(response).get('submission_id')
        return isinstance(value,str) and bool(value)
    # Official V2 followup_task returns a successful empty body, not a UUID.
    # None/missing body, prose, errors, and an arbitrary {} are NOT acknowledgement.
    if response=='' or response==[]:return True
    if isinstance(response,dict):
        if response.get('isError') is True or response.get('is_error') is True:return False
        content=response.get('content')
        if isinstance(content,list) and not set(response)-{'content','isError','is_error'}:
            return all(isinstance(p,dict) and p.get('type')=='text' and p.get('text')=='' for p in content)
    return False


def bind_worker(store, db, owner, state, row, member, key, supplied):
    """Bind only a trusted observed worker; assignment tokens are capabilities.

    Do not derive a UUID from the task path. If SubagentStart is not observable,
    leave the slot unbound. The worker can retry the SAME ticket after its hook.
    """
    if not is_v2(state) or member['agent_id']:return
    handle=target_in(db,owner,member['slot'])
    observed=store.get(key,'meta',{})
    agent=observed.get('agent_id')
    alias=store.get('__agent_alias__',agent) if isinstance(agent,str) else None
    root=store.get(owner,'meta',{})
    if (not handle or not isinstance(agent,str) or not agent or observed!=supplied or
        observed.get('role')!='worker' or observed.get('model')!=state['model'] or
        not observed.get('native_start_observed') or not alias or alias.get('key')!=key or
        alias.get('model')!=state['model'] or observed.get('workspace')!=root.get('workspace')):
        raise HarnessError('V2 runtime identity requires its real SubagentStart and current ticket; no inferred worker ID',code='NATIVE_IDENTITY_PENDING')
    parent=observed.get('parent_session_id')
    if parent is not None and parent!=root.get('session_id'):
        raise HarnessError('V2 worker belongs to another parent')
    if observed.get('team_ticket') and observed.get('team_ticket')!=row['ticket']:
        raise HarnessError('V2 identity is already assigned to another ticket')
    taken=db.execute('SELECT owner,slot FROM crew_members WHERE agent_id=?',(agent,)).fetchone()
    if taken:raise HarnessError('V2 runtime identity already belongs to a fixed slot')
    ack=db.execute("SELECT 1 FROM dispatches WHERE owner=? AND ticket=? AND state='running'",(owner,row['ticket'])).fetchone()
    if not ack:raise HarnessError('V2 canonical spawn acknowledgement is pending')
    db.execute('UPDATE crew_members SET agent_id=?,worker_key=? WHERE owner=? AND slot=?',(agent,key,owner,member['slot']))
    db.execute('UPDATE work SET agent_id=? WHERE ticket=?',(agent,row['ticket']))
    binding={'native_target':handle,'runtime_id':agent,'worker_key':key,'ticket':row['ticket'],
             'binding':'OBSERVED_WORKER_AND_CURRENT_ASSIGNMENT_CAPABILITY','model':observed['model']}
    db.execute('INSERT OR REPLACE INTO kv VALUES(?,?,?)',(owner,'native-binding:'+str(member['slot']),canonical(binding)))


def capsule_ready(store, owner, state):
    """Use the first member of the same six as a model-identity handshake.

    Fresh contexts may use host child defaults. Before spending five more model
    calls, require one real, joined Luna hook. No seventh probe or setting change.
    Effective reasoning effort is not exposed by this hook contract.
    """
    if configuration(state.get('native'),legacy=True)['context']=='full':return True
    for member in state.get('members',[]):
        if member.get('worker_key'):
            meta=store.get(member['worker_key'],'meta',{})
            if meta.get('native_model_observed')==state['model'] and meta.get('team_owner')==owner:return True
    return False


def routing_hash(kind, payload):
    """Visible routing identity excludes only the host-encrypted message field."""
    return json_hash([kind,{k:v for k,v in payload.items() if k!='message'}])


def remember_intent(store, owner, state, ticket, kind, payload):
    store.put(owner,'native-intent:'+ticket,{'plan_id':state['plan_id'],'kind':kind,
              'routing_hash':routing_hash(kind,payload),'payload_hash':json_hash(payload)})


def dispatch_ticket(store, owner, state, kind, payload, matches):
    if len(matches)==1:
        return matches[0],False
    if matches or not is_v2(state) or not isinstance(payload.get('message'),str) or not payload['message']:
        raise HarnessError('fixed crew dispatch requires exactly one current ticket')
    # V2 messages are opaque to PreToolUse. Authorize only a route emitted by
    # this root for one current reservation; full message semantics remain
    # uninspected, and actual current-ticket join/report gates remain mandatory.
    found=[]
    for row in state['tasks']:
        if row['state'] not in {'reserved','returned'} or not row['ticket']:
            continue
        intent=store.get(owner,'native-intent:'+row['ticket'])
        if intent and intent.get('plan_id')==state['plan_id'] and intent.get('kind')==kind and intent.get('routing_hash')==routing_hash(kind,payload):
            found.append(row['ticket'])
    if len(found)!=1:
        raise HarnessError('opaque V2 message has no unique current emitted route; use the exact crew-step call',code='NATIVE_ROUTE_UNCONFIRMED')
    return found[0],True
