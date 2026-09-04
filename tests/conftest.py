"""Throwaway git repositories, and the import path for the payload.

`payload/` holds the files that get installed into a target repo as `tools/`.
Tests import them from that source location rather than from an installed copy,
so a failure points at the file you would actually edit.
"""
from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
import tempfile
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

    STAGED ONCE PER PROCESS and then copied, for the reason the repository
    templates below are: twelve test files call this, and walking the payload
    to evaluate an ignore pattern against every file gives the same answer
    every time. The staging directory is built lazily - a run that never
    installs anything never pays for it - and removed at exit rather than left
    in the system temp directory.
    """
    tools = Path(repo) / "tools"
    shutil.copytree(_staged_payload(), tools, dirs_exist_ok=True)
    return tools


_STAGED: Path | None = None


def _staged_payload() -> Path:
    """The `tools/` directory an install produces, built once per process."""
    global _STAGED
    if _STAGED is None:
        staged = Path(tempfile.mkdtemp(prefix="extant-payload-")) / "tools"
        staged.mkdir(parents=True)
        shutil.copyfile(PAYLOAD / "extant_collect.py",
                        staged / "extant_collect.py")
        shutil.copytree(PAYLOAD / "extant", staged / "extant",
                        ignore=shutil.ignore_patterns("__pycache__"))
        atexit.register(shutil.rmtree, str(staged.parent), True)
        _STAGED = staged
    return _STAGED


@pytest.fixture(autouse=True)
def neutral_config(tmp_path: Path):
    """Run every in-process test against DEFAULT settings.

    Configuration is read once at import, relative to extant/session.py, and
    the upward search then finds THIS repository's own `.extant.toml`. Tests that
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
    from extant import session as hc

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
    # Per-document and per-run state, cleared for the same reason the config is
    # neutralised: both are reachable from the module, and a test that leaves
    # either set makes the NEXT test's answer depend on which one ran first.
    #
    # It stayed invisible while nothing read the document's PATH outside the
    # call that sets it. The moment link suppression became scoped to the
    # document's position in the tree, three tests began failing in the full
    # suite and passing alone - which is what an order dependency looks like,
    # and why this belongs here rather than in the tests that noticed it.
    #
    # Two objects now, where this used to name `_DOC_PATH` and `_LINK_BASE`
    # individually. That is the point of the change rather than a detail of it:
    # the old form had to grow a name every time a per-document or per-run value
    # appeared, and a value nobody added here is exactly the one that leaks. The
    # RUN scope is reset for the same reason, and was not covered before at all
    # - twenty-six caches keyed on `str(repo)` survived every test in this
    # suite, and only tmp_path handing out a fresh directory per test kept that
    # from being visible.
    saved_doc, saved_scope = hc._DOC, hc._SCOPE
    hc._DOC, hc._SCOPE = hc.DocScope(), hc.RunScope()
    hc.reload_config(neutral)
    try:
        yield
    finally:
        hc.CONFIG = saved_config
        hc._ACTIVE = saved_active
        hc._DOC, hc._SCOPE = saved_doc, saved_scope
        for name, value in saved.items():
            setattr(hc, name, value)


@pytest.fixture
def reconfigure(monkeypatch):
    """Change a configured value so that BOTH readers see it.

    Setting `session._BRANCH_TOKEN` (or any of the twenty-one names in
    `_CONFIG_DERIVED`) used to be enough, because the rules read those globals.
    From Task 9 the rules are package modules that read `ctx.config`, which is
    the built `Config` on `session._ACTIVE` - so a plain attribute patch
    reaches the derived globals and NOT the rule under test. The rule then matches
    nothing and the test reports no findings, which is indistinguishable from
    the rule working and the document being clean. Two tests failed exactly
    that way when their rules moved; the danger is the ones that would have
    kept passing.

    This writes the built Config and every global derived from it together,
    which is the same invariant `_apply_config` maintains: one build feeds both,
    so there is no arrangement in which a global and `_ACTIVE` disagree.
    `monkeypatch` undoes both at teardown.

    The alternative - writing a `.extant.toml` and calling `reload_config` -
    reaches the same two places and is what a test should use when the point IS
    the file. This exists for the many tests whose point is a pattern.
    """
    import dataclasses

    from extant import session as hc

    def apply(**changes: object):
        monkeypatch.setattr(hc, "_ACTIVE",
                            dataclasses.replace(hc._ACTIVE, **changes))
        for name, build in hc._CONFIG_DERIVED.items():
            monkeypatch.setattr(hc, name, build(hc._ACTIVE))
        return hc._ACTIVE

    return apply


# --- fixture repositories, built once and copied ------------------------------
#
# 498 tests across 40 files take `git_repo`, and each was paying three git
# spawns to build the same empty repository. Measured on this machine, median
# of 12, Windows with git 2.53.0:
#
#     build as the fixture did      113.4 ms   3 spawns
#     build with an environment dict 53.4 ms   1 spawn
#     copytree from a template       30.1 ms   0 spawns
#
# THE MIDDLE ROW IS HERE BECAUSE IT WAS EXPECTED TO BE SLOWER AND IS NOT.
# Handing `subprocess` a large environment on Windows was supposed to cost more
# than the two `git config` spawns it removes; measured, it is about half the
# cost of the fixture as written. It is still not what is used, because
# copytree is faster again and removes the last spawn as well - but "the
# obvious optimisation does not work" was not reproducible here, and a number
# nobody can reproduce is worse than no number.
#
# The richer the shape, the larger the saving. The `gitflow` repository in
# tests/test_multi_trunk.py runs 17 git commands, costs 1358.7 ms to build and
# 80.3 ms to copy (median of 6, 31 KB), and 15 tests take it - so that file
# went from paying the build 15 times to paying it once and copying 15 times.
# So this is one template PER SHAPE rather than one template, and each is
# session-scoped - under `-n auto` that means once per WORKER, not once per run.
#
# tests/test_fixture_templates.py is the guard, and it matters more than the
# speed does: a fixture that is subtly not equivalent produces tests passing
# against a repository shape nobody intended, which is the quiet failure this
# project's denominators exist to make visible.


def init_repo(repo: Path) -> None:
    """A fresh repository on `main`, with an identity so it can commit."""
    repo.mkdir(parents=True, exist_ok=True)
    _run(repo, "init", "-b", "main")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")


def committer(repo: Path) -> Callable[[str, str, str], str]:
    """`commit(filename, content, message) -> sha`, against `repo`.

    Separate from the fixture so a session-scoped TEMPLATE can be built with
    the same function the per-test copy hands out. A template built by a
    second, similar-looking helper is exactly the divergence these templates
    have to be tested against.
    """
    def commit(filename: str, content: str, message: str) -> str:
        target = repo / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        _run(repo, "add", filename)
        _run(repo, "commit", "-m", message)
        return _run(repo, "rev-parse", "HEAD").strip()

    return commit


@pytest.fixture(scope="session")
def empty_repo_template(tmp_path_factory) -> Path:
    """The five git spawns every `git_repo` used to pay, paid once."""
    template = tmp_path_factory.mktemp("empty-repo-template") / "repo"
    init_repo(template)
    return template


@pytest.fixture
def git_repo(tmp_path: Path,
             empty_repo_template: Path
             ) -> tuple[Path, Callable[[str, str, str], str]]:
    repo = tmp_path / "repo"
    shutil.copytree(empty_repo_template, repo)
    return repo, committer(repo)
