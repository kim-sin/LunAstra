"""Small transactional metadata store, outside project sources; no raw prompt logging."""
from __future__ import annotations
from contextlib import closing, contextmanager
import json
import sqlite3
import time
import threading
from pathlib import Path
from .util import HarnessError, strict_json, canonical, no_symlinks

class Store:
    def __init__(self, directory: Path):
        self.directory = Path(directory).absolute()
        no_symlinks(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'runtime.sqlite3'
        no_symlinks(self.path)
        self._local = threading.local()
        self._shared = None
        self._schemas = set()
        self.ensure_schema('store', '''
CREATE TABLE IF NOT EXISTS kv (scope TEXT, name TEXT, value TEXT NOT NULL, PRIMARY KEY(scope,name));
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, unique_id TEXT, kind TEXT, at REAL, data TEXT, UNIQUE(scope,unique_id));
CREATE INDEX IF NOT EXISTS events_scope_seq ON events(scope,seq);
CREATE TABLE IF NOT EXISTS leases (workspace TEXT, path TEXT, owner TEXT, token TEXT, at REAL, PRIMARY KEY(workspace,path,owner,token));
''')

    @property
    def _shared(self):
        return getattr(getattr(self, '_local', None), 'db', None)

    @_shared.setter
    def _shared(self, value):
        if not hasattr(self, '_local'):self._local=threading.local()
        self._local.db = value

    @property
    def _schemas(self):
        if not hasattr(self._local, 'schemas'):
            self._local.schemas = set()
        return self._local.schemas

    @_schemas.setter
    def _schemas(self, value):
        self._local.schemas = value

    @contextmanager
    def connection(self):
        """Reuse a connection only within this synchronous operation, never a daemon.

        No value cache: each SELECT still sees the current committed state. Every
        transaction ends at its original boundary; nested writes use savepoints.
        Separate Store instances/threads never share this connection.
        """
        if self._shared is not None:
            yield self
            return
        with closing(sqlite3.connect(self.path, timeout=3, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA busy_timeout=3000')
            self._shared = db
            try:
                yield self
            finally:
                self._shared = None
                self._schemas.clear()
                if db.in_transaction:
                    db.rollback()

    def ensure_schema(self, name, script):
        # Static internal DDL only. executescript implicitly COMMITs an existing
        # transaction; statement execution preserves callers' atomicity.
        if name in self._schemas:
            return
        already_in_transaction = bool(self._shared is not None and self._shared.in_transaction)
        with self.db(True) as db:
            for statement in script.split(';'):
                if statement.strip():
                    db.execute(statement)
        if self._shared is not None and not already_in_transaction:
            self._schemas.add(name)

    @contextmanager
    def db(self, write: bool = False):
        if self._shared is None:
            with self.connection():
                with self.db(write) as db:
                    yield db
            return
        db = self._shared
        nested = write and db.in_transaction
        savepoint = 'sp_' + __import__('uuid').uuid4().hex if nested else None
        entered = False
        try:
            if write:
                db.execute('SAVEPOINT ' + savepoint if nested else 'BEGIN IMMEDIATE')
                entered = True
            yield db
            if write:
                if nested:
                    db.execute('RELEASE ' + savepoint)
                else:
                    db.commit()
        except BaseException:
            if write and entered and db.in_transaction:
                if nested:
                    db.execute('ROLLBACK TO ' + savepoint)
                    db.execute('RELEASE ' + savepoint)
                else:
                    db.rollback()
            raise

    def get(self, scope, name, default=None):
        with self.db() as db:
            row = db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(scope,name)).fetchone()
        return strict_json(row[0]) if row else default

    def put(self, scope, name, value):
        with self.db(True) as db:
            db.execute('INSERT INTO kv VALUES(?,?,?) ON CONFLICT(scope,name) DO UPDATE SET value=excluded.value',
                       (scope,name,canonical(value)))

    def once(self, scope: str, name: str, generation: str) -> bool:
        with self.db(True) as db:
            row=db.execute('SELECT value FROM kv WHERE scope=? AND name=?',(scope,name)).fetchone()
            if row and strict_json(row[0]) == generation: return False
            db.execute('INSERT INTO kv VALUES(?,?,?) ON CONFLICT(scope,name) DO UPDATE SET value=excluded.value',
                       (scope,name,canonical(generation)))
        return True

    def event(self, scope, unique_id, kind, data):
        with self.db(True) as db:
            cursor=db.execute('INSERT OR IGNORE INTO events(scope,unique_id,kind,at,data) VALUES(?,?,?,?,?)',
                              (scope,unique_id,kind,time.time(),canonical(data)))
            # Bounded operational trace. Aggregate counters and evidence are separate.
            db.execute('DELETE FROM events WHERE scope=? AND seq < COALESCE((SELECT seq FROM events WHERE scope=? ORDER BY seq DESC LIMIT 1 OFFSET 999),-1)',(scope,scope))
            return bool(cursor.rowcount)

    def recent(self, scope, limit=12):
        if type(limit) is not int or not 1 <= limit <= 1000: raise HarnessError('invalid event limit')
        with self.db() as db:
            rows=db.execute('SELECT kind,at,data FROM events WHERE scope=? ORDER BY seq DESC LIMIT ?',(scope,limit)).fetchall()
        return [dict(kind=r['kind'],at=r['at'],**strict_json(r['data'])) for r in reversed(rows)]


def evidence_directory(state, key, meta=None):
    """Each reused worker assignment has an immutable, separate evidence context."""
    import re
    if meta is None:
        meta = Store(state).get(key, 'meta', {})
    value = meta.get('evidence_key', key)
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise HarnessError('invalid evidence context identity')
    return Path(state) / 'sessions' / value
