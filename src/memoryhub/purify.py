"""Purify Claude Code session transcripts into User/Agent dialog markdown.

Vendored and adapted from ~/.claude/skills/purify-context/purify.py so the
installed tool is self-contained. Extraction semantics are identical (a parity
test pins this); mh-specific differences: turns are returned in-memory instead
of written to a file, project-wide transcript discovery lives in agents.py
(all agents, never another project's sessions), render() labels turns
User/Agent where the original emits Q/A, and each answer carries the model
that produced it. Models ride alongside the turns rather than inside them, so
a transcript that names no model renders exactly what the original does — the
parity test pins that, and so covers the real save path.
"""

from __future__ import annotations

import base64
import binascii
import glob as globmod
import json
import os
import re
from datetime import datetime
from pathlib import Path

from .hub import MhError

SESSION_GLOB = "~/.claude/projects/*/{sid}.jsonl"

# A slash command as Claude Code records it — `/mh load` is written as
# <command-message>mh</command-message> <command-name>/mh</command-name>
# <command-args>load</command-args>. The user's own words are in there, so a
# command is dialog whenever the agent answered it (a skill invocation); one
# nobody answered was a local command (/clear, /model) and the turn builder
# drops it. Matched at the very start of the (l-stripped) message.
COMMAND_PREFIXES = ("<command-name>", "<command-message>", "<command-args>")
COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.DOTALL)
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)

# User strings that are harness artifacts, not real dialog. Matched at the very
# start of the message once <system-reminder> blocks are gone, so genuine
# questions that merely mention a tag are never dropped. (A command wrapper
# that names no command is one; so is a background task's completion notice,
# which Claude Code delivers as a user record.)
WRAPPER_PREFIXES = (
    *COMMAND_PREFIXES,
    "<task-notification>",
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

# What a model id may look like. Deliberately narrow: it has to survive a
# round-trip through a `## Agent N — `id`` heading, and it screens out Claude
# Code's "<synthetic>" placeholder for replies it generated itself.
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+-]*$")


def model_of(message: object) -> str:
    """The model id on an assistant record, or "" when there isn't a real one.
    Claude Code and pi both put it at message.model."""
    model = (message or {}).get("model") if isinstance(message, dict) else None
    return model if isinstance(model, str) and MODEL_RE.match(model) else ""


def note_model(seen: list[str], message: object) -> None:
    """Credit a record's model to the turn being built, first use first. Only
    called for records that contributed visible text, so the label never claims
    a model whose output was filtered out of the dialog."""
    model = model_of(message)
    if model and model not in seen:
        seen.append(model)


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


def command_text(text: str) -> str:
    """The slash command a wrapper records, as the user typed it (`/mh load`),
    or '' when the text is not a command wrapper."""
    if not text.lstrip().startswith(COMMAND_PREFIXES):
        return ""
    name = COMMAND_NAME_RE.search(text)
    if not name or not name.group(1).strip():
        return ""
    args = COMMAND_ARGS_RE.search(text)
    words = [name.group(1).strip(), args.group(1).strip() if args else ""]
    return " ".join(w for w in words if w)


def user_turn(rec: dict) -> tuple[str, bool]:
    """(dialog, is_command) for a user record: the genuine user text — '' when
    the record is not real dialog — and whether it was a slash command, which
    the turn builder keeps only if the agent answered it."""
    if rec.get("isMeta") or rec.get("isSidechain"):
        return "", False
    content = (rec.get("message") or {}).get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    text = _strip("\n".join(p for p in parts if p))
    if not text:
        return "", False
    command = command_text(text)
    if command:
        return command, True
    if text.startswith(WRAPPER_PREFIXES):
        return "", False
    if any(m in text[:64] for m in INTERRUPT_MARKERS):
        return "", False
    return text, False


def user_text(rec: dict) -> str:
    """Genuine user dialog for this record, or '' if it is not real dialog."""
    return user_turn(rec)[0]


IMAGE_MEDIA = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def user_images(rec: dict, keep_data: bool = False) -> list[dict]:
    """The pictures pasted into a user record, as Claude Code stores them: a
    base64 `image` block each. Descriptors only unless `keep_data` — a
    screenshot is half a megabyte of base64, and the live panel wants to know
    there is one long before anyone looks at it."""
    if rec.get("isMeta") or rec.get("isSidechain"):
        return []
    content = (rec.get("message") or {}).get("content")
    out: list[dict] = []
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        src = block.get("source") or {}
        data, media = src.get("data"), src.get("media_type")
        if src.get("type") != "base64" or not isinstance(data, str) or media not in IMAGE_MEDIA:
            continue
        padding = len(data) - len(data.rstrip("="))
        item = {"media_type": media, "size": len(data) * 3 // 4 - padding}
        if keep_data:
            item["data"] = data
        out.append(item)
    return out


def assistant_text(rec: dict) -> str:
    """The assistant's visible reply text for this record (no thinking/tools)."""
    if rec.get("isSidechain"):
        return ""
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return ""
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(p for p in parts if p).strip()


class TurnBuilder:
    """Pairs each user turn with the assistant text that follows it — the one
    rule every agent adapter shares, kept in one place so they cannot drift.

    A new question closes the previous exchange only once that exchange has an
    answer, so consecutive unanswered questions merge into one — except a slash
    command, which is only dialog once it has been answered: one nobody
    answered was a local command (/clear, /model), not part of the next
    question either. Only a trailing one waits, since it may be a skill
    invocation whose answer is still on its way. Assistant text before any
    question belongs to no exchange. Each exchange is credited with the models
    that actually contributed text to its answer, first use first, so a
    mid-session model switch is visible per exchange.
    """

    def __init__(self, default_model: str = "") -> None:
        self.turns: list[tuple[str, str]] = []
        self.models: list[str] = []
        self.last_ts: str | None = None  # the session's end time
        self._default_model = default_model
        self._q: list[tuple[str, bool]] = []  # (text, is a slash command)
        self._a: list[str] = []
        self._m: list[str] = []
        # What rode along with each exchange's question — pasted pictures —
        # parallel to `turns`, like `models`. Display only; never stored.
        self.attachments: list[list[dict]] = []
        self._att: list[dict] = []

    def stamp(self, ts: object) -> None:
        if ts:
            self.last_ts = str(ts)

    def ask(self, text: str, command: bool = False) -> None:
        if self._a:  # prior turn already answered -> close it
            self._flush()
        else:
            self._q = [p for p in self._q if not p[1]]
        self._q.append((text, command))

    def answer(self, text: str, message: object = None) -> None:
        if text and self._q:
            self._a.append(text)
            note_model(self._m, message)

    def attach(self, item: dict) -> None:
        """Something that came with the pending question; with no question
        pending there is nothing to attach it to."""
        if self._q:
            self._att.append(item)

    def _flush(self) -> None:
        if self._q:
            self.turns.append(("\n\n".join(q for q, _ in self._q), "\n\n".join(self._a)))
            self.models.append(", ".join(self._m) or self._default_model)
            self.attachments.append(self._att)
        self._q, self._a, self._m, self._att = [], [], [], []

    def result(self) -> tuple[list[tuple[str, str]], str | None, list[str]]:
        """(turns, last timestamp, one model field per turn)."""
        self._flush()
        return self.turns, self.last_ts, self.models


def iter_records(path: Path):
    """The JSON records of a .jsonl transcript, skipping blank and broken lines."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def walk_claude(path: Path, keep_images: bool = False) -> TurnBuilder:
    """Feed a Claude Code transcript through the TurnBuilder; the finished
    builder carries turns, models, the end timestamp and, per exchange, the
    pictures pasted with its question (descriptors, or the data too)."""
    builder = TurnBuilder()
    for rec in iter_records(path):
        builder.stamp(rec.get("timestamp"))
        kind = rec.get("type")
        if kind == "user":
            text, command = user_turn(rec)
            if text:
                builder.ask(text, command)
            for image in user_images(rec, keep_data=keep_images):
                builder.attach(image)
        elif kind == "assistant":
            builder.answer(assistant_text(rec), rec.get("message"))
    builder.result()
    return builder


def build_turns(path: Path) -> tuple[list[tuple[str, str]], str | None, list[str]]:
    """The purified dialog of a Claude Code transcript: (turns, last timestamp,
    per-turn models). See TurnBuilder for the pairing rules."""
    return walk_claude(path).result()


def claude_image(path: Path, index: int, n: int) -> tuple[str, bytes] | None:
    """The n-th picture pasted with exchange `index` (both 1-based), decoded —
    or None when there is no such picture."""
    walk = walk_claude(path, keep_images=True)
    if not (1 <= index <= len(walk.attachments)):
        return None
    images = walk.attachments[index - 1]
    if not (1 <= n <= len(images)):
        return None
    try:
        return images[n - 1]["media_type"], base64.b64decode(images[n - 1]["data"])
    except (ValueError, binascii.Error):
        return None


def drop_trailing_unanswered(
    turns: list[tuple[str, str]], models: list[str] | None = None
) -> tuple[list[tuple[str, str]], list[str]]:
    """Drop a trailing question with no answer, keeping models in step. One
    function rather than two so the turn list and its labels cannot drift."""
    models = list(models or [])
    if turns and not turns[-1][1].strip():
        return turns[:-1], models[:-1]
    return turns, models


def render(
    turns: list[tuple[str, str]],
    source: str,
    session_id: str | None,
    models: list[str] | None = None,
) -> str:
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
        model = models[i - 1] if models and i <= len(models) else ""
        blocks.append(f"## User {i}\n\n{user}\n")
        blocks.append(f"## Agent {i}{f' — `{model}`' if model else ''}\n\n{reply}\n")
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
    return datetime.fromtimestamp(source.stat().st_mtime).astimezone().strftime("%Y-%m-%d_%H%M")
