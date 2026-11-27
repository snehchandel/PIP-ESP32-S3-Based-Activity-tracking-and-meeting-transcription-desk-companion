# PIP — User Manual

PIP is a small desk companion that helps you focus on **one thing at a time**. It has a reflective screen,
two buttons (**KEY** on the side, **BOOT** next to it), a microphone and a speaker. It works with the
**PIP Companion** app on your PC, and keeps working on its own when unplugged.

## 1. Getting started
1. Plug PIP into your PC with the USB-C cable.
2. Double-click **PIP Companion** on your Desktop (or Start menu). The app opens and a PIP icon appears in the
   system tray (bottom-right). PIP's screen shows **LINKED** at the top within a few seconds.
3. Optional: right-click the tray icon → **Start with Windows** so PIP is ready every time you log in.
4. To close PIP completely: right-click the tray icon → **Quit PIP**. Closing the window only hides it: PIP keeps
   running in the tray (alarms, the link to PIP). Opening **PIP Companion** again brings the window back.
5. With an NVIDIA graphics card: **Settings → GPU speech → Download GPU speech** (one-time, ~1.3 GB), then
   **Restart PIP**. Speech-to-text and meeting transcripts become much faster.

PIP Companion is installed with **PIP-Setup-<version>.exe**. Your tasks, settings, voices and meetings are kept
in `%LOCALAPPDATA%\PIP` and survive uninstalling and updating (to update, install the new version over the old).

Starting from a terminal, restarting, and checking that it runs: see **9. Starting, restarting and checking the
host**.

## 2. Reading the screen
- **Top bar:** a big clock · 🔔 next alarm · 🏠 inside temperature and humidity (PIP's own sensor) · outside
  weather in °C with humidity (from the PC). The weather icon matches the sky and moves: spinning sun, moon and
  stars at night, sun or moon peeking past a cloud, drifting clouds, falling rain or drizzle, snow, a flickering
  storm bolt or fog. The inside reading can run a few degrees warm because the sensor sits next to PIP's electronics.
- **PIP:** on the Let's Focus screen the whole screen is PIP's little space station (porthole, wall terminal,
  hazard-striped deck) and your text sits on a holo-monitor on short legs. PIP never makes props appear out of
  nowhere: between two activities it walks off the edge of the screen (carrying what it was playing with) and comes
  back with the next toy. PIP
  walks behind the board (you'll see its legs underneath) and peeks out from its edge, leans on it, points at it
  like a presenter, kicks a ball under it to the far wall, runs off one side and comes back in from the other, and
  plays with props (ball tricks, kite, paper plane, block tower, guitar, umbrella in the rain, telescope, plant…),
  gets bored and sighs, checks its calendar, or walks right up to the glass and knocks to get your attention. No
  animation repeats within 2 hours there. On the other screens PIP does what you are doing: while the timer runs it acts out
  your step (writes in its notebook for "Draft the summary", is on the phone for "Call the dentist", flips pancakes
  for "Cook dinner", works out for "Go to the gym", strolls with a shopping bag for "Pick up groceries"...). When
  you pause it waits with its things, when you finish a step it holds up what it worked with. While you talk it
  listens the way you chose (calendar, notes, focus, alarm clock), while planning it transcribes then thinks, and the
  break screen's "Stretch, sip some water, look far away" is exactly what it does, in that order. When a step is lined
  up, the Let's Focus screen mixes in a preview: PIP brings that task's things and points at "Next:" on the board.
  It turns its whole body to look at the option you're about to pick, and reacts to every button press (turns, spins,
  leans in). Its little symbols (focus lines, Zzz, ?, !, hearts, notes, sparkles) are animated too.
- **Today's calendar:** double-click KEY. A timeline of today (time, task/reminder/alarm mark, title; done items
  crossed out) with a marker for "now". The Let's Focus board also lists today's open items, then **Coming up** (the next days:
  "Wed 05:00 Gym wake-up"), with "+2 more" when there are more than fit, and today's date when there is room.
- **Easter eggs:** every now and then PIP vanishes in a puff of smoke and one of its relatives drops by - a wind-up
  tin-toy ancestor, or a 1960s cabinet computer that prints you a "HI!". And on a really bad day (the error screen)
  PIP may lose patience with its posh potato battery (monocle, bow tie, a bulb that won't stay lit) and
  throw it off the screen.
- **Moving between screens:** screens slide like pages behind PIP (PIP itself stays where it is) — forward
  (talk → plan → focus → done, calendar) to the left, back to the right. Alarms and messages drop in from the top and lift away when you dismiss them.
- **Right:** the important thing right now (timer, step, agenda, alarm or question). On every screen except Let's
  Focus PIP keeps to the left so it never covers this.
- **Black bar at the bottom:** what the buttons do on this screen, the link icon (plus **OFFLINE** when PIP is on
  its own) and battery.

## 3. Buttons
| | What it does |
|---|---|
| **KEY click** | Start / pause the timer. On "Step Done!": start the next step. On an alarm: snooze 5 min. |
| **KEY double-click** | Show today's agenda / go back. On an alarm: dismiss. |
| **KEY hold** | Leave a voice message: first pick what it's about, then hold again to talk (see 4). Needs the PC. |
| **BOOT click** | Mark the current step done. On "Step Done!": take a 5-min break. On a question: confirm. |
| **BOOT hold 1.2 s** | **Cut the step in half** when it feels too big. Nothing is lost — the rest becomes the next step. |
| **BOOT double-click** | **Park the task for later.** It moves to Parked tangents with its steps and the time left; Resume it from the app any time. Needs the PC. |
| **KEY hold (while recording a meeting)** | End the meeting. Clicks do nothing while a meeting records, so a bumped button can't stop it. |

## 4. A typical session
1. **Voice message.** Hold **KEY** — PIP asks **"What's it about?"**:
   **Calendar** · **Brain dump** · **Focus** · **Alarms** · **Meeting**. Click KEY to move the highlight, then
   **hold KEY** and speak; release to send (up to **10 minutes**). BOOT goes back.
   **Hands-free:** say the wake word, then the activity's name and (after a short pause or a comma) your
   message — *"Hi ESP… Meeting"* starts a meeting recording, *"Hi ESP, alarms, wake me at 7"* sets an alarm,
   *"Hi ESP, calendar, dentist Thursday at 2"*. PIP chimes softly the moment it hears the wake word; when the
   laptop has recognised the name (about a second) PIP plays a rising "go ahead" chime and shows
   **"Got it: Alarms - go ahead"** (or *recording meeting*), and keeps recording. Just start talking without a name
   and it's a brain dump. Say nothing for 3 s and you get the menu instead; from the menu, the wake word again
   talks about the highlighted option. Hands-free (wake word) messages end after a **3.5 s pause** (5 s once
   you've talked for 20 s), so thinking pauses don't cut you off; **click KEY** to send straight away.
   (You can also type it in the app's **Brain Dump** page and
   pick the same four topics there.)
   - *Brain dump:* everything on your mind — PIP picks one task to do now and parks the rest.
   - *Calendar:* "Dentist Thursday at 2", "move gym to Friday morning".
   - *Focus:* "pause", "I need a break", "this step is too big".
   - *Alarms:* "wake me at 6:30 every weekday".
2. Kimi breaks the task into 3–6 concrete steps in your own situation (the first is a 2-minute starter), gives it a
   short name that fits PIP's screen, parks side thoughts for later, and sets alarms. Planning takes ~20–40 s.
   Steps name the real places and things you mentioned ("Drive to Old Navy", "Find kids' winter pants"), and each
   step says what you'll be doing (errand, computer, call...) so PIP acts out the right thing — one task can mix
   them (pull the numbers on the computer, then call Priya). Say when you'll start ("starting in 10 minutes",
   "at 2") and the task goes on the calendar at that time; PIP chimes and says **"Time to start: …"** then.
   **Reminders** now ping you the same way when they're due ("Reminder: …").
   If that start time comes while you're mid-step on *another* task, PIP stays quiet and mentions it once at your
   next break (step done, pause): **"Next: … (09:29)"** — then switch, or drag it to Tomorrow or Parked. A task you
   have already begun gets no start nudge. If you add a task while another is in progress, PIP says
   **"Added to today: …"** and keeps you on the current one.
   Add the names and acronyms you use under **Settings → Words PIP should know** (e.g. CASL, CST, Priya): speech
   recognition hears them better and Kimi fixes near-misses ("castle consent" → "CASL consent").
3. **Time you can feel.** While a step runs, a disc in the top-left corner shrinks like a kitchen timer, with the
   minutes left under it. At **5 minutes left** (steps of 8+ min) PIP chimes softly and turns to you; at **1 minute**
   it says **"Time to wrap up"**. Works offline too.
4. **Meetings.** Pick **Meeting** in the voice menu and hold KEY: PIP records until you **hold KEY again** — no time
   limit (the screen shows REC and the running time). The recording is saved on the PC as it goes, then transcribed
   and summarised there (nothing is uploaded). Open **Meetings** in the app to read who said what.
5. Click **KEY** to start the 2-minute starter. Click **BOOT** when done. Repeat.
6. Vague times like "Friday afternoon" are never set silently — PIP asks **Confirm Time**: BOOT to confirm,
   KEY to keep it as a parked note instead.

## 5. The Companion app
- **Today:** the overview — a slim **Now focusing** strip (the step in progress, time left, a progress bar, one
  Start/Pause button and **Open Focus**; after a step: *Start next step* / *Break*; on a break: *I'm back*), then
  today/tomorrow and parked tangents. The big timer, the step controls and the step list are on **Focus**. **Drag** any task,
  reminder or one-time alarm between **Today** and **Tomorrow**, or onto **Parked tangents**; drag a parked item onto
  Today to start it (the row buttons do the same without a mouse). Moving the task in progress sets it down with its
  time left. **Park for later** on the
  Focus page sends the task in progress to Parked tangents; **Resume** brings it back exactly where it stopped. For a
  parked *thought*, **Promote** asks Kimi to break it into concrete steps (~20–40 s); if Kimi can't be reached the
  note simply stays parked.
- **Calendar:** Outlook-style Month / Week / Day: events are blocks with their title and time range, the
  all-day/anytime row wraps long titles (+N more expands). Week and Day show the hours of the day; click any hour to add a task or
  reminder at that time. **Drag** a task or reminder to another time or day; **drag a task's top or bottom edge** to
  change how long it is (snaps to 15 minutes). The panel **beside the grid** stays on screen while you scroll the
  hours: click an item (on the grid or in the day's list) and its editor opens at the top of that panel, next to the
  block — change its date/time, make it "anytime", or delete it; **Esc** or ✕ closes it. Below it are the selected
  day's items (a long day scrolls inside the list) and *Add on this day*. On a narrow window the panel sits under the
  grid and the editor floats at the bottom of the screen instead. Alarms are edited on the Alarms page.
- **Brain Dump:** review and edit a plan before saving it.
- **Focus:** the full focus timer — Start/Pause (or **Space**), **Complete step**, **Cut in half** (**S**),
  **Park for later** — with the cut-in-half preview and every step of the task (Alt+↑/↓ to reorder).
- **Meetings:** every recorded (or imported) meeting with its date, time, length and speakers. Play the audio and
  click a line's time to jump there. Speakers PIP doesn't know are **Speaker 01, Speaker 02...**: type a name and
  Save — with **Remember this voice** ticked, PIP names that person automatically in later meetings. Fix a line's
  speaker from its drop-down, edit a mis-heard word, merge two speakers who are the same person ("Same person as…"),
  add a missed speaker, or tell PIP how many people were there and **Detect again**. Right after transcription the
  PC writes a **summary**, decisions, action items and topics itself (local AI, free, nothing leaves the PC; see
  *Meetings: summaries, Obsidian and questions* below). **Redo on this PC** makes it again; **Kimi** asks Kimi
  instead (uses your AI budget). The summary starts with the **Outcome** (how the meeting ended) and has **Key
  points** with times you can click. **Action items:** each shows whose it is (*yours* when the owner is you —
  Settings → Meetings → *Your name in meetings*), the deadline as said and the date PIP worked out from the meeting's
  date (change it if it's wrong). Tick items (yours are pre-ticked) and choose **Make tasks** (on that date),
  **Reminders** (a ping at that date and time), **Park**, or **Not for me**. Items with a date also appear on the
  **Calendar** as dashed "from meeting" blocks until you decide — click one to decide there, or drag it to another
  day. **Archive** keeps a meeting but leaves it out of search, questions, action items and the calendar (Restore
  brings it back); archived meetings are listed at the bottom.
  **Ask your meetings** (top of the page) answers questions across every meeting — *"Who is sending the Q3 budget?"*
  — with links to where it was said; **Find** just lists the matching lines (no AI at all).
  **Graph** (the tab beside **List**) draws your meetings like Obsidian's graph view: each meeting is a dark dot
  (dashed while it is still being transcribed), its summary an orange diamond beside it, people green rings and
  topics violet dots — a person or topic shared by several meetings links them. A dashed line from a summary to a
  person means they were talked about in a meeting they weren't in; dashed lines between topics join related
  subjects, and topics worded slightly differently in different meetings ("QR codes", "QR code review") are one dot.
  Click a dot to read it in the panel
  on the right: a meeting shows its transcript (with a find box), a summary shows the outcome, decisions and action
  items, a person or topic lists its meetings. Links in the panel move the graph to that dot. **Open meeting** (or
  double-click a meeting) takes you to the List to edit it; **Show in graph** on a meeting comes back. Hover a dot to
  light up its links; use the search box to find a meeting, person or topic; the chips hide or show summaries,
  people and topics; **Include archived** adds archived meetings. Drag to pan, drag a dot to move it, scroll or
  **+**/**−** to zoom, **0** fits everything, **Esc** clears the selection.
  **Export** as Markdown, TXT, SRT subtitles or JSON, or download the audio. **Import audio** transcribes a recording
  from elsewhere (wav, mp3, m4a...). Speaker detection uses a small voice model on this PC (downloaded once,
  30 MB; nothing leaves the PC): it counts the people itself and rarely splits one person into two. Older
  meetings keep the speakers you set; press **Detect again** to re-run detection on one.
- **Alarms:** one-time or weekly alarms. Sound is either **Chime** or **Spoken wake-up, then chimes**: pick a voice,
  type a script or press **Write with Kimi** for a ~30-second (70-90 word) wake-up message, and **Preview on this
  PC**. When it rings, PIP speaks the script, then chimes every few seconds for **1 minute** unless you dismiss it.
  Any button on PIP (or Dismiss in the app) stops the voice and chimes immediately. **Test on device** rings PIP
  right away; a test closes by itself after **30 seconds** and never uses up the real alarm.
- **Voice alarms by voice:** in the Alarms activity say e.g. *"wake me up at 5 for the gym with a lady's voice"*:
  Kimi writes the script, the default female wake-up voice is used (change it under Settings: Wake-up voice).
- **Confirmation:** whenever PIP schedules something it shows a toast such as **"Alarm set: Wed 05:00"** on the
  screen and in the app, plays a confirm chime and says it out loud.
- **Device:** a live copy of PIP's screen and battery/health info.
- **Settings:** Kimi API key (see below), speech status, voice picker and "Play on PIP" voice test.
- Keyboard: **Space** start/pause · **N** brain dump · **S** cut in half · **1–8** switch views.

## 5a. Meetings: summaries, Obsidian and questions
- **Local AI.** Summaries and questions use a model running on your PC through **Ollama** (free, from ollama.com).
  Install it once, then open **Settings → Meetings** and choose a model from the list. Each one shows what it is
  good for, its download size, a quality rating (●●●●○) and whether it fits your PC: *Fits your GPU* (fast),
  *GPU + RAM, slower*, *CPU only, slow* or *Too big* (hidden unless you ask). PIP marks one as **Recommended** for
  your PC (an 8 GB laptop GPU: `qwen3:8b`, about 5 GB). **Download & use** fetches it and switches to it when the
  download finishes; **Use** switches between downloaded models; the bin removes one from disk (not the one in
  use). Any other model from ollama.com/library can be typed in below the list. Until then summaries show *"local AI not running"* and
  you can still use **Kimi** per meeting. **After each transcription** can be set to *Summarise on this PC*
  (default), *Summarise with Kimi* or *Don't summarise*. PIP never switches to Kimi by itself. **Summary quality:**
  *Careful* (default, about 2 minutes per meeting: it double-checks every action item against what was said) or
  *Fast* (one pass, about 40 seconds). **Meeting speech-to-text:** *Automatic* uses the most accurate model your
  GPU can run (`large-v3-turbo` on an NVIDIA card). **Remove filler words** (on by default) takes out "um", "uh",
  stutters ("the the") and comma-wrapped ", you know," from transcripts and voice commands; the original words are
  kept, and **Clean up existing transcripts** applies it to meetings recorded earlier.
- **Several things at once.** Transcriptions always go first: a summary waits for them, and a long meeting is
  summarised in parts so it can pause between parts and continue later without redoing work. While PIP is
  listening to or transcribing a voice command, summaries wait too. A one-hour meeting takes about a minute on a
  laptop GPU.
- **Obsidian.** In **Settings → Meetings → Obsidian vault**, pick your vault (PIP suggests the ones Obsidian knows)
  and Save. Every finished meeting is written into the folder **PIP Meetings**: one note per meeting (date, people
  as `[[links]]`, topics, summary, decisions, action items as checkboxes, a link to the full transcript), the
  transcript in `Transcripts/`, a **Meetings index** and a list of all **Action items**. Write your own thoughts
  under **My notes** in a meeting's note — PIP keeps them when it updates the note, and an action item you tick in
  Obsidian shows as done in PIP. Deleting a meeting in PIP leaves its note in the vault.
- **Summarise with another AI.** In a meeting's **Summary** card, press **Another AI**. (1) **Transcript for AI
  (.md)** downloads the transcript with instructions for the AI at the top. (2) Give that file to any AI assistant
  (Claude, ChatGPT, ...). If it ignores the instructions, **Copy prompt** and paste that too; the prompt also works
  with the ordinary **Markdown** export. (3) Paste the AI's reply into the box, or **Choose file…** if it gave you a
  `.md` file, optionally type which AI it was, and press **Use this summary**. It replaces the meeting's summary:
  action items, due dates, the calendar and the Obsidian note update as usual, and action items you already decided
  on keep your choice. If PIP says the text doesn't look like a summary, ask the AI to answer in the format from the
  prompt (headings such as *## Summary* and *## Action items*).
- **Asking with other AI tools.** The vault is laid out so any AI assistant can read it cheaply: the index first,
  then the meeting notes, and a transcript only for exact wording (see `_About these notes.md` in the folder).

## 6. Kimi AI (required for planning)
PIP uses Kimi to break tasks into steps. Set it up once: **Settings → Kimi API key → paste → Test this key →
Save key**. The key is kept in Windows Credential Manager; the app shows only its last 4 characters. The model is
picked automatically: the newest *standard* Kimi model (never the pricier "highspeed"/turbo variants); you
can pin one under **Kimi model**. Your brain-dump text is sent to
Moonshot for planning.

If Kimi can't be reached, PIP flashes **"AI has left the device"** and waits. Press any button to dismiss — your
words are not lost: they're saved as a parked note you can promote later.

## 6a. Wi-Fi, firmware updates, wake word, AI costs
- **Wi-Fi (no cable needed):** with PIP plugged in by USB, open **Device → Connection**, type your Wi-Fi name and
  password (2.4 GHz) and press **Connect PIP to Wi-Fi**. This also pairs PIP with this PC. Afterwards PIP can sit
  anywhere and run from any USB charger; the app finds it on your network by itself and switches back to the cable
  whenever you plug it in. The password goes to PIP only and is never stored on the PC.
- **More than one Wi-Fi:** PIP remembers up to 5 networks and joins the strongest one in range. See **6c**.
- **Away from home (another Wi-Fi):** PIP can reach this PC over the internet from the office, a café or your phone's
  hotspot. It needs a one-time setup: see **6c. Using PIP away from home**.
- **Firmware updates:** **Device → Firmware** shows the version on PIP and any newer build on this PC (or upload a
  `.bin`). Press **Update PIP**: about 25 seconds over USB or Wi-Fi, PIP restarts by itself. If a new version ever
  fails to start properly, PIP goes back to the previous one automatically.
- **Wake word:** **Settings → Wake word**. Say **"Hi ESP"** (or Jarvis / Computer / Hi Joy) and PIP opens
  *What's it about?* — the same screen as holding KEY. Click KEY to pick, then either hold KEY and talk, or simply
  say the wake word **again** and talk hands-free; PIP stops listening after a 3.5 s pause (or when you click KEY).
  The microphone audio stays on PIP until it hears the word. *Test* checks the detector with a synthetic voice.
- **AI costs:** **Settings → AI usage & budget** shows Kimi tokens and dollars per day and this month. Set a
  monthly cap: at 80 % you get a warning, at 100 % PIP stops planning (screen: *AI budget reached*) and parks your
  words until you raise the cap or the month ends. Prices per model are editable if Moonshot changes them.

## 6b. Error screens
If anything goes wrong or gets stuck (for example "Planning…" never finishes), PIP shows a ⚠ error screen with a
short explanation instead of freezing, flashing briefly to get your attention. **Press any button to dismiss.**
The same message appears in the app with a Dismiss button. Details are written to `data/logs/errors.log`.

## 6c. Using PIP away from home
At home the app finds PIP on your Wi-Fi by itself. On another network (the office, a café, your phone's hotspot) the
PC cannot see PIP, so **PIP calls the PC over the internet** instead. You set this up once, at home:

1. Save the other Wi-Fi networks on PIP (**A**).
2. Make this PC reachable from the internet (**B** or **C**).
3. Turn on **Away from home** in the app (**D**).

**This PC must stay on, with PIP Companion running and connected to the internet.** PIP only calls *this* PC (the
one it was paired with over USB).

### A. Save the networks PIP will use
Do this at home, with PIP on the USB cable or on the home Wi-Fi:
1. Open **Device → Connection**.
2. Type the network's **Wi-Fi name** and **Password** and press **Add network**. PIP saves it and stays on the
   network it is on now, so you add networks before you get there.
3. Repeat for each place, up to **5 networks** in all. They appear under *Saved networks*.

PIP keeps its current network as long as it works. When it loses it (you carried PIP away), it looks around and
joins the strongest saved network in range. To remove one, press the **x** next to its name.
*Forget all networks* clears the list (PIP then has no Wi-Fi until you add one again).

> **Phone hotspot:** PIP only uses **2.4 GHz** Wi-Fi. On an iPhone turn on **Settings → Personal Hotspot →
> Maximize Compatibility**; on Android pick the **2.4 GHz** band for the hotspot. Type the hotspot's name exactly
> as the phone shows it.
>
> **Café and hotel Wi-Fi** with a sign-in page (you have to tick a box in a browser) does **not** work: PIP has no
> browser. Use your phone's hotspot there instead.

### B. Make this PC reachable — with Tailscale Funnel (recommended)
Tailscale Funnel is free and needs no router changes. It gives this PC a fixed public name such as
`my-pc.tail1234.ts.net`.
1. Install **Tailscale** on this PC from tailscale.com and sign in (a free personal account is enough).
2. Open **PowerShell** and run:
   ```powershell
   tailscale funnel --bg --tls-terminated-tcp=10000 tcp://localhost:18423
   ```
   The first time, Tailscale opens a web page asking you to **enable Funnel** (and HTTPS) for your account. Approve
   it, then run the command again if needed. `--bg` keeps Funnel running after a restart of the PC.
3. Find this PC's public name:
   ```powershell
   tailscale funnel status
   ```
   It lists this PC's name ending in **`.ts.net`** (for example `my-pc.tail1234.ts.net`) with port **10000**. The
   name is the **public address** and **10000** the **public port**. The same name is shown for this PC in the
   Tailscale app and on the *Machines* page of the Tailscale website. (Funnel only allows the public ports 443, 8443
   and 10000. If you use 443 or 8443 instead, use that number in the command and in the app.)

To stop Funnel later, run the same command with `off` at the end:
```powershell
tailscale funnel --tls-terminated-tcp=10000 tcp://localhost:18423 off
```

### C. Make this PC reachable — with a port forward on your router (alternative)
Use this only if you cannot use Tailscale and you know your way around your router.
1. Give this PC a fixed address on your home network (in the router: "DHCP reservation" or "static lease").
2. In the router's **port forwarding** page, forward a **TCP** port of your choice (for example **18423**) to this
   PC's address, port **18423**.
3. Find your **public address**: the WAN or internet IP shown in the router. Most home connections get a new public
   IP from time to time, so a free **dynamic DNS** name (many routers have this built in) is better than the bare IP.
4. When Windows asks whether PIP Companion may communicate on networks, allow **Private networks**.

> If the WAN address shown in your router differs from the address a "what is my IP" website shows, your provider
> shares one public address among many customers (CGNAT) and a port forward **cannot** work. Use Tailscale (**B**).

### D. Turn it on in the app
1. With PIP connected (cable or home Wi-Fi), open **Device → Away from home**.
2. **How this PC is reachable:** pick *Tailscale Funnel* (for **B**) or *Port forward on my router* (for **C**).
3. **Public address:** the `….ts.net` name (B) or your public IP / dynamic-DNS name (C). Only the name, without
   `https://`. (Pasting `my-pc.tail1234.ts.net:10000` into this field also works: the app splits off the port.)
4. **Public port:** 10000 (B), or the port you forwarded on the router (C).
5. **Local port:** leave **18423** unless you changed it in the Funnel command or the port forward.
6. Press **Turn on**. The card shows *This PC: Listening on port 18423*, and PIP learns the address right away.

**Try it once before you rely on it:** power PIP from a power bank, turn on your phone's hotspot (saved in **A**)
and take PIP out of reach of your home Wi-Fi (or try it at the office). About half a minute after PIP joins the
other network, the **Connection** badge in the app reads **Away link**.

### What you see
| Where | Shows | Meaning |
|---|---|---|
| Connection badge | **USB cable** / **Wi-Fi** | PIP is at home; the away link is not used. |
| Connection badge | **Away link** | PIP is linked over the internet. Everything works as at home. |
| Away card, *This PC* | *Listening on port 18423* | The PC is ready for PIP's call. |
| Away card, *PIP* | *Standing by* | PIP has the address and is on the cable or home Wi-Fi: it does not need to call. *Off* means PIP has no address yet. |
| Away card, *PIP* | *Connected over the internet* | Linked over the internet. |
| Away card, *Last call* | date and time | When PIP last got through. |
| Away card | *Refused: n unauthenticated connections* | Strangers (internet scanners) knocked and were turned away. Normal on a public address; nothing to do. |
| PIP's screen | **OFFLINE**, then linked again | Until the call gets through, PIP keeps working offline (see **7**). |

While PIP is away and *not* connected, the app cannot hear from it, so the card shows what PIP last reported.

**When PIP calls:** only when it has had neither the USB cable nor the home Wi-Fi link to this PC for **10
seconds**. It tries again after 2 seconds, then waits longer each time, up to once a minute. Back at home, plug it
in or let it join the home Wi-Fi: the app switches back by itself.

**Privacy and safety:** everything between PIP and this PC is encrypted with the key PIP shares with this PC alone
(set over the USB cable). Tailscale, your router or the café network cannot read your words, audio or tasks, and
nobody else can control PIP or pretend to be it. Over a slow connection, speech and screen captures may lag a
little. Do firmware updates at home, on the cable or the home Wi-Fi.

**To turn it off:** **Device → Away from home → Turn off**, then stop Funnel (**B**) or remove the port forward (**C**).

## 7. Unplugged (offline) use
PIP keeps counting, lets you finish/cut steps, and rings alarms it already knows about (offline it plays chimes
for a minute; the spoken script needs the PC). The top bar says
**OFFLINE**. Voice needs the PC. When you plug back in, everything you did is synced automatically.
After 15 idle minutes offline PIP rests (sleep screen); press any button to wake it.

## 8. Troubleshooting
- **Screen says OFFLINE while plugged in:** open PIP Companion (tray icon must be running); see section 9 to
  check it and restart it.
- **"Connect PC for Voice":** voice needs the app running and the cable connected.
- **Voice not understood:** speak after the Listening screen appears; check Settings → Speech-to-text = Ready.
- **"AI has left the device":** check Settings → Kimi API key → *Test saved key*, and your internet connection.
- **Weather missing:** Settings → Temperature & weather → pick your city.
- **PIP won't join a saved network away from home:** it must be 2.4 GHz (see the phone-hotspot tip in **6c A**),
  the name and password must be exact (add it again to correct the password), and sign-in-page Wi-Fi does not work.
- **Away from home: PIP stays OFFLINE and the badge never reads *Away link*:**
  1. Is PIP on a saved network? (See the entry above.) Is this PC on, awake (not asleep) and online, with PIP
     Companion running, and does the Away card say *This PC: Listening*?
  2. Tailscale: run `tailscale funnel status` — it must list port 10000 (or yours) forwarding to
     `tcp://localhost:18423`. If not, run the command in **6c B** again. Check that the address in the app matches.
  3. Port forward: the router rule must point to this PC's current address; your public IP may have changed (use a
     dynamic-DNS name); and Windows Firewall must allow PIP Companion on private networks.
  4. *This PC: cannot listen on port 18423* in the card: another program uses that port. Pick another **Local port**
     in the app and use the same number in the Funnel command or port forward.
  5. The Away card's *PIP* line says *Off*: PIP never received the address (it only learns it while connected).
     Connect PIP at home, press **Turn on** again and check that the line changes to *Standing by*.
- **Logs:** `data/logs/pip.log` (everything) and `data/logs/errors.log` (only problems).
  **Restore Waveshare demo firmware:** see README.

## 9. Starting, restarting and checking the host
The **host** is the part of PIP that runs on your PC: it talks to PIP over USB or Wi-Fi, runs Kimi planning, speech
recognition, meetings and alarms, and serves the Companion app at **http://127.0.0.1:18421**. It runs inside the
**PIP Companion** tray app. PIP keeps working on its own while the host is off (see 7), but voice, planning,
meetings and spoken alarms need it.

Terminal commands below are for **PowerShell**, run from the PIP folder (e.g. `C:\claudecodefolder\PIP ESP`).

### Start it
- **Normal:** double-click **PIP Companion** (Desktop or Start menu). The app window opens and the PIP icon appears
  in the tray. Right-click the icon → **Start with Windows** to have it start every time you log in.
- **Installed app (PIP.exe):** that is all - the commands below are only for running PIP from its source folder
  (shortcut **PIP Companion (dev)**). From a terminal: `& "$env:LOCALAPPDATA\Programs\PIP Companion\PIP.exe"`
  (add `--background` for tray only); stop it with `Stop-Process -Name PIP`. Its logs are in
  `%LOCALAPPDATA%\PIP\logs`. Only one PIP can run at a time: quit the other one first.
- **Shortcuts missing (source folder)?** Recreate them once:
  ```powershell
  .\tools\install_windows.ps1
  ```
- **From a terminal, with the app window:**
  ```powershell
  Start-Process .venv\Scripts\pythonw.exe -ArgumentList '"tools\pip_tray.pyw"'
  ```
- **From a terminal, tray only (no window):** add `--background`. Open the window later from the tray icon
  (**Open PIP**) or by browsing to http://127.0.0.1:18421.
  ```powershell
  Start-Process .venv\Scripts\pythonw.exe -ArgumentList '"tools\pip_tray.pyw"','--background'
  ```

### Stop or restart it
- **Normal:** right-click the tray icon → **Quit PIP**, then open **PIP Companion** again.
- **From a terminal** (e.g. the tray icon is gone but the host still runs):
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | ? CommandLine -match pip_tray | % { Stop-Process -Id $_.ProcessId }
  ```
  then start it again with one of the commands above.
- Restarting **pauses a running focus timer** (it keeps the time left) — press KEY or Start to carry on.
- **Don't restart during a meeting recording:** what was recorded before the restart is kept and transcribed, but
  audio after it is not captured. If it happens, hold KEY on PIP to end the meeting and start a new one.
- After updating PIP's software, restart once so the new version is used.

### Check that it runs
- Open **http://127.0.0.1:18421** — the Companion app should load. The pill top-right says **Linked · PIP device** when PIP is
  connected (over USB or Wi-Fi).
- PIP's bottom bar shows the link symbol instead of **OFFLINE**.
- **Settings** shows Speech-to-text **Ready** and the Kimi key **active**.
- Logs: `data\logs\pip.log` (everything) and `data\logs\errors.log` (only problems).

### Run it in a console (for troubleshooting)
Shows every log line live. **Quit the tray app first** — only one host may run, because both use port 18421 and
PIP's USB port:
```powershell
.venv\Scripts\python -m uvicorn service.main:create_app --factory --app-dir host --port 18421
```
Press **Ctrl+C** to stop it, then start PIP Companion normally again.
