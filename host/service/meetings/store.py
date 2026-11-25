"""Meetings, their transcript segments, speakers and remembered voices (SQLite CRUD)."""
from __future__ import annotations

import json
from typing import Any

from ..storage.db import Database, new_id, utcnow


def speaker_label(n: int) -> str:
    return f"Speaker {n:02d}"


class MeetingRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---- meetings ------------------------------------------------------------------------
    def create(self, title: str, started_at: str, tz: str, audio_path: str, source: str = "DEVICE",
               status: str = "RECORDING") -> str:
        mid = new_id("meet")
        now = utcnow()
        with self.db.tx() as c:
            c.execute("INSERT INTO meetings(id,title,started_at,timezone,status,source,audio_path,created_at,updated_at)"
                      " VALUES (?,?,?,?,?,?,?,?,?)", (mid, title, started_at, tz, status, source, audio_path, now, now))
        return mid

    def update(self, mid: str, **fields: Any) -> bool:
        allowed = {"title", "ended_at", "duration_s", "status", "progress", "error", "notes", "summary_json", "gaps_s",
                   "audio_path"}
        cols = {k: v for k, v in fields.items() if k in allowed}
        if not cols:
            return False
        sets = ",".join(f"{k}=?" for k in cols)
        with self.db.tx() as c:
            return c.execute(f"UPDATE meetings SET {sets},updated_at=? WHERE id=?",  # noqa: S608 - column names are whitelisted
                             (*cols.values(), utcnow(), mid)).rowcount == 1

    def get(self, mid: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM meetings WHERE id=?", (mid,))
        if r is None:
            return None
        m = dict(r)
        m["summary"] = json.loads(m.pop("summary_json") or "null")
        m["speakers"] = self.speakers(mid)
        return m

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT m.*, (SELECT COUNT(*) FROM meeting_speakers s WHERE s.meeting_id=m.id) AS speaker_count, "
            "(SELECT COUNT(*) FROM meeting_segments g WHERE g.meeting_id=m.id) AS segment_count "
            "FROM meetings m ORDER BY started_at DESC")
        out = []
        for r in rows:
            m = dict(r)
            summary = json.loads(m.pop("summary_json") or "null")
            m["has_summary"] = summary is not None
            m["speaker_names"] = [s["name"] for s in self.speakers(m["id"])]
            out.append(m)
        return out

    def with_status(self, *status: str) -> list[dict[str, Any]]:
        marks = ",".join("?" for _ in status)
        return [dict(r) for r in self.db.query(f"SELECT * FROM meetings WHERE status IN ({marks})"  # noqa: S608
                                                " ORDER BY started_at", status)]

    def delete(self, mid: str) -> bool:
        with self.db.tx() as c:
            return c.execute("DELETE FROM meetings WHERE id=?", (mid,)).rowcount == 1

    # ---- transcript -------------------------------------------------------------------------
    def replace_transcript(self, mid: str, segments: list[dict[str, Any]], speakers: list[dict[str, Any]]) -> None:
        """segments: {start_s, end_s, text, speaker_key, embedding?}; speakers: {key, name, profile_id?, auto?}."""
        with self.db.tx() as c:
            c.execute("DELETE FROM meeting_segments WHERE meeting_id=?", (mid,))
            c.execute("DELETE FROM meeting_speakers WHERE meeting_id=?", (mid,))
            for i, s in enumerate(segments):
                emb = s.get("embedding")
                c.execute("INSERT INTO meeting_segments(meeting_id,idx,start_s,end_s,text,speaker_key,embedding)"
                          " VALUES (?,?,?,?,?,?,?)", (mid, i, float(s["start_s"]), float(s["end_s"]), s["text"],
                                                       s["speaker_key"], json.dumps(emb) if emb is not None else None))
            for sp in speakers:
                c.execute("INSERT INTO meeting_speakers(meeting_id,key,name,profile_id,auto) VALUES (?,?,?,?,?)",
                          (mid, sp["key"], sp["name"], sp.get("profile_id"), int(bool(sp.get("auto")))))

    def segments(self, mid: str, with_embeddings: bool = False) -> list[dict[str, Any]]:
        cols = "id,idx,start_s,end_s,text,speaker_key" + (",embedding" if with_embeddings else "")
        out = []
        for r in self.db.query(f"SELECT {cols} FROM meeting_segments WHERE meeting_id=? ORDER BY idx", (mid,)):  # noqa: S608
            s = dict(r)
            if with_embeddings:
                s["embedding"] = json.loads(s["embedding"]) if s["embedding"] else None
            out.append(s)
        return out

    def speakers(self, mid: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT s.key, s.name, s.profile_id, s.auto, (SELECT COUNT(*) FROM meeting_segments g WHERE "
            "g.meeting_id=s.meeting_id AND g.speaker_key=s.key) AS segments, (SELECT COALESCE(SUM(g.end_s-g.start_s),0) "
            "FROM meeting_segments g WHERE g.meeting_id=s.meeting_id AND g.speaker_key=s.key) AS talk_s "
            "FROM meeting_speakers s WHERE s.meeting_id=? ORDER BY s.key", (mid,))
        out = [dict(r) for r in rows]
        for s in out:
            s["auto"] = bool(s["auto"])
        return sorted(out, key=lambda s: int(s["key"][1:]) if s["key"][1:].isdigit() else 999)

    def rename_speaker(self, mid: str, key: str, name: str, profile_id: str | None) -> bool:
        with self.db.tx() as c:
            return c.execute("UPDATE meeting_speakers SET name=?, profile_id=?, auto=0 WHERE meeting_id=? AND key=?",
                             (name, profile_id, mid, key)).rowcount == 1

    def add_speaker(self, mid: str, name: str | None = None) -> str:
        keys = [s["key"] for s in self.speakers(mid)]
        n = max([int(k[1:]) for k in keys if k[1:].isdigit()] or [0]) + 1
        with self.db.tx() as c:
            c.execute("INSERT INTO meeting_speakers(meeting_id,key,name,auto) VALUES (?,?,?,0)",
                      (mid, f"S{n}", name or speaker_label(n)))
        return f"S{n}"

    def set_segment_speaker(self, mid: str, seg_id: int, key: str) -> bool:
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM meeting_speakers WHERE meeting_id=? AND key=?", (mid, key)).fetchone() is None:
                return False
            return c.execute("UPDATE meeting_segments SET speaker_key=? WHERE meeting_id=? AND id=?",
                             (key, mid, seg_id)).rowcount == 1

    def set_segment_text(self, mid: str, seg_id: int, text: str) -> bool:
        with self.db.tx() as c:
            return c.execute("UPDATE meeting_segments SET text=? WHERE meeting_id=? AND id=?",
                             (text, mid, seg_id)).rowcount == 1

    def merge_speakers(self, mid: str, src: str, dst: str) -> bool:
        if src == dst:
            return False
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM meeting_speakers WHERE meeting_id=? AND key=?", (mid, dst)).fetchone() is None:
                return False
            c.execute("UPDATE meeting_segments SET speaker_key=? WHERE meeting_id=? AND speaker_key=?", (dst, mid, src))
            return c.execute("DELETE FROM meeting_speakers WHERE meeting_id=? AND key=?", (mid, src)).rowcount == 1

    # ---- remembered voices --------------------------------------------------------------------
    def profiles(self, with_embeddings: bool = False) -> list[dict[str, Any]]:
        out = []
        for r in self.db.query("SELECT * FROM speaker_profiles ORDER BY name COLLATE NOCASE"):
            p = dict(r)
            if with_embeddings:
                p["embedding"] = json.loads(p["embedding"])
            else:
                p.pop("embedding")
            out.append(p)
        return out

    def profile_by_name(self, name: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM speaker_profiles WHERE name=? COLLATE NOCASE", (name,))
        if r is None:
            return None
        p = dict(r)
        p["embedding"] = json.loads(p["embedding"])
        return p

    def learn_profile(self, name: str, embedding: list[float], samples: int) -> str:
        """Create or update the remembered voice `name` with a weighted running mean of its features."""
        p = self.profile_by_name(name)
        now = utcnow()
        with self.db.tx() as c:
            if p is None:
                pid = new_id("voice")
                c.execute("INSERT INTO speaker_profiles(id,name,embedding,samples,updated_at) VALUES (?,?,?,?,?)",
                          (pid, name, json.dumps(embedding), samples, now))
                return pid
            old, n = p["embedding"], int(p["samples"])
            if len(old) == len(embedding):
                total = max(1, n + samples)
                merged = [(a * n + b * samples) / total for a, b in zip(old, embedding, strict=True)]
            else:  # feature layout changed: start over
                merged, total = embedding, samples
            c.execute("UPDATE speaker_profiles SET embedding=?, samples=?, updated_at=? WHERE id=?",
                      (json.dumps(merged), total, now, p["id"]))
            return str(p["id"])

    def delete_profile(self, pid: str) -> bool:
        with self.db.tx() as c:
            c.execute("UPDATE meeting_speakers SET profile_id=NULL WHERE profile_id=?", (pid,))
            return c.execute("DELETE FROM speaker_profiles WHERE id=?", (pid,)).rowcount == 1
