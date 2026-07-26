# MemoryHub (`mh`)

Git-like checkpoints for AI session context.

Every Claude Code session starts from zero. MemoryHub fixes that: when a session
ends, `mh save` **purifies** it (pure Q&A markdown — tool calls, thinking, and
harness noise stripped, mechanically, no LLM cost) and stores it into a
**checkpoint**. A checkpoint is a sub-hub: a named container of purified
sessions. Checkpoints are **independent** by default; **link** two and they
**load together, merged in time order**. A new session runs `mh load` and gets
the project's memory back.

```
.memoryhub/                                  ← the hub: a normal git repo
  checkpoints/
    2026-07-14_1650_data-pipeline/           ← checkpoint: <created>_<name>/
      2026-07-10_1432_a1b2c3d4.md            ← purified session: <time>_<session-id>.md
      2026-07-12_0910_e5f6a7b8.md
    2026-07-17_1820_backtest-scaffold/
      2026-07-15_1100_c9d0e1f2.md
  links.toml                                 ← linked checkpoints load together
  current                                    ← untracked pointer: the current checkpoint
```

## Install

```sh
uv tool install .          # or:  uv tool install -e .  (hackable)
mh skill install           # teach Claude Code sessions the workflow
```

Assumes macOS, git ≥ 2.32, Python ≥ 3.12.

## Quickstart

```console
$ cd ~/dev/tickstore
$ mh init                        # hub at the project root; prints a CLAUDE.md snippet
$ mh checkpoint data-pipeline    # create a checkpoint; it becomes current

# ... work with Claude; at session end (agent runs this itself via the skill):
$ mh save
saved 2026-07-18_0941_7aee4e68.md -> data-pipeline (1 sessions)

# next session, warm start:
$ mh load
<!-- mh | loaded: data-pipeline | 1 of 1 sessions | @ 3f1c2ab -->
...

# a second workstream, later linked to the first:
$ mh checkpoint backtest
$ mh save
$ mh link data-pipeline backtest
$ mh load                        # sessions of BOTH, merged in time order
<!-- mh | loaded: backtest + data-pipeline (linked) | 3 of 3 sessions | @ 9d8e7f6 -->
```

## Commands

| Command | What it does |
|---|---|
| `mh init [--global] [--claude]` | Create the hub (`--claude` appends the Memory snippet to CLAUDE.md). |
| `mh checkpoint <name>` | New checkpoint (sub-hub); becomes current. |
| `mh save [--to CKPT] [--file MD] [--session-id ID] [--transcript P]` | Purify the current session into a checkpoint. |
| `mh import [--to CKPT] [--agent A]... [--dry-run]` | Backfill: discover this project's past sessions (Claude Code, pi, Codex) launched in your cwd's subtree and import them into a checkpoint. |
| `mh load [CKPT...] [--no-links] [--budget N] [--all] [--json]` | Warm-start pack: selection + linked closure, time-merged. |
| `mh link A B` / `mh unlink A B` | Make checkpoints load together / stop that. |
| `mh list` / `mh show CKPT[/SESSION]` / `mh search Q` | Inspect the hub. |
| `mh back [N]` / `mh forward [N]` / `mh goto CKPT` | Walk the current pointer across the time-ordered checkpoints. |
| `mh status` | Position, counts, staleness, remote. |
| `mh log` | The hub's git journal (every mutation is a commit). |
| `mh sync` | `pull --rebase` + `push` to `origin`; conflicts auto-abort, hub restored. |
| `mh hubs [--prune]` | All registered hubs. |
| `mh skill install` | Install the Claude Code skill. |

## Taking over a project with existing history

```console
$ cd ~/dev/legacy-project
$ mh init
$ mh import --dry-run     # what's out there, across all agents
$ mh import
imported 17 sessions -> history (claude 11, codex 1, pi 5)
$ mh load                 # the project's whole past, time-merged
```

`mh import` discovers this project's past sessions across **Claude Code**
(`~/.claude/projects`), **pi** (`~/.pi/agent/sessions`), and **Codex**
(`~/.codex/sessions`), validated against each session's own recorded `cwd` (so
sibling projects never leak in), purifies each mechanically, and lands them in
a `history` checkpoint (`--to` overrides) as one git commit.

**Scope follows your cwd**: run from the repo root and the whole project's
history is imported; run from a subfolder and only sessions launched in that
subtree are imported — one workstream at a time:

```console
$ cd ~/dev/legacy-project/backtest
$ mh import --to backtest     # just the backtest workstream's sessions
```

Already-saved sessions are skipped, so re-running `mh import` later picks up
only what's new. Archival imports keep the final unanswered turn (unlike live
`mh save`, which drops the request that triggered it). Adding another agent is
one discover function + one extract function in `src/memoryhub/agents.py`.

## Semantics worth knowing

- **Loading**: `mh load` takes the current checkpoint (or the ones you name),
  expands across links (connected component), and emits whole sessions oldest →
  newest within `--budget` (default ~6000 tokens; selection keeps the newest
  contiguous suffix, the omission footer names what was cut).
- **Session identity**: one file per session per checkpoint. Re-saving the same
  session replaces its file — never duplicates. Filenames carry the session's
  *end time*, so merged ordering reflects when work actually happened.
- **`mh save` works from any agent**: inside Claude Code it resolves the live
  session via `$CLAUDE_CODE_SESSION_ID`; elsewhere (pi, codex, plain shell) it
  takes the project's newest transcript across all agents — a live session is
  always its own newest. `--transcript` auto-detects the file's schema.
- **Walking** moves only the untracked `current` pointer; nothing is checked
  out, all checkpoints stay on disk.
- **Every mutation is a git commit** in the hub (`mh log`). Undo, surgery,
  rename, delete, merge: plain `git -C .memoryhub ...` — the hub is a normal
  repo and mh never fights you over it.
- **Excluded, not ignored**: `mh init` writes `.git/info/exclude` in the project
  (local-only) rather than touching your tracked `.gitignore`.
- **Concurrency**: two sessions writing the same hub are serialized by git's own
  `index.lock`; mh surfaces a retry hint. No custom locking.
- **Durability**: the hub is excluded from the project repo, so the project's
  remote does **not** back it up — configure `origin` once and use `mh sync`.
- Relationship to the `purify-context` skill: same extraction (vendored,
  parity-tested). That skill remains for ad-hoc exports; `mh save` is
  purify + store + commit in one deterministic step.

## Development

```sh
uv run pytest        # full E2E suite (subprocess CLI in a hermetic HOME)
```
