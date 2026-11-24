"""Wi-Fi link (HMAC challenge handshake), USB->Wi-Fi fallback, firmware image checks and the OTA stream."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket
import struct
import threading
import time
from typing import Any

import pytest
from service.device.firmware import FirmwareUpdater, image_info
from service.protocol import AckStatus, FrameParser, FrameType, encode
from service.transport import AutoTransport, WifiTransport, auth_response

TOKEN = bytes(range(32))


class FakePip:
    """Minimal stand-in for PIP's TCP endpoint: challenge, verify HMAC, then send heartbeats."""

    def __init__(self) -> None:
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.authed: list[bool] = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            nonce = bytes(16 * [7])
            c.sendall(encode(FrameType.AUTH_CHALLENGE, nonce + b"\x01\x02\x03\x04\x05\x06", 1, 0))
            p, ok = FrameParser(), None
            c.settimeout(2)
            while ok is None:
                for f in p.feed(c.recv(256)):
                    if f.type == FrameType.AUTH_RESPONSE:
                        ok = hmac.compare_digest(f.payload, hmac.new(TOKEN, nonce, hashlib.sha256).digest())
            self.authed.append(ok)
            if ok:
                c.sendall(encode(FrameType.HEARTBEAT, struct.pack("<BBHIII", 1, 1, 0, 5, 0, 1), 2, 0))
                time.sleep(0.5)
            c.close()


def _wait(pred: Any, s: float = 3.0) -> bool:
    end = time.monotonic() + s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_auth_response_is_hmac_sha256() -> None:
    assert auth_response(TOKEN, b"n" * 16) == hmac.new(TOKEN, b"n" * 16, hashlib.sha256).digest()


def test_wifi_transport_authenticates_and_receives(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pip = FakePip()
    monkeypatch.setattr("service.transport.wifi.PIP_TCP_PORT", pip.port)
    got: list[int] = []
    t = WifiTransport(lambda: (["127.0.0.1"], TOKEN), on_frame=lambda f: got.append(f.type))
    t.start()
    try:
        assert _wait(lambda: FrameType.HEARTBEAT in got)
        assert pip.authed[0] is True and t.kind == "WIFI"
    finally:
        t.stop()


def test_wrong_token_is_rejected(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pip = FakePip()
    monkeypatch.setattr("service.transport.wifi.PIP_TCP_PORT", pip.port)
    got: list[int] = []
    t = WifiTransport(lambda: (["127.0.0.1"], b"\xff" * 32), on_frame=lambda f: got.append(f.type))
    t.start()
    try:
        assert _wait(lambda: len(pip.authed) >= 1)
        assert pip.authed[0] is False
        time.sleep(0.3)
        assert FrameType.HEARTBEAT not in got
    finally:
        t.stop()


def test_auto_transport_falls_back_to_wifi_without_usb(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pip = FakePip()
    monkeypatch.setattr("service.transport.wifi.PIP_TCP_PORT", pip.port)
    monkeypatch.setattr("service.transport.auto.find_board_port", lambda: None)
    got: list[int] = []
    t = AutoTransport(None, lambda: (["127.0.0.1"], TOKEN), on_frame=lambda f: got.append(f.type))
    t.start()
    try:
        assert _wait(lambda: FrameType.HEARTBEAT in got)
        assert t.kind == "WIFI"
    finally:
        t.stop()
    unpaired = AutoTransport(None, lambda: ([], None))
    with pytest.raises(OSError):
        unpaired._open()


def make_image(version: str = "1.2.3", project: str = "pip_firmware", size: int = 9000) -> bytes:
    b = bytearray(size)
    b[0] = 0xE9
    struct.pack_into("<I", b, 0x20, 0xABCD5432)
    for off, text in ((16, version), (48, project), (80, "12:00:00"), (96, "Nov 24 2026"), (112, "v5.5.5")):
        b[0x20 + off: 0x20 + off + len(text)] = text.encode()
    for i in range(300, size):
        b[i] = i % 251
    return bytes(b)


def test_image_info_accepts_only_pip_images() -> None:
    info = image_info(make_image())
    assert info["version"] == "1.2.3" and info["project"] == "pip_firmware" and info["size"] == 9000
    with pytest.raises(ValueError, match="not PIP"):
        image_info(make_image(project="other_app"))
    with pytest.raises(ValueError):
        image_info(b"\x00" * 5000)


class FakeLink:
    def __init__(self) -> None:
        self.linked = True
        self.transport_kind = "USB_HARDWARE"
        self.telemetry: dict[str, Any] = {"boot_id": 1}
        self.frames: list[tuple[int, bytes]] = []
        self.events: list[dict[str, Any]] = []

    async def request(self, ftype: int, payload: bytes = b"", timeout: float = 5.0) -> int:
        self.frames.append((ftype, payload))
        if ftype == FrameType.OTA_END:  # PIP reboots, then comes back
            async def bounce() -> None:
                await asyncio.sleep(0.2)
                self.telemetry = {"boot_id": 2, "fw_ver": "1.2.3", "ota": {"slot": "ota_1"}}
            asyncio.ensure_future(bounce())
        return AckStatus.OK

    async def diagnostics(self, timeout: float = 3.0) -> dict[str, Any]:
        return self.telemetry

    def notify(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append(payload)


def test_ota_streams_whole_image_in_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    img = make_image()
    link = FakeLink()
    up = FirmwareUpdater(link, tmp_path, tmp_path / "none.bin")  # type: ignore[arg-type]
    up.save_upload(img)

    async def go() -> None:
        up.start("upload")
        assert up._task is not None
        await asyncio.wait_for(up._task, 20)

    asyncio.run(go())
    kinds = [f for f, _ in link.frames]
    assert kinds[0] == FrameType.OTA_BEGIN and kinds[-1] == FrameType.OTA_END
    size, digest = struct.unpack_from("<I", link.frames[0][1])[0], link.frames[0][1][4:36]
    assert size == len(img) and digest == hashlib.sha256(img).digest()
    data = b"".join(p[4:] for f, p in link.frames if f == FrameType.OTA_DATA)
    offsets = [struct.unpack_from("<I", p)[0] for f, p in link.frames if f == FrameType.OTA_DATA]
    assert data == img and offsets == sorted(offsets)
    assert up.status["state"] == "DONE" and "1.2.3" in up.status["message"]


def _services(tmp_path):  # type: ignore[no-untyped-def]
    from service.config import Settings
    from service.services import Services
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    return Services(s, transport=None)


def test_pairing_token_only_travels_over_usb(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = _services(tmp_path)
    sent: list[tuple[int, dict[str, Any]]] = []
    svc.link.send_json = lambda t, obj: sent.append((t, obj)) or True  # type: ignore[method-assign]
    svc._on_link_up("USB_HARDWARE")
    svc._on_link_up("WIFI")
    assert [t for t, _ in sent] == [FrameType.DEVICE_CONFIG, FrameType.DEVICE_CONFIG]
    assert len(sent[0][1]["token"]) == 64 and sent[0][1]["wake"] == {"enabled": True, "word": "hiesp"}
    assert "token" not in sent[1][1]
    assert svc.settings.link_token() == bytes.fromhex(sent[0][1]["token"])  # same secret the PC will use on Wi-Fi
    svc._on_diag({"wifi": {"ip": "192.168.1.50", "host": "pip-abcd.local", "ssid": "home"}})
    assert svc.settings.wifi_hosts() == ["192.168.1.50", "pip-abcd.local"]


def test_wake_event_and_self_test(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import numpy as np
    from fastapi.testclient import TestClient
    from service.config import Settings
    from service.main import create_app
    from service.protocol import Frame
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    app = create_app(s)
    with TestClient(app) as c:
        svc = app.state.services
        link = svc.link
        frames: list[int] = []
        link.linked = True
        link.send = lambda t, payload=b"", ack=False: frames.append(t) or True  # type: ignore[method-assign]
        svc.tts.synthesize_pcm = lambda text, voice=None, scale=None: np.zeros(3200, np.int16)  # type: ignore[method-assign]
        type(svc.tts).enabled = property(lambda self: True)  # type: ignore[assignment]
        loop = link.loop

        def fire() -> None:  # PIP reports the hit while the clip streams
            link._dispatch(Frame(FrameType.WAKE_EVENT, 0, 9, bytes([1, 0])))
        loop.call_later(0.3, fire)
        r = c.post("/api/v1/device/wake/test").json()
        assert r["detected"] is True and r["word"] == "hiesp"
        assert frames.count(FrameType.WAKE_TEST) >= 3  # clip streamed in 100 ms frames (heartbeats interleave)
        link.linked = False  # offline: the choice is saved and sent to PIP on the next link-up
        w = c.put("/api/v1/device/wake", json={"enabled": False, "word": "jarvis"}).json()
        assert w["enabled"] is False and w["word"] == "jarvis" and svc.wake_settings()["word"] == "jarvis"
