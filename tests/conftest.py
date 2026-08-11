"""Throwaway git repositories, and the import path for the payload.

`payload/` holds the files that get installed into a target repo as `tools/`.
Tests import them from that source location rather than from an installed copy,
so a failure points at the file you would actually edit.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
PAYLOAD = SKILL_ROOT / "payload"
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


def _install_into(repo: Path) -> Path:
    """Reproduce the installed layout: the shim, plus the package beside it.

    A `copyfile` loop silently produced a `tools/` directory with a shim and no
    package, which fails at import with a message about `extant` rather than
    about the fixture. That went from one call site to eight the moment the
    shim's version handshake made the package mandatory, so it lives here once
    instead of being pasted into each of the seven files that need it.

    The loop it replaces also named `extant_config.py` explicitly. That file is
    now `extant/config.py` and arrives with the package, which is exactly the
    kind of per-file list this helper exists to stop anyone maintaining.

    `__pycache__` is not copied: a fixture repository should hold what the
    installer would put there, not this checkout's bytecode.
    """
    tools = Path(repo) / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PAYLOAD / "extant_collect.py", tools / "extant_collect.py")
    shutil.copytree(PAYLOAD / "extant", tools / "extant", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    return tools


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
    # `_ACTIVE` is the built Config the package's functions are handed, and it
    # is the same information as the globals above in a second shape. Restoring
    # one without the other would leave this module describing two different
    # projects at once, which is the exact divergence Config was introduced to
    # end - so it is saved and restored alongside them rather than left to the
    # next test's reload to fix.
    saved_active = hc._ACTIVE
    # Per-document state, cleared for the same reason the config is
    # neutralised: it is a module global, and a test that leaves it set makes
    # the NEXT test's answer depend on which one ran first.
    #
    # It stayed invisible while nothing read `_DOC_PATH` outside the call that
    # sets it. The moment link suppression became scoped to the document's
    # position in the tree, three tests began failing in the full suite and
    # passing alone - which is what an order dependency looks like, and why
    # this belongs here rather than in the tests that noticed it.
    saved_doc, saved_base = hc._DOC_PATH, hc._LINK_BASE
    hc._DOC_PATH, hc._LINK_BASE = None, None
    hc.reload_config(neutral)
    try:
        yield
    finally:
        hc.CONFIG = saved_config
        hc._ACTIVE = saved_active
        hc._DOC_PATH, hc._LINK_BASE = saved_doc, saved_base
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
