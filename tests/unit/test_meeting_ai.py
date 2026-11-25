"""Meeting summaries on this PC (local AI, part by part), how they share the machine with transcriptions and voice
commands, the Obsidian vault, and search / questions across meetings."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
from service.config import Settings
from service.main import create_app
from service.meetings import summarize as summ
from service.meetings.local_ai import LocalAI
from service.meetings.obsidian import MARK, ObsidianVault, safe_name
from service.meetings.service import MeetingService, wav_header

from tests.support.fake_ollama import SUMMARY, FakeOllama
from tests.support.meeting_audio import ScriptedSegmentsSTT


class ScriptedLLM:  # test double for LocalAI: records calls, answers like a model would
    engine = "local/test"

    def __init__(self, on_call: Any = None) -> None:
        self.calls: list[tuple[str, str]] = []  # (purpose, user text)
        self.on_call = on_call
        self.unloads = 0

    def check_ready(self) -> None:
        pass

    def unload(self) -> None:
        self.unloads += 1

    def chat_json(self, system: str, user: str, schema: dict[str, Any], purpose: str, max_out: int = 1200) -> dict[str, Any]:
        self.calls.append((purpose, user))
        if self.on_call:
            self.on_call(len(self.calls), purpose)
        if "points" in schema["properties"]:
            return {"points": [user.splitlines()[3][:50]], "decisions": [], "topics": ["Q3 budget"],
                    "action_items": [{"task": "Send the Q3 budget", "owner": "Sam", "due": None}]}
        return dict(SUMMARY)

    def chat_text(self, system: str, user: str, purpose: str, max_out: int = 700) -> str:
        self.calls.append((purpose, user))
        return "Sam sends the Q3 budget [Budget chat @ 00:02]."


def _meeting(svc: MeetingService, title: str, lines: list[tuple[str, str]], gap: float = 5.0) -> str:
    """A READY meeting with a transcript: lines = (speaker name, text)."""
    mid = svc.repo.create(title, "2026-11-24T15:00:00Z", "America/Toronto", "", status="READY")
    names = list(dict.fromkeys(n for n, _ in lines))
    segs = [{"start_s": i * gap, "end_s": i * gap + gap - 0.5, "text": t, "speaker_key": f"S{names.index(n) + 1}"}
            for i, (n, t) in enumerate(lines)]
    svc.repo.replace_transcript(mid, segs, [{"key": f"S{i + 1}", "name": n} for i, n in enumerate(names)])
    svc.repo.update(mid, duration_s=len(lines) * gap)
    return mid


def _long(n: int = 150) -> list[tuple[str, str]]:
    words = "we went through the numbers for the quarter and what each team needs next " * 3
    return [("Ana" if i % 2 else "Sam", f"Point {i}: {words}") for i in range(n)]


def _service(manager, tmp_path: Path, llm: Any = None, **kw: Any) -> MeetingService:  # type: ignore[no-untyped-def]
    return MeetingService(manager, tmp_path, "small.en", lambda k, p: None, local_ai=llm,
                          stt=ScriptedSegmentsSTT([(0.0, 0.9, "Hello there.")]), **kw)  # type: ignore[arg-type]


# ---- summariser -------------------------------------------------------------------------------------------
def test_chunks_follow_turns_and_clean_repairs_model_output() -> None:
    lines = [f"[00:{i:02d}] Ana: " + "x" * 100 for i in range(50)]
    parts = summ.chunks(lines, 1000)
    assert all(len(p) <= 1000 for p in parts) and "\n".join(parts).splitlines() == lines
    out = summ.clean({"title": "", "summary": "  Fine.  ", "decisions": ["Ship it", "ship it", ""],
                      "action_items": [{"task": "Do it", "owner": "null", "due": ""}, {"task": "do it"}, "junk"],
                      "topics": ["#Budget", "budget", "[[Hiring]]"]}, "Weekly")
    assert out["title"] == "Weekly" and out["summary"] == "Fine." and out["decisions"] == ["Ship it"]
    assert out["action_items"] == [{"task": "Do it", "owner": None, "due": None, "done": False, "parked": False}]
    assert out["topics"] == ["Budget", "Hiring"]


def test_long_meeting_is_summarised_part_by_part_then_merged(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    llm = ScriptedLLM()
    svc = _service(manager, tmp_path, llm)
    mid = _meeting(svc, "Planning", _long())
    data = summ.summarize(llm, svc.repo.get(mid), svc.repo.segments(mid))
    purposes = [p for p, _ in llm.calls]
    assert purposes[:-1] == ["meeting_notes"] * (len(purposes) - 1) and purposes[-1] == "meeting_summary"
    assert len(purposes) >= 4  # >= 3 parts + the merge
    assert all(len(u) < summ.CHUNK_CHARS + 300 for _, u in llm.calls)  # each call fits a small model's context
    merge = llm.calls[-1][1]
    assert "Part 1/" in merge and len(merge) < 3000  # the merge reads notes, not the transcript
    assert data["title"] == "Budget review" and data["topics"] == ["Q3 budget", "Client deck"]
    short = _meeting(svc, "Quick", [("Ana", "Hi"), ("Sam", "I'll send the Q3 budget.")])
    llm.calls.clear()
    summ.summarize(llm, svc.repo.get(short), svc.repo.segments(short))
    assert [p for p, _ in llm.calls] == ["meeting_summary"]  # short meetings: one call


# ---- sharing the machine ----------------------------------------------------------------------------------
def test_new_transcription_goes_first_and_the_summary_resumes_where_it_stopped(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    order: list[str] = []
    wav = tmp_path / "b.wav"
    pcm = (np.random.default_rng(1).normal(0, 2000, 16000 * 2)).astype("<i2").tobytes()
    wav.write_bytes(wav_header(len(pcm)) + pcm)
    box: dict[str, Any] = {}

    def on_call(n: int, purpose: str) -> None:
        order.append(purpose)
        if n == 1:  # while part 1 of meeting A is being summarised, meeting B arrives for transcription
            box["b"] = svc.import_audio(wav, "Meeting B", datetime(2026, 11, 24, 16, tzinfo=UTC))

    llm = ScriptedLLM(on_call)
    svc = _service(manager, tmp_path, llm, summary_mode=lambda: "local")
    stt = svc.stt
    orig = stt.transcribe_segments

    def traced(audio: Any, on_segment: Any = None, beam_size: int = 1) -> Any:
        order.append("transcribe")
        return orig(audio, on_segment, beam_size)

    stt.transcribe_segments = traced  # type: ignore[method-assign]
    a = _meeting(svc, "Meeting A", _long())
    svc.enqueue_summary(a)
    assert svc.wait_idle(30)
    parts = sum(1 for p in order if p == "meeting_notes")
    first_t = order.index("transcribe")
    assert order[:first_t] == ["meeting_notes"]  # A stepped aside after its first part...
    assert order[first_t + 1:first_t + parts] == ["meeting_notes"] * (parts - 1)  # ...and resumed without redoing it
    assert order[-1] == "meeting_summary" and order.count("meeting_summary") == 2  # A's merge, then B's summary
    assert svc.repo.get(a)["summary_status"] == "READY" and svc.repo.get(box["b"])["summary_status"] == "READY"
    assert svc.repo.get(a)["summary_engine"] == "local/test"
    assert llm.unloads >= 1  # the summariser's model was let go before Whisper ran


def test_voice_command_pauses_local_summaries(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    busy = {"on": True}
    llm = ScriptedLLM()
    svc = _service(manager, tmp_path, llm, voice_busy=lambda: busy["on"])
    mid = _meeting(svc, "Standup", [("Ana", "Hi"), ("Sam", "I'll send the Q3 budget.")])
    svc.enqueue_summary(mid)
    time.sleep(0.6)
    assert llm.calls == [] and svc.repo.get(mid)["summary_status"] == "QUEUED"  # PIP is listening: wait
    busy["on"] = False
    assert svc.wait_idle(10) and svc.repo.get(mid)["summary_status"] == "READY"


def test_missing_local_ai_fails_the_summary_without_using_kimi(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    kimi_calls: list[int] = []
    svc = _service(manager, tmp_path, LocalAI("http://127.0.0.1:9"), summarizer=lambda: kimi_calls.append(1))
    mid = _meeting(svc, "Standup", [("Ana", "Hi")])
    svc.enqueue_summary(mid)
    assert svc.wait_idle(10)
    m = svc.repo.get(mid)
    assert m["summary_status"] == "FAILED" and "not running" in m["summary_error"] and kimi_calls == []


# ---- Obsidian ---------------------------------------------------------------------------------------------
def test_obsidian_notes_links_and_the_users_edits_survive(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "vault"
    root.mkdir()
    svc = _service(manager, tmp_path, ScriptedLLM(), vault=lambda: ObsidianVault(root),
                   vocabulary=lambda: ["Kubernetes", "Ana"])
    mid = _meeting(svc, "Meeting · Tue Nov 24, 10:00", [("Ana", "Let's move the cluster to Kubernetes."),
                                                       ("Speaker 02", "I'll send the Q3 budget.")])
    svc._save_summary(mid, summ.clean(dict(SUMMARY), "x"), "local/test")
    m = svc.repo.get(mid)
    assert m["title"] == "Budget review" and m["vault_note"] == "PIP Meetings/2026-11-24 1000 Budget review.md"
    note = (root / m["vault_note"]).read_text(encoding="utf-8")
    assert note.startswith("---\ntype: meeting\n") and '  - "[[Ana]]"' in note and "[[Speaker 02]]" not in note
    assert '"[[Q3 budget]]"' in note and '"[[Kubernetes]]"' in note  # summary topic + the user's own word
    assert "[[2026-11-24]]" in note and "- [ ] Send the Q3 budget — [[Sam]], due Friday" in note
    transcript = root / "PIP Meetings/Transcripts/2026-11-24 1000 Budget review (transcript).md"
    assert "[00:05] **Speaker 02**: I'll send the Q3 budget." in transcript.read_text(encoding="utf-8")
    index = (root / "PIP Meetings/Meetings index.md").read_text(encoding="utf-8")
    assert "[[2026-11-24 1000 Budget review\\|Budget review]]" in index and "| 1 |" in index
    assert (root / "PIP Meetings/_About these notes.md").exists()
    # the user ticks the action item and writes under the marker in Obsidian; then the meeting is renamed in PIP
    path = root / m["vault_note"]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Send", "- [x] Send") + "My own thoughts.\n",
                    encoding="utf-8")
    svc.repo.update(mid, title="Q3 budget review")
    svc.touched(mid)
    m = svc.repo.get(mid)
    new = root / m["vault_note"]
    assert not path.exists() and new.name == "2026-11-24 1000 Q3 budget review.md"
    text = new.read_text(encoding="utf-8")
    assert text.endswith(MARK + "\nMy own thoughts.\n") and "- [x] Send the Q3 budget" in text
    assert m["summary"]["action_items"][0]["done"] is True  # ticked in Obsidian -> done in PIP
    actions = (root / "PIP Meetings/Action items.md").read_text(encoding="utf-8")
    assert actions.index("## Done") < actions.index("Send the Q3 budget")
    assert safe_name('a/b: "c"?') == "a b c"


# ---- search + questions -----------------------------------------------------------------------------------
def test_search_and_questions_use_only_the_matching_passages(manager, tmp_path) -> None:  # type: ignore[no-untyped-def]
    llm = ScriptedLLM()
    svc = _service(manager, tmp_path, llm)
    budget = _meeting(svc, "Budget chat", [("Ana", "Hello everyone."), ("Sam", "I'll send the Q3 budget by Friday."),
                                           ("Ana", "Great, thanks.")])
    other = _meeting(svc, "Garden club", [("Bo", "The tomatoes need more sun this year.")] * 3)
    for mid in (budget, other):
        svc.touched(mid)
    hits = svc.search("Who sends the budget?")
    assert hits and {h["meeting_id"] for h in hits} == {budget} and "**budget**" in hits[0]["snippet"].lower()
    out = svc.ask("When is the budget being sent?")
    prompt = llm.calls[-1][1]
    assert "I'll send the Q3 budget by Friday." in prompt and "tomatoes" not in prompt
    assert out["sources"][0]["meeting_id"] == budget and out["engine"] == "local/test" and "[Budget chat" in out["answer"]
    n = len(llm.calls)
    assert "couldn't find" in svc.ask("What about the zebra migration?")["answer"] and len(llm.calls) == n  # no call


# ---- end to end over HTTP with a fake Ollama --------------------------------------------------------------
def test_app_summarises_on_this_pc_writes_obsidian_and_answers(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ollama = FakeOllama(models=[])
    vault = tmp_path / "vault"
    vault.mkdir()
    s = Settings(pip_db_path=str(tmp_path / "t.db"), pip_transport="none", pip_use_keyring=False,
                 pip_stt_preload=False, pip_weather=False, pip_prefs_path=str(tmp_path / "prefs.json"),
                 pip_local_ai_url=ollama.url)
    with TestClient(create_app(s)) as c:
        svcs = c.app.state.services  # type: ignore[attr-defined]
        st = c.get("/api/v1/settings/meetings").json()
        assert st["summary_mode"] == "local" and st["local_ai"]["running"] and not st["local_ai"]["model_ready"]
        assert c.post("/api/v1/settings/local-ai/pull").status_code == 200  # the user downloads the model
        deadline = time.monotonic() + 10
        while not c.get("/api/v1/settings/meetings").json()["local_ai"]["model_ready"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert c.put("/api/v1/settings/meetings", json={"obsidian_vault": str(vault)}).json()["obsidian"]["enabled"]
        assert c.put("/api/v1/settings/meetings", json={"obsidian_vault": str(tmp_path / "nope")}).status_code == 404
        svcs.meetings.stt = ScriptedSegmentsSTT([(0.0, 2.0, "Let's start."), (2.2, 4.0, "I'll send the Q3 budget."),
                                                 (4.2, 5.8, "Thanks, bye.")])
        pcm = (np.random.default_rng(0).normal(0, 2000, 16000 * 6)).astype("<i2").tobytes()
        mid = c.post("/api/v1/meetings/import?filename=in.wav&title=Budget%20chat",
                     content=wav_header(len(pcm)) + pcm).json()["id"]
        assert svcs.meetings.wait_idle(30)
        m = c.get(f"/api/v1/meetings/{mid}").json()
        assert m["summary_status"] == "READY" and m["summary_engine"] == "local/qwen3:8b"
        assert m["summary"]["topics"] == ["Q3 budget", "Client deck"]
        assert ollama.chats[-1]["think"] is False and ollama.chats[-1]["format"]["required"][0] == "title"
        assert (vault / m["vault_note"]).exists() and (vault / "PIP Meetings/Meetings index.md").exists()
        hits = c.get("/api/v1/meetings/search?q=budget").json()["hits"]
        assert hits[0]["meeting_id"] == mid
        ans = c.post("/api/v1/meetings/ask", json={"question": "Who sends the budget?"}).json()
        assert "Sam" in ans["answer"] and ans["sources"][0]["meeting_id"] == mid
        items = c.get("/api/v1/meetings/actions").json()["items"]
        assert items[0]["task"] == "Send the Q3 budget" and items[0]["meeting_id"] == mid
        usage = c.get("/api/v1/ai/usage").json()["month"]
        assert usage["cost_usd"] == 0 and usage["by_model"][0]["model"] == "local/qwen3:8b"  # counted, never billed
        ollama.down = True  # a redo while the model is broken: shown on the meeting, no silent switch to Kimi
        assert c.post(f"/api/v1/meetings/{mid}/summarize").json()["queued"]
        assert svcs.meetings.wait_idle(30)
        m = c.get(f"/api/v1/meetings/{mid}").json()
        assert m["summary_status"] == "FAILED" and m["summary"]["title"] == "Budget review"  # the old one stays
        assert c.post("/api/v1/meetings/ask", json={"question": "Who sends the budget?"}).status_code == 503
    ollama.close()
