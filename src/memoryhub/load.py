"""Assemble the warm-start context pack from selected checkpoints."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import checkpoint as ck
from . import git
from .hub import MhError, read_current

# One definition; the CLI, the hook, the API and the page share it. About a
# tenth of a 200k context: three or four typical sessions of purified dialog,
# which is a warm start rather than a reminder. The estimate runs ~10% low on
# English markdown, so this is ~22k real tokens.
DEFAULT_BUDGET = 20000

# CJK scripts run ~1 token per character where ASCII prose runs ~4 characters
# per token; a plain len//4 undercounts a Chinese session ~4x and the budget
# would pack four times more context than asked for.
CJK_RE = re.compile(
    "["
    "\u3000-\u30ff"  # CJK punctuation, hiragana, katakana
    "\u3400-\u4dbf"  # CJK extension A
    "\u4e00-\u9fff"  # CJK unified
    "\uac00-\ud7a3"  # hangul syllables
    "\uf900-\ufaff"  # CJK compatibility
    "\uff00-\uffef"  # fullwidth forms
    "]"
)


def estimate_tokens(text: str) -> int:
    # Still a heuristic — deliberately no tokenizer dependency.
    cjk = len(CJK_RE.findall(text))
    return max(1, cjk + (len(text) - cjk) // 4)


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
    skipped: list[str]  # left out on request (mh skip, the map's checkbox)


def build(
    hub: Path,
    refs: list[str] | None,
    follow_links: bool,
    budget: int | None,
    tree: bool = False,
) -> LoadResult:
    all_cps = ck.list_checkpoints(hub)
    if refs:
        base = [ck.resolve(hub, r) for r in refs]
    else:
        current = read_current(hub)
        if not current:
            raise MhError("no current checkpoint (run 'mh checkpoint <name>' or 'mh goto <ckpt>')")
        base = [ck.resolve(hub, current)]

    slugs = {c.slug for c in base}
    links = ck.read_links(hub) if follow_links else []
    expanded = False
    # The pack is closed under three rules, applied until nothing more joins:
    # a sub-checkpoint brings its parents (a scope includes what it sits in);
    # with `tree`, every checkpoint brings its whole node — the top-level
    # checkpoint it sits under and everything below that; and a link brings
    # its partner. The parent alone, without `tree`, stays the parent.
    while True:
        before = len(slugs)
        for s in list(slugs):
            parts = s.split(".")
            slugs.update(".".join(parts[:i]) for i in range(1, len(parts)))
        if tree:
            roots = {s.split(".", 1)[0] for s in slugs}
            slugs.update(c.slug for c in all_cps if c.slug.split(".", 1)[0] in roots)
        if links:
            full = ck.closure(slugs, links)
            expanded = expanded or full != slugs
            slugs = full
        if len(slugs) == before:
            break

    selected = [c for c in all_cps if c.slug in slugs]
    files = sorted(((f, c.slug) for c in selected for f in c.sessions), key=lambda t: t[0].name)
    # a skipped session stays in its checkpoint but never in the pack — the
    # user said so (mh skip, or the checkbox on the map's session row)
    skips = ck.read_skips(hub)
    skipped = [f"{slug}/{f.name}" for f, slug in files if f"{slug}/{f.name}" in skips]
    files = [(f, slug) for f, slug in files if f"{slug}/{f.name}" not in skips]

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
        keep_set = set(range(len(blocks)))
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
        keep_set = set(keep_idx)
        kept = [blocks[i] for i in sorted(keep_idx)]

    omitted = [b["id"] for i, b in enumerate(blocks) if i not in keep_set]

    try:
        sha = git.run(hub, "rev-parse", "--short", "HEAD").strip()
    except git.GitError:
        sha = "empty"

    names = " + ".join(sorted(slugs))
    linked = " (linked)" if expanded else ""
    header = (
        f"<!-- mh | loaded: {names}{linked} | {len(kept)} of {len(blocks)} sessions | @ {sha} -->\n"
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
    if skipped:
        parts.append(
            f"\n<!-- mh: skipped {len(skipped)} session(s) on request: {', '.join(skipped)}"
            f" — `mh unskip <checkpoint>/<file>` loads them again -->\n"
        )

    return LoadResult(
        text="".join(parts),
        loaded=sorted(slugs),
        expanded=expanded,
        included=[{k: b[k] for k in ("id", "checkpoint", "file", "tokens", "body")} for b in kept],
        omitted=omitted,
        budget=budget,
        used=used,
        over_budget=over_budget,
        sha=sha,
        skipped=skipped,
    )
