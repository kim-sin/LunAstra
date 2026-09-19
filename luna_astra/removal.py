"""Explicit removal of owned local data; never remove a project or stop a job."""
from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path
import re
import shutil
import sqlite3
import stat

from .install import Installer, OWNER, install_lock, read_hooks, strip_owned, decoded
from .util import HarnessError, canonical, digest, load_json, no_symlinks, strict_json, write_json

CONFIRMATION = 'DELETE-LUNASTRA-DATA'
_ALLOWED = {'releases', 'backups', 'installation.json', 'install.lock', 'model-gate-trace'}


def _readonly_database(path: Path):
    no_symlinks(path)
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)


def _active_records(app: Path) -> list[str]:
    blockers = []
    databases = []
    for state in app.glob('state-v*'):
        if not state.is_dir():
            continue
        if (state / 'runtime.sqlite3').is_file():
            databases.append(state / 'runtime.sqlite3')
        databases.extend(state.glob('sessions/*/evidence.sqlite3'))
    for path in databases:
        no_symlinks(path)
        try:
            with closing(_readonly_database(path)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise HarnessError('Runtime database integrity check failed.')
                for table, column, states in (
                    ('work','state',{'pending','reserved','running','returned','accepted','abandoned','failed'}),
                    ('dispatches','state',{'pending','running','returned','failed','unknown'}),
                    ('attempts','status',{'RUNNING','PASS','FAIL','ERROR','STALE'})):
                    if table in tables and any(r[0] not in states for r in db.execute('SELECT DISTINCT '+column+' FROM '+table)):
                        raise HarnessError('Unknown runtime activity state.')
                if 'work' in tables and db.execute("SELECT 1 FROM work WHERE state IN ('reserved','running','returned') LIMIT 1").fetchone():
                    blockers.append('unresolved delegated work')
                if 'dispatches' in tables and db.execute("SELECT 1 FROM dispatches WHERE state IN ('pending','running','unknown') LIMIT 1").fetchone():
                    blockers.append('unresolved native worker dispatch')
                if 'attempts' in tables and db.execute("SELECT 1 FROM attempts WHERE status='RUNNING' LIMIT 1").fetchone():
                    blockers.append('an unfinished verification attempt')
                if 'research_studies' in tables:
                    for raw, in db.execute('SELECT spec FROM research_studies'):
                        research=strict_json(raw)
                        if research.get('state') not in {'PAUSED','FINISHED'}:
                            blockers.append('an active or unknown research controller')
                if 'research_jobs' in tables and db.execute("SELECT 1 FROM research_jobs WHERE state='RUNNING' LIMIT 1").fetchone():
                    blockers.append('an unfinished research subprocess')
                if 'kv' in tables:
                    for name, raw in db.execute("SELECT name,value FROM kv WHERE name LIKE 'job:%'"):
                        from .jobs import job_record
                        value = job_record(raw)
                        if value.get('status') not in {'FINISHED', 'ERROR'}:
                            blockers.append('an active or unknown check controller')
        except (sqlite3.Error, ValueError, OSError) as exc:
            raise HarnessError('Runtime state cannot be inspected safely; preserve it and use the recovery guide.') from exc
    return sorted(set(blockers))


def _inventory(app: Path) -> dict:
    files = {}
    for current, dirs, names in os.walk(app, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(current) / name
            no_symlinks(path)
            st = path.lstat()
            if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
                raise HarnessError('Nonregular data cannot be removed automatically: ' + str(path))
            rel = path.relative_to(app).as_posix()
            if rel == 'install.lock':
                continue
            files[rel] = [st.st_size, st.st_mtime_ns, st.st_ino, stat.S_IFMT(st.st_mode)]
            if len(files) > 100000:
                raise HarnessError('Removal inventory exceeds 100,000 entries; use the recovery guide.')
    return files


def purge_plan(installer: Installer, *, include_workspaces: bool = False) -> dict:
    home = installer.home
    app = home / 'luna-astra'
    no_symlinks(app)
    if not app.exists():
        return {'exists': False, 'target': str(app), 'files': 0, 'bytes': 0, 'blockers': [], 'workspaces': 0}
    if installer.package.is_relative_to(app) or Path(os.path.abspath(os.sys.executable)).is_relative_to(app):
        raise HarnessError('Run removal from the extracted distribution, outside the installed data directory.')
    receipt = installer._receipt()
    if not receipt or not receipt.get('release') or not receipt.get('state'):
        raise HarnessError('Owned installation receipt is missing; automatic data removal is refused.')
    release, state = Path(receipt['release']).absolute(), Path(receipt['state']).absolute()
    if release.parent != app / 'releases' or state.parent != app or not re.fullmatch(r'state-v\d+', state.name):
        raise HarnessError('Receipt locations are outside the owned installation layout.')
    for child in app.iterdir():
        if child.name not in _ALLOWED and not re.fullmatch(r'state-v\d+', child.name):
            raise HarnessError('Unrecognized installation data is preserved: ' + child.name)
    inventory = _inventory(app)
    _, hooks = read_hooks(home / 'hooks.json')
    clean = strip_owned(hooks, receipt, home)
    for groups in clean.get('hooks', {}).values():
        for group in groups:
            for handler in group['hooks']:
                commands = [str(handler.get(field,'')) for field in ('command','commandWindows')]
                if any(str(app).casefold() in (command+' '+decoded(command)).casefold() for command in commands):
                    raise HarnessError('A retained hook still references the installed data directory.')
                if str(handler.get('statusMessage', '')).startswith((OWNER, 'Luna Astra v2 / ', 'Luna Astra / owned worker hook /')):
                    raise HarnessError('Modified or unowned LunAstra hooks remain. Resolve them before deleting their code.')
    workspaces = sum(1 for name in inventory if '/worktrees/' in '/' + name and name.endswith('/tree'))
    blockers = _active_records(app)
    if (app/'model-gate-trace'/'active.json').exists() or (app/'model-gate-trace'/'control.lock').exists():
        blockers.append('model-gate diagnostic marker/operation present; stop diagnostics before explicit data removal')
    if workspaces and not include_workspaces:
        blockers.append('worktree copies exist; export needed changes and explicitly include workspaces')
    return {'exists': True, 'target': str(app), 'files': sum(v[3] == stat.S_IFREG for v in inventory.values()),
            'bytes': sum(v[0] for v in inventory.values() if v[3] == stat.S_IFREG),
            'inventory_sha256': digest(canonical(inventory).encode()), 'workspaces': workspaces,
            'blockers': blockers, 'external_projects_deleted': False,
            'warning': 'Model-gate diagnostic captures, runtime notes, test logs, hook backups, installed releases and explicitly included worktree copies will be deleted. Project Git worktree registrations are not modified.'}


def purge(installer: Installer, *, confirm: str = '', confirm_idle: bool = False,
          include_workspaces: bool = False) -> dict:
    if confirm != CONFIRMATION or not confirm_idle:
        raise HarnessError('Removal requires --confirm DELETE-LUNASTRA-DATA and --confirm-idle after closing all Codex sessions and local checks.')
    plan = purge_plan(installer, include_workspaces=include_workspaces)
    if not plan['exists']:
        return {**plan, 'removed': False}
    app = installer.home / 'luna-astra'
    with install_lock(installer.home):
        plan = purge_plan(installer, include_workspaces=include_workspaces)
        if plan['blockers']:
            raise HarnessError('Removal blocked: ' + '; '.join(plan['blockers']))
        before, obj = read_hooks(installer.home / 'hooks.json')
        receipt = installer._receipt()
        clean = strip_owned(obj, receipt, installer.home)
        # Re-read immediately before changing registrations, just as installation does.
        current = (installer.home / 'hooks.json').read_bytes() if (installer.home / 'hooks.json').exists() else None
        if current != before:
            raise HarnessError('Hook configuration changed while preparing removal.')
        if clean != obj:
            write_json(installer.home / 'hooks.json', clean)
        # Retain the ownership receipt until all other data is removed, so an
        # interrupted deletion can be retried from the same known root.
        for child in sorted(app.iterdir()):
            if child.name in {'install.lock', 'installation.json'}:
                continue
            no_symlinks(child)
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        (app / 'installation.json').unlink()
    # Never recursively remove after releasing the lock: a concurrent reinstall
    # may already have created new files. rmdir can only remove an empty root.
    try:
        app.rmdir()
    except OSError:
        if not app.exists():
            pass
        elif any(app.iterdir()):
            return {**plan, 'removed': True, 'container_retained': True,
                    'note': 'New or remaining entries were preserved after removal; inspect the target.'}
        else:
            raise
    return {**plan, 'removed': True, 'container_retained': False,
            'note': 'Owned local data removed. No process was stopped. External project files and their Git administrative records were preserved.'}
