#!/usr/bin/env bash
# Run the test suite on another machine over ssh — a Mac, typically — to catch
# platform-specific failures before CI does. Syncs the WORKING TREE, not the
# last commit, so what you test is what you are about to push.
#
#   scripts/test-remote.sh [ssh-host] [pytest args...]
#
# Needs `uv` on the remote (curl -LsSf https://astral.sh/uv/install.sh | sh).
# Without node/tmux there, the UI-javascript and relay tests skip — the same
# ones the macOS CI runners skip.
set -euo pipefail
host="${1:-mac}"
shift || true
dir=".cache/memoryhub-remote-test"

rsync -a --delete \
  --exclude .git --exclude .venv --exclude .memoryhub --exclude .claude \
  --exclude .pytest_cache --exclude .ruff_cache --exclude __pycache__ \
  ./ "$host:$dir/"

# shellcheck disable=SC2029  # $dir and args expand here on purpose
ssh "$host" "cd '$dir' && export PATH=\"\$HOME/.local/bin:\$PATH\" \
  && { command -v uv >/dev/null \
       || { echo \"uv missing on \$(hostname) — install it there:\" >&2; \
            echo '  curl -LsSf https://astral.sh/uv/install.sh | sh' >&2; exit 1; }; } \
  && uv run --locked pytest -q $*"
