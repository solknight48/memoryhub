<p align="center">
  <strong>English</strong> · <a href="https://github.com/solknight48/memoryhub/blob/main/README.zh.md">简体中文</a>
</p>

![The MemoryHub map: a project's sessions as checkpoints on a timeline](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/map.png)

# MemoryHub

**Manage every AI coding session as git-backed memory — save it purified, load it back, curate it on a map.**

*Managing context is all you need; leave everything else to the model.*

MemoryHub (`mh`) is a small Python CLI and a local web map for Claude Code, pi and Codex. A session ends and `mh save` keeps it; the next session runs `mh load` and the project's memory is back; `mh ui` is where you manage all of it.

- **Every session kept, none of the noise** — purified to the User/Agent dialog by rule, no model call, stored as a file in a checkpoint, committed to a git repo you own
- **Loaded when it matters** — the next session starts from the checkpoint you are at, its parents and its links, newest first within a token budget
- **Curated, not hoarded** — skip a session, drop or rewrite an exchange, move a session, write a summary instead, from the map or the terminal
- **Shaped like the project** — stages from a template, parallel takes at a stage, sub-checkpoints for a smaller scope, links between the ones that belong together

[![CI](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml/badge.svg)](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)
![Python](https://img.shields.io/badge/python-3.12%2B-3776ab?style=flat-square)
![Agents](https://img.shields.io/badge/agents-Claude%20Code%20%C2%B7%20pi%20%C2%B7%20Codex-7C3AED?style=flat-square)
[![PyPI](https://img.shields.io/pypi/v/memoryhub-mh?style=flat-square&color=0891b2)](https://pypi.org/project/memoryhub-mh/)

```bash
uv tool install memoryhub-mh && mh skill install
```

Linux or macOS · git ≥ 2.32 · Python ≥ 3.12 · on [PyPI](https://pypi.org/project/memoryhub-mh/) as `memoryhub-mh`. See the [changelog](https://github.com/solknight48/memoryhub/blob/main/CHANGELOG.md) for what is new.

## See it in action

Real captures of the map on a small café-site project, not mockups.

| Click a node | Open a checkpoint | Save the running session |
|---|---|---|
| ![The node menu: open, make current, sub-checkpoint, another take, link, rename, delete](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/node-menu.png) | ![A checkpoint's sessions; one unticked and skipped on load](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/checkpoint.png) | ![The save box: a summary or the full dialog, to which checkpoint](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/save-box.png) |
| Everything you can do to it, with a word on each. | Untick a session and every load leaves it out. | A summary the agent writes — or every word, curated by you. |

A saved session is the dialog and nothing else. Edit or delete an exchange; the hub keeps the history.

![A saved session, purified, with edit and delete on each exchange](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/session.png)

The session running right now, thinking and tool calls included, with the save box on top.

![The live session panel with the save box](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/live.png)

New checkpoint: the template's next stage, another take at this one, a sub-checkpoint, or any name.

![The new-checkpoint menu](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/new-checkpoint.png)

## Quick start

### 1. Install

```bash
uv tool install memoryhub-mh   # the package is memoryhub-mh, the command is mh
mh skill install               # teaches Claude Code the /mh workflow
```

| | Install | Upgrade |
|---|---|---|
| uv — fetches Python 3.12 if the machine has none | `uv tool install memoryhub-mh` | `uv tool upgrade memoryhub-mh` |
| pipx | `pipx install memoryhub-mh` | `pipx upgrade memoryhub-mh` |
| pip — Python ≥ 3.12, in a venv | `pip install memoryhub-mh` | `pip install -U memoryhub-mh` |

Hooks run plain `mh`, so it must be on PATH: uv and pipx put it there, a venv only while it is active. The development version is `uv tool install git+https://github.com/solknight48/memoryhub`.

### 2. Give the project a hub

```bash
cd my-site
mh init --template frontend   # .memoryhub/ with the stages of a frontend project
mh checkpoint                 # the first stage: requirement-analysis
```

### 3. Work, save, load

```bash
# … work with Claude Code; at the end the agent runs:
mh save                       # this session, purified, into the checkpoint
# next time:
mh load                       # the memory, back in context
mh ui                         # the map
```

`mh hook install` makes Claude Code run the load at session start and the save at the end.

## Manage sessions

| You want to | On the map | In the terminal |
|---|---|---|
| Keep this session | save box → **Full dialog** | `mh save` |
| Keep a summary instead | save box → **Summary** | `mh save --compact --with agent` |
| Leave a session out of loads | untick it | `mh skip CKPT/SESSION` |
| Fix or drop one exchange | edit / delete on the exchange | `mh edit`, `mh rm -x N` |
| Move a session elsewhere | move… on its row | `mh mv CKPT/SESSION CKPT` |
| Load two checkpoints together | node → Link to… | `mh link A B` |
| Work in a smaller scope | node → Sub-checkpoint… | `mh checkpoint NAME --under CKPT` |
| Try the stage again, in parallel | node → Another take | `mh checkpoint --at STAGE` |
| Load a node whole | tick "with sub-checkpoints" | `mh load --tree` |
| Find where a session came from | open original ↗ | `mh trace CKPT/SESSION` |
| Bring in past sessions | — | `mh import` |
| Undo anything | — | `git -C .memoryhub revert HEAD` |

## Why MemoryHub

- **Purified, mechanically** — tool calls, thinking, harness wrappers and the unanswered last question are stripped by rule. What is stored reads like the conversation, and costs nothing to produce.
- **A git repo, not a database** — `.memoryhub/` is plain markdown in a normal repository: diff it, push it, revert it, read it without mh.
- **Independent by default** — checkpoints load alone unless you link them; a sub-checkpoint loads inside its parents; a take is a parallel path, not a copy.
- **The map tells the truth** — purple is exactly what the next `mh load` packs; a link the load does not reach is grey; a terminal change shows up within a poll.
- **Local only** — loopback, a per-run token, no cloud. Nothing leaves the machine unless you push the hub. The one model call there is, the summary, uses the CLI you already run.

## How it works

| Step | What happens |
|---|---|
| **Save** | The session's transcript is found, each user turn paired with the reply that followed, everything else stripped. |
| **Store** | The dialog lands as `<end-time>_<session>.md` in the current checkpoint, one commit in the hub. A session lives in exactly one checkpoint. |
| **Load** | The current checkpoint, its parents and its links; sessions merged by time, newest first, within the budget (20 000 tokens by default). |
| **Map** | `mh ui` draws the hub: stages, takes, sub-checkpoints, links, what the next load packs, and the session being written right now. |
| **Curate** | Skips, edits, moves and summaries are commits like any other; the map and the CLI share one rule for each. |

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

```bash
mh hook install            # this project: load at session start, save at the end
mh hook install --user     # every project
mh hook install --remove   # undo
```

SessionStart injects `mh load`; SessionEnd and PreCompact run `mh save`.

## Reference and scope

- [PyPI](https://pypi.org/project/memoryhub-mh/) — releases, each a `vX.Y.Z` tag published by CI · [CHANGELOG.md](https://github.com/solknight48/memoryhub/blob/main/CHANGELOG.md) — what changed when · [CONTRIBUTING.md](https://github.com/solknight48/memoryhub/blob/main/CONTRIBUTING.md) — the invariants a change must keep, and how a release is cut
- `scripts/showcase.py` rebuilds the screenshots above from a throwaway project
- Out of scope on purpose: a hosted service, typing into the running session, choosing the template from the map

## License

[MIT](https://github.com/solknight48/memoryhub/blob/main/LICENSE) — free to use, modify and distribute.

## Contributing

Issues and pull requests are welcome. Start with the [contribution guide](https://github.com/solknight48/memoryhub/blob/main/CONTRIBUTING.md); every change keeps the suite hermetic and both READMEs in step.
