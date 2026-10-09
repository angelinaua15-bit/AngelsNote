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
    def do_GET(self):
        key = parse_qs(urlparse(self.path).query).get("key", [""])[0]
        if not config.CRON_SECRET or key != config.CRON_SECRET:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return
        host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or self.headers.get("host")
        try:
            res = asyncio.run(runner.setup(host))
            code = 200
        except Exception as e:
            traceback.print_exc()
            res, code = {"error": str(e)}, 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(res).encode())
