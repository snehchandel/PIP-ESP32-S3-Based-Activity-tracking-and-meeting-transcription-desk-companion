"""REST: reminders, parked tangents, confirmations, calendar, device mirror, settings."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..calendar.agenda import day_items
from ..planner.step_templates import steps_for
from .routes_core import health, svc

router = APIRouter(prefix="/api/v1")


class ReminderIn(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    due_local: datetime
    if_then_cue: str | None = None


@router.get("/reminders")
def reminders(req: Request) -> list[dict[str, Any]]:
    return svc(req).manager.tasks.reminders(include_done=True)


@router.post("/reminders")
def add_reminder(body: ReminderIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    local = body.due_local if body.due_local.tzinfo else body.due_local.replace(tzinfo=s.manager.tz)
    rid = s.manager.tasks.add_reminder(body.title, local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       s.manager.tz.key, body.if_then_cue)
    s.manager.changed()
    return {"id": rid}


class ReminderPatch(BaseModel):
    title: str | None = None
    due_local: datetime | None = None
    done: bool | None = None


@router.patch("/reminders/{rid}")
def patch_reminder(rid: str, body: ReminderPatch, req: Request) -> dict[str, bool]:
    s = svc(req)
    due = None
    if body.due_local:
        local = body.due_local if body.due_local.tzinfo else body.due_local.replace(tzinfo=s.manager.tz)
        due = local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ok = s.manager.tasks.update_reminder(rid, title=body.title, due_utc=due,
                                         done=None if body.done is None else int(body.done))
    if not ok:
        raise HTTPException(404, "reminder not found")
    s.manager.changed()
    return {"updated": True}


@router.delete("/reminders/{rid}")
def delete_reminder(rid: str, req: Request) -> dict[str, bool]:
    s = svc(req)
    if not s.manager.tasks.delete_reminder(rid):
        raise HTTPException(404, "reminder not found")
    s.manager.changed()
    return {"deleted": True}


@router.post("/parked/{pid}/promote")
def promote(pid: str, req: Request) -> dict[str, Any]:
    s = svc(req)
    p = s.manager.tasks.get_parked(pid)
    if p is None or p["status"] != "PARKED":
        raise HTTPException(404, "parked item not found")
    tid = s.manager.tasks.create_task(p["title"], steps_for(p["title"]), datetime.now(s.manager.tz).date().isoformat(),
                                      s.manager.tz.key)
    s.manager.tasks.set_parked_status(pid, "PROMOTED")
    if s.manager.active_step() is None:
        s.manager.activate_task(tid)
    else:
        s.manager.changed()
    return {"task_id": tid}


@router.delete("/parked/{pid}")
def dismiss_parked(pid: str, req: Request) -> dict[str, bool]:
    s = svc(req)
    if not s.manager.tasks.set_parked_status(pid, "DISMISSED"):
        raise HTTPException(404, "parked item not found")
    s.manager.changed()
    return {"dismissed": True}


class ConfirmIn(BaseModel):
    items: list[dict[str, Any]] | None = None


@router.post("/confirmation/confirm")
def confirm(body: ConfirmIn, req: Request) -> dict[str, Any]:
    return {"scheduled_ids": svc(req).manager.confirm_pending(body.items)}


@router.post("/confirmation/dismiss")
def dismiss(req: Request) -> dict[str, bool]:
    svc(req).manager.dismiss_pending()
    return {"dismissed": True}


@router.get("/calendar")
def calendar(req: Request, start: date, days: int = 7) -> list[dict[str, Any]]:
    m = svc(req).manager
    tasks, rems, alarms = m.tasks.list_tasks(), m.tasks.reminders(include_done=True), m.alarms.list()
    return [{"date": (start + timedelta(days=i)).isoformat(),
             "items": day_items(tasks, rems, alarms, start + timedelta(days=i), m.tz)} for i in range(min(days, 42))]


@router.get("/device/framebuffer.png")
async def framebuffer(req: Request) -> Response:
    png = await svc(req).link.framebuffer_png()
    if png is None:
        raise HTTPException(503, "device not connected")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


class ButtonIn(BaseModel):
    button: Literal["KEY", "BOOT"]
    gesture: Literal["SHORT", "DOUBLE", "HOLD"]
    hold_ms: int = Field(default=0, ge=0, le=65000)


@router.post("/device/simulate-button")
def simulate_button(body: ButtonIn, req: Request) -> dict[str, Any]:
    action = {"SHORT": 0, "DOUBLE": 1, "HOLD": 2}[body.gesture]
    hold = body.hold_ms or (1300 if body.button == "BOOT" else 800)
    try:
        sent = svc(req).link.simulate_button(0 if body.button == "KEY" else 1, action, hold if action == 2 else 0)
    except PermissionError as e:
        raise HTTPException(409, str(e)) from None
    if not sent:
        raise HTTPException(503, "simulator not connected")
    return {"sent": True}


@router.get("/device/diagnostics")
async def diagnostics(req: Request) -> dict[str, Any]:
    s = svc(req)
    diag = await s.link.diagnostics() if s.link.linked else None
    return {"linked": s.link.linked, "transport": s.link.transport_kind, "diag": diag,
            "heartbeat": s.link.last_heartbeat}


@router.get("/voice/sessions")
def voice_sessions(req: Request) -> list[dict[str, Any]]:
    return svc(req).manager.device.voice_sessions()


@router.get("/diagnostics/export")
async def export(req: Request) -> dict[str, Any]:
    from .routes_settings import settings  # local import: routes_settings imports this module's peers

    s = svc(req)
    return {"settings": settings(req), "health": health(req),
            "device": await diagnostics(req), "events": [dict(r) for r in s.db.query(
                "SELECT ts_utc, level, category, message FROM event_log ORDER BY id DESC LIMIT 200")]}
