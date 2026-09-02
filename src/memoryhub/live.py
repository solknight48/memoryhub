"""The session happening right now, and the edits you make to it while it runs.

`mh ui` renders the live session straight from the agent's transcript — the
newest one this project has — re-read whenever the file grows, so the browser
follows the terminal within a couple of seconds.

The transcript belongs to the agent, so mh never writes to it. Curation of a
running session is recorded instead as a *draft* beside the hub
(`<hub>/drafts/<key>.json`, untracked like `current`): one decision per
exchange, keyed by its number in the transcript. Every save of that session —
`mh save`, the SessionEnd/PreCompact hook, the UI's save button — applies the
draft before rendering. That is what makes editing a live session safe: the
decisions live outside both the transcript and the saved file, so a later save
re-applies them instead of erasing them.

Each entry carries the exchange's original user text as an anchor. Only the
in-flight last exchange can still change under an entry (consecutive
unanswered user messages merge into one turn); when it does the anchor stops
matching and the entry is ignored rather than applied to different dialog.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import agents, curate, git, purify
from . import checkpoint as ck
from . import save as savemod
from .hub import MhError, project_root_of

DRAFTS_DIR = "drafts"
EXCLUDE_LINE = "/drafts/"
DISCOVERY_TTL = 5.0  # seconds; the UI polls, codex discovery reads every rollout

_discovery: dict[str, tuple[float, list[agents.Discovered]]] = {}


@dataclass
class LiveSession:
    agent: str
    path: Path
    sid: str
    key: str
    turns: list[tuple[str, str]]
    models: list[str]
    last_ts: str | None
    # Everything the agent emitted for each exchange — thinking, text and tool
    # calls, unfiltered — or None when it was not asked for, or when this
    # agent's block format is not one mh has verified. Purely for reading: a
    # save stores the purified dialog in `turns`, never this.
    parts: list[list[dict]] | None = None
    # Pictures pasted with each exchange's question (descriptors), parallel to
    # `turns`; only Claude Code records them. Display only, never stored.
    images: list[list[dict]] = field(default_factory=list)

    @property
    def pending(self) -> bool:
        """The last exchange has no answer yet — the agent is still replying.
        Shown live, but dropped by every save, exactly as `mh save` does."""
        return bool(self.turns) and not self.turns[-1][1].strip()


# --- finding the live session ------------------------------------------------


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def candidates(root: Path, ttl: float = DISCOVERY_TTL) -> list[agents.Discovered]:
    """This project's transcripts, newest first. Discovery is cached for a few
    seconds (the UI polls, and codex discovery reads the head of every rollout
    on the machine); the ordering is not, so the newest session is always the
    one currently being written."""
    cached = _discovery.get(str(root))
    now = time.monotonic()
    if cached is None or now - cached[0] >= ttl:
        found = agents.discover(root)
        _discovery[str(root)] = (now, found)
    else:
        found = cached[1]
    alive = [d for d in found if d.path.is_file()]
    return sorted(alive, key=lambda d: _mtime(d.path), reverse=True)


def pick(cands: list[agents.Discovered], sid: str | None = None):
    """The session to follow: the one asked for, else the newest."""
    if not sid:
        return cands[0] if cands else None
    for d in cands:
        if sid in (d.sid, d.key):
            return d
    raise MhError(f"no session '{sid}' among this project's transcripts")


def find(hub: Path, sid: str) -> agents.Discovered | None:
    """The original transcript for a saved session's id, if it is still on this
    machine — the purified file records the id, mh resolves it on demand rather
    than storing a path that would rot. None when it has been deleted, or the
    save came from elsewhere."""
    if not sid:
        return None
    for d in candidates(project_root_of(hub)):
        if sid in (d.sid, d.key):
            return d
    return None


def read(hub: Path, sid: str | None = None, full: bool = False) -> LiveSession | None:
    """Purify the live transcript in memory. None when the project has none.
    `full` also collects the unfiltered stream, a second pass nothing but the
    reading panel needs."""
    d = pick(candidates(project_root_of(hub)), sid)
    return None if d is None else from_discovered(d, full)


def from_discovered(d: agents.Discovered, full: bool = False) -> LiveSession:
    images: list[list[dict]] = []
    if d.agent == "claude":
        walk = purify.walk_claude(d.path)
        turns, last_ts, models = walk.result()
        images = walk.attachments
    else:
        turns, last_ts, models = agents.extract(d)
    parts = agents.stream(d) if full else None
    if parts is not None and len(parts) != len(turns):
        # The two walks disagree about where the exchanges are; show the dialog
        # rather than pin one exchange's output onto another.
        parts = None
    return LiveSession(d.agent, d.path, d.sid, d.key, turns, models, last_ts, parts, images)


def image(hub: Path, sid: str | None, index: int, n: int) -> tuple[str, bytes]:
    """A picture pasted into the live session, decoded from its transcript."""
    d = pick(candidates(project_root_of(hub)), sid)
    if d is None:
        raise MhError("no transcript for this project yet (claude, pi, codex)")
    found = purify.claude_image(d.path, index, n) if d.agent == "claude" else None
    if found is None:
        raise MhError(f"no picture {n} on exchange {index}")
    return found


def _sig(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return "0"
    return f"{st.st_mtime_ns}.{st.st_size}"


def fingerprint(hub: Path, key: str, transcript: Path, stored: Path | None) -> str:
    """What the client polls on: the transcript, the draft and the saved copy.
    Unchanged fingerprint == unchanged answer, so the poll costs one stat each
    instead of re-purifying the whole transcript."""
    parts = [transcript.name, _sig(transcript), _sig(draft_path(hub, key))]
    if stored is not None:
        parts.append(_sig(stored))
    return "-".join(parts)


# --- the draft ---------------------------------------------------------------


def drafts_dir(hub: Path) -> Path:
    return hub / DRAFTS_DIR


def draft_path(hub: Path, key: str) -> Path:
    return drafts_dir(hub) / f"{key}.json"


def read_draft(hub: Path, key: str) -> dict:
    """The decisions recorded for this session, `{"<index>": {...}}`. A draft
    mh cannot read is no draft: it must never block a save."""
    path = draft_path(hub, key)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    return (
        {k: v for k, v in entries.items() if isinstance(v, dict)}
        if isinstance(entries, dict)
        else {}
    )


def write_draft(hub: Path, key: str, entries: dict) -> None:
    d = drafts_dir(hub)
    if not d.is_dir():
        d.mkdir(parents=True, exist_ok=True)
        # Pending intent about a session still being written is not hub
        # content: keep it out of the journal, the way `current` is kept out.
        git.exclude(hub, EXCLUDE_LINE)
    path = draft_path(hub, key)
    if entries:
        body = {"key": key, "entries": {k: entries[k] for k in sorted(entries, key=int)}}
        path.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def apply(
    turns: list[tuple[str, str]], models: list[str], entries: dict
) -> tuple[list[tuple[str, str]], list[str], int, int]:
    """Fresh dialog with the live edits folded in: (turns, models, applied,
    stale). An entry whose anchor no longer matches the transcript is counted
    stale and ignored — never applied to dialog it was not written for."""
    out_turns: list[tuple[str, str]] = []
    out_models: list[str] = []
    applied = stale = 0
    for i, (user, agent) in enumerate(turns, 1):
        entry = entries.get(str(i))
        if entry is not None and entry.get("anchor") != user:
            stale += 1
            entry = None
        if entry is not None:
            applied += 1
            if entry.get("drop"):
                continue
            user = entry.get("user", user)
            agent = entry.get("agent", agent)
        out_turns.append((user, agent))
        out_models.append(models[i - 1] if i <= len(models) else "")
    return out_turns, out_models, applied, stale


def curated(live: LiveSession, entries: dict) -> tuple[list[tuple[str, str]], list[str], int, int]:
    """What a save of this session would store right now: the draft applied,
    then the trailing unanswered question dropped as `mh save` always does."""
    turns, models, applied, stale = apply(live.turns, live.models, entries)
    turns, models = purify.drop_trailing_unanswered(turns, models)
    return turns, models, applied, stale


# --- storing it --------------------------------------------------------------


def _stored(hub: Path, key: str):
    """(checkpoint, path) of this session's saved copy anywhere in the hub."""
    return ck.find_by_key(hub, key)


def _body(live: LiveSession, entries: dict) -> tuple[str, int, int]:
    turns, models, applied, _ = curated(live, entries)
    if not turns:
        raise MhError(
            "every exchange is dropped — nothing left to save"
            if applied
            else f"no dialog to save yet in {live.path.name}"
        )
    return purify.render(turns, str(live.path), live.sid, models), len(turns), applied


def _write(hub: Path, target: ck.Checkpoint, live: LiveSession, body: str, message: str) -> str:
    stamp = purify.stamp_for(live.last_ts, live.path)
    fname = ck.write_session(target, body, live.key, stamp)
    git.auto_commit(hub, message)
    return fname


def save(hub: Path, ckpt_ref: str | None = None, sid: str | None = None) -> dict:
    """Store the live session now, draft applied. Where it lands follows the
    one policy every save path shares (save.store): where it already lives,
    else the checkpoint asked for, else the current one — and a compacted
    save is kept rather than overwritten by the panel."""
    live = read(hub, sid)
    if live is None:
        raise MhError("no transcript for this project yet (claude, pi, codex)")
    entries = read_draft(hub, live.key)
    body, count, applied = _body(live, entries)
    stored = savemod.store(
        hub,
        live.key,
        body,
        purify.stamp_for(live.last_ts, live.path),
        ckpt_ref,
        replace_compacted=False,
        note="live",
    )
    return {
        "checkpoint": stored.checkpoint.slug,
        "file": stored.file,
        "exchanges": count,
        "applied": applied,
        "moved_from": stored.moved_from,
    }


def _resync(hub: Path, live: LiveSession, entries: dict, note: str) -> dict | None:
    """Keep an already-saved copy in step with a draft decision, so the hub
    never shows dialog the user just curated away. Nothing saved yet, nothing
    to do — the draft is applied by the first save."""
    where, path = _stored(hub, live.key)
    if path is None:
        return None
    parsed = curate.parse(path.read_text(encoding="utf-8", errors="replace"))
    if parsed and parsed.compacted:
        return {"checkpoint": where.slug, "file": path.name, "skipped": "compacted"}
    body, count, _ = _body(live, entries)
    if path.read_text(encoding="utf-8", errors="replace") == body:
        return {"checkpoint": where.slug, "file": path.name, "exchanges": count}
    fname = _write(hub, where, live, body, f"curate: {note} in {path.name} ({where.slug})")
    return {"checkpoint": where.slug, "file": fname, "exchanges": count}


# --- editing a running session -----------------------------------------------


def _decide(
    hub: Path,
    index: int,
    sid: str | None,
    note: str,
    *,
    drop: bool = False,
    revert: bool = False,
    user: str | None = None,
    agent: str | None = None,
) -> dict:
    live = read(hub, sid)
    if live is None:
        raise MhError("no transcript for this project yet (claude, pi, codex)")
    if not 1 <= index <= len(live.turns):
        raise MhError(f"no exchange {index} in the live session")
    entries = read_draft(hub, live.key)
    anchor = live.turns[index - 1][0]
    slot = str(index)
    if revert:
        entries.pop(slot, None)
    else:
        entry = entries.get(slot) or {}
        if entry.get("anchor") != anchor:
            entry = {}  # a stale entry describes different dialog; start over
        entry["anchor"] = anchor
        if drop:
            entry["drop"] = True
        if user is not None:
            entry.pop("drop", None)
            entry["user"] = user.strip()
        if agent is not None:
            entry.pop("drop", None)
            entry["agent"] = agent.strip()
        entries[slot] = entry
    turns, _, _, _ = curated(live, entries)
    if not turns:
        raise MhError("that is the session's only exchange; drop the session instead")
    if not revert and any(not u.strip() for u, _ in turns):
        raise MhError("the user side of an exchange cannot be empty")
    curate.ensure_committable(hub)
    write_draft(hub, live.key, entries)
    return {
        "key": live.key,
        "index": index,
        "edits": len(entries),
        "saved": _resync(hub, live, entries, note),
    }


def drop(hub: Path, index: int, sid: str | None = None) -> dict:
    return _decide(hub, index, sid, f"drop live exchange {index}", drop=True)


def revert(hub: Path, index: int, sid: str | None = None) -> dict:
    return _decide(hub, index, sid, f"restore live exchange {index}", revert=True)


def edit(
    hub: Path,
    index: int,
    user: str | None = None,
    agent: str | None = None,
    sid: str | None = None,
) -> dict:
    if user is None and agent is None:
        raise MhError("nothing to edit: give a user or agent side")
    return _decide(hub, index, sid, f"rewrite live exchange {index}", user=user, agent=agent)


def discard(hub: Path, sid: str | None = None) -> dict:
    """Throw the whole draft away; the session goes back to what the
    transcript says. An already-saved copy is re-rendered to match."""
    live = read(hub, sid)
    if live is None:
        raise MhError("no transcript for this project yet (claude, pi, codex)")
    curate.ensure_committable(hub)
    write_draft(hub, live.key, {})
    return {"key": live.key, "saved": _resync(hub, live, {}, "discard live edits")}
