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
    tts_script: str | None = None
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


@router.get("/alarms")
def list_alarms(req: Request) -> list[dict[str, Any]]:
    return svc(req).manager.alarms.list()


@router.post("/alarms")
def create_alarm(body: AlarmIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if body.schedule_kind == "RECURRING" and not body.rrule_days:
        raise HTTPException(422, "recurring alarms need rrule_days like MO,WE,FR")
    aid = s.manager.alarms.create(**_alarm_fields(body, s.manager.tz))
    s.manager.changed()
    return s.manager.alarms.get(aid) or {}


@router.patch("/alarms/{aid}")
def patch_alarm(aid: str, body: AlarmIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if not s.manager.alarms.update(aid, **_alarm_fields(body, s.manager.tz)):
        raise HTTPException(404, "alarm not found")
    s.manager.changed()
    return s.manager.alarms.get(aid) or {}


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
