"""Loop B: Playwright E2E + visual capture of the desktop app against a live sim_rlcd.

  python tools/verify_desktop_ui.py          # writes artifacts/desktop/<viewport>/*.png + results.json
Uses the system Microsoft Edge (Chromium) so no browser download is needed."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_stack import ROOT, Stack  # noqa: E402

OUT = ROOT / "artifacts/desktop"
VIEWS = [("today", "/"), ("calendar", "/calendar"), ("voice", "/voice"), ("focus", "/focus"),
         ("meetings", "/meetings"), ("alarms", "/alarms"), ("device", "/device"), ("settings", "/settings")]
VIEWPORTS = [(1440, 900), (900, 700)]
DUMP = "Finish Q3 report, also remind me to call dentist, and set alarm for 3pm"


class Probe:
    def __init__(self, page: Page) -> None:
        self.console: list[str] = []
        self.page_errors: list[str] = []
        self.bad_http: list[str] = []
        page.on("console", lambda m: self.console.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.page_errors.append(str(e)))
        page.on("response", lambda r: self.bad_http.append(f"{r.status} {r.url}") if r.status >= 400 else None)

    def reset(self) -> None:
        self.console.clear()
        self.page_errors.clear()
        self.bad_http.clear()


A11Y_JS = """() => {
  const out = {main: !!document.querySelector('main'), nav: !!document.querySelector('nav'), unnamed: []};
  for (const el of document.querySelectorAll('button, input, select, textarea, a[href]')) {
    const name = (el.getAttribute('aria-label') || el.textContent || el.getAttribute('title') || '').trim();
    const labelled = el.id && document.querySelector(`label[for="${el.id}"]`);
    if (!name && !labelled && !el.getAttribute('aria-labelledby')) out.unnamed.push(el.outerHTML.slice(0, 80));
  }
  out.overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
  return out;
}"""


def check_view(page: Page, probe: Probe, path: str, shot: Path, results: list[dict]) -> None:  # type: ignore[type-arg]
    probe.reset()
    page.goto(page.url.split("/", 3)[0] + "//" + page.url.split("/", 3)[2] + path)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)
    a11y = page.evaluate(A11Y_JS)
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot), full_page=True)
    ok = not (probe.console or probe.page_errors or probe.bad_http or a11y["unnamed"] or a11y["overflow"]
              or not a11y["main"] or not a11y["nav"])
    results.append({"view": path, "shot": str(shot.relative_to(ROOT)), "ok": ok, "console": probe.console[:],
                    "page_errors": probe.page_errors[:], "http": probe.bad_http[:], **a11y})


def flows(page: Page, stack: Stack, base: str) -> list[str]:
    log: list[str] = []
    page.goto(base + "/voice")
    page.fill("#dump-text", DUMP)
    page.get_by_role("button", name="Break it down").click()
    page.get_by_role("button", name="Accept all").wait_for()
    plan = stack.http.get("/api/v1/voice/sessions").json()[0]
    p = json.loads(plan["raw_json"])
    steps = p["active_task"]["steps"]
    assert 3 <= len(steps) <= 6 and steps[0]["is_starter"] and 2 <= steps[0]["duration_min"] <= 5
    assert len(p["parked"]) == 1 and [s["kind"] for s in p["scheduled"]] == ["ALARM"]
    page.get_by_role("button", name="Accept all").click()
    stack.wait(lambda: stack.state()["active_task"], 5, "plan committed")
    log.append("desktop->device: brain dump parsed (steps/starter/parked/alarm) and accepted")
    page.goto(base + "/")
    page.get_by_role("button", name="Start").click()
    stack.wait(lambda: stack.http.get("/api/v1/device/diagnostics").json()["diag"]["ui_state"] == "RUNNING", 6,
               "device RUNNING")
    png = stack.http.get("/api/v1/device/framebuffer.png").content
    (OUT / "device_running_fb.png").write_bytes(png)
    log.append("desktop Start -> sim_rlcd RUNNING, framebuffer captured")
    first = stack.state()["active_step_id"]
    stack.http.post("/api/v1/device/simulate-button", json={"button": "BOOT", "gesture": "SHORT"})
    page.get_by_text("Step done!").first.wait_for(timeout=6000)  # live WS update, no reload
    st = {s["id"]: s for s in stack.state()["active_task"]["steps"]}
    assert st[first]["status"] == "COMPLETED"
    log.append("device BOOT click -> step completed in SQLite -> desktop updated live")
    page.get_by_role("button", name="Start next step").click()
    n = len(stack.state()["active_task"]["steps"])
    stack.http.post("/api/v1/device/simulate-button", json={"button": "BOOT", "gesture": "HOLD", "hold_ms": 1300})
    page.get_by_text("(second half)").first.wait_for(timeout=6000)
    assert len(stack.state()["active_task"]["steps"]) == n + 1
    log.append("device BOOT hold -> rescue split visible on desktop, zero lost duration")
    page.fill("#brain-dump-input", "unsaved thought survives")
    rev = stack.state()["revision"]
    step_id = stack.state()["active_step_id"]
    stack.stop_sim()
    page.get_by_text("Standalone / Disconnected").wait_for(timeout=4500)
    assert page.input_value("#brain-dump-input") == "unsaved thought survives"
    page.screenshot(path=str(OUT / "1440x900/disconnected_today.png"), full_page=True)
    log.append("sim stopped -> calm Standalone banner within 4 s, form input preserved")
    stack.start_sim(offline_events=f"STEP_COMPLETE:{step_id}")
    stack.wait(lambda: stack.state()["revision"] > rev and {s["id"]: s for s in
               stack.state()["active_task"]["steps"]}[step_id]["status"] == "COMPLETED", 12, "offline reconcile")
    log.append("sim restarted with queued STEP_COMPLETE -> reconciled, revision incremented")
    page.fill("#brain-dump-input", "")
    log += calendar_drag(page, stack, base)
    log += meeting_review(page, stack, base)
    return log


def calendar_drag(page: Page, stack: Stack, base: str) -> list[str]:
    """Outlook-style editing: drag a block one hour later, then drag its bottom edge 30 minutes longer."""
    from datetime import date, timedelta
    day = (date.today() + timedelta(days=1)).isoformat()
    t = stack.http.post("/api/v1/tasks", json={"title": "Drag me", "target_date": day, "start_hhmm": "10:00",
                                               "steps": [{"title": "Drive to the bank", "duration_min": 30}]}).json()
    page.goto(base + "/calendar")
    block = page.get_by_role("button", name="Drag me, ", exact=False).first
    block.wait_for()
    box = block.bounding_box()
    assert box
    x, y = box["x"] + box["width"] / 2, box["y"] + 12
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + 20, steps=3)
    page.mouse.move(x, y + 64, steps=5)  # 64 px = 1 hour
    page.mouse.up()
    stack.wait(lambda: stack.http.get(f"/api/v1/tasks?date_from={day}&date_to={day}").json()[0]["start_hhmm"] == "11:00",
               5, "task moved to 11:00")
    block = page.get_by_role("button", name="Drag me, ", exact=False).first
    page.wait_for_timeout(400)
    box = block.bounding_box()
    assert box
    bx, by = box["x"] + box["width"] / 2, box["y"] + box["height"] - 2
    page.mouse.move(bx, by)
    page.mouse.down()
    page.mouse.move(bx, by + 10, steps=2)
    page.mouse.move(bx, by + 32, steps=4)  # 32 px = 30 min
    page.mouse.up()
    stack.wait(lambda: next(i for i in stack.http.get(f"/api/v1/calendar?start={day}&days=1").json()[0]["items"]
                            if i["id"] == t["id"])["duration_min"] == 60, 5, "task resized to 60 min")
    page.screenshot(path=str(OUT / "1440x900/calendar_dragged.png"), full_page=True)
    stack.http.delete(f"/api/v1/tasks/{t['id']}")
    return ["calendar: block dragged 10:00 -> 11:00 and resized 30 -> 60 min by its edge"]


def meeting_review(page: Page, stack: Stack, base: str) -> list[str]:
    """Two Piper voices -> imported recording -> real Whisper + speaker detection -> name a speaker in the UI."""
    import io
    import wave
    lines = [("en_GB-jenny_dioco-medium", "Good morning. Let's go through the launch checklist together."),
             ("en_US-ryan-medium", "Sure. The landing page is finished and the emails are scheduled for Monday."),
             ("en_GB-jenny_dioco-medium", "Great. Did legal approve the new pricing table yet?"),
             ("en_US-ryan-medium", "Not yet, I will chase them this afternoon and report back tomorrow.")]
    pcm = b""
    for voice, text in lines:
        r = stack.http.get("/api/v1/speech/say.wav", params={"text": text, "voice": voice}, timeout=60)
        if r.status_code != 200:
            return ["meetings: skipped (Piper voices not available)"]
        with wave.open(io.BytesIO(r.content)) as w:
            pcm += w.readframes(w.getnframes()) + bytes(16000)  # 0.5 s pause between turns
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    mid = stack.http.post("/api/v1/meetings/import?filename=launch.wav&title=Launch%20check", content=out.getvalue(),
                          timeout=60).json()["id"]
    stack.wait(lambda: stack.http.get(f"/api/v1/meetings/{mid}").json()["status"] in ("READY", "FAILED"), 240,
               "meeting transcribed")
    m = stack.http.get(f"/api/v1/meetings/{mid}").json()
    assert m["status"] == "READY", m.get("error")
    assert len(m["speakers"]) == 2, [s["name"] for s in m["speakers"]]
    page.goto(base + "/meetings")
    page.get_by_role("button", name="Launch check", exact=False).first.click()
    page.get_by_label("Name for Speaker 01").fill("Priya")
    page.get_by_label("Name for Speaker 01").press("Enter")
    stack.wait(lambda: any(s["name"] == "Priya" for s in stack.http.get(f"/api/v1/meetings/{mid}").json()["speakers"]),
               5, "speaker renamed")
    page.get_by_text("Priya").first.wait_for()
    page.screenshot(path=str(OUT / "1440x900/meeting_review.png"), full_page=True)
    md = stack.http.get(f"/api/v1/meetings/{mid}/export?format=md").text
    assert "**Priya**" in md and "pricing" in md.lower()
    stack.http.delete(f"/api/v1/meetings/{mid}")
    for v in stack.http.get("/api/v1/voices").json():
        if v["name"] == "Priya":
            stack.http.delete(f"/api/v1/voices/{v['id']}")
    return ["meetings: imported 2-voice recording -> Whisper transcript with 2 speakers -> named in the UI -> exported"]


def main() -> int:
    stack = Stack()
    stack.start()
    results: list[dict] = []  # type: ignore[type-arg]
    flow_log: list[str] = []
    failures: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            probe = Probe(page)
            page.goto(stack.base + "/")
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(OUT / "1440x900/00_today_empty.png"), full_page=True)
            try:
                flow_log = flows(page, stack, stack.base)
            except AssertionError as e:
                failures.append(f"flow: {e}")
            stack.wait(lambda: stack.health().get("link_state") == "TETHERED", 10, "relinked")
            time.sleep(0.5)
            for w, h in VIEWPORTS:
                page.set_viewport_size({"width": w, "height": h})
                for i, (name, path) in enumerate(VIEWS, 1):
                    check_view(page, probe, path, OUT / f"{w}x{h}/{i:02d}_{name}.png", results)
            page.set_viewport_size({"width": 480, "height": 800})
            check_view(page, probe, "/", OUT / "480x800/01_today.png", results)
            browser.close()
    finally:
        stack.stop()
    failures += [f"{r['shot']}: {k}" for r in results for k in ("console", "page_errors", "http", "unnamed")
                 if r[k]] + [f"{r['shot']}: horizontal overflow" for r in results if r["overflow"]]
    (OUT / "results.json").write_text(json.dumps({"flows": flow_log, "views": results, "failures": failures}, indent=2))
    for line in flow_log:
        print("FLOW OK:", line)
    print(f"views checked: {len(results)}, failures: {len(failures)}")
    for f in failures:
        print("FAIL:", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
