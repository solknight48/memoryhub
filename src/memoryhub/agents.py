"""Multi-agent session discovery and extraction for `mh import`.

Adapters ship only for agents whose on-disk formats were verified against real
data on this machine: Claude Code (~/.claude/projects), pi (~/.pi/agent/sessions),
Codex (~/.codex/sessions). Adding an agent = one discover function + one
extract branch, registered in AGENTS.

Path encodings differ per agent (verified):
- Claude Code replaces every non-alphanumeric with '-' (purify.encode_project_dir).
- pi replaces '/' with '-' (dots/underscores kept) and wraps as '-<esc>--'.
- Codex has no per-project dirs; each rollout's session_meta carries the cwd.

Sessions launched from a subdirectory land in prefix-variant dirs (<esc>-sub);
those can collide with sibling projects, so prefix-variant files are trusted
only when their own records' cwd lies under the project root.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import purify
from .hub import MhError

CODEX_WRAPPER_PREFIXES = (
    "<environment_context>",
    "<user_instructions>",
    "<turn_context>",
)

# pi and codex prepend an invoked skill's full body to the user turn, as
# `<skill name=".." location="..">..</skill>` (pi) or `<skill><name>..</name>
# ..</skill>` (codex), followed by the real message. Strip the block, keep the
# message. (Claude Code surfaces skills as <command-name>/<system-reminder>
# instead, handled in purify.py — so this lives in the agent layer only.)
SKILL_RE = re.compile(r"<skill\b[^>]*>.*?</skill>", re.DOTALL)


@dataclass
class Discovered:
    agent: str
    path: Path
    sid: str
    key: str  # session-file identity key: claude "7aee4e68", pi "pi-…", codex "cx-…"


_jsonl = purify.iter_records


def _cwd_matches(cwd: object, root: Path) -> bool:
    if not isinstance(cwd, str) or not cwd:
        return False
    return cwd == str(root) or cwd.startswith(str(root) + "/")


def _first_cwd(path: Path, limit: int = 50) -> str | None:
    """First 'cwd' value among the file's leading records (claude records and
    pi's session header both carry one)."""
    try:
        for i, rec in enumerate(_jsonl(path)):
            if i >= limit:
                break
            cwd = rec.get("cwd")
            if isinstance(cwd, str):
                return cwd
    except OSError:
        return None
    return None


# --- discovery ---------------------------------------------------------------


def discover_claude(root: Path, scope: Path | None = None) -> list[Discovered]:
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return []
    scope = scope or root
    esc = purify.encode_project_dir(root)
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        exact = d.name == esc
        if not exact and not d.name.startswith(esc + "-"):
            continue
        # The exact dir holds sessions launched at the project root; when the
        # scope is a subfolder, those lie outside it by definition.
        if exact and scope != root:
            continue
        for f in sorted(d.glob("*.jsonl")):
            if not exact and not _cwd_matches(_first_cwd(f), scope):
                continue
            sid = f.stem
            out.append(Discovered("claude", f, sid, sid.split("-")[0][:8] or "session"))
    return out


def discover_pi(root: Path, scope: Path | None = None) -> list[Discovered]:
    base = Path.home() / ".pi" / "agent" / "sessions"
    if not base.is_dir():
        return []
    scope = scope or root
    esc = "-" + str(root).rstrip("/").replace("/", "-")
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or not d.name.endswith("--"):
            continue
        core = d.name[:-2]
        exact = core == esc
        if not exact and not core.startswith(esc + "-"):
            continue
        if exact and scope != root:
            continue
        for f in sorted(d.glob("*.jsonl")):
            if not exact and not _cwd_matches(_first_cwd(f), scope):
                continue
            stem = f.stem
            sid = stem.split("_", 1)[1] if "_" in stem else stem
            # pi/codex ids are UUIDv7 (timestamp-prefixed): 8 chars collide for
            # sessions minutes apart, so take 12 dashless hex chars.
            out.append(Discovered("pi", f, sid, "pi-" + sid.replace("-", "")[:12]))
    return out


def discover_codex(root: Path, scope: Path | None = None) -> list[Discovered]:
    base = Path.home() / ".codex" / "sessions"
    if not base.is_dir():
        return []
    scope = scope or root
    out = []
    for f in sorted(base.rglob("*.jsonl")):
        meta = _codex_meta(f)
        if not meta:
            continue
        payload = meta.get("payload") or {}
        if not _cwd_matches(payload.get("cwd"), scope):
            continue
        source = payload.get("source")
        if isinstance(source, dict) and "subagent" in source:
            continue  # judge/guardian sidechains, not user dialog
        sid = str(payload.get("id") or f.stem)
        out.append(Discovered("codex", f, sid, "cx-" + sid.replace("-", "")[:12]))
    return out


def _codex_meta(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            line = fh.readline().strip()
    except OSError:
        return None
    if not line:
        return None
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    return rec if rec.get("type") == "session_meta" else None


AGENTS = {
    "claude": discover_claude,
    "pi": discover_pi,
    "codex": discover_codex,
}


def discover(
    root: Path, agents: set[str] | None = None, scope: Path | None = None
) -> list[Discovered]:
    """All sessions launched inside `scope` (a directory within `root`;
    default: the whole project)."""
    names = sorted(agents) if agents else sorted(AGENTS)
    unknown = [n for n in names if n not in AGENTS]
    if unknown:
        raise MhError(
            f"unknown agent(s): {', '.join(unknown)} (known: {', '.join(sorted(AGENTS))})"
        )
    found: list[Discovered] = []
    for name in names:
        found.extend(AGENTS[name](root, scope))
    return found


def detect_agent(path: Path) -> str:
    """Sniff which agent wrote a transcript from its record types."""
    for i, rec in enumerate(_jsonl(path)):
        if i >= 50:
            break
        kind = rec.get("type")
        if kind in ("user", "assistant"):
            return "claude"
        if kind in ("message", "session"):
            return "pi"
        if kind in ("session_meta", "response_item"):
            return "codex"
    return "claude"


def identify(agent: str, path: Path) -> tuple[str, str]:
    """(session id, filename identity key) for a transcript of a known agent."""
    if agent == "claude":
        sid = path.stem
        return sid, sid.split("-")[0][:8] or "session"
    if agent == "pi":
        stem = path.stem
        sid = stem.split("_", 1)[1] if "_" in stem else stem
        return sid, "pi-" + sid.replace("-", "")[:12]
    if agent == "codex":
        meta = _codex_meta(path)
        sid = str(((meta or {}).get("payload") or {}).get("id") or path.stem)
        return sid, "cx-" + sid.replace("-", "")[:12]
    raise MhError(f"unknown agent '{agent}'")


# --- the unfiltered stream ---------------------------------------------------
# extract() gives the purified dialog — what mh stores. This gives what the
# agent actually emitted while producing it: thinking, visible text and tool
# calls, in order, grouped by exchange. The live panel shows this; nothing is
# saved from it. Grouping reuses the turn builders' own text functions, so the
# two walks cannot disagree about where an exchange ends.

# Per-part caps. The visible reply is the dialog and is never cut — the page
# shows exactly what a save would store. Thinking gets room to be read; a tool
# call carrying a whole file (a Write) is not the point of the panel.
STREAM_CLIP = {"text": None, "thinking": 12000, "tool": 4000}
TOOL_PREVIEW_KEYS = (
    "command",
    "file_path",
    "path",
    "pattern",
    "query",
    "url",
    "prompt",
    "description",
)


def _clip(text: str, limit: int | None) -> tuple[str, bool]:
    text = text.strip()
    if limit is None or len(text) <= limit:
        return text, False
    return text[:limit], True


def _dump(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=1, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


PREVIEW_CHARS = 160


def _cut(text: str) -> str:
    """Shorten to one readable line. On a word boundary with an ellipsis: a
    command sliced mid-token ("… cut -d= -f2) cu") reads as a rendering fault
    rather than as the deliberate elision it is. The whole call is one click
    away either way."""
    line = " ".join(text.split())
    if len(line) <= PREVIEW_CHARS:
        return line
    head = line[:PREVIEW_CHARS]
    space = head.rfind(" ")
    if space >= PREVIEW_CHARS * 0.6:
        head = head[:space]
    return head.rstrip(" ,;:|&") + " …"


def _preview(args: object) -> str:
    """The one line that says what a tool call does: its most telling argument,
    or the whole call flattened when none of it is a plain string."""
    if isinstance(args, dict):
        named = [args.get(k) for k in TOOL_PREVIEW_KEYS]
        for v in [*named, *args.values()]:
            if isinstance(v, str) and v.strip():
                return _cut(v)
    return _cut(_dump(args)) if args else ""


def _part(kind: str, text: object, name: str = "", sidechain: bool = False) -> dict:
    body, clipped = _clip(_dump(text), STREAM_CLIP.get(kind))
    part = {"kind": kind, "text": body, "clipped": clipped}
    if name:
        part["name"] = name
    if sidechain:
        part["sidechain"] = True
    if kind == "tool":
        part["preview"] = _preview(text)
    return part


def _batched(parts: list[dict], counter) -> list[dict]:
    """Mark the tool calls that were emitted together — those run concurrently.

    One reply asking for three tools is three parallel calls, and showing them
    as three lone calls in a row tells the reader the wrong story about how the
    work happened. Claude Code writes one record per content block, so the
    message id is what says two calls came from the same reply; pi keeps them
    in one record. Either way the emission key groups them, and a group of one
    is not a batch.
    """
    groups: dict[str, list[dict]] = {}
    for p in parts:
        if p["kind"] == "tool":
            groups.setdefault(p.pop("emit", ""), []).append(p)
        else:
            p.pop("emit", None)
    for group in groups.values():
        if len(group) > 1:
            batch = next(counter)
            for p in group:
                p["batch"] = batch
                p["batch_size"] = len(group)
    return parts


def _stream(path: Path, user_text, answer_text, parts_of, emission=None) -> list[list[dict]]:
    """Emitted parts per exchange, aligned one-to-one with extract()'s turns.

    The one rule the builders follow: a new question closes the previous
    exchange only once that exchange has an answer, so consecutive unanswered
    questions stay one exchange. Same rule here, over the same text functions.
    """
    out: list[list[dict]] = []
    current: list[dict] = []
    asked = answered = False
    batches = itertools.count(1)
    for i, rec in enumerate(_jsonl(path)):
        if user_text(rec):
            if answered:
                out.append(_batched(current, batches))
                current, answered = [], False
            asked = True
            continue
        if not asked:
            continue  # anything before the first question belongs to no exchange
        emitted = (emission(rec) if emission else "") or f"#{i}"
        for part in parts_of(rec):
            part["emit"] = emitted
            current.append(part)
        if answer_text(rec):
            answered = True
    if asked:
        out.append(_batched(current, batches))
    return out


def _parts_claude(rec: dict) -> list[dict]:
    if rec.get("type") != "assistant":
        return []
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    side = bool(rec.get("isSidechain"))  # a subagent's output is still output
    out = []
    for b in content:
        if not isinstance(b, dict):
            continue
        kind = b.get("type")
        if kind == "thinking":
            out.append(_part("thinking", b.get("thinking", ""), sidechain=side))
        elif kind == "text":
            out.append(_part("text", b.get("text", ""), sidechain=side))
        elif kind == "tool_use":
            out.append(_part("tool", b.get("input"), b.get("name", "tool"), side))
    return [p for p in out if p["text"] or p["kind"] == "tool"]


def _parts_pi(rec: dict) -> list[dict]:
    msg = rec.get("message") or {}
    if rec.get("type") != "message" or msg.get("role") != "assistant":
        return []
    content = msg.get("content")
    if not isinstance(content, list):
        return [_part("text", _pi_text(msg))] if _pi_text(msg) else []
    out = []
    for b in content:
        if not isinstance(b, dict):
            continue
        kind = b.get("type")
        if kind == "thinking":
            out.append(_part("thinking", b.get("thinking", "")))
        elif kind == "text":
            out.append(_part("text", b.get("text", "")))
        elif kind == "toolCall":
            out.append(_part("tool", b.get("arguments"), b.get("name", "tool")))
    return [p for p in out if p["text"] or p["kind"] == "tool"]


def stream(d: Discovered) -> list[list[dict]] | None:
    """Everything the agent emitted, per exchange — or None for a format whose
    blocks mh has not verified against real data (codex, as for models)."""
    if d.agent == "claude":
        return _stream(
            d.path,
            lambda r: purify.user_text(r) if r.get("type") == "user" else "",
            lambda r: purify.assistant_text(r) if r.get("type") == "assistant" else "",
            _parts_claude,
            # each block is its own record; the message id is the reply it came
            # from, and requestId says the same thing for anything older
            lambda r: (r.get("message") or {}).get("id") or r.get("requestId") or "",
        )
    if d.agent == "pi":

        def _user(rec):
            msg = rec.get("message") or {}
            if rec.get("type") != "message" or msg.get("role") != "user":
                return ""
            return _pi_user_text(msg)

        def _answer(rec):
            msg = rec.get("message") or {}
            if rec.get("type") != "message" or msg.get("role") != "assistant":
                return ""
            return _pi_text(msg)

        return _stream(d.path, _user, _answer, _parts_pi)
    return None


# --- extraction --------------------------------------------------------------


def extract(d: Discovered) -> tuple[list[tuple[str, str]], str | None, list[str]]:
    """(turns, last_timestamp, models) for any supported agent. The trailing
    unanswered turn is KEPT — archival imports preserve the full record (unlike
    live `mh save`, which drops the request that triggered it)."""
    if d.agent == "claude":
        return purify.build_turns(d.path)
    if d.agent == "pi":
        return _build_turns_pi(d.path)
    if d.agent == "codex":
        return _build_turns_codex(d.path)
    raise MhError(f"no extractor for agent '{d.agent}'")


def _pi_text(msg: dict) -> str:
    """The visible text of a pi message: a bare string, or its text blocks."""
    content = msg.get("content")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ]
    else:
        texts = []
    return "\n".join(t for t in texts if t).strip()


def _pi_user_text(msg: dict) -> str:
    """Genuine user dialog in a pi message, or '' — skill bodies, harness
    wrappers and interrupted turns are not dialog."""
    text = SKILL_RE.sub("", _pi_text(msg))
    head = text.lstrip()
    if not head or head.startswith(purify.WRAPPER_PREFIXES):
        return ""
    if any(m in head[:64] for m in purify.INTERRUPT_MARKERS):
        return ""
    return purify._strip(text)


def _build_turns_pi(path: Path) -> tuple[list[tuple[str, str]], str | None, list[str]]:
    """pi schema: type:"message" records with message.{role,content}; content is
    a string or blocks of which only type:"text" survive. Mirrors the
    memory-map skill's adapter, plus timestamp and model capture. pi names the
    model at message.model, the same place Claude Code does."""
    builder = purify.TurnBuilder()
    for rec in _jsonl(path):
        builder.stamp(rec.get("timestamp"))
        if rec.get("type") != "message":
            continue
        msg = rec.get("message") or {}
        role = msg.get("role")
        if role == "user":
            text = _pi_user_text(msg)
            if text:
                builder.ask(text)
        elif role == "assistant":
            builder.answer(_pi_text(msg), msg)
    return builder.result()


def _build_turns_codex(
    path: Path,
) -> tuple[list[tuple[str, str]], str | None, list[str]]:
    """Codex rollouts: type:"response_item" with payload.type:"message"; user
    text in input_text blocks (harness wrappers dropped), assistant text in
    output_text blocks.

    Codex names the model per response_item where it says so, otherwise the
    session_meta model stands in for the whole session. Unlike claude and pi
    this is unverified against a real rollout — no codex transcript exists on
    the machine mh was built on — so it degrades to no label rather than
    guessing a field name.
    """
    session_model = purify.model_of((_codex_meta(path) or {}).get("payload"))
    builder = purify.TurnBuilder(default_model=session_model)
    for rec in _jsonl(path):
        builder.stamp(rec.get("timestamp"))
        if rec.get("type") != "response_item":
            continue
        payload = rec.get("payload") or {}
        if payload.get("type") != "message":
            continue
        role = payload.get("role")
        content = payload.get("content")
        if not isinstance(content, list):
            continue
        if role == "user":
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "input_text"
            ]
            texts = [t for t in texts if t and not t.lstrip().startswith(CODEX_WRAPPER_PREFIXES)]
            text = purify._strip(SKILL_RE.sub("", "\n".join(texts)).strip())
            if text:
                builder.ask(text)
        elif role == "assistant":
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "output_text"
            ]
            builder.answer("\n".join(t for t in texts if t).strip(), payload)
    return builder.result()
