"""`mh ui --budget`: the map's initial budget box follows the flag."""

import pytest

from memoryhub import server
from memoryhub.hub import MhError


def test_page_keeps_the_stock_default():
    assert b'value="6000"' in server._page(6000)


def test_page_rewrites_the_budget_box():
    assert b'value="12000"' in server._page(12000)
    assert b'value="6000"' not in server._page(12000)


def test_page_with_budget_none_leaves_the_box_empty():
    page = server._page(None)
    assert b'value=""' in page
    assert b'value="6000"' not in page


def test_bad_budget_fails_before_serving(mh, hub_project):
    p = mh("ui", "--budget", "bogus", cwd=hub_project)
    assert p.returncode == 1
    assert "--budget must be a non-negative integer or 'none'" in p.stderr


def test_negative_budget_fails_before_serving(mh, hub_project):
    p = mh("ui", "--budget", "-5", cwd=hub_project)
    assert p.returncode == 1
    assert "--budget must be a non-negative integer or 'none'" in p.stderr


def test_missing_default_marker_fails_loudly(monkeypatch):
    from importlib.resources import files

    class FakeResource:
        def read_bytes(self):
            return b"<html>no marker here</html>"

    monkeypatch.setattr(
        type(files("memoryhub")), "joinpath", lambda self, *a, **k: FakeResource()
    )
    with pytest.raises(MhError, match="default budget marker"):
        server._page(6000)
