import subprocess

from conftest import TIMEOUT, git_run, make_records, write_transcript

SID = "abab1111-0000-4000-8000-0000000000ab"


def test_sync_requires_remote(mh, hub_project):
    p = mh("sync", cwd=hub_project)
    assert p.returncode == 1
    assert "no remote configured" in p.stderr
    assert "remote add origin" in p.stderr


def test_sync_happy_path_and_conflict_autoabort(mh, ws, hub_project, tmp_path):
    env = ws["env"]
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        env=env,
        check=True,
        capture_output=True,
        timeout=TIMEOUT,
    )
    hub_a = hub_project / ".memoryhub"
    git_run(hub_a, env, "remote", "add", "origin", str(bare))

    # content so the checkpoint dir is present in git (empty dirs are not)
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID, make_records([("q", "a")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)

    p = mh("sync", cwd=hub_project, check=0)
    assert "sync complete" in p.stdout
    assert int(git_run(bare, env, "rev-list", "--count", "main").strip()) >= 3

    # second machine: a clone of the hub inside another project dir
    proj_b = ws["root"] / "proj-b"
    proj_b.mkdir()
    subprocess.run(
        ["git", "clone", str(bare), str(proj_b / ".memoryhub")],
        env=env,
        check=True,
        capture_output=True,
        timeout=TIMEOUT,
    )

    # A: link alpha--beta, sync (advances the remote)
    mh("checkpoint", "beta", cwd=hub_project, check=0)
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    mh("sync", cwd=hub_project, check=0)

    # B (stale): conflicting links.toml, then sync -> rebase conflict -> auto-abort
    mh("checkpoint", "gamma", cwd=proj_b, check=0)
    mh("link", "alpha", "gamma", cwd=proj_b, check=0)
    p = mh("sync", cwd=proj_b)
    assert p.returncode == 1
    assert "hub restored to your local state" in p.stderr
    hub_b = proj_b / ".memoryhub"
    assert not (hub_b / ".git" / "rebase-merge").exists()
    assert not (hub_b / ".git" / "rebase-apply").exists()
    assert "link: alpha -- gamma" in git_run(hub_b, env, "log", "--oneline", "-n", "3")


def test_sync_refuses_dirty_manual_edits(mh, ws, hub_project, tmp_path):
    env = ws["env"]
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        env=env,
        check=True,
        capture_output=True,
        timeout=TIMEOUT,
    )
    hub = hub_project / ".memoryhub"
    git_run(hub, env, "remote", "add", "origin", str(bare))
    (hub / "README.md").write_text("hand-edited\n")
    p = mh("sync", cwd=hub_project)
    assert p.returncode == 1
    assert "uncommitted manual edits" in p.stderr
