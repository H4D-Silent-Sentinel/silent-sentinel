"""Tiny local web map: http://127.0.0.1:8080 (polls /state.json once a second)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files


def serve(base, host: str = "127.0.0.1", port: int = 8080, log=print) -> ThreadingHTTPServer:
    page = files("cuas").joinpath("static/map.html").read_bytes()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/state.json"):
                body, ctype = json.dumps(base.state()).encode(), "application/json"
            elif self.path in ("/", "/index.html"):
                body, ctype = page, "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="map").start()
    log(f"map: http://{host}:{port}")
    return srv
