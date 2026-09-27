"""Reading a file of the checkout without leaving it.

A name the repository gives is not a promise about where its bytes live. git
stores a symbolic link as a blob holding the target's path, and a Linux
checkout - every CI runner - makes it a real link, so opening a tracked
`notes.md` can read `../.git/config`, where actions/checkout persists the
job's credential, or `/dev/zero`, which never ends. And a name need not be a
link at all to leave: `.extant.toml` is read from the repository too, and a
consistency source spelled `/etc/hostname` or `../x` was joined onto the root
and read. Every name this tool opens comes from the repository - the tracked
list, a pull request's diff, a link, a `path:line` pointer, the
configuration - and on a pull request from a fork the repository is somebody
else's. The consistency rule then PRINTS what its pattern captured, so a
configured source was a way to copy any readable file into a CI log.

So a file is read only when its RESOLVED location is a regular file inside the
resolved checkout and outside `.git`. A link that stays inside - `CLAUDE.md ->
AGENTS.md`, the common case, and moby's own - is followed exactly as before.
A name that resolves nowhere is returned untouched, so `open` raises the
FileNotFoundError every caller already reports.

Found by the review of pull request #16 on 2026-09-27. Measured nowhere on the
corpus, and it could not have been: this machine checks symlinks out as plain
files (`core.symlinks` is false), which is also why the tests of it skip here
and run on Linux.

PURE, and imports nothing from the package, so any module may read through
it without joining a cycle.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["OutsideRepository", "inside", "refusal"]


class OutsideRepository(OSError):
    """A name whose resolved location is outside the checkout, inside `.git`,
    or not a regular file.

    An OSError, so every reader that already counts a file it could not read
    counts this one the same way, by class name, rather than growing a second
    except clause for one of them to forget.
    """


def inside(repo: Path, path: Path) -> Path:
    """`path` itself, once it is known to be safe to open for `repo`.

    Raises `OutsideRepository` when it resolves outside the checkout, into its
    git directory, or to something that is not a regular file - a device, a
    FIFO, a directory - and when resolving it loops. Returns `path` unchanged
    rather than the resolved form, so what a caller prints is the name the
    repository used.
    """
    try:
        root = repo.resolve()
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        # A link loop: RuntimeError before Python 3.13, OSError from it on.
        raise OutsideRepository(f"{path}: {exc.__class__.__name__}") from exc
    if not resolved.exists():
        return path
    if resolved != root and root not in resolved.parents:
        raise OutsideRepository(f"{path} leads outside the repository")
    if ".git" in resolved.relative_to(root).parts:
        raise OutsideRepository(f"{path} leads into the git directory")
    if not resolved.is_file():
        raise OutsideRepository(f"{path} is not a regular file")
    return path


def refusal(repo: Path, path: Path) -> str | None:
    """Why `inside` would refuse `path`, or None when it would not - for a
    caller that reports the refusal as a finding rather than as unreadable."""
    try:
        inside(repo, path)
    except OutsideRepository as exc:
        return str(exc)
    return None
