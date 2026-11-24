"""Live fixtures: a real sim_rlcd process + the real host service on ephemeral ports."""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterator

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host"))
SIM = ROOT / "build" / "host" / ("sim_rlcd.exe" if sys.platform == "win32" else "sim_rlcd")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class SimProcess:
    def __init__(self, port: int) -> None:
        self.port = port
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self, offline_events: str | None = None) -> None:
        args = [str(SIM), "--tcp", f"127.0.0.1:{self.port}"]
        if offline_events:
            args += ["--offline-events", offline_events]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("sim_rlcd did not start")

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=5)
            self.proc = None


@pytest.fixture()
def sim() -> Iterator[SimProcess]:
    if not SIM.exists():
        pytest.skip("sim_rlcd not built (cmake --build build/host)")
    s = SimProcess(free_port())
    yield s
    s.stop()


class LiveService:
    def __init__(self, sim_port: int, db: str) -> None:
        import uvicorn

        from service.config import Settings
        from service.main import create_app

        self.port = free_port()
        settings = Settings(pip_db_path=db, pip_transport="sim", pip_sim_addr=f"127.0.0.1:{sim_port}",
                            moonshot_api_key="", pip_host_port=self.port)
        cfg = uvicorn.Config(create_app(settings), host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.base = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.base, timeout=10)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if self.http.get("/api/v1/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError("service did not start")

    def wait(self, pred, timeout: float = 8.0, step: float = 0.1):  # type: ignore[no-untyped-def]
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = pred()
            if last:
                return last
            time.sleep(step)
        raise AssertionError(f"condition not met within {timeout}s (last={last!r})")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.http.close()


@pytest.fixture()
def service(sim: SimProcess, tmp_path: Path) -> Iterator[LiveService]:
    sim.start()
    svc = LiveService(sim.port, str(tmp_path / "pip_test.db"))
    svc.start()
    yield svc
    svc.stop()
