"""`mh hook`: the Claude Code hook loop — load injected at SessionStart, saves
at SessionEnd/PreCompact, and settings.json wiring that only ever touches mh's
own entries."""

import json

from conftest import make_records, write_transcript
from memoryhub import checkpoint as ck

SID = "abcd1234-9999-4999-8999-999999999999"


def _payload(project, tr=None, **extra):
    p = {"cwd": str(project), "hook_event_name": "SessionEnd"}
    if tr is not None:
        p["transcript_path"] = str(tr)
    p.update(extra)
    return json.dumps(p)


def _sessions(project):
    hub = project / ".memoryhub"
    return [p.name for c in ck.list_checkpoints(hub) for p in c.sessions]


# --- mh hook save ------------------------------------------------------------


def test_hook_save_saves_the_session(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")]))
    p = mh("hook", "save", cwd=hub_project, input=_payload(hub_project, tr), check=0)
    assert "saved" in p.stdout and "-> alpha" in p.stdout
    assert _sessions(hub_project) == ["2026-07-10_0401_abcd1234.md"]


def test_hook_save_without_a_hub_is_silent(mh, ws, project):
    p = mh("hook", "save", cwd=project, input=_payload(project), check=0)
    assert p.stdout == "" and p.stderr == ""


def test_hook_save_without_a_current_checkpoint_skips(mh, ws, hub_project):
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")]))
    p = mh("hook", "save", cwd=hub_project, input=_payload(hub_project, tr), check=0)
    assert "no current checkpoint" in p.stderr and "skipped" in p.stderr
    assert _sessions(hub_project) == []


def test_hook_save_with_no_dialog_skips(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, [])
    p = mh("hook", "save", cwd=hub_project, input=_payload(hub_project, tr), check=0)
    assert "skipped" in p.stderr
    assert _sessions(hub_project) == []


def test_hook_save_uses_the_payload_cwd_not_the_process_cwd(mh, ws, hub_project):
    """Hook JSON carries the session's cwd; the hub is discovered from it even
    if the hook process happens to run elsewhere."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")]))
    elsewhere = ws["root"]
    mh("hook", "save", cwd=elsewhere, input=_payload(hub_project, tr), check=0)
    assert _sessions(hub_project) == ["2026-07-10_0401_abcd1234.md"]


def test_hook_save_keeps_a_compacted_save_of_the_same_session(mh, ws, hub_project, tmp_path):
    """A deliberate --compact save must survive session end — the mechanical
    hook never downgrades the user's chosen representation."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")]))
    summary = tmp_path / "sum.md"
    summary.write_text("what happened, condensed\n")
    mh("save", "--compact", "--file", summary, "--transcript", tr, cwd=hub_project, check=0)
    p = mh("hook", "save", cwd=hub_project, input=_payload(hub_project, tr), check=0)
    assert "compacted save — kept as is" in p.stderr
    assert len(_sessions(hub_project)) == 1
    hub = hub_project / ".memoryhub"
    body = (ck.resolve(hub, "alpha").sessions[0]).read_text()
    assert "Compacted" in body and "condensed" in body


def test_hook_save_updates_the_checkpoint_the_session_was_routed_to(mh, ws, hub_project):
    """`mh save --to beta` mid-session routes the session; the hook must update
    it there, not duplicate it into the current checkpoint."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("goto", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")]))
    mh("save", "--to", "beta", "--transcript", tr, cwd=hub_project, check=0)
    tr = write_transcript(
        ws["home"], hub_project, SID, make_records([("q", "a"), ("more", "later")])
    )
    p = mh("hook", "save", cwd=hub_project, input=_payload(hub_project, tr), check=0)
    assert "-> beta" in p.stdout
    hub = hub_project / ".memoryhub"
    assert ck.resolve(hub, "alpha").sessions == []
    (saved,) = ck.resolve(hub, "beta").sessions
    assert "more" in saved.read_text()


# --- mh hook load ------------------------------------------------------------


def test_hook_load_emits_the_pack_on_startup(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("warm-q", "warm-a")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    p = mh(
        "hook",
        "load",
        cwd=hub_project,
        input=json.dumps({"cwd": str(hub_project), "source": "startup"}),
        check=0,
    )
    assert "<!-- mh | loaded: alpha" in p.stdout and "warm-q" in p.stdout


def test_hook_load_skips_resume_and_compact(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    for source in ("resume", "compact"):
        p = mh(
            "hook",
            "load",
            cwd=hub_project,
            input=json.dumps({"cwd": str(hub_project), "source": source}),
            check=0,
        )
        assert p.stdout == ""


def test_hook_load_without_a_hub_is_silent(mh, project):
    p = mh(
        "hook",
        "load",
        cwd=project,
        input=json.dumps({"cwd": str(project), "source": "startup"}),
        check=0,
    )
    assert p.stdout == "" and p.stderr == ""


def test_hook_load_without_a_current_checkpoint_skips_quietly(mh, hub_project):
    p = mh(
        "hook",
        "load",
        cwd=hub_project,
        input=json.dumps({"cwd": str(hub_project), "source": "startup"}),
        check=0,
    )
    assert p.stdout == ""
    assert "skipped" in p.stderr


# --- mh hook install ---------------------------------------------------------


def _settings(project):
    return project / ".claude" / "settings.local.json"


def test_hook_install_writes_project_local_settings(mh, hub_project):
    p = mh("hook", "install", cwd=hub_project, check=0)
    assert "installed mh hooks" in p.stdout
    data = json.loads(_settings(hub_project).read_text())
    events = data["hooks"]
    assert set(events) == {"SessionStart", "SessionEnd", "PreCompact"}
    assert events["SessionStart"][0]["hooks"][0]["command"] == "mh hook load"
    assert events["SessionEnd"][0]["hooks"][0]["command"] == "mh hook save"
    assert events["PreCompact"][0]["hooks"][0]["command"] == "mh hook save"


def test_hook_install_is_idempotent(mh, hub_project):
    mh("hook", "install", cwd=hub_project, check=0)
    p = mh("hook", "install", cwd=hub_project, check=0)
    assert "already present" in p.stdout
    data = json.loads(_settings(hub_project).read_text())
    assert len(data["hooks"]["SessionEnd"]) == 1


def test_hook_install_merges_with_existing_settings(mh, hub_project):
    s = _settings(hub_project)
    s.parent.mkdir(parents=True)
    s.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls:*)"]},
                "hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "echo bye"}]}]},
            }
        )
    )
    mh("hook", "install", cwd=hub_project, check=0)
    data = json.loads(s.read_text())
    assert data["permissions"] == {"allow": ["Bash(ls:*)"]}  # untouched
    cmds = [h["command"] for e in data["hooks"]["SessionEnd"] for h in e["hooks"]]
    assert cmds == ["echo bye", "mh hook save"]


def test_hook_install_remove_only_strips_mh_entries(mh, hub_project):
    s = _settings(hub_project)
    s.parent.mkdir(parents=True)
    s.write_text(
        json.dumps(
            {
                "hooks": {"SessionEnd": [{"hooks": [{"type": "command", "command": "echo bye"}]}]},
            }
        )
    )
    mh("hook", "install", cwd=hub_project, check=0)
    p = mh("hook", "install", "--remove", cwd=hub_project, check=0)
    assert "removed mh hooks" in p.stdout
    data = json.loads(s.read_text())
    cmds = [h["command"] for e in data["hooks"].get("SessionEnd", []) for h in e["hooks"]]
    assert cmds == ["echo bye"]
    assert "SessionStart" not in data["hooks"]

    p = mh("hook", "install", "--remove", cwd=hub_project, check=0)
    assert "nothing to do" in p.stdout


def test_hook_install_user_targets_home_settings(mh, ws, hub_project):
    mh("hook", "install", "--user", cwd=hub_project, check=0)
    data = json.loads((ws["home"] / ".claude" / "settings.json").read_text())
    assert "SessionStart" in data["hooks"]
    assert not _settings(hub_project).exists()


def test_hook_install_refuses_broken_settings(mh, hub_project):
    s = _settings(hub_project)
    s.parent.mkdir(parents=True)
    s.write_text("{not json")
    p = mh("hook", "install", cwd=hub_project)
    assert p.returncode == 1
    assert "not valid JSON" in p.stderr
    assert s.read_text() == "{not json"  # untouched
