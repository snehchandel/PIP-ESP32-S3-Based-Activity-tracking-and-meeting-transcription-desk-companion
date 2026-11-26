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

## ADR-023 — Board shows what's coming up; host resyncs a rebooted PIP; one PIP during slides
User report after 1.3.0: the Let's Focus board was "missing future tasks" and the header was wrong.
- **Root cause (BUG-016):** after the OTA reboot USB reconnected inside `RECONNECT_GRACE_S`, so the host never saw a
  link-down/up and never re-sent UI_UPDATE / CALENDAR_SYNC / DEVICE_CONFIG. PIP ran blank: clock in UTC (no
  `tz_offset_min`), no next alarm, no outdoor weather, empty agenda. Any quick USB-side reboot did the same.
  Fix: `DeviceLink` resyncs when the heartbeat `uptime_s` goes backwards (restart: also re-sends DEVICE_CONFIG) or
  the heartbeat `state_rev` lags the host revision for 3 s; at most once per 3 s. Verified live: "device restarted:
  resyncing state" 3 s after an OTA, screen complete without any manual step.
- **Future tasks:** CALENDAR_SYNC gains `upcoming` (open items of the next 7 days, soonest first, max 6:
  `day`/`hhmm`/`title`/`kind`), separate from `upcoming_alarms` (offline ringing). The board shows TODAY's open items,
  then COMING UP (at least one row whenever there is something), "+N more" per section, the date if room is left.
  Older firmware ignores the new key.
- **Seamless slides:** a sliding page used to carry its own PIP, so mid-slide two PIPs could show. Pages now render
  without PIP and the single animated PIP is drawn on top at its home spot (the same on every screen).
- **Flying props from the hand:** a kite, a tossed ball or a kicked ball used to appear in the air / on PIP's head at
  the first frame of an act although the prop trip had delivered it in PIP's hand. They now leave from the real
  hand position (`from_hand`, via the rig) and return to it; `test_ui` checks every act's first and last frame.
  Firmware 1.3.2.

## ADR-024 — PIP acts out the task at hand
User request: animations on the activity (focus) and other screens must be specific to the task at hand rather than
random picks from a library.
- **Classification on the PC, not by Kimi:** `planner/activity.py` maps a step title (then its task title) to one
  of 14 activities with keyword rules; the *earliest* keyword wins because step titles lead with their verb ("Create a
  task for going to bed" is planning, not sleep). Free, instant, offline, works for steps planned before this change.
  UI_UPDATE carries `activity` (step in progress), `next_activity` (so an offline step advance keeps it right) and
  `done_activity` (the step-done screen shows what was finished; at STEP_DONE the host's active step is already the
  next one). Unknown names fall back to "general".
- **Scene tags:** acts got a tag mask; `mascot_set_scene(mode, tags)` filters the library. Focus: each activity has
  its own acts (writing notes / typing, reading, on the phone, sweeping, workout / stretch, cooking, watering, guitar /
  dancing, wrench / building, calendar, errands with a shopping bag, winding down; general = the old cheer-you-on
  acts). Pause, done and the idle "next up" preview are one parameterised act each (`k_wait`, `k_done`, `k_ready`)
  using the activity's props (`GEAR[]`). Listening follows the voice picker (calendar, notes, ear, alarm clock);
  thinking is transcribing (headphones at the laptop) then planning; the break plays its own on-screen cue in order.
  Agenda, alarm, confirm, sleep and error were already specific.
- **New props:** phone, frying pan (pancake flip / stirring with steam), shopping bag.
- **Continuity:** an activity change restarts the act and the prop trip fetches the new things; when only the
  mirror side differs PIP keeps its props where they are (the engine flips the act's direction instead of moving them).
- **Tests:** every activity gets only its own acts for 30 min on focus, pause and done; switching activity switches
  at once; listen/think/break/idle-preview rules; UI_UPDATE parsing; classifier table (pytest). Firmware 1.4.0.

## ADR-025 — Easter eggs, hands that touch what they use
- **Easter eggs:** the user asked for homages to well-known film/game robots and a game's potato. We do not draw
  other works' characters, even simplified, so the eggs are PIP's own family instead: "PIP Mk.0" (a wind-up tin toy
  with a turning key, accordion arms and a grille mouth) and "PIP-1960" (a cabinet computer with tape reels, status
  lamps and a printer that hands you "HI!"), swapped in behind a smoke puff (`pose.form`, `pose.puff`); and when PIP
  is upset on the error screen it sometimes hurls a potato off the screen and dusts off its hands. The potato is a
  science-fair potato battery (copper + zinc electrode, wire, tiny bulb) worn with a monocle on a chain and a bow
  tie - a posh spud with no face: the bulb flickers, PIP shakes it, the bulb flares and dies, the spud goes flying
  (1.5.1). Rarity: a
  roll in `start_perf` (idle ~1 in 24, error 1 in 3), never twice within 2 h, never on the focus screen. The potato is
  fetched from the edge by a prop trip like every other prop.
- **Grip:** the rig used to swing arms only outward, so the hands floated beside the laptop and the guitar.
  `pose.grip` now pulls the hands onto the object (keyboard deck with alternating taps, guitar neck + strings with a
  strum), arms drawn in front, a gripped laptop drawn under the arms; the guitar is strapped to the body instead of
  hanging between the hands. Tests check the hand positions. Firmware 1.5.0.
- **Laptop + held props (1.7.1, BUG-018):** the laptop stands beside PIP in a 3/4 view with its screen turned toward
  you (`mascot_laptop()`, shared by rig and renderer); book and calendar are held by their edges (`held_c`).

## ADR-026 — Meeting recordings with speakers, transcribed on the PC
- **Device:** a 5th voice-picker option "Meeting" (AUDIO_START activity 4, `max_sec` 0 = no limit) puts PIP in
  `UI_STATE_MEETING` / screen `14_meeting` (REC dot, h:mm:ss, level). Only a KEY hold ends it (clicks just explain
  how), the host's UI_UPDATE never changes the state, a running focus timer is paused, sleep and the stuck watchdog
  don't apply, and a PC link drop keeps it recording for 2 min before it stops itself. No new frame types.
- **Host:** `meetings/service.py` appends every chunk to `data/meetings/<id>.wav` (nothing held in RAM; chunk-seq
  gaps from link drops are filled with silence so timestamps stay true; a host crash is repaired at startup).
  A worker thread with its **own** faster-whisper instance (voice commands never queue behind a meeting; unloaded
  when idle) transcribes in 10-min windows cut at the quietest moment, VAD splitting at 0.5 s pauses so segments
  follow turns. Date/time/duration are stored; the title comes from the calendar item around the start time.
- **Speakers:** pyannote/speechbrain need torch, a token and a model download, so `meetings/diarize.py` uses numpy
  only: per segment MFCC mean/std + delta std + pitch median/IQR, scaled by a fixed per-feature within-speaker
  spread (floored at 0.1 so noise-driven high cepstra don't dominate), average-linkage clustering stopped at RMS
  distance 1.75, tiny groups (<2 lines/3 s and <8 s) absorbed. Tuned on synthetic meetings from the 4 Piper voices:
  1-4 speakers counted right in 29-30 of 30; real faster-whisper on a 3-voice meeting attributed 12/12 lines.
  Naming a speaker (with "remember") stores the raw feature centroid as a voice profile; later meetings label the
  closest cluster within distance 1.45. Similar real voices can still merge: the app allows per-line reassignment,
  merge, add, rename and re-detection with a known speaker count. A neural embedding model could replace the
  features later behind the same interface.
- **Kimi:** optional "Summarize" (title, summary, decisions, action items; metered) and "Park action items".

## ADR-027 — Longer voice messages, time cues, parking, sharper steps, calendar drag
- **10-minute messages:** PTT watchdog 60 s -> 10 min, hands-free limit 25 s -> 10 min with a 2.5 s end pause after
  20 s of speech, host buffer 600 s; watchdogs: device LISTENING 11 min, TRANSCRIBING/THINKING 7 min; host
  LISTENING 660 s, TRANSCRIBING 420 s, THINKING 300 s; Kimi HTTP timeout 120 s (a 90 s ReadTimeout had parked a
  brain dump).
- **Time cues:** focus/paused screens draw a shrinking pie in the stage corner; device-local chimes 7 (soft, "5
  minutes left", steps >= 8 min) and 8 ("Time to wrap up" at 1 min, steps >= 3 min), played at lower volume, with a
  toast and PIP turning to the user. Offline-safe because the device decides.
- **Parking:** BOOT now has a double-click (its click waits out the 300 ms window like KEY's). BOOT 2x / "Park for
  later" archives the task, keeps its steps and remaining time, and creates a parked note pointing at it
  (`parked_tasks.task_id`); promoting that note resumes the same task. A parked *thought* is now broken into steps by
  Kimi (activity "TASK") instead of the generic templates that produced "Put the tools or files for ..." steps;
  if Kimi fails the note stays parked (HTTP 502). Calendar quick-adds keep instant placeholder steps that Kimi
  replaces in the background while the task is untouched.
- **Sharper steps:** the prompt makes Kimi work out where the task happens and what is involved, include travel for
  errands, use the user's own nouns, and pick a per-step `activity` (stored in `steps.activity`, preferred over the
  keyword classifier for what PIP acts out). Generic filler steps fail validation (one repair retry).
- **Calendar:** tasks and reminders drag to another time/day; tasks resize from either edge (15-min snap,
  `tasks.block_min` overrides the steps' total). Firmware 1.6.0.

## ADR-028 — Name the activity after the wake word (recognised on the laptop)
- **Ask:** "Hi ESP… Meeting" should start a meeting without touching a button. Options: ESP-SR MultiNet on the
  device (instant, offline, but another model in flash and RAM we don't have: ~36 KB internal free) or Whisper on
  the PC. The user chose the PC: only the seconds after the wake word go there, which already receives every voice
  message, so privacy is unchanged.
- **Flow:** the first wake word starts a hands-free stream at once with activity 5 (AUTO). The host transcribes the
  first <= 4 s at 1.6 s and every 0.5 s after; `spoken_activity.parse` accepts a name only at the start and standing
  alone (followed by punctuation = a pause, or end of text with a quiet tail) so "Meeting with Bob at 3" stays a
  brain dump. Talking 3+ words / 3.5 s without a name = brain dump. The decision goes to PIP in UI_UPDATE
  (`voice_stream`, `voice_activity`); PIP shows the activity, restarts its end-of-speech clock, and for MEETING
  turns the same stream into the meeting (the host moves the audio heard so far into the recording, so nothing is
  lost). The name is stripped from the message before Kimi sees it.
- **Silence:** no speech for 3 s after the wake word -> PIP cancels the stream (AUDIO_END reason 2, host discards
  it) and shows the picker, where the wake word again works as before. While undecided PIP waits 4 s of silence
  before sending (the decision normally arrives ~1 s after the name). No new frame types. Firmware 1.7.0.
- **Acknowledgement + longer pause (1.7.2, BUG-019):** the user got no sign the activity was heard or that PIP was
  recording, and a short pause ended the message. Chimes queued during capture used to wait until the mic closed;
  now the audio task plays the "heard you" (CONFIRM, on the wake word) and "go ahead" (START, when the activity is
  decided) chimes *over the live mic*, 20 ms at a time between mic reads (`audio_chime_fill` +
  `audio_write_mono_duplex`), so no speech is lost; the VAD ignores those frames plus ~200 ms of echo. Other chimes
  still wait. The decision also shows "Got it: <Activity> - go ahead" for 4 s. Hands-free messages now end after a
  3.5 s pause (5 s once 20 s were spoken; undecided 5 s), and a KEY click sends at once (bar: "Pause or press KEY
  to send"). Configurable pause length was left for later.

## ADR-029 — Repair step lengths, start times with nudges, reminders that ping, personal vocabulary
- **Seen on hardware:** "Hi ESP, focus… in the next 10 minutes, the CASL consent metrics for Priya" failed twice in
  validation: Kimi treated "next 10 minutes" as a time budget and made 4-minute steps, which the 5-25 min rule
  rejected -> "AI has left the device" for a good plan. Whisper also heard "CASL" as "castle".
- **Repair, don't reject:** `ActiveTask` keeps the strict structural checks (3-6 steps, concrete starter, no
  headings/filler) but clamps durations (starter 2-5, others 5-25) and fixes the starter flag.
- **Start time:** `ActiveTask.start_local`; the prompt says "in 10 minutes"/"at 2" is when the user starts, never a
  limit. The task gets that date + `start_hhmm` (still the active task, timer waits for KEY). The FOCUS rule now
  creates the named task instead of preferring to park it. Promoting a parked note keeps a start time.
- **Nudges:** reminders never notified before (calendar only). `alarms/nudges.py` checks each second for reminders
  due and tasks whose start time came (within 2 min, so a restart doesn't replay old ones) -> toast
  "Reminder: ..." / "Time to start: ...", confirm chime and Piper speech on PIP.
- **Vocabulary:** Settings "Words PIP should know" (prefs `vocabulary`) -> faster-whisper `hotwords` for voice and
  meetings, and "My words:" in the Kimi request with an instruction to fix mis-hearings from context.

## ADR-030 — Today drag and drop; start nudges never interrupt focus
- **Drag and drop (Today page):** rows of Today/Tomorrow and Parked tangents are HTML5-draggable; `POST
  /agenda/move` (task -> another day, setting down the task in progress with its time left; reminder and one-time
  alarm keep their time of day; weekly alarms refuse) and `POST /agenda/park` (task keeps its steps via
  `parked_tasks.task_id`; a reminder/alarm becomes a parked note). A parked item dropped on Today is promoted.
  Every drag has a button equivalent for keyboard users.
- **Conflicting start time (seen in use):** a task's start time came while the user was mid-step on another task,
  and PIP spoke over it. `NudgeScheduler` now holds a start nudge while a timer runs on a different task and says it
  once at the next natural break ("Next: ... (09:29)"); no start nudge for the active task once begun. Reminders
  still ping on time (hard times). Nothing is switched for the user.
- **Also:** a task added while another is in progress now gets a toast "Added to today: ..." (it used to land
  silently); a spoken activity name heard without a pause ("Focus I want to...") wins over the brain-dump default.

## ADR-031 — Meeting summaries on the PC (local AI), Obsidian vault, questions by retrieval
- **Ask:** summaries made locally by default once a transcript is ready; meetings in Obsidian so notes link to each
  other; easy, token-efficient questions and task harvesting across meetings; a clear answer to "what happens when a
  transcription and a summary are due at the same time".
- **Local AI = Ollama** (`meetings/local_ai.py`, default `qwen3:8b`, prefs `local_ai_model`, URL
  `PIP_LOCAL_AI_URL`). Every call asks for JSON matching a schema (Ollama structured outputs, `think: false`,
  `num_ctx` 8192), so a small model can't break the format. Tokens are metered as `local/<model>` at $0. The user
  installs Ollama and clicks *Download model* in Settings (`POST /settings/local-ai/pull`); PIP never downloads by
  itself. This is not planning: Kimi stays the only planner (ADR-013). A failed local summary is shown as failed,
  never silently redone by Kimi; Kimi summaries/answers are per click (or the "Summarise with Kimi" setting).
- **Map-reduce** (`meetings/summarize.py`): transcripts up to ~20k chars (~30 min) in one call; longer ones in
  ~12k-char parts at speaker turns -> a few lines of notes each -> one merge call that reads only the notes. Keeps
  every call inside an 8B model's context on an 8 GB GPU and makes the job pausable.
- **Scheduling** (one worker thread, `MeetingService._run`): transcriptions always first; local summaries in their own
  queue after them. Between two parts a summary yields (`Yielded`) when a transcription is queued or a voice command
  is being heard/transcribed (`manager.overlay` LISTENING/TRANSCRIBING, bounded by the stuck-state watchdog; the
  summary waits at most 5 min for it), keeping finished parts in memory. Only one big model holds memory at a time:
  the meeting Whisper model is unloaded before a summary, the Ollama model (`keep_alive: 0`) before a transcription.
  A host restart re-queues summaries that were QUEUED/SUMMARIZING (parts are redone). Kimi summaries are remote and
  run at once.
- **Obsidian** (`meetings/obsidian.py`, prefs `obsidian_vault` / `obsidian_folder`): per meeting a small note
  (frontmatter: date, attendees, topics, open_actions, transcript, pip_id; `[[people]]` only for named speakers,
  `[[YYYY-MM-DD]]` daily note, topics from the summary + the user's vocabulary) and a separate transcript note;
  plus `Meetings index.md`, `Action items.md`, `_About these notes.md`. A note is written once its summary is
  settled (so it is born with its final title), rewritten on any change, renamed with the meeting if the new name
  is free. Text under the `%% PIP ... %%` marker and ticked checkboxes are preserved; ticks flow back as
  `action_items[].done`. Deleting a meeting leaves its note (it may hold the user's writing). The Markdown download
  is the same note with the transcript inline.
- **Questions** (`meetings/ask.py`): SQLite FTS5 (`meeting_fts`, migration 007: one row per speaker turn + summary
  parts, porter stemming, bm25 with summary parts weighted 1.6x) finds passages; no hit -> answer without any model
  call; else the hits +- one turn, grouped per meeting with its summary, capped at 6,000 chars, go to one call that
  cites `[Meeting @ mm:ss]`. Local by default, Kimi on request. `GET /meetings/search` (no AI), `POST
  /meetings/ask`, `GET /meetings/actions`; park-actions parks each action item once (`parked`).
- **Choosing the model** (`meetings/models.py`): Ollama has no API to browse its online library, so Settings shows a
  curated catalog (17 general chat models, 1.4-20 GB, that follow a JSON schema; reasoning-only models whose thinking
  can't be turned off, like gpt-oss, are left out) plus anything already downloaded and a free-text name for any
  other. Each entry is matched to the PC (NVIDIA GPU memory via `nvidia-smi`, RAM): gpu / mixed (Ollama splits GPU +
  RAM) / cpu / too_big; the recommendation is the best that fits the GPU, else a <= 3.5 GB model. The user decides:
  `GET /settings/local-ai/models`, `POST /settings/local-ai/pull {model, use}` (switches when the download
  succeeds), `DELETE /settings/local-ai/models?name=` (never the model in use). `think: false` is sent so reasoning
  models answer directly; a model that rejects the switch (HTTP 400) is asked again without it and remembered.
- **Outside AI tools:** for deep cross-meeting analysis (trends, "what did we promise the client across November",
  harvesting tasks) point an assistant such as Claude Code at the vault folder: index -> notes -> transcripts only
  when needed. Next step if this is used a lot: a small MCP server over `/meetings/search`, `/meetings/actions` and
  park-actions so assistants query the index instead of reading files, and create tasks through PIP.

## ADR-032 — Local summaries tuned toward Kimi quality; action items you decide on; archived meetings
- **Measured gap (qwen3:8b vs kimi-k3 on real meetings):** decisions repeated action items; detail lost across
  4 parts; topics only from the first half; placeholders ("Not specified"); the main conclusion missed.
- **Fewer parts:** Ollama runs with `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` (user environment), so a
  16k context fits qwen3:8b fully on the 8 GB GPU (measured 5.85 GB); `num_ctx` is sized to each prompt. Up to ~10k
  transcript tokens (~1 hour) are read in one pass; fillers/stutters are stripped (`tidy`); 4.2 chars/token.
- **Prompt:** one shared system prompt with strict definitions (decision vs action item, cue words, owner rules, no
  invented facts), placeholders instead of example names (a named example leaked into a real summary), the
  transcript marked in ~5-minute sections with key points required from every section, fields written in order
  (key points -> topics -> decisions -> action items with `said_at` -> outcome -> summary -> title). New fields:
  `key_points`, `outcome`, `action_items[].said_at`.
- **Careful mode (default; Settings "Summary quality"):** main pass with thinking; a commitments scan sharing the
  same prompt prefix (Ollama reuses the cached prefix); every decision/action item checked in batches of 8 against
  the 2 minutes of transcript where it was said (scan-only items must be confirmed, main-pass items survive a failed
  check; lists capped at 12 actions / 8 decisions); a final write-up of outcome + summary from the checked notes and
  the last ~5k characters. Code removes placeholders, statements posing as tasks/decisions ("X confirms ...",
  "The printer issue ..."), "no decision was made", duplicates; broken JSON is retried once. Sampling: 0.2 / top_p 0.85
  without thinking, Qwen's 0.6 / 0.95 / top_k 20 with it (greedy decoding loops). About 2 minutes per meeting
  (fast: about 40 s).
- **Result on the Kimi-reference meeting (careful, several runs):** key points span the whole meeting, the meeting's
  main conclusion appears in most runs (was 0/2), Kimi's three action items are each found in most runs, owners
  corrected. Still below Kimi: run-to-run variance, occasional facts listed as decisions. Next levers: qwen3:14b
  (GPU + RAM, ~3x slower) or a hybrid (local notes -> Kimi write-up).
- **The user's Google suggestions, checked:** explicit num_ctx, flash attention + q8_0 cache, Q4_K_M, temperature
  0.1-0.2 / top_p 0.85 and two-pass chunking were adopted (chunking only above ~1 hour, where an 8B model loses the
  middle); a Modelfile is not needed (options go per request); repeat_penalty was not used (it can corrupt JSON);
  thinking off everywhere was rejected for quality - it stays on for the main, check and write-up steps.
- **Speech:** CUDA 12 cuBLAS + cuDNN 9 wheels (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) are put on the DLL path by
  `speech/stt.py`, so faster-whisper runs on the GPU (`small.en` loads in 1.7 s). Meetings use `large-v3-turbo` on
  the GPU when it works (a 5-minute meeting in 5.5 s, fewer dropped and mis-heard words), else `small.en` on the CPU
  (Settings "Meeting speech-to-text", prefs `meeting_stt_model`).
- **Action items (`meetings/actions.py`, `due.py`):** deadline words -> a date relative to the meeting's own date
  (code, not the model; soft deadlines flagged `due_exact=false`); `mine` from Settings "Your name in meetings" (else
  the named voice in most meetings). Each item is `new` until the user picks: task (on its date), reminder (date +
  time, 09:00 default), parked, or "not for me"; one at a time or ticked in bulk (yours pre-ticked). Undecided items
  with a date show on the Calendar as dashed "from meeting" blocks (yours + unowned; others' behind a toggle), can be
  dragged to another day and decided there; decided ones become real tasks/reminders (no duplicates). Obsidian
  lines carry `📅 YYYY-MM-DD` (Tasks plugin) and what the item became. Why not "park all": a meeting yields other
  people's commitments too, and for an ADHD planner the useful question is "which are mine, and when"; other
  people's items are better as follow-up reminders than as tasks.
- **Archive:** `meetings.archived` (migration 008). Archived meetings keep transcript, summary, audio and note but
  leave search/questions, action lists, the calendar and the Obsidian index (the note gets `archived: true`);
  restore any time.

## ADR-033 — Cleaner transcripts: no fillers or stutters, beam search on the GPU, silence phantoms dropped
- **Measured on real meetings:** the old `small.en` (CPU, greedy) transcripts had few "um"s (Whisper drops most) but
  27 repeated words ("The the", "I, I", "no, no, no, no, no, no, no") and comma-wrapped fillers (", you know," x23);
  `large-v3-turbo` keeps more hesitations ("uh", "we we've"). On a 5-minute meeting the old pipeline produced 550
  words, the new one 810 - `small.en` had been dropping about a third of the speech.
- **Clean-up (`speech/cleanup.py`, on by default, Settings "Remove filler words"):** removes hesitation sounds
  (um, uh, er, ah, hmm, mm-hmm; a line of only that is dropped), stutters/repeats ("the the", "I, I", "no, no, no"
  -> one; not "had had" or "that that's"), and fillers only when set off by commas (", you know,", ", I mean,",
  ", like,"); restores the vocabulary's spelling ("sfmc" -> "SFMC"). "kind of" / "sort of" / bare "like" stay (often
  real words). Meeting lines keep the original in `meeting_segments.raw_text` (migration 009) when it changed;
  `POST /meetings/clean-transcripts` cleans older transcripts in place (originals kept, idempotent). Voice commands
  are cleaned before they go to Kimi. The summarizer's `tidy` is the same function.
- **Decoding:** beam search 5 on the GPU (measured: cleaner sentences and punctuation, false starts dropped, longer
  segments, ~25 % slower: 6.8 s vs 5.4 s for 5 minutes), greedy on the CPU. Missing full stops at line ends (common
  with turbo) are added when the next line starts a sentence (`end_sentences`).
- **Phantoms:** segments Whisper itself marks as probably not speech (no_speech_prob > 0.6 with low confidence), and
  the classic caption phantoms ("Thank you.", "Thanks for watching", "you") when no_speech_prob > 0.4, are dropped.
- **Not done (ideas):** word-level timestamps to split a line at a speaker change; a larger model for voice commands
  (turbo would sit beside the 8B summariser in 8 GB of VRAM); fuzzy vocabulary correction ("castle" -> CASL) is left
  to Kimi/the summariser, because a wrong automatic replacement in a transcript is worse than a mis-hearing.

## ADR-034 — PIP as its own Windows app: PIP.exe + installer, GPU speech as an add-on
- **Why:** PIP only ran from the repository checkout and its 3.1 GB `.venv` (shortcuts pointed at `pythonw.exe` and a
  script). The user wanted one program that starts its own services.
- **Packaging:** PyInstaller **one-folder** build (`tools/pip.spec`, entry `host/pip_app.py`). A one-file exe would
  unpack ~300 MB to a temp folder on every start. `tools/build_exe.ps1` builds the UI, the exe, runs
  `tools/smoke_exe.py` and makes the installer.
- **Files (`service/paths.py`):** files that ship with the app (UI, migrations, icon, the firmware image) come from
  the bundle. The user's data lives in `%LOCALAPPDATA%\PIP` when packaged and in `data/` from the repository, as
  before. `PIP_DATA_DIR` overrides both. `PIP.exe --import-data <old data folder>` copies an existing folder once
  (SQLite backup, absolute paths into the old folder rewritten); it never overwrites a database.
- **Window (`service/desktop.py`):** pywebview (WebView2) gives PIP its own window and taskbar entry instead of an
  Edge `--app` window. Closing the window hides it; Quit is in the tray. One PIP per port (a named mutex); starting
  it again shows the running window (a named event). Without WebView2 it falls back to the browser.
  `tools/pip_tray.pyw` now runs the same module from the repository.
- **GPU speech add-on (`speech/gpu_pack.py`):** the CUDA 12 cuBLAS + cuDNN 9 DLLs (~2 GB unpacked) are not bundled.
  Settings -> GPU speech (shown when an NVIDIA GPU is found), or the installer's "GPU speech" box
  (`PIP.exe --install-gpu`), downloads NVIDIA's wheels from PyPI. Their versions and SHA-256 are pinned in the code,
  and only the DLLs are unpacked into `<data>/gpu`. Takes effect after a restart (`POST /app/restart`).
  Rejected: always bundling CUDA (a 2.5 GB installer for CPU-only PCs) and CPU only (meetings far too slow).
- **Whisper models:** the packaged app keeps them in `<data>/models`. On first use it copies a model the PC already has in
  the Hugging Face cache instead of downloading it again. Settings shows "DOWNLOADING (n MB so far)" meanwhile.
- **Installer (Inno Setup, `tools/installer/pip.iss`):** per user (no admin prompt; all users via the dialog),
  Start menu + optional Desktop and Start-with-Windows shortcuts. The uninstaller keeps `%LOCALAPPDATA%\PIP`.
- **Ollama is left alone** (user's choice): PIP only talks to an Ollama the user runs.
- **Not done:** code signing (SmartScreen warns on first run), the app updating itself (install the new version
  over the old one).

## ADR-035 — Away link: PIP calls the PC from other networks; several saved Wi-Fi networks
- **Why:** PIP only worked on the PC's own network (the PC dials PIP's LAN address). The user wants PIP on another
  Wi-Fi (office, phone hotspot) while the PC stays at home.
- **Options weighed (user chose 1):** (1) PIP dials **out** to the PC's public address; (2) both sides connect to a
  public MQTT broker (third party sees metadata, monthly data caps, ~115 MB per hour of audio); (3) a relay server the
  user hosts. (1) needs no third party in the data path; the PC is made reachable by Tailscale Funnel or a port forward.
- **Networks:** up to 5 saved (`dev_settings.c`, portable + `test_settings`): newest first, the strongest visible one
  wins (each failed join costs 15 dB so a wrong password does not lock PIP on), unseen ones are tried in turn (hidden
  SSIDs). Slot 0 keeps the old NVS keys, so 1.7 boards keep their network. Adding or forgetting a network does not
  drop the current connection unless it was that one. DEVICE_CONFIG: `wifi` (add), `wifi_forget`, `wifi_clear`.
- **When PIP dials:** not while the PC uses the cable (USB frames in the last 3 s), not while a LAN client is
  connected, and only after 10 s without either (`AWAY_QUIET_MS`), so at home the LAN link keeps winning. Backoff 2 s
  doubling to 60 s on failure. A sealed session silent for 30 s (the PC heartbeats every second) is redialled; the PC
  takes the newest authenticated connection in place (`AutoTransport`, kind `WIFI_AWAY`). DEVICE_CONFIG
  `remote:{host,port,tls}` is sent on every link-up (empty host = off).
- **Security:** the internet sees this port, so both sides prove the link token (provisioned over USB only):
  PIP's challenge, the PC's HMAC + its own nonce, PIP's domain-separated HMAC. Session keys per direction from both
  nonces; every frame is one AES-256-GCM record with a counter IV, so replayed, reordered or altered bytes end the
  link. No forward secrecy: whoever steals the token can read recorded traffic (same trust as the LAN link). At most
  4 handshakes at once, 5 s each.
- **TLS:** Tailscale Funnel routes by SNI, so plain TCP cannot pass. With `tls` PIP wraps the stream in TLS to the
  public name (esp-tls, built-in CA bundle) and the PC runs `--tls-terminated-tcp`; the records inside are unchanged.
  mbedtls now allocates in PSRAM (`CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC`): its 16 KB record buffers do not fit beside
  Wi-Fi + WakeNet in internal RAM. Reads and writes of the TLS context share the tx lock (mbedtls is not safe for both
  at once); the reader polls the socket unlocked first.
- **Rejected:** encrypting the LAN link too (would break older firmware against a new host; the LAN stays as ADR-019),
  TLS-PSK (Python's PSK support is 3.13-only and Funnel needs a real certificate anyway).
- **Verified on hardware:** the dial, handshake and sealed records (plain TCP over the LAN). **Not verified:** the TLS
  path through a real Funnel, a dial from a foreign network, picking between two networks in range.

