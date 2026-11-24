"""Tasks, micro-steps, parked tangents and reminders (transactional CRUD)."""
from __future__ import annotations

from typing import Any

from .db import Database, new_id, utcnow


def _row(r: Any) -> dict[str, Any]:
    return dict(r) if r is not None else {}


class TaskRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- tasks -------------------------------------------------------------------------
    def create_task(self, title: str, steps: list[dict[str, Any]], target_date: str, tz: str,
                    status: str = "SCHEDULED", if_then_cue: str | None = None, priority: int = 0,
                    start_hhmm: str | None = None, short_title: str | None = None) -> str:
        tid = new_id("task")
        now = utcnow()
        with self.db.tx() as c:
            c.execute("INSERT INTO tasks(id,title,status,target_date,timezone,if_then_cue,priority,created_at,updated_at,short_title,"
                      "start_hhmm) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, title, status, target_date, tz, if_then_cue, priority, now, now, short_title or None,
                       start_hhmm or None))
            for i, s in enumerate(steps):
                dur = int(s["duration_min"])
                c.execute("INSERT INTO steps(id,task_id,position,title,duration_min,is_starter,remaining_sec,status)"
                          " VALUES (?,?,?,?,?,?,?,?)", (new_id("step"), tid, i, s["title"], dur,
                                                         int(bool(s.get("is_starter"))), dur * 60, "PENDING"))
        return tid

    def get_task(self, tid: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM tasks WHERE id=?", (tid,))
        if r is None:
            return None
        t = _row(r)
        t["steps"] = self.steps(tid)
        return t

    def list_tasks(self, date_from: str | None = None, date_to: str | None = None,
                   include_done: bool = True) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM tasks WHERE status != 'ARCHIVED'", []
        if not include_done:
            sql += " AND status != 'COMPLETED'"
        if date_from:
            sql += " AND target_date >= ?"
            args.append(date_from)
        if date_to:
            sql += " AND target_date <= ?"
            args.append(date_to)
        sql += " ORDER BY target_date, priority DESC, created_at"
        out = []
        for r in self.db.query(sql, tuple(args)):
            t = _row(r)
            t["steps"] = self.steps(t["id"])
            out.append(t)
        return out

    def update_task(self, tid: str, **fields: Any) -> bool:
        allowed = {"title", "status", "target_date", "if_then_cue", "priority", "start_hhmm"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if sets.get("start_hhmm") == "":
            sets["start_hhmm"] = None  # "" clears the time (task becomes "anytime")
        if not sets:
            return self.db.one("SELECT 1 FROM tasks WHERE id=?", (tid,)) is not None
        cols = ", ".join(f"{k}=?" for k in sets)
        with self.db.tx() as c:
            cur = c.execute(f"UPDATE tasks SET {cols}, revision=revision+1, updated_at=? WHERE id=?",
                            (*sets.values(), utcnow(), tid))
            return cur.rowcount == 1

    def delete_task(self, tid: str) -> bool:
        with self.db.tx() as c:
            return c.execute("DELETE FROM tasks WHERE id=?", (tid,)).rowcount == 1

    def set_active(self, tid: str) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE tasks SET status='SCHEDULED', updated_at=? WHERE status='ACTIVE' AND id != ?",
                      (utcnow(), tid))
            c.execute("UPDATE tasks SET status='ACTIVE', updated_at=? WHERE id=?", (utcnow(), tid))

    # ---- steps ---------------------------------------------------------------------------
    def steps(self, tid: str) -> list[dict[str, Any]]:
        return [_row(r) for r in self.db.query("SELECT * FROM steps WHERE task_id=? ORDER BY position", (tid,))]

    def get_step(self, sid: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM steps WHERE id=?", (sid,))
        return _row(r) if r else None

    def set_step_status(self, sid: str, status: str, remaining_sec: int | None = None) -> None:
        with self.db.tx() as c:
            if remaining_sec is None:
                c.execute("UPDATE steps SET status=?, completed_at=? WHERE id=?",
                          (status, utcnow() if status == "COMPLETED" else None, sid))
            else:
                c.execute("UPDATE steps SET status=?, remaining_sec=?, completed_at=? WHERE id=?",
                          (status, remaining_sec, utcnow() if status == "COMPLETED" else None, sid))

    def set_step_remaining(self, sid: str, remaining_sec: int) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE steps SET remaining_sec=? WHERE id=?", (max(0, remaining_sec), sid))

    def split_step(self, sid: str, current_sec: int, next_sec: int) -> str:
        """Rescue: shrink current step, insert the remainder right after it. Nothing is deleted."""
        s = self.get_step(sid)
        if s is None:
            raise KeyError(sid)
        base = s["title"].removesuffix(" (first half)")
        new_sid = new_id("step")
        with self.db.tx() as c:
            c.execute("UPDATE steps SET position=position+1 WHERE task_id=? AND position>?", (s["task_id"], s["position"]))
            c.execute("UPDATE steps SET title=?, remaining_sec=?, duration_min=? WHERE id=?",
                      (f"{base} (first half)", current_sec, max(1, min(60, -(-current_sec // 60))), sid))
            c.execute("INSERT INTO steps(id,task_id,position,title,duration_min,is_starter,remaining_sec,status)"
                      " VALUES (?,?,?,?,?,0,?,'PENDING')",
                      (new_sid, s["task_id"], s["position"] + 1, f"{base} (second half)",
                       max(1, min(60, -(-next_sec // 60))), next_sec))
        return new_sid

    def reorder_steps(self, tid: str, ordered_ids: list[str]) -> None:
        current = {s["id"] for s in self.steps(tid)}
        if set(ordered_ids) != current:
            raise ValueError("reorder must contain exactly the task's steps")
        with self.db.tx() as c:
            for i, sid in enumerate(ordered_ids):
                c.execute("UPDATE steps SET position=? WHERE id=?", (i, sid))

    # ---- parked tangents ------------------------------------------------------------------
    def park(self, title: str, source_text: str | None, target_date: str | None = None) -> str:
        pid = new_id("park")
        with self.db.tx() as c:
            c.execute("INSERT INTO parked_tasks(id,title,source_text,target_date,status,created_at)"
                      " VALUES (?,?,?,?,'PARKED',?)", (pid, title, source_text, target_date, utcnow()))
        return pid

    def parked(self) -> list[dict[str, Any]]:
        return [_row(r) for r in self.db.query(
            "SELECT * FROM parked_tasks WHERE status='PARKED' ORDER BY created_at")]

    def set_parked_status(self, pid: str, status: str) -> bool:
        with self.db.tx() as c:
            return c.execute("UPDATE parked_tasks SET status=? WHERE id=?", (status, pid)).rowcount == 1

    def get_parked(self, pid: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM parked_tasks WHERE id=?", (pid,))
        return _row(r) if r else None

    # ---- reminders --------------------------------------------------------------------------
    def add_reminder(self, title: str, due_utc: str, tz: str, cue: str | None = None) -> str:
        rid = new_id("rem")
        with self.db.tx() as c:
            c.execute("INSERT INTO reminders(id,title,due_utc,timezone,if_then_cue,created_at) VALUES (?,?,?,?,?,?)",
                      (rid, title, due_utc, tz, cue, utcnow()))
        return rid

    def reminders(self, include_done: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM reminders" + ("" if include_done else " WHERE done=0") + " ORDER BY due_utc"
        return [_row(r) for r in self.db.query(sql)]

    def update_reminder(self, rid: str, **fields: Any) -> bool:
        allowed = {"title", "due_utc", "done", "if_then_cue"}
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not sets:
            return False
        with self.db.tx() as c:
            return c.execute(f"UPDATE reminders SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                             (*sets.values(), rid)).rowcount == 1

    def delete_reminder(self, rid: str) -> bool:
        with self.db.tx() as c:
            return c.execute("DELETE FROM reminders WHERE id=?", (rid,)).rowcount == 1
