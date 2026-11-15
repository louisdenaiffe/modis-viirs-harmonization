#!/usr/bin/env python3
"""Static file server for Fire Globe that supports partial downloads ("Range" requests),
which Python's built-in server does not. The app uses them to read small pieces of
large data files.

    python3 tools/serve.py [port]      then open http://localhost:8765
"""
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        m = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        path = self.translate_path(self.path)
        if not m or not os.path.isfile(path):
            return super().do_GET()
        size = os.path.getsize(path)
        start = int(m.group(1))
        end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
        if start > end:
            self.send_error(416, "Requested range not satisfiable")
            return
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            self.wfile.write(fh.read(end - start + 1))

    def do_PUT(self):
        """Save data/countries.bin sent by the app's ?precompute page (this computer only)."""
        if self.path.split("?")[0] != "/data/countries.bin":
            self.send_error(403, "Only data/countries.bin can be saved")
            return
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length)
        tmp = os.path.join(ROOT, "data", "countries.bin.tmp")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, os.path.join(ROOT, "data", "countries.bin"))
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"Fire Globe on http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
