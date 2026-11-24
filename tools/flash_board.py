"""Gated firmware flash for the Waveshare ESP32-S3-RLCD-4.2 (spec v6 section 3.3).

Flashes ONLY when both hold:
  1. a USB device with Espressif USB Serial/JTAG VID 0x303A / PID 0x1001 is present
     (or PIP_SERIAL_PORT names a port explicitly), and
  2. PIP_ALLOW_AUTO_FLASH=1 is set in the environment.

Usage: python tools/flash_board.py [--monitor-seconds N]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from serial.tools import list_ports

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "firmware/build"
VID, PID = 0x303A, 0x1001


def find_port() -> str | None:
    explicit = os.environ.get("PIP_SERIAL_PORT")
    if explicit:
        return explicit
    for p in list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    port = find_port()
    if not port:
        print("no ESP32-S3 USB Serial/JTAG device (VID 0x303A PID 0x1001) found - not flashing")
        return 2
    if os.environ.get("PIP_ALLOW_AUTO_FLASH") != "1":
        print(f"device found on {port}, but PIP_ALLOW_AUTO_FLASH!=1 - refusing to flash")
        return 3
    args_file = BUILD / "flash_args"
    if not args_file.exists():
        print("firmware/build/flash_args missing - run `idf.py build` first")
        return 4
    flash_args = args_file.read_text().split()
    cmd = [sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", port, "--baud", "921600",
           "write-flash", *flash_args]
    print("flashing:", " ".join(cmd))
    if args.dry_run:
        return 0
    return subprocess.call(cmd, cwd=BUILD)


if __name__ == "__main__":
    raise SystemExit(main())
