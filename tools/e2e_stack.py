"""Launches an isolated live stack for E2E runs: sim_rlcd (TCP) + host service (uvicorn) on free ports."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.support.fake_kimi import FakeKimi  # noqa: E402
from tests.support.fake_ollama import FakeOllama

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "build/host" / ("sim_rlcd.exe" if sys.platform == "win32" else "sim_rlcd")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Stack:
    def __init__(self) -> None:
        self.sim_port = free_port()
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.tmp = tempfile.mkdtemp(prefix="pip_e2e_")
        self.sim: subprocess.Popen[bytes] | None = None
        self.svc: subprocess.Popen[bytes] | None = None
        self.http = httpx.Client(base_url=self.base, timeout=10)
        self.kimi = FakeKimi()  # test double for the Moonshot API (tests/support/fake_kimi.py)
        self.ollama = FakeOllama()  # test double for the local AI (tests/support/fake_ollama.py)

    def start_sim(self, offline_events: str | None = None) -> None:
        args = [str(SIM), "--tcp", f"127.0.0.1:{self.sim_port}"]
        if offline_events:
            args += ["--offline-events", offline_events]
        self.sim = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)

    def stop_sim(self) -> None:
        if self.sim:
            self.sim.terminate()
            self.sim.wait(5)
            self.sim = None

    def start(self) -> None:
        self.start_sim()
        env = dict(os.environ, PIP_DB_PATH=str(Path(self.tmp) / "e2e.db"), PIP_TRANSPORT="sim",
                   PIP_SIM_ADDR=f"127.0.0.1:{self.sim_port}", PIP_HOST_PORT=str(self.port), MOONSHOT_API_KEY="test-key",
                   MOONSHOT_BASE_URL=self.kimi.base_url, PIP_LOCAL_AI_URL=self.ollama.url, PIP_WEATHER="0",
                   PIP_USE_KEYRING="0", PIP_STT_PRELOAD="0",
                   PIP_PREFS_PATH=str(Path(self.tmp) / "prefs.json"),
                   PYTHONPATH=str(ROOT / "host"))
        self.svc = subprocess.Popen([sys.executable, "-m", "service.main"], cwd=ROOT / "host", env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.wait(lambda: self.health().get("link_state") == "TETHERED", 15, "service tethered to simulator")
        except AssertionError:
            self.stop()  # never leak a simulator or service process on a failed start
            raise

    def health(self) -> dict:  # type: ignore[type-arg]
        try:
            return self.http.get("/api/v1/health").json()  # type: ignore[no-any-return]
        except httpx.HTTPError:
            return {}

    def state(self) -> dict:  # type: ignore[type-arg]
        return self.http.get("/api/v1/state").json()  # type: ignore[no-any-return]

    def wait(self, pred, timeout: float, what: str):  # type: ignore[no-untyped-def]
        end = time.time() + timeout
        while time.time() < end:
            try:
                r = pred()
                if r:
                    return r
            except (httpx.HTTPError, KeyError, TypeError):
                pass
            time.sleep(0.15)
        raise AssertionError(f"timeout waiting for: {what}")

    def stop(self) -> None:
        self.http.close()
        if self.svc:
            self.svc.terminate()
            self.svc.wait(10)
        self.stop_sim()
