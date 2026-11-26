"""TEST DOUBLE ONLY: a tiny local stand-in for Ollama's HTTP API (/api/tags, /api/chat, /api/generate, /api/pull),
so tests exercise the real LocalAI HTTP path without a GPU or a model download. Answers are deterministic:
part notes / a summary / a plain answer, depending on the JSON schema the request asks for.
`down = True` simulates a crashed server (HTTP 500); `models` is what /api/tags lists; models in `no_think`
answer HTTP 400 to the "think" switch like Ollama does for models that don't reason."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SUMMARY = {"title": "Budget review", "summary": "The team went over the Q3 budget and agreed next steps.",
           "decisions": ["Present to the client on Friday"],
           "action_items": [{"task": "Send the Q3 budget", "owner": "Sam", "due": "Friday"}],
           "topics": ["Q3 budget", "Client deck"]}


class FakeOllama:
    def __init__(self, models: list[str] | None = None) -> None:
        self.models = models if models is not None else ["qwen3:8b"]
        self.down = False
        self.no_think: set[str] = set()
        self.deleted: list[str] = []
        self.delay = 0.0
        self.chats: list[dict[str, Any]] = []
        self.unloads = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a: object) -> None:
                pass

            def _send(self, code: int, obj: object) -> None:
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/api/tags":
                    return self._send(200, {"models": [{"name": m, "size": 5_200_000_000} for m in fake.models]})
                self._send(404, {"error": "not found"})

            def do_DELETE(self) -> None:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path != "/api/delete" or req.get("model") not in fake.models:
                    return self._send(404, {"error": "model not found"})
                fake.models.remove(req["model"])
                fake.deleted.append(req["model"])
                return self._send(200, {})

            def do_POST(self) -> None:
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                if fake.down:
                    return self._send(500, {"error": "model crashed"})
                if self.path == "/api/generate":
                    fake.unloads += 1
                    return self._send(200, {"done": True})
                if self.path == "/api/pull":
                    lines = [{"status": "pulling manifest"}, {"status": "downloading", "completed": 5, "total": 10},
                             {"status": "success"}]
                    body = "".join(json.dumps(x) + "\n" for x in lines).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    fake.models.append(req["model"])
                    return None
                if self.path != "/api/chat":
                    return self._send(404, {"error": "not found"})
                if "think" in req and req.get("model") in fake.no_think:
                    return self._send(400, {"error": f"\"{req['model']}\" does not support thinking"})
                fake.chats.append(req)
                if fake.delay:
                    time.sleep(fake.delay)
                fmt = req.get("format")
                user = req["messages"][-1]["content"]
                if fmt is None:  # a question
                    content = "Sam will send the Q3 budget by Friday [Budget chat @ 00:02]."
                elif "points" in fmt.get("properties", {}):  # notes on one part of a long meeting
                    first = next((ln for ln in user.splitlines() if ln.startswith("[")), "")
                    content = json.dumps({"points": [f"{first[:60]}"], "decisions": [],
                                          "action_items": [{"task": "Send the Q3 budget", "owner": "Sam", "due": None}],
                                          "topics": ["Q3 budget"]})
                else:
                    content = json.dumps(SUMMARY)
                self._send(200, {"message": {"role": "assistant", "content": content}, "done": True,
                                 "prompt_eval_count": len(user) // 4, "eval_count": len(content) // 4})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
