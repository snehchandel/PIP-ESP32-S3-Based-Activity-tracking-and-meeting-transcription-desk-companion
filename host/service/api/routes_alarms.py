"""REST: alarm CRUD (one-time + weekly), live device test, snooze/dismiss."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..calendar.timeparse import resolve_local
from .routes_core import svc

router = APIRouter(prefix="/api/v1")

class AlarmIn(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    local_hhmm: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_kind: Literal["ONCE", "RECURRING"] = "ONCE"
    fire_date: date | None = None
    rrule_days: str | None = None
    audio_mode: Literal["WAV", "TTS", "CHIME"] = "CHIME"
    audio_path: str | None = None
    tts_script: str | None = Field(default=None, max_length=1200)
    voice: str | None = Field(default=None, max_length=80)  # Piper voice name; None = the Settings default
    snooze_min: int = Field(default=5, ge=1, le=60)
    task_id: str | None = None
    enabled: bool = True


def _alarm_fields(body: AlarmIn, tz: Any) -> dict[str, Any]:
    f = body.model_dump(exclude={"fire_date"})
    f["timezone"] = tz.key
    f["enabled"] = int(body.enabled)
    if body.schedule_kind == "ONCE":
        hh, mm = (int(x) for x in body.local_hhmm.split(":"))
        d = body.fire_date or datetime.now(tz).date()
        local, _ = resolve_local(d, time(hh, mm), tz)
        if local <= datetime.now(tz) and body.fire_date is None:  # "07:00" typed in the evening = tomorrow
            local, _ = resolve_local(d + timedelta(days=1), time(hh, mm), tz)
        f["fire_utc"] = local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    f["ack_state"] = "IDLE"
    return f


def _prepare_voice(s: Any, f: dict[str, Any]) -> None:
    """A spoken alarm gets a voice (Settings default if unset) and is pre-rendered so it plays instantly."""
    if f.get("audio_mode") != "TTS":
        return
    if not (f.get("tts_script") or "").strip():
        raise HTTPException(422, "a spoken alarm needs a wake-up script")
    if f.get("voice") and f["voice"] not in s.tts.voices():
        raise HTTPException(404, "voice not found in data/voices")
    f["voice"] = f.get("voice") or s.alarm_voice("female")


@router.get("/alarms")
def list_alarms(req: Request) -> list[dict[str, Any]]:
    return svc(req).manager.alarms.list()


@router.post("/alarms")
def create_alarm(body: AlarmIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if body.schedule_kind == "RECURRING" and not body.rrule_days:
        raise HTTPException(422, "recurring alarms need rrule_days like MO,WE,FR")
    f = _alarm_fields(body, s.manager.tz)
    _prepare_voice(s, f)
    aid = s.manager.alarms.create(**f)
    s.manager.changed()
    _prerender(s, aid)
    return s.manager.alarms.get(aid) or {}


@router.patch("/alarms/{aid}")
def patch_alarm(aid: str, body: AlarmIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    f = _alarm_fields(body, s.manager.tz)
    _prepare_voice(s, f)
    if not s.manager.alarms.update(aid, **f):
        raise HTTPException(404, "alarm not found")
    s.manager.changed()
    _prerender(s, aid)
    return s.manager.alarms.get(aid) or {}


def _prerender(s: Any, aid: str) -> None:
    a = s.manager.alarms.get(aid)
    if a and a.get("audio_mode") == "TTS" and s.tts.enabled:
        import threading
        threading.Thread(target=s.alarm_audio.render, args=(a,), daemon=True, name="alarm-prerender").start()


class ScriptIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=300)  # e.g. "gym at 6, be playful"


@router.post("/alarms/script")
def write_script(body: ScriptIn, req: Request) -> dict[str, Any]:
    """Kimi writes a ~30 second spoken wake-up script (70-90 words)."""
    from ..planner import BudgetExceeded, PlannerError
    s = svc(req)
    try:
        script = s.planner().wake_script(body.title, body.note)
    except BudgetExceeded as e:
        raise HTTPException(429, f"AI budget reached: {e}") from None
    except PlannerError as e:
        raise HTTPException(503, f"AI has left the device: {e}") from None
    words = len(script.split())
    return {"script": script, "words": words, "seconds": round(words / 2.6)}


@router.delete("/alarms/{aid}")
def delete_alarm(aid: str, req: Request) -> dict[str, bool]:
    s = svc(req)
    if not s.manager.alarms.delete(aid):
        raise HTTPException(404, "alarm not found")
    s.manager.changed()
    return {"deleted": True}


@router.post("/alarms/{aid}/test")
def test_alarm(aid: str, req: Request) -> dict[str, Any]:
    s = svc(req)
    if not s.alarm_scheduler.test(aid):
        raise HTTPException(404, "alarm not found")
    return {"ringing": s.manager.ringing, "sent_to_device": s.link.linked}


class AckIn(BaseModel):
    snooze: bool = False


@router.post("/alarms/ack")
def ack_alarm(body: AckIn, req: Request) -> dict[str, Any]:
    svc(req).manager.ack_alarm(body.snooze)
    return {"ringing": svc(req).manager.ringing}
