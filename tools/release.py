#!/usr/bin/env python3
"""Create and verify a public source ZIP. Never publish or include runtime state."""
from __future__ import annotations
import argparse
import ast
import stat
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOP={'README.md','LICENSE','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md','install.py','luna.py','INSTALL.cmd','CHECK.cmd','UNREGISTER.cmd','PURGE.cmd','.gitignore','.gitattributes','requirements-dev.txt'}
DIRS={'luna_astra','prompts','tests','evals','tools','docs','.github'}
EXT={'.py','.md','.json','.yml','.yaml','.toml','.txt','.cmd'}
FORBIDDEN={'state','state-v2','state-v3','worktrees','backups','checkpoints','.codex','.omx','.lunastra','.env'}

def validate_files(files):
    """Apply the same publication boundary on build AND archive verification."""
    folded = set()
    for name, raw in files.items():
        parts = name.split('/')
        if (not parts or any(part in ('', '.', '..') or part.endswith((' ', '.')) for part in parts)
                or any(ord(char)<32 for char in name) or '\\' in name or ':' in name
                or name.casefold() in folded):
            raise ValueError('unsafe/colliding source path: '+name)
        folded.add(name.casefold())
        if any(re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part) for part in parts):
            raise ValueError('Windows-reserved source path: '+name)
        if parts[0] not in DIRS and name not in TOP:
            raise ValueError('unlisted source file: '+name)
        if any(part in FORBIDDEN or re.fullmatch(r'state-v\d+', part) or part.startswith('.env.') for part in parts):
            raise ValueError('private/runtime path refused: '+name)
        if Path(name).suffix not in EXT and name not in TOP:
            raise ValueError('binary/runtime extension refused: '+name)
        if len(raw)>2*1024*1024:
            raise ValueError('oversized source file: '+name)
        text=raw.decode('utf-8-sig')
        patterns = [
            r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----',
            r'\bgh[pousr]_[A-Za-z0-9]{30,}\b',
            r'\bgithub_pat_[A-Za-z0-9_]{40,}\b',
            r'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b',
            r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
            r'\bxox[baprs]-[A-Za-z0-9-]{20,}\b',
        ]
        if any(re.search(pattern,text) for pattern in patterns):
            raise ValueError('possible credential/private-key material refused in '+name)
    missing=TOP-set(files)
    if missing: raise ValueError('missing public entrypoints: '+', '.join(sorted(missing)))
    if 'luna_astra/__init__.py' not in files: raise ValueError('missing runtime version source')
    check_links(files)


def collect(root=ROOT):
    root=Path(root).resolve(); files={}
    for p in sorted(root.rglob('*')):
        rel=p.relative_to(root)
        if '__pycache__' in rel.parts or '.git' in rel.parts or p.suffix in {'.pyc','.pyo'}: continue
        if p.is_symlink() or (p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('symlink/junction refused: '+rel.as_posix())
        if not p.is_file(): continue
        if rel.as_posix()=='MANIFEST.sha256.json': continue
        if p.stat().st_size>2*1024*1024: raise ValueError('oversized source file: '+rel.as_posix())
        files[rel.as_posix()]=p.read_bytes()
        if len(files)>10000 or sum(map(len,files.values()))>64*1024*1024:
            raise ValueError('source tree exceeds publication budget')
    validate_files(files)
    return files

def check_links(files):
    for name,data in files.items():
        if not name.endswith('.md'):continue
        for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)',data.decode('utf-8-sig')):
            value=match.group(1).split('#',1)[0]
            if not value or re.match(r'\w+://|mailto:',value):continue
            target=(Path(name).parent/value).as_posix()
            import posixpath
            target=posixpath.normpath(target)
            if target not in files:raise ValueError('broken local documentation link: '+name+' -> '+target)

def strict_manifest(raw):
    def pairs(items):
        obj={}
        for key,value in items:
            if key in obj:raise ValueError('duplicate manifest key')
            obj[key]=value
        return obj
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite manifest value')))

def version_text(text):
    tree=ast.parse(text)
    versions=[n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)]
    if len(versions)!=1 or not re.fullmatch(r'\d+\.\d+\.\d+',versions[0]):raise ValueError('missing or invalid source version')
    return versions[0]

def verify(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist(); infos=z.infolist()
        if len(names)>10000 or sum(i.file_size for i in infos)>64*1024*1024:raise ValueError('archive exceeds source budget')
        if len(names)!=len(set(names)) or len(names)!=len({n.casefold() for n in names}):raise ValueError('duplicate/case-colliding ZIP paths')
        for i in infos:
            name=i.filename; parts=name.split('/')
            if not name.startswith('LunAstra/') or any(p in ('','..','.') for p in parts) or '\\' in name or ':' in name or i.is_dir():raise ValueError('unsafe ZIP path')
            if stat.S_ISLNK(i.external_attr>>16):raise ValueError('ZIP symlink refused')
            if i.file_size>2*1024*1024:raise ValueError('oversized archive member')
        if z.testzip() is not None:raise ValueError('ZIP CRC failure')
        manifest_name='LunAstra/MANIFEST.sha256.json'
        if manifest_name not in names:raise ValueError('missing manifest')
        manifest=strict_manifest(z.read(manifest_name))
        if not isinstance(manifest,dict) or set(manifest)!={'format','project','version','files'} or type(manifest['format']) is not int or manifest['format']!=1 or manifest['project']!='LunAstra':raise ValueError('invalid manifest header')
        members=manifest['files']
        if not isinstance(members,dict) or not all(isinstance(n,str) and isinstance(h,str) and re.fullmatch('[a-f0-9]{64}',h) for n,h in members.items()):raise ValueError('invalid manifest members')
        expected={'LunAstra/'+p for p in members}|{manifest_name}
        if set(names)!=expected:raise ValueError('manifest membership mismatch')
        if not TOP<=set(members) or 'luna_astra/__init__.py' not in members:raise ValueError('missing source entrypoints')
        for name,sha in members.items():
            if hashlib.sha256(z.read('LunAstra/'+name)).hexdigest()!=sha:raise ValueError('file hash mismatch: '+name)
        validate_files({name:z.read('LunAstra/'+name) for name in members})
        version=version_text(z.read('LunAstra/luna_astra/__init__.py').decode('utf-8'))
        if manifest['version']!=version:raise ValueError('archive version differs from source')
        return {'version':version,'files':len(members),'crc':'PASS','manifest':'PASS','archive_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest()}

def source_version(root):
    return version_text((Path(root)/'luna_astra'/'__init__.py').read_text(encoding='utf-8'))

def build(output,root=ROOT):
    output=Path(output).absolute()
    if output.exists():raise ValueError('output already exists; preserve it and choose a new name')
    if output.is_relative_to(Path(root).resolve()):raise ValueError('write release ZIP outside the public source tree')
    files=collect(root);check_links(files)
    manifest={'format':1,'project':'LunAstra','version':source_version(root),'files':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()}}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for n,b in files.items():
            info=zipfile.ZipInfo('LunAstra/'+n,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
            z.writestr(info,b)
        info=zipfile.ZipInfo('LunAstra/MANIFEST.sha256.json',date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
        z.writestr(info,json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return verify(output)

def build_source(output, root=ROOT):
    """Repository upload archive: no generated checksum manifest in the source tree."""
    output=Path(output).absolute()
    if output.exists(): raise ValueError('output already exists; choose a new name')
    if output.is_relative_to(Path(root).resolve()): raise ValueError('write archives outside the source tree')
    files=collect(root)
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,raw in files.items():
            info=zipfile.ZipInfo('LunAstra/'+name,date_time=(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=0o100644<<16
            z.writestr(info,raw)
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None: raise ValueError('source archive CRC failure')
        if {n.removeprefix('LunAstra/'):z.read(n) for n in z.namelist()}!=files:
            raise ValueError('source archive readback mismatch')
    return {'version':source_version(root),'files':len(files),'kind':'repository-source',
            'manifest':'EXCLUDED_BY_DESIGN','archive_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--output',type=Path); group.add_argument('--verify',type=Path)
    group.add_argument('--source-output',type=Path)
    a=p.parse_args()
    try:
        result=verify(a.verify) if a.verify else (build_source(a.source_output) if a.source_output else build(a.output))
        print(json.dumps(result,indent=2)); return 0
    except (OSError,ValueError,KeyError,TypeError,SyntaxError,UnicodeError,zipfile.BadZipFile,RuntimeError) as exc:
        print('Release not verified: '+str(exc),file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
