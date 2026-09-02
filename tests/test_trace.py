"""Tracing a saved session back to its original transcript.

The link is the session id in the purified file — machine-independent, nothing
stored in the hub — resolved against the transcripts present now. So the same
save is traceable where its transcript still lives and honestly untraceable
where it does not.
"""

from __future__ import annotations

import json

from conftest import make_records, write_transcript
from memoryhub import checkpoint as ck
from memoryhub import live as livemod
from memoryhub import server

SID = "abcd1234-7777-4777-8777-777777777777"


def hub_of(project):
    return project / ".memoryhub"


def _trace(mh, project, session, *args):
    return mh("trace", f"alpha/{session.name}", *args, cwd=project, check=0).stdout


def _saved(mh, ws, project):
    mh("checkpoint", "alpha", cwd=project, check=0)
    livemod._discovery.clear()
    tr = write_transcript(ws["home"], project, SID, make_records([("q", "a")], cwd=str(project)))
    mh("save", "--transcript", tr, cwd=project, check=0)
    return ck.resolve(hub_of(project), "alpha").sessions[0], tr


def test_find_resolves_the_id_to_the_transcript_on_disk(mh, ws, hub_project):
    _saved(mh, ws, hub_project)
    livemod._discovery.clear()
    hit = livemod.find(hub_of(hub_project), SID)
    assert hit is not None and hit.sid == SID and hit.agent == "claude"
    assert livemod.find(hub_of(hub_project), "0000-gone") is None
    assert livemod.find(hub_of(hub_project), "") is None


def test_trace_prints_the_path_when_the_transcript_is_here(mh, ws, hub_project):
    session, tr = _saved(mh, ws, hub_project)
    out = mh("trace", f"alpha/{session.name}", cwd=hub_project, check=0).stdout
    assert SID in out and str(tr) in out and "claude:" in out
    data = json.loads(
        mh("trace", f"alpha/{session.name}", "--json", cwd=hub_project, check=0).stdout
    )
    assert data["on_this_machine"] is True
    assert data["session_id"] == SID and data["path"] == str(tr) and data["agent"] == "claude"


def test_trace_says_so_when_the_transcript_is_gone(mh, ws, hub_project):
    session, tr = _saved(mh, ws, hub_project)
    tr.unlink()  # the transcript is deleted; the save keeps the id
    livemod._discovery.clear()
    out = mh("trace", f"alpha/{session.name}", cwd=hub_project, check=0).stdout
    assert "not on this machine" in out
    data = json.loads(
        mh("trace", f"alpha/{session.name}", "--json", cwd=hub_project, check=0).stdout
    )
    assert data["on_this_machine"] is False and data["path"] is None
    assert data["session_id"] == SID  # the link survives the transcript


def test_the_session_payload_offers_the_original(mh, ws, hub_project):
    session, _ = _saved(mh, ws, hub_project)
    livemod._discovery.clear()
    status, data = server.dispatch(
        hub_of(hub_project),
        "GET",
        "/api/session",
        {"ckpt": "alpha", "file": session.name},
        {},
        False,
    )
    assert status == 200
    assert data["session_id"] == SID
    assert data["original"] == {"key": SID.split("-")[0][:8], "agent": "claude"}
