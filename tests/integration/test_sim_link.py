"""Host service <-> real sim_rlcd over TCP: link, sync, gestures, framebuffer, reconnect reconciliation."""
from __future__ import annotations

import io

from PIL import Image

from .conftest import LiveService, SimProcess

DUMP = "Finish Q3 report, also remind me to call dentist, and set alarm for 3pm"


def _linked(svc: LiveService) -> bool:
    h = svc.http.get("/api/v1/health").json()
    return h["device_transport"] == "SIMULATOR" and h["link_state"] == "TETHERED"


def _plan_and_start(svc: LiveService) -> dict:
    r = svc.http.post("/api/v1/tasks/plan", json={"text": DUMP, "auto_commit": True}).json()
    assert r["committed"]["task_id"]
    svc.http.post("/api/v1/timer/start")
    return svc.http.get("/api/v1/state").json()


def _device_ui_state(svc: LiveService) -> str:
    d = svc.http.get("/api/v1/device/diagnostics").json()
    return (d.get("diag") or {}).get("ui_state", "")


def test_link_heartbeat_and_diag(service: LiveService) -> None:
    service.wait(lambda: _linked(service))
    d = service.http.get("/api/v1/device/diagnostics").json()
    assert d["diag"]["is_sim"] is True
    assert d["diag"]["proto_ver"] == 1
    assert d["diag"]["crc_errors"] == 0


def test_focus_running_reaches_device_framebuffer(service: LiveService) -> None:
    service.wait(lambda: _linked(service))
    st = _plan_and_start(service)
    assert st["ui_state"] == "RUNNING"
    service.wait(lambda: _device_ui_state(service) == "RUNNING")
    png = service.http.get("/api/v1/device/framebuffer.png")
    assert png.status_code == 200
    img = Image.open(io.BytesIO(png.content))
    assert img.size == (400, 300)
    assert set(img.convert("L").getdata()) <= {0, 255}


def test_device_boot_click_completes_step(service: LiveService) -> None:
    service.wait(lambda: _linked(service))
    st = _plan_and_start(service)
    first = st["active_step_id"]
    r = service.http.post("/api/v1/device/simulate-button", json={"button": "BOOT", "gesture": "SHORT"})
    assert r.status_code == 200

    def done() -> bool:
        s = service.http.get("/api/v1/state").json()
        steps = {x["id"]: x for x in s["active_task"]["steps"]}
        return steps[first]["status"] == "COMPLETED" and s["ui_state"] == "STEP_DONE"
    service.wait(done)


def test_device_rescue_hold_splits_step(service: LiveService) -> None:
    service.wait(lambda: _linked(service))
    st = _plan_and_start(service)
    n_before = len(st["active_task"]["steps"])
    service.http.post("/api/v1/device/simulate-button", json={"button": "BOOT", "gesture": "HOLD", "hold_ms": 1300})

    def split() -> bool:
        s = service.http.get("/api/v1/state").json()
        return len(s["active_task"]["steps"]) == n_before + 1
    service.wait(split)
    s = service.http.get("/api/v1/state").json()
    halves = [x for x in s["active_task"]["steps"] if "half" in x["title"]]
    assert len(halves) == 2
    assert sum(h["remaining_sec"] for h in halves) >= 120  # starter (2 min) is never shortened below its work


def test_key_double_toggles_agenda_on_both_sides(service: LiveService) -> None:
    service.wait(lambda: _linked(service))
    _plan_and_start(service)
    service.http.post("/api/v1/device/simulate-button", json={"button": "KEY", "gesture": "DOUBLE"})
    service.wait(lambda: service.http.get("/api/v1/state").json()["page"] == "AGENDA")


def test_disconnect_then_offline_events_reconcile(service: LiveService, sim: SimProcess) -> None:
    service.wait(lambda: _linked(service))
    st = _plan_and_start(service)
    step_id = st["active_step_id"]
    rev = st["revision"]
    sim.stop()
    service.wait(lambda: service.http.get("/api/v1/health").json()["link_state"] == "STANDALONE", timeout=6)
    sim.start(offline_events=f"STEP_COMPLETE:{step_id}")
    service.wait(lambda: _linked(service), timeout=10)

    def reconciled() -> bool:
        s = service.http.get("/api/v1/state").json()
        steps = {x["id"]: x for x in s["active_task"]["steps"]}
        return steps[step_id]["status"] == "COMPLETED" and s["revision"] > rev
    service.wait(reconciled)
