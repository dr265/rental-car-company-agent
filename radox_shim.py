"""Local shim for the radoxai.com OpenAI-compatible gateway.

Problem: some clients ((stripped)Code) send BOTH `max_tokens` AND `max_completion_tokens`
in one /chat/completions request. The gateway answers
  400 `max_tokens` and `max_completion_tokens` are mutually exclusive
for every model, so nothing works.

This shim sits on http://127.0.0.1:8791, forwards everything to
https://radoxai.com unchanged EXCEPT it keeps only `max_tokens`
(the field this gateway provenly accepts), and forces a browser
User-Agent because the gateway's Cloudflare blocks script UAs.

Usage:
  1. python radox_shim.py        (keep this window open)
  2. In ZCode provider settings set Base URL to: http://127.0.0.1:8791/v1
     (same API key, same model ids, e.g. claude-fable-5.1)
"""
import json
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM_HOST = "radoxai.com"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PORT = 8791

_HOP = {"connection", "keep-alive", "proxy-connection",
        "transfer-encoding", "upgrade"}


def patch_body(raw: bytes) -> bytes:
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw
    if isinstance(obj, dict):
        if "max_tokens" in obj and "max_completion_tokens" in obj:
            obj.pop("max_completion_tokens", None)
        elif "max_completion_tokens" in obj and "max_tokens" not in obj:
            obj["max_tokens"] = obj.pop("max_completion_tokens")
    return json.dumps(obj).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # connection-close framing: safe for SSE streams
    server_version = "RadoxShim/1.0"

    def log_message(self, *args):  # quiet
        pass

    def _forward(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        if self.command in ("POST", "PUT", "PATCH") and raw:
            raw = patch_body(raw)
        fwd = {}
        for k, v in self.headers.items():
            lk = k.lower()
            if lk in _HOP or lk in ("host", "content-length"):
                continue
            fwd[k] = v
        fwd["User-Agent"] = BROWSER_UA
        fwd["Host"] = UPSTREAM_HOST
        fwd["Connection"] = "close"
        try:
            conn = http.client.HTTPSConnection(UPSTREAM_HOST, timeout=300)
            conn.request(self.command, self.path, body=raw or None, headers=fwd)
            resp = conn.getresponse()
        except Exception as exc:  # noqa: BLE001 - upstream unreachable
            body = json.dumps({"error": f"shim upstream failed: {exc}"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() in _HOP or k.lower() == "content-length":
                continue
            self.send_header(k, v)
        self.end_headers()
        try:
            while True:
                chunk = resp.read(16384)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            conn.close()

    do_GET = _forward
    do_POST = _forward
    do_PUT = _forward
    do_PATCH = _forward
    do_DELETE = _forward
    do_OPTIONS = _forward


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"radox shim listening on http://127.0.0.1:{PORT} -> https://{UPSTREAM_HOST}")
    print("Set ZCode Base URL to http://127.0.0.1:8791/v1 (keep key + models). Ctrl+C to stop.")
    srv.serve_forever()
