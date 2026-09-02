"""Stage templates: default checkpoint names, created in order.

The rule under test is small — the next stage is the first whose checkpoint is
missing — but three surfaces depend on it (the bare `mh checkpoint`, `mh
status`, the map's dashed nodes), so it is pinned once here and the surfaces
are checked against it.
"""

from __future__ import annotations

import json

import pytest

from conftest import git_run
from memoryhub import checkpoint as ck
from memoryhub import server, templates
from memoryhub.hub import MhError


def hub_of(project):
    return project / ".memoryhub"


# --- the module ---------------------------------------------------------------


def test_every_template_has_unique_clean_slugs():
    for t in templates.TEMPLATES.values():
        slugs = [ck.slugify(s) for s, _ in t.stages]
        assert len(set(slugs)) == len(slugs), t.name
        assert all("-" not in s[:1] and s == s.strip("-") for s in slugs)
        assert all(about for _, about in t.stages), f"{t.name}: a stage without a gloss"


def test_choosing_a_template_records_a_copy_of_its_stages_in_the_journal(ws, hub_project):
    hub = hub_of(hub_project)
    assert templates.read(hub) is None and templates.progress(hub) is None
    rec = templates.use(hub, "Quant")  # case does not matter
    assert rec["name"] == "quant"
    assert rec["stages"][:3] == ["Research", "Design", "Data Engineering"]
    assert templates.path(hub).is_file()
    log = git_run(hub, ws["env"], "log", "--oneline", "-1")
    assert "template: quant" in log
    assert git_run(hub, ws["env"], "status", "--porcelain").strip() == ""


def test_progress_names_the_first_missing_stage_even_after_a_stage_out_of_turn(ws, hub_project):
    hub = hub_of(hub_project)
    templates.use(hub, "hotfix")
    assert templates.next_name(hub) == "Reproduce"
    ck.create(hub, "Reproduce")
    ck.create(hub, "Fix Development")  # out of turn
    p = templates.progress(hub)
    assert p["done"] == 2 and p["total"] == 6 and p["next"] == "Root Cause Analysis"
    assert [s["exists"] for s in p["stages"]] == [True, False, True, False, False, False]
    assert p["stages"][2]["slug"] == "fix-development"


def test_when_every_stage_exists_a_bare_checkpoint_says_so(ws, hub_project):
    hub = hub_of(hub_project)
    templates.use(hub, "hotfix")
    for name, _ in templates.TEMPLATES["hotfix"].stages:
        ck.create(hub, name)
    assert templates.progress(hub)["next"] is None
    with pytest.raises(MhError, match="every stage of the hotfix template exists"):
        templates.next_name(hub)


def test_the_file_is_the_projects_own_sequence_once_edited(ws, hub_project):
    hub = hub_of(hub_project)
    templates.use(hub, "sdlc")
    templates.path(hub).write_text('name = "mine"\nstages = ["Idea", "Ship 它"]\n')
    p = templates.progress(hub)
    assert p["name"] == "mine" and [s["slug"] for s in p["stages"]] == ["idea", "ship-它"]
    assert templates.next_name(hub) == "Idea"


def test_a_broken_file_and_an_unknown_name_are_refused(ws, hub_project):
    hub = hub_of(hub_project)
    with pytest.raises(MhError, match="no template 'nope'"):
        templates.use(hub, "nope")
    templates.path(hub).write_text("stages = 3\n")
    with pytest.raises(MhError, match="'stages' must be a list"):
        templates.progress(hub)
    templates.path(hub).write_text("not toml [\n")
    with pytest.raises(MhError, match="not readable"):
        templates.read(hub)


def test_clearing_removes_the_file_and_is_a_commit(ws, hub_project):
    hub = hub_of(hub_project)
    assert templates.clear(hub) is False
    templates.use(hub, "ml")
    assert templates.clear(hub) is True
    assert not templates.path(hub).exists()
    assert "template: none" in git_run(hub, ws["env"], "log", "--oneline", "-1")


# --- the CLI ------------------------------------------------------------------


def test_bare_mh_checkpoint_walks_the_template(mh, ws, hub_project):
    out = mh("checkpoint", cwd=hub_project, check=1).stderr
    assert "a name is needed" in out and "mh template" in out

    mh("template", "quant", cwd=hub_project, check=0)
    first = mh("checkpoint", cwd=hub_project, check=0).stdout
    assert "checkpoint 'research' created (current)" in first
    assert "stage 1 of 9 in quant — next: Design" in first
    second = json.loads(mh("checkpoint", "--json", cwd=hub_project, check=0).stdout)
    assert second["checkpoint"] == "design"
    expected = {"name": "quant", "done": 2, "total": 9, "next": "Data Engineering"}
    assert second["template"] == expected

    shown = mh("template", cwd=hub_project, check=0).stdout
    assert "template: quant — 2 of 9 stages created" in shown
    assert "✓  1. Research" in shown and "→  3. Data Engineering" in shown
    status = mh("status", cwd=hub_project, check=0).stdout
    assert "template: quant — 2 of 9 stages · next: Data Engineering" in status
    status_json = json.loads(mh("status", "--json", cwd=hub_project, check=0).stdout)
    assert status_json["template"]["next"] == "Data Engineering"

    # a named checkpoint still works, and is not a stage
    named = mh("checkpoint", "spike", cwd=hub_project, check=0).stdout
    assert "checkpoint 'spike' created (current)" in named and "stage" not in named

    assert "template cleared" in mh("template", "--clear", cwd=hub_project, check=0).stdout
    assert "no template" in mh("template", cwd=hub_project, check=0).stdout


def test_mh_template_list_shows_every_template_and_needs_no_hub(mh, ws):
    out = mh("template", "--list", cwd=ws["root"], check=0).stdout
    for name in templates.TEMPLATES:
        assert f"\n{name:10}" in "\n" + out
    assert "1. Research — hypothesis" in out
    listed = json.loads(mh("template", "--list", "--json", cwd=ws["root"], check=0).stdout)
    assert [t["name"] for t in listed] == list(templates.TEMPLATES)


def test_mh_init_takes_a_template(mh, ws, project):
    out = mh("init", "--template", "sdlc", cwd=project, check=0).stdout
    assert "template: sdlc — Planning → Analysis → Design" in out
    assert templates.read(hub_of(project))["name"] == "sdlc"
    # an unknown template fails before the hub is created
    other = ws["root"] / "other"
    other.mkdir()
    err = mh("init", "--template", "nope", cwd=other, check=1).stderr
    assert "no template 'nope'" in err and not (other / ".memoryhub").exists()


# --- the map ----------------------------------------------------------------


def test_the_map_carries_the_progress_and_the_catalogue(ws, hub_project):
    hub = hub_of(hub_project)
    status, data = server.dispatch(hub, "GET", "/api/map", {}, {}, False)
    assert status == 200 and data["template"] is None
    assert [t["name"] for t in data["templates"]] == list(templates.TEMPLATES)

    status, rec = server.dispatch(hub, "POST", "/api/template", {}, {"name": "hotfix"}, False)
    assert status == 200 and rec["name"] == "hotfix"
    server.dispatch(hub, "POST", "/api/checkpoint/create", {}, {"name": "Reproduce"}, False)
    _, data = server.dispatch(hub, "GET", "/api/map", {}, {}, False)
    assert data["template"]["next"] == "Root Cause Analysis"
    assert [s["exists"] for s in data["template"]["stages"]][:2] == [True, False]

    status, rec = server.dispatch(hub, "POST", "/api/template", {}, {"name": None}, False)
    assert status == 200 and rec == {"name": None}
    assert templates.read(hub) is None
    # read-only: the picker is a mutation
    status, _ = server.dispatch(hub, "POST", "/api/template", {}, {"name": "ml"}, True)
    assert status == 403
