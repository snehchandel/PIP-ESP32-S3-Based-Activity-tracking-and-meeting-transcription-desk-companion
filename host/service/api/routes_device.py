"""REST: PIP's Wi-Fi link, wake word and in-app firmware updates.

The Wi-Fi password is relayed to PIP once and never stored or logged on the PC."""
from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..protocol import AckStatus, FrameType
from .routes_core import svc

router = APIRouter(prefix="/api/v1")

WAKE_TEST_PHRASE = {"hiesp": "Hi, E S P.", "jarvis": "Jarvis.", "computer": "Computer.", "hijoy": "Hi, Joy."}


def _network(s: Any) -> dict[str, Any]:
    wifi = dict(s.link.telemetry.get("wifi") or {})
    return {"linked": s.link.linked, "via": s.link.transport_kind, "paired_on_pc": s.settings.link_token() is not None,
            "wifi": wifi, "known_hosts": s.settings.wifi_hosts()}


@router.get("/device/network")
async def network(req: Request) -> dict[str, Any]:
    s = svc(req)
    if s.link.linked:
        await s.link.diagnostics(timeout=2.0)
    return _network(s)


class WifiIn(BaseModel):
    ssid: str = Field(min_length=1, max_length=32)
    password: str = Field(default="", max_length=64)


async def _config(s: Any, cfg: dict[str, Any]) -> None:
    import json

    if not s.link.linked:
        raise HTTPException(409, "PIP is not connected")
    st = await s.link.request(FrameType.DEVICE_CONFIG, json.dumps(cfg, separators=(",", ":")).encode(), timeout=5.0)
    if st == AckStatus.UNKNOWN_TYPE:
        raise HTTPException(409, "this PIP (or the simulator) has no Wi-Fi / wake word support")
    if st != AckStatus.OK:
        raise HTTPException(502, f"PIP did not accept the settings (status {st})")


@router.put("/device/wifi")
async def set_wifi(body: WifiIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if body.password and not 8 <= len(body.password) <= 63:
        raise HTTPException(422, "a WPA2 password is 8-63 characters")
    cfg = {"wifi": {"ssid": body.ssid, "password": body.password}}
    if s.link.transport_kind == "USB_HARDWARE":
        cfg.update(s.device_config(include_token=True))  # pair this PC at the same time
    elif s.settings.link_token() is None:
        raise HTTPException(409, "connect PIP with the USB cable once to pair it with this PC")
    await _config(s, cfg)
    s.db.log("INFO", "device", f"Wi-Fi network set to '{body.ssid}' (password not stored)")
    for _ in range(20):  # give PIP up to ~20 s to join and report its address
        await asyncio.sleep(1.0)
        diag = await s.link.diagnostics(timeout=2.0) or {}
        state = (diag.get("wifi") or {}).get("state")
        if state in ("UP", "FAILED"):
            break
    return _network(s)


@router.delete("/device/wifi")
async def forget_wifi(req: Request) -> dict[str, Any]:
    s = svc(req)
    await _config(s, {"wifi_clear": True})
    s.settings.save_prefs(device_net={})
    return _network(s)


class WakeIn(BaseModel):
    enabled: bool
    word: str = Field(default="hiesp", max_length=24)


@router.get("/device/wake")
def get_wake(req: Request) -> dict[str, Any]:
    s = svc(req)
    return {**s.wake_settings(), "words": s.WAKE_WORDS, "device": s.link.telemetry.get("wake") or {}}


@router.put("/device/wake")
async def set_wake(body: WakeIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if body.word not in s.WAKE_WORDS:
        raise HTTPException(422, "unknown wake word")
    s.settings.save_prefs(wake_enabled=body.enabled, wake_word=body.word)
    if s.link.linked:
        await _config(s, {"wake": s.wake_settings()})
        await s.link.diagnostics(timeout=2.0)
    return get_wake(req)


@router.post("/device/wake/test")
async def test_wake(req: Request) -> dict[str, Any]:
    """Speak the wake word with Piper straight into PIP's detector (not through the air)."""
    s = svc(req)
    if not s.link.linked:
        raise HTTPException(409, "PIP is not connected")
    if not s.tts.enabled:
        raise HTTPException(409, "Piper voice not configured")
    word = s.wake_settings()["word"]
    pcm = await asyncio.to_thread(s.tts.synthesize_pcm, WAKE_TEST_PHRASE[word])
    clip = np.concatenate([np.zeros(4800, np.int16), pcm.astype(np.int16), np.zeros(9600, np.int16)])
    waiter = asyncio.ensure_future(s.link.wait_wake(timeout=len(clip) / 16000 + 2.5))
    for off in range(0, len(clip), 1600):  # 100 ms per frame, real-time pacing
        s.link.send(FrameType.WAKE_TEST, clip[off: off + 1600].astype("<i2").tobytes())
        await asyncio.sleep(0.1)
    ev = await waiter
    return {"word": word, "phrase": WAKE_TEST_PHRASE[word], "detected": ev is not None}


# ---- firmware ----------------------------------------------------------------------------------
@router.get("/firmware")
def firmware(req: Request) -> dict[str, Any]:
    s = svc(req)
    return {"device": {"version": s.link.telemetry.get("fw_ver"), "ota": s.link.telemetry.get("ota") or {}},
            "linked": s.link.linked, "via": s.link.transport_kind, "available": s.firmware.sources(),
            "status": s.firmware.status}


@router.post("/firmware/upload")
async def upload(req: Request) -> dict[str, Any]:
    s = svc(req)
    data = await req.body()
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(413, "image too large")
    try:
        info = s.firmware.save_upload(data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"uploaded": info, **firmware(req)}


class UpdateIn(BaseModel):
    source: str = Field(pattern="^(build|upload)$")


@router.post("/firmware/update")
async def update(body: UpdateIn, req: Request) -> dict[str, Any]:
    s = svc(req)
    if not s.link.linked:
        raise HTTPException(409, "PIP is not connected")
    try:
        s.firmware.start(body.source)
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        raise HTTPException(409, str(e)) from None
    return firmware(req)
