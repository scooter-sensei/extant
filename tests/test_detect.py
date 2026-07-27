"""Tests for the repository-inspection half of the installer.

This module existed untested, and it shipped a crash because of it. Its document
reader called `Path.read_text(newline="")`, an argument that pathlib did not
accept until Python 3.13, so `install.py` raised TypeError on 3.11 and 3.12: the
oldest versions the project claims to support. CI ran the suite on both and went
green on this file, because nothing here called into it.
"""
from __future__ import annotations

from pathlib import Path

from detect import detect_trunk, find_documents, inspect_document

DOC = (
    "# Status\r\n"
    "\r\n"
    "## Release 4 - checkout (shipped, 2026-07-22)\r\n"
    "\r\n"
    "Merged to `main` at `abc1234`.\r\n"
    "\r\n"
    "## Release 3 - search (shipped, 2026-06-01)\r\n"
    "\r\n"
    "Shipped into `main` at `def5678`.\r\n"
    "\r\n"
    "## Notes\r\n"
    "\r\n"
    "Not an entry.\r\n"
)


def write(path: Path, text: str) -> Path:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def test_inspect_document_reads_a_file_with_crlf_endings(tmp_path: Path) -> None:
    """The regression test. Calling this at all is most of the point.

    Any assertion would do, because the defect was a TypeError raised on the
    first line of the function. It is written against CRLF content because that
    is why the newline argument was there: on a Windows checkout the file really
    does contain carriage returns, and the reader must not translate them away.
    """
    doc = write(tmp_path / "STATUS.md", DOC)

    info = inspect_document(doc)

    assert info["path"] == doc
    assert info["lines"] == 13


def test_inspect_document_finds_the_entry_header(tmp_path: Path) -> None:
    """Catches a scorer that ranks a reference section above a real entry.

    "## Notes" repeats too, so repetition alone picks the wrong header. Entries
    are the ones carrying a date or version, and must score above it.
    """
    info = inspect_document(write(tmp_path / "STATUS.md", DOC))

    scores = dict(info["header_scores"])  # type: ignore[arg-type]
    assert scores["## Release"] > scores.get("## Notes", 0)


def test_inspect_document_reports_the_merge_phrasing_it_saw(tmp_path: Path) -> None:
    """Catches a detector that reports a merge count without reading the verbs.

    The installer builds the merge_claim pattern out of these, so inventing them
    produces a rule matching nothing, which is the failure this project is most
    concerned with.
    """
    info = inspect_document(write(tmp_path / "STATUS.md", DOC))

    assert info["merge_count"] == 2
    assert sorted(info["merge_verbs"]) == ["merged", "shipped"]  # type: ignore[arg-type]


def test_find_documents_returns_every_candidate(tmp_path: Path) -> None:
    """Catches a finder that silently picks one when several exist.

    Choosing quietly is how the tool ends up validating the wrong file, so all
    candidates come back and the installer reports the ambiguity.
    """
    write(tmp_path / "STATUS.md", "# a\n")
    (tmp_path / "docs").mkdir()
    write(tmp_path / "docs" / "HANDOFF.md", "# b\n")

    found = [p.name for p in find_documents(tmp_path)]

    assert sorted(found) == ["HANDOFF.md", "STATUS.md"]


def test_detect_trunk_prefers_origin_head(git_repo) -> None:
    """The authoritative source, and the branch of this function nothing tested.

    `origin/HEAD` is what the remote itself says its default branch is, which
    beats guessing from local branch names. Found by mutation: ignoring it
    entirely left the suite green, because every other trunk test happened to
    exercise the local-branch fallback, where the answer is the same by
    coincidence rather than by the code being right.
    """
    import subprocess
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    # A remote-tracking ref, without needing a real remote to talk to.
    subprocess.run(["git", "update-ref", "refs/remotes/origin/trunk", "HEAD"],
                   cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "symbolic-ref", "refs/remotes/origin/HEAD",
                    "refs/remotes/origin/trunk"],
                   cwd=repo, check=True, capture_output=True)

    observation = detect_trunk(repo)

    assert observation.value == "trunk", (
        "origin/HEAD names 'trunk'; falling back to the local 'main' means the "
        "remote's own answer was ignored"
    )
    assert "origin/HEAD" in observation.evidence


def test_detect_trunk_reads_git_rather_than_prose(git_repo) -> None:
    """Catches a trunk guessed from the document instead of asked of git.

    An earlier version inferred it from phrases, which quietly produced "main"
    for any repository whose document happened not to mention a merge.
    """
    repo, commit = git_repo
    commit("README.md", "# repo\n", "init")

    observation = detect_trunk(repo)

    assert observation.value == "main"
    assert observation.evidence


# --- release-tag shape -------------------------------------------------------
#
# The default pattern recognises `v1.2.3` and `1.2.3`, which is what the corpus
# it was built against used. A project tagging `release-1.2.3` or `api@2.0.0`
# got a pattern matching NOTHING: the rule examined zero candidates and never
# checked a release claim, while the run looked perfectly healthy. Found by a
# scenario, not by reasoning about tag conventions.

import re
import subprocess

from detect import detect_release_tag


def _tagged(tmp_path: Path, *tags: str) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    for cmd in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                ["config", "user.name", "T"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True, check=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=repo, capture_output=True, check=True)
    for tag in tags:
        subprocess.run(["git", "tag", "-a", tag, "-m", "r"], cwd=repo,
                       capture_output=True, check=True)
    return repo


def _captures(observation, prose: str) -> str | None:
    match = re.search(str(observation.value), prose, re.I)
    return match.group(1) if match else None


def test_release_prefixed_tags_are_matched(tmp_path) -> None:
    """`release-1.2.3`, common in the JVM and .NET worlds.

    A wrong implementation that keeps the default pattern captures nothing here
    and the rule silently checks no release claim at all.
    """
    obs = detect_release_tag(_tagged(tmp_path, "release-1.2.3"))

    assert _captures(obs, "shipped in `release-1.2.3`") == "release-1.2.3"
    assert obs.confidence == "derived"


def test_monorepo_package_tags_are_matched(tmp_path) -> None:
    """`api@2.0.0`, how a monorepo tags one package's release."""
    obs = detect_release_tag(_tagged(tmp_path, "api@2.0.0", "web@1.0.0"))

    assert _captures(obs, "shipped as `api@2.0.0`") == "api@2.0.0"


def test_a_conventional_repo_keeps_the_default_pattern(tmp_path) -> None:
    """The false-widening guard, and the reason prefixes are read off the repo.

    A repository tagging `v1.2.3` must get exactly the default back. Widening
    the pattern for everyone would be a guess, and a looser pattern is where
    false positives come from.
    """
    obs = detect_release_tag(_tagged(tmp_path, "v1.2.3", "v1.3.0"))

    assert _captures(obs, "released in `v1.2.3`") == "v1.2.3"
    # Asserted by BEHAVIOUR, not by searching the pattern for "release-".
    # `re.escape` writes that prefix as `release\-`, so the substring check
    # this replaced could never fail: a mutation that widened the pattern for
    # every repository survived it untouched.
    assert _captures(obs, "shipped in `release-9.9.9`") is None, (
        "the pattern widened to a convention this repository does not use"
    )


def test_no_tags_falls_back_and_says_so(tmp_path) -> None:
    """No tags is not the same as no convention, and must not be guessed at."""
    obs = detect_release_tag(_tagged(tmp_path))

    assert obs.confidence == "default"
    assert _captures(obs, "released in `v1.2.3`") == "v1.2.3"


def test_non_version_tags_are_ignored(tmp_path) -> None:
    """A tag like `latest` carries no version, so it shapes nothing."""
    obs = detect_release_tag(_tagged(tmp_path, "latest", "stable"))

    assert obs.confidence == "default"
    assert "latest" not in str(obs.value)
