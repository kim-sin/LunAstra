"""Bounded content observations for detecting unreported changes; not a sandbox."""
from __future__ import annotations
import os
import time
from pathlib import Path
from .codemap import SKIP, sensitive, _ignore_rules, _ignored
from .util import HarnessError, file_hash, no_symlinks

def observe(root:Path,max_files=5000,max_bytes=32*1024*1024,max_seconds=1.5):
    root=Path(root).resolve();files={};total=0;partial=False;start=time.monotonic()
    if root==Path(root.anchor) or root==Path.home().resolve():return {'files':{},'complete':False,'reason':'refusing_home_or_drive'}
    no_symlinks(root)
    if not root.is_dir():return {'files':{},'complete':False,'reason':'workspace_missing'}
    patterns=[]
    for current,dirs,names in os.walk(root,followlinks=False):
        current=Path(current);base=current.relative_to(root).as_posix()
        extra,uncertain=_ignore_rules(current);partial=partial or uncertain
        patterns.extend(('' if base=='.' else base,p) for p in extra)
        kept=[]
        for name in sorted(dirs):
            p=current/name;rel=p.relative_to(root).as_posix()
            if name in SKIP or name=='.lunastra' or sensitive(rel) or _ignored(rel,patterns,True):continue
            try:no_symlinks(p)
            except HarnessError:partial=True;continue
            if (p/'.git').exists():partial=True;continue
            kept.append(name)
        dirs[:]=kept
        for name in sorted(names):
            p=current/name;rel=p.relative_to(root).as_posix()
            if name=='.git' or name.endswith(('.pyc','.pyo')) or sensitive(rel) or _ignored(rel,patterns):continue
            if len(files)>=max_files or time.monotonic()-start>max_seconds:return {'files':files,'complete':False,'reason':'scan_budget'}
            try:
                no_symlinks(p)
                if not p.is_file():partial=True;continue
                size=p.stat().st_size
                if size>2*1024*1024 or total+size>max_bytes:partial=True;continue
                total+=size;files[rel]=file_hash(p)
            except (OSError,ValueError):partial=True
    return {'files':files,'complete':not partial,'reason':None if not partial else 'some_paths_unobserved'}

def changes(before,after):
    a=before.get('files',{});b=after.get('files',{})
    return sorted(n for n in a.keys()|b.keys() if a.get(n)!=b.get(n))
