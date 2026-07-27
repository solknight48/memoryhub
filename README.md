# MemoryHub (`mh`)

**English** | [简体中文](README.zh-CN.md)

Git-like checkpoints for AI session context.

Every Claude Code session starts from zero. MemoryHub fixes that: when a session
ends, `mh save` **purifies** it (pure User/Agent dialog — tool calls, thinking, and
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
uv tool install git+https://github.com/solknight48/memoryhub
mh skill install           # teach Claude Code sessions the workflow
```

**Requirements**: Linux or macOS, git ≥ 2.32, Python ≥ 3.12. `mh` shells out to
the system `git` and touches nothing platform-specific; the test suite runs on
both. Windows is untested.

### Updating, and working from a clone

`uv tool install` **copies** the source, so an install made from a path is a
snapshot: `git pull` in the clone does not change the installed `mh`, and a new
command like `mh ui` simply will not appear. Pick one:

```sh
# follow your working tree — every edit and every `git pull` is live,
# and there is nothing to update afterwards
uv tool install --force -e .

# or re-snapshot on demand, from the clone or straight from GitHub
uv tool install --force .
uv tool install --force git+https://github.com/solknight48/memoryhub
```

To see which one you have:

```sh
cat "$(uv tool dir)"/memoryhub/lib/python*/site-packages/memoryhub-*.dist-info/direct_url.json
```

`"editable": true` means it follows your working tree. If `mh --help` is missing
a command you know is in the source, this is why.

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
| `mh save [CKPT] [--to CKPT] [--file MD] [--session-id ID] [--transcript P]` | Purify the current session into a checkpoint. |
| `mh save [CKPT] --compact --file MD` | Store an agent-written summary of this session instead of the full dialog. |
| `mh import [--to CKPT] [--agent A]... [--dry-run]` | Backfill: discover this project's past sessions (Claude Code, pi, Codex) launched in your cwd's subtree and import them into a checkpoint. |
| `mh load [CKPT...] [--no-links] [--budget N] [--all] [--json]` | Warm-start pack: selection + linked closure, time-merged. |
| `mh link A B` / `mh unlink A B` | Make checkpoints load together / stop that. |
| `mh list` / `mh show CKPT[/SESSION]` / `mh search Q` | Inspect the hub. |
| `mh back [N]` / `mh forward [N]` / `mh goto CKPT` | Walk the current pointer across the time-ordered checkpoints. |
| `mh status` | Position, counts, staleness, remote. |
| `mh log` | The hub's git journal (every mutation is a commit). |
| `mh sync` | `pull --rebase` + `push` to `origin`; conflicts auto-abort, hub restored. |
| `mh hubs [--prune]` | All registered hubs. |
| `mh ui [--port N] [--read-only]` | Open the checkpoint map in a browser and curate the hub. |
| `mh skill install` | Install the Claude Code skill. |

## What `mh save` actually does

One deterministic pass — no LLM call, no network:

1. **Resolve the target checkpoint** — `--to CKPT` (exact slug, unique prefix, or
   1-based index from `mh list`), otherwise the `current` pointer. No current
   checkpoint and no `--to` is an error, never a silent default.
2. **Find the transcript**, first match wins: `--transcript PATH` (schema
   auto-detected) → `--session-id ID` or `$CLAUDE_CODE_SESSION_ID`, globbed
   across `~/.claude/projects/*/` → otherwise this project's newest transcript
   across all agents, since a live session is always its own newest.
   (`--file MD` skips steps 2–5 and stores markdown you supply verbatim.)
3. **Pair the dialog** — walk the JSONL in order, pairing each user turn with the
   assistant text that follows it. Consecutive unanswered user messages merge
   into one **User** turn; assistant text before any question is ignored.
4. **Strip everything that isn't dialog** — mechanically, by rule:
   - assistant **thinking blocks, tool calls, and tool results** — only
     `type: "text"` content blocks survive;
   - **subagent traffic** and meta records (`isSidechain`, `isMeta`);
   - `<system-reminder>…</system-reminder>` blocks, anywhere in a message;
   - harness wrappers whose message *starts* with `<command-name>`,
     `<command-args>`, `<local-command-stdout>`, `<bash-input>`,
     `<bash-stdout>`, `<user-prompt-submit-hook>`, and friends — matched at the
     start only, so a genuine question that merely mentions a tag survives;
   - turns cancelled by `[Request interrupted by user` / `[Request cancelled`.
5. **Drop the trailing unanswered turn** — the "save this session" request that
   triggered the run never lands in the record. (`mh import` keeps it: archival
   imports preserve the full history.) Nothing left after this is an error, so
   an empty session never becomes an empty file.
6. **Write `<end-time>_<key>.md`** into the checkpoint directory. The timestamp
   is the session's **end** time — the last record's timestamp in local time,
   falling back to the transcript's mtime — so time-merged loading reflects when
   work actually happened, even for sessions saved late. The key is the session's
   identity: `7aee4e68` (Claude, first 8 of the uuid), `pi-…`, or `cx-…`. **Any
   existing file with the same key in that checkpoint is deleted first** —
   re-saving a session replaces it and moves it to its new end time; it never
   duplicates.
7. **Commit** — `git add -A` and `save: <file> -> <checkpoint>` in the hub. A
   save that changed nothing commits nothing.

The rendered file is `# Session Context`: a provenance line naming the source
transcript, session id, and exchange count, then `## User 1` / `## Agent 1`
pairs separated by `---`. An answered-but-silent turn renders as
`_(no textual reply captured)_`.

```markdown
# Session Context

_Pure dialog extracted from `7aee4e68-….jsonl` (session `7aee4e68-…`). 12
exchanges. Tool calls, results, and internal reasoning removed._

## User 1

I want to build a memory management extension for terminal use.

## Agent 1

A "git for context" — nice concept. Let me take a quick look …
```

## Compacted saves: `mh save --compact`

Sometimes you want the *gist* of a session in memory, not all forty exchanges of
it. `mh save --compact` stores a summary instead of the purified dialog:

```console
$ mh save backtest --compact --file /tmp/summary.md
saved 2026-07-27_1512_fb9fbc61.md -> backtest (3 sessions)
```

**mh does not summarize by itself** — it has no model, no API key, and makes no
network calls, and `--compact` does not change that. The agent driving the
session writes the summary and hands it over with `--file`; the mh skill carries
that workflow, so in practice you just ask for a compact save and the agent does
both halves. Run `mh save --compact` from a bare shell with no summary and it
fails, deliberately: falling back to purified dialog would put a representation
in the checkpoint that you did not ask for.

Unlike plain `--file` (which keys off the filename), a compacted save lands under
the **session's real identity**, so it replaces a purified save of the same
session rather than sitting beside it — one representation per session, whichever
you saved last. The file is a distinct document type (`# Session Context —
Compacted`), which `mh ui` shows as a summary rather than exchanges: there are no
turns to edit individually, so it is read-only there by design. This also means a
summary that *quotes* the conversation can't be mistaken for dialog.

## The map: `mh ui`

```console
$ mh ui
mh ui: http://127.0.0.1:7777/?t=iZOfgx9wYdtc7eA9YTSyYQ
```

A checkpoint timeline — nodes sized by session count, linked checkpoints joined
by an arc, the current pointer ringed, and the sessions the next `mh load` would
actually include picked out at your token budget. Click a checkpoint for its
sessions, a session for its exchanges.

From there you can **delete or rewrite a single exchange**, delete or move a
whole session, and rename, delete, link or unlink checkpoints. Every change is a
commit in the hub (`curate: …` in `mh log`), so `git -C .memoryhub revert` is
the undo. `--read-only` serves the map with editing disabled.

Two things make editing safe rather than reckless:

- **mh will not rewrite a file it cannot reproduce.** Before any edit it parses
  the session and re-renders it; unless the result matches the original
  byte-for-byte the session is marked read-only in the UI and left alone. This
  matters because purified dialog often *quotes* mh's own output — a session
  about MemoryHub contains `## User 1` lines as content — and a parser that
  guessed wrong would silently split a turn in half.
- **Nothing is written until the commit is known to work.** A curation writes
  then commits; if the commit failed afterwards, the change would sit on disk
  outside the journal. mh checks the hub can commit *first*, so an error means
  nothing happened.

Serving is loopback-only and every request carries a one-shot token minted at
startup (any page in your browser can otherwise POST to `127.0.0.1`), with the
`Host` header checked so a hostile DNS name cannot be pointed at the port. The
page is self-contained — no CDN, no network — so it works offline.

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
- **Saving** is detailed above: one file per session per checkpoint, keyed by
  session identity and stamped with the session's end time.
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
git clone https://github.com/solknight48/memoryhub
cd memoryhub
uv run pytest              # full E2E suite (subprocess CLI in a hermetic HOME)
uv tool install --force -e .   # so the installed `mh` is the code you are editing
```

Layout: `src/memoryhub/{cli,hub,git,purify,checkpoint,load,agents,curate,server}.py`;
the Claude Code skill and the `mh ui` page ship as package data in
`src/memoryhub/{skill,ui}/`.

- `purify.py` is vendored from the `purify-context` skill — a parity test pins
  extraction semantics to it, and skips when that skill isn't on the machine.
- `curate.py` is the only code that parses session markdown (`load`, `show` and
  `search` read files verbatim), and must never rewrite a file whose
  parse → re-render isn't byte-identical.
- `server.py` is stdlib-only on purpose, so `typer` stays the single runtime
  dependency; its `dispatch()` is a plain function, so the API is tested without
  a socket.

## License

[MIT](LICENSE).
