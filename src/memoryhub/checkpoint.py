"""Checkpoints (sub-hubs of purified sessions) and the links between them."""

from __future__ import annotations

import json
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import git
from .hub import MhError, write_current

# Session files carry minute stamps (from transcript timestamps); checkpoint
# dirs carry second stamps so lexical order == creation order (see create()).
STAMP_FMT = "%Y-%m-%d_%H%M"
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}$")
CKPT_STAMP_FMT = "%Y-%m-%d_%H%M%S"
CKPT_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")


def slugify(name: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:60].strip("-")
    if not slug:
        raise MhError("cannot derive a name slug; use ascii letters/digits")
    return slug


@dataclass
class Checkpoint:
    slug: str
    created: str  # "YYYY-MM-DD_HHMMSS"
    path: Path
    sessions: list[Path]


def checkpoints_dir(hub: Path) -> Path:
    return hub / "checkpoints"


def _parse_dirname(name: str) -> tuple[str, str] | None:
    parts = name.split("_", 2)
    if len(parts) == 3:
        stamp = f"{parts[0]}_{parts[1]}"
        if CKPT_STAMP_RE.match(stamp) and parts[2]:
            return stamp, parts[2]
    return None


def list_checkpoints(hub: Path) -> list[Checkpoint]:
    root = checkpoints_dir(hub)
    result: list[Checkpoint] = []
    if not root.is_dir():
        return result
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        parsed = _parse_dirname(d.name)
        if not parsed:
            continue
        stamp, slug = parsed
        sessions = sorted(p for p in d.glob("*.md") if p.is_file())
        result.append(Checkpoint(slug, stamp, d, sessions))
    return result


def resolve(hub: Path, ref: str) -> Checkpoint:
    cps = list_checkpoints(hub)
    if not cps:
        raise MhError("no checkpoints yet (run 'mh checkpoint <name>')")
    exact = [c for c in cps if c.slug == ref]
    if exact:
        return exact[0]
    prefixed = [c for c in cps if c.slug.startswith(ref)]
    if len(prefixed) == 1:
        return prefixed[0]
    if len(prefixed) > 1:
        raise MhError(
            f"ambiguous checkpoint '{ref}': " + ", ".join(c.slug for c in prefixed)
        )
    if ref.isdigit():
        idx = int(ref)
        if 1 <= idx <= len(cps):
            return cps[idx - 1]
    raise MhError(f"no checkpoint '{ref}' (see 'mh list')")


def create(hub: Path, name: str, set_current: bool = True) -> Checkpoint:
    slug = slugify(name)
    existing = list_checkpoints(hub)
    if any(c.slug == slug for c in existing):
        raise MhError(f"checkpoint '{slug}' already exists")
    # Strictly increasing stamps: same-second creations bump by one second so
    # lexical dir order always equals creation order (the walk order).
    now = datetime.now().astimezone()
    taken = {c.created for c in existing}
    stamp = now.strftime(CKPT_STAMP_FMT)
    while stamp in taken or (existing and stamp <= existing[-1].created):
        now += timedelta(seconds=1)
        stamp = now.strftime(CKPT_STAMP_FMT)
    d = checkpoints_dir(hub) / f"{stamp}_{slug}"
    d.mkdir(parents=True)
    if set_current:
        write_current(hub, slug)
    # Empty dirs are invisible to git; the --allow-empty commit records the
    # creation event in the journal anyway.
    git.auto_commit(hub, f"checkpoint: {slug}", allow_empty=True)
    return Checkpoint(slug, stamp, d, [])


def write_session(ckpt: Checkpoint, body: str, key: str, stamp: str) -> str:
    """Write one purified session into a checkpoint without committing. One file
    per session key — rewriting the same session replaces its earlier file
    (latest wins)."""
    for old in ckpt.path.glob(f"*_{key}.md"):
        old.unlink()
    fname = f"{stamp}_{key}.md"
    (ckpt.path / fname).write_text(body, encoding="utf-8")
    return fname


def save_session(hub: Path, ckpt: Checkpoint, body: str, key: str, stamp: str) -> str:
    fname = write_session(ckpt, body, key, stamp)
    git.auto_commit(hub, f"save: {fname} -> {ckpt.slug}")
    return fname


def existing_keys(hub: Path) -> set[str]:
    """Session identity keys already present anywhere in the hub (for import
    dedup: a session saved once is never imported again)."""
    keys: set[str] = set()
    for c in list_checkpoints(hub):
        for p in c.sessions:
            name = p.name[:-3]  # strip .md
            if len(name) > 16 and STAMP_RE.match(name[:15]) and name[15] == "_":
                keys.add(name[16:])
    return keys


# --- links -------------------------------------------------------------------


def links_path(hub: Path) -> Path:
    return hub / "links.toml"


def read_links(hub: Path) -> list[tuple[str, str]]:
    path = links_path(hub)
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text())
    return [(str(e[0]), str(e[1])) for e in data.get("links", []) if len(e) == 2]


def write_links(hub: Path, links: list[tuple[str, str]]) -> None:
    uniq = sorted({(min(a, b), max(a, b)) for a, b in links})
    if uniq:
        rows = ",\n  ".join(json.dumps(list(e)) for e in uniq)
        links_path(hub).write_text(f"links = [\n  {rows},\n]\n")
    else:
        links_path(hub).write_text("links = []\n")


def add_link(hub: Path, ref_a: str, ref_b: str) -> tuple[str, str] | None:
    """Returns the added edge, or None if it was a no-op (self/duplicate)."""
    a = resolve(hub, ref_a).slug
    b = resolve(hub, ref_b).slug
    if a == b:
        return None
    edge = (min(a, b), max(a, b))
    links = read_links(hub)
    if edge in {(min(x, y), max(x, y)) for x, y in links}:
        return None
    write_links(hub, links + [edge])
    git.auto_commit(hub, f"link: {edge[0]} -- {edge[1]}")
    return edge


def remove_link(hub: Path, ref_a: str, ref_b: str) -> tuple[str, str] | None:
    a = resolve(hub, ref_a).slug
    b = resolve(hub, ref_b).slug
    edge = (min(a, b), max(a, b))
    links = read_links(hub)
    kept = [e for e in links if (min(e[0], e[1]), max(e[0], e[1])) != edge]
    if len(kept) == len(links):
        return None
    write_links(hub, kept)
    git.auto_commit(hub, f"unlink: {edge[0]} -- {edge[1]}")
    return edge


def closure(slugs: set[str], links: list[tuple[str, str]]) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for a, b in links:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    seen = set(slugs)
    queue = list(slugs)
    while queue:
        node = queue.pop()
        for neighbor in adjacency.get(node, ()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def partners_of(slug: str, links: list[tuple[str, str]]) -> list[str]:
    out = set()
    for a, b in links:
        if a == slug:
            out.add(b)
        elif b == slug:
            out.add(a)
    return sorted(out)
