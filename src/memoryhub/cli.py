"""mh — MemoryHub: git-like checkpoints for purified AI session context."""

from __future__ import annotations

import functools
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import typer

from . import __version__, curate, git, purify
from . import agents as agents_mod
from . import checkpoint as ck
from . import hooks as hooksmod
from . import hub as hubmod
from . import live as livemod
from . import load as loadmod
from . import relay as relaymod
from . import save as savemod
from . import templates as tmpl
from .hub import MhError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Git-like checkpoints for purified AI session context.",
)
skill_app = typer.Typer(help="Manage the Claude Code skill.")
app.add_typer(skill_app, name="skill")
hook_app = typer.Typer(help="Automate load/save through Claude Code hooks.")
app.add_typer(hook_app, name="hook")

JSON_OPT = typer.Option(False, "--json", help="Machine-readable output.")


def _print_version(value: bool):
    if not value:
        return
    # The path answers the classic support question — a snapshot install lives
    # under the tool dir and silently ignores `git pull`; an editable install
    # points into the working tree.
    print(f"mh {__version__} ({Path(__file__).resolve().parent})")
    raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Show the version and where mh is installed from.",
    ),
):
    pass


def die(message: str, code: int = 1):
    print(f"mh: {message}", file=sys.stderr)
    raise typer.Exit(code)


def guard(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except MhError as e:
            die(e.message, e.code)
        except git.GitError as e:
            if e.stderr:
                sys.stderr.write(e.stderr)
            die(git.explain(e))

    return wrapper


def _hub() -> Path:
    return hubmod.discover()


def _announce(hub: Path) -> None:
    print(f"hub: {hub}", file=sys.stderr)


def _emit_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# --- init --------------------------------------------------------------------


@app.command()
@guard
def init(
    global_: bool = typer.Option(False, "--global", help="Create the global hub at ~/.memoryhub."),
    claude: bool = typer.Option(
        False, "--claude", help="Append the Memory section to the project CLAUDE.md."
    ),
    template: str | None = typer.Option(
        None,
        "--template",
        help="Stage template for checkpoint names (see 'mh template --list').",
    ),
):
    """Create a hub for this project (or the global hub)."""
    if template is not None:
        tmpl.get(template)  # an unknown name fails before anything is created
    res = hubmod.init_hub(Path.cwd(), global_=global_)
    _announce(res.hub)
    if res.created:
        print(f"initialized hub at {res.hub}")
    else:
        print(f"hub already initialized at {res.hub}")
    if template is not None:
        rec = tmpl.use(res.hub, template)
        print(f"template: {rec['name']} — " + " → ".join(rec["stages"]))
        print("  'mh checkpoint' with no name creates the next stage")
    if res.shadowed:
        print(
            f"note: this hub shadows {res.shadowed} for files under {res.root}",
            file=sys.stderr,
        )
    if global_:
        return
    if claude:
        path = hubmod.append_claude_snippet(res.root)
        print(f"appended Memory section to {path}")
    else:
        print("\nAdd this to the project CLAUDE.md (or rerun with --claude):\n")
        print(hubmod.CLAUDE_SNIPPET)


# --- capture -----------------------------------------------------------------


@app.command()
@guard
def checkpoint(
    name: str | None = typer.Argument(
        None, help="Name for the new checkpoint; omitted, the template's next stage."
    ),
    at: str | None = typer.Option(
        None,
        "--at",
        help="Stage (timeline column) to put it at; alone, names it design-2, design-3, …",
    ),
    json_: bool = JSON_OPT,
):
    """Create a new checkpoint (sub-hub) and make it current."""
    hub = _hub()
    _announce(hub)
    if name is None and at is not None:
        name = ck.next_at(hub, at)
    elif name is None:
        name = tmpl.next_name(hub)
    c = ck.create(hub, name, stage=at)
    prog = tmpl.progress(hub)
    if json_:
        _emit_json(
            {
                "checkpoint": c.slug,
                "created": c.created,
                "path": str(c.path),
                "template": prog and {k: prog[k] for k in ("name", "done", "total", "next")},
            }
        )
        return
    column = ck.stage_of(hub, c.slug)
    members = next((col["members"] for col in ck.stages(hub) if col["stage"] == column), [])
    others = ", ".join(m for m in members if m != c.slug)
    where = f" — at {column}, with {others}" if others else ""
    print(f"checkpoint '{c.slug}' created (current){where}")
    if prog and any(st["slug"] == column for st in prog["stages"]):
        stage = next(i for i, st in enumerate(prog["stages"], 1) if st["slug"] == column)
        ahead = f"next: {prog['next']}" if prog["next"] else "the last stage"
        print(f"  stage {stage} of {prog['total']} in {prog['name']} — {ahead}")


@app.command()
@guard
def template(
    name: str | None = typer.Argument(
        None, help="Template to use for this hub's checkpoint names."
    ),
    list_: bool = typer.Option(False, "--list", help="Show the built-in templates."),
    clear: bool = typer.Option(False, "--clear", help="Stop using a template."),
    json_: bool = JSON_OPT,
):
    """Stage template: default checkpoint names, created in order by 'mh checkpoint'."""
    if list_:
        if json_:
            _emit_json(tmpl.catalogue())
            return
        for t in tmpl.catalogue():
            print(f"{t['name']:10} {t['title']}")
            for i, st in enumerate(t["stages"], 1):
                print(f"  {i:2}. {st['name']} — {st['about']}")
        print("\nmh template <name> uses one; mh checkpoint (no name) then creates its stages")
        return
    hub = _hub()
    _announce(hub)
    if clear:
        was = tmpl.clear(hub)
        print("template cleared" if was else "no template was set")
        return
    if name is not None:
        tmpl.use(hub, name)
    prog = tmpl.progress(hub)
    if json_:
        _emit_json(prog)
        return
    if prog is None:
        print("no template — 'mh template --list' shows them, 'mh template <name>' uses one")
        return
    print(f"template: {prog['name']} — {prog['done']} of {prog['total']} stages created")
    for i, st in enumerate(prog["stages"], 1):
        mark = "✓" if st["exists"] else ("→" if st["name"] == prog["next"] else " ")
        print(f"  {mark} {i:2}. {st['name']}")
    if prog["next"]:
        print(f"'mh checkpoint' creates {prog['next']} next")


def _resolve_session(hub: Path, session_id, transcript):
    """(source, session id, identity key, turns, last timestamp, per-turn
    models, live edits applied) for the session being saved. Shared by the
    purified and compacted paths so both land under the same identity — a
    compacted save replaces a purified one, and vice versa, instead of
    duplicating the session.

    Edits made to this session while it ran (the `mh ui` live panel) are folded
    in here, so every save path applies them: that is what stops a later save
    from resurrecting dialog the user already curated away.
    """
    root = hubmod.project_root_of(hub)
    sid_opt = session_id or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if transcript:
        src = purify.find_transcript(transcript=transcript)
        agent_name = agents_mod.detect_agent(src)
    elif sid_opt:
        src = purify.find_transcript(session_id=sid_opt)
        agent_name = "claude"
    else:
        # No session id in the environment (pi, codex, plain shell): the
        # newest transcript of this project across all agents — a live
        # session is always its own newest.
        candidates = agents_mod.discover(root)
        if not candidates:
            raise MhError("no transcripts found for this project (claude, pi, codex)")
        src = max(candidates, key=lambda d: d.path.stat().st_mtime).path
        agent_name = agents_mod.detect_agent(src)
    sid, key = agents_mod.identify(agent_name, src)
    turns, last_ts, models = agents_mod.extract(agents_mod.Discovered(agent_name, src, sid, key))
    turns, models, applied, _stale = livemod.apply(turns, models, livemod.read_draft(hub, key))
    return src, sid, key, turns, last_ts, models, applied


@app.command()
@guard
def save(
    checkpoint_ref: str | None = typer.Argument(
        None, metavar="[CHECKPOINT]", help="Target checkpoint (same as --to)."
    ),
    to: str | None = typer.Option(None, "--to", help="Target checkpoint (default: current)."),
    file: Path | None = typer.Option(
        None, "--file", help="Ingest an already-purified markdown file."
    ),
    compact: bool = typer.Option(
        False,
        "--compact",
        help="Store an agent-written summary of this session (needs --file).",
    ),
    session_id: str | None = typer.Option(
        None, "--session-id", help="Purify a specific session id."
    ),
    transcript: Path | None = typer.Option(
        None, "--transcript", help="Purify an explicit .jsonl transcript."
    ),
    json_: bool = JSON_OPT,
):
    """Purify the current session and store it into a checkpoint."""
    hub = _hub()
    _announce(hub)
    if checkpoint_ref and to and checkpoint_ref != to:
        raise MhError(f"two target checkpoints given: '{checkpoint_ref}' and '{to}'")
    ref = to or checkpoint_ref
    if ref:
        ck.resolve(hub, ref)  # a bad name fails before the transcript is read
    elif not hubmod.read_current(hub):
        raise MhError("no current checkpoint (run 'mh checkpoint <name>' or 'mh goto <ckpt>')")

    applied = 0  # live edits folded in; the --file branch stores a given document
    if compact:
        # mh has no model of its own: the agent driving the session writes the
        # summary and hands it over. Without one there is nothing to compact,
        # and falling back to purified dialog would put a representation in the
        # checkpoint that the flag did not ask for.
        if not file:
            raise MhError(
                "--compact needs the summary to store: mh does not summarize by "
                "itself. Let the agent write one and pass it with --file "
                "(the mh skill does this), or save without --compact."
            )
        if not file.is_file():
            raise MhError(f"file not found: {file}")
        summary = file.read_text(encoding="utf-8").strip()
        if not summary:
            raise MhError(f"{file} is empty — nothing to compact")
        src, sid, key, turns, last_ts, models, applied = _resolve_session(
            hub, session_id, transcript
        )
        # count what a purified save of this session would hold, so the two
        # representations never disagree about how many exchanges there were
        turns, _ = purify.drop_trailing_unanswered(turns, models)
        body = curate.render_compacted(summary, str(src), sid, len(turns))
        stamp = purify.stamp_for(last_ts, src)
    elif file:
        if not file.is_file():
            raise MhError(f"file not found: {file}")
        body = file.read_text(encoding="utf-8")
        stamp = datetime.fromtimestamp(file.stat().st_mtime).astimezone().strftime(ck.STAMP_FMT)
        key = ck.slugify(file.stem)[:40]
    else:
        src, sid, key, turns, last_ts, models, applied = _resolve_session(
            hub, session_id, transcript
        )
        turns, models = purify.drop_trailing_unanswered(turns, models)
        if not turns:
            raise MhError(f"no dialog found in {src.name}")
        body = purify.render(turns, str(src), sid, models)
        stamp = purify.stamp_for(last_ts, src)

    # An explicit `mh save` may replace a compacted summary with the dialog;
    # the automatic paths (hook, panel) never do.
    stored = savemod.store(hub, key, body, stamp, ref, replace_compacted=True)
    target, fname = stored.checkpoint, stored.file
    count = len(ck.resolve(hub, target.slug).sessions)
    if json_:
        _emit_json(
            {
                "checkpoint": target.slug,
                "file": fname,
                "path": str(target.path / fname),
                "sessions": count,
                "live_edits": applied,
                "moved_from": stored.moved_from,
            }
        )
    else:
        print(f"saved {fname} -> {target.slug} ({count} sessions)")
        if stored.moved_from:
            print(f"(moved from {stored.moved_from} — a session lives in one checkpoint)")
        if applied:
            print(f"({applied} live edit{'' if applied == 1 else 's'} applied)")


@app.command("import")
@guard
def import_(
    to: str | None = typer.Option(
        None, "--to", help="Target checkpoint (default: 'history', created if missing)."
    ),
    agent: list[str] | None = typer.Option(
        None,
        "--agent",
        help="Limit to specific agents (claude, pi, codex). Repeatable.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be imported; write nothing."
    ),
    json_: bool = JSON_OPT,
):
    """Backfill: import this project's past sessions (every agent) into a checkpoint."""
    hub = _hub()
    _announce(hub)
    root = hubmod.project_root_of(hub)
    # Scope follows the invocation directory: from the project root import
    # everything; from a subfolder import only sessions launched in its subtree.
    cwd = Path.cwd().resolve()
    scope = cwd if cwd.is_relative_to(root) and not cwd.is_relative_to(hub) else root
    if scope != root:
        print(
            f"scope: {scope.relative_to(root)}/ — only sessions launched in this "
            f"subtree (run from {root} to import the whole project)",
            file=sys.stderr,
        )
    found = agents_mod.discover(root, set(agent) if agent else None, scope=scope)
    existing = ck.existing_keys(hub)
    fresh = [d for d in found if d.key not in existing]
    skipped_existing = len(found) - len(fresh)

    items = []
    skipped_empty = 0
    for d in fresh:
        turns, last_ts, models = agents_mod.extract(d)
        if not turns:
            skipped_empty += 1
            continue
        stamp = purify.stamp_for(last_ts, d.path)
        body = purify.render(turns, str(d.path), d.sid, models)
        items.append((d, stamp, body, len(turns)))
    items.sort(key=lambda item: item[1])  # chronological

    counts: dict[str, int] = {}
    for d, *_ in items:
        counts[d.agent] = counts.get(d.agent, 0) + 1
    breakdown = ", ".join(f"{a} {n}" for a, n in sorted(counts.items()))
    skip_note = f"skipped: {skipped_existing} already in hub, {skipped_empty} with no dialog"

    if dry_run:
        if json_:
            _emit_json(
                {
                    "dry_run": True,
                    "would_import": [
                        {
                            "agent": d.agent,
                            "file": f"{stamp}_{d.key}.md",
                            "source": str(d.path),
                            "exchanges": n_turns,
                        }
                        for d, stamp, _body, n_turns in items
                    ],
                    "skipped_existing": skipped_existing,
                    "skipped_empty": skipped_empty,
                }
            )
            return
        for d, stamp, _body, n_turns in items:
            print(f"would import {d.agent}: {stamp}_{d.key}.md ({n_turns} exchanges)")
        print(
            f"dry run: {len(items)} to import -> {to or 'history'}"
            f"{f' ({breakdown})' if breakdown else ''}; {skip_note}"
        )
        return

    if not items:
        print(f"nothing to import ({skip_note})")
        return

    if to:
        target = ck.resolve(hub, to)
    else:
        cps = ck.list_checkpoints(hub)
        target = next((c for c in cps if c.slug == "history"), None)
        if target is None:
            target = ck.create(hub, "history", set_current=not cps)
    written = []
    for d, stamp, body, _n in items:
        written.append(ck.write_session(target, body, d.key, stamp))
    git.auto_commit(hub, f"import: {len(written)} sessions ({breakdown})")
    if json_:
        _emit_json(
            {
                "checkpoint": target.slug,
                "imported": written,
                "skipped_existing": skipped_existing,
                "skipped_empty": skipped_empty,
            }
        )
    else:
        print(f"imported {len(written)} sessions -> {target.slug} ({breakdown})")
        if skipped_existing or skipped_empty:
            print(skip_note)


# --- links -------------------------------------------------------------------


@app.command()
@guard
def link(a: str = typer.Argument(...), b: str = typer.Argument(...)):
    """Link two checkpoints so they load together."""
    hub = _hub()
    _announce(hub)
    edge = ck.add_link(hub, a, b)
    if edge is None:
        print("link already present (or self-link) — nothing to do")
    else:
        print(f"linked {edge[0]} -- {edge[1]}")


@app.command()
@guard
def unlink(a: str = typer.Argument(...), b: str = typer.Argument(...)):
    """Remove a link between two checkpoints."""
    hub = _hub()
    _announce(hub)
    edge = ck.remove_link(hub, a, b)
    if edge is None:
        print("no such link — nothing to do")
    else:
        print(f"unlinked {edge[0]} -- {edge[1]}")


# --- curation ----------------------------------------------------------------
# The same surgery the map (`mh ui`) offers, reachable from a terminal — the
# usual operator of mh is an agent, and an agent cannot click a browser.


def _undo_hint(hub: Path) -> None:
    print(f"undo: git -C {hub} revert HEAD")


def _split_session_ref(ref: str, usage: str) -> tuple[str, str]:
    ck_ref, _, file_ref = ref.partition("/")
    if not ck_ref or not file_ref:
        raise MhError(usage)
    return ck_ref, file_ref


@app.command()
@guard
def rm(
    ref: str = typer.Argument(
        ..., metavar="CKPT[/SESSION]", help="Checkpoint, or checkpoint/session-file (prefix ok)."
    ),
    exchange: int | None = typer.Option(
        None, "--exchange", "-x", help="Delete one exchange (1-based) instead of the whole session."
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Required to delete a checkpoint that still holds sessions."
    ),
    json_: bool = JSON_OPT,
):
    """Delete a checkpoint, a session, or a single exchange (git history keeps everything)."""
    hub = _hub()
    _announce(hub)
    ck_ref, _, file_ref = ref.partition("/")
    if file_ref:
        if exchange is not None:
            res = curate.delete_exchange(hub, ck_ref, file_ref, exchange)
            msg = f"deleted exchange {exchange} of {res['file']} ({res['exchanges']} left)"
        else:
            res = curate.delete_session(hub, ck_ref, file_ref)
            msg = f"deleted session {res['file']} from {res['checkpoint']}"
    else:
        if exchange is not None:
            raise MhError("-x needs a session: mh rm <checkpoint>/<session> -x N")
        c = ck.resolve(hub, ck_ref)
        if c.sessions and not force:
            raise MhError(
                f"'{c.slug}' still holds {len(c.sessions)} session(s); "
                f"pass --force to delete them all"
            )
        res = curate.delete_checkpoint(hub, c.slug)
        msg = f"deleted checkpoint {res['slug']} ({res['sessions']} sessions)"
    if json_:
        _emit_json(res)
    else:
        print(msg)
        _undo_hint(hub)


@app.command()
@guard
def mv(
    src: str = typer.Argument(..., metavar="CKPT/SESSION", help="Session to move (prefix ok)."),
    to: str = typer.Argument(..., metavar="CKPT", help="Destination checkpoint."),
    json_: bool = JSON_OPT,
):
    """Move a session into another checkpoint."""
    hub = _hub()
    _announce(hub)
    ck_ref, file_ref = _split_session_ref(
        src, "mv moves sessions: mh mv <checkpoint>/<session> <checkpoint>"
    )
    res = curate.move_session(hub, ck_ref, file_ref, to)
    if json_:
        _emit_json(res)
    else:
        print(f"moved {res['file']}: {res['from']} -> {res['to']}")


@app.command()
@guard
def rename(
    ref: str = typer.Argument(..., help="Checkpoint to rename (slug, prefix, or index)."),
    name: str = typer.Argument(..., help="New name."),
    json_: bool = JSON_OPT,
):
    """Rename a checkpoint (its creation stamp, and so the walk order, stays)."""
    hub = _hub()
    _announce(hub)
    res = curate.rename_checkpoint(hub, ref, name)
    if json_:
        _emit_json(res)
    elif res.get("unchanged"):
        print(f"'{res['slug']}' already has that name — nothing to do")
    else:
        print(f"renamed {res['was']} -> {res['slug']}")


@app.command()
@guard
def edit(
    ref: str = typer.Argument(..., metavar="CKPT/SESSION", help="Session to edit (prefix ok)."),
    exchange: int = typer.Option(..., "--exchange", "-x", help="Exchange to rewrite (1-based)."),
    user: str | None = typer.Option(None, "--user", help="New user side."),
    agent: str | None = typer.Option(None, "--agent", help="New agent side."),
    user_file: Path | None = typer.Option(
        None, "--user-file", help="Read the new user side from a file."
    ),
    agent_file: Path | None = typer.Option(
        None, "--agent-file", help="Read the new agent side from a file."
    ),
    json_: bool = JSON_OPT,
):
    """Rewrite one side (or both) of an exchange in a saved session."""
    hub = _hub()
    _announce(hub)
    ck_ref, file_ref = _split_session_ref(
        ref, "edit needs a session: mh edit <checkpoint>/<session> -x N --agent '...'"
    )
    if user is not None and user_file:
        raise MhError("give --user or --user-file, not both")
    if agent is not None and agent_file:
        raise MhError("give --agent or --agent-file, not both")
    for opt, path in (("--user-file", user_file), ("--agent-file", agent_file)):
        if path and not path.is_file():
            raise MhError(f"{opt}: file not found: {path}")
    if user_file:
        user = user_file.read_text(encoding="utf-8")
    if agent_file:
        agent = agent_file.read_text(encoding="utf-8")
    if user is None and agent is None:
        raise MhError("nothing to change: pass --user/--agent (or the --*-file variants)")
    res = curate.edit_exchange(hub, ck_ref, file_ref, exchange, user, agent)
    if json_:
        _emit_json(res)
    elif res.get("unchanged"):
        print("no change — the exchange already reads exactly like that")
    else:
        print(f"rewrote exchange {exchange} of {res['file']}")
        _undo_hint(hub)


# --- navigation --------------------------------------------------------------


def _set_current(hub: Path, target: ck.Checkpoint) -> None:
    hubmod.write_current(hub, target.slug)
    cps = ck.list_checkpoints(hub)
    idx = next(i for i, c in enumerate(cps) if c.slug == target.slug)
    print(f"now at '{target.slug}' ({len(target.sessions)} sessions) — {idx + 1} of {len(cps)}")


def _walk(delta: int) -> None:
    hub = _hub()
    _announce(hub)
    cps = ck.list_checkpoints(hub)
    if not cps:
        raise MhError("no checkpoints yet (run 'mh checkpoint <name>')")
    current = hubmod.read_current(hub)
    if not current:
        raise MhError("no current checkpoint (run 'mh goto <ckpt>')")
    idx = next((i for i, c in enumerate(cps) if c.slug == current), None)
    if idx is None:
        raise MhError(f"current checkpoint '{current}' no longer exists (run 'mh goto <ckpt>')")
    target_idx = idx + delta
    if target_idx < 0:
        raise MhError("already at the oldest checkpoint")
    if target_idx >= len(cps):
        raise MhError("already at the newest checkpoint")
    _set_current(hub, cps[target_idx])


@app.command()
@guard
def back(n: int = typer.Argument(1, help="How many checkpoints to walk back.")):
    """Walk the current pointer backward in time."""
    _walk(-n)


@app.command()
@guard
def forward(n: int = typer.Argument(1, help="How many checkpoints to walk forward.")):
    """Walk the current pointer forward in time."""
    _walk(n)


@app.command()
@guard
def goto(ref: str = typer.Argument(..., help="Checkpoint slug, prefix, or index.")):
    """Jump the current pointer to a checkpoint."""
    hub = _hub()
    _announce(hub)
    _set_current(hub, ck.resolve(hub, ref))


# --- reading -----------------------------------------------------------------


@app.command()
@guard
def load(
    refs: list[str] | None = typer.Argument(None, help="Checkpoints to load (default: current)."),
    no_links: bool = typer.Option(False, "--no-links", help="Do not follow links."),
    budget: int = typer.Option(
        loadmod.DEFAULT_BUDGET,
        "--budget",
        help="Token budget (est. ~4 ASCII chars or 1 CJK char per token).",
    ),
    all_: bool = typer.Option(False, "--all", help="No budget: load everything."),
    json_: bool = JSON_OPT,
):
    """Emit the warm-start context pack: selected checkpoints (+ linked), merged by time."""
    hub = _hub()
    result = loadmod.build(
        hub,
        list(refs) if refs else None,
        follow_links=not no_links,
        budget=None if all_ else budget,
    )
    if result.over_budget:
        print(
            f"mh: newest session alone exceeds the budget "
            f"(~{result.used} > {result.budget} tokens); included anyway",
            file=sys.stderr,
        )
    if json_:
        _emit_json(
            {
                "loaded": result.loaded,
                "linked_expansion": result.expanded,
                "sessions": result.included,
                "omitted": result.omitted,
                "budget": result.budget,
                "used_tokens": result.used,
                "hub_commit": result.sha,
            }
        )
    else:
        sys.stdout.write(result.text)


@app.command()
@guard
def trace(
    ref: str = typer.Argument(..., metavar="CKPT/SESSION", help="Saved session (prefix ok)."),
    json_: bool = JSON_OPT,
):
    """Find the original transcript a saved session was purified from.

    The link is the session id recorded in the saved file, resolved against the
    transcripts on this machine now — nothing machine-specific is stored in the
    hub. Prints the transcript's path when it is still here."""
    hub = _hub()
    ck_ref, file_ref = _split_session_ref(
        ref, "trace needs a session: mh trace <checkpoint>/<session>"
    )
    c, session = curate.resolve_session(hub, ck_ref, file_ref)
    parsed = curate.parse(session.read_text(encoding="utf-8", errors="replace"))
    sid = parsed.session_id if parsed else None
    original = livemod.find(hub, sid) if sid else None
    if json_:
        _emit_json(
            {
                "checkpoint": c.slug,
                "file": session.name,
                "session_id": sid,
                "source": parsed.source if parsed else None,
                "path": str(original.path) if original else None,
                "agent": original.agent if original else None,
                "on_this_machine": original is not None,
            }
        )
        return
    if not sid:
        print(f"{c.slug}/{session.name} records no session id (an old save) — cannot trace")
        return
    print(f"{c.slug}/{session.name}  ←  session {sid}")
    if original is not None:
        print(f"  {original.agent}: {original.path}")
    else:
        src = f" ({parsed.source})" if parsed and parsed.source else ""
        print(f"  original transcript{src} is not on this machine")


def _newest_stamp(c: ck.Checkpoint) -> str | None:
    """The latest session stamp in a checkpoint, in filename form."""
    stamps = [p.name[:15] for p in c.sessions if ck.STAMP_RE.match(p.name[:15])]
    return max(stamps) if stamps else None


def _stamp_display(stamp: str) -> str:
    return f"{stamp[:10]} {stamp[11:13]}:{stamp[13:]}"


@app.command("list")
@guard
def list_(json_: bool = JSON_OPT):
    """List checkpoints in time order."""
    hub = _hub()
    cps = ck.list_checkpoints(hub)
    links = ck.read_links(hub)
    current = hubmod.read_current(hub)
    placed = ck.read_stages(hub)
    if json_:
        _emit_json(
            [
                {
                    "index": i + 1,
                    "checkpoint": c.slug,
                    "stage": ck.stage_of(hub, c.slug, placed),
                    "created": c.created,
                    "sessions": len(c.sessions),
                    "last_save": _newest_stamp(c),
                    "links": ck.partners_of(c.slug, links),
                    "current": c.slug == current,
                }
                for i, c in enumerate(cps)
            ]
        )
        return
    if not cps:
        print("no checkpoints yet (run 'mh checkpoint <name>')")
        return
    width = max(len(c.slug) for c in cps)
    print(
        f"    #  {'created'.ljust(19)}  {'name'.ljust(width)}  sessions  "
        f"{'last save'.ljust(16)}  links"
    )
    for i, c in enumerate(cps):
        marker = "*" if c.slug == current else " "
        created = f"{c.created[:10]} {c.created[11:13]}:{c.created[13:15]}:{c.created[15:17]}"
        newest = _newest_stamp(c)
        last = _stamp_display(newest) if newest else "—"
        partners = ", ".join(ck.partners_of(c.slug, links))
        column = ck.stage_of(hub, c.slug, placed)
        at = f"  (at {column})" if column != c.slug else ""
        print(
            f"  {marker} {i + 1}  {created}  {c.slug.ljust(width)}  "
            f"{str(len(c.sessions)).rjust(8)}  {last.ljust(16)}  {partners}{at}"
        )


@app.command()
@guard
def show(
    ref: str = typer.Argument(..., help="Checkpoint, or checkpoint/session-file (prefix ok)."),
    json_: bool = JSON_OPT,
):
    """Print a checkpoint's sessions (or one session file) verbatim."""
    hub = _hub()
    ck_ref, _, file_ref = ref.partition("/")
    c = ck.resolve(hub, ck_ref)
    if file_ref:
        c, session = curate.resolve_session(hub, ck_ref, file_ref)
        body = session.read_text(encoding="utf-8", errors="replace")
        if json_:
            _emit_json({"checkpoint": c.slug, "file": session.name, "body": body})
        else:
            sys.stdout.write(body)
        return
    if json_:
        _emit_json(
            {
                "checkpoint": c.slug,
                "sessions": [
                    {
                        "file": p.name,
                        "body": p.read_text(encoding="utf-8", errors="replace"),
                    }
                    for p in c.sessions
                ],
            }
        )
        return
    if not c.sessions:
        print(f"(checkpoint '{c.slug}' has no sessions yet)")
        return
    parts = []
    for p in c.sessions:
        content = p.read_text(encoding="utf-8", errors="replace").rstrip()
        parts.append(f"<!-- mh session: {c.slug}/{p.name} -->\n\n{content}\n")
    sys.stdout.write("\n".join(parts))


@app.command()
@guard
def status(json_: bool = JSON_OPT):
    """Show the hub's status: current checkpoint, counts, staleness, remote."""
    hub = _hub()
    cps = ck.list_checkpoints(hub)
    links = ck.read_links(hub)
    current = hubmod.read_current(hub)
    total_sessions = sum(len(c.sessions) for c in cps)

    stamps = [s for c in cps if (s := _newest_stamp(c))]
    newest = max(stamps) if stamps else None
    days = None
    if newest:
        days = (datetime.now() - datetime.strptime(newest, ck.STAMP_FMT)).days

    try:
        git.run(hub, "remote", "get-url", "origin")
        origin = "configured"
    except git.GitError:
        origin = None

    cur_ck = next((c for c in cps if c.slug == current), None)
    closure_slugs = sorted(ck.closure({cur_ck.slug}, links)) if cur_ck else []
    from . import server

    ui_rec = server.running(hub)
    prog = tmpl.progress(hub)

    if json_:
        _emit_json(
            {
                "hub": str(hub),
                "current": current if cur_ck else None,
                "position": (cps.index(cur_ck) + 1) if cur_ck else None,
                "checkpoints": len(cps),
                "sessions": total_sessions,
                "links": len(links),
                "loads_with": closure_slugs,
                "template": prog and {k: prog[k] for k in ("name", "done", "total", "next")},
                "last_save": newest,
                "days_since_save": days,
                "stale": bool(days is not None and days > 7),
                "origin": origin,
                "ui": ui_rec["url"] if ui_rec else None,
            }
        )
        return

    print(f"hub: {hub}")
    if cur_ck:
        pos = cps.index(cur_ck) + 1
        print(f"current: {cur_ck.slug} ({pos} of {len(cps)}) — {len(cur_ck.sessions)} sessions")
        others = [s for s in closure_slugs if s != cur_ck.slug]
        if others:
            n_sessions = sum(len(c.sessions) for c in cps if c.slug in closure_slugs)
            print(
                f"linked: + {', '.join(others)} -> loads "
                f"{len(closure_slugs)} checkpoints, {n_sessions} sessions"
            )
    else:
        print("current: none (run 'mh checkpoint <name>' or 'mh goto <ckpt>')")
    print(f"checkpoints: {len(cps)} · sessions: {total_sessions} · links: {len(links)}")
    if prog:
        ahead = f"next: {prog['next']}" if prog["next"] else "all stages created"
        print(f"template: {prog['name']} — {prog['done']} of {prog['total']} stages · {ahead}")
    if ui_rec:
        print(f"ui: {ui_rec['url']} (pid {ui_rec['pid']}, background — mh ui --stop ends it)")
    if newest:
        age = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
        stale = " — stale (>7 days)" if days is not None and days > 7 else ""
        print(f"last save: {_stamp_display(newest)} ({age}){stale}")
    else:
        print("last save: never")
    if origin is None:
        print(f"origin: not configured (git -C {hub} remote add origin <url>)")
    else:
        print("origin: configured")


@app.command()
@guard
def search(query: str = typer.Argument(...), json_: bool = JSON_OPT):
    """Search all sessions in all checkpoints (case-insensitive substring)."""
    hub = _hub()
    needle = query.lower()
    hits = []
    for c in ck.list_checkpoints(hub):
        for p in c.sessions:
            for lineno, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if needle in line.lower():
                    hits.append(
                        {
                            "checkpoint": c.slug,
                            "file": p.name,
                            "line": lineno,
                            "text": line.strip(),
                        }
                    )
    if json_:
        _emit_json(hits)
        return
    if not hits:
        print(f"no matches for '{query}'")
        return
    shown = None
    for h in hits:
        sid = f"{h['checkpoint']}/{h['file']}"
        if sid != shown:
            print(sid)
            shown = sid
        text = h["text"] if len(h["text"]) <= 200 else h["text"][:200] + "…"
        print(f"  {h['line']}: {text}")
    n_files = len({(h["checkpoint"], h["file"]) for h in hits})
    print(
        f"\n{len(hits)} hit{'' if len(hits) == 1 else 's'} in {n_files} "
        f"session{'' if n_files == 1 else 's'} — read one with "
        f"`mh show <checkpoint>/<file>`"
    )


@app.command()
@guard
def log(n: int = typer.Option(20, "-n", help="Number of journal entries.")):
    """Show the hub's git journal (how the context evolved)."""
    hub = _hub()
    code = git.passthrough(hub, "log", "--oneline", "-n", str(n))
    if code != 0:
        raise typer.Exit(code)


# --- infrastructure ----------------------------------------------------------


@app.command()
@guard
def sync():
    """Pull --rebase then push the hub to its origin remote."""
    hub = _hub()
    _announce(hub)
    try:
        git.run(hub, "remote", "get-url", "origin")
    except git.GitError:
        raise MhError(f"no remote configured. run: git -C {hub} remote add origin <url>") from None
    if git.is_dirty(hub):
        raise MhError(
            f"hub has uncommitted manual edits. commit them first: "
            f"git -C {hub} add -A && git -C {hub} commit -m 'manual edits'"
        )
    branch = git.run(hub, "branch", "--show-current").strip() or "main"
    upstream = git.run(hub, "ls-remote", "--heads", "origin", branch).strip()
    if upstream and git.passthrough(hub, "pull", "--rebase", "origin", branch) != 0:
        git.run(hub, "rebase", "--abort", check=False)
        raise MhError(
            f"sync hit a conflict; hub restored to your local state. "
            f"resolve manually: git -C {hub} pull --rebase origin {branch}"
        )
    if git.passthrough(hub, "push", "-u", "origin", branch) != 0:
        raise MhError("push failed (see git output above)")
    print("sync complete")


@app.command()
@guard
def hubs(
    prune: bool = typer.Option(False, "--prune", help="Drop missing hubs."),
    json_: bool = JSON_OPT,
):
    """List all known hubs (from the registry)."""
    paths = hubmod.read_registry()
    rows = [(p, (Path(p) / ".git").exists()) for p in paths]
    if prune:
        keep = [p for p, ok in rows if ok]
        hubmod.write_registry(keep)
        rows = [(p, True) for p in keep]
    if json_:
        _emit_json([{"path": p, "exists": ok} for p, ok in rows])
        return
    if not rows:
        print("no hubs registered")
        return
    for p, ok in rows:
        print(p + ("" if ok else "  (missing)"))


def _budget_value(budget: str) -> int | None:
    if budget.strip().lower() == "none":
        return None
    try:
        value = int(budget)
    except ValueError:
        raise MhError(
            f"--budget must be a non-negative integer or 'none', got '{budget}'"
        ) from None
    if value < 0:
        raise MhError(f"--budget must be a non-negative integer or 'none', got '{budget}'")
    return value


@app.command()
@guard
def ui(
    port: int | None = typer.Option(
        None,
        "--port",
        help="Port to bind. Default: 7777 when free, else any free port; 0 picks a free one.",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    browser: bool = typer.Option(True, "--browser/--no-browser", help="Open a browser."),
    read_only: bool = typer.Option(False, "--read-only", help="Serve the map without any editing."),
    budget: str = typer.Option(
        str(loadmod.DEFAULT_BUDGET),
        "--budget",
        help="Initial token budget in the map ('none' for no budget).",
    ),
    detach: bool = typer.Option(
        False,
        "--detach",
        "-d",
        help="Run the server in the background and print its URL; `mh ui --stop` ends it.",
    ),
    stop: bool = typer.Option(False, "--stop", help="Stop the background server."),
    session: str | None = typer.Option(
        None,
        "--session",
        help="Session the live panel follows (id or key). Default: $CLAUDE_CODE_SESSION_ID.",
    ),
    adopt_socket: int | None = typer.Option(None, "--adopt-socket", hidden=True),
):
    """Open the checkpoint map: visualize the hub and curate it in a browser."""
    import webbrowser

    from . import server

    hub = _hub()
    if adopt_socket is not None:
        # the spawned half of --detach: serve on the socket the parent bound
        server.adopt(hub, adopt_socket, read_only, _budget_value(budget))
        return
    if stop:
        rec = server.stop(hub)
        print(f"stopped mh ui (pid {rec['pid']})" if rec else "no background mh ui is running")
        return
    # From inside an agent session the panel follows the session that asked,
    # not merely the newest transcript of the project.
    sid = session or os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    rec = server.running(hub)
    if rec:
        url = server.page_url(rec["url"], sid)
        print(f"mh ui: {url}")
        print(f"already running in the background (pid {rec['pid']}) — mh ui --stop ends it")
        if browser:
            webbrowser.open(url)
        return
    budget_value = _budget_value(budget)
    if host not in server.ALLOWED_HOSTS:
        # The Host check rejects anything that is not a loopback name, so a
        # remote browser gets 403s even when the bind is wide open — the
        # working remote path is a tunnel that arrives as 127.0.0.1.
        p = str(port) if port else "PORT"
        print(
            f"mh: binding {host} — remote browsers will fail the Host check (403). "
            f"To use the map from another machine: ssh -L {p}:127.0.0.1:{p} <this-host>",
            file=sys.stderr,
        )
    server.serve(
        hub,
        host=host,
        port=port,
        open_browser=browser,
        read_only=read_only,
        budget=budget_value,
        detach=detach,
        sid=sid,
    )


# --- hooks -------------------------------------------------------------------
# The skill relies on the agent remembering to run mh; hooks remove the
# remembering. SessionStart stdout lands in the session's context, so `mh hook
# load` IS the warm start; SessionEnd and PreCompact fire `mh hook save`, the
# latter snapshotting dialog right before compaction would destroy it.


def _hook_hub(payload: dict) -> Path | None:
    """The hub for a hook invocation, or None when this project has none —
    hooks may be installed user-wide, so absence is normal, never an error."""
    cwd = payload.get("cwd")
    start = None
    if isinstance(cwd, str) and cwd:
        p = Path(cwd)
        if p.is_dir():
            start = p
    try:
        return hubmod.discover(start)
    except MhError:
        return None


@hook_app.command("save")
@guard
def hook_save():
    """Claude Code SessionEnd/PreCompact handler: save this session automatically.

    Reads the hook JSON from stdin. Quiet no-ops (no hub, no checkpoint,
    nothing to save) exit 0 so the hook can sit in user-wide settings without
    ever disturbing a session. It respects earlier explicit saves: a session
    already stored --compact is left alone, and one routed --to another
    checkpoint is updated there, not duplicated into the current one.
    """
    payload = hooksmod.read_payload()
    hub = _hook_hub(payload)
    if hub is None:
        return
    try:
        transcript = payload.get("transcript_path")
        transcript = (
            Path(transcript)
            if isinstance(transcript, str) and transcript and Path(transcript).is_file()
            else None
        )
        sid_raw = payload.get("session_id")
        sid_hint = sid_raw if isinstance(sid_raw, str) and sid_raw else None
        src, sid, key, turns, last_ts, models, applied = _resolve_session(
            hub, None if transcript else sid_hint, transcript
        )
        turns, models = purify.drop_trailing_unanswered(turns, models)
        if not turns:
            print(f"mh hook save: no dialog in {src.name} — skipped", file=sys.stderr)
            return
        body = purify.render(turns, str(src), sid, models)
        stamp = purify.stamp_for(last_ts, src)
        # No target: the session is updated where it already lives (a mid-
        # session `mh save --to` routed it there on purpose), else stored in
        # the current checkpoint. A compacted save is kept, and says so.
        stored = savemod.store(hub, key, body, stamp, None, replace_compacted=False, note="hook")
        note = f" ({applied} live edits applied)" if applied else ""
        print(f"mh: saved {stored.file} -> {stored.checkpoint.slug}{note}")
    except MhError as e:
        print(f"mh hook save: {e.message} — skipped", file=sys.stderr)
    except git.GitError as e:
        if e.stderr:
            sys.stderr.write(e.stderr)
        die(git.explain(e))


@hook_app.command("load")
@guard
def hook_load(
    budget: int = typer.Option(
        loadmod.DEFAULT_BUDGET, "--budget", help="Token budget for the injected pack."
    ),
    all_: bool = typer.Option(False, "--all", help="No budget: inject everything."),
):
    """Claude Code SessionStart handler: emit the warm-start pack into context.

    Reads the hook JSON from stdin. Runs only for fresh sessions (startup /
    clear) — on resume the context is still there, and after compaction it is
    summarized; re-injecting would duplicate. No hub, or nothing to load,
    exits 0 quietly.
    """
    payload = hooksmod.read_payload()
    hub = _hook_hub(payload)
    if hub is None:
        return
    # Which tmux pane this session lives in, so `mh ui` can type into it. Done
    # before the resume check: a resumed session has its context already, but
    # it still moved to a new pane.
    relaymod.record_from_hook(hub, payload)
    if payload.get("source") in ("resume", "compact"):
        return
    try:
        result = loadmod.build(hub, None, follow_links=True, budget=None if all_ else budget)
    except MhError as e:
        print(f"mh hook load: {e.message} — skipped", file=sys.stderr)
        return
    if result.over_budget:
        print(
            f"mh: newest session alone exceeds the budget "
            f"(~{result.used} > {result.budget} tokens); included anyway",
            file=sys.stderr,
        )
    sys.stdout.write(result.text)


@hook_app.command("install")
@guard
def hook_install(
    user: bool = typer.Option(
        False,
        "--user",
        help="Install into ~/.claude/settings.json for every project "
        "(the hooks quietly no-op where there is no hub).",
    ),
    remove: bool = typer.Option(
        False, "--remove", help="Uninstall mh's hooks from the chosen settings file."
    ),
    budget: int | None = typer.Option(
        None,
        "--budget",
        help=f"Token budget for the pack injected at session start "
        f"(default {loadmod.DEFAULT_BUDGET}).",
    ),
):
    """Wire mh into Claude Code hooks: load at SessionStart, save at SessionEnd and PreCompact."""
    if user:
        path = hooksmod.settings_path(None)
    else:
        path = hooksmod.settings_path(hubmod.project_root_of(_hub()))
    if remove:
        events = hooksmod.remove(path)
        if events:
            print(f"removed mh hooks ({', '.join(events)}) from {path}")
        else:
            print(f"no mh hooks in {path} — nothing to do")
        return
    events = hooksmod.install(path, budget)
    if events:
        print(f"installed mh hooks ({', '.join(events)}) -> {path}")
        if budget is not None:
            print(f"session start injects up to ~{budget} tokens of memory")
        print(
            "active from the next Claude Code session: memory injects itself at "
            "start, and saves run at session end and before compaction"
        )
        print("undo any time: mh hook install --remove" + (" --user" if user else ""))
    else:
        print(f"mh hooks already present in {path} — nothing to do")


@skill_app.command("install")
@guard
def skill_install():
    """Install the mh skills for Claude Code, and for pi when present."""
    from importlib.resources import files

    # `mh` is the workflow; `mh-ui` is one paragraph that only starts the map,
    # so a session that wants the map does not pay for the whole workflow.
    skills = {
        "mh": files("memoryhub").joinpath("skill/SKILL.md").read_text(encoding="utf-8"),
        "mh-ui": files("memoryhub").joinpath("skill/ui/SKILL.md").read_text(encoding="utf-8"),
    }
    targets = [
        ("claude", Path.home() / ".claude" / "skills", (Path.home() / ".claude").is_dir()),
        ("pi", Path.home() / ".pi" / "agent" / "skills", (Path.home() / ".pi" / "agent").is_dir()),
    ]
    installed = 0
    for name, root, present in targets:
        if not present:
            print(f"{name}: not detected — skipped")
            continue
        for skill, content in skills.items():
            dest = root / skill / "SKILL.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            print(f"installed skill ({name}) -> {dest}")
        installed += 1
    if not installed:
        print("no agent detected (no ~/.claude or ~/.pi/agent) — start the agent once, then rerun")
