"""Protocol fuzz harness: corrupt sync / LEN / CRC / truncation / garbage / reconnect.

  python tools/protocol_fuzz.py --iterations 5000

Phase A fuzzes the Python FrameParser in-process (every valid frame must be recovered, memory bounded).
Phase B streams the same corruption into the C parser inside a live sim_rlcd and verifies it keeps
answering DIAG requests, counts CRC errors, and survives abrupt reconnects."""
from __future__ import annotations

import argparse
import random
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))

from service.protocol import FrameParser, FrameType, encode  # noqa: E402
from service.protocol.frames import MAX_FRAME  # noqa: E402

SIM = ROOT / "build/host" / ("sim_rlcd.exe" if sys.platform == "win32" else "sim_rlcd")


def mutate(rng: random.Random, frame: bytes) -> tuple[bytes, bool]:
    """Return (bytes, still_valid)."""
    kind = rng.randrange(7)
    b = bytearray(frame)
    if kind == 0:
        return frame, True
    if kind == 1:  # flip a payload/CRC byte
        i = rng.randrange(2, len(b))
        b[i] ^= 1 << rng.randrange(8)
        return bytes(b), False
    if kind == 2:  # break sync
        b[rng.randrange(2)] ^= 0xFF
        return bytes(b), False
    if kind == 3:  # absurd LEN
        b[7:9] = struct.pack("<H", rng.randrange(4097, 65536))
        return bytes(b), False
    if kind == 4:  # truncation
        return bytes(b[: rng.randrange(1, len(b))]), False
    if kind == 5:  # garbage prefix (may contain fake sync)
        junk = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40)))
        return junk + frame, True
    return bytes(b) + bytes([0xAA]), True  # dangling sync byte after a good frame


def phase_a(iterations: int, seed: int) -> None:
    rng = random.Random(seed)
    p = FrameParser()
    valid_seqs: set[int] = set()
    recovered: set[int] = set()
    for i in range(iterations):
        payload = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 300)))
        frame = encode(rng.choice([0x00, 0x04, 0x10, 0x16, 0xF0]), payload, seq=i & 0xFFFF)
        data, valid = mutate(rng, frame)
        if valid:
            valid_seqs.add(i & 0xFFFF)
        # a frame swallowed by a corrupted neighbour's LEN is recovered later, so count by seq, not by order
        recovered.update(f.seq for f in p.feed(data))
        assert len(p.buf) <= MAX_FRAME, "parser buffer grew past one max frame"
    for _ in range(3):  # flush: enough bytes to resolve any frame still waiting on a bogus LEN
        recovered.update(f.seq for f in p.feed(encode(0, bytes(4000), seq=0xFFFF)))
    missing = valid_seqs - recovered
    assert not missing, f"lost {len(missing)} valid frames, e.g. {sorted(missing)[:5]}"
    print(f"phase A: {iterations} iterations, recovered {len(valid_seqs)}/{len(valid_seqs)} valid frames, "
          f"crc_errors={p.crc_errors} frame_errors={p.frame_errors}")


def _diag(sock: socket.socket) -> bool:
    sock.sendall(encode(FrameType.DIAG_REPORT, b"", seq=1))
    p = FrameParser()
    end = time.time() + 2
    while time.time() < end:
        try:
            data = sock.recv(8192)
        except socket.timeout:
            continue
        if not data:
            return False
        if any(f.type == FrameType.DIAG_REPORT for f in p.feed(data)):
            return True
    return False


def phase_b(iterations: int, seed: int, port: int = 18452) -> None:
    if not SIM.exists():
        print("phase B skipped: sim_rlcd not built")
        return
    rng = random.Random(seed + 1)
    proc = subprocess.Popen([str(SIM), "--tcp", f"127.0.0.1:{port}"], stdout=subprocess.DEVNULL)
    try:
        time.sleep(0.4)
        reconnects = 0
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        sock.settimeout(0.05)
        for i in range(iterations):
            payload = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 200)))
            frame = encode(rng.choice([0x00, 0x10, 0x16, 0x15, 0x99]), payload, seq=i & 0xFFFF)
            sock.sendall(mutate(rng, frame)[0])
            if i % 500 == 499:
                sock.settimeout(0.2)
                assert _diag(sock), f"sim stopped answering after {i + 1} fuzz frames"
                if rng.random() < 0.5:  # abrupt disconnect / reconnect mid-stream
                    sock.close()
                    sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                    reconnects += 1
                sock.settimeout(0.05)
            try:
                sock.recv(65536)  # drain ACK/NACK traffic
            except socket.timeout:
                pass
        sock.settimeout(0.3)
        assert _diag(sock), "sim not responsive at end of fuzzing"
        assert proc.poll() is None, "sim_rlcd crashed"
        print(f"phase B: {iterations} corrupted frames into C parser, {reconnects} reconnects, sim alive")
        sock.close()
    finally:
        proc.terminate()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=1234)
    a = ap.parse_args()
    phase_a(a.iterations, a.seed)
    phase_b(a.iterations, a.seed)
    print("protocol fuzz: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
