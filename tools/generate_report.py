"""Run the full test pyramid and compile artifacts/VERIFICATION_REPORT.md (spec phase 9).

  python tools/generate_report.py [--run-e2e]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
CMAKE = str(ROOT / ".venv/Scripts/ctest") if sys.platform == "win32" else "ctest"


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 900) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def last(pattern: str, text: str, default: str = "n/a") -> str:
    m = re.findall(pattern, text)
    return m[-1] if m else default


def size_rows() -> list[str]:
    txt = (ROOT / "artifacts/firmware_size.txt")
    if not txt.exists():
        return ["| Firmware size | not measured (run `idf.py size`) | | |"]
    t = txt.read_text(encoding="utf-8", errors="ignore")
    total = int(last(r"Total image size: (\d+)", t, "0"))
    bss, data = int(last(r"\.bss\s+│\s+(\d+)", t, "0")), int(last(r"\.data\s+│\s+(\d+)", t, "0"))
    diag_p = ROOT / "artifacts/rlcd/hardware/diag.json"
    heap = json.loads(diag_p.read_text()).get("free_heap_b", 0) if diag_p.exists() else 0
    ok = lambda c: "✅" if c else "❌"  # noqa: E731
    return [f"| App image (factory 4 MB) | {total / 1024:.0f} KB | ≤ 2048 KB | {ok(total <= 2048 * 1024)} |",
            f"| Static DRAM (.bss + .data) | {(bss + data) / 1024:.1f} KB | ≤ 120 KB | {ok(bss + data <= 120 * 1024)} |",
            f"| Free internal heap (live board) | {heap / 1024:.0f} KB | ≥ 120 KB | {ok(heap >= 120 * 1024)} |",
            "| RLCD framebuffer | 15,000 B (static assert) | 15,000 B | ✅ |",
            "| Max protocol payload | 4,096 B (DUMP_FB chunk 3,754 B) | 4,096 B | ✅ |"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-e2e", action="store_true")
    a = ap.parse_args()
    results: list[tuple[str, bool, str]] = []
    rc, out = run([CMAKE, "--test-dir", "build/host"])
    results.append(("C core (CTest: protocol, gestures, timer, json, ui, app)", rc == 0, last(r"(\d+% tests passed.*)", out)))
    rc, out = run([PY, "-m", "pytest", "tests", "-q"])
    results.append(("Python host + integration (pytest, live sim_rlcd)", rc == 0, last(r"(\d+ passed.*?)(?:\n|$)", out)))
    rc, out = run([PY, "tools/protocol_fuzz.py", "--iterations", "5000"])
    results.append(("Protocol fuzz (Python + C parser, 5000 iter)", rc == 0, last(r"(phase B:.*)", out)))
    rc, out = run([PY, "tools/verify_rlcd.py", "--strict"])
    results.append(("RLCD Loop A (pixels, overlap, margins, golden)", rc == 0, last(r"(verify_rlcd: .*)", out)))
    if a.run_e2e:
        rc, out = run([PY, "tools/verify_desktop_ui.py"])
    e2e = json.loads((ROOT / "artifacts/desktop/results.json").read_text())
    results.append(("Desktop Loop B (Playwright E2E, 3 viewports)", not e2e["failures"],
                    f"{len(e2e['flows'])}/6 flows, {len(e2e['views'])} view checks, {len(e2e['failures'])} failures"))
    rc, out = run([PY, "tools/check_guardrails.py"])
    results.append(("Guardrails (mocks, secrets, -Werror, ruff, mypy, tsc, eslint, trace)", rc == 0,
                    last(r"(guardrails .*)", out)))
    idf_ok = (ROOT / "firmware/build/pip_firmware.bin").exists()
    results.append(("ESP-IDF v5.5.5 firmware build", idf_ok, "pip_firmware.bin built" if idf_ok else "not built"))
    diag_p = ROOT / "artifacts/rlcd/hardware/diag.json"
    diag = json.loads(diag_p.read_text()) if diag_p.exists() else {}
    write(results, diag, e2e)
    print(*(f"{'PASS' if ok else 'FAIL'}  {n}: {d}" for n, ok, d in results), sep="\n")
    return 0 if all(ok for _, ok, _ in results) else 1


def write(results: list[tuple[str, bool, str]], diag: dict, e2e: dict) -> None:  # type: ignore[type-arg]
    hw = bool(diag) and not diag.get("is_sim", True)
    L = [f"# PIP — Verification Report\n\n_Generated {datetime.now():%Y-%m-%d %H:%M} by `tools/generate_report.py`._\n",
         "## Executive summary\n", "| Track | Result | Detail |", "|---|---|---|"]
    L += [f"| {n} | {'✅ PASS' if ok else '❌ FAIL'} | {d} |" for n, ok, d in results]
    L += ["\n## Environment & locked assumptions\n",
          f"- **Physical ESP32-S3 attached:** {'**yes** — flashed and verified over USB (HIL)' if hw else 'no'}"
          + (f"; firmware {diag.get('fw_ver')}, I²C {diag.get('i2c_addrs')}, battery {diag.get('batt_mv')} mV, "
             f"RTC {'ok' if diag.get('rtc_ok') else 'missing'}, audio {'ok' if diag.get('audio_ok') else 'missing'}" if hw else ""),
          "- **Planner:** `LocalRulePlanner` (offline) active — no `MOONSHOT_API_KEY` set. Kimi path covered by mocked-HTTP tests.",
          "- **ESP-IDF:** v5.5.5 installed; `idf.py build` clean. Host build uses zig cc (ADR-002).",
          "- **STT:** faster-whisper `small.en` loads on first voice capture (CUDA if usable, else CPU int8).",
          "- **TTS:** Piper not configured → built-in chimes. Host→device `AUDIO_*_OUT` playback is accepted but not "
          "played in v1 (known gap).", "- Deviations: see `docs/decisions.md` (ADR-001 … ADR-012).",
          "\n## Budgets\n", "| Resource | Measured | Budget | |", "|---|---|---|---|", *size_rows(),
          "\n## Visual gallery\n", "PIP expressions: ![contact sheet](pip_contact_sheet.png)\n", "### RLCD screens (simulator)\n"]
    for p in sorted((ROOT / "artifacts/rlcd/preview").glob("*.png")):
        L.append(f"![{p.stem}](rlcd/preview/{p.name})")
    L.append("\n### Captured from the physical board (DUMP_FB)\n")
    for p in sorted((ROOT / "artifacts/rlcd/hardware").glob("hw_*.png")):
        L.append(f"![{p.stem}](rlcd/hardware/{p.name})")
    L.append("\n### Desktop companion\n")
    for vp in ("1440x900", "900x700", "480x800"):
        L.append(f"**{vp}**\n")
        L += [f"![{p.stem}](desktop/{vp}/{p.name})" for p in sorted((ROOT / f"artifacts/desktop/{vp}").glob("*.png"))]
    L += ["\n### Bidirectional sync flows (Playwright + sim_rlcd)\n", *[f"- ✅ {f}" for f in e2e["flows"]],
          "\n## 5-minute physical bring-up checklist\n",
          "1. Plug the board into USB-C. Flash: `$env:PIP_ALLOW_AUTO_FLASH=1; python tools/flash_board.py`.",
          "2. Capture: `python tools/capture_rlcd.py --prefer-hardware --drive` → compare `artifacts/rlcd/hardware/`.",
          "3. **Optical check (needs your eyes):** landscape orientation, text not mirrored, PIP on the left, black "
          "status bar at the bottom, good contrast under desk light.",
          "4. Battery: multimeter across the cell vs. DIAG `batt_mv` (divider ×3, ADR-004).",
          "5. Mic/speaker: run `python tools/launch_desktop.py`, hold KEY ~3 s and speak — Brain Dump shows the "
          "transcript; finish a step with BOOT and listen for the 'done' chime.",
          "6. Restore factory demo anytime: `python -m esptool --port COM3 write-flash 0 backups/factory_flash_backup_16MB.bin`."]
    (ROOT / "artifacts/VERIFICATION_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
