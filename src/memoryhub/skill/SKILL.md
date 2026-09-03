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
1. If the context already contains an `<!-- mh | loaded:` header, a
   SessionStart hook has run `mh load` for you — do not run it again. Otherwise
   run `mh load` and treat the output as prior project memory. The header says
   which checkpoints were included. Trust it over guessing; if it contradicts
   the code, the code wins.
2. `mh status` shows the current checkpoint, position, and staleness.

## During / end of session
- `mh save` — purify THIS session (mechanical, no LLM cost) into the current
  checkpoint. Run it at session end, and whenever the user asks to save or
  checkpoint. Re-running later in the same session simply updates the saved
  file — never a duplicate. (If `mh hook install` is set up, a SessionEnd hook
  saves automatically; a manual `mh save` is still harmless.)
- `mh save [<checkpoint>] --compact --file <md>` — store a **summary you write**
  instead of the full purified dialog, when the user asks for a compact/
  summarized save (`--compact`, "compact this session", "压缩保存"). mh has no
  model of its own, so YOU are the summarizer:
  1. Write the summary to a temp file. Cover, in this order: the user's explicit
     requests and intent; key technical concepts; files and code sections
     touched and why; errors hit and how they were fixed; problems solved;
     every non-tool-result user message; pending tasks; what was in progress
     immediately before the save; and the next step if one is clearly implied.
  2. Preserve any security-relevant instruction or constraint **verbatim**, so
     it still applies to whoever loads this memory later.
  3. Quote the user's own words for anything in progress — do not paraphrase a
     task description, or the next session will drift.
  4. Then `mh save --compact --file <that file>`; delete the temp file after.
  It lands under the session's real identity, so it replaces (never duplicates)
  a purified save of the same session — one representation per session.
  If the user would rather have the CLI write it ("let claude compact it"),
  `mh save --compact --with agent [--focus <text>]` runs the session's own
  `claude -p` / `pi -p` on the purified dialog — a model call on the user's
  account, so only on request; the map's save button offers the same.
  Without `--file` the command fails by design; do not retry without `--compact`
  unless the user asks for the purified save instead.
- `mh checkpoint <name>` — start a new checkpoint (becomes current). Only when
  the user declares a new workstream or stage. Names may be in any script
  (`mh checkpoint 数据管道` is fine).
- **Another take at the same stage** ("second design", "再开一个 design",
  "one checkpoint per worktree at this stage"): `mh checkpoint --at <stage>`
  names it `<stage>-2`, `<stage>-3`, …; `mh checkpoint <name> --at <stage>`
  keeps a name of the user's choosing. Same-stage checkpoints are parallel
  branches through the stage on the map and stay independent unless linked.
- **A smaller scope under a checkpoint** ("sub-checkpoint for the head page",
  "design 下面开个 footer"): `mh checkpoint <name> --under <ckpt>` (or the
  dotted `mh checkpoint design.head-page`) creates `design.head-page`, drawn
  indented under its parent's node. Loading it loads the parents too; loading
  the parent alone stays at the parent, and `mh load --tree` loads whole
  nodes — each checkpoint in the pack with its node's sub-checkpoints. Not a
  take, not a template stage.
- **Stage templates** — when the user asks for a project-stage template or
  default checkpoint names ("use the quant template", "按量化流程建
  checkpoint", "what templates are there"): `mh template --list` shows them
  (quant, frontend, backend, sdlc, mobile, devops, data, ml, sprint, hotfix);
  `mh template <name>` records the choice. With a template set, `mh checkpoint`
  with no name creates the next stage — prefer it over inventing a name when the
  user says "next stage" / "下一阶段" — and `mh template` alone shows the
  progress. `mh template --clear` stops using one. Only on explicit request.
- `mh link A B` / `mh unlink A B` — only on explicit user request.
- Curation (`mh rm <ckpt>[/<session>] [-x N]`, `mh mv`, `mh rename`,
  `mh edit <ckpt>/<session> -x N --user/--agent`, `mh skip`/`mh unskip <ckpt>/<session>`
  to leave a session out of `mh load` or bring it back) — only on explicit user
  request ("delete that exchange", "移除这段", "rename the checkpoint"). Every
  curation is a hub commit; tell the user `git -C .memoryhub revert HEAD` is
  the undo.
- `mh trace <ckpt>/<session>` — find the original transcript a saved session
  was purified from ("show me the real session", "回到原始记录", "check what was
  cut"). Prints the `.jsonl` path when it is still on this machine. In the web
  UI the session panel links "open original", which opens the full transcript
  in the live panel.
- Navigation (`mh back`, `mh forward`, `mh goto <ckpt>`) — only on explicit
  user request; afterwards tell the user which checkpoint is now current.
- If the user wants load/save to happen automatically, offer `mh hook install`
  (project) or `mh hook install --user` (all projects): SessionStart injects
  `mh load`, SessionEnd and PreCompact run the save. Run it only on approval —
  it edits Claude Code settings.

## Web UI
- `/mh ui`, "open the map", "start the web UI" ("打开地图", "起 webui"): run
  exactly one command, `mh ui --detach`, and reply with the URL it prints —
  one line, nothing else. No checks before it and no diagnostics after: mh
  picks a free port by itself, prints the URL of a server that is already
  running instead of starting another, and follows THIS session's live panel
  (it reads `CLAUDE_CODE_SESSION_ID`). Never a bare `mh ui` (it blocks the
  shell). `mh ui --stop` ends the server — only on the user's request.
- The map also shows this project's Claude Code auto-memory (the `memory/`
  folder beside the transcripts) read-only, under the timeline — no command,
  it is just there when the folder exists.

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
