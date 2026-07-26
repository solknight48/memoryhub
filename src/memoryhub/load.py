"""Assemble the warm-start context pack from selected checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import checkpoint as ck
from . import git
from .hub import MhError, read_current


def estimate_tokens(text: str) -> int:
    # Documented estimate (~4 chars/token); no tokenizer dependency.
    return max(1, len(text) // 4)


@dataclass
class LoadResult:
    text: str
    loaded: list[str]
    expanded: bool
    included: list[dict]
    omitted: list[str]
    budget: int | None
    used: int
    over_budget: bool
    sha: str


def build(
    hub: Path,
    refs: list[str] | None,
    follow_links: bool,
    budget: int | None,
) -> LoadResult:
    all_cps = ck.list_checkpoints(hub)
    if refs:
        base = [ck.resolve(hub, r) for r in refs]
    else:
        current = read_current(hub)
        if not current:
            raise MhError(
                "no current checkpoint (run 'mh checkpoint <name>' or 'mh goto <ckpt>')"
            )
        base = [ck.resolve(hub, current)]

    slugs = {c.slug for c in base}
    expanded = False
    if follow_links:
        full = ck.closure(slugs, ck.read_links(hub))
        expanded = full != slugs
        slugs = full

    selected = [c for c in all_cps if c.slug in slugs]
    files = sorted(
        ((f, c.slug) for c in selected for f in c.sessions), key=lambda t: t[0].name
    )

    blocks = []
    for path, slug in files:
        content = path.read_text(encoding="utf-8", errors="replace").rstrip()
        text = f"<!-- mh session: {slug}/{path.name} -->\n\n{content}\n"
        blocks.append(
            {
                "id": f"{slug}/{path.name}",
                "checkpoint": slug,
                "file": path.name,
                "text": text,
                "tokens": estimate_tokens(text),
                "body": content,
            }
        )

    over_budget = False
    if budget is None:
        kept = blocks
        used = sum(b["tokens"] for b in blocks)
    else:
        # Whole sessions only, newest-first until the budget stops fitting —
        # the pack is always a contiguous newest suffix of the timeline. The
        # newest session is always included, even alone over budget.
        keep_idx: list[int] = []
        used = 0
        for i in reversed(range(len(blocks))):
            tokens = blocks[i]["tokens"]
            if not keep_idx:
                keep_idx.append(i)
                used += tokens
                over_budget = tokens > budget
                continue
            if used + tokens <= budget:
                keep_idx.append(i)
                used += tokens
            else:
                break
        kept = [blocks[i] for i in sorted(keep_idx)]

    omitted = [b["id"] for b in blocks if b not in kept]

    try:
        sha = git.run(hub, "rev-parse", "--short", "HEAD").strip()
    except git.GitError:
        sha = "empty"

    names = " + ".join(sorted(slugs))
    linked = " (linked)" if expanded else ""
    header = (
        f"<!-- mh | loaded: {names}{linked} | "
        f"{len(kept)} of {len(blocks)} sessions | @ {sha} -->\n"
    )
    parts = [header]
    for block in kept:
        parts.append("\n" + block["text"])
    if not blocks:
        parts.append("\n(no sessions saved in the loaded checkpoints yet)\n")
    if omitted:
        parts.append(
            f"\n<!-- mh: omitted {len(omitted)} older session(s) for budget: "
            f"{', '.join(omitted)} — fetch with `mh show <checkpoint>/<file>` -->\n"
        )

    return LoadResult(
        text="".join(parts),
        loaded=sorted(slugs),
        expanded=expanded,
        included=[
            {k: b[k] for k in ("checkpoint", "file", "tokens", "body")} for b in kept
        ],
        omitted=omitted,
        budget=budget,
        used=used,
        over_budget=over_budget,
        sha=sha,
    )
