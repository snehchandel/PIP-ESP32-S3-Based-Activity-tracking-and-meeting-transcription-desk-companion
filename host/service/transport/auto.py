"""Auto transport: the USB cable always wins when PIP is plugged in; Wi-Fi only when it is not.

- While PIP's USB port is enumerated, a transient serial error (Windows sometimes reports ClearCommError for a
  moment, e.g. while PIP's radio starts) is answered by re-opening USB, not by hopping to Wi-Fi. Wi-Fi is used
  only if the cable is unplugged, or the port stays unusable for USB_GRACE_S (another program holds it).
- While on Wi-Fi, USB is probed every USB_PROBE_S; when it can be opened the link switches over *in place*
  (no disconnect seen by the app), and the Wi-Fi socket is closed.
- Away link (ADR-035): when PIP is on another network it dials in through the AwayListener. A waiting away
  connection is taken before LAN Wi-Fi is tried, and a newer one replaces the current one in place (PIP redials
  after it found the old link dead)."""
from __future__ import annotations

import logging
import socket
import time

import serial

from ..protocol import FrameParser
from .away import AwayListener, SealedStream
from .base import DeviceTransport, FrameCallback
from .usb_serial import find_board_port, open_serial
from .wifi import WifiTarget, open_wifi

log = logging.getLogger("pip.transport")
USB_PROBE_S = 5.0
USB_GRACE_S = 10.0


class AutoTransport(DeviceTransport):
    def __init__(self, serial_port: str | None, wifi_target: WifiTarget | None,
                 on_frame: FrameCallback | None = None, away: AwayListener | None = None) -> None:
        super().__init__(on_frame)
        self.serial_port = serial_port
        self.wifi_target = wifi_target
        self.away = away
        self._ser: serial.Serial | None = None
        self._sock: socket.socket | None = None
        self._away: SealedStream | None = None
        self._active = "DISCONNECTED"
        self._probe_at = 0.0
        self._usb_fail_since: float | None = None

    @property  # type: ignore[override]
    def kind(self) -> str:
        return self._active

    def _port(self) -> str | None:
        return self.serial_port or find_board_port()

    def _open(self) -> None:
        port = self._port()
        if port:
            try:
                self._ser = open_serial(port)
                self._active = "USB_HARDWARE"
                self._usb_fail_since = None
                return
            except (OSError, serial.SerialException) as e:
                now = time.monotonic()
                self._usb_fail_since = self._usb_fail_since or now
                if now - self._usb_fail_since < USB_GRACE_S:
                    raise OSError(f"USB port busy, retrying the cable: {e}") from e
                # plugged in but unusable for a while (port held elsewhere): use Wi-Fi meanwhile
        else:
            self._usb_fail_since = None
        if self._take_away():
            return
        if self.wifi_target:
            hosts, token = self.wifi_target()
            if token and hosts:
                self._sock, _ = open_wifi(hosts, token)
                self._active = "WIFI"
                self._probe_at = time.monotonic() + USB_PROBE_S
                return
        raise OSError("PIP not found on USB and not paired/reachable on Wi-Fi")

    def _take_away(self) -> bool:
        stream = self.away.take() if self.away else None
        if stream is None:
            return False
        if self._sock:
            self._sock.close()
            self._sock = None
        if self._away:
            self._away.close()
        self._away = stream
        self._active = "WIFI_AWAY"
        self._probe_at = time.monotonic() + USB_PROBE_S
        self.parser = FrameParser()
        return True

    def _close(self) -> None:
        if self._ser:
            self._ser.close()
            self._ser = None
        if self._sock:
            self._sock.close()
            self._sock = None
        if self._away:
            self._away.close()
            self._away = None
        self._active = "DISCONNECTED"

    def _switch_to_usb(self) -> bool:
        """Called while on Wi-Fi: move to the cable without dropping the link."""
        port = self._port()
        if not port:
            return False
        try:
            ser = open_serial(port)
        except (OSError, serial.SerialException):
            return False
        if self._sock:
            self._sock.close()
            self._sock = None
        if self._away:
            self._away.close()
            self._away = None
        self._ser = ser
        self._active = "USB_HARDWARE"
        self.parser = FrameParser()
        log.info("PIP plugged in: switched from Wi-Fi to USB")
        return True

    def _read(self) -> bytes:
        if self._ser:
            try:
                return self._ser.read(4096)
            except serial.SerialException as e:
                raise OSError(str(e)) from e
        if time.monotonic() >= self._probe_at:
            self._probe_at = time.monotonic() + USB_PROBE_S
            if self._switch_to_usb():
                return b""
        if self._away or (self.away and self.away.waiting()):
            if self.away and self.away.waiting() and self._take_away():
                log.info("PIP dialed in again: switched to the new away link")
                return b""
            assert self._away is not None
            return self._away.recv()
        assert self._sock is not None
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
        elif self._away:
            self._away.send(data)
        elif self._sock:
            self._sock.sendall(data)
        else:
            raise OSError("not connected")
