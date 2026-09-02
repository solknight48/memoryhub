import json

from conftest import (
    dump_jsonl,
    make_pi_records,
    make_records,
    write_codex_rollout,
    write_pi_transcript,
    write_transcript,
)
from memoryhub.purify import encode_project_dir

CL_SID = "11aa22bb-0000-4000-8000-000000000001"
PI_SID = "019f596e-94d6-7332-bc08-d07aa8782001"
PI_EMPTY = "019f60aa-11d6-7332-bc08-d07aa8782002"
CX_SID = "019dee2a-7fd6-77e0-a429-ed6600000001"
CX_SUB = "019dee2a-7fd6-77e0-a429-ed6600000002"


def _seed_all_agents(ws, root):
    home = ws["home"]
    write_transcript(
        home,
        root,
        CL_SID,
        make_records([("cl-q", "cl-a")], start="2026-07-01T04:00:00Z"),
    )
    write_pi_transcript(
        home,
        root,
        PI_SID,
        make_pi_records([("pi-q", "pi-a")], start="2026-07-02T04:00:00Z", cwd=str(root)),
    )
    write_pi_transcript(
        home,
        root,
        PI_EMPTY,
        make_pi_records([], start="2026-07-05T04:00:00Z", cwd=str(root)),
        stamp_name="2026-07-05T04-00-00-000Z",
    )
    write_codex_rollout(home, root, CX_SID, [("cx-q", "cx-a")], start="2026-07-03T04:00:00Z")
    write_codex_rollout(
        home,
        root,
        CX_SUB,
        [("sub-q", "sub-a")],
        start="2026-07-04T04:00:00Z",
        subagent=True,
    )


def test_import_all_agents_dry_run_then_real(mh, ws, hub_project):
    root = hub_project
    _seed_all_agents(ws, root)

    p = mh("import", "--dry-run", cwd=root, check=0)
    assert "would import claude:" in p.stdout
    assert "would import pi:" in p.stdout
    assert "would import codex:" in p.stdout
    assert "sub-q" not in p.stdout  # codex subagent rollout skipped
    assert "1 with no dialog" in p.stdout
    assert not any((root / ".memoryhub" / "checkpoints").iterdir())  # wrote nothing

    p = mh("import", cwd=root, check=0)
    assert "imported 3 sessions -> history (claude 1, codex 1, pi 1)" in p.stdout
    assert "1 with no dialog" in p.stdout

    hist = next(
        d for d in (root / ".memoryhub" / "checkpoints").iterdir() if d.name.endswith("_history")
    )
    names = sorted(f.name for f in hist.glob("*.md"))
    # pi/codex fixtures end with a junk record at 04:02 — the session end time
    # comes from the LAST record of any kind, so those stamps read 0402
    assert names == [
        f"2026-07-01_0401_{CL_SID[:8]}.md",
        f"2026-07-02_0402_pi-{PI_SID.replace('-', '')[:12]}.md",
        f"2026-07-03_0402_cx-{CX_SID.replace('-', '')[:12]}.md",
    ]
    body = (hist / names[1]).read_text()
    assert "pi-q" in body and "pi-a" in body and "hmm" not in body
    body = (hist / names[2]).read_text()
    assert "cx-q" in body and "environment_context" not in body

    # one commit for the whole batch; hub had no checkpoints -> history is current
    journal = mh("log", cwd=root, check=0).stdout
    assert journal.count("import:") == 1
    status = mh("status", cwd=root, check=0).stdout
    assert "current: history" in status

    # warm start covers the full timeline, chronological across agents
    out = mh("load", "--all", cwd=root, check=0).stdout
    order = [out.index("cl-q"), out.index("pi-q"), out.index("cx-q")]
    assert order == sorted(order)

    # idempotent: nothing new on re-run
    p = mh("import", cwd=root, check=0)
    assert "nothing to import" in p.stdout
    assert "3 already in hub" in p.stdout


def test_import_dedups_against_mh_save_and_agent_filter(mh, ws, hub_project):
    root = hub_project
    home = ws["home"]
    mh("checkpoint", "alpha", cwd=root, check=0)
    tr = write_transcript(
        home,
        root,
        CL_SID,
        make_records([("cl-q", "cl-a")], start="2026-07-01T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=root, check=0)
    write_pi_transcript(
        home,
        root,
        PI_SID,
        make_pi_records([("pi-q", "pi-a")], start="2026-07-02T04:00:00Z", cwd=str(root)),
    )

    p = mh("import", "--agent", "pi", cwd=root, check=0)
    assert "imported 1 sessions -> history (pi 1)" in p.stdout
    # alpha existed, so import must NOT steal the current pointer
    assert "current: alpha" in mh("status", cwd=root, check=0).stdout

    # full import now: claude session already saved by `mh save`, pi imported
    p = mh("import", cwd=root, check=0)
    assert "nothing to import" in p.stdout
    assert "2 already in hub" in p.stdout

    p = mh("import", "--agent", "gemini", cwd=root)
    assert p.returncode == 1
    assert "unknown agent" in p.stderr


def test_import_to_targets_named_checkpoint(mh, ws, hub_project):
    root = hub_project
    mh("checkpoint", "alpha", cwd=root, check=0)
    write_pi_transcript(
        ws["home"],
        root,
        PI_SID,
        make_pi_records([("pi-q", "pi-a")], start="2026-07-02T04:00:00Z", cwd=str(root)),
    )
    p = mh("import", "--to", "alpha", cwd=root, check=0)
    assert "-> alpha (pi 1)" in p.stdout
    assert not any(
        d.name.endswith("_history") for d in (root / ".memoryhub" / "checkpoints").iterdir()
    )


def test_import_subdir_variant_needs_matching_cwd(mh, ws, hub_project):
    root = hub_project
    home = ws["home"]
    esc = encode_project_dir(root)
    base = home / ".claude" / "projects"
    # subdir launch: cwd under the project root -> accepted
    dump_jsonl(
        base / (esc + "-src") / f"{CL_SID}.jsonl",
        make_records([("sub-q", "sub-a")], start="2026-07-01T04:00:00Z", cwd=str(root / "src")),
    )
    # sibling project: prefix-matches the dir name but cwd is elsewhere -> rejected
    dump_jsonl(
        base / (esc + "-2") / f"{CX_SID}.jsonl",
        make_records([("sib-q", "sib-a")], start="2026-07-01T04:00:00Z", cwd="/somewhere/else"),
    )
    p = mh("import", cwd=root, check=0)
    assert "imported 1 sessions -> history (claude 1)" in p.stdout
    out = mh("load", "--all", cwd=root, check=0).stdout
    assert "sub-q" in out and "sib-q" not in out


def test_import_scoped_to_cwd_subtree(mh, ws, hub_project):
    root = hub_project
    home = ws["home"]
    esc = encode_project_dir(root)
    base = home / ".claude" / "projects"
    sids = [f"{i}{i}{i}{i}aaaa-0000-4000-8000-00000000000{i}" for i in range(1, 5)]
    dump_jsonl(
        base / esc / f"{sids[0]}.jsonl",
        make_records([("root-q", "a")], start="2026-07-01T04:00:00Z", cwd=str(root)),
    )
    dump_jsonl(
        base / (esc + "-sub") / f"{sids[1]}.jsonl",
        make_records([("sub-q", "a")], start="2026-07-02T04:00:00Z", cwd=str(root / "sub")),
    )
    dump_jsonl(
        base / (esc + "-sub-deep") / f"{sids[2]}.jsonl",
        make_records(
            [("deep-q", "a")],
            start="2026-07-03T04:00:00Z",
            cwd=str(root / "sub" / "deep"),
        ),
    )
    dump_jsonl(
        base / (esc + "-other") / f"{sids[3]}.jsonl",
        make_records([("other-q", "a")], start="2026-07-04T04:00:00Z", cwd=str(root / "other")),
    )

    sub = root / "sub"
    (sub / "deep").mkdir(parents=True)
    p = mh("import", cwd=sub, check=0)
    assert "scope: sub/" in p.stderr
    assert "imported 2 sessions -> history (claude 2)" in p.stdout
    out = mh("load", "--all", cwd=root, check=0).stdout
    assert "sub-q" in out and "deep-q" in out
    assert "root-q" not in out and "other-q" not in out

    # from the root: everything, minus what the scoped run already imported
    p = mh("import", cwd=root, check=0)
    assert "scope:" not in p.stderr
    assert "imported 2 sessions -> history (claude 2)" in p.stdout
    assert "2 already in hub" in p.stdout


def test_import_json_output(mh, ws, hub_project):
    root = hub_project
    _seed_all_agents(ws, root)
    data = json.loads(mh("import", "--json", cwd=root, check=0).stdout)
    assert data["checkpoint"] == "history"
    assert len(data["imported"]) == 3
    assert data["skipped_empty"] == 1
