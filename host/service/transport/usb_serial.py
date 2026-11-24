"""USB Serial/JTAG transport to the physical board (VID 0x303A / PID 0x1001 auto-detect)."""
from __future__ import annotations

import os

import serial
from serial.tools import list_ports

from .base import DeviceTransport, FrameCallback

ESPRESSIF_VID = 0x303A
USB_JTAG_PID = 0x1001


def find_board_port() -> str | None:
    """Only ever returns a port that is verified by VID/PID, or the explicit PIP_SERIAL_PORT."""
    explicit = os.environ.get("PIP_SERIAL_PORT")
    if explicit:
        return explicit
    for p in list_ports.comports():
        if p.vid == ESPRESSIF_VID and p.pid == USB_JTAG_PID:
            return p.device
    return None


def open_serial(port: str) -> serial.Serial:
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = 115200  # ignored by USB-CDC, required by the API
    ser.timeout = 0.05
    ser.write_timeout = 1.0
    # Keep DTR/RTS de-asserted: toggling them resets the ESP32-S3 via USB-JTAG.
    ser.dtr = False
    ser.rts = False
    ser.open()
    return ser


class UsbSerialTransport(DeviceTransport):
    kind = "USB_HARDWARE"

    def __init__(self, port: str | None = None, on_frame: FrameCallback | None = None) -> None:
        super().__init__(on_frame)
        self.port = port
        self._ser: serial.Serial | None = None

    def _open(self) -> None:
        port = self.port or find_board_port()
        if not port:
            raise OSError("no ESP32-S3 USB Serial/JTAG device found")
        self._ser = open_serial(port)

    def _close(self) -> None:
        if self._ser:
            self._ser.close()
            self._ser = None

    def _read(self) -> bytes:
        assert self._ser is not None
        try:
            return self._ser.read(4096)
        except serial.SerialException as e:
            raise OSError(str(e)) from e

    def _write(self, data: bytes) -> None:
        assert self._ser is not None
        try:
            self._ser.write(data)
        except serial.SerialException as e:
            raise OSError(str(e)) from e
