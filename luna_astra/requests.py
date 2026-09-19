"""Content-addressed, owner-scoped JSON requests. No command evaluation.

A PreToolUse hook stores a validated literal JSON argument once, then rewrites
only its transport to --input-ref sha256:... . The model no longer has to send
hundreds of tiny input-append tool calls. Private blobs are never packaged.
"""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
from .util import HarnessError, atomic_write, canonical, no_symlinks, strict_json

MAX_BYTES = 2 * 1024 * 1024
KEY = re.compile(r"[a-f0-9]{64}")


def _directory(state: Path, owner: str) -> Path:
    if not isinstance(owner, str) or not KEY.fullmatch(owner):
        raise HarnessError("request requires an observed session key")
    path = Path(state).absolute() / "requests" / owner
    no_symlinks(path)
    return path


def put(state: Path, owner: str, raw: str) -> str:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise HarnessError("request exceeds 2 MiB")
    # Hash canonical data, not an encoding or a mutable user-selected filename.
    data = canonical(strict_json(raw)).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise HarnessError("canonical request exceeds 2 MiB")
    digest = hashlib.sha256(data).hexdigest()
    target = _directory(state, owner) / (digest + ".json")
    no_symlinks(target)
    if target.exists():
        if not target.is_file() or target.read_bytes() != data:
            raise HarnessError("immutable request blob changed")
    else:
        atomic_write(target, data)
    return "sha256:" + digest


def read(state: Path, owner: str, reference: str) -> str:
    if not isinstance(reference, str) or not reference.startswith("sha256:"):
        raise HarnessError("invalid request reference")
    digest = reference[7:]
    if not KEY.fullmatch(digest):
        raise HarnessError("invalid request digest")
    target = _directory(state, owner) / (digest + ".json")
    no_symlinks(target)
    if not target.is_file() or target.stat().st_size > MAX_BYTES:
        raise HarnessError("request blob missing or oversized for this session")
    with target.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != digest:
        raise HarnessError("request blob fingerprint mismatch")
    text = data.decode("utf-8")
    strict_json(text)
    return text
