def test_no_hub_exit2(mh, ws):
    d = ws["root"] / "plain"
    d.mkdir()
    p = mh("status", cwd=d)
    assert p.returncode == 2
    assert "no hub found (run 'mh init' to create one)" in p.stderr


def test_init_creates_hub(mh, ws, project):
    p = mh("init", cwd=project, check=0)
    hub = project / ".memoryhub"
    assert (hub / ".git").is_dir()
    assert (hub / "README.md").is_file()
    assert (hub / ".gitignore").read_text() == "/current\n"
    assert (hub / "checkpoints").is_dir()
    exclude = project / ".git" / "info" / "exclude"
    assert "/.memoryhub/" in exclude.read_text()
    registry = ws["home"] / ".config" / "memoryhub" / "hubs.toml"
    assert str(hub) in registry.read_text()
    assert "initialized hub at" in p.stdout
    assert "## Memory" in p.stdout  # CLAUDE.md snippet printed


def test_init_idempotent_no_duplicate_exclude(mh, project):
    mh("init", cwd=project, check=0)
    p = mh("init", cwd=project, check=0)
    assert "already initialized" in p.stdout
    exclude = (project / ".git" / "info" / "exclude").read_text()
    assert exclude.count("/.memoryhub/") == 1


def test_init_from_subdir_lands_at_toplevel(mh, project):
    sub = project / "src" / "deep"
    sub.mkdir(parents=True)
    mh("init", cwd=sub, check=0)
    assert (project / ".memoryhub" / ".git").is_dir()


def test_init_without_project_git(mh, ws):
    d = ws["root"] / "nogit"
    d.mkdir()
    mh("init", cwd=d, check=0)
    assert (d / ".memoryhub" / ".git").is_dir()


def test_init_claude_appends_once(mh, project):
    mh("init", "--claude", cwd=project, check=0)
    text = (project / "CLAUDE.md").read_text()
    assert "## Memory" in text
    mh("init", "--claude", cwd=project, check=0)
    assert (project / "CLAUDE.md").read_text().count("## Memory") == 1


def test_discovery_nearest_wins_and_global_via_walk(mh, ws, project):
    mh("init", "--global", cwd=ws["home"], check=0)
    deep = ws["home"] / "somewhere" / "deep"
    deep.mkdir(parents=True)
    p = mh("status", cwd=deep, check=0)
    assert str(ws["home"] / ".memoryhub") in p.stdout

    mh("init", cwd=project, check=0)
    sub = project / "src"
    sub.mkdir()
    p = mh("status", cwd=sub, check=0)
    assert str(project / ".memoryhub") in p.stdout


def test_mh_hub_override(mh, ws, project):
    mh("init", cwd=project, check=0)
    other = ws["root"] / "elsewhere"
    other.mkdir()
    p = mh(
        "status",
        cwd=other,
        env_extra={"MH_HUB": str(project / ".memoryhub")},
        check=0,
    )
    assert str(project / ".memoryhub") in p.stdout

    p = mh("status", cwd=other, env_extra={"MH_HUB": str(ws["root"] / "nope")})
    assert p.returncode == 2
    assert "is not an initialized hub" in p.stderr
