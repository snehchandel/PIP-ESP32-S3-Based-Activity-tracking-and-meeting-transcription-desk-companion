"""Blocking request helpers on top of a DeviceTransport (used by CLI tools and tests)."""
from __future__ import annotations

import json
import queue
import time
from typing import Any

from ..protocol import Ack, Frame, FramebufferAssembler, FrameType, Heartbeat, encode  # noqa: F401
from .base import DeviceTransport


class DeviceClient:
    def __init__(self, transport: DeviceTransport) -> None:
        self.t = transport
        self.frames: queue.Queue[Frame] = queue.Queue()
        self.t.on_frame = self._on_frame
        self._fb = FramebufferAssembler()
        self.state_rev = 0

    def _on_frame(self, f: Frame) -> None:
        if f.type != FrameType.HEARTBEAT and f.type != FrameType.AUDIO_DATA:
            self.frames.put(f)
        if f.ack_required and f.type != FrameType.ACK:
            self.t.send(FrameType.ACK, Ack(f.seq, 0).pack())

    def wait_connected(self, timeout: float = 5.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.t.connected:
                return True
            time.sleep(0.05)
        return False

    def heartbeat(self) -> None:
        hb = Heartbeat(1, 1, 0, int(time.monotonic()), int(time.time()), self.state_rev)
        self.t.send(FrameType.HEARTBEAT, hb.pack())

    def wait_for(self, ftype: int, timeout: float = 3.0) -> Frame | None:
        end = time.monotonic() + timeout
        stash: list[Frame] = []
        found = None
        while time.monotonic() < end:
            try:
                f = self.frames.get(timeout=0.05)
            except queue.Empty:
                continue
            if f.type == ftype:
                found = f
                break
            stash.append(f)
        for f in stash:
            self.frames.put(f)
        return found

    def drain(self) -> None:
        while not self.frames.empty():
            self.frames.get_nowait()

    def send_json(self, ftype: int, obj: dict[str, Any], ack: bool = True) -> int:
        return self.t.send(ftype, json.dumps(obj, separators=(",", ":")).encode(), ack=ack)

    def diag(self, timeout: float = 3.0) -> dict[str, Any] | None:
        self.drain()
        self.t.send(FrameType.DIAG_REPORT, b"", ack=False)
        f = self.wait_for(FrameType.DIAG_REPORT, timeout)
        return json.loads(f.payload) if f else None

    def framebuffer(self, timeout: float = 3.0, retries: int = 1) -> bytes | None:
        for _ in range(retries + 1):  # a chunk can be lost while the board is still settling after reset
            fb = self._framebuffer_once(timeout)
            if fb is not None:
                return fb
        return None

    def _framebuffer_once(self, timeout: float) -> bytes | None:
        self.drain()
        self._fb = FramebufferAssembler()
        self.t.send(FrameType.DUMP_FB)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            f = self.wait_for(FrameType.DUMP_FB, max(0.05, end - time.monotonic()))
            if f is None:
                return None
            fb = self._fb.add(f.payload)
            if fb:
                return fb
        return None
