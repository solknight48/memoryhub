# MemoryHub development

`mh` — git-like checkpoints for purified AI session context. Python ≥3.12, uv-managed, Typer CLI over system git.

- Run tests: `uv run pytest` (E2E: subprocess against `python -m memoryhub` in a hermetic HOME — never the real one)
- Local install: `uv tool install -e .`
- Layout: `src/memoryhub/{cli,hub,git,purify,checkpoint,load,agents,curate,server,hooks}.py`; skill and UI ship as package data in `src/memoryhub/{skill,ui}/`
- `curate.py` is the ONLY code that parses session markdown (load/show/search read files verbatim). It must never rewrite a file whose parse→re-render is not byte-identical — that guard is what keeps editing safe for dialog quoting mh's own headings. Mutations call `ensure_committable()` before touching disk, so a failed commit can't leave a change outside the journal
- `server.py` is stdlib-only on purpose: typer stays the single runtime dependency. `dispatch()` is a plain function so the API is tested without a socket
- `purify.py` is vendored from `~/.claude/skills/purify-context/purify.py` — keep extraction semantics identical (the parity test in `tests/test_purify.py` pins this)
- Presentation deliberately diverges: `render()` emits `## User N` / `## Agent N` where the original emits `## QN` / `## AN`. The parity test stays byte-for-byte by relabelling the original's output via `as_mh_format()`; extend that helper, don't weaken the assertion, if rendering changes again
- Per-turn models ride *beside* the turns (`models: list[str]`, parallel to `turns`), never inside the tuple — so a transcript naming no model renders exactly what the original does, and the parity fixture stays model-free to keep pinning the real save path. Anything that reorders or drops turns (`drop_trailing_unanswered`, `delete_exchange`) must move the model with them
- The UI's pure JS (markdown renderer, model labels) is tested for real: `tests/uijs.mjs` slices the functions out of the shipped `index.html` and runs them against a DOM shim; call them from Python with `run_ui_js(...)` in `conftest.py`. These tests skip without `node`, which both CI runners have
