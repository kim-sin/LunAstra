"""Small transactional metadata store, outside project sources; no raw prompt logging."""
from __future__ import annotations
from contextlib import closing, contextmanager
import json
import sqlite3
import time
from pathlib import Path
from .util import HarnessError, strict_json, canonical, no_symlinks

class Store:
    def __init__(self, directory: Path):
        self.directory = Path(directory).absolute()
        no_symlinks(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'runtime.sqlite3'
        no_symlinks(self.path)
        with self.db() as db:
            db.executescript('''
CREATE TABLE IF NOT EXISTS kv (scope TEXT, name TEXT, value TEXT NOT NULL, PRIMARY KEY(scope,name));
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, unique_id TEXT, kind TEXT, at REAL, data TEXT, UNIQUE(scope,unique_id));
CREATE TABLE IF NOT EXISTS leases (workspace TEXT, path TEXT, owner TEXT, token TEXT, at REAL, PRIMARY KEY(workspace,path,owner,token));
''')

    @contextmanager
    def db(self, write: bool = False):
        with closing(sqlite3.connect(self.path, timeout=3, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA busy_timeout=3000')
            try:
                if write: db.execute('BEGIN IMMEDIATE')
                yield db
                if write: db.commit()
            except BaseException:
                if write: db.rollback()
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
