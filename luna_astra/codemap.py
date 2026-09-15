"""Bounded local source index. Parses code as data, never imports project modules.

Python syntax/relative imports are structural; other languages use labeled hints.
The map is a navigation aid, never proof of behavior or complete call coverage.
"""
from __future__ import annotations
import ast
from collections import Counter, deque
import fnmatch
import io
import math
import os
from pathlib import Path
import re
import time
import tokenize
from .util import HarnessError, digest, file_hash, json_hash, load_json, no_symlinks, write_json

FORMAT=4
EXTENSIONS={'.py','.pyi','.js','.jsx','.ts','.tsx','.mjs','.cjs','.rs','.go','.java','.cs','.c','.h','.cpp','.hpp','.sh','.ps1','.sql','.kt','.kts','.swift','.rb','.php','.vue','.svelte'}
SKIP={'.git','.hg','.svn','node_modules','vendor','.venv','venv','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','dist','build','target','coverage','.next','.nuxt','.idea','.vscode','.codex','.agents','.omx','.luna-astra'}
SENSITIVE=re.compile(r'(^|[._-])(secret|secrets|credential|credentials|token|tokens|id_rsa|id_ed25519)([._-]|$)',re.I)


def terms(text: str) -> list[str]:
    words=re.findall(r'[A-Za-z_][A-Za-z_0-9]*|[\uAC00-\uD7A3]{2,}',text[:20000])
    out=[]
    for word in words:
        out.append(word.lower())
        out.extend(x.lower() for x in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[\uAC00-\uD7A3]+',word) if len(x)>1 and x.lower()!=word.lower())
    return out


def sensitive(path: str) -> bool:
    return any(p.startswith('.env') or SENSITIVE.search(p) or p.lower().endswith(('.pem','.key','.p12','.pfx')) for p in Path(path).parts)


def _ignore_rules(root: Path):
    path=root/'.gitignore'
    if not path.is_file() or path.is_symlink(): return [],False
    if path.stat().st_size>65536: return [],True
    try: text=path.read_text(encoding='utf-8')
    except (OSError,UnicodeError): return [],True
    patterns=[]; unsupported=False
    for line in text.splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('!') or '\\' in line:
            unsupported=True; continue  # Do not re-include excluded paths by guessing git semantics.
        patterns.append(line)
    return patterns,unsupported


def _ignored(rel: str, patterns, directory=False):
    # Conservative gitignore subset. Negations never silently re-include paths.
    for rule in patterns:
        base,pattern=rule if isinstance(rule,tuple) else ('',rule)
        if base and not rel.startswith(base+'/'):continue
        local=rel[len(base)+1:] if base else rel
        anchored=pattern.startswith('/')
        p=pattern.strip('/')
        if not p:continue
        if '/' not in p and not anchored:
            if any(fnmatch.fnmatchcase(part,p) for part in local.split('/')):return True
        if fnmatch.fnmatchcase(local,p) or local.startswith(p+'/'):return True
    return False


def _cached_info(value):
    """Old caches are acceleration data, never authority for malformed structures."""
    if not isinstance(value,dict):return False
    if not isinstance(value.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',value['sha256']):return False
    if value.get('confidence') not in {'python_ast','lexical_hint','parse_incomplete'}:return False
    for field in ('symbols','imports','calls','warnings'):
        if not isinstance(value.get(field),list):return False
    if not all(isinstance(x,dict) and isinstance(x.get('name'),str) and type(x.get('line')) is int and isinstance(x.get('kind'),str) for x in value['symbols']):return False
    if not all(isinstance(x,dict) and isinstance(x.get('module'),str) and type(x.get('level')) is int and isinstance(x.get('names'),list) and all(isinstance(n,str) for n in x['names']) for x in value['imports']):return False
    if not all(isinstance(x,str) for x in value['calls']+value['warnings']):return False
    return isinstance(value.get('terms'),dict) and all(isinstance(k,str) and type(v) is int and v>=0 for k,v in value['terms'].items())


def _read_source(path: Path, max_bytes: int):
    no_symlinks(path)
    before=path.stat()
    if not path.is_file() or before.st_size>max_bytes: raise HarnessError('oversized or nonregular source')
    data=path.read_bytes()
    after=path.stat()
    if len(data)>max_bytes or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
        raise HarnessError('source changed during read')
    if b'\x00' in data: raise HarnessError('binary source')
    if path.suffix in {'.py','.pyi'}:
        encoding,_=tokenize.detect_encoding(io.BytesIO(data).readline)
        text=data.decode(encoding)
    else: text=data.decode('utf-8-sig')
    return data,text


def parse_source(rel: str, text: str) -> dict:
    suffix=Path(rel).suffix.lower()
    symbols=[]; imports=[]; calls=[]; identifiers=[]; warnings=[]
    confidence='lexical_hint'
    if suffix in {'.py','.pyi'}:
        confidence='python_ast'
        try:
            tree=ast.parse(text,filename=rel)
            for node in ast.walk(tree):
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    symbols.append({'name':node.name,'line':node.lineno,'kind':'class' if isinstance(node,ast.ClassDef) else 'function'})
                elif isinstance(node,ast.Import): imports.extend({'module':n.name,'level':0,'names':[]} for n in node.names)
                elif isinstance(node,ast.ImportFrom): imports.append({'module':node.module or '', 'level':node.level, 'names':[n.name for n in node.names]})
                elif isinstance(node,ast.Call):
                    f=node.func
                    if isinstance(f,ast.Name): calls.append(f.id)
                    elif isinstance(f,ast.Attribute): calls.append(f.attr)
                    if isinstance(f,ast.Name) and f.id in {'__import__','eval','exec'}: warnings.append('dynamic_execution')
                    if isinstance(f,ast.Attribute) and f.attr=='import_module': warnings.append('dynamic_import')
            for token in tokenize.generate_tokens(io.StringIO(text).readline):
                if token.type==tokenize.NAME: identifiers.append(token.string)
        except (SyntaxError,tokenize.TokenError,IndentationError,RecursionError):
            confidence='parse_incomplete'; warnings.append('python_parse_error')
            # Names only. Never index string literal values after failed parsing.
    else:
        # Strip literals/comments for identifiers. Import paths are handled separately.
        cleaned=re.sub(r'(?s)/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`',lambda m:'\n'*m.group(0).count('\n')+' ',text)
        if suffix in {'.ps1','.sh'}:cleaned=re.sub(r'(?m)#[^\n]*','',cleaned)
        if suffix=='.sql':cleaned=re.sub(r'(?m)--[^\n]*','',cleaned)
        for match in re.finditer(r'\b(?:class|interface|function|def|fn|func|fun|struct|enum|trait|object|protocol)\s+([A-Za-z_$][\w$]*)',cleaned):
            symbols.append({'name':match.group(1),'line':cleaned.count('\n',0,match.start())+1,'kind':'lexical_symbol'})
        # Other languages deliberately index declarations, not arbitrary source words.
        # This is a hint index, not a language parser or a security-grade redactor.
        identifiers=[x['name'] for x in symbols]
        if suffix in {'.js','.jsx','.ts','.tsx','.mjs','.cjs'}:
            for m in re.finditer(r'(?:\bfrom\s*|\bimport\s*|\brequire\(\s*)["\']([./A-Za-z_@][\w./@-]{0,240})["\']',text):
                imports.append({'module':m.group(1),'level':0,'names':[]})
    # No string constants, comments, function bodies, prompts, or API credentials are stored.
    if len(symbols)>150 or len(imports)>150 or len(set(calls))>150 or len(' '.join(identifiers))>20000:
        warnings.append('truncated_static_details')
    counts=Counter(terms(' '.join(identifiers)))
    return {'symbols':symbols[:150], 'imports':imports[:150], 'calls':sorted(set(calls))[:150],
            'terms':dict(counts.most_common(350)), 'confidence':confidence,'warnings':sorted(set(warnings))}


class CodeMap:
    def __init__(self, root: Path, cache: Path, *, max_files=3000, max_file_bytes=512000, max_total_bytes=24*1024*1024):
        root=Path(root).absolute(); no_symlinks(root)
        self.root=root.resolve(); self.cache=Path(cache).absolute()
        if not self.root.is_dir(): raise HarnessError('workspace does not exist')
        if self.root==Path(self.root.anchor) or self.root==Path.home().resolve():
            raise HarnessError('refusing whole-drive/home index; use a project directory')
        if self.cache.resolve().is_relative_to(self.root): raise HarnessError('code map cache must be outside source workspace')
        for value in (max_files,max_file_bytes,max_total_bytes):
            if type(value) is not int or value<=0: raise HarnessError('invalid index budget')
        self.max_files=max_files; self.max_file_bytes=max_file_bytes; self.max_total_bytes=max_total_bytes
        no_symlinks(self.cache)
        self.path=self.cache/(json_hash(str(self.root))+'.json')

    def build(self, max_seconds: float | None = None):
        start=time.monotonic(); prior={}
        if self.path.is_file():
            try:
                obj=load_json(self.path)
                if isinstance(obj,dict) and obj.get('format')==FORMAT and obj.get('root')==str(self.root) and isinstance(obj.get('files'),dict): prior=obj['files']
            except (OSError,ValueError,TypeError): prior={}
        base_patterns,ignore_partial=_ignore_rules(self.root)
        patterns=[('',p) for p in base_patterns]
        files={}; skipped=[]; errors=[]; total=0; examined=0; hits=0; parsed=0; truncated=False
        stop=False
        for current,dirs,names in os.walk(self.root,followlinks=False):
            if max_seconds is not None and time.monotonic()-start>=max_seconds: truncated=True;break
            dirs.sort(); names.sort()
            if Path(current)!=self.root:
                extra,partial=_ignore_rules(Path(current))
                ignore_partial=ignore_partial or partial
                base=Path(current).relative_to(self.root).as_posix()
                patterns.extend((base,p) for p in extra)
            good=[]
            for name in dirs:
                p=Path(current)/name; rel=p.relative_to(self.root).as_posix()
                if name in SKIP or sensitive(rel) or _ignored(rel,patterns,True): continue
                try: no_symlinks(p)
                except HarnessError: skipped.append(rel+':link'); continue
                if (p/'.git').exists(): skipped.append(rel+':nested_repository'); continue
                good.append(name)
            dirs[:]=good
            for name in names:
                if max_seconds is not None and time.monotonic()-start>=max_seconds: truncated=True;stop=True;break
                examined+=1
                if examined>20000: truncated=True;stop=True;break
                p=Path(current)/name; rel=p.relative_to(self.root).as_posix()
                if p.suffix.lower() not in EXTENSIONS or sensitive(rel) or _ignored(rel,patterns): continue
                if len(files)>=self.max_files: truncated=True;stop=True;break
                try:
                    size=p.stat().st_size
                    if size>self.max_file_bytes: skipped.append(rel+':oversized');continue
                    if total+size>self.max_total_bytes: truncated=True;stop=True;break
                    data,text=_read_source(p,self.max_file_bytes);total+=len(data);sha=digest(data)
                    old=prior.get(rel)
                    if _cached_info(old) and old['sha256']==sha:
                        info=old.copy();hits+=1
                    else:
                        info=parse_source(rel,text);parsed+=1
                    info.update(sha256=sha,bytes=len(data))
                    files[rel]=info
                except (OSError,ValueError,UnicodeError,SyntaxError) as e: errors.append(rel+':'+type(e).__name__)
            if stop:break
        edges=self._edges(files)
        summary={'indexed_files':len(files),'parsed_files':parsed,'cache_hits':hits,'bytes_read':total,
                 'truncated':truncated,'ignored_patterns_partial':ignore_partial,'skipped':skipped[:40],'errors':errors[:40],
                 'parse_incomplete':sum(f['confidence']=='parse_incomplete' for f in files.values()),
                 'wall_seconds':time.monotonic()-start}
        result={'format':FORMAT,'root':str(self.root),'built_at':time.time(),'files':files,'edges':edges,'stats':summary,
                'identity':json_hash({p:f['sha256'] for p,f in files.items()}),
                'limit':'Static navigation hints, not exhaustive call graphs or source reading. Unindexed/dynamic code may affect behavior.'}
        write_json(self.path,result)
        return result

    def _edges(self, files):
        modules={}
        for rel in files:
            p=Path(rel)
            if p.suffix not in {'.py','.pyi'}: continue
            parts=list(p.with_suffix('').parts)
            if parts and parts[-1]=='__init__':parts.pop()
            name='.'.join(parts);modules.setdefault(name,[]).append(rel)
            if name.startswith('src.'):modules.setdefault(name[4:],[]).append(rel)
        edges={p:[] for p in files}
        for rel,f in files.items():
            targets=set()
            for imp in f['imports']:
                name=imp['module']
                if Path(rel).suffix in {'.py','.pyi'}:
                    if imp['level']:
                        base=list(Path(rel).parent.parts)
                        if base==['.']:base=[]
                        up=imp['level']-1
                        if up>len(base):continue
                        base=base[:len(base)-up]
                        name='.'.join(base+([name] if name else []))
                    candidates=[name]+[(name+'.' if name else '')+n for n in imp['names'] if n!='*']
                    for c in candidates:
                        found=modules.get(c,[])
                        if len(found)==1:targets.add(found[0])
                elif name.startswith('.'):
                    base=Path(os.path.normpath(str(Path(rel).parent/name))).as_posix()
                    for candidate in [base]+[base+s for s in ('.ts','.tsx','.js','.jsx','/index.ts','/index.js')]:
                        if candidate in files:targets.add(candidate)
            edges[rel]=sorted(targets-{rel})
        return edges

    def select(self, index: dict, query: str, hints: list[str] | None=None, max_chars=3200):
        if type(max_chars) is not int or not 400<=max_chars<=16000: raise HarnessError('invalid context budget')
        q=set(terms(query)); docs=index['files']; n=max(len(docs),1); df=Counter()
        for p,f in docs.items():
            for term in set(f['terms'])|set(terms(p)):df[term]+=1
        scores={}
        hints=set(hints or [])
        for p,f in docs.items():
            count=Counter(f['terms']);names=set(terms(p+' '+' '.join(s['name'] for s in f['symbols'])))
            score=sum(math.log(1+(n-df[t]+.5)/(df[t]+.5))*(1+math.log1p(count[t]))+(4 if t in names else 0) for t in q if count[t] or t in names)
            if p in hints:score+=100
            scores[p]=score
        seeds=sorted(scores,key=lambda p:(-scores[p],p))[:5]
        for source,targets in index['edges'].items():
            if source in seeds and scores[source]>0:
                for target in targets:scores[target]+=2
            if any(t in seeds and scores[t]>0 for t in targets):scores[source]+=2
        ordered=sorted(scores,key=lambda p:(-scores[p],p))
        header='LOCAL CODE MAP (navigation hints; read source before edits)\n'
        lines=[header.rstrip()]; selected=[]
        for p in ordered:
            f=docs[p]
            if q and scores[p]<=0:continue
            symbol_text=', '.join(s['name']+':'+str(s['line']) for s in f['symbols'][:5])
            line=f'{p} [{f["confidence"]}; sha={f["sha256"][:12]}] '+symbol_text
            if index['edges'].get(p):line+='; imports -> '+', '.join(index['edges'][p][:3])
            if len('\n'.join(lines+[line]))>max_chars-200:break
            lines.append(line);selected.append(p)
            if len(selected)>=12:break
        if not selected:lines.append('No confident match. Refine names/paths and inspect code; absence is not proof.')
        if index['stats']['truncated'] or index['stats']['errors'] or index['stats']['parse_incomplete']:
            lines.append('INCOMPLETE INDEX: broaden inspection before choosing verification scope.')
        return {'text':'\n'.join(lines),'selected_files':selected,'index_identity':index['identity'],
                'characters':len('\n'.join(lines)),'token_estimate':None,'stats':index['stats']}

    def risk(self,index:dict,changed:list[str],mandatory:list[str]|None=None):
        changed=list(dict.fromkeys(changed));reverse={p:set() for p in index['files']}
        for p,targets in index['edges'].items():
            for t in targets:reverse[t].add(p)
        affected=set(changed);queue=deque(changed)
        while queue:
            for p in reverse.get(queue.popleft(),set()):
                if p not in affected:affected.add(p);queue.append(p)
        tests=sorted(p for p in affected if re.search(r'(^|/)(tests?/|test_)|(_test|\.test|\.spec)\.',p))
        reasons=[]
        stats=index['stats']
        if not changed:reasons.append('no_changed_files_supplied')
        if stats['truncated'] or stats['errors'] or stats['parse_incomplete'] or stats['ignored_patterns_partial']:reasons.append('index_coverage_uncertain')
        if any(p not in index['files'] for p in changed):reasons.append('unindexed_or_deleted_change')
        if any(index['files'].get(p,{}).get('confidence')!='python_ast' for p in affected):reasons.append('non_structural_or_unknown_dependency')
        if any(index['files'].get(p,{}).get('warnings') for p in affected):reasons.append('dynamic_or_incomplete_code')
        if any(re.search(r'(auth|security|cache|thread|async|concurr|payment|settle|timestamp|schema|config|lock)',p,re.I) for p in changed):reasons.append('sensitive_behavior')
        if not tests:reasons.append('no_mapped_tests')
        if len(affected)>8:reasons.append('broad_shared_impact')
        return {'risk':'broader_review' if reasons else 'focused_candidate','reasons':reasons,'affected_files':sorted(affected),
                'suggested_tests':tests,'mandatory_checks':list(mandatory or []),'automatic_test_skipping':False,
                'decision':'Keep every caller-required check. Suggestions cannot certify complete dependency coverage.'}
