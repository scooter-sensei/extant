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
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
# payload/ holds what is installed into a target repo; SKILL_ROOT holds the
# installer and the detection module, which stay here. Both are importable so
# that install-time code is testable, not only the copied part. It was the
# untested half that shipped a crash on Python 3.11 and 3.12.
sys.path.insert(0, str(SKILL_ROOT / "payload"))
sys.path.insert(0, str(SKILL_ROOT))


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


@pytest.fixture(autouse=True)
def neutral_config(tmp_path: Path):
    """Run every in-process test against DEFAULT settings.

    Configuration is read once at import, relative to the payload file, and the
    upward search then finds THIS repository's own `.extant.toml`. Tests that
    call `main()` or `validate()` in process therefore inherit whatever this
    project happens to configure for itself, which has nothing to do with the
    behaviour under test.

    That coupling was invisible while the file configured only a consistency
    block, because `inconsistent-artifact` deliberately reads the config of the
    repository being CHECKED rather than the ambient one. `extra_docs` does not,
    so the moment this repository listed extra documents, a temporary repo was
    asked for files it had never heard of and one unrelated test went red.

    Without this, any contributor adding any setting here can turn unrelated
    tests red, and the failure names a document rather than a cause.

    Tests that run the tool as a SUBPROCESS are unaffected either way: a new
    process reads the target repository's config, which is the real install
    shape and is tested separately.
    """
    import extant_collect as hc

    # A directory with a `.git` in it and no config: the upward search stops
    # there, so this cannot pick up a stray file from anywhere above tmp_path.
    neutral = tmp_path / "_neutral_config"
    (neutral / ".git").mkdir(parents=True, exist_ok=True)

    saved_config = hc.CONFIG
    saved = {name: getattr(hc, name) for name in hc._CONFIG_DERIVED}
    hc.reload_config(neutral)
    try:
        yield
    finally:
        hc.CONFIG = saved_config
        for name, value in saved.items():
            setattr(hc, name, value)


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
