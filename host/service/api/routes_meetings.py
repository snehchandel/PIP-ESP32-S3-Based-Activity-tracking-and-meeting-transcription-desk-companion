"""REST: meeting recordings - list, transcript review (speakers, lines), summary, exports, audio, voices."""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..planner import PlannerError
from .routes_core import svc

router = APIRouter(prefix="/api/v1")


def _meeting(req: Request, mid: str) -> dict[str, Any]:
    m = svc(req).meetings.repo.get(mid)
    if m is None:
        raise HTTPException(404, "meeting not found")
    return m


@router.get("/meetings")
def list_meetings(req: Request) -> dict[str, Any]:
    s = svc(req)
    return {"meetings": s.meetings.repo.list(), "status": s.meetings.status()}


@router.get("/meetings/{mid}")
def get_meeting(mid: str, req: Request) -> dict[str, Any]:
    m = _meeting(req, mid)
    m["segments"] = svc(req).meetings.repo.segments(mid)
    return m


class MeetingPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=20_000)


@router.patch("/meetings/{mid}")
def patch_meeting(mid: str, body: MeetingPatch, req: Request) -> dict[str, Any]:
    _meeting(req, mid)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        svc(req).meetings.repo.update(mid, **fields)
    return {"updated": bool(fields)}


@router.delete("/meetings/{mid}")
def delete_meeting(mid: str, req: Request) -> dict[str, bool]:
    _meeting(req, mid)
    if not svc(req).meetings.delete(mid):
        raise HTTPException(409, "the meeting is still recording")
    return {"deleted": True}


class SpeakerName(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    remember: bool = True  # learn this voice so future meetings name it automatically


@router.put("/meetings/{mid}/speakers/{key}")
def rename_speaker(mid: str, key: str, body: SpeakerName, req: Request) -> dict[str, Any]:
    _meeting(req, mid)
    try:
        return svc(req).meetings.rename_speaker(mid, key, body.name, body.remember)
    except KeyError as e:
        raise HTTPException(404, "speaker not found") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class NewSpeaker(BaseModel):
    name: str | None = Field(default=None, max_length=60)


@router.post("/meetings/{mid}/speakers")
def add_speaker(mid: str, body: NewSpeaker, req: Request) -> dict[str, str]:
    """A speaker the detection missed: add one, then move their lines to it."""
    _meeting(req, mid)
    return {"key": svc(req).meetings.repo.add_speaker(mid, body.name)}


class Merge(BaseModel):
    into: str


@router.post("/meetings/{mid}/speakers/{key}/merge")
def merge_speaker(mid: str, key: str, body: Merge, req: Request) -> dict[str, bool]:
    _meeting(req, mid)
    if not svc(req).meetings.repo.merge_speakers(mid, key, body.into):
        raise HTTPException(404, "speaker not found")
    return {"merged": True}


class SegmentPatch(BaseModel):
    speaker_key: str | None = None
    text: str | None = Field(default=None, min_length=1, max_length=4000)


@router.patch("/meetings/{mid}/segments/{seg_id}")
def patch_segment(mid: str, seg_id: int, body: SegmentPatch, req: Request) -> dict[str, bool]:
    _meeting(req, mid)
    repo = svc(req).meetings.repo
    ok = True
    if body.speaker_key is not None:
        ok = repo.set_segment_speaker(mid, seg_id, body.speaker_key)
    if ok and body.text is not None:
        ok = repo.set_segment_text(mid, seg_id, body.text.strip())
    if not ok:
        raise HTTPException(404, "line or speaker not found")
    return {"updated": True}


class Rediarize(BaseModel):
    num_speakers: int | None = Field(default=None, ge=1, le=12)


@router.post("/meetings/{mid}/rediarize")
async def rediarize(mid: str, body: Rediarize, req: Request) -> dict[str, Any]:
    _meeting(req, mid)
    try:
        await asyncio.to_thread(svc(req).meetings.rediarize, mid, body.num_speakers)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"speakers": svc(req).meetings.repo.speakers(mid)}


@router.post("/meetings/{mid}/retry")
def retry(mid: str, req: Request) -> dict[str, bool]:
    m = _meeting(req, mid)
    if m["status"] not in ("FAILED", "READY"):
        raise HTTPException(409, f"meeting is {m['status'].lower()}")
    svc(req).meetings.enqueue(mid)
    return {"queued": True}


@router.post("/meetings/{mid}/summarize")
async def summarize(mid: str, req: Request) -> dict[str, Any]:
    _meeting(req, mid)
    try:
        return await asyncio.to_thread(svc(req).meetings.summarize, mid)
    except PlannerError as e:
        raise HTTPException(502, f"Kimi couldn't summarize: {e}") from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/meetings/{mid}/park-actions")
def park_actions(mid: str, req: Request) -> dict[str, Any]:
    """Send the summary's action items to Parked tangents, so nothing promised in the meeting gets lost."""
    s = svc(req)
    m = _meeting(req, mid)
    items = (m.get("summary") or {}).get("action_items") or []
    if not items:
        raise HTTPException(409, "summarize the meeting first")
    ids = [s.manager.tasks.park(str(a["task"])[:64], f"From meeting '{m['title']}': {a['task']}"
                                + (f" (owner: {a['owner']})" if a.get("owner") else "")
                                + (f" (due: {a['due']})" if a.get("due") else "")) for a in items]
    s.manager.changed()
    return {"parked_ids": ids}


@router.get("/meetings/{mid}/export")
def export(mid: str, req: Request, format: str = "md") -> Response:  # noqa: A002 - query parameter name
    try:
        body, media, name = svc(req).meetings.export(mid, format)
    except KeyError as e:
        raise HTTPException(404, "meeting not found") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return Response(body.encode("utf-8"), media_type=f"{media}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/meetings/{mid}/audio")
def audio(mid: str, req: Request, download: bool = False) -> FileResponse:
    from ..meetings.export import filename

    m = _meeting(req, mid)
    path = Path(m["audio_path"])
    if not path.exists():
        raise HTTPException(404, "audio file is gone")
    return FileResponse(path, media_type="audio/wav", filename=filename(m, "wav") if download else None)


MAX_IMPORT_BYTES = 1024 * 1024 * 1024


@router.post("/meetings/import")
async def import_audio(req: Request, filename: str = "audio", title: str = "") -> dict[str, str]:
    """Transcribe an existing recording (wav, mp3, m4a...; raw request body) with the same pipeline."""
    s = svc(req)
    suffix = "".join(c for c in Path(filename).suffix[:8] if c.isalnum() or c == ".") or ".bin"
    size = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        async for chunk in req.stream():
            size += len(chunk)
            if size > MAX_IMPORT_BYTES:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(413, "audio file too large (1 GB max)")
            tmp.write(chunk)
    if size == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(422, "empty upload")
    try:
        mid = await asyncio.to_thread(s.meetings.import_audio, tmp_path, title.strip()[:80])
    except Exception as e:
        raise HTTPException(422, f"couldn't read that audio file: {str(e)[:160]}") from e
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"id": mid}


@router.get("/voices")
def voices(req: Request) -> list[dict[str, Any]]:
    """Remembered voices (named speakers PIP recognises in new meetings)."""
    return svc(req).meetings.repo.profiles()


@router.delete("/voices/{pid}")
def forget_voice(pid: str, req: Request) -> dict[str, bool]:
    if not svc(req).meetings.repo.delete_profile(pid):
        raise HTTPException(404, "voice not found")
    return {"deleted": True}
