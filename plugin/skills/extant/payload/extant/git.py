"""Running git, and nothing else.

No caching lives here. Memoised answers belong to a RunScope, which is what
gives them a lifetime; a cache in this module would have the lifetime of the
process and no way to say so.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# The surface Task 2 said this would become. `_git` and `_git_soft` were
# declared here transitionally, because the shim re-exported them by name and
# five test sites wrapped them to count calls; both are back to being private
# implementation, called by SubprocessGit and named nowhere outside this file.
__all__ = ["Git", "SubprocessGit", "CountingGit", "is_shallow"]


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
    # A worktree or a submodule keeps `.git` as a FILE pointing elsewhere, and
    # the marker lives at the real git directory rather than beside the file.
    pointer = repo / ".git"
    if pointer.is_file():
        try:
            content = pointer.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return False
        if content.startswith("gitdir:"):
            gitdir = Path(content.split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = repo / gitdir
            if (gitdir / "shallow").is_file():
                return True
            # A LINKED WORKTREE has a git dir of its own but shares the object
            # store, and `shallow` lives in the shared one - `.git/shallow` of
            # the original clone, not `.git/worktrees/<name>/shallow`. Checking
            # only the former returned False for every worktree of a shallow
            # clone while git itself said true, which is the silent wrong
            # answer this function exists to prevent. `commondir` is how git
            # records where the shared directory is.
            common = gitdir / "commondir"
            if common.is_file():
                try:
                    shared = Path(common.read_text(encoding="utf-8").strip())
                except (OSError, UnicodeDecodeError):
                    return False
                if not shared.is_absolute():
                    shared = gitdir / shared
                return (shared / "shallow").is_file()
    return False


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, returning stdout. Raises on non-zero."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout
