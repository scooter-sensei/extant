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


def _search(repo: Path, query: str, *extra: str) -> tuple[int, str]:
    """Drive the real CLI entry point and capture what a user would see.

    `SystemExit` is caught rather than left to propagate. argparse raises it for
    a rejected argument, and a caller wrapped in `pytest.raises` cannot then
    assert on the exit code and the message together - which is the pair a user
    actually gets, and the pair that tells "refused" apart from "crashed".
    """
    import extant_collect as hc

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = hc.main(["--search", query, *extra, "--repo", str(repo)])
        except SystemExit as stop:
            code = stop.code if isinstance(stop.code, int) else 1
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


# --- what the mode PRINTS, as opposed to whether it runs ---------------------
#
# Everything above asks whether `--search` works at all, which is what it
# stopped doing. None of it looks at the output past the denominator line, so
# the excerpt, `--full` and the empty-query guard were unexercised - and
# `--full` is a whole flag whose two branches nothing separated.

# Long enough that the 96-character cap has something to remove, and a single
# repeated character so an assertion can name an exact length.
LONG_LINE = "z" * 200


def _wordy_document(repo: Path, commit) -> None:
    """One entry whose body outruns the excerpt in both ways it can.

    The long line sits SECOND, inside the four non-blank lines the excerpt
    keeps. Placed after them it would be dropped for being the fifth line, and
    the truncation would never be reached - a test that passes without ever
    exercising the cap.
    """
    commit(
        "NEXT_SESSION.md",
        "# status\n\n"
        "## Phase 1 - the wordy one (shipped, 2026-01-01)\n\n"
        "A distinctive word: pomegranate.\n"
        f"{LONG_LINE}\n"
        "third line\n"
        "fourth line\n"
        "fifth line, past where the excerpt stops.\n",
        "docs: a status document with a long entry",
    )


def test_the_excerpt_stops_and_full_does_not(git_repo) -> None:
    """The one thing `--full` is for, asserted on the line that separates them.

    A body line past the fourth is what the excerpt drops and what `--full`
    keeps, so it is the only assertion that can tell the two branches apart.
    Asserting that each prints "something" passes against a `--full` that is
    wired to nothing.
    """
    repo, commit = git_repo
    _wordy_document(repo, commit)

    excerpt_code, excerpt = _search(repo, "pomegranate")
    full_code, full = _search(repo, "pomegranate", "--full")

    assert excerpt_code == 0, excerpt
    assert full_code == 0, full
    assert "fifth line, past where the excerpt stops." not in excerpt, excerpt
    assert "fifth line, past where the excerpt stops." in full, full


def test_the_excerpt_truncates_a_long_line_and_full_keeps_it(git_repo) -> None:
    """The other half of the same flag, and the half a length can pin exactly.

    97 rather than "the whole line": asserting only that the 200-character line
    is absent would also pass if the excerpt dropped the line altogether, which
    is a different behaviour. One character past the cap fails for the right
    reason and no other.
    """
    repo, commit = git_repo
    _wordy_document(repo, commit)

    _, excerpt = _search(repo, "pomegranate")
    _, full = _search(repo, "pomegranate", "--full")

    assert "z" * 96 in excerpt, "the capped line should still be printed"
    assert "z" * 97 not in excerpt, "the excerpt caps a line at 96 characters"
    assert LONG_LINE in full, "--full prints the line as written"


def test_an_empty_query_is_refused_rather_than_matching_everything(git_repo) -> None:
    """A blank query is a mistake, not a request for every entry.

    Whitespace counts as blank, which is the case a bare `.strip()` guard is
    there for: `--search " "` would otherwise be a substring present in almost
    every entry ever written, and the mode would answer by printing the whole
    document back.
    """
    repo, commit = git_repo
    _document(repo, commit)

    for query in ("", "   "):
        code, text = _search(repo, query)
        assert code == 2, (query, text)
        assert "needs something to look for" in text, (query, text)


def test_the_note_fires_when_there_was_nothing_to_search(git_repo) -> None:
    """The other direction of the denominator, and the one nothing asserted.

    A sibling test already checks that this note is ABSENT when an entry was
    searched. Only asserting absence leaves a note that never prints at all
    looking perfectly correct, so the case it exists for is checked here: a
    document whose headers do not match `entry_prefix` yields nothing to
    search, and that must not read as "found nothing".
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# status\n\nA preamble and nothing else.\n\n## 1. Reference\n\nref\n",
           "docs: a status document with no entries")

    code, text = _search(repo, "pomegranate")

    assert code == 0, text
    assert "0 match(es) in 0 entries across 1 document(s)" in text, text
    assert "no entries were found to search" in text, text


def test_both_documents_are_searched_and_the_live_one_comes_first(git_repo) -> None:
    """Entries MOVE between the two documents, so both are searched as one.

    The ordering is the useful half: somebody looking for a decision wants the
    live document first, because that is where the current answer is if there
    is one. Asserting only that both appear would pass whichever order they
    came in.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# status\n\n## Phase 9 - recent (in progress, 2026-09-01)\n\n"
           "the widget rewrite landed\n", "docs: the live document")
    commit("docs/status-archive.md",
           "# Archive\n\n## Phase 0 - ancient (shipped, 2025-01-01)\n\n"
           "the widget decision was made here\n", "docs: the archive")

    code, text = _search(repo, "widget")

    assert code == 0, text
    assert "2 match(es) in 2 entries across 2 document(s)" in text, text
    assert text.index("Phase 9") < text.index("Phase 0"), text


def test_a_reference_section_between_entries_is_not_searched(git_repo) -> None:
    """Search returns dated decisions, and reference material is neither.

    An interleaved `## ` section that is not an entry is classified "other" and
    skipped, so a query living only there matches nothing - while the two real
    entries around it still count toward the denominator. Both halves matter:
    a skip that also stopped counting would print "0 in 0" and read as an
    unconfigured repository.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# status\n\n"
           "## Phase 2 - second (shipped, 2026-01-02)\n\nnothing notable\n\n"
           "## Architecture roadmap\n\nthe pomegranate plan lives here\n\n"
           "## Phase 1 - first (shipped, 2026-01-01)\n\nnothing notable either\n",
           "docs: a status document with an interleaved reference section")

    code, text = _search(repo, "pomegranate")

    assert code == 0, text
    assert "0 match(es) in 2 entries across 1 document(s)" in text, text
    assert "no entries were found to search" not in text, text
