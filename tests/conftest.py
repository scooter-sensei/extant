"""Throwaway git repositories, and the import path for the payload.

`payload/` holds the files that get installed into a target repo as `tools/`.
Tests import them from that source location rather than from an installed copy,
so a failure points at the file you would actually edit.
"""
from __future__ import annotations

import atexit
import contextlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterator

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


def _abbrev(sha: str) -> str:
    """The shortest prefix of at least seven characters that the scanner
    will read as a commit.

    `looks_like_sha` refuses an all-digit token by design - a number is not
    a commit - and a real seven-character abbreviation is all digits about
    4% of the time, so a test written `real[:7]` went red on one run in
    twenty-five. Found on 2026-09-13 when a mutation was reported caught by
    test_widened_scanners.py's range test rather than by the bounds test it
    was written for; found AGAIN on 2026-09-22, when the rebase-journal test
    in test_hooks.py - `Shipped in `{cited[:7]}`` - had reddened one CI leg
    in three since PR #15 and once in forty local runs, always as `[]` where
    `dead-sha` was due: a prefix of digits alone is no candidate at all. One
    helper here, so the third copy of `[:7]` is not written.
    """
    for width in range(7, len(sha) + 1):
        prefix = sha[:width]
        if any(c.isalpha() for c in prefix) and any(c.isdigit() for c in prefix):
            return prefix
    return sha


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

    # Both halves of the configuration: the raw settings and the Config built
    # from them, which every reader - rule or mode - is handed. They used to
    # be three: twenty-one module globals derived from the same build sat
    # beside `_ACTIVE`, and restoring one without the others left this module
    # describing two projects at once. The globals are gone; what is saved
    # here is everything `reload_config` writes.
    saved_config, saved_active = hc.CONFIG, hc._ACTIVE
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
        hc.CONFIG, hc._ACTIVE = saved_config, saved_active
        hc._DOC, hc._SCOPE = saved_doc, saved_scope


@pytest.fixture(autouse=True)
def no_rule_error_left_behind():
    """Fail the test that leaves an entry in `RULE_ERRORS`, and name it.

    The run's error list is process state the other fixtures here do not
    cover, and a test that leaves an entry there turns the NEXT in-process
    run red - a different test, in whatever order the suite happened to run.
    That is how it was found: two tests in test_introduced_since.py failed
    under `-n auto` on 2026-09-27 and passed alone, because a third had left
    its deliberately raising rule's entry behind. So the test that leaves one
    fails here, at its own teardown, in every order; and only THEN is the list
    emptied, so the report lands on the cause rather than on its victims.
    Not a reset that hides a leak - the leak is the failure.
    """
    from extant.registry import RULE_ERRORS

    yield
    left = list(RULE_ERRORS)
    if left:
        # MUTATED, never rebound: the rules append to this very list.
        del RULE_ERRORS[:]
        pytest.fail(f"this test left {left!r} in RULE_ERRORS; the next "
                    f"in-process run would report it as its own. Take back "
                    f"what the run recorded - see `raising_rule`.", pytrace=False)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--order-seed", type=int, default=None, metavar="N",
        help="run the collected tests in an order shuffled by seed N "
             "(tests/test_suite_order.py says why)")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config,
                                  items: list[pytest.Item]) -> None:
    """Shuffle the whole suite when `--order-seed` is given, and only then.

    The guard above covers the ONE kind of leaked state that has been found.
    A shuffled order is how the next kind shows itself: on 2026-09-28 the
    suite passed three seeds serially on Linux and one under
    `-n auto --dist load` on Windows, every seed moving at least 1,416 of
    1,419 tests, so today's suite has no order dependency any of those four
    orders could see. One Linux CI leg runs one more in every run, with
    the seed written in the workflow so that a red run is reproduced here
    by copying its command line. Last among the collection hooks, so it shuffles whatever
    order the others produced, and seeded, so every xdist worker collects
    the same order - which xdist requires.
    """
    seed = config.getoption("order_seed")
    if seed is not None:
        random.Random(seed).shuffle(items)


# How tests/test_properties.py generates. `ci` is what every run uses unless
# told otherwise: DERANDOMIZED, so which examples a property tries is a
# function of the commit, of the Hypothesis requirements-test.txt pins, and -
# for the one property drawing from `st.characters` - of the Python version's
# Unicode tables, and of nothing else: the same rule as `--order-seed` and the
# fuzz job's fixed seed, because a red that moves between runs cannot be
# handed to whoever has to fix it. And NO DATABASE, so a run never replays
# what an earlier run on this machine happened to find: a verdict depends on
# the commit, as tests/harnesses/mutate.py requires of a kill.
#
# It is Hypothesis's OWN `ci` profile - the one Hypothesis loads by itself on
# a CI runner - with a larger budget, so it keeps that profile's suppression
# of the timing-based `too_slow` health check. The first version registered
# a `ci` of its own, which replaced Hypothesis's outright and put the check
# back on exactly the slow runners it is suppressed for (Phase 62's gap
# audit). `explore` is the other half, by hand: `ci` at random, with ten
# times the examples,
#
#     python -m pytest tests/test_properties.py --hypothesis-profile=explore
#
# and what it finds becomes an `@example` on the property, so the `ci`
# profile tries it from then on. Registered here because this conftest loads
# before Hypothesis's own plugin reads `--hypothesis-profile`, so that flag
# overrides `ci` rather than being overridden by it. Absent on 3.9, which
# requirements-test.txt does not give Hypothesis; the property module says so.
#
# Derandomizing alone did NOT make the draws a function of the commit.
# Hypothesis (6.131.1 on) mines the literal constants of every local, non-test
# module in `sys.modules` and draws one with probability 0.05 per choice, so
# the examples depended on what the process had imported before a property
# ran: under `-n auto` on which files a worker took first, under
# `--order-seed` on the order, and in mutate.py's confirm-alone run on
# running alone. Measured 2026-10-02: one derandomized property, two
# digests, with and without the payload imported first. No setting turns it
# off (HypothesisWorks/hypothesis#4627 closed without one), so the pool is
# held EMPTY here. That replaces a private function, which is one more
# reason the pin is exact, and a Hypothesis that renamed it stops this
# import rather than quietly mining again. tests/test_property_settings.py
# imports a fresh module of constants between two runs of one property and
# asserts the same draws. The price is Hypothesis no longer seeding a draw
# with a string the payload happens to spell; every property here draws
# from alphabets and pieces it chose for itself.
try:
    from hypothesis import settings as _hypothesis_settings
except ImportError:
    pass
else:
    from hypothesis.internal.conjecture import providers as _providers

    if not callable(getattr(_providers, "_get_local_constants", None)):
        raise RuntimeError(
            "hypothesis.internal.conjecture.providers._get_local_constants is "
            "gone, so tests/conftest.py cannot hold the local-constant pool "
            "empty and derandomized draws depend on import order again: find "
            "what replaced it before moving the pin in requirements-test.txt")
    _NO_LOCAL_CONSTANTS = _providers.Constants()
    _providers._get_local_constants = lambda: _NO_LOCAL_CONSTANTS
    _hypothesis_settings.register_profile(
        "ci", parent=_hypothesis_settings.get_profile("ci"), max_examples=500,
        derandomize=True, database=None, deadline=None, print_blob=True)
    _hypothesis_settings.register_profile(
        "explore", parent=_hypothesis_settings.get_profile("ci"),
        max_examples=5000, derandomize=False)
    _hypothesis_settings.load_profile("ci")


@pytest.fixture
def reconfigure(monkeypatch):
    """Change a configured value so that every reader sees it.

    Setting `session._BRANCH_TOKEN` (or any of twenty-one such module
    globals) used to be enough, because the rules read those globals. From
    Task 9 the rules are package modules that read `ctx.config`, which is the
    built `Config` on `session._ACTIVE` - so a plain attribute patch reached
    the derived globals and NOT the rule under test. The rule then matched
    nothing and the test reported no findings, which is indistinguishable
    from the rule working and the document being clean. Two tests failed
    exactly that way when their rules moved; the danger was the ones that
    would have kept passing.

    The globals are gone now and the modes read `session.config()`, the same
    object the rules are handed, so there is one place to write and this
    writes it. `monkeypatch` undoes it at teardown.

    The alternative - writing a `.extant.toml` and calling `reload_config` -
    reaches the same place and is what a test should use when the point IS
    the file. This exists for the many tests whose point is a pattern.
    """
    import dataclasses

    from extant import session as hc

    def apply(**changes: object):
        monkeypatch.setattr(hc, "_ACTIVE",
                            dataclasses.replace(hc._ACTIVE, **changes))
        return hc._ACTIVE

    return apply


@contextlib.contextmanager
def raising_rule() -> Iterator[object]:
    """The first rule replaced by one whose check raises, for as long as the
    `with` block lasts; the rule is yielded so a test can name its kind.

    Putting `RULES` back is half the undo. A rule that raised is recorded in
    `RULE_ERRORS`, the RUN's list, which `main()` clears at the start of a run
    and which a mode function called directly - as these tests call them -
    never passes through. A monkeypatch cannot know a run appended to a list,
    so the entries the broken rule caused stayed, and the next gate run in the
    same process exited 1 naming a rule nothing had broken: two tests in
    test_introduced_since.py, whenever the suite ran this one first, which
    serial file order never does and `-n auto` did on 2026-09-27. So this
    takes back exactly what was recorded while it was installed - by mark,
    the way test_rule_contract.py does - and nothing recorded before it.
    """
    import dataclasses

    from extant import session as hc
    from extant.registry import RULE_ERRORS

    def explode(ctx: object, text: str) -> list[object]:
        raise RuntimeError("deliberate")

    broken = dataclasses.replace(hc.RULES[0], check=explode)
    mark = len(RULE_ERRORS)
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(hc, "RULES", (broken,) + hc.RULES[1:])
            yield broken
    finally:
        # MUTATED, never rebound: the rules append to this very list.
        del RULE_ERRORS[mark:]


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
        return _head_sha(repo)

    return commit


_FULL_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def _head_sha(repo: Path) -> str:
    """HEAD's commit, read from the files git has just written where that is
    unambiguous, and asked of git everywhere else.

    `commit` asked `git rev-parse HEAD` after every commit: 1,394 spawns in a
    run of the suite, 29.5 ms each on the development machine against 0.23 ms
    to read the loose ref the commit had just written (measured 2026-09-28).
    So the plain layouts are read - `HEAD` naming a loose ref, or holding the
    commit itself when detached - and anything else is refused rather than
    guessed at: packed refs, a linked worktree whose `.git` is a file, a
    reftable repository, a symbolic ref pointing at another. Each of those
    falls back to git, which is what tests/test_fixture_templates.py pins,
    shape by shape.
    """
    git_dir = repo / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        sha = ((git_dir / head[len("ref: "):]).read_text(encoding="ascii").strip()
               if head.startswith("ref: ") else head)
    except (OSError, UnicodeDecodeError):
        sha = ""
    if _FULL_SHA.fullmatch(sha):
        return sha
    return _run(repo, "rev-parse", "HEAD").strip()


def described(repo: Path) -> dict[str, str]:
    """Everything about a repository that any rule here can ask git.

    Here rather than in tests/test_fixture_templates.py, which wrote it, so
    a file that builds a template of its own compares its copies by the same
    properties rather than by a second list that could drift from this one.
    """
    def git(*args: str) -> str:
        return _run(repo, *args).strip()

    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "refs": git("for-each-ref",
                    "--format=%(refname)\t%(objectname)\t%(objecttype)"),
        # Trees and subjects, not parents: two commits made a moment apart are
        # different objects, so their ids and therefore their children's parent
        # ids differ between any two builds - copied or not. What a rule reads
        # is the CONTENT and the shape, so those are what is compared, with the
        # shape reduced to how many parents each commit has.
        "log": git("log", "--all", "--format=%T %s"),
        "graph": " ".join(
            str(len(line.split()))
            for line in git("log", "--all", "--format=%P").splitlines()),
        "tree": git("ls-tree", "-r", "HEAD", "--name-only"),
        "status": git("status", "--porcelain"),
    }


@pytest.fixture(scope="session")
def empty_repo_template(tmp_path_factory) -> Path:
    """The three git spawns every `git_repo` used to pay, paid once.

    THREE, matching `init_repo` and the measurement above it. This read "five"
    while the comment 59 lines up said three and the function makes exactly
    three calls - a count contradicted by its own file, which is the class of
    claim no rule here can check and the reason the measurement is written out
    rather than summarised.
    """
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
