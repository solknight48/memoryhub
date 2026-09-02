# MemoryHub (`mh`)

[简体中文](README.md) | **English**

[![CI](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml/badge.svg)](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml)

Git-like checkpoints for AI session context.

Every Claude Code session starts from zero. MemoryHub fixes that: when a session
ends, `mh save` **purifies** it (User/Agent dialog only — tool calls, thinking
and harness noise stripped by rule, mechanically, no LLM cost) and stores it in a
**checkpoint**. Checkpoints are independent by default; **link** two and they
load together, merged in time order. A new session runs `mh load` and the
project's memory is back.

```
.memoryhub/                                  ← the hub: a normal git repo
  checkpoints/
    2026-07-14_1650_data-pipeline/           ← checkpoint: <created>_<name>/
      2026-07-10_1432_a1b2c3d4.md            ← purified session: <end-time>_<sid>.md
  links.toml                                 ← linked checkpoints load together
  current                                    ← local pointer, not version-controlled
```

## Install

```sh
uv tool install git+https://github.com/solknight48/memoryhub
mh skill install           # teach Claude Code sessions the workflow
```

Needs Linux or macOS, git ≥ 2.32, Python ≥ 3.12. Windows is untested.

Installing from a clone has one catch: `uv tool install` **copies** the source, so
you get a snapshot — `git pull` will not update the installed `mh`, and new
commands simply will not appear. Use `uv tool install --force -e .` to follow your
working tree, or re-run with `--force` to take a fresh snapshot.

## Quickstart

```console
$ cd ~/dev/tickstore
$ mh init                        # hub at the project root
$ mh checkpoint data-pipeline    # create a checkpoint; it becomes current

# ... work with Claude; at session end (the agent does this via the skill):
$ mh save
saved 2026-07-18_0941_7aee4e68.md -> data-pipeline (1 sessions)

# next session, warm start:
$ mh load
<!-- mh | loaded: data-pipeline | 1 of 1 sessions | @ 3f1c2ab -->

# a second workstream, linked to the first so they load together:
$ mh checkpoint backtest
$ mh save
$ mh link data-pipeline backtest
$ mh load                        # sessions of BOTH, merged in time order
```

## Commands

| Command | What it does |
|---|---|
| `mh init [--global] [--claude] [--template T]` | Create the hub. |
| `mh checkpoint [name] [--at STAGE]` | New checkpoint; becomes current. No name: the template's next stage; `--at` alone: one more take at a stage (`design-2`). |
| `mh template [name] [--list] [--clear]` | Stage template — default names for the checkpoints ahead. |
| `mh save [CKPT] [--to CKPT] [--file MD] [--session-id ID] [--transcript P]` | Purify the current session into a checkpoint. |
| `mh save [CKPT] --compact --file MD` | Store an agent-written summary instead of the full dialog. |
| `mh import [--to CKPT] [--agent A]... [--dry-run]` | Backfill this project's past sessions (Claude Code, pi, Codex). |
| `mh load [CKPT...] [--no-links] [--budget N] [--all] [--json]` | Warm-start pack: selection + linked closure, time-merged. |
| `mh link A B` / `mh unlink A B` | Make checkpoints load together / stop that. |
| `mh list` / `mh show CKPT[/SESSION]` / `mh search Q` | Inspect the hub. |
| `mh trace CKPT/SESSION` | Find the original transcript a saved session was purified from. |
| `mh rm CKPT[/SESSION] [-x N] [--force]` | Delete a checkpoint, a session, or one exchange. |
| `mh mv CKPT/SESSION CKPT` / `mh rename CKPT NAME` | Move a session / rename a checkpoint. |
| `mh edit CKPT/SESSION -x N [--user T] [--agent T]` | Rewrite one side of an exchange. |
| `mh back [N]` / `mh forward [N]` / `mh goto CKPT` | Move the current pointer. |
| `mh status` / `mh log` | Position and counts / the hub's git journal. |
| `mh sync` | `pull --rebase` + `push` to `origin`; conflicts auto-abort. |
| `mh hubs [--prune]` | All registered hubs. |
| `mh ui [--port N] [--budget N\|none] [--read-only] [--detach] [--stop] [--session ID]` | Open the checkpoint map in a browser and curate the hub. |
| `mh hook install [--user] [--remove] [--budget N]` | Automate load/save through Claude Code hooks. |
| `mh skill install` | Install the Claude Code skill. |

## Saving: purified, or compacted

`mh save` is one deterministic pass — no LLM call, no network. It finds this
session's transcript, pairs each user turn with the assistant text that follows,
strips everything that isn't dialog (thinking blocks, tool calls and results,
subagent traffic, `<system-reminder>`, harness wrappers, interrupted turns),
drops the trailing question that triggered the save, then writes
`<end-time>_<session-key>.md` and commits. A slash command the agent answered —
`/mh load` — is kept as you typed it; one nobody answered (`/clear`, `/model`) is
harness noise and goes.

The timestamp is the session's **end** time, so time-merged loading reflects when
work actually happened. A session lives in exactly one checkpoint: re-saving
replaces, never duplicates — even after the current pointer has moved on, a plain
`mh save` updates the session where it already is, and `mh save --to <ckpt>` moves
it. The hooks and the map's save button follow the same rule.

`mh save --compact --file <md>` stores a summary instead of the full dialog.
**mh does not summarize by itself** — it has no model and makes no network calls;
the agent driving the session writes the summary, and the skill carries that
workflow, so in practice you just ask for a compact save. Run it in a shell with
no agent and it fails **deliberately** rather than falling back to purified
dialog. A compacted save lands under the session's real identity, so it replaces
a purified save of the same session — one representation per session.

## Hands-free: `mh hook install`

The skill relies on the agent *remembering* to run mh. Hooks remove the
remembering:

```sh
mh hook install          # this project (.claude/settings.local.json)
mh hook install --user   # every project (~/.claude/settings.json)
```

From the next Claude Code session on: **SessionStart** runs `mh load` and its
output is injected straight into context, so memory arrives before the first
word; **SessionEnd** and **PreCompact** run `mh hook save` — the latter
snapshots the dialog right before compaction would destroy it.

The handlers are deliberately forgiving: no hub, no current checkpoint, or
nothing to save all exit 0 quietly, so a `--user` install never disturbs a
project that does not use mh. They also respect choices made mid-session — a
session already stored `--compact` is kept as is, and one routed `--to` another
checkpoint is updated there rather than duplicated. Undo any time with
`mh hook install --remove`.

## The map: `mh ui`

```console
$ mh ui
mh ui: http://127.0.0.1:7777/?t=<a fresh token, minted per run>
```

`mh ui --detach` starts the server in the background and prints the URL; that is
what `/mh ui` runs from inside an agent session, with the live panel pinned to
the session that asked (`$CLAUDE_CODE_SESSION_ID`). The pin holds only while
that session lives: quiet for ten minutes with a newer transcript in the
project, and the page follows the newest instead — saying so. Run it again and
it prints the running server's URL; `mh ui --stop` ends it; `mh status` shows it.
`mh skill install` also installs **`/mh-ui`**, a one-paragraph skill that does
only this — about 150 tokens of context instead of the whole `/mh` workflow.

A checkpoint timeline: nodes sized by session count, links drawn as arcs, the
current pointer ringed, and the sessions the next `mh load` would include picked
out at your token budget. Click through to **delete or rewrite a single
exchange**, delete or move sessions, and rename, delete or link checkpoints.
Every change is a commit in the hub, so `git -C .memoryhub revert` is the undo.
`--read-only` serves the map with all editing hidden. The same surgery works
from a terminal — `mh rm`, `mh mv`, `mh rename`, `mh edit` — so an agent can
curate memory on request without a browser.

Under the timeline sits **project memory** — the notes Claude Code keeps about
this project (`~/.claude/projects/<project>/memory/`), shown read-only: one card
per note with its type, its markdown body, the notes it links to (`[[name]]`,
clickable), and — when that transcript is still here — the session it came
from, opened on a page of its own. mh does not own that folder and never writes it; it just shows it next to
the checkpoints.

Under the map sits the **live session**: the transcript the agent is writing
right now, re-read whenever it grows, so what you type in the terminal shows up
in the browser a breath later. The feed shows the newest three exchanges — the
rest are one click away, so the map is never buried under a long session. It shows the session **unfiltered** — thinking, visible text and every tool
call in the order the agent emitted them, the calls of one reply gathered
under a rail as the parallel batch they ran as, a subagent's output labelled
as its own — because while you are watching a session happen, the tool calls are the
session. Pictures show too: one you pasted into the session, or a screenshot the
agent read, appears under the turn — served by mh from the transcript or the
file, never copied into the hub. (What gets *stored* is still purified dialog;
the panel's `full output` box turns the raw stream off.) You can curate it while it runs — drop
an exchange, rewrite an answer, restore either. Those decisions are kept as a draft
beside the hub (`.memoryhub/drafts/`, untracked, never in the journal) and
applied by *every* save of that session: `mh save`, the SessionEnd/PreCompact
hook, and the panel's own save button. So what you curate mid-session does not
come back when the session is finally stored, and dialog that arrives after you
curated it still does. The question the agent is still answering is shown but
never stored, exactly as `mh save` has always dropped it.

You can also **type back**. The composer sits at the bottom of the panel, pinned
to the window while the feed is in view. It does not fake a reply — mh has no model. It pastes what you wrote into the tmux pane the
session is running in, exactly as if you had typed it there, and the agent's
answer comes back through the transcript like any other turn. The pane is not
guessed: `mh hook load` records it at session start (tmux exports `TMUX_PANE`
into the hook), and every send re-checks that the pane is still there and that
the same agent is still alive inside it — a pane whose session has exited is
refused, never pasted into. Sessions outside tmux say so instead: open one with
`tmux new -s mh`, run `claude` inside it, and the composer lights up. Start tmux
as a shell, not as `tmux new -s mh claude` — that pane closes the moment claude
quits and takes the tmux session with it; a shell pane outlives `claude -c`
restarts, and mh recognises the agent that comes back in it. Typing back is
Linux-only for now — mh reads `/proc` to prove the pane still holds the agent.

The box is also a **projection of the CLI's input**: a message that starts with
`/` lists the skills and commands of the session's own agent — read from disk by
mh (`~/.claude/skills`, the project's `.claude/skills`, `commands/`, installed
plugins; pi's `~/.pi/agent/skills`) plus the few built-ins worth sending from a
browser; after `/model` come the names the CLI resolves and the models this
session has used. ↑↓ choose, ⏎ or ⇥ inserts, add the arguments, Ctrl+⏎ sends —
the message is pasted into the session as usual and the CLI runs it, so the
page never needs to know what a command does, and anything not on the list goes
through all the same. An agent mh has not verified (codex) gets no list, just a
line saying so.

Safety: loopback-only, a one-shot token minted per run, and the `Host` header
checked; the page is self-contained and works offline. **mh will not rewrite a
file it cannot reproduce byte-for-byte** — it parses and re-renders first, and
marks the session read-only if the result differs. Purified dialog often quotes
mh's own output (a session about MemoryHub contains `## User 1` lines as
content), and that guard is what stops an edit splitting a turn in half.

## Taking over a project with existing history

```console
$ mh init
$ mh import --dry-run     # what's out there
$ mh import
imported 17 sessions -> history (claude 11, codex 1, pi 5)
```

`mh import` discovers this project's past sessions across Claude Code, pi and
Codex, validated against each session's own recorded `cwd` (so sibling projects
never leak in), purifies each, and lands them in a `history` checkpoint as one
commit. Scope follows your cwd: run from the repo root for the whole project, or
from a subfolder for just that workstream. Already-saved sessions are skipped, so
re-running later picks up only what's new.

## Good to know

- **Loading**: `mh load` takes the current checkpoint (or the ones you name),
  expands across links, and emits whole sessions oldest → newest within
  `--budget` (default 20000 tokens — about a tenth of a 200k context, three
  or four typical sessions — keeping the newest contiguous suffix; the
  SessionStart hook takes its own size from `mh hook install --budget N`).
- **Token estimates are CJK-aware**: ~1 token per CJK character, ~4 ASCII
  characters per token — close enough for budgeting, with no tokenizer
  dependency.
- **Names in any script**: `mh checkpoint 数据管道` is as first-class as
  `mh checkpoint backtest`.
- **Several checkpoints at one stage**: `design`, `design-2`, `design-3`
  stack under one node of the timeline — a trailing number is another take at
  the same stage, and `mh checkpoint --at design` names the next one for you.
  `mh checkpoint dollar-bars --at research` puts a checkpoint at a stage its
  name does not say (recorded in the hub's `stages.toml`). They stay as
  independent as any other checkpoints — link them if they should load
  together — so parallel attempts, or one worktree per attempt, each get their
  own memory without leaving the stage they belong to.
- **Stage templates**: most projects move through the same skeleton — plan,
  design, build, test, deploy, monitor — with a field's own names for the
  steps. `mh template --list` shows ten (quant, frontend, backend, sdlc,
  mobile, devops, data, ml, sprint, hotfix); `mh template quant` (or
  `mh init --template quant`) records one in the hub, and from then on
  `mh checkpoint` with no name creates the next stage, `mh status` says where
  the project stands, and the map draws the stages still ahead as dashed nodes
  you can click. Nothing is created up front, so the timeline keeps its real
  dates. The hub's `template.toml` carries a copy of the stages: edit it to
  give a project its own sequence.
- **Traceable to the source**: a saved session records the id of the transcript
  it was purified from. `mh trace <ckpt>/<session>` resolves it to the original
  `.jsonl` on this machine (or says it is elsewhere); in the map, a saved
  session's panel links **open original ↗**, which opens the full unfiltered
  transcript — thinking, tool calls, pictures — on a page of its own
  (`?view=<id>`: only that transcript, pinned for good), so the purified
  session and its source sit side by side. Nothing machine-specific is stored
  in the hub; the id is the whole link.
- **Every mutation is a git commit.** Undo, rename, delete, merge: plain
  `git -C .memoryhub ...` — the hub is a normal repo.
- **Excluded, not ignored**: `mh init` writes `.git/info/exclude` in the project
  rather than touching your tracked `.gitignore`.
- **Durability**: the hub is excluded from the project repo, so the project's
  remote does not back it up — configure `origin` once and use `mh sync`.
- **Concurrency**: serialized by git's own `index.lock`. No custom locking.

## Development

```sh
git clone https://github.com/solknight48/memoryhub
cd memoryhub
uv run pytest                  # full E2E suite, subprocess CLI in a hermetic HOME
uv run ruff check && uv run ruff format --check   # what CI runs
uv tool install --force -e .   # so the installed mh is the code you are editing
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the invariants a change must keep;
[CHANGELOG.md](CHANGELOG.md) what changed when.

`purify.py` is vendored from the `purify-context` skill, with a parity test
pinning extraction semantics to it. `curate.py` is the only code that parses
session markdown, and must never rewrite a file whose parse → re-render is not
byte-identical. `server.py` is stdlib-only on purpose, so `typer` stays the
single runtime dependency.

## License

[MIT](LICENSE).
