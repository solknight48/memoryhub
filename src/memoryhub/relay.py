"""Typing into a live session from the browser.

The live panel is a reading surface until you can answer from it. mh has no
model and will not fake a reply: it finds the terminal the session is running
in and pastes your text there, exactly as if you had typed it, and the agent's
own answer arrives through the transcript like any other turn.

tmux only — it is the one multiplexer that will say which pane holds which
process. The pane is never guessed. `mh hook load` records it at session start
(tmux exports TMUX_PANE into every process in the pane, and the hook is a child
of the agent), and every send re-verifies that the pane still exists and that
the recorded agent is still alive inside it. A pane whose agent has exited, or
that has since been reused, fails that check: mh refuses to type rather than
paste into whatever is sitting at that prompt. The one thing it does accept in
that pane is an agent of this project that came back — `claude -c` after a
quit — verified through /proc like everything else here.

Start tmux as a shell (`tmux new -s mh`) and run the agent inside it: a pane
started as `tmux new -s mh claude` closes the moment claude quits, taking the
whole tmux session with it, and nothing can be typed into a pane that is gone.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from . import git
from . import live as livemod
from .hub import MhError, project_root_of

PANES_FILE = "panes.json"
EXCLUDE_LINE = "/panes.json"
AGENT_COMMS = {"claude", "pi", "codex"}
TIMEOUT = 5
NOT_IN_TMUX = (
    "this session is not running inside tmux — open one with 'tmux new -s mh', "
    "run 'claude -c' inside it, and mh can type into it"
)
TMUX_GONE = (
    "the tmux this session ran in has exited — open a lasting one with "
    "'tmux new -s mh' (not 'tmux new … claude', which closes when claude quits), "
    "then 'claude -c' inside it"
)


# --- what the hook records ----------------------------------------------------


def panes_path(hub: Path) -> Path:
    return hub / PANES_FILE


def read_panes(hub: Path) -> dict:
    path = panes_path(hub)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_panes(hub: Path, data: dict) -> None:
    if not panes_path(hub).exists():
        # Local, machine-specific, worthless in a clone: the same treatment the
        # `current` pointer and the live drafts get.
        git.exclude(hub, EXCLUDE_LINE)
    panes_path(hub).write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def record(hub: Path, sid: str, pane: str, pid: int | None, cwd: str | None) -> None:
    data = read_panes(hub)
    data[sid] = {
        "pane": pane,
        "pid": pid,
        "cwd": cwd,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _write_panes(hub, data)


def record_from_hook(hub: Path, payload: dict) -> None:
    """Best effort, always quiet: a session that cannot be typed into is a
    missing convenience, never a reason to disturb a session start."""
    sid = payload.get("session_id")
    pane = os.environ.get("TMUX_PANE")
    if not (isinstance(sid, str) and sid and pane):
        return
    with contextlib.suppress(OSError, MhError):
        record(hub, sid, pane, _agent_ancestor(os.getpid()), payload.get("cwd"))


# --- processes ----------------------------------------------------------------


def _stat_field(pid: int, index: int) -> str | None:
    """A field of /proc/<pid>/stat, counted after the comm parens — the comm
    itself may contain spaces, so splitting the whole line does not work."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    tail = raw.rpartition(")")[2].split()
    return tail[index] if index < len(tail) else None


def _ppid(pid: int) -> int | None:
    field = _stat_field(pid, 1)  # state, then ppid
    return int(field) if field and field.isdigit() else None


def _comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return ""


def _alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").is_dir()


def _ancestors(pid: int, limit: int = 24) -> list[int]:
    out: list[int] = []
    seen = {pid}
    for _ in range(limit):
        parent = _ppid(pid)
        if parent is None or parent in seen or parent <= 1:
            break
        out.append(parent)
        seen.add(parent)
        pid = parent
    return out


def _agent_ancestor(pid: int) -> int | None:
    for p in _ancestors(pid):
        if _comm(p) in AGENT_COMMS:
            return p
    return None


def _agents_in(root: Path) -> list[int]:
    """Agent processes running inside this project — the fallback for a session
    that started before mh recorded panes."""
    found: list[int] = []
    try:
        pids = sorted(int(d.name) for d in Path("/proc").iterdir() if d.name.isdigit())
    except OSError:
        return found
    for pid in pids:
        if _comm(pid) not in AGENT_COMMS:
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        if cwd == str(root) or cwd.startswith(str(root) + "/"):
            found.append(pid)
    return found


# --- tmux ---------------------------------------------------------------------


def _tmux(*args: str) -> str:
    try:
        proc = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise MhError("tmux is not installed, so mh cannot type into a session") from None
    except subprocess.TimeoutExpired:
        raise MhError("tmux did not answer in time") from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise MhError(f"tmux {args[0]} failed: {detail[0] if detail else 'unknown error'}")
    return proc.stdout


def panes() -> dict[str, dict]:
    """Every pane on this machine: id -> {pid, command}."""
    out: dict[str, dict] = {}
    try:
        listed = _tmux("list-panes", "-a", "-F", "#{pane_id}\t#{pane_pid}\t#{pane_current_command}")
    except MhError as e:
        # tmux installed but not running is not a failure, it is zero panes —
        # and the caller has something useful to say about that.
        if "no server running" in e.message or "error connecting" in e.message:
            return {}
        raise
    for line in listed.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[1].isdigit():
            out[parts[0]] = {"pid": int(parts[1]), "command": parts[2]}
    return out


def _in_pane(pid: int, pane_pid: int) -> bool:
    return pid == pane_pid or pane_pid in _ancestors(pid)


def _agent_in_pane(info: dict, root: Path) -> int | None:
    """An agent process of this project running in the pane, or None."""
    for pid in _agents_in(root):
        if _in_pane(pid, info["pid"]):
            return pid
    return None


def target(hub: Path, live: livemod.LiveSession) -> dict:
    """Where this session's keystrokes would go: {"pane": ...} or {"reason": ...}.

    Verified against tmux and /proc every time — a record written at session
    start proves nothing about a pane an hour later.
    """
    try:
        available = panes()
    except MhError as e:
        return {"reason": e.message}
    rec = read_panes(hub).get(live.sid)
    if not available:
        # a record with no server behind it: the tmux it named is gone, which
        # is a different fix from never having used tmux
        return {"reason": TMUX_GONE if isinstance(rec, dict) else NOT_IN_TMUX}

    if isinstance(rec, dict) and rec.get("pane") in available:
        pane = rec["pane"]
        pid = rec.get("pid")
        info = available[pane]
        if isinstance(pid, int) and _alive(pid) and _in_pane(pid, info["pid"]):
            return {"pane": pane, "pid": pid, "how": "recorded at session start"}
        if pid is None and info["command"] in AGENT_COMMS:
            return {"pane": pane, "pid": None, "how": "recorded at session start"}
        # Another session recorded this pane later and is still alive in it:
        # the pane is theirs now. Without this, an old session viewed from its
        # own page would type into whichever session runs there today.
        for other, orec in read_panes(hub).items():
            if other == live.sid or not isinstance(orec, dict) or orec.get("pane") != pane:
                continue
            opid = orec.get("pid")
            if isinstance(opid, int) and _alive(opid) and _in_pane(opid, info["pid"]):
                return {
                    "reason": f"tmux pane {pane} now runs session ‹{other[:8]}›, not this "
                    "one; open that session to type into it"
                }
        # `claude -c` after a quit: the pane holds an agent of this project
        # again — the session resumed, not "whatever took its place"
        again = _agent_in_pane(info, project_root_of(hub))
        if again is not None:
            return {"pane": pane, "pid": again, "how": "restarted in the same pane"}
        return {
            "reason": f"the session that ran in tmux pane {pane} has exited; mh "
            "will not type into whatever took its place"
        }

    # No record (the session predates it, or the hooks are not installed): fall
    # back to this project's agent processes, but only when there is exactly
    # one — choosing between two would be guessing which session you meant.
    matches = [
        (pid, pane)
        for pid in _agents_in(project_root_of(hub))
        for pane, info in available.items()
        if _in_pane(pid, info["pid"])
    ]
    if len(matches) == 1:
        return {"pane": matches[0][1], "pid": matches[0][0], "how": "matched by process"}
    if not matches:
        return {"reason": NOT_IN_TMUX}
    return {
        "reason": f"{len(matches)} agents of this project are running in tmux; mh "
        "cannot tell which is this session (restart it so the hook records the pane)"
    }


def send(hub: Path, text: str, sid: str | None = None) -> dict:
    """Paste text into the session's terminal and submit it."""
    body = (text or "").strip()
    if not body:
        raise MhError("nothing to send")
    live = livemod.read(hub, sid)
    if live is None:
        raise MhError("no transcript for this project yet (claude, pi, codex)")
    where = target(hub, live)
    if "reason" in where:
        raise MhError(where["reason"])
    # A paste, not keystrokes: bracketed paste keeps a multi-line message one
    # message instead of submitting it at every newline.
    _tmux("set-buffer", "--", body)
    _tmux("paste-buffer", "-d", "-p", "-t", where["pane"])
    _tmux("send-keys", "-t", where["pane"], "Enter")
    return {"pane": where["pane"], "chars": len(body), "session": live.key}
