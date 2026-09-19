"""Small side-effect-free selector; model authorization remains separate.

Only known edit, shell and native coordination tools need operational hooks.
Unknown tools are not claimed to be sandboxed. Native read/search tools keep
host controls without paying LunAstra process/SQLite overhead.
"""
import re
NATIVE = frozenset({'spawn_agent','wait_agent','send_input','close_agent',
    'resume_agent','followup_task','send_message','interrupt_agent','list_agents'})
EDIT = frozenset({'apply_patch','Edit','Write','edit_file','write_file'})
SHELL = frozenset({'Bash','exec_command','shell_command'})
TOOLS = NATIVE | EDIT | SHELL | {'Agent'}
MATCHER = r'^(?:(?:functions\.)?(?:'+'|'.join(sorted(TOOLS))+r')|(?:multi_agent_v1|multi_agent_v2)(?:'+'|'.join(sorted(NATIVE))+r'))$'
_MATCH = re.compile(MATCHER)

def relevant(event):
    if not isinstance(event,dict):
        return False
    if event.get('hook_event_name') not in {'PreToolUse','PostToolUse'}:
        return True
    name=event.get('tool_name')
    return isinstance(name,str) and _MATCH.fullmatch(name) is not None


def canonical_tool(value):
    if not isinstance(value,str):return ''
    if value.startswith('functions.') and value[10:] in TOOLS:
        return value[10:]
    for prefix in ('multi_agent_v1','multi_agent_v2'):
        if value.startswith(prefix) and value[len(prefix):] in NATIVE:
            return value[len(prefix):]
    return value
