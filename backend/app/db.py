"""SQLite storage (zero external services). One connection per thread, WAL mode, simple migrations."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS: list[str] = [
    # 1
    """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id        TEXT PRIMARY KEY,
        status        TEXT NOT NULL,              -- queued | running | done | failed
        stage         TEXT NOT NULL DEFAULT 'queued',
        progress      REAL NOT NULL DEFAULT 0,
        priority      INTEGER NOT NULL DEFAULT 1, -- 0 jury, 1 ui, 2 replay
        source        TEXT NOT NULL DEFAULT 'ui',
        filename      TEXT,
        sha256        TEXT,
        size_bytes    INTEGER,
        duration_sec  REAL,
        upload_path   TEXT,
        result_path   TEXT,
        verdict       TEXT,
        n_violations  INTEGER,
        analyzer      TEXT,
        attempts      INTEGER NOT NULL DEFAULT 0,
        partial       INTEGER NOT NULL DEFAULT 0,
        dedup_of      TEXT,
        error         TEXT,
        warning       TEXT,
        request_started_at REAL,
        created_at    REAL NOT NULL,
        started_at    REAL,
        finished_at   REAL,
        deadline_at   REAL,
        updated_at    REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);
    CREATE INDEX IF NOT EXISTS ix_jobs_sha ON jobs(sha256);
    CREATE INDEX IF NOT EXISTS ix_jobs_created ON jobs(created_at);

    CREATE TABLE IF NOT EXISTS api_keys (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        key_hash     TEXT NOT NULL UNIQUE,
        prefix       TEXT NOT NULL,
        role         TEXT NOT NULL,                -- jury | ui | admin
        name         TEXT,
        disabled     INTEGER NOT NULL DEFAULT 0,
        created_at   REAL NOT NULL,
        last_used_at REAL
    );

    CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id      TEXT,
        camera_id   TEXT,
        type_code   TEXT,
        type_name   TEXT,
        t_sec       REAL,
        confidence  REAL,
        source      TEXT,
        payload     TEXT,
        created_at  REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_events_created ON events(created_at);

    CREATE TABLE IF NOT EXISTS alerts (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id         INTEGER,
        job_id           TEXT,
        camera_id        TEXT,
        type_code        TEXT,
        type_name        TEXT,
        severity         TEXT NOT NULL,
        state            TEXT NOT NULL,             -- open | acknowledged | resolved | false_positive
        message          TEXT,
        dedup_key        TEXT,
        count            INTEGER NOT NULL DEFAULT 1,
        escalation_level INTEGER NOT NULL DEFAULT 0,
        escalate_at      REAL,
        acked_by         TEXT,
        acked_at         REAL,
        payload          TEXT,
        created_at       REAL NOT NULL,
        updated_at       REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_alerts_state ON alerts(state);
    CREATE INDEX IF NOT EXISTS ix_alerts_dedup ON alerts(dedup_key);

    CREATE TABLE IF NOT EXISTS alert_deliveries (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id    INTEGER NOT NULL,
        channel     TEXT NOT NULL,
        target      TEXT,
        status      TEXT NOT NULL,                  -- pending | sent | failed | skipped
        attempts    INTEGER NOT NULL DEFAULT 0,
        last_error  TEXT,
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS feedback (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id          TEXT,
        violation_index INTEGER,
        decision        TEXT,
        comment         TEXT,
        type_code       TEXT,
        timecode_sec    REAL,
        filename        TEXT,
        created_at      REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS cameras (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        url         TEXT NOT NULL,
        enabled     INTEGER NOT NULL DEFAULT 1,
        fps         REAL NOT NULL DEFAULT 4,
        loop        INTEGER NOT NULL DEFAULT 1,
        meta        TEXT,
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        ts       REAL NOT NULL,
        actor    TEXT,
        action   TEXT NOT NULL,
        entity   TEXT,
        detail   TEXT
    );
    """,
]


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._all: dict[sqlite3.Connection, threading.Thread] = {}
        self._all_lock = threading.Lock()
        self.migrate()

    # ------------------------------------------------------------------ connections
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
            with self._all_lock:
                self._all[c] = threading.current_thread()
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction (SQLite allows one writer at a time anyway)."""
        with self._write_lock:
            c = self.conn()
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def close(self) -> None:
        """Service shutdown: close connections owned by finished threads and by this thread.

        A sqlite3 connection must never be closed from another thread while it may be in use (segfault),
        so connections of threads that are still alive are left to the garbage collector.
        """
        me = threading.current_thread()
        with self._all_lock:
            items = list(self._all.items())
            self._all = {c: t for c, t in items if t is not me and t.is_alive()}
        for c, t in items:
            if t is me or not t.is_alive():
                try:
                    c.close()
                except Exception:
                    pass
        self._local = threading.local()

    # ------------------------------------------------------------------ migrations
    def migrate(self) -> None:
        c = self.conn()
        c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = c.execute("SELECT version FROM schema_version").fetchone()
        current = row["version"] if row else 0
        for i, sql in enumerate(MIGRATIONS[current:], start=current + 1):
            with self.tx() as t:
                for stmt in _split(sql):
                    t.execute(stmt)
                if row is None and i == 1:
                    t.execute("INSERT INTO schema_version(version) VALUES (?)", (i,))
                    row = {"version": i}
                else:
                    t.execute("UPDATE schema_version SET version=?", (i,))

    # ------------------------------------------------------------------ helpers
    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        r = self.conn().execute(sql, params).fetchone()
        return dict(r) if r else None

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        return [dict(r) for r in self.conn().execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self.tx() as t:
            cur = t.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    def insert(self, table: str, row: dict[str, Any]) -> int:
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        with self.tx() as t:
            cur = t.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", tuple(_enc(v) for v in row.values()))
            return int(cur.lastrowid)

    def update(self, table: str, key: str, key_value: Any, fields: dict[str, Any]) -> int:
        if not fields:
            return 0
        sets = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as t:
            cur = t.execute(f"UPDATE {table} SET {sets} WHERE {key}=?",
                            tuple(_enc(v) for v in fields.values()) + (key_value,))
            return cur.rowcount

    def audit(self, action: str, actor: str | None = None, entity: str | None = None, detail: Any = None) -> None:
        self.insert("audit_log", {"ts": time.time(), "actor": actor, "action": action, "entity": entity,
                                  "detail": _enc(detail) if detail is not None else None})


def _enc(v: Any) -> Any:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, Path):
        return str(v)
    return v


def _split(script: str) -> list[str]:
    out, buf = [], []
    for line in script.splitlines():
        stripped = line.split("--", 1)[0]
        buf.append(stripped)
        if stripped.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def loads(v: str | None, default: Any = None) -> Any:
    if not v:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default
