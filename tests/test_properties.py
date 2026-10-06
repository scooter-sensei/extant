"""Six invariants, held as properties: Hypothesis generates the inputs.

An example test holds the cases somebody thought of. These hold claims the
package makes about EVERY input - the offset contract `strip_code` and
`prose` keep, the two line numberings, the `exclude_paths` matcher against
git's own, link-target decoding, the grouping of parallel findings, and the
completeness of the SHA scanners - and let Hypothesis look for the input
that breaks one. The pilot runs found two defects 1,566 example tests had
not: a finding grouped with itself under a directory literally named `*`,
at once, and a `**` that crossed separators where git reads a `*` (Phase
62) - that one not on the first run, as the last paragraph says.

How they run is set in tests/conftest.py: derandomized, without a
database, and with Hypothesis's mining of constants from imported modules
held off, so which examples a property tries is a function of the commit,
of the Hypothesis version requirements-test.txt pins, and - for 4a, which
draws from `st.characters` - of the Python version's Unicode tables.
tests/test_property_settings.py holds all of that from outside this module,
and that this module runs at all. `--hypothesis-profile=explore` searches
ten times as far, at random.

A property that cannot fail proves nothing. Each was watched failing
against a mutation of the code it guards, and the mutations the rest of the
suite let pass are anchors in tests/harnesses/mutate.py.

A property is also only as strong as what it generates. The first generator
for the matcher drew paths independently of the pattern. It passed 300
random examples, and every derandomized set of a size CI runs; it found the
defect only at 1,000 random examples a run. Paths built FROM the pattern
found it in a derandomized set of 25. So every strategy below is aimed at
where its function's mistakes would live, and says how.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Literal

import pytest

if sys.version_info < (3, 10):
    # Not a missing install: Hypothesis dropped 3.9 in 6.142.0 (2025-10-16),
    # 6.141.1 the last release that installs there, and requirements-test.txt
    # installs it from 3.10 on. On 3.10+ a missing Hypothesis is a collection
    # error below, never this skip - and tests/test_property_settings.py
    # fails if this skip is ever taken there.
    pytest.skip("Hypothesis needs Python 3.10; the properties run on every "
                "other leg", allow_module_level=True)

from hypothesis import example, given, settings
from hypothesis import strategies as st

from extant.commits import (
    BACKTICKED, _ASSET_PATH, _HEX_WORDS, _LINKED_BARE_SHA, _LINKED_SHA,
    _PINNED_REF, _URL, _UUID, _range_ends, find_bare_sha_candidates,
    find_sha_candidates, looks_like_bare_sha, looks_like_sha, translate_shas,
)
from extant.exclusions import _exclusion_regex
from extant.finding import Finding, Located
from extant.git import environment
from extant.links import percent_decoded
from extant.refs import SHA_SHAPE, normalise_remote
from extant.report import group_parallel
from extant.rewrites import translated_value
from extant.scope import DocScope
from extant.text import (
    line_breaks, line_number_at, lone_cr_to_lf, prose, strip_code,
)


# --------------------------------------------------------------------------
# 1. Blanking keeps every offset
# --------------------------------------------------------------------------
#
# The first contract extant/text.py states for its callers: code is blanked
# with SPACES, so a span found in the blanked text indexes the same
# characters in the original - broken once on CRLF, at a cost of 1627
# characters on one document. Generated as LINES of markup fragments, not
# as characters: a fence, a list marker, an HTML block or an rst directive
# is several characters that mean nothing apart, and most of them mean
# something only at the start of a line - fragments strung together put a
# `>>> ` there so rarely that a doctest line ending in CRLF, the shape the
# rst loop's terminator handling exists for, was never built. Every
# terminator spelling ends some line, and so do the breaks `splitlines()`
# honours and `LINE_BREAK` does not.
OPENERS = ["", "", "    ", "  ", "\t", "> ", "- ", "* ", "1. ", ">>> ", "... ",
           ":   ", "```", "~~~", "````", ".. code-block:: py", "<!--", "<pre>",
           "<div>", "<script>", ":::", "!!! note", '=== "t"', "<Tabs>", "# "]
FRAGMENTS = ["a", "b", " ", "`", "``", "```", "abc1234", "[l](x.md)", "::",
             "-->", "</pre>", "</div>", "</script>", "</Tabs>", "|", "#",
             "\u00a0"]
ENDINGS = ["\n", "\n", "\r\n", "\r\n", "\r", "", "\f", "\v", "\x1c", "\x85",
           "\u2028"]
LINE = st.builds(lambda opener, body, ending: opener + "".join(body) + ending,
                 st.sampled_from(OPENERS),
                 st.lists(st.sampled_from(FRAGMENTS), max_size=5),
                 st.sampled_from(ENDINGS))
DOCUMENTS = st.lists(LINE, max_size=12).map("".join)
# The three markdown readings - no path, `.md`, `.mdx`, which has no
# indented code - and reStructuredText, whose blanking is a separate loop.
SCOPES = st.sampled_from([
    DocScope(), DocScope(doc_path="d.md"), DocScope(doc_path="d.mdx"),
    DocScope(doc_format="rst", doc_path="d.rst"),
])


@given(DOCUMENTS, SCOPES)
@example("```\r\ncode\r\n```\r\ntext `a`\r\n", DocScope())
@example(".. code-block:: py\r\n\r\n   x = 1\r\n\r\ntext\r\n",
         DocScope(doc_format="rst", doc_path="d.rst"))
def test_blanking_keeps_every_offset(text: str, doc: DocScope) -> None:
    """Same length, same breaks, and every character either the original
    or a space - never a break blanked. The one rewrite is `_blank`'s own:
    a bare `\\r` read as `\\n`, which is length-preserving by design. And
    `strip_code` blanks everything `prose` does: it adds inline spans."""
    original = lone_cr_to_lf(text)
    stripped, kept = strip_code(doc, text), prose(doc, text)
    for blanked in (stripped, kept):
        assert len(blanked) == len(text)
        assert line_breaks(blanked) == line_breaks(text)
        moved = [(i, was, now) for i, (was, now) in enumerate(zip(original, blanked))
                 if now != was and (now != " " or was in "\r\n")]
        assert not moved, moved[:5]
    narrower = [i for i, (was, p, s) in enumerate(zip(original, kept, stripped))
                if p == " " and was != " " and s != " "]
    assert not narrower, narrower[:5]


# --------------------------------------------------------------------------
# 2. The two line numberings
# --------------------------------------------------------------------------
#
# Thirteen sites number lines by `splitlines()` and two by `line_number_at`
# (its docstring keeps the ledger). They agree everywhere except the one
# character `line_number_at` documents - the `\n` of a CRLF - and except
# the eight breaks only `splitlines()` honours, measured on 0.014 per cent
# of documents and closed on that number. Bare `\r` needs no exclusion: both
# read it as a break.
SPLITLINES_ONLY = "\f\v\x1c\x1d\x1e\x85\u2028\u2029"


def _splitlines_line(text: str, offset: int) -> int:
    start = 0
    for number, piece in enumerate(text.splitlines(keepends=True), start=1):
        if start <= offset < start + len(piece):
            return number
        start += len(piece)
    raise AssertionError(f"offset {offset} is past the text")


@given(st.text(alphabet="ab \t`#\n\r", max_size=80))
def test_line_number_at_agrees_with_splitlines(text: str) -> None:
    """Every offset, off the eight breakers, but the `\\n` of a CRLF."""
    for offset, char in enumerate(text):
        if char == "\n" and offset and text[offset - 1] == "\r":
            continue
        assert line_number_at(text, offset) == _splitlines_line(text, offset), offset


@given(st.text(alphabet="ab \n\r" + SPLITLINES_ONLY, max_size=80))
def test_line_number_at_agrees_with_line_breaks(text: str) -> None:
    """Its own contract, which holds on every input: the breaks, in every
    spelling, that start before the offset, plus one."""
    for offset in range(len(text) + 1):
        assert line_number_at(text, offset) == line_breaks(text[:offset]) + 1, offset


# --------------------------------------------------------------------------
# 3. exclude_paths, against git check-ignore
# --------------------------------------------------------------------------
#
# The matcher is documented as gitignore-shaped, so git is the oracle. The
# alphabet leaves out what it does not implement and names instead - a
# leading `!`, `[`, backslash escapes, a leading `#`, surrounding spaces -
# and git runs with `core.ignorecase` off, the case rule config.md states.
#
# Paths are built FROM each pattern: every star run and `?` replaced by a
# fill that may or may not cross a separator, plus a prefix, plus unrelated
# paths. That is where a matcher's mistakes live. Paths drawn apart from the
# pattern reached the star-run defect this property found (Phase 62; seven
# of the eleven patterns tests/test_exclude_paths.py records against git)
# only at 1,000 random examples a run, and in no derandomized set CI could
# afford; built from it, they reach it in 25.
#
# Batched for cost: up to twenty patterns per example, each in its own
# directory's `.gitignore` - a pattern there is relative to that directory,
# as one here is to the repository - and one `check-ignore` for all of them.
PATTERN_PIECES = ["a", "b", "A", ".", "-", "_", "*", "?", "**", "***"]
SEGMENT = st.lists(st.sampled_from(PATTERN_PIECES), min_size=1, max_size=4).map("".join)
PATTERNS = st.builds(
    lambda rooted, segments, directory: (("/" if rooted else "") + "/".join(segments)
                                         + ("/" if directory else "")),
    st.booleans(), st.lists(SEGMENT, min_size=1, max_size=3), st.booleans())
NAME = st.lists(st.sampled_from(["a", "b", "A", ".", "-", "_", "ab", "x", "xb"]),
                min_size=1, max_size=3).map("".join)
UNRELATED = st.lists(NAME, min_size=1, max_size=4).map("/".join)
_WILD = re.compile(r"\*+|\?")
BATCH = 20


def _a_path(path: str) -> bool:
    """What `git ls-files` can list: no empty, `.` or `..` segment."""
    return all(part not in ("", ".", "..") for part in path.split("/"))


@st.composite
def pattern_and_paths(draw: st.DrawFn) -> tuple[str, list[str]]:
    pattern = draw(PATTERNS)
    paths = set(draw(st.lists(UNRELATED, max_size=6)))
    for _ in range(draw(st.integers(1, 6))):
        fill = st.sampled_from(["", "a", "ab", "a/b", "b/a", "x"])
        one = st.sampled_from(["a", "/", ""])
        body = _WILD.sub(lambda m: draw(one if m.group() == "?" else fill), pattern)
        body = body.strip("/")
        if pattern.endswith("/"):
            body += "/" + draw(st.sampled_from(["x", "x/y"]))
        paths.add(body)
        paths.add(draw(st.sampled_from(["", "b/", "a/b/"])) + body)
    return pattern, sorted(p for p in paths if _a_path(p))


@pytest.fixture(scope="module")
def ignore_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("check-ignore")
    subprocess.run(["git", "init", "-q", str(root)], check=True,
                   capture_output=True, env=environment())
    # The operator's global excludes file is read by check-ignore too.
    (root / "no-global-excludes").touch()
    return root


def _a_twentieth_of_the_budget() -> int:
    """The loaded profile's `max_examples` over twenty, and at least one."""
    loaded = settings.default
    assert loaded is not None, "no Hypothesis profile is loaded"
    budget = loaded.max_examples
    assert isinstance(budget, int), budget
    return max(1, budget // 20)


@settings(max_examples=_a_twentieth_of_the_budget())
@given(cases=st.lists(pattern_and_paths(), min_size=1, max_size=BATCH))
@example(cases=[("a/**b", ["a/xb", "a/x/b"]), ("a**/a", ["a/a", "aaa"]),
                ("***/b", ["b", "x/b"]), ("docs/?.md", ["docs/a.md", "docs/a/b.md"])])
def test_exclusion_agrees_with_git_check_ignore(
        ignore_tree: Path, cases: list[tuple[str, list[str]]]) -> None:
    for n in range(BATCH):
        stale = ignore_tree / f"p{n}" / ".gitignore"
        if stale.exists():
            stale.unlink()
    queries: list[str] = []
    ours: set[str] = set()
    for n, (pattern, paths) in enumerate(cases):
        (ignore_tree / f"p{n}").mkdir(exist_ok=True)
        (ignore_tree / f"p{n}" / ".gitignore").write_text(pattern + "\n", encoding="utf-8")
        regex = _exclusion_regex(pattern)
        assert regex is not None, pattern
        for path in paths:
            queries.append(f"p{n}/{path}")
            if regex.match(path):
                ours.add(f"p{n}/{path}")
    done = subprocess.run(
        ["git", "-C", str(ignore_tree), "-c", "core.ignorecase=false",
         "-c", f"core.excludesFile={ignore_tree / 'no-global-excludes'}",
         "check-ignore", "--stdin", "--no-index", "-z", "-v", "--non-matching"],
        input=b"".join(q.encode("utf-8") + b"\0" for q in queries),
        capture_output=True, env=environment())
    assert done.returncode in (0, 1), done.stderr
    # <source> <line> <pattern> <path>, four fields per path asked about; a
    # path no pattern matched comes back with an empty source.
    fields = done.stdout.split(b"\0")
    theirs = {fields[i + 3].decode("utf-8") for i in range(0, len(fields) - 3, 4)
              if fields[i].endswith(b".gitignore")}
    wrong = {n: (pattern, sorted(p for p in ours - theirs if p.startswith(f"p{n}/")),
                 sorted(p for p in theirs - ours if p.startswith(f"p{n}/")))
             for n, (pattern, _) in enumerate(cases)}
    assert ours == theirs, {n: w for n, w in wrong.items() if w[1] or w[2]}


# --------------------------------------------------------------------------
# 4. Percent-decoding a link target
# --------------------------------------------------------------------------
#
# Mostly the standard library's behaviour, held because every Python leg
# runs it and `percent_decoded` makes a promise of its own: a target with
# no escape in it comes back as written - a literal `%` or `+` is never
# rewritten into something else.
_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


# Surrogates, which no `str` a document holds can carry.
_NO_SURROGATES: tuple[Literal["Cs"]] = ("Cs",)


@given(st.text(st.characters(exclude_categories=_NO_SURROGATES), max_size=40))
def test_percent_decoding_undoes_percent_encoding(target: str) -> None:
    from urllib.parse import quote
    assert percent_decoded(quote(target, safe="/")) == target


@given(st.text(alphabet="ab%/.0129AFfgz+ ", max_size=30))
def test_a_target_without_an_escape_is_left_as_written(target: str) -> None:
    if not _ESCAPE.search(target):
        assert percent_decoded(target) == target


# --------------------------------------------------------------------------
# 5. Grouping parallel findings is a partition
# --------------------------------------------------------------------------
#
# `group_parallel`'s docstring: every finding appears in exactly one group.
# And what makes a group: one rule, one stratum, one side of `primary`, one
# segment allowed to vary. Paths draw on segments that recur - translations,
# a filename two documents share, and `*`, which a directory can be named.
# Messages name path segments in backticks, the only place the key masks.
SEGMENTS = st.sampled_from(["docs", "en", "ko", "a", "b", "*", "x.md", "y.md"])
LOCATED = st.builds(
    lambda parts, line, kind, detail, primary, stratum: Located(
        "/".join(parts), Finding(line, kind, detail), primary, stratum=stratum),
    st.lists(SEGMENTS, min_size=1, max_size=4), st.integers(1, 5),
    st.sampled_from(["dead-md-link", "dead-sha"]),
    st.sampled_from(["`x.md` is gone", "`en/x.md` is gone", "`ko` is gone", "gone"]),
    st.booleans(), st.sampled_from(["ordinary", "vendored"]))


@given(st.lists(LOCATED, max_size=12))
def test_grouping_is_a_partition(located: list[Located]) -> None:
    groups = group_parallel(located)
    flat = [item for group in groups for item in group]
    assert Counter(map(id, flat)) == Counter(map(id, located)), [
        [item.path for item in group] for group in groups]
    for group in groups:
        assert group == sorted(group, key=lambda i: (i.path, i.finding.line))
        assert len({(i.finding.kind, i.stratum, i.primary) for i in group}) == 1
        parts = [item.path.split("/") for item in group]
        assert len({len(p) for p in parts}) == 1, [i.path for i in group]
        varying = [k for k in range(len(parts[0])) if len({p[k] for p in parts}) > 1]
        assert len(varying) <= 1, [i.path for i in group]
    firsts = [(g[0].path, g[0].finding.line) for g in groups]
    assert firsts == sorted(firsts)


# --------------------------------------------------------------------------
# 6. Every SHA-shaped token is examined, or skipped for a NAMED reason
# --------------------------------------------------------------------------
#
# The completeness claim behind a "skipped by reason" count: nothing shaped
# like a commit falls through the two scanners in extant/commits.py
# unexamined and unexplained. The model below is written from their
# docstrings, one named reason per skip the code makes; the property is
# that the scanners examine exactly what the model says and the model has a
# name for everything else. It checks how the skips COMPOSE - which side
# reads a token, which span sets it aside, and that nothing falls between -
# not whether each span's pattern is right, which is the corpus's question.
#
# Measured over the corpus the same way (extant-hardening's m22_sha_reasons.py,
# Phase 62): 139 repositories, 82,912 documents, 94,918 tokens examined,
# 0 unaccounted, sixteen reasons seen. The two not seen are a backticked hex
# word and a run joined to a non-ASCII letter - `\w` is Unicode, so a commit
# written against Chinese text with no space is no token at all.
#
# The population: a run of seven or more lowercase hex characters with no
# ASCII letter, digit or underscore on either side. Upper case is outside it:
# neither scanner reads it.
POPULATION = re.compile(r"(?<![0-9A-Za-z_])[0-9a-f]{7,}(?![0-9A-Za-z_])")
_WORD = re.compile(r"\w")
_DIGEST = "a1" * 16

# Every reason the model can give, with a line and an origin that reach it.
REASONS = {
    "backticked: a number": ("`1234567`", None),
    "backticked: 32 characters, a digest": (f"`{_DIGEST}`", None),
    "backticked: no digit": ("`deadbeef`", None),
    "backticked: a word spelled in hex": ("`ed25519`", None),
    "backticked: the text of a commit link elsewhere":
        ("[`abc1234`](https://github.com/f/z/commit/abc1234)", "o/r"),
    "backticked: the text of a relative commit link":
        ("[`abc1234`](../../commit/abc1234)", None),
    "in backticks: part of a longer code span": ("`git show abc1234`", None),
    "bare: a '#' colour": ("fill #abc1234 here", None),
    "bare: longer than a full object name": ("a" * 40 + "1", None),
    "bare: joined to a non-ASCII word character": ("\u63d0\u4ea4abc1234", None),
    "bare: inside a URL": ("see https://x.y/abc1234", None),
    "bare: part of a UUID": ("f43eb21b-84cb-49e7-90fb-56595df594e6", None),
    "bare: inside an asset filename": ("img/abc1234-shot.png", None),
    "bare: a ref pinned to another repository": ("uses: o/r@abc1234", None),
    "bare: a commit link elsewhere":
        ("[abc1234](https://github.com/f/z/commit/abc1234)", "o/r"),
    "bare: the text of a relative commit link": ("[abc1234](../../commit/abc1234)", None),
    "bare: a number": ("1234567", None),
    "bare: 32 characters, a digest": (_DIGEST, None),
    "bare: no digit": ("deadbeef", None),
    "bare: a word spelled in hex": ("ed25519", None),
}


def _covered(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    return any(s < span[1] and span[0] < e for s, e in spans)


def _links(pattern: re.Pattern[str], line: str, own: str | None,
           whole: bool) -> list[tuple[tuple[int, int], bool]]:
    """(span, relative) for each commit link a scanner sets aside: a
    relative one's TEXT, and the text - or the whole link - of one that
    is not this repository's or cannot be told to be."""
    out = []
    for m in pattern.finditer(line):
        head = m.group("head")
        if not head or head.startswith("."):
            out.append((m.span(1), True))
        elif own is None or normalise_remote(head) != own:
            out.append((m.span() if whole else m.span(1), False))
    return out


def _shape(token: str) -> str:
    if len(token) == 32:
        return "32 characters, a digest"
    if token.lower() in _HEX_WORDS:
        return "a word spelled in hex"
    if not any(c.isalpha() for c in token):
        return "a number"
    return "no digit"


def model(line: str, own: str | None) -> tuple[list[str], list[str], Counter[str]]:
    """(examined backticked, examined bare, why each other token was not)."""
    backticked: list[str] = []
    bare: list[str] = []
    why: Counter[str] = Counter()
    links = _links(_LINKED_SHA, line, own, whole=False)
    ticks = []
    for m in BACKTICKED.finditer(line):
        ticks.append(m.span())
        for end in _range_ends(m.group(1)):
            if not SHA_SHAPE.match(end):
                continue
            linked = [relative for span, relative in links if _covered(m.span(1), [span])]
            if linked:
                why["backticked: the text of a relative commit link" if linked[0]
                    else "backticked: the text of a commit link elsewhere"] += 1
            elif looks_like_sha(end):
                backticked.append(end)
            else:
                why["backticked: " + _shape(end)] += 1
    named = [
        ("bare: inside a URL", [m.span() for m in _URL.finditer(line)]),
        ("bare: part of a UUID", [m.span() for m in _UUID.finditer(line)]),
        ("bare: inside an asset filename", [m.span() for m in _ASSET_PATH.finditer(line)]),
        ("bare: a ref pinned to another repository",
         [m.span() for m in _PINNED_REF.finditer(line)]),
    ]
    bare_links = _links(_LINKED_BARE_SHA, line, own, whole=True)
    for m in POPULATION.finditer(line):
        token, span = m.group(), m.span()
        inside = [(s, e) for s, e in ticks if s <= span[0] and span[1] <= e]
        if inside:
            s, e = inside[0]
            if token not in _range_ends(line[s + 1:e - 1]):
                why["in backticks: part of a longer code span"] += 1
            continue                    # otherwise the backticked side read it
        before = line[span[0] - 1] if span[0] else ""
        after = line[span[1]] if span[1] < len(line) else ""
        label = next((name for name, spans in named if _covered(span, spans)), None)
        linked = [relative for s, relative in bare_links if _covered(span, [s])]
        if before == "#":
            why["bare: a '#' colour"] += 1
        elif len(token) > 40:
            why["bare: longer than a full object name"] += 1
        elif _WORD.match(before) or _WORD.match(after):
            why["bare: joined to a non-ASCII word character"] += 1
        elif label is not None:
            why[label] += 1
        elif linked:
            why["bare: the text of a relative commit link" if linked[0]
                else "bare: a commit link elsewhere"] += 1
        elif looks_like_bare_sha(token):
            bare.append(token)
        else:
            why["bare: " + _shape(token)] += 1
    return backticked, bare, why


HEX = ["abc1234", "abc12345", "a1b2c3d4e5f6", "1234567", "deadbeef", "ed25519",
       _DIGEST, "a" * 39 + "1", "a" * 40 + "1", "ABC1234", "abc1234..def5678",
       "abc1234...def5678"]
AROUND = [" ", "`", "``", "[", "]", "](", ")", "https://x.y/", "git@h:", "#",
          "_", "-", "/", "@", "o/r@", ".png", "x", "../commit/",
          "https://github.com/o/r/commit/", "https://github.com/f/z/commit/",
          "f43eb21b-84cb-49e7-90fb-56595df594e6", ".", "\u63d0", "\u00e9",
          "\u3002"]
LINES = st.lists(st.sampled_from(HEX + AROUND), max_size=14).map("".join)
ORIGINS = st.sampled_from([None, "o/r", "f/z"])


def _with_every_reason(test: Callable[..., None]) -> Callable[..., None]:
    """One explicit example per named reason, so each is tried however
    generation goes."""
    for line, own in REASONS.values():
        test = example([line], own)(test)
    return test


@given(st.lists(LINES, min_size=1, max_size=4), ORIGINS)
@_with_every_reason
@example(["see abc1234 now", "`abc1234`", "`abc1234..def5678`"], None)
@example(["[abc1234](https://github.com/o/r/commit/abc1234)"], "o/r")
def test_every_sha_shaped_token_is_examined_or_named(
        lines: list[str], own: str | None) -> None:
    text = "\n".join(lines)
    expected_backticked: list[tuple[int, str]] = []
    expected_bare: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        backticked, bare, why = model(line, own)
        assert set(why) <= set(REASONS), set(why) - set(REASONS)
        expected_backticked += [(number, t) for t in backticked]
        expected_bare += [(number, t) for t in bare]
    assert sorted(find_sha_candidates(text, lambda: own)) == sorted(expected_backticked)
    assert sorted(find_bare_sha_candidates(text, lambda: own)) == sorted(expected_bare)


def test_every_named_reason_is_reached() -> None:
    """The list of reasons is the claim, so each must be reachable: a reason
    nothing can produce any more is a skip that silently became something
    else."""
    unreached = {reason for reason, (line, own) in REASONS.items()
                 if not model(line, own)[2][reason]}
    print(f"checked {len(REASONS)} named reasons")
    assert not unreached, unreached


# --------------------------------------------------------------------------
# 7. `--sha-map` changes only the tokens it maps, and every one it reports
# --------------------------------------------------------------------------
#
# The one mode that WRITES documents (gate.py writes `translate_shas`' text
# back to disk), and until Phase 64 nothing compared its output whole: the
# tests were one-line inputs asserted with `in`, and the fuzz oracle reads
# crash, exit and denominator, not text. mutmut found a separator joined
# between every line, the same inside a line holding a bare rewrite, an
# all-digit backticked token losing its backticks, and every `continue` ->
# `break` that left the later tokens on a line untranslated - each surviving
# the whole suite. Three claims, all from the docstring:
# 1. an empty map is a no-op, byte for byte;
# 2. a rewrite keeps the document's length, and changes nothing but whole
#    hex runs the scanners read as commits, each into exactly its mapped
#    value - `translated_value` truncates to the token's length;
# 3. no token the scanners report survives with a mapping: what `dead-sha`
#    reports, `--sha-map` repairs (the EX-8 argument).
#
# The map is drawn from fixed old ids, so the tokens can be built FROM it -
# the matcher property's lesson. Two share an eight-character prefix, so a
# short token is ambiguous and must stay; one opens with seven digits, so an
# all-digit range end prefixes it and must stay too. New ids open with
# letters no old id does, so no rewrite is itself rewritable.
OLD_IDS = ["a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
           "a1b2c3d4ffff0000111122223333444455556666",
           "b7e6d5c4b3a2918273645546372819a0b1c2d3e4",
           "1234567abc0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f"]
NEW_IDS = ["c0ffee11" + "c" * 32, "d00d2222" + "d" * 32,
           "e1e1e333" + "e" * 32, "f4f4f444" + "f" * 32]
MAP_TOKENS = [old[:n] for old in OLD_IDS for n in (7, 10, 40)] + [
    "1234567", "deadbeef", "ed25519", _DIGEST, "ABC1234", "c0d1e2f"]
_UUID_TAIL = "-84cb-49e7-90fb-56595df594e6"
WRAPPED = st.one_of(
    st.sampled_from(MAP_TOKENS),
    st.sampled_from(MAP_TOKENS).map(lambda t: f"`{t}`"),
    st.builds(lambda a, sep, b: f"`{a}{sep}{b}`", st.sampled_from(MAP_TOKENS),
              st.sampled_from(["..", "..."]), st.sampled_from(MAP_TOKENS)),
    st.sampled_from(MAP_TOKENS).map(lambda t: f"https://github.com/o/r/commit/{t}"),
    st.sampled_from(MAP_TOKENS).map(lambda t: f"o/r@{t}"),
    st.sampled_from(MAP_TOKENS).map(lambda t: f"[`{t}`](https://github.com/f/z/commit/{t})"),
    st.sampled_from(MAP_TOKENS).map(lambda t: f"[{t}](../../commit/{t})"),
    st.sampled_from(MAP_TOKENS).map(lambda t: f"#{t}"),
    st.sampled_from(OLD_IDS).map(lambda old: old[:8] + _UUID_TAIL),
)
MAP_LINE = st.lists(st.tuples(st.sampled_from([" ", "", "x", ", ", "`", "[", "]("]),
                              WRAPPED), max_size=5).map(
    lambda items: "".join(sep + token for sep, token in items))
MAP_DOCUMENTS = st.builds(
    lambda lines, ending, last: ending.join(lines) + (ending if last else ""),
    st.lists(MAP_LINE, min_size=1, max_size=5), st.sampled_from(["\n", "\r\n"]),
    st.booleans())
MAPS = st.sets(st.integers(0, len(OLD_IDS) - 1)).map(
    lambda picked: {OLD_IDS[i]: NEW_IDS[i] for i in sorted(picked)})
_HEX_RUN = re.compile(r"[0-9A-Fa-f]+")
_EVERY_ID = dict(zip(OLD_IDS, NEW_IDS))


@given(MAP_DOCUMENTS, MAPS)
@example("see `1234567` and `b7e6d5c` now\n", _EVERY_ID)
@example("a `b7e6d5c..1234567` range\n", _EVERY_ID)
@example("one b7e6d5c\ntwo a1b2c3d4e5\r\n", _EVERY_ID)
@example("`a1b2c3d` x b7e6d5c", _EVERY_ID)
@example("deadbeef b7e6d5c", _EVERY_ID)
@example("c0d1e2f b7e6d5c", _EVERY_ID)
def test_sha_map_changes_only_what_it_maps_and_repairs_what_is_reported(
        text: str, mapping: dict[str, str]) -> None:
    assert translate_shas(text, {}) == (text, 0)
    out, count = translate_shas(text, mapping)
    assert len(out) == len(text), (text, out)
    assert ([line[len(line.rstrip("\r\n")):] for line in out.splitlines(True)]
            == [line[len(line.rstrip("\r\n")):] for line in text.splitlines(True)])
    runs = [m.span() for m in _HEX_RUN.finditer(text)]
    changed = 0
    for start, end in runs:
        token = text[start:end]
        if out[start:end] != token:
            changed += 1
            assert looks_like_sha(token) or looks_like_bare_sha(token), token
            assert out[start:end] == translated_value(token, mapping), token
    inside = {i for start, end in runs for i in range(start, end)}
    moved = [i for i, (was, now) in enumerate(zip(text, out))
             if was != now and i not in inside]
    assert not moved, (text, out)
    assert count >= changed
    left = [token for _number, token in (find_sha_candidates(out, lambda: None)
                                         + find_bare_sha_candidates(out, lambda: None))
            if translated_value(token, mapping) is not None]
    assert not left, (text, out, left)
