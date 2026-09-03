"""The map follows the terminal: every map and live response carries a
fingerprint of the hub (its last commit, its current pointer), and the page
re-reads the map when it moves — so a `mh link` or `mh goto` typed in a
terminal shows up on the page within a poll, not when refresh is pressed.
"""

from memoryhub import server
from memoryhub.hub import write_current


def test_the_hub_fingerprint_moves_with_commits_and_the_pointer(mh, ws, hub_project):
    hub = hub_project / ".memoryhub"
    mh("checkpoint", "alpha", cwd=hub_project, check=0)
    _, before = server.dispatch(hub, "GET", "/api/map", {}, {}, False)
    _, live = server.dispatch(hub, "GET", "/api/live", {}, {}, False)
    assert live["present"] is False  # no transcript, still a fingerprint to compare
    assert live["hub_rev"] == before["hub_rev"]

    server.dispatch(hub, "POST", "/api/checkpoint/create", {}, {"name": "beta"}, False)
    _, after = server.dispatch(hub, "GET", "/api/map", {}, {}, False)
    assert after["hub_rev"] != before["hub_rev"]  # a commit moved it

    write_current(hub, "alpha")  # what `mh goto` does: no commit, still a change to show
    _, moved = server.dispatch(hub, "GET", "/api/map", {}, {}, False)
    assert moved["hub_rev"] != after["hub_rev"]
