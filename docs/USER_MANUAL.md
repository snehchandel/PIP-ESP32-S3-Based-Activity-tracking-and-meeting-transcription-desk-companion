# PIP — User Manual

PIP is a small desk companion that helps you focus on **one thing at a time**. It has a reflective screen,
two buttons (**KEY** on the side, **BOOT** next to it), a microphone and a speaker. It works with the
**PIP Companion** app on your PC, and keeps working on its own when unplugged.

## 1. Getting started
1. Plug PIP into your PC with the USB-C cable.
2. Double-click **PIP Companion** on your Desktop (or Start menu). The app opens and a PIP icon appears in the
   system tray (bottom-right). PIP's screen shows **LINKED** at the top within a few seconds.
3. Optional: right-click the tray icon → **Start with Windows** so PIP is ready every time you log in.
4. To close PIP completely: right-click the tray icon → **Quit PIP**.

## 2. Reading the screen
- **Top bar:** clock · LINKED (talking to your PC) or **OFFLINE** (working on its own) · 🔔 next alarm ·
  🏠 inside temperature and humidity (PIP's own sensor) · ☀/☁/🌧 outside weather in °C with humidity (from the PC).
  The inside reading can run a few degrees warm because the sensor sits next to PIP's electronics.
- **Left:** PIP itself. Its mood shows what's going on (ready, listening, thinking, working, paused, done, alarm,
  sleeping) and it's alive: it blinks, glances at the text when something changes, looks around, hops when a step
  is done, sips its drink while paused, and breathes slowly when asleep — at random moments, smoothly.
- **Right:** the important thing right now (timer, step, agenda, alarm or question).
- **Black bar at the bottom:** what the buttons do on this screen, plus link and battery.

## 3. Buttons
| | What it does |
|---|---|
| **KEY click** | Start / pause the timer. On "Step Done!": start the next step. On an alarm: snooze 5 min. |
| **KEY double-click** | Show today's agenda / go back. On an alarm: dismiss. |
| **KEY hold** | Leave a voice message: first pick what it's about, then hold again to talk (see 4). Needs the PC. |
| **BOOT click** | Mark the current step done. On "Step Done!": take a 5-min break. On a question: confirm. |
| **BOOT hold 1.2 s** | **Cut the step in half** when it feels too big. Nothing is lost — the rest becomes the next step. |

## 4. A typical session
1. **Voice message.** Hold **KEY** — PIP asks **"What's it about?"**:
   **Calendar** · **Brain dump** · **Focus** · **Alarms**. Click KEY to move the highlight, then **hold KEY** and
   speak; release to send (up to 60 s). BOOT goes back. (You can also type it in the app's **Brain Dump** page and
   pick the same four topics there.)
   - *Brain dump:* everything on your mind — PIP picks one task to do now and parks the rest.
   - *Calendar:* "Dentist Thursday at 2", "move gym to Friday morning".
   - *Focus:* "pause", "I need a break", "this step is too big".
   - *Alarms:* "wake me at 6:30 every weekday".
2. Kimi breaks the task into 3–6 concrete steps in your own situation (the first is a 2-minute starter), gives it a
   short name that fits PIP's screen, parks side thoughts for later, and sets alarms. Planning takes ~20–40 s.
3. Click **KEY** to start the 2-minute starter. Click **BOOT** when done. Repeat.
4. Vague times like "Friday afternoon" are never set silently — PIP asks **Confirm Time**: BOOT to confirm,
   KEY to keep it as a parked note instead.

## 5. The Companion app
- **Today:** focus timer, steps (Alt+↑/↓ to reorder), today/tomorrow, parked tangents (Promote / let go).
- **Calendar:** Month / Week / Day. Week and Day show the hours of the day; click any hour to add a task or
  reminder at that time. Click an item to move it, change its time, make it "anytime", or delete it.
- **Brain Dump:** review and edit a plan before saving it.
- **Focus:** the cut-in-half preview.
- **Alarms:** one-time or weekly alarms; sound can be a chime or PIP's voice (Piper). **Test on device** rings
  PIP right away; a test closes by itself after **30 seconds** and never uses up the real alarm.
- **Device:** a live copy of PIP's screen and battery/health info.
- **Settings:** Kimi API key (see below), speech status, voice picker and "Play on PIP" voice test.
- Keyboard: **Space** start/pause · **N** brain dump · **S** cut in half · **1–7** switch views.

## 6. Kimi AI (required for planning)
PIP uses Kimi to break tasks into steps. Set it up once: **Settings → Kimi API key → paste → Test this key →
Save key**. The key is kept in Windows Credential Manager; the app shows only its last 4 characters. The model is
picked automatically (newest available); you can pin one under **Kimi model**. Your brain-dump text is sent to
Moonshot for planning.

If Kimi can't be reached, PIP flashes **"AI has left the device"** and waits. Press any button to dismiss — your
words are not lost: they're saved as a parked note you can promote later.

## 6b. Error screens
If anything goes wrong or gets stuck (for example "Planning…" never finishes), PIP shows a ⚠ error screen with a
short explanation instead of freezing, flashing briefly to get your attention. **Press any button to dismiss.**
The same message appears in the app with a Dismiss button. Details are written to `data/logs/errors.log`.

## 7. Unplugged (offline) use
PIP keeps counting, lets you finish/cut steps, and rings alarms it already knows about. The top bar says
**OFFLINE**. Voice needs the PC. When you plug back in, everything you did is synced automatically.
After 15 idle minutes offline PIP rests (sleep screen); press any button to wake it.

## 8. Troubleshooting
- **Screen says OFFLINE while plugged in:** open PIP Companion (tray icon must be running).
- **"Connect PC for Voice":** voice needs the app running and the cable connected.
- **Voice not understood:** speak after the Listening screen appears; check Settings → Speech-to-text = Ready.
- **"AI has left the device":** check Settings → Kimi API key → *Test saved key*, and your internet connection.
- **Weather missing:** Settings → Temperature & weather → pick your city.
- **Logs:** `data/logs/pip.log` (everything) and `data/logs/errors.log` (only problems).
  **Restore Waveshare demo firmware:** see README.
