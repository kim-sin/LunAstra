"""Advisory CLI discovery; inspect local hook observations separately."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

# Reference coverage, not a minimum version or an installation gate.
REVIEWED_CODEX = {(0, 154, 0)}


def version_status(text: str) -> dict:
    if not isinstance(text,str) or len(text)>4096:
        return {'status':'UNKNOWN','version':None,
                'message':'CLI version output was invalid or oversized. Installation is not blocked.'}
    match = re.fullmatch(r'codex(?:-cli)?\s+(\d+)\.(\d+)\.(\d+)([-+][0-9A-Za-z.+-]+)?\s*', text.strip())
    if not match:
        return {'status': 'UNKNOWN', 'version': None,
                'message': 'CLI version output was not recognized. Installation is not blocked.'}
    version = tuple(int(match[i]) for i in (1, 2, 3))
    label = '.'.join(map(str, version)) + (match[4] or '')
    if match[4] and match[4].startswith('-'):
        status, message = 'PREVIEW', 'Preview CLI detected. Its version alone does not establish active-host compatibility.'
    elif version in REVIEWED_CODEX:
        status, message = 'REVIEWED', 'Reference CLI version detected. Offline coverage is not a live connection check.'
    else:
        status, message = 'UNREVIEWED', 'CLI version is outside the pinned reference. Installation is allowed; check actual hook activity.'
    return {'status': status, 'version': label, 'message': message}


def inspect_host(executable: str | None = None) -> dict:
    """Probe at most one CLI; never assume it is the desktop/IDE's active engine."""
    command = str(Path(executable).absolute()) if executable else shutil.which('codex')
    result = {'status': 'UNKNOWN', 'version': None, 'executable': command,
              'origin': 'EXPLICIT_CLI' if executable else 'PATH_CLI',
              'advisory_only': True, 'active_host_identified': False,
              'executable_found': bool(command),
              'python_version': '.'.join(map(str, sys.version_info[:3])),
              'git_found': bool(shutil.which('git')), 'live_verified': False}
    if not command:
        result['message'] = 'No CLI found on PATH. A desktop or IDE may use its own engine. Installation is allowed.'
        return result
    try:
        completed = subprocess.run([command, '--version'], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, encoding='utf-8', errors='replace',
                                   timeout=5, shell=False)
        if completed.returncode:
            result['message'] = 'CLI version probe failed. Installation is allowed; use the active app to review hooks.'
        else:
            result.update(version_status(completed.stdout or completed.stderr))
    except (OSError, subprocess.SubprocessError):
        result['message'] = 'CLI version probe was unavailable or timed out. Installation is allowed.'
    return result


def configuration_hints(home: Path) -> dict:
    """Inspect direct root settings only; do not imply full profile/policy resolution."""
    result = {'native_agent_setting': 'NOT_INSPECTED', 'native_concurrency': None,
              'hooks_explicitly_disabled': False, 'config_parse': 'ABSENT',
              'note': 'Direct root settings only. Profiles, managed policy, remote hosts and live tool availability must be checked in Codex.'}
    path = Path(home) / 'config.toml'
    if not path.is_file():
        return result
    try:
        raw = path.read_text(encoding='utf-8-sig')
        try:
            import tomllib
        except ImportError:
            # Preserve the stdlib-only Python 3.10 runtime. Do not guess a TOML
            # interpretation or silently certify feature flags without a parser.
            result['config_parse'] = 'NOT_INSPECTED_PYTHON_310'
            return result
        cfg = tomllib.loads(raw)
        features, agents = cfg.get('features', {}), cfg.get('agents', {})
        if not isinstance(features, dict) or not isinstance(agents, dict):
            raise ValueError('invalid settings table')
        def enabled(value):
            return value.get('enabled') if isinstance(value, dict) else value
        # Luna uses V1; an explicitly disabled V2 must not be reported as a
        # disabled V1. The current key takes precedence over its legacy alias.
        setting = enabled(features.get('multi_agent', features.get('collab')))
        result['native_agent_setting'] = 'EXPLICITLY_DISABLED' if setting is False else 'NO_EXPLICIT_DISABLE'
        result['hooks_explicitly_disabled'] = enabled(features.get('hooks', features.get('codex_hooks'))) is False
        result['native_concurrency'] = agents.get('max_threads')
        result['config_parse'] = 'PARSED_ROOT_SETTINGS'
    except (OSError, UnicodeError, ValueError):
        result['config_parse'] = 'UNREADABLE'
    return result
