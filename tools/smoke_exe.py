"""Smoke test of the packaged app (ADR-034): starts the built PIP.exe on a spare port with a throw-away data folder
and checks that it really runs on its own - service, companion UI, Piper speech, Whisper, bundled firmware, the
single-instance guard - and that no test doubles or CUDA DLLs were bundled.

  python tools/smoke_exe.py build/app/dist/PIP/PIP.exe [--skip-stt] [--gpu]
Run by tools/build_exe.ps1 after every build. Never touches the real data folder, keyring or the board.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
PORT = 18431
URL = f"http://127.0.0.1:{PORT}"


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what, flush=True)
    if not ok:
        raise SystemExit(1)


def wait(pred, timeout: float, step: float = 0.5) -> bool:  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if pred():
                return True
        except httpx.HTTPError:
            pass
        time.sleep(step)
    return False


def bundle_checks(exe: Path) -> None:
    internal = exe.parent / "_internal"
    names = {p.name.lower() for p in internal.rglob("*")}
    check(not any(n.startswith(("fake_kimi", "fake_ollama")) for n in names), "no test doubles bundled")
    check(not (internal / "nvidia").exists() and "cublas64_12.dll" not in names, "CUDA DLLs not bundled (GPU add-on)")
    check((internal / "ui" / "index.html").exists(), "companion UI bundled")
    check(any((internal / "service" / "storage" / "migrations").glob("*.sql")), "migrations bundled")
    size = sum(p.stat().st_size for p in exe.parent.rglob("*") if p.is_file()) / 1e6
    print(f"       app folder: {size:.0f} MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe", type=Path)
    ap.add_argument("--skip-stt", action="store_true", help="do not load Whisper (copies ~0.5 GB into the temp folder)")
    ap.add_argument("--gpu", action="store_true",
                    help="fill the GPU speech pack from this venv's NVIDIA wheels (~2 GB copy) and expect Whisper on CUDA")
    a = ap.parse_args()
    exe = a.exe.resolve()
    check(exe.exists(), f"{exe} exists")
    bundle_checks(exe)

    data = Path(tempfile.mkdtemp(prefix="pip-smoke-"))
    voices = sorted((ROOT / "data" / "voices").glob("*.onnx"))
    env = dict(os.environ, PIP_DATA_DIR=str(data), PIP_HOST_PORT=str(PORT), PIP_TRANSPORT="none",
               PIP_USE_KEYRING="false", PIP_WEATHER="false", PIP_STT_PRELOAD=str(not a.skip_stt).lower(),
               PIP_LOCAL_AI_URL="http://127.0.0.1:9")
    if voices:  # Piper needs a voice: use one the developer already has
        (data / "voices").mkdir(parents=True)
        for f in (voices[0], voices[0].with_suffix(".onnx.json")):
            if f.exists():
                shutil.copy2(f, data / "voices" / f.name)
        env["PIP_PIPER_VOICE"] = str(data / "voices" / voices[0].name)
    if a.gpu:  # what speech/gpu_pack.py would download, copied from the development venv instead
        import nvidia  # type: ignore[import-not-found]
        from service.speech.gpu_pack import MARKER, WHEELS

        base = Path(next(iter(nvidia.__path__)))
        for w in WHEELS:
            shutil.copytree(base / w.part / "bin", data / "gpu" / w.part / "bin")
        (data / "gpu" / MARKER).write_text("{}", encoding="utf-8")
    proc = subprocess.Popen([str(exe), "--background"], env=env)
    try:
        check(wait(lambda: httpx.get(URL + "/api/v1/health", timeout=2).status_code == 200, 120),
              "service answers /health")
        r = httpx.get(URL + "/", timeout=5)
        check(r.status_code == 200 and "<div id=\"root\"" in r.text, "companion UI served")
        check(httpx.get(URL + "/settings", timeout=5).status_code == 200, "client-side route served")
        s = httpx.get(URL + "/api/v1/settings", timeout=5).json()
        check("stt" in s and "tts" in s, f"settings API (tts: {s.get('tts')})")
        if voices:
            w = httpx.get(URL + "/api/v1/speech/say.wav", params={"text": "PIP is packaged."}, timeout=60)
            check(w.status_code == 200 and w.content[:4] == b"RIFF" and len(w.content) > 20_000,
                  f"Piper speaks ({len(w.content) // 1000} KB WAV)")
        fw = httpx.get(URL + "/api/v1/firmware", timeout=5)
        bundled = (exe.parent / "_internal" / "firmware" / "pip_firmware.bin").exists()
        check(fw.status_code == 200 and (bool(fw.json()["available"]) or not bundled),
              f"firmware updater offers the bundled image ({str(fw.json()['available'])[:90]})")
        g = httpx.get(URL + "/api/v1/settings/gpu-pack", timeout=15)
        check(g.status_code == 200 and not g.json()["from_python_env"], f"GPU add-on status ({g.json()['state']})")
        if not a.skip_stt:
            check(wait(lambda: httpx.get(URL + "/api/v1/settings", timeout=5).json()["stt_ready"], 300, 2),
                  f"Whisper loads ({httpx.get(URL + '/api/v1/settings', timeout=5).json()['stt']})")
            check(any((data / "models").glob("models--*")), "Whisper model kept in PIP's data folder")
            if a.gpu:
                stt = httpx.get(URL + "/api/v1/settings", timeout=5).json()["stt"]
                check("cuda" in stt, f"Whisper runs on the GPU with the add-on ({stt})")
        second = subprocess.run([str(exe), "--background"], check=False, env=env, timeout=30)
        check(second.returncode == 0 and proc.poll() is None, "second start hands over to the running PIP")
        check((data / "pip.db").exists() and (data / "logs" / "pip.log").exists(), "data + logs in the data folder")
        check(proc.poll() is None, "still running")
    finally:
        subprocess.run(["taskkill", "/pid", str(proc.pid), "/t", "/f"], capture_output=True, check=False)
        proc.wait(10)
        shutil.rmtree(data, ignore_errors=True)
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
