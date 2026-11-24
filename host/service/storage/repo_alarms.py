"""Alarms CRUD (one-time + recurring) and device/session state persistence."""
from __future__ import annotations

from typing import Any

from .db import Database, new_id, utcnow

ALARM_FIELDS = {"task_id", "title", "schedule_kind", "fire_utc", "rrule_days", "local_hhmm", "timezone",
                "audio_mode", "audio_path", "tts_script", "fallback_chime_id", "snooze_min", "enabled",
                "last_fired_utc", "ack_state"}


class AlarmRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, **f: Any) -> str:
        aid = new_id("alarm")
        data = {k: v for k, v in f.items() if k in ALARM_FIELDS}
        data.setdefault("schedule_kind", "ONCE")
        data.setdefault("audio_mode", "CHIME")
        cols = ", ".join(["id", *data.keys()])
        marks = ", ".join("?" * (len(data) + 1))
        with self.db.tx() as c:
            c.execute(f"INSERT INTO alarms({cols}) VALUES ({marks})", (aid, *data.values()))
        return aid

    def get(self, aid: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM alarms WHERE id=?", (aid,))
        return dict(r) if r else None

    def list(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM alarms ORDER BY local_hhmm")]

    def update(self, aid: str, **f: Any) -> bool:
        sets = {k: v for k, v in f.items() if k in ALARM_FIELDS}
        if not sets:
            return self.get(aid) is not None
        with self.db.tx() as c:
            return c.execute(f"UPDATE alarms SET {', '.join(f'{k}=?' for k in sets)}, revision=revision+1 WHERE id=?",
                             (*sets.values(), aid)).rowcount == 1

    def delete(self, aid: str) -> bool:
        with self.db.tx() as c:
            return c.execute("DELETE FROM alarms WHERE id=?", (aid,)).rowcount == 1


class DeviceRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def state(self) -> dict[str, Any]:
        r = self.db.one("SELECT * FROM device_state WHERE singleton_id=1")
        return dict(r) if r else {}

    def update(self, **f: Any) -> None:
        if not f:
            return
        with self.db.tx() as c:
            c.execute(f"UPDATE device_state SET {', '.join(f'{k}=?' for k in f)} WHERE singleton_id=1", tuple(f.values()))

    def bump_revision(self) -> int:
        with self.db.tx() as c:
            c.execute("UPDATE device_state SET revision=revision+1, last_sync_utc=? WHERE singleton_id=1", (utcnow(),))
            r = c.execute("SELECT revision FROM device_state WHERE singleton_id=1").fetchone()
            return int(r[0])

    def record_device_event(self, boot_id: int, seq: int, kind: str, ref_id: str, remaining_ms: int,
                            ts_epoch: int) -> bool:
        """Idempotent ingest keyed by (boot_id, event_seq). Returns False if already applied."""
        with self.db.tx() as c:
            cur = c.execute("INSERT OR IGNORE INTO device_events(boot_id,event_seq,kind,ref_id,remaining_ms,ts_epoch,"
                            "applied_at) VALUES (?,?,?,?,?,?,?)",
                            (boot_id, seq, kind, ref_id, remaining_ms, ts_epoch, utcnow()))
            return cur.rowcount == 1

    def add_voice_session(self, key: str, status: str, transcript: str, planner_mode: str, raw_json: str,
                          needs_confirmation: bool) -> str:
        vid = new_id("voice")
        with self.db.tx() as c:
            c.execute("INSERT OR IGNORE INTO voice_sessions(id,idempotency_key,status,transcript,planner_mode,raw_json,"
                      "needs_confirmation,created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (vid, key, status, transcript, planner_mode, raw_json, int(needs_confirmation), utcnow()))
        return vid

    def voice_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM voice_sessions ORDER BY created_at DESC LIMIT ?",
                                               (limit,))]

    def set_voice_status(self, vid: str, status: str, raw_json: str | None = None) -> None:
        with self.db.tx() as c:
            if raw_json is None:
                c.execute("UPDATE voice_sessions SET status=? WHERE id=?", (status, vid))
            else:
                c.execute("UPDATE voice_sessions SET status=?, raw_json=? WHERE id=?", (status, raw_json, vid))
