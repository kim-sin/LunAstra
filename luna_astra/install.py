"""Additive, content-addressed install. No config, model, trust or process changes."""
from __future__ import annotations
import base64
import copy
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from . import __version__, __build__
from .model_gate import EVENTS
from .hook_policy import MATCHER
from .util import HarnessError, atomic_write, canonical, digest, file_hash, load_json, no_symlinks, write_json

OWNER='LunAstra / '

def payload(package):
    result={}
    for name in ('luna.py',):
        path=package/name;no_symlinks(path);result[name]=file_hash(path)
    for folder in ('luna_astra','prompts'):
        for path in sorted((package/folder).rglob('*')):
            if '__pycache__' in path.parts or path.suffix=='.pyc':continue
            no_symlinks(path)
            if path.is_file():result[path.relative_to(package).as_posix()]=file_hash(path)
    if 'prompts/CORE.md' not in result:raise HarnessError('incomplete package')
    return result

def read_hooks(path):
    no_symlinks(path)
    if not path.exists():return None,{'hooks':{}}
    before=path.read_bytes();obj=load_json(path)
    if not isinstance(obj,dict) or not isinstance(obj.get('hooks',{}),dict):raise HarnessError('existing hooks are malformed')
    for groups in obj.get('hooks',{}).values():
        if not isinstance(groups,list):raise HarnessError('invalid existing hook groups')
        for group in groups:
            if not isinstance(group,dict) or not isinstance(group.get('hooks'),list) or any(not isinstance(h,dict) for h in group['hooks']):
                raise HarnessError('invalid existing hook handlers')
    return before,obj

def powershell_argv(argv):return '& '+' '.join("'"+x.replace("'","''")+"'" for x in argv)

def definition(python,release,state,event):
    argv=[str(python),str(release/'luna.py'),'--state',str(state),'hook']
    # Fast gate: the substring test is only an optimization, never an authorization check.
    # Any possible Luna event still reaches luna.py, which parses JSON and validates the exact model.
    # False positives merely pay the normal Python cost; non-Luna events usually avoid Python entirely.
    child=shlex.join(argv)
    trace_child=shlex.join(argv[:-1]+['--trace-model-gate','hook'])
    arm=state.parent/'model-gate-trace'/'active.json'
    posix_script=(
        "payload=$(cat); "
        "if [ -f "+shlex.quote(str(arm))+" ]; then printf '%s' \"$payload\" | "+trace_child+"; else "
        "case \"$payload\" in *-luna*|*gpt-reserve*|*'\\u'*) printf '%s' \"$payload\" | "+child+
        " ;; *) printf '{}\\n' ;; esac; fi"
    )
    posix='sh -c '+shlex.quote(posix_script)

    # Only this child PowerShell process is changed; no profile/system setting is written.
    # It performs the same cheap prefilter before Python, preserving UTF-8 for genuine Luna events.
    script=("$ErrorActionPreference='Stop'; "
            "$utf8=[System.Text.UTF8Encoding]::new($false); "
            "[Console]::InputEncoding=$utf8; [Console]::OutputEncoding=$utf8; $OutputEncoding=$utf8; "
            "$raw=[Console]::In.ReadToEnd(); "
            "if([System.IO.File]::Exists("+powershell_argv([str(arm)])[2:]+")){$raw | "+powershell_argv(argv[:-1]+['--trace-model-gate','hook'])+"; exit $LASTEXITCODE}; "
            "if((-not $raw.Contains('-luna')) -and (-not $raw.Contains('gpt-reserve')) -and (-not $raw.Contains('\\u'))){[Console]::Out.WriteLine('{}'); exit 0}; "
            "$raw | "+powershell_argv(argv)+'; exit $LASTEXITCODE')
    windows='powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '+base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    command=windows if os.name=='nt' else posix
    handler={'type':'command','command':command,'commandWindows':windows,'statusMessage':OWNER+event,'timeout':300 if event in {'Stop','SubagentStop'} else 3 if event=='Interrupt' else 10}
    if event not in {'Stop','SubagentStop','Interrupt','PostCompact'}:handler['additionalContextLimit']=3500
    group={'hooks':[handler]}
    if event in {'PreToolUse','PostToolUse'}:group['matcher']=MATCHER
    elif event not in {'Stop','UserPromptSubmit','Interrupt'}:group['matcher']='.*'
    return group

def decoded(command):
    if not isinstance(command,str):return ''
    marker='powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '
    if command.startswith(marker):
        try:return base64.b64decode(command[len(marker):],validate=True).decode('utf-16-le')
        except (ValueError,UnicodeError):return ''
    return command

def legacy_argv(command):
    """Recognize only the generated legacy invocation; never execute or substring-match it."""
    if not isinstance(command,str) or len(command)>65536:return None
    marker='powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand '
    if command.startswith(marker):
        script=decoded(command)
        prefix="$ErrorActionPreference='Stop'; & "
        suffix='; exit $LASTEXITCODE'
        if not script.startswith(prefix) or not script.endswith(suffix):return None
        body=script[len(prefix):-len(suffix)]
        literals=re.findall(r"'(?:[^']|'')*'",body)
        if ' '.join(literals)!=body:return None
        return [x[1:-1].replace("''", "'") for x in literals]
    try:
        argv=shlex.split(command)
    except ValueError:return None
    # Canonical shell quoting also excludes operators and shell substitutions.
    if shlex.join(argv)!=command:return None
    return argv

def strip_owned(obj,receipt,home):
    result=copy.deepcopy(obj);hooks=result.setdefault('hooks',{})
    registered=receipt.get('owned_handlers',{}) if receipt else {}
    old_release=receipt.get('release') if receipt else None
    def owns(event,h):
        if any(h==saved for saved in registered.get(event,[])):return True
        # Migration is constrained by the existing rc1 receipt's exact release path.
        if receipt and receipt.get('version')=='1.0.0-rc1' and old_release and event in {'SubagentStart','SubagentStop'}:
            release=Path(old_release).absolute()
            if release.parent!=home/'luna-astra'/'releases':return False
            expected='Luna Astra / owned worker hook / '+('start' if event=='SubagentStart' else 'stop')
            argv=legacy_argv(h.get('command'))
            if not (h.get('type')=='command' and h.get('statusMessage')==expected and
                    isinstance(argv,list) and len(argv)==5 and argv[1:]==[str(release/'luna.py'),'--state',receipt.get('state'),'hook']):return False
            if 'commandWindows' in h and legacy_argv(h['commandWindows'])!=argv:return False
            return Path(argv[0]).is_absolute()
        return False
    for event,groups in list(hooks.items()):
        out=[]
        for group in groups:
            remaining=[h for h in group['hooks'] if not owns(event,h)]
            if len(remaining)==len(group['hooks']):out.append(group)
            elif remaining:out.append({**group,'hooks':remaining})
        if out:hooks[event]=out
        else:del hooks[event]
    return result

@contextmanager
def install_lock(home):
    path=home/'luna-astra'/'install.lock';no_symlinks(path);path.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as e:raise HarnessError('another install may be active; never break its lock automatically') from e
    try:
        with os.fdopen(fd,'w') as f:f.write(canonical({'pid':os.getpid(),'at':time.time()}))
        yield
    finally:path.unlink()

class Installer:
    def __init__(self,package,home,python=None):
        self.package=Path(package).resolve();self.home=Path(home).absolute();self.python=Path(python or sys.executable).absolute()
        no_symlinks(self.home)
        if not self.python.is_file():raise HarnessError('Python executable unavailable')
        if sys.version_info<(3,10):raise HarnessError('Python 3.10+ required')
    def _receipt(self):
        p=self.home/'luna-astra'/'installation.json';no_symlinks(p)
        if not p.exists():return None
        obj=load_json(p)
        if not isinstance(obj,dict) or not isinstance(obj.get('version'),str) or not obj['version']:
            raise HarnessError('invalid existing installation receipt')
        owned=obj.get('owned_handlers',{})
        if not isinstance(owned,dict) or any(not isinstance(k,str) or not isinstance(v,list) or any(not isinstance(h,dict) for h in v) for k,v in owned.items()):
            raise HarnessError('invalid hook ownership receipt; preserve original settings')
        for field in ('release','state'):
            if field in obj and (not isinstance(obj[field],str) or not obj[field]):
                raise HarnessError('invalid installation '+field)
        return obj
    def plan(self):
        files=payload(self.package);sha=digest(canonical(files).encode())
        release=self.home/'luna-astra'/'releases'/(__version__+'-'+sha[:16])
        state=self.home/'luna-astra'/'state-v4';no_symlinks(state)
        path=self.home/'hooks.json';before,obj=read_hooks(path);receipt=self._receipt()
        clean=strip_owned(obj,receipt,self.home)
        # Do not duplicate an apparently owned hook after its ownership receipt was lost/edited.
        for groups in clean['hooks'].values():
            for group in groups:
                if any(str(h.get('statusMessage','')).startswith((OWNER,'Luna Astra v2 / ','Luna Astra / owned worker hook /')) for h in group['hooks']):
                    raise HarnessError('unmatched Luna Astra hook found; preserve it and resolve ownership before installing')
        after=copy.deepcopy(clean)
        for event in sorted(EVENTS):after['hooks'].setdefault(event,[]).append(definition(self.python,release,state,event))
        return {'version':__version__,'build':__build__,'release':str(release),'state':str(state),'payload_files':files,'payload_sha256':sha,
                'hooks_path':str(path),'before_sha256':digest(before) if before is not None else None,
                'hooks_after':after,'needs_hook_change':after!=obj,
                'untouched':['config.toml','AGENTS.md','auth','model','reasoning','parallel allocation','trust','project files','running processes'],
                'activation':'INSTALLED_IS_NOT_LIVE_VERIFIED','codex_home':str(self.home)}
    def registration_status(self):
        """Count exact owned handlers; a visible name alone proves no activation."""
        _,obj=read_hooks(self.home/'hooks.json')
        clean=strip_owned(obj,self._receipt(),self.home)
        count=lambda data:sum(len(g['hooks']) for groups in data.get('hooks',{}).values() for g in groups)
        owned=count(obj)-count(clean)
        return {'HOOKS_REGISTERED':owned>0,'owned_handlers':owned,
                'handler_bound_home':str(self.home),'host_effective_codex_home':'UNKNOWN'}

    def apply(self):
        self.home.mkdir(parents=True,exist_ok=True)
        with install_lock(self.home):
            plan=self.plan();release=Path(plan['release']);no_symlinks(release)
            previous=self._receipt()
            if previous and previous.get('payload_sha256')!=plan['payload_sha256']:
                from .removal import _active_records
                outstanding=_active_records(self.home/'luna-astra')
                if outstanding:
                    raise HarnessError('preserve the active installation: '+', '.join(outstanding),code='UPGRADE_ACTIVE_WORK')
            if release.exists():
                if payload(release)!=plan['payload_files']:raise HarnessError('installed immutable release changed; will not overwrite')
            else:
                staging=release.parent/('.stage-'+uuid.uuid4().hex);no_symlinks(staging);staging.mkdir(parents=True)
                try:
                    for name in plan['payload_files']:
                        target=staging/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.package/name,target)
                    if payload(staging)!=plan['payload_files']:raise HarnessError('package changed during copy')
                    os.replace(staging,release)
                finally:
                    if staging.exists():shutil.rmtree(staging)  # Only this invocation's uniquely named staging directory.
            try:
                check=subprocess.run([str(self.python),str(release/'luna.py'),'help'],
                                     stdin=subprocess.DEVNULL,capture_output=True,text=True,
                                     encoding='utf-8',errors='replace',timeout=10,shell=False,
                                     env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
                info=json.loads(check.stdout) if check.returncode==0 else None
                if not isinstance(info,dict) or info.get('version')!=__version__ or info.get('build')!=__build__:
                    raise HarnessError('Installed helper startup check failed; hook settings were not changed.')
            except (OSError,ValueError,subprocess.SubprocessError) as exc:
                raise HarnessError('Installed helper could not start; hook settings were not changed. Check Python and local access permissions.') from exc
            path=Path(plan['hooks_path']);no_symlinks(path);before=path.read_bytes() if path.exists() else None
            if (digest(before) if before is not None else None)!=plan['before_sha256']:raise HarnessError('concurrent hooks edit; refusing overwrite')
            after=(json.dumps(plan['hooks_after'],ensure_ascii=False,indent=2)+'\n').encode('utf-8')
            changed=plan['needs_hook_change'];backup=None
            if changed and before is not None:
                backup=self.home/'luna-astra'/'backups'/('hooks-'+str(time.time_ns())+'.json');atomic_write(backup,before)
            receipt={'version':__version__,'build':__build__,'release':str(release),'state':plan['state'],'payload_sha256':plan['payload_sha256'],
                     'backup':str(backup) if backup else None,'hook_changed':changed,'installed_at':time.time(),
                     'activation':'INSTALLED_NOT_LIVE_VERIFIED','local_helper_startup':'PASS',
                     'owned_handlers':{e:definition(self.python,release,Path(plan['state']),e)['hooks'] for e in sorted(EVENTS)}}
            try:
                if changed:atomic_write(path,after)
                if load_json(path)!=plan['hooks_after']:raise HarnessError('hooks readback mismatch')
                receipt['hooks_sha256']=file_hash(path)
                write_json(self.home/'luna-astra'/'installation.json',receipt)
            except BaseException:
                if changed and path.exists() and path.read_bytes()==after:
                    if before is None:path.unlink()
                    else:atomic_write(path,before)
                raise
            return receipt
    def remove(self):
        if not self.home.exists():return {'changed':False}
        with install_lock(self.home):
            path=self.home/'hooks.json';before,obj=read_hooks(path);receipt=self._receipt()
            after=strip_owned(obj,receipt,self.home)
            if before is None or obj==after:return {'changed':False}
            backup=self.home/'luna-astra'/'backups'/('unregister-'+str(time.time_ns())+'.json');atomic_write(backup,before)
            if path.read_bytes()!=before:raise HarnessError('concurrent hooks change')
            write_json(path,after)
            return {'changed':True,'backup':str(backup),'preserved':'all releases, state, other hooks and running processes'}
