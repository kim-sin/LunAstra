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

from .util import HarnessError, inside, no_symlinks

_AGENT_TOOLS = {'spawn_agent', 'wait_agent', 'send_input', 'close_agent', 'resume_agent'}
_HELPERS = {
    'help', 'context', 'risk', 'begin', 'run', 'run-all', 'status', 'finish',
    'note', 'trace', 'claim', 'release', 'team-join', 'jobs', 'start-check',
    'worker-exec', 'read', 'input-append', 'crew-join', 'crew-report',
    'crew-start','crew-revise','crew-continue','crew-next','crew-state','crew-drive','crew-recover','crew-report-read','crew-execute','crew-repair','crew-review','crew-complete',
}


def tool_name(value: str) -> str:
    # Codex flattens multi_agent_v1 + name without a separator. Do not match
    # arbitrary MCP tools just because their names end in a familiar word.
    if value.startswith('multi_agent_v1'):
        suffix = value[len('multi_agent_v1'):]
        if suffix in _AGENT_TOOLS:
            return suffix
    if value.startswith('functions.'):
        suffix = value[len('functions.'):]
        if suffix in _AGENT_TOOLS | {'apply_patch', 'exec_command', 'shell_command'}:
            return suffix
    return value


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
    if not windows:
        return None
    argv = literal_argv(command)
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
    """Read-only navigation for delegates without granting arbitrary execution."""
    if type(start_line) is not int or start_line<1 or type(max_lines) is not int or not 1<=max_lines<=2000:
        raise HarnessError('read requires start-line >= 1 and max-lines in 1..2000')
    target=inside(root,path)
    if not target.is_file() or target.stat().st_size>4*1024*1024:
        raise HarnessError('source unavailable or exceeds the 4 MiB read limit')
    lines=target.read_text(encoding='utf-8-sig').splitlines()
    selected=lines[start_line-1:start_line-1+max_lines]
    # A single generated source line can be huge: bound response bytes too.
    used=0;result=[]
    for line in selected:
        used+=len(line.encode('utf-8'))
        if used>128000:break
        result.append(line)
    if selected and not result:raise HarnessError('source line exceeds the 128 KiB response limit')
    end=start_line-1+len(result)
    return {'path':path,'start_line':start_line,'end_line':end,'total_lines':len(lines),
            'lines':result,'eof':end>=len(lines),'next_start_line':end+1 if end<len(lines) else None}