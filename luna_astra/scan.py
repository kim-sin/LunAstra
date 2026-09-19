"""Streaming content observations; bounded hook previews are not certificates."""
from __future__ import annotations
import os
import time
from itertools import chain
from pathlib import Path
from .codemap import SKIP, sensitive, _ignore_rules, _ignored
from .util import HarnessError, file_hash, no_symlinks, stat_identity


def observe(root: Path, max_files=5000, max_bytes=32*1024*1024, max_seconds=1.5, *, full=False):
    """Full helper scans stream every eligible file, regardless of its byte size.

    Automatic previews retain their old bounded cost. A full scan is requested
    only at contract start/certification, not on every read, search or prompt.
    Both modes reject inaccessible/special/changed paths instead of blessing a
    partial tree. Ignore policy is unchanged; this is not a filesystem sandbox.
    """
    root=Path(root).absolute(); no_symlinks(root); root=root.resolve()
    files={}; stamps={}; directories={}; total=0; partial=False; start=time.monotonic()
    if root==Path(root.anchor) or root==Path.home().resolve():
        return {'files':{},'complete':False,'reason':'refusing_home_or_drive'}
    if not root.is_dir():return {'files':{},'complete':False,'reason':'workspace_missing'}
    errors=[]; patterns=[]
    for current,dirs,names in os.walk(root,followlinks=False,onerror=lambda exc: errors.append(str(exc))):
        current=Path(current); base=current.relative_to(root).as_posix()
        try:
            no_symlinks(current); directories[current]=stat_identity(current.stat())
        except (OSError,ValueError):
            partial=True; dirs[:]=[]; continue
        extra,uncertain=_ignore_rules(current); partial=partial or uncertain
        patterns.extend(('' if base=='.' else base,p) for p in extra)
        kept=[]
        for name in sorted(dirs):
            path=current/name; rel=path.relative_to(root).as_posix()
            if name in SKIP or name=='.lunastra' or sensitive(rel) or _ignored(rel,patterns,True):continue
            try:no_symlinks(path)
            except HarnessError:partial=True;continue
            if (path/'.git').exists():partial=True;continue
            kept.append(name)
        dirs[:]=kept
        for name in sorted(names):
            path=current/name; rel=path.relative_to(root).as_posix()
            if name=='.git' or name.endswith(('.pyc','.pyo')) or sensitive(rel) or _ignored(rel,patterns):continue
            if not full and (len(files)>=max_files or time.monotonic()-start>max_seconds):
                return {'files':files,'complete':False,'reason':'scan_budget'}
            try:
                no_symlinks(path)
                if not path.is_file():partial=True;continue
                before=path.stat(); size=before.st_size
                if not full and (size>2*1024*1024 or total+size>max_bytes):
                    partial=True;continue
                total+=size; value=file_hash(path)
                if stat_identity(before)!=stat_identity(path.stat()):
                    partial=True;continue
                files[rel]=value;stamps[path]=stat_identity(before)
            except (OSError,ValueError):partial=True
    # Detect additions/removals and late changes while a large tree is scanned.
    for path,stamp in chain(directories.items(),stamps.items()):
        try:
            no_symlinks(path)
            if stat_identity(path.stat())!=stamp:partial=True
        except (OSError,ValueError):partial=True
    partial=partial or bool(errors)
    return {'files':files,'complete':not partial,'reason':None if not partial else 'some_paths_unobserved'}


def changes(before,after):
    a=before.get('files',{});b=after.get('files',{})
    return sorted(n for n in a.keys()|b.keys() if a.get(n)!=b.get(n))


def completeness_problem(before, after):
    for label,value in (('baseline',before),('current',after)):
        if not isinstance(value,dict) or value.get('complete') is not True:
            reason=value.get('reason') if isinstance(value,dict) else 'missing'
            return label+' workspace observation is incomplete ('+str(reason)+'); preserve checked results, but whole-change coverage is not certified'
    return None


def require_complete(before, after):
    problem=completeness_problem(before,after)
    if problem:raise HarnessError(problem,code='WORKSPACE_OBSERVATION_INCOMPLETE')
