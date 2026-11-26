"""Packaged app (ADR-034): file locations, the GPU speech add-on download, importing an old data folder."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from service import paths
from service.config import Settings
from service.desktop import import_data, launch_command
from service.main import create_app
from service.speech.gpu_pack import GpuPack, Wheel


# ---- paths --------------------------------------------------------------------------------------------------
def test_development_paths_stay_in_the_repository(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("PIP_DATA_DIR", raising=False)
    assert paths.data_dir() == paths.REPO_ROOT / "data"
    assert paths.ui_dist() == paths.REPO_ROOT / "host" / "desktop_ui" / "dist"
    assert paths.models_dir() is None  # development keeps the Hugging Face cache
    assert launch_command("--background")[-2:] == [str(paths.REPO_ROOT / "tools" / "pip_tray.pyw"), "--background"]


def test_packaged_paths_split_bundle_and_user_data(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.delenv("PIP_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert paths.ui_dist() == tmp_path / "bundle" / "ui"
    assert paths.bundled_firmware() == tmp_path / "bundle" / "firmware" / "pip_firmware.bin"
    assert paths.data_dir() == tmp_path / "local" / "PIP"
    assert paths.models_dir() == tmp_path / "local" / "PIP" / "models"
    assert paths.env_file() == tmp_path / "local" / "PIP" / ".env"
    monkeypatch.setenv("PIP_DATA_DIR", str(tmp_path / "elsewhere"))
    assert paths.logs_dir() == tmp_path / "elsewhere" / "logs"
    assert launch_command("--after", "5") == [sys.executable, "--after", "5"]


# ---- GPU speech add-on --------------------------------------------------------------------------------------
def _wheel(part: str, dlls: tuple[str, ...]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for d in dlls:
            z.writestr(f"nvidia/{part}/bin/{d}", b"MZ" + d.encode())
        z.writestr(f"nvidia/{part}/include/header.h", b"x")  # not a DLL: skipped
        z.writestr(f"nvidia/{part}/bin/sub/other.dll", b"x")  # nested: skipped
    return buf.getvalue()


def _index(files: dict[str, bytes], served: dict[str, bytes] | None = None) -> httpx.MockTransport:
    """A tiny PyPI: JSON metadata + the wheel files (served can differ from files to fake a corrupt download)."""
    served = served or files

    def handler(req: httpx.Request) -> httpx.Response:
        parts = req.url.path.strip("/").split("/")
        if req.url.host == "pypi.test":
            name = parts[1]
            data = files[name]
            return httpx.Response(200, json={"urls": [
                {"filename": f"{name}-1-py3-none-manylinux.whl", "digests": {"sha256": "0"}, "url": "https://files.test/no"},
                {"filename": f"{name}-1-py3-none-win_amd64.whl", "digests": {"sha256": hashlib.sha256(data).hexdigest()},
                 "url": f"https://files.test/{name}.whl"}]})
        return httpx.Response(200, content=served[parts[0].removesuffix(".whl")])

    return httpx.MockTransport(handler)


def _pack(tmp_path: Path, served: dict[str, bytes] | None = None) -> GpuPack:
    files = {"nv-a": _wheel("cublas", ("cublas64_12.dll", "cublasLt64_12.dll")), "nv-b": _wheel("cudnn", ("cudnn64_9.dll",))}
    wheels = tuple(Wheel(n, "1", hashlib.sha256(b).hexdigest(), len(b), p) for (n, b), p in zip(files.items(), ("cublas", "cudnn"),
                                                                                                  strict=True))
    return GpuPack(tmp_path / "gpu", wheels, "https://pypi.test/pypi",
                   client=lambda: httpx.Client(transport=_index(files, served)))


def test_gpu_pack_downloads_checks_and_unpacks_only_the_dlls(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pack = _pack(tmp_path)
    assert not pack.installed()
    assert pack.start()
    pack.wait(10)
    st = pack.status()
    assert st["state"] == "done" and st["installed"], st
    assert sorted(p.name for p in (tmp_path / "gpu" / "cublas" / "bin").iterdir()) == ["cublas64_12.dll", "cublasLt64_12.dll"]
    assert not (tmp_path / "gpu" / "_download").exists()  # wheels removed after unpacking
    assert json.loads((tmp_path / "gpu" / "pack.json").read_text()) == {"nv-a": "1", "nv-b": "1"}
    pack.remove()
    assert not pack.installed() and not (tmp_path / "gpu").exists()


def test_gpu_pack_rejects_a_corrupt_download(tmp_path) -> None:  # type: ignore[no-untyped-def]
    good = _wheel("cublas", ("cublas64_12.dll", "cublasLt64_12.dll"))
    pack = _pack(tmp_path, served={"nv-a": good[:-10] + b"tampered!!", "nv-b": b""})
    pack.start()
    pack.wait(10)
    assert pack.state == "error" and "checksum" in pack.error
    assert not pack.installed() and not any((tmp_path / "gpu").rglob("*.dll"))


def test_gpu_pack_and_restart_routes(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from service.meetings import models

    monkeypatch.setattr(models, "_HW", {"gpu": "Test GPU", "vram_gb": 8.0, "ram_gb": 16.0})
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False, pip_stt_preload=False,
                 pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"))
    with TestClient(create_app(s)) as c:
        g = c.get("/api/v1/settings/gpu-pack").json()
        assert g["gpu"] == "Test GPU" and not g["installed"] and g["state"] == "idle"
        assert g["folder"] == str(tmp_path / "gpu") and g["can_restart"] is False
        assert c.post("/api/v1/app/restart").status_code == 409  # not started as the desktop app
        calls: list[int] = []
        c.app.state.services.restart_app = lambda: calls.append(1)  # type: ignore[attr-defined]
        assert c.post("/api/v1/app/restart").json() == {"restarting": True} and calls == [1]
        assert c.delete("/api/v1/settings/gpu-pack").json()["installed"] is False


# ---- importing the repository's data folder ------------------------------------------------------------------
def test_import_data_copies_and_repoints_paths(tmp_path) -> None:  # type: ignore[no-untyped-def]
    src, dst = tmp_path / "old data", tmp_path / "new"
    (src / "voices").mkdir(parents=True)
    (src / "voices" / "v.onnx").write_bytes(b"onnx")
    (src / "logs").mkdir()
    (src / "logs" / "pip.log").write_text("old log")
    (src / "settings.json").write_text(json.dumps({"piper_voice": str(src / "voices" / "v.onnx"), "kimi_model": "k"}))
    with sqlite3.connect(src / "pip.db") as db:
        db.execute("CREATE TABLE meetings(id TEXT, audio_path TEXT, n INTEGER)")
        db.execute("INSERT INTO meetings VALUES ('m1', ?, 3)", (str(src / "meetings" / "m1.wav"),))
        db.execute("INSERT INTO meetings VALUES ('m2', 'C:/elsewhere/x.wav', 4)")
    assert import_data(src, dst).startswith("Imported")
    assert (dst / "voices" / "v.onnx").read_bytes() == b"onnx" and not (dst / "logs").exists()
    assert json.loads((dst / "settings.json").read_text())["piper_voice"] == str(dst.resolve() / "voices" / "v.onnx")
    with sqlite3.connect(dst / "pip.db") as db:
        rows = dict(db.execute("SELECT id, audio_path FROM meetings").fetchall())
    assert rows == {"m1": str(dst.resolve() / "meetings" / "m1.wav"), "m2": "C:/elsewhere/x.wav"}
    assert "already has PIP data" in import_data(src, dst)  # never overwrites
    assert import_data(tmp_path / "nothing", tmp_path / "x").startswith("No PIP data")
