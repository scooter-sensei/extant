"""Documents whose lines end with a bare CR, and the three places that missed it.

`\\r\\n` contains `\\n`, so counting newlines is right for CRLF and was never in
question. A bare `\\r` contains none, and three pieces of this package counted
`\\n` or tested for `\\r\\n` and took the answer as complete:

* the merge-claim scanner's one-line-break bound, which never tripped, so the
  guard that stops a claim borrowing a SHA from the next paragraph was not a
  guard at all;
* the release-claim scanner's copy of the same bound;
* `archive`, which detects the document's own terminator to write it back, and
  which normalises `\\r\\n` to `\\n` before splitting. A CR-only document was
  neither split into entries nor written back in the spelling it arrived in.

The first two report every claim on line 1 as well, because the offset-to-line
count has the same blind spot.

Raised by a CodeRabbit review of the two scanners, verified against the code
before being acted on, and extended here to the third site and to the line
numbers, neither of which the review named. Acting on a review literally is its
own way of fixing half a defect.

CR-only line endings are close to extinct, and that is deliberately not the
argument. A bound that silently does not bind is the failure this package is
built to refuse, and it costs two lines to make it hold for every spelling a
line ending has.
"""
from __future__ import annotations

import pytest

TERMINATORS = [
    pytest.param("\n", id="LF"),
    pytest.param("\r\n", id="CRLF"),
    pytest.param("\r", id="CR"),
]


def _config():
    from extant import session as hc
    return hc._ACTIVE


# --- the two claim scanners --------------------------------------------------

@pytest.mark.parametrize("newline", TERMINATORS)
def test_a_merge_claim_is_not_joined_across_a_blank_line(newline) -> None:
    """The bound holds for every spelling of a line ending, or it is not one."""
    from extant.commits import merge_claims
    text = (f"Everything was merged to `main`{newline}{newline}"
            f"at `abc1234` the tests broke.{newline}")

    assert merge_claims(_config(), text) == []


@pytest.mark.parametrize("newline", TERMINATORS)
def test_a_merge_claim_reports_the_line_it_sits_on(newline) -> None:
    """A claim on the third line is on the third line however lines are ended."""
    from extant.commits import merge_claims
    text = (f"# Title{newline}{newline}"
            f"The work is merged to `main` at `abc1234`.{newline}")

    (number, _, _), = merge_claims(_config(), text)

    assert number == 3


@pytest.mark.parametrize("newline", TERMINATORS)
def test_a_release_claim_is_not_joined_across_a_blank_line(newline) -> None:
    from extant.rules.release_tag import _release_claims
    text = (f"Everything was shipped in{newline}{newline}"
            f"1.2.3 was the worst build.{newline}")

    assert _release_claims(_config(), text) == []


@pytest.mark.parametrize("newline", TERMINATORS)
def test_a_release_claim_reports_the_line_it_sits_on(newline) -> None:
    from extant.rules.release_tag import _release_claims
    text = (f"# Title{newline}{newline}"
            f"The rewrite shipped in 1.2.3 last week.{newline}")

    (number, _), = _release_claims(_config(), text)

    assert number == 3


@pytest.mark.parametrize("newline", TERMINATORS)
def test_a_wrapped_claim_is_still_read_on_every_terminator(newline) -> None:
    """The widening must not be undone by tightening the bound.

    One break is still one break. A bound that counted a CR-only document's
    every line as a break would refuse the wrapped claim the scan exists to
    read, which is the opposite failure and just as silent.
    """
    from extant.commits import merge_claims
    text = f"The work is merged to `main` at{newline}`abc1234`.{newline}"

    assert merge_claims(_config(), text) == [(1, "`main`", "abc1234")]


# --- archive, which writes the document back ---------------------------------

CR_DOC = (
    "# Status\r\r"
    "## Phase 5 - fifth\r\rbody five\r\r"
    "## Phase 4 - fourth\r\rbody four\r\r"
    "## Phase 3 - third\r\rbody three\r\r"
    "## Phase 2 - second\r\rbody two\r\r"
    "## Phase 1 - first\r\rbody one\r\r"
    "## 1. Reference\r\rreference body\r"
)


def test_archive_splits_a_cr_only_document_into_its_entries(git_repo) -> None:
    """`^` in a MULTILINE pattern follows a newline, and `\\r` is not one.

    Left unnormalised, a CR-only document presents as a single line: no entry
    header matches, `split_entries` returns nothing to move, and `--archive`
    reports a document with nothing in it rather than failing. That is the
    reassuring-zero shape, in the one operation here that rewrites a file.
    """
    from extant import session as hc
    from extant import entries
    repo, commit = git_repo
    commit("NEXT_SESSION.md", CR_DOC, "docs: a CR-only status document")

    counts = entries.archive(repo, 3, hc._ACTIVE)

    assert counts == {"retained": 3, "archived": 2}, counts


def test_archive_writes_a_cr_only_document_back_as_cr_only(git_repo) -> None:
    """The terminator a file arrived in is the one it leaves in.

    `archive` is the only irreversible write in this system. Detecting only
    `\\r\\n` and defaulting to `\\n` rewrites every line ending in a CR-only
    document as a side effect of retiring two entries, which is a change to
    every line of a file the user asked to have two sections moved in.
    """
    from extant import session as hc
    from extant import entries
    repo, commit = git_repo
    commit("NEXT_SESSION.md", CR_DOC, "docs: a CR-only status document")

    entries.archive(repo, 3, hc._ACTIVE)

    with open(repo / "NEXT_SESSION.md", "rb") as fh:
        live = fh.read()
    assert b"\r" in live
    assert b"\n" not in live, "a CR-only document came back containing LF"
