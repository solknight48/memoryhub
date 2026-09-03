# Changelog

All notable changes to `mh` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Sub-checkpoints**: `mh checkpoint <name> --under <ckpt>` (or the dotted
  `mh checkpoint design.head-page`) creates a smaller scope under a
  checkpoint, stored inside its parent's directory and named `parent.child`.
  Loading a sub-checkpoint loads its parents too; loading the parent stays
  at the parent, and `--tree` loads whole nodes — every checkpoint in the
  pack, linked ones included, with the sub-checkpoints of its node (also
  `mh hook install --tree` for the session-start pack, and a "with
  sub-checkpoints" preview box on the map). The map draws them indented under the node, the checkpoint
  panel lists them and offers "+ sub-checkpoint…", and renames, deletes,
  links and skips follow the subtree (`POST /api/checkpoint/create` takes
  `under`; `mh rm` needs `--force` for a checkpoint with sub-checkpoints).
- **Skip a session on load**: untick a session in the map's checkpoint panel
  (or `mh skip <ckpt>/<session>`; `mh unskip` brings it back) and `mh load` —
  and so the SessionStart hook — leave it out, while it stays in its
  checkpoint for `mh show` and the map. The list is the hub's `skip.toml`,
  committed like every other change; entries follow renames and moves and
  leave with a deleted session. The pack notes what was skipped;
  `mh load --json` gains `skipped`, `mh status` counts them
  (`POST /api/session/skip`).
- **Compact with the session's own agent**: the live panel's save button now
  offers the purified dialog or a summary written by the CLI that runs the
  session — `claude -p` or `pi -p` started fresh in a scratch directory with
  that tool's own compaction prompt (pi's verbatim), tools and session
  persistence off — stored as the compacted save (`POST /api/live/compact`).
  An optional focus works like `/compact <instructions>`. From a terminal:
  `mh save --compact --with agent|claude|pi [--focus TEXT]`. The running
  session is never touched; codex sessions get no compaction yet.
- The timeline acts: click a node for its menu — open / make current /
  sub-checkpoint / another take / link / unlink / rename / stage inserts /
  delete, each with a line saying what it does, greyed when it cannot apply;
  the checkpoint panel underneath carries the same actions as a toolbar,
  both drawn from one list so they cannot drift;
  a stage ahead (dashed) offers create / rename / remove / insert before or
  after / move earlier or later, editing the hub's `template.toml`
  (`POST /api/template/stages`, `POST /api/goto`). Renaming a checkpoint that
  is a template stage renames the stage with it (`mh rename` too).
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
  are parallel branches through the stage on the timeline, each connected to
  the stage before and the stage after (a trailing number is another take at
  the stage; `mh checkpoint --at design` numbers the next one; `--at` with a
  name places a checkpoint at a stage its name does not say, kept in
  `stages.toml`). Independent as ever; the map's panel gains "+ another here".
- **Stage templates** — default checkpoint names for a kind of project:
  `mh template --list` shows ten (quant, frontend, backend, sdlc, mobile,
  devops, data, ml, sprint, hotfix), each as its numbered stages (`-v` adds
  what happens at each stage); `mh template <name>` or
  `mh init --template <name>` records one in the hub (`template.toml`, a copy
  of the stages you can edit), `mh checkpoint` with no name creates the next
  stage, `mh status` reports the progress, and the map draws the stages ahead
  as dashed nodes (click to create), shown before the first checkpoint exists
  too, with the progress in the timeline's status line. Choosing the template
  is a terminal step; the map does not offer one.
- **Live session panel** in `mh ui`: the transcript being written right now,
  re-read as it grows, shown unfiltered (thinking, text, tool calls, parallel
  batches, subagent output) while saves keep storing purified dialog. Curation
  done while the session runs (drop, rewrite, restore) is kept as a draft and
  applied by every later save.
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
- `CONTRIBUTING.md`, `.editorconfig`, a `ruff` configuration and a CI lint job.

### Changed
- `mh ui` reads top to bottom: a sticky header (project, the jump to the live
  session, template, new checkpoint, refresh); the timeline with its status
  line (current, template progress, load budget); the checkpoint and session
  panels a click opens, each with a title row, a close and its own toolbar;
  the live session, whose toolbar sits in its title row and whose save button
  says where the save goes; project memory last. Every question the page asks
  is an inline popover — deletes and discards included, no browser dialogs —
  and a button that cannot apply is greyed instead of failing with a toast;
  the save and new-checkpoint menus name each choice with a line saying what
  it does. The live panel's save is a box of its own: the target checkpoint
  in the open (another one moves the session), Dialog or Summary with a word
  on each, the summary's focus inline, and one button saying what it will do
  (`POST /api/live/compact` takes `to`, as the dialog save does). The
  "watch" box is gone: the poll always runs (it also carries the hub
  fingerprint the map follows), and the pulse dot means what it says. The
  header's live-session button switches the whole live panel
  on and off, lit while it is on, remembered across reloads. The live
  panel's "full output" box is now two, "thinking" and
  "tool calls", each leaving that part of the stream out of the page; the
  dialog always stays, and the agent is never affected.
  The timeline's status line names what the next load packs (with "whole
  nodes" when the sub-checkpoints box is ticked), a node is purple when it is
  in that set — sessions or not, with the budget fit in its tooltip — and a
  link the next load does not reach is drawn grey and dashed. The map re-reads the
  hub when it changes under it — a terminal `mh link` or `mh goto`, a hook's
  save — within a poll of the live panel, instead of waiting for refresh.
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
- The three agent adapters share one turn-pairing rule (`purify.TurnBuilder`).
- The test suite runs in parallel by default (`pytest-xdist`).

### Removed
- The browser composer: typing back into the running session, the
  slash-command palette (`GET /api/live/commands`, `POST /api/live/say`)
  and the tmux relay behind it, including the pane `mh hook load` recorded
  in `panes.json`. mh manages memory and sessions; it does not drive the
  agent. (On `main` between ffebc56 and this change; never in a release.)

### Fixed
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
