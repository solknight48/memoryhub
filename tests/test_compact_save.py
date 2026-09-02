"""`mh save --compact`: store an agent-written summary instead of the purified
dialog. mh has no model of its own — the agent supplies the summary via --file,
and a bare invocation must fail rather than quietly save the other thing."""

from conftest import make_records, write_transcript
from memoryhub import checkpoint as ck
from memoryhub import curate

SID = "b7c8d9e0-3333-4333-8333-333333333333"


def _hub(project):
    return project / ".memoryhub"


def _seed(mh, ws, project, turns=None, ckpt="alpha"):
    mh("checkpoint", ckpt, cwd=project, check=0)
    return write_transcript(
        ws["home"], project, SID, make_records(turns or [("q1", "a1"), ("q2", "a2")])
    )


def _only_body(project):
    c = ck.list_checkpoints(_hub(project))[0]
    return c.sessions[0].read_text(), c.sessions[0]


# --- the happy path ----------------------------------------------------------


def test_compact_stores_the_agent_summary(mh, ws, hub_project, tmp_path):
    tr = _seed(mh, ws, hub_project)
    summary = tmp_path / "summary.md"
    summary.write_text("## Summary\n\n1. Primary Request: ship the thing.\n")
    mh("save", "--compact", "--file", summary, "--transcript", tr, cwd=hub_project, check=0)
    body, _ = _only_body(hub_project)
    assert "# Session Context — Compacted" in body
    assert "1. Primary Request: ship the thing." in body
    assert "2 exchanges compacted" in body
    assert "## User 1" not in body  # the dialog itself is not stored


def test_compact_lands_under_the_session_identity_not_the_filename(mh, ws, hub_project, tmp_path):
    """So a compacted save and a purified save of the same session are one
    file, not two — `--file` alone keys off the filename, `--compact` must not."""
    tr = _seed(mh, ws, hub_project)
    summary = tmp_path / "some-random-name.md"
    summary.write_text("summary text\n")
    mh("save", "--compact", "--file", summary, "--transcript", tr, cwd=hub_project, check=0)
    _, path = _only_body(hub_project)
    assert path.name.endswith(f"_{SID[:8]}.md")
    assert "some-random-name" not in path.name


def test_a_later_purified_save_replaces_the_compacted_one(mh, ws, hub_project, tmp_path):
    tr = _seed(mh, ws, hub_project)
    summary = tmp_path / "s.md"
    summary.write_text("summary text\n")
    mh("save", "--compact", "--file", summary, "--transcript", tr, cwd=hub_project, check=0)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    c = ck.list_checkpoints(_hub(hub_project))[0]
    assert len(c.sessions) == 1  # one representation per session, never both
    assert "## User 1" in c.sessions[0].read_text()


def test_positional_checkpoint_argument(mh, ws, hub_project):
    """`mh save <checkpoint>`, the form the flag is usually typed with."""
    tr = _seed(mh, ws, hub_project)
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("save", "alpha", "--transcript", tr, cwd=hub_project, check=0)
    assert ck.resolve(_hub(hub_project), "alpha").sessions
    assert not ck.resolve(_hub(hub_project), "beta").sessions


def test_positional_and_to_must_agree(mh, ws, hub_project):
    tr = _seed(mh, ws, hub_project)
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    p = mh("save", "alpha", "--to", "beta", "--transcript", tr, cwd=hub_project)
    assert p.returncode == 1
    assert "two target checkpoints" in p.stderr


# --- refusing to guess -------------------------------------------------------


def test_compact_without_a_summary_errors_and_saves_nothing(mh, ws, hub_project):
    tr = _seed(mh, ws, hub_project)
    p = mh("save", "--compact", "--transcript", tr, cwd=hub_project)
    assert p.returncode == 1
    assert "does not summarize by itself" in p.stderr
    assert ck.list_checkpoints(_hub(hub_project))[0].sessions == []


def test_compact_with_an_empty_summary_errors(mh, ws, hub_project, tmp_path):
    tr = _seed(mh, ws, hub_project)
    empty = tmp_path / "empty.md"
    empty.write_text("   \n")
    p = mh("save", "--compact", "--file", empty, "--transcript", tr, cwd=hub_project)
    assert p.returncode == 1
    assert "nothing to compact" in p.stderr
    assert ck.list_checkpoints(_hub(hub_project))[0].sessions == []


def test_compact_with_a_missing_file_errors(mh, ws, hub_project, tmp_path):
    tr = _seed(mh, ws, hub_project)
    p = mh("save", "--compact", "--file", tmp_path / "nope.md", "--transcript", tr, cwd=hub_project)
    assert p.returncode == 1
    assert "file not found" in p.stderr


# --- how the rest of mh sees a compacted session -----------------------------


def test_curate_recognises_a_compacted_session_as_read_only(mh, ws, hub_project, tmp_path):
    tr = _seed(mh, ws, hub_project)
    summary = tmp_path / "s.md"
    summary.write_text("## Summary\n\nstuff happened.\n")
    mh("save", "--compact", "--file", summary, "--transcript", tr, cwd=hub_project, check=0)
    body, _ = _only_body(hub_project)
    parsed = curate.parse(body)
    assert parsed is not None, "a compacted session must still be recognised as ours"
    assert parsed.compacted
    assert not parsed.editable  # a summary has no exchanges to edit
    assert parsed.session_id == SID


def test_a_summary_quoting_dialog_headings_stays_compacted(mh, ws, hub_project, tmp_path):
    """Summaries quote the conversation, so they contain `## User 1` lines. That
    must not make the file parse as dialog."""
    tr = _seed(mh, ws, hub_project)
    summary = tmp_path / "s.md"
    summary.write_text("## Summary\n\nThe user asked:\n\n## User 1\n\nquoted turn\n")
    mh("save", "--compact", "--file", summary, "--transcript", tr, cwd=hub_project, check=0)
    body, _ = _only_body(hub_project)
    parsed = curate.parse(body)
    assert parsed.compacted and parsed.turns == []


def test_compacted_sessions_load_like_any_other(mh, ws, hub_project, tmp_path):
    tr = _seed(mh, ws, hub_project)
    summary = tmp_path / "s.md"
    summary.write_text("## Summary\n\nthe compacted gist.\n")
    mh("save", "--compact", "--file", summary, "--transcript", tr, cwd=hub_project, check=0)
    out = mh("load", cwd=hub_project, check=0).stdout
    assert "the compacted gist." in out
    assert "Compacted" in out


def test_plain_file_ingest_is_unchanged(mh, ws, hub_project, tmp_path):
    """--file without --compact keeps its old verbatim behaviour."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    md = tmp_path / "hand-written.md"
    md.write_text("# Whatever\n\nverbatim content\n")
    mh("save", "--file", md, cwd=hub_project, check=0)
    body, path = _only_body(hub_project)
    assert body == "# Whatever\n\nverbatim content\n"
    assert "hand-written" in path.name
