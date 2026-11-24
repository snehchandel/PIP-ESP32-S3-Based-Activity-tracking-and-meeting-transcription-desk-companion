"""PIP wire protocol v1 - Python mirror of firmware/components/usb_protocol (byte-for-byte)."""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

SYNC = b"\xAA\x55"
PROTO_VER = 0x01
HDR_LEN = 9
MAX_PAYLOAD = 4096
MAX_FRAME = HDR_LEN + MAX_PAYLOAD + 2

FLAG_ACK_REQUIRED = 0x01
FLAG_COMPRESSED = 0x02
FLAG_IS_SIMULATOR = 0x04

FB_CHUNKS = 4
FB_CHUNK_BYTES = 3750
FB_BYTES = 15000


class FrameType(IntEnum):
    HEARTBEAT = 0x00
    AUDIO_START = 0x01
    AUDIO_DATA = 0x02
    AUDIO_END = 0x03
    BTN_EVENT = 0x04
    OFFLINE_EVENTS = 0x05
    AUTH_CHALLENGE = 0x06
    WAKE_EVENT = 0x07
    UI_UPDATE = 0x10
    AUDIO_START_OUT = 0x11
    AUDIO_DATA_OUT = 0x12
    AUDIO_END_OUT = 0x13
    PLAY_CHIME = 0x14
    ALARM_TRIGGER = 0x15
    CALENDAR_SYNC = 0x16
    DEVICE_CONFIG = 0x17
    AUTH_RESPONSE = 0x18
    OTA_BEGIN = 0x20
    OTA_DATA = 0x21
    OTA_END = 0x22
    WAKE_TEST = 0x23
    SIM_INPUT = 0xE0
    ACK = 0xF0
    DIAG_REPORT = 0xFD
    DUMP_FB = 0xFE


class AckStatus(IntEnum):
    OK = 0
    BAD_VER = 1
    BAD_LEN = 2
    BAD_JSON = 3
    BUSY = 4
    UNKNOWN_TYPE = 5
    FAILED = 6
    DENIED = 7


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True)
class Frame:
    type: int
    flags: int
    seq: int
    payload: bytes

    @property
    def ack_required(self) -> bool:
        return bool(self.flags & FLAG_ACK_REQUIRED)


def encode(ftype: int, payload: bytes = b"", seq: int = 0, flags: int = 0) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload {len(payload)} > {MAX_PAYLOAD}")
    body = struct.pack("<BBBHH", PROTO_VER, ftype, flags, seq & 0xFFFF, len(payload)) + payload
    return SYNC + body + struct.pack("<H", crc16_ccitt_false(body))


class FrameParser:
    """Streaming parser with the same resync rule as the C parser: on bad sync, version,
    LEN > 4096 or CRC mismatch, drop one byte and rescan. Memory is bounded by MAX_FRAME."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.crc_errors = 0
        self.frame_errors = 0
        self.frames_ok = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buf += data
        out: list[Frame] = []
        while True:
            r = self._try()
            if r is None:
                break
            if isinstance(r, Frame):
                out.append(r)
        if len(self.buf) > MAX_FRAME:
            del self.buf[: len(self.buf) - MAX_FRAME]
        return out

    def idle(self) -> list[Frame]:
        """Line went idle with a partial frame buffered: it can never complete. Drop it byte by
        byte and rescan, recovering any complete frame it swallowed (mirror of pip_parser_idle)."""
        out: list[Frame] = []
        while self.buf:
            self.frame_errors += 1
            del self.buf[0]
            while True:
                r = self._try()
                if r is None:
                    break
                if isinstance(r, Frame):
                    out.append(r)
        return out

    def _drop(self) -> bool:
        del self.buf[0]
        return False

    def _try(self) -> Frame | bool | None:
        b = self.buf
        if not b:
            return None
        if b[0] != 0xAA:
            return self._drop()
        if len(b) >= 2 and b[1] != 0x55:
            self.frame_errors += 1
            return self._drop()
        if len(b) < HDR_LEN:
            return None
        ver, ftype, flags, seq, length = struct.unpack_from("<BBBHH", b, 2)
        if ver != PROTO_VER or length > MAX_PAYLOAD:
            self.frame_errors += 1
            return self._drop()
        total = HDR_LEN + length + 2
        if len(b) < total:
            return None
        (want,) = struct.unpack_from("<H", b, HDR_LEN + length)
        if crc16_ccitt_false(bytes(b[2: HDR_LEN + length])) != want:
            self.crc_errors += 1
            return self._drop()
        frame = Frame(ftype, flags, seq, bytes(b[HDR_LEN: HDR_LEN + length]))
        del b[:total]
        self.frames_ok += 1
        return frame
