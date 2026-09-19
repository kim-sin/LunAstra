"""Pinned Codex hook boundary: names, safe helper commands and explicit cwd.

The native Bash hook does not expose exec_command.workdir or the selected
shell. Never invent either field. Assigned workers use a literal helper
invocation; worker-exec accepts an argv array and runs it from the recorded
checkout. This is cwd routing, not a replacement for the host's OS sandbox.
"""
from __future__ import annotations

import base64
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from .util import HarnessError, inside, no_symlinks, stat_identity

_AGENT_TOOLS = {'spawn_agent', 'wait_agent', 'send_input', 'close_agent', 'resume_agent', 'followup_task', 'send_message', 'interrupt_agent', 'list_agents'}
_HELPERS = {
    'help', 'context', 'risk', 'begin', 'run', 'run-all', 'status', 'finish',
    'note', 'trace', 'claim', 'release', 'team-join', 'jobs', 'start-check',
    'worker-exec', 'read', 'read-bytes', 'read-source', 'resources', 'input-append', 'crew-join', 'crew-report',
    'crew-step','research-configure','research-enqueue','research-status','research-start','research-recover','research-pause','research-finish','research-wait','research-cancel','research-resume','research-policy','research-read',
    'crew-start','crew-capacity','crew-revise','crew-continue','crew-next','crew-state','crew-drive','crew-reconcile','crew-retry','crew-recover','crew-report-read','crew-execute','crew-repair','crew-review','crew-complete',
}


def tool_name(value: str) -> str:
    # Shared with the cheap hook selector, including supported functions.* edits.
    from .hook_policy import canonical_tool
    return canonical_tool(value)


def helper_command(argv: list[str], *, windows: bool | None = None) -> str:
    windows = os.name == 'nt' if windows is None else windows
    if windows:
        return '& ' + ' '.join("'" + x.replace("'", "''") + "'" for x in argv)
    return shlex.join(argv)


def literal_argv(command: str) -> list[str]:
    """Accept only literal one-command encodings; no evaluation or shell parser."""
    if not isinstance(command, str) or not command or '\x00' in command:
        raise HarnessError('expected one literal local helper command')
    if command.startswith('& '):
        body = command[2:]
        tokens = re.findall(r"'(?:[^']|'')*'|[A-Za-z0-9_./:-]+", body)
        if not tokens or ' '.join(tokens) != body:
            raise HarnessError('use the quoted LOCAL_HELPER_COMMAND without shell operators')
        return [t[1:-1].replace("''", "'") if t.startswith("'") else t for t in tokens]
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise HarnessError('invalid local helper quoting') from exc
    if not argv or shlex.join(argv) != command:
        raise HarnessError('use the literal LOCAL_HELPER_COMMAND without pipes or shell substitutions')
    return argv


def validate_worker_shell(command: str, prefix: list[str], *, joined: bool, read_only: bool = False) -> str:
    argv = literal_argv(command)
    if argv[:len(prefix)] != prefix:
        raise HarnessError('worker shell must use its own LOCAL_HELPER_COMMAND; raw shell cwd is not observable')
    rest = argv[len(prefix):]
    if rest[:1] in (['--input-json'],['--input-ref']):
        if len(rest) < 3:
            raise HarnessError('missing helper JSON or subcommand')
        rest = rest[2:]
    if not rest or rest[0] not in _HELPERS:
        raise HarnessError('unsupported worker helper command')
    if not joined and rest[0] not in {'team-join', 'crew-join', 'help', 'context', 'status', 'trace', 'jobs'}:
        raise HarnessError('join the assigned ticket before executing or changing files')
    if read_only and rest[0] in {'worker-exec','run','run-all','start-check'}:
        raise HarnessError('read-only delegates inspect with read/context/risk; send executable checks to the leader')
    return rest[0]


def worker_shell_input(command: str, prefix: list[str], *, joined: bool,
                       read_only: bool = False, windows: bool | None = None) -> dict | None:
    """Validate the actual Bash boundary and preserve native Windows arguments.

    Windows PowerShell 5.1 can strip embedded quotes when calling native EXEs.
    Pass the validated argument vector to ProcessStartInfo instead of relying
    on that legacy binder. No profile, policy, account or elevation is changed.
    """
    validate_worker_shell(command, prefix, joined=joined, read_only=read_only)
    return literal_shell_input(command, prefix, windows=windows)


def literal_shell_input(command: str, prefix: list[str], *, windows: bool | None = None) -> dict | None:
    """Preserve literal helper argv; caller performs role and phase checks."""
    if literal_argv(command)[:len(prefix)] != prefix:
        raise HarnessError('helper must use its own literal command prefix')
    windows = os.name == 'nt' if windows is None else windows
    argv = literal_argv(command)
    original_argv = list(argv)
    rest = argv[len(prefix):]
    if rest[:1] == ['--input-json'] and len(rest) >= 3 and len(rest[1].encode('utf-8')) > 1000:
        from .requests import put
        try:
            state = Path(prefix[prefix.index('--state')+1])
            owner = prefix[prefix.index('--session')+1]
        except (ValueError, IndexError) as exc:
            raise HarnessError('large request requires the observed state and session') from exc
        reference = put(state, owner, rest[1])
        argv = prefix + ['--input-ref', reference] + rest[2:]
    if not windows:
        return {'command':helper_command(argv,windows=False)} if argv != original_argv else None
    quote = lambda s: "'" + s.replace("'", "''") + "'"

    script = (
        "$ErrorActionPreference='Stop'; "
        "$p=New-Object System.Diagnostics.Process; "
        "$p.StartInfo.UseShellExecute=$false; "
        "$p.StartInfo.FileName=" + quote(argv[0]) + "; "
        "$p.StartInfo.Arguments=" + quote(subprocess.list2cmdline(argv[1:])) + "; "
        "try { if(-not $p.Start()){throw 'helper did not start'}; "
        "$p.WaitForExit(); $code=$p.ExitCode } finally { $p.Dispose() }; exit $code"
    )
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    rewritten = 'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ' + encoded
    # cmd.exe has an 8191-character limit; use a conservative bound that also
    # works when the native Codex shell was configured as cmd instead of PS.
    if len(rewritten) > 8000:
        raise HarnessError('Windows helper arguments exceed the safe command limit; split the request into smaller commands')
    return {'command': rewritten}


def worker_exec(meta: dict, argv: list[str], relative_cwd: str = '.') -> dict:
    if meta.get('role') != 'worker' or not meta.get('team_ticket') or not meta.get('assigned_workspace'):
        raise HarnessError('worker-exec requires a joined native worker ticket')
    if meta.get('read_only'):
        raise HarnessError('read-only delegates cannot execute arbitrary commands in the leader workspace')
    if (not isinstance(argv, list) or not argv or len(argv) > 512 or
            any(not isinstance(v, str) or '\x00' in v for v in argv) or not argv[0] or
            sum(len(v) for v in argv) > 256 * 1024):
        raise HarnessError('worker-exec argv must be a bounded nonempty string array')
    root = Path(meta['assigned_workspace']).absolute()
    no_symlinks(root)
    cwd = inside(root, relative_cwd, allow_root=True)
    if not cwd.is_dir():
        raise HarnessError('worker command directory is unavailable')
    env = os.environ.copy()
    env['PWD'] = str(cwd)
    # Git overrides inherited from a launcher must not redirect a worker's Git
    # operations into the leader checkout. Preserve other user configuration.
    for key in tuple(env):
        if key in {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
                   'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_CONFIG_COUNT'} or key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_')):
            env.pop(key, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    # No timeout/termination: native Codex owns command lifecycle. Temporary
    # files bound memory even when an invoked command writes a large log.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=err, shell=False)
        def tail(stream):
            size = stream.tell()
            stream.seek(max(0, size - 64000))
            return stream.read().decode('utf-8', 'replace'), size > 64000
        stdout, clipped_out = tail(out)
        stderr, clipped_err = tail(err)
    return {'exit_code': process.returncode, 'cwd': str(cwd), 'stdout': stdout,
            'stderr': stderr, 'output_truncated': clipped_out or clipped_err,
            'verification_receipt': False,
            'limit': 'Explicit cwd only. Native permissions still apply; argv programs can access paths allowed by the host.'}


def read_source(root: Path, path: str, start_line: int = 1, max_lines: int = 400) -> dict:
    """Read a bounded line window without loading a multi-megabyte file."""
    if type(start_line) is not int or start_line<1 or type(max_lines) is not int or not 1<=max_lines<=2000:
        raise HarnessError('read requires start-line >= 1 and max-lines in 1..2000')
    target=inside(root,path)
    if not target.exists():raise HarnessError('source not found: '+path,code='SOURCE_NOT_FOUND')
    if not target.is_file():raise HarnessError('source is not a regular file: '+path,code='SOURCE_NOT_REGULAR')
    before=target.stat(); result=[]; used=0; number=0; eof=False
    try:
        with target.open('r',encoding='utf-8-sig',newline=None) as stream:
            if stat_identity(before)!=stat_identity(os.fstat(stream.fileno())):
                raise HarnessError('source replaced before reading',code='SOURCE_CHANGED')
            while True:
                line=stream.readline(128001)
                if not line:
                    eof=True;break
                number+=1
                if len(line)>128000 and not line.endswith('\n'):
                    raise HarnessError('source line exceeds the 128 KiB response limit; use read-bytes',
                                       code='SOURCE_LINE_TOO_LARGE',details={'path':path,'line':number,'next_action':'read-bytes'})
                if number<start_line:continue
                value=line.rstrip('\r\n'); size=len(value.encode('utf-8'))
                if len(result)>=max_lines or used+size>128000:
                    if not result:raise HarnessError('source line exceeds the 128 KiB response limit; use read-bytes',code='SOURCE_LINE_TOO_LARGE')
                    break
                used+=size;result.append(value)
            ended=os.fstat(stream.fileno())
    except PermissionError as exc:
        raise HarnessError('source permission denied: '+path,code='SOURCE_PERMISSION_DENIED') from exc
    except UnicodeError as exc:
        raise HarnessError('source is not valid UTF-8; use read-bytes',code='SOURCE_ENCODING_ERROR') from exc
    after=target.stat()
    if stat_identity(before)!=stat_identity(ended) or stat_identity(ended)!=stat_identity(after):
        raise HarnessError('source changed while reading',code='SOURCE_CHANGED')
    end=start_line-1+len(result)
    return {'path':path,'start_line':start_line,'end_line':end,'total_lines':number if eof else None,
            'lines':result,'eof':eof,'next_start_line':None if eof else end+1,
            'source_size_bytes':after.st_size,'source_mtime_ns':after.st_mtime_ns}


def read_bytes(root: Path, path: str, offset: int = 0, max_bytes: int = 64000) -> dict:
    """Exact bounded bytes, including huge JSONL lines and non-UTF8 sources."""
    if type(offset) is not int or offset<0 or type(max_bytes) is not int or not 1<=max_bytes<=128000:
        raise HarnessError('invalid byte window')
    target=inside(root,path)
    if not target.exists():raise HarnessError('source not found: '+path,code='SOURCE_NOT_FOUND')
    if not target.is_file():raise HarnessError('source is not a regular file',code='SOURCE_NOT_REGULAR')
    before=target.stat()
    try:
        with target.open('rb') as stream:
            if stat_identity(before)!=stat_identity(os.fstat(stream.fileno())):
                raise HarnessError('source replaced before reading',code='SOURCE_CHANGED')
            stream.seek(offset); data=stream.read(max_bytes)
            ended=os.fstat(stream.fileno())
    except PermissionError as exc:
        raise HarnessError('source permission denied',code='SOURCE_PERMISSION_DENIED') from exc
    after=target.stat()
    if stat_identity(before)!=stat_identity(ended) or stat_identity(ended)!=stat_identity(after):
        raise HarnessError('source changed while reading',code='SOURCE_CHANGED')
    end=offset+len(data)
    try:text=data.decode('utf-8');encoding='utf-8'
    except UnicodeError:text=base64.b64encode(data).decode('ascii');encoding='base64'
    return {'path':path,'offset':offset,'end_offset':end,'source_size_bytes':after.st_size,
            'data':text,'encoding':encoding,'eof':end>=after.st_size,
            'next_offset':None if end>=after.st_size else end,'source_mtime_ns':after.st_mtime_ns}
