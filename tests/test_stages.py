"""Stages: several checkpoints at one column of the timeline.

The name decides — design, design-2, design-3 stack under one node — and
`--at` places a checkpoint at a column its name does not say. Everything else
(load, links, current) treats them as the independent checkpoints they are.
"""

from __future__ import annotations

import json

import pytest

from conftest import git_run
from memoryhub import checkpoint as ck
from memoryhub import curate, server, templates
from memoryhub.hub import MhError


def hub_of(project):
    return project / ".memoryhub"


# --- the rule ------------------------------------------------------------------


def test_a_trailing_number_is_another_take_at_the_same_stage(ws, hub_project):
    hub = hub_of(hub_project)
    for name in ("design", "design 2", "design-3", "v2", "data-2024"):
        ck.create(hub, name)
    assert ck.stage_of(hub, "design") == "design"
    assert ck.stage_of(hub, "design-2") == "design"
    assert ck.stage_of(hub, "design-3") == "design"
    assert ck.stage_of(hub, "v2") == "v2"  # no hyphen: a name, not a take
    assert ck.stage_of(hub, "data-2024") == "data"
    assert ck.stages(hub) == [
        {"stage": "design", "members": ["design", "design-2", "design-3"]},
        {"stage": "v2", "members": ["v2"]},
        {"stage": "data", "members": ["data-2024"]},
    ]
    assert not ck.stages_path(hub).exists()  # nothing explicit was needed


def test_at_places_a_checkpoint_where_its_name_does_not_say(ws, hub_project):
    hub = hub_of(hub_project)
    ck.create(hub, "research")
    ck.create(hub, "dollar-bars", stage="Research")
    ck.create(hub, "research-2", stage="research")  # the name already says it
    assert ck.read_stages(hub) == {"dollar-bars": "research"}
    assert ck.stages(hub) == [
        {"stage": "research", "members": ["research", "dollar-bars", "research-2"]}
    ]
    assert "stages.toml" in git_run(hub, ws["env"], "show", "--stat", "HEAD~1")


def test_a_column_sits_where_its_first_checkpoint_was_created(ws, hub_project):
    hub = hub_of(hub_project)
    ck.create(hub, "alpha")
    ck.create(hub, "beta")
    ck.create(hub, "alpha-2")  # created last, drawn under alpha, before beta
    assert [c["stage"] for c in ck.stages(hub)] == ["alpha", "beta"]


def test_next_at_numbers_the_takes(ws, hub_project):
    hub = hub_of(hub_project)
    assert ck.next_at(hub, "Design") == "design"  # nothing there yet: the stage's own name
    ck.create(hub, "design")
    assert ck.next_at(hub, "design") == "design-2"
    ck.create(hub, "design-2")
    ck.create(hub, "design-4")
    assert ck.next_at(hub, "design") == "design-3"  # the first free number
    ck.create(hub, "spike", stage="build")
    assert ck.next_at(hub, "build") == "build-2"  # a column with no node of its own name


# --- surgery keeps the placements honest -------------------------------------


def test_rename_and_delete_follow_the_placement(ws, hub_project):
    hub = hub_of(hub_project)
    ck.create(hub, "research")
    ck.create(hub, "dollar-bars", stage="research")
    curate.rename_checkpoint(hub, "dollar-bars", "volume-bars")
    assert ck.read_stages(hub) == {"volume-bars": "research"}
    # a rename that lands in another column by name keeps the column it had
    ck.create(hub, "design")
    ck.create(hub, "design-2")
    curate.rename_checkpoint(hub, "design-2", "alt-design")
    assert ck.stage_of(hub, "alt-design") == "design"
    curate.delete_checkpoint(hub, "volume-bars")
    assert ck.read_stages(hub) == {"alt-design": "design"}


def test_the_template_counts_a_stage_reached_by_any_take(ws, hub_project):
    hub = hub_of(hub_project)
    templates.use(hub, "sdlc")
    ck.create(hub, "planning")
    ck.create(hub, "analysis-2")  # the stage's name itself never created
    p = templates.progress(hub)
    assert [s["exists"] for s in p["stages"]][:3] == [True, True, False]
    assert p["next"] == "Design"


# --- the CLI and the map -------------------------------------------------------


def test_mh_checkpoint_at(mh, ws, hub_project):
    mh("checkpoint", "design", cwd=hub_project, check=0)
    out = mh("checkpoint", "--at", "design", cwd=hub_project, check=0).stdout
    assert "checkpoint 'design-2' created (current) — at design, with design" in out
    out = mh("checkpoint", "dollar-bars", "--at", "design", cwd=hub_project, check=0).stdout
    assert "at design, with design, design-2" in out
    listed = mh("list", cwd=hub_project, check=0).stdout
    assert "design-2" in listed and "(at design)" in listed
    rows = json.loads(mh("list", "--json", cwd=hub_project, check=0).stdout)
    assert [(r["checkpoint"], r["stage"]) for r in rows] == [
        ("design", "design"),
        ("design-2", "design"),
        ("dollar-bars", "design"),
    ]
    with pytest.raises(MhError):
        ck.create(hub_of(hub_project), "design-2")  # still one slug each


def test_the_map_carries_columns_and_creates_takes(ws, hub_project):
    hub = hub_of(hub_project)
    server.dispatch(hub, "POST", "/api/checkpoint/create", {}, {"name": "design"}, False)
    status, r = server.dispatch(hub, "POST", "/api/checkpoint/create", {}, {"at": "design"}, False)
    assert status == 200 and r == {"slug": "design-2", "created": r["created"], "stage": "design"}
    status, r = server.dispatch(
        hub, "POST", "/api/checkpoint/create", {}, {"name": "bars", "at": "design"}, False
    )
    assert r["slug"] == "bars" and r["stage"] == "design"
    _, data = server.dispatch(hub, "GET", "/api/map", {}, {}, False)
    assert data["stages"] == [{"stage": "design", "members": ["design", "design-2", "bars"]}]
    assert [c["stage"] for c in data["checkpoints"]] == ["design"] * 3
    with pytest.raises(MhError, match="missing 'name'"):
        server.dispatch(hub, "POST", "/api/checkpoint/create", {}, {}, False)
