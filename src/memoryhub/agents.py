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


def _jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


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
            f"unknown agent(s): {', '.join(unknown)} "
            f"(known: {', '.join(sorted(AGENTS))})"
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


# --- extraction --------------------------------------------------------------


def extract(d: Discovered) -> tuple[list[tuple[str, str]], str | None]:
    """(turns, last_timestamp) for any supported agent. The trailing unanswered
    turn is KEPT — archival imports preserve the full record (unlike live
    `mh save`, which drops the request that triggered it)."""
    if d.agent == "claude":
        return purify.build_turns(d.path)
    if d.agent == "pi":
        return _build_turns_pi(d.path)
    if d.agent == "codex":
        return _build_turns_codex(d.path)
    raise MhError(f"no extractor for agent '{d.agent}'")


def _build_turns_pi(path: Path) -> tuple[list[tuple[str, str]], str | None]:
    """pi schema: type:"message" records with message.{role,content}; content is
    a string or blocks of which only type:"text" survive. Mirrors the
    memory-map skill's adapter, plus timestamp capture."""
    turns: list[tuple[str, str]] = []
    q_parts: list[str] = []
    a_parts: list[str] = []
    last_ts: str | None = None

    def flush() -> None:
        if q_parts:
            turns.append(("\n\n".join(q_parts), "\n\n".join(a_parts)))
        q_parts.clear()
        a_parts.clear()

    for rec in _jsonl(path):
        ts = rec.get("timestamp")
        if ts:
            last_ts = ts
        if rec.get("type") != "message":
            continue
        msg = rec.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
        else:
            texts = []
        text = "\n".join(t for t in texts if t).strip()
        if not text:
            continue
        if role == "user":
            text = SKILL_RE.sub("", text)
            head = text.lstrip()
            if not head:
                continue
            if head.startswith(purify.WRAPPER_PREFIXES):
                continue
            if any(m in head[:64] for m in purify.INTERRUPT_MARKERS):
                continue
            text = purify._strip(text)
            if not text:
                continue
            if a_parts:
                flush()
            q_parts.append(text)
        elif role == "assistant" and q_parts:
            a_parts.append(text)
    flush()
    return turns, last_ts


def _build_turns_codex(path: Path) -> tuple[list[tuple[str, str]], str | None]:
    """Codex rollouts: type:"response_item" with payload.type:"message"; user
    text in input_text blocks (harness wrappers dropped), assistant text in
    output_text blocks."""
    turns: list[tuple[str, str]] = []
    q_parts: list[str] = []
    a_parts: list[str] = []
    last_ts: str | None = None

    def flush() -> None:
        if q_parts:
            turns.append(("\n\n".join(q_parts), "\n\n".join(a_parts)))
        q_parts.clear()
        a_parts.clear()

    for rec in _jsonl(path):
        ts = rec.get("timestamp")
        if ts:
            last_ts = ts
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
            texts = [
                t
                for t in texts
                if t and not t.lstrip().startswith(CODEX_WRAPPER_PREFIXES)
            ]
            text = purify._strip(SKILL_RE.sub("", "\n".join(texts)).strip())
            if not text:
                continue
            if a_parts:
                flush()
            q_parts.append(text)
        elif role == "assistant":
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "output_text"
            ]
            text = "\n".join(t for t in texts if t).strip()
            if text and q_parts:
                a_parts.append(text)
    flush()
    return turns, last_ts
