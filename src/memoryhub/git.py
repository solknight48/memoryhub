"""Thin wrapper around the system git binary, always scoped to a directory."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, git_args: tuple[str, ...], returncode: int, stderr: str):
        super().__init__(f"git {' '.join(git_args)} failed ({returncode})")
        self.git_args = git_args
        self.returncode = returncode
        self.stderr = stderr


LOCK_HINT = "another mh/git process is writing to this hub; retry in a moment"


def stderr_lines(e: GitError) -> list[str]:
    return [ln for ln in (e.stderr or "").strip().splitlines() if ln.strip()]


def explain(e: GitError) -> str:
    """One wording for a failed git call, so the CLI and the UI never describe
    the same failure differently."""
    if "index.lock" in (e.stderr or ""):
        return LOCK_HINT
    detail = stderr_lines(e)
    head = f"git {e.git_args[0]} failed"
    return f"{head}: {detail[0]}" if detail else head


def _env() -> dict[str, str]:
    env = os.environ.copy()
    # mh-invoked git must never block on a terminal prompt (agents would hang).
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run(target: Path, *args: str, check: bool = True) -> str:
    """Run git with captured output; return stdout."""
    proc = subprocess.run(
        ["git", "--no-pager", "-C", str(target), *args],
        capture_output=True,
        text=True,
        env=_env(),
    )
    if check and proc.returncode != 0:
        raise GitError(args, proc.returncode, proc.stderr)
    return proc.stdout


def passthrough(target: Path, *args: str) -> int:
    """Run git with inherited stdio (git's own output is the UX)."""
    proc = subprocess.run(["git", "--no-pager", "-C", str(target), *args], env=_env())
    return proc.returncode


def exclude(target: Path, line: str) -> None:
    """Add a line to a repo's local `.git/info/exclude`. Untracked by
    definition, so local-only state stays out of the journal — and out of any
    clone. Silent when target is not a repo: an ignore rule is never the point
    of the operation that asks for it.
    """
    try:
        common = run(target, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    except GitError:
        return
    path = Path(common) / "info" / "exclude"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.is_file() else ""
    if line in text.splitlines():
        return
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + line + "\n")


def is_dirty(target: Path) -> bool:
    return bool(run(target, "status", "--porcelain").strip())


def auto_commit(target: Path, message: str, allow_empty: bool = False) -> None:
    run(target, "add", "-A")
    if not allow_empty and not run(target, "status", "--porcelain").strip():
        return
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    run(target, *args)
