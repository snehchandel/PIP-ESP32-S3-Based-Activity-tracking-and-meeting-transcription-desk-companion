"""REST: health, state, planning, tasks, steps, timer (spec 7.1)."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..planner.schema import PlannerOutputV1
from ..planner.step_templates import steps_for
from ..services import Services

router = APIRouter(prefix="/api/v1")


def svc(req: Request) -> Services:
    return req.app.state.services  # type: ignore[no-any-return]


@router.get("/health")
def health(req: Request) -> dict[str, Any]:
    s = svc(req)
    return {"status": "ok", "device_transport": s.link.transport_kind,
            "link_state": "TETHERED" if s.link.linked else "STANDALONE",
            "planner_mode": s.planner_mode, "stt_mode": s.stt.status, "tts_mode": s.tts.status,
            "revision": s.manager.revision}


@router.get("/state")
def state(req: Request) -> dict[str, Any]:
    s = svc(req)
    st = s.manager.full_state()
    st["device"] = {"transport": s.link.transport_kind, "linked": s.link.linked, "telemetry": s.link.telemetry,
                    "heartbeat": s.link.last_heartbeat}
    st["voice"] = s.voice.last
    return st


class PlanIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    auto_commit: bool = False
    activity: Literal["BRAIN_DUMP", "CALENDAR", "FOCUS", "ALARMS"] = "BRAIN_DUMP"


@router.post("/tasks/plan")
def plan(body: PlanIn, req: Request) -> dict[str, Any]:
    from ..speech.pipeline import AI_GONE, AiUnavailable

    s = svc(req)
    try:
        result = s.voice.process_text(body.text, key=f"text-{hash(body.text)}-{s.manager.revision}",
                                      source="text", auto_commit=False, activity=body.activity)
    except AiUnavailable as e:
        raise HTTPException(503, f"{AI_GONE[0]}: {e}") from None
    if body.auto_commit and not result["plan"].get("needs_confirmation"):
        result["committed"] = s.manager.commit_plan(PlannerOutputV1.model_validate(result["plan"]), body.text)
        s.manager.device.set_voice_status(result["voice_session_id"], "COMMITTED")
    return result


class CommitIn(BaseModel):
    plan: PlannerOutputV1
    source_text: str = ""
    activate: bool = True
    voice_session_id: str | None = None


@router.post("/tasks/commit")
def commit(body: CommitIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    out = s.manager.commit_plan(body.plan, body.source_text, body.activate)
    if body.voice_session_id:
        s.manager.device.set_voice_status(body.voice_session_id, "COMMITTED", body.plan.model_dump_json())
    return out


HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    target_date: date
    start_hhmm: str | None = Field(default=None, pattern=HHMM)
    block_min: int | None = Field(default=None, ge=5, le=24 * 60)
    steps: list[dict[str, Any]] | None = None


@router.get("/tasks")
def list_tasks(req: Request, date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    return svc(req).manager.tasks.list_tasks(date_from, date_to)


@router.post("/tasks")
def create_task(body: TaskIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    tid = s.manager.tasks.create_task(body.title, body.steps or steps_for(body.title), body.target_date.isoformat(),
                                      s.manager.tz.key, start_hhmm=body.start_hhmm)
    if body.block_min:
        s.manager.tasks.update_task(tid, block_min=body.block_min)
    s.manager.changed()
    if not body.steps:  # placeholder steps now, Kimi's concrete ones a few seconds later
        s.refine_task_steps(tid, body.title)
    return s.manager.tasks.get_task(tid) or {}


class TaskPatch(BaseModel):
    title: str | None = None
    target_date: date | None = None
    status: str | None = None
    if_then_cue: str | None = None
    start_hhmm: str | None = Field(default=None, pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")  # "" clears the time
    block_min: int | None = Field(default=None, ge=0, le=24 * 60)  # calendar length (0 = the open steps' total)


@router.patch("/tasks/{tid}")
def patch_task(tid: str, body: TaskPatch, req: Request) -> dict[str, Any]:
    s = svc(req)
    if not s.manager.tasks.update_task(tid, title=body.title, status=body.status, if_then_cue=body.if_then_cue,
                                       target_date=body.target_date.isoformat() if body.target_date else None,
                                       start_hhmm=body.start_hhmm, block_min=body.block_min):
        raise HTTPException(404, "task not found")
    s.manager.changed()
    return s.manager.tasks.get_task(tid) or {}


@router.delete("/tasks/{tid}")
def delete_task(tid: str, req: Request) -> dict[str, bool]:
    s = svc(req)
    with s.manager.lock:
        if s.manager.device.state().get("active_task_id") == tid:
            s.manager.device.update(active_task_id=None, active_step_id=None)
            s.manager.timer.load(0, 0, "STOPPED")
        if not s.manager.tasks.delete_task(tid):
            raise HTTPException(404, "task not found")
        s.manager.changed()
    return {"deleted": True}


@router.post("/tasks/{tid}/park")
def park(tid: str, req: Request) -> dict[str, Any]:
    """Send a task (usually the one in progress) back to Parked tangents; its steps are kept for later."""
    pid = svc(req).manager.park_active_task(tid)
    if pid is None:
        raise HTTPException(404, "no open task with that id")
    return {"parked_id": pid}


@router.post("/tasks/{tid}/activate")
def activate(tid: str, req: Request) -> dict[str, Any]:
    try:
        svc(req).manager.activate_task(tid)
    except KeyError:
        raise HTTPException(404, "task not found") from None
    return svc(req).manager.full_state()


@router.post("/steps/{sid}/complete")
def complete(sid: str, req: Request) -> dict[str, Any]:
    if svc(req).manager.complete_step(sid) is None:
        raise HTTPException(409, "step not found or already complete")
    return svc(req).manager.full_state()


@router.post("/steps/{sid}/rescue-split")
def split(sid: str, req: Request) -> dict[str, Any]:
    r = svc(req).manager.rescue_split(sid)
    if r is None:
        raise HTTPException(409, "step not found or already complete")
    return {"current_sec": r[0], "next_sec": r[1], "state": svc(req).manager.full_state()}


class ReorderIn(BaseModel):
    task_id: str
    step_ids: list[str]


@router.patch("/steps/reorder")
def reorder(body: ReorderIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    try:
        s.manager.tasks.reorder_steps(body.task_id, body.step_ids)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    s.manager.changed()
    return s.manager.tasks.get_task(body.task_id) or {}


@router.post("/timer/{action}")
def timer(action: str, req: Request) -> dict[str, Any]:
    m = svc(req).manager
    fns = {"start": m.timer_start, "resume": m.timer_start, "pause": m.timer_pause, "break": m.start_break,
           "reset": m.timer_reset, "end-break": m.end_break, "next": m.start_next_step}
    if action not in fns:
        raise HTTPException(404, f"unknown timer action '{action}'")
    fns[action]()
    return m.full_state()
