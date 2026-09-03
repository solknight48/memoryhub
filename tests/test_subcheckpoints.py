"""Sub-checkpoints: a smaller scope under a checkpoint. Stored inside the
parent's directory and named parent.child; loaded together with the parents;
following the parent through a rename, gone with it on delete; never a take
and never a template stage.
"""

import json

from conftest import make_records, write_transcript
from memoryhub import checkpoint as ck
from memoryhub import server, templates

SID_P = "dddd1111-0000-4000-8000-00000000000d"
SID_C = "eeee2222-0000-4000-8000-00000000000e"
SID_S = "ffff3333-0000-4000-8000-00000000000f"


def _save(mh, ws, project, sid, q, start):
    tr = write_transcript(ws["home"], project, sid, make_records([(q, "a-" + q)], start=start))
    mh("save", "--transcript", tr, cwd=project, check=0)


def test_a_sub_checkpoint_lives_inside_its_parent(mh, ws, hub_project):
    hub = hub_project / ".memoryhub"
    mh("checkpoint", "design", cwd=hub_project, check=0)
    p = mh("checkpoint", "head page", "--under", "design", cwd=hub_project, check=0)
    assert "sub-checkpoint 'design.head-page' created (current) — under design" in p.stdout
    p = mh("checkpoint", "design.main-page", cwd=hub_project, check=0)  # the dotted form
    assert "'design.main-page' created" in p.stdout

    cps = ck.list_checkpoints(hub)
    assert [c.slug for c in cps] == ["design", "design.head-page", "design.main-page"]
    assert [c.parent for c in cps] == [None, "design", "design"]
    assert cps[1].path.parent == cps[0].path and cps[1].leaf == "head-page"
    # one column: sub-checkpoints hang under the node, they are not takes
    assert ck.stages(hub) == [{"stage": "design", "members": ["design"]}]
    assert "design.head-page  " in mh("list", cwd=hub_project, check=0).stdout
    assert "(under design)" in mh("list", cwd=hub_project, check=0).stdout

    p = mh("checkpoint", "x", "--under", "design", "--at", "research", cwd=hub_project)
    assert p.returncode == 1 and "--at and --under" in p.stderr
    p = mh("checkpoint", "head-page", "--under", "design", cwd=hub_project)
    assert p.returncode == 1 and "already exists" in p.stderr


def test_loading_a_sub_checkpoint_loads_its_parents_too(mh, ws, hub_project):
    mh("checkpoint", "design", cwd=hub_project, check=0)
    _save(mh, ws, hub_project, SID_P, "q-design", "2026-07-10T04:00:00Z")
    mh("checkpoint", "head-page", "--under", "design", cwd=hub_project, check=0)
    _save(mh, ws, hub_project, SID_C, "q-head", "2026-07-11T04:00:00Z")
    mh("checkpoint", "main-page", "--under", "design", cwd=hub_project, check=0)
    _save(mh, ws, hub_project, SID_S, "q-main", "2026-07-12T04:00:00Z")

    mh("goto", "design.head-page", cwd=hub_project, check=0)
    out = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert "loaded: design + design.head-page |" in out
    assert "q-design" in out and "q-head" in out
    assert "q-main" not in out  # a sibling scope stays apart
    out = mh("load", "design", "--all", cwd=hub_project, check=0).stdout
    assert "q-design" in out and "q-head" not in out  # the parent alone stays the parent


def test_rename_and_delete_carry_the_subtree(mh, ws, hub_project):
    hub = hub_project / ".memoryhub"
    mh("checkpoint", "research", cwd=hub_project, check=0)
    mh("checkpoint", "design", cwd=hub_project, check=0)
    mh("checkpoint", "head-page", "--under", "design", cwd=hub_project, check=0)
    _save(mh, ws, hub_project, SID_C, "q-head", "2026-07-11T04:00:00Z")
    shown = json.loads(mh("show", "design.head-page", "--json", cwd=hub_project, check=0).stdout)
    file = shown["sessions"][0]["file"]
    mh("link", "design.head-page", "research", cwd=hub_project, check=0)
    mh("skip", f"design.head-page/{file}", cwd=hub_project, check=0)

    mh("rename", "design", "layout", cwd=hub_project, check=0)
    assert [c.slug for c in ck.list_checkpoints(hub)] == ["research", "layout", "layout.head-page"]
    assert ck.read_links(hub) == [("layout.head-page", "research")]
    assert ck.read_skips(hub) == {f"layout.head-page/{file}"}
    assert "current: layout.head-page" in mh("status", cwd=hub_project, check=0).stdout
    mh("rename", "layout.head-page", "header", cwd=hub_project, check=0)
    assert [c.slug for c in ck.list_checkpoints(hub)] == ["research", "layout", "layout.header"]
    assert "current: layout.header" in mh("status", cwd=hub_project, check=0).stdout

    p = mh("rm", "layout", cwd=hub_project)
    assert p.returncode == 1 and "1 session(s) and 1 sub-checkpoint(s)" in p.stderr
    p = mh("rm", "layout", "--force", cwd=hub_project, check=0)
    assert "deleted checkpoint layout (1 sessions, 1 sub-checkpoints)" in p.stdout
    assert [c.slug for c in ck.list_checkpoints(hub)] == ["research"]
    assert ck.read_links(hub) == [] and ck.read_skips(hub) == set()
    assert "current: research" in mh("status", cwd=hub_project, check=0).stdout


def test_a_sub_checkpoint_is_not_a_template_stage(mh, ws, hub_project):
    hub = hub_project / ".memoryhub"
    mh("template", "sdlc", cwd=hub_project, check=0)
    mh("checkpoint", cwd=hub_project, check=0)  # Planning
    mh("checkpoint", "analysis", "--under", "planning", cwd=hub_project, check=0)
    p = templates.progress(hub)
    assert p["done"] == 1 and p["next"] == "Analysis"  # named like a stage, reaches none


def test_the_map_carries_parents_and_creates_under(mh, ws, hub_project):
    hub = hub_project / ".memoryhub"
    mh("checkpoint", "design", cwd=hub_project, check=0)
    status, r = server.dispatch(
        hub, "POST", "/api/checkpoint/create", {}, {"name": "head page", "under": "design"}, False
    )
    assert status == 200 and r["slug"] == "design.head-page" and r["parent"] == "design"
    _, data = server.dispatch(hub, "GET", "/api/map", {"budget": "none"}, {}, False)
    assert [(c["slug"], c["parent"], c["name"]) for c in data["checkpoints"]] == [
        ("design", None, "design"),
        ("design.head-page", "design", "head-page"),
    ]
    assert data["stages"] == [{"stage": "design", "members": ["design"]}]
    assert data["current"] == "design.head-page"
    assert data["load"]["loaded"] == ["design", "design.head-page"]


def test_tree_loads_the_whole_node(mh, ws, hub_project):
    hub = hub_project / ".memoryhub"
    mh("checkpoint", "design", cwd=hub_project, check=0)
    _save(mh, ws, hub_project, SID_P, "q-design", "2026-07-10T04:00:00Z")
    mh("checkpoint", "head-page", "--under", "design", cwd=hub_project, check=0)
    _save(mh, ws, hub_project, SID_C, "q-head", "2026-07-11T04:00:00Z")
    mh("checkpoint", "main-page", "--under", "design", cwd=hub_project, check=0)
    _save(mh, ws, hub_project, SID_S, "q-main", "2026-07-12T04:00:00Z")

    out = mh("load", "design", "--tree", "--all", cwd=hub_project, check=0).stdout
    assert "loaded: design + design.head-page + design.main-page |" in out
    assert "q-design" in out and "q-head" in out and "q-main" in out
    # from inside the node, --tree is still the whole node: the sibling comes too
    mh("goto", "design.head-page", cwd=hub_project, check=0)
    out = mh("load", "--tree", "--all", cwd=hub_project, check=0).stdout
    assert "q-head" in out and "q-design" in out and "q-main" in out
    out = mh("load", "--all", cwd=hub_project, check=0).stdout  # without it, the scope alone
    assert "q-head" in out and "q-design" in out and "q-main" not in out

    # the session-start hook can pack the node the same way, and the map previews it
    mh("hook", "install", "--tree", cwd=hub_project, check=0)
    settings = json.loads((hub_project / ".claude" / "settings.local.json").read_text())
    assert settings["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "mh hook load --tree"
    mh("goto", "design", cwd=hub_project, check=0)
    payload = json.dumps({"cwd": str(hub_project), "source": "startup"})
    out = mh("hook", "load", "--tree", cwd=hub_project, check=0, input=payload).stdout
    assert "q-main" in out
    _, data = server.dispatch(hub, "GET", "/api/map", {"budget": "none", "tree": "1"}, {}, False)
    assert data["load"]["loaded"] == ["design", "design.head-page", "design.main-page"]
    _, data = server.dispatch(hub, "GET", "/api/map", {"budget": "none"}, {}, False)
    assert data["load"]["loaded"] == ["design"]
