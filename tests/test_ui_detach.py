"""`mh ui --detach`: the map server in the background — what an agent runs,
since a bare `mh ui` blocks the shell it was started from. The CLI must come
back with the URL, find the same server next time, and `--stop` must end it
without leaving a record behind."""

import json
import os
import re
import socket
import time
import urllib.request

import pytest

from conftest import TIMEOUT
from memoryhub import server
from memoryhub.hub import MhError


def _hub(project):
    return project / ".memoryhub"


def _record(project):
    path = _hub(project) / "ui.json"
    return json.loads(path.read_text()) if path.is_file() else None


def _gone(pid: int) -> bool:
    for _ in range(int(TIMEOUT / 0.05)):
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.05)
    return False


@pytest.fixture()
def stop_after(mh, hub_project):
    """Whatever the test leaves running is ended — a detached server must never
    outlive its test."""
    yield
    rec = _record(hub_project)
    mh("ui", "--stop", cwd=hub_project)
    if rec:
        _gone(rec["pid"])


def test_detach_returns_the_url_and_stop_ends_the_server(mh, hub_project, stop_after):
    p = mh("ui", "--detach", "--no-browser", "--port", "0", cwd=hub_project, check=0)
    m = re.search(r"mh ui: (http://127\.0\.0\.1:\d+/\?t=[\w-]+)$", p.stdout, re.M)
    assert m, p.stdout
    url = m.group(1)
    assert "background" in p.stdout and "mh ui --stop" in p.stdout
    rec = _record(hub_project)
    assert rec["url"] == url and isinstance(rec["pid"], int)
    exclude = (_hub(hub_project) / ".git" / "info" / "exclude").read_text()
    assert "/ui.json" in exclude and "/ui.log" in exclude

    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:  # the page is up
        assert r.status == 200 and b"mh-config" in r.read()
    with pytest.raises(urllib.error.HTTPError) as e:  # and still token-gated
        urllib.request.urlopen(url.split("?")[0], timeout=TIMEOUT)
    assert e.value.code == 403

    # a second start finds the running server instead of racing it for a port
    p2 = mh("ui", "--detach", "--no-browser", "--port", "0", cwd=hub_project, check=0)
    assert "already running" in p2.stdout and url in p2.stdout
    assert _record(hub_project)["pid"] == rec["pid"]

    p3 = mh("ui", "--stop", cwd=hub_project, check=0)
    assert f"stopped mh ui (pid {rec['pid']})" in p3.stdout
    assert _gone(rec["pid"])
    assert _record(hub_project) is None
    p4 = mh("ui", "--stop", cwd=hub_project, check=0)
    assert "no background mh ui" in p4.stdout


def test_the_page_follows_the_session_that_asked(mh, hub_project, stop_after):
    """From inside an agent session the URL names that session, so the live
    panel follows it rather than whichever transcript is newest."""
    p = mh(
        "ui",
        "--detach",
        "--no-browser",
        "--port",
        "0",
        cwd=hub_project,
        check=0,
        env_extra={"CLAUDE_CODE_SESSION_ID": "abcd1234-0000-4000-8000-000000000000"},
    )
    assert "&sid=abcd1234-0000-4000-8000-000000000000" in p.stdout
    base = _record(hub_project)["url"]
    assert "sid=" not in base  # the record is the server; the session rides on the link
    p2 = mh("ui", "--no-browser", "--session", "pi-deadbeef0123", cwd=hub_project, check=0)
    assert "already running" in p2.stdout and base + "&sid=pi-deadbeef0123" in p2.stdout


def test_a_stale_record_is_not_believed(mh, hub_project):
    """A record whose pid is gone (a reboot, a kill -9) must not stop a fresh
    start, and must not be reported as running."""
    (_hub(hub_project) / "ui.json").write_text(json.dumps({"pid": 2**22 - 1, "url": "http://x"}))
    p = mh("ui", "--stop", cwd=hub_project, check=0)
    assert "no background mh ui" in p.stdout
    assert _record(hub_project) is None


def test_the_usual_port_gives_way_when_taken(monkeypatch):
    """Another hub's map on 7777 must not turn `mh ui --detach` into a
    diagnosis: with no port asked for, mh takes a free one and says so."""
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        taken_port = busy.getsockname()[1]
        monkeypatch.setattr(server, "DEFAULT_PORT", taken_port)
        httpd, gave_up = server.listen("127.0.0.1", None, server.make_handler)
        try:
            assert gave_up == taken_port and httpd.server_address[1] != taken_port
        finally:
            httpd.server_close()
        # an explicit port is a promise, not a preference
        with pytest.raises(MhError, match="cannot listen"):
            server.listen("127.0.0.1", taken_port, server.make_handler)
