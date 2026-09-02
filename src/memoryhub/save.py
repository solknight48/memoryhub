"""Where a saved session lands — one policy for every path that saves.

Three things store a session: `mh save`, the SessionEnd/PreCompact hook, and
the map's live panel. Each used to carry its own copy of the rules, and they
drifted — `mh save` would write a second copy of a session that was already
stored in another checkpoint. The rules live here now:

- A session lives in exactly one checkpoint. A save with no target updates it
  where it already is; only a session never stored before lands in the current
  checkpoint.
- An explicit target that differs from where the session lives *moves* it
  there, in one commit — never a second copy.
- A compacted save (an agent-written summary) is a deliberate choice. Only an
  explicit `mh save` replaces it with purified dialog; the hook and the panel
  keep it and say so.
- The commit is checked for before anything touches disk, so a failed commit
  can never leave a file outside the journal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import checkpoint as ck
from . import curate, git
from .hub import MhError, read_current


@dataclass
class Stored:
    checkpoint: ck.Checkpoint
    file: str
    moved_from: str | None = None  # the checkpoint the session was moved out of


def store(
    hub: Path,
    key: str,
    body: str,
    stamp: str,
    target_ref: str | None = None,
    *,
    replace_compacted: bool = False,
    note: str = "",
) -> Stored:
    """Write one session document into the hub and commit it.

    `key` is the session's identity (see checkpoint.session_key); `stamp` the
    filename timestamp; `target_ref` an explicit checkpoint, or None to follow
    the session to where it already lives, else the current checkpoint. `note`
    names the save path in the journal ("hook", "live").
    """
    home, existing = ck.find_by_key(hub, key)
    if existing is not None:
        parsed = curate.parse(existing.read_text(encoding="utf-8", errors="replace"))
        fresh = curate.parse(body)
        keep = parsed and parsed.compacted and not (fresh and fresh.compacted)
        if keep and not replace_compacted:
            raise MhError(f"{home.slug}/{existing.name} is a compacted save — kept as is")
    if target_ref:
        target = ck.resolve(hub, target_ref)
    elif home is not None:
        target = home
    else:
        current = read_current(hub)
        if not current:
            raise MhError("no current checkpoint (run 'mh checkpoint <name>' or 'mh goto <ckpt>')")
        target = ck.resolve(hub, current)

    curate.ensure_committable(hub)
    moved_from = None
    if existing is not None and home.slug != target.slug:
        existing.unlink()
        moved_from = home.slug
    fname = ck.write_session(target, body, key, stamp)
    message = f"save: {fname} -> {target.slug}"
    if moved_from:
        message += f" (moved from {moved_from})"
    if note:
        message += f" ({note})"
    git.auto_commit(hub, message)
    return Stored(target, fname, moved_from)
