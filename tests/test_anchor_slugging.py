"""`anchors()` spells three slug conventions out; these hold it to them.

The conventions have names - `_slug`, `_slug_punctuation_to_dash`,
`_slug_keeping_edges` - and `_disambiguated` names the repeat numbering. For
speed `anchors()` does not call any of them: it walks the headings once and
produces all four results inline, which is worth 1.32x on a real corpus and
matters because this runs for every document a link reaches rather than only
for the one under validation.

Two implementations of one rule is a rot vector. The fast one can drift from
the named one and nothing downstream would say so - a dead anchor is reported
by ABSENCE from a set, so a drifting slug shows up as a link that was fine
yesterday being called broken today, in someone else's repository. These tests
are the thing that says so instead.

They fail against a wrong implementation by construction: each asserts the
inline result equals what the named function returns for the same input, so
changing either side alone turns them red.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

from extant.text import (                                   # noqa: E402
    _disambiguated, _heading_text, _slug, _slug_keeping_edges,
    _slug_punctuation_to_dash, _without_tags, anchors,
)

# Deliberately awkward. Every entry is a shape that has moved a slug in some
# renderer: punctuation at the edges, runs of separators, inline markup, casing,
# non-ASCII, and the empty result a heading of pure punctuation produces.
HEADINGS = [
    "Hello World", "API: the `run()` entry", "What's new?", "C++ / C# notes",
    "<b>Bold</b> heading", "Trailing punctuation!!!", "-leading dash",
    "dash-  -mid", "100% done", "a  b   c", "Unicode: Ueber alles",
    "multi--dash--title", "...", "_under_score_", "(parens) [brackets]",
    "ends with dash-", "-", "--", "a & b", '"quoted"', "CamelCase API",
    "snake_case_name", "x=y+z", "50/50", "1.2.3", "a/b/c path", "",
    "   ", "tab\theading", "double  space", "emoji-free but long " * 3,
]


def _inline_spellings(heading: str) -> set[str]:
    """Every spelling `anchors()` produces for ONE heading, read back out.

    A document with a single heading offers exactly the slugs that heading
    generates, so running the real function over a one-heading document is how
    the inline arithmetic is observed without reaching into it.
    """
    return anchors(f"# {heading}\n")


def test_the_inline_slugging_matches_the_three_named_conventions() -> None:
    """The fast path must offer every spelling the named functions do.

    Against a fast path that dropped a convention - say it stopped emitting the
    punctuation-to-dash spelling - this goes red on the first heading whose two
    spellings differ, which is most of the list.
    """
    checked = 0
    for heading in HEADINGS:
        produced = _inline_spellings(heading)
        variants = [v for v in (heading, _without_tags(heading))]
        expected = {_slug(v) for v in variants}
        expected |= {_slug_punctuation_to_dash(v) for v in variants}
        expected |= {_slug_keeping_edges(v) for v in variants}
        expected -= {""}
        assert produced == expected, (
            f"heading {heading!r}: inline slugging produced {produced!r}, "
            f"the named conventions produce {expected!r}")
        checked += 1
    # The denominator. A loop over an empty list asserts nothing and passes.
    assert checked == len(HEADINGS) and checked >= 30, checked


def test_repeated_headings_are_numbered_the_way_disambiguated_numbers_them() -> None:
    """`-1`, `-2` suffixes must match `_disambiguated`, which defines them.

    Against a fast path that counted repeats per VARIANT rather than per
    heading, or that started the suffixes at 1 instead of 0, the sets differ.
    """
    cases = [
        ["Hello", "Hello"],
        ["Hello", "Hello", "Hello"],
        ["Notes", "notes", "NOTES"],
        ["A", "B", "A", "B", "A"],
        ["<b>x</b>", "x"],
    ]
    for headings in cases:
        document = "".join(f"# {h}\n\n" for h in headings)
        produced = anchors(document)
        for spelling in _disambiguated(headings):
            if spelling:
                assert spelling in produced, (
                    f"{headings!r}: `_disambiguated` offers {spelling!r} and "
                    f"the inline numbering does not")
    assert len(cases) == 5


def test_heading_text_is_still_the_shared_front_end() -> None:
    """Both sides must strip the heading the same way before slugging.

    `_heading_text` is the one piece the fast path still CALLS. If it stopped
    being shared - if the inline version grew its own stripping - a heading
    with trailing hashes would slug differently on the two sides, so this pins
    that the call is still what happens.
    """
    checked = 0
    for raw in ("Title ###", "Title", "  Title  ", "Title #", "A B ##"):
        expected = _slug(_heading_text(raw))
        # No `or not expected` escape. Every input here slugs to something, and
        # an assertion that forgives an empty result is one that stops testing
        # the moment somebody adds an input that produces one.
        assert expected, f"{raw!r} slugged to nothing; the case tests nothing"
        assert expected in anchors(f"# {raw}\n"), (
            f"heading {raw!r}: `_heading_text` gives {expected!r} and the "
            f"inline path does not offer it")
        checked += 1
    assert checked == 5
