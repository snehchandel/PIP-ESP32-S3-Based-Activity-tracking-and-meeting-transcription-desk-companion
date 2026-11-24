"""DeviceLink: sole owner of the serial/simulator connection (spec 7.1)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

from ..calendar.agenda import calendar_sync
from ..protocol import (Ack, AudioEnd, AudioStart, BtnEvent, Frame, FramebufferAssembler, FrameType, Heartbeat,
                        pack_chime, pack_sim_input, unpack_audio_data)
from ..protocol.fbimage import fb_to_png
from ..speech.pipeline import VoicePipeline
from ..state.manager import DeviceStateManager
from ..transport import DeviceTransport, SimTcpTransport, UsbSerialTransport, find_board_port

log = logging.getLogger("pip.link")
LINK_TIMEOUT_S = 3.0


def make_transport(mode: str, sim_addr: str, serial_port: str) -> DeviceTransport | None:
    if mode == "none":
        return None
    if mode == "usb" or (mode == "auto" and (serial_port or find_board_port())):
        return UsbSerialTransport(serial_port or None)
    return SimTcpTransport(sim_addr)


class DeviceLink:
    def __init__(self, manager: DeviceStateManager, transport: DeviceTransport | None, voice: VoicePipeline,
                 notify: Callable[[str, dict[str, Any]], None]) -> None:
        self.m = manager
        self.t = transport
        self.voice = voice
        self.notify = notify
        self.loop: asyncio.AbstractEventLoop | None = None
        self.linked = False
        self.last_rx = 0.0
        self.telemetry: dict[str, Any] = {}
        self.last_heartbeat: dict[str, Any] = {}
        self.btn_seen: set[tuple[int, int]] = set()
        self._fb = FramebufferAssembler()
        self._fb_waiters: list[asyncio.Future[bytes]] = []
        self._diag_waiters: list[asyncio.Future[dict[str, Any]]] = []
        self._task: asyncio.Task[None] | None = None

    @property
    def transport_kind(self) -> str:
        return self.t.kind if (self.t and self.linked) else "DISCONNECTED"

    # ---- lifecycle -------------------------------------------------------------------------
    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.m.subscribe(self._on_state_change)
        if self.t:
            self.t.on_frame = lambda f: self.loop.call_soon_threadsafe(self._handle, f)  # type: ignore[union-attr]
            self.t.start()
        self._task = asyncio.create_task(self._supervise())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self.t:
            self.t.stop()

    async def _supervise(self) -> None:
        while True:
            try:
                self._heartbeat()
                if self.m.tick():
                    pass  # tick already pushed via change listener
                linked = bool(self.t and self.t.connected and time.monotonic() - self.last_rx < LINK_TIMEOUT_S)
                if linked != self.linked:
                    self.linked = linked
                    self.notify("device_link_changed", {"linked": linked, "transport": self.transport_kind})
                    if linked:
                        self.push_all()
                        self.send(FrameType.DIAG_REPORT)
                self.notify("timer_tick", {"remaining_ms": self.m.timer.remaining_ms, "state": self.m.timer.state,
                                           "ui_state": self.m.ui_state()})
            except Exception:
                log.exception("supervisor iteration failed")
            await asyncio.sleep(1.0)

    # ---- outgoing ---------------------------------------------------------------------------
    def send(self, ftype: int, payload: bytes = b"", ack: bool = False) -> bool:
        if not self.t or not self.t.connected:
            return False
        try:
            self.t.send(ftype, payload, ack)
            return True
        except ConnectionError:
            return False

    def send_json(self, ftype: int, obj: dict[str, Any]) -> bool:
        data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()
        return self.send(ftype, data, ack=True)

    def _heartbeat(self) -> None:
        hb = Heartbeat(1, 1, 0, int(time.monotonic()), int(time.time()), self.m.revision)
        self.send(FrameType.HEARTBEAT, hb.pack())

    def push_all(self) -> None:
        self.send_json(FrameType.UI_UPDATE, self.m.snapshot())
        self.send_json(FrameType.CALENDAR_SYNC, calendar_sync(
            self.m.tasks.list_tasks(), self.m.tasks.reminders(), self.m.alarms.list(), len(self.m.tasks.parked()),
            self.m.tz, self.m.revision))

    def _on_state_change(self, kind: str, payload: dict[str, Any]) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(self._after_change, kind, payload)

    def _after_change(self, kind: str, payload: dict[str, Any]) -> None:
        if kind == "alarm_triggered" and self.m.ringing:
            r = self.m.ringing
            self.send_json(FrameType.ALARM_TRIGGER, {"alarm_id": r["id"][:23], "title": r["title"][:60],
                                                     "subtitle": "", "hhmm": r["hhmm"], "audio_mode": r["audio_mode"],
                                                     "chime_id": 4, "snooze_min": r["snooze_min"]})
        self.push_all()

    def play_chime(self, chime_id: int) -> bool:
        return self.send(FrameType.PLAY_CHIME, pack_chime(chime_id), ack=True)

    def simulate_button(self, btn: int, action: int, hold_ms: int = 0) -> bool:
        if not self.t or self.t.kind != "SIMULATOR":
            raise PermissionError("button simulation is only available with the simulator")
        return self.send(FrameType.SIM_INPUT, pack_sim_input(btn, action, hold_ms))

    async def framebuffer_png(self, timeout: float = 3.0) -> bytes | None:
        assert self.loop
        fut: asyncio.Future[bytes] = self.loop.create_future()
        self._fb_waiters.append(fut)
        if not self.send(FrameType.DUMP_FB):
            self._fb_waiters.remove(fut)
            return None
        try:
            return fb_to_png(await asyncio.wait_for(fut, timeout))
        except asyncio.TimeoutError:
            return None
        finally:
            if fut in self._fb_waiters:
                self._fb_waiters.remove(fut)

    async def diagnostics(self, timeout: float = 3.0) -> dict[str, Any] | None:
        assert self.loop
        fut: asyncio.Future[dict[str, Any]] = self.loop.create_future()
        self._diag_waiters.append(fut)
        self.send(FrameType.DIAG_REPORT)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return self.telemetry or None
        finally:
            if fut in self._diag_waiters:
                self._diag_waiters.remove(fut)

    # ---- incoming ------------------------------------------------------------------------------
    def _handle(self, f: Frame) -> None:
        self.last_rx = time.monotonic()
        status = 0
        try:
            status = self._dispatch(f)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            log.warning("bad frame 0x%02X: %s", f.type, e)
            status = 3
        if f.ack_required and f.type != FrameType.ACK:
            self.send(FrameType.ACK, Ack(f.seq, status).pack())

    def _dispatch(self, f: Frame) -> int:
        t = f.type
        if t == FrameType.HEARTBEAT:
            hb = Heartbeat.unpack(f.payload)
            self.last_heartbeat = {"uptime_s": hb.uptime_s, "utc_epoch_s": hb.utc_epoch_s, "link_mode": hb.link_mode,
                                   "is_sim": bool(hb.flags & 2), "offline_pending": bool(hb.flags & 1)}
        elif t == FrameType.BTN_EVENT:
            ev = BtnEvent.unpack(f.payload)
            boot = int(self.telemetry.get("boot_id", 0))
            if (boot, ev.event_seq) not in self.btn_seen:  # idempotent on retransmit
                self.btn_seen.add((boot, ev.event_seq))
                action = self.m.apply_button(ev.btn_id, ev.gesture, ev.flags)
                self.notify("button_event", {"btn": ev.btn_id, "gesture": ev.gesture, "action": action})
        elif t == FrameType.OFFLINE_EVENTS:
            events = json.loads(f.payload.decode())
            n = self.m.apply_offline_events(events if isinstance(events, list) else [])
            log.info("reconciled %d offline events", n)
        elif t == FrameType.DIAG_REPORT:
            self.telemetry = json.loads(f.payload.decode())
            self.m.device.update(fw_version=self.telemetry.get("fw_ver"), proto_version=self.telemetry.get("proto_ver"))
            for w in self._diag_waiters:
                if not w.done():
                    w.set_result(self.telemetry)
        elif t == FrameType.DUMP_FB:
            fb = self._fb.add(f.payload)
            if fb:
                for w in self._fb_waiters:
                    if not w.done():
                        w.set_result(fb)
                self.notify("framebuffer_updated", {})
        elif t == FrameType.AUDIO_START:
            self.voice.start(AudioStart.unpack(f.payload).stream_id)
        elif t == FrameType.AUDIO_DATA:
            sid, _, pcm = unpack_audio_data(f.payload)
            self.voice.data(sid, pcm)
        elif t == FrameType.AUDIO_END:
            e = AudioEnd.unpack(f.payload)
            self.voice.end(e.stream_id, e.total_samples)
        elif t == FrameType.ACK:
            pass
        else:
            return 5
        return 0
