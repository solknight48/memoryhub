"""Keep the two READMEs, and the CLI, from drifting apart.

A translated README rots quietly: the next feature updates the English one and
leaves the Chinese behind, with nothing to notice. These are cheap structural
checks — they cannot verify the prose says the same thing, but they do catch a
section or a command added to one file and not the other.
"""

import re
from pathlib import Path

import pytest

from memoryhub.cli import app

ROOT = Path(__file__).resolve().parents[1]
EN = ROOT / "README.md"  # English is the front page GitHub renders
ZH = ROOT / "README.zh.md"
READMES = (EN, ZH)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _headings(text: str, level: str) -> int:
    """Count real headings only. The READMEs quote mh's own `## User 1` output
    inside code fences, which is content, not structure."""
    count, fence = 0, None
    for line in text.splitlines():
        token = re.match(r"^\s*(```|~~~)", line)
        if token:
            fence = (
                token.group(1) if fence is None else (None if fence == token.group(1) else fence)
            )
            continue
        if fence is None and line.startswith(level + " "):
            count += 1
    return count


def _command_column(text: str) -> list[str]:
    """First column of every command-table row (identical in both languages —
    the signatures are things you type, so they are never translated)."""
    return [m.group(1).strip() for m in re.finditer(r"^\|\s*(`mh [^|]*?)\s*\|", text, re.M)]


def _documented_commands(text: str) -> set[str]:
    return {
        m.group(1) for row in _command_column(text) for m in re.finditer(r"`mh ([a-z][\w-]*)", row)
    }


def _cli_commands() -> set[str]:
    names = {
        c.name or c.callback.__name__.rstrip("_").replace("_", "-") for c in app.registered_commands
    }
    return names | {g.name for g in app.registered_groups}


@pytest.mark.parametrize("path", READMES, ids=lambda p: p.name)
def test_readme_exists_and_fences_are_balanced(path):
    text = _text(path)
    assert text.strip(), f"{path.name} is empty"
    assert _text(path).count("\n```") % 2 == 0, f"unbalanced code fence in {path.name}"


def test_same_section_structure():
    en, zh = _text(EN), _text(ZH)
    assert _headings(en, "##") == _headings(zh, "##"), (
        "section count differs — a `##` section was added to one README only"
    )
    assert _headings(en, "###") == _headings(zh, "###"), (
        "subsection count differs — a `###` was added to one README only"
    )


def test_command_tables_are_identical():
    en, zh = _command_column(_text(EN)), _command_column(_text(ZH))
    assert en, f"no command table found in {EN.name}"
    assert en == zh, "command tables differ between the two READMEs"


def test_every_documented_command_exists_in_the_cli():
    cli = _cli_commands()
    for path in READMES:
        stale = sorted(_documented_commands(_text(path)) - cli)
        assert not stale, f"{path.name} documents commands the CLI does not have: {stale}"


def test_every_cli_command_is_documented():
    for path in READMES:
        undocumented = sorted(_cli_commands() - _documented_commands(_text(path)))
        assert not undocumented, f"{path.name} is missing commands: {undocumented}"


def _links_to(text: str, name: str) -> bool:
    """A markdown or HTML link ending in the file's name — relative, or the absolute GitHub
    URL the READMEs use so the same text renders on the PyPI page."""
    return re.search(rf'(?:\]\(|href=")(?:[^)"\s]*/)?{re.escape(name)}[)"]', text) is not None


def test_the_readmes_link_to_each_other():
    assert _links_to(_text(EN), ZH.name), f"{EN.name} does not link to {ZH.name}"
    assert _links_to(_text(ZH), EN.name), f"{ZH.name} does not link to {EN.name}"
