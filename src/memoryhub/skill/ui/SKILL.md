---
name: mh-ui
description: >-
  Start the MemoryHub web UI for the current session (live panel + checkpoint
  map). Use when the user types /mh-ui or says "open the map", "start the web
  UI", "打开地图". Costs one command; the full `mh` workflow skill is not needed.
---

Run exactly one command:

    mh ui --detach

Reply with the URL it prints — one line, nothing else. No checks before it, no
diagnostics after: mh picks a free port by itself, prints the URL of a server
that is already running instead of starting another, and follows this
session's live panel. `mh ui --stop` ends it, only if the user asks.
