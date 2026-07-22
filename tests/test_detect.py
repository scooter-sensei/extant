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
