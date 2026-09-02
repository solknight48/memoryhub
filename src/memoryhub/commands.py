"""What the session's CLI accepts at the start of a message — its skills and
slash commands — read from disk so the page's input box can offer them.

mh keeps no list of its own to maintain. A skill is a SKILL.md in a directory
the agent reads; a command is a markdown file in a commands directory; a
plugin's skills are `/plugin:name`. Verified on this machine's own data: Claude
Code and pi share the SKILL.md format, and both are invoked as `/name` (pi
sessions here carry `/mh save …` typed exactly as in Claude Code). Codex is not
verified, so it gets no list rather than a guessed one — the box still sends
whatever is typed.

The CLI's built-in commands live nowhere mh can read. A short list of the ones
worth sending from a browser rides along, marked as such; anything else can be
typed all the same, because the message goes to the CLI, not to this list.
"""

from __future__ import annotations

import json
from pathlib import Path

DESCRIPTION_MAX = 160

# Claude Code built-ins that act or print as soon as they arrive. The dialogs
# (/permissions, /resume, /config …) are left out: they open in the terminal,
# where the page cannot see them.
CLAUDE_BUILTINS = [
    ("model", "Switch the model for this session", "<model>"),
    ("clear", "Clear the conversation and start fresh", None),
    ("compact", "Compact the conversation, keeping what matters", "[focus]"),
    ("cost", "Show what this session has cost", None),
    ("context", "Show what is using the context window", None),
    ("status", "Show the session's status", None),
    ("help", "List the CLI's own commands", None),
    ("init", "Write a CLAUDE.md for this project", None),
    ("export", "Export the conversation", "[file]"),
    ("doctor", "Check the installation", None),
]
# Names `/model` resolves without a full id, in Claude Code's own words
CLAUDE_MODEL_ALIASES = [
    ("default", "the account's default"),
    ("opus", "the most capable"),
    ("sonnet", "balanced"),
    ("haiku", "the fastest"),
]


def _frontmatter(text: str) -> dict[str, str]:
    """The YAML frontmatter's scalar fields, enough for `name`, `description`
    and `argument-hint`: quoted or bare values, and folded (`>-`) or literal
    (`|`) blocks joined into one line. Anything fancier reads as text."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    key: str | None = None
    block: list[str] | None = None  # the lines of a folded value being collected

    def close() -> None:
        if key is not None and block is not None:
            out[key] = " ".join(block)

    for line in lines[1:]:
        if line.strip() == "---":
            break
        if block is not None and (not line.strip() or line[0] in " \t"):
            if line.strip():
                block.append(line.strip())
            continue
        close()
        block = None
        head, sep, value = line.partition(":")
        if not sep or head[:1] in (" ", "\t", "#"):
            continue
        key, value = head.strip(), value.strip()
        if value in (">", ">-", "|", "|-"):
            block = []
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            out[key] = value[1:-1]
        else:
            out[key] = value
    close()
    return out


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= DESCRIPTION_MAX else text[: DESCRIPTION_MAX - 1].rstrip() + "…"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _entry(name: str, kind: str, where: str, meta: dict[str, str], body: str) -> dict:
    description = meta.get("description") or _first_line(body)
    return {
        "name": name,
        "kind": kind,
        "where": where,
        "description": _clip(description),
        "hint": meta.get("argument-hint") or None,
    }


def _first_line(text: str) -> str:
    """A file without a description: its first line of prose, headings and
    frontmatter skipped."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
        except ValueError:
            return ""
        lines = lines[end + 1 :]
    for line in lines:
        s = line.strip().lstrip("#").strip()
        if s:
            return s
    return ""


def _skills(root: Path, kind: str, where: str, prefix: str = "") -> list[dict]:
    """`<root>/<name>/SKILL.md` for every name; the frontmatter's own `name`
    wins over the directory's when it has one."""
    found: list[dict] = []
    if not root.is_dir():
        return found
    for d in sorted(root.iterdir()):
        text = _read(d / "SKILL.md") if d.is_dir() else None
        if text is None:
            continue
        meta = _frontmatter(text)
        found.append(_entry(prefix + (meta.get("name") or d.name), kind, where, meta, text))
    found.sort(key=lambda e: e["name"])  # by the name it answers to, not its directory
    return found


def _command_files(root: Path, where: str, prefix: str = "") -> list[dict]:
    """`<root>/<name>.md` — the older custom-command form, still `/name`."""
    found: list[dict] = []
    if not root.is_dir():
        return found
    for f in sorted(root.glob("*.md")):
        text = _read(f)
        if text is None:
            continue
        found.append(_entry(prefix + f.stem, "command", where, _frontmatter(text), text))
    return found


def _claude_plugins(home: Path) -> list[dict]:
    """Installed plugins, from the registry Claude Code keeps: each install
    path's skills and commands, invoked as `/plugin:name`."""
    text = _read(home / ".claude" / "plugins" / "installed_plugins.json")
    if text is None:
        return []
    try:
        registry = json.loads(text).get("plugins", {})
    except (json.JSONDecodeError, AttributeError):
        return []
    found: list[dict] = []
    for key, installs in sorted(registry.items()):
        plugin = key.split("@", 1)[0]
        for inst in installs if isinstance(installs, list) else []:
            path = inst.get("installPath") if isinstance(inst, dict) else None
            if not path:
                continue
            found += _skills(Path(path) / "skills", "plugin", plugin, prefix=plugin + ":")
            found += _command_files(Path(path) / "commands", plugin, prefix=plugin + ":")
    return found


def _claude(project: Path, home: Path) -> list[dict]:
    out = _skills(project / ".claude" / "skills", "skill", "project")
    out += _skills(home / ".claude" / "skills", "skill", "user")
    out += _command_files(project / ".claude" / "commands", "project")
    out += _command_files(home / ".claude" / "commands", "user")
    out += _claude_plugins(home)
    out += [
        {"name": n, "kind": "builtin", "where": "claude", "description": d, "hint": h}
        for n, d, h in CLAUDE_BUILTINS
    ]
    return out


def _pi(project: Path, home: Path) -> list[dict]:
    out = _skills(project / ".pi" / "skills", "skill", "project")
    out += _skills(home / ".pi" / "agent" / "skills", "skill", "user")
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    """One entry per name, the first one standing — the project's copy of a
    skill shadows the user's, as it does for the CLI."""
    seen: set[str] = set()
    out = []
    for it in items:
        if it["name"] in seen:
            continue
        seen.add(it["name"])
        out.append(it)
    return out


def commands(agent: str, project: Path, home: Path | None = None) -> dict:
    """The slash commands the page may offer for this agent, and the model
    aliases behind `/model`. An agent mh has not verified gets `known: False`
    and nothing else — the page says so instead of inventing a list."""
    home = home or Path.home()
    if agent == "claude":
        found = _claude(project, home)
        models = [{"name": n, "description": d} for n, d in CLAUDE_MODEL_ALIASES]
    elif agent == "pi":
        found = _pi(project, home)
        models = []
    else:
        return {"agent": agent, "known": False, "commands": [], "models": []}
    return {"agent": agent, "known": True, "commands": _dedupe(found), "models": models}
