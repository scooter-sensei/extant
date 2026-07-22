"""Throwaway git repositories, and the import path for the payload.

`payload/` holds the files that get installed into a target repo as `tools/`.
Tests import them from that source location rather than from an installed copy,
so a failure points at the file you would actually edit.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "handoff"
sys.path.insert(0, str(SKILL_ROOT / "payload"))


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, Callable[[str, str, str], str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-b", "main")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")

    def commit(filename: str, content: str, message: str) -> str:
        target = repo / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        _run(repo, "add", filename)
        _run(repo, "commit", "-m", message)
        return _run(repo, "rev-parse", "HEAD").strip()

    return repo, commit
