"""The end-to-end loop from the README: build context in checkpoints, link,
load time-merged, walk, search — everything a real first day with mh does."""

import json

from conftest import make_records, write_transcript

SID_DP1 = "11111111-0000-4000-8000-000000000001"
SID_DP2 = "22222222-0000-4000-8000-000000000002"
SID_BT1 = "33333333-0000-4000-8000-000000000003"


def test_golden_flow(mh, ws, project):
    mh("init", cwd=project, check=0)

    mh("checkpoint", "data-pipeline", cwd=project, check=0)
    tr = write_transcript(
        ws["home"],
        project,
        SID_DP1,
        make_records([("q-dp-one", "a-dp-one")], start="2026-07-10T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=project, check=0)
    tr = write_transcript(
        ws["home"],
        project,
        SID_DP2,
        make_records([("q-dp-two", "a-dp-two")], start="2026-07-12T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=project, check=0)

    mh("checkpoint", "backtest", cwd=project, check=0)
    tr = write_transcript(
        ws["home"],
        project,
        SID_BT1,
        make_records([("q-bt-one", "a-bt-one")], start="2026-07-11T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=project, check=0)

    listing = mh("list", cwd=project, check=0).stdout
    assert "data-pipeline" in listing and "backtest" in listing
    current_line = next(line for line in listing.splitlines() if "backtest" in line)
    assert current_line.lstrip().startswith("*")

    # independent by default
    out = mh("load", "--all", cwd=project, check=0).stdout
    assert "q-bt-one" in out and "q-dp-one" not in out

    # linked -> all sessions, merged by time across checkpoints
    mh("link", "data-pipeline", "backtest", cwd=project, check=0)
    out = mh("load", "--all", cwd=project, check=0).stdout
    assert "loaded: backtest + data-pipeline (linked)" in out
    order = [out.index("q-dp-one"), out.index("q-bt-one"), out.index("q-dp-two")]
    assert order == sorted(order)

    # walk backward, status reflects the position
    p = mh("back", cwd=project, check=0)
    assert "now at 'data-pipeline'" in p.stdout
    status = mh("status", cwd=project, check=0).stdout
    assert "current: data-pipeline (1 of 2)" in status

    # search attributes hits to checkpoint/file
    hits = mh("search", "q-bt-one", cwd=project, check=0).stdout
    assert "backtest/" in hits

    # the journal shows every mutation
    journal = mh("log", cwd=project, check=0).stdout
    assert "checkpoint: backtest" in journal
    assert "save:" in journal
    assert "link: backtest -- data-pipeline" in journal

    stat = json.loads(mh("status", "--json", cwd=project, check=0).stdout)
    assert stat["checkpoints"] == 2
    assert stat["sessions"] == 3
    assert stat["links"] == 1
    assert stat["loads_with"] == ["backtest", "data-pipeline"]
