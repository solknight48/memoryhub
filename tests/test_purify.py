import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import (
    TIMEOUT,
    make_pi_records,
    make_records,
    write_codex_rollout,
    write_pi_transcript,
    write_transcript,
)

ORIG = Path.home() / ".claude" / "skills" / "purify-context" / "purify.py"

SID = "d4e5f6a7-4444-4444-8444-444444444444"
PI_SKILL_SID = "019f74da-9631-7c10-9d05-d50425ec4001"
CX_SKILL_SID = "019dee2a-7fd6-77e0-a429-ed6600009901"


def _only_ckpt_body(hub_project):
    ckdir = next(d for d in (hub_project / ".memoryhub" / "checkpoints").iterdir() if d.is_dir())
    return next(ckdir.glob("*.md")).read_text()


def test_pi_skill_wrapper_stripped(mh, ws, hub_project):
    """pi prepends an invoked skill's whole body to the user turn; purify must
    strip the <skill ...>...</skill> block but keep the real message after it."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    skill_q = (
        '<skill name="memoryhub" '
        'location="/Users/x/.pi/agent/skills/memoryhub/SKILL.md">\n'
        "# MemoryHub workflow\nSKILL-BODY-MARKER should never reach memory.\n"
        "</skill>\n\nload start please"
    )
    recs = make_pi_records([(skill_q, "ok answer")], cwd=str(hub_project), sid=PI_SKILL_SID)
    tr = write_pi_transcript(ws["home"], hub_project, PI_SKILL_SID, recs)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    body = _only_ckpt_body(hub_project)
    assert "load start please" in body  # real user text kept
    assert "SKILL-BODY-MARKER" not in body  # skill body stripped
    assert "<skill" not in body


def test_codex_skill_wrapper_stripped(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    skill_q = (
        "<skill>\n<name>skill-installer</name>\n<path>/x</path>\n"
        "SKILL-BODY-MARKER should never reach memory.\n</skill>\n\n"
        "actual codex question"
    )
    write_codex_rollout(ws["home"], hub_project, CX_SKILL_SID, [(skill_q, "ok")])
    tr = next((ws["home"] / ".codex" / "sessions").rglob(f"*{CX_SKILL_SID}.jsonl"))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    body = _only_ckpt_body(hub_project)
    assert "actual codex question" in body
    assert "SKILL-BODY-MARKER" not in body
    assert "<skill" not in body


JUNK = [
    {
        "type": "user",
        "message": {"role": "user", "content": "<command-name>/foo</command-name>"},
        "timestamp": "2026-07-10T04:10:00Z",
    },
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": "<local-command-stdout>noise</local-command-stdout>",
        },
    },
    {
        "type": "user",
        "isMeta": True,
        "message": {"role": "user", "content": "meta noise"},
    },
    {
        "type": "user",
        "isSidechain": True,
        "message": {"role": "user", "content": "sidechain question"},
    },
    {
        "type": "assistant",
        "isSidechain": True,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "sidechain answer"}],
        },
    },
    {
        "type": "user",
        "message": {"role": "user", "content": "[Request interrupted by user]"},
    },
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": "tool output"}],
        },
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hmm"},
                {"type": "tool_use", "name": "Bash"},
            ],
        },
    },
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": "real question <system-reminder>reminder noise</system-reminder> tail",
        },
        "timestamp": "2026-07-10T04:20:00Z",
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "real answer"}],
        },
        "timestamp": "2026-07-10T04:21:00Z",
    },
]


def test_junk_filtered_and_timestamp_from_last_record(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    records = make_records([("first q", "first a")]) + JUNK
    tr = write_transcript(ws["home"], hub_project, SID, records)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    ckdir = next(d for d in (hub_project / ".memoryhub" / "checkpoints").iterdir() if d.is_dir())
    saved = next(ckdir.glob("*.md"))
    body = saved.read_text()
    assert "first q" in body and "first a" in body
    assert "real question" in body and "tail" in body and "real answer" in body
    assert "## User 2" in body
    for absent in (
        "<system-reminder>",
        "reminder noise",
        "command-name",
        "sidechain",
        "meta noise",
        "tool output",
        "hmm",
    ):
        assert absent not in body
    # filename timestamp = last record's timestamp (04:21 UTC)
    assert saved.name == f"2026-07-10_0421_{SID[:8]}.md"


def as_mh_format(original_md: str) -> str:
    """The original script's Q&A rendering, relabelled to mh's User/Agent one.

    These four substitutions are the ONLY intended divergence from the original,
    so parity below stays byte-for-byte: any other drift, in extraction or in
    rendering, still fails the test. Caveat for future fixtures: a dialog line
    that is itself a `## Q<n>` heading would be relabelled here but not by
    render(), so keep such content out of the parity fixture.
    """
    md = original_md.replace("# Session Context — Q&A", "# Session Context").replace(
        "**Q** = user, **A** = assistant. ", ""
    )
    md = re.sub(r"^## Q(\d+)$", r"## User \1", md, flags=re.M)
    return re.sub(r"^## A(\d+)$", r"## Agent \1", md, flags=re.M)


@pytest.mark.skipif(not ORIG.is_file(), reason="original purify.py not on this machine")
def test_parity_with_original_script(ws, tmp_path):
    from memoryhub import purify as vendored

    records = make_records([("hello", "there"), ("second", "answer")]) + JUNK
    tr = tmp_path / "some-session.jsonl"
    tr.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    out = tmp_path / "orig.md"
    subprocess.run(
        [sys.executable, str(ORIG), "--transcript", str(tr), "--out", str(out)],
        check=True,
        capture_output=True,
        timeout=TIMEOUT,
        cwd=str(tmp_path),
        env=ws["env"],
    )
    turns, _, models = vendored.build_turns(tr)
    turns, models = vendored.drop_trailing_unanswered(turns, models)
    # The fixture names no model, so models is all-empty and render() takes the
    # very path a real save takes — parity still covers the shipping renderer,
    # not a stripped-down variant of it.
    assert models == ["", ""]
    assert vendored.render(turns, str(tr), None, models) == as_mh_format(out.read_text())


def test_trailing_unanswered_dropped(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    records = make_records([("answered", "yes")])
    records.append(
        {
            "type": "user",
            "message": {"role": "user", "content": "save this session please"},
            "timestamp": "2026-07-10T05:00:00Z",
        }
    )
    tr = write_transcript(ws["home"], hub_project, SID, records)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    ckdir = next(d for d in (hub_project / ".memoryhub" / "checkpoints").iterdir() if d.is_dir())
    body = next(ckdir.glob("*.md")).read_text()
    assert "answered" in body
    assert "save this session please" not in body
    assert "1 exchange." in body


def _command(name, args="", ts="2026-07-10T04:30:00Z"):
    """A slash command as Claude Code records it in the transcript."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": (
                f"<command-message>{name.lstrip('/')}</command-message>\n"
                f"<command-name>{name}</command-name>\n"
                f"<command-args>{args}</command-args>"
            ),
        },
        "timestamp": ts,
    }


def test_command_wrappers_are_recognised_only_at_the_start():
    from memoryhub import purify

    def rec(s):
        return {"type": "user", "message": {"role": "user", "content": s}}

    assert purify.user_turn(
        rec("<command-name>/mh</command-name>\n<command-args> load </command-args>")
    ) == ("/mh load", True)
    assert purify.user_turn(rec(_command("/mh")["message"]["content"])) == ("/mh", True)
    # a wrapper naming no command is noise; a question mentioning a tag is dialog
    assert purify.user_turn(rec("<command-message>x</command-message>")) == ("", False)
    assert purify.user_turn(rec("what does <command-name> mean?")) == (
        "what does <command-name> mean?",
        False,
    )


def test_an_answered_slash_command_is_dialog(mh, ws, hub_project):
    """`/mh start the webui first` is the user's words in a wrapper. When the
    agent answered it (a skill invocation), the exchange is kept — rendered as
    the user typed it, without the skill body Claude Code injects after it —
    instead of the whole opening exchange vanishing from memory."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    records = [
        _command("/mh", "start the webui first"),
        {
            "type": "user",
            "isMeta": True,
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "SKILL-BODY-MARKER"}],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "the ui is up"}],
            },
            "timestamp": "2026-07-10T04:31:00Z",
        },
    ]
    records += make_records([("second q", "second a")], start="2026-07-10T04:40:00Z")
    tr = write_transcript(ws["home"], hub_project, SID, records)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    body = _only_ckpt_body(hub_project)
    assert "## User 1\n\n/mh start the webui first\n" in body
    assert "the ui is up" in body
    assert "## User 2\n\nsecond q" in body
    assert "SKILL-BODY-MARKER" not in body
    assert "<command" not in body


def test_an_unanswered_slash_command_is_not_dialog(mh, ws, hub_project):
    """A command nobody answered was a local one — /clear, /model — and is
    dropped outright: neither an exchange nor a prefix of the next question.
    A skill invoked without arguments is still kept once answered, and a
    trailing unanswered command is left to the usual trailing-question rule."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    stdout = lambda text: {  # noqa: E731
        "type": "user",
        "message": {
            "role": "user",
            "content": f"<local-command-stdout>{text}</local-command-stdout>",
        },
    }
    records = [
        _command("/clear"),
        stdout(""),
        _command("/model", "fable", ts="2026-07-10T04:31:00Z"),
        stdout("Set model to fable"),
        *make_records([("real question", "real answer")], start="2026-07-10T04:40:00Z"),
        _command("/daily-review", ts="2026-07-10T04:50:00Z"),
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "skill body"}},
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "reviewed"}]},
            "timestamp": "2026-07-10T04:51:00Z",
        },
        _command("/model", ts="2026-07-10T04:52:00Z"),  # trailing, never answered
    ]
    tr = write_transcript(ws["home"], hub_project, SID, records)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    body = _only_ckpt_body(hub_project)
    assert "## User 1\n\nreal question" in body  # /clear and /model fable: gone, not merged in
    assert "/clear" not in body and "fable" not in body
    assert "## User 2\n\n/daily-review\n" in body and "reviewed" in body
    assert "/model" not in body
    assert "2 exchanges." in body


def test_a_background_task_notice_is_not_dialog(mh, ws, hub_project):
    """Claude Code delivers a background task's completion as a *user* record
    (`<task-notification>…`). It is the harness talking, not the user: dropped,
    and what the agent said next stays with the exchange it belongs to."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    notice = (
        "<task-notification>\n<task-id>b1</task-id>\n<status>completed</status>\n"
        "<summary>NOTICE-MARKER tests finished</summary>\n</task-notification>"
    )
    records = [
        *make_records([("run the suite", "Started it in the background.")]),
        {"type": "user", "message": {"role": "user", "content": notice}},
        {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "All green."}]},
            "timestamp": "2026-07-10T04:05:00Z",
        },
        # a reminder in front of an artifact does not turn it into dialog
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": "<system-reminder>context</system-reminder>\n" + notice,
            },
        },
    ]
    tr = write_transcript(ws["home"], hub_project, SID, records)
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    body = _only_ckpt_body(hub_project)
    assert "NOTICE-MARKER" not in body and "task-notification" not in body
    assert "1 exchange." in body
    assert "Started it in the background.\n\nAll green." in body
