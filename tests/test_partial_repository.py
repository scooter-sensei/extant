"""A partial repository: objects the transport left out, and the promise that
nothing here goes back for them.

`git clone --filter=blob:none` keeps every commit and tree and only the blobs
the checkout needs. Any command that then wants another blob asks the promisor
remote for it, mid-command, over the network - and the README says nothing
here touches the network. It was not a hypothetical: sweeping one such
repository stalled for half an hour while rename detection went blob by blob
to the server, and `--sweep` reported FEWER findings each time as the object
store warmed (Phase 25 in the status document).

Verified by hand before these tests existed, on git 2.53: in a `blob:none`
copy holding one rename with an edit, `git log --diff-filter=R --name-status`
retrieved the old blob and printed `R063`; under `GIT_NO_LAZY_FETCH=1` the same
command exited 128 with "could not fetch ... from promisor remote" and the
blob stayed missing. So the guard costs the rename hint for that case, and
the note beside the denominators is what says so.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import committer, init_repo  # noqa: E402

DOC = ("## Phase 1 - x (in progress, 2026-01-01)\n\n"
       "**Design:** `docs/old.md`\n")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def git_version() -> tuple[int, ...]:
    words = git(Path.cwd(), "--version").split()[2]
    return tuple(int(part) for part in words.split(".")[:2] if part.isdigit())


def missing_objects(repo: Path) -> set[str]:
    """What the object store does not hold, asked in the one way that does
    not go and get it."""
    out = git(repo, "rev-list", "--objects", "--missing=print", "--all")
    return {line[1:] for line in out.splitlines() if line.startswith("?")}


@pytest.fixture
def partial_repo(tmp_path: Path) -> Path:
    """A `blob:none` copy of a repository holding a rename WITH an edit.

    The edit is what makes the fixture bite: an exact rename is matched by
    object id and needs no blob, so a `git mv` alone would never ask the
    transport for anything and the test below would pass without the guard.
    """
    source = tmp_path / "source"
    init_repo(source)
    commit = committer(source)
    commit("docs/old.md", "# Guide\n\nSome words about the thing.\nMore.\n",
           "docs: add")
    git(source, "mv", "docs/old.md", "docs/new.md")
    commit("docs/new.md",
           "# Guide\n\nSome words about the thing.\nMore, revised.\n",
           "docs: rename")
    commit("NEXT_SESSION.md", DOC, "docs: status")
    # The filter is honoured over the local transport only when the SOURCE
    # allows it; without this git says "filtering not recognized by server"
    # and hands back a full copy, which is a fixture that proves nothing.
    git(source, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    subprocess.run(["git", "clone", "-q", "--filter=blob:none",
                    "file://" + source.as_posix(), str(partial)],
                   check=True, capture_output=True)
    git(partial, "config", "user.email", "test@example.com")
    git(partial, "config", "user.name", "Test")
    assert missing_objects(partial), "the copy is not partial; nothing is missing"
    return partial


def test_a_partial_repository_is_recognised_from_its_config(
        partial_repo, git_repo) -> None:
    """`remote.<name>.promisor = true` is what git itself checks."""
    from extant.git import is_partial

    assert is_partial(partial_repo) is True
    repo, _commit = git_repo
    assert is_partial(repo) is False


def test_verify_says_the_repository_is_partial(partial_repo, capsys) -> None:
    """Beside the denominators, where the shallow note goes, and for the same
    reason: a reader cannot tell from the count alone that some answers were
    given about less than the repository holds."""
    from extant import cli

    cli.main(["--verify", "--repo", str(partial_repo)])
    out = capsys.readouterr().out
    print(out)
    notes = [line for line in out.splitlines()
             if "NOTE:" in line and "partial" in line]
    assert len(notes) == 1, out


def test_verify_never_goes_back_for_an_object_the_transport_left_out(
        partial_repo, capsys) -> None:
    """The guarantee, measured: the set of missing objects before a run is
    the set after it. The document points at the OLD name of a renamed file,
    which is exactly the question - "where did this go?" - that made git
    retrieve the old blob to answer.

    Skipped, with the version printed, below git 2.42: `GIT_NO_LAZY_FETCH` is
    ignored there, the blob IS retrieved, and the note is what remains.
    """
    from extant import cli

    version = git_version()
    if version < (2, 42):
        pytest.skip(f"git {version} ignores GIT_NO_LAZY_FETCH; needs 2.42")

    before = missing_objects(partial_repo)
    code = cli.main(["--verify", "--repo", str(partial_repo)])
    out = capsys.readouterr().out
    after = missing_objects(partial_repo)
    print(f"exit {code}; missing before {sorted(before)}, after {sorted(after)}")
    assert "dead-path-pointer" in out, out
    assert after == before, (
        f"{len(before - after)} object(s) were retrieved over the transport "
        f"during --verify: {sorted(before - after)}")


def test_deleted_since_counts_a_missing_previous_version_as_unreadable(
        partial_repo, tmp_path) -> None:
    """The guard's one new way to be wrong, closed.

    `--deleted-since` reads each configured document as it stood at the ref
    with `git show`, and None from that read meant "absent then". In a
    partial repository the old version's blob is exactly what the transport
    left out, so with retrieval refused the read fails - and "absent" would
    silently hide the deleted false claim that mode exists to report. Found
    by the audit of this change, on this fixture: examined 0, unreadable 0.
    "Could not be read" is the bucket it belongs in, and the mode already
    has one.
    """
    from extant import session as hc
    from extant import deleted_since

    old = ("## Phase 1 - x (in progress, 2026-01-01)\n\n"
           "Merged at `" + "dead" + "0" * 36 + "`.\n")
    # Two versions of the status document, so the earlier one's blob is a
    # historical object the copy does not hold.
    source = tmp_path / "source"
    commit = committer(source)
    commit("NEXT_SESSION.md", old, "docs: claim")
    commit("NEXT_SESSION.md", "## Phase 1 - x (in progress, 2026-01-01)\n\n"
                              "Nothing.\n", "docs: remove")
    git(partial_repo, "pull", "-q", "--ff-only")
    assert git(partial_repo, "log", "-1", "--format=%s").strip() == "docs: remove"
    hc.reload_config(partial_repo)

    gone, examined, _skipped, unreadable = deleted_since.deleted_claims(partial_repo,
                                                                 "HEAD~1")
    print(f"examined={examined} unreadable={unreadable} gone={len(gone)}")
    assert (examined, unreadable) == (0, 1), (
        f"the old version's blob is not local; examined {examined}, "
        f"unreadable {unreadable} - a missing object was read as an absent "
        f"document")


def test_the_older_spelling_of_the_filter_is_recognised_too(git_repo) -> None:
    """Before `promisor = true`, a filtered copy recorded itself as
    `extensions.partialclone = origin` with `core.partialclonefilter`. The
    prefix arm is what reads those, and the modern fixture above never
    reaches it because `promisor` answers first."""
    from extant.git import common_git_dir, is_partial

    repo, _commit = git_repo
    shared = common_git_dir(repo)
    assert shared is not None
    config = shared / "config"
    config.write_text(config.read_text(encoding="utf-8")
                      + "[extensions]\n\tpartialclone = origin\n",
                      encoding="utf-8")
    assert is_partial(repo) is True
