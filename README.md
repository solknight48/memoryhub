# MemoryHub (`mh`)

**English** | [简体中文](README.zh.md)

[![CI](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml/badge.svg)](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml)

Git-like checkpoints for AI session context. A session ends, `mh save` stores it
purified — the dialog only, no tool noise, no model call. The next session runs
`mh load` and the project's memory is back. `mh ui` is the map of it all.

![The timeline: stages, a second take, sub-checkpoints, a link, the stages still ahead](docs/img/map.png)

## Install

```sh
uv tool install git+https://github.com/solknight48/memoryhub
mh skill install           # teaches Claude Code the /mh workflow
```

Linux or macOS, git ≥ 2.32, Python ≥ 3.12.

## Quick start

```sh
cd my-site
mh init --template frontend   # a hub in the project, stage names ready
mh checkpoint                 # the first stage: requirement-analysis
# … work with Claude Code; at the end the agent runs:
mh save                       # this session, purified, into the checkpoint
# next time:
mh load                       # the memory, back in context
mh ui                         # the map
```

`mh hook install` makes Claude Code do the load and the save itself.

## The map

Click a node for what you can do with it.

![The node menu](docs/img/node-menu.png)

A checkpoint and its sessions. Untick a session and `mh load` leaves it out.

![A checkpoint with a skipped session](docs/img/checkpoint.png)

A session, purified: the dialog and nothing else. Edit or delete an exchange.

![A saved session](docs/img/session.png)

The session running right now, thinking and tool calls included, with the save
box on top: store it as the dialog, or as a summary the agent writes.

![The live session](docs/img/live.png)

![The save box, summary chosen](docs/img/save-box.png)

New checkpoint: the template's next stage, another take at this one, a
sub-checkpoint, or any name.

![The new-checkpoint menu](docs/img/new-checkpoint.png)

## Commands

| Command | What it does |
|---|---|
| `mh init [--global] [--claude] [--template T]` | Create the hub. |
| `mh checkpoint [name] [--at STAGE] [--under CKPT]` | New checkpoint; becomes current. No name: the template's next stage; `--at` alone: one more take at a stage (`design-2`); `--under`: a sub-checkpoint (`design.head-page`). |
| `mh template [name] [--list [-v]] [--clear]` | Stage template — default names for the checkpoints ahead. |
| `mh save [CKPT] [--to CKPT] [--file MD] [--session-id ID] [--transcript P]` | Purify the current session into a checkpoint. |
| `mh save [CKPT] --compact --file MD` | Store an agent-written summary instead of the full dialog. |
| `mh save [CKPT] --compact --with agent [--focus TEXT]` | Have the session's own CLI (`claude -p` or `pi -p`; `--with claude`/`pi` picks one) write the summary and store it. |
| `mh import [--to CKPT] [--agent A]... [--dry-run]` | Backfill this project's past sessions (Claude Code, pi, Codex). |
| `mh load [CKPT...] [--no-links] [--tree] [--budget N] [--all] [--json]` | Warm-start pack: selection + linked closure, time-merged; `--tree` adds the sub-checkpoints under the selection. |
| `mh link A B` / `mh unlink A B` | Make checkpoints load together / stop that. |
| `mh list` / `mh show CKPT[/SESSION]` / `mh search Q` | Inspect the hub. |
| `mh trace CKPT/SESSION` | Find the original transcript a saved session was purified from. |
| `mh rm CKPT[/SESSION] [-x N] [--force]` | Delete a checkpoint, a session, or one exchange. |
| `mh mv CKPT/SESSION CKPT` / `mh rename CKPT NAME` | Move a session / rename a checkpoint. |
| `mh edit CKPT/SESSION -x N [--user T] [--agent T]` | Rewrite one side of an exchange. |
| `mh skip CKPT/SESSION` / `mh unskip CKPT/SESSION` | Leave a session out of `mh load` (it stays in its checkpoint) / load it again. |
| `mh back [N]` / `mh forward [N]` / `mh goto CKPT` | Move the current pointer. |
| `mh status` / `mh log` | Position and counts / the hub's git journal. |
| `mh sync` | `pull --rebase` + `push` to `origin`; conflicts auto-abort. |
| `mh hubs [--prune]` | All registered hubs. |
| `mh ui [--port N] [--budget N\|none] [--read-only] [--detach] [--stop] [--session ID]` | Open the checkpoint map in a browser and curate the hub. |
| `mh hook install [--user] [--remove] [--budget N] [--tree]` | Automate load/save through Claude Code hooks. |
| `mh skill install` | Install the Claude Code skill. |

## Hands-free

```sh
mh hook install            # this project: load at session start, save at the end
mh hook install --user     # every project
```

The SessionStart hook injects `mh load`; SessionEnd and PreCompact run `mh save`.
`mh hook install --remove` undoes it.

## Good to know

- **Purified** means the User/Agent dialog only. Tool calls, thinking, harness
  wrappers and the unanswered last question are stripped by rule, mechanically.
- **Checkpoints are independent.** `mh link A B` makes two load together, merged
  in time order. `mh load` packs the newest sessions first, within `--budget`
  (20 000 tokens by default).
- **Takes**: `design-2` is another path through the same stage. **Sub-checkpoints**:
  `design.header` is a scope inside design; loading it loads design too, and
  `--tree` loads a node whole.
- **Templates** name the stages of a kind of project (`mh template --list`).
  Chosen in the terminal; the map draws the stages still ahead.
- **Skip** a session (`mh skip`, or the box on its row) and every load leaves
  it out while it stays in its checkpoint.
- **Summary instead of dialog**: `mh save --compact --with agent` has the
  session's own CLI (`claude -p`, `pi -p`) write it — one model call, the
  running session untouched.
- **Every change is a commit** in `.memoryhub/`, a normal git repo you can push.
  `git -C .memoryhub revert HEAD` is the undo.
- **Local only.** The map listens on loopback with a per-run token. Nothing
  leaves the machine unless you push the hub.

## Development

```sh
uv run pytest -q           # the suite, hermetic, in parallel
uv run ruff check src tests && uv run ruff format --check src tests
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the invariants a change must keep;
[CHANGELOG.md](CHANGELOG.md) what changed when. `scripts/showcase.py` rebuilds
the screenshots above from a throwaway project.

## License

[MIT](LICENSE).
