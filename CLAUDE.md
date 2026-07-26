# MemoryHub development

`mh` — git-like checkpoints for purified AI session context. Python ≥3.12, uv-managed, Typer CLI over system git.

- Run tests: `uv run pytest` (E2E: subprocess against `python -m memoryhub` in a hermetic HOME — never the real one)
- Local install: `uv tool install -e .`
- Layout: `src/memoryhub/{cli,hub,git,purify,checkpoint,load}.py`; skill ships as package data in `src/memoryhub/skill/`
- `purify.py` is vendored from `~/.claude/skills/purify-context/purify.py` — keep extraction semantics identical (the parity test in `tests/test_purify.py` pins this)
