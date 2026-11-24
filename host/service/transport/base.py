"""Unified device transport: a reader thread feeds the protocol parser and dispatches frames.

Thread-based so the same code serves CLI tools (capture/HIL) and the asyncio host service
(which bridges callbacks onto its event loop)."""
from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable

from ..protocol import FLAG_ACK_REQUIRED, Frame, FrameParser, encode

log = logging.getLogger("pip.transport")
FrameCallback = Callable[[Frame], None]


class DeviceTransport(ABC):
    kind = "DISCONNECTED"

    def __init__(self, on_frame: FrameCallback | None = None) -> None:
        self.on_frame = on_frame
        self.parser = FrameParser()
        self._seq = 1
        self._tx_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.connected = False
        self.last_rx = 0.0
        self.disconnects = 0

    # -- subclass hooks ---------------------------------------------------------------
    @abstractmethod
    def _open(self) -> None: ...

    @abstractmethod
    def _close(self) -> None: ...

    @abstractmethod
    def _read(self) -> bytes: ...

    @abstractmethod
    def _write(self, data: bytes) -> None: ...

    # -- public API -------------------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"pip-{self.kind}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._safe_close()

    def send(self, ftype: int, payload: bytes = b"", ack: bool = False) -> int:
        with self._tx_lock:
            seq = self._seq
            self._seq = (self._seq + 1) & 0xFFFF or 1
            data = encode(ftype, payload, seq, FLAG_ACK_REQUIRED if ack else 0)
            if not self.connected:
                raise ConnectionError("device not connected")
            try:
                self._write(data)
            except OSError as e:
                self._mark_down(e)
                raise ConnectionError(str(e)) from e
            return seq

    # -- internals ----------------------------------------------------------------------
    def _safe_close(self) -> None:
        try:
            self._close()
        except OSError:
            pass
        self.connected = False

    def _mark_down(self, err: Exception) -> None:
        if self.connected:
            log.info("%s link down: %s", self.kind, err)
            self.disconnects += 1
        self._safe_close()

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.connected:
                try:
                    self._open()
                    self.parser = FrameParser()
                    self.connected = True
                    log.info("%s link up", self.kind)
                except OSError as e:
                    log.debug("%s open failed: %s", self.kind, e)
                    self._stop.wait(1.0)
                    continue
            try:
                data = self._read()
            except OSError as e:
                self._mark_down(e)
                continue
            if not data:
                continue
            self.last_rx = time.monotonic()
            for frame in self.parser.feed(data):
                if self.on_frame:
                    try:
                        self.on_frame(frame)
                    except Exception:  # never let a handler kill the reader thread
                        log.exception("frame handler failed")
