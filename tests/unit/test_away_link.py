"""Away link (ADR-035): PIP on another network dials the PC; mutual token proof, AES-GCM records both ways,
AutoTransport prefers the cable, takes the away link before LAN Wi-Fi and swaps to a newer one in place."""
from __future__ import annotations

import os
import socket
import struct
import threading
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from service.protocol import FrameParser, FrameType, encode
from service.transport import AutoTransport, AwayListener
from service.transport.away import derive_keys, device_proof
from service.transport.wifi import auth_response

TOKEN = bytes(range(32))
HB = struct.pack("<BBHIII", 1, 1, 0, 5, 0, 1)


def _iv(n: int) -> bytes:
    return struct.pack("<Q", n) + b"\0\0\0\0"


class FakeAwayPip:
    """What net_link.c does on the board: dial, challenge, verify the PC, prove the token, then sealed frames."""

    def __init__(self, port: int, token: bytes = TOKEN, tamper: bool = False) -> None:
        self.s = socket.create_connection(("127.0.0.1", port), timeout=3)
        self.token, self.tamper = token, tamper
        self.got: list[int] = []
        self.pc_ok: bool | None = None
        self.closed = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        nonce_d = os.urandom(16)
        self.s.sendall(encode(FrameType.AUTH_CHALLENGE, nonce_d + b"\x01\x02\x03\x04\x05\x06", 0, 0))
        p, resp = FrameParser(), None
        try:
            while resp is None:
                data = self.s.recv(256)
                if not data:
                    self.pc_ok = False
                    return
                resp = next((f for f in p.feed(data) if f.type == FrameType.AUTH_RESPONSE), None)
            self.pc_ok = len(resp.payload) == 48 and resp.payload[:32] == auth_response(self.token, nonce_d)
            if not self.pc_ok:
                return
            nonce_p = resp.payload[32:]
            self.s.sendall(encode(FrameType.AUTH_RESPONSE, device_proof(self.token, nonce_p, nonce_d), 0, 0))
            up, down = derive_keys(self.token, nonce_d, nonce_p)
            self.tx, self.rx, self.ctr_tx, self.ctr_rx = AESGCM(up), AESGCM(down), 0, 0
            self.send_sealed(encode(FrameType.HEARTBEAT, HB, 2, 0))  # right behind the proof, as the board may
            buf, parser = bytearray(), FrameParser()
            while True:
                data = self.s.recv(8192)
                if not data:
                    return
                buf += data
                while len(buf) >= 2:
                    (n,) = struct.unpack_from("<H", buf)
                    if len(buf) < 2 + n + 16:
                        break
                    rec, buf = bytes(buf[:2 + n + 16]), buf[2 + n + 16:]
                    plain = self.rx.decrypt(_iv(self.ctr_rx), rec[2:], rec[:2])
                    self.ctr_rx += 1
                    self.got += [f.type for f in parser.feed(plain)]
        except OSError:
            return
        finally:
            self.closed.set()

    def send_sealed(self, frame: bytes) -> None:
        head = struct.pack("<H", len(frame))
        body = bytearray(self.tx.encrypt(_iv(self.ctr_tx), frame, head))
        if self.tamper:
            body[0] ^= 1
        self.ctr_tx += 1
        self.s.sendall(head + bytes(body))

    def close(self) -> None:
        self.s.close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait(pred: Any, s: float = 4.0) -> bool:
    end = time.monotonic() + s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def listener():  # type: ignore[no-untyped-def]
    port = _free_port()
    lst = AwayListener(lambda: (True, port, TOKEN))
    lst.start()
    assert _wait(lambda: lst.status()["listening"])
    yield lst, port
    lst.stop()


def test_keys_differ_per_direction_and_session() -> None:
    up, down = derive_keys(TOKEN, b"d" * 16, b"p" * 16)
    assert up != down and len(up) == len(down) == 32
    assert derive_keys(TOKEN, b"d" * 16, b"q" * 16)[0] != up
    assert device_proof(TOKEN, b"p" * 16, b"d" * 16) != auth_response(TOKEN, b"d" * 16)  # no reflection


def test_away_link_end_to_end(listener, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    lst, port = listener
    monkeypatch.setattr("service.transport.auto.find_board_port", lambda: None)
    got: list[int] = []
    t = AutoTransport(None, lambda: ([], TOKEN), on_frame=lambda f: got.append(f.type), away=lst)
    pip = FakeAwayPip(port)
    t.start()
    try:
        assert _wait(lambda: FrameType.HEARTBEAT in got)  # the record that arrived right behind the proof
        assert pip.pc_ok is True and t.kind == "WIFI_AWAY" and t.connected
        t.send(FrameType.DIAG_REPORT)
        t.send(FrameType.UI_UPDATE, b"{" + b'"x":"' + b"y" * 4000 + b'"}')
        assert _wait(lambda: pip.got == [FrameType.DIAG_REPORT, FrameType.UI_UPDATE])
        pip.send_sealed(encode(FrameType.HEARTBEAT, HB, 3, 0))
        assert _wait(lambda: got.count(FrameType.HEARTBEAT) == 2)
        st = lst.status()
        assert st["links"] == 1 and st["rejected"] == 0 and st["last_peer"].startswith("127.0.0.1")

        # PIP found the link dead and dialed again: the transport moves to the new connection in place
        pip2 = FakeAwayPip(port)
        assert _wait(lambda: pip2.pc_ok is True)
        assert _wait(lambda: pip.closed.is_set())
        t.send(FrameType.DIAG_REPORT)
        assert _wait(lambda: pip2.got == [FrameType.DIAG_REPORT])
        assert t.disconnects == 0 and t.kind == "WIFI_AWAY"
    finally:
        t.stop()


def test_wrong_token_never_links(listener) -> None:  # type: ignore[no-untyped-def]
    lst, port = listener
    pip = FakeAwayPip(port, token=b"\xee" * 32)
    assert _wait(lambda: pip.pc_ok is not None)
    assert pip.pc_ok is False  # the PC's answer does not match: the board would hang up
    pip.close()
    assert _wait(lambda: lst.status()["rejected"] == 1)
    assert not lst.waiting()


def test_impostor_without_token_is_rejected(listener) -> None:  # type: ignore[no-untyped-def]
    lst, port = listener
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.sendall(encode(FrameType.AUTH_CHALLENGE, os.urandom(16) + b"\0" * 6, 0, 0))
    FrameParser().feed(s.recv(256))
    s.sendall(encode(FrameType.AUTH_RESPONSE, os.urandom(32), 0, 0))  # cannot compute the proof
    assert _wait(lambda: lst.status()["rejected"] == 1)
    assert s.recv(64) == b""
    assert not lst.waiting()
    s.close()


def test_tampered_record_drops_the_link(listener, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    lst, port = listener
    monkeypatch.setattr("service.transport.auto.find_board_port", lambda: None)
    got: list[int] = []
    t = AutoTransport(None, lambda: ([], TOKEN), on_frame=lambda f: got.append(f.type), away=lst)
    pip = FakeAwayPip(port, tamper=True)
    t.start()
    try:
        assert _wait(lambda: pip.pc_ok is True)
        assert _wait(lambda: pip.closed.is_set())
        assert FrameType.HEARTBEAT not in got
    finally:
        t.stop()


def test_listener_follows_the_setting() -> None:
    port, on = _free_port(), {"v": False}
    lst = AwayListener(lambda: (on["v"], port, TOKEN))
    lst.start()
    try:
        time.sleep(0.3)
        assert not lst.status()["listening"]
        on["v"] = True
        assert _wait(lambda: lst.status()["listening"])
        on["v"] = False
        assert _wait(lambda: not lst.status()["listening"])
    finally:
        lst.stop()


def _services(tmp_path):  # type: ignore[no-untyped-def]
    from service.config import Settings
    from service.services import Services
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    return Services(s, transport=None)


def test_device_config_carries_the_away_address(tmp_path) -> None:  # type: ignore[no-untyped-def]
    svc = _services(tmp_path)
    assert svc.device_config(include_token=False)["remote"] == {"host": ""}
    svc.settings.save_prefs(away_enabled=True, away_host="my-pc.tail1234.ts.net", away_port=10000)
    assert svc.device_config(include_token=False)["remote"] == {"host": "my-pc.tail1234.ts.net", "port": 10000, "tls": True}
    svc.settings.save_prefs(away_tls=False)
    assert svc.device_config(include_token=False)["remote"]["tls"] is False
    assert svc.away_settings()["listen_port"] == 18423
    svc.settings.save_prefs(away_enabled=False)
    assert svc.device_config(include_token=False)["remote"] == {"host": ""}


def test_away_api_validates_and_saves(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient
    from service.config import Settings
    from service.main import create_app
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    with TestClient(create_app(s)) as c:
        r = c.put("/api/v1/device/away", json={"enabled": True, "host": "my-pc.tail1234.ts.net", "port": 10000})
        assert r.status_code == 409  # not paired yet
        s.link_token(create=True)
        assert c.put("/api/v1/device/away", json={"enabled": True, "host": "bad host", "port": 1}).status_code == 422
        assert c.put("/api/v1/device/away", json={"enabled": True, "host": "x.example"}).status_code == 422
        r = c.put("/api/v1/device/away", json={"enabled": True, "host": "https://my-pc.tail1234.ts.net:10000/"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] and body["host"] == "my-pc.tail1234.ts.net" and body["port"] == 10000 and body["tls"]
        assert c.get("/api/v1/device/network").json()["away"]["host"] == "my-pc.tail1234.ts.net"
        r = c.put("/api/v1/device/away", json={"enabled": False})
        assert r.status_code == 200 and r.json()["enabled"] is False
