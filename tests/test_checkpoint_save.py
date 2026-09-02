import json
import os
import time

from conftest import (
    make_pi_records,
    make_records,
    write_pi_transcript,
    write_transcript,
)

SID_A = "a1b2c3d4-1111-4111-8111-111111111111"
SID_B = "b2c3d4e5-2222-4222-8222-222222222222"


def _checkpoints_dir(project):
    return project / ".memoryhub" / "checkpoints"


def test_checkpoint_create_and_collision(mh, hub_project):
    p = mh("checkpoint", "Data Pipeline", cwd=hub_project, check=0)
    assert "checkpoint 'data-pipeline' created (current)" in p.stdout
    p = mh("checkpoint", "data pipeline", cwd=hub_project)
    assert p.returncode == 1
    assert "already exists" in p.stderr


def test_checkpoint_names_can_be_chinese(mh, ws, hub_project):
    p = mh("checkpoint", "数据管道", cwd=hub_project, check=0)
    assert "checkpoint '数据管道' created (current)" in p.stdout
    tr = write_transcript(ws["home"], hub_project, SID_A, make_records([("你好", "世界")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    out = mh("load", cwd=hub_project, check=0).stdout
    assert "loaded: 数据管道" in out and "你好" in out
    # mixed and fullwidth names slug like anything else; punctuation folds away
    p = mh("checkpoint", "回测：v２", cwd=hub_project, check=0)
    assert "'回测-v2'" in p.stdout


def test_checkpoint_name_without_any_letters_fails(mh, hub_project):
    p = mh("checkpoint", "!!!", cwd=hub_project)
    assert p.returncode == 1
    assert "letters or digits" in p.stderr


def test_save_requires_current(mh, hub_project):
    p = mh("save", cwd=hub_project)
    assert p.returncode == 1
    assert "no current checkpoint" in p.stderr


def test_save_from_transcript(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID_A, make_records([("hello", "world")]))
    p = mh("save", "--transcript", tr, cwd=hub_project, check=0)
    assert "-> alpha (1 sessions)" in p.stdout
    ckdir = next(d for d in _checkpoints_dir(hub_project).iterdir() if d.is_dir())
    files = list(ckdir.glob("*.md"))
    assert len(files) == 1
    assert files[0].name == "2026-07-10_0401_a1b2c3d4.md"
    body = files[0].read_text()
    assert "## User 1" in body and "hello" in body and "world" in body


def test_save_project_scoped_fallback(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    p = mh("save", cwd=hub_project)
    assert p.returncode == 1
    assert "no transcripts found for this project" in p.stderr

    write_transcript(
        ws["home"],
        hub_project,
        SID_B,
        make_records([("q1", "a1")], start="2026-07-11T09:00:00Z"),
    )
    p = mh("save", cwd=hub_project, check=0)
    assert "b2c3d4e5" in p.stdout


def test_resave_replaces_same_session(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID_A, make_records([("q", "a")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    tr = write_transcript(
        ws["home"], hub_project, SID_A, make_records([("q", "a"), ("more", "stuff")])
    )
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    ckdir = next(d for d in _checkpoints_dir(hub_project).iterdir() if d.is_dir())
    files = list(ckdir.glob("*_a1b2c3d4.md"))
    assert len(files) == 1
    assert files[0].name == "2026-07-10_0403_a1b2c3d4.md"
    assert "more" in files[0].read_text()


def test_save_to_and_file_import(mh, hub_project, tmp_path):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    mh("checkpoint", "beta", cwd=hub_project, check=0)  # current is now beta
    doc = tmp_path / "notes.md"
    doc.write_text("# external context\n")
    p = mh("save", "--file", doc, "--to", "alpha", cwd=hub_project, check=0)
    assert "-> alpha" in p.stdout
    alpha = next(d for d in _checkpoints_dir(hub_project).iterdir() if d.name.endswith("_alpha"))
    assert list(alpha.glob("*_notes.md"))


def test_save_fallback_picks_newest_across_agents(mh, ws, hub_project):
    """A pi session running `mh save` has no CLAUDE_CODE_SESSION_ID; the
    fallback must find the newest transcript across ALL agents — which is the
    live session itself."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    pi_sid = "019f596e-94d6-7332-bc08-d07aa8782001"
    cl = write_transcript(ws["home"], hub_project, SID_A, make_records([("cl-q", "cl-a")]))
    pi = write_pi_transcript(
        ws["home"],
        hub_project,
        pi_sid,
        make_pi_records([("pi-q", "pi-a")], cwd=str(hub_project)),
    )
    now = time.time()
    os.utime(cl, (now - 100, now - 100))
    os.utime(pi, (now, now))

    p = mh("save", cwd=hub_project, check=0)
    assert "pi-019f596e94d6" in p.stdout
    ckdir = next(d for d in _checkpoints_dir(hub_project).iterdir() if d.is_dir())
    saved = next(ckdir.glob("*_pi-*.md"))
    assert "pi-q" in saved.read_text()

    # explicit --transcript with a pi file: schema auto-detected
    p = mh("save", "--transcript", pi, cwd=hub_project, check=0)
    assert "pi-019f596e94d6" in p.stdout


def test_list_output_and_json(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID_A, make_records([("q", "a")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    mh("checkpoint", "beta", cwd=hub_project, check=0)

    p = mh("list", cwd=hub_project, check=0)
    assert "alpha" in p.stdout and "beta" in p.stdout
    beta_line = next(line for line in p.stdout.splitlines() if "beta" in line)
    assert beta_line.lstrip().startswith("*")  # current marker
    alpha_line = next(line for line in p.stdout.splitlines() if "alpha" in line)
    assert "2026-07-10 04:01" in alpha_line  # last save shown per checkpoint
    assert "—" in beta_line  # no sessions yet

    data = json.loads(mh("list", "--json", cwd=hub_project, check=0).stdout)
    assert [d["checkpoint"] for d in data] == ["alpha", "beta"]
    assert data[0]["sessions"] == 1
    assert data[0]["last_save"] == "2026-07-10_0401"
    assert data[1]["last_save"] is None
    assert data[1]["current"] is True


def test_show_checkpoint_and_session(mh, ws, hub_project):
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID_A, make_records([("needle-q", "needle-a")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    p = mh("show", "alpha", cwd=hub_project, check=0)
    assert "needle-q" in p.stdout and "mh session: alpha/" in p.stdout
    p = mh("show", "alpha/2026-07-10", cwd=hub_project, check=0)
    assert "needle-a" in p.stdout
    p = mh("show", "alpha/zzz", cwd=hub_project)
    assert p.returncode == 1
    assert "no session" in p.stderr


def test_a_saved_session_lives_in_one_checkpoint(mh, ws, hub_project):
    """The policy every save path shares: a plain `mh save` follows the session
    to where it already lives even after the current pointer moved on, and an
    explicit other target moves it — never a second copy."""
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, SID_A, make_records([("q", "a")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    mh("checkpoint", "beta", cwd=hub_project, check=0)  # current is now beta

    tr = write_transcript(
        ws["home"], hub_project, SID_A, make_records([("q", "a"), ("more", "stuff")])
    )
    p = mh("save", "--transcript", tr, cwd=hub_project, check=0)
    assert "-> alpha" in p.stdout
    alpha = next(d for d in _checkpoints_dir(hub_project).iterdir() if d.name.endswith("_alpha"))
    beta = next(d for d in _checkpoints_dir(hub_project).iterdir() if d.name.endswith("_beta"))
    assert len(list(alpha.glob("*_a1b2c3d4.md"))) == 1 and not list(beta.glob("*.md"))

    p = mh("save", "--to", "beta", "--transcript", tr, cwd=hub_project, check=0)
    assert "-> beta" in p.stdout and "moved from alpha" in p.stdout
    assert not list(alpha.glob("*.md")) and len(list(beta.glob("*_a1b2c3d4.md"))) == 1
    journal = mh("log", cwd=hub_project, check=0).stdout
    assert "(moved from alpha)" in journal
