"""PIP Companion - standalone Windows app (no console, no Claude Code needed).

Runs the host service in-process, opens the dashboard as an app window, and sits in the system tray:
  Open PIP · Start with Windows (toggle) · Quit
Launch:  .venv\\Scripts\\pythonw.exe tools\\pip_tray.pyw [--background]
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
LOG_DIR = ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
if sys.stdout is None or sys.stderr is None:  # pythonw: no console streams
    sys.stdout = sys.stderr = open(LOG_DIR / "console.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115

import httpx  # noqa: E402
import pystray  # noqa: E402
import uvicorn  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from service.config import get_settings  # noqa: E402
from service.main import create_app  # noqa: E402

STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/PIP Companion.lnk"
PYTHONW = Path(sys.executable).with_name("pythonw.exe")
log = logging.getLogger("pip.tray")


def setup_logging() -> None:
    h = logging.handlers.RotatingFileHandler(LOG_DIR / "pip.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h])


def icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line([(24, 18), (17, 5)], fill="#18181b", width=4)
    d.ellipse([11, 0, 23, 12], fill="#e87a1e", outline="#18181b", width=2)
    d.ellipse([4, 14, 60, 62], fill="#faf8f4", outline="#18181b", width=5)
    d.rounded_rectangle([13, 26, 51, 48], radius=8, fill="#18181b")
    d.rounded_rectangle([21, 30, 27, 44], radius=3, fill="#faf8f4")
    d.rounded_rectangle([37, 30, 43, 44], radius=3, fill="#faf8f4")
    return img


def open_window(url: str) -> None:
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(exe).exists():
            subprocess.Popen([exe, f"--app={url}", "--window-size=1440,900"])
            return
    import webbrowser
    webbrowser.open(url)


def make_shortcut(path: Path, args: str) -> None:
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{path}');"
          f"$s.TargetPath='{PYTHONW}';$s.Arguments='\"{Path(__file__)}\" {args}';"
          f"$s.WorkingDirectory='{ROOT}';$s.IconLocation='{ROOT / 'tools' / 'pip.ico'}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, creationflags=0x08000000)


def toggle_autostart(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    if STARTUP.exists():
        STARTUP.unlink()
        log.info("autostart disabled")
    else:
        make_shortcut(STARTUP, "--background")
        log.info("autostart enabled")
    icon.update_menu()


def main() -> int:
    setup_logging()
    s = get_settings()
    url = f"http://127.0.0.1:{s.pip_host_port}"
    try:  # single instance: if PIP is already running, just show it
        if httpx.get(url + "/api/v1/health", timeout=1).status_code == 200:
            open_window(url)
            return 0
    except httpx.HTTPError:
        pass
    server = uvicorn.Server(uvicorn.Config(create_app(s), host="127.0.0.1", port=s.pip_host_port, log_config=None))
    threading.Thread(target=server.run, name="pip-service", daemon=True).start()
    for _ in range(150):
        try:
            if httpx.get(url + "/api/v1/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    log.info("PIP service running at %s", url)
    if "--background" not in sys.argv:
        open_window(url)

    def quit_app(icon: pystray.Icon, _: pystray.MenuItem) -> None:
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open PIP", lambda *_: open_window(url), default=True),
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda _: STARTUP.exists()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit PIP", quit_app),
    )
    pystray.Icon("pip", icon_image(), "PIP Companion", menu).run()
    time.sleep(1.0)  # let uvicorn close the device port cleanly
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
