"""The repo's own tooling scripts: the parts of their logic that decide what the gate demands."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load("release")
hook = _load("check_changelog_fragment")


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        ".github/workflows/ci.yml",
        "scripts/release.py",
        "tests/test_cli.py",
        ".githooks/pre-commit",
        ".claude/settings.json",
        "AGENTS.md",
        "CLAUDE.md",
    ],
)
def test_tooling_changes_need_no_fragment(path: str) -> None:
    assert not release.needs_fragment(path)


@pytest.mark.parametrize("path", ["src/pkg/cli.py", "pyproject.toml", "README.md", "scripts.py", "testsuite/x.py"])
def test_package_changes_need_a_fragment(path: str) -> None:
    assert release.needs_fragment(path)


def test_gate_and_pre_commit_hook_agree() -> None:
    assert release.NO_FRAGMENT_NEEDED == hook.NO_FRAGMENT_NEEDED


def test_release_follows_towncrier_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "_tool", lambda name: {"filename": "docs/CHANGES.md"} if name == "towncrier" else {})
    assert release.changelog_file() == "docs/CHANGES.md"
    monkeypatch.setattr(release, "_tool", lambda name: {})
    assert release.changelog_file() == "CHANGELOG.md"


def test_release_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Independent of this project's own [tool.cli-generator]: defaults, then configured values.
    monkeypatch.setattr(release, "_tool", lambda name: {})
    assert (release.gate_extras(), release.release_commit_message("1.2.3")) == ([], "Release v1.2.3")

    config = {"gate_extras": ["browser"], "release_commit": "chore(release): v{version}"}
    monkeypatch.setattr(release, "_tool", lambda name: config if name == "cli-generator" else {})
    assert (release.gate_extras(), release.release_commit_message("1.2.3")) == (["browser"], "chore(release): v1.2.3")
