"""Wi-Fi transport: TCP to PIP on the home network (port 18422) with the HMAC challenge handshake.

PIP opens every connection with AUTH_CHALLENGE (16-byte nonce + 6-byte MAC); we answer
AUTH_RESPONSE = HMAC-SHA256(link token, nonce). The token was given to PIP over USB, so only this PC can
drive it over the LAN. After the handshake the stream carries the same protocol v1 frames as USB."""
from __future__ import annotations

import hashlib
import hmac
import socket
import time
from collections.abc import Callable

from ..protocol import Frame, FrameParser, FrameType, encode
from .base import DeviceTransport, FrameCallback

PIP_TCP_PORT = 18422

# () -> (candidate hosts to try in order, link token or None)
WifiTarget = Callable[[], tuple[list[str], bytes | None]]


def auth_response(token: bytes, nonce: bytes) -> bytes:
    return hmac.new(token, nonce, hashlib.sha256).digest()


def open_wifi(hosts: list[str], token: bytes, timeout: float = 3.0) -> tuple[socket.socket, bytes]:
    """Connect to the first reachable host and authenticate. Returns (socket, device MAC)."""
    last: Exception = OSError("no Wi-Fi address known for PIP")
    for host in hosts:
        try:
            s = socket.create_connection((host, PIP_TCP_PORT), timeout=timeout)
        except OSError as e:
            last = e
            continue
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.settimeout(0.2)
            parser, deadline = FrameParser(), time.monotonic() + timeout
            challenge: Frame | None = None
            while challenge is None and time.monotonic() < deadline:
                try:
                    data = s.recv(256)
                except TimeoutError:
                    continue
                if not data:
                    raise OSError("PIP closed the connection during the handshake")
                challenge = next((f for f in parser.feed(data) if f.type == FrameType.AUTH_CHALLENGE), None)
            if challenge is None or len(challenge.payload) < 16:
                raise OSError("no authentication challenge from PIP")
            s.sendall(encode(FrameType.AUTH_RESPONSE, auth_response(token, challenge.payload[:16]), 1, 0))
            s.settimeout(0.05)
            return s, challenge.payload[16:22]
        except OSError as e:
            s.close()
            last = e
    raise last


class WifiTransport(DeviceTransport):
    kind = "WIFI"

    def __init__(self, target: WifiTarget, on_frame: FrameCallback | None = None) -> None:
        super().__init__(on_frame)
        self.target = target
        self._sock: socket.socket | None = None

    def _open(self) -> None:
        hosts, token = self.target()
        if not token or not hosts:
            raise OSError("PIP is not paired for Wi-Fi yet")
        self._sock, _ = open_wifi(hosts, token)

    def _close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def _read(self) -> bytes:
        assert self._sock is not None
        try:
            data = self._sock.recv(8192)
        except TimeoutError:
            return b""
        if not data:
            raise OSError("PIP closed the Wi-Fi connection")
        return data

    def _write(self, data: bytes) -> None:
        assert self._sock is not None
        self._sock.sendall(data)
