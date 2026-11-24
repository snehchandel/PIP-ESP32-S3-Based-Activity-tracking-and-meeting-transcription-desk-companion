"""Fixed little-endian payload structs for protocol v1 (mirror of pip_protocol.h)."""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .frames import FB_BYTES, FB_CHUNK_BYTES, FB_CHUNKS


@dataclass
class Heartbeat:
    proto_ver: int
    link_mode: int
    flags: int
    uptime_s: int
    utc_epoch_s: int
    state_rev: int
    FMT = "<BBHIII"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, self.proto_ver, self.link_mode, self.flags, self.uptime_s,
                           self.utc_epoch_s, self.state_rev)

    @classmethod
    def unpack(cls, b: bytes) -> Heartbeat:
        return cls(*struct.unpack(cls.FMT, b))


@dataclass
class BtnEvent:
    event_seq: int
    btn_id: int    # 0 KEY, 1 BOOT
    gesture: int   # 1 SHORT 2 DOUBLE 3 HOLD_START 4 HOLD_END 5 RESCUE
    flags: int     # (reserved field) bit0 = PTT watchdog timeout
    ts_ms: int
    FMT = "<IBBHI"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, self.event_seq, self.btn_id, self.gesture, self.flags, self.ts_ms)

    @classmethod
    def unpack(cls, b: bytes) -> BtnEvent:
        return cls(*struct.unpack(cls.FMT, b))


@dataclass
class AudioStart:
    stream_id: int
    sample_rate_hz: int
    channels: int
    bits_per_sample: int
    max_sec: int
    activity: int = 0  # former reserved u16: 0 brain dump, 1 calendar, 2 focus, 3 alarms
    FMT = "<IHBBHH"

    @classmethod
    def unpack(cls, b: bytes) -> AudioStart:
        s, r, c, bps, mx, act = struct.unpack(cls.FMT, b)
        return cls(s, r, c, bps, mx, act)


@dataclass
class AudioEnd:
    stream_id: int
    reason: int
    truncated: int
    total_samples: int
    FMT = "<IBBHI"

    @classmethod
    def unpack(cls, b: bytes) -> AudioEnd:
        s, r, t, _, n = struct.unpack(cls.FMT, b)
        return cls(s, r, t, n)


def unpack_audio_data(b: bytes) -> tuple[int, int, bytes]:
    stream_id, chunk_seq = struct.unpack_from("<IH", b)
    return stream_id, chunk_seq, b[6:]


@dataclass
class Ack:
    ref_seq: int
    status: int
    detail: int = 0
    FMT = "<HBBH"

    def pack(self) -> bytes:
        return struct.pack(self.FMT, self.ref_seq, self.status, self.detail, 0)

    @classmethod
    def unpack(cls, b: bytes) -> Ack:
        r, s, d, _ = struct.unpack(cls.FMT, b)
        return cls(r, s, d)


def pack_chime(chime_id: int, volume_pct: int = 70) -> bytes:
    return struct.pack("<BBBB", chime_id, volume_pct, 0, 0)


def pack_sim_input(btn_id: int, action: int, hold_ms: int = 0) -> bytes:
    """Simulator-only: action 0 short, 1 double, 2 hold(hold_ms)."""
    return struct.pack("<BBH", btn_id, action, hold_ms)


class FramebufferAssembler:
    """Collects the 4 DUMP_FB chunks ([idx][total][offset u16][3750 B]) into 15,000 bytes."""

    def __init__(self) -> None:
        self.buf = bytearray(FB_BYTES)
        self.seen: set[int] = set()

    def add(self, payload: bytes) -> bytes | None:
        if len(payload) != 4 + FB_CHUNK_BYTES:
            raise ValueError(f"bad DUMP_FB chunk length {len(payload)}")
        idx, total, offset = struct.unpack_from("<BBH", payload)
        if total != FB_CHUNKS or idx >= FB_CHUNKS or offset != idx * FB_CHUNK_BYTES:
            raise ValueError("bad DUMP_FB chunk header")
        self.buf[offset: offset + FB_CHUNK_BYTES] = payload[4:]
        self.seen.add(idx)
        if len(self.seen) == FB_CHUNKS:
            data = bytes(self.buf)
            self.seen.clear()
            return data
        return None
