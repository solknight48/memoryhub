"""CLI curation: `mh rm / mv / rename / edit` — the map's surgery, reachable
from a terminal (an agent cannot click a browser)."""

from conftest import make_records, write_transcript
from memoryhub import checkpoint as ck

SID = "e1f2a3b4-6666-4666-8666-666666666666"


def _hub(project):
    return project / ".memoryhub"


def _seed(mh, ws, project, turns, ckpt="alpha"):
    mh("checkpoint", ckpt, cwd=project, check=0)
    tr = write_transcript(ws["home"], project, SID, make_records(turns))
    mh("save", "--transcript", tr, cwd=project, check=0)
    return ck.resolve(_hub(project), ckpt).sessions[0]


def test_rm_exchange(mh, ws, hub_project):
    path = _seed(mh, ws, hub_project, [("first-q", "first-a"), ("second-q", "second-a")])
    p = mh("rm", f"alpha/{path.name}", "-x", "1", cwd=hub_project, check=0)
    assert "deleted exchange 1" in p.stdout and "1 left" in p.stdout
    assert "undo: git -C" in p.stdout
    body = path.read_text()
    assert "first-q" not in body and "second-q" in body


def test_rm_session_by_prefix(mh, ws, hub_project):
    path = _seed(mh, ws, hub_project, [("q", "a")])
    p = mh("rm", "alpha/2026-07-10", cwd=hub_project, check=0)
    assert f"deleted session {path.name} from alpha" in p.stdout
    assert not path.exists()


def test_rm_checkpoint_requires_force_when_it_holds_sessions(mh, ws, hub_project):
    _seed(mh, ws, hub_project, [("q", "a")])
    p = mh("rm", "alpha", cwd=hub_project)
    assert p.returncode == 1
    assert "--force" in p.stderr
    assert ck.list_checkpoints(_hub(hub_project))  # still there

    p = mh("rm", "alpha", "--force", cwd=hub_project, check=0)
    assert "deleted checkpoint alpha (1 sessions)" in p.stdout
    assert ck.list_checkpoints(_hub(hub_project)) == []


def test_rm_empty_checkpoint_needs_no_force(mh, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    mh("rm", "alpha", cwd=hub_project, check=0)
    assert ck.list_checkpoints(_hub(hub_project)) == []


def test_rm_exchange_needs_a_session(mh, ws, hub_project):
    _seed(mh, ws, hub_project, [("q", "a")])
    p = mh("rm", "alpha", "-x", "1", cwd=hub_project)
    assert p.returncode == 1
    assert "-x needs a session" in p.stderr


def test_mv_session(mh, ws, hub_project):
    path = _seed(mh, ws, hub_project, [("q", "a")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    p = mh("mv", f"alpha/{path.name}", "beta", cwd=hub_project, check=0)
    assert "moved" in p.stdout and "alpha -> beta" in p.stdout
    hub = _hub(hub_project)
    assert ck.resolve(hub, "alpha").sessions == []
    assert [s.name for s in ck.resolve(hub, "beta").sessions] == [path.name]


def test_mv_needs_a_session_ref(mh, ws, hub_project):
    _seed(mh, ws, hub_project, [("q", "a")])
    p = mh("mv", "alpha", "beta", cwd=hub_project)
    assert p.returncode == 1
    assert "mv moves sessions" in p.stderr


def test_rename_checkpoint(mh, ws, hub_project):
    _seed(mh, ws, hub_project, [("q", "a")])
    p = mh("rename", "alpha", "data pipeline", cwd=hub_project, check=0)
    assert "renamed alpha -> data-pipeline" in p.stdout
    assert ck.resolve(_hub(hub_project), "data-pipeline").sessions


def test_edit_exchange_inline(mh, ws, hub_project):
    path = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    p = mh("edit", f"alpha/{path.name}", "-x", "2", "--agent", "shorter", cwd=hub_project, check=0)
    assert "rewrote exchange 2" in p.stdout
    body = path.read_text()
    assert "shorter" in body and "a2" not in body and "a1" in body


def test_edit_exchange_from_files(mh, ws, hub_project, tmp_path):
    path = _seed(mh, ws, hub_project, [("q1", "a1")])
    agent_md = tmp_path / "agent.md"
    agent_md.write_text("multi\nline answer\n")
    mh("edit", f"alpha/{path.name}", "-x", "1", "--agent-file", agent_md, cwd=hub_project, check=0)
    assert "multi\nline answer" in path.read_text()


def test_edit_rejects_conflicting_and_missing_input(mh, ws, hub_project, tmp_path):
    path = _seed(mh, ws, hub_project, [("q1", "a1")])
    f = tmp_path / "x.md"
    f.write_text("x")
    p = mh(
        "edit", f"alpha/{path.name}", "-x", "1", "--agent", "a", "--agent-file", f, cwd=hub_project
    )
    assert p.returncode == 1 and "not both" in p.stderr
    p = mh("edit", f"alpha/{path.name}", "-x", "1", cwd=hub_project)
    assert p.returncode == 1 and "nothing to change" in p.stderr


def test_curation_commands_commit_to_the_journal(mh, ws, hub_project):
    path = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("edit", f"alpha/{path.name}", "-x", "1", "--user", "reworded", cwd=hub_project, check=0)
    mh("mv", f"alpha/{path.name}", "beta", cwd=hub_project, check=0)
    mh("rename", "beta", "gamma", cwd=hub_project, check=0)
    mh("rm", f"gamma/{path.name}", cwd=hub_project, check=0)
    log = mh("log", cwd=hub_project, check=0).stdout
    for needle in (
        "curate: rewrite exchange 1",
        "curate: move",
        "curate: rename checkpoint beta -> gamma",
        "curate: delete session",
    ):
        assert needle in log


def test_search_groups_hits_with_line_numbers(mh, ws, hub_project):
    _seed(mh, ws, hub_project, [("needle in q", "needle in a")])
    p = mh("search", "needle", cwd=hub_project, check=0)
    lines = p.stdout.splitlines()
    assert lines[0].startswith("alpha/2026-07-10")
    assert lines[1].lstrip()[0].isdigit()  # "  <line>: text"
    assert "2 hits in 1 session" in p.stdout
    assert "mh show" in p.stdout


def test_search_reports_no_matches(mh, ws, hub_project):
    _seed(mh, ws, hub_project, [("q", "a")])
    p = mh("search", "zzz-not-there", cwd=hub_project, check=0)
    assert "no matches" in p.stdout
