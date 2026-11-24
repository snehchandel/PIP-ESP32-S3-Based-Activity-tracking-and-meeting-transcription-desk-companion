"""SQLite (WAL + foreign keys) connection, idempotent versioned migrations, redacted event log."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS = Path(__file__).parent / "migrations"
EVENT_LOG_MAX = 2000
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]+)")
_REDACT_KEYS = {"transcript", "api_key", "authorization", "source_text", "raw_json"}


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def redact(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if k.lower() in _REDACT_KEYS:
            out[k] = "[redacted]"
        elif isinstance(v, str):
            out[k] = _SECRET_RE.sub("[redacted]", v)
        else:
            out[k] = v
    return out


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.migrate()

    def migrate(self) -> list[int]:
        applied: list[int] = []
        with self.lock:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r[0] for r in self.conn.execute("SELECT version FROM schema_migrations")}
            for f in sorted(MIGRATIONS.glob("*.sql")):
                version = int(f.name.split("_", 1)[0])
                if version in done:
                    continue
                with self.tx() as c:
                    c.executescript_safe(f.read_text(encoding="utf-8"))
                    c.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)", (version, utcnow()))
                applied.append(version)
        return applied

    @contextmanager
    def tx(self) -> Iterator[Cursor]:
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield Cursor(self.conn)
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.conn.execute(sql, args))

    def one(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def log(self, level: str, category: str, message: str, meta: dict[str, Any] | None = None) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO event_log(ts_utc, level, category, message, meta_json) VALUES (?,?,?,?,?)",
                      (utcnow(), level, category, _SECRET_RE.sub("[redacted]", message),
                       json.dumps(redact(meta)) if meta else None))
            c.execute("DELETE FROM event_log WHERE id <= (SELECT MAX(id) FROM event_log) - ?", (EVENT_LOG_MAX,))

    def close(self) -> None:
        self.conn.close()


class Cursor:
    """Thin wrapper so statements inside a transaction cannot accidentally COMMIT early."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, args: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, args)

    def executescript_safe(self, script: str) -> None:
        # executescript() would COMMIT the open transaction; run statements one by one instead.
        for stmt in [s.strip() for s in script.split(";")]:
            body = "\n".join(line for line in stmt.splitlines() if not line.strip().startswith("--")).strip()
            if body:
                self.conn.execute(body)
