"""The offset contract `strip_code` states, and did not keep.

`strip_code` and `prose` blank code with SPACES rather than removing it, and
their docstrings say why: "both the line count and every character offset
survive", so a caller may take a span from the stripped text and use it against
the original. Two callers do exactly that - the `dead-md-link` and
`dead-md-anchor` probes splice `match.span(1)` from the stripped text into the
untouched document.

The contract was not kept. Both blanking paths ran `text.splitlines()` and
rejoined with `"\\n"`, which drops the real terminator and reinstates a bare
newline: every `\\r\\n` lost a character, and a trailing newline was lost even on
LF input. On this repository's own status document that was 1627 characters, so
on a CRLF checkout every offset past the first line was wrong and both probes
spliced into the wrong place. The probe then reported that it had corrupted a
real match while the rule, reading an untouched claim, correctly found nothing -
`--selftest` exiting 1 on Windows and 0 on Linux for the same commit.

CI could not see it. The runners check out LF, where the only casualty is the
final newline and every offset a probe cares about still lines up.

These tests pin the contract itself rather than the two probes, because the
contract is what the next caller will rely on.
"""
from __future__ import annotations

from pathlib import Path

import pytest

DOC = (
    "# Title\r\n"
    "\r\n"
    "Prose with `inline code` in it.\r\n"
    "\r\n"
    "```python\r\n"
    "x = [a link](target.md)\r\n"
    "```\r\n"
    "\r\n"
    "A [real link](docs/plan.md) after the fence.\r\n"
)


def _doc_scope(fmt: str = "markdown"):
    from extant import session as hc
    hc.set_document(doc_format=fmt)
    return hc._DOC


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_strip_code_preserves_the_length_of_the_document(newline) -> None:
    """The promise in the docstring, stated as the equality it claims.

    Length is the whole of it: the function only ever replaces a run of
    characters with the same number of spaces, so any difference means a
    terminator was rewritten and every offset after it has moved.
    """
    from extant.text import strip_code
    text = DOC.replace("\r\n", newline)

    stripped = strip_code(_doc_scope(), text)

    assert len(stripped) == len(text), (
        f"{len(text) - len(stripped)} character(s) lost with "
        f"{newline!r} terminators; every offset after the first is now wrong")


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_prose_preserves_the_length_of_the_document(newline) -> None:
    """`prose` shares the blanking path and states the same promise."""
    from extant.text import prose
    text = DOC.replace("\r\n", newline)

    assert len(prose(_doc_scope(), text)) == len(text)


def test_a_span_taken_from_the_stripped_text_lands_on_the_original() -> None:
    """The property the two probes actually depend on, on CRLF.

    Length equality alone would be satisfied by a function that shifted
    characters around without losing any. What a probe needs is that a match
    found in the stripped text sits at the SAME index in the original, which is
    what makes `text[:start] + replacement + text[end:]` replace the thing that
    was matched.
    """
    from extant.links import MD_LINK
    from extant.text import strip_code
    text = DOC                                   # CRLF, as Windows checks out

    stripped = strip_code(_doc_scope(), text)
    match = next(m for m in MD_LINK.finditer(stripped)
                 if not m.group(1).startswith("#"))
    start, end = match.span(1)

    assert text[start:end] == match.group(1), (
        f"stripped text matched {match.group(1)!r} at {start}:{end}, but the "
        f"original holds {text[start:end]!r} there")
    # The fenced link must not be the one found: it is code, so it is blanked.
    assert match.group(1) == "docs/plan.md"


def test_the_trailing_newline_survives() -> None:
    """The LF casualty, which is small enough to have gone unnoticed.

    One character, at the very end, so no probe ever mis-spliced because of it
    on Linux. It is still the same defect as the CRLF loss - the rejoin decides
    the terminator instead of preserving it - and pinning only the CRLF half
    would leave a fix free to keep dropping this one.
    """
    from extant.text import strip_code
    text = "# Title\n\nSome prose.\n"

    assert strip_code(_doc_scope(), text).endswith("\n")


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_rst_stripping_preserves_the_length_too(newline) -> None:
    """The reStructuredText path is a second copy of the same loop.

    It carries the same sentence in its docstring - "line numbers and offsets
    survive for every rule that shares this" - and had the same defect. Fixing
    only the markdown path would leave an rst document mis-spliced in exactly
    the way this whole file is about.
    """
    from extant.text import strip_code
    text = ("Title\r\n"
            "=====\r\n"
            "\r\n"
            "A literal block::\r\n"
            "\r\n"
            "    x = [a link](target.md)\r\n"
            "\r\n"
            "Prose with ``inline`` after it.\r\n").replace("\r\n", newline)

    assert len(strip_code(_doc_scope("rst"), text)) == len(text)


# --------------------------------------------------------------------------
# What closes a fence, and what opens one. Measured 2026-09-22 against
# markdown-it-py's `commonmark` preset over the 152 visible corpus clones:
# 1,498 documents hold a line the reference parser calls fence content and
# this stripper does not blank, and 41 findings sit on those lines - claims
# the tool checked out of a code block.
# --------------------------------------------------------------------------

def _prose(text: str, fmt: str = "markdown") -> str:
    from extant.text import prose
    return prose(_doc_scope(fmt), text)


def test_a_longer_fence_is_not_closed_by_a_shorter_one() -> None:
    """CommonMark closes a fence only with the same character, at least as
    long as the opener. The toggle closed on any run of three, so a
    four-backtick block quoting a three-backtick one went OUT OF PHASE and
    everything after the inner fence was read as prose.

    aider's posts and superpowers' plan documents are full of it - a
    transcript of a session that itself shows fenced code - and that is where
    16 of the 41 findings measured on the corpus come from.
    """
    text = ("````\n"
            "Here is what the assistant wrote:\n"
            "```python\n"
            "x = 1\n"
            "```\n"
            "Merged at a1b2c3d, it says.\n"
            "````\n"
            "\n"
            "Real prose, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "a claim inside the outer fence was read as prose"
    assert "d4e5f6a" in blanked, "prose after the block was blanked"


def test_a_fence_inside_a_block_quote_is_still_a_fence() -> None:
    """`_FENCE` anchored on optional whitespace only, so `> ```' never matched
    and the quoted block was read as prose from its first line to its last.
    fxamacker/cbor's README quotes a hex dump that way, and moby and
    kubernetes each vendor it.
    """
    text = ("> Output:\n"
            "> ```\n"
            "> hex(JSON): 7b22466f6f223a7b22517578223a7b7d7d7d\n"
            "> ```\n"
            "\n"
            "Prose after, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "7b22466f6f223a7b22517578223a7b7d7d7d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_fence_with_an_info_string_does_not_close_one() -> None:
    """A closing fence carries no info string, so ```` ```python ```` inside a
    fenced block is content rather than the end of it."""
    text = ("```\n"
            "$ cat example.md\n"
            "```python\n"
            "merged at a1b2c3d\n"
            "```\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked


def test_an_ordinary_fence_still_closes(git_repo) -> None:
    """The other half: the common case must be untouched, and a claim after a
    plain fence is still read."""
    text = ("Before, merged at a1b2c3d.\n"
            "```\n"
            "inside b2c3d4e\n"
            "```\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "b2c3d4e" not in blanked
    assert "a1b2c3d" in blanked and "d4e5f6a" in blanked


def test_a_tilde_fence_is_not_closed_by_backticks() -> None:
    """The character has to match too: a backtick run inside a tilde block is
    content, and the tilde block runs to its own closer."""
    text = ("~~~\n"
            "```\n"
            "merged at a1b2c3d\n"
            "```\n"
            "~~~\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_fence_inside_a_block_quote_ends_when_the_quote_does() -> None:
    """A container's end closes every block inside it, a fence included.

    Recognising `> ```' as a fence was half the repair; the other half is
    that the quote can end before any closer arrives - a pasted message cut
    off mid-block - and CommonMark closes the fence with it. Without that
    the fence stayed open and blanked the prose after the quote. Found by the
    identity gate on 2026-09-26 rather than by a test: aider's chat-history
    fixture lost 129 findings the reference parser calls prose, all after one
    quoted fence that its message never closed.
    """
    text = ("> ```\n"
            "> code the message never closed\n"
            "\n"
            "Prose after the quote, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "d4e5f6a" in blanked, "the quote ended and the fence did not"
    assert "never closed" not in blanked, "the quoted fence's content was read"


def test_a_line_that_leaves_the_quote_ends_its_fence_too() -> None:
    """The same without a blank line between: the first line without the
    quote marker is outside the quote, whatever it says."""
    text = ("> ```\n"
            "> quoted code\n"
            "Unquoted prose, merged at d4e5f6a.\n")
    assert "d4e5f6a" in _prose(text)


def test_a_fence_indented_four_past_its_opener_is_content() -> None:
    """CommonMark's closer may be indented at most three columns, measured
    from where the block's content starts - so a fence line four or more
    columns deeper than its opener is the block's CONTENT, an example of a
    fence shown inside a fence. Closing on it put the stripper out of phase,
    and the real closer then opened a fence that ran to the end of the
    document: mini-swe-agent's admonition example and superpowers' reviewer
    template both, found by the old-against-new measurement on 2026-09-26.
    """
    text = ("```markdown\n"
            "Show this to the reader:\n"
            "\n"
            "    ```\n"
            "    an example fence, merged at a1b2c3d\n"
            "    ```\n"
            "```\n"
            "\n"
            "Prose after, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "the example inside the fence was read"
    assert "d4e5f6a" in blanked, "the prose after the fence was blanked"


def test_a_backtick_run_with_a_backtick_after_it_is_inline_code() -> None:
    """A backtick fence's info string may not contain a backtick, so a line
    that opens with three backticks and closes them later is an inline code
    span, not a fence. kubernetes' changelogs write commands that way, and
    reading one as a fence blanked every entry below it.
    """
    # The backticks START the line, as they do in kubernetes' changelog -
    # which is what makes the line look like a fence at all.
    text = ("* Federation secret, if upgrading:\n"
            "    ```$ kubectl get secret federation-apiserver-secret```\n"
            "* Fixed in the release merged at d4e5f6a.\n")
    assert "d4e5f6a" in _prose(text)
