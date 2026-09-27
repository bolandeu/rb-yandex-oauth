#!/usr/bin/env python3
"""The quality gate and the release, in one place.

    uv run scripts/release.py --check              run the full gate, release nothing
    uv run scripts/release.py patch|minor|major    gate, assemble the changelog, commit, tag

This local gate is the authoritative check (tools/docs/standard-release.md
§3): agents run `--check` before committing, CI (if any) runs `--check`,
and nothing is released unless it passes on the machine cutting the release.
Gate steps, in order — the first failure stops everything and prints that
step's name and output:

    uv lock --check · ruff check · ruff format --check · ty check · pytest ·
    changelog fragment (at least one in changelog.d/ when anything but
    uv.lock / .github/ changed since the last tag) · build + install the wheel
    into a throwaway venv, `<cli> --version` must print the version being
    built, `<cli> --help` must work · osv-scanner over uv.lock (skipped with a
    notice when osv-scanner isn't installed)

The version lives only in git tags (`vX.Y.Z`, read at build time by
uv-dynamic-versioning); a release bumps the last `v*` tag by `part`. Releasing
refuses off `main`, on a dirty tree, when `main` is behind its upstream, or
with no fragments. It never pushes: it prints the push command for you.

Canonical copy: cli-generator `template/scripts/release.py`. Other repos
copy it verbatim instead of editing it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
FRAGMENTS = ROOT / "changelog.d"
PARTS = ("patch", "minor", "major")
COMMANDS = (
    ("uv lock --check", ("uv", "lock", "--check")),
    ("ruff check", ("uv", "run", "ruff", "check", ".")),
    ("ruff format --check", ("uv", "run", "ruff", "format", "--check", ".")),
    ("ty check", ("uv", "run", "ty", "check")),
    ("pytest", ("uv", "run", "pytest")),
)
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class StepFailed(Exception):
    def __init__(self, output: str) -> None:
        super().__init__(output)
        self.output = output


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""


def step_output(*args: str, env: dict[str, str] | None = None) -> str:
    """Run one gate command; raise StepFailed with its combined output if it fails."""
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, env=env, check=False)
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise StepFailed(f"$ {' '.join(args)}\n{output}")
    return output


def fail(message: str) -> NoReturn:
    print(f"release: {message}", file=sys.stderr)
    raise SystemExit(1)


def tags() -> list[tuple[int, int, int]]:
    result = subprocess.run(["git", "tag", "--list", "v*"], cwd=ROOT, text=True, capture_output=True, check=False)
    listed = result.stdout.split()  # not a git repo yet (fresh scaffold): no tags
    return sorted((int(m[1]), int(m[2]), int(m[3])) for t in listed if (m := TAG_RE.match(t)))


def fragments() -> list[Path]:
    return [p for p in FRAGMENTS.glob("*") if p.is_file() and not p.name.startswith(".")]


# --- gate steps ----------------------------------------------------------------


def run_command(argv: tuple[str, ...]) -> str:
    step_output(*argv)
    return ""


def _changed_since(tag: str) -> list[str]:
    """Files that differ from `tag`: committed, staged, unstaged and untracked."""
    tracked = run("git", "diff", "--name-only", tag, capture=True).splitlines()
    untracked = run("git", "ls-files", "--others", "--exclude-standard", capture=True).splitlines()
    return sorted(set(tracked + untracked))


def check_fragment() -> str:
    # Looks at the working tree, not commits: `towncrier check` only sees
    # committed files, and agents run --check before committing.
    if found := fragments():
        return f"{len(found)} fragment(s)"
    versions = tags()
    if versions:
        last = "v{}.{}.{}".format(*versions[-1])
        changed = _changed_since(last)
        if not changed:
            return f"nothing changed since {last}"
        # Dependabot's lock/CI bumps aren't user-visible changes.
        if all(path == "uv.lock" or path.startswith(".github/") for path in changed):
            return f"only uv.lock / .github/ changed since {last}"
        since = f"since {last}"
    else:
        since = "and there is no release tag yet"
    raise StepFailed(
        f"changes exist {since} but changelog.d/ has no fragment. Add one:\n"
        '  uv run towncrier create +<slug>.<type>.md -c "What changed, for a human reader."\n'
        "  (type: added/changed/deprecated/removed/fixed/security)"
    )


def check_vulnerabilities() -> str:
    scanner = shutil.which("osv-scanner")
    if scanner is None:
        return "skipped: osv-scanner not installed (brew install osv-scanner)"
    step_output(scanner, "--lockfile=uv.lock")
    return "no known vulnerabilities in uv.lock"


def _wheel_version(wheel: Path) -> str:
    """`Version:` from the wheel's METADATA — what importlib.metadata (and so `--version`) reports.

    Not the file name: it normalizes the local part (`+0814724` -> `+814724`).
    """
    with zipfile.ZipFile(wheel) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = archive.read(name).decode()
    return next(line.split(":", 1)[1].strip() for line in metadata.splitlines() if line.startswith("Version:"))


def check_installed_wheel(version: str | None) -> str:
    """Build the wheel (as `version` if given), install it into a throwaway venv, run the CLI."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    script = next(iter(project.get("scripts", {})), None)
    # The release tag doesn't exist yet while the gate runs, so tell the build which version it is.
    env = {**os.environ, "UV_DYNAMIC_VERSIONING_BYPASS": version} if version else None
    with tempfile.TemporaryDirectory() as tmp:
        dist, venv = Path(tmp) / "dist", Path(tmp) / "venv"
        step_output("uv", "build", "--wheel", "--out-dir", str(dist), env=env)
        wheel = next(dist.glob("*.whl"))
        built = _wheel_version(wheel)
        if version is not None and built != version:
            raise StepFailed(f"built {wheel.name}, expected version {version}")
        if tags() and built.startswith("0.0.0"):
            raise StepFailed(f"built version {built}: the build saw no v* tag (uv-dynamic-versioning fell back)")
        step_output("uv", "venv", "--quiet", str(venv))
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        step_output("uv", "pip", "install", "--quiet", "--python", str(python), str(wheel))
        if script is None:
            return f"{wheel.name} installs (no console script to run)"
        exe = python.parent / (f"{script}.exe" if os.name == "nt" else script)
        printed = step_output(str(exe), "--version").splitlines()
        reported = printed[-1].strip() if printed else ""
        if reported != built:
            raise StepFailed(f"`{script} --version` printed {reported!r}, but the wheel is version {built}")
        step_output(str(exe), "--help")
        return f"{wheel.name}; `{script} --version` = {reported}; `{script} --help` ok"


def run_gate(version: str | None) -> None:
    steps: list[tuple[str, Callable[[], str]]] = [
        *((name, lambda argv=argv: run_command(argv)) for name, argv in COMMANDS),
        ("changelog fragment", check_fragment),
        ("build + install wheel", lambda: check_installed_wheel(version)),
        ("vulnerability audit", check_vulnerabilities),
    ]
    for name, step in steps:
        print(f"release: {name} ...", end=" ", flush=True)
        try:
            detail = step()
        except StepFailed as exc:
            print("FAILED", flush=True)
            print(f"\nrelease: gate step '{name}' failed:\n{exc.output}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"ok ({detail})" if detail else "ok", flush=True)


# --- release -------------------------------------------------------------------


def check_branch() -> None:
    if run("git", "rev-parse", "--abbrev-ref", "HEAD", capture=True) != "main":
        fail("releases are cut from main")
    if run("git", "status", "--porcelain", capture=True):
        fail("working tree is not clean — commit or stash first")
    run("git", "fetch", "--quiet")
    try:
        counts = run("git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}", capture=True)
    except subprocess.CalledProcessError:
        fail("main has no upstream — push it first (git push -u origin main)")
    _, behind = counts.split()
    if int(behind):
        fail(f"main is {behind} commit(s) behind its upstream — pull first")


def next_version(part: str) -> str:
    versions = tags()
    if not versions:
        fail("no vX.Y.Z tag yet — tag the current version first: git tag -a v0.1.0 -m v0.1.0")
    major, minor, patch = versions[-1]
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) == 2 else ""
    if arg == "--check":
        run_gate(None)
        print("release: gate passed")
        return
    if arg not in PARTS:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    check_branch()
    if not fragments():
        fail("changelog.d/ has no fragments — nothing to release (uv run towncrier create +<slug>.<type>.md -c '...')")
    version = next_version(arg)
    tag = f"v{version}"
    if run("git", "tag", "--list", tag, capture=True):
        fail(f"tag {tag} already exists")
    run_gate(version)

    run("uv", "run", "towncrier", "build", "--version", version, "--yes")  # writes CHANGELOG.md, `git rm`s fragments
    run("git", "add", "--all", "CHANGELOG.md", *(["changelog.d"] if FRAGMENTS.exists() else []))
    run("git", "commit", "-m", f"Release {tag}")
    run("git", "tag", "-a", tag, "-m", tag)
    print(f"Released {tag} locally. Push it (needs your confirmation): git push --follow-tags")
    print(f'Then pin it anywhere with: uv tool install "git+<repo-url>@{tag}"')


if __name__ == "__main__":
    main()
