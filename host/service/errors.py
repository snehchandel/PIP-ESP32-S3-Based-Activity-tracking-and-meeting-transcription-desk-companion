"""Error reporting: every user-visible failure or stuck state is written to data/logs/errors.log (with traceback
and context) and to the SQLite event_log, so problems can be diagnosed after the fact."""
from __future__ import annotations

import logging
import logging.handlers
import traceback
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger("pip.errors")
_configured = False


def setup_error_log(log_dir: Path | None = None) -> Path:
    global _configured
    path = (log_dir or paths.logs_dir()) / "errors.log"
    if not _configured:
        path.parent.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        h.setLevel(logging.WARNING)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logging.getLogger("pip").addHandler(h)  # all pip.* loggers: errors + warnings land here
        logging.getLogger("pip").setLevel(logging.INFO)
        _configured = True
    return path


def report(db: Any, category: str, title: str, detail: str, exc: BaseException | None = None,
           **context: Any) -> None:
    """Log one failure with context. Never raises (error reporting must not cause new errors)."""
    try:
        ctx = " ".join(f"{k}={v!r}" for k, v in context.items())
        tb = "".join(traceback.format_exception(exc)) if exc else ""
        log.error("[%s] %s: %s %s%s", category, title, detail, ctx, f"\n{tb}" if tb else "")
        if db is not None:
            db.log("ERROR", category, f"{title}: {detail}", {**context, "exception": type(exc).__name__ if exc else None})
    except Exception:  # pragma: no cover - last-resort guard
        pass
