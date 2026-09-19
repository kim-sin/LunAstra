"""Small, dependency-free primitives with explicit filesystem boundaries."""
from __future__ import annotations
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

class HarnessError(ValueError):
    """An invalid or unsafe request; callers must not substitute success."""
    def __init__(self, message: str, *, code: str = "INVALID_REQUEST", details=None):
        super().__init__(message)
        self.code = code
        self.details = details


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def json_hash(value: Any) -> str:
    return digest(canonical(value).encode("utf-8"))

def strict_json(text: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise HarnessError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda s: (_ for _ in ()).throw(HarnessError(f"invalid JSON number: {s}")))

def load_json(path: Path) -> Any:
    return strict_json(path.read_text(encoding="utf-8-sig"))

def no_symlinks(path: Path) -> None:
    path = Path(os.path.abspath(path))
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise HarnessError(f"symlink is not allowed here: {candidate}")
        if candidate.exists() and (getattr(candidate, "is_junction", lambda: False)()
                                  or getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400):
            raise HarnessError(f"junction is not allowed here: {candidate}")

def inside(root: Path, relative: str, *, allow_root: bool = False) -> Path:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise HarnessError("path must be a nonempty relative string")
    # Reject alternate OS absolute paths too; manifests can travel between systems.
    p = Path(relative)
    if p.is_absolute() or ":" in relative or "\\" in relative or ".." in p.parts:
        raise HarnessError(f"unsafe relative path: {relative!r}")
    if relative in (".", "./") and not allow_root:
        raise HarnessError("explicit source/test directories required; whole-root scan is not implicit")
    target = root / p
    no_symlinks(target)
    target = target.resolve()
    if not target.is_relative_to(root.resolve()):
        raise HarnessError("path escaped workspace")
    return target

def atomic_write(path: Path, data: bytes) -> None:
    no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".luna-astra-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))

def stat_identity(st):
    """File identity/change metadata, never a substitute for a content digest."""
    return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,st.st_mode)

def file_hash(path: Path) -> str:
    before=path.stat()
    h=hashlib.sha256()
    with path.open('rb') as f:
        opened=os.fstat(f.fileno())
        if stat_identity(before)!=stat_identity(opened):
            raise HarnessError(f"file replaced before fingerprinting: {path}")
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
        ended=os.fstat(f.fileno())
    after=path.stat()
    if stat_identity(before)!=stat_identity(ended) or stat_identity(ended)!=stat_identity(after):
        raise HarnessError(f"file changed while fingerprinting: {path}")
    return h.hexdigest()

SKIP_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})

def snapshot(root: Path, dependencies: list[str]) -> dict[str, str]:
    if not dependencies or not isinstance(dependencies, list):
        raise HarnessError("at least one explicit dependency is required")
    root = Path(root).absolute(); no_symlinks(root); root = root.resolve()
    result: dict[str, str] = {}
    for dep in dependencies:
        target = inside(root, dep)
        if not target.exists():
            raise HarnessError(f"dependency missing: {dep}")
        if target.is_dir():
            result[target.relative_to(root).as_posix() + "/"] = "DIRECTORY"
            for current, dirs, files in os.walk(target, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for name in dirs + sorted(files):
                    child = Path(current) / name
                    no_symlinks(child)
                    rel = child.relative_to(root).as_posix()
                    if child.is_dir():
                        result[rel + "/"] = "DIRECTORY"
                    elif child.is_file():
                        result[rel] = file_hash(child)
                    else:
                        raise HarnessError(f"not a regular dependency: {rel}")
        elif target.is_file():
            result[target.relative_to(root).as_posix()] = file_hash(target)
        else:
            raise HarnessError(f"not a regular dependency: {dep}")
    return dict(sorted(result.items()))
