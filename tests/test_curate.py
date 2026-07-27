"""Curation: exchange/session/checkpoint surgery, and the round-trip guard that
makes rewriting saved sessions safe."""

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import make_records, write_transcript
from memoryhub import checkpoint as ck
from memoryhub import curate, purify, server

SID = "c1a2b3c4-7777-4777-8777-777777777777"
SID2 = "d2b3c4d5-8888-4888-8888-888888888888"


def _hub(project) -> Path:
    return project / ".memoryhub"


def _only_session(project, slug=None):
    hub = _hub(project)
    c = ck.list_checkpoints(hub)[0] if slug is None else ck.resolve(hub, slug)
    return c, c.sessions[0]


def _seed(mh, ws, project, turns, sid=SID, ckpt="alpha"):
    mh("checkpoint", ckpt, cwd=project, check=0)
    tr = write_transcript(ws["home"], project, sid, make_records(turns))
    mh("save", "--transcript", tr, cwd=project, check=0)
    return _hub(project)


# --- the round-trip guard ----------------------------------------------------


ROUND_TRIP_CASES = {
    "simple": [("hi", "there")],
    "many turns (two-digit indices)": [(f"q{i}", f"a{i}") for i in range(1, 13)],
    "empty answer": [("q", ""), ("q2", "a2")],
    "horizontal rule in content": [("before\n\n---\n\nafter", "ok"), ("x", "y")],
    "fenced block quoting a heading": [("```\n## User 1\nfake\n```\nreal", "ok"), ("x", "y")],
    "heading quoted out of sequence": [("see\n\n## User 9\n\nquoted", "ok"), ("x", "y")],
    "unicode and markdown": [("**bold** 中文 — em", "- a\n- b\n\n### h3")],
}


@pytest.mark.parametrize("name", list(ROUND_TRIP_CASES))
def test_parse_round_trips_and_preserves_turns(name):
    turns = ROUND_TRIP_CASES[name]
    text = purify.render(turns, "s.jsonl", "sid-1")
    parsed = curate.parse(text)
    assert parsed is not None
    assert parsed.round_trip, f"{name} should round-trip"
    assert parsed.turns == turns, f"{name} lost content"


def test_content_quoting_the_next_heading_is_refused_not_corrupted():
    """The one shape the parser cannot resolve must go read-only, never silently
    mangle the file."""
    turns = [("a", "b\n\n## User 2\n\nnasty"), ("x", "y")]
    parsed = curate.parse(purify.render(turns, "s.jsonl", None))
    assert parsed is not None
    assert not parsed.editable  # refused, so no mutation can reach it
    assert parsed.turns != turns  # it did mis-split — which is exactly why it is refused


def test_legacy_qa_sessions_parse_and_round_trip():
    turns = [("old q", "old a"), ("second", "answer")]
    legacy = curate._render_qa(turns, "s.jsonl", "sid-1")
    parsed = curate.parse(legacy)
    assert parsed is not None and parsed.legacy and parsed.round_trip
    assert parsed.turns == turns
    # migrate=True re-renders in the current format
    assert "## User 1" in curate.render(parsed)


def test_non_mh_markdown_is_not_parsed():
    assert curate.parse("# Some other doc\n\nhello\n") is None


# --- exchange surgery --------------------------------------------------------


def test_delete_exchange_renumbers_and_updates_the_count(mh, ws, hub_project):
    # distinctive content: short tokens like "a2" also occur inside session uuids
    turns = [("first-q", "first-a"), ("second-q", "second-a"), ("third-q", "third-a")]
    hub = _seed(mh, ws, hub_project, turns)
    c, path = _only_session(hub_project)
    curate.delete_exchange(hub, c.slug, path.name, 2)
    body = path.read_text()
    assert "second-q" not in body and "second-a" not in body
    assert "3 exchanges" not in body and "2 exchanges" in body
    assert "## User 1" in body and "## User 2" in body and "## User 3" not in body
    reparsed = curate.parse(body)
    assert reparsed.turns == [("first-q", "first-a"), ("third-q", "third-a")]
    assert reparsed.round_trip


def test_delete_exchange_commits_to_the_hub_journal(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    c, path = _only_session(hub_project)
    curate.delete_exchange(hub, c.slug, path.name, 1)
    log = mh("log", cwd=hub_project, check=0).stdout
    assert "curate: drop exchange 1" in log


def test_deleting_the_only_exchange_is_refused(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("only", "one")])
    c, path = _only_session(hub_project)
    before = path.read_text()
    with pytest.raises(Exception) as e:
        curate.delete_exchange(hub, c.slug, path.name, 1)
    assert "delete the session instead" in str(e.value)
    assert path.read_text() == before


def test_edit_exchange_rewrites_only_that_turn(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    c, path = _only_session(hub_project)
    curate.edit_exchange(hub, c.slug, path.name, 2, agent="condensed answer")
    parsed = curate.parse(path.read_text())
    assert parsed.turns == [("q1", "a1"), ("q2", "condensed answer")]
    assert parsed.round_trip


def test_edit_cannot_empty_the_user_side(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q1", "a1")])
    c, path = _only_session(hub_project)
    with pytest.raises(Exception) as e:
        curate.edit_exchange(hub, c.slug, path.name, 1, user="   ")
    assert "cannot be empty" in str(e.value)


def test_editing_a_legacy_session_migrates_it(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    c, path = _only_session(hub_project)
    # rewrite the file in the old Q&A shape, as a pre-User/Agent hub would hold it
    parsed = curate.parse(path.read_text())
    path.write_text(curate._render_qa(parsed.turns, parsed.source, parsed.session_id))
    assert "## Q1" in path.read_text()
    curate.edit_exchange(hub, c.slug, path.name, 1, user="updated")
    body = path.read_text()
    assert "## Q1" not in body and "## User 1" in body
    assert curate.parse(body).turns == [("updated", "a1"), ("q2", "a2")]


# --- session surgery ---------------------------------------------------------


def test_delete_session(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    c, path = _only_session(hub_project)
    curate.delete_session(hub, c.slug, path.name)
    assert not path.exists()
    assert ck.resolve(hub, c.slug).sessions == []


def test_move_session_between_checkpoints(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    c, path = _only_session(hub_project, "alpha")
    curate.move_session(hub, "alpha", path.name, "beta")
    assert ck.resolve(hub, "alpha").sessions == []
    assert [p.name for p in ck.resolve(hub, "beta").sessions] == [path.name]


def test_move_refuses_the_same_filename(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("save", "--to", "beta", "--session-id", SID, cwd=hub_project, check=0)
    c, path = _only_session(hub_project, "alpha")
    with pytest.raises(Exception) as e:
        curate.move_session(hub, "alpha", path.name, "beta")
    assert "already holds" in str(e.value)
    assert path.exists()


def test_move_refuses_the_same_session_under_a_different_timestamp(mh, ws, hub_project):
    """One file per session key per checkpoint — a re-stamped copy would
    silently duplicate the session in the loaded pack."""
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("save", "--to", "beta", "--session-id", SID, cwd=hub_project, check=0)
    beta = ck.resolve(hub, "beta").sessions[0]
    beta.rename(beta.with_name("2026-07-11_0900_" + beta.name[16:]))
    c, path = _only_session(hub_project, "alpha")
    with pytest.raises(Exception) as e:
        curate.move_session(hub, "alpha", path.name, "beta")
    assert "already holds this session" in str(e.value)
    assert path.exists()


# --- checkpoint surgery ------------------------------------------------------


def test_rename_keeps_created_stamp_and_fixes_links_and_current(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    mh("goto", "alpha", cwd=hub_project, check=0)
    before = ck.resolve(hub, "alpha").created
    curate.rename_checkpoint(hub, "alpha", "renamed one")
    c = ck.resolve(hub, "renamed-one")
    assert c.created == before  # walk order preserved
    assert c.sessions and (hub / "current").read_text().strip() == "renamed-one"
    assert ck.read_links(hub) == [("beta", "renamed-one")]


def test_rename_onto_an_existing_slug_is_refused(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    with pytest.raises(Exception) as e:
        curate.rename_checkpoint(hub, "alpha", "beta")
    assert "already exists" in str(e.value)


def test_delete_checkpoint_drops_links_and_moves_current(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    mh("goto", "beta", cwd=hub_project, check=0)
    curate.delete_checkpoint(hub, "beta")
    assert [c.slug for c in ck.list_checkpoints(hub)] == ["alpha"]
    assert ck.read_links(hub) == []
    assert (hub / "current").read_text().strip() == "alpha"


def test_a_hub_that_cannot_commit_is_refused_before_anything_is_written(
    mh, ws, hub_project, monkeypatch
):
    """Regression: curation writes then commits. If the commit fails the change
    is already on disk but absent from the journal, so the check must run
    first — the error must mean 'nothing happened'."""
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    c, path = _only_session(hub_project)
    before = path.read_text()
    from memoryhub import git as gitmod

    # no config anywhere, and no guessing from gecos/hostname either
    gitmod.run(hub, "config", "user.useConfigOnly", "true")
    gitmod.run(hub, "config", "--unset-all", "user.email", check=False)
    gitmod.run(hub, "config", "--unset-all", "user.name", check=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(Exception) as e:
        curate.delete_exchange(hub, c.slug, path.name, 1)
    assert "cannot commit" in str(e.value)
    assert path.read_text() == before  # untouched, not written-then-orphaned
    assert not gitmod.run(hub, "status", "--porcelain").strip()


def test_curation_survives_as_git_history(mh, ws, hub_project):
    """Every mutation is a commit, so the hub is the undo path."""
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    c, path = _only_session(hub_project)
    curate.delete_exchange(hub, c.slug, path.name, 1)
    assert "q1" not in path.read_text()
    from memoryhub import git as gitmod

    gitmod.run(hub, "revert", "--no-edit", "HEAD")
    assert "q1" in path.read_text()


# --- the HTTP layer ----------------------------------------------------------


def test_dispatch_map_and_session(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    status, data = server.dispatch(hub, "GET", "/api/map", {"budget": "6000"}, {}, False)
    assert status == 200
    assert [c["slug"] for c in data["checkpoints"]] == ["alpha"]
    assert data["current"] == "alpha"
    row = data["checkpoints"][0]["sessions"][0]
    assert row["exchanges"] == 2 and row["editable"] is True and row["tokens"] > 0

    status, data = server.dispatch(
        hub, "GET", "/api/session", {"ckpt": "alpha", "file": row["file"]}, {}, False
    )
    assert status == 200 and len(data["exchanges"]) == 2
    assert data["exchanges"][0]["user"] == "q1"


def test_dispatch_rejects_writes_when_read_only(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    c, path = _only_session(hub_project)
    status, data = server.dispatch(
        hub, "POST", "/api/exchange/delete",
        {}, {"ckpt": "alpha", "file": path.name, "index": 1}, True,
    )
    assert status == 403 and "read-only" in data["error"]
    assert "q1" in path.read_text()


def test_dispatch_unknown_route(mh, ws, hub_project):
    hub = _seed(mh, ws, hub_project, [("q", "a")])
    assert server.dispatch(hub, "GET", "/api/nope", {}, {}, False)[0] == 404


@pytest.fixture()
def live(mh, ws, hub_project):
    """The real server on a real socket, torn down after the test."""
    hub = _seed(mh, ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    from http.server import ThreadingHTTPServer

    token = "test-token-value"
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(hub, token, False))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield {"base": base, "token": token, "hub": hub, "project": hub_project}
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def _get(url, token=None, host=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("X-Mh-Token", token)
    if host:
        req.add_header("Host", host)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read() or b"{}")


def test_live_server_serves_the_page_and_the_api(live):
    req = urllib.request.Request(f"{live['base']}/?t={live['token']}")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200 and b"checkpoint map" in r.read()
    status, data = _get(f"{live['base']}/api/map", live["token"])
    assert status == 200 and data["current"] == "alpha"


def test_live_server_rejects_a_missing_or_wrong_token(live):
    for token in (None, "wrong-token"):
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(f"{live['base']}/api/map", token)
        assert e.value.code == 403


def test_live_server_rejects_a_foreign_host_header(live):
    """Blocks DNS rebinding: a hostile name resolving to 127.0.0.1."""
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(f"{live['base']}/api/map", live["token"], host="evil.example.com")
    assert e.value.code == 403


def test_live_server_edits_through_the_api(live):
    _, data = _get(f"{live['base']}/api/map", live["token"])
    file = data["checkpoints"][0]["sessions"][0]["file"]
    body = json.dumps({"ckpt": "alpha", "file": file, "index": 1}).encode()
    req = urllib.request.Request(
        f"{live['base']}/api/exchange/delete", data=body, method="POST"
    )
    req.add_header("X-Mh-Token", live["token"])
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert json.loads(r.read())["exchanges"] == 1
    path = ck.resolve(live["hub"], "alpha").sessions[0]
    assert "q1" not in path.read_text() and "q2" in path.read_text()


def test_live_server_reports_errors_as_json(live):
    body = json.dumps({"ckpt": "alpha", "file": "nope.md", "index": 1}).encode()
    req = urllib.request.Request(
        f"{live['base']}/api/exchange/delete", data=body, method="POST"
    )
    req.add_header("X-Mh-Token", live["token"])
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 400
    assert "no session" in json.loads(e.value.read())["error"]
