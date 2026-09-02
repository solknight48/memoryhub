"""The composer's projection of the CLI: its skills and commands read from
disk (`commands.py`), and the palette's parsing and ranking run from the
shipped page. Everything here is hermetic — a fabricated home and project —
because the real home has forty skills that change under the tests' feet.
"""

from __future__ import annotations

from pathlib import Path

from conftest import make_records, needs_node, run_ui_js, write_transcript
from memoryhub import commands, server
from memoryhub import live as livemod

SID = "cccccccc-1111-4111-8111-111111111111"


def skill(root: Path, name: str, description: str, *, frontmatter_name: str | None = None):
    d = root / name
    d.mkdir(parents=True)
    fm = f"name: {frontmatter_name}\n" if frontmatter_name else ""
    (d / "SKILL.md").write_text(f"---\n{fm}description: {description}\n---\n\nBody.\n")


# --- discovery ---------------------------------------------------------------


def test_claude_skills_commands_plugins_and_builtins_in_that_order(ws):
    home, project = ws["home"], ws["root"] / "proj"
    skill(project / ".claude" / "skills", "local", "a project skill")
    skill(home / ".claude" / "skills", "mh", "memory")
    skill(home / ".claude" / "skills", "dir-name", "named by frontmatter", frontmatter_name="mh-ui")
    (home / ".claude" / "commands").mkdir()
    (home / ".claude" / "commands" / "afml.md").write_text(
        '---\ndescription: quant code\nargument-hint: "<task>"\n---\nLaunch the agent.\n'
    )
    plug = home / "plug" / "hey" / "1.0"
    skill(plug / "skills", "hey", "mail")
    (home / ".claude" / "plugins").mkdir()
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        f'{{"version": 2, "plugins": {{"hey@37signals": [{{"installPath": "{plug}"}}]}}}}'
    )

    out = commands.commands("claude", project, home)
    assert out["known"] is True and out["agent"] == "claude"
    names = [c["name"] for c in out["commands"]]
    assert names[:5] == ["local", "mh", "mh-ui", "afml", "hey:hey"]
    assert names[5:] == [n for n, _, _ in commands.CLAUDE_BUILTINS]
    by = {c["name"]: c for c in out["commands"]}
    assert by["local"]["kind"] == "skill" and by["local"]["where"] == "project"
    assert by["mh-ui"]["where"] == "user"
    assert by["afml"] == {
        "name": "afml",
        "kind": "command",
        "where": "user",
        "description": "quant code",
        "hint": "<task>",
    }
    assert by["hey:hey"]["kind"] == "plugin" and by["hey:hey"]["where"] == "hey"
    assert by["model"]["kind"] == "builtin" and by["model"]["hint"] == "<model>"
    assert [m["name"] for m in out["models"]] == ["default", "opus", "sonnet", "haiku"]


def test_the_projects_skill_shadows_the_users_of_the_same_name(ws):
    home, project = ws["home"], ws["root"] / "proj"
    skill(project / ".claude" / "skills", "mh", "the project's")
    skill(home / ".claude" / "skills", "mh", "the user's")
    out = commands.commands("claude", project, home)
    mine = [c for c in out["commands"] if c["name"] == "mh"]
    assert len(mine) == 1 and mine[0]["description"] == "the project's"


def test_a_folded_description_is_one_line_and_a_long_one_is_clipped(ws):
    home, project = ws["home"], ws["root"] / "proj"
    d = home / ".claude" / "skills" / "folded"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: folded\ndescription: >-\n  Start the UI.\n  Costs one command.\n\n"
        "  Second paragraph.\nallowed-tools: Bash\n---\n"
    )
    d = home / ".claude" / "skills" / "long"
    d.mkdir()
    (d / "SKILL.md").write_text("---\ndescription: " + "word " * 80 + "\n---\n")
    d = home / ".claude" / "skills" / "bare"
    d.mkdir()
    (d / "SKILL.md").write_text("# Bare\n\nNo frontmatter, just prose.\n")
    by = {c["name"]: c for c in commands.commands("claude", project, home)["commands"]}
    assert by["folded"]["description"] == "Start the UI. Costs one command. Second paragraph."
    assert len(by["long"]["description"]) == commands.DESCRIPTION_MAX
    assert by["long"]["description"].endswith("…")
    assert by["bare"]["description"] == "Bare"  # the first line of prose, heading marks off


def test_pi_lists_its_skills_and_nothing_it_has_not_verified(ws):
    home, project = ws["home"], ws["root"] / "proj"
    skill(home / ".pi" / "agent" / "skills", "mh", "memory")
    skill(project / ".pi" / "skills", "local", "project")
    out = commands.commands("pi", project, home)
    assert out["known"] is True
    found = [(c["name"], c["where"]) for c in out["commands"]]
    assert found == [("local", "project"), ("mh", "user")]
    assert out["models"] == []  # no /model for pi: not verified, so not offered


def test_an_unverified_agent_gets_no_list_rather_than_a_guess(ws):
    home, project = ws["home"], ws["root"] / "proj"
    skill(home / ".codex" / "skills", "hey", "mail")
    assert commands.commands("codex", project, home) == {
        "agent": "codex",
        "known": False,
        "commands": [],
        "models": [],
    }


def test_a_broken_plugin_registry_is_ignored(ws):
    home, project = ws["home"], ws["root"] / "proj"
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text("{not json")
    out = commands.commands("claude", project, home)
    assert [c["kind"] for c in out["commands"]] == ["builtin"] * len(commands.CLAUDE_BUILTINS)


def test_the_api_serves_the_list_for_the_followed_sessions_agent(mh, ws, hub_project):
    skill(ws["home"] / ".claude" / "skills", "mh", "memory")
    livemod._discovery.clear()
    write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")], cwd=str(hub_project)))
    hub = hub_project / ".memoryhub"
    status, out = server.dispatch(hub, "GET", "/api/live/commands", {}, {}, False)
    assert status == 200 and out["agent"] == "claude"
    assert out["commands"][0]["name"] == "mh"
    # readable in --read-only too: it is a list, not a mutation
    status, _ = server.dispatch(hub, "GET", "/api/live/commands", {}, {}, True)
    assert status == 200


# --- the palette, from the page ----------------------------------------------


@needs_node
def test_a_message_is_a_command_only_while_it_is_one_line_starting_with_a_slash():
    texts = ["/", "/mh", "/mh ", "/mh save dev", "/model op", "hi", "/mh\nmore", ""]
    out = run_ui_js(slashState=texts)
    assert out["slashState"] == [
        {"name": "", "args": None},
        {"name": "mh", "args": None},
        {"name": "mh", "args": ""},
        {"name": "mh", "args": "save dev"},
        {"name": "model", "args": "op"},
        None,
        None,
        None,
    ]


@needs_node
def test_matches_rank_the_name_over_the_description_and_keep_list_order():
    items = [
        {"name": "mh-ui", "description": "the map"},
        {"name": "zzz", "description": "mentions mh in passing"},
        {"name": "mh", "description": "memory"},
        {"name": "omh", "description": "contains it"},
        {"name": "other", "description": "nothing"},
    ]
    out = run_ui_js(paletteMatches=[[items, "mh"], [items, ""], [items, "MH-"], [items, "nope"]])
    assert [i["name"] for i in out["paletteMatches"][0]] == ["mh", "mh-ui", "omh", "zzz"]
    assert [i["name"] for i in out["paletteMatches"][1]] == [i["name"] for i in items]
    assert [i["name"] for i in out["paletteMatches"][2]] == ["mh-ui"]  # case does not matter
    assert out["paletteMatches"][3] == []
