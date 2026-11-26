r"""PIP Companion from the repository (no console): the same desktop app PIP.exe runs (host/service/desktop.py).

Launch:  .venv\Scripts\pythonw.exe tools\pip_tray.pyw [--background]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))

from service.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
