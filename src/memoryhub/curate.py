"""Content-level curation: parse a saved session back into exchanges so single
turns can be dropped or rewritten, plus session and checkpoint surgery.

Nothing else in mh parses session markdown — load, show and search all read
files verbatim — so this module is the only code coupled to the rendered shape.
It stays safe by refusing to touch any file it cannot reproduce: parse then
re-render must equal the original byte-for-byte, or the session is read-only.
That guard is what makes editing safe in the presence of dialog that quotes
mh's own output (a session *about* MemoryHub certainly will).

Three document shapes exist: the current User/Agent dialog (rendered by
purify.render), the legacy Q&A shape kept only so old files round-trip, and a
compacted summary. Each is verified by re-rendering, never by assertion.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import checkpoint as ck
from . import git, purify
from .hub import MhError, clear_current, read_current, write_current

PREAMBLE_RE = re.compile(
    r"_Pure dialog extracted from `(?P<src>[^`]*)`"
    r"(?: \(session `(?P<sid>[^`]*)`\))?\. "
    r"(?:\*\*Q\*\* = user, \*\*A\*\* = assistant\. )?"
    r"\d+ exchanges?\. "
)
HEADING_RE = re.compile(r"^## (User|Agent|Q|A) ?(\d+)(?: — `(?P<model>[^`\n]+)`)?\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
NO_REPLY = "_(no textual reply captured)_"

# A compacted session is a summary, not exchanges — a different document shape,
# written by the agent at save time rather than extracted mechanically.
COMPACT_PREAMBLE_RE = re.compile(
    r"_Compacted summary of `(?P<src>[^`]*)`"
    r"(?: \(session `(?P<sid>[^`]*)`\))?\. "
    r"(?P<n>\d+) exchanges? compacted\. "
)


@dataclass
class ParsedSession:
    source: str
    session_id: str | None
    turns: list[tuple[str, str]]
    legacy: bool
    round_trip: bool
    compacted: bool = False
    summary: str = ""  # the compacted payload; empty for dialog sessions
    exchanges: int = 0  # the count a compacted preamble records
    # One model field per turn, parallel to `turns`; "" where the answer's
    # heading names no model, which is every session saved before mh recorded
    # them. Kept beside the turns, never inside, so the tuple shape the whole
    # codebase passes around is unchanged.
    models: list[str] = field(default_factory=list)

    @property
    def editable(self) -> bool:
        # A summary has no exchanges to operate on; per-turn surgery is
        # meaningless, so it is deliberately read-only rather than unsupported.
        return self.round_trip and not self.compacted


def readonly_reason(parsed: ParsedSession | None) -> str | None:
    """Why this session cannot be edited, or None if it can. One policy, so the
    CLI error and the UI badge can never explain the same file differently."""
    if parsed is None:
        return "not a rendered mh session"
    if parsed.compacted:
        return "compacted session — a summary, not exchanges; nothing to edit per-turn"
    if not parsed.round_trip:
        return "mh cannot reproduce this file byte-for-byte, so it will not rewrite it"
    return None


def render_compacted(summary: str, source: str, session_id: str | None, exchanges: int) -> str:
    """A summary the agent wrote, wrapped in mh's session document shape."""
    src = os.path.basename(source)
    prov = f"`{src}`" + (f" (session `{session_id}`)" if session_id else "")
    return "\n".join(
        [
            "# Session Context — Compacted",
            "",
            f"_Compacted summary of {prov}. "
            f"{exchanges} exchange{'' if exchanges == 1 else 's'} compacted. "
            "Written by the agent at save time, not a mechanical extraction._",
            "",
            summary.strip(),
            "",
        ]
    )


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
        detail = git.stderr_lines(e) or ["unknown error"]
        raise MhError(f"git cannot commit in this hub: {detail[0]}") from None


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


def _headings(lines: list[str]) -> list[tuple[int, str, int, str]]:
    """Every heading-shaped line outside fenced code, as (line, role, index,
    model) — model is "" on user turns and on answers written before mh
    recorded one."""
    out: list[tuple[int, str, int, str]] = []
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
            out.append((i, m.group(1), int(m.group(2)), m.group("model") or ""))
    return out


def _structural(
    heads: list[tuple[int, str, int, str]], legacy: bool
) -> list[tuple[int, str, int, str]]:
    """Filter to headings that are genuine turn boundaries.

    A heading counts only when it is the NEXT one the renderer would have
    written (User 1, Agent 1, User 2, ...). Dialog quoting a heading out of
    sequence is therefore absorbed into the surrounding turn instead of
    splitting it.
    """
    roles = ("Q", "A") if legacy else ("User", "Agent")
    out = []
    for line, role, idx, model in heads:
        # the k-th genuine heading is always roles[k % 2], numbered k // 2 + 1
        if (role, idx) == (roles[len(out) % 2], len(out) // 2 + 1):
            out.append((line, role, idx, model))
    return out


def _parse_compacted(text: str) -> ParsedSession | None:
    """A compacted session, but only if re-rendering reproduces the file.

    Verified, never asserted: a *dialog* session that merely quotes a compacted
    preamble matches the regex too, and claiming it is a summary would hide its
    real exchanges behind a read-only badge. Failing the check here lets it fall
    through to the dialog parser, which is what it actually is.
    """
    m = COMPACT_PREAMBLE_RE.search(text)
    if not m:
        return None
    body = text[text.index("\n", m.end()) :].strip() if "\n" in text[m.end() :] else ""
    parsed = ParsedSession(
        source=m.group("src"),
        session_id=m.group("sid"),
        turns=[],
        legacy=False,
        round_trip=False,
        compacted=True,
        summary=body,
        exchanges=int(m.group("n")),
    )
    parsed.round_trip = _render_as_parsed(parsed) == text
    return parsed if parsed.round_trip else None


def parse(text: str) -> ParsedSession | None:
    """Exchanges of a rendered session, or None if this is not one of ours."""
    compacted = _parse_compacted(text)
    if compacted:
        return compacted
    m = PREAMBLE_RE.search(text)
    if not m:
        return None
    lines = text.splitlines()
    heads = _headings(lines)
    legacy = heads[0][1] in ("Q", "A") if heads else False
    structural = _structural(heads, legacy)

    turns: list[tuple[str, str]] = []
    models: list[str] = []
    pending: str | None = None
    for j, (line, role, _idx, model) in enumerate(structural):
        end = structural[j + 1][0] if j + 1 < len(structural) else len(lines)
        body = "\n".join(lines[line + 1 : end]).strip()
        answer = role in ("Agent", "A")
        if answer and j + 1 < len(structural):
            body = body.removesuffix("---").strip()  # the inter-turn separator
        if answer:
            if pending is None:  # malformed; round-trip will reject the file
                continue
            turns.append((pending, "" if body == NO_REPLY else body))
            models.append(model)
            pending = None
        else:
            pending = body

    parsed = ParsedSession(
        source=m.group("src"),
        session_id=m.group("sid"),
        turns=turns,
        legacy=legacy,
        round_trip=False,
        models=models,
    )
    parsed.round_trip = _render_as_parsed(parsed) == text
    return parsed


def _render_as_parsed(parsed: ParsedSession) -> str:
    """Re-render in the shape it was parsed from — this is the round-trip check."""
    if parsed.compacted:
        return render_compacted(parsed.summary, parsed.source, parsed.session_id, parsed.exchanges)
    if parsed.legacy:
        # The Q&A renderer never wrote a model, so a legacy file carrying one
        # fails to reproduce and stays read-only rather than being rewritten
        # into a shape it was not saved in.
        return _render_qa(parsed.turns, parsed.source, parsed.session_id)
    return purify.render(parsed.turns, parsed.source, parsed.session_id, parsed.models)


def render(parsed: ParsedSession) -> str:
    """Canonical form for writing: dialog is migrated to the current format, and
    a compacted session stays compacted rather than being flattened to zero
    exchanges."""
    if parsed.compacted:
        return render_compacted(parsed.summary, parsed.source, parsed.session_id, parsed.exchanges)
    return purify.render(parsed.turns, parsed.source, parsed.session_id, parsed.models)


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


def _load(
    hub: Path, ckpt_ref: str, file_ref: str, index: int | None = None
) -> tuple[ck.Checkpoint, Path, ParsedSession]:
    c, path = resolve_session(hub, ckpt_ref, file_ref)
    parsed = parse(path.read_text(encoding="utf-8", errors="replace"))
    reason = readonly_reason(parsed)
    if reason:
        raise MhError(f"{c.slug}/{path.name} is read-only: {reason}")
    if index is not None and not 1 <= index <= len(parsed.turns):
        raise MhError(f"no exchange {index} in {c.slug}/{path.name}")
    return c, path, parsed


# --- exchange surgery --------------------------------------------------------


def _write(path: Path, parsed: ParsedSession) -> None:
    path.write_text(render(parsed), encoding="utf-8")


def delete_exchange(hub: Path, ckpt_ref: str, file_ref: str, index: int) -> dict:
    """Drop one exchange (1-based). Remaining turns are renumbered by render."""
    ensure_committable(hub)
    c, path, parsed = _load(hub, ckpt_ref, file_ref, index)
    if len(parsed.turns) == 1:
        raise MhError("that is the session's only exchange; delete the session instead")
    parsed.turns.pop(index - 1)
    if index <= len(parsed.models):
        parsed.models.pop(index - 1)  # or every later answer inherits the wrong one
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
    c, path, parsed = _load(hub, ckpt_ref, file_ref, index)
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
    key = ck.session_key(path.name)
    clash = [p for p in target.sessions if key and ck.session_key(p.name) == key]
    if clash:
        raise MhError(f"'{target.slug}' already holds this session as {clash[0].name}")
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
    # an explicit stage placement follows its checkpoint, and leaves with it;
    # a renamed checkpoint keeps its column, since the new name may say otherwise
    stages = ck.read_stages(hub)
    if drop:
        stages.pop(drop, None)
    if rename and rename[0] in stages:
        stages[rename[1]] = stages.pop(rename[0])
    elif rename:
        old, new = rename
        column = ck.stage_of(hub, old, stages)
        if ck.stage_of(hub, new, stages) != column:
            stages[new] = column
    if stages or ck.stages_path(hub).exists():
        ck.write_stages(hub, stages)


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
    from . import templates  # a stage of the template is renamed with it

    if templates.rename_stage(hub, c.slug, name):
        # the stage moved with the checkpoint, so its new name is its column —
        # not the old one _relink pinned it to
        placed = ck.read_stages(hub)
        if placed.pop(new_slug, None) is not None:
            ck.write_stages(hub, placed)
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
            clear_current(hub)
    git.auto_commit(hub, f"curate: delete checkpoint {c.slug} ({sessions} sessions)")
    return {
        "slug": c.slug,
        "sessions": sessions,
        "current": read_current(hub),
    }
