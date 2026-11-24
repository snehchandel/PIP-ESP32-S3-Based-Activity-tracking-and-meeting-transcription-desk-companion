"""SQLite: WAL, FK cascade, idempotent migrations, transactional rollback, redaction, pruning."""
from __future__ import annotations

import sqlite3

import pytest

from service.storage.db import EVENT_LOG_MAX, Database
from service.storage.repo_tasks import TaskRepo

STEPS = [{"title": "Open doc", "duration_min": 2, "is_starter": True}, {"title": "Write", "duration_min": 10},
         {"title": "Edit", "duration_min": 10}]


def test_wal_and_migrations_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = str(tmp_path / "p.db")
    db = Database(path)
    assert db.one("PRAGMA journal_mode")[0] == "wal"
    assert db.migrate() == []  # second run applies nothing
    db.close()
    db2 = Database(path)
    assert [r[0] for r in db2.query("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
    db2.close()


def test_fk_cascade_deletes_steps() -> None:
    db = Database(":memory:")
    repo = TaskRepo(db)
    tid = repo.create_task("T", STEPS, "2026-11-23", "America/Toronto")
    assert len(repo.steps(tid)) == 3
    repo.delete_task(tid)
    assert db.query("SELECT * FROM steps") == []


def test_check_constraints_reject_bad_data() -> None:
    db = Database(":memory:")
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as c:
            c.execute("INSERT INTO tasks(id,title,status,target_date,timezone,created_at,updated_at) "
                      "VALUES ('x','t','WEIRD','d','tz','n','n')")


def test_transaction_rolls_back_on_error() -> None:
    db = Database(":memory:")
    repo = TaskRepo(db)
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            c.execute("INSERT INTO parked_tasks(id,title,status,created_at) VALUES ('p1','x','PARKED','n')")
            raise RuntimeError("boom")
    assert repo.parked() == []


def test_split_preserves_order_and_total() -> None:
    db = Database(":memory:")
    repo = TaskRepo(db)
    tid = repo.create_task("T", STEPS, "2026-11-23", "America/Toronto")
    s = repo.steps(tid)
    repo.split_step(s[1]["id"], 300, 300)
    titles = [x["title"] for x in repo.steps(tid)]
    assert titles == ["Open doc", "Write (first half)", "Write (second half)", "Edit"]
    with pytest.raises(ValueError):
        repo.reorder_steps(tid, [s[0]["id"]])


def test_event_log_redacts_and_prunes() -> None:
    db = Database(":memory:")
    db.log("INFO", "voice", "key sk-abcdefghijklmnop used", {"transcript": "my secret plans", "n": 1})
    row = db.one("SELECT message, meta_json FROM event_log")
    assert "sk-abc" not in row["message"] and "secret plans" not in row["meta_json"]
    for i in range(EVENT_LOG_MAX + 25):
        db.log("INFO", "t", f"m{i}")
    assert db.one("SELECT COUNT(*) FROM event_log")[0] <= EVENT_LOG_MAX + 1


def test_device_event_ingest_is_idempotent() -> None:
    from service.storage.repo_alarms import DeviceRepo
    repo = DeviceRepo(Database(":memory:"))
    assert repo.record_device_event(7, 1, "STEP_COMPLETE", "s", 0, 0) is True
    assert repo.record_device_event(7, 1, "STEP_COMPLETE", "s", 0, 0) is False
    assert repo.record_device_event(8, 1, "STEP_COMPLETE", "s", 0, 0) is True  # new boot, same seq
