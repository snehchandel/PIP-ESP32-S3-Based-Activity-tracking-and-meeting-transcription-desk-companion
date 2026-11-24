"""Auto transport: USB when the cable is in (fastest, also used to pair), otherwise Wi-Fi.

While on Wi-Fi it re-probes USB every few seconds and hops back to the cable as soon as PIP is plugged in;
when the cable is pulled it falls back to Wi-Fi on the next reconnect (about a second)."""
from __future__ import annotations

import socket
import time

import serial

from .base import DeviceTransport, FrameCallback
from .usb_serial import find_board_port, open_serial
from .wifi import WifiTarget, open_wifi

USB_PROBE_S = 5.0


class AutoTransport(DeviceTransport):
    def __init__(self, serial_port: str | None, wifi_target: WifiTarget | None,
                 on_frame: FrameCallback | None = None) -> None:
        super().__init__(on_frame)
        self.serial_port = serial_port
        self.wifi_target = wifi_target
        self._ser: serial.Serial | None = None
        self._sock: socket.socket | None = None
        self._active = "DISCONNECTED"
        self._probe_at = 0.0

    @property  # type: ignore[override]
    def kind(self) -> str:
        return self._active

    def _open(self) -> None:
        port = self.serial_port or find_board_port()
        if port:
            self._ser = open_serial(port)
            self._active = "USB_HARDWARE"
            return
        if self.wifi_target:
            hosts, token = self.wifi_target()
            if token and hosts:
                self._sock, _ = open_wifi(hosts, token)
                self._active = "WIFI"
                self._probe_at = time.monotonic() + USB_PROBE_S
                return
        raise OSError("PIP not found on USB and not paired/reachable on Wi-Fi")

    def _close(self) -> None:
        if self._ser:
            self._ser.close()
            self._ser = None
        if self._sock:
            self._sock.close()
            self._sock = None
        self._active = "DISCONNECTED"

    def _read(self) -> bytes:
        if self._ser:
            try:
                return self._ser.read(4096)
            except serial.SerialException as e:
                raise OSError(str(e)) from e
        assert self._sock is not None
        if time.monotonic() >= self._probe_at:
            self._probe_at = time.monotonic() + USB_PROBE_S
            if find_board_port():
                raise OSError("PIP plugged in: switching to USB")
        try:
            data = self._sock.recv(8192)
        except TimeoutError:
            return b""
        if not data:
            raise OSError("PIP closed the Wi-Fi connection")
        return data

    def _write(self, data: bytes) -> None:
        if self._ser:
            try:
                self._ser.write(data)
            except serial.SerialException as e:
                raise OSError(str(e)) from e
        elif self._sock:
            self._sock.sendall(data)
        else:
            raise OSError("not connected")
