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

import errno
import json
import os
import secrets
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import __version__, curate, git, load, purify
from . import checkpoint as ck
from . import commands as commandsmod
from . import live as livemod
from . import memory as memorymod
from . import relay as relaymod
from . import templates as tmpl
from .hub import MhError, project_root_of, read_current, write_current

MAX_BODY = 4 * 1024 * 1024
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
DEFAULT_PORT = 7777


class MapServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind reverse-resolves the bind address for the
        # Server header (socket.getfqdn) — worth thirty stuck seconds on a
        # machine with no resolver, worth nothing to a loopback-only map.
        socketserver.TCPServer.server_bind(self)
        self.server_name = str(self.server_address[0])
        self.server_port = self.server_address[1]


UI_RECORD = "ui.json"  # the detached server, if any: pid and URL — untracked
UI_LOG = "ui.log"


def _session_rows(c: ck.Checkpoint) -> list[dict]:
    rows = []
    for p in c.sessions:
        text = p.read_text(encoding="utf-8", errors="replace")
        parsed = curate.parse(text)
        if parsed and parsed.turns:
            first = parsed.turns[0][0]
        elif parsed and parsed.compacted:
            first = parsed.summary
        else:
            first = ""
        preview = " ".join(first.split())
        if len(preview) > 160:
            preview = preview[:160] + "…"
        # the model that answered most of the session, "" when none was recorded
        named = [m for m in (parsed.models if parsed else []) if m]
        model = max(set(named), key=named.count) if named else ""
        rows.append(
            {
                "file": p.name,
                "id": f"{c.slug}/{p.name}",
                "model": model,
                "tokens": load.estimate_tokens(text),
                "exchanges": len(parsed.turns) if parsed else None,
                "editable": bool(parsed and parsed.editable),
                "legacy": bool(parsed and parsed.legacy),
                "compacted": bool(parsed and parsed.compacted),
                "preview": preview,
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
    placed = ck.read_stages(hub)
    return {
        "checkpoints": [
            {
                "slug": c.slug,
                "stage": ck.stage_of(hub, c.slug, placed),
                "created": c.created,
                "sessions": _session_rows(c),
            }
            for c in cps
        ],
        # the timeline's columns: checkpoints at one stage stack under one node
        "stages": ck.stages(hub, cps),
        "links": [list(e) for e in ck.read_links(hub)],
        "current": read_current(hub),
        "budget": budget,
        # the stage template, with the stages still ahead: the map draws them
        "template": tmpl.progress(hub),
        "templates": tmpl.catalogue(),
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
    sid = parsed.session_id if parsed else None
    original = livemod.find(hub, sid) if sid else None
    return {
        "checkpoint": c.slug,
        "file": path.name,
        "editable": bool(parsed and parsed.editable),
        "legacy": bool(parsed and parsed.legacy),
        "compacted": bool(parsed and parsed.compacted),
        "reason": curate.readonly_reason(parsed),
        "raw": text if parsed is None or parsed.compacted else None,
        "source": parsed.source if parsed else None,
        "session_id": sid,
        # the original transcript, when it is still on this machine: the live
        # panel can open it unfiltered, keyed by this id
        "original": {"key": original.key, "agent": original.agent} if original else None,
        "exchanges": [
            {
                "index": i,
                "user": u,
                "agent": a,
                # "" for anything saved before mh recorded models; the UI shows
                # no badge rather than inventing one
                "model": parsed.models[i - 1] if i <= len(parsed.models) else "",
            }
            for i, (u, a) in enumerate(parsed.turns if parsed else [], 1)
        ],
    }


def _live_exchanges(ls: livemod.LiveSession, entries: dict) -> list[dict]:
    """The live dialog as the page shows it: the transcript's exchanges with
    the draft's decisions marked on them. An entry whose anchor no longer
    matches the transcript is ignored here exactly as it is at save time."""
    rows = []
    for i, (user, agent) in enumerate(ls.turns, 1):
        entry = entries.get(str(i)) or {}
        live_entry = entry.get("anchor") == user
        edited = live_entry and ("user" in entry or "agent" in entry)
        dropped = bool(live_entry and entry.get("drop"))
        row = {
            "index": i,
            "user": entry.get("user", user) if edited else user,
            "agent": entry.get("agent", agent) if edited else agent,
            "model": ls.models[i - 1] if i <= len(ls.models) else "",
            "dropped": dropped,
            "edited": bool(edited),
            # the answer is still being written; every save drops it
            "pending": i == len(ls.turns) and ls.pending,
        }
        # The unfiltered stream is for reading the session as it happens. An
        # edited turn shows what will be stored instead, and a dropped one is
        # collapsed to a line, so neither carries it.
        if ls.parts is not None and not dropped and not edited:
            row["parts"] = ls.parts[i - 1]
        if i <= len(ls.images) and ls.images[i - 1] and not dropped:
            # pictures pasted with the question: descriptors and where to
            # fetch each, decoded from the transcript on request
            row["images"] = [
                {
                    "n": n,
                    "type": img["media_type"],
                    "size": img["size"],
                    "url": f"/api/live/image?sid={quote(ls.key)}&index={i}&n={n}",
                }
                for n, img in enumerate(ls.images[i - 1], 1)
            ]
        rows.append(row)
    return rows


# --- pictures ----------------------------------------------------------------
# Two kinds show in the panel: a local image file the agent read (a screenshot
# it took), and a picture pasted into the session, which Claude Code keeps as
# base64 in the transcript. Both are served by this process, bytes sniffed —
# an image route that would hand out any file is a different thing entirely.

MAX_IMAGE = 32 * 1024 * 1024
IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sniff_image(data: bytes) -> str | None:
    for magic, ctype in IMAGE_MAGIC:
        if data.startswith(magic):
            return ctype
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_file(raw: str) -> tuple[bytes, str]:
    """A local image file for the page: (bytes, content type). Anything that
    is not an absolute path to a real PNG/JPEG/GIF/WebP is refused."""
    path = Path(raw) if raw else None
    if path is None or not path.is_absolute():
        raise MhError("an absolute path to an image file is required")
    if not path.is_file():
        raise MhError(f"no such file: {raw}")
    if path.stat().st_size > MAX_IMAGE:
        raise MhError(f"{path.name} is larger than {MAX_IMAGE // (1024 * 1024)} MB")
    data = path.read_bytes()
    ctype = sniff_image(data)
    if ctype is None:
        raise MhError(f"{path.name} is not an image mh can show")
    return data, ctype


def live_image(hub: Path, query: dict) -> tuple[bytes, str]:
    """A picture pasted into the live session: (bytes, content type)."""
    try:
        index, n = int(query.get("index", "")), int(query.get("n", ""))
    except ValueError:
        raise MhError("index and n must be integers") from None
    _media, data = livemod.image(hub, query.get("sid") or None, index, n)
    ctype = sniff_image(data)
    if ctype is None:
        raise MhError("the recorded picture is not an image mh can show")
    return data, ctype


def _saved_copy(hub: Path, ls: livemod.LiveSession, entries: dict) -> dict | None:
    """Where this session already lives in the hub, and whether that copy still
    says what a save right now would say."""
    where, path = ck.find_by_key(hub, ls.key)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = curate.parse(text)
    turns, models, _, _ = livemod.curated(ls, entries)
    fresh = purify.render(turns, str(ls.path), ls.sid, models) if turns else None
    return {
        "checkpoint": where.slug,
        "file": path.name,
        "exchanges": len(parsed.turns) if parsed and not parsed.compacted else None,
        "compacted": bool(parsed and parsed.compacted),
        "in_sync": fresh is not None and text == fresh,
    }


def _live(hub: Path, fp: str, sid: str | None, full: bool = False) -> dict:
    cands = livemod.candidates(project_root_of(hub))
    if not cands:
        return {
            "present": False,
            "reason": "no transcript for this project yet (claude, pi, codex)",
        }
    d = livemod.pick(cands, sid)
    _where, stored = ck.find_by_key(hub, d.key)
    now = livemod.fingerprint(hub, d.key, d.path, stored)
    clock = time.time()
    head = {
        "present": True,
        "fp": now,
        "key": d.key,
        "agent": d.agent,
        "session_id": d.sid,
        "file": d.path.name,
        "current": read_current(hub),
        # newest first; `idle` is seconds since the transcript was last written
        # — how the page tells a session that ended from one merely older than
        # the one it was asked to follow
        "newest": cands[0].key,
        "sessions": [
            {
                "sid": c.sid,
                "key": c.key,
                "agent": c.agent,
                "file": c.path.name,
                "idle": int(max(0.0, clock - livemod._mtime(c.path))),
            }
            for c in cands[:12]
        ],
    }
    # Nothing moved since the client last asked: one stat beats re-purifying a
    # transcript every couple of seconds.
    if fp and fp == now:
        return {**head, "unchanged": True}
    ls = livemod.from_discovered(d, full)
    entries = livemod.read_draft(hub, ls.key)
    turns, _models, applied, stale = livemod.curated(ls, entries)
    return {
        **head,
        "unchanged": False,
        # the page asked for the raw stream and this agent's blocks are known
        "stream": ls.parts is not None,
        "exchanges": _live_exchanges(ls, entries),
        "pending": ls.pending,
        "edits": len(entries),
        "applied": applied,
        "stale": stale,
        "would_store": len(turns),
        "saved": _saved_copy(hub, ls, entries),
        # where a message typed in the page would land, or why it cannot
        "terminal": relaymod.target(hub, ls),
    }


def _commands(hub: Path, sid: str | None) -> dict:
    """What the composer may offer at the start of a message: the skills and
    commands of the agent behind the followed session, read from disk now, so
    a skill installed a minute ago is already on the list."""
    ls = livemod.read(hub, sid)
    if ls is None:
        raise MhError("no transcript for this project yet (claude, pi, codex)")
    return commandsmod.commands(ls.agent, project_root_of(hub))


def _memory(hub: Path) -> dict:
    """Claude Code's per-project memory for the page (read-only). Each note that
    still has its origin transcript on this machine is marked, so the page can
    open it in the live panel the way a saved session does."""
    data = memorymod.read(project_root_of(hub))
    for m in data["memories"]:
        origin = livemod.find(hub, m["origin"]) if m["origin"] else None
        m["origin_here"] = origin is not None
        m["origin_key"] = origin.key if origin else (m["origin"][:8] if m["origin"] else None)
    return data


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
        if path == "/api/live":
            return 200, _live(
                hub,
                query.get("fp", ""),
                query.get("sid") or None,
                query.get("full") == "1",
            )
        if path == "/api/memory":
            return 200, _memory(hub)
        if path == "/api/live/commands":
            return 200, _commands(hub, query.get("sid") or None)
        return 404, {"error": f"no route {path}"}

    if method != "POST":
        return 405, {"error": "method not allowed"}
    if read_only:
        return 403, {"error": "server is running with --read-only"}

    if path == "/api/live/save":
        return 200, livemod.save(hub, body.get("to") or None, body.get("sid") or None)
    if path == "/api/live/drop":
        (index,) = _need(body, "index")
        return 200, livemod.drop(hub, int(index), body.get("sid") or None)
    if path == "/api/live/restore":
        (index,) = _need(body, "index")
        return 200, livemod.revert(hub, int(index), body.get("sid") or None)
    if path == "/api/live/edit":
        (index,) = _need(body, "index")
        return 200, livemod.edit(
            hub, int(index), body.get("user"), body.get("agent"), body.get("sid") or None
        )
    if path == "/api/live/say":
        (text,) = _need(body, "text")
        return 200, relaymod.send(hub, text, body.get("sid") or None)
    if path == "/api/live/discard":
        return 200, livemod.discard(hub, body.get("sid") or None)

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
        # a name, or a stage to add one more take at (named design-2, design-3, …)
        at = body.get("at") or None
        name = body.get("name") or (ck.next_at(hub, at) if at else None)
        if not name:
            raise MhError("missing 'name'")
        c = ck.create(hub, name, stage=at)
        return 200, {"slug": c.slug, "created": c.created, "stage": ck.stage_of(hub, c.slug)}
    if path == "/api/template":
        # {"name": "quant"} chooses one; {"name": null} stops using any
        if body.get("name"):
            return 200, tmpl.use(hub, str(body["name"]))
        tmpl.clear(hub)
        return 200, {"name": None}
    if path == "/api/template/stages":
        (stages,) = _need(body, "stages")
        return 200, tmpl.set_stages(hub, stages)
    if path == "/api/goto":
        (slug,) = _need(body, "slug")
        c = ck.resolve(hub, str(slug))
        write_current(hub, c.slug)
        return 200, {"current": c.slug}
    if path == "/api/link":
        a, b = _need(body, "a", "b")
        edge = ck.add_link(hub, a, b)
        return 200, {"linked": list(edge) if edge else None}
    if path == "/api/unlink":
        a, b = _need(body, "a", "b")
        edge = ck.remove_link(hub, a, b)
        return 200, {"unlinked": list(edge) if edge else None}
    return 404, {"error": f"no route {path}"}


CONFIG_MARKER = b'<script id="mh-config" type="application/json">{}</script>'


def _page(budget: int | None, read_only: bool, hub: Path) -> bytes:
    from importlib.resources import files

    html = files("memoryhub").joinpath("ui/index.html").read_bytes()
    if html.count(CONFIG_MARKER) != 1:
        # The page lost its config slot — fail loudly rather than serve a map
        # that silently ignores the flags it was started with.
        raise MhError("ui/index.html no longer carries the config marker")
    cfg = {
        "budget": budget,
        "readOnly": read_only,
        "hub": str(hub),
        "version": __version__,
    }
    # Escape '<' so no value can ever close the script element early.
    payload = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c").encode()
    filled = CONFIG_MARKER.replace(b"{}", payload)
    return html.replace(CONFIG_MARKER, filled, 1)


def make_handler(hub: Path, token: str, read_only: bool, budget: int | None = load.DEFAULT_BUDGET):
    class Handler(BaseHTTPRequestHandler):
        server_version = "mh"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # quiet; mh prints its own line
            pass

        def _send(self, status: int, payload: bytes, ctype: str, cache: str = "no-store") -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache)
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
                self._send(200, _page(budget, read_only, hub), "text/html; charset=utf-8")
                return
            if method == "GET" and parts.path in ("/api/image", "/api/live/image"):
                try:
                    if parts.path == "/api/image":
                        data, ctype = image_file(query.get("path", ""))
                    else:
                        data, ctype = live_image(hub, query)
                except MhError as e:
                    self._json(404, {"error": e.message})
                    return
                self._send(200, data, ctype, cache="private, max-age=3600")
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
                status, obj = dispatch(hub, method, parts.path, query, body, read_only)
            except MhError as e:
                status, obj = 400, {"error": e.message}
            except git.GitError as e:
                # Surface git's own words, or an unset user.email leaves the
                # user stuck on a bare "git failed".
                status, obj = (
                    409,
                    {
                        "error": git.explain(e),
                        "detail": "\n".join(git.stderr_lines(e)[:8]),
                    },
                )
            except (ValueError, KeyError) as e:
                status, obj = 400, {"error": str(e)}
            self._json(status, obj)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


# --- the detached server -----------------------------------------------------
# `mh ui --detach` is what an agent runs: a bare `mh ui` blocks the shell it was
# started from until something kills it. The server forks into the background,
# the CLI prints the URL and returns, and <hub>/ui.json remembers the pid so a
# second `mh ui` finds the running one and `mh ui --stop` can end it.


def record_path(hub: Path) -> Path:
    return hub / UI_RECORD


def _is_mh(pid: int) -> bool:
    """Alive, and one of ours. /proc settles it; without /proc (macOS) a live
    pid is trusted — the record was written by mh for its own child."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return True
    return b"memoryhub" in cmd or b"/mh\0" in cmd or cmd.startswith(b"mh\0")


def running(hub: Path) -> dict | None:
    """The detached server recorded for this hub, if it is still alive. A
    stale record — the process is gone, or the pid belongs to something else
    now — is removed rather than believed."""
    path = record_path(hub)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = None
    pid = data.get("pid") if isinstance(data, dict) else None
    if isinstance(pid, int) and isinstance(data.get("url"), str) and _is_mh(pid):
        return data
    path.unlink(missing_ok=True)
    return None


def stop(hub: Path) -> dict | None:
    """End the detached server; its record, or None when none was running."""
    rec = running(hub)
    if rec is None:
        return None
    os.kill(rec["pid"], signal.SIGTERM)
    for _ in range(100):
        if not _is_mh(rec["pid"]):
            break
        time.sleep(0.05)
    record_path(hub).unlink(missing_ok=True)
    return rec


def page_url(base: str, sid: str | None) -> str:
    """The page URL, following one session's live panel when `sid` is given."""
    return base + (f"&sid={quote(sid, safe='')}" if sid else "")


def _spawn(
    hub: Path,
    httpd: ThreadingHTTPServer,
    token: str,
    host: str,
    read_only: bool,
    budget: int | None,
) -> int:
    """Start a fresh process that adopts the already-bound socket and serves
    until stopped. Spawn, never fork-without-exec — macOS wedges forked
    children that touch its frameworks, and an exec'd child starts clean.
    The token rides in the environment, not argv: ps shows argv to everyone."""
    if os.name != "posix":
        raise MhError("--detach needs a POSIX system; run `mh ui` in a terminal of its own")
    git.exclude(hub, "/" + UI_RECORD)
    git.exclude(hub, "/" + UI_LOG)
    fd = httpd.fileno()
    os.set_inheritable(fd, True)
    argv = [
        sys.executable,
        "-m",
        "memoryhub",
        "ui",
        "--adopt-socket",
        str(fd),
        "--host",
        host,
        "--budget",
        str(budget) if budget is not None else "none",
    ]
    if read_only:
        argv.append("--read-only")
    log = os.open(str(hub / UI_LOG), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,  # outlives the terminal and the agent
            close_fds=True,
            pass_fds=(fd,),
            env={**os.environ, "MH_UI_TOKEN": token},
        )
    finally:
        os.close(log)
    return proc.pid


def adopt(hub: Path, fd: int, read_only: bool, budget: int | None) -> None:
    """The spawned half of --detach: serve on the socket the parent bound,
    with the token it minted, until SIGTERM (`mh ui --stop`)."""
    token = os.environ.pop("MH_UI_TOKEN", "")
    httpd = MapServer(
        ("127.0.0.1", 0), make_handler(hub, token, read_only, budget), bind_and_activate=False
    )
    httpd.socket.close()  # the placeholder — the real one is inherited
    httpd.socket = socket.socket(fileno=fd)
    httpd.server_address = httpd.socket.getsockname()
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    print(
        f"mh ui: serving on port {httpd.server_address[1]} "
        f"(pid {os.getpid()}, started {datetime.now():%H:%M:%S})",
        flush=True,
    )
    httpd.serve_forever()


def listen(host: str, port: int | None, handler) -> tuple[ThreadingHTTPServer, int | None]:
    """Bind the server. No port asked for: the usual one when it is free, else
    any free port — another hub's map may hold 7777, and an agent starting
    this one must get a URL, not a diagnosis to chase. An explicit port is
    strict. Returns the server and the port it had to give up on, if any."""
    want = DEFAULT_PORT if port is None else port
    try:
        return MapServer((host, want), handler), None
    except OSError as e:
        if port is not None or e.errno != errno.EADDRINUSE:
            raise MhError(f"cannot listen on {host}:{want} — {e.strerror or e}") from None
    return MapServer((host, 0), handler), want


def serve(
    hub: Path,
    host: str = "127.0.0.1",
    port: int | None = None,
    open_browser: bool = True,
    read_only: bool = False,
    budget: int | None = load.DEFAULT_BUDGET,
    detach: bool = False,
    sid: str | None = None,
) -> None:
    token = secrets.token_urlsafe(16)
    httpd, taken = listen(host, port, make_handler(hub, token, read_only, budget))
    base = f"http://{host}:{httpd.server_address[1]}/?t={token}"
    url = page_url(base, sid)
    if taken:
        print(f"port {taken} is taken (another map?) — using {httpd.server_address[1]}", flush=True)
    if detach:
        pid = _spawn(hub, httpd, token, host, read_only, budget)
        httpd.socket.close()  # the parent's copy; the spawned server keeps its own
        record_path(hub).write_text(
            json.dumps(
                {
                    "pid": pid,
                    "url": base,
                    "port": httpd.server_address[1],
                    "started": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"mh ui: {url}", flush=True)
        print(f"running in the background (pid {pid}) — mh ui --stop ends it", flush=True)
        if open_browser:
            webbrowser.open(url)
        return
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
