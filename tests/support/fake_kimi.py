"""TEST DOUBLE ONLY: a tiny local stand-in for the Moonshot API so integration/E2E tests exercise the real
KimiPlanner HTTP path without network or a real key. It answers with deterministic plans built by the
offline rule engine. `FakeKimi.down = True` simulates an outage (HTTP 503)."""
from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "host"))
from service.planner.local_rule import LocalRulePlanner  # noqa: E402

MODEL = "kimi-k3.1-pro-highspeed"


class FakeKimi:
    def __init__(self) -> None:
        self.down = False
        self.calls = 0
        planner = LocalRulePlanner()
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

            def do_GET(self) -> None:  # noqa: N802
                if fake.down:
                    return self._send(503, {"error": {"message": "service unavailable"}})
                self._send(200, {"data": [{"id": MODEL}, {"id": "kimi-k2.6"}]})

            def do_POST(self) -> None:  # noqa: N802
                fake.calls += 1
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if fake.down:
                    return self._send(503, {"error": {"message": "service unavailable"}})
                said = re.search(r"What I said: (.*)$", req["messages"][-1]["content"], re.S)
                plan = planner.plan(said.group(1) if said else "")
                self._send(200, {"choices": [{"message": {"content": plan.model_dump_json()}}]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
