# Changelog

All notable changes to `mh` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- The timeline acts: click a node for open / make current / rename / another
  take / link / delete; a stage ahead offers create / rename / remove / insert
  before or after / move earlier or later, editing the hub's `template.toml`
  (`POST /api/template/stages`, `POST /api/goto`). The checkpoint panel gains
  "make current". Renaming a checkpoint that is a template stage renames the
  stage with it (`mh rename` too).
- **Project memory in the map**: the notes Claude Code keeps about a project
  (`~/.claude/projects/<project>/memory/`) are shown read-only under the
  timeline — one card per note with its type, markdown body, `[[name]]` links
  to related notes, and the originating session opened on its own page when
  its transcript is still on this machine (`GET /api/memory`). mh never
  writes the folder.
- **Trace a saved session to its origin**: `mh trace <ckpt>/<session>` resolves
  the session id recorded in the purified file to the original transcript on
  this machine (nothing machine-specific is stored — the id is the link). The
  map's session panel gains an **open original ↗** link that opens the full
  unfiltered transcript on a page of its own (`?view=<id>`, pinned for good).
- **Several checkpoints at one stage**: `design`, `design-2`, `design-3`
  stack under one node of the timeline (a trailing number is another take at
  the stage; `mh checkpoint --at design` numbers the next one; `--at` with a
  name places a checkpoint at a stage its name does not say, kept in
  `stages.toml`). Independent as ever; the map's panel gains "+ another here".
- **Stage templates** — default checkpoint names for a kind of project:
  `mh template --list` shows ten (quant, frontend, backend, sdlc, mobile,
  devops, data, ml, sprint, hotfix), `mh template <name>` or
  `mh init --template <name>` records one in the hub (`template.toml`, a copy
  of the stages you can edit), `mh checkpoint` with no name creates the next
  stage, `mh status` reports the progress, and the map draws the stages ahead
  as dashed nodes (click to create) with a template picker in the header.
- **Live session panel** in `mh ui`: the transcript being written right now,
  re-read as it grows, shown unfiltered (thinking, text, tool calls, parallel
  batches, subagent output) while saves keep storing purified dialog. Curation
  done while the session runs (drop, rewrite, restore) is kept as a draft and
  applied by every later save.
- **Type back** into a running session from the browser: the composer pastes
  into the tmux pane the session runs in, verified against tmux and `/proc` on
  every send (Linux, tmux).
- `mh ui`: the feed shows the newest three exchanges with the rest one click
  away; a "● live session" button in the header jumps to it; names are typed
  into an inline field instead of a `prompt()` dialog; error toasts carry git's
  own first line of detail.
- `mh ui --detach` runs the map server in the background and prints its URL
  (`--stop` ends it, `mh status` shows it); `--session` / `?sid=` pins the live
  panel to one session, and from an agent session it defaults to that session
  (`$CLAUDE_CODE_SESSION_ID`). The `/mh` skill gained `/mh ui`, and `mh skill
  install` adds `/mh-ui`, a one-paragraph skill that only starts the map.
- `mh ui` falls back to a free port when 7777 is held by another map, so an
  agent starting it always gets a URL; `--port N` stays strict.
- A `?sid=` pin in the map's URL holds only while that session is alive: once it
  has been quiet for 10 minutes and the project has a newer transcript, the page
  follows the newest and says so; a "follow the newest" button shows whenever
  the followed session is not the newest.
- The live panel shows pictures: one pasted into the session (decoded from the
  transcript on request) or an image file the agent read (served only when its
  bytes sniff as PNG/JPEG/GIF/WebP). Nothing is copied into the hub.
- The live panel no longer clips the agent's reply text at 4,000 characters;
  only tool inputs (4k) and thinking (12k) are capped.
- The composer projects the CLI's input: a message starting with `/` offers
  the session's own skills and commands (read from disk — user and project
  skills, custom commands, installed plugins; pi's skills) plus the built-ins
  worth sending from a browser, and `/model` offers the CLI's aliases and the
  models the session has used. The composed text is pasted into the session
  and run by the CLI itself (`GET /api/live/commands`).
- `CONTRIBUTING.md`, `.editorconfig`, a `ruff` configuration and a CI lint job.

### Changed
- A session's avatar in the map names the model that ran it ("F5", "S4",
  "G5") in the colour its exchange chips use, instead of two characters of
  the session id; the agent shows when no model was recorded.
- The default load budget is 20000 tokens (was 6000): about a tenth of a 200k
  context, three or four typical sessions instead of one. `mh hook install
  --budget N` sizes the pack the SessionStart hook injects.
- **One save policy** (`save.py`) shared by `mh save`, `mh hook save` and the
  panel: a session lives in exactly one checkpoint — a save with no target
  updates it where it already is, `mh save --to <ckpt>` moves it, and only an
  explicit `mh save` replaces a compacted summary with dialog.
- A slash command the agent answered (`/mh load`) is now kept as dialog, as
  the user typed it; one nobody answered (`/clear`, `/model`) is dropped
  outright instead of being merged into the next question.
- The composer sits at the bottom of the live panel, pinned to the window
  while the feed is in view.
- The three agent adapters share one turn-pairing rule (`purify.TurnBuilder`).
- The test suite runs in parallel by default (`pytest-xdist`).

### Fixed
- Typing back: a pane that another session of the project has since started in
  (its own record, alive) is no longer handed to the older session as
  "restarted in the same pane" — the keys would have landed in the new one.
- Running the test suite from inside tmux killed the developer's tmux server
  (the relay tests' private server honoured the inherited `$TMUX` socket).
  Tests no longer see `TMUX`/`TMUX_PANE` at all.
- Typing back after `claude -c`: an agent of this project that comes back in
  the recorded tmux pane is accepted again instead of being refused as
  "whatever took its place"; when the recorded tmux server is gone the panel
  says so. The hint now reads `tmux new -s mh` + `claude` inside it — a pane
  started as `tmux new -s mh claude` died with claude and took tmux with it.
- `mh save` no longer writes a second copy of a session that was already
  saved in another checkpoint.
- Background-task notices (`<task-notification>`), which Claude Code delivers
  as user records, no longer appear as dialog; harness wrappers are recognised
  even when a `<system-reminder>` block precedes them.
- A session that opened with a slash command lost its whole first exchange.
- `mh --version` and the page footer read the version from one place
  (`memoryhub.__version__`, which had drifted to 0.1.0).

## [0.2.0] - 2026-08-28

### Added
- Claude Code hooks (`mh hook install [--user]`): `mh load` injected at
  SessionStart, saves at SessionEnd and PreCompact.
- CLI curation with the map's surgery: `mh rm`, `mh mv`, `mh rename`,
  `mh edit`.
- `mh save --compact --file <md>`: store an agent-written summary under the
  session's identity.
- `mh ui --budget N|none`, `--read-only`; clickable pickers instead of typed
  slugs; the served page carries its config in one JSON block.
- `mh --version` with the install path; CI on Linux and macOS.
- CJK-aware token estimates and checkpoint names in any script.

## [0.1.0] - 2026-07-26

Initial release: `mh init`, `checkpoint`, `save`, `load`, `link`, `import`,
`list`/`show`/`status`/`search`/`log`, `sync`, `hubs`, `ui`, `skill install`.
