"""Which model wrote each answer: transcript -> heading -> API -> badge.

The model rides beside the turns rather than inside them, so the whole chain has
two things to prove — that a session naming a model carries it end to end, and
that one naming none is byte-for-byte what mh has always written.
"""

from __future__ import annotations

import json

import pytest

from conftest import (
    make_pi_records,
    make_records,
    needs_node,
    run_ui_js,
    write_codex_rollout,
    write_pi_transcript,
    write_transcript,
)
from memoryhub import agents, curate, purify, server
from memoryhub import checkpoint as ck

SID = "e5f6a7b8-5555-4555-8555-555555555555"
PI_SID = "019f74da-9631-7c10-9d05-d50425ec4002"
CX_SID = "019dee2a-7fd6-77e0-a429-ed6600009902"


def _body(project, mh, ws, turns, model=None, sid=SID):
    mh("checkpoint", "alpha", cwd=project, check=0)
    tr = write_transcript(ws["home"], project, sid, make_records(turns, model=model))
    mh("save", "--transcript", tr, cwd=project, check=0)
    ckdir = next(d for d in (project / ".memoryhub" / "checkpoints").iterdir() if d.is_dir())
    return next(ckdir.glob("*.md")).read_text()


# --- extraction --------------------------------------------------------------


def test_the_model_lands_on_the_agent_heading(mh, ws, hub_project):
    body = _body(hub_project, mh, ws, [("q", "a")], model="claude-opus-5")
    assert "## Agent 1 — `claude-opus-5`" in body
    assert "## User 1\n" in body  # the question side stays plain


def test_a_mid_session_model_switch_shows_per_exchange(mh, ws, hub_project):
    body = _body(
        hub_project,
        mh,
        ws,
        [("q1", "a1"), ("q2", "a2")],
        model=["claude-fable-5", "claude-opus-5"],
    )
    assert "## Agent 1 — `claude-fable-5`" in body
    assert "## Agent 2 — `claude-opus-5`" in body


def test_two_models_inside_one_answer_are_both_named(tmp_path):
    """One question, two assistant records, different models — both contributed
    visible text, so the exchange is credited to both."""
    recs = make_records([("q", "first half")], model="claude-fable-5")
    recs.append(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [{"type": "text", "text": "second half"}],
            },
            "timestamp": "2026-07-10T04:02:00Z",
        }
    )
    tr = tmp_path / "s.jsonl"
    tr.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    turns, _, models = purify.build_turns(tr)
    assert models == ["claude-fable-5, claude-opus-5"]
    assert turns[0][1] == "first half\n\nsecond half"


@pytest.mark.parametrize("bad", ["<synthetic>", "", "not a model id", "has space", None, 5])
def test_placeholders_and_junk_are_not_models(bad):
    """Claude Code writes model "<synthetic>" for replies it generated itself;
    anything that would not survive the heading round-trip is refused too."""
    assert purify.model_of({"model": bad}) == ""


def test_synthetic_answers_carry_no_label(mh, ws, hub_project):
    body = _body(hub_project, mh, ws, [("q", "a")], model="<synthetic>")
    assert "## Agent 1\n" in body
    assert "synthetic" not in body


def test_pi_names_its_model(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    recs = make_pi_records([("q", "a")], cwd=str(hub_project), sid=PI_SID, model="glm-5.3")
    tr = write_pi_transcript(ws["home"], hub_project, PI_SID, recs)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    ckdir = next(d for d in (hub_project / ".memoryhub" / "checkpoints").iterdir() if d.is_dir())
    assert "## Agent 1 — `glm-5.3`" in next(ckdir.glob("*.md")).read_text()


def test_codex_falls_back_to_the_session_model(ws, hub_project):
    """Codex records the model on the session, not per message — unverified
    against a real rollout, so this pins the assumed shape rather than claiming
    it is confirmed."""
    write_codex_rollout(ws["home"], hub_project, CX_SID, [("q", "a")], model="gpt-5-codex")
    tr = next((ws["home"] / ".codex" / "sessions").rglob(f"*{CX_SID}.jsonl"))
    _, _, models = agents.extract(agents.Discovered("codex", tr, CX_SID, "cx-x"))
    assert models == ["gpt-5-codex"]


def test_codex_without_a_model_labels_nothing(ws, hub_project):
    write_codex_rollout(ws["home"], hub_project, CX_SID, [("q", "a")])
    tr = next((ws["home"] / ".codex" / "sessions").rglob(f"*{CX_SID}.jsonl"))
    _, _, models = agents.extract(agents.Discovered("codex", tr, CX_SID, "cx-x"))
    assert models == [""]


# --- rendering ---------------------------------------------------------------


NO_MODEL_GOLDEN = """# Session Context

_Pure dialog extracted from `s.jsonl` (session `sid-1`). 2 exchanges. Tool \
calls, results, and internal reasoning removed._

## User 1

hi

## Agent 1

there

---

## User 2

again

## Agent 2

sure
"""


@pytest.mark.parametrize("models", [None, [], ["", ""]])
def test_a_session_with_no_models_renders_exactly_as_before(models):
    """The pin that keeps the parity test meaningful: with no model to name,
    render() must produce the document mh has always produced. (The parity test
    itself only runs where the original purify.py is installed.)"""
    turns = [("hi", "there"), ("again", "sure")]
    assert purify.render(turns, "s.jsonl", "sid-1", models) == NO_MODEL_GOLDEN


def test_an_unanswered_trailing_turn_drops_its_model_too():
    turns, models = purify.drop_trailing_unanswered(
        [("q1", "a1"), ("q2", "")], ["claude-opus-5", "claude-fable-5"]
    )
    assert turns == [("q1", "a1")] and models == ["claude-opus-5"]


# --- the round-trip guard ----------------------------------------------------


ROUND_TRIP_MODELS = {
    "one model": ["claude-opus-5"],
    "a switch": ["claude-fable-5", "claude-opus-5"],
    "only the second is known": ["", "glm-5.3"],
    "none at all": ["", ""],
    "dotted and dated ids": ["glm-5.3", "claude-sonnet-4-5-20250929"],
}


@pytest.mark.parametrize("name", list(ROUND_TRIP_MODELS))
def test_a_session_with_models_round_trips(name):
    models = ROUND_TRIP_MODELS[name]
    turns = [(f"q{i}", f"a{i}") for i in range(1, len(models) + 1)]
    text = purify.render(turns, "s.jsonl", "sid-1", models)
    parsed = curate.parse(text)
    assert parsed is not None and parsed.round_trip
    assert parsed.turns == turns
    assert parsed.models == models
    assert parsed.editable


def test_a_session_saved_before_models_still_parses_and_edits():
    """Every checkpoint already on disk looks like this — no heading carries a
    model, and mh must keep treating those files as fully editable."""
    text = purify.render([("q1", "a1"), ("q2", "a2")], "s.jsonl", "sid-1")
    parsed = curate.parse(text)
    assert parsed is not None and parsed.round_trip and parsed.editable
    assert parsed.models == ["", ""]
    assert curate.render(parsed) == text


def test_a_model_heading_on_a_legacy_file_is_refused():
    """The Q&A renderer never wrote a model, so a legacy file carrying one
    cannot be reproduced — it goes read-only instead of being rewritten."""
    text = curate._render_qa([("q", "a")], "s.jsonl", "sid-1").replace(
        "## A1", "## A1 — `claude-opus-5`"
    )
    parsed = curate.parse(text)
    assert parsed is not None and not parsed.round_trip
    assert not parsed.editable
    assert "byte-for-byte" in curate.readonly_reason(parsed)


def test_dialog_quoting_a_model_heading_is_absorbed():
    """A session about mh will quote these headings; out-of-sequence ones must
    stay content rather than splitting the turn."""
    turns = [("see\n\n## Agent 9 — `claude-opus-5`\n\nquoted", "ok"), ("x", "y")]
    text = purify.render(turns, "s.jsonl", "sid-1", ["claude-opus-5", ""])
    parsed = curate.parse(text)
    assert parsed is not None and parsed.round_trip
    assert parsed.turns == turns


# --- curation keeps the two lists in step ------------------------------------


def test_deleting_an_exchange_deletes_its_model(mh, ws, hub_project):
    _body(
        hub_project,
        mh,
        ws,
        [("q1", "a1"), ("q2", "a2"), ("q3", "a3")],
        model=["claude-fable-5", "claude-opus-5", "glm-5.3"],
    )
    hub = hub_project / ".memoryhub"
    c = ck.list_checkpoints(hub)[0]
    curate.delete_exchange(hub, c.slug, c.sessions[0].name, 1)
    body = c.sessions[0].read_text()
    # what was exchange 2 is now exchange 1, and keeps ITS model
    assert "## Agent 1 — `claude-opus-5`" in body
    assert "## Agent 2 — `glm-5.3`" in body
    assert "claude-fable-5" not in body


def test_editing_an_exchange_keeps_its_model(mh, ws, hub_project):
    _body(hub_project, mh, ws, [("q1", "a1"), ("q2", "a2")], model="claude-opus-5")
    hub = hub_project / ".memoryhub"
    c = ck.list_checkpoints(hub)[0]
    curate.edit_exchange(hub, c.slug, c.sessions[0].name, 1, agent="redacted")
    body = c.sessions[0].read_text()
    assert "## Agent 1 — `claude-opus-5`" in body and "redacted" in body


# --- the API -----------------------------------------------------------------


def test_the_session_api_reports_the_model(mh, ws, hub_project):
    _body(
        hub_project,
        mh,
        ws,
        [("q1", "a1"), ("q2", "a2")],
        model=["claude-opus-5", "glm-5.3"],
    )
    hub = hub_project / ".memoryhub"
    c = ck.list_checkpoints(hub)[0]
    status, data = server.dispatch(
        hub,
        "GET",
        "/api/session",
        {"ckpt": c.slug, "file": c.sessions[0].name},
        {},
        False,
    )
    assert status == 200
    assert [e["model"] for e in data["exchanges"]] == ["claude-opus-5", "glm-5.3"]


def test_the_api_reports_an_empty_model_for_older_sessions(mh, ws, hub_project):
    _body(hub_project, mh, ws, [("q", "a")])
    hub = hub_project / ".memoryhub"
    c = ck.list_checkpoints(hub)[0]
    _, data = server.dispatch(
        hub,
        "GET",
        "/api/session",
        {"ckpt": c.slug, "file": c.sessions[0].name},
        {},
        False,
    )
    assert data["exchanges"][0]["model"] == ""


# --- the badge ---------------------------------------------------------------

LABELS = {
    "claude-opus-5": "Opus 5",
    "claude-fable-5": "Fable 5",
    "claude-sonnet-4-5-20250929": "Sonnet 4.5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-3-5-sonnet-20241022": "Sonnet 3.5",
    "claude-opus-4-1-20250805": "Opus 4.1",
    "us.anthropic.claude-opus-5-v1:0": "Opus 5",
    # not Anthropic, or not recognised: shown exactly as the file records it
    "glm-5.3": "glm-5.3",
    "gpt-5-codex": "gpt-5-codex",
    "some-future-thing": "some-future-thing",
}


@needs_node
def test_the_badge_shortens_known_models_and_leaves_the_rest():
    ids = list(LABELS)
    assert run_ui_js(modelLabel=ids)["modelLabel"] == [LABELS[i] for i in ids]


@needs_node
def test_the_badge_keeps_the_raw_id_on_hover():
    chip = run_ui_js(modelChip=["claude-sonnet-4-5-20250929"])["modelChip"][0]
    assert 'title="claude-sonnet-4-5-20250929"' in chip  # the file's own value
    assert ">Sonnet 4.5<" in chip
    assert "background:" in chip  # the deterministic colour dot
