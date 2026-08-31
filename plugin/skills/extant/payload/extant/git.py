"""Running git, and nothing else.

No caching lives here. Memoised answers belong to a RunScope, which is what
gives them a lifetime; a cache in this module would have the lifetime of the
process and no way to say so.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The surface Task 2 said this would become. `_git` and `_git_soft` were
# declared here transitionally, because the shim re-exported them by name and
# five test sites wrapped them to count calls; both are back to being private
# implementation, called by SubprocessGit and named nowhere outside this file.
__all__ = ["Git", "SubprocessGit", "CountingGit", "common_git_dir",
           "is_shallow", "rewrite_map_path"]


class Git:
    """The subcommands the validator asks for, behind one replaceable object.

    Both behaviours are modelled deliberately. `run` raises where `soft`
    returns empty, and an implementation that collapses them turns every error
    path into a success path, which is silent by construction. The two
    docstrings below say which is which; the reasoning for the distinction is
    on `_git_soft`, which is where it was written when the distinction was
    made.
    """

    def run(self, repo: Path, *args: str) -> str:
        """Run git in `repo` and return stdout. Raises when git fails."""
        raise NotImplementedError

    def soft(self, repo: Path, *args: str) -> str:
        """Run git in `repo`, returning "" rather than raising when it fails."""
        raise NotImplementedError


class SubprocessGit(Git):
    """The real one: a `git` process per call."""

    def run(self, repo: Path, *args: str) -> str:
        return _git(repo, *args)

    def soft(self, repo: Path, *args: str) -> str:
        return _git_soft(repo, *args)


class CountingGit(Git):
    """A Git that records every command, for budgets and profiles.

    Delegating rather than subclassing SubprocessGit so that a fake can be
    counted the same way.

    ONE entry per call, including a soft one, and that is the difference from
    the wrapper-counting it replaces. `_git_soft` delegates to `_git`, so a
    test that wrapped both names by hand saw two entries for one soft call -
    and the spawn figure this seam was built to defend was measured that way,
    wrongly, the first time. Here the delegation happens inside SubprocessGit,
    BELOW the interface, so it cannot be seen twice.

    Not a spawn count, and must not be read as one. Six git invocations across
    this package do not fit `run(repo, *args)` - three `cat-file` batches fed
    on stdin (two in extant/rules/lfs.py, one in extant/refs.py's
    `_batch_shas`), a `-z` listing paired with `check-attr --stdin` (both in
    extant/rules/lfs.py), and a `git show` that must return bytes
    (extant/sweep.py's `_document_at`) - so they call subprocess directly and
    are invisible here. tests/test_spawn_budget.py counts at the subprocess
    boundary for exactly that reason, and tests/test_scope.py prints both
    populations so the gap is a number somebody chose rather than one nobody
    noticed.
    """

    def __init__(self, inner: Git) -> None:
        self.inner = inner
        self.calls: list[tuple[str, ...]] = []

    def run(self, repo: Path, *args: str) -> str:
        self.calls.append(args)
        return self.inner.run(repo, *args)

    def soft(self, repo: Path, *args: str) -> str:
        self.calls.append(args)
        return self.inner.soft(repo, *args)


def _git_soft(repo: Path, *args: str) -> str:
    """Run git, returning "" instead of raising when the command fails.

    For FACT GATHERING, where the absence of an answer is itself a legitimate
    answer. A repository with no commits has no HEAD, no trunk ref and no
    branches, so `git log`, `git rev-parse HEAD` and `git branch --merged main`
    all exit 128 - not because anything is wrong, but because someone has just
    run `git init`.

    Deliberately NOT used by the validation rules. There, a git command that
    fails means a claim could not be checked, and silently treating that as
    "no finding" is the exact shape of failure this project exists to prevent.
    """
    try:
        return _git(repo, *args)
    except (subprocess.CalledProcessError, OSError):
        return ""


def is_shallow(repo: Path) -> bool:
    """True when this checkout is depth-limited.

    It matters because `dead-sha` asks whether a commit is REACHABLE, and a
    shallow clone answers that question about the slice it was given rather
    than about the repository. A SHA that is perfectly alive upstream reads as
    dead here, and the run reports it with the same confidence as a real one.
    Nothing about this can be fixed without the missing history, so the only
    honest thing available is to say which kind of answer the reader is
    holding - the same reason every mode prints its denominator.

    Read from the marker file rather than by shelling out, because it is one
    stat, and because a `git rev-parse --is-shallow-repository` that fails
    would have to be interpreted, and the interpretation of a failure here is
    exactly the ambiguity this is trying to remove.
    """
    if (repo / ".git" / "shallow").is_file():
        return True
    shared = common_git_dir(repo)
    if shared is None or shared == repo / ".git":
        return False
    return (shared / "shallow").is_file()


def common_git_dir(repo: Path) -> Path | None:
    """The SHARED git directory - `.git` of the original clone - or None.

    Everything git keeps once per REPOSITORY rather than once per checkout
    lives here: the object store, `shallow`, and the commit-map a
    `git filter-repo` run leaves behind. A linked worktree has a git directory
    of its own beside those, and looking in that one instead finds none of
    them.

    Read from the filesystem rather than by shelling out to
    `rev-parse --git-common-dir`, for the two reasons `is_shallow` gives: it is
    a stat, and the interpretation of a failed `rev-parse` is exactly the
    ambiguity this is trying to remove. It also has to stay a stat because the
    spawn budget in tests/test_spawn_budget.py has no spare margin, and a
    question asked once per run is still a question.

    The three shapes, each of which git writes differently:

    * A plain checkout keeps a `.git` DIRECTORY, and it is the shared one.
    * A LINKED WORKTREE keeps a `.git` FILE naming a directory under
      `.git/worktrees/<name>/`, which carries `commondir` pointing back at the
      original. This is the case that was got wrong once: `shallow` lives in
      the shared directory, so checking only the worktree's own returned False
      for every worktree of a shallow clone while git said true.
    * A SUBMODULE keeps a `.git` FILE too, naming a directory that IS its
      shared one - no `commondir` beside it - so the pointer is the answer.

    None means the question could not be settled: no `.git` at all, a pointer
    that does not parse, or one naming a directory that is not there. Callers
    report that rather than treating it as an absence, because "this
    repository was never rewritten" and "this repository could not be read"
    are the two answers this project exists to keep apart.
    """
    pointer = repo / ".git"
    if pointer.is_dir():
        return pointer
    if not pointer.is_file():
        return None
    try:
        content = pointer.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not content.startswith("gitdir:"):
        return None
    gitdir = Path(content.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = repo / gitdir
    common = gitdir / "commondir"
    if not common.is_file():
        return _normal(gitdir)
    try:
        shared = Path(common.read_text(encoding="utf-8").strip())
    except (OSError, UnicodeDecodeError):
        return None
    return _normal(shared if shared.is_absolute() else gitdir / shared)


def _normal(path: Path) -> Path:
    """Fold away the `..` git writes, so two spellings of one directory compare.

    `commondir` holds `../..` relative to `.git/worktrees/<name>`, so joining
    it yields `.../worktrees/<name>/../..` - the right directory under a name
    that is equal to nothing, which matters because callers compare this
    against `repo / ".git"` and key caches on it.

    Lexical rather than `resolve()`: it touches no filesystem, so a question
    asked once per run stays a question and not a walk, and it cannot turn a
    path the caller gave into a different one by following a symlink.
    """
    return Path(os.path.normpath(path))


def rewrite_map_path(repo: Path) -> Path | None:
    """The commit-map `git filter-repo` leaves behind, or None if there is none.

    Measured 2026-08-30 on a real agent-written project: 12 of its 12 dead SHA
    references resolve through this file, and none of them resolves through
    `rev-list --all`, an unreachable-object scan or any reflog. A rewrite
    replaces every commit id at once, so it is a single event that kills a
    document's whole population of commit references - and it records exactly
    what each one became, at a fixed path, in the repository being checked.

    `--sha-map` has been able to REPAIR that since the flag existed. What was
    missing is that nobody looked: the operator had to know the flag existed
    and hand it this path.

    Finding the file does not repair anything. `--sha-map` stays the explicit
    opt-in for rewriting a document, because a validation run that edited
    prose on its own is the authoring this tool refuses.
    """
    shared = common_git_dir(repo)
    if shared is None:
        return None
    candidate = shared / "filter-repo" / "commit-map"
    return candidate if candidate.is_file() else None


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, returning stdout. Raises on non-zero."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout
