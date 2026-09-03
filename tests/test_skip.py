"""Skipping a session on load: it stays in its checkpoint, `mh load` leaves it
out, the map shows it dimmed, and the skip follows the session through a
rename or a move and leaves with a delete. One list (`skip.toml`), one filter
(`load.build`), so the CLI, the hook and the map cannot disagree.
"""

import json

from conftest import make_records, write_transcript
from memoryhub import server

SID_A = "aaaa1111-0000-4000-8000-00000000000a"
SID_B = "bbbb2222-0000-4000-8000-00000000000b"


def _two_sessions(mh, ws, project) -> list[str]:
    mh("checkpoint", "alpha", cwd=project, check=0)
    for sid, q, start in (
        (SID_A, "q-one", "2026-07-10T04:00:00Z"),
        (SID_B, "q-two", "2026-07-12T04:00:00Z"),
    ):
        tr = write_transcript(ws["home"], project, sid, make_records([(q, "a-" + q)], start=start))
        mh("save", "--transcript", tr, cwd=project, check=0)
    shown = json.loads(mh("show", "alpha", "--json", cwd=project, check=0).stdout)
    return [s["file"] for s in shown["sessions"]]


def test_a_skipped_session_leaves_the_pack_and_comes_back(mh, ws, hub_project):
    first, second = _two_sessions(mh, ws, hub_project)

    p = mh("skip", f"alpha/{first}", cwd=hub_project, check=0)
    assert "mh load leaves it out" in p.stdout
    assert (
        hub_project / ".memoryhub" / "skip.toml"
    ).read_text() == f'skip = [\n  "alpha/{first}",\n]\n'

    out = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert "q-two" in out and "q-one" not in out
    assert "1 of 1 sessions" in out
    assert f"skipped 1 session(s) on request: alpha/{first}" in out
    data = json.loads(mh("load", "--all", "--json", cwd=hub_project, check=0).stdout)
    assert data["skipped"] == [f"alpha/{first}"]
    assert [s["file"] for s in data["sessions"]] == [second]

    # the file is still there for anyone who asks for it by name
    assert "q-one" in mh("show", f"alpha/{first}", cwd=hub_project, check=0).stdout
    assert "skipped on load: 1" in mh("status", cwd=hub_project, check=0).stdout

    assert "already skipped" in mh("skip", f"alpha/{first}", cwd=hub_project, check=0).stdout
    assert "loads again" in mh("unskip", f"alpha/{first}", cwd=hub_project, check=0).stdout
    out = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert "q-one" in out and "skipped" not in out
    assert "not skipped" in mh("unskip", f"alpha/{first}", cwd=hub_project, check=0).stdout
    assert "skipped on load" not in mh("status", cwd=hub_project, check=0).stdout


def test_a_skip_needs_a_session_not_a_checkpoint(mh, ws, hub_project):
    _two_sessions(mh, ws, hub_project)
    p = mh("skip", "alpha", cwd=hub_project)
    assert p.returncode == 1 and "mh skip <checkpoint>/<session>" in p.stderr


def test_the_skip_follows_rename_and_move_and_leaves_with_delete(mh, ws, hub_project):
    first, _second = _two_sessions(mh, ws, hub_project)
    mh("skip", f"alpha/{first}", cwd=hub_project, check=0)

    mh("rename", "alpha", "alpha-two", cwd=hub_project, check=0)
    skips = (hub_project / ".memoryhub" / "skip.toml").read_text()
    assert f'"alpha-two/{first}"' in skips and '"alpha/' not in skips
    assert "q-one" not in mh("load", "--all", cwd=hub_project, check=0).stdout

    mh("checkpoint", "beta", cwd=hub_project, check=0)  # current is now beta
    mh("mv", f"alpha-two/{first}", "beta", cwd=hub_project, check=0)
    skips = (hub_project / ".memoryhub" / "skip.toml").read_text()
    assert f'"beta/{first}"' in skips and "alpha-two" not in skips
    out = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert "loaded: beta |" in out and "q-one" not in out

    mh("rm", f"beta/{first}", cwd=hub_project, check=0)
    assert (hub_project / ".memoryhub" / "skip.toml").read_text() == "skip = []\n"
    assert json.loads(mh("status", "--json", cwd=hub_project, check=0).stdout)["skipped"] == 0


def test_deleting_the_checkpoint_drops_its_skips(mh, ws, hub_project):
    first, _second = _two_sessions(mh, ws, hub_project)
    mh("skip", f"alpha/{first}", cwd=hub_project, check=0)
    mh("rm", "alpha", "--force", cwd=hub_project, check=0)
    assert (hub_project / ".memoryhub" / "skip.toml").read_text() == "skip = []\n"


def test_the_map_shows_and_toggles_the_skip(mh, ws, hub_project):
    first, second = _two_sessions(mh, ws, hub_project)
    hub = hub_project / ".memoryhub"

    status, data = server.dispatch(
        hub,
        "POST",
        "/api/session/skip",
        {},
        {"ckpt": "alpha", "file": first, "skipped": True},
        False,
    )
    assert status == 200 and data["skipped"] is True

    status, data = server.dispatch(hub, "GET", "/api/map", {"budget": "none"}, {}, False)
    rows = {r["file"]: r for r in data["checkpoints"][0]["sessions"]}
    assert rows[first]["skipped"] is True and rows[second]["skipped"] is False
    assert data["load"]["included"] == [f"alpha/{second}"]
    assert data["load"]["skipped"] == [f"alpha/{first}"]

    status, data = server.dispatch(
        hub,
        "POST",
        "/api/session/skip",
        {},
        {"ckpt": "alpha", "file": first, "skipped": False},
        False,
    )
    assert status == 200 and data["skipped"] is False
    status, data = server.dispatch(hub, "GET", "/api/map", {"budget": "none"}, {}, False)
    assert [r["skipped"] for r in data["checkpoints"][0]["sessions"]] == [False, False]
    assert data["load"]["skipped"] == []

    # --read-only serves the flag but refuses to change it
    status, _ = server.dispatch(
        hub, "POST", "/api/session/skip", {}, {"ckpt": "alpha", "file": first}, True
    )
    assert status == 403


def test_the_hook_pack_respects_the_skip(mh, ws, hub_project):
    first, _second = _two_sessions(mh, ws, hub_project)
    mh("skip", f"alpha/{first}", cwd=hub_project, check=0)
    payload = json.dumps({"cwd": str(hub_project), "source": "startup"})
    out = mh("hook", "load", cwd=hub_project, check=0, input=payload).stdout
    assert "q-two" in out and "q-one" not in out
