"""Owned, detached Git checkouts and conflict-checked patch integration.

No resets, branch rewrites, automatic commits, force removal or network commands.
Worktrees separate file changes, not permissions; native Codex sandboxing remains
necessary. Dirty source checkouts are deliberately not snapshotted by guessing.
"""
from __future__ import annotations
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import time
from .util import HarnessError, atomic_write, file_hash, inside, load_json, no_symlinks, write_json
from .coordination import normalized

class Workspaces:
    def __init__(self,directory:Path):
        self.directory=Path(directory).absolute();no_symlinks(self.directory)
        self.git=shutil.which('git')
        if not self.git:raise HarnessError('Git unavailable: use read-only helpers and a single writer')
        self.empty_hooks=self.directory/'empty-hooks'

    def _git(self,root,*args,data=None,check=True):
        env=os.environ.copy()
        for k in tuple(env):
            if k in {'GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_CONFIG_COUNT'} or k.startswith(('GIT_CONFIG_KEY_','GIT_CONFIG_VALUE_')):env.pop(k,None)
        env['GIT_TERMINAL_PROMPT']='0'
        command=[self.git,'-c','core.hooksPath='+str(self.empty_hooks),'-c','core.fsmonitor=false','-c','core.untrackedCache=false','-C',str(root),*args]
        r=subprocess.run(command,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=None if data is not None else subprocess.DEVNULL,env=env,shell=False,timeout=30)
        if check and r.returncode:raise HarnessError('Git operation failed: '+r.stderr.decode('utf-8','replace')[:800])
        return r

    def _names(self,root,*args):
        raw=self._git(root,*args).stdout
        names=raw.decode('utf-8',errors='strict').split('\x00')
        for n in names:
            if n and any(ord(c)<32 for c in n):raise HarnessError('control characters in a Git path are unsupported')
        return [n for n in names if n]

    def prepare(self,ticket:str,root:Path,paths:list[str]):
        import re
        if not re.fullmatch('[a-f0-9]{32}',ticket):raise HarnessError('invalid worktree ticket')
        root=Path(root).resolve();no_symlinks(root)
        if self.directory.resolve().is_relative_to(root):raise HarnessError('worktree storage must be outside the source repository')
        directory=self.directory/ticket;record=directory/'record.json'
        if record.exists():
            info=load_json(record)
            if info['root']!=str(root) or info['paths']!=paths:raise HarnessError('worktree ticket identity mismatch')
            return info
        top=Path(self._git(root,'rev-parse','--show-toplevel').stdout.decode().strip()).resolve()
        if top!=root:raise HarnessError('select the Git repository root for isolated implementation')
        if self._git(root,'status','--porcelain=v1','-z','--untracked-files=all').stdout:
            raise HarnessError('source checkout has uncommitted files: preserve them; use one writer rather than an incomplete worktree')
        # Checkout filters may execute commands or fetch data. Do not start them implicitly.
        filters=self._git(root,'config','--get-regexp',r'^filter\..*\.(smudge|process)$',check=False)
        if filters.returncode==0 and filters.stdout.strip():raise HarnessError('checkout filters configured: use the existing workspace without starting filters')
        if filters.returncode not in (0,1):raise HarnessError('cannot inspect checkout filters')
        files=self._names(root,'ls-files','-z');snapshot={};modes={};total=0
        if len(files)>10000:raise HarnessError('checkout snapshot budget exceeded; prefer read-only helpers')
        for name in files:
            p=inside(root,name)
            if not p.is_file():raise HarnessError('submodules/nonregular tracked paths need explicit handling')
            total+=p.stat().st_size
            if total>100*1024*1024:raise HarnessError('checkout snapshot byte budget exceeded')
            snapshot[name]=file_hash(p);modes[name]=__import__("stat").S_IMODE(p.stat().st_mode)
        sha=self._git(root,'rev-parse','HEAD').stdout.decode().strip()
        for p in paths:normalized(root,p)
        if directory.exists():raise HarnessError('incomplete worktree preparation preserved for inspection')
        directory.mkdir(parents=True);self.empty_hooks.mkdir(parents=True,exist_ok=True)
        target=directory/'tree';no_symlinks(target)
        self._git(root,'worktree','add','--detach',str(target),sha)
        info={'ticket':ticket,'root':str(root),'tree':str(target),'base':sha,'paths':paths,'baseline':snapshot,'baseline_modes':modes,'integrated':False,'created_at':time.time()}
        write_json(record,info)
        return info

    def changes(self,info):
        tree=Path(info['tree']);no_symlinks(tree)
        names=sorted(set(self._names(tree,'diff','--no-ext-diff','--name-only','-z',info['base'])+self._names(tree,'ls-files','--others','--exclude-standard','-z')))
        allowed=info['paths']
        for name in names:
            p=normalized(tree,name)
            if not any(p==a or p.startswith(a.rstrip('/')+'/') for a in allowed):raise HarnessError('worker changed an unassigned path: '+p)
            if p.split('/')[0] in {'.git','.codex','.agents'}:raise HarnessError('worker changed repository control files')
            path=inside(tree,name)
            if path.exists() and not path.is_file():raise HarnessError('nonregular worker output')
        return names

    @contextmanager
    def _lock(self,root):
        from .util import json_hash
        lock=self.directory/('merge-'+json_hash(str(root))+'.lock');no_symlinks(lock)
        fd=None
        try:
            fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            yield
        except FileExistsError as e:raise HarnessError('another checked integration owns the workspace') from e
        finally:
            if fd is not None:lock.unlink(missing_ok=True)

    def integrate(self,ticket):
        import re
        if not isinstance(ticket,str) or not re.fullmatch('[a-f0-9]{32}',ticket):raise HarnessError('invalid ticket')
        record=self.directory/ticket/'record.json';no_symlinks(record);info=load_json(record)
        root=Path(info['root']);tree=Path(info['tree']);no_symlinks(root);no_symlinks(tree)
        if info['integrated']:return info
        with self._lock(root):
            names=self.changes(info)
            for n in names:
                path=inside(root,n);now=file_hash(path) if path.is_file() else None
                if path.is_file() and n in info['baseline'] and (not isinstance(info.get('baseline_modes'),dict) or __import__('stat').S_IMODE(path.stat().st_mode)!=info['baseline_modes'].get(n)):
                    raise HarnessError('original file mode changed or old baseline lacks mode evidence: '+n)
                if now!=info['baseline'].get(n):raise HarnessError('leader or another worker already changed '+n+'; never overwrite it')
            if names:
                self._git(tree,'add','-A','--',*[':(literal)'+n for n in names])
                staged=set(self._names(tree,'diff','--cached','--name-only','-z',info['base']))
                if staged!=set(names):raise HarnessError('staged changes differ from reviewed worktree changes; integration refused')
                patch=self._git(tree,'diff','--cached','--binary','--no-ext-diff','--no-textconv',info['base']).stdout
                if len(patch)>16*1024*1024:raise HarnessError('integration patch exceeds review budget')
                atomic_write(record.parent/'result.patch',patch)
                self._git(root,'apply','--check','--binary','--whitespace=nowarn','-',data=patch)
                # No --reject, --3way, force, reset or index replacement.
                self._git(root,'apply','--binary','--whitespace=nowarn','-',data=patch)
            info.update(integrated=True,changed_paths=names,integrated_at=time.time(),
                        final_checks_required=True)
            write_json(record,info)
        return info
