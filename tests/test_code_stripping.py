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
    from extant.text import MD_LINK, strip_code
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
