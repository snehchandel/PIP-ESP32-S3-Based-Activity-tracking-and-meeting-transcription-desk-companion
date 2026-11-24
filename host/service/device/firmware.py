"""In-app firmware updates: validate an ESP32-S3 app image (must be PIP's own project), then stream it to the
board as OTA_BEGIN / OTA_DATA / OTA_END frames over whatever link is up (USB or Wi-Fi). PIP writes the inactive
slot, checks SHA-256, reboots into it and keeps it only after 20 s of healthy running (automatic rollback)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import struct
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..protocol import AckStatus, FrameType

if TYPE_CHECKING:
    from .link import DeviceLink

log = logging.getLogger("pip.firmware")
PROJECT = "pip_firmware"
CHUNK = 4000  # payload = 4-byte offset + chunk <= 4096
IMAGE_MAGIC = 0xE9
APP_DESC_OFFSET = 0x20
APP_DESC_MAGIC = 0xABCD5432


def image_info(data: bytes) -> dict[str, Any]:
    """Parse esp_app_desc_t from an app image; raises ValueError if it isn't a PIP firmware image."""
    if len(data) < APP_DESC_OFFSET + 256 or data[0] != IMAGE_MAGIC:
        raise ValueError("not an ESP32 application image (.bin)")
    magic, = struct.unpack_from("<I", data, APP_DESC_OFFSET)
    if magic != APP_DESC_MAGIC:
        raise ValueError("image has no application description")

    def cstr(off: int, n: int) -> str:
        return data[APP_DESC_OFFSET + off: APP_DESC_OFFSET + off + n].split(b"\0", 1)[0].decode(errors="replace")

    info = {"version": cstr(16, 32), "project": cstr(48, 32), "time": cstr(80, 16), "date": cstr(96, 16),
            "idf": cstr(112, 32), "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if info["project"] != PROJECT:
        raise ValueError(f"this image is for '{info['project']}', not PIP")
    return info


class FirmwareUpdater:
    def __init__(self, link: DeviceLink, data_dir: Path, build_bin: Path) -> None:
        self.link = link
        self.upload_path = data_dir / "firmware" / "upload.bin"
        self.build_bin = build_bin
        self.status: dict[str, Any] = {"state": "IDLE", "progress": 0, "message": ""}
        self._task: asyncio.Task[None] | None = None

    def sources(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, path in (("build", self.build_bin), ("upload", self.upload_path)):
            if path.exists():
                try:
                    out[name] = image_info(path.read_bytes())
                except ValueError as e:
                    out[name] = {"error": str(e)}
        return out

    def save_upload(self, data: bytes) -> dict[str, Any]:
        info = image_info(data)  # validate before keeping it
        self.upload_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_path.write_bytes(data)
        return info

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, source: str) -> None:
        path = self.build_bin if source == "build" else self.upload_path
        if self.busy:
            raise RuntimeError("an update is already running")
        if not path.exists():
            raise FileNotFoundError("no firmware image for that source")
        data = path.read_bytes()
        image_info(data)
        self._task = asyncio.create_task(self._run(data))

    def _set(self, state: str, progress: int, message: str) -> None:
        self.status = {"state": state, "progress": progress, "message": message, "at": time.time()}
        self.link.notify("firmware_update", self.status)

    async def _req(self, ftype: int, payload: bytes, timeout: float, tries: int = 3) -> int | None:
        for _ in range(tries):
            st = await self.link.request(ftype, payload, timeout)
            if st is not None:
                return st
        return None

    async def _run(self, data: bytes) -> None:
        info = image_info(data)
        via = self.link.transport_kind
        boot0 = self.link.telemetry.get("boot_id")
        try:
            if not self.link.linked:
                raise RuntimeError("PIP is not connected")
            self._set("SENDING", 0, f"Preparing PIP for {info['version']} (via {via})…")
            begin = struct.pack("<I", len(data)) + hashlib.sha256(data).digest() + info["version"].encode()[:31].ljust(32, b"\0")
            st = await self._req(FrameType.OTA_BEGIN, begin, timeout=30.0, tries=1)  # erasing the slot takes a few s
            if st == AckStatus.UNKNOWN_TYPE:
                raise RuntimeError("this PIP (or the simulator) does not support in-app updates")
            if st != AckStatus.OK:
                raise RuntimeError(f"PIP refused the update (status {st})")
            t0 = time.monotonic()
            for off in range(0, len(data), CHUNK):
                st = await self._req(FrameType.OTA_DATA, struct.pack("<I", off) + data[off: off + CHUNK], timeout=5.0)
                if st != AckStatus.OK:
                    raise RuntimeError(f"transfer failed at {off} bytes (status {st})")
                pct = int((off + CHUNK) * 100 / len(data))
                if pct != self.status["progress"]:
                    self._set("SENDING", min(pct, 100), f"Sending {min(pct, 100)} %")
            st = await self._req(FrameType.OTA_END, b"", timeout=15.0, tries=1)
            if st != AckStatus.OK:
                raise RuntimeError("PIP rejected the image (checksum or validation failed)")
            log.info("firmware %s sent in %.1f s via %s", info["version"], time.monotonic() - t0, via)
            self._set("REBOOTING", 100, "Installed. PIP is restarting…")
            # PIP reboots (USB reconnects within ~1 s, so a dropped link may never be seen): wait for a new boot id
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                await asyncio.sleep(2.0)
                if not self.link.linked:
                    continue
                diag = await self.link.diagnostics(timeout=3.0) or {}
                if diag.get("boot_id") not in (None, boot0):
                    slot = (diag.get("ota") or {}).get("slot", "?")
                    self._set("DONE", 100, f"PIP restarted on {diag.get('fw_ver', '?')} ({slot}). It keeps this version "
                                           "after 20 s of healthy running, otherwise it rolls back by itself.")
                    return
            raise RuntimeError("PIP did not come back after the update - it will roll back to the previous firmware")
        except Exception as e:
            log.warning("firmware update failed: %s", e)
            self._set("FAILED", int(self.status.get("progress", 0)), str(e))
