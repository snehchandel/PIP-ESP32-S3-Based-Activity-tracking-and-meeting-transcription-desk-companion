# Architecture Decision Records & Logged Assumptions

## Capability matrix (probed 2026-11-23)

| Capability | Result |
|---|---|
| Physical board | **Attached** — Waveshare ESP32-S3-RLCD-4.2 on COM3, USB VID 0x303A / PID 0x1001, ESP32-S3 (QFN56) rev v0.2, 16 MB flash, 8 MB embedded PSRAM, MAC xx:xx:xx:xx:xx:xx |
| ESP-IDF | **v5.5.5** cloned + installed at `C:\esp\esp-idf-v5.5.5` (xtensa-esp-elf esp-14.2.0) |
| Host C compiler | No MSVC/MinGW present → **zig cc 0.17.1** (pip `ziglang`) via `tools/zcc.cmd` + `tools/host-toolchain.cmake` |
| CMake / Ninja | pip `cmake` 4.4.5, `ninja` in project `.venv` |
| Python | 3.13.3 (venv at `.venv/`) |
| Node / npm | v22.15.0 / 10.9.2 |
| GPU | NVIDIA RTX 3070 Laptop → faster-whisper may use CUDA |

## ADR-001 — Repository root is the working folder
The spec names the root `pip-companion/`; the existing working folder `PIP ESP/` is used as the repo root unchanged.

## ADR-002 — Host toolchain is zig cc
No system C compiler is installed. `zig cc` (clang-based, shipped as a pip wheel) builds the portable C core
and `sim_rlcd` with `-Wall -Wextra -Werror -Wconversion -Wshadow`, keeping the dual-track build reproducible
from `pip install` alone.

## ADR-003 — Mascot stage ground line
Spec 4.2 places the stage at `y 72..191` (ground `y=186`) while 4.3 says `y 52..171` (ground `y=174`).
4.3 + the verifier (9.1 step 6) are authoritative: stage at `(16,52)`, 120×120. Sprite art is shifted so
the stabilizer pads rest on a ground line at `y=164` (inside the stage), state pill at `y=180..200`.

## ADR-004 — Battery divider ratio is 3.0 (spec said 2.0)
Waveshare's own `adc_bsp.cpp` computes `vol = 0.001 * mV * 3`. Verified on hardware: 4164 mV on USB power.
`BAT_DIVIDER_NUM/DEN = 3/1` in `board_pins.h`.

## ADR-005 — Display SPI host
Vendor examples use `SPI3_HOST`; spec says SPI2. SPI2 is used (both are free on this board). Init sequence,
10 MHz pclk and the landscape RAM mapping are copied from the vendor driver and verified on the panel.

## ADR-006 — Simulator-only `0xE0 SIM_INPUT` frame
`POST /device/simulate-button` must exercise the real gesture FSM. The simulator accepts `0xE0 SIM_INPUT`
(`btn, action(short/double/hold), hold_ms`) and replays raw press/release edges in real time into the
same `button_gestures` recognizer. Firmware ignores the type (no ACK).

## ADR-007 — Short click accepted for any release < 450 ms
Spec 6 lists "Short click: release < 300 ms". A 300–449 ms press would then be a dead click, violating
the "zero dead clicks" goal of D7. Any KEY release before the 450 ms PTT threshold counts as a click.

## ADR-008 — Confirmation screen button semantics
`10_needs_confirmation` shows `(✓) Confirm · (→) Dismiss`. Icons consistently mean ✓ = BOOT, → = KEY, so
BOOT short = confirm, KEY short = dismiss on that screen (the device reports the gesture; the host decides).

## ADR-009 — Fonts
Open DejaVu fonts (Bitstream Vera licence, redistributable) are rasterised with FreeType mono hinting into
1-bit tables at 14/16/16B/24B/32B px and a 64 px tabular mono digit set — zero antialiasing.

## ADR-010 — Timer completion
When a running step reaches 0:00 the device shows `STEP_DONE` immediately (offline: logs `STEP_COMPLETE`).
While tethered the host runs the same countdown and remains authoritative via `UI_UPDATE`.

## ADR-012 — No per-file line limit
The spec's ≤300-line-per-file rule (§0.1, §10.1 gate 1) is withdrawn at the user's request
(2026-11-23). `check_guardrails.py` no longer enforces or warns on file length. Existing splits stay.

## ADR-011 — Factory firmware backup before first flash
Before the first flash, the full 16 MB flash was read to `backups/factory_flash_backup_16MB.bin`
(gitignored). Restore: `python -m esptool --port COM3 write-flash 0 backups/factory_flash_backup_16MB.bin`.

## ADR-013 — Kimi is the only planner (no silent offline fallback)
User decision (2026-11-24): task breakdown is always done by Kimi. If Kimi can't be reached (no key, HTTP error,
timeout, invalid output twice) the device flashes **"AI has left the device"** until dismissed, the failure is
written to `data/logs/errors.log` + event_log, and the spoken/typed words are kept as a parked note.
The model is auto-selected from the account's `/models` list (newest preferred, pinnable in Settings) because the
configured `kimi-k2-0905-preview` returned 404; the k3 family rejects `temperature != 1`, so none is sent.
`LocalRulePlanner` remains only as a library (time parsing, templates, test double backing `tests/support/fake_kimi.py`).

## ADR-014 — Smaller task text, live eyes, no mascot stage
Task/step text moved to 14 px (user request). PIP's eyes are drawn procedurally over eyeless sprites so it can
blink, glance at the text, hop and breathe at up to 20 FPS; the ground line and state pill were removed and PIP is
centred against the text column. verify_rlcd's ink floor lowered 8% -> 6% to accommodate the smaller text.

## ADR-015 — Voice activity picker
Holding KEY opens a device-local picker (Calendar / Brain dump / Focus / Alarms); holding KEY again records.
The activity travels in AUDIO_START's former reserved u16 and selects Kimi's instructions on the host.
