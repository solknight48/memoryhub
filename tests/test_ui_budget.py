"""`mh ui` page config: the served page carries the flags it was started with
(budget, read-only, hub path) in one injected JSON block."""

import json
import re
from pathlib import Path

import pytest

from memoryhub import server
from memoryhub.hub import MhError


def _config(page: bytes) -> dict:
    m = re.search(
        rb'<script id="mh-config" type="application/json">(.*?)</script>', page
    )
    assert m, "no config block in the served page"
    return json.loads(m.group(1))


def test_page_carries_the_budget():
    cfg = _config(server._page(6000, False, Path("/tmp/hub")))
    assert cfg["budget"] == 6000
    assert cfg["readOnly"] is False
    assert cfg["hub"] == "/tmp/hub"


def test_page_with_budget_none_and_read_only():
    cfg = _config(server._page(None, True, Path("/tmp/hub")))
    assert cfg["budget"] is None
    assert cfg["readOnly"] is True


def test_page_replaces_the_marker_exactly_once():
    page = server._page(12000, False, Path("/x"))
    assert server.CONFIG_MARKER not in page
    assert page.count(b'id="mh-config"') == 1


def test_config_cannot_break_out_of_the_script_element():
    page = server._page(None, False, Path("/tmp/</script><script>alert(1)"))
    # the '<' of any value is escaped, so the config block still ends exactly once
    assert b"</script><script>alert(1)" not in page
    assert _config(page)["hub"] == "/tmp/</script><script>alert(1)"


def test_bad_budget_fails_before_serving(mh, hub_project):
    p = mh("ui", "--budget", "bogus", cwd=hub_project)
    assert p.returncode == 1
    assert "--budget must be a non-negative integer or 'none'" in p.stderr


def test_negative_budget_fails_before_serving(mh, hub_project):
    p = mh("ui", "--budget", "-5", cwd=hub_project)
    assert p.returncode == 1
    assert "--budget must be a non-negative integer or 'none'" in p.stderr


def test_missing_config_marker_fails_loudly(monkeypatch):
    from importlib.resources import files

    class FakeResource:
        def read_bytes(self):
            return b"<html>no marker here</html>"

    monkeypatch.setattr(
        type(files("memoryhub")), "joinpath", lambda self, *a, **k: FakeResource()
    )
    with pytest.raises(MhError, match="config marker"):
        server._page(6000, False, Path("/x"))
