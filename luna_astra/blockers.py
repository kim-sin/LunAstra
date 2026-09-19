"""Dependency-bound blockers and report freshness; history is never erased.

STALE means a new observation is required. It NEVER means the result passed.
Only a fresh report or a concrete local predicate can resolve a blocker.
"""
from __future__ import annotations
import time
from pathlib import Path
from .util import HarnessError, canonical, strict_json, json_hash

KINDS = frozenset({"RESULT_INVALID", "VERIFICATION_INCOMPLETE", "INTERNAL_RECOVERABLE", "EXTERNAL_WAIT", "USER_REQUIRED"})
SCHEMA = """
CREATE TABLE IF NOT EXISTS crew_report_sources (
 ticket TEXT PRIMARY KEY, report_hash TEXT NOT NULL, workspace TEXT NOT NULL,
 paths TEXT NOT NULL, fingerprint TEXT, requirements_hash TEXT NOT NULL, error TEXT);
CREATE TABLE IF NOT EXISTS blocker_history (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, blocker_id TEXT NOT NULL,
 state TEXT NOT NULL, at REAL NOT NULL, record TEXT NOT NULL);
"""


def install(store):
    store.ensure_schema('blockers', SCHEMA)


def source_record(workspace: Path, paths: list[str], requirements: list[str], body: dict) -> dict:
    from .crew import fingerprint
    # An unavailable snapshot never suppresses the actual report. Its freshness
    # remains UNKNOWN and cannot be used to auto-resolve a missing dependency.
    try:
        stamp = fingerprint(workspace, paths)["sha256"] if paths else json_hash([])
        error = None
    except (OSError, ValueError) as exc:
        stamp, error = None, str(exc)
    return {"report_hash":json_hash(body), "workspace":str(workspace),"paths":sorted(set(paths)),
            "fingerprint":stamp,"requirements_hash":json_hash(requirements),"error":error}


def store_source(db, ticket: str, record: dict):
    db.execute("INSERT OR REPLACE INTO crew_report_sources VALUES(?,?,?,?,?,?,?)",
               (ticket,record["report_hash"],record["workspace"],canonical(record["paths"]),
                record["fingerprint"],record["requirements_hash"],record["error"]))


def freshness(store, ticket: str, report: dict | None, requirements: list[str]) -> dict:
    with store.db() as db:
        row = db.execute("SELECT * FROM crew_report_sources WHERE ticket=?",(ticket,)).fetchone()
    if row is None or not report or row["report_hash"]!=json_hash(report) or row["fingerprint"] is None:
        return {"state":"UNKNOWN","reason":"no matching complete source observation"}
    from .crew import fingerprint
    try:
        current = fingerprint(Path(row["workspace"]),strict_json(row["paths"]))["sha256"] if strict_json(row["paths"]) else json_hash([])
    except (OSError,ValueError) as exc:
        return {"state":"UNKNOWN","reason":str(exc)}
    unchanged = current==row["fingerprint"] and json_hash(requirements)==row["requirements_hash"]
    return {"state":"CURRENT" if unchanged else "STALE", "observed_fingerprint":row["fingerprint"],
            "current_fingerprint":current,"report_hash":row["report_hash"],
            "reason":None if unchanged else "recheck changed dependencies; do not convert stale to clear"}


def record_blocker(db, owner: str, ticket: str, report: dict, source: dict, kind: str):
    if kind not in KINDS:raise HarnessError("invalid blocker classification")
    blocker={"ticket":ticket,"kind":kind,"summary":report["summary"],"report_hash":json_hash(report),
             "dependencies":source["paths"],"fingerprint":source["fingerprint"],
             "result_preserved":True,"authority_promoted":False}
    db.execute("INSERT INTO blocker_history(owner,blocker_id,state,at,record) VALUES(?,?,?,?,?)",
               (owner,ticket,"ACTIVE",time.time(),canonical(blocker)))


def archive_recheck(db, owner: str, ticket: str, report: dict, observation: dict):
    db.execute("INSERT INTO blocker_history(owner,blocker_id,state,at,record) VALUES(?,?,?,?,?)",
               (owner,ticket,"RECHECKING",time.time(),canonical({"old_report":report,"observation":observation})))


def resolve_by_report(db, owner: str, ticket: str, report: dict):
    old = db.execute("SELECT 1 FROM blocker_history WHERE owner=? AND blocker_id=?",(owner,ticket)).fetchone()
    if old and report["verdict"]!="blocked":
        db.execute("INSERT INTO blocker_history(owner,blocker_id,state,at,record) VALUES(?,?,?,?,?)",
                   (owner,ticket,"RESOLVED_BY_NEW_REPORT",time.time(),canonical({"report_hash":json_hash(report),
                    "verdict":report["verdict"],"result_pass_asserted":False})))


def current(store, owner: str, crew_state: dict) -> list[dict]:
    results=[]
    for row in crew_state.get("tasks",[]):
        report=crew_state.get("reports",{}).get(row["ticket"])
        if not report or report.get("verdict")!="blocked":continue
        status=freshness(store,row["ticket"],report,crew_state["requirements"])
        results.append({"slot":row["id"],"ticket":row["ticket"],"kind":report.get("blocker_kind","VERIFICATION_INCOMPLETE"),
                        "state":status["state"],"summary":report["summary"],"recheck":status,
                        "result_preserved":True,"authority_promoted":False})
    return results
