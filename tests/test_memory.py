"""Claude Code's per-project auto-memory, shown read-only in the map.

mh does not own the memory folder; these pin the reading of it — the
frontmatter parser (top-level scalars plus the nested `metadata` map), the
index order, and the route that marks a note whose origin transcript is still
here.
"""

from __future__ import annotations

from pathlib import Path

from conftest import make_records, needs_node, run_ui_js, write_transcript
from memoryhub import live as livemod
from memoryhub import memory, purify, server


def mem_dir(ws, project) -> Path:
    d = ws["home"] / ".claude" / "projects" / purify.encode_project_dir(project) / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_note(d: Path, name: str, *, type_="feedback", origin=None, body="A note.", desc="d"):
    meta = f"  node_type: memory\n  type: {type_}\n"
    if origin:
        meta += f"  originSessionId: {origin}\n"
    meta += "  modified: 2026-09-02T07:38:30.606Z\n"
    (d / f"{name}.md").write_text(
        f'---\nname: {name}\ndescription: "{desc}"\nmetadata: \n{meta}---\n\n{body}\n'
    )


# --- the parser ---------------------------------------------------------------


def test_frontmatter_scalars_and_the_nested_metadata_map():
    text = (
        '---\nname: foo\ndescription: "one: two"\nmetadata: \n'
        "  node_type: memory\n  type: reference\n  originSessionId: abc\n"
        "  modified: 2026-09-02T07:38:30.606Z\n---\n\nBody **here** with [[bar]] and [[baz]].\n"
    )
    front, body = memory._split_front(text)
    assert front["name"] == "foo" and front["description"] == "one: two"
    assert front["metadata"] == {
        "node_type": "memory",
        "type": "reference",
        "originSessionId": "abc",
        "modified": "2026-09-02T07:38:30.606Z",
    }
    assert body == "Body **here** with [[bar]] and [[baz]]."


def test_a_file_without_frontmatter_is_all_body():
    front, body = memory._split_front("no front, just text\n")
    assert front == {} and body == "no front, just text"


# --- reading the folder -------------------------------------------------------


def test_no_folder_is_absent_not_an_error(ws, hub_project):
    out = memory.read(hub_project)
    assert out["present"] is False and out["memories"] == []


def test_index_order_first_then_orphans_newest(ws, hub_project):
    d = mem_dir(ws, hub_project)
    write_note(d, "alpha", type_="project", body="First. [[beta]]")
    write_note(d, "beta", type_="feedback")
    write_note(d, "orphan", type_="reference")  # not in the index
    (d / "MEMORY.md").write_text(
        "- [Alpha note](alpha.md) — the hook for alpha\n- [Beta](beta.md) — beta hook\n"
    )
    out = memory.read(hub_project)
    assert out["present"] is True
    assert [m["name"] for m in out["memories"]] == ["alpha", "beta", "orphan"]
    alpha = out["memories"][0]
    assert alpha["title"] == "Alpha note" and alpha["hook"] == "the hook for alpha"
    assert alpha["type"] == "project" and alpha["links"] == ["beta"]
    assert alpha["modified"] == "2026-09-02"
    # an orphan still renders, titled from its own frontmatter name
    assert out["memories"][2]["title"] == "orphan" and out["memories"][2]["hook"] == ""


# --- the route ----------------------------------------------------------------


def test_the_route_marks_a_note_whose_origin_transcript_is_here(ws, hub_project):
    sid = "77770000-1111-4111-8111-111111111111"
    d = mem_dir(ws, hub_project)
    write_note(d, "with-origin", origin=sid)
    write_note(d, "gone-origin", origin="00000000-dead-4000-8000-000000000000")
    livemod._discovery.clear()
    write_transcript(ws["home"], hub_project, sid, make_records([("q", "a")], cwd=str(hub_project)))
    status, data = server.dispatch(hub_project / ".memoryhub", "GET", "/api/memory", {}, {}, False)
    assert status == 200 and data["present"] is True
    by = {m["name"]: m for m in data["memories"]}
    assert (
        by["with-origin"]["origin_here"] is True and by["with-origin"]["origin_key"] == "77770000"
    )
    assert by["gone-origin"]["origin_here"] is False
    # a list, so read-only serves it too
    status, _ = server.dispatch(hub_project / ".memoryhub", "GET", "/api/memory", {}, {}, True)
    assert status == 200


# --- the card, from the page --------------------------------------------------


@needs_node
def test_the_memory_card_renders_type_body_and_related_chips():
    m = {
        "name": "feedback-x",
        "title": "Feedback X",
        "type": "feedback",
        "modified": "2026-09-02",
        "origin": "abcd1234-1111",
        "origin_here": True,
        "origin_key": "abcd1234",
        "body": "Body **bold** and a [[known]] link.",
        "links": ["known", "missing"],
    }
    (html,) = run_ui_js(memoryCard=[[m, ["feedback-x", "known"]]])["memoryCard"]
    assert 'class="mtype feedback"' in html and "Feedback X" in html
    assert "<strong>bold</strong>" in html  # body went through the markdown renderer
    assert "open session ↗" in html  # origin transcript is here
    assert '<button class="memchip" title="Jump to this note">known</button>' in html
    assert 'class="memchip missing"' in html  # a link with no note yet
