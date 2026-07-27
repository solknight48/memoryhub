"""Hub discovery, initialization, registry, and the current-checkpoint pointer."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import git

HUB_DIR = ".memoryhub"
EXCLUDE_LINE = "/.memoryhub/"

CLAUDE_SNIPPET = (
    "## Memory\n"
    "This project uses MemoryHub (`mh`). At session start run `mh load` and treat the output as\n"
    "prior project memory. At session end run `mh save`. Start a new workstream with\n"
    "`mh checkpoint <name>`. See the mh skill for details.\n"
)

HUB_README = """\
# MemoryHub

This directory is a MemoryHub: checkpointed, purified AI session context for the
surrounding project, managed by the `mh` CLI.

- `checkpoints/<created>_<name>/` — a checkpoint: a container of purified sessions
  (`<timestamp>_<session-id>.md`), independent of other checkpoints unless linked.
- `links.toml` — undirected links between checkpoints; linked checkpoints load together.
- `current` — untracked local pointer to the current checkpoint.

The hub is a normal git repo: every mh mutation is a commit. Anything mh does not
cover (rename, delete, merge, undo) is plain `git -C <this dir> ...`.
"""


class MhError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "memoryhub"


def registry_path() -> Path:
    return config_dir() / "hubs.toml"


def read_registry() -> list[str]:
    path = registry_path()
    if not path.is_file():
        return []
    return [str(p) for p in tomllib.loads(path.read_text()).get("hubs", [])]


def write_registry(paths: list[str]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    uniq = sorted(set(paths))
    if uniq:
        rows = ",\n  ".join(json.dumps(p) for p in uniq)
        path.write_text(f"hubs = [\n  {rows},\n]\n")
    else:
        path.write_text("hubs = []\n")


def discover(cwd: Path | None = None) -> Path:
    env = os.environ.get("MH_HUB")
    if env:
        hub = Path(env).expanduser()
        if not (hub / ".git").exists():
            raise MhError(f"MH_HUB={env} is not an initialized hub", 2)
        return hub.resolve()
    start = (cwd or Path.cwd()).resolve()
    for parent in [start, *start.parents]:
        hub = parent / HUB_DIR
        if hub.is_dir():
            if (hub / ".git").exists():
                return hub
            raise MhError(
                f"found {hub} but it is not initialized (run 'mh init' from {parent})",
                2,
            )
    raise MhError("no hub found (run 'mh init' to create one)", 2)


def project_root_of(hub: Path) -> Path:
    return hub.parent


def read_current(hub: Path) -> str | None:
    path = hub / "current"
    if not path.is_file():
        return None
    return path.read_text().strip() or None


def write_current(hub: Path, slug: str) -> None:
    (hub / "current").write_text(slug + "\n")


def clear_current(hub: Path) -> None:
    (hub / "current").unlink(missing_ok=True)


@dataclass
class InitResult:
    hub: Path
    root: Path
    created: bool
    shadowed: Path | None


def _write_exclude(root: Path) -> None:
    try:
        common = git.run(
            root, "rev-parse", "--path-format=absolute", "--git-common-dir"
        ).strip()
    except git.GitError:
        return
    exclude = Path(common) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    text = exclude.read_text() if exclude.is_file() else ""
    if EXCLUDE_LINE in text.splitlines():
        return
    if text and not text.endswith("\n"):
        text += "\n"
    exclude.write_text(text + EXCLUDE_LINE + "\n")


def _register(hub: Path) -> None:
    write_registry(read_registry() + [str(hub)])


def init_hub(cwd: Path, global_: bool = False) -> InitResult:
    if global_:
        root = Path.home()
    else:
        try:
            root = Path(git.run(cwd, "rev-parse", "--show-toplevel").strip())
        except git.GitError:
            root = cwd.resolve()
    hub = root / HUB_DIR
    if (hub / ".git").exists():
        _register(hub)
        return InitResult(hub, root, False, None)

    shadowed = None
    try:
        shadowed = discover(root.parent)
    except MhError:
        pass

    hub.mkdir(parents=True, exist_ok=True)
    (hub / "checkpoints").mkdir(exist_ok=True)
    git.run(hub, "init", "-b", "main")
    (hub / ".gitignore").write_text("/current\n")
    (hub / "README.md").write_text(HUB_README)
    git.auto_commit(hub, "mh: init hub")
    if not global_:
        _write_exclude(root)
    _register(hub)
    return InitResult(hub, root, True, shadowed)


def append_claude_snippet(root: Path) -> Path:
    path = root / "CLAUDE.md"
    text = path.read_text() if path.is_file() else ""
    if "## Memory" in text:
        return path
    if text and not text.endswith("\n"):
        text += "\n"
    if text:
        text += "\n"
    path.write_text(text + CLAUDE_SNIPPET)
    return path
