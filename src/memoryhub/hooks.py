"""Claude Code hook wiring: automate `mh load` / `mh save` per session.

Two halves. `read_payload()` parses the JSON Claude Code pipes to a hook
command on stdin (cwd, transcript_path, session_id, source, ...). install() /
remove() edit a settings file's "hooks" table, merging with whatever is already
there — mh only ever appends or removes its own `mh hook ...` entries, never
touching hooks it does not own.

The hook commands themselves (cli.py) are deliberately forgiving: a hook that
fails a session teardown helps nobody, so "no hub here" and "nothing to save"
exit 0 quietly, and only real failures (git broken) speak up.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .hub import MhError

# SessionStart stdout is injected into the session's context — that is the
# whole trick: memory arrives without the agent having to remember to fetch it.
# SessionEnd and PreCompact both save; PreCompact matters most, it snapshots
# the dialog right before compaction would destroy it.
HOOK_COMMANDS = {
    "SessionStart": "mh hook load",
    "SessionEnd": "mh hook save",
    "PreCompact": "mh hook save",
}
MH_PREFIX = "mh hook "


def read_payload() -> dict:
    """The hook input JSON from stdin, or {} when a hook sent nothing usable."""
    if sys.stdin.isatty():
        raise MhError(
            "this command reads Claude Code hook JSON on stdin — it is wired "
            "by 'mh hook install', not typed by hand"
        )
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def settings_path(project_root: Path | None) -> Path:
    """Project install: .claude/settings.local.json (personal, not checked in —
    collaborators without mh must not inherit the hooks). User install: the
    global ~/.claude/settings.json."""
    if project_root is None:
        return Path.home() / ".claude" / "settings.json"
    return project_root / ".claude" / "settings.local.json"


def _load_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise MhError(f"{path} is not valid JSON ({e}); fix it before installing hooks") from None
    if not isinstance(data, dict):
        raise MhError(f"{path} does not hold a JSON object; refusing to rewrite it")
    return data


def _write_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _has_mh_hook(entries: list) -> bool:
    return any(
        isinstance(h, dict) and str(h.get("command", "")).startswith(MH_PREFIX)
        for e in entries
        if isinstance(e, dict)
        for h in e.get("hooks", [])
    )


def install(path: Path, budget: int | None = None) -> list[str]:
    """Add mh's hook entries to a settings file; returns the events added.
    Idempotent — an event that already carries an `mh hook` command is left
    exactly as it is. `budget` sizes the pack SessionStart injects."""
    data = _load_settings(path)
    hooks_cfg = data.setdefault("hooks", {})
    if not isinstance(hooks_cfg, dict):
        raise MhError(f"'hooks' in {path} is not an object; refusing to rewrite it")
    added = []
    commands = dict(HOOK_COMMANDS)
    if budget is not None:
        commands["SessionStart"] += f" --budget {budget}"
    for event, cmd in commands.items():
        entries = hooks_cfg.setdefault(event, [])
        if not isinstance(entries, list):
            raise MhError(f"'hooks.{event}' in {path} is not a list; refusing to rewrite it")
        if _has_mh_hook(entries):
            continue
        entries.append({"hooks": [{"type": "command", "command": cmd}]})
        added.append(event)
    if added:
        _write_settings(path, data)
    return added


def remove(path: Path) -> list[str]:
    """Strip mh's hook entries from a settings file; returns the events touched.
    Hooks mh does not own are preserved untouched."""
    data = _load_settings(path)
    hooks_cfg = data.get("hooks")
    if not isinstance(hooks_cfg, dict):
        return []
    removed = []
    for event in list(hooks_cfg):
        entries = hooks_cfg[event]
        if not isinstance(entries, list) or not _has_mh_hook(entries):
            continue
        kept_entries = []
        for e in entries:
            if not isinstance(e, dict):
                kept_entries.append(e)
                continue
            kept_hooks = [
                h
                for h in e.get("hooks", [])
                if not (isinstance(h, dict) and str(h.get("command", "")).startswith(MH_PREFIX))
            ]
            if kept_hooks or not e.get("hooks"):
                kept_entries.append({**e, "hooks": kept_hooks} if "hooks" in e else e)
        if kept_entries:
            hooks_cfg[event] = kept_entries
        else:
            del hooks_cfg[event]
        removed.append(event)
    if removed:
        _write_settings(path, data)
    return removed
