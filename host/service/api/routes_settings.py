"""REST: dashboard settings - Kimi API key (OS keyring), Piper voice, speech status and voice tests.

The key is write-only over the API: responses only ever reveal whether it is set and its last 4 chars."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .routes_core import svc

router = APIRouter(prefix="/api/v1")


def _hint(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 8 else ""


@router.get("/settings")
def settings(req: Request) -> dict[str, Any]:
    s = svc(req)
    key = s.settings.api_key()
    return {"planner_mode": s.planner_mode, "kimi_model": s.settings.moonshot_model if key else None,
            "api_key": {"configured": bool(key), "source": s.settings.api_key_source(), "hint": _hint(key),
                        "editable": s.settings.api_key_source() != "env" and s.settings.pip_use_keyring},
            "stt": s.stt.status, "stt_ready": s.stt._model is not None, "stt_loading": s.stt.loading,
            "tts": s.tts.status, "tts_enabled": s.tts.enabled,
            "piper_voice": s.tts.voice_path.stem if s.tts.voice_path else None,
            "voices": [p.stem for p in sorted(Path(s.settings.pip_voices_dir).glob("*.onnx"))],
            "timezone": s.settings.pip_timezone, "transport_setting": s.settings.pip_transport,
            "host_port": s.settings.pip_host_port,
            "privacy": ("Typed and spoken brain dumps are sent to Moonshot (Kimi) for planning."
                        if key else "Planning runs fully on this computer (Local Rule Engine). Nothing leaves your PC."),
            "missed_alarms": s.alarm_scheduler.missed[-10:]}


class KeyIn(BaseModel):
    key: str = Field(min_length=10, max_length=300)


@router.put("/settings/api-key")
def set_key(body: KeyIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if s.settings.api_key_source() == "env":
        raise HTTPException(409, "MOONSHOT_API_KEY is set in .env, which takes priority - remove it there first")
    try:
        s.settings.set_api_key(body.key.strip())
    except Exception as e:
        raise HTTPException(500, f"could not store the key securely: {type(e).__name__}") from None
    s.db.log("INFO", "settings", "Kimi API key updated (stored in OS keyring)")
    s.hub.publish("state_updated", {"settings": True})
    return settings(req)


@router.delete("/settings/api-key")
def delete_key(req: Request) -> dict[str, Any]:
    s = svc(req)
    if s.settings.api_key_source() == "env":
        raise HTTPException(409, "the key comes from .env; remove it there")
    s.settings.set_api_key(None)
    s.db.log("INFO", "settings", "Kimi API key removed")
    return settings(req)


class KeyTestIn(BaseModel):
    key: str | None = None  # test a candidate before saving; default = the stored key


@router.post("/settings/api-key/test")
def test_key(body: KeyTestIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    key = (body.key or "").strip() or s.settings.api_key()
    if not key:
        return {"ok": False, "detail": "No key saved yet."}
    try:
        r = httpx.get(f"{s.settings.moonshot_base_url.rstrip('/')}/models",
                      headers={"Authorization": f"Bearer {key}"}, timeout=15)
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"Could not reach Moonshot: {type(e).__name__}"}
    if r.status_code == 200:
        models = [m.get("id") for m in r.json().get("data", [])]
        has = s.settings.moonshot_model in models
        return {"ok": True, "detail": f"Key works. {len(models)} models available"
                + ("" if has else f"; note: {s.settings.moonshot_model} not listed")}
    return {"ok": False, "detail": "Moonshot rejected the key (401)." if r.status_code == 401 else
            f"Moonshot answered HTTP {r.status_code}."}


class PrefsIn(BaseModel):
    piper_voice: str | None = None


@router.put("/settings/preferences")
def set_prefs(body: PrefsIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if body.piper_voice is not None:
        path = Path(s.settings.pip_voices_dir) / f"{body.piper_voice}.onnx"
        if not path.exists():
            raise HTTPException(404, "voice not found in data/voices")
        s.settings.save_prefs(piper_voice=str(path))
        s.tts.set_voice(str(path))
    return settings(req)


@router.post("/speech/preload")
def preload(req: Request) -> dict[str, Any]:
    svc(req).stt.preload()
    return settings(req)


class SayIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


@router.post("/speech/say")
async def say(body: SayIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if not s.tts.enabled:
        raise HTTPException(409, "Piper voice not configured")
    return {"played_on_device": await s.speak(body.text)}


@router.get("/speech/say.wav")
def say_wav(text: str, req: Request) -> Response:
    s = svc(req)
    if not s.tts.enabled:
        raise HTTPException(409, "Piper voice not configured")
    return Response(s.tts.synthesize_wav(text[:400]), media_type="audio/wav", headers={"Cache-Control": "no-store"})
