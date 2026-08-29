"""A merge claim that wraps a line, and the two things it must not join.

`merge_claim` separates its parts with `\\s+`, which matches a newline, and the
rule's probe searches the whole document - so a claim wrapped at the margin is
found there. The scanner the rule actually reads did not: `_merge_claims` fed
the pattern one line at a time, so the pattern was never given the chance its
own `\\s+` describes. Two matchers for one claim, and the rule was the blind one.

The consequence is the quiet direction. "merged to `main` at `abc1234`" wrapping
at 79 columns is ordinary prose, and a false one went unexamined rather than
judged and found true - the denominator counted it as absent, not as passing.
Found by accident: the first draft of this repository's own status entry wrapped
exactly there, `--selftest` reported the rule DID NOT FIRE, and the rule was
working perfectly on every claim it was allowed to see.

Widening a scan is the change this project refuses to make on reasoning alone,
so the guards below are half the point. Scanning whole text lets `\\s+` cross
anything whitespace-shaped, including the spaces `prose()` leaves where a fenced
block used to be - which would let a claim in one paragraph borrow a SHA from
another, or from inside a code block that was blanked precisely so it could not
be read as a promise. A claim may wrap ONE line break and no more.
"""
from __future__ import annotations

import pytest


def _config():
    from extant import session as hc
    return hc._ACTIVE


def _claims(text: str):
    from extant.commits import merge_claims
    return merge_claims(_config(), text)


def test_a_claim_wrapped_onto_the_next_line_is_found() -> None:
    """The defect. `\\s+` spans the break, and the scanner must let it."""
    text = ("The work is merged to `main` at\n"
            "`abc1234` and the tests pass.\n")

    claims = _claims(text)

    assert len(claims) == 1, claims
    _, ref, sha = claims[0]
    assert ref == "`main`"
    assert sha == "abc1234"


def test_a_wrapped_claim_is_reported_on_the_line_it_starts_on() -> None:
    """Where the reader has to go to fix it.

    The claim opens on the line that says "merged to", so that is the line the
    finding names. Reporting the SHA's line would send a reader to a fragment
    that reads like an ordinary sentence continuation.
    """
    text = ("# Title\n"
            "\n"
            "The work is merged to `main` at\n"
            "`abc1234` and the tests pass.\n")

    (number, _, _), = _claims(text)

    assert number == 3, f"expected the line carrying 'merged to', got {number}"


def test_a_same_line_claim_still_reports_its_own_line() -> None:
    """The case that always worked, kept honest while the scan widens."""
    text = ("# Title\n"
            "\n"
            "Shipped into develop at `deadbee` last week.\n")

    (number, ref, sha), = _claims(text)

    assert (number, ref, sha) == (3, "develop", "deadbee")


def test_two_claims_on_one_line_are_both_found() -> None:
    """finditer over the whole text must not lose the second match on a line."""
    text = "merged to `main` at `aaaaaaa`, merged to `dev` at `bbbbbbb`\n"

    assert [sha for _, _, sha in _claims(text)] == ["aaaaaaa", "bbbbbbb"]


def test_a_claim_is_not_joined_across_a_blank_line() -> None:
    """The paragraph guard.

    `\\s+` will happily cross a blank line, which would let a sentence ending in
    a branch name adopt a SHA from the paragraph after it. That is a claim
    nobody wrote, and inventing one is worse than missing one: a false positive
    is what gets a validator switched off.
    """
    text = ("Everything was merged to `main`\n"
            "\n"
            "at `abc1234` the tests broke.\n")

    assert _claims(text) == []


def test_a_claim_is_not_joined_across_a_blanked_fence() -> None:
    """The guard that only matters because `prose` blanks rather than deletes.

    A fenced block becomes a run of spaces of the same length, so whole-text
    scanning can walk straight through it. A claim on one side of a fence must
    not collect a SHA from the other side - the fence is there to say that what
    is inside is an example, not a promise.
    """
    from extant import session as hc
    from extant.text import prose
    hc.set_document(doc_format="markdown")
    text = ("The work is merged to `main` at\n"
            "```\n"
            "example\n"
            "```\n"
            "`abc1234`, apparently.\n")

    assert _claims(prose(hc._DOC, text)) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_a_wrapped_claim_is_found_with_either_terminator(newline) -> None:
    """CRLF is what a Windows checkout hands the scanner.

    `\\s+` covers `\\r` as well as `\\n`, so this passes for the same reason the
    LF case does - but the newline counting behind the line number does not get
    that for free, and a claim wrapped on CRLF must still name line 1.
    """
    text = f"The work is merged to `main` at{newline}`abc1234`.{newline}"

    (number, _, sha), = _claims(text)

    assert (number, sha) == (1, "abc1234")


def test_a_false_wrapped_claim_reaches_the_rule(git_repo) -> None:
    """End to end, because the scanner is not the thing anyone runs.

    A commit that exists and is not an ancestor of `main`, claimed as merged
    across a line break. Before the scan widened, this document validated clean
    while making a false claim about where work landed.
    """
    from extant import session as hc
    from extant.rules import merge as rule_merge
    repo, commit = git_repo
    commit("a.txt", "a\n", "feat: on main")
    import subprocess
    subprocess.run(["git", "checkout", "-q", "-b", "side"], cwd=repo, check=True)
    stray = commit("b.txt", "b\n", "feat: never merged")
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)

    text = (f"The rewrite is merged to `main` at\n`{stray[:7]}` and is done.\n")
    findings = rule_merge.check(hc.context(repo), text)

    assert [f.kind for f in findings] == ["false-merge-claim"], findings
    assert stray[:7] in findings[0].detail
