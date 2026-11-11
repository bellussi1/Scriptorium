"""Deterministic mock of the Ollama chat API for destructive resume tests."""
from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 11555
DELAY = float(os.getenv("MOCK_DELAY", "0"))
REQUESTS = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/stats"):
            return self._json({"requests": REQUESTS})
        if self.path.startswith("/api/tags"):
            return self._json({"models": [{"name": "mock", "model": "mock"}]})
        if self.path.startswith("/api/ps"):
            return self._json({"models": []})
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        if self.path.startswith("/api/show"):
            return self._json(
                {
                    "model_info": {"general.context_length": 8192},
                    "details": {"family": "mock"},
                }
            )
        if self.path.startswith("/api/chat"):
            global REQUESTS
            REQUESTS += 1
            if DELAY:
                time.sleep(DELAY)
            messages = payload.get("messages") or []
            text = " ".join(str(message.get("content", "")) for message in messages)
            placeholders: list[str] = []
            for match in re.finditer(r"\[id\d+\]", text):
                if match.group(0) not in placeholders:
                    placeholders.append(match.group(0))
            content = "Tradução de teste. " + " ".join(placeholders)
            if payload.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                for start in range(0, len(content), 80):
                    line = {
                        "model": "mock",
                        "created_at": "2026-01-01T00:00:00Z",
                        "message": {
                            "role": "assistant",
                            "content": content[start : start + 80],
                        },
                        "done": False,
                    }
                    self.wfile.write((json.dumps(line) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.02)
                final = {
                    "model": "mock",
                    "created_at": "2026-01-01T00:00:00Z",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "prompt_eval_count": 100,
                    "eval_count": 20,
                }
                self.wfile.write((json.dumps(final) + "\n").encode("utf-8"))
                self.wfile.flush()
                return
            return self._json(
                {
                    "model": "mock",
                    "message": {"role": "assistant", "content": content},
                    "done": True,
                }
            )
        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
