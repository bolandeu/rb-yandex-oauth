#!/usr/bin/env python3
"""Block a command's logic from changing without its docstring changing too.

Every command function's docstring is what Typer renders as `--help` —
the documentation agents and humans read (see architecture.md, "AI-first
output"). A command is a function in `src/*/commands/*.py` (or the globs in
`[tool.cli-generator] commands` in pyproject.toml) decorated with
`output.guard`; "logic" is its signature plus its body minus the
docstring. One check, three callers:

    check_command_docstrings.py                      git pre-commit (.githooks/): staged vs HEAD, exit 1
    check_command_docstrings.py --claude-post-edit   Claude Code PostToolUse: the edited file vs HEAD, exit 2
    check_command_docstrings.py --claude-stop        Claude Code Stop: every changed command file vs HEAD, exit 2

Exit 2 is how a Claude Code hook hands its stderr back to the agent. The
Stop hook lets the turn end on its second attempt (`stop_hook_active`), so
a change that truly doesn't alter behaviour can't loop forever; the git
hook's escape for the same case is `SKIP_DOCSTRING_CHECK=1 git commit ...`.
"""

from __future__ import annotations

import ast
import fnmatch
import functools
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_COMMAND_FILES = ("src/*/commands/*.py",)


@functools.cache
def command_globs() -> tuple[str, ...]:
    """Where commands live: `[tool.cli-generator] commands` in pyproject.toml (a glob or a list), else the default.

    Relative to the repo root (main() chdirs there first).
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # the hook's python3 is older than 3.11
        return DEFAULT_COMMAND_FILES
    try:
        config = tomllib.loads(Path("pyproject.toml").read_text()).get("tool", {}).get("cli-generator", {})
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_COMMAND_FILES
    value = config.get("commands", DEFAULT_COMMAND_FILES)
    return (value,) if isinstance(value, str) else tuple(value)


def is_command_file(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in command_globs())


def _git(*args: str) -> str | None:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def _doc_assignments(tree: ast.Module) -> dict[str, str]:
    """`name.__doc__ = <expr>` at module level (e.g. an f-string help text) -> the expression's source."""
    assigned: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Attribute) and target.attr == "__doc__" and isinstance(target.value, ast.Name):
                assigned[target.value.id] = ast.unparse(node.value)
    return assigned


def _commands(source: str) -> dict[str, tuple[str | None, str]]:
    """Map command name -> (docstring, normalized signature + body excluding the docstring).

    The docstring is the literal one, or — when the module later sets
    `command.__doc__ = f"..."` — that expression's source, since that's what
    `--help` renders.
    """
    tree = ast.parse(source)
    assigned = _doc_assignments(tree)
    commands: dict[str, tuple[str | None, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not any(ast.unparse(dec).split(".")[-1] == "guard" for dec in node.decorator_list):
            continue
        literal = ast.get_docstring(node)
        docstring = assigned.get(node.name, literal)
        body = node.body[1:] if literal is not None else node.body
        commands[node.name] = (docstring, "\n".join(ast.dump(part) for part in (node.args, *body)))
    return commands


def stale_commands(paths: list[str], *, staged: bool) -> list[str]:
    """Commands in `paths` (repo-relative) whose logic differs from HEAD while their docstring doesn't.

    `staged` compares the index (what's being committed); otherwise the working tree.
    """
    stale: list[str] = []
    for path in paths:
        new_source = _git("show", f":{path}") if staged else (Path(path).read_text() if Path(path).is_file() else None)
        if new_source is None:
            continue
        try:
            new = _commands(new_source)
            head_source = _git("show", f"HEAD:{path}")
            old = _commands(head_source) if head_source is not None else {}
        except SyntaxError:
            continue  # mid-edit; the next check sees the finished file
        for name, (doc, logic) in new.items():
            if not doc:
                stale.append(f"{path}: command `{name}` has no docstring — it is the command's --help text")
            elif name in old and logic != old[name][1] and doc == old[name][0]:
                stale.append(f"{path}: command `{name}` changed its logic, but its docstring (--help) did not")
    return stale


def _report(stale: list[str], footer: str) -> None:
    print("Command help is out of date:", file=sys.stderr)
    for item in stale:
        print(f"  - {item}", file=sys.stderr)
    print(
        "Update each docstring to describe the new behaviour (keep its `Example: {cli} ...` line valid), "
        "then refresh the help snapshots: uv run pytest --snapshot-update, and review tests/snapshots/help/.",
        file=sys.stderr,
    )
    print(footer, file=sys.stderr)


def _changed_command_files() -> list[str]:
    tracked = (_git("diff", "--name-only", "HEAD") or "").splitlines()
    untracked = (_git("ls-files", "--others", "--exclude-standard") or "").splitlines()
    return [p for p in tracked + untracked if is_command_file(p)]


def main(argv: list[str]) -> int:
    root = _git("rev-parse", "--show-toplevel")
    if root is None:
        return 0  # not a git checkout: nothing to compare against
    os.chdir(root.strip())

    if "--claude-post-edit" in argv:
        event = json.load(sys.stdin)
        file_path = event.get("tool_input", {}).get("file_path", "")
        try:
            path = Path(file_path).resolve().relative_to(Path.cwd()).as_posix()
        except ValueError:
            return 0
        if not is_command_file(path):
            return 0
        stale = stale_commands([path], staged=False)
        if stale:
            _report(stale, "Fix it now, in this same change.")
            return 2
        return 0

    if "--claude-stop" in argv:
        if json.load(sys.stdin).get("stop_hook_active"):
            return 0  # already blocked once this turn — don't loop
        stale = stale_commands(_changed_command_files(), staged=False)
        if stale:
            _report(stale, "Update the docstrings before finishing (or say why the behaviour is unchanged).")
            return 2
        return 0

    if os.environ.get("SKIP_DOCSTRING_CHECK"):
        return 0
    staged = [p for p in (_git("diff", "--cached", "--name-only", "--diff-filter=ACM") or "").splitlines()]
    stale = stale_commands([p for p in staged if is_command_file(p)], staged=True)
    if stale:
        _report(stale, "Commit blocked. If the behaviour truly didn't change: SKIP_DOCSTRING_CHECK=1 git commit ...")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
