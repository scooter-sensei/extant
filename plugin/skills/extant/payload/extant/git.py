"""Running git, and nothing else.

No caching lives here. Memoised answers belong to a RunScope, which is what
gives them a lifetime; a cache in this module would have the lifetime of the
process and no way to say so.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Transitional, and deliberately naming underscore names. `_git` and
# `_git_soft` ARE this module's surface today: the shim re-exports them by
# name, and six test sites wrap them to count calls. Task 7 introduces the
# `Git` interface with `run` and `soft`, and this becomes ["Git", "SubprocessGit"].
#
# Declaring ["run", "soft"] here instead would name two things that do not
# exist for five more tasks, which is a false surface rather than a forward
# -looking one.
__all__ = ["_git", "_git_soft"]


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


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, returning stdout. Raises on non-zero."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout
