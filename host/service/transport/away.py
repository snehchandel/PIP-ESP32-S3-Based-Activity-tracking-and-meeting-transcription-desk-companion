"""Away link (ADR-035): PIP dials OUT to this PC when it is on another network (office Wi-Fi, a phone hotspot).

The PC listens on AWAY_PORT; the user makes that port reachable from the internet (Tailscale Funnel or a router
port forward) and tells PIP the public address. Every connection proves the link token both ways, then each frame
travels in an AES-256-GCM record, so whatever relays the TCP stream sees neither the words nor the audio:

  PIP -> PC   AUTH_CHALLENGE  nonce_d(16) + MAC(6)
  PC  -> PIP  AUTH_RESPONSE   HMAC(token, nonce_d)(32) + nonce_p(16)
  PIP -> PC   AUTH_RESPONSE   HMAC(token, "PIP-DEV" | nonce_p | nonce_d)(32)
  K = HMAC(token, "PIP-AWAY-1" | nonce_d | nonce_p); up (PIP->PC) = HMAC(K, "up"), down (PC->PIP) = HMAC(K, "down")
  record = len(u16 LE) | AES-256-GCM(key, iv = counter(u64 LE) | 0000, aad = the 2 length bytes) | tag(16)

The device side is firmware/main/net_link.c."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import socket
import struct
import threading
import time
from collections.abc import Callable
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..protocol.frames import HDR_LEN, MAX_FRAME, Frame, FrameParser, FrameType, encode
from .wifi import auth_response

log = logging.getLogger("pip.transport")
AWAY_PORT = 18423
TAG_LEN = 16
HANDSHAKE_S = 5.0
MAX_HANDSHAKES = 4  # concurrent half-open connections (the port is on the internet)

# () -> (enabled, listen port, link token or None)
AwayConfig = Callable[[], tuple[bool, int, bytes | None]]


def _h(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def derive_keys(token: bytes, nonce_d: bytes, nonce_p: bytes) -> tuple[bytes, bytes]:
    """(up, down): up encrypts PIP -> PC, down PC -> PIP."""
    k = _h(token, b"PIP-AWAY-1" + nonce_d + nonce_p)
    return _h(k, b"up"), _h(k, b"down")


def device_proof(token: bytes, nonce_p: bytes, nonce_d: bytes) -> bytes:
    return _h(token, b"PIP-DEV" + nonce_p + nonce_d)


def _iv(ctr: int) -> bytes:
    return struct.pack("<Q", ctr) + b"\0\0\0\0"


class SealedStream:
    """Both directions of an authenticated away link: plaintext frame bytes in, GCM records on the wire."""

    def __init__(self, sock: socket.socket, tx_key: bytes, rx_key: bytes, leftover: bytes = b"",
                 peer: str = "", mac: bytes = b"") -> None:
        self.sock = sock
        self.peer = peer
        self.mac = mac
        self._tx, self._rx = AESGCM(tx_key), AESGCM(rx_key)
        self._ctr_tx = self._ctr_rx = 0
        self._buf = bytearray(leftover)
        self._lock = threading.Lock()

    def send(self, data: bytes) -> None:
        with self._lock:
            out = bytearray()
            for i in range(0, len(data), MAX_FRAME):
                chunk = data[i:i + MAX_FRAME]
                head = struct.pack("<H", len(chunk))
                out += head + self._tx.encrypt(_iv(self._ctr_tx), chunk, head)
                self._ctr_tx += 1
            self.sock.sendall(bytes(out))

    def _open(self) -> bytes:
        out = bytearray()
        while len(self._buf) >= 2:
            (n,) = struct.unpack_from("<H", self._buf)
            if n == 0 or n > MAX_FRAME:
                raise OSError("away link: malformed record")
            if len(self._buf) < 2 + n + TAG_LEN:
                break
            rec = bytes(self._buf[:2 + n + TAG_LEN])
            del self._buf[:2 + n + TAG_LEN]
            try:
                out += self._rx.decrypt(_iv(self._ctr_rx), rec[2:], rec[:2])
            except Exception as e:  # InvalidTag: tampered or out of order
                raise OSError("away link: record failed authentication") from e
            self._ctr_rx += 1
        return bytes(out)

    def recv(self) -> bytes:
        """Decrypted frame bytes ready so far (b"" on a read timeout); OSError when closed or tampered."""
        pending = self._open()
        if pending:
            return pending
        try:
            data = self.sock.recv(8192)
        except TimeoutError:
            return b""
        if not data:
            raise OSError("PIP closed the away link")
        self._buf += data
        return self._open()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _read_frame(sock: socket.socket, buf: bytearray, deadline: float) -> Frame:
    """Exactly one clear frame from the start of the stream; bytes after it stay in buf (they are sealed)."""
    while True:
        if len(buf) >= HDR_LEN:
            if buf[:2] != b"\xaa\x55":
                raise OSError("away link: bad frame during the handshake")
            (n,) = struct.unpack_from("<H", buf, 7)
            total = HDR_LEN + n + 2
            if n > 256:
                raise OSError("away link: oversized handshake frame")
            if len(buf) >= total:
                frames = FrameParser().feed(bytes(buf[:total]))
                del buf[:total]
                if len(frames) != 1:
                    raise OSError("away link: corrupt handshake frame")
                return frames[0]
        left = deadline - time.monotonic()
        if left <= 0:
            raise OSError("away link: handshake timed out")
        sock.settimeout(left)
        try:
            data = sock.recv(512)
        except TimeoutError as e:
            raise OSError("away link: handshake timed out") from e
        if not data:
            raise OSError("away link: closed during the handshake")
        buf += data


def accept_handshake(sock: socket.socket, token: bytes, peer: str = "") -> SealedStream:
    """PC side of the handshake on a connection PIP dialed. Raises OSError unless PIP proves the token."""
    deadline, buf = time.monotonic() + HANDSHAKE_S, bytearray()
    hello = _read_frame(sock, buf, deadline)
    if hello.type != FrameType.AUTH_CHALLENGE or len(hello.payload) < 22:
        raise OSError("away link: no challenge")
    nonce_d, mac = hello.payload[:16], hello.payload[16:22]
    nonce_p = os.urandom(16)
    sock.sendall(encode(FrameType.AUTH_RESPONSE, auth_response(token, nonce_d) + nonce_p, 1, 0))
    proof = _read_frame(sock, buf, deadline)
    if proof.type != FrameType.AUTH_RESPONSE or len(proof.payload) != 32 or \
            not hmac.compare_digest(proof.payload, device_proof(token, nonce_p, nonce_d)):
        raise OSError("away link: the device did not prove the link token")
    up, down = derive_keys(token, nonce_d, nonce_p)
    sock.settimeout(0.05)
    return SealedStream(sock, tx_key=down, rx_key=up, leftover=bytes(buf), peer=peer, mac=mac)


class AwayListener:
    """Listens for PIP's away link while enabled; hands the newest authenticated connection to the transport."""

    def __init__(self, config: AwayConfig) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._ready: SealedStream | None = None
        self._srv: socket.socket | None = None
        self._port = 0
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(MAX_HANDSHAKES)
        self._thread: threading.Thread | None = None
        self.stats: dict[str, Any] = {"listening": False, "port": 0, "links": 0, "rejected": 0,
                                      "last_link_at": None, "last_peer": "", "error": ""}

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pip-away", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._close_srv()
        with self._lock:
            if self._ready:
                self._ready.close()
                self._ready = None

    def take(self) -> SealedStream | None:
        with self._lock:
            s, self._ready = self._ready, None
            return s

    def waiting(self) -> bool:
        return self._ready is not None

    def status(self) -> dict[str, Any]:
        return dict(self.stats)

    def _close_srv(self) -> None:
        if self._srv:
            self._srv.close()
            self._srv = None
        self.stats.update(listening=False)

    def _run(self) -> None:
        while not self._stop.is_set():
            enabled, port, _ = self.config()
            if not enabled or port != self._port:
                self._close_srv()
                self._port = 0
            if enabled and self._srv is None:
                try:
                    srv = socket.create_server(("0.0.0.0", port), reuse_port=False)
                    srv.settimeout(1.0)
                    self._srv, self._port = srv, port
                    self.stats.update(listening=True, port=port, error="")
                    log.info("away link: listening on port %d", port)
                except OSError as e:
                    self.stats.update(listening=False, port=port, error=f"cannot listen on port {port}: {e}")
                    self._stop.wait(5.0)
                    continue
            if self._srv is None:
                self._stop.wait(2.0)
                continue
            try:
                conn, addr = self._srv.accept()
            except TimeoutError:
                continue
            except OSError:
                self._close_srv()
                continue
            if not self._slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._handshake, args=(conn, f"{addr[0]}:{addr[1]}"), daemon=True).start()

    def _handshake(self, conn: socket.socket, peer: str) -> None:
        try:
            _, _, token = self.config()
            if not token:
                raise OSError("this PC is not paired with PIP yet")
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            stream = accept_handshake(conn, token, peer)
        except OSError as e:
            self.stats["rejected"] += 1
            log.info("away link: rejected %s (%s)", peer, e)
            conn.close()
            return
        finally:
            self._slots.release()
        log.info("away link: PIP connected from %s", peer)
        self.stats.update(links=self.stats["links"] + 1, last_link_at=time.time(), last_peer=peer)
        with self._lock:
            old, self._ready = self._ready, stream
        if old:
            old.close()
