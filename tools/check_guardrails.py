"""Guardrail suite (spec 10.1). Exit 0 only when every gate passes.

  python tools/check_guardrails.py [--phase N] [--skip-builds]"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SRC_EXT = {".c", ".h", ".py", ".ts", ".tsx"}
SKIP_DIRS = {"node_modules", "build", "dist", ".venv", "managed_components", "__pycache__", ".git", "backups"}
GENERATED = {"pip_sprites.h", "fonts_gen.c", "icons_gen.c"}
MOCK_MARKERS = re.compile(r"MOCK_|FAKE_DATA|DUMMY_RESPONSE|TODO_STUB|lorem ipsum|Welcome to your app", re.I)
SECRET = re.compile(r"(sk-[A-Za-z0-9]{24,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
FRAME_TYPES = ["HEARTBEAT", "AUDIO_START", "AUDIO_DATA", "AUDIO_END", "BTN_EVENT", "OFFLINE_EVENTS", "UI_UPDATE",
               "AUDIO_START_OUT", "PLAY_CHIME", "ALARM_TRIGGER", "CALENDAR_SYNC", "ACK", "DIAG_REPORT", "DUMP_FB",
               "AUTH_CHALLENGE", "WAKE_EVENT", "DEVICE_CONFIG", "AUTH_RESPONSE", "OTA_BEGIN", "OTA_DATA", "OTA_END",
               "WAKE_TEST"]
EXPRESSIONS = ["ready", "listening", "thinking", "working", "paused", "done", "alarm", "sleep"]
VIEWS = ["today", "calendar", "voice", "focus", "alarms", "device", "settings"]


def sources() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if p.suffix in SRC_EXT and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and p.name not in GENERATED:
            out.append(p)
    return out


def tracked_files() -> list[Path]:
    r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return [ROOT / f for f in r.stdout.splitlines()] if r.returncode == 0 else sources()



def gate_mocks(fails: list[str]) -> None:
    for p in sources():
        rel = p.relative_to(ROOT)
        if rel.parts[0] == "tests" or p.name == "check_guardrails.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if MOCK_MARKERS.search(line):
                fails.append(f"{rel}:{i}: production stub marker")


def gate_secrets(fails: list[str]) -> None:
    gi = (ROOT / ".gitignore").read_text()
    if not re.search(r"^\.env$", gi, re.M):
        fails.append(".env is not gitignored")
    for p in tracked_files():
        if p.is_file() and p.suffix not in {".png", ".bin", ".ico"} and p.stat().st_size < 2_000_000:
            if SECRET.search(p.read_text(encoding="utf-8", errors="ignore")):
                fails.append(f"{p.relative_to(ROOT)}: looks like a hardcoded secret")
    if "redact" not in (ROOT / "tests/unit/test_storage.py").read_text():
        fails.append("no redaction test for event_log")


def run(cmd: list[str], cwd: Path, fails: list[str], label: str) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=sys.platform == "win32" and cmd[0] == "npm")
    if r.returncode != 0:
        fails.append(f"{label} failed: {(r.stdout + r.stderr).strip().splitlines()[-1:]}")


def gate_builds(fails: list[str]) -> None:
    cmake = str(ROOT / ".venv/Scripts/cmake") if sys.platform == "win32" else "cmake"
    run([cmake, "--build", str(ROOT / "build/host")], ROOT, fails, "C host build (-Werror -Wconversion)")
    if "rlcd_fb_size_guard_t" not in (ROOT / "firmware/components/ui_core/include/rlcd_fb.h").read_text():
        fails.append("missing sizeof(rlcd_fb_t)==15000 static assert")
    run([PY, "-m", "ruff", "check", "service", "../tools", "../tests", "--config", "pyproject.toml"], ROOT / "host",
        fails, "ruff")
    run([PY, "-m", "mypy", "service/protocol", "service/planner", "--config-file", "pyproject.toml"], ROOT / "host",
        fails, "mypy (strict protocol/planner)")
    ui = ROOT / "host/desktop_ui"
    run(["npm", "run", "typecheck"], ui, fails, "tsc --noEmit")
    run(["npm", "run", "lint"], ui, fails, "eslint")
    run(["npm", "run", "build"], ui, fails, "vite build")


def gate_traceability(fails: list[str]) -> None:
    for e in EXPRESSIONS:
        if not (ROOT / f"artifacts/pip/png/{e}.png").exists():
            fails.append(f"expression {e}: no rendered sprite")
    golden = sorted(p.stem for p in (ROOT / "tests/golden/rlcd").glob("*.png"))
    if len(golden) != 14:
        fails.append(f"golden RLCD baselines: {len(golden)}/14")
    res = ROOT / "artifacts/desktop/results.json"
    if res.exists():
        r = json.loads(res.read_text())
        seen = {Path(v["shot"]).stem.split("_", 1)[1] for v in r["views"] if v["ok"]}
        for v in VIEWS:
            if v not in seen:
                fails.append(f"desktop view {v}: no passing Playwright check")
        if r["failures"]:
            fails.append(f"desktop E2E has {len(r['failures'])} failures")
    else:
        fails.append("artifacts/desktop/results.json missing (run tools/verify_desktop_ui.py)")
    tests = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "tests").rglob("*")
                      if p.suffix in {".c", ".py"})
    for t in FRAME_TYPES:
        if not re.search(rf"(PIP_{t}\b|FrameType\.{t}\b)", tests):
            fails.append(f"frame type {t}: no test coverage")
    inv = (ROOT / "tests/unit/test_adhd_invariants.py").read_text()
    for i in range(1, 8):
        if f"def test_{i}_" not in inv:
            fails.append(f"ADHD invariant {i}: no test")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, default=9)
    ap.add_argument("--skip-builds", action="store_true")
    a = ap.parse_args()
    fails: list[str] = []
    warns: list[str] = []
    gate_mocks(fails)  # file-size gate removed by the user (ADR-012)
    gate_secrets(fails)
    if a.phase >= 2 and not a.skip_builds:
        gate_builds(fails)
    if a.phase >= 7:
        gate_traceability(fails)
    for w in warns:
        print("WARN", w)
    for f in fails:
        print("FAIL", f)
    print(f"guardrails (phase {a.phase}): {'PASS' if not fails else 'FAIL'} ({len(fails)} failures, {len(warns)} warnings)")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
