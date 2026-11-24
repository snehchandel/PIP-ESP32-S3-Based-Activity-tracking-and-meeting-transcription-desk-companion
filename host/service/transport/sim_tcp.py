"""TCP transport to the host-native simulator (`sim_rlcd --tcp host:port`)."""
from __future__ import annotations

import socket

from .base import DeviceTransport, FrameCallback


class SimTcpTransport(DeviceTransport):
    kind = "SIMULATOR"

    def __init__(self, addr: str = "127.0.0.1:18422", on_frame: FrameCallback | None = None) -> None:
        super().__init__(on_frame)
        host, port = addr.rsplit(":", 1)
        self.addr = (host, int(port))
        self._sock: socket.socket | None = None

    def _open(self) -> None:
        s = socket.create_connection(self.addr, timeout=1.0)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.settimeout(0.05)
        self._sock = s

    def _close(self) -> None:
        if self._sock:
            self._sock.close()
            self._sock = None

    def _read(self) -> bytes:
        assert self._sock is not None
        try:
            data = self._sock.recv(8192)
        except socket.timeout:
            return b""
        if not data:
            raise OSError("simulator closed the connection")
        return data

    def _write(self, data: bytes) -> None:
        assert self._sock is not None
        self._sock.sendall(data)
