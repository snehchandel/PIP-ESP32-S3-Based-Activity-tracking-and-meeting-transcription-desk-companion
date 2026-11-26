"""PyInstaller entry point of PIP.exe (tools/pip.spec) - the desktop app in service/desktop.py."""
from __future__ import annotations

import multiprocessing

from service.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
