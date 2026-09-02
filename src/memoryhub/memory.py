"""Claude Code's per-project auto-memory, read for the web UI.

Beside a project's transcripts (`~/.claude/projects/<project>/memory/`) Claude
Code keeps a memory folder: `MEMORY.md`, a one-line index, and one file per
fact — frontmatter (name, description, a metadata map) over a markdown body,
with `[[name]]` links between facts. mh does not own it and never writes it;
this reads it so the map can show it next to the checkpoints.

Verified format only: Claude Code's folder. Each fact records the session it
came from (`originSessionId`), so a note can point back at its transcript the
same way a saved session does.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import purify

INDEX = "MEMORY.md"
# a MEMORY.md row: "- [Title](file.md) — hook"
INDEX_ROW = re.compile(
    r"^\s*[-*]\s*\[(?P<title>[^\]]+)\]\((?P<file>[^)]+)\)\s*(?:[\u2014-]\s*(?P<hook>.*))?$"
)
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def folder(root: Path) -> Path:
    return Path.home() / ".claude" / "projects" / purify.encode_project_dir(root) / "memory"


def _split_front(text: str) -> tuple[dict, str]:
    """The frontmatter (top-level scalars plus a one-level `metadata` map) and
    the markdown body. Not a full YAML parser — the shape Claude Code writes."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text.strip()
    front: dict = {}
    into = front  # the map the next indented line belongs to
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        key, value = key.strip(), _unquote(value.strip())
        if line[0] in " \t":
            into[key] = value
        elif value == "":
            into = front[key] = {}  # a nested map opens (e.g. metadata:)
        else:
            into = front
            front[key] = value
    return front, "\n".join(lines[end + 1 :]).strip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _title_from(name: str) -> str:
    return name.replace("-", " ").replace("_", " ").strip().capitalize()


def read_index(dir_: Path) -> list[dict]:
    """MEMORY.md as an ordered list of {file, title, hook}."""
    path = dir_ / INDEX
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = INDEX_ROW.match(line)
        if m:
            rows.append(
                {
                    "file": m.group("file"),
                    "title": m.group("title").strip(),
                    "hook": (m.group("hook") or "").strip(),
                }
            )
    return rows


def _entry(path: Path, order: dict[str, dict]) -> dict:
    front, body = _split_front(path.read_text(encoding="utf-8", errors="replace"))
    meta = front.get("metadata") if isinstance(front.get("metadata"), dict) else {}
    listed = order.get(path.name, {})
    return {
        "name": front.get("name") or path.stem,
        "file": path.name,
        "title": listed.get("title") or front.get("name") or _title_from(path.stem),
        "hook": listed.get("hook", ""),
        "description": front.get("description", ""),
        "type": meta.get("type") or "note",
        "origin": meta.get("originSessionId") or None,
        "modified": (meta.get("modified") or "")[:10],
        "body": body,
        "links": sorted(set(WIKILINK.findall(body))),
    }


def read(root: Path) -> dict:
    """The project's memory folder for the page: the index order first, then any
    file the index does not list, newest by modification. Read-only, always."""
    dir_ = folder(root)
    if not dir_.is_dir():
        return {"present": False, "dir": str(dir_), "memories": []}
    index = read_index(dir_)
    order = {row["file"]: row for row in index}
    files = {p.name: p for p in dir_.glob("*.md") if p.name != INDEX and p.is_file()}
    memories = [_entry(files[row["file"]], order) for row in index if row["file"] in files]
    seen = {row["file"] for row in index}
    extra = sorted(
        (p for name, p in files.items() if name not in seen),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    memories += [_entry(p, order) for p in extra]
    return {"present": True, "dir": str(dir_), "memories": memories}
