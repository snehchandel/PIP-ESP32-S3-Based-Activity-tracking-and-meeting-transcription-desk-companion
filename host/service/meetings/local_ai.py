"""Local AI on this PC (Ollama, http://127.0.0.1:11434) for meeting summaries and questions about meetings.

Nothing leaves the PC and nothing is billed. Every call asks for JSON that must match a schema (Ollama's
structured outputs), so a small model cannot wander off format. Token counts are still recorded in the AI usage
table under "local/<model>" at a price of zero, so the app shows how much work the summaries take.

This is not a planner: Kimi stays the only planner (ADR-013). If the local AI is missing or fails, the summary is
marked failed and the user may choose Kimi for it - nothing switches over silently."""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger("pip.local_ai")
DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3:8b"
NUM_CTX = 8192          # tokens of context per call: fits an 8B model + its cache in 8 GB of VRAM
KEEP_ALIVE = "2m"       # Ollama frees the model this long after the last call (VRAM back for Whisper)
UsageSink = Callable[[str, str, dict[str, Any]], None]


class LocalAIError(RuntimeError):
    pass


class LocalAI:
    def __init__(self, base_url: str = DEFAULT_URL, model: Callable[[], str] | str = DEFAULT_MODEL,
                 on_usage: UsageSink | None = None, timeout: float = 600.0,
                 client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.on_usage = on_usage
        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout, connect=3.0))
        self.pull_state: dict[str, Any] = {"active": False, "model": "", "status": "", "error": ""}

    @property
    def model(self) -> str:
        return self._model() if callable(self._model) else self._model

    @property
    def engine(self) -> str:
        return f"local/{self.model}"

    # ---- status ----------------------------------------------------------------------------------
    def models(self) -> list[str]:
        try:
            r = self.client.get(f"{self.base_url}/api/tags", timeout=3.0)
            r.raise_for_status()
            return sorted(str(m.get("name", "")) for m in r.json().get("models", []))
        except (httpx.HTTPError, ValueError) as e:
            raise LocalAIError(f"local AI not running at {self.base_url} ({type(e).__name__})") from e

    def has_model(self, models: list[str]) -> bool:
        want = self.model
        return want in models or (":" not in want and f"{want}:latest" in models)

    def status(self) -> dict[str, Any]:
        try:
            models = self.models()
        except LocalAIError as e:
            return {"running": False, "url": self.base_url, "model": self.model, "model_ready": False,
                    "models": [], "detail": str(e), "pull": dict(self.pull_state)}
        ready = self.has_model(models)
        return {"running": True, "url": self.base_url, "model": self.model, "model_ready": ready, "models": models,
                "detail": "ready" if ready else f"model {self.model} is not downloaded yet",
                "pull": dict(self.pull_state)}

    def check_ready(self) -> None:
        if not self.has_model(self.models()):
            raise LocalAIError(f"local AI model {self.model} is not downloaded (Settings -> Meetings)")

    # ---- calls -------------------------------------------------------------------------------------
    def _chat(self, messages: list[dict[str, str]], purpose: str, fmt: dict[str, Any] | None,
              max_out: int) -> str:
        body: dict[str, Any] = {
            "model": self.model, "messages": messages, "stream": False, "think": False, "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0.2, "num_ctx": NUM_CTX, "num_predict": max_out},
        }
        if fmt is not None:
            body["format"] = fmt
        try:
            r = self.client.post(f"{self.base_url}/api/chat", json=body)
        except httpx.HTTPError as e:
            raise LocalAIError(f"local AI unreachable ({type(e).__name__})") from e
        if r.status_code >= 400:
            try:
                detail = str(r.json().get("error", ""))[:160]
            except ValueError:
                detail = ""
            raise LocalAIError(f"local AI HTTP {r.status_code} {detail}".strip())
        try:
            data = r.json()
            content = str(data["message"]["content"])
        except (ValueError, KeyError, TypeError) as e:
            raise LocalAIError("local AI answer had no content") from e
        if self.on_usage:
            try:
                self.on_usage(self.engine, purpose, {"prompt_tokens": int(data.get("prompt_eval_count") or 0),
                                                     "completion_tokens": int(data.get("eval_count") or 0)})
            except Exception:  # metering must never break a summary
                log.exception("recording local AI usage failed")
        return content

    def chat_json(self, system: str, user: str, schema: dict[str, Any], purpose: str,
                  max_out: int = 1200) -> dict[str, Any]:
        content = self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                             purpose, schema, max_out)
        try:
            out = json.loads(content)
        except ValueError as e:
            raise LocalAIError("local AI returned broken JSON") from e
        if not isinstance(out, dict):
            raise LocalAIError("local AI returned JSON that is not an object")
        return out

    def chat_text(self, system: str, user: str, purpose: str, max_out: int = 700) -> str:
        return self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                          purpose, None, max_out).strip()

    def unload(self) -> None:
        """Free the model's (V)RAM now instead of after KEEP_ALIVE (best effort)."""
        try:
            self.client.post(f"{self.base_url}/api/generate", json={"model": self.model, "keep_alive": 0},
                             timeout=5.0)
        except httpx.HTTPError:
            pass

    # ---- model download (started by the user in Settings) ---------------------------------------------
    def pull(self, model: str) -> bool:
        """Download `model` through Ollama in the background. False if a download is already running."""
        if self.pull_state["active"]:
            return False
        self.pull_state = {"active": True, "model": model, "status": "starting", "error": ""}

        def run() -> None:
            try:
                with self.client.stream("POST", f"{self.base_url}/api/pull", json={"model": model, "stream": True},
                                        timeout=httpx.Timeout(None, connect=3.0)) as r:
                    if r.status_code >= 400:
                        raise LocalAIError(f"HTTP {r.status_code}")
                    for line in r.iter_lines():
                        if not line:
                            continue
                        ev = json.loads(line)
                        if ev.get("error"):
                            raise LocalAIError(str(ev["error"])[:160])
                        done, total = ev.get("completed"), ev.get("total")
                        pct = f" {100 * done / total:.0f}%" if done and total else ""
                        self.pull_state["status"] = f"{ev.get('status', '')}{pct}"
                self.pull_state.update(active=False, status="done")
            except Exception as e:
                log.warning("pulling %s failed: %s", model, e)
                self.pull_state.update(active=False, status="failed", error=str(e)[:160])

        threading.Thread(target=run, name="pip-ollama-pull", daemon=True).start()
        return True
