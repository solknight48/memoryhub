"""Typing into a live session from `mh ui`.

Driven against a real tmux server on a private socket (`TMUX_TMPDIR`), with a
stand-in agent — a copy of `cat` named `claude`, so the pane really does report
an agent as its foreground command. What matters most here is the refusals: mh
must never paste into a pane whose session has gone.
"""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest

from conftest import TIMEOUT, make_records, write_transcript
from memoryhub import live as livemod
from memoryhub import relay, server
from memoryhub.hub import MhError

SID = "aabbccdd-1111-4111-8111-111111111111"

needs_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="needs tmux to drive a real pane"
)


@pytest.fixture()
def tmux(ws, monkeypatch):
    """A tmux server of our own, and a fake agent to run in it."""
    sockdir = ws["root"] / "tmuxsock"
    sockdir.mkdir()
    monkeypatch.setenv("TMUX_TMPDIR", str(sockdir))
    bindir = ws["root"] / "fakebin"
    bindir.mkdir()
    agent = bindir / "claude"  # comm becomes "claude", which is the point
    shutil.copy(shutil.which("cat"), agent)

    started: list[str] = []

    def run(*args: str) -> str:
        return subprocess.run(
            ["tmux", *args], capture_output=True, text=True, timeout=TIMEOUT
        ).stdout

    def start(name: str = "t", cwd: str | None = None) -> str:
        run("new-session", "-d", "-s", name, *(["-c", cwd] if cwd else []), str(agent))
        started.append(name)
        for _ in range(50):  # the pane needs a moment to exec the agent
            panes = relay.panes()
            for pane, info in panes.items():
                if info["command"] == "claude":
                    return pane
            time.sleep(0.05)
        raise AssertionError("the fake agent never came up in a pane")

    yield {"start": start, "run": run, "agent": agent}
    for name in started:
        run("kill-session", "-t", name)
    run("kill-server")


def hub_of(project):
    return project / ".memoryhub"


def live_session(ws, project):
    livemod._discovery.clear()
    write_transcript(ws["home"], project, SID, make_records([("q", "a")], cwd=str(project)))
    return livemod.read(hub_of(project))


# --- no terminal, no pretending ----------------------------------------------


def test_without_tmux_the_panel_says_so_instead_of_failing(mh, ws, hub_project, monkeypatch):
    monkeypatch.setenv("TMUX_TMPDIR", str(ws["root"] / "empty"))
    (ws["root"] / "empty").mkdir()
    live = live_session(ws, hub_project)
    where = relay.target(hub_of(hub_project), live)
    assert "pane" not in where
    assert where["reason"] == relay.NOT_IN_TMUX  # what to do, not tmux's words

    # and the live payload carries the reason rather than blowing up the poll
    status, data = server.dispatch(hub_of(hub_project), "GET", "/api/live", {}, {}, False)
    assert status == 200
    assert "reason" in data["terminal"]


def test_an_empty_message_is_refused(mh, ws, hub_project):
    live_session(ws, hub_project)
    with pytest.raises(MhError, match="nothing to send"):
        relay.send(hub_of(hub_project), "   ")


# --- with a real pane ---------------------------------------------------------


@needs_tmux
def test_a_message_lands_in_the_session_terminal(mh, ws, hub_project, tmux):
    pane = tmux["start"]()
    hub = hub_of(hub_project)
    live = live_session(ws, hub_project)
    relay.record(hub, live.sid, pane, relay.panes()[pane]["pid"], str(hub_project))

    where = relay.target(hub, live)
    assert where["pane"] == pane and where["how"] == "recorded at session start"

    result = relay.send(hub, "ship it, and run the tests")
    assert result["pane"] == pane and result["chars"] == 26

    for _ in range(50):
        shown = tmux["run"]("capture-pane", "-p", "-t", pane)
        if "ship it" in shown:
            break
        time.sleep(0.05)
    assert "ship it, and run the tests" in shown


@needs_tmux
def test_a_multi_line_message_arrives_as_one_message(mh, ws, hub_project, tmux):
    pane = tmux["start"]()
    hub = hub_of(hub_project)
    live = live_session(ws, hub_project)
    relay.record(hub, live.sid, pane, None, str(hub_project))  # verified by command

    relay.send(hub, "first line\nsecond line")
    for _ in range(50):
        shown = tmux["run"]("capture-pane", "-p", "-t", pane)
        if "second line" in shown:
            break
        time.sleep(0.05)
    assert "first line" in shown and "second line" in shown


@needs_tmux
def test_mh_will_not_type_into_a_pane_whose_session_has_gone(mh, ws, hub_project, tmux):
    pane = tmux["start"]()
    hub = hub_of(hub_project)
    live = live_session(ws, hub_project)

    dead = subprocess.Popen(["sleep", "30"])
    dead.terminate()
    dead.wait(timeout=TIMEOUT)
    relay.record(hub, live.sid, pane, dead.pid, str(hub_project))

    where = relay.target(hub, live)
    assert "pane" not in where
    assert "has exited" in where["reason"]
    with pytest.raises(MhError, match="has exited"):
        relay.send(hub, "hello?")


@needs_tmux
def test_an_agent_restarted_in_the_recorded_pane_is_accepted(mh, ws, hub_project, tmux):
    """`claude -c` after a quit: the recorded pid is dead, but the pane holds
    an agent of this project again. That is the session coming back, not
    something else sitting at the prompt — verified by its cwd, like the
    fallback would."""
    pane = tmux["start"](cwd=str(hub_project))
    hub = hub_of(hub_project)
    live = live_session(ws, hub_project)
    dead = subprocess.Popen(["sleep", "30"])
    dead.terminate()
    dead.wait(timeout=TIMEOUT)
    relay.record(hub, live.sid, pane, dead.pid, str(hub_project))

    where = relay.target(hub, live)
    assert where["pane"] == pane and where["how"] == "restarted in the same pane"
    assert where["pid"] == relay.panes()[pane]["pid"]  # the agent now in the pane


def test_a_record_whose_tmux_has_exited_says_how_to_come_back(mh, ws, hub_project, monkeypatch):
    """A pane started as `tmux new -s mh claude` dies with claude, and the
    whole server with it. The reason names that mistake rather than claiming
    tmux was never used."""
    monkeypatch.setenv("TMUX_TMPDIR", str(ws["root"] / "empty"))
    (ws["root"] / "empty").mkdir()
    hub = hub_of(hub_project)
    live = live_session(ws, hub_project)
    relay.record(hub, live.sid, "%0", 1, str(hub_project))
    where = relay.target(hub, live)
    assert where["reason"] == relay.TMUX_GONE
    assert "tmux new -s mh" in where["reason"]


@needs_tmux
def test_a_pane_that_is_no_longer_there_falls_back_to_looking(mh, ws, hub_project, tmux):
    tmux["start"]()
    hub = hub_of(hub_project)
    live = live_session(ws, hub_project)
    relay.record(hub, live.sid, "%999", 1, str(hub_project))  # a pane that never was
    where = relay.target(hub, live)
    # the fake agent's cwd is not this project, so the process fallback finds
    # nothing and says how to fix it rather than picking something plausible
    assert "not running inside tmux" in where["reason"]


# --- what the hook records ----------------------------------------------------


def test_the_hook_records_the_pane_and_keeps_it_out_of_the_journal(
    mh, ws, hub_project, monkeypatch
):
    hub = hub_of(hub_project)
    monkeypatch.setenv("TMUX_PANE", "%7")
    relay.record_from_hook(hub, {"session_id": SID, "cwd": str(hub_project)})
    assert relay.read_panes(hub)[SID]["pane"] == "%7"
    assert "/panes.json" in (hub / ".git" / "info" / "exclude").read_text()
    status = subprocess.run(
        ["git", "-C", str(hub), "status", "--porcelain"],
        env=ws["env"],
        capture_output=True,
        text=True,
        check=True,
        timeout=TIMEOUT,
    ).stdout
    assert status.strip() == ""


def test_outside_tmux_the_hook_records_nothing(mh, ws, hub_project, monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    hub = hub_of(hub_project)
    relay.record_from_hook(hub, {"session_id": SID, "cwd": str(hub_project)})
    assert not relay.panes_path(hub).exists()
