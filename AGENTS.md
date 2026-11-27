# AGENTS.md — working on PIP

Read this before changing anything. It is the map of the project for an AI coding agent (or a new developer):
what PIP is, how the pieces fit, how to build/test/flash, the rules that must not be broken, and the lessons
already paid for. Deeper references: `docs/decisions.md` (ADRs), `debugging_log.md` (BUG-xxx post-mortems; local only, like `development_journal.md`),
`docs/USER_MANUAL.md` (user-facing behaviour), `esp32-s3-rlcd-development-plan-v6.md` (original spec; local only, not in the repository).

---

## 1. What PIP is

PIP is an ADHD-friendly desk companion. Hardware: **Waveshare ESP32-S3-RLCD-4.2** (ESP32-S3-WROOM-1-N16R8:
16 MB flash, 8 MB octal PSRAM) with a **400×300 1-bit reflective LCD**, two buttons (KEY, BOOT), an ES7210 mic +
ES8311 speaker codec, PCF85063 RTC, SHTC3 temperature/humidity sensor and a Li-ion battery. A Windows PC runs the
**host service** (Python/FastAPI) and the **companion app** (React, served by the host), packaged together as
**PIP.exe** (installer, own WebView2 window + tray, ADR-034) or run from the repository by `tools/pip_tray.pyw`.

The user brain-dumps by voice or text → **Kimi** (Moonshot API) turns it into one focus task of small steps,
parked tangents, alarms and reminders → PIP shows one step at a time with a timer, an animated robot mascot,
today's calendar, weather and alarms (including spoken wake-up alarms).

```
 PIP board (C, ESP-IDF 5.5.5)                PC host service (Python 3.11+, FastAPI)        Companion app (React 19)
 ui_core · mascot rig · gestures ·  ◄─USB─►  device link · state manager (canonical) ·  ◄──►  REST + WebSocket
 timer · protocol (portable C99)     or      Kimi planner · cost meter · STT (whisper) ·         http://127.0.0.1:18421
 + ESP adapters: display, audio,   ─Wi-Fi─►  TTS (Piper) · alarms · weather · SQLite             (served from dist/)
   RTC, battery, USB, Wi-Fi, OTA,  (TCP+HMAC)
   wake word (ESP-SR)
 firmware/sim/sim_rlcd  ◄── same protocol over TCP ──►  (simulator for tests/demos; same portable C core)
```

**The host owns the canonical state** (`host/service/state/manager.py`). The device acts locally first (timer,
alarms it already knows, offline event log) and reconciles idempotently when the link returns.

---

## 2. Rules that must never be broken

1. **Flashing over USB** only via `tools/flash_board.py`, only with `PIP_ALLOW_AUTO_FLASH=1` set *for that one
   command*, and only to a port verified by VID 0x303A / PID 0x1001. Stop the tray app first (it holds COM3).
   Prefer the **in-app updater** (§7) for normal firmware changes; USB flashing is for bootloader/partition-table
   changes and recovery. A factory image backup lives in `backups/` (gitignored) — never delete it.
2. **Secrets:** never print, log, commit or send the Kimi API key (Windows Credential Manager via `keyring`,
   service `pip-companion`). Same for the Wi-Fi link token (`PIP_LINK_TOKEN` in keyring) and the user's Wi-Fi
   password (relayed to PIP once, never stored on the PC). Never overwrite `.env`. Tests set
   `pip_use_keyring=False` so they never touch the real credential store.
3. **Kimi is the only planner** (ADR-013). If it fails, the device shows "AI has left the device" and the words
   are parked — never silently fall back to the local rule engine. Auto model choice must skip
   `highspeed`/`turbo` variants (ADR-018, cost). The monthly AI cap must stop planning when reached.
4. **Git:** commit locally with clear messages; **never push** unless the user asks.
5. **No mocks in production code** (`tools/check_guardrails.py` scans for them). Test doubles live in
   `tests/support/` (e.g. `fake_kimi.py`, a local fake Moonshot server).
6. **Every protocol frame type needs a test** (guardrail) and must exist identically in
   `firmware/components/usb_protocol/include/pip_protocol.h` and `host/service/protocol/frames.py`.
7. **Keep `APP_FW_VERSION` (firmware/main/app_controller.h) and `PROJECT_VER` (firmware/CMakeLists.txt) equal**;
   bump both for every firmware you ship so the app can tell builds apart.
8. No per-file line limit (ADR-012). Match the surrounding style instead.

---

## 3. Repository map

| Path | What lives there |
|---|---|
| `host/service/meetings/` | Meeting recorder/transcriber + the one worker that also runs summaries (`service.py`), speaker detection + remembered voices (`diarize.py`: neural voiceprints clustered by NME-SC, MFCC fallback) and the voiceprint model (`voice_embed.py`: CAM++ via onnxruntime, numpy front-ends, ADR-038), storage + FTS5 search index (`store.py`), exports md/txt/srt/json (`export.py`), local AI client for Ollama (`local_ai.py`) + the model catalog matched to the PC's GPU/RAM (`models.py`), summaries (`summarize.py`: one pass up to ~1 h; careful mode = think + scan + check + write-up), summaries by another AI agent (`handoff.py`: transcript + prompt out, Markdown reply parsed back in, ADR-036), deadline words -> dates (`due.py`), action-item triage + calendar items (`actions.py`), Obsidian vault writer (`obsidian.py`), questions by retrieval (`ask.py`). Recordings: `data/meetings/<id>.wav`. |
| `firmware/main/` | ESP-IDF app. `app_main.c` = FreeRTOS wiring (tasks, adapters, link routing). `app_controller.c/.h`, `app_gestures.c`, `app_frames.c`, `app_report.c` = **portable** state coordinator (also compiled into the simulator and C tests). `dev_config.c` (NVS settings), `net_link.c` (Wi-Fi + TCP server + mDNS + HMAC auth), `dev_ota.c` (firmware updates), `dev_wake.c` (wake word) are ESP-only. |
| `firmware/components/ui_core/` | 1-bit renderer: primitives (`ui_draw*.c`), fonts (`fonts_gen.c`, generated), icons, header/bar chrome (`ui_chrome.c`), screens (`ui_screens_a/b/c.c`), PIP rig drawing (`ui_mascot.c`), props (`ui_props.c`), slide transitions (`ui_slide.c`), animated weather icons (`ui_weather.c`), layout constants (`include/ui_layout.h`), the UI model (`include/ui_model.h`). |
| `firmware/components/mascot_renderer/` | PIP rig geometry + scene engine (`mascot.c`) and choreography (`mascot_acts.c`): per-screen act libraries, 2-hour no-repeat history, reactions. Pure C, no drawing. |
| `firmware/components/usb_protocol/` | Wire protocol v1 (framing, CRC, parser, payload structs) + `json_mini` (tiny JSON reader with escape decoding). |
| other components | `usb_transport` (USB Serial/JTAG), `rlcd_display`, `audio_codec`, `rtc_calendar` (PCF85063 + SHTC3), `battery_monitor`, `button_gestures`, `local_timer`, `board_pins`. |
| `firmware/sim/` | `sim_rlcd`: host-native simulator (`--tcp`), batch renderer (`--render-all`), act contact sheets (`--render-acts`), slide frames (`--render-slides`). |
| `firmware/partitions.csv`, `sdkconfig.defaults` | 16 MB layout: nvs, otadata, ota_0/ota_1 (3.75 MB each), `model` (ESP-SR wake words), storage, coredump. `sdkconfig` is generated — edit the defaults and delete `sdkconfig` to regenerate. |
| `host/service/` | FastAPI app (`main.py`), DI container (`services.py`), config (`config.py`, prefs in `data/settings.json`), `api/` routes, `state/` (manager, actions, reconcile, timer), `planner/` (Kimi, schema, local rules library), `speech/` (STT, TTS, voice pipeline), `alarms/` (scheduler, spoken wake-up audio), `calendar/`, `storage/` (SQLite + numbered migrations), `device/` (link, voice out, firmware updater), `transport/` (USB, Wi-Fi, auto, simulator), `ai_cost.py`, `weather.py`, `errors.py`. |
| `host/desktop_ui/` | React 19 + Vite + Tailwind v4. Views: Today, Calendar (Outlook-style), Voice (brain dump), Focus, Alarms, Device, Settings. `npm run build` → `dist/` served by the host. |
| `tests/` | `unit/` (pytest), `unit/c/` (C tests via CTest), `integration/` (host ↔ sim over TCP), `protocol/`, `golden/rlcd/` (pixel baselines), `support/` (test doubles). |
| `tools/` | `idf.ps1` (ESP-IDF env), `flash_board.py`, `capture_rlcd.py`, `verify_rlcd.py` (pixel/layout gate), `verify_desktop_ui.py` (Playwright E2E, 15 views), `e2e_stack.py`, `check_guardrails.py`, `generate_fonts.py`, `act_sheet.py`, `pip_tray.pyw` (the desktop app from the repo), `install_windows.ps1` ("PIP Companion (dev)" shortcuts), `build_exe.ps1` + `pip.spec` + `installer/pip.iss` + `smoke_exe.py` (packaged app, ADR-034), `zcc.cmd` + `host-toolchain.cmake` (zig cc for host C builds). |
| `data/` (gitignored) | `pip.db`, `settings.json` (prefs), `logs/pip.log`, `logs/errors.log`, `voices/` (Piper `.onnx`), `alarm_audio/` (pre-rendered wake-up speech), `firmware/upload.bin`. |
| `artifacts/` | Rendered screens (`rlcd/raw`), hardware captures (`rlcd/hardware`), previews, act contact sheets (`rlcd_acts/sheet_*.png`), desktop E2E screenshots. |

---

## 4. Firmware architecture

**Tasks (FreeRTOS)** — core 0: `usb_rx` (6 KB), `net_srv` (6 KB), `audio` (mic capture, speaker playback, wake-word
feeding, silence detection), `wake` (WakeNet detector). Core 1: `ui` (buttons, timer, RTC/battery/SHTC3, mascot
step + render + display flush at ≤20 FPS). One mutex (`s_lock`) guards `s_app`; flash writes (OTA) and socket I/O
happen outside it.

**Portable core** (`app_*.c`, `ui_core`, `mascot_renderer`, protocol, gestures, timer) has **zero ESP-IDF
dependencies** — it is compiled into `sim_rlcd` and the C tests with `-Wall -Wextra -Werror -Wconversion`
(zig cc). Device-only behaviour plugs in through `app_io_t` callbacks (send, chime, capture, diag, play) and the
device-frame interceptor in `app_main.c` (`device_frame()` handles DEVICE_CONFIG / OTA_* / WAKE_TEST).

**Screens** (`ui_render.c` → `ui_screen_for()`): idle "Let's Focus", listening, thinking, focus running, paused,
break, step done, today's calendar, alarm, confirm time, sleep, voice picker, error, meeting (14 in all). Focus and
paused draw a shrinking time pie in the stage corner; the device chimes "5 minutes left" / "Time to wrap up" itself. Layout: header 0–34 px
(24 px bold clock, alarm, indoor and animated outdoor weather; **no link status in the header** — it is in the
bottom bar), PIP stage column x 4–147 (home spot `STAGE_CX/STAGE_FY`, a plain floor line — no isometric tile),
text column x 154–392, inverted bottom bar y 264–299. **The idle screen is PIP's world** (ADR-021, ADR-022): a small
space station (porthole, wall terminal, airlock pillar PIP fetches props from, hazard-striped deck). PIP may use the
whole width (`UI_STAGE_WORLD`), the text sits on a holo-monitor (`BOARD_*` in `ui_layout.h`, x 150–393, y 40–226,
on short legs so the panel gets the most room) and `pose.behind` draws PIP behind the board (only its feet show). Screen
changes **slide** (`ui_slide.c`, driven by `app_render_if_dirty()`): forward in the flow (idle → voice → plan →
focus → done, calendar furthest right) pushes left, back pushes right, alarm/error/sleep drop in from the top;
header and bar switch at once. **PIP does not slide:** pages render without it (`ui_mascot_hide`) and the one PIP
is drawn on top, so it never appears twice. Slide buffers + the shown model (~48 KB) are one heap block (PSRAM on the
device), allocated on first render; without it screens switch instantly.
The board lists TODAY's open items, then **COMING UP** (open items of the next 7 days, from CALENDAR_SYNC
`upcoming`: day, hhmm, title, kind), then the date if there is room. Fonts: DejaVu 11/12/12B/14/14B/16/16B/20B/24B/32B/64 (regenerate with
`tools/generate_fonts.py`; only Latin-1 + `· — … °` are mapped — avoid other UTF-8 in device strings).

**PIP mascot** (ADR-017): `mascot_pose_t` → `mascot_rig()` (cylinder model: yaw reveals profile/back, arms open
into a V when raised) → `ui_draw_mascot()` (clipped to the stage). Scene engine: `mascot_set_mode()` per screen,
acts are pure functions of time in `mascot_acts.c` (tables `IDLE[]`, `FOCUS[]`, ...). A performance is
(mode, act, variant, dir, mood); the idle library offers 480 and none repeats within 2 h (C test simulates 2 h).
**Props never pop:** when the next performance carries different props (or starts far away) the engine plays a
*prop trip* first (`mascot_trip_pose`, state `trip_*` in `mascot_anim_t`): PIP picks up what lies on the floor,
carries everything off the nearest screen edge, swaps it off-screen and walks back in with the new props, setting
floor props down where the act expects them. Acts must therefore leave their props where they end (the ball is
dropped beside PIP, not teleported home); `test_ui` runs 2 h of mode changes and fails on any jump or prop pop.
**PIP acts out the task at hand** (ADR-024): the host classifies each step (`planner/activity.py`, keyword rules,
earliest keyword wins) into an activity - general, write, computer, read, call, clean, exercise, cook, garden, music,
fix, plan, errand, rest - and sends `activity` / `next_activity` / `done_activity` in UI_UPDATE. The app turns the
screen + activity into *scene tags* (`app_scene_tags` → `mascot_set_scene`); every act carries a tag mask
(`ACT_T`/`KITS` in the tables) and only matching acts play: focus = the activity's own acts, pause/done/idle preview =
one "kit" act per activity (`GEAR[]` props), listening = the picked voice activity, thinking = transcribing then
planning, break = its cue in order (stretch, sip water, look far away). Idle stays free play; with a step lined up
every third act previews it. A tag change mid-screen restarts the performance (props via a trip).
**Hands on objects:** `pose.grip` makes the rig put the hands where the object needs them (laptop keyboard deck,
guitar neck + strings; the guitar is strapped to the body) and draws the arms in front; a gripped laptop is drawn
under the arms. The laptop is one 3/4-view model (`mascot_laptop()` in `mascot.c`, used by the rig and `ui_props.c`):
it stands on the floor beside PIP (`LAPTOP_DX`), keyboard toward PIP, screen turned toward you, lid shut while
carried. Book and calendar are always held by their edges (`pip_rig_t.held_c`; a pencil writes on the page). **Easter eggs** (ADR-025): acts tagged `PIP_TAG_EGG` only come from a rare roll in `start_perf`
(idle ~1 in 24, error screen 1 in 3, never twice in 2 h, never while focusing): PIP's relatives "PIP Mk.0" (tin toy)
and "PIP-1960" (mainframe) swap in behind a smoke `puff` via `pose.form`, and an upset PIP hurls its potato battery (monocle + bow tie, no face). All
original designs - do not draw film/game characters.
Idle acts may roam the world (`PIP_BOARD_DX`, `PIP_WORLD_L/R`, `PIP_OFFSCREEN` in `mascot.h`): they may only flip
`behind` while PIP is clear of the board or off-screen, and must start and end at home — `test_ui` checks both.
To add an act: write `static void a_xxx(mascot_pose_t *p, float t, float D, int v, float s, int mood)`, start and
end near the home pose, add it to a table with duration and variant count, run `test_ui` (smoothness + no-repeat)
and look at it: `build/host/sim_rlcd --render-acts artifacts/rlcd_acts && python tools/act_sheet.py`.

**Voice:** KEY hold (or the wake word) → voice picker ("What's it about?": Calendar / Brain dump / Focus / Alarms /
Meeting) → KEY hold records (release ends, 10 min max) **or** saying the wake word again records hands-free (WebRTC
VAD ends it after a 3.5 s pause - 5 s once 20 s were spoken -, 6 s with no speech, 10 min max; a KEY click sends
at once; `APP_QUIET_END_*` in `app_controller.h`). **Meeting**
(ADR-026) records in `UI_STATE_MEETING` until KEY is held again, with no limit; the host stores and transcribes it.
The first wake word now listens at once (AUDIO_START activity 5 = AUTO, `voice_auto`): the host transcribes the first
seconds, `speech/spoken_activity.py` finds a leading activity name, and UI_UPDATE `voice_stream`/`voice_activity`
tells PIP (a MEETING stream is handed to the recorder in place). 3 s of silence -> AUDIO_END reason 2 (cancelled) +
the picker (ADR-028). Acknowledgements: the CONFIRM (wake word) and START (activity heard) chimes play *over the live
mic* (the only exception to half-duplex, `audio_write_mono_duplex`), plus a "Got it: <Activity> - go ahead" toast.
BOOT double-click parks the task in progress (ADR-027). Audio: 16 kHz mono PCM16 in 20 ms frames
(AUDIO_START/DATA/END); the activity id rides in AUDIO_START's former reserved u16.

**Wake word** (`dev_wake.c`, ADR-019): ESP-SR WakeNet9 stock models ("Hi ESP" default, "Jarvis", "Computer",
"Hi Joy") in the `model` partition. The mic feeds the detector only while PIP is silent (no self-triggering).
A custom "Hey PIP" is not possible without Espressif's paid training — the user chose stock words.

**Wi-Fi** (`net_link.c`, ADR-019, ADR-035): STA mode, up to 5 saved networks in NVS namespace `pip` (strongest
in range wins, `dev_settings.c`), mDNS `pip-xxxx.local`
(`_pip._tcp`), one TCP client on port 18422. Every connection starts with AUTH_CHALLENGE (16-byte nonce + MAC);
the PC must answer HMAC-SHA256(link token, nonce) within 5 s. The token is delivered **only over USB**
(DEVICE_CONFIG on every USB link-up), so only a PC that was once cabled to PIP can drive it. Replies go back over
whichever link the PC last spoke on (`s_src`).
**Away link** (ADR-035): on another network PIP dials OUT to the PC's public address (`remote` in DEVICE_CONFIG;
Tailscale Funnel with TLS, or a router port forward) after 10 s with no cable and no LAN client. Both sides prove the
token, then every frame is an AES-256-GCM record; the PC listens on 18423 (`transport/away.py`, kind `WIFI_AWAY`).
mbedtls allocates in PSRAM (TLS buffers).

**OTA** (`dev_ota.c`): OTA_BEGIN (size + SHA-256 + version) → OTA_DATA (offset + ≤4000 B, ACK each) → OTA_END
(hash check, `esp_ota_end`, switch boot slot, reboot after 0.8 s). `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`: the
new image is marked valid after 20 s of healthy running; a crash before that rolls back automatically.

---

## 5. Wire protocol v1 (`pip_protocol.h` ⇄ `protocol/frames.py`)

Frame: `AA 55 | ver(1) | type(1) | flags(1) | seq(u16) | len(u16) | payload | CRC16-CCITT-FALSE(u16)`, little
endian, payload ≤ 4096. Flags: 0x01 ACK required, 0x04 simulator. Parser resyncs byte-wise on bad sync/len/CRC and
on 20 ms idle with a partial frame.

| Type | Dir | Payload / meaning |
|---|---|---|
| 0x00 HEARTBEAT | ⇄ | proto, link mode, flags, uptime, epoch, revision |
| 0x01–0x03 AUDIO_START/DATA/END | dev→host | mic stream (activity in START: 0 brain dump, 1 calendar, 2 focus, 3 alarms, 4 meeting, 5 auto = named after the wake word; max_sec 600, 0 = meeting/no limit; END reason 2 = cancelled) |
| 0x04 BTN_EVENT | dev→host | gesture (idempotent by boot id + seq) |
| 0x05 OFFLINE_EVENTS | dev→host | JSON list of offline actions to reconcile |
| 0x06 AUTH_CHALLENGE | dev→host | Wi-Fi only: nonce(16) + MAC(6) |
| 0x07 WAKE_EVENT | dev→host | source (0 mic, 1 test), listening flag |
| 0x10 UI_UPDATE | host→dev | JSON snapshot (`manager.snapshot()`, ≤2 KB): step, timer, toast, error, weather, `activity`/`next_activity`/`done_activity`… |
| 0x11–0x13 AUDIO_*_OUT | host→dev | Piper speech to the speaker; END with flag byte 1 = abort |
| 0x14 PLAY_CHIME, 0x15 ALARM_TRIGGER, 0x16 CALENDAR_SYNC | host→dev | chime id / alarm JSON / today's agenda (8 items) + alarms |
| 0x17 DEVICE_CONFIG | host→dev | JSON `{"wifi":{"ssid","password"},"wifi_forget","wifi_clear","token":"hex64","wake":{"enabled","word"},"remote":{"host","port","tls"}}` |
| 0x18 AUTH_RESPONSE | ⇄ | HMAC-SHA256(token, nonce); away link: + PC nonce (48 B), then PIP's proof back (32 B) |
| 0x20–0x22 OTA_BEGIN/DATA/END | host→dev | firmware update (ACK each) |
| 0x23 WAKE_TEST | host→dev | PCM fed straight into the wake detector (self-test) |
| 0xE0 SIM_INPUT | host→sim | simulator-only button injection |
| 0xF0 ACK | ⇄ | ref seq, status (0 OK … 5 UNKNOWN_TYPE, 6 FAILED, 7 DENIED) |
| 0xFD DIAG_REPORT | ⇄ | request / JSON report incl. `wifi`, `ota`, `wake` objects |
| 0xFE DUMP_FB | ⇄ | request / framebuffer in 4 chunks (screenshots) |

---

## 6. Host service

- **Startup:** `service/desktop.py` - the desktop app: host service in-process, WebView2 window (closing hides it),
  tray (Open / Start with Windows / Quit), one instance per port (named mutex; a second start shows the window),
  `POST /app/restart`. Runs as **PIP.exe** (packaged) or `tools/pip_tray.pyw` (repo); `python -m uvicorn` via
  `service.main:create_app` for a console. Port 18421.
- **Files** (`service/paths.py`, ADR-034): bundled resources (UI, migrations, icon, firmware image) vs user data.
  User data = `data/` from the repo, `%LOCALAPPDATA%\PIP` when packaged, `PIP_DATA_DIR` overrides. Never build a
  path from `__file__` for user data; use `paths`. The packaged app keeps Whisper models in `<data>/models` and the
  GPU speech add-on (`speech/gpu_pack.py`: pinned + checksummed NVIDIA wheels from PyPI, DLLs only) in `<data>/gpu`.
  Logs: `data/logs/pip.log`; errors + stuck-state reports: `data/logs/errors.log` and the `event_log` table.
- **State:** `DeviceStateManager` (+ `ActionsMixin`, `ReconcileMixin`) — every change calls `changed(kind, …)`,
  which bumps the revision and fans out to the WebSocket hub and the device link (pushes UI_UPDATE + CALENDAR_SYNC).
  A 1 Hz tick runs timers, test-ring expiry, ack expiry and the stuck-state watchdog.
- **Planning:** `speech/pipeline.py` (voice) and `/tasks/plan` (text) → `Services.planner()` (checks the AI budget,
  resolves the model) → `KimiPlanner.plan()` (strict JSON schema `planner/schema.py`, one repair retry) →
  `manager.commit_plan()` (tasks, parked notes, alarms incl. spoken wake-ups, reminders, confirmation toast).
- **Cost meter** (`ai_cost.py`): every Kimi call's `usage` is priced (editable per-model prices, defaults
  k3.1-pro $2 / $0.20 cached / $10 per M tokens) into `ai_usage`; optional monthly cap → `BudgetExceeded`
  → device error "AI budget reached".
- **Meetings** (ADR-026): activity-4 streams go to `MeetingService` (WAV on disk, gap fill, crash recovery, own
  faster-whisper instance `pip_meeting_model`, 10-min windows, numpy speaker detection, remembered voices, optional
  summary). API under `/meetings` + `/voices`; WebSocket event `meeting_updated` (status, progress,
  summary_status, summary_part/parts).
- **Meeting summaries, Obsidian, questions** (ADR-031): after each transcription the summary is made **on this PC**
  by default (Ollama, `meetings/local_ai.py` + `summarize.py`; prefs `meeting_summary` local|kimi|off,
  `local_ai_model`; `PIP_LOCAL_AI_URL`). The meetings worker runs transcriptions first; summaries go part by part
  and yield between parts to a new transcription or a voice command (overlay LISTENING/TRANSCRIBING). A failed
  local summary never falls back to Kimi. Each meeting is written to the Obsidian vault (prefs `obsidian_vault`,
  `obsidian_folder`): note + transcript + index + action items; user text under the marker and ticks survive.
  Careful mode (default), action-item triage and archive: ADR-032. Action items: `PATCH /meetings/{id}/actions/{i}`,
  `POST /meetings/{id}/actions/convert` (task/reminder/park), `POST /meetings/{id}/archive`; `/calendar` adds undecided
  dated items as kind 3 (`others=true` for other people's). Ollama needs `OLLAMA_FLASH_ATTENTION=1` and
  `OLLAMA_KV_CACHE_TYPE=q8_0` (user env) for the 16k context on the 8 GB GPU. Meeting speech: NVIDIA Parakeet-TDT-0.6B v3 on the
  CPU (`speech/parakeet.py`, onnx-asr, 2.5 GB pinned download, Whisper fallback; ADR-039); Whisper `large-v3-turbo` on
  the GPU stays selectable (CUDA wheels `nvidia-cublas-cu12`/`nvidia-cudnn-cu12`, DLL path set in `speech/stt.py`).
  Model downloads go through `webclient.download_client()` (Windows certificate store).
  Another AI agent (ADR-036): `GET /meetings/{id}/export?format=ai` (prompt + transcript), `GET /meetings/summary-prompt`,
  `POST /meetings/{id}/summary/upload?source=` (Markdown reply -> the summary, engine `upload/<source>`).
  `GET /meetings/search` (FTS5, no AI), `POST /meetings/ask` (retrieval, ~1.5k tokens), `GET /meetings/graph`
  (`meetings/graph.py`: meeting/summary/person/topic nodes, the Obsidian links; a person's name is never a topic
  ("mentioned" edge), near-identical topics merge, related topics link, `topic_catalog()` feeds the summarizers -
  ADR-037; drawn by the Meetings -> Graph tab,
  `components/MeetingGraph.tsx` + `lib/forceLayout.ts`, no graph library), `GET /meetings/actions`,
  Settings `GET/PUT /settings/meetings`, `POST /settings/local-ai/pull`. Tests use `tests/support/fake_ollama.py`
  and conftest points `PIP_LOCAL_AI_URL` at a closed port so a real Ollama is never touched.
- **Nudges** (`alarms/nudges.py`, ADR-029): due reminders and task start times -> toast + chime + speech.
  Personal vocabulary (prefs `vocabulary`) feeds Whisper `hotwords` and the Kimi request.
- **Speech:** faster-whisper `small.en` for voice (CUDA float16 when the cuBLAS/cuDNN wheels load, else CPU int8),
  beam 5 on the GPU / greedy on the CPU, silence phantoms dropped; transcripts and voice commands are cleaned of
  fillers and stutters (`speech/cleanup.py`, ADR-033; raw meeting text kept in `meeting_segments.raw_text`).
  Migration comments must not contain `;` (the runner splits statements on it). Piper voices in `data/voices`. Spoken alarms
  are pre-rendered to `data/alarm_audio/` at creation; ring sequence = device chime → script → chimes every
  2.5 s for 60 s, aborted the moment the alarm is dismissed.
- **Device link** (`device/link.py`): `make_transport()` → `AutoTransport` (USB when plugged in, else PIP's away
  link if it dialed in (`AwayListener`, prefs `away_*`, `GET/PUT /device/away`), else Wi-Fi to the last reported IP /
  mDNS name, hops back to USB within 5 s of plugging in), `SimTcpTransport`, `WifiTransport`.
  `link.request()` sends with ACK and awaits it by sequence number. On link-up `Services._on_link_up` sends
  DEVICE_CONFIG (token only over USB); `_on_diag` remembers PIP's Wi-Fi address.
- **Firmware updater** (`device/firmware.py`): validates the image (`esp_app_desc_t` project must be
  `pip_firmware`), streams OTA frames, detects completion by a new `boot_id` (USB reconnects too fast to see a
  drop). Sources: `firmware/build/pip_firmware.bin` (latest local build) or an uploaded `.bin`.
- **API** (all under `/api/v1`): health, state, tasks/steps/timer/plan/commit, calendar, reminders, parked,
  confirmation, alarms (+ test, ack, script), voice sessions, speech (preload, say, say.wav), settings (API key,
  Kimi model, preferences), ai (usage, budget, prices), weather, device (diagnostics, framebuffer.png, network,
  wifi, wake, wake/test, simulate-button), firmware (status, upload, update), error/dismiss, diagnostics/export.
  WebSocket: `/ws/events`.
- **DB:** SQLite WAL, migrations `storage/migrations/NNN_*.sql` applied in order (current: 001–010). Add a new
  numbered file; never edit an applied one.

---

## 7. Build, test, flash, verify (Windows PowerShell, repo root)

```powershell
# Python + tests
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python -m ruff check host/service tests
# Host C build (portable core, simulator, C tests) - cmake/ninja from the ESP-IDF tools dir
$b="$env:USERPROFILE\.espressif\tools\cmake\3.30.2\bin"; $env:PATH="$b;$env:USERPROFILE\.espressif\tools\ninja\1.12.1;$env:PATH"
cmake --build build/host; ctest --test-dir build/host
# Screens: render all 13, then the pixel/layout gate (update goldens only after looking at the renders)
build\host\sim_rlcd.exe --render-all artifacts/rlcd; .venv\Scripts\python tools\verify_rlcd.py --strict
# Desktop app
cd host/desktop_ui; npx tsc --noEmit -p .; npx eslint src; npm run build; cd ../..
.venv\Scripts\python tools\verify_desktop_ui.py     # 15 views + 6 end-to-end flows against the simulator
.venv\Scripts\python tools\check_guardrails.py --skip-builds
# Firmware (ESP-IDF 5.5.5 at C:\esp\esp-idf-v5.5.5). NOTE: idf.ps1 changes the current directory - use absolute paths after it.
.\tools\idf.ps1 build
```

**Packaged app (PIP.exe + installer, ADR-034):** bump `version` in `host/pyproject.toml`, then
```powershell
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1   # UI -> PyInstaller -> smoke test -> Inno Setup
```
Output: `build/app/dist/PIP/` (~350 MB) and `build/app/PIP-Setup-<version>.exe` (~110 MB). Rebuild after building new
firmware (the image is bundled for the updater). `tools/smoke_exe.py <exe> --gpu` also checks CUDA with the add-on.
Runtime dependencies belong in `host/requirements-runtime.txt` (what gets bundled); a new lazily imported module
or data file may need an entry in `tools/pip.spec`. Install over the old version to update; data is kept.

**Updating firmware on the board:** bump the version (rule 7), build, then either
- app: Device → Firmware → *Update PIP* (or `POST /api/v1/firmware/update {"source":"build"}`), ~25 s over USB; or
- USB flash (partition/bootloader changes, recovery): stop the tray app (packaged: `Stop-Process -Name PIP`; repo:
  `Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | ? CommandLine -match pip_tray | % { Stop-Process -Id $_.ProcessId }`),
  `$env:PIP_ALLOW_AUTO_FLASH="1"; .venv\Scripts\python tools\flash_board.py; Remove-Item Env:PIP_ALLOW_AUTO_FLASH`,
  then relaunch: `Start-Process .venv\Scripts\pythonw.exe -ArgumentList '"tools\pip_tray.pyw"','--background'`.

**Looking at the real screen:** `GET /api/v1/device/framebuffer.png` while the host runs (or
`tools/capture_rlcd.py --prefer-hardware` when the host is stopped). **After a crash:** stop the tray app and run
`.\tools\idf.ps1 -p COM3 coredump-info` (core dumps are stored in flash). Uptime and `reset_reason` are in
`GET /api/v1/device/diagnostics`.

**Hardware verification checklist for firmware changes:** board links (health `link_state` TETHERED), uptime keeps
growing for ≥ 90 s with `reset_reason` POWERON/USB/SW (never PANIC/WDT), free internal heap stays > 30 KB, a
framebuffer capture looks right, `dropped_audio_chunks` stays 0 after `/speech/say`.

---

## 8. Lessons already learned (read before you repeat them)

- **Stack sizes:** the DIAG report grew to ~1.4 KB and overflowed the 4 KB `usb_rx` stack, corrupting the USB
  driver's mutex → PANIC loop (fixed: static buffers, 6 KB stacks, stack canary on). Anything big in code reached
  from the link rx tasks must be static or heap.
- **Internal RAM is tight** with Wi-Fi + WakeNet (~38 KB free): `CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=4096` and
  Wi-Fi/LWIP in PSRAM. Check `free_heap_b` after changes.
- **Encoding:** shell heredocs mangled `\x..` escapes and inserted control characters (BUG-007). Write patch
  scripts to files, or use an editor tool; grep the result for stray bytes. Device strings must stay ASCII or the
  mapped Latin-1 glyphs.
- **Sync FastAPI routes run in a thread pool** — anything that creates asyncio tasks must be `async def`.
- **USB reconnects in < 1 s** after a reboot: detect device restarts by `boot_id`, not by waiting for a link drop.
- **A rebooted PIP is blank until the host re-sends everything** (UTC clock, no weather/alarm/agenda). USB reconnects
  inside the link grace period, so there is no link-down/up after an OTA or watchdog reset. `DeviceLink` resyncs when
  the heartbeat uptime goes backwards or the device's `state_rev` lags the host's for 3 s (BUG-016).
- **The SHTC3 failed about every other read** in its wake/measure/sleep cycle on the shared I2C bus, and one miss
  hid the header's indoor reading for 30 s (BUG-017). The sensor now stays awake, reads retry 3x, a miss is retried
  after 2 s, and the app keeps the last good value for 5 min. `env.ok`/`env.fail` in DIAG count reads since boot.
- **Windows occasionally drops PIP's COM port for a moment** ("ClearCommError ... device does not recognize the
  command", seen even before Wi-Fi existed). Never treat that as "unplugged": `AutoTransport` re-opens USB while
  the port is enumerated, uses Wi-Fi only when the cable is gone (or the port is unusable for 10 s), and moves back
  to USB in place. The device answers over USB whenever the PC spoke over USB in the last 3 s (BUG-015).
- **Kimi:** k3 models reject `temperature`, sometimes wrap JSON in a list or code fence (`extract_json`), count
  hidden reasoning tokens as output (budget accordingly), and planning takes 18–38 s (watchdogs: host 150 s for
  THINKING, device 180 s).
- **Golden images** change whenever the UI does: render, *look at the PNGs*, then
  `verify_rlcd.py --strict --update-golden` (delete stale baselines first).
- `sdkconfig` keeps old values: after editing `sdkconfig.defaults`, delete `firmware/sdkconfig` before building.
- **Heredocs again:** a `\b` inside a bash heredoc'd Python patch landed in a regex as a literal backspace byte (the
  BUG-007 class). Patch scripts with backslashes go in files written by the editor tool, then scan for control bytes.
- **faster-whisper's `decode_audio` breaks with PyAV 19** (`metadata_errors` kwarg). The meeting importer decodes
  itself (`decode_to_pcm16`: `wave` for WAV, PyAV resampler otherwise); always pass numpy audio to Whisper.
- **Speaker features are noise-sensitive:** never normalise per meeting (one voice got split into 8); use the fixed
  within-speaker scale in `diarize.py` and re-run the Piper-voice tests in `tests/unit/test_meetings.py` after changes.
- **MFCC voiceprints split one person into several speakers** on real meetings (28 % same/other EER across
  meetings). Neural voiceprints fixed the features, but a fixed cosine merge distance still over-split short noisy
  lines into dozens of speakers: count speakers with NME-SC (eigengap), not a threshold (ADR-038). Score speaker
  changes on AMI (true labels), not only on the user's meetings - their saved labels began as the old method's
  output, so they flatter it.

---

## 9. Status and known gaps (keep this section current)

- Verified on hardware: display/animations, buttons, voice capture → Whisper → Kimi, Piper speech, spoken alarms,
  toasts, in-app OTA over USB (both slots) **and over Wi-Fi** (~30 s, PIP rejoins Wi-Fi ~9 s after reboot),
  the Wi-Fi link end-to-end (mDNS, HMAC handshake, wrong token rejected, screen capture, speech streaming,
  wake test), cable preference (8 min with both links up: zero link changes), wake-word detection ("Hi ESP",
  "Jarvis" via WAKE_TEST; live "Hi ESP" by the user), cost meter against the real Moonshot API.
- Cable pulled: the host moved to Wi-Fi 0.1 s later without a visible disconnect; PIP kept working on battery
  (screen, speech with 0 dropped chunks, link stable).
- Firmware 1.3.2 (space-station room, prop trips, short-legged board with COMING UP, one PIP during slides) on
  hardware via in-app OTA; after the reboot the host resynced on its own (header: local time, alarm, weather; board:
  today + coming up + date; `artifacts/rlcd/hardware/hw_idle_world_v132.png`).
- Firmware 1.4.0 (task-specific acts) on hardware: with the step "Put the tools or files…" (→ computer) PIP
  played free acts and, every third act, fetched the laptop and pointed at "Next: …" on the board
  (`artifacts/rlcd/hardware/hw_next_up_v140.png`).
- Firmware 1.5.1 (1.5.0 + potato battery): indoor reading steady (48/48 samples over 4 min, `env` 9 ok / 0 fail; before: 24/46 missing),
  hands on laptop keys and guitar, easter eggs; 254 s uptime, heap 36 KB.
- Firmware 1.7.0 (1.6.0 meeting recording, 10-min messages, time pie + cues, BOOT 2x park; 1.7.0 activity named
  after the wake word): see the hardware notes below. Host: meetings verified end-to-end with real faster-whisper on synthetic voices
  (12/12 lines attributed) and in the Playwright flow; a real-room meeting with real people is not yet tested.
- Firmware 1.7.2 (wake-word acknowledgement chimes over the live mic + "Got it" toast, 3.5 s / 5 s end-of-speech
  pause, KEY click sends, BUG-019) on hardware via in-app OTA over USB (ota_1): 150 s uptime, reset SW, heap 34 KB,
  0 dropped chunks after `/speech/say`, screen correct. The chimes over a live mic and the 3.5 s pause still need a
  real spoken wake-word test.
- Firmware 1.7.1 (laptop redrawn in 3/4 view with a visible screen; book/calendar held by their edges, BUG-018):
  on hardware (it was running before 1.7.2 replaced it).
- **Not yet verified on hardware:** an actual rollback (needs a deliberately broken image), hands-free recording
  end-of-speech timing in a real room, a slide transition and a full prop trip watched on the panel (needs a
  real button press / a minute of idle play; `simulate-button` is simulator-only).
- Packaged app (ADR-034) 1.0.0: `smoke_exe.py` passes (also `--gpu`: Whisper on cuda/float16 with the add-on DLLs),
  window + in-app restart, silent install/uninstall. **Not yet:** the installed PIP.exe linked to the board (the
  dev tray holds COM3; needs the switch-over with `--import-data`), the real 1.3 GB GPU pack download from PyPI.
- Local meeting summaries / Obsidian / questions (ADR-031/032): unit tests + Playwright against a fake Ollama, and
  tuned on two real meetings with Ollama 0.40 + qwen3:8b on the RTX 3070 (careful ~2 min per meeting). Quality is
  close to Kimi's but varies run to run (ADR-032). `test_voices_are_told_apart[voices2]` fails about 1 run in 4:
  Piper synthesis is random (noise sampling), not a diarization change.
- To exercise the app over Wi-Fi while the cable stays plugged in, start the host with `PIP_TRANSPORT=wifi`.
- Firmware 1.8.0 (ADR-035: several saved networks, away link with TLS) on hardware via in-app OTA: the 1.7 home
  network carried over into the saved list; 95 s uptime, reset SW, heap 35.6 KB (link buffers moved to PSRAM;
  1.7.2 had 33.7 KB). Away link on hardware (plain TCP, PC's LAN address, tray stopped): PIP dialed in 9.2 s after
  USB went quiet, DIAG + a 15 KB framebuffer through the sealed records, 40 s with 0 disconnects. The first 1.8.0
  build panicked at boot (DIAG over USB before `net_link_init` made its lock) and rolled back by itself.
  **Not yet on hardware:** choosing between two networks in range, a dial from a really foreign network, and TLS
  through a real Tailscale Funnel.
- Speaker detection (ADR-038): CAM++ voiceprints + NME-SC verified on AMI and on a copy of the user's database
  (upgrade of 7 meetings in 68 s, right count in 6 of 7). **Not yet:** a new real meeting recorded and checked by
  ear. Transcription: Parakeet-TDT-0.6B v3 (AMI far-field 34.8 vs Whisper's 46.3 % WER) is the meeting default
  (ADR-039), verified on 3 real meetings in a database copy. **Not yet:** the packaged PIP.exe rebuilt with onnx-asr,
  vocabulary boosting for Parakeet, the planned fine-tune on corrected meetings.
- Wake word: stock Espressif words only; a custom "Hey PIP" needs a trained model (paid service) or a PC-side
  detector (rejected by the user in favour of on-device privacy).
- Four old ruff findings in tests (SIM117 ×2, RUF015, RUF059) are pre-existing and harmless.
- Prices in `ai_cost.py` are list prices from Nov 2026 web sources (the highspeed cached rate is an assumption);
  the user can edit them in Settings.
