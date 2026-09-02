"""The live session: `mh ui` follows the transcript being written right now,
and the curation done to it while it runs survives every later save."""

import json
import subprocess

import pytest

from conftest import TIMEOUT, make_records, write_transcript
from memoryhub import checkpoint as ck
from memoryhub import live as livemod
from memoryhub import server
from memoryhub.hub import MhError

SID = "aabbccdd-1111-4111-8111-111111111111"
SID2 = "eeff0011-2222-4222-8222-222222222222"


def _hub(project):
    return project / ".memoryhub"


def call(project, method, path, query=None, body=None, read_only=False):
    return server.dispatch(_hub(project), method, path, query or {}, body or {}, read_only)


def transcript(ws, project, turns, sid=SID, **kw):
    """Write (or grow) a transcript, and forget any cached discovery so a
    freshly created session is visible to the very next poll."""
    livemod._discovery.clear()
    return write_transcript(ws["home"], project, sid, make_records(turns, cwd=str(project), **kw))


def stored(project):
    return [p for c in ck.list_checkpoints(_hub(project)) for p in c.sessions]


def live(project, **query):
    status, data = call(project, "GET", "/api/live", query)
    assert status == 200, data
    return data


# --- following the transcript ------------------------------------------------


def test_no_transcript_is_not_an_error(mh, hub_project):
    data = live(hub_project)
    assert data["present"] is False
    assert "no transcript" in data["reason"]


def test_live_renders_the_session_being_written(mh, ws, hub_project):
    transcript(
        ws, hub_project, [("first q", "first a"), ("second q", "second a")], model="claude-opus-5"
    )
    data = live(hub_project)
    assert data["present"] and data["agent"] == "claude"
    assert data["key"] == "aabbccdd"
    assert [e["user"] for e in data["exchanges"]] == ["first q", "second q"]
    assert data["exchanges"][0]["model"] == "claude-opus-5"
    assert data["pending"] is False
    assert data["would_store"] == 2
    assert data["saved"] is None


def test_an_unanswered_question_shows_live_but_is_not_stored(mh, ws, hub_project):
    path = transcript(ws, hub_project, [("q1", "a1")])
    path.write_text(
        path.read_text()
        + json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "q2"},
                "timestamp": "2026-07-10T05:00:00Z",
                "cwd": str(hub_project),
            }
        )
        + "\n"
    )
    data = live(hub_project)
    assert [e["index"] for e in data["exchanges"]] == [1, 2]
    assert data["exchanges"][1]["pending"] is True
    assert data["pending"] is True
    assert data["would_store"] == 1  # every save drops the question in flight


def test_an_unchanged_transcript_answers_without_re_reading(mh, ws, hub_project):
    transcript(ws, hub_project, [("q1", "a1")])
    first = live(hub_project)
    again = live(hub_project, fp=first["fp"])
    assert again["unchanged"] is True
    assert "exchanges" not in again
    grown = transcript(ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    assert grown  # same file, now longer
    assert live(hub_project, fp=first["fp"])["unchanged"] is False


def test_following_a_named_session(mh, ws, hub_project):
    transcript(ws, hub_project, [("old q", "old a")], sid=SID)
    transcript(ws, hub_project, [("new q", "new a")], sid=SID2)
    newest = live(hub_project)
    assert {s["sid"] for s in newest["sessions"]} == {SID, SID2}
    picked = live(hub_project, sid=SID)
    assert picked["session_id"] == SID
    assert picked["exchanges"][0]["user"] == "old q"
    # the payload says which transcript is newest and how long each has been
    # quiet, so the page can tell "ended" from "older than the one pinned"
    assert picked["newest"] == SID2[:8] and newest["key"] == SID2[:8]
    assert picked["sessions"][0]["key"] == SID2[:8]
    assert all(isinstance(s["idle"], int) and s["idle"] >= 0 for s in picked["sessions"])
    # dispatch raises; the request handler is what turns MhError into a 400
    with pytest.raises(MhError, match="no session 'nope'"):
        call(hub_project, "GET", "/api/live", {"sid": "nope"})


# --- curating it while it runs -----------------------------------------------


def test_drop_and_restore_before_anything_is_saved(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("keep", "a1"), ("junk", "a2")])
    status, r = call(hub_project, "POST", "/api/live/drop", body={"index": 2})
    assert status == 200 and r["edits"] == 1
    assert r["saved"] is None  # nothing stored yet; the draft waits for the save
    data = live(hub_project)
    assert [e["dropped"] for e in data["exchanges"]] == [False, True]
    assert data["would_store"] == 1
    call(hub_project, "POST", "/api/live/restore", body={"index": 2})
    assert live(hub_project)["would_store"] == 2


def test_saving_the_live_session_stores_the_curated_dialog(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("keep", "a1"), ("junk", "a2")])
    call(hub_project, "POST", "/api/live/drop", body={"index": 2})
    status, r = call(hub_project, "POST", "/api/live/save", body={})
    assert status == 200 and r["checkpoint"] == "alpha" and r["exchanges"] == 1
    (path,) = stored(hub_project)
    text = path.read_text()
    assert "keep" in text and "junk" not in text
    assert live(hub_project)["saved"]["in_sync"] is True


def test_editing_a_saved_live_session_updates_the_stored_copy(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "secret token")])
    call(hub_project, "POST", "/api/live/save", body={})
    status, r = call(
        hub_project, "POST", "/api/live/edit", body={"index": 1, "agent": "[redacted]"}
    )
    assert status == 200 and r["saved"]["checkpoint"] == "alpha"
    (path,) = stored(hub_project)
    assert "[redacted]" in path.read_text()
    assert "secret token" not in path.read_text()
    assert live(hub_project)["exchanges"][0]["edited"] is True


def test_the_last_exchange_cannot_be_dropped(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("only", "a1")])
    with pytest.raises(MhError, match="only exchange"):
        call(hub_project, "POST", "/api/live/drop", body={"index": 1})


def test_an_empty_user_side_is_refused(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1")])
    with pytest.raises(MhError, match="cannot be empty"):
        call(hub_project, "POST", "/api/live/edit", body={"index": 1, "user": "  "})
    assert live(hub_project)["edits"] == 0  # and nothing was written


def test_discard_puts_the_transcript_back(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    call(hub_project, "POST", "/api/live/drop", body={"index": 1})
    call(hub_project, "POST", "/api/live/save", body={})
    assert "q1" not in stored(hub_project)[0].read_text()
    call(hub_project, "POST", "/api/live/discard", body={})
    assert live(hub_project)["edits"] == 0
    assert "q1" in stored(hub_project)[0].read_text()


def test_a_read_only_server_only_looks(mh, ws, hub_project):
    transcript(ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    assert live(hub_project)["present"] is True
    status, err = call(hub_project, "POST", "/api/live/drop", {}, {"index": 1}, read_only=True)
    assert status == 403 and "read-only" in err["error"]


# --- and the edits outlive the session ---------------------------------------


def test_a_later_save_re_applies_the_live_edits(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1"), ("junk", "a2")])
    call(hub_project, "POST", "/api/live/drop", body={"index": 2})
    call(hub_project, "POST", "/api/live/edit", body={"index": 1, "agent": "trimmed"})
    call(hub_project, "POST", "/api/live/save", body={})

    # the session keeps going, then Claude Code's SessionEnd hook saves it
    transcript(ws, hub_project, [("q1", "a1"), ("junk", "a2"), ("q3", "a3")])
    payload = json.dumps({"cwd": str(hub_project), "session_id": SID})
    p = mh("hook", "save", cwd=hub_project, check=0, input=payload)
    assert "2 live edits applied" in p.stdout

    (path,) = stored(hub_project)
    text = path.read_text()
    assert "junk" not in text  # dropped stays dropped
    assert "trimmed" in text  # the rewrite stays rewritten
    assert "a1" not in text
    assert "q3" in text  # and new dialog still arrives


def test_mh_save_applies_the_draft_too(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1"), ("junk", "a2")])
    call(hub_project, "POST", "/api/live/drop", body={"index": 2})
    p = mh("save", cwd=hub_project, check=0)
    assert "1 live edit applied" in p.stdout
    assert "junk" not in stored(hub_project)[0].read_text()


def test_an_entry_whose_dialog_moved_is_ignored(mh, ws, hub_project):
    """Only the in-flight exchange can change under a draft entry: two
    consecutive unanswered questions merge into one turn. The anchor catches
    it, so the entry is dropped rather than applied to different dialog."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    path = transcript(ws, hub_project, [("q1", "a1")])
    tail = json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": "half a thought"},
            "timestamp": "2026-07-10T05:00:00Z",
            "cwd": str(hub_project),
        }
    )
    path.write_text(path.read_text() + tail + "\n")
    call(hub_project, "POST", "/api/live/edit", body={"index": 2, "agent": "note to self"})
    assert live(hub_project)["exchanges"][1]["edited"] is True

    more = json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": "the rest of it"},
            "timestamp": "2026-07-10T05:01:00Z",
            "cwd": str(hub_project),
        }
    )
    path.write_text(path.read_text() + more + "\n")
    data = live(hub_project)
    assert data["stale"] == 1
    assert data["exchanges"][1]["edited"] is False
    assert "half a thought" in data["exchanges"][1]["user"]


# --- the draft is local state, not hub content -------------------------------


def test_drafts_stay_out_of_the_journal(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    call(hub_project, "POST", "/api/live/drop", body={"index": 2})
    hub = _hub(hub_project)
    assert (hub / "drafts" / "aabbccdd.json").is_file()
    assert "/drafts/" in (hub / ".git" / "info" / "exclude").read_text()
    status = subprocess.run(
        ["git", "-C", str(hub), "status", "--porcelain"],
        env=ws["env"],
        capture_output=True,
        text=True,
        check=True,
        timeout=TIMEOUT,
    ).stdout
    assert status.strip() == ""


def test_an_unreadable_draft_never_blocks_a_save(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1")])
    drafts = _hub(hub_project) / "drafts"
    drafts.mkdir()
    (drafts / "aabbccdd.json").write_text("{ this is not json")
    mh("save", cwd=hub_project, check=0)
    assert "q1" in stored(hub_project)[0].read_text()


def test_a_session_lives_in_exactly_one_checkpoint(mh, ws, hub_project):
    """The same policy as `mh save`: an explicit other target moves the session,
    and a save with no target follows it to where it lives — never two copies."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1")])
    call(hub_project, "POST", "/api/live/save", body={"to": "alpha"})
    status, r = call(hub_project, "POST", "/api/live/save", body={"to": "beta"})
    assert status == 200 and r["checkpoint"] == "beta" and r["moved_from"] == "alpha"
    assert len(stored(hub_project)) == 1
    status, r = call(hub_project, "POST", "/api/live/save", body={})
    assert status == 200 and r["checkpoint"] == "beta"
    assert ck.resolve(_hub(hub_project), "alpha").sessions == []


def test_a_compacted_save_is_left_alone(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    summary = hub_project / "summary.md"
    summary.write_text("What this session settled.\n")
    mh("save", "--compact", "--file", summary, cwd=hub_project, check=0)
    with pytest.raises(MhError, match="compacted save"):
        call(hub_project, "POST", "/api/live/save", body={})
    assert live(hub_project)["saved"]["compacted"] is True


def test_an_index_outside_the_session_is_refused(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1")])
    with pytest.raises(MhError, match="no exchange 9"):
        call(hub_project, "POST", "/api/live/drop", body={"index": 9})


# --- the unfiltered stream ----------------------------------------------------
# extract() gives the dialog mh stores; stream() gives what the agent actually
# emitted on the way there. The live panel reads the second, saves the first.


def rich_records(cwd):
    """A Claude transcript with the blocks a purified save throws away:
    thinking, tool calls, tool results, and a subagent's own output."""

    def user(text, **extra):
        return {
            "type": "user",
            "message": {"role": "user", "content": text},
            "timestamp": "2026-07-10T04:00:00Z",
            "cwd": cwd,
            **extra,
        }

    def assistant(blocks, **extra):
        return {
            "type": "assistant",
            "cwd": cwd,
            "timestamp": "2026-07-10T04:01:00Z",
            "message": {"role": "assistant", "content": blocks, "model": "claude-opus-5"},
            **extra,
        }

    return [
        user("run the tests"),
        assistant(
            [
                {"type": "thinking", "thinking": "pytest is the way"},
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "uv run pytest -q", "description": "run tests"},
                },
            ]
        ),
        user([{"type": "tool_result", "content": "207 passed"}]),
        assistant(
            [
                {"type": "thinking", "thinking": "green"},
                {"type": "text", "text": "All **207** pass."},
            ]
        ),
        user("and the linter?"),
        assistant([{"type": "tool_use", "name": "Task", "input": {"prompt": "check lint"}}]),
        assistant([{"type": "text", "text": "subagent talking"}], isSidechain=True),
        assistant([{"type": "text", "text": "Clean."}]),
    ]


def test_the_stream_lines_up_with_the_dialog(mh, ws, hub_project):
    livemod._discovery.clear()
    from conftest import dump_jsonl
    from memoryhub.purify import encode_project_dir

    dump_jsonl(
        ws["home"] / ".claude" / "projects" / encode_project_dir(hub_project) / f"{SID}.jsonl",
        rich_records(str(hub_project)),
    )
    data = live(hub_project, full="1")
    assert data["stream"] is True
    first, second = data["exchanges"]
    # the dialog side is still purified: text only
    assert first["agent"] == "All **207** pass."
    kinds = [(p["kind"], p.get("name", "")) for p in first["parts"]]
    assert kinds == [("thinking", ""), ("tool", "Bash"), ("thinking", ""), ("text", "")]
    tool = first["parts"][1]
    assert tool["preview"] == "uv run pytest -q"
    assert "uv run pytest -q" in tool["text"]  # the whole call, as JSON
    assert "207 passed" not in json.dumps(first["parts"])  # a result is not agent output
    assert [p["kind"] for p in second["parts"]] == ["tool", "text", "text"]
    assert second["parts"][1]["sidechain"] is True  # the subagent's own output


def test_calls_from_one_reply_are_marked_as_one_batch(mh, ws, hub_project):
    """Claude Code writes one record per block, so only the message id says
    which calls came from the same reply — and those ran concurrently."""
    livemod._discovery.clear()
    from conftest import dump_jsonl
    from memoryhub.purify import encode_project_dir

    def block(b, mid):
        return {
            "type": "assistant",
            "cwd": str(hub_project),
            "timestamp": "2026-07-10T04:01:00Z",
            "message": {"role": "assistant", "id": mid, "content": [b]},
        }

    def tool(name, cmd):
        return {"type": "tool_use", "name": name, "input": {"command": cmd}}

    dump_jsonl(
        ws["home"] / ".claude" / "projects" / encode_project_dir(hub_project) / f"{SID}.jsonl",
        [
            {
                "type": "user",
                "cwd": str(hub_project),
                "timestamp": "2026-07-10T04:00:00Z",
                "message": {"role": "user", "content": "look around"},
            },
            block(tool("Bash", "ls"), "msg_a"),  # one reply, two calls
            block(tool("Bash", "git log"), "msg_a"),
            block(tool("Bash", "alone"), "msg_b"),  # the next reply, one call
            block({"type": "text", "text": "done"}, "msg_c"),
        ],
    )
    parts = live(hub_project, full="1")["exchanges"][0]["parts"]
    batched = [p for p in parts if p.get("batch")]
    assert len(batched) == 2
    assert {p["batch"] for p in batched} == {1}
    assert {p["batch_size"] for p in batched} == {2}
    assert [p["preview"] for p in batched] == ["ls", "git log"]
    assert "batch" not in parts[2]  # a call of its own is not a batch
    assert "emit" not in parts[0]  # the grouping key never leaves the server


def test_a_long_command_is_elided_at_a_word_not_mid_token(mh, ws, hub_project):
    """A preview that stops dead inside a path ("... cut -d= -f2) cu") reads as
    a rendering fault. It ends on a word, with an ellipsis that says so."""
    from memoryhub.agents import PREVIEW_CHARS, _preview

    cmd = (
        "for i in $(seq 30); do [ -s /tmp/mh-ui-7777.log ] && break; done; "
        "cat /tmp/mh-ui-7777.log; T=$(grep -o 't=[^ ]*' /tmp/mh-ui-7777.log "
        "| head -1 | cut -d= -f2) curl -s http://127.0.0.1:7777/api/live"
    )
    out = _preview({"command": cmd})
    assert out.endswith(" …")
    assert len(out) <= PREVIEW_CHARS + 2
    assert not out[:-2].endswith(" ")  # no dangling space before it
    assert cmd.startswith(out[:-2])  # a true prefix, nothing invented
    assert out.split()[-2] in cmd.split()  # the last word survived whole
    assert _preview({"command": "uv run pytest -q"}) == "uv run pytest -q"
    # a single token with no word boundary still has to be cut somewhere
    assert _preview({"command": "x" * 400}).endswith(" …")


def test_the_stream_is_only_sent_when_the_page_asks(mh, ws, hub_project):
    transcript(ws, hub_project, [("q1", "a1")])
    plain = live(hub_project)
    assert "stream" not in plain or plain["stream"] is False
    assert "parts" not in plain["exchanges"][0]
    assert "parts" in live(hub_project, full="1")["exchanges"][0]


def test_a_curated_exchange_shows_what_will_be_stored(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    transcript(ws, hub_project, [("q1", "a1"), ("q2", "a2")])
    call(hub_project, "POST", "/api/live/edit", body={"index": 1, "agent": "rewritten"})
    call(hub_project, "POST", "/api/live/drop", body={"index": 2})
    one, two = live(hub_project, full="1")["exchanges"]
    assert "parts" not in one and one["agent"] == "rewritten"
    assert "parts" not in two and two["dropped"] is True


def test_a_pi_session_streams_its_thinking_and_tool_calls(mh, ws, hub_project):
    from conftest import write_pi_transcript

    livemod._discovery.clear()
    recs = [
        {
            "type": "session",
            "version": 3,
            "id": "p1",
            "cwd": str(hub_project),
            "timestamp": "2026-07-10T04:00:00Z",
        },
        {
            "type": "message",
            "timestamp": "2026-07-10T04:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "查一下"}]},
        },
        {
            "type": "message",
            "timestamp": "2026-07-10T04:01:00Z",
            "message": {
                "role": "assistant",
                "model": "gpt-5",
                "content": [
                    {"type": "thinking", "thinking": "先搜索"},
                    {
                        "type": "toolCall",
                        "name": "web_search",
                        "arguments": {"queries": ["hyperliquid"]},
                    },
                    {"type": "text", "text": "查到了。"},
                ],
            },
        },
    ]
    write_pi_transcript(ws["home"], hub_project, "p1", recs)
    data = live(hub_project, full="1")
    assert data["agent"] == "pi" and data["stream"] is True
    parts = data["exchanges"][0]["parts"]
    assert [p["kind"] for p in parts] == ["thinking", "tool", "text"]
    assert parts[1]["name"] == "web_search" and "hyperliquid" in parts[1]["preview"]


def test_a_format_mh_has_not_verified_says_so_instead_of_guessing(mh, ws, hub_project):
    from conftest import write_codex_rollout

    livemod._discovery.clear()
    write_codex_rollout(ws["home"], hub_project, "cx1", [("q1", "a1")])
    data = live(hub_project, full="1")
    assert data["agent"] == "codex"
    assert data["stream"] is False  # the page falls back to the dialog
    assert "parts" not in data["exchanges"][0]
    assert data["exchanges"][0]["agent"] == "a1"


def test_a_session_opened_by_a_slash_command_still_streams(mh, ws, hub_project):
    """`/mh load` answered by the agent is exchange 1 in the stream as in the
    dialog; a `/model` nobody answered is in neither. The two walks must agree
    on every boundary, or the page loses the full output for the whole session."""
    livemod._discovery.clear()
    from conftest import dump_jsonl
    from memoryhub.purify import encode_project_dir

    cwd = str(hub_project)

    def user(text, **extra):
        return {
            "type": "user",
            "message": {"role": "user", "content": text},
            "timestamp": "2026-07-10T04:00:00Z",
            "cwd": cwd,
            **extra,
        }

    def assistant(blocks):
        return {
            "type": "assistant",
            "cwd": cwd,
            "timestamp": "2026-07-10T04:01:00Z",
            "message": {"role": "assistant", "content": blocks, "model": "claude-opus-5"},
        }

    def command(name, args=""):
        return user(
            f"<command-message>{name[1:]}</command-message>\n"
            f"<command-name>{name}</command-name>\n<command-args>{args}</command-args>"
        )

    dump_jsonl(
        ws["home"] / ".claude" / "projects" / encode_project_dir(hub_project) / f"{SID}.jsonl",
        [
            command("/mh", "load"),
            user("skill body", isMeta=True),
            assistant(
                [
                    {"type": "thinking", "thinking": "load first"},
                    {"type": "tool_use", "name": "Bash", "input": {"command": "mh load"}},
                    {"type": "text", "text": "Memory loaded."},
                ]
            ),
            command("/model", "fable"),
            user("<local-command-stdout>Set model to fable</local-command-stdout>"),
            user("and now?"),
            assistant([{"type": "text", "text": "Now we work."}]),
        ],
    )
    data = live(hub_project, full="1")
    assert data["stream"] is True
    first, second = data["exchanges"]
    assert first["user"] == "/mh load" and first["agent"] == "Memory loaded."
    assert [p["kind"] for p in first["parts"]] == ["thinking", "tool", "text"]
    assert second["user"] == "and now?"
    assert [p["kind"] for p in second["parts"]] == ["text"]


# --- pictures ------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(24))  # a PNG's magic is all a viewer needs to be sure


def test_a_pasted_picture_shows_in_the_live_panel(mh, ws, hub_project):
    """Claude Code keeps a pasted picture as a base64 block in the user record.
    The panel is told there is one (never the bytes), and fetches it decoded
    from the transcript — nothing is copied into the hub."""
    import base64

    from conftest import dump_jsonl
    from memoryhub.purify import encode_project_dir

    livemod._discovery.clear()
    cwd = str(hub_project)
    dump_jsonl(
        ws["home"] / ".claude" / "projects" / encode_project_dir(hub_project) / f"{SID}.jsonl",
        [
            {
                "type": "user",
                "cwd": cwd,
                "timestamp": "2026-07-10T04:00:00Z",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "[Image #1] what is this?"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(PNG).decode(),
                            },
                        },
                    ],
                },
            },
            {
                "type": "assistant",
                "cwd": cwd,
                "timestamp": "2026-07-10T04:01:00Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "A chart."}]},
            },
        ],
    )
    (ex,) = live(hub_project)["exchanges"]
    assert ex["user"] == "[Image #1] what is this?"  # the marker stays, the bytes do not
    assert ex["images"] == [
        {
            "n": 1,
            "type": "image/png",
            "size": len(PNG),
            "url": f"/api/live/image?sid={SID[:8]}&index=1&n=1",
        }
    ]
    data, ctype = server.live_image(_hub(hub_project), {"sid": SID, "index": "1", "n": "1"})
    assert data == PNG and ctype == "image/png"
    with pytest.raises(MhError, match="no picture 2"):
        server.live_image(_hub(hub_project), {"sid": SID, "index": "1", "n": "2"})
    # a purified save carries the dialog only
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    call(hub_project, "POST", "/api/live/save", body={})
    assert "base64" not in stored(hub_project)[0].read_text()


def test_only_real_image_files_are_served(tmp_path):
    """The file route hands out pictures, not files: the bytes must sniff as
    an image, the path must be absolute, and it must exist."""
    good = tmp_path / "shot.png"
    good.write_bytes(PNG)
    assert server.image_file(str(good)) == (PNG, "image/png")
    fake = tmp_path / "secrets.png"
    fake.write_text("BEGIN PRIVATE KEY")
    with pytest.raises(MhError, match="not an image"):
        server.image_file(str(fake))
    with pytest.raises(MhError, match="absolute"):
        server.image_file("shot.png")
    with pytest.raises(MhError, match="no such file"):
        server.image_file(str(tmp_path / "gone.png"))
    assert server.sniff_image(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    assert server.sniff_image(b"\xff\xd8\xff\xe0") == "image/jpeg"


def test_a_long_reply_streams_whole_while_a_long_tool_call_is_clipped(mh, ws, hub_project):
    """The reply is the dialog: the panel must show all of it, exactly as a
    save would store it. A tool call carrying a whole file is what the cap is
    for."""
    from conftest import dump_jsonl
    from memoryhub.purify import encode_project_dir

    livemod._discovery.clear()
    cwd = str(hub_project)
    reply = "word " * 3000  # 15k characters of answer
    dump_jsonl(
        ws["home"] / ".claude" / "projects" / encode_project_dir(hub_project) / f"{SID}.jsonl",
        [
            {
                "type": "user",
                "cwd": cwd,
                "timestamp": "2026-07-10T04:00:00Z",
                "message": {"role": "user", "content": "write it all down"},
            },
            {
                "type": "assistant",
                "cwd": cwd,
                "timestamp": "2026-07-10T04:01:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": "/tmp/big.md", "content": "x" * 9000},
                        },
                        {"type": "text", "text": reply},
                    ],
                },
            },
        ],
    )
    (ex,) = live(hub_project, full="1")["exchanges"]
    tool, text = ex["parts"]
    assert tool["clipped"] is True and len(tool["text"]) == 4000
    assert text["clipped"] is False and text["text"] == reply.strip()
