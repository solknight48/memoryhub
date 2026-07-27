"""Local-only HTTP server behind `mh ui`.

Stdlib only — typer stays mh's single runtime dependency. The request handler is
a thin shell over dispatch(), which is a plain function so the API can be tested
without a socket.

This server mutates the hub, so it is not open house: it binds loopback by
default, every request must carry the one-shot token minted at startup (any
page in your browser can POST to 127.0.0.1 otherwise), and the Host header must
name a loopback address so a hostile DNS name cannot be pointed at it.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import checkpoint as ck
from . import curate, git, load
from .hub import MhError, read_current

MAX_BODY = 4 * 1024 * 1024
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _session_rows(c: ck.Checkpoint) -> list[dict]:
    rows = []
    for p in c.sessions:
        text = p.read_text(encoding="utf-8", errors="replace")
        parsed = curate.parse(text)
        rows.append(
            {
                "file": p.name,
                "id": f"{c.slug}/{p.name}",
                "tokens": load.estimate_tokens(text),
                "exchanges": len(parsed.turns) if parsed else None,
                "editable": bool(parsed and parsed.editable),
                "legacy": bool(parsed and parsed.legacy),
                "compacted": bool(parsed and parsed.compacted),
            }
        )
    return rows


def _map(hub: Path, budget: int | None) -> dict:
    cps = ck.list_checkpoints(hub)
    error = None
    try:
        result = load.build(hub, None, True, budget)
        loaded, omitted = result.loaded, result.omitted
        included = [b["id"] for b in result.included]
    except MhError as e:
        # Say why the next load would be empty; a greyed-out map with no
        # explanation is the same dead end the git errors below avoid.
        loaded, included, omitted, error = [], [], [], e.message
    return {
        "checkpoints": [
            {
                "slug": c.slug,
                "created": c.created,
                "sessions": _session_rows(c),
            }
            for c in cps
        ],
        "links": [list(e) for e in ck.read_links(hub)],
        "current": read_current(hub),
        "budget": budget,
        "load": {
            "loaded": loaded,
            "included": included,
            "omitted": omitted,
            "error": error,
        },
    }


def _session(hub: Path, ckpt: str, file: str) -> dict:
    c, path = curate.resolve_session(hub, ckpt, file)
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = curate.parse(text)
    return {
        "checkpoint": c.slug,
        "file": path.name,
        "editable": bool(parsed and parsed.editable),
        "legacy": bool(parsed and parsed.legacy),
        "compacted": bool(parsed and parsed.compacted),
        "reason": curate.readonly_reason(parsed),
        "raw": text if parsed is None or parsed.compacted else None,
        "source": parsed.source if parsed else None,
        "session_id": parsed.session_id if parsed else None,
        "exchanges": [
            {"index": i, "user": u, "agent": a}
            for i, (u, a) in enumerate(parsed.turns if parsed else [], 1)
        ],
    }


def _need(body: dict, *keys: str) -> list:
    out = []
    for k in keys:
        if k not in body or body[k] in (None, ""):
            raise MhError(f"missing '{k}'")
        out.append(body[k])
    return out


def dispatch(
    hub: Path, method: str, path: str, query: dict, body: dict, read_only: bool
) -> tuple[int, dict]:
    """Route one API call. Pure over the filesystem — no socket involved."""
    if method == "GET":
        if path == "/api/map":
            raw = query.get("budget") or str(load.DEFAULT_BUDGET)
            budget = None if raw in ("", "none", "all") else int(raw)
            return 200, _map(hub, budget)
        if path == "/api/session":
            ckpt, file = _need(query, "ckpt", "file")
            return 200, _session(hub, ckpt, file)
        return 404, {"error": f"no route {path}"}

    if method != "POST":
        return 405, {"error": "method not allowed"}
    if read_only:
        return 403, {"error": "server is running with --read-only"}

    if path == "/api/exchange/delete":
        ckpt, file, index = _need(body, "ckpt", "file", "index")
        return 200, curate.delete_exchange(hub, ckpt, file, int(index))
    if path == "/api/exchange/edit":
        ckpt, file, index = _need(body, "ckpt", "file", "index")
        return 200, curate.edit_exchange(
            hub, ckpt, file, int(index), body.get("user"), body.get("agent")
        )
    if path == "/api/session/delete":
        ckpt, file = _need(body, "ckpt", "file")
        return 200, curate.delete_session(hub, ckpt, file)
    if path == "/api/session/move":
        ckpt, file, to = _need(body, "ckpt", "file", "to")
        return 200, curate.move_session(hub, ckpt, file, to)
    if path == "/api/checkpoint/rename":
        slug, name = _need(body, "slug", "name")
        return 200, curate.rename_checkpoint(hub, slug, name)
    if path == "/api/checkpoint/delete":
        (slug,) = _need(body, "slug")
        return 200, curate.delete_checkpoint(hub, slug)
    if path == "/api/checkpoint/create":
        (name,) = _need(body, "name")
        c = ck.create(hub, name)
        return 200, {"slug": c.slug, "created": c.created}
    if path == "/api/link":
        a, b = _need(body, "a", "b")
        edge = ck.add_link(hub, a, b)
        return 200, {"linked": list(edge) if edge else None}
    if path == "/api/unlink":
        a, b = _need(body, "a", "b")
        edge = ck.remove_link(hub, a, b)
        return 200, {"unlinked": list(edge) if edge else None}
    return 404, {"error": f"no route {path}"}


def _page() -> bytes:
    from importlib.resources import files

    return files("memoryhub").joinpath("ui/index.html").read_bytes()


def make_handler(hub: Path, token: str, read_only: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "mh"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet; mh prints its own line
            pass

        def _send(self, status: int, payload: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj).encode(), "application/json")

        def _authorized(self, query: dict) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in ALLOWED_HOSTS:
                return False
            supplied = self.headers.get("X-Mh-Token") or query.get("t", "")
            return secrets.compare_digest(supplied, token)

        def _handle(self, method: str) -> None:
            parts = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            if not self._authorized(query):
                self._json(403, {"error": "bad or missing token"})
                return
            if method == "GET" and parts.path in ("/", "/index.html"):
                self._send(200, _page(), "text/html; charset=utf-8")
                return
            body = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self._json(413, {"error": "body too large"})
                    return
                if length:
                    try:
                        body = json.loads(self.rfile.read(length) or b"{}")
                    except json.JSONDecodeError:
                        self._json(400, {"error": "invalid JSON body"})
                        return
            try:
                status, obj = dispatch(
                    hub, method, parts.path, query, body, read_only
                )
            except MhError as e:
                status, obj = 400, {"error": e.message}
            except git.GitError as e:
                # Surface git's own words, or an unset user.email leaves the
                # user stuck on a bare "git failed".
                status, obj = 409, {
                    "error": git.explain(e),
                    "detail": "\n".join(git.stderr_lines(e)[:8]),
                }
            except (ValueError, KeyError) as e:
                status, obj = 400, {"error": str(e)}
            self._json(status, obj)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def serve(
    hub: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    read_only: bool = False,
) -> None:
    token = secrets.token_urlsafe(16)
    httpd = ThreadingHTTPServer((host, port), make_handler(hub, token, read_only))
    url = f"http://{host}:{httpd.server_address[1]}/?t={token}"
    # flush: serve_forever() blocks, so a piped stdout would otherwise hold the
    # URL in the buffer and show the user nothing at all.
    print(f"mh ui: {url}", flush=True)
    print(f"hub: {hub}" + ("  (read-only)" if read_only else ""), flush=True)
    print("ctrl-c to stop", flush=True)
    if open_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.shutdown()
        httpd.server_close()
