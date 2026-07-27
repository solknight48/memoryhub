"""Purify Claude Code session transcripts into User/Agent dialog markdown.

Vendored and adapted from ~/.claude/skills/purify-context/purify.py so the
installed tool is self-contained. Extraction semantics are identical (a parity
test pins this); mh-specific differences: turns are returned in-memory instead
of written to a file, project-wide transcript discovery lives in agents.py
(all agents, never another project's sessions), and render() labels turns
User/Agent where the original emits Q/A.
"""

from __future__ import annotations

import glob as globmod
import json
import os
import re
from datetime import datetime
from pathlib import Path

from .hub import MhError

SESSION_GLOB = "~/.claude/projects/*/{sid}.jsonl"

# User strings that are harness artifacts, not real dialog. Matched at the very
# start of the (l-stripped) message, so genuine questions that merely mention a
# tag are never dropped.
WRAPPER_PREFIXES = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<local-command-caveat>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<user-prompt-submit-hook>",
)
INTERRUPT_MARKERS = ("[Request interrupted by user", "[Request cancelled")
SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)


def encode_project_dir(root: Path) -> str:
    # Claude Code stores transcripts under ~/.claude/projects/<encoded-cwd>/,
    # with path punctuation replaced by '-'. Only the no-session-id fallback
    # depends on this encoding; session-id lookups glob across all projects.
    return re.sub(r"[^A-Za-z0-9]", "-", str(root))


def find_transcript(
    session_id: str | None = None,
    transcript: str | Path | None = None,
) -> Path:
    """Resolve an explicit transcript path or a Claude session id. (Agentless
    project-wide fallback lives in agents.discover — all agents, not just
    Claude.)"""
    if transcript:
        path = Path(transcript).expanduser()
        if not path.is_file():
            raise MhError(f"transcript not found: {path}")
        return path
    if session_id:
        matches = globmod.glob(os.path.expanduser(SESSION_GLOB.format(sid=session_id)))
        if not matches:
            raise MhError(f"no transcript for session id {session_id}")
        return Path(max(matches, key=os.path.getmtime))
    raise MhError("find_transcript requires a session id or a path")


def _strip(text: str) -> str:
    return SYSTEM_REMINDER_RE.sub("", text).strip()


def user_text(rec: dict) -> str:
    """Genuine user dialog for this record, or '' if it is not real dialog."""
    if rec.get("isMeta") or rec.get("isSidechain"):
        return ""
    content = (rec.get("message") or {}).get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    text = "\n".join(p for p in parts if p)
    head = text.lstrip()
    if not head:
        return ""
    if head.startswith(WRAPPER_PREFIXES):
        return ""
    if any(m in head[:64] for m in INTERRUPT_MARKERS):
        return ""
    return _strip(text)


def assistant_text(rec: dict) -> str:
    """The assistant's visible reply text for this record (no thinking/tools)."""
    if rec.get("isSidechain"):
        return ""
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return ""
    parts = [
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    return "\n".join(p for p in parts if p).strip()


def build_turns(path: Path) -> tuple[list[tuple[str, str]], str | None]:
    """Walk the transcript in order, pairing each user turn with the assistant
    text that follows it. Consecutive unanswered user messages merge into one Q.
    Also returns the last record timestamp seen (the session's end time)."""
    turns: list[tuple[str, str]] = []
    q_parts: list[str] = []
    a_parts: list[str] = []
    last_ts: str | None = None

    def flush() -> None:
        if q_parts:
            turns.append(("\n\n".join(q_parts), "\n\n".join(a_parts)))
        q_parts.clear()
        a_parts.clear()

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("timestamp")
            if ts:
                last_ts = ts
            kind = rec.get("type")
            if kind == "user":
                txt = user_text(rec)
                if not txt:
                    continue
                if a_parts:  # prior turn already answered -> close it
                    flush()
                q_parts.append(txt)
            elif kind == "assistant":
                txt = assistant_text(rec)
                if txt and q_parts:  # ignore assistant text before any question
                    a_parts.append(txt)
    flush()
    return turns, last_ts


def drop_trailing_unanswered(turns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if turns and not turns[-1][1].strip():
        return turns[:-1]
    return turns


def render(turns: list[tuple[str, str]], source: str, session_id: str | None) -> str:
    n = len(turns)
    src = os.path.basename(source)
    prov = f"`{src}`" + (f" (session `{session_id}`)" if session_id else "")
    lines = [
        "# Session Context",
        "",
        f"_Pure dialog extracted from {prov}. "
        f"{n} exchange{'' if n == 1 else 's'}. Tool calls, results, and internal "
        "reasoning removed._",
        "",
    ]
    blocks = []
    for i, (user, agent) in enumerate(turns, 1):
        reply = agent if agent else "_(no textual reply captured)_"
        blocks.append(f"## User {i}\n\n{user}\n")
        blocks.append(f"## Agent {i}\n\n{reply}\n")
        blocks.append("---\n")
    if blocks:
        blocks.pop()  # no trailing separator
    return "\n".join(lines + blocks).rstrip() + "\n"


def stamp_for(last_ts: str | None, source: Path) -> str:
    """Filename timestamp for a session: its end time in local time, so merged
    loading across checkpoints follows true chronology even for late imports."""
    if last_ts:
        try:
            dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d_%H%M")
        except ValueError:
            pass
    return (
        datetime.fromtimestamp(source.stat().st_mtime)
        .astimezone()
        .strftime("%Y-%m-%d_%H%M")
    )
