"""Reading a document: what is code, what is prose, where its lines break.

Everything here is about the TEXT in front of it, which is what separates this
module from `refs.py` beside it. Most of it is pure, and the exceptions are the
three functions that ask the repository which documents exist.

There was a fourth question - what anchors a document offers - and it left for
`anchors.py` when this module hit its 923-line ceiling. The split was chosen
over raising the number because the anchor machinery was the one part with no
reader on this side of the cut.

Three calling conventions, and the split is deliberate rather than untidy:

* Pure functions take what they read and nothing else. `percent_decoded`,
  `line_breaks`, `_line_and_terminator` and the rest cannot be affected by a
  repository or a run, so handing them a Context would be a claim about their
  dependencies that is simply false.
* `current_document`, `_blank`, `_blank_uncached`, `strip_code` and `prose`
  take
  a `DocScope`, because the only ambient thing they read is which document is
  open and what language it is written in.
* `unique_basename`, `_translation_tree` and `numbered_document` take the full
  `Context`: they ask git what it tracks and memoise the answer on the run.

The alternative - one `Context` parameter everywhere - was rejected because the
one thing this split is for is making a module's dependencies legible from its
signature, and a `Context` on `prose()` would advertise a repository, a git
seam and a configuration that it never touches. It would also have to be
CONSTRUCTED by every caller that has none, which for `prose` means inventing a
repository path, and an invented value in a field named `repo` is the kind of
false claim this project keeps paying for.

`_STRIPPED` stays a module-level memo here for the reason extant/scope.py gives
for leaving it out of RunScope: it is keyed on the IDENTITY of the text passed
in. That key is INCOMPLETE, not absent, and extant/scope.py now says so
directly rather than claiming otherwise. `_blank_uncached` below also reads
`doc.doc_format` - markdown and reStructuredText strip code differently - so
the cached VALUE depends on the format as well as the text, while the cache
key does not. A known latent bug, recorded but not fixed here: a caller that
validates the same text object twice under two different formats - once with
`doc_format="markdown"`, once with `"rst"` - gets back whichever result was
computed first, both times. `--sweep` is the mode that changes `doc_format`
per document within one run, which is what makes the condition real rather
than theoretical.
"""
from __future__ import annotations

import bisect
import re
import subprocess
from pathlib import Path

from extant.refs import tracked_markdown
from extant.scope import Context, DocScope

# TWO of these thirty-four names are public, and the rule is the same one
# every module in this package follows: a name is public when a SIBLING MODULE
# calls it, and keeps its underscore when it does not.
#
# `current_document` and `ORDER_PREFIX` are the two, and sites.py calls both.
# Reaching for an underscore name across that boundary is a hard failure of
# test_no_module_reaches_past_another_modules_surface, so the choice there is
# between promoting them and lying about the boundary.
#
# `anchors` was the third until the anchor and slug machinery left for
# anchors.py; sites.py imports it from there now. Fifteen names went with it,
# five of them the private patterns only `anchors()` reads - moved rather than
# imported back, because the gate above would have made that a violation.
#
# The rest were read by extant_collect.py and by nothing else,
# before the split. The shim was deliberately NOT counted as a sibling - that
# gate's own comment says so, because extant_collect.py sits outside the
# package - and Task 10 deleted its direct reads of this module outright, so
# today none of the thirty-eight has an external caller at all.
#
# Task 9 settled the rest by measurement rather than by taste: when a shim rule
# became extant/rules/*.py, whatever it reached for here became a genuine
# sibling call and was promoted in the commit that created the caller. `prose`
# was the largest of those, with eight rule modules reading it; the eleven shim
# consumers it also had were wrappers that Task 10 deleted.
#
# The private names are listed in `__all__` anyway, following
# extant/collect.py, which keeps `_CHECKED` and `_VENV_LAYOUTS` in its own:
# the shim used to re-export them under their historical spellings for the
# suite and the mutation harness. Task 10 removed that path and neither reads
# them by name today, so the list stands as a record of what this module owns
# rather than a promise to an outside caller.
__all__ = [
    "LINE_BREAK", "ORDER_PREFIX",
    "_BREAKS", "_BREAKS_KEPT", "_break_starts",
    "_FENCE", "_INLINE_CODE", "_LANGUAGE_DIR", "_line_and_terminator",
    "_ROUTE_DEPTH", "_RST_DIRECTIVE", "_RST_DOCTEST", "_RST_INLINE",
    "_RST_LITERAL_INTRO", "_STRIPPED", "_blank", "_blank_rst",
    "_blank_uncached",
    "_route_name", "_translation_tree",
    "EXTERNAL", "HEADING", "MARKDOWN_ONLY", "MD_LINK",
    "format_for", "link_sites",
    "current_document", "line_breaks", "line_number_at", "lone_cr_to_lf",
    "numbered_document",
    "percent_decoded",
    "prose", "strip_code", "unique_basename",
]

# Markdown link syntax is fixed by the format, not by any project's habits, so
# unlike the prose patterns this one is not configurable. There is no corpus to
# measure for the SHAPE: `[text](target)` means the same thing everywhere.
#
# Both halves are BOUNDED, and unbounded they were each quadratic. Measured
# through the shipped CLI, one line, `[a](` repeated - a prefix that commits
# the engine to a match the subject never completes:
#     n= 2,000    8 KB      1.11s
#     n= 4,000   16 KB      3.33s   x3.01
#     n= 8,000   32 KB     12.14s   x3.65
#     n=16,000   64 KB     47.60s   x3.92
#     n=32,000  128 KB    188.83s   x3.97
# The ratio converges on x4 per doubling, which is the definition of quadratic.
# A 128 KB markdown file - an unremarkable size - costs over three minutes, and
# extrapolating the curve a ~1.4 MB one exhausts a six-hour CI job. Nothing
# needs configuring for this: `--sweep` picks the document up on its own. The
# unbounded-USER-pattern hang in rules/consistency.py is documented and
# deliberate; this one was neither.
#
# `[^)\s]+?` is the worse of the two and the reason both are bounded rather
# than just the first. It is lazy, so with no `)` anywhere it expands to the
# end of the subject once per opener; bounding only `[^\]]*` left 23.5s of a
# measured 23.8s in place. `commits.py` records the same repair for its own
# 322-second incident, so the shape of the fix is precedent here, not
# invention.
#
# 4096 is the smallest power of two above the longest real instance of EITHER
# half, measured over 694,676 markdown links in 176 repositories: link text
# tops out at 1,278 characters and a target at 3,064. At 4096 the number of
# real links this stops matching is ZERO - and the direction is the safe one
# regardless, because a bound can only ever drop a finding, never invent one,
# and a false positive is the expensive failure here.
_MD_LINK_SPAN = 4096
MD_LINK = re.compile(
    r"\[[^\]]{0,%d}\]\(\s*([^)\s]{1,%d}?)\s*\)" % (_MD_LINK_SPAN, _MD_LINK_SPAN))
# TLDs for the schemeless arm below, and the whole hazard is that a great many
# of them are also file extensions - `.md` is Moldova, `.rs` Serbia, `.py`
# Paraguay - so "any letters after a dot" would read every markdown link as a
# URL and silence the link rules everywhere while looking clean. Two admission
# rules, both a priori: the generic TLDs a documentation link uses, and the
# ISO-3166 two-letter codes. Then one MEASURED exclusion - every code really
# used as a file extension in 157 repositories is struck out, which is why
# `.py` (81,121 files), `.rs` (61,737), `.md` (53,611), `.cc`, `.sh`, `.mk`,
# `.tf`, `.pl`, `.in` and `.pm` are absent, along with generic `.info`
# (110), `.page` (83), `.tools` (38) and `.xyz` (22).
#
# `ai` IS PRESENT, and this paragraph listed it among the struck-out extensions
# until 2026-09-09 - a sentence stating the opposite of the line directly below
# it, in the one place this project relies on to stop a measured decision being
# undone by the next reader. It is in the GENERIC arm, beside `io`, `dev` and
# `app`, because a documentation link to an `.ai` site is now ordinary. The
# consequence is real and belongs here rather than being discovered: a bare
# `[logo](logo.ai)` is read as a URL and is not checked. `assets/logo.ai` is
# unaffected, because this arm needs `label.` at the START of the target. What
# bounds the whole suppression is the measurement below - 41 matched targets
# over 220,990, not one of which resolved to a file that exists.
_TLD = ("com|org|net|edu|gov|mil|io|ai|dev|app|cloud|tech|club|blog|wiki"
        "|at|be|bg|ca|ch|cl|co|cy|cz|de|dk|ee|eu|fi|gr|hk|hr|hu|ie|is|it|jp"
        "|kr|lt|lu|lv|me|mt|mx|my|nl|no|nz|pe|ph|pt|ro|se|sg|si|sk|th|tr|tv"
        "|tw|ua|uk|vn|za")

# ANY URI scheme, not an enumerated few. phoenixframework/phoenix links to
# `irc://irc.libera.chat/elixir`, and a named list will always be missing the
# next scheme somebody uses - slack:, vscode:, ssh:, matrix:. Two or more
# characters before the colon so a Windows drive letter is not mistaken for
# one; a relative path does not carry a colon before its first slash.
#
# AND A SCHEMELESS URL, which is not a path and was resolved as one:
# `[docs](www.skyvern.com/docs)` was joined to the document's directory and
# reported dead - 27 such findings in two corpora no rule was designed on.
# A SUPPRESSION, SO IT IS BOUNDED BY MEASUREMENT: over 157 repositories and
# 220,990 internal link targets it matches 41 distinct targets, every one a
# URL, and NOT ONE that resolves to a file which exists. The hostname arm
# needs `label.` before a listed TLD and then a path, query, fragment or end,
# which is what keeps `README.md` and `script.sh` paths. See design.md.
EXTERNAL = re.compile(
    r"^(?:"
    r"[a-z][a-z0-9+.-]+:"                              # any URI scheme
    r"|//"                                             # protocol-relative
    r"|www\.[a-z0-9-]+\."                              # www.example.anything
    rf"|(?:[a-z0-9-]+\.)+(?:{_TLD})(?:[/?#]|$)"        # example.com[/path]
    r")", re.I)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


# The three per-document values - the directory a relative link resolves
# against, the document's own path, and its markup language - are one object
# now. `DocScope` in extant/scope.py carries the reason each of them exists,
# which is the same reason in all three cases: a rule signature is
# (repo, text) and can carry none of them.
#
# Public, unlike most of its neighbours, because sites.py calls it and a
# leading underscore on a name another module reaches for is a false claim
# about the boundary. tests/test_module_quality.py enforces that directly: a
# sibling importing an underscore name is a violation, so the choice is
# between promoting this and lying about it.
def current_document(doc: DocScope) -> str | None:
    """The document under validation, as a forward-slashed relative path."""
    return doc.doc_path.replace("\\", "/") if doc.doc_path else None


# Rules whose syntax is markdown's alone. Skipped outside it rather than
# tuned, because there is no version of a markdown link regex that is correct
# on a language which has no markdown links.
#
# Public since Task 10, for the reason `current_document` above gives: the
# caller that reads it, `rule_applies` in extant/session.py, is a sibling
# module, and a leading underscore on a name another module reaches for is a
# false claim about the boundary.
MARKDOWN_ONLY = {"dead-md-link", "dead-md-anchor"}


# Public for the same reason, and with two siblings rather than one:
# extant/sweep.py sets the format per file it surveys and extant/cli.py does
# the same around `--deleted-since`.
def format_for(path: str) -> str:
    """Which markup language a filename is written in."""
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return "rst" if suffix == "rst" else "markdown"


_INLINE_CODE = re.compile(r"`[^`\n]*`")


def strip_code(doc: DocScope, text: str) -> str:
    """Blank out fenced blocks AND inline code spans, preserving line numbers.

    A README demonstrating link syntax is showing an example, not making a
    promise, and checking it produces exactly the kind of false positive that
    gets a validator ignored.

    Inline spans were missed at first, and this project's own README caught it:
    the table row documenting this very rule contains a backticked example
    link, and the rule reported it as dead. Documentation ABOUT links is the
    most predictable place for example links to appear, which makes it the last
    place a link checker can afford to be naive.

    Blanked with SPACES rather than emptied, so both the line count and every
    character offset survive. Rules that report a line by counting newlines up
    to a match offset therefore keep working on the stripped text, which is what
    lets every claim rule share this instead of only the link rules.
    """
    return _blank(doc, text, inline=True)


# Nine rules each stripped the same document independently: 1.22 of 6.4 seconds
# on a 100,000-line file, spent producing nine identical copies. Keyed on object
# IDENTITY rather than equality, which is what makes this safe without a
# lifecycle: every rule in one validate() receives the same str object, and a
# different object simply misses. No hashing of a 5 MB string, and at most two
# entries retained.
_STRIPPED: dict[bool, tuple[str, str]] = {}


# A bare carriage return, rewritten to a newline WITHOUT changing the length.
#
# `^` in a MULTILINE pattern follows a NEWLINE, and a bare CR is not one - so
# in a CR-only document every `^`-anchored header pattern matches at position
# 0 and nowhere else. `split_entries` then finds no sections, and every rule
# reading the newest entry examines ZERO candidates. Measured on one document
# written twice: LF reported `stale-live-claim 2, unknown-branch 2` and CR-only
# reported 0 and 0, printed beside every other rule's honest count - the
# reassuring zero this project exists to remove, arriving in the denominator
# built to prevent it. Found by the Stage 6 encoding axis.
#
# LENGTH-PRESERVING IS THE WHOLE CONSTRAINT, which is why this does not
# collapse CRLF too. That SHRINKS the text, and every offset computed against
# the result would index different characters in the original - the contract
# `strip_code` keeps by blanking code with spaces, broken once already on this
# very axis at a cost of 1627 characters. Substituting only a CR NOT followed
# by a newline leaves LF and CRLF byte-identical and maps CR-only one to one.
#
# Returns the SAME OBJECT when there is nothing to do, because `_blank` memoises
# on identity and a fresh string every call would turn that memo off.
_LONE_CR = re.compile(r'\r(?!\n)')


def lone_cr_to_lf(text: str) -> str:
    return _LONE_CR.sub('\n', text) if _LONE_CR.search(text) else text


def _blank(doc: DocScope, text: str, *, inline: bool) -> str:
    # Normalised HERE, at the one function both `prose` and `strip_code` reach,
    # so a rule and `split_entries` cannot disagree about where the lines are.
    # Normalising in `split_entries` alone was the first attempt and was worse
    # than the bug: it returned segments the caller could no longer find in its
    # own copy of the text, so `text.index(entry)` raised and two rules went
    # from a silent zero to `ValueError: substring not found`.
    text = lone_cr_to_lf(text)
    cached = _STRIPPED.get(inline)
    if cached is not None and cached[0] is text:
        return cached[1]
    result = _blank_uncached(doc, text, inline=inline)
    _STRIPPED[inline] = (text, result)
    return result


# Every spelling a line ending has, longest first so `\r\n` is one break and
# not two. Counting `"\n"` instead is right for LF and for CRLF - which
# contains one - and silently wrong for a bare `\r`, which contains none.
LINE_BREAK = re.compile(r"\r\n|[\n\r]")


def line_breaks(text: str) -> int:
    """How many line breaks a string contains, in any spelling.

    Used to BOUND a claim to a single wrapped line. A bound that counts only
    `\\n` does not bind at all on a CR-only document: the scanners it guards
    read the whole text, so the bound is the only thing standing between a
    claim and a version or SHA in the paragraph after it.
    """
    return len(LINE_BREAK.findall(text))


# Where every line break in ONE document starts, so asking for a line number is
# a bisection rather than a rescan.
#
# `line_number_at` counted from position 0 on every call, and both of its
# callers ask once per claim inside a loop - `_merge_claims` in
# extant/commits.py and the release-claim scanner in
# extant/rules/release_tag.py. With m claims over n characters that is O(m*n),
# and it is why the two slowest rules on a 17,000-line document were the two
# that ask for a line number: `dead-sha` grew x10.1 for x8 lines where linear
# would be x8, on an input whose git answers were all memo hits. Measured on
# this machine over a 375 KB CRLF document, 2000 lookups, median of 5, with a
# fresh string each repetition so every one pays its own scan: 7470.4 ms
# rescanning against 8.0 ms bisecting, 929x.
#
# End to end, which is the number a reader can reproduce - a whole `--validate`
# of this repository's own status document, doubled, best of two:
#
#     lines   rescanning   bisecting
#      2171      1550 ms      916 ms
#      4342      1742 ms      990 ms
#      8684      2370 ms     1410 ms
#     17368      5434 ms     1399 ms
#
# The speedup at the bottom row is what the shape change is; the columns are
# what it means. Eight times the document cost 3.51x rescanning and costs 1.53x
# bisecting, so the run is bounded by the scan rather than by the rescans.
#
# `line_breaks` is deliberately NOT routed through here. It is handed
# `match.group(0)` - one matched span, a few characters long - so memoising it
# would retain a string that is never shown again.
#
# Keyed on object IDENTITY and bounded, exactly like `_STRIPPED` above and for
# the same reasons: no multi-megabyte string is ever hashed, a changed input
# MISSES rather than answering stalely, and a sweep does not retain every
# document it walked. Unlike `_STRIPPED` the key here is COMPLETE - the break
# positions are a function of the text and of nothing else, no format, no
# repository, no file on disk - so this needs no lifetime and is deliberately
# absent from `registry.forget_memos()`, which exists for the memos that cannot
# key themselves. Two entries because the rules that ask see a document both as
# itself and as its prose-stripped copy, and alternate between them. The
# parallel survey is a ProcessPoolExecutor, so this is process-local and cannot
# race.
_BREAKS: list[tuple[str, list[int]]] = []
_BREAKS_KEPT = 2


def _break_starts(text: str) -> list[int]:
    # `is`, over at most two entries, rather than a dict keyed on `id()`. An id
    # is reused once the object that carried it is collected, so a dict keyed on
    # one answers for a string that no longer exists; holding the text itself
    # keeps the key alive for as long as the answer is reachable, which is what
    # `_STRIPPED` does and why.
    for held, starts in _BREAKS:
        if held is text:
            return starts
    starts = [match.start() for match in LINE_BREAK.finditer(text)]
    _BREAKS.append((text, starts))
    del _BREAKS[:-_BREAKS_KEPT]
    return starts


def line_number_at(text: str, offset: int) -> int:
    """The 1-based line an offset falls on, in any spelling.

    Its counterpart. Counting `"\\n"` up to the offset reports every claim in a
    CR-only document as line 1 - a number that is confidently wrong rather than
    absent, which sends a reader to the top of the file.

    Counts the breaks that START before the offset, and that one word is the
    whole of what makes precomputed spans agree with the rescan they replace.
    `findall(text, 0, offset)` restricts the SEARCH REGION, so an offset landing
    between a `\\r` and its `\\n` cut that pair in half and matched the `\\r`
    alone - one break, counted. The same pair computed over the whole text is
    one break ENDING after that offset, so counting breaks that have ENDED
    reports the line above for exactly those offsets and for no others. Every
    other input gives the two formulations the same number, which is why the
    divergence is one character wide and tests/test_line_numbering.py steps
    through every offset of every terminator spelling rather than sampling.

    THIS IS NOT THE ONLY LINE NUMBERING IN THE PACKAGE, and a reader who has
    got this far deserves telling rather than discovering it. Eight sites
    number lines with `enumerate(..., start=1)` over `splitlines()` - two in
    extant/commits.py and one each in the line-pointer, manifest-floor,
    md-anchor, md-link, path-pointer and pinned-ref rules - and two number them
    from an offset through this function. `splitlines()` breaks on a larger
    set than `LINE_BREAK` does: form feed, vertical tab, the file separators and
    the Unicode line separators are all breaks to it and content to this. So a
    document carrying one of those gets TWO DIFFERENT line numbers for one
    position, and a finding is reported against the wrong line by whichever
    rule read it:

        >>> doc = "alpha\\nbeta\\fgamma\\ndelta HERE\\n"
        >>> line_number_at(doc, doc.index("HERE"))
        3
        >>> # enumerate(doc.splitlines(), start=1) puts the same offset on 4

    Recorded and deliberately NOT repaired here, because the obvious repair is
    wrong in a way that touches every document rather than the rare one. Making
    the eight agree with this by splitting on `LINE_BREAK` appends a phantom
    trailing line to every file ending in a newline - `"alpha\\nbeta\\n"` is two
    lines to `splitlines()` and three to `LINE_BREAK.split()` - so every rule
    that counts lines would gain one, on every ordinary document. Widening
    `LINE_BREAK` instead changes what BOUNDS a claim, which is a rule
    behaviour, not a numbering one. Either direction needs its own change and
    its own measurement over the corpus.
    """
    return bisect.bisect_left(_break_starts(text), offset) + 1


def _line_and_terminator(raw: str) -> tuple[str, str]:
    """Split a kept-ends line into its content and its EXACT terminator.

    The terminator is carried through verbatim rather than rebuilt, and that is
    the whole of the repair here. Both blanking loops used to read
    `text.splitlines()` and rejoin with `"\\n"`, which decides the terminator
    instead of preserving it: every `\\r\\n` came back as `\\n` and a trailing
    newline vanished, so the blanked copy was shorter than the document it is
    supposed to align with - 1627 characters shorter on this repository's own
    status document.

    That broke the promise both public functions make, and two callers rely on:
    the `dead-md-link` and `dead-md-anchor` probes take `match.span()` from the
    stripped text and splice it into the ORIGINAL. On a CRLF checkout the
    splice landed one character earlier per preceding line, so the probe
    reported corrupting a real match while the rule read an untouched claim and
    correctly found nothing. It looked like two broken rules and was neither.

    A terminator this does not recognise is left as content, which keeps the
    length right: `splitlines()` also breaks on form feed and the Unicode line
    separators, and blanking one of those to a space inside a fence costs a
    character's identity but never an offset.
    """
    if raw.endswith("\r\n"):
        return raw[:-2], "\r\n"
    if raw.endswith(("\n", "\r")):
        return raw[:-1], raw[-1]
    return raw, ""


def _blank_uncached(doc: DocScope, text: str, *, inline: bool) -> str:
    if doc.doc_format == "rst":
        return _blank_rst(text, inline=inline)
    out: list[str] = []
    inside = False
    for raw in text.splitlines(keepends=True):
        line, end = _line_and_terminator(raw)
        if _FENCE.match(line):
            inside = not inside
            out.append(" " * len(line) + end)
            continue
        if inside:
            out.append(" " * len(line) + end)
        elif inline and "`" in line:
            out.append(_INLINE_CODE.sub(
                lambda m: " " * len(m.group(0)), line) + end)
        else:
            out.append(line + end)
    return "".join(out)


# reStructuredText marks code three ways, and none of them is a fence.
_RST_DIRECTIVE = re.compile(r"^\s*\.\.\s+(?:code-block|code|literalinclude|"
                            r"sourcecode|parsed-literal|math)::")
_RST_LITERAL_INTRO = re.compile(r"::\s*$")
_RST_DOCTEST = re.compile(r"^\s*(?:>>>|\.\.\.)\s")
_RST_INLINE = re.compile(r"``[^`]*``|`[^`]*`(?:_+)?")


def _blank_rst(text: str, *, inline: bool) -> str:
    """The same job for reStructuredText, whose code blocks are indentation.

    A literal block opens with a line ending in `::` or a `.. code-block::`
    directive and runs until the indentation returns; a doctest opens with
    `>>>`. None of that is a fence, so the markdown stripper left every example
    in place and the rules read Python as prose - numpy's
    `float64('1e10000')` became a dead commit, and its
    `np.dtype[mp.mpf](dps=100)` became a dead link.

    Blanked with spaces like the markdown path, so line numbers and offsets
    survive for every rule that shares this.
    """
    out: list[str] = []
    block_indent: int | None = None
    for raw in text.splitlines(keepends=True):
        line, end = _line_and_terminator(raw)
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            # A blank line does not end a literal block; a return to the
            # opening indentation does.
            if not stripped or indent > block_indent:
                out.append(" " * len(line) + end)
                continue
            block_indent = None
        if _RST_DOCTEST.match(line):
            out.append(" " * len(line) + end)
            continue
        if _RST_DIRECTIVE.match(line) or _RST_LITERAL_INTRO.search(line):
            block_indent = indent
            out.append(" " * len(line) + end)
            continue
        out.append((_RST_INLINE.sub(lambda m: " " * len(m.group(0)), line)
                    if inline else line) + end)
    return "".join(out)


def prose(doc: DocScope, text: str) -> str:
    """Text with FENCED BLOCKS removed, for rules that check claims.

    A fenced block is an example or captured output, not a promise. A README
    showing the expected format, or a pasted `git log`, was being read as a
    claim about the commits in it.

    Inline code is deliberately KEPT here, unlike in the link rules. Claims are
    written inside backticks by convention - "merged to `main` at `abc1234`",
    "**Design:** `docs/plan.md`" - so blanking inline spans would delete the
    very thing these rules exist to check. Applying the link rules' stripping
    wholesale turned eight tests red at once, which is a cheaper way to learn it
    than shipping a validator that silently checks nothing.

    NOT used by the secret scan either, for the opposite reason: a credential
    pasted inside a fence is still a committed credential. That rule is about
    what the file CONTAINS, not what it claims.
    """
    return _blank(doc, text, inline=False)


def link_sites(doc: DocScope, text: str) -> list[tuple[int, str, str]]:
    """Every markdown link a caller will TRY to decide: (line, raw, target).

    Moved here from `rules/md_link.py`, where it was the rule's private
    scanner, because it had grown a SECOND reader: `gate.suggest_renames`
    scanned the same documents for the same links with its own filter, and the
    two disagreed five ways. AGENTS.md names that shape as the recurring defect
    here and gives the remedy - "if a rule needs the same claims twice, give it
    one function and have both callers read it". `test_rules_are_leaves` lets
    only `registry.py` import a rule module, so gate.py could not read it where
    it was; this module is the home it can.

    It belongs here on the merits too, not merely by elimination. Everything it
    reads - `strip_code`, `EXTERNAL`, `MD_LINK`, `percent_decoded` - already
    lives in this file, and it takes nothing off a Context but the DocScope, so
    nothing had to follow it across. It sat in md_link.py by history.

    THREE values per site, and the third is the reason the merge is not a
    simple deduplication. The two callers need DIFFERENT strings and both are
    right:

      `target` is normalised - fragment and query removed, percent-decoded -
        because a rule RESOLVES it against the filesystem.
      `raw` is the spelling as written, because a patch REPLACES it in the
        document, and `text.replace` matches what is on the page rather than
        what it means.

    Returning only the target would have silently broken the patch generator:
    a link written `docs/old%20guide.md` has the target `docs/old guide.md`,
    which does not occur in the document at all, so the replacement would match
    nothing and the patch would come out empty.

    The refusals below are the UNCONDITIONAL ones - true of the link whatever
    the repository looks like. Anything that depends on what is on disk, or on
    the target failing to resolve, stays with the caller.
    """
    sites: list[tuple[int, str, str]] = []
    for number, line in enumerate(strip_code(doc, text).splitlines(), start=1):
        if "[" not in line or "(" not in line:
            continue
        for raw in MD_LINK.findall(line):
            if EXTERNAL.match(raw) or raw.startswith("#"):
                continue
            # The query string is not part of the filename. `?raw=1` and
            # `?plain=1` are how GitHub serves a file, and leaving them on the
            # target made every such link resolve to nothing and report a file
            # that is plainly there as missing.
            target = raw.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            # `@` opens a generator macro, not a path. Documenter.jl writes
            # `[text](@ref)` for a cross-reference and JuliaLang/julia carries
            # 1,779 of them - every single one reported as a dead file, and 96%
            # of that repository's findings.
            if target.startswith("@"):
                continue
            # A markdown link percent-encodes characters that are awkward in a
            # URL, and the file on disk carries the decoded name.
            # nlohmann/json documents `operator[]` and links to it as
            # `operator%5B%5D.md`, which is the same file spelled for a browser.
            target = percent_decoded(target)
            # A `.html` target is a rendered page, in every repository and not
            # only in a detected one. MEASURED across 20 repositories in two
            # corpora: 407 markdown links point at a `.html` target and NOT ONE
            # resolves to a checked-in file. Gating this on generator detection
            # is what made rails report 276 of its own guide links dead - its
            # guides compile to HTML with a bespoke builder that ships none of
            # the configs `sites.py` detects.
            #
            # Refused HERE rather than beside the site routes in a rule,
            # because it is refused whatever the repository looks like and
            # whatever is on disk. A caller that would never judge this link
            # must not count it either.
            if target.endswith(".html"):
                continue
            sites.append((number, raw, target))
    return sites

def unique_basename(ctx: Context, target: str) -> bool:
    """Does exactly one tracked markdown file carry this basename?

    Exactly one, never "at least one". Two files called `index.md` say nothing
    about which was meant, and guessing would trade a false positive for a
    silent wrong answer, which is worse.
    """
    name = Path(target).name.lower()
    if not name:
        return False
    key = str(ctx.repo)
    if key not in ctx.run.basenames:
        counts: dict[str, dict[str, int]] = {}
        try:
            for path in tracked_markdown(ctx):
                leaf = path.rsplit("/", 1)[-1].lower()
                tree = _translation_tree(ctx, path)
                counts.setdefault(tree, {})
                counts[tree][leaf] = counts[tree].get(leaf, 0) + 1
        except (OSError, subprocess.CalledProcessError):
            counts = {}
        ctx.run.basenames[key] = counts
    # Counted WITHIN the citing document's translation tree, not across the
    # whole repository.
    #
    # A bare-name match is a claim that the generator resolves this name from
    # anywhere, and it does - within one site. fastapi builds a separate site
    # per language and keeps `newsletter.md` only in English, so counting
    # repository-wide made every translated page's link to it "resolve"
    # against a file in a different language's site. That silenced 68 real
    # defects across ten languages the moment fastapi was detected at all.
    #
    # A repository with no translation trees has one bucket and behaves
    # exactly as before, which is what keeps ExDoc's flat namespace working.
    here = _translation_tree(ctx, current_document(ctx.doc) or "")
    return ctx.run.basenames[key].get(here, {}).get(name, 0) == 1

# A directory named for a language: `en`, `de`, `pt`, `zh-hant`, `pt_BR`.
_LANGUAGE_DIR = re.compile(r"^[a-z]{2,3}(?:[-_][A-Za-z]{2,4})?$")


def _translation_tree(ctx: Context, path: str) -> str:
    """Which parallel language tree this path belongs to, or "" for none.

    Recognised by SIBLINGS, not by the name alone. `docs/es/` is Spanish
    because `docs/de/`, `docs/fr/` and eleven more sit beside it; a lone
    `docs/id/` would be an "id" directory and is left alone. Three or more
    language-shaped siblings is the threshold, which no repository reaches by
    accident.
    """
    parts = path.replace("\\", "/").split("/")
    for index, part in enumerate(parts[:-1]):
        if not _LANGUAGE_DIR.match(part):
            continue
        parent = "/".join(parts[:index])
        key = (str(ctx.repo), parent)
        if key not in ctx.run.language_siblings:
            directory = ctx.repo / parent if parent else ctx.repo
            try:
                siblings = sum(1 for child in directory.iterdir()
                               if child.is_dir()
                               and _LANGUAGE_DIR.match(child.name))
            except OSError:
                siblings = 0
            ctx.run.language_siblings[key] = siblings
        if ctx.run.language_siblings[key] >= 3:
            return "/".join(parts[:index + 1])
    return ""


# `07-misc`, `04-custom-elements.md`, `1.2-intro.md`: an ordering prefix a
# docs generator strips when it builds the route.
#
# Public for the reason `current_document` above is: sites.py reads it when it
# decides whether a numbered documentation tree declares a site.
ORDER_PREFIX = re.compile(r"^\d+(?:\.\d+)*[-_.]")


def _route_name(segment: str) -> str:
    """A path segment with its ordering prefix and `.md` suffix removed."""
    stem = re.sub(r"\.(?:md|markdown|mdx)$", "", segment, flags=re.I)
    return ORDER_PREFIX.sub("", stem).lower()


def numbered_document(ctx: Context, target: str) -> bool:
    """Does exactly one tracked document answer to this route once prefixes go?

    Compares the WHOLE path segment by segment, not just the basename, so
    `guides/setup` and `reference/setup` stay distinguishable. A bare
    `custom-elements` matches `documentation/docs/07-misc/04-custom-elements.md`
    on its last segment; a two-segment target must match the last two.

    Exactly one match, never "at least one", for the reason
    `unique_basename` gives: guessing between candidates trades a false
    positive for a silently wrong answer.
    """
    wanted = [_route_name(part) for part in target.strip("/").split("/") if part]
    if not wanted or not wanted[-1]:
        return False
    key = str(ctx.repo)
    if key not in ctx.run.routes:
        routes: dict[str, int] = {}
        try:
            for path in tracked_markdown(ctx):
                segments = path.split("/")
                # ONLY documents that actually carry an ordering prefix are
                # indexed. Without that condition this becomes
                # `unique_basename` with the generator gate removed, and
                # would silence a link to `foo` anywhere `foo.md` happens to
                # exist in an unrelated directory. The prefix is the evidence
                # that something strips it, so no prefix, no claim.
                if not any(ORDER_PREFIX.match(s) for s in segments):
                    continue
                parts = [_route_name(s) for s in segments]
                # Index every trailing run, so a target of any depth is one
                # dictionary hit rather than a scan.
                for depth in range(1, min(len(parts), _ROUTE_DEPTH) + 1):
                    suffix = "/".join(parts[-depth:])
                    routes[suffix] = routes.get(suffix, 0) + 1
        except (OSError, subprocess.CalledProcessError):
            routes = {}
        ctx.run.routes[key] = routes
    return ctx.run.routes[key].get("/".join(wanted[-_ROUTE_DEPTH:]), 0) == 1


_ROUTE_DEPTH = 4


def percent_decoded(target: str) -> str:
    """A link target with percent-escapes resolved, or unchanged if it has none.

    Left alone when there is nothing to decode, so a path containing a literal
    `%` is never rewritten into something else.
    """
    if "%" not in target:
        return target
    from urllib.parse import unquote
    return unquote(target)
