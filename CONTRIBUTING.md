# Contributing to MemoryHub

Thanks for looking under the hood. `mh` is small on purpose — one runtime
dependency (typer), system git, a stdlib HTTP server and one HTML file — and
the rules below are what keep it that way.

## Setup

```sh
git clone https://github.com/solknight48/memoryhub
cd memoryhub
uv sync --all-groups            # Python ≥ 3.12, pytest, pytest-xdist, ruff
uv tool install --force -e .    # the installed `mh` is the code you are editing
```

## Before you open a PR

```sh
uv run pytest                   # the whole suite, in parallel, ~5 s
uv run ruff check               # lint
uv run ruff format --check      # formatting (`uv run ruff format` to apply)
```

CI runs exactly these on Linux and macOS, Python 3.12 and 3.13. The UI tests
need `node` (they run the page's own JavaScript through `tests/uijs.mjs`) and
skip without it.

Developing on Linux with a Mac within reach? `scripts/test-remote.sh <ssh-host>`
rsyncs the working tree there and runs the suite over ssh — macOS-only failures
(BSD sockets, spawn semantics, a resolver that answers differently) surface in
seconds instead of a CI round-trip. It needs `uv` on the remote and nothing else.

## Invariants a change must keep

The architecture notes live in [`CLAUDE.md`](CLAUDE.md) — written for the
coding agents that work on this repo, and the best map of it for humans too.
The short version:

- **Every mutation of the hub is a git commit**, checked for *before* anything
  touches disk (`curate.ensure_committable`). A failed commit must never leave
  a file outside the journal.
- **A session lives in exactly one checkpoint.** Every path that stores a
  session goes through `save.store()`; do not write session files anywhere
  else.
- **`curate.py` is the only code that parses session markdown**, and it never
  rewrites a file whose parse → re-render is not byte-identical.
- **`purify.py` extracts dialog by rule, never by model.** Turn pairing lives
  in `purify.TurnBuilder`; an agent adapter in `agents.py` only walks its own
  record shape. Adapters ship only for formats verified against real
  transcripts — an unverified shape returns nothing rather than a guess.
- **The server stays stdlib-only**, loopback-only, token-gated. The page uses
  no `innerHTML`: every string from a session reaches the DOM as text.
- **Tests are hermetic.** They drive the real CLI as a subprocess with a fake
  `HOME`; nothing may read or write the developer's machine, and every test
  must be safe to run in parallel.

## Docs

`README.md` (Chinese, the front page) and `README.en.md` are kept in step by
`tests/test_readme_parity.py`: same section structure, identical command
table, and every CLI command documented in both. A new command means editing
both files. User-visible changes get a line in `CHANGELOG.md` under
*Unreleased*.

## Looking at the UI

```sh
mh ui --no-browser --port 7777
chromium --headless=new --no-sandbox --hide-scrollbars --window-size=1200,3000 \
  --virtual-time-budget=12000 --screenshot=/tmp/shot.png "$URL"
```

CSS and JS are served from disk per request, so a reload shows an edit; only
`server.py` changes need a restart.

## Commit messages

Imperative, one line that says what changed and why it mattered —
`mh ui: make a saved session readable — HEY-style map, tables, model badges`
is the house style. Curation commits inside a hub are written by `mh` itself;
leave their wording alone.
