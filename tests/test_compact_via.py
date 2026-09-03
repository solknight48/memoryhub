"""`--with`: the session's own CLI writes the compacted summary.

mh has no model; `compact.py` runs `claude -p` or `pi -p` in print mode over
the purified dialog. The suite must never make a model call, so a fake `claude`
and `pi` sit first on PATH: they record how they were called (arguments, cwd,
stdin, the environment mh must scrub) and answer with a canned summary.
"""

import os
import subprocess

import pytest

from conftest import make_records, write_transcript
from memoryhub import checkpoint as ck
from memoryhub import compact, server
from memoryhub.hub import MhError

SID = "c1d2e3f4-4444-4444-8444-444444444444"

FAKE_CLI = r"""#!/usr/bin/env bash
# A stand-in for `claude` / `pi` in print mode: log the call, print a summary.
printf '%s\n' "$0" > "$MH_FAKE_LOG.cli"
printf '%s\n' "$PWD" > "$MH_FAKE_LOG.cwd"
printf '%s\0' "$@" > "$MH_FAKE_LOG.argv"
cat > "$MH_FAKE_LOG.stdin"
env | grep -E '^(CLAUDECODE|CLAUDE_CODE_SESSION_ID|TMUX|TMUX_PANE)=' >"$MH_FAKE_LOG.env" || true
if [ -n "$MH_FAKE_FAIL" ]; then echo "boom: not logged in" >&2; exit 3; fi
if [ -n "$MH_FAKE_EMPTY" ]; then exit 0; fi
printf '%s\n' "${MH_FAKE_OUT:-## Goal
Ship it.}"
"""


@pytest.fixture()
def fake_cli(tmp_path, monkeypatch):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    for name in ("claude", "pi"):
        exe = bin_dir / name
        exe.write_text(FAKE_CLI)
        exe.chmod(0o755)
    log = tmp_path / "calls"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MH_FAKE_LOG", str(log))
    for var in ("MH_FAKE_FAIL", "MH_FAKE_EMPTY", "MH_FAKE_OUT"):
        monkeypatch.delenv(var, raising=False)
    return log


def _call(log):
    """What the fake CLI saw: (cli name, argv, cwd, stdin, leaked env lines)."""
    read = lambda ext: log.with_name(log.name + ext).read_text()  # noqa: E731
    argv = read(".argv").split("\0")[:-1]
    return (
        os.path.basename(read(".cli").strip()),
        argv,
        read(".cwd").strip(),
        read(".stdin"),
        [line for line in read(".env").splitlines() if line],
    )


def _hub(project):
    return project / ".memoryhub"


def _only_body(project):
    c = ck.list_checkpoints(_hub(project))[0]
    return c.sessions[0].read_text(), c.sessions[0]


# --- the module ---------------------------------------------------------------


def test_describe_names_the_cli_or_says_why_not(fake_cli, monkeypatch, tmp_path):
    assert compact.describe("claude") == {
        "agent": "claude",
        "cli": "claude",
        "available": True,
        "reason": None,
    }
    assert compact.describe("pi")["available"] is True
    codex = compact.describe("codex")
    assert codex["available"] is False and "codex" in codex["reason"]
    empty = tmp_path / "nothing"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert compact.describe("claude") == {
        "agent": "claude",
        "cli": "claude",
        "available": False,
        "reason": "claude is not on PATH",
    }


def test_prompt_is_the_dialog_then_the_tools_own_instructions():
    dialog = "## User 1\n\nhello\n\n## Agent 1\n\nhi\n"
    claude = compact.build_prompt("claude", dialog)
    assert claude.index("<conversation>") < claude.index("hello") < claude.index("</conversation>")
    assert claude.index("</conversation>") < claude.index("1. Primary Request and Intent")
    assert "Additional focus" not in claude
    pi = compact.build_prompt("pi", dialog, focus="the API changes")
    assert "## Goal" in pi and "## Next Steps" in pi  # pi's own /compact format
    assert pi.rstrip().endswith("Additional focus: the API changes")
    with pytest.raises(MhError, match="codex"):
        compact.build_prompt("codex", dialog)


def test_claude_runs_one_turn_without_tools_in_a_scratch_cwd_with_a_clean_env(
    fake_cli, monkeypatch
):
    # what the map server inherits from the agent session that started it
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SID)
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,1,0")
    monkeypatch.setenv("TMUX_PANE", "%3")
    out = compact.summarize("claude", "## User 1\n\nq\n\n## Agent 1\n\na\n", "focus on tests")
    assert out == "## Goal\nShip it."
    cli, argv, cwd, stdin, leaked = _call(fake_cli)
    assert cli == "claude"
    assert argv[:6] == ["-p", "--no-session-persistence", "--max-turns", "1", "--tools", ""]
    assert argv[argv.index("--system-prompt") + 1] == compact.SYSTEM
    assert "--bare" not in argv  # it skips the login state
    assert "## User 1" in stdin and stdin.rstrip().endswith("Additional focus: focus on tests")
    assert leaked == []  # a nested claude refuses to start under these
    assert "mh-compact-" in cwd and cwd != os.getcwd()
    assert not os.path.isdir(cwd)  # the scratch directory is gone afterwards


def test_pi_runs_ephemeral_with_nothing_of_the_project_loaded(fake_cli):
    compact.summarize("pi", "## User 1\n\nq\n\n## Agent 1\n\na\n")
    cli, argv, _cwd, stdin, _ = _call(fake_cli)
    assert cli == "pi"
    for flag in ("-p", "--no-session", "--no-tools", "--no-extensions", "--no-skills"):
        assert flag in argv
    assert "--no-context-files" in argv and "--no-prompt-templates" in argv
    assert "Use this EXACT format:" in stdin and "## Critical Context" in stdin


def test_a_fenced_answer_is_unwrapped(fake_cli, monkeypatch):
    monkeypatch.setenv("MH_FAKE_OUT", "```markdown\n## Goal\nx\n```")
    assert compact.summarize("claude", "## User 1\n\nq\n") == "## Goal\nx"


def test_failures_never_yield_a_summary(fake_cli, monkeypatch, tmp_path):
    monkeypatch.setenv("MH_FAKE_FAIL", "1")
    with pytest.raises(MhError, match=r"claude -p failed \(exit 3\): boom: not logged in"):
        compact.summarize("claude", "## User 1\n\nq\n")
    monkeypatch.delenv("MH_FAKE_FAIL")
    monkeypatch.setenv("MH_FAKE_EMPTY", "1")
    with pytest.raises(MhError, match="empty summary"):
        compact.summarize("pi", "## User 1\n\nq\n")
    with pytest.raises(MhError, match="codex"):
        compact.summarize("codex", "## User 1\n\nq\n")
    empty = tmp_path / "nothing"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(MhError, match="claude is not on PATH"):
        compact.summarize("claude", "## User 1\n\nq\n")


# --- the panel's route --------------------------------------------------------


def _live_session(mh, ws, project):
    mh("checkpoint", "alpha", cwd=project, check=0)
    return write_transcript(
        ws["home"], project, SID, make_records([("q1", "a1"), ("q2", "a2"), ("q3", "")])
    )


def test_live_compact_stores_the_summary_as_the_compacted_save(mh, ws, hub_project, fake_cli):
    _live_session(mh, ws, hub_project)
    hub = _hub(hub_project)
    status, live = server.dispatch(hub, "GET", "/api/live", {}, {}, False)
    assert status == 200 and live["compactor"]["available"] is True
    assert live["compactor"]["agent"] == "claude"

    status, data = server.dispatch(
        hub, "POST", "/api/live/compact", {}, {"focus": "  the tests  "}, False
    )
    assert status == 200
    assert data["agent"] == "claude" and data["checkpoint"] == "alpha"
    assert data["exchanges"] == 2  # the unanswered q3 is dropped, as every save does
    body, path = _only_body(hub_project)
    assert "# Session Context — Compacted" in body and "2 exchanges compacted" in body
    assert "Ship it." in body and "## User 1" not in body
    assert path.name.endswith(f"_{SID[:8]}.md")
    _, _, _, stdin, _ = _call(fake_cli)
    assert "## User 1\n\nq1" in stdin and "q3" not in stdin
    assert stdin.rstrip().endswith("Additional focus: the tests")

    status, live = server.dispatch(hub, "GET", "/api/live", {}, {}, False)
    assert live["saved"] == {
        "checkpoint": "alpha",
        "file": path.name,
        "exchanges": None,
        "compacted": True,
        "in_sync": False,
    }
    # the journal names the path that wrote it
    _, sessions = server.dispatch(hub, "GET", "/api/map", {"budget": "6000"}, {}, False)
    assert sessions["checkpoints"][0]["sessions"][0]["compacted"] is True


def test_live_compact_refuses_without_a_cli_and_leaves_the_hub_alone(
    mh, ws, hub_project, monkeypatch, tmp_path
):
    _live_session(mh, ws, hub_project)
    empty = tmp_path / "nothing"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    hub = _hub(hub_project)
    _, live = server.dispatch(hub, "GET", "/api/live", {}, {}, False)
    assert live["compactor"] == {
        "agent": "claude",
        "cli": "claude",
        "available": False,
        "reason": "claude is not on PATH",
    }
    with pytest.raises(MhError, match="claude is not on PATH"):
        server.dispatch(hub, "POST", "/api/live/compact", {}, {}, False)
    assert ck.list_checkpoints(hub)[0].sessions == []


def test_live_compact_replaces_an_earlier_dialog_save_and_the_panel_keeps_it(
    mh, ws, hub_project, fake_cli
):
    tr = _live_session(mh, ws, hub_project)
    hub = _hub(hub_project)
    server.dispatch(hub, "POST", "/api/live/save", {}, {}, False)
    body, _ = _only_body(hub_project)
    assert "## User 1" in body
    server.dispatch(hub, "POST", "/api/live/compact", {}, {}, False)
    body, _ = _only_body(hub_project)
    assert "Compacted" in body and "## User 1" not in body
    # the panel's plain save keeps a compacted representation (save.py policy)
    with pytest.raises(MhError, match="compacted save"):
        server.dispatch(hub, "POST", "/api/live/save", {}, {}, False)
    assert len(ck.list_checkpoints(hub)[0].sessions) == 1
    # only an explicit `mh save` brings the dialog back
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    body, _ = _only_body(hub_project)
    assert "## User 1" in body


# --- the CLI ------------------------------------------------------------------


def _env(fake_cli):
    return {"PATH": os.environ["PATH"], "MH_FAKE_LOG": str(fake_cli)}


def test_cli_with_agent_uses_the_cli_that_ran_the_session(mh, ws, hub_project, fake_cli):
    tr = _live_session(mh, ws, hub_project)
    out = mh(
        "save", "--compact", "--with", "agent", "--focus", "the API", "--transcript", tr,
        cwd=hub_project, check=0, env_extra=_env(fake_cli),
    )  # fmt: skip
    assert "-> alpha" in out.stdout
    cli, _argv, _cwd, stdin, _ = _call(fake_cli)
    assert cli == "claude"  # detected from the transcript
    assert stdin.rstrip().endswith("Additional focus: the API")
    body, _ = _only_body(hub_project)
    assert "# Session Context — Compacted" in body and "Ship it." in body
    head = subprocess.run(
        ["git", "-C", str(_hub(hub_project)), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True, env=ws["env"],
    ).stdout.strip()  # fmt: skip
    assert head.endswith("(compact via claude)")


def test_cli_with_pi_overrides_the_detected_agent(mh, ws, hub_project, fake_cli):
    tr = _live_session(mh, ws, hub_project)
    mh(
        "save", "--compact", "--with", "pi", "--transcript", tr,
        cwd=hub_project, check=0, env_extra=_env(fake_cli),
    )  # fmt: skip
    cli, argv, _, _, _ = _call(fake_cli)
    assert cli == "pi" and "--no-session" in argv


def test_cli_rejects_half_asked_combinations(mh, ws, hub_project, fake_cli, tmp_path):
    tr = _live_session(mh, ws, hub_project)
    r = mh("save", "--compact", "--with", "bogus", "--transcript", tr, cwd=hub_project)
    assert r.returncode != 0 and "--with takes one of agent, claude, pi" in r.stderr
    r = mh("save", "--focus", "x", "--transcript", tr, cwd=hub_project)
    assert r.returncode != 0 and "--with and --focus go with --compact" in r.stderr
    f = tmp_path / "s.md"
    f.write_text("summary\n")
    r = mh("save", "--compact", "--with", "agent", "--file", f, "--transcript", tr, cwd=hub_project)
    assert r.returncode != 0 and "two sources" in r.stderr
    r = mh("save", "--compact", "--transcript", tr, cwd=hub_project)
    assert r.returncode != 0 and "--with agent" in r.stderr  # the bare form still refuses
    assert ck.list_checkpoints(_hub(hub_project))[0].sessions == []


def test_cli_surfaces_the_clis_own_failure(mh, ws, hub_project, fake_cli):
    tr = _live_session(mh, ws, hub_project)
    r = mh(
        "save", "--compact", "--with", "agent", "--transcript", tr,
        cwd=hub_project, env_extra={**_env(fake_cli), "MH_FAKE_FAIL": "1"},
    )  # fmt: skip
    assert r.returncode != 0 and "claude -p failed (exit 3): boom: not logged in" in r.stderr
    assert ck.list_checkpoints(_hub(hub_project))[0].sessions == []


def test_live_compact_takes_a_target_like_the_dialog_save(mh, ws, hub_project, fake_cli):
    """The save box names the checkpoint for both ways of saving: "to" on the
    compact route lands the summary there, the same way it does for the dialog."""
    _live_session(mh, ws, hub_project)  # current: alpha
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("goto", "alpha", cwd=hub_project, check=0)
    hub = _hub(hub_project)
    status, data = server.dispatch(hub, "POST", "/api/live/compact", {}, {"to": "beta"}, False)
    assert status == 200 and data["checkpoint"] == "beta"
    _, live = server.dispatch(hub, "GET", "/api/live", {}, {}, False)
    assert live["saved"]["checkpoint"] == "beta" and live["saved"]["compacted"] is True
