"""Cooperative edit leases. Not an OS sandbox and not automatic Git merging."""
from __future__ import annotations
import os
import re
import time
from pathlib import Path
from .util import HarnessError, inside, no_symlinks
from .store import Store
from .transport import tool_name

class Conflict(HarnessError):
    pass

def normalized(root: Path, value: str) -> str:
    if not isinstance(value,str) or not value: raise HarnessError('invalid edit path')
    root=root.resolve()
    p=Path(value)
    if p.is_absolute():
        no_symlinks(p)
        try: value=p.resolve().relative_to(root).as_posix()
        except ValueError as e: raise HarnessError('edit path is outside workspace') from e
    if os.name == 'nt': value=value.replace('\\','/')
    target=inside(root,value,allow_root=True)
    rel=target.relative_to(root).as_posix()
    return rel.casefold() if os.name == 'nt' else rel

def overlaps(a: str, b: str) -> bool:
    return a == '.' or b == '.' or a == b or a.startswith(b.rstrip('/')+'/') or b.startswith(a.rstrip('/')+'/')

def edit_paths(tool: str, payload) -> list[str]:
    name=tool_name(tool)
    if name == 'apply_patch':
        text=payload if isinstance(payload,str) else (payload.get('command',payload.get('input',payload.get('patch',''))) if isinstance(payload,dict) else '')
        if not isinstance(text,str): return []
        return list(dict.fromkeys(re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$',text,re.M)))
    if name in {'Edit','Write','edit_file','write_file'} and isinstance(payload,dict):
        value=payload.get('file_path',payload.get('path'))
        return [value] if isinstance(value,str) else []
    return []

class Coordinator:
    def __init__(self, store: Store, workspace: Path):
        self.store=store; self.root=workspace.resolve(); self.workspace=os.path.normcase(str(self.root))

    def claim(self, owner: str, paths: list[str], token: str) -> list[str]:
        if not owner or not token or not isinstance(paths,list) or not paths: raise HarnessError('owner, token and paths required')
        normalized_paths=sorted(set(normalized(self.root,p) for p in paths))
        with self.store.db(True) as db:
            current=db.execute('SELECT * FROM leases WHERE workspace=?',(self.workspace,)).fetchall()
            for p in normalized_paths:
                for row in current:
                    different_operation=(row['token'].startswith('tool:') and token.startswith('tool:') and row['token']!=token)
                    if (row['owner'] != owner or different_operation) and overlaps(p,row['path']):
                        raise Conflict('file ownership conflict: '+p+'; owner='+row['owner'][:12])
            for p in normalized_paths:
                db.execute('INSERT OR IGNORE INTO leases VALUES(?,?,?,?,?)',(self.workspace,p,owner,token,time.time()))
        return normalized_paths

    def release(self, owner: str, token: str | None = None):
        with self.store.db(True) as db:
            if token is None: db.execute('DELETE FROM leases WHERE workspace=? AND owner=?',(self.workspace,owner))
            else: db.execute('DELETE FROM leases WHERE workspace=? AND owner=? AND token=?',(self.workspace,owner,token))

    def status(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute('SELECT path,owner,token,at FROM leases WHERE workspace=? ORDER BY path',(self.workspace,))]

    def enforce_task(self, paths: list[str], task: dict | None):
        if not task: return
        allowed=[normalized(self.root,p) for p in task.get('allowed_paths',[])]
        protected=[normalized(self.root,p) for p in task.get('protected_paths',[])]
        for value in paths:
            p=normalized(self.root,value)
            if any(overlaps(p,b) for b in protected): raise Conflict('protected path: '+p)
            if allowed and not any(a=='.' or p==a or p.startswith(a+'/') for a in allowed):
                raise Conflict('outside assigned edit scope: '+p)


def assigned_edit_input(tool: str, payload, root: Path):
    """Translate recognized worker edits into absolute owned-checkout paths.

    Native subagents inherit the session cwd. A prompt alone cannot change it.
    Hook updatedInput is used only on documented, recognized edit shapes.
    """
    name=tool_name(tool)
    root=root.resolve()
    def target(value):
        rel=normalized(root,value)
        if rel=='.':raise HarnessError('cannot edit the workspace directory as a file')
        # Preserve case in the actual path; normalized is only for comparisons.
        path=Path(value)
        return str(path if path.is_absolute() else inside(root,value.replace('\\','/') if os.name=='nt' else value))
    if name=='apply_patch':
        field=None
        if isinstance(payload,str):patch=payload
        elif isinstance(payload,dict):
            field=next((k for k in ('command','input','patch') if isinstance(payload.get(k),str)),None)
            patch=payload.get(field,'')
        else:raise HarnessError('unrecognized edit payload')
        if not edit_paths(tool,payload):raise HarnessError('unrecognized patch; cannot direct it to the owned workspace')
        rewritten=re.sub(r'^(\*\*\* (?:Add File|Update File|Delete File|Move to): )(.+?)\s*$',
                         lambda m:m.group(1)+target(m.group(2)),patch,flags=re.M)
        return rewritten if field is None else {**payload,field:rewritten}
    if name in {'Edit','Write','edit_file','write_file'} and isinstance(payload,dict):
        field='file_path' if 'file_path' in payload else 'path'
        return {**payload,field:target(payload[field])}
    raise HarnessError('unrecognized edit tool; use a supported scoped patch')
