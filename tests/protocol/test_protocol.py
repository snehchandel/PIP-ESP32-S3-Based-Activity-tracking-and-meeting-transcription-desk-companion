"""Cross-language protocol checks: Python codec == C codec (golden vectors + live sim frames)."""
from __future__ import annotations

import json
import random
import struct

from service.protocol import (Ack, BtnEvent, FramebufferAssembler, FrameParser, FrameType, Heartbeat,
                              crc16_ccitt_false, encode)
from service.protocol.frames import FB_CHUNK_BYTES, MAX_PAYLOAD


def test_crc_vectors_match_c() -> None:
    assert crc16_ccitt_false(b"123456789") == 0x29B1  # same vector as tests/unit/c/test_protocol.c
    assert crc16_ccitt_false(b"") == 0xFFFF


def test_golden_frame_matches_c_layout() -> None:
    f = encode(FrameType.HEARTBEAT, b"hi", seq=0x1234, flags=0x01)
    assert f[:11] == bytes([0xAA, 0x55, 0x01, 0x00, 0x01, 0x34, 0x12, 0x02, 0x00]) + b"hi"
    assert struct.unpack("<H", f[11:])[0] == crc16_ccitt_false(f[2:11])


def test_struct_sizes_match_c() -> None:
    assert len(Heartbeat(1, 1, 0, 0, 0, 0).pack()) == 16
    assert len(BtnEvent(1, 0, 1, 0, 0).pack()) == 12
    assert len(Ack(1, 0).pack()) == 6


def test_resync_after_garbage_and_corruption() -> None:
    good = encode(FrameType.ACK, Ack(9, 0).pack(), seq=5)
    bad = bytearray(good)
    bad[10] ^= 0xFF
    p = FrameParser()
    frames = p.feed(b"\x00\xAA\x13" + bytes(bad) + good)
    assert [f.seq for f in frames] == [5]
    assert p.crc_errors == 1


def test_oversize_len_rejected() -> None:
    p = FrameParser()
    hdr = bytes([0xAA, 0x55, 0x01, 0x10, 0x00, 0x00, 0x00]) + struct.pack("<H", MAX_PAYLOAD + 1)
    assert p.feed(hdr) == [] and p.frame_errors >= 1
    assert len(p.feed(encode(0, b"x"))) == 1


def test_byte_by_byte_streaming() -> None:
    payload = json.dumps({"rev": 1, "ui_state": "RUNNING"}).encode()
    data = encode(FrameType.UI_UPDATE, payload, seq=77, flags=1) * 3
    p = FrameParser()
    out = []
    for b in data:
        out += p.feed(bytes([b]))
    assert len(out) == 3 and all(f.payload == payload and f.ack_required for f in out)


def test_framebuffer_chunks_reassemble() -> None:
    fb = bytes(random.Random(1).randrange(256) for _ in range(15000))
    asm = FramebufferAssembler()
    res = None
    for idx in (2, 0, 3, 1):  # any order
        off = idx * FB_CHUNK_BYTES
        res = asm.add(struct.pack("<BBH", idx, 4, off) + fb[off: off + FB_CHUNK_BYTES])
    assert res == fb


def test_live_sim_speaks_same_protocol(sim) -> None:  # type: ignore[no-untyped-def]
    """Frames produced by the C simulator parse with the Python codec (and vice versa)."""
    import time

    from service.transport import SimTcpTransport
    from service.transport.client import DeviceClient
    sim.start()
    c = DeviceClient(SimTcpTransport(f"127.0.0.1:{sim.port}"))
    c.t.start()
    try:
        assert c.wait_connected(5)
        c.heartbeat()
        diag = c.diag()
        assert diag and diag["proto_ver"] == 1 and diag["is_sim"] is True
        seq = c.send_json(FrameType.UI_UPDATE, {"rev": 3, "ui_state": "PAUSED", "step_id": "s1",
                                                "step_title": "Draft", "remaining_ms": 60000, "timer_state": "PAUSED"})
        ack = c.wait_for(FrameType.ACK, 3)
        assert ack is not None and Ack.unpack(ack.payload).ref_seq == seq
        time.sleep(0.2)
        fb = c.framebuffer()
        assert fb is not None and len(fb) == 15000 and c.t.parser.crc_errors == 0
    finally:
        c.t.stop()


def test_idle_resync_recovers_swallowed_frame() -> None:
    p = FrameParser()
    fake = bytes([0xAA, 0x55, 0x01, 0x10, 0x00, 0x00, 0x00]) + struct.pack("<H", 4000)
    good = encode(FrameType.ACK, Ack(3, 0).pack(), seq=42)
    assert p.feed(fake + good) == []  # swallowed by the bogus LEN
    assert [f.seq for f in p.idle()] == [42]
    assert p.buf == bytearray()
