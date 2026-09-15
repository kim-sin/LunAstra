"""Worker-local check evidence. Selected-check receipts, never semantic proof.

No networking, shell interpolation, automatic retries, process termination or
repository mutation. Check commands are explicitly supplied by the worker.
"""
from __future__ import annotations
import json
import os
import sqlite3
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator
from .util import HarnessError, strict_json, canonical, file_hash, inside, json_hash, no_symlinks, snapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checks (id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, check_id TEXT NOT NULL, task_hash TEXT NOT NULL,
 spec_hash TEXT NOT NULL, status TEXT NOT NULL, started REAL NOT NULL, ended REAL,
 before_json TEXT, after_json TEXT, exit_code INTEGER,
 stdout_path TEXT, stderr_path TEXT, stdout_hash TEXT, stderr_hash TEXT, error TEXT);
"""

class Evidence:
    def __init__(self, directory: Path, workspace: Path | None = None):
        self.directory = Path(directory).absolute()
        no_symlinks(self.directory)
        if workspace is not None:
            no_symlinks(Path(workspace).absolute())
            root = Path(workspace).resolve()
            if not root.is_dir():
                raise HarnessError("workspace does not exist")
            if self.directory.resolve().is_relative_to(root):
                raise HarnessError("evidence must live outside the source workspace")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "evidence.sqlite3"
        no_symlinks(self.path)
        with self._db() as db:
            db.executescript(SCHEMA)
            previous = self._get(db, "workspace")
            if workspace is not None:
                root = Path(workspace).resolve()
                if not root.is_dir():
                    raise HarnessError("workspace does not exist")
                if previous and previous != str(root):
                    raise HarnessError("worker state already belongs to a different workspace")
                if self.directory.resolve().is_relative_to(root):
                    raise HarnessError("evidence must live outside the source workspace")
                self._set(db, "workspace", str(root))
                previous = str(root)
            if not previous:
                raise HarnessError("workspace is required for new evidence state")
            self.workspace = Path(previous)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        # Protect setup as well as the yielded body: a corrupt database can
        # raise during PRAGMA, before a generator context manager has yielded.
        with closing(sqlite3.connect(self.path, timeout=30, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("PRAGMA journal_mode=WAL")
            yield db

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _get(db, key, default=None):
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return strict_json(row[0]) if row else default

    @staticmethod
    def _set(db, key, value):
        db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, canonical(value)))

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise HarnessError(f"{field} must be a nonempty string")
        return value

    def begin(self, task: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise HarnessError("task must be an object")
        task_id = self._text(task.get("task_id"), "task_id")
        design = self._text(task.get("design"), "design")
        requirements = task.get("requirements")
        if not isinstance(requirements, list) or not requirements:
            raise HarnessError("requirements must explicitly describe the assigned outcome")
        if any(not isinstance(r, str) or not r.strip() for r in requirements) or len(set(requirements)) != len(requirements):
            raise HarnessError("requirements must be distinct nonempty strings")
        specs = task.get("checks", [])
        if not isinstance(specs, list):
            raise HarnessError("checks must be a list")
        clean: list[dict[str, Any]] = []
        names: set[str] = set()
        for original in specs:
            if not isinstance(original, dict):
                raise HarnessError("check must be an object")
            name = self._text(original.get("id"), "check.id")
            if name in names:
                raise HarnessError(f"duplicate check id: {name}")
            names.add(name)
            argv = original.get("argv")
            if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x or "\x00" in x for x in argv):
                raise HarnessError("argv must be a nonempty string array, not shell text")
            deps = original.get("dependencies")
            if not isinstance(deps, list) or not deps or any(not isinstance(d, str) for d in deps):
                raise HarnessError("declare source, test and other relevant dependencies")
            for dep in deps:
                inside(self.workspace, dep)
            absent=original.get('expected_absent',[])
            if not isinstance(absent,list) or any(not isinstance(n,str) for n in absent):raise HarnessError('expected_absent must be relative paths')
            for n in absent:inside(self.workspace,n)
            covers = original.get("covers")
            if not isinstance(covers, list) or not covers or any(type(i) is not int or i < 0 or i >= len(requirements) for i in covers):
                raise HarnessError("covers must refer to requirement indices")
            purpose = self._text(original.get("purpose"), "check.purpose")
            cwd = original.get("cwd", ".")
            working = inside(self.workspace, cwd, allow_root=True)
            if not working.is_dir():
                raise HarnessError("check cwd must exist")
            # Identity is metadata supplied from the assigned environment/data, not inferred.
            identity = original.get("identity", {})
            if not isinstance(identity, dict):
                raise HarnessError("identity must be an object")
            canonical(identity)
            reusable = original.get("reusable", False)
            if type(reusable) is not bool: raise HarnessError("reusable must be boolean")
            environment_keys = original.get("environment_keys", [])
            if not isinstance(environment_keys, list) or any(not isinstance(k, str) or not k for k in environment_keys):
                raise HarnessError("environment_keys must be strings")
            clean.append(dict(id=name, argv=argv, dependencies=sorted(set(deps)),
                              covers=sorted(set(covers)), purpose=purpose, cwd=cwd, identity=identity, reusable=reusable, environment_keys=sorted(set(environment_keys)),expected_absent=sorted(set(absent))))
        allowed = task.get("allowed_paths", [])
        protected = task.get("protected_paths", [])
        for field, paths in (("allowed_paths", allowed), ("protected_paths", protected)):
            if not isinstance(paths, list) or any(not isinstance(x, str) or not x for x in paths):
                raise HarnessError(f"{field} must be a list of strings")
            for path in paths:
                inside(self.workspace, path, allow_root=True)
        normalized = dict(task_id=task_id, design=design, requirements=requirements,
                          allowed_paths=allowed, protected_paths=protected, checks=clean)
        fingerprint = json_hash(normalized)
        with self._transaction() as db:
            if self._get(db, "task_hash") == fingerprint:
                return dict(task_hash=fingerprint, changed=False)
            if db.execute("SELECT 1 FROM attempts WHERE status='RUNNING' LIMIT 1").fetchone():
                raise HarnessError("cannot replace task definition while a check is running; do not terminate it")
            self._set(db, "task", normalized)
            self._set(db, "task_hash", fingerprint)
            self._set(db, "finish", None)
            db.execute("DELETE FROM checks")
            for check in clean:
                db.execute("INSERT INTO checks VALUES(?,?,?)", (check["id"], canonical(check), json_hash(check)))
        return dict(task_hash=fingerprint, changed=True)

    def _context(self, spec: dict[str, Any]) -> dict[str, Any]:
        cwd = inside(self.workspace, spec["cwd"], allow_root=True)
        exe = spec["argv"][0]
        resolved = str((cwd / exe).resolve()) if ("/" in exe or "\\" in exe) and not Path(exe).is_absolute() else shutil.which(exe)
        if not resolved or not Path(resolved).is_file(): raise HarnessError("check executable unavailable")
        for n in spec.get('expected_absent',[]):
            if inside(self.workspace,n).exists():raise HarnessError('required deleted path still exists: '+n)
        environment = {key: os.environ.get(key) for key in spec.get("environment_keys", [])}
        return {"executable_sha256": file_hash(Path(resolved)), "executable_path": resolved,
                "declared_environment_sha256": json_hash(environment),
                "files": snapshot(self.workspace, spec["dependencies"]),
                "executable_mode": __import__("stat").S_IMODE(Path(resolved).stat().st_mode),
                "identity": spec["identity"], "expected_absent": spec.get("expected_absent",[]), "platform": sys.platform,
                "runner_python": sys.version, "workspace": str(self.workspace)}

    def run(self, check_id: str, expected_task_hash: str | None = None) -> dict[str, Any]:
        # Starting a new attempt atomically invalidates an earlier completion claim.
        with self._transaction() as db:
            if expected_task_hash is not None and self._get(db, "task_hash") != expected_task_hash:
                raise HarnessError("task changed during batch; refusing a different assignment")
            record = db.execute("SELECT * FROM checks WHERE id=?", (check_id,)).fetchone()
            if not record:
                raise HarnessError(f"unknown check: {check_id}")
            spec = strict_json(record["spec"])
            definition=self._get(db,'task')
            if not isinstance(spec,dict) or not isinstance(definition,dict) or not isinstance(definition.get('checks'),list) or json_hash(definition)!=self._get(db,'task_hash') or json_hash(spec)!=record['spec_hash'] or spec not in definition['checks']:
                raise HarnessError('corrupt check definition; execution refused')
            if db.execute("SELECT 1 FROM attempts WHERE check_id=? AND status='RUNNING' LIMIT 1",(check_id,)).fetchone():
                raise HarnessError('this check is already running; observe it instead of launching a duplicate')
            task_hash = self._get(db, "task_hash")
            self._set(db, "finish", None)
            cursor = db.execute("INSERT INTO attempts(check_id,task_hash,spec_hash,status,started) VALUES(?,?,?,?,?)",
                                (check_id, task_hash, record["spec_hash"], "RUNNING", time.time()))
            seq = cursor.lastrowid
        logs = self.directory / "logs"
        no_symlinks(logs)
        logs.mkdir(exist_ok=True)
        stdout = logs / f"{seq}-{uuid.uuid4().hex}.stdout"
        stderr = logs / f"{seq}-{uuid.uuid4().hex}.stderr"
        before = after = None
        code = None
        error = None
        status = "ERROR"
        try:
            before = self._context(spec)
            cwd = inside(self.workspace, spec["cwd"], allow_root=True)
            # Fresh Python processes do not overwrite dependency bytecode. No global env changes.
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            with stdout.open("xb") as out, stderr.open("xb") as err:
                process = subprocess.Popen(spec["argv"], cwd=cwd, env=env,
                                           stdin=subprocess.DEVNULL, stdout=out, stderr=err, shell=False)
                # Deliberately no timeout / kill / terminate / cancellation of external jobs.
                code = process.wait()
            after = self._context(spec)
            status = "PASS" if code == 0 and before == after else ("FAIL" if code != 0 else "STALE")
        except (OSError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        # KeyboardInterrupt/SystemExit are not recast as success; an interrupted runner stays RUNNING.
        with self._transaction() as db:
            db.execute("""UPDATE attempts SET status=?,ended=?,before_json=?,after_json=?,exit_code=?,
                        stdout_path=?,stderr_path=?,stdout_hash=?,stderr_hash=?,error=? WHERE seq=?""",
                       (status, time.time(), canonical(before), canonical(after), code,
                        stdout.relative_to(self.directory).as_posix() if stdout.exists() else None,
                        stderr.relative_to(self.directory).as_posix() if stderr.exists() else None,
                        file_hash(stdout) if stdout.exists() else None,
                        file_hash(stderr) if stderr.exists() else None, error, seq))
        return dict(attempt=seq, check=check_id, status=status, exit_code=code,
                    stdout=str(stdout) if stdout.exists() else None,
                    stderr=str(stderr) if stderr.exists() else None, error=error)

    def _check_report(self, db, check, task_hash):
        spec = strict_json(check["spec"])
        task=self._get(db,'task')
        if not isinstance(spec,dict) or json_hash(spec)!=check['spec_hash'] or not isinstance(task,dict) or json_hash(task)!=task_hash or spec not in task.get('checks',[]):
            raise HarnessError('corrupt reusable check definition')
        row = db.execute("SELECT * FROM attempts WHERE check_id=? AND task_hash=? ORDER BY seq DESC LIMIT 1",
                         (check["id"], task_hash)).fetchone()
        state = "NOT_RUN" if row is None else row["status"]
        reason = ""
        if row is not None and state == "PASS":
            try:
                if type(row["exit_code"]) is not int or row["exit_code"] != 0 or row["ended"] is None or row["error"] is not None:
                    raise HarnessError("invalid successful attempt record")
                if row["spec_hash"] != check["spec_hash"]:
                    raise HarnessError("check definition changed")
                current = self._context(spec)
                if strict_json(row["before_json"]) != current or strict_json(row["after_json"]) != current:
                    raise HarnessError("source/input/environment evidence is stale")
                for stream in ("stdout", "stderr"):
                    value = row[stream + "_path"]
                    if not value:
                        raise HarnessError("missing execution log")
                    path = inside(self.directory, value)
                    if file_hash(path) != row[stream + "_hash"]:
                        raise HarnessError("execution log missing or changed")
            except (OSError, ValueError) as exc:
                state, reason = "STALE", str(exc)
        return dict(id=check["id"], status=state, attempt=row["seq"] if row else None, reason=reason),spec

    def _assess(self, db) -> dict[str, Any]:
        task = self._get(db, "task")
        task_hash = self._get(db, "task_hash")
        if task is None:
            return dict(status="UNCONFIGURED", passed=False, checks=[], missing_requirements=[], active=0)
        if not isinstance(task,dict) or not isinstance(task.get('requirements'),list) or not isinstance(task.get('checks'),list) or any(not isinstance(c,dict) or not isinstance(c.get('id'),str) for c in task.get('checks',[])):
            raise HarnessError('corrupt task definition')
        records = db.execute("SELECT * FROM checks ORDER BY id").fetchall()
        active = db.execute("SELECT COUNT(*) FROM attempts WHERE status='RUNNING'").fetchone()[0]
        expected={c['id']:c for c in task.get('checks',[])}
        if json_hash(task)!=task_hash or len(expected)!=len(records):
            return dict(status='CORRUPT_DEFINITION',passed=False,checks=[],missing_requirements=list(range(len(task.get('requirements',[])))),active=active)
        for record in records:
            spec=strict_json(record['spec'])
            if spec!=expected.get(record['id']) or json_hash(spec)!=record['spec_hash']:
                return dict(status='CORRUPT_DEFINITION',passed=False,checks=[],missing_requirements=list(range(len(task.get('requirements',[])))),active=active)
        reports = []
        covered: set[int] = set()
        for check in records:
            report,spec=self._check_report(db,check,task_hash)
            if report['status']=='PASS':covered.update(spec['covers'])
            reports.append(report)
        missing = [i for i in range(len(task["requirements"])) if i not in covered]
        passed = bool(records) and not active and not missing and all(r["status"] == "PASS" for r in reports)
        return dict(status="CHECKS_PASSED" if passed else "NOT_VERIFIED", passed=passed,
                    task_id=task["task_id"], task_hash=task_hash, checks=reports,
                    missing_requirements=missing, active=active,
                    limit="Only declared checks/dependencies are verified; adequacy and design fidelity require review.")

    def status(self) -> dict[str, Any]:
        # Serialize against new check starts while evaluating this point-in-time receipt.
        with self._transaction() as db:
            result = self._assess(db)
            claim = self._get(db, "finish")
            if claim is not None and (not isinstance(claim,dict) or not isinstance(claim.get('kind'),str) or claim.get('kind') not in {'tested','analysis','partial','blocked'} or type(claim.get('valid')) is not bool):
                raise HarnessError('corrupt completion record')
            if claim and (claim.get('task_hash')!=self._get(db,'task_hash') or (claim['kind']=='tested' and not result['passed'])):
                claim = dict(claim, valid=False)
            result["finish"] = claim
            return result

    def run_all(self, reuse: bool = True) -> dict[str, Any]:
        with self._transaction() as db:
            task_hash=self._get(db,'task_hash')
            specs = [strict_json(r[0]) for r in db.execute("SELECT spec FROM checks ORDER BY rowid")]
        if not specs: raise HarnessError("no registered checks")
        results = []
        for spec in specs:
            reusable_report=None
            if reuse and spec.get('reusable') is True:
                # Check this candidate once, not all earlier successes N times.
                with self._transaction() as db:
                    if self._get(db,'task_hash')!=task_hash:raise HarnessError('task changed during batch')
                    check=db.execute('SELECT * FROM checks WHERE id=?',(spec['id'],)).fetchone()
                    active=db.execute("SELECT 1 FROM attempts WHERE status='RUNNING' LIMIT 1").fetchone()
                    if check and not active:
                        report,_=self._check_report(db,check,task_hash)
                        if report['status']=='PASS':reusable_report=report
            if reusable_report:
                results.append(dict(check=spec['id'],status='PASS',reused=True,attempt=reusable_report['attempt']))
                continue
            result = self.run(spec['id'],expected_task_hash=task_hash)
            results.append(result)
            if result['status'] != 'PASS': break
        status=self.status()
        if status.get('task_hash')!=task_hash:raise HarnessError('task changed at batch completion')
        return {'checks':results,'status':status}

    def finish(self, kind: str, summary: str, review: str, limitations: str) -> dict[str, Any]:
        if not isinstance(kind,str) or kind not in {"tested", "analysis", "partial", "blocked"}:
            raise HarnessError("kind must be tested, analysis, partial or blocked")
        for field, value in (("summary", summary), ("review", review), ("limitations", limitations)):
            self._text(value, field)
        with self._transaction() as db:
            result = self._assess(db)
            if kind == "tested" and not result["passed"]:
                raise HarnessError("cannot claim tested completion: " + canonical(result))
            if kind == "analysis" and result.get("active", 0):
                raise HarnessError("running checks require an explicit partial/blocked handback")
            claim = dict(kind=kind, summary=summary, review=review, limitations=limitations,
                         at=time.time(), valid=True, task_hash=self._get(db, "task_hash"),
                         evidence=result)
            self._set(db, "finish", claim)
            return claim
