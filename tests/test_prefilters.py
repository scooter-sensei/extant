"""A scan skipped only when the pattern could not have matched.

`_release_claims` and `_merge_claims` run a configurable pattern over every
document's prose, and on a 650-document sweep of ruff that is 0.71 s and
0.29 s, measured wall-clock without a profiler - 14% of the run - to find
claims in 19 and 12 documents. Both default patterns open with a literal
alternation, `(?:released|shipped|tagged)` and `(?:merged|shipped)`, so a
document holding none of those words cannot match, and a substring test
settles that at memory speed.

What makes this more than a one-line change is the word "cannot". The
pattern is the user's to configure, so the words are DERIVED from it, and
only from a shape where they really are necessary: a leading `(?:a|b|c)`
group of plain literals, not optional, with no top-level `|` after it.
And the pattern is compiled with `re.IGNORECASE`, whose idea of a letter is
wider than `str.lower()`'s - verified: `SH<U+0130>PPED`, `<U+017F>hipped`,
`sh<U+0131>pped` all
match the default pattern and none contains "shipped" after `lower()`. A
pre-filter that missed those would skip a scan the regex would have made,
which is a wrong answer arriving as a speed-up.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def test_the_default_patterns_open_with_a_literal_alternation() -> None:
    from extant.config import DEFAULTS
    from extant.text import leading_literals

    assert leading_literals(DEFAULTS["release_tag"]) == ("released", "shipped", "tagged")
    assert leading_literals(DEFAULTS["merge_claim"]) == ("merged", "shipped")


# Every shape in which the leading words are NOT necessary for a match, so
# the derivation must refuse it and the scan run in full. Each was written
# as a pattern somebody could plausibly configure, and each fools a naive
# read of the first group.
UNSOUND = [
    pytest.param(r"(?:merged|shipped)?\s+to", id="optional-group"),
    pytest.param(r"(?:merged|shipped)*\s+to", id="starred-group"),
    pytest.param(r"(?:merged|shipped){0,1}\s+to", id="braced-group"),
    pytest.param(r"(?:merged|shipped)\s+to|landed", id="top-level-bar-later"),
    pytest.param(r"\b(?:merged|shipped)\s+to", id="boundary-first"),
    pytest.param(r"(?:releas\w+|shipped)\s+in", id="non-literal-alternative"),
    pytest.param(r"(?:merged to|landed)\s+", id="space-in-alternative"),
    pytest.param(r"[Ss]hipped in `([\w.@-]+)`", id="character-class-first"),
    pytest.param(r"(?i)(?:merged|shipped)\s+to", id="inline-flag-first"),
    pytest.param(r"merged\s+to\s+main", id="no-group-at-all"),
]


@pytest.mark.parametrize("source", UNSOUND)
def test_a_shape_where_the_words_are_not_necessary_gets_no_prefilter(source) -> None:
    from extant.text import leading_literals

    assert leading_literals(source) == ()


SOUND = [
    pytest.param(r"(?:merged|shipped)\s+(?:to|into)\s+x", ("merged", "shipped"),
                 id="alternation-inside-a-later-group"),
    pytest.param(r"(?:merged|shipped)\s+[|x]", ("merged", "shipped"),
                 id="bar-inside-a-class"),
    pytest.param(r"(?:merged|shipped)\s+\|", ("merged", "shipped"),
                 id="escaped-bar"),
    pytest.param(r"(?:landed)\s+in", ("landed",), id="single-word"),
    pytest.param(r"(?:Merged|SHIPPED)\s+to", ("Merged", "SHIPPED"),
                 id="case-kept-as-written"),
]


@pytest.mark.parametrize("source, words", SOUND)
def test_a_shape_where_the_words_are_necessary_yields_them(source, words) -> None:
    from extant.text import leading_literals

    assert leading_literals(source) == words


# The four characters `re.IGNORECASE` folds onto an ASCII letter that
# `str.lower()` does not: dotted and dotless capital I, long s, Kelvin sign.
SPECIALS = ("SH\u0130PPED in 1.0", "sh\u0131pped in 1.0", "\u017fhipped in 1.0")


@pytest.mark.parametrize("text", [
    "shipped in 1.0", "SHIPPED in 1.0", "Shipped\u00a0in 1.0",
    "It was released in v2.1 last week.", "tagged as 3.0", *SPECIALS,
])
def test_could_match_never_refuses_a_text_the_pattern_matches(text) -> None:
    """The property that makes a pre-filter safe: False only when `search`
    would find nothing. Each text here IS matched by the pattern, which the
    test asserts first so it cannot pass on a fixture the regex ignores."""
    from extant.config import DEFAULTS
    from extant.text import could_match

    pattern = re.compile(DEFAULTS["release_tag"], re.IGNORECASE)
    assert pattern.search(text), f"fixture not matched by the pattern: {text!r}"
    assert could_match(pattern, text) is True


@pytest.mark.parametrize("text", [
    "Version 1.0 is out.", "The ship sailed and the tag was cut.",
    "RELEASE 2.0 landed.", "", "released" [:-1] + " in 1.0",
])
def test_could_match_refuses_a_text_without_any_of_the_words(text) -> None:
    from extant.config import DEFAULTS
    from extant.text import could_match

    pattern = re.compile(DEFAULTS["release_tag"], re.IGNORECASE)
    assert pattern.search(text) is None, f"fixture matched: {text!r}"
    assert could_match(pattern, text) is False


def test_the_kelvin_sign_is_let_through_for_a_pattern_holding_a_k() -> None:
    """None of the default words holds a k, so the fourth fold is reached
    only by a configured pattern - and the guard is for the fold, not for
    the words, so it is tested on one."""
    from extant.text import could_match

    pattern = re.compile(r"(?:kept|dropped)\s+in", re.IGNORECASE)
    text = "\u212aept in 1.0"
    assert pattern.search(text), "fixture not matched by the pattern"
    assert could_match(pattern, text) is True
    assert could_match(pattern, "dropped from 1.0") is True
    assert could_match(pattern, "removed in 1.0") is False


def test_could_match_is_case_sensitive_when_the_pattern_is() -> None:
    """Without IGNORECASE a word is required as written, so the test may be
    stricter - and lowercasing both sides here would be WRONG in the other
    direction only for speed, never for correctness, so it is not done."""
    from extant.text import could_match

    pattern = re.compile(r"(?:Merged|Shipped)\s+to")
    assert could_match(pattern, "merged to main") is False
    assert could_match(pattern, "Merged to main") is True


def test_a_pattern_with_no_derivable_words_is_always_worth_scanning() -> None:
    from extant.text import could_match

    assert could_match(re.compile(r"[Ss]hipped in"), "nothing here") is True


class _Recording:
    """A compiled pattern that counts how often it is asked to scan."""

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern.pattern
        self.flags = pattern.flags
        self.groups = pattern.groups
        self.inner = pattern
        self.scans = 0

    def finditer(self, text: str):
        self.scans += 1
        return self.inner.finditer(text)

    def findall(self, text: str):
        self.scans += 1
        return self.inner.findall(text)


def test_the_release_scan_is_skipped_for_a_document_without_its_words(
        reconfigure) -> None:
    """The pre-filter is in the scanner both `check` and `examined` read,
    so neither pays for a document that cannot hold a claim - and a document
    that can is scanned exactly as before."""
    from extant import session as hc
    from extant.rules.release_tag import _release_claims

    recording = _Recording(hc._ACTIVE.release_tag)
    config = reconfigure(release_tag=recording)
    assert _release_claims(config, "Version 1.0 is out and the tag was cut.\n") == []
    assert recording.scans == 0, "a document without the words was scanned"
    assert _release_claims(config, "Shipped in 1.0 yesterday.\n") == [(1, "1.0")]
    assert recording.scans == 1


def test_the_merge_scan_is_skipped_for_a_document_without_its_words(
        reconfigure) -> None:
    from extant import session as hc
    from extant.commits import _merge_claims

    recording = _Recording(hc._ACTIVE.merge_claim)
    config = reconfigure(merge_claim=recording)
    assert _merge_claims(config, "Landed on main at `abc1234`.\n") == []
    assert recording.scans == 0, "a document without the words was scanned"
    assert _merge_claims(config, "Merged to `main` at `abc1234`.\n") == [
        (1, "`main`", "abc1234")]
    assert recording.scans == 1


def test_a_document_without_a_rev_line_never_asks_for_the_remote(git_repo) -> None:
    """`_PIN_REV` requires the literal `rev:`, so a document without it holds
    no pin and the rule has nothing to govern - it used to ask for the
    repository's remote anyway, and walk every line with two patterns, on
    every document. 5 of ruff's 650 hold `rev:`; on CI, where the remote is
    a spawn per document, the other 645 paid for it."""
    from extant import session as hc
    from extant.rules.pinned_ref import _pinned_refs

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    with hc.run_scope():
        ctx = hc.context(repo)
        assert _pinned_refs(ctx, "repo: https://github.com/acme/widget\n") == []
        assert str(repo) not in ctx.run.own_remote, "the remote was asked for nothing"
        _pinned_refs(ctx, "  - repo: https://github.com/acme/widget\n    rev: v1.0.0\n")
        assert str(repo) in ctx.run.own_remote


# --- a literal every match must contain, derived from the pattern ------------
#
# `leading_literals` reads the WORDS a match must begin with, and only from a
# pattern that opens with an alternation of them; the path-pointer pattern
# opens with a group nobody can derive words from - `\*\*(?:Plan|...)` or a
# `\bsee\b` - and is run per line over every line of every document, ungated:
# 0.54 s of a 5.9 s sequential sweep of ruff, 9%, for 5 pointers. What every
# match of it MUST contain is a backtick, and that is readable off the
# pattern too: a literal at the top level, outside every group and class,
# unescaped or escaped-as-itself, followed by no quantifier that could make
# it optional, in a pattern with no top-level `|`. Letters are refused - the
# pattern compiles with IGNORECASE - and so is VERBOSE, under which a space
# in the source is not a literal at all. A pattern offering no such
# character scans in full.


def test_the_default_path_pointer_requires_a_backtick() -> None:
    from extant.config import DEFAULTS
    from extant.text import required_literals

    assert required_literals(DEFAULTS["path_pointer"], re.IGNORECASE) == ("`",)


NO_REQUIRED_LITERAL = [
    pytest.param(r"see `([\w./-]+\.md)`|read ([\w./-]+\.md)", 0, id="top-level-bar"),
    pytest.param(r"(?:see `)([\w./-]+\.md)", 0, id="literal-only-inside-a-group"),
    pytest.param(r"see `?([\w./-]+\.md)`?", 0, id="optional-literal"),
    pytest.param(r"see `*([\w./-]+\.md)", 0, id="starred-literal"),
    pytest.param(r"see `{0,1}([\w./-]+\.md)", 0, id="braced-literal"),
    pytest.param(r"see [`'\"]([\w./-]+\.md)", 0, id="literal-inside-a-class"),
    pytest.param(r"see ([\w./-]+\.md)", 0, id="letters-and-spaces-only"),
    pytest.param(r"see\s+\d+", 0, id="escaped-classes-are-not-literals"),
    pytest.param(r"see . ([\w./-]+\.md)", 0, id="dot-is-not-a-literal"),
    pytest.param(r"see `([\w./-]+\.md)`", re.VERBOSE, id="verbose-flag"),
    pytest.param(r"(?x) see `([\w./-]+\.md)`", 0, id="inline-verbose-flag"),
]


@pytest.mark.parametrize("source, flags", NO_REQUIRED_LITERAL)
def test_a_pattern_with_no_mandatory_literal_gets_no_gate(source, flags) -> None:
    """Handed the COMPILED flags, as the scanner hands them: an inline `(?x)`
    is visible there and nowhere in the flags the caller passed."""
    from extant.text import required_literals

    assert required_literals(source, re.compile(source, flags).flags) == ()


REQUIRED_LITERAL = [
    pytest.param(r"see `([\w./-]+\.md)`", 0, ("`",), id="backticks-either-side"),
    pytest.param(r"see `([\w./-]+\.md)`:(\d+)", 0, ("`", ":"),
                 id="two-distinct-literals"),
    pytest.param(r"(?:see|read)\s+`([\w./-]+\.md)`", 0, ("`",),
                 id="alternation-inside-a-group"),
    pytest.param(r"see `([\w./-]+\.md)`+", 0, ("`",), id="plus-keeps-it-mandatory"),
    pytest.param(r"see \*\*([\w./-]+\.md)\*\*", 0, ("*",),
                 id="escaped-metacharacter"),
    pytest.param(r"see (?:`|')?([\w./-]+\.md):(\d+)", 0, (":",),
                 id="optional-group-then-literal"),
    pytest.param(r"See `([\w./-]+\.md)`", re.IGNORECASE, ("`",),
                 id="ignorecase-keeps-the-non-letters"),
]


@pytest.mark.parametrize("source, flags, expected", REQUIRED_LITERAL)
def test_a_mandatory_top_level_literal_is_derived(source, flags, expected) -> None:
    from extant.text import required_literals

    assert required_literals(source, re.compile(source, flags).flags) == expected


@pytest.mark.parametrize("line", [
    "**Plan:** `docs/plan.md`", "see `src/app.py:12` for it", "READ `X.MD` FIRST",
    "**Design:** the notes in `docs/design.md` and `docs/other.md`",
])
def test_the_gate_never_refuses_a_line_the_pattern_matches(line) -> None:
    """The property that makes the gate safe: a line missing a required
    literal cannot be matched. Each line here IS matched, asserted first so
    the test cannot pass on a fixture the regex ignores."""
    from extant.config import DEFAULTS
    from extant.text import required_literals

    pattern = re.compile(DEFAULTS["path_pointer"], re.IGNORECASE)
    assert pattern.search(line), f"fixture not matched by the pattern: {line!r}"
    required = required_literals(pattern.pattern, pattern.flags)
    assert required, "the default pattern offers a gate, or this test is vacuous"
    assert all(literal in line for literal in required)


def test_the_path_pointer_scan_skips_a_line_without_its_literal(
        git_repo, reconfigure) -> None:
    """The gate is in the scanner both `check` and `examined` read, so a
    line that cannot hold a pointer is never handed to the pattern - and a
    line that can is scanned exactly as before."""
    from extant import session as hc
    from extant.rules.path_pointer import _path_pointer_sites_uncached
    repo, _commit = git_repo

    recording = _Recording(hc._ACTIVE.path_pointer)
    reconfigure(path_pointer=recording)
    text = "see the plan for it\nsee `docs/plan.md` for it\nand nothing else\n"
    sites = _path_pointer_sites_uncached(hc.context(repo), text)
    assert [(number, raws) for number, _line, raws in sites] == [
        (2, ["docs/plan.md"])]
    assert recording.scans == 1, (
        f"the pattern was run on {recording.scans} lines; one carries a backtick")


def test_a_configured_pointer_pattern_without_a_literal_scans_every_line(
        git_repo, reconfigure) -> None:
    """The safety half. A pattern offering no mandatory character gets no
    gate, so every line reaches it and no pointer it would find is lost."""
    from extant import session as hc
    from extant.rules.path_pointer import _path_pointer_sites_uncached
    repo, _commit = git_repo

    recording = _Recording(re.compile(r"see ([\w./-]+\.md)", re.IGNORECASE))
    reconfigure(path_pointer=recording)
    text = "see docs/plan.md for it\nand nothing else\n"
    sites = _path_pointer_sites_uncached(hc.context(repo), text)
    assert [(number, raws) for number, _line, raws in sites] == [
        (1, ["docs/plan.md"])]
    assert recording.scans == 2


def test_a_letter_in_the_pattern_is_never_a_gate_under_ignorecase(
        git_repo, reconfigure) -> None:
    """`path_pointer` compiles with IGNORECASE, so `See` matches `see` and a
    gate on the capital would refuse the line the pattern accepts. Letters
    are excluded from the derivation for exactly this reason."""
    from extant import session as hc
    from extant.rules.path_pointer import _path_pointer_sites_uncached
    repo, _commit = git_repo

    reconfigure(path_pointer=re.compile(r"See `([\w./-]+\.md)`", re.IGNORECASE))
    sites = _path_pointer_sites_uncached(hc.context(repo), "see `docs/plan.md`\n")
    assert [raws for _number, _line, raws in sites] == [["docs/plan.md"]]


def test_a_top_level_alternative_without_the_literal_keeps_the_full_scan(
        git_repo, reconfigure) -> None:
    """A pattern reading `` `x` `` OR `read x`: the backtick is mandatory
    for one alternative and absent from the other, so it gates nothing."""
    from extant import session as hc
    from extant.rules.path_pointer import _path_pointer_sites_uncached
    repo, _commit = git_repo

    reconfigure(path_pointer=re.compile(
        r"see `([\w./-]+\.md)`|read ([\w./-]+\.md)", re.IGNORECASE))
    sites = _path_pointer_sites_uncached(hc.context(repo), "read docs/plan.md\n")
    assert [raws for _number, _line, raws in sites] == [[("", "docs/plan.md")]]


def test_the_backticked_sha_scan_skips_a_line_without_a_backtick(monkeypatch) -> None:
    """Both patterns the scan runs carry a literal backtick - `BACKTICKED`
    opens with one and `_LINKED_SHA` needs `` [` `` - so a line without one
    cannot match either, and neither is run on it. Checkable by reading the
    two patterns, which is the argument the line-pointer rule makes for its
    colon gate."""
    from extant import commits

    recording = _Recording(commits.BACKTICKED)
    monkeypatch.setattr(commits, "BACKTICKED", recording)
    text = "no code here\nfixed in `abc1234` yesterday\n1234567 bare and unread\n"
    assert commits._find_sha_candidates(text, lambda: None)[0] == [(2, "abc1234")]
    assert recording.scans == 1, (
        f"the backtick scan ran on {recording.scans} lines; one carries a backtick")
