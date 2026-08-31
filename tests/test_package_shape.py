"""The package ships, and a half-finished upgrade fails loudly.

Both tests exist because the shim keeps `tools/extant_collect.py` working, and
a shim that silently runs an OLD payload is indistinguishable from one that
works.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAYLOAD = REPO / "plugin" / "skills" / "extant" / "payload"


def test_package_version_matches_pyproject() -> None:
    """A shim that disagrees with its package is a half-finished upgrade."""
    sys.path.insert(0, str(PAYLOAD))
    import extant

    declared = re.search(r'^version = "([^"]+)"',
                         (REPO / "pyproject.toml").read_text(encoding="utf-8"),
                         re.M)
    assert declared, "pyproject has no version; this test would pass vacuously"
    assert extant.__version__ == declared.group(1), (
        f"package says {extant.__version__}, pyproject says {declared.group(1)}")


def test_shim_refuses_a_mismatched_package(tmp_path) -> None:
    """The failure mode this guards: a user has locally modified
    tools/extant_collect.py, install refuses to overwrite it, the new package
    lands beside it, and the OLD shim keeps running while everything looks
    fine. Version skew has to be an error, not a quiet downgrade.
    """
    staging = tmp_path / "tools"
    staging.mkdir()
    (staging / "extant_collect.py").write_bytes(
        (PAYLOAD / "extant_collect.py").read_bytes())
    package = staging / "extant"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "0.0.0-wrong"\n',
                                         encoding="utf-8")

    result = subprocess.run([sys.executable, str(staging / "extant_collect.py"),
                             "--verify", "--repo", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode != 0, "a mismatched package ran anyway"
    assert "version" in (result.stderr + result.stdout).lower(), (
        "the failure did not say what was wrong")


def test_installer_copies_the_whole_package(tmp_path) -> None:
    """A directory copy that silently drops files leaves a package that
    imports until it reaches the missing module.
    """
    sys.path.insert(0, str(REPO / "plugin" / "skills" / "extant"))
    import install

    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True,
                   check=True)
    actions = install.copy_payload(repo, dry_run=False, force=False)

    shipped = {p.relative_to(PAYLOAD).as_posix()
               for p in PAYLOAD.rglob("*.py")
               if "__pycache__" not in p.parts and "egg-info" not in str(p)}
    landed = {p.relative_to(repo / "tools").as_posix()
              for p in (repo / "tools").rglob("*.py")}
    assert shipped, "nothing is shipped; this test would pass vacuously"
    assert shipped == landed, (
        f"copied {len(landed)} of {len(shipped)} shipped files; "
        f"missing {sorted(shipped - landed)}")
    assert actions, "copy_payload reported nothing it did"


def test_git_helpers_differ_in_their_failure_behaviour(git_repo) -> None:
    """`run` raises where `soft` swallows. Collapsing them turns error paths
    into success paths, which is silent by construction.

    The case that actually distinguishes the two is `check=True`: a git
    command that RUNS and exits non-zero. A freshly `git init`-ed repo with
    no commits has no HEAD, so `git rev-parse HEAD` exits 128 (see
    `_git_soft`'s own docstring) without anything being wrong. If `check=True`
    were ever dropped, `subprocess.run` would return that non-zero result
    instead of raising, and this is the sub-case that would notice - a missing
    directory (below) raises via OSError before git even runs, so it cannot
    tell `check=True` apart from its absence.

    Through `SubprocessGit` rather than the two underscore helpers it delegates
    to, since Task 7 made those private again. The contract is the same one and
    is asserted at the level that now carries it - which is strictly more than
    before, because a SubprocessGit that wired `run` to the swallowing helper
    would pass the old form of this test and fail this one.
    """
    sys.path.insert(0, str(PAYLOAD))
    from extant.git import SubprocessGit

    git = SubprocessGit()
    repo, _ = git_repo
    assert git.soft(repo, "rev-parse", "HEAD") == "", (
        "soft must return empty when git runs and exits non-zero")
    try:
        git.run(repo, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError(
            "run must raise when git runs and exits non-zero (that is "
            "what check=True is for), not return empty")

    # A different failure mode: the command never runs at all. Kept because
    # soft's contract is to swallow OSError too, not only a
    # CalledProcessError from a non-zero exit - losing that would let
    # soft crash on a repo path that does not exist.
    missing = Path(__file__).resolve().parent / "__no_such_repo__"
    assert git.soft(missing, "rev-parse", "HEAD") == "", (
        "soft must return empty on failure, not raise")
    try:
        git.run(missing, "rev-parse", "HEAD")
    except OSError:
        pass
    else:
        raise AssertionError("run must raise on failure, not return empty")


def test_the_base_git_refuses_to_answer_rather_than_guessing(git_repo) -> None:
    """`Git` itself is not a working implementation, and must not become one.

    A base class that returned "" from both methods would satisfy every caller
    and silence every rule that asks git a question, which is the exact failure
    mode this project exists to catch: a check that examines nothing prints the
    same thing as a check that found nothing.
    """
    sys.path.insert(0, str(PAYLOAD))
    from extant.git import Git

    repo, _ = git_repo
    for method in ("run", "soft"):
        try:
            getattr(Git(), method)(repo, "rev-parse", "HEAD")
        except NotImplementedError:
            continue
        raise AssertionError(
            f"Git.{method} answered instead of refusing; an unimplemented seam "
            f"that returns a value makes every rule silently pass")


def test_counting_git_records_one_entry_per_call(git_repo) -> None:
    """One entry per call, including a soft one.

    The wrapper-counting this replaces saw TWO for every soft call, because
    `_git_soft` delegates to `_git` and both names were patched. That is not a
    tidiness point: the spawn figure this refactor was measured against was
    inflated exactly that way on the first attempt, and a budget built on it
    would have been set 40 per cent too high.
    """
    sys.path.insert(0, str(PAYLOAD))
    from extant.git import CountingGit, SubprocessGit

    repo, _ = git_repo
    counter = CountingGit(SubprocessGit())
    counter.soft(repo, "rev-parse", "HEAD")     # fails: no commits yet
    counter.soft(repo, "status", "--porcelain")
    assert counter.calls == [("rev-parse", "HEAD"), ("status", "--porcelain")], (
        f"a soft call must be recorded once, and a failing one still recorded: "
        f"{counter.calls}")


def test_finding_fields_are_frozen_and_ordered() -> None:
    """The field ORDER is load-bearing: findings are constructed positionally
    throughout, and everything after `detail` must stay optional and last
    because the baseline fingerprint keys on (path, kind, detail) and must not
    shift.

    `subject` and `repair` are both outside that key, deliberately and for the
    same reason - folding either in would invalidate every baseline already
    recorded in every project that has one. `repair` makes the point sharper
    than `subject` did: it varies with the CHECKOUT rather than the document,
    so a repository that acquires a `filter-repo` commit-map would re-report
    every `dead-sha` a baseline had forgiven. Anything added here must state
    which side of the fingerprint it is on.
    """
    import dataclasses
    sys.path.insert(0, str(PAYLOAD))
    from extant.finding import Finding, Located

    names = [f.name for f in dataclasses.fields(Finding)]
    assert names == ["line", "kind", "detail", "subject", "repair"], names
    for field in dataclasses.fields(Finding)[3:]:
        assert field.default is None, (
            f"{field.name} sits after `detail` and must default to None, or "
            f"every existing caller constructing a Finding positionally breaks")
    # The fingerprint reads `detail` and nothing after it. A field that leaked
    # into the identity would silently re-raise findings a project had agreed
    # to leave alone, which fails no test and simply stops being read.
    from extant.report import fingerprint
    plain = Finding(1, "dead-sha", "d")
    decorated = Finding(1, "dead-sha", "d", subject="abc1234", repair="hint")
    assert (fingerprint("p.md", plain.kind, plain.detail)
            == fingerprint("p.md", decorated.kind, decorated.detail))
    assert decorated.message() != plain.message(), (
        "a repair that changes no output is not being shown to anyone")
    assert [f.name for f in dataclasses.fields(Located)] == [
        "path", "finding", "primary", "gating"]
    try:
        Finding(1, "k", "d").line = 2
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Finding is no longer frozen")
