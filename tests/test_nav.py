from conftest import git_run, make_records, write_transcript

SID_OLD = "ffff0000-0000-4000-8000-00000000000f"


def test_walk_back_forward_goto(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("checkpoint", "gamma", cwd=hub_project, check=0)

    p = mh("back", cwd=hub_project, check=0)
    assert "now at 'beta'" in p.stdout and "2 of 3" in p.stdout
    mh("back", cwd=hub_project, check=0)
    p = mh("back", cwd=hub_project)
    assert p.returncode == 1
    assert "already at the oldest checkpoint" in p.stderr

    p = mh("forward", "2", cwd=hub_project, check=0)
    assert "now at 'gamma'" in p.stdout
    p = mh("forward", cwd=hub_project)
    assert p.returncode == 1
    assert "already at the newest checkpoint" in p.stderr

    p = mh("goto", "al", cwd=hub_project, check=0)  # unique prefix
    assert "now at 'alpha'" in p.stdout
    p = mh("goto", "2", cwd=hub_project, check=0)  # index
    assert "now at 'beta'" in p.stdout

    mh("checkpoint", "alps", cwd=hub_project, check=0)
    p = mh("goto", "al", cwd=hub_project)
    assert p.returncode == 1
    assert "ambiguous checkpoint" in p.stderr

    # the pointer is untracked local state: hub tree stays clean
    porcelain = git_run(hub_project / ".memoryhub", ws["env"], "status", "--porcelain")
    assert porcelain.strip() == ""


def test_status_reports_position_links_staleness(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(
        ws["home"],
        hub_project,
        SID_OLD,
        make_records([("old q", "old a")], start="2020-01-01T00:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    mh("back", cwd=hub_project, check=0)

    out = mh("status", cwd=hub_project, check=0).stdout
    assert "current: alpha (1 of 2)" in out
    assert "linked: + beta" in out
    assert "checkpoints: 2 · sessions: 1 · links: 1" in out
    assert "stale" in out  # 2020 save is long past the 7-day threshold
    assert "origin: not configured" in out


def test_status_without_current(mh, hub_project):
    out = mh("status", cwd=hub_project, check=0).stdout
    assert "current: none" in out
    assert "last save: never" in out
