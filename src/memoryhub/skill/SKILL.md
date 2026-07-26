---
name: mh
description: >-
  Load and save project memory with the `mh` CLI (MemoryHub): purified session
  contexts stored in .memoryhub/ checkpoints. Use at the START of any session in
  a project containing .memoryhub/ (run `mh load` before other work); when the
  user says "save/checkpoint this session", "保存上下文", "load memory",
  "pick up where we left off", "link checkpoints", "go back a stage", or asks to
  take over a project / import old sessions / backfill history ("接管项目",
  "导入历史会话"); and at session end to save the purified session with `mh save`.
---

# MemoryHub workflow

`.memoryhub/` is the project's context hub: **checkpoints** (sub-hubs) holding
**purified sessions**, versioned in the hub's own git repo and managed by `mh`
(see `mh --help`). Checkpoints are independent of each other; **linked**
checkpoints load together, their sessions merged in time order.

## Session start
1. Run `mh load` and treat the output as prior project memory. The header says
   which checkpoints were included. Trust it over guessing; if it contradicts
   the code, the code wins.
2. `mh status` shows the current checkpoint, position, and staleness.

## During / end of session
- `mh save` — purify THIS session (mechanical, no LLM cost) into the current
  checkpoint. Run it at session end, and whenever the user asks to save or
  checkpoint. Re-running later in the same session simply updates the saved
  file — never a duplicate.
- `mh checkpoint <name>` — start a new checkpoint (becomes current). Only when
  the user declares a new workstream or stage.
- `mh link A B` / `mh unlink A B` — only on explicit user request.
- Navigation (`mh back`, `mh forward`, `mh goto <ckpt>`) — only on explicit
  user request; afterwards tell the user which checkpoint is now current.

## Taking over a project with existing history
When the user asks to take over a project, import old sessions, or backfill
history: run `mh import --dry-run` first and show the summary, then on approval
`mh import`. It discovers the project's past sessions across ALL agents
(Claude Code, pi, Codex), purifies them, and lands them in a `history`
checkpoint in one commit. Scope follows the invocation directory: run it from
the project root for the whole history, or from a subfolder to import only that
workstream's sessions (e.g. `cd backtest && mh import --to backtest`).
Re-running later only picks up new sessions. Then `mh load history` (or
`mh load` if history is current) to absorb the past.

## Rules
- Do not create HANDOFF.md / EXP.md / context.md files in a project that has a
  hub — that content belongs in checkpoints via `mh save`.
- `mh save --file <md>` ingests an already-purified markdown file (the
  purify-context skill's output format) when the user provides one. The
  purify-context skill remains for ad-hoc exports; `mh save` is
  purify + store + commit in one step.
- If there is no hub and the user asks for memory: propose `mh init`, run it on
  approval, then `mh checkpoint <name>` and proceed.
- The hub is a normal git repo. Anything `mh` does not cover (rename, delete,
  merge, undo) is `git -C .memoryhub ...` — only on user request.
