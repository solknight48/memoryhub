import json
import re

from conftest import make_records, write_transcript
from memoryhub.load import estimate_tokens


def test_token_estimate_ascii_and_cjk():
    """ASCII prose ~4 chars/token; CJK ~1 token/char — a Chinese session must
    not be undercounted 4x or the budget packs far more than asked."""
    assert estimate_tokens("hello world " * 10) == 30  # 120 chars / 4
    assert estimate_tokens("这是一个中文句子" * 15) == 120  # 120 CJK chars
    mixed = "abcd" + "中文"
    assert estimate_tokens(mixed) == 3  # 4 ascii chars -> 1, 2 CJK -> 2


SIDS = {
    "alpha1": "aaaa1111-0000-4000-8000-000000000001",
    "alpha2": "aaaa2222-0000-4000-8000-000000000002",
    "beta1": "bbbb1111-0000-4000-8000-000000000003",
    "gamma1": "cccc1111-0000-4000-8000-000000000004",
}


def _setup(mh, ws, project):
    """alpha: two sessions (07-10, 07-12); beta: one session (07-11) — beta's
    session falls BETWEEN alpha's two, proving cross-checkpoint time merge."""
    mh("checkpoint", "alpha", cwd=project, check=0)
    tr = write_transcript(
        ws["home"],
        project,
        SIDS["alpha1"],
        make_records([("q-alpha-one", "a-alpha-one")], start="2026-07-10T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=project, check=0)
    tr = write_transcript(
        ws["home"],
        project,
        SIDS["alpha2"],
        make_records([("q-alpha-two", "a-alpha-two")], start="2026-07-12T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=project, check=0)
    mh("checkpoint", "beta", cwd=project, check=0)
    tr = write_transcript(
        ws["home"],
        project,
        SIDS["beta1"],
        make_records([("q-beta-one", "a-beta-one")], start="2026-07-11T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=project, check=0)


def test_independent_then_linked_time_merge(mh, ws, hub_project):
    _setup(mh, ws, hub_project)

    out = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert "loaded: beta |" in out
    assert "q-beta-one" in out
    assert "q-alpha-one" not in out  # independent by default

    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    out = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert "loaded: alpha + beta (linked)" in out
    order = [
        out.index("q-alpha-one"),
        out.index("q-beta-one"),
        out.index("q-alpha-two"),
    ]
    assert order == sorted(order)  # merged by session time, not by checkpoint

    out = mh("load", "--all", "--no-links", cwd=hub_project, check=0).stdout
    assert "q-alpha-one" not in out

    mh("unlink", "alpha", "beta", cwd=hub_project, check=0)
    out = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert "q-alpha-one" not in out

    out = mh("load", "alpha", "beta", "--all", cwd=hub_project, check=0).stdout
    assert "q-alpha-one" in out and "q-beta-one" in out  # explicit multi-select


def test_chained_closure(mh, ws, hub_project):
    _setup(mh, ws, hub_project)
    mh("checkpoint", "gamma", cwd=hub_project, check=0)
    tr = write_transcript(
        ws["home"],
        hub_project,
        SIDS["gamma1"],
        make_records([("q-gamma-one", "a-gamma-one")], start="2026-07-13T04:00:00Z"),
    )
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    mh("link", "beta", "gamma", cwd=hub_project, check=0)
    out = mh("load", "alpha", "--all", cwd=hub_project, check=0).stdout
    assert "loaded: alpha + beta + gamma (linked)" in out
    assert "q-gamma-one" in out


def test_link_edge_cases(mh, ws, hub_project):
    _setup(mh, ws, hub_project)
    p = mh("link", "alpha", "alpha", cwd=hub_project, check=0)
    assert "nothing to do" in p.stdout
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    p = mh("link", "beta", "alpha", cwd=hub_project, check=0)
    assert "nothing to do" in p.stdout
    p = mh("link", "alpha", "nope", cwd=hub_project)
    assert p.returncode == 1
    assert "no checkpoint 'nope'" in p.stderr
    p = mh("unlink", "alpha", "beta", cwd=hub_project, check=0)
    assert "unlinked" in p.stdout
    p = mh("unlink", "alpha", "beta", cwd=hub_project, check=0)
    assert "nothing to do" in p.stdout


def test_budget_keeps_newest_contiguous(mh, ws, hub_project):
    _setup(mh, ws, hub_project)
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    # Each session is ~90 tokens; budget 100 keeps only the newest (alpha-two).
    p = mh("load", "--budget", "100", cwd=hub_project, check=0)
    out = p.stdout
    assert "q-alpha-two" in out
    assert "q-alpha-one" not in out and "q-beta-one" not in out
    assert "omitted 2 older session(s) for budget" in out
    assert re.search(r"alpha/2026-07-10_\d{4}_aaaa1111\.md", out)
    assert re.search(r"beta/2026-07-11_\d{4}_bbbb1111\.md", out)
    # Tiny budget: newest still included, warning on stderr.
    p = mh("load", "--budget", "5", cwd=hub_project, check=0)
    assert "q-alpha-two" in p.stdout
    assert "exceeds the budget" in p.stderr


def test_load_json_and_determinism(mh, ws, hub_project):
    _setup(mh, ws, hub_project)
    mh("link", "alpha", "beta", cwd=hub_project, check=0)
    first = mh("load", "--all", cwd=hub_project, check=0).stdout
    second = mh("load", "--all", cwd=hub_project, check=0).stdout
    assert first == second  # byte-identical, deterministic

    data = json.loads(mh("load", "--all", "--json", cwd=hub_project, check=0).stdout)
    assert data["loaded"] == ["alpha", "beta"]
    assert data["linked_expansion"] is True
    assert len(data["sessions"]) == 3
    assert data["omitted"] == []
    assert data["sessions"][0]["checkpoint"] == "alpha"


def test_load_golden_output(mh, ws, hub_project):
    sid = "e5f6a7b8-5555-4555-8555-555555555555"
    mh("checkpoint", "solo", cwd=hub_project, check=0)
    tr = write_transcript(ws["home"], hub_project, sid, make_records([("hello", "world")]))
    mh("save", "--transcript", tr, cwd=hub_project, check=0)
    out = mh("load", cwd=hub_project, check=0).stdout
    normalized = re.sub(r"@ [0-9a-f]+", "@ SHA", out)
    expected = f"""<!-- mh | loaded: solo | 1 of 1 sessions | @ SHA -->

<!-- mh session: solo/2026-07-10_0401_e5f6a7b8.md -->

# Session Context

_Pure dialog extracted from `{sid}.jsonl` (session `{sid}`). 1 exchange. Tool calls, results, and internal reasoning removed._

## User 1

hello

## Agent 1

world
"""
    assert normalized == expected
