"""`--search`, which shipped broken and which nothing was watching.

The module split separated `StatusConfig` - the raw parsed settings - from
`Config`, which carries the values derived from it. `search_entries` reaches
`split_entries`, and `split_entries` needs the derived object because
`section_header` is one of the derived fields. A caller handed it the raw one
and the mode raised `AttributeError` on every invocation.

That survived 641 tests, a byte-identical `--verify` comparison and ten task
reviews, because no test drove `--search` at all. The smoke harness caught it
at the very end of the work. These tests exist so the next such break is caught
by the suite rather than by luck.

A regex query is one of the cases because it is the one the harness happened to
try; a plain query crashed identically, so the failure was never about regex.
"""
from __future__ import annotations

import io
import contextlib
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _search(repo: Path, query: str) -> tuple[int, str]:
    """Drive the real CLI entry point and capture what a user would see."""
    import extant_collect as hc

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = hc.main(["--search", query, "--repo", str(repo)])
    return code, out.getvalue() + err.getvalue()


def _document(repo: Path, commit) -> None:
    commit(
        "NEXT_SESSION.md",
        "# status\n\n"
        "## Phase 2 - the second thing (shipped, 2026-01-02)\n\n"
        "A distinctive word: pomegranate.\n\n"
        "## Phase 1 - the first thing (shipped, 2026-01-01)\n\n"
        "Nothing notable here.\n",
        "docs: a status document to search",
    )


def test_a_plain_query_finds_the_entry_that_carries_it(git_repo) -> None:
    """The mode's whole job. Against the broken code this raised
    AttributeError before printing anything."""
    repo, commit = git_repo
    _document(repo, commit)

    code, text = _search(repo, "pomegranate")

    assert code == 0, text
    assert "Traceback" not in text, text
    assert "match" in text, text


def test_a_query_matching_nothing_says_so_rather_than_failing(git_repo) -> None:
    """Zero matches is an answer, not an error. Distinguishing the two is the
    same denominator problem the rules have: `0 found` and `it broke` must not
    print alike."""
    repo, commit = git_repo
    _document(repo, commit)

    code, text = _search(repo, "certainly-not-present-anywhere")

    assert code == 0, text
    assert "Traceback" not in text, text
    assert "0 match" in text, text


def test_a_regex_wildcard_query_does_not_crash(git_repo) -> None:
    """The exact invocation the smoke harness flagged.

    `.*` matches every entry, so this also proves the entry SPLIT works
    through this path - which is precisely the code that was reaching for a
    field the object it was handed did not have.
    """
    repo, commit = git_repo
    _document(repo, commit)

    code, text = _search(repo, ".*")

    assert code == 0, text
    assert "Traceback" not in text, text
    assert "AttributeError" not in text, text
    # Two entries exist, so a working split reports both.
    assert "2 entries" in text, text
