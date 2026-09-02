"""The live panel's card builder, run for real through `tests/uijs.mjs`.

The page is the only implementation of how a live exchange looks, so the tests
drive the shipped function rather than a Python restatement of it. What matters
here is the state an exchange can be in — in flight, edited, dropped — and that
a dropped one collapses to a single line you can restore, instead of the dialog
the user just asked mh to forget.
"""

from __future__ import annotations

from conftest import needs_node, run_ui_js

pytestmark = needs_node


def card(**over) -> str:
    ex = {
        "index": 3,
        "user": "what did we decide about **budgets**?",
        "agent": "6000 tokens, and `--budget none` turns it off.",
        "model": "claude-opus-5",
        "dropped": False,
        "edited": False,
        "pending": False,
    }
    ex.update(over)
    return run_ui_js(liveCard=[ex])["liveCard"][0]


def test_a_settled_exchange_shows_both_sides_and_the_model():
    html = card()
    assert "exchange 3" in html
    assert "<strong>budgets</strong>" in html  # markdown, not asterisks
    assert "<code>--budget none</code>" in html
    assert "Opus 5" in html  # the model badge, not the raw id
    assert 'text="edit"' not in html  # buttons carry no text attribute
    assert "drop" in html and "edit" in html


def test_an_answer_still_being_written_says_so():
    html = card(agent="", pending=True)
    assert "in flight" in html
    assert "still answering" in html


def test_an_edited_exchange_is_badged():
    html = card(edited=True, agent="[redacted]")
    assert "edited" in html
    assert "[redacted]" in html


def test_a_dropped_exchange_collapses_to_one_line_you_can_restore():
    html = card(dropped=True, user="a whole paragraph\nand a second line")
    assert "droppreview" in html
    assert "a whole paragraph" in html
    assert "and a second line" not in html  # the body is gone, not just dimmed
    assert "restore" in html
    assert "drop" not in html.replace("dropped", "").replace("droppreview", "")


def test_the_unfiltered_stream_renders_block_by_block():
    html = card(
        parts=[
            {"kind": "thinking", "text": "pytest is the way", "clipped": False},
            {
                "kind": "tool",
                "name": "Bash",
                "preview": "uv run pytest -q",
                "text": '{\n "command": "uv run pytest -q"\n}',
                "clipped": False,
            },
            {"kind": "text", "text": "All **207** pass.", "clipped": False},
        ]
    )
    assert "thinking" in html and "pytest is the way" in html
    assert "uv run pytest -q" in html
    assert "<pre>" in html  # the whole call is there, one click away
    # name and argument are their own columns: that is what makes a command
    # long enough to wrap hang under the argument instead of the container edge
    assert '<span class="toolname">Bash</span>' in html
    assert '<span class="toolarg">uv run pytest -q</span>' in html
    assert "<strong>207</strong>" in html
    assert "6000 tokens" not in html  # the purified text is not shown twice


def test_an_expanded_tool_call_is_coloured_as_the_json_it_is():
    html = card(
        parts=[
            {
                "kind": "tool",
                "name": "Bash",
                "preview": "ls",
                "text": '{\n "command": "ls -la",\n "timeout": 120\n}',
                "clipped": False,
            }
        ]
    )
    assert '<span class="s">"command"</span>' in html
    assert '<span class="n">120</span>' in html


def test_a_subagent_block_says_whose_output_it_is():
    html = card(
        parts=[{"kind": "text", "text": "from the subagent", "sidechain": True, "clipped": False}]
    )
    assert "subagent" in html


def test_a_clipped_block_says_it_was_clipped():
    html = card(
        parts=[{"kind": "tool", "name": "Write", "preview": "x", "text": "y" * 10, "clipped": True}]
    )
    assert "clipped" in html


def test_without_a_stream_the_dialog_still_renders():
    html = card(parts=[])
    assert "6000 tokens" in html  # falls back to the purified answer


def test_dialog_never_reaches_the_page_as_markup():
    html = card(user="<img src=x onerror=alert(1)>")
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_every_element_the_page_reaches_for_exists():
    """`$("id")` is the page's only handle on its own markup, and a typo there
    fails silently in a browser (`null.textContent` on the next line) — cheap
    to catch here. Ids the page creates itself (the popover) count as declared.
    """
    import re

    from conftest import UI_PAGE

    html = UI_PAGE.read_text(encoding="utf-8")
    markup = html.split("<script>", 1)[0]
    declared = set(re.findall(r'id="([^"]+)"', markup))
    declared |= set(re.findall(r'\{ ?id: "([^"]+)"', html))  # built by el()
    used = set(re.findall(r'\$\("([^"]+)"\)', html))
    assert not used - declared, f"ids used but never declared: {sorted(used - declared)}"


def test_calls_from_one_reply_read_as_one_parallel_step():
    html = card(
        parts=[
            {
                "kind": "tool",
                "name": "Bash",
                "preview": "ls -la",
                "text": "{}",
                "clipped": False,
                "batch": 1,
                "batch_size": 2,
            },
            {
                "kind": "tool",
                "name": "Read",
                "preview": "server.py",
                "text": "{}",
                "clipped": False,
                "batch": 1,
                "batch_size": 2,
            },
            {"kind": "tool", "name": "Bash", "preview": "git log", "text": "{}", "clipped": False},
        ]
    )
    assert "2 calls in parallel" in html
    assert html.count("part batch") == 1  # the lone third call stays on its own
    # both batched calls sit inside that one box, ahead of the call that follows
    head, first, second, lone = (
        html.index("2 calls in parallel"),
        html.index("ls -la"),
        html.index("server.py"),
        html.index("git log"),
    )
    assert head < first < second < lone


def test_a_batch_split_by_text_still_reports_its_real_size():
    html = card(
        parts=[
            {
                "kind": "tool",
                "name": "Bash",
                "preview": "one",
                "text": "{}",
                "clipped": False,
                "batch": 4,
                "batch_size": 3,
            },
        ]
    )
    assert "1 of 3 calls in parallel" in html


def test_a_pasted_picture_is_shown_under_the_question():
    html = card(
        images=[
            {
                "n": 1,
                "type": "image/png",
                "size": 12,
                "url": "/api/live/image?sid=abcd1234&index=3&n=1",
            }
        ]
    )
    assert '<img class="shot"' in html
    assert 'src="/api/live/image?sid=abcd1234&amp;index=3&amp;n=1&amp;t="' in html
    assert 'target="_blank"' in html  # full size, one click away


def test_a_picture_the_agent_read_is_shown_not_just_named():
    html = card(
        parts=[
            {
                "kind": "tool",
                "name": "Read",
                "preview": "/tmp/shot.png",
                "text": '{"file_path": "/tmp/shot.png"}',
                "clipped": False,
            }
        ]
    )
    assert 'src="/api/image?path=%2Ftmp%2Fshot.png&amp;t="' in html
    html = card(
        parts=[
            {
                "kind": "tool",
                "name": "Read",
                "preview": "/tmp/notes.py",
                "text": '{"file_path": "/tmp/notes.py"}',
                "clipped": False,
            }
        ]
    )
    assert "<img" not in html
