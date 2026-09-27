#!/usr/bin/env bash
# Point git at the versioned hooks in .githooks/ (git never runs hooks from
# the working tree on its own). One-time per clone; Claude Code sessions do
# it automatically via the SessionStart hook in .claude/settings.json.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
git -C "$repo_root" config core.hooksPath .githooks
chmod +x "$repo_root"/.githooks/*
echo "git hooks -> $repo_root/.githooks"
