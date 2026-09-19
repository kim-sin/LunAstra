"""One path-identity rule for scopes, receipts and change detection.

Display spelling is kept separately. This does not grant access to a path;
all identities pass the existing traversal/symlink guard first.
"""
from __future__ import annotations
import os
import posixpath
from pathlib import Path
from .util import HarnessError, inside


def relative_id(value: str, *, windows: bool | None = None) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise HarnessError("invalid path identity")
    windows = os.name == "nt" if windows is None else windows
    value = value.replace("\\", "/") if windows else value
    if value.startswith("/") or ":" in value or "\\" in value or ".." in value.split("/"):
        raise HarnessError("unsafe relative path identity")
    value = posixpath.normpath(value)
    return value.casefold() if windows else value


def identity(root: Path, value: str) -> str:
    inside(root, value, allow_root=True)
    return relative_id(value)


def covers(root: Path, dependency: str, target: str) -> bool:
    parent, child = identity(root, dependency), identity(root, target)
    return parent == "." or parent == child or child.startswith(parent.rstrip("/") + "/")


def uncovered(root: Path, targets: list[str], dependencies: list[str]) -> list[str]:
    parents = {identity(root, d) for d in dependencies}
    result = []
    for path in targets:
        key = identity(root, path)
        if not any(p == "." or p == key or key.startswith(p.rstrip("/") + "/") for p in parents):
            result.append(path)
    return sorted(set(result))
