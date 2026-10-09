import asyncio
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planner import config, runner  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def _run(self):
        key = self.headers.get("x-cron-secret") or parse_qs(urlparse(self.path).query).get("key", [""])[0]
        if not config.CRON_SECRET or key != config.CRON_SECRET:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return
        try:
            res = asyncio.run(runner.handle_cron())
            code = 200
        except Exception as e:
            traceback.print_exc()
            res, code = {"error": str(e)}, 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(res).encode())

    do_GET = _run
    do_POST = _run
