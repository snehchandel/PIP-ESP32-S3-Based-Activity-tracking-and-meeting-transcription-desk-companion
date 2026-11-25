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

## ADR-016 — Spoken wake-up alarms and scheduling confirmation
Voice alarms (`audio_mode=TTS`) store a Piper voice and a ~30 s script (Kimi via `use_voice`/`script` in the plan,
or `POST /alarms/script`; a missing/short script triggers a dedicated Kimi call, then a built-in fallback, so an
alarm is never lost). Speech is pre-rendered at creation (`data/alarm_audio/`) so it starts instantly. Ring order:
device chime -> script on PIP's speaker -> CHIME_ALARM every 2.5 s for 60 s, all stopped the moment the alarm is
dismissed: the host aborts the stream (AUDIO_END_OUT flag byte 1) and the device drops its buffer on any local
dismiss or host `alarm_ringing=false`. Offline the device repeats the chime itself for 60 s. Every scheduled item
yields a toast (`toast`/`toast_id` in UI_UPDATE, ids unique across host restarts, each shown once for 6 s), a
confirm chime and a spoken sentence.

## ADR-017 — Procedural PIP rig, act libraries and a 2-hour no-repeat rule
The 8 fixed sprites could not turn, hold props or move their bodies. PIP is now a procedural rig (head/visor on a
cylinder so yaw reveals ears, profile and back panel; body, arms, legs, sitting, scale) drawn on an isometric floor
in a clipped stage column, with ~23 props and 13 animated emotes. A scene engine plays per-screen act libraries
(28 idle, 10 focus, others 1-6) with 450 ms cross-fades, blinks, breathing and full-body button reactions.
"No animation repeats within 2 hours" is enforced on the performance = (act, variant, direction, mood): idle offers
420 distinct performances (~18 s each, ~390 per 2 h); a history check rejects anything seen in the last 2 h and an
activity type sits out at least half the library before returning. A C test simulates 2 h: 388 performances,
0 repeats, no activity within 6 of itself. Header grew to 34 px (24 px bold clock); body text moved to 11-14 px.
Weather codes gained day/night and partly-cloudy/drizzle variants (WMO + Open-Meteo is_day).

## ADR-018 — Standard Kimi models only
Auto model selection skips "highspeed"/"turbo" variants (several times the price); kimi-k3.1-pro is now chosen.
A user can still pin any model explicitly in Settings.

## ADR-019 — Wi-Fi link, in-app firmware updates and an on-device wake word
- **Wi-Fi:** PIP joins the home network and serves the unchanged protocol v1 over one TCP connection (port 18422,
  mDNS `pip-xxxx.local`). Each connection must answer an HMAC-SHA256 challenge with a 32-byte link token that the
  PC delivers **only over USB** (DEVICE_CONFIG on every USB link-up) — physical pairing, no passwords on the LAN.
  The host's `AutoTransport` prefers USB, falls back to Wi-Fi, and returns to USB within 5 s of plugging in.
  The Wi-Fi password is relayed to PIP once and never stored on the PC.
- **Firmware updates:** partition table moved from one factory slot to ota_0/ota_1 (+ otadata, `model`).
  Updates are protocol frames (OTA_BEGIN/DATA/END, SHA-256 checked) over whichever link is up, so USB and Wi-Fi
  share one path and esptool is no longer needed. Rollback is enabled: a new image is confirmed only after 20 s of
  healthy running. Images are validated on the PC (`esp_app_desc_t.project_name == pip_firmware`).
- **Wake word:** ESP-SR WakeNet9 stock models on the device (user choice: privacy, works without the PC busy);
  "Hey PIP" would need a paid custom model. The mic feeds the detector only while PIP is silent. Saying the word
  opens the activity picker (user request, same as holding KEY); saying it again records hands-free and WebRTC
  VAD ends the recording on silence.

## ADR-020 — Kimi cost meter and monthly cap
Every API response's `usage` is priced and stored (`ai_usage`, migration 005) with per-model prices editable in
Settings. An optional monthly cap warns at 80 % and stops planning at 100 % with an "AI budget reached" screen —
words are parked, never lost. Reasoning tokens count as output, so k3.1-pro calls cost more than the visible text
suggests (~$0.006 for an 83-word wake-up script).

## ADR-021 — The idle screen is PIP's world; screens slide
User request (with a lab-scene reference): on "Let's Focus" PIP should be able to use the whole screen, the
isometric floor tile goes, and moving between screens should be smooth.
- **World, not column:** the idle screen draws a room (floor with perspective planks, a window) across the full
  width; PIP's clip is the whole world (`UI_STAGE_WORLD`). The text moves onto a free-standing message board so it
  stays readable *and* becomes something to play with. The board has a fixed size (x 150–393, y 40–194): PIP's
  body and legs show under it when it walks behind (`pose.behind`, drawn before the board), so "hiding" reads as a
  joke instead of PIP vanishing. Agenda rows are capped at 3 with a "+N more" hint; the date fills spare room.
- **New idle acts:** behind the board (peeks out of its edge), lean on the board, present the board, kick a ball
  across the room (rolls under the board, off the far wall and back), lap of the room (exits right behind the
  board, re-enters from the left). Hide-and-seek now leaves through the left screen edge; the paper plane loops
  over the board; the balloon lifts higher. Emotes switch to PIP's left side next to the board so they never cover
  text. Depth may only flip while PIP is clear of the board or off-screen (tested), so cross-fades never pop.
- **Other screens** keep PIP in the left column (it must not cover a timer or a question) on a plain floor line.
  The feet line is the same everywhere (y 236) so PIP stays put between screens.
- **Slides:** on a screen change `app_render_if_dirty()` snapshots the panel and composes old/new for 420 ms
  (360 ms vertical) with an ease-out at <= 25 FPS; header and bar switch immediately. Direction follows the flow
  (rank table in `ui_slide.c`); pause/resume switches instantly (same layout). Each output row is a 400-px window
  into the two source rows side by side, so a frame costs a few thousand byte shifts plus one normal render. The
  two frame buffers are heap-allocated on first use (PSRAM on the device: allocations > 4 KB go there); if
  allocation fails the screen simply switches. Firmware 1.2.0.

## ADR-022 — Futuristic room, seamless prop trips
User request: make the idle room more futuristic; PIP's switch from one animation to the next must be seamless —
a prop must never "magically appear": PIP should fetch it from the edge of the screen. The message board should
have small legs so the text gets the maximum area.
- **Look:** line art only, so text stays loudest. Porthole with twinkling stars, a shooting star and a ringed
  planet; a wall terminal with blinking status lights and a live oscilloscope trace; a conduit; deck plates in
  perspective with rivets and a hazard-striped edge; an airlock pillar at the left edge (drawn over PIP, its lamp
  blinks while PIP is at the hatch). The message board is a chamfered holo-monitor with a status tab and a blinking
  cursor after the headline. Header rule and bottom bar got HUD-style notches and chamfered corners; the other
  screens' floor line became a riveted deck plate. All animated parts key off `anim_ms`.
- **Board:** panel y 40–226 on two short piston legs (the deck lip is at y 240), so 5 agenda rows plus the date fit
  (was 3). Behind the board only PIP's feet show.
- **Prop trips:** `start_perf()` computes the first pose of the next act; if its props differ from PIP's current
  ones (`mascot_same_props`) or PIP is > 12 px from where the act starts, a trip runs before the act: face the
  exit, pick up the floor prop (crouch, carry it in both arms), walk off the nearest screen edge (left, or right
  when the prop/PIP is right of the board - behind the board), swap props off-screen, walk back in carrying the
  next act's props, set the floor prop down, walk to the start pose. Flying props are carried in a free hand
  (balloon stays on its string). Trips take 2-5 s; the act's own clock starts when PIP is back, so acts are
  unchanged. Ball acts now drop the ball beside PIP / leave it where it was trapped, and the next trip picks it up.
- **Test:** two simulated hours of idle play with a random screen change every 6.7 s: 800+ trips, 0 jumps, 0 prop
  pops. Firmware 1.3.0.
