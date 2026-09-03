"""Compaction by the session's own agent: a summary instead of the dialog.

`mh save --compact --file` stores a summary someone else wrote. This is the
other way to get one without mh growing a model of its own: hand the purified
dialog to the CLI that ran the session — `claude -p` for Claude Code, `pi -p`
for pi — with that tool's own compaction prompt, and store what comes back as
the compacted save.

The running session is never touched. The CLI starts fresh and non-interactive
in a scratch directory with tools, session persistence and (for claude) the
nested-session markers off, so the only trace is one model call on the user's
account and the summary that lands in the hub. codex has no verified print
mode here, so a codex session gets no compaction.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import curate, live, purify
from . import save as savemod
from .hub import MhError

TIMEOUT = 300  # seconds; a long session's summary is a minute or two

CLIS = {"claude": "claude", "pi": "pi"}
CHOICES = ("agent", *CLIS)  # `--with agent` means whichever ran the session

# Both tools read the conversation first and the instructions last, the order
# that keeps a long input from burying the task.
SYSTEM = (
    "You are a context summarization assistant. Your task is to read a "
    "conversation between a user and an AI assistant, then produce a structured "
    "summary following the exact format specified.\n\n"
    "Do NOT continue the conversation. Do NOT respond to any questions in the "
    "conversation. ONLY output the structured summary."
)

# The shape Claude Code's own /compact produces: the numbered sections its
# continuation summaries carry, so a save compacted here reads like one the
# CLI would have written.
CLAUDE_INSTRUCTIONS = """\
The conversation above is a coding session to summarize. Create a detailed \
summary that another instance of the assistant will use to continue the work \
without the original context.

Use this EXACT format, in markdown, and only this:

1. Primary Request and Intent: every explicit request the user made and the \
intent behind it.
2. Key Technical Concepts: technologies, frameworks and ideas discussed.
3. Files and Code Sections: each file examined, modified or created, why it \
mattered, and the key snippets or changes (exact paths).
4. Errors and Fixes: every error hit and how it was fixed, including any user \
feedback that changed the approach.
5. Problem Solving: problems solved and ongoing troubleshooting.
6. All User Messages: every message the user typed (not tool results), in order.
7. Pending Tasks: what the user asked for that is not done.
8. Current Work: exactly what was in progress immediately before this summary, \
with file names and code where relevant.
9. Optional Next Step: the next step only if it follows directly from the \
user's most recent request, with the user's own words that call for it.

Preserve any security-relevant instruction or constraint verbatim. Preserve \
exact file paths, function names, commands and error messages."""

# pi's compaction prompt, verbatim from pi-mono
# (packages/coding-agent/src/core/compaction/compaction.ts, MIT), so a save
# compacted from a pi session has the same sections pi's own /compact writes.
PI_INSTRUCTIONS = """\
The messages above are a conversation to summarize. Create a structured context \
checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session \
covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Keep each section concise. Preserve exact file paths, function names, and error \
messages."""

INSTRUCTIONS = {"claude": CLAUDE_INSTRUCTIONS, "pi": PI_INSTRUCTIONS}

# What the summarizer must not inherit from the process that starts it: the
# markers Claude Code sets for its own children (a nested claude refuses to
# start under them) and the tmux pane of the session being summarized.
SCRUB_PREFIXES = ("CLAUDE_CODE_",)
SCRUB = frozenset({"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "TMUX", "TMUX_PANE"})


def describe(agent: str) -> dict:
    """Whether a session of this agent can be compacted here, and by what."""
    cli = CLIS.get(agent)
    if cli is None:
        return {
            "agent": agent,
            "cli": None,
            "available": False,
            "reason": f"no compaction for {agent} sessions yet (no verified print mode)",
        }
    found = shutil.which(cli)
    return {
        "agent": agent,
        "cli": cli,
        "available": found is not None,
        "reason": None if found else f"{cli} is not on PATH",
    }


def build_prompt(agent: str, dialog: str, focus: str | None = None) -> str:
    """The one message the summarizer gets: the dialog, the tool's own
    instructions, and the optional focus — `/compact <instructions>`."""
    if agent not in INSTRUCTIONS:
        raise MhError(describe(agent)["reason"])
    text = f"<conversation>\n{dialog.strip()}\n</conversation>\n\n{INSTRUCTIONS[agent]}"
    if focus:
        text += f"\n\nAdditional focus: {focus.strip()}"
    return text + "\n"


def argv(agent: str) -> list[str]:
    """The print-mode invocation: one turn, no tools, nothing persisted."""
    if agent == "claude":
        return [
            "claude",
            "-p",
            "--no-session-persistence",
            "--max-turns",
            "1",
            "--tools",
            "",
            "--system-prompt",
            SYSTEM,
        ]
    if agent == "pi":
        return [
            "pi",
            "-p",
            "--no-session",
            "--no-tools",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--system-prompt",
            SYSTEM,
        ]
    raise MhError(describe(agent)["reason"])


def environment(agent: str) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in SCRUB and not k.startswith(SCRUB_PREFIXES)
    }
    env.setdefault("NO_COLOR", "1")
    return env


def _unfence(text: str) -> str:
    """A model that wraps its answer in a markdown fence gets unwrapped."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def summarize(agent: str, dialog: str, focus: str | None = None, *, timeout: int = TIMEOUT) -> str:
    """Run the agent's CLI over the dialog and return its summary. Raises
    MhError with the CLI's own words when it is missing, fails or says nothing;
    a compacted save is never written from a failure."""
    info = describe(agent)
    if not info["available"]:
        raise MhError(info["reason"])
    cli = info["cli"]
    prompt = build_prompt(agent, dialog, focus)
    # A scratch cwd: no project settings, memory or hooks of the real project
    # apply to the summarizer, and nothing it might write lands among the
    # project's own transcripts.
    scratch = tempfile.mkdtemp(prefix="mh-compact-")
    try:
        proc = subprocess.run(
            argv(agent),
            input=prompt,
            capture_output=True,
            text=True,
            cwd=scratch,
            env=environment(agent),
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise MhError(f"{cli} is not on PATH") from None
    except subprocess.TimeoutExpired:
        raise MhError(f"{cli} -p did not finish within {timeout}s — nothing saved") from None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = " · ".join(detail[-3:]) if detail else "no output"
        raise MhError(f"{cli} -p failed (exit {proc.returncode}): {tail}")
    summary = _unfence(proc.stdout)
    if not summary:
        raise MhError(f"{cli} -p returned an empty summary — nothing saved")
    return summary


def compact_live(
    hub: Path,
    sid: str | None = None,
    focus: str | None = None,
    ckpt_ref: str | None = None,
    via: str | None = None,
) -> dict:
    """The panel's path: summarize the live session (draft applied, the
    unanswered tail dropped as every save does) and store the result where
    save.store puts this session. A compacted save is a deliberate choice, so
    it replaces whatever representation is there."""
    ls = live.read(hub, sid)
    if ls is None:
        raise MhError("no transcript for this project yet (claude, pi, codex)")
    agent = ls.agent if via in (None, "agent") else via
    entries = live.read_draft(hub, ls.key)
    turns, models, applied, _stale = live.curated(ls, entries)
    if not turns:
        raise MhError(f"no dialog to compact yet in {ls.path.name}")
    dialog = purify.render(turns, str(ls.path), ls.sid, models)
    summary = summarize(agent, dialog, focus)
    body = curate.render_compacted(summary, str(ls.path), ls.sid, len(turns))
    stored = savemod.store(
        hub,
        ls.key,
        body,
        purify.stamp_for(ls.last_ts, ls.path),
        ckpt_ref,
        replace_compacted=True,
        note=f"compact via {agent}",
    )
    return {
        "checkpoint": stored.checkpoint.slug,
        "file": stored.file,
        "exchanges": len(turns),
        "agent": agent,
        "chars": len(summary),
        "applied": applied,
        "moved_from": stored.moved_from,
    }
