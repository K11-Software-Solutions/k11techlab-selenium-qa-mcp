"""Tiny demo app server with a switchable "redesign".

  python demo/server.py --port 8765 --version v1

/login.html          sign-in page (sets a session in localStorage)
/account.html        account page, v1 or v2 (v2 is the redesign)
/store/login.html    stand-alone login page used by the "see it heal" example, v1 or v2
"""

from __future__ import annotations

import argparse
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent


class DemoServer:
    def __init__(self, port: int = 0, version: str = "v1"):
        self.version = version
        demo = self

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0].split("#")[0]
                files = {
                    "/login.html": HERE / "app" / "login.html",
                    "/account.html": HERE / "app" / demo.version / "account.html",
                    "/store/login.html": HERE / demo.version / "login.html",
                }
                f = files.get(path)
                if path == "/":
                    self.send_response(302)
                    self.send_header("Location", "/login.html")
                    self.end_headers()
                    return
                if not f or not f.is_file():
                    self.send_error(404)
                    return
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> "DemoServer":
        self.thread.start()
        return self

    def set_version(self, version: str) -> None:
        self.version = version

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--version", default="v1", choices=["v1", "v2"])
    a = ap.parse_args()
    s = DemoServer(a.port, a.version)
    print(f"Demo app ({a.version}) on {s.url}  (Ctrl-C to stop)")
    try:
        s.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
