import asyncio
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planner import config, runner  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes = b"ok") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, "🪴 planner bot is alive".encode())

    def do_POST(self):
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != config.WEBHOOK_SECRET:
            return self._send(403, b"forbidden")
        try:
            n = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            asyncio.run(runner.handle_update(body))
        except Exception:
            traceback.print_exc()
        self._send(200)
