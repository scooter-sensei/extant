"""`line_number_at` answers the same question, once per document instead of once per claim.

The function is two lines long and was the largest single term in a `--verify`
that had gone superlinear. It rescanned from position 0 on every call, and both
of its callers - `_merge_claims` in extant/commits.py and the release-claim
scanner in extant/rules/release_tag.py - call it once per claim inside a loop.
With m claims over n characters that is O(m*n), which is why the two slowest
rules on a 17,000-line document were the two that ask it for a line number.

Measured over a 380 KB CRLF document, 2000 lookups: 8734.9 ms rescanning,
18.2 ms precomputed - 479x, and the reason this file exists.

The precomputation is not obviously equivalent, and that is the point of the
first three tests. `findall(text, 0, offset)` restricts the SEARCH REGION, so a
`\r\n` straddling the boundary degrades to a lone `\r` match and is still
counted, while a span computed over the whole text sees one break ending after
the offset. Counting spans that START before the offset is what reconciles the
two; counting spans that END before it silently reports the line above for
every offset that lands between a CR and its LF.
"""
from __future__ import annotations

import random

import pytest

from extant.text import LINE_BREAK, line_number_at


def rescan(text: str, offset: int) -> int:
    """The implementation this replaces, kept as the oracle.

    Lifted verbatim rather than described, because an oracle that is a
    paraphrase of the code under test proves the paraphrase.
    """
    return len(LINE_BREAK.findall(text, 0, offset)) + 1


# Every spelling of a terminator, and every position one can occupy. Named
# rather than generated so a failure says which shape broke.
SPELLINGS = [
    pytest.param("", id="empty"),
    pytest.param("one line, no terminator at all", id="none"),
    pytest.param("a\nb\nc\n", id="LF-only"),
    pytest.param("a\r\nb\r\nc\r\n", id="CRLF-only"),
    pytest.param("a\rb\rc\r", id="CR-only"),
    pytest.param("a\nb\r\nc\rd", id="mixed"),
    pytest.param("a\n\rb", id="LFCR"),
    pytest.param("a\r\rb", id="double-CR"),
    pytest.param("\r\na", id="leading"),
    pytest.param("a\r\n", id="trailing"),
]


@pytest.mark.parametrize("text", SPELLINGS)
def test_a_line_number_is_the_same_one_a_full_rescan_reports(text: str) -> None:
    """Every offset, not a sampled few: the divergence is one character wide.

    The CRLF case is why. Only the offset landing BETWEEN the `\r` and the
    `\n` distinguishes the two ways of counting a span, so a test that steps
    through offsets in twos can miss it entirely.
    """
    disagreements = [
        (offset, rescan(text, offset), line_number_at(text, offset))
        for offset in range(len(text) + 1)
        if rescan(text, offset) != line_number_at(text, offset)
    ]
    print(f"checked {len(text) + 1} offsets over {text!r}")
    assert not disagreements, disagreements


def test_an_offset_outside_the_text_answers_what_it_always_did() -> None:
    """Neither caller can produce one, which is exactly why this is pinned.

    A bound that only holds for offsets the current callers happen to pass is
    a bound that breaks in the commit that adds a third caller.
    """
    text = "a\r\nb\nc"
    for offset in (-1, -5, -len(text) - 10, len(text) + 1, 10 ** 6):
        assert line_number_at(text, offset) == rescan(text, offset), offset


def test_randomised_mixed_terminator_texts_agree_at_every_offset() -> None:
    """A soak, because the hand-built cases are the ones somebody thought of.

    Fixed seed: a fuzz that finds a different failure each run cannot be
    handed to whoever has to fix it.
    """
    rng = random.Random(20260904)
    pieces = ["a", "b", " ", "\n", "\r\n", "\r", "\r\r", "\n\r"]
    checked = 0
    for _ in range(300):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 40)))
        for offset in range(len(text) + 1):
            checked += 1
            assert line_number_at(text, offset) == rescan(text, offset), (
                repr(text), offset)
    print(f"checked {checked} offsets over 300 randomised texts")
    assert checked > 1000, "the soak generated too little to mean anything"


def test_one_document_is_scanned_once_however_many_claims_it_carries() -> None:
    """The cost contract, and the whole reason for the change.

    Asserted as SCANS rather than as seconds, because a timing assertion on a
    shared runner is the one that goes intermittent. A rule asking for two
    hundred line numbers must not walk the document two hundred times.
    """
    from extant import text as markup

    real = markup.LINE_BREAK
    scans = []

    class Counting:
        def finditer(self, *args, **kwargs):
            scans.append("finditer")
            return real.finditer(*args, **kwargs)

        def findall(self, *args, **kwargs):
            scans.append("findall")
            return real.findall(*args, **kwargs)

    document = "".join(f"line {i} of the document\r\n" for i in range(400))
    markup.LINE_BREAK = Counting()
    try:
        numbers = [markup.line_number_at(document, offset)
                   for offset in range(0, len(document), 7)]
    finally:
        markup.LINE_BREAK = real

    print(f"{len(numbers)} lookups over {len(document)} characters "
          f"cost {len(scans)} scan(s)")
    assert len(numbers) > 200, "too few lookups for this to mean anything"
    assert len(scans) == 1, (
        f"{len(scans)} scans for {len(numbers)} lookups: the document is "
        f"being rescanned per claim, which is the O(m*n) this replaced")
