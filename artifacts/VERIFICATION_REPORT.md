# PIP — Verification Report

_Generated 2026-11-23 22:48 by `tools/generate_report.py`._

## Executive summary

| Track | Result | Detail |
|---|---|---|
| C core (CTest: protocol, gestures, timer, json, ui, app) | ✅ PASS | 100% tests passed out of 6 |
| Python host + integration (pytest, live sim_rlcd) | ✅ PASS | 96 passed, 1 warning in 17.89s |
| Protocol fuzz (Python + C parser, 5000 iter) | ✅ PASS | phase B: 5000 corrupted frames into C parser, 3 reconnects, sim alive |
| RLCD Loop A (pixels, overlap, margins, golden) | ✅ PASS | verify_rlcd: PASS (11 screens, 8 expressions) |
| Desktop Loop B (Playwright E2E, 3 viewports) | ✅ PASS | 6/6 flows, 15 view checks, 0 failures |
| Guardrails (mocks, secrets, -Werror, ruff, mypy, tsc, eslint, trace) | ✅ PASS | guardrails (phase 9): PASS (0 failures, 0 warnings) |
| ESP-IDF v5.5.5 firmware build | ✅ PASS | pip_firmware.bin built |

## Environment & locked assumptions

- **Physical ESP32-S3 attached:** **yes** — flashed and verified over USB (HIL); firmware 1.0.0, I²C 0x18,0x40,0x51,0x70, battery 4158 mV, RTC ok, audio ok
- **Planner:** `LocalRulePlanner` (offline) active — no `MOONSHOT_API_KEY` set. Kimi path covered by mocked-HTTP tests.
- **ESP-IDF:** v5.5.5 installed; `idf.py build` clean. Host build uses zig cc (ADR-002).
- **STT:** faster-whisper `small.en` loads on first voice capture (CUDA if usable, else CPU int8).
- **TTS:** Piper not configured → built-in chimes. Host→device `AUDIO_*_OUT` playback is accepted but not played in v1 (known gap).
- Deviations: see `docs/decisions.md` (ADR-001 … ADR-012).

## Budgets

| Resource | Measured | Budget | |
|---|---|---|---|
| App image (factory 4 MB) | 413 KB | ≤ 2048 KB | ✅ |
| Static DRAM (.bss + .data) | 57.8 KB | ≤ 120 KB | ✅ |
| Free internal heap (live board) | 254 KB | ≥ 120 KB | ✅ |
| RLCD framebuffer | 15,000 B (static assert) | 15,000 B | ✅ |
| Max protocol payload | 4,096 B (DUMP_FB chunk 3,754 B) | 4,096 B | ✅ |

## Visual gallery

PIP expressions: ![contact sheet](pip_contact_sheet.png)

### RLCD screens (simulator)

![01_idle_ready](rlcd/preview/01_idle_ready.png)
![02_listening](rlcd/preview/02_listening.png)
![03_thinking](rlcd/preview/03_thinking.png)
![04_focus_running](rlcd/preview/04_focus_running.png)
![05_paused](rlcd/preview/05_paused.png)
![06_break_screen](rlcd/preview/06_break_screen.png)
![07_step_done](rlcd/preview/07_step_done.png)
![08_daily_tasks](rlcd/preview/08_daily_tasks.png)
![09_alarm_ringing](rlcd/preview/09_alarm_ringing.png)
![10_needs_confirmation](rlcd/preview/10_needs_confirmation.png)
![11_standalone_sleep](rlcd/preview/11_standalone_sleep.png)

### Captured from the physical board (DUMP_FB)

![hw_01_idle_ready](rlcd/hardware/hw_01_idle_ready.png)
![hw_04_focus_running](rlcd/hardware/hw_04_focus_running.png)
![hw_07_step_done](rlcd/hardware/hw_07_step_done.png)
![hw_08_daily_tasks](rlcd/hardware/hw_08_daily_tasks.png)
![hw_10_needs_confirmation](rlcd/hardware/hw_10_needs_confirmation.png)

### Desktop companion

**1440x900**

![00_today_empty](desktop/1440x900/00_today_empty.png)
![01_today](desktop/1440x900/01_today.png)
![02_calendar](desktop/1440x900/02_calendar.png)
![03_voice](desktop/1440x900/03_voice.png)
![04_focus](desktop/1440x900/04_focus.png)
![05_alarms](desktop/1440x900/05_alarms.png)
![06_device](desktop/1440x900/06_device.png)
![07_settings](desktop/1440x900/07_settings.png)
![disconnected_today](desktop/1440x900/disconnected_today.png)
**900x700**

![01_today](desktop/900x700/01_today.png)
![02_calendar](desktop/900x700/02_calendar.png)
![03_voice](desktop/900x700/03_voice.png)
![04_focus](desktop/900x700/04_focus.png)
![05_alarms](desktop/900x700/05_alarms.png)
![06_device](desktop/900x700/06_device.png)
![07_settings](desktop/900x700/07_settings.png)
**480x800**

![01_today](desktop/480x800/01_today.png)

### Bidirectional sync flows (Playwright + sim_rlcd)

- ✅ desktop->device: brain dump parsed (steps/starter/parked/alarm) and accepted
- ✅ desktop Start -> sim_rlcd RUNNING, framebuffer captured
- ✅ device BOOT click -> step completed in SQLite -> desktop updated live
- ✅ device BOOT hold -> rescue split visible on desktop, zero lost duration
- ✅ sim stopped -> calm Standalone banner within 4 s, form input preserved
- ✅ sim restarted with queued STEP_COMPLETE -> reconciled, revision incremented

## 5-minute physical bring-up checklist

1. Plug the board into USB-C. Flash: `$env:PIP_ALLOW_AUTO_FLASH=1; python tools/flash_board.py`.
2. Capture: `python tools/capture_rlcd.py --prefer-hardware --drive` → compare `artifacts/rlcd/hardware/`.
3. **Optical check (needs your eyes):** landscape orientation, text not mirrored, PIP on the left, black status bar at the bottom, good contrast under desk light.
4. Battery: multimeter across the cell vs. DIAG `batt_mv` (divider ×3, ADR-004).
5. Mic/speaker: run `python tools/launch_desktop.py`, hold KEY ~3 s and speak — Brain Dump shows the transcript; finish a step with BOOT and listen for the 'done' chime.
6. Restore factory demo anytime: `python -m esptool --port COM3 write-flash 0 backups/factory_flash_backup_16MB.bin`.
