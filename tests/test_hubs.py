import shutil


def test_hubs_listing_and_prune(mh, ws, project):
    mh("init", cwd=project, check=0)
    gone = ws["root"] / "gone"
    gone.mkdir()
    mh("init", cwd=gone, check=0)
    shutil.rmtree(gone / ".memoryhub")

    p = mh("hubs", cwd=project, check=0)
    assert str(project / ".memoryhub") in p.stdout
    assert "(missing)" in p.stdout

    p = mh("hubs", "--prune", cwd=project, check=0)
    assert "(missing)" not in p.stdout

    p = mh("hubs", cwd=project, check=0)
    assert "gone" not in p.stdout


def test_skill_install(mh, ws, project):
    p = mh("skill", "install", cwd=project, check=0)
    dest = ws["home"] / ".claude" / "skills" / "mh" / "SKILL.md"
    assert dest.is_file()
    assert "name: mh" in dest.read_text()
    assert str(dest) in p.stdout
    assert "pi: not detected — skipped" in p.stdout  # no ~/.pi/agent in this HOME

    (ws["home"] / ".pi" / "agent").mkdir(parents=True)
    p = mh("skill", "install", cwd=project, check=0)
    pi_dest = ws["home"] / ".pi" / "agent" / "skills" / "mh" / "SKILL.md"
    assert pi_dest.is_file()
    assert pi_dest.read_text() == dest.read_text()
    assert str(pi_dest) in p.stdout
