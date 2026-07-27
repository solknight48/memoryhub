"""Content-level curation: parse a saved session back into exchanges so single
turns can be dropped or rewritten, plus session and checkpoint surgery.

Nothing else in mh parses session markdown — load, show and search all read
files verbatim — so this module is the only code coupled to the rendered shape.
It stays safe by refusing to touch any file it cannot reproduce: parse then
re-render must equal the original byte-for-byte, or the session is read-only.
That guard is what makes editing safe in the presence of dialog that quotes
mh's own output (a session *about* MemoryHub certainly will).

Re-rendering goes through purify.render, so the format keeps exactly one
producer. Sessions still in the legacy Q&A shape parse and round-trip against a
copy of the old renderer, and are migrated to User/Agent on first edit.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import checkpoint as ck
from . import git, purify
from .hub import MhError, read_current, write_current

PREAMBLE_RE = re.compile(
    r"_Pure dialog extracted from `(?P<src>[^`]*)`"
    r"(?: \(session `(?P<sid>[^`]*)`\))?\. "
    r"(?:\*\*Q\*\* = user, \*\*A\*\* = assistant\. )?"
    r"\d+ exchanges?\. "
)
HEADING_RE = re.compile(r"^## (User|Agent|Q|A) ?(\d+)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
NO_REPLY = "_(no textual reply captured)_"


@dataclass
class ParsedSession:
    source: str
    session_id: str | None
    turns: list[tuple[str, str]]
    legacy: bool
    round_trip: bool

    @property
    def editable(self) -> bool:
        return self.round_trip


def ensure_committable(hub: Path) -> None:
    """Fail before touching the filesystem, not after.

    Every curation writes and then commits. If the commit fails the change is
    already on disk but missing from the journal — the hub's one invariant
    broken, and a later `mh save` would sweep it into an unrelated commit. The
    usual cause is an unset git identity, which is cheap to check up front.
    """
    try:
        git.run(hub, "var", "GIT_AUTHOR_IDENT")
    except git.GitError as e:
        first = ((e.stderr or "").strip().splitlines() or ["unknown error"])[0]
        raise MhError(f"git cannot commit in this hub: {first}") from None


def _render_qa(turns: list[tuple[str, str]], source: str, sid: str | None) -> str:
    """The pre-User/Agent renderer, kept so legacy sessions round-trip."""
    n = len(turns)
    src = os.path.basename(source)
    prov = f"`{src}`" + (f" (session `{sid}`)" if sid else "")
    lines = [
        "# Session Context — Q&A",
        "",
        f"_Pure dialog extracted from {prov}. **Q** = user, **A** = assistant. "
        f"{n} exchange{'' if n == 1 else 's'}. Tool calls, results, and internal "
        "reasoning removed._",
        "",
    ]
    blocks = []
    for i, (user, agent) in enumerate(turns, 1):
        blocks.append(f"## Q{i}\n\n{user}\n")
        blocks.append(f"## A{i}\n\n{agent if agent else NO_REPLY}\n")
        blocks.append("---\n")
    if blocks:
        blocks.pop()
    return "\n".join(lines + blocks).rstrip() + "\n"


def _headings(lines: list[str]) -> list[tuple[int, str, int]]:
    """Every heading-shaped line outside fenced code, as (line, role, index)."""
    out: list[tuple[int, str, int]] = []
    fence: str | None = None
    for i, line in enumerate(lines):
        f = FENCE_RE.match(line)
        if f:
            token = f.group(1)
            if fence is None:
                fence = token
            elif fence == token:
                fence = None
            continue
        if fence is not None:
            continue
        m = HEADING_RE.match(line)
        if m:
            out.append((i, m.group(1), int(m.group(2))))
    return out


def _structural(
    heads: list[tuple[int, str, int]], legacy: bool
) -> list[tuple[int, str, int]]:
    """Filter to headings that are genuine turn boundaries.

    A heading counts only when it is the NEXT one the renderer would have
    written (User 1, Agent 1, User 2, ...). Dialog quoting a heading out of
    sequence is therefore absorbed into the surrounding turn instead of
    splitting it.
    """
    roles = ("Q", "A") if legacy else ("User", "Agent")
    want_role, want_idx = roles[0], 1
    out = []
    for line, role, idx in heads:
        if role != want_role or idx != want_idx:
            continue
        out.append((line, role, idx))
        if want_role == roles[0]:
            want_role = roles[1]
        else:
            want_role, want_idx = roles[0], want_idx + 1
    return out


def parse(text: str) -> ParsedSession | None:
    """Exchanges of a rendered session, or None if this is not one of ours."""
    m = PREAMBLE_RE.search(text)
    if not m:
        return None
    lines = text.splitlines()
    heads = _headings(lines)
    legacy = heads[0][1] in ("Q", "A") if heads else False
    structural = _structural(heads, legacy)

    turns: list[tuple[str, str]] = []
    pending: str | None = None
    for j, (line, role, _idx) in enumerate(structural):
        end = structural[j + 1][0] if j + 1 < len(structural) else len(lines)
        body = "\n".join(lines[line + 1 : end]).strip()
        answer = role in ("Agent", "A")
        if answer and j + 1 < len(structural):
            body = body.removesuffix("---").strip()  # the inter-turn separator
        if answer:
            if pending is None:  # malformed; round-trip will reject the file
                continue
            turns.append((pending, "" if body == NO_REPLY else body))
            pending = None
        else:
            pending = body

    parsed = ParsedSession(
        source=m.group("src"),
        session_id=m.group("sid"),
        turns=turns,
        legacy=legacy,
        round_trip=False,
    )
    parsed.round_trip = render(parsed, migrate=False) == text
    return parsed


def render(parsed: ParsedSession, migrate: bool = True) -> str:
    """Re-render. migrate=True always writes the current User/Agent format."""
    if parsed.legacy and not migrate:
        return _render_qa(parsed.turns, parsed.source, parsed.session_id)
    return purify.render(parsed.turns, parsed.source, parsed.session_id)


# --- locating ----------------------------------------------------------------


def resolve_session(hub: Path, ckpt_ref: str, file_ref: str) -> tuple[ck.Checkpoint, Path]:
    c = ck.resolve(hub, ckpt_ref)
    matches = [p for p in c.sessions if p.name == file_ref]
    if not matches:
        matches = [p for p in c.sessions if p.name.startswith(file_ref)]
    if not matches:
        raise MhError(f"no session '{file_ref}' in '{c.slug}'")
    if len(matches) > 1:
        raise MhError("ambiguous session: " + ", ".join(p.name for p in matches))
    return c, matches[0]


def _load(hub: Path, ckpt_ref: str, file_ref: str) -> tuple[ck.Checkpoint, Path, ParsedSession]:
    c, path = resolve_session(hub, ckpt_ref, file_ref)
    parsed = parse(path.read_text(encoding="utf-8", errors="replace"))
    if parsed is None:
        raise MhError(
            f"{c.slug}/{path.name} is not a rendered mh session — read-only "
            "(edit it with git if you know what you are doing)"
        )
    if not parsed.editable:
        raise MhError(
            f"{c.slug}/{path.name} does not round-trip: mh cannot reproduce it "
            "byte-for-byte, so it refuses to rewrite it. Read-only."
        )
    return c, path, parsed


# --- exchange surgery --------------------------------------------------------


def _write(path: Path, parsed: ParsedSession) -> None:
    path.write_text(render(parsed), encoding="utf-8")


def delete_exchange(hub: Path, ckpt_ref: str, file_ref: str, index: int) -> dict:
    """Drop one exchange (1-based). Remaining turns are renumbered by render."""
    ensure_committable(hub)
    c, path, parsed = _load(hub, ckpt_ref, file_ref)
    if not 1 <= index <= len(parsed.turns):
        raise MhError(f"no exchange {index} in {c.slug}/{path.name}")
    if len(parsed.turns) == 1:
        raise MhError(
            "that is the session's only exchange; delete the session instead"
        )
    parsed.turns.pop(index - 1)
    _write(path, parsed)
    git.auto_commit(hub, f"curate: drop exchange {index} of {path.name} ({c.slug})")
    return {"checkpoint": c.slug, "file": path.name, "exchanges": len(parsed.turns)}


def edit_exchange(
    hub: Path,
    ckpt_ref: str,
    file_ref: str,
    index: int,
    user: str | None = None,
    agent: str | None = None,
) -> dict:
    """Rewrite one side or both of an exchange (1-based)."""
    ensure_committable(hub)
    c, path, parsed = _load(hub, ckpt_ref, file_ref)
    if not 1 <= index <= len(parsed.turns):
        raise MhError(f"no exchange {index} in {c.slug}/{path.name}")
    old_user, old_agent = parsed.turns[index - 1]
    new_user = old_user if user is None else user.strip()
    new_agent = old_agent if agent is None else agent.strip()
    if not new_user:
        raise MhError("the user side of an exchange cannot be empty")
    if (new_user, new_agent) == (old_user, old_agent):
        return {"checkpoint": c.slug, "file": path.name, "unchanged": True}
    parsed.turns[index - 1] = (new_user, new_agent)
    _write(path, parsed)
    git.auto_commit(hub, f"curate: rewrite exchange {index} of {path.name} ({c.slug})")
    return {"checkpoint": c.slug, "file": path.name, "exchanges": len(parsed.turns)}


# --- session surgery ---------------------------------------------------------


def delete_session(hub: Path, ckpt_ref: str, file_ref: str) -> dict:
    ensure_committable(hub)
    c, path = resolve_session(hub, ckpt_ref, file_ref)
    name = path.name
    path.unlink()
    git.auto_commit(hub, f"curate: delete session {name} ({c.slug})")
    return {"checkpoint": c.slug, "file": name}


def move_session(hub: Path, ckpt_ref: str, file_ref: str, to_ref: str) -> dict:
    ensure_committable(hub)
    c, path = resolve_session(hub, ckpt_ref, file_ref)
    target = ck.resolve(hub, to_ref)
    if target.slug == c.slug:
        raise MhError(f"{path.name} is already in '{c.slug}'")
    dest = target.path / path.name
    if dest.exists():
        raise MhError(f"'{target.slug}' already holds {path.name}")
    # One file per session key per checkpoint — a same-session file under a
    # different timestamp would silently duplicate the session.
    key = path.name[16:-3] if len(path.name) > 19 else path.stem
    clash = [p for p in target.sessions if p.name.endswith(f"_{key}.md")]
    if clash:
        raise MhError(
            f"'{target.slug}' already holds this session as {clash[0].name}"
        )
    shutil.move(str(path), str(dest))
    git.auto_commit(hub, f"curate: move {path.name} {c.slug} -> {target.slug}")
    return {"from": c.slug, "to": target.slug, "file": path.name}


# --- checkpoint surgery ------------------------------------------------------


def _relink(hub: Path, rename: tuple[str, str] | None = None, drop: str | None = None):
    links = ck.read_links(hub)
    if drop:
        links = [(a, b) for a, b in links if drop not in (a, b)]
    if rename:
        old, new = rename
        links = [(new if a == old else a, new if b == old else b) for a, b in links]
    ck.write_links(hub, links)


def rename_checkpoint(hub: Path, ref: str, name: str) -> dict:
    ensure_committable(hub)
    c = ck.resolve(hub, ref)
    new_slug = ck.slugify(name)
    if new_slug == c.slug:
        return {"slug": c.slug, "unchanged": True}
    if any(x.slug == new_slug for x in ck.list_checkpoints(hub)):
        raise MhError(f"checkpoint '{new_slug}' already exists")
    # The created stamp is preserved: it defines walk order.
    c.path.rename(c.path.with_name(f"{c.created}_{new_slug}"))
    _relink(hub, rename=(c.slug, new_slug))
    if read_current(hub) == c.slug:
        write_current(hub, new_slug)
    git.auto_commit(hub, f"curate: rename checkpoint {c.slug} -> {new_slug}")
    return {"slug": new_slug, "was": c.slug}


def delete_checkpoint(hub: Path, ref: str) -> dict:
    ensure_committable(hub)
    c = ck.resolve(hub, ref)
    remaining = [x for x in ck.list_checkpoints(hub) if x.slug != c.slug]
    sessions = len(c.sessions)
    shutil.rmtree(c.path)
    _relink(hub, drop=c.slug)
    if read_current(hub) == c.slug:
        if remaining:
            write_current(hub, remaining[-1].slug)
        else:
            (hub / "current").unlink(missing_ok=True)
    git.auto_commit(hub, f"curate: delete checkpoint {c.slug} ({sessions} sessions)")
    return {
        "slug": c.slug,
        "sessions": sessions,
        "current": read_current(hub),
    }
