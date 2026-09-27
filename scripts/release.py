#!/usr/bin/env python3
"""Cut a release: gate, assemble the CHANGELOG from fragments, commit, tag.

    uv run scripts/release.py patch|minor|major

The version lives only in the git tag `vX.Y.Z` (uv-dynamic-versioning), so
the next version is the last `v*` tag bumped by the given part. The script
never pushes: it prints the push command, and pushing needs the user's OK.
Refuses to run off `main`, on a dirty tree, or when `main` has diverged from
`origin/main` — a release is a statement about what's on `main`.
Standard: tools/docs/standard-release.md, §3.
"""

from __future__ import annotations

import re
import subprocess
import sys
from typing import NoReturn

PARTS = ("patch", "minor", "major")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
GATE = (
    ("uv", "run", "ruff", "check", "."),
    ("uv", "run", "ruff", "format", "--check", "."),
    ("uv", "run", "ty", "check"),
    ("uv", "run", "pytest"),
)


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture)  # noqa: S603 — фиксированные команды
    return result.stdout.strip() if capture else ""


def fail(message: str) -> NoReturn:
    print(f"release: {message}", file=sys.stderr)
    raise SystemExit(1)


def last_version() -> tuple[int, int, int]:
    tags = run("git", "tag", "--list", "v*", "--merged", "HEAD", capture=True).split()
    versions: list[tuple[int, int, int]] = [(int(m[1]), int(m[2]), int(m[3])) for t in tags if (m := TAG_RE.match(t))]
    if not versions:
        fail("no vX.Y.Z tag on main — tag the current version first: git tag -a vX.Y.Z -m vX.Y.Z <sha>")
    return max(versions)


def bump(version: tuple[int, int, int], part: str) -> str:
    major, minor, patch = version
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> None:
    part = sys.argv[1] if len(sys.argv) == 2 else ""
    if part not in PARTS:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)

    if run("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True) != "main":
        fail("releases are cut from main")
    if run("git", "status", "--porcelain", capture=True):
        fail("working tree is not clean — commit or stash first")
    run("git", "fetch", "--quiet", "origin", "main")
    behind, ahead = run("git", "rev-list", "--left-right", "--count", "origin/main...HEAD", capture=True).split()
    if behind != "0":
        fail(f"main is {behind} commit(s) behind origin/main — pull first")

    for command in GATE:
        print("$", " ".join(command), file=sys.stderr)
        try:
            run(*command)
        except subprocess.CalledProcessError:
            fail(f"gate failed: {' '.join(command)}")

    version = bump(last_version(), part)
    tag = f"v{version}"
    if run("git", "tag", "--list", tag, capture=True):
        fail(f"tag {tag} already exists")

    run("uv", "run", "towncrier", "build", "--version", version, "--yes")
    run("git", "add", "CHANGELOG.md")  # towncrier сам делает git rm собранных фрагментов
    run("git", "commit", "-m", f"Release {tag}")
    run("git", "tag", "-a", tag, "-m", tag)

    note = f" (main is also {ahead} commit(s) ahead of origin/main)" if ahead != "0" else ""
    print(f"Tagged {tag}{note}. Publish with:\n    git push origin main {tag}")


if __name__ == "__main__":
    main()
