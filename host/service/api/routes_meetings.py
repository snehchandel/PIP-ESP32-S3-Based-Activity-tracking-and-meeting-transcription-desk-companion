"""REST: meeting recordings - list, transcript review (speakers, lines), summary (on this PC or Kimi), search and
questions across meetings, action items, Obsidian vault, exports, audio, voices; Settings -> Meetings."""
from __future__ import annotations

import asyncio
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..meetings import models as model_catalog
from ..meetings.graph import build_graph
from ..meetings.handoff import PROMPT as SUMMARY_PROMPT
from ..meetings.local_ai import LocalAIError
from ..meetings.obsidian import DEFAULT_FOLDER, detected_vaults
from ..meetings.service import SUMMARY_MODES
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


@router.get("/meetings/search")
def search_meetings(req: Request, q: str, meeting_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Full-text search over every transcript and summary (no AI): best passages first."""
    return {"hits": svc(req).meetings.search(q[:300], meeting_id, max(1, min(limit, 50)))}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    engine: str = Field(default="local", pattern="^(local|kimi)$")
    meeting_id: str | None = None


@router.post("/meetings/ask")
async def ask_meetings(body: AskIn, req: Request) -> dict[str, Any]:
    """Answer a question from the meeting passages that match it (local AI by default)."""
    try:
        return await asyncio.to_thread(svc(req).meetings.ask, body.question, body.engine, body.meeting_id)
    except LocalAIError as e:
        raise HTTPException(503, f"Local AI couldn't answer: {e}") from e
    except PlannerError as e:
        raise HTTPException(502, f"Kimi couldn't answer: {e}") from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/meetings/actions")
def meeting_actions(req: Request, archived: bool = False) -> dict[str, Any]:
    """Every action item from every summarised meeting: undecided first, mine first."""
    return {"items": svc(req).meetings.action_items(include_archived=archived), "my_name": svc(req).my_name()}


@router.get("/meetings/graph")
def meetings_graph(req: Request, archived: bool = False) -> dict[str, Any]:
    """Meetings, summaries, people and topics as a graph (the links the Obsidian notes make)."""
    s = svc(req)
    return build_graph(s.meetings.repo.all_with_summaries(), s.vocabulary(), include_archived=archived)


@router.post("/meetings/clean-transcripts")
def clean_transcripts(req: Request) -> dict[str, int]:
    """Remove fillers and stutters from transcripts made before the clean-up existed (originals are kept)."""
    return svc(req).meetings.clean_existing()


@router.post("/meetings/vault/sync")
def vault_sync(req: Request) -> dict[str, Any]:
    s = svc(req)
    if s.vault() is None:
        raise HTTPException(409, "choose an Obsidian vault in Settings first")
    return {"written": s.meetings.sync_vault_all()}


@router.get("/meetings/summary-prompt")
def summary_prompt() -> dict[str, str]:
    """The prompt to give another AI agent with a transcript; its Markdown reply can be uploaded back (ADR-036)."""
    return {"prompt": SUMMARY_PROMPT}


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
        svc(req).meetings.touched(mid)
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
    key = svc(req).meetings.repo.add_speaker(mid, body.name)
    svc(req).meetings.touched(mid)
    return {"key": key}


class Merge(BaseModel):
    into: str


@router.post("/meetings/{mid}/speakers/{key}/merge")
def merge_speaker(mid: str, key: str, body: Merge, req: Request) -> dict[str, bool]:
    _meeting(req, mid)
    if not svc(req).meetings.repo.merge_speakers(mid, key, body.into):
        raise HTTPException(404, "speaker not found")
    svc(req).meetings.touched(mid)
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
    svc(req).meetings.touched(mid)
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
async def summarize(mid: str, req: Request, engine: str = "local") -> dict[str, Any]:
    """engine=local: queued for this PC (answer at once, `meeting_updated` events follow); engine=kimi: Kimi now."""
    _meeting(req, mid)
    if engine not in ("local", "kimi"):
        raise HTTPException(422, "engine must be local or kimi")
    try:
        return await asyncio.to_thread(svc(req).meetings.summarize, mid, engine)
    except PlannerError as e:
        raise HTTPException(502, f"Kimi couldn't summarize: {e}") from e
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from e


MAX_SUMMARY_BYTES = 512 * 1024


@router.post("/meetings/{mid}/summary/upload")
async def upload_summary(mid: str, req: Request, source: str = "") -> dict[str, Any]:
    """A summary another AI agent wrote (Markdown, raw request body) becomes the meeting's summary."""
    _meeting(req, mid)
    raw = await req.body()
    if len(raw) > MAX_SUMMARY_BYTES:
        raise HTTPException(413, "that file is too large for a summary (512 KB max)")
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        raise HTTPException(422, "empty upload")
    try:
        return await asyncio.to_thread(svc(req).meetings.upload_summary, mid, text, source)
    except KeyError as e:
        raise HTTPException(404, "meeting not found") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


class ParkIn(BaseModel):
    indexes: list[int] | None = None  # which action items; default: every undecided one


@router.post("/meetings/{mid}/park-actions")
def park_actions(mid: str, req: Request, body: ParkIn | None = None) -> dict[str, Any]:
    """Send chosen (default: all undecided) action items to Parked tangents - each one only once."""
    s = svc(req)
    m = _meeting(req, mid)
    items = (m.get("summary") or {}).get("action_items") or []
    if not items:
        raise HTTPException(409, "summarize the meeting first")
    wanted = body.indexes if body and body.indexes is not None else range(len(items))
    picks = [{"index": i, "as": "park"} for i in wanted
             if 0 <= i < len(items) and items[i].get("status", "new") == "new" and not items[i].get("parked")
             and not items[i].get("done")]
    made = s.meetings.convert_actions(mid, picks)
    return {"parked_ids": [x["id"] for x in made]}


class ActionPatch(BaseModel):
    task: str | None = Field(default=None, min_length=2, max_length=200)
    owner: str | None = Field(default=None, max_length=60)
    due_date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # "" clears it
    due_time: str | None = Field(default=None, pattern=r"^(\d{2}:\d{2})?$")
    status: str | None = Field(default=None, pattern="^(new|dismissed)$")  # task/reminder/parked come from convert
    done: bool | None = None


@router.patch("/meetings/{mid}/actions/{index}")
def patch_action(mid: str, index: int, body: ActionPatch, req: Request) -> dict[str, Any]:
    _meeting(req, mid)
    fields = {k: (v or None) if k in ("due_date", "due_time", "owner") else v
              for k, v in body.model_dump(exclude_unset=True).items()}
    try:
        return svc(req).meetings.update_action(mid, index, **fields)
    except KeyError as e:
        raise HTTPException(404, "action item not found") from e


class Pick(BaseModel):
    index: int = Field(ge=0)
    as_: str = Field(alias="as", pattern="^(task|reminder|park)$")
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")


class ConvertIn(BaseModel):
    items: list[Pick] = Field(min_length=1, max_length=50)


@router.post("/meetings/{mid}/actions/convert")
def convert_actions(mid: str, body: ConvertIn, req: Request) -> dict[str, Any]:
    """Make chosen action items into tasks (on their date), reminders (date + time) or parked tangents."""
    _meeting(req, mid)
    picks = [{"index": p.index, "as": p.as_, "date": p.date, "time": p.time} for p in body.items]
    return {"made": svc(req).meetings.convert_actions(mid, picks)}


class ArchiveIn(BaseModel):
    archived: bool = True


@router.post("/meetings/{mid}/archive")
def archive_meeting(mid: str, body: ArchiveIn, req: Request) -> dict[str, Any]:
    """Archive (or restore) a meeting: kept on the PC, left out of search, questions, action lists, calendar."""
    _meeting(req, mid)
    svc(req).meetings.archive(mid, body.archived)
    return {"archived": body.archived}


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


# ---- Settings -> Meetings: summaries, local AI, Obsidian ----------------------------------------------------
def _meeting_settings(req: Request) -> dict[str, Any]:
    s = svc(req)
    p = s.settings.prefs()
    vault = str(p.get("obsidian_vault") or "")
    from ..speech.stt import cuda_usable
    return {"summary_mode": s.meeting_summary_mode(), "summary_modes": list(SUMMARY_MODES),
            "summary_quality": s.meeting_summary_quality(), "my_name": s.my_name(),
            "my_name_set": bool(str(p.get("my_name") or "").strip()),
            "speech_model": str(p.get("meeting_stt_model") or "auto"), "speech_model_active": s.meeting_stt_model(),
            "speech_models": list(s.MEETING_STT_MODELS), "gpu_speech": cuda_usable(),
            "transcript_cleanup": s.transcript_cleanup(),
            "local_ai": s.local_ai.status(),
            "obsidian": {"vault": vault, "folder": str(p.get("obsidian_folder") or DEFAULT_FOLDER),
                         "enabled": s.vault() is not None, "detected": detected_vaults()}}


@router.get("/settings/meetings")
def meeting_settings(req: Request) -> dict[str, Any]:
    return _meeting_settings(req)


class MeetingSettingsIn(BaseModel):
    summary_mode: str | None = Field(default=None, pattern="^(local|kimi|off)$")
    local_ai_model: str | None = Field(default=None, min_length=2, max_length=80, pattern=r"^[\w.:/-]+$")
    obsidian_vault: str | None = Field(default=None, max_length=400)  # "" turns the vault off
    obsidian_folder: str | None = Field(default=None, min_length=1, max_length=60)
    summary_quality: str | None = Field(default=None, pattern="^(careful|fast)$")
    my_name: str | None = Field(default=None, max_length=60)  # "" = guess from the voices
    speech_model: str | None = Field(default=None, pattern="^(auto|small.en|medium.en|large-v3-turbo|large-v3)$")
    transcript_cleanup: bool | None = None


@router.put("/settings/meetings")
def set_meeting_settings(body: MeetingSettingsIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    vault_changed = False
    if body.obsidian_vault is not None:
        path = body.obsidian_vault.strip()
        if path and not Path(path).is_dir():
            raise HTTPException(404, "that folder does not exist")
        vault_changed = path != str(s.settings.prefs().get("obsidian_vault") or "")
        s.settings.save_prefs(obsidian_vault=path)
    if body.obsidian_folder is not None:
        vault_changed = vault_changed or body.obsidian_folder.strip() != s.settings.prefs().get("obsidian_folder")
        s.settings.save_prefs(obsidian_folder=body.obsidian_folder.strip())
    if body.summary_mode is not None:
        s.settings.save_prefs(meeting_summary=body.summary_mode)
    if body.local_ai_model is not None:
        s.settings.save_prefs(local_ai_model=body.local_ai_model)
    if body.summary_quality is not None:
        s.settings.save_prefs(meeting_summary_quality=body.summary_quality)
    if body.speech_model is not None:
        s.settings.save_prefs(meeting_stt_model=body.speech_model)
        stt = s.meetings.stt
        if getattr(stt, "model_name", None) != s.meeting_stt_model():
            stt.unload()  # loaded again, with the new model, by the next transcription
            stt.model_name = s.meeting_stt_model()
    if body.transcript_cleanup is not None:
        s.settings.save_prefs(transcript_cleanup=body.transcript_cleanup)
        s.stt.cleanup = body.transcript_cleanup
    if body.my_name is not None:
        s.settings.save_prefs(my_name=" ".join(body.my_name.split()) or "")
        threading.Thread(target=s.meetings.reenrich_all, name="pip-mine", daemon=True).start()
    if vault_changed and s.vault() is not None:  # write every meeting there now, in the background
        threading.Thread(target=s.meetings.sync_vault_all, name="pip-vault-sync", daemon=True).start()
    return _meeting_settings(req)


MODEL_NAME = r"^[\w][\w.:/-]{1,79}$"  # an Ollama model name, e.g. qwen3:8b or hf.co/org/model:Q4_K_M


@router.get("/settings/local-ai/models")
def local_models(req: Request) -> dict[str, Any]:
    """Models to choose from: the curated catalog marked downloaded / fits this PC / recommended / in use, plus any
    other downloaded model, the PC's GPU and RAM, and the download in progress."""
    s = svc(req)
    try:
        installed, running = s.local_ai.installed(), True
    except LocalAIError:
        installed, running = [], False
    out = model_catalog.listing(installed, s.local_ai.model, model_catalog.hardware())
    return {**out, "running": running, "pull": dict(s.local_ai.pull_state)}


class PullIn(BaseModel):
    model: str | None = Field(default=None, pattern=MODEL_NAME)  # default: the model in use
    use: bool = False  # switch to it once it is downloaded


@router.post("/settings/local-ai/pull")
def pull_local_model(req: Request, body: PullIn | None = None) -> dict[str, Any]:
    """Download a local AI model through Ollama (GBs; progress in GET /settings/local-ai/models)."""
    s = svc(req)
    model = (body.model if body and body.model else s.local_ai.model).strip()
    if not s.local_ai.status()["running"]:
        raise HTTPException(409, "Ollama is not running on this PC - install it from ollama.com first")
    use = bool(body and body.use)
    if not s.local_ai.pull(model, on_done=(lambda m: s.settings.save_prefs(local_ai_model=m)) if use else None):
        raise HTTPException(409, "a download is already running")
    return local_models(req)


@router.delete("/settings/local-ai/models")
def remove_local_model(req: Request, name: str) -> dict[str, Any]:
    """Delete a downloaded model from disk (the one in use can't be removed - pick another first)."""
    s = svc(req)
    if not re.match(MODEL_NAME, name):
        raise HTTPException(422, "not a model name")
    if model_catalog.same_model(name, s.local_ai.model):
        raise HTTPException(409, "that model is in use - choose another one first")
    try:
        s.local_ai.delete(name)
    except LocalAIError as e:
        raise HTTPException(409, str(e)) from e
    return local_models(req)
