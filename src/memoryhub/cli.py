"""mh — MemoryHub: git-like checkpoints for purified AI session context."""

from __future__ import annotations

import functools
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from . import agents as agents_mod
from . import checkpoint as ck
from . import git
from . import hub as hubmod
from . import load as loadmod
from . import purify
from .hub import MhError

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Git-like checkpoints for purified AI session context.",
)
skill_app = typer.Typer(help="Manage the Claude Code skill.")
app.add_typer(skill_app, name="skill")

JSON_OPT = typer.Option(False, "--json", help="Machine-readable output.")


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
            if "index.lock" in e.stderr:
                print(
                    "mh: another mh/git process is writing to this hub; retry in a moment",
                    file=sys.stderr,
                )
            die(f"git failed ({e.git_args[0]})")

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
    global_: bool = typer.Option(
        False, "--global", help="Create the global hub at ~/.memoryhub."
    ),
    claude: bool = typer.Option(
        False, "--claude", help="Append the Memory section to the project CLAUDE.md."
    ),
):
    """Create a hub for this project (or the global hub)."""
    res = hubmod.init_hub(Path.cwd(), global_=global_)
    _announce(res.hub)
    if res.created:
        print(f"initialized hub at {res.hub}")
    else:
        print(f"hub already initialized at {res.hub}")
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
    name: str = typer.Argument(..., help="Name for the new checkpoint."),
    json_: bool = JSON_OPT,
):
    """Create a new checkpoint (sub-hub) and make it current."""
    hub = _hub()
    _announce(hub)
    c = ck.create(hub, name)
    if json_:
        _emit_json({"checkpoint": c.slug, "created": c.created, "path": str(c.path)})
    else:
        print(f"checkpoint '{c.slug}' created (current)")


@app.command()
@guard
def save(
    to: Optional[str] = typer.Option(
        None, "--to", help="Target checkpoint (default: current)."
    ),
    file: Optional[Path] = typer.Option(
        None, "--file", help="Ingest an already-purified markdown file."
    ),
    session_id: Optional[str] = typer.Option(
        None, "--session-id", help="Purify a specific session id."
    ),
    transcript: Optional[Path] = typer.Option(
        None, "--transcript", help="Purify an explicit .jsonl transcript."
    ),
    json_: bool = JSON_OPT,
):
    """Purify the current session and store it into a checkpoint."""
    hub = _hub()
    _announce(hub)
    if to:
        target = ck.resolve(hub, to)
    else:
        current = hubmod.read_current(hub)
        if not current:
            raise MhError(
                "no current checkpoint (run 'mh checkpoint <name>' or 'mh goto <ckpt>')"
            )
        target = ck.resolve(hub, current)

    if file:
        if not file.is_file():
            raise MhError(f"file not found: {file}")
        body = file.read_text(encoding="utf-8")
        stamp = (
            datetime.fromtimestamp(file.stat().st_mtime)
            .astimezone()
            .strftime(ck.STAMP_FMT)
        )
        key = ck.slugify(file.stem)[:40]
    else:
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
                raise MhError(
                    "no transcripts found for this project (claude, pi, codex)"
                )
            src = max(candidates, key=lambda d: d.path.stat().st_mtime).path
            agent_name = agents_mod.detect_agent(src)
        sid, key = agents_mod.identify(agent_name, src)
        turns, last_ts = agents_mod.extract(
            agents_mod.Discovered(agent_name, src, sid, key)
        )
        turns = purify.drop_trailing_unanswered(turns)
        if not turns:
            raise MhError(f"no dialog found in {src.name}")
        body = purify.render(turns, str(src), sid)
        stamp = purify.stamp_for(last_ts, src)

    fname = ck.save_session(hub, target, body, key, stamp)
    count = len(ck.resolve(hub, target.slug).sessions)
    if json_:
        _emit_json(
            {
                "checkpoint": target.slug,
                "file": fname,
                "path": str(target.path / fname),
                "sessions": count,
            }
        )
    else:
        print(f"saved {fname} -> {target.slug} ({count} sessions)")


@app.command("import")
@guard
def import_(
    to: Optional[str] = typer.Option(
        None, "--to", help="Target checkpoint (default: 'history', created if missing)."
    ),
    agent: Optional[list[str]] = typer.Option(
        None,
        "--agent",
        help="Limit to specific agents (claude, pi, codex). Repeatable.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be imported; write nothing."
    ),
    json_: bool = JSON_OPT,
):
    """Backfill: discover this project's past sessions across all agents and import them into a checkpoint."""
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
        turns, last_ts = agents_mod.extract(d)
        if not turns:
            skipped_empty += 1
            continue
        stamp = purify.stamp_for(last_ts, d.path)
        body = purify.render(turns, str(d.path), d.sid)
        items.append((d, stamp, body, len(turns)))
    items.sort(key=lambda item: item[1])  # chronological

    counts: dict[str, int] = {}
    for d, *_ in items:
        counts[d.agent] = counts.get(d.agent, 0) + 1
    breakdown = ", ".join(f"{a} {n}" for a, n in sorted(counts.items()))
    skip_note = (
        f"skipped: {skipped_existing} already in hub, {skipped_empty} with no dialog"
    )

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


# --- navigation --------------------------------------------------------------


def _set_current(hub: Path, target: ck.Checkpoint) -> None:
    hubmod.write_current(hub, target.slug)
    cps = ck.list_checkpoints(hub)
    idx = next(i for i, c in enumerate(cps) if c.slug == target.slug)
    print(
        f"now at '{target.slug}' ({len(target.sessions)} sessions) — "
        f"{idx + 1} of {len(cps)}"
    )


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
        raise MhError(
            f"current checkpoint '{current}' no longer exists (run 'mh goto <ckpt>')"
        )
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
    refs: Optional[list[str]] = typer.Argument(
        None, help="Checkpoints to load (default: current)."
    ),
    no_links: bool = typer.Option(False, "--no-links", help="Do not follow links."),
    budget: int = typer.Option(6000, "--budget", help="Token budget (~4 chars/token)."),
    all_: bool = typer.Option(False, "--all", help="No budget: load everything."),
    json_: bool = JSON_OPT,
):
    """Emit the warm-start context pack: selected checkpoints (+ linked), sessions merged by time."""
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


@app.command("list")
@guard
def list_(json_: bool = JSON_OPT):
    """List checkpoints in time order."""
    hub = _hub()
    cps = ck.list_checkpoints(hub)
    links = ck.read_links(hub)
    current = hubmod.read_current(hub)
    if json_:
        _emit_json(
            [
                {
                    "index": i + 1,
                    "checkpoint": c.slug,
                    "created": c.created,
                    "sessions": len(c.sessions),
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
    print(f"    #  {'created'.ljust(19)}  {'name'.ljust(width)}  sessions  links")
    for i, c in enumerate(cps):
        marker = "*" if c.slug == current else " "
        created = (
            f"{c.created[:10]} {c.created[11:13]}:{c.created[13:15]}:{c.created[15:17]}"
        )
        partners = ", ".join(ck.partners_of(c.slug, links))
        print(
            f"  {marker} {i + 1}  {created}  {c.slug.ljust(width)}  "
            f"{str(len(c.sessions)).rjust(8)}  {partners}"
        )


@app.command()
@guard
def show(
    ref: str = typer.Argument(
        ..., help="Checkpoint, or checkpoint/session-file (prefix ok)."
    ),
    json_: bool = JSON_OPT,
):
    """Print a checkpoint's sessions (or one session file) verbatim."""
    hub = _hub()
    ck_ref, _, file_ref = ref.partition("/")
    c = ck.resolve(hub, ck_ref)
    if file_ref:
        matches = [p for p in c.sessions if p.name == file_ref]
        if not matches:
            matches = [p for p in c.sessions if p.name.startswith(file_ref)]
        if not matches:
            raise MhError(f"no session '{file_ref}' in '{c.slug}'")
        if len(matches) > 1:
            raise MhError("ambiguous session: " + ", ".join(p.name for p in matches))
        body = matches[0].read_text(encoding="utf-8", errors="replace")
        if json_:
            _emit_json({"checkpoint": c.slug, "file": matches[0].name, "body": body})
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

    newest = None
    for c in cps:
        for p in c.sessions:
            stamp = p.name[:15]
            if ck.STAMP_RE.match(stamp) and (newest is None or stamp > newest):
                newest = stamp
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
                "last_save": newest,
                "days_since_save": days,
                "stale": bool(days is not None and days > 7),
                "origin": origin,
            }
        )
        return

    print(f"hub: {hub}")
    if cur_ck:
        pos = cps.index(cur_ck) + 1
        print(
            f"current: {cur_ck.slug} ({pos} of {len(cps)}) — "
            f"{len(cur_ck.sessions)} sessions"
        )
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
    if newest:
        age = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
        stale = " — stale (>7 days)" if days is not None and days > 7 else ""
        when = f"{newest[:10]} {newest[11:13]}:{newest[13:]}"
        print(f"last save: {when} ({age}){stale}")
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
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if needle in line.lower():
                    hits.append(
                        {"checkpoint": c.slug, "file": p.name, "text": line.strip()}
                    )
    if json_:
        _emit_json(hits)
        return
    for h in hits:
        print(f"{h['checkpoint']}/{h['file']}: {h['text']}")


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
        raise MhError(
            f"no remote configured. run: git -C {hub} remote add origin <url>"
        )
    if git.is_dirty(hub):
        raise MhError(
            f"hub has uncommitted manual edits. commit them first: "
            f"git -C {hub} add -A && git -C {hub} commit -m 'manual edits'"
        )
    branch = git.run(hub, "branch", "--show-current").strip() or "main"
    if git.run(hub, "ls-remote", "--heads", "origin", branch).strip():
        if git.passthrough(hub, "pull", "--rebase", "origin", branch) != 0:
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


@skill_app.command("install")
@guard
def skill_install():
    """Install the mh skill for Claude Code, and for pi when present."""
    from importlib.resources import files

    content = files("memoryhub").joinpath("skill/SKILL.md").read_text(encoding="utf-8")
    targets = [
        ("claude", Path.home() / ".claude" / "skills" / "mh" / "SKILL.md", True),
        (
            "pi",
            Path.home() / ".pi" / "agent" / "skills" / "mh" / "SKILL.md",
            (Path.home() / ".pi" / "agent").is_dir(),
        ),
    ]
    for name, dest, present in targets:
        if not present:
            print(f"{name}: not detected — skipped")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        print(f"installed skill ({name}) -> {dest}")
