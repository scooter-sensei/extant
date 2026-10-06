"""`line_number_at` answers the same question, once per document instead of once per claim.

The function is two lines long and was the largest single term in a `--verify`
that had gone superlinear. It rescanned from position 0 on every call, and both
of its callers - `_merge_claims` in extant/commits.py and the release-claim
scanner in extant/rules/release_tag.py - call it once per claim inside a loop.
With m claims over n characters that is O(m*n), which is why the two slowest
rules on a 17,000-line document were the two that ask it for a line number.

Measured on the development machine over a 375 KB CRLF document, 2000
lookups, median of 5 with a fresh string each time so every repetition pays
its own scan: 7470.4 ms rescanning, 8.0 ms precomputed - 929x, and the reason
this file exists.

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
import re
from typing import Iterator

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


def test_one_document_is_scanned_once_however_many_claims_it_carries(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The cost contract, and the whole reason for the change.

    Asserted as SCANS rather than as seconds, because a timing assertion on a
    shared runner is the one that goes intermittent. A rule asking for two
    hundred line numbers must not walk the document two hundred times.
    """
    from extant import text as markup

    real = markup.LINE_BREAK
    scans: list[str] = []

    class Counting:
        def finditer(self, text: str) -> Iterator[re.Match[str]]:
            scans.append("finditer")
            return real.finditer(text)

        def findall(self, text: str) -> list[object]:
            scans.append("findall")
            return real.findall(text)

    document = "".join(f"line {i} of the document\r\n" for i in range(400))
    monkeypatch.setattr(markup, "LINE_BREAK", Counting())
    numbers = [markup.line_number_at(document, offset)
               for offset in range(0, len(document), 7)]

    print(f"{len(numbers)} lookups over {len(document)} characters "
          f"cost {len(scans)} scan(s)")
    assert len(numbers) > 200, "too few lookups for this to mean anything"
    assert len(scans) == 1, (
        f"{len(scans)} scans for {len(numbers)} lookups: the document is "
        f"being rescanned per claim, which is the O(m*n) this replaced")


# Every place the package numbers lines ITSELF, 1-based, rather than through
# `line_number_at`, and the rule each one cuts lines by. `splitlines()` breaks
# on a form feed and the Unicode line separators where `LINE_BREAK` does not,
# so a document holding one can be numbered two ways - measured and closed in
# 2026-09 as the internals review's 6.2, on 15 of 108,647 documents (0.014 per
# cent), with the reasoning in `line_number_at`'s docstring. Closing it on a
# count is only honest while the count of SITES is known: this is that count,
# keyed by function so an edit that moves a line does not move the ledger, and
# a thirteenth site becomes a decision somebody sees rather than a drift.
LINE_NUMBERING_SITES = {
    "blocks.py:code_lines": "splitlines",
    "text.py:_blank_uncached": "splitlines, against code_lines",
    "commits.py:_find_sha_candidates": "splitlines",
    "commits.py:_find_bare_sha_candidates": "splitlines",
    # Since 2026-10-01: the line `--sha-map` names a rewrite on, counted by
    # the same cut as the two scanners beside it, so it names the line they
    # would report a finding on.
    "commits.py:translate_shas": "splitlines",
    "links.py:_link_sites_uncached": "splitlines",
    "rules/line_pointer.py:_line_pointer_sites_uncached": "splitlines",
    "rules/manifest_floor.py:_floor_claims": "splitlines",
    "rules/md_anchor.py:_fragment_sites": "splitlines",
    "rules/path_pointer.py:_path_pointer_sites_uncached": "splitlines",
    "rules/pinned_ref.py:_pinned_refs": "splitlines",
    "collect.py:scan_todos": "splitlines",
    # A third rule: a file opened with newline="" and iterated, which cuts at
    # \n, \r and \r\n and nowhere else - the SARIF snippet for a finding.
    "report.py:_sarif_snippet": "file iteration",
}


def test_every_line_numbering_site_is_on_the_ledger() -> None:
    """Catches a fourteenth `enumerate(..., start=1)`, or a site that went.

    The plan that asked for this ledger counted ten, and the count taken for
    it by grep counted nine: a grep for `enumerate(...splitlines())` cannot
    see `lines = text.splitlines()` a line above `enumerate(lines, start=1)`,
    nor a file iterated. Read from the syntax tree instead, which sees both.
    """
    import ast
    from pathlib import Path

    root = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
            / "extant" / "payload" / "extant")
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "enumerate"
                        and any(k.arg == "start" and isinstance(k.value, ast.Constant)
                                and k.value.value == 1 for k in node.keywords)):
                    found.add(f"{path.relative_to(root).as_posix()}:{func.name}")
    assert found, "no site found; this test would pass vacuously"
    assert found == set(LINE_NUMBERING_SITES), (
        f"new: {sorted(found - set(LINE_NUMBERING_SITES))}; "
        f"gone: {sorted(set(LINE_NUMBERING_SITES) - found)}. Name the rule the "
        f"site cuts lines by here, and in line_number_at's docstring.")
