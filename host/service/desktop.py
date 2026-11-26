"""PIP desktop app (ADR-034): PIP.exe when packaged, `pythonw tools/pip_tray.pyw` from the repository.

Starts the host service in-process, shows the companion app in its own WebView2 window and sits in the tray:
  Open PIP · Start with Windows · Quit PIP
Closing the window only hides it; PIP keeps running (alarms, the board link) until Quit.

  PIP.exe [--background] [--install-gpu] [--import-data <old data folder>]
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import logging.handlers
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import paths

APP_NAME = "PIP Companion"
# Per port, so a second PIP on another port (the build smoke test, PIP_HOST_PORT) is not taken for this one.
_PORT = os.environ.get("PIP_HOST_PORT", "18421").strip()
MUTEX_NAME = f"Local\\PIPCompanion.{_PORT}.Instance"
SHOW_EVENT = f"Local\\PIPCompanion.{_PORT}.Show"
log = logging.getLogger("pip.desktop")


# ---- Windows helpers ---------------------------------------------------------------------------------------
def message_box(text: str, error: bool = False) -> None:
    log.warning("message: %s", text)
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, text, APP_NAME, 0x10 if error else 0x40)  # type: ignore[attr-defined]


class Instance:
    """One PIP per Windows session: a named mutex; a second start asks the first to show its window."""

    def __init__(self) -> None:
        self.mutex = self.event = None
        self.first = True
        if sys.platform != "win32":
            return
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        k32.CreateMutexW.restype = k32.CreateEventW.restype = ctypes.c_void_p
        self.mutex = k32.CreateMutexW(None, False, MUTEX_NAME)
        self.first = k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
        self.event = k32.CreateEventW(None, False, False, SHOW_EVENT)

    def signal_show(self) -> None:
        if self.event:
            ctypes.windll.kernel32.SetEvent(ctypes.c_void_p(self.event))  # type: ignore[attr-defined]

    def watch_show(self, on_show: Callable[[], None]) -> None:
        if not self.event:
            return

        def run() -> None:
            k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            while k32.WaitForSingleObject(ctypes.c_void_p(self.event), 0xFFFFFFFF) == 0:
                on_show()

        threading.Thread(target=run, name="pip-show-watch", daemon=True).start()


def wait_for_exit(pid: int, timeout_s: float = 20.0) -> None:
    """Restart: wait until the previous PIP (which still holds the port and the board) has exited."""
    if sys.platform != "win32":
        return
    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        k32.WaitForSingleObject(ctypes.c_void_p(h), int(timeout_s * 1000))
        k32.CloseHandle(ctypes.c_void_p(h))


def launch_command(*args: str) -> list[str]:
    """How to start this app again (autostart shortcut, restart)."""
    if paths.FROZEN:
        return [sys.executable, *args]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else sys.executable), str(paths.REPO_ROOT / "tools" / "pip_tray.pyw"), *args]


STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/PIP Companion.lnk"


def set_autostart(on: bool) -> None:
    if not on:
        STARTUP.unlink(missing_ok=True)
        return
    exe, *args = launch_command("--background")
    argline = " ".join(f'"{a}"' if " " in a else a for a in args)
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{STARTUP}');"
          f"$s.TargetPath='{exe}';$s.Arguments='{argline}';$s.WorkingDirectory='{paths.app_dir()}';"
          f"$s.IconLocation='{exe if paths.FROZEN else paths.icon_path()}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False,  # noqa: S603, S607
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


# ---- data import (repository data/ -> the packaged app's data folder) -----------------------------------------
def import_data(src: Path, dst: Path) -> str:
    """Copy an existing PIP data folder (e.g. the repository's data/) into dst. Never overwrites a database.
    Absolute paths into the old folder (meeting recordings, the chosen voice) are pointed at the new one."""
    src, dst = src.resolve(), dst.resolve()
    if not (src / "pip.db").exists():
        return f"No PIP data in {src}."
    if (dst / "pip.db").exists():
        return f"{dst} already has PIP data - nothing imported."
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name.startswith("pip.db") or item.name in ("logs", "gpu", "models", "webview"):
            continue
        if item.is_dir():
            shutil.copytree(item, dst / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst / item.name)
    with sqlite3.connect(src / "pip.db") as a, sqlite3.connect(dst / "pip.db") as b:
        a.backup(b)  # consistent copy including the WAL
        old, new = str(src), str(dst)
        for (table,) in b.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            if table.endswith(("_fts", "_data", "_idx", "_docsize", "_config", "_content")):
                continue  # FTS5 shadow tables follow their content table
            for col in [r[1] for r in b.execute(f"PRAGMA table_info('{table}')") if r[2].upper() in ("TEXT", "")]:
                b.execute(f"UPDATE '{table}' SET \"{col}\" = replace(\"{col}\", ?, ?) "  # noqa: S608
                          f"WHERE instr(\"{col}\", ?) > 0", (old, new, old))
    prefs = dst / "settings.json"
    if prefs.exists():
        prefs.write_text(prefs.read_text(encoding="utf-8").replace(old.replace("\\", "\\\\"), new.replace("\\", "\\\\")),
                         encoding="utf-8")
    return f"Imported PIP data from {src}."


# ---- logging -------------------------------------------------------------------------------------------------
def setup_logging() -> None:
    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None:  # windowed: no console streams
        sys.stdout = sys.stderr = open(logs / "console.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    h = logging.handlers.RotatingFileHandler(logs / "pip.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h])


def draw_icon() -> Any:
    """PIP's head (tray icon; tools/pip.ico is made from it: `python -m service.desktop --write-icon <file>`)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line([(24, 18), (17, 5)], fill="#18181b", width=4)
    d.ellipse([11, 0, 23, 12], fill="#e87a1e", outline="#18181b", width=2)
    d.ellipse([4, 14, 60, 62], fill="#faf8f4", outline="#18181b", width=5)
    d.rounded_rectangle([13, 26, 51, 48], radius=8, fill="#18181b")
    d.rounded_rectangle([21, 30, 27, 44], radius=3, fill="#faf8f4")
    d.rounded_rectangle([37, 30, 43, 44], radius=3, fill="#faf8f4")
    return img


def icon_image() -> Any:
    from PIL import Image

    try:
        return Image.open(paths.icon_path())
    except OSError:
        return draw_icon()


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def healthy(url: str) -> bool:
    import httpx

    try:
        return httpx.get(url + "/api/v1/health", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


# ---- the app ---------------------------------------------------------------------------------------------------
class DesktopApp:
    def __init__(self, background: bool, install_gpu: bool) -> None:
        self.background = background
        self.install_gpu = install_gpu
        self.window: Any = None
        self.tray: Any = None
        self.server: Any = None
        self.server_thread: threading.Thread | None = None
        self.quitting = False
        self.restart_after = False
        self.url = ""

    # service
    def start_service(self) -> bool:
        import uvicorn

        from .config import get_settings
        from .main import create_app

        s = get_settings()
        self.url = f"http://127.0.0.1:{s.pip_host_port}"
        if not port_free(s.pip_host_port):
            if healthy(self.url):
                message_box("PIP is already running in another copy (for example the one started from the source "
                            "folder). Quit that one from its tray icon, then open PIP again.")
            else:
                message_box(f"Port {s.pip_host_port} on this PC is used by another program, so PIP cannot start.\n"
                            "Close that program (or set PIP_HOST_PORT) and try again.", error=True)
            return False
        Path(s.pip_db_path).parent.mkdir(parents=True, exist_ok=True)
        app = create_app(s)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=s.pip_host_port, log_config=None))
        self.server_thread = threading.Thread(target=self.server.run, name="pip-service", daemon=True)
        self.server_thread.start()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and self.server_thread.is_alive():
            if healthy(self.url):
                break
            time.sleep(0.2)
        if not healthy(self.url):
            message_box(f"PIP's service did not start. Details are in\n{paths.logs_dir() / 'pip.log'}", error=True)
            return False
        svcs = app.state.services
        svcs.restart_app = self.restart
        if self.install_gpu and not svcs.gpu_pack.installed():
            svcs.gpu_pack.start()
        log.info("PIP service running at %s (data in %s)", self.url, paths.data_dir())
        return True

    # window
    def show(self) -> None:
        if self.window is not None:
            try:
                self.window.show()
                self.window.restore()
                return
            except Exception as e:  # window gone: fall through to the browser
                log.info("window show failed: %s", e)
        open_in_browser(self.url)

    def _on_closing(self) -> bool:
        if self.quitting:
            return True
        threading.Thread(target=self.window.hide, daemon=True).start()  # keep running in the tray
        return False

    # tray
    def start_tray(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Open PIP", lambda *_: self.show(), default=True),
            pystray.MenuItem("Start with Windows", lambda *_: (set_autostart(not STARTUP.exists()), self.tray.update_menu()),
                             checked=lambda _: STARTUP.exists()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit PIP", lambda *_: self.quit()),
        )
        self.tray = pystray.Icon("pip", icon_image(), APP_NAME, menu)
        threading.Thread(target=self.tray.run, name="pip-tray", daemon=True).start()

    def quit(self) -> None:
        self.quitting = True
        if self.server is not None:
            self.server.should_exit = True
        if self.tray is not None:
            self.tray.stop()
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception as e:
                log.info("window destroy: %s", e)

    def restart(self) -> None:
        self.restart_after = True
        threading.Timer(0.3, self.quit).start()  # let the HTTP reply go out first

    def run(self) -> int:
        if not self.start_service():
            return 1
        self.start_tray()
        start = self.url + ("/settings" if self.install_gpu else "/")
        try:
            import webview

            self.window = webview.create_window("PIP", start, width=1440, height=900, min_size=(900, 600),
                                                hidden=self.background, background_color="#faf8f4")
            self.window.events.closing += self._on_closing
            webview.start(private_mode=False, storage_path=str(paths.data_dir() / "webview"))
        except Exception as e:  # no WebView2 runtime: browser window + tray
            log.warning("WebView2 window unavailable (%s) - using the browser", e)
            self.window = None
            if not self.background:
                open_in_browser(start)
            while not self.quitting:
                time.sleep(0.5)
        if not self.quitting:  # window closed by the system
            self.quit()
        if self.server_thread is not None:
            self.server_thread.join(timeout=8)  # let uvicorn close the board's port cleanly
        if self.restart_after:
            subprocess.Popen(launch_command("--after", str(os.getpid())), close_fds=True)  # noqa: S603
        return 0


def open_in_browser(url: str) -> None:
    for exe in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(exe).exists():
            subprocess.Popen([exe, f"--app={url}", "--window-size=1440,900"])  # noqa: S603
            return
    import webbrowser

    webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="PIP")
    ap.add_argument("--background", action="store_true", help="start in the tray without showing the window")
    ap.add_argument("--install-gpu", action="store_true", help="download the GPU speech pack after starting")
    ap.add_argument("--import-data", metavar="FOLDER", help="copy an existing PIP data folder in (first run only)")
    ap.add_argument("--after", type=int, default=0, help=argparse.SUPPRESS)  # restart: wait for this PID to exit
    ap.add_argument("--write-icon", metavar="FILE", help=argparse.SUPPRESS)  # build: tools/pip.ico
    a = ap.parse_args(argv)
    if a.write_icon:
        draw_icon().save(a.write_icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        return 0
    setup_logging()
    if a.after:
        wait_for_exit(a.after)
    if a.import_data:
        msg = import_data(Path(a.import_data), paths.data_dir())
        log.info(msg)
        message_box(msg)
    inst = Instance()
    if not inst.first:
        inst.signal_show()  # PIP is already running: bring its window up
        return 0
    app = DesktopApp(background=a.background, install_gpu=a.install_gpu)
    inst.watch_show(app.show)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
