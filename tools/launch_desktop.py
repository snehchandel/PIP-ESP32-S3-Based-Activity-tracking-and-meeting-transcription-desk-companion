"""Launch the PIP host service and open the companion app as a desktop window.

  python tools/launch_desktop.py            # auto: physical board if plugged in, else simulator
  python tools/launch_desktop.py --sim      # force the host simulator (starts sim_rlcd)
  python tools/launch_desktop.py --no-window
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
SIM = ROOT / "build/host" / ("sim_rlcd.exe" if sys.platform == "win32" else "sim_rlcd")


def app_window(url: str) -> None:
    """Edge/Chrome --app mode gives a native-feeling window without browser chrome."""
    for exe in ("msedge", "chrome", "google-chrome", "chromium"):
        path = shutil.which(exe)
        if not path and sys.platform == "win32" and exe == "msedge":
            for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
                if Path(c).exists():
                    path = c
        if path:
            subprocess.Popen([path, f"--app={url}", "--window-size=1440,900"])
            return
    webbrowser.open(url)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="use sim_rlcd instead of the USB board")
    ap.add_argument("--no-window", action="store_true")
    a = ap.parse_args()
    from service.config import get_settings
    from service.transport import find_board_port

    s = get_settings()
    url = f"http://127.0.0.1:{s.pip_host_port}"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "host"))
    procs: list[subprocess.Popen[bytes]] = []
    if a.sim or (s.pip_transport == "auto" and not find_board_port()):
        if not SIM.exists():
            print("sim_rlcd not built: cmake --build build/host")
            return 2
        procs.append(subprocess.Popen([str(SIM), "--tcp", s.pip_sim_addr], stdout=subprocess.DEVNULL))
        env["PIP_TRANSPORT"] = "sim"
        print(f"simulator on {s.pip_sim_addr}")
    try:
        httpx.get(url + "/api/v1/health", timeout=1)
        print(f"host service already running at {url}")
    except httpx.HTTPError:
        procs.append(subprocess.Popen([sys.executable, "-m", "service.main"], cwd=ROOT / "host", env=env))
        for _ in range(100):
            try:
                if httpx.get(url + "/api/v1/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
    print(f"PIP companion: {url}")
    if not a.no_window:
        app_window(url)
    try:
        while all(p.poll() is None for p in procs) if procs else False:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
