"""Capture the live 400x300 RLCD framebuffer via DUMP_FB (hardware first, simulator fallback).

  python tools/capture_rlcd.py --prefer-hardware            # current screen -> artifacts/rlcd/hardware/
  python tools/capture_rlcd.py --prefer-hardware --drive    # drive key screens via UI_UPDATE, capture each
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))

from service.protocol import FrameType  # noqa: E402
from service.protocol.fbimage import fb_to_image  # noqa: E402
from service.transport import SimTcpTransport, UsbSerialTransport, find_board_port  # noqa: E402
from service.transport.client import DeviceClient  # noqa: E402

SIM_EXE = ROOT / "build/host/sim_rlcd.exe"

STEP = {"task_title": "Q3 report", "step_id": "hil-step-1", "step_title": "Open template & add 3 headings",
        "step_index": 1, "step_total": 4, "is_starter": True, "step_total_ms": 120000,
        "next_step_id": "hil-step-2", "next_step_title": "Export Q3 metrics", "next_step_min": 10,
        "parked_count": 3, "next_alarm_hhmm": "15:00", "tz_offset_min": -300}
SCENES = [
    ("hw_01_idle_ready", {"ui_state": "IDLE_READY", "timer_state": "PAUSED", "remaining_ms": 120000}),
    ("hw_04_focus_running", {"ui_state": "RUNNING", "timer_state": "PAUSED", "remaining_ms": 1122000,
                             "step_total_ms": 1500000, "is_starter": False, "step_index": 2,
                             "step_title": "Draft the summary section for Q3"}),
    ("hw_07_step_done", {"ui_state": "STEP_DONE", "done_title": "Open template & add 3 headings",
                         "remaining_ms": 0}),
    ("hw_08_daily_tasks", {"ui_state": "IDLE_READY", "page": "AGENDA", "remaining_ms": 120000}),
    ("hw_10_needs_confirmation", {"ui_state": "NEEDS_CONFIRMATION",
                                  "clarification_text": "Gym on Friday at 2:00 PM?", "remaining_ms": 120000}),
]
CALENDAR = {"rev": 1, "date_label": time.strftime("%a, %b %d"), "tomorrow_count": 2, "parked_count": 3,
            "today": [{"id": "t1", "title": "Team Sync", "hhmm": "", "kind": 0, "done": True},
                      {"id": "t2", "title": "Draft Q3", "hhmm": "", "kind": 0, "done": False},
                      {"id": "t3", "title": "Call dentist", "hhmm": "15:00", "kind": 1, "done": False}],
            "upcoming_alarms": []}


def open_device(prefer_hw: bool) -> tuple[DeviceClient, subprocess.Popen | None]:
    proc = None
    if prefer_hw and find_board_port():
        t = UsbSerialTransport()
    else:
        print("hardware not available - falling back to sim_rlcd")
        proc = subprocess.Popen([str(SIM_EXE), "--tcp", "127.0.0.1:18432"], stdout=subprocess.DEVNULL)
        time.sleep(0.5)
        t = SimTcpTransport("127.0.0.1:18432")
    c = DeviceClient(t)
    t.start()
    if not c.wait_connected(6):
        raise SystemExit(f"could not open {t.kind} transport")
    print(f"connected: {t.kind}")
    return c, proc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefer-hardware", action="store_true")
    ap.add_argument("--drive", action="store_true", help="drive sample screens via UI_UPDATE")
    ap.add_argument("--out", default=str(ROOT / "artifacts/rlcd/hardware"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    c, proc = open_device(args.prefer_hardware)
    try:
        for _ in range(3):  # establish the link (device needs a frame within 3 s)
            c.heartbeat()
            time.sleep(0.3)
        diag = c.diag()
        print("DIAG:", json.dumps(diag, indent=1) if diag else "no response")
        if diag:
            (out / "diag.json").write_text(json.dumps(diag, indent=2))
        scenes = SCENES if args.drive else [("hw_current", None)]
        if args.drive:
            c.send_json(FrameType.CALENDAR_SYNC, CALENDAR)
        for i, (name, patch) in enumerate(scenes):
            if patch is not None:
                c.send_json(FrameType.UI_UPDATE, {"rev": 100 + i, "page": "FOCUS", **STEP, **patch})
            c.heartbeat()
            time.sleep(0.6)
            fb = c.framebuffer()
            if fb is None:
                print(f"{name}: no framebuffer response")
                continue
            fb_to_image(fb).save(out / f"{name}.png")
            print(f"{name}: saved ({sum(bin(b).count('1') for b in fb) / 1200:.1f}% ink)")
        return 0
    finally:
        c.t.stop()
        if proc:
            proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
