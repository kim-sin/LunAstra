"""Prepare a typed, byte-bound resource registry before any native dispatch.

Missing outputs are valid. Missing required inputs are not manufactured or
silently reclassified. The registry indexes original sources, not a root's
summary of them, so independent reviewers retain access to actual evidence.
"""
from __future__ import annotations
from pathlib import Path
from .util import HarnessError, canonical, file_hash, inside, json_hash, no_symlinks
from .coordination import normalized
from .paths import covers

ROLES = ("required_inputs", "optional_inputs", "outputs", "protected", "working")


def prepare(root: Path, resources: dict, *, expected_workspace: str | None = None) -> dict:
    root = Path(root).absolute()
    no_symlinks(root)
    root = root.resolve()
    if not root.is_dir():
        raise HarnessError("workspace unavailable", code="WORKSPACE_MISSING")
    if expected_workspace is not None:
        expected = Path(expected_workspace).absolute()
        no_symlinks(expected)
        if expected.resolve() != root:
            raise HarnessError("requested and observed workspaces differ", code="WORKSPACE_MISMATCH",
                               details={"expected":str(expected),"observed":str(root)})
    if not isinstance(resources, dict) or set(resources) - set(ROLES):
        raise HarnessError("resources accept required_inputs, optional_inputs, outputs, protected, working")
    clean = {}
    for role in ROLES:
        paths = resources.get(role, [])
        if not isinstance(paths, list) or len(paths) > 100:
            raise HarnessError("resource roles require at most 100 paths each")
        clean[role] = sorted({normalized(root, path) for path in paths})
        if any(p == "." or p.split("/")[0] in {".git", ".codex", ".agents"} for p in clean[role]):
            raise HarnessError("declare narrow non-control resource paths")
    for output in clean["outputs"] + clean["working"]:
        if any(covers(root, protected, output) or covers(root, output, protected) for protected in clean["protected"]):
            raise HarnessError("output/working path overlaps protected source", code="PROTECTED_SCOPE_CONFLICT")
    entries = []
    from .crew import fingerprint  # local import avoids a module cycle
    for role in ROLES:
        for path in clean[role]:
            p = inside(root, path)
            if role == "required_inputs" and not p.exists():
                raise HarnessError("required input not found: " + path,
                    code="SOURCE_NOT_FOUND", details={"path":path,"role":role,
                    "also_declared_output":path in clean["outputs"],
                    "repair":"Locate the original input or correct its role; do not invent its contents."})
            if p.exists() and not (p.is_file() or p.is_dir()):
                raise HarnessError("source is not a regular file/directory: " + path, code="SOURCE_NOT_REGULAR")
            try:
                stamp = fingerprint(root, [path])
            except PermissionError as exc:
                raise HarnessError("source permission denied: " + path, code="SOURCE_PERMISSION_DENIED") from exc
            entries.append({"id":"source-"+json_hash([role,path])[:16], "role":role,
                            "path":path,"exists":p.exists(),"fingerprint":stamp["sha256"],
                            "bytes":p.stat().st_size if p.is_file() else None})
    result = {"schema":1,"workspace":str(root),"roles":clean,"entries":entries,
              "outputs_must_exist_at_start":False,"source_content_read_by_model":False}
    result["registry_hash"] = json_hash(result)
    return result


def registered_read(store, key: str, source_id: str) -> str:
    meta = store.get(key, "meta", {})
    owner = key
    if meta.get("role") == "worker":
        from .team import Team
        row = Team(store).lookup(meta.get("team_ticket"))
        if not row:
            raise HarnessError("join the assigned ticket before reading a registered source")
        owner = row["owner"]
    registry = store.get(owner, "resource_registry")
    if not isinstance(registry, dict):
        raise HarnessError("no prepared resource registry")
    expected = dict(registry); digest = expected.pop("registry_hash", None)
    if json_hash(expected) != digest:
        raise HarnessError("resource registry changed")
    entry = next((e for e in registry["entries"] if e["id"] == source_id), None)
    if entry is None:
        raise HarnessError("unknown resource ID")
    root = Path(meta.get("assigned_workspace", meta["workspace"]))
    if meta.get("role") == "worker" and not any(covers(root, scope, entry["path"]) for scope in meta.get("assigned_paths", [])):
        raise HarnessError("registered source is outside this worker's assignment")
    return entry["path"]
