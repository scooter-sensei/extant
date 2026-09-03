"""Git output that is not valid UTF-8, and the two ways that used to break.

Everything here is about ONE seam: where bytes git wrote become a `str` this
package can read. It was left to `text=True`, which decodes inside
`subprocess` - and inside `subprocess` is not one place. On Windows a reader
thread does it, so a byte that will not decode kills that thread and
`communicate()` returns None, and `_git` hands None to callers annotated
`str`. On POSIX the same byte raises UnicodeDecodeError out of
`Popen._communicate`, which `_git_soft` does not list. A silent wrong answer
on one platform and a crash on the other, out of the same line.

The silent half is why these are tests rather than a note. A rule handed None
finds nothing, and finding nothing prints exactly what a clean document
prints - the conflation every denominator in this project exists to refuse.

Not a hypothetical input. Any repository carrying pre-UTF-8 history - a
latin-1 or Shift-JIS commit subject written before an `encoding` header was
routine - emits these bytes from `git log`, and sweeping other people's
repositories is the job.

`extant/sweep.py`'s `_document_at` had already diagnosed exactly this and
worked around it locally. What it could not do from where it sits is fix the
module every rule asks its questions through.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import PAYLOAD

sys.path.insert(0, str(PAYLOAD))

LF = bytes([10])
# A lone latin-1 byte is not valid UTF-8. U+FFFD is what replacing it yields.
LATIN1_SUBJECT = b"caf" + bytes([0xE9]) + b" pre-utf8 subject"
REPLACEMENT = chr(0xFFFD)


@pytest.fixture
def legacy_repo(tmp_path: Path) -> Path:
    """A repository whose HEAD subject holds bytes git will not re-encode.

    Built with `hash-object --literally` rather than `git commit`, and that is
    forced rather than fussy: `git commit -F` transcodes its input from the
    locale encoding, so on a machine where that is cp1252 the bytes land as
    valid UTF-8 and the test proves nothing. Writing the object verbatim is
    the only portable way to put the byte in the repository that a real
    pre-UTF-8 history already contains.
    """
    repo = tmp_path / "legacy"
    repo.mkdir()

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=repo, check=True,
                              capture_output=True)

    run("init", "-q", "-b", "main")
    (repo / "README.md").write_text("x", encoding="utf-8")
    run("add", "README.md")
    tree = run("write-tree").stdout.decode().strip()
    raw = LF.join([
        b"tree " + tree.encode(),
        b"author T <t@example.com> 1700000000 +0000",
        b"committer T <t@example.com> 1700000000 +0000",
        b"",
        LATIN1_SUBJECT,
        b"",
    ])
    sha = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin", "--literally"],
        cwd=repo, input=raw, check=True,
        capture_output=True).stdout.decode().strip()
    run("update-ref", "refs/heads/main", sha)
    run("symbolic-ref", "HEAD", "refs/heads/main")

    # The fixture is worthless if this platform quietly repaired the bytes, so
    # it asserts its own premise before any test is allowed to read it.
    emitted = subprocess.run(["git", "log", "--format=%s"], cwd=repo,
                             capture_output=True).stdout
    with pytest.raises(UnicodeDecodeError):
        emitted.decode("utf-8")
    return repo


def test_git_run_returns_a_string_rather_than_none(legacy_repo: Path) -> None:
    """The Windows half. `_git` is annotated `-> str` and must honour it.

    Asserting `is not None` before anything else is deliberate. Every caller in
    the package goes straight on to a string method, so None never surfaces
    here as a decoding problem - it surfaces three modules away as an
    AttributeError attributed to whichever rule happened to ask.
    """
    from extant.git import SubprocessGit

    out = SubprocessGit().run(legacy_repo, "log", "--format=%s")

    assert out is not None
    assert isinstance(out, str)
    assert REPLACEMENT in out


def test_git_soft_stays_soft_on_bytes_it_cannot_decode(
        legacy_repo: Path) -> None:
    """The POSIX half. `soft` promises "" rather than an exception on failure.

    It caught CalledProcessError and OSError. UnicodeDecodeError is neither, so
    the tolerant path tolerated everything except the one failure its caller
    could do nothing about.
    """
    from extant.git import SubprocessGit

    out = SubprocessGit().soft(legacy_repo, "log", "--format=%s")

    assert isinstance(out, str)
    assert REPLACEMENT in out


def test_the_subject_survives_apart_from_the_undecodable_byte(
        legacy_repo: Path) -> None:
    """Replacement, not truncation, and not the whole value discarded.

    A decode that dropped the rest of the line would turn one bad byte into a
    lost commit subject, which is the same silence by a slower route.
    """
    from extant.git import SubprocessGit

    out = SubprocessGit().run(legacy_repo, "log", "--format=%s")

    assert out.startswith("caf")
    assert "pre-utf8 subject" in out


@pytest.fixture
def repo_with_undecodable_path(tmp_path: Path) -> Path:
    """A repository tracking a document whose PATH is not valid UTF-8.

    Committed through `mktree`, which reads the path as bytes on stdin, so the
    file never has to exist in a working tree - which is what makes this
    runnable on Windows, where the filesystem could not hold the name. On the
    platforms where sweeps actually run a path is an arbitrary byte string and
    this repository is nothing unusual.

    `ls-tree -z` is the sharp part. `-z` turns OFF the `core.quotePath` escaping
    that would otherwise render these bytes as ASCII, so the raw bytes reach
    the caller on every platform and under every configuration.
    """
    repo = tmp_path / "oddly-named"
    repo.mkdir()

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=repo, check=True,
                              capture_output=True)

    run("init", "-q", "-b", "main")
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo,
                          input=b"# a document", check=True,
                          capture_output=True).stdout.decode().strip()
    entry = (b"100644 blob " + blob.encode() + bytes([9])
             + b"caf" + bytes([0xE9]) + b".md" + LF)
    tree = subprocess.run(["git", "mktree"], cwd=repo, input=entry, check=True,
                          capture_output=True).stdout.decode().strip()
    commit = subprocess.run(
        ["git", "commit-tree", tree, "-m", "add a document"], cwd=repo,
        check=True, capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "T",
             "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T",
             "GIT_COMMITTER_EMAIL": "t@example.com"}).stdout.decode().strip()
    run("update-ref", "refs/heads/main", commit)
    run("symbolic-ref", "HEAD", "refs/heads/main")
    return repo


def test_one_oddly_named_file_does_not_take_the_whole_listing_down(
        repo_with_undecodable_path: Path) -> None:
    """`tracked_markdown` is what decides which documents get swept at all.

    Its own docstring calls a listing that comes back short "the worst shape
    available - a silent all-clear on a repository nobody checked", and says
    the `ls-tree` behind it must RAISE rather than return [] for exactly that
    reason. `text=True` broke both halves of that intent at once: on Windows
    the listing came back None and died on `.split` as whichever rule asked
    having erred, and on POSIX it raised a UnicodeDecodeError naming a codec
    rather than a repository.

    Either way one file with an unusual name cost the listing of EVERY file
    beside it. Decoding here instead keeps the other documents in the sweep
    and spells the odd one with a replacement character.
    """
    from extant import refs, session

    files = refs.tracked_markdown(session.context(repo_with_undecodable_path))

    assert files == ["caf" + REPLACEMENT + ".md"]


def test_a_validate_over_such_a_repository_still_reports_denominators(
        legacy_repo: Path) -> None:
    """End to end, because the seam is only interesting through a rule.

    The denominator is the assertion that matters: every rule still states how
    many candidates it looked at, and no rule is sitting in RULE_ERRORS having
    failed on a repository that is merely old.
    """
    from extant import registry, session

    del registry.RULE_ERRORS[:]
    text = "Merged to `main`. See `README.md`."

    findings = session.validate(legacy_repo, text, has_entries=False)
    counts = registry.count_examined(session.context(legacy_repo), text)

    assert not registry.RULE_ERRORS, registry.RULE_ERRORS
    assert isinstance(findings, list)
    assert set(counts) == {rule.kind for rule in registry.RULES}
