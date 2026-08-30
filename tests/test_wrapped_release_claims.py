"""A release claim that wraps a line, and the denominator that counted it anyway.

`dead-release-tag` had three readers of one pattern and two different scans.
`examined` and `probe` searched the whole document; `check` - the only one that
decides a finding - iterated `splitlines()` and matched per line. `release_tag`
separates its parts with `\\s+`, which matches a newline, so a claim wrapped at
the margin was seen by two of the three.

That is worse than the merge-claim version of the same defect, and worth being
precise about. There, a wrapped claim was invisible to the rule AND absent from
its denominator: the count said "nothing here", which is at least honest. Here
the count said examined=1 and the check reported 0 findings, which prints as
EXAMINED AND CLEAN. The one number this project keeps to tell "checked and fine"
apart from "never looked" was reporting the wrong one of the two.

Found by stopping to ask whether it was safe to wrap a claim before writing
eight of them into the status document, rather than by anything failing.

The guards below are half the change, for the reason they were half the merge
fix: scanning whole text lets `\\s+` cross anything whitespace-shaped, including
the spaces `prose()` leaves where a fenced block used to be. A claim may wrap
ONE line break and no more.
"""
from __future__ import annotations

import pytest


def _claims(text: str):
    from extant import session as hc
    from extant.rules.release_tag import _release_claims
    return _release_claims(hc._ACTIVE, text)


def _repo(git_repo):
    """A repository with one tag that exists and is on the trunk."""
    repo, commit = git_repo
    commit("a.txt", "a\n", "feat: a")
    import subprocess
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo, check=True,
                   capture_output=True)
    return repo


def test_a_wrapped_claim_is_scanned_at_all() -> None:
    """The scan the check reads must see what `\\s+` describes."""
    text = "The rewrite shipped in\n1.2.3 last week.\n"

    claims = _claims(text)

    assert claims == [(1, "1.2.3")], claims


def test_a_wrapped_claim_is_reported_on_the_line_it_starts_on() -> None:
    """Where the reader goes to fix it: the line that says "shipped in"."""
    text = "# Title\n\nThe rewrite shipped in\n1.2.3 last week.\n"

    (number, _), = _claims(text)

    assert number == 3, f"expected the line carrying 'shipped in', got {number}"


def test_a_same_line_claim_is_unchanged() -> None:
    text = "# Title\n\nReleased in v2.0.1 on Tuesday.\n"

    assert _claims(text) == [(3, "v2.0.1")]


def test_two_claims_on_one_line_are_both_found() -> None:
    text = "shipped in 1.0.0 and later released as 2.0.0\n"

    assert [tag for _, tag in _claims(text)] == ["1.0.0", "2.0.0"]


def test_a_claim_is_not_joined_across_a_blank_line() -> None:
    """The paragraph guard: a version starting a paragraph is not a release."""
    text = "Everything was shipped in\n\n1.2.3 was the year's worst build.\n"

    assert _claims(text) == []


def test_a_claim_is_not_joined_across_a_blanked_fence() -> None:
    """`prose` blanks a fence to spaces, so whole-text scanning can walk it."""
    from extant import session as hc
    from extant.text import prose
    hc.set_document(doc_format="markdown")
    text = ("The rewrite shipped in\n"
            "```\n"
            "example\n"
            "```\n"
            "1.2.3, apparently.\n")

    assert _claims(prose(hc._DOC, text)) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_a_wrapped_claim_is_found_with_either_terminator(newline) -> None:
    text = f"The rewrite shipped in{newline}1.2.3.{newline}"

    assert _claims(text) == [(1, "1.2.3")]


def test_the_denominator_never_counts_a_claim_the_check_cannot_read(
        git_repo, reconfigure) -> None:
    """The defect itself, stated as the equality that was broken.

    A wrapped claim naming a tag that does not exist used to report
    `examined=1, findings=0` - a denominator asserting it had looked at
    something the check never read, which prints exactly like a claim that was
    checked and found true. Either number alone looks healthy; only the pair
    shows the hole, so the pair is what this asserts.
    """
    from extant import session as hc
    from extant.rules import release_tag
    repo = _repo(git_repo)
    reconfigure(release_claims_are_ours=True)
    hc.set_document(doc_format="markdown")
    text = "The rewrite shipped in\n9.9.9 last week.\n"

    ctx = hc.context(repo)
    counted = release_tag.examined(ctx, text)
    found = release_tag.check(hc.context(repo), text)

    assert counted == 1, counted
    assert len(found) == 1, f"examined {counted} but checked {len(found)}"
    assert "9.9.9" in found[0].detail


def test_a_wrapped_claim_naming_a_live_tag_stays_silent(
        git_repo, reconfigure) -> None:
    """The other direction, so the fix is not just "report more".

    A rule that fired on every wrapped claim would pass the test above and be
    useless. The tag here exists and is on the trunk, so the claim is true and
    the correct answer is silence.
    """
    from extant import session as hc
    from extant.rules import release_tag
    repo = _repo(git_repo)
    reconfigure(release_claims_are_ours=True)
    hc.set_document(doc_format="markdown")
    text = "The rewrite shipped in\nv1.0.0 last week.\n"

    assert release_tag.check(hc.context(repo), text) == []
