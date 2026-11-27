"""GPU speech add-on (ADR-034): the CUDA 12 cuBLAS + cuDNN 9 DLLs faster-whisper needs for the NVIDIA GPU.

The packaged app ships without them (~2 GB unpacked). On request (Settings -> Voice, or the installer's "GPU speech"
box) PIP downloads NVIDIA's official wheels from PyPI - pinned versions, each checked against its pinned SHA-256 -
and unpacks only their DLLs into <data>/gpu/<part>/bin, where speech/stt.py looks for them. Takes effect after PIP
restarts (CTranslate2 binds CUDA once per process).
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..webclient import download_client

log = logging.getLogger("pip.gpu_pack")


@dataclass(frozen=True)
class Wheel:
    name: str  # PyPI project
    version: str
    sha256: str  # of the win_amd64 wheel file
    size: int
    part: str  # folder under nvidia/ inside the wheel (cublas, cudnn, cuda_nvrtc)


# Same versions as the development venv (requirements-gpu.txt), tested with CTranslate2 4.x.
WHEELS: tuple[Wheel, ...] = (
    Wheel("nvidia-cuda-nvrtc-cu12", "12.9.86", "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349",
          76_408_187, "cuda_nvrtc"),
    Wheel("nvidia-cublas-cu12", "12.9.2.10", "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661",
          553_162_896, "cublas"),
    Wheel("nvidia-cudnn-cu12", "9.28.1.4", "3467aafa9b260e6adf5fbbfc0e21d180133305b42032aa1160be2d3142bb8b09",
          696_300_805, "cudnn"),
)
MARKER = "pack.json"


class GpuPack:
    def __init__(self, target: Path, wheels: tuple[Wheel, ...] = WHEELS, index_url: str = "https://pypi.org/pypi",
                 client: Callable[[], httpx.Client] | None = None) -> None:
        self.target = target
        self.wheels = wheels
        self.index_url = index_url.rstrip("/")
        self._client = client or download_client
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.state = "idle"  # idle | downloading | unpacking | done | error
        self.done_bytes = 0
        self.error = ""

    @property
    def total_bytes(self) -> int:
        return sum(w.size for w in self.wheels)

    def installed(self) -> bool:
        if not (self.target / MARKER).exists():
            return False
        return all(any((self.target / w.part / "bin").glob("*.dll")) for w in self.wheels)

    def status(self) -> dict[str, Any]:
        return {"installed": self.installed(), "state": self.state, "done_mb": self.done_bytes // 1_000_000,
                "total_mb": self.total_bytes // 1_000_000, "error": self.error, "folder": str(self.target)}

    def start(self) -> bool:
        """Download + unpack in the background. False if already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self.state, self.done_bytes, self.error = "downloading", 0, ""
            self._thread = threading.Thread(target=self._run, name="pip-gpu-pack", daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def remove(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("the GPU speech pack is still downloading")
        shutil.rmtree(self.target, ignore_errors=True)
        self.state = "idle"

    # ---- worker ------------------------------------------------------------------------------------------
    def _run(self) -> None:
        tmp = self.target / "_download"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            with self._client() as client:
                files = [self._download(client, w, tmp) for w in self.wheels]
            self.state = "unpacking"
            for w, f in zip(self.wheels, files, strict=True):
                self._unpack(w, f)
            (self.target / MARKER).write_text(json.dumps({w.name: w.version for w in self.wheels}, indent=2),
                                              encoding="utf-8")
            self.state = "done"
            log.info("GPU speech pack installed in %s", self.target)
        except Exception as e:
            self.state, self.error = "error", str(e)[:200]
            log.warning("GPU speech pack failed: %s", e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _wheel_url(self, client: httpx.Client, w: Wheel) -> str:
        r = client.get(f"{self.index_url}/{w.name}/{w.version}/json")
        r.raise_for_status()
        for u in r.json().get("urls", []):
            if str(u.get("filename", "")).endswith("win_amd64.whl") and u.get("digests", {}).get("sha256") == w.sha256:
                return str(u["url"])
        raise RuntimeError(f"{w.name} {w.version}: no Windows wheel with the expected checksum")

    def _download(self, client: httpx.Client, w: Wheel, tmp: Path) -> Path:
        url = self._wheel_url(client, w)
        out = tmp / f"{w.name}-{w.version}.whl"
        digest = hashlib.sha256()
        with client.stream("GET", url) as r, out.open("wb") as f:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                digest.update(chunk)
                self.done_bytes += len(chunk)
        if digest.hexdigest() != w.sha256:
            raise RuntimeError(f"{w.name}: checksum mismatch - download discarded")
        return out

    def _unpack(self, w: Wheel, wheel: Path) -> None:
        prefix = f"nvidia/{w.part}/bin/"
        dest = self.target / w.part / "bin"
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        with zipfile.ZipFile(wheel) as z:
            for name in z.namelist():
                base = name[len(prefix):]
                if name.startswith(prefix) and base.lower().endswith(".dll") and "/" not in base:
                    with z.open(name) as src, (dest / base).open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
        if not any(dest.glob("*.dll")):
            raise RuntimeError(f"{w.name}: no DLLs found in the wheel")
