"""dead-line-pointer: does the file this document cites have that many lines?"""
from __future__ import annotations

import re
from pathlib import Path

from extant.contract import Rule
from extant.finding import Finding
from extant.scope import Context
from extant.sites import resolve_reference
from extant.text import prose

__all__ = ["RULE", "check", "examined", "probe"]


# `core/engine.py:123` where that file has 40 lines. Derived from a
# 39-repository corpus measured 2026-08-04: 7,775 candidate sites, of which
# 6,525 sit outside a code block, 51 name a file this repository actually
# tracks, and 3 cite a line past its end. All three were real - plan documents
# instructing an implementer to edit a line of a file that has since shrunk.
#
# The narrow claim is deliberate. This does NOT ask whether line 123 still
# holds what the document says, which would be judging content and is the
# question no rule here may ask. It asks whether the file has that many lines.
#
# The 6,474 pointers naming something this repository does not track are left
# alone. They are pasted stack traces, third-party paths and example output,
# and whether a path exists is already `dead-path-pointer`'s question - asking
# it again here would report the same fault twice under two names.
_LINE_POINTER = re.compile(
    r"(?<![\w/.\\-])"
    r"((?:[\w.\-]+[/\\])*[\w.\-]+\.[A-Za-z]\w{0,9})"
    r":(\d{1,6})"
    r"(?![\w.])")
# Two narrowings the pattern makes silently, recorded so they are choices
# rather than accidents:
#
# A RANGE is read by its start. `SKILL.md:211-215` is checked at 211, so a
# file of 213 lines is not reported even though 214 and 215 are missing.
# Firing only when the FIRST cited line is already past the end keeps the
# claim unarguable; widening it to the range end is a separate measurement.
#
# Six digits at most. A line number of 1,234,567 does not match at all,
# rather than matching its first six digits and judging the wrong line.
# Documents citing a line past a million are not a population this was
# measured against.

# A generated bundle or a vendored blob is not something a document points
# into, and reading one per pointer is the only cost this rule can incur.
_LINE_COUNT_LIMIT = 2_000_000


def _line_count(ctx: Context, relative: str) -> int | None:
    """Lines in a tracked file, or None when it cannot be counted here.

    None means "do not judge": the path is absent, unreadable, or too large to
    be worth reading. A rule that treated None as zero would report every
    binary and every missing file as a pointer past the end.

    Counted in BINARY mode. Decoding first would make a file with one invalid
    byte unreadable, and the question here is how many newlines it has, which
    does not need the text. Memoised for the lifetime of a validate() call,
    like every other repository fact: a document citing forty lines of one
    file would otherwise read it forty times.
    """
    key = f"{ctx.repo}\0{relative}"
    if key in ctx.run.linecount:
        return ctx.run.linecount[key]
    count: int | None = None
    target = ctx.repo / relative
    try:
        if target.is_file() and target.stat().st_size <= _LINE_COUNT_LIMIT:
            with open(target, "rb") as handle:
                count = sum(1 for _ in handle)
    except (OSError, ValueError):
        count = None
    ctx.run.linecount[key] = count
    return count


# Identity-keyed like `_STRIPPED` and `_BARE_SHAS`, and for the same reason: the
# rule and the denominator ask for the same document's sites in the same pass.
# The repo and the format are compared as well, because unlike `_BARE_SHAS`
# this reads both - a cache that ignored them would answer a question it was
# never asked. `_STRIPPED` (extant/text.py) reads the format too, through
# _blank_uncached, but does not compare it - a known latent bug recorded
# there; this cache's format comparison is exactly what that one is missing.
# Measured on pytest's 308 documents: 617 calls, 1.19s.
_POINTER_SITES: "tuple[str, Path, str, list[tuple[int, str, int, int]]] | None" = None


def _forget_sites() -> None:
    """Drop the memo above.

    Called by `validate()` when it opens a FRESH run scope, and by
    `run_scope()` at both ends. The memo is not pure - it reads the filesystem
    through `_line_count` - so it has to be dropped whenever the answers it was
    built from are, and identity keying alone cannot see a checkout that moved
    under the same text object.

    It is deliberately NOT dropped when a call ENDS, which is the asymmetry the
    comment above describes: `count_examined` runs immediately after validate()
    returns and needs exactly this entry.

    Private. Before Task 10 the shim reached it directly as
    `_line_pointer._forget_sites()`, bypassing every sibling boundary; now
    `validate()` lives in the package too, and extant/registry.py's own
    `forget_memos` is the sibling call that reaches it - registry.py is the
    one module allowed to import a rule's private surface, for the reason its
    own docstring gives.
    """
    global _POINTER_SITES
    _POINTER_SITES = None


def _line_pointer_sites(ctx: Context, text: str) -> list[tuple[int, str, int, int]]:
    """Pointers this rule can actually decide, as (line, target, cited, total).

    The DENOMINATOR, computed exactly where the rule computes its findings, so
    the two describe one population. A pointer whose target this repository
    does not track is not counted: the rule cannot decide it, and reporting
    coverage it does not have is worse than reporting none.
    """
    global _POINTER_SITES
    if (_POINTER_SITES is not None and _POINTER_SITES[0] is text
            and _POINTER_SITES[1] == ctx.repo
            and _POINTER_SITES[2] == ctx.doc.doc_format):
        return _POINTER_SITES[3]
    sites = _line_pointer_sites_uncached(ctx, text)
    _POINTER_SITES = (text, ctx.repo, ctx.doc.doc_format, sites)
    return sites


def _line_pointer_sites_uncached(
        ctx: Context, text: str) -> list[tuple[int, str, int, int]]:
    sites: list[tuple[int, str, int, int]] = []
    for number, line in enumerate(prose(ctx.doc, text).splitlines(), start=1):
        for match in _LINE_POINTER.finditer(line):
            raw, cited = match.group(1), int(match.group(2))
            if cited < 1:
                continue
            exists, _actual = resolve_reference(ctx, ctx.repo, raw)
            if not exists:
                continue
            total = _line_count(ctx, raw)
            if total is None:
                continue
            sites.append((number, raw, cited, total))
    return sites


def check(ctx: Context, text: str) -> list[Finding]:
    """A cited line number that is past the end of the file it cites.

    The file is here and git tracks it; the line is not. That is settled by
    counting newlines, and nothing about it is a judgement.

    Whole-file and in the archive, like path pointers: a pointer is an
    instruction at any age, and retiring the entry that holds it does not make
    line 211 of a 167-line file exist.
    """
    findings: list[Finding] = []
    for number, raw, cited, total in _line_pointer_sites(ctx, text):
        if cited <= total:
            continue
        findings.append(Finding(
            number, "dead-line-pointer",
            f"points at `{raw}:{cited}`, but that file has {total} line"
            f"{'' if total == 1 else 's'}",
            subject=f"{raw}:{cited}"))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Pointers whose target this repository tracks and can count.

    One naming a file we do not have is not counted: the rule cannot decide it,
    and `dead-path-pointer` already asks whether a path exists. On a
    39-repository corpus that was 51 of 6,525.
    """
    return len(_line_pointer_sites(ctx, text))


def probe(ctx: Context, text: str) -> str | None:
    """Push a real line pointer past the end of the file it names.

    Located BY LINE, like the manifest probe: the first `path:number` in a
    document is often inside a transcript that the rule never reads, so a
    pattern-located probe would corrupt something invisible and then report
    that the rule did not fire.

    Returns None when this document cites no line of a file this repository
    tracks, which is the ordinary case.
    """
    sites = _line_pointer_sites(ctx, text)
    if not sites:
        return None
    number, raw, cited, total = sites[0]
    lines = text.splitlines(keepends=True)
    index = number - 1
    if index >= len(lines):
        return None
    needle = f"{raw}:{cited}"
    if needle not in lines[index]:
        return None
    lines[index] = lines[index].replace(needle, f"{raw}:{total + 9999}", 1)
    return "".join(lines)


RULE = Rule(
    kind="dead-line-pointer",
    sequence=13,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does the cited file have at least that many lines?",
    probe=probe,
    examined=examined,
)
