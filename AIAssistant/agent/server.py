"""Local HTTP server: static SPA, JSON API, SSE event stream, MCP endpoint.

Security: 127.0.0.1 only, random port, random token required for every /api and
/mcp call, Host header must be localhost (blocks DNS rebinding)."""
import base64
import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

from . import mcp

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")
MAX_BODY = 80 * 1024 * 1024
IMAGE_MIME = {"image/png", "image/jpeg"}
MODEL_EXT = (".stl", ".obj", ".3mf")


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(name or "file"))[:80] or "file"


class App(object):
    def __init__(self, settings, llm, agent, registry, bus, token):
        self.settings, self.llm, self.agent, self.registry, self.bus, self.token = settings, llm, agent, registry, bus, token
        self.httpd = None
        self.url = None


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        # helpers
        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _guard(self, query):
            host = self.headers.get("Host", "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                self._json(403, {"error": "bad host"})
                return False
            tok = self.headers.get("X-Token") or (query.get("t") or [""])[0]
            if tok != app.token:
                self._json(401, {"error": "bad token"})
                return False
            return True

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("Слишком большой запрос")
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

        # GET
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/events":
                if self._guard(q):
                    self._sse(int((q.get("after") or ["0"])[0]))
                return
            if u.path == "/api/settings":
                if self._guard(q):
                    self._json(200, app.settings.public())
                return
            self._static(u.path)

        def _static(self, path):
            host = self.headers.get("Host", "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                self.send_error(403)
                return
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(WEB_DIR, rel))
            root = os.path.realpath(WEB_DIR)
            if not full.startswith(root + os.sep) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", (mimetypes.guess_type(full)[0] or "application/octet-stream") + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _sse(self, after):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = app.bus.subscribe(after)
            try:
                while True:
                    try:
                        ev = q.get(timeout=15)
                        data = "id: %d\ndata: %s\n\n" % (ev["seq"], json.dumps(ev, ensure_ascii=False))
                    except Exception:
                        data = ": keepalive\n\n"
                    self.wfile.write(data.encode("utf-8"))
                    self.wfile.flush()
            except (OSError, ValueError):
                pass
            finally:
                app.bus.unsubscribe(q)

        # POST
        def do_POST(self):
            u = urlparse(self.path)
            if not self._guard(parse_qs(u.query)):
                return
            try:
                data = self._body()
                if u.path == "/api/message":
                    return self._message(data)
                if u.path == "/api/settings":
                    for k in ("base_url", "model", "output_dir"):
                        if isinstance(data.get(k), str) and data[k].strip():
                            app.settings.set(k, data[k].strip())
                    if isinstance(data.get("api_key"), str) and data["api_key"].strip():
                        app.settings.set("api_key", data["api_key"].strip())
                    return self._json(200, app.settings.public())
                if u.path == "/api/test":
                    try:
                        app.llm.ping()
                        return self._json(200, {"ok": True})
                    except Exception as e:
                        return self._json(200, {"ok": False, "error": str(e)})
                if u.path == "/api/reset":
                    app.agent.reset()
                    return self._json(200, {"ok": True})
                if u.path == "/mcp":
                    resp = mcp.handle(app.registry, data)
                    return self._json(200, resp) if resp is not None else self._json(202, {})
                self._json(404, {"error": "not found"})
            except ValueError as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": str(e)})

        def _message(self, data):
            text = (data.get("text") or "").strip()
            atts = []
            for a in data.get("attachments") or []:
                raw = base64.b64decode(a.get("b64") or "")
                name = _safe_name(a.get("name"))
                if a.get("mime") in IMAGE_MIME:
                    atts.append({"kind": "image", "name": name, "mime": a["mime"], "b64": a["b64"]})
                elif name.lower().endswith(MODEL_EXT):
                    path = os.path.join(app.settings.uploads_dir(), name)
                    with open(path, "wb") as f:
                        f.write(raw)
                    atts.append({"kind": "model", "name": name, "path": path})
                else:
                    raise ValueError("Файл %s не поддерживается" % name)
            if not text and not atts:
                raise ValueError("Пустое сообщение")
            if app.agent.busy:
                return self._json(409, {"error": "Агент занят"})
            app.bus.emit(type="user", text=text, files=[a["name"] for a in atts])
            threading.Thread(target=app.agent.handle, args=(text, atts), daemon=True).start()
            self._json(202, {"accepted": True})

    return Handler


def serve(app, port=0):
    httpd = _Server(("127.0.0.1", port), make_handler(app))
    app.httpd = httpd
    app.url = "http://127.0.0.1:%d/?t=%s" % (httpd.server_port, app.token)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return app
