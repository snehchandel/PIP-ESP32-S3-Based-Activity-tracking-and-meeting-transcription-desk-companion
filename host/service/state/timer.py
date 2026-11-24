"""Host-authoritative countdown (monotonic clock), mirroring firmware local_timer semantics."""
from __future__ import annotations

import time
from typing import Callable

Clock = Callable[[], float]


class HostTimer:
    def __init__(self, clock: Clock = time.monotonic) -> None:
        self.clock = clock
        self.state = "STOPPED"
        self.total_ms = 0
        self._remaining_ms = 0
        self._since = 0.0

    def load(self, remaining_ms: int, total_ms: int | None = None, state: str = "PAUSED") -> None:
        self._remaining_ms = max(0, int(remaining_ms))
        self.total_ms = int(total_ms if total_ms is not None else remaining_ms)
        self.state = state if self._remaining_ms > 0 else "STOPPED"
        self._since = self.clock()

    @property
    def remaining_ms(self) -> int:
        if self.state != "RUNNING":
            return self._remaining_ms
        return max(0, self._remaining_ms - int((self.clock() - self._since) * 1000))

    @property
    def started(self) -> bool:
        return self.state == "RUNNING" or self._remaining_ms < self.total_ms

    def start(self) -> bool:
        if self._remaining_ms <= 0 or self.state == "RUNNING":
            return False
        self._since = self.clock()
        self.state = "RUNNING"
        return True

    def pause(self) -> bool:
        if self.state != "RUNNING":
            return False
        self._remaining_ms = self.remaining_ms
        self.state = "PAUSED" if self._remaining_ms > 0 else "STOPPED"
        return True

    def stop(self) -> None:
        self._remaining_ms = self.remaining_ms
        self.state = "STOPPED"

    def expired(self) -> bool:
        return self.state == "RUNNING" and self.remaining_ms == 0
