"""Reading a document: what is code, what is prose, what anchors it offers.

Everything here is about the TEXT in front of it, which is what separates this
module from `refs.py` beside it. Most of it is pure - a heading in, a slug out -
and the exceptions are the three functions that ask the repository which
documents exist.

Three calling conventions, and the split is deliberate rather than untidy:

* Pure functions take what they read and nothing else. `_slug`, `anchors`,
  `_definition_terms` and the rest cannot be affected by a repository or a run,
  so handing them a Context would be a claim about their dependencies that is
  simply false.
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

# THREE of these forty-one names are public, and the rule is the same one
# every module in this package follows: a name is public when a SIBLING MODULE
# calls it, and keeps its underscore when it does not.
#
# `current_document`, `anchors` and `ORDER_PREFIX` are the three, and sites.py
# calls all three. Reaching for an underscore name across that boundary is a
# hard failure of test_no_module_reaches_past_another_modules_surface, so the
# choice there is between promoting them and lying about the boundary.
#
# The other thirty-eight were read by extant_collect.py and by nothing else,
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
    "_ATTR_ANCHOR", "_BREAKS", "_BREAKS_KEPT", "_DIRECTIVE_LABEL",
    "_EXPLICIT_ANCHOR", "_break_starts",
    "_FENCE", "_INLINE_CODE", "_LANGUAGE_DIR", "_line_and_terminator",
    "_MYST_TARGET", "_NESTED_HEADING",
    "_ROUTE_DEPTH", "_RST_DIRECTIVE", "_RST_DOCTEST", "_RST_INLINE",
    "_RST_LITERAL_INTRO", "_SETEXT_RULE", "_STRIPPED", "_blank", "_blank_rst",
    "_blank_uncached", "_definition_terms", "_disambiguated",
    "_heading_text",
    "_route_name", "_setext_headings", "_slug", "_slug_keeping_edges",
    "_slug_punctuation_to_dash", "_translation_tree",
    "_without_tags", "EXTERNAL", "HEADING", "MARKDOWN_ONLY", "MD_LINK",
    "anchors", "format_for",
    "current_document", "line_breaks", "line_number_at", "lone_cr_to_lf",
    "numbered_document",
    "percent_decoded",
    "prose", "strip_code", "unique_basename",
]

# Markdown link syntax is fixed by the format, not by any project's habits, so
# unlike the prose patterns this one is not configurable. There is no corpus to
# measure: `[text](target)` means the same thing everywhere.
MD_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+?)\s*\)")
# ANY URI scheme, not an enumerated few. phoenixframework/phoenix links to
# `irc://irc.libera.chat/elixir`, and a named list will always be missing the
# next scheme somebody uses - slack:, vscode:, ssh:, matrix:. Two or more
# characters before the colon so a Windows drive letter is not mistaken for
# one; a relative path does not carry a colon before its first slash.
EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]+:|//)", re.I)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
# A heading nested inside a list item. CommonMark renders `- ### Title` as a
# real h3 and gives it an id, which is how a README builds an indented table
# of contents:
#
#     - ### [Getting the project](#getting-the-project-1)
#
# Unity's BossRoom does exactly that, and because the nested copy was invisible
# here the later `## Getting the project` never looked like a repeat, so the
# `-1` a renderer appends was never offered. Twelve findings, and every anchor
# finding that Unity project had.
_NESTED_HEADING = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+#{1,6}\s+(.+?)\s*#*$")
_EXPLICIT_ANCHOR = re.compile(r"""(?:name|id)\s*=\s*["']([^"']+)["']""")
# The attribute syntax pandoc, kramdown and PHP Markdown Extra use to name a
# heading or a span outright: `## Template {#type-template}` and
# `[Inlines]{#inlines-filter}`. It overrides whatever the text would slug to,
# so a document using it has anchors that no amount of slug guessing will
# reach. pandoc's own doc/lua-filters.md carries 368 and accounted for 120 of
# its 149 findings - the largest single class left in a 26-repository corpus.
#
# The JSX-comment spelling is the same declaration with MDX's parser in mind:
# `### \`baseUrl\` {/* #baseUrl */}`. MDX v3 reads a bare `{#id}` as a JSX
# expression, so Docusaurus wraps it in a comment. Same intent, same override,
# and it accounted for most of Docusaurus's 1,078 anchor findings once `.mdx`
# files were swept at all.
_ATTR_ANCHOR = re.compile(r"\{\s*(?:/\*)?\s*#([^\s}*]+)")
# MyST names a target on its own line, immediately before what it labels:
#
#     (a11y:contribute)=
#     ## Contributing
#
# Same idea as the attribute syntax and equally explicit, but it sits outside
# the thing it names, so nothing that reads headings would ever see it.
# executablebooks/mystmd links to `#a11y:contribute` throughout, and those
# labels were 248 of its 275 findings.
_MYST_TARGET = re.compile(r"^\(([^)\s]+)\)=\s*$", re.MULTILINE)
# A directive option naming its block. MyST writes `:label:` and Sphinx writes
# `:name:` inside a fenced directive:
#
#     ```{list-table} Affiliations
#     :label: table-frontmatter-affiliations
#     ```
#
# Same explicit naming as `(target)=`, in the third of three places MyST allows
# it. mystmd links to `#table-frontmatter-affiliations` from another document,
# and the label existed the whole time - in a directive option nothing read.
_DIRECTIVE_LABEL = re.compile(r"^\s*:(?:label|name):\s*(\S+)\s*$", re.MULTILINE)
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
# would be x8, on an input whose git answers were all memo hits. Measured over
# a 380 KB CRLF document, 2000 lookups: 8734.9 ms rescanning against 18.2 ms
# bisecting, 479x.
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


def _heading_text(title: str) -> str:
    """Heading text as rendered: link syntax reduced to its text, code unwrapped.

    A heading may itself be a link. Alamofire's changelog writes
    `## [5.12.0](https://github.com/Alamofire/Alamofire/releases/tag/5.12.0)`
    and indexes it as `#5120`, because a renderer slugs what the reader SEES -
    `5.12.0` - and drops the destination. Folding the URL in instead produced
    `1-0-0-https-github-com-alamofire-...` and called all 119 of that
    repository's changelog anchors dead.
    """
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title.strip())
    return re.sub(r"`([^`]*)`", r"\1", text).lower()


def _without_tags(title: str) -> str:
    """The same heading with angle-bracket markup removed.

    Offered ALONGSIDE the untouched spelling, never instead of it, because the
    two conventions collide head-on and both are real.

    vitejs/vite writes `## resolve.conditions <NonInheritBadge />` and links to
    it as `#resolve-conditions`, so the component tag has to go. Prometheus
    writes `### \\`<relabel_config>\\`` - a YAML placeholder that IS the heading
    - and links to it as `#relabel_config`, so the angle brackets have to stay.
    Stripping unconditionally fixed vite's two and broke fifty of Prometheus's,
    which is the worse trade by far and is why this is additive.
    """
    return re.sub(r"<[^>]*>", " ", title)


def _slug(title: str) -> str:
    """Approximate the heading-to-anchor conversion used by common renderers.

    Each space becomes its own dash rather than a run collapsing to one, which
    is what GitHub does: `### Serialization / Deserialization` drops the slash
    and keeps both surrounding spaces, so the anchor is
    `serialization--deserialization` with two. Collapsing produced one dash and
    called nlohmann/json's own README link dead.
    """
    text = re.sub(r"[^\w\s-]", "", _heading_text(title))
    return re.sub(r"\s", "-", text).strip("-")


def _slug_keeping_edges(title: str) -> str:
    """The same slug with a leading or trailing dash LEFT ON.

    GitHub does not trim the edges, and a heading that opens with an emoji
    therefore anchors with a dash in front: `## <emoji> Component structure`
    is reachable as `#-component-structure`, because the emoji is dropped and
    the space after it still becomes a dash. AutoGPT's contributing guide
    links to its own sections that way and every link works.

    Stripping produced `component-structure`, which matched nothing the
    document offered, so 58 working links on the held-out corpus were reported
    dead. Added as an extra spelling rather than by changing `_slug`, because
    both are real: renderers that DO trim exist, and a fragment matching
    neither spelling is still dead.
    """
    text = re.sub(r"[^\w\s-]", "", _heading_text(title))
    untrimmed = re.sub(r"\s", "-", text)
    # Contributes ONLY the spelling trimming would lose, and nothing when
    # there is no edge to keep.
    #
    # Returning the trimmed form too would duplicate `_slug` and mask it. It
    # did: the mutation that stops `_slug` stripping punctuation SURVIVED
    # once this function existed, because `## build.target` still offered
    # `buildtarget` from here after `_slug` stopped offering it. A check that
    # another check silently covers is a check nobody is running.
    return untrimmed if untrimmed != untrimmed.strip("-") else ""


def _slug_punctuation_to_dash(title: str) -> str:
    """The other common convention: punctuation becomes a separator.

    Renderers disagree here, and both spellings are correct on the site that
    produced them. GitHub DROPS a dot, so `## build.target` offers
    `#buildtarget`; VitePress and several others turn it into a dash, so the
    same heading offers `#build-target`.

    Measured on vitejs/vite, which links to `#build-target` throughout and
    renders correctly: following GitHub's rule alone reported ten dead anchors
    in a documentation site with no broken anchors. Accepting BOTH spellings
    costs nothing that matters - a fragment matching neither is still dead,
    which is why httpx's genuinely broken `#routing` survives this change.
    """
    text = re.sub(r"[^\w\s-]", "-", _heading_text(title))
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _definition_terms(lines: list[str]) -> list[str]:
    """Terms of a markdown definition list.

    A term is a plain line whose successor begins with a colon and a space:

        `titleCaseStyle`
        : (`bool`) Whether to capitalize automatic list titles.

    Renderers supporting the extension - Goldmark, PHP Markdown Extra,
    kramdown, pandoc - give each `<dt>` an id the same way they give one to a
    heading, so a term is an anchor source and had been invisible here.

    Measured on the Hugo documentation, which documents every configuration key
    this way: 71 of its 101 same-document anchor findings are terms, and no
    other repository in a 26-project corpus has a single one, so this widens
    nothing anywhere else.

    Excluded openers are the shapes that are already something else - a
    heading, a quote, a list item, a table row, an indented block - because
    each can be followed by a colon line without being a definition list.
    """
    terms: list[str] = []
    for index, line in enumerate(lines[:-1]):
        if not line.strip() or line.startswith((" ", "\t", "#", ">", "-", "*", "|", "=")):
            continue
        if re.match(r"^:\s", lines[index + 1]):
            terms.append(line.strip())
    return terms


_SETEXT_RULE = re.compile(r"^(?:=+|-{2,})\s*$")


def _setext_headings(lines: list[str]) -> list[str]:
    """Headings written by underlining rather than with `#`.

        Limitations
        -----------

    CommonMark calls these setext headings and every renderer gives them an
    id, but only ATX headings were parsed here. A document written entirely in
    this style therefore offered NO anchors at all, so every link into it read
    as dead - the failure is total rather than partial, which is what makes it
    worth handling. Found on a vendored README carrying 13 such headings and
    not one `#`.

    YAML frontmatter is skipped first. Its closing `---` follows a non-blank
    line, which would otherwise promote `title: something` to a heading and
    invent an anchor the document does not have.
    """
    start = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() in ("---", "..."):
                start = index + 1
                break
    found: list[str] = []
    for index in range(start, len(lines) - 1):
        title = lines[index].strip()
        if not title or not _SETEXT_RULE.match(lines[index + 1].strip()):
            continue
        # Shapes that are already something else and can be followed by a
        # rule of dashes without being a heading.
        if title.startswith(("#", ">", "-", "*", "+", "|", "=", ":")):
            continue
        if lines[index].startswith((" ", "\t")):
            continue
        found.append(title)
    return found


# Public for the reason `current_document` above is: sites.py reads the anchors
# a partial or a project-wide document offers, and reaching for an underscore
# name across that boundary is what tests/test_module_quality.py forbids.
def anchors(text: str) -> set[str]:
    """Every fragment this document offers, from headings and explicit anchors."""
    lines = text.splitlines()
    headings = [m.group(1) for line in lines
                if (m := HEADING.match(line) or _NESTED_HEADING.match(line))]
    headings += _definition_terms(lines)
    headings += _setext_headings(lines)

    # Every spelling a renderer might produce: three slug conventions, each
    # over the heading as written and with angle-bracket markup removed.
    # Offering a spelling that no renderer uses costs nothing - a fragment
    # matching none of them is still dead - while missing one reports a
    # working link as broken, which is the failure that matters.
    #
    # The three conventions are spelled out here rather than called, and the
    # repeat counting that `_disambiguated` does is folded into the same pass.
    # That is worth 1.32x on a real corpus (66 documents, 315ms -> 239ms
    # measured 2026-08-23), because this runs for every document a link
    # reaches, not only the one under validation.
    #
    # `_slug_punctuation_to_dash`, `_slug_keeping_edges` and `_disambiguated`
    # remain below as the DEFINITION of what those three conventions are, and
    # tests/test_anchor_slugging.py holds this loop to them over a corpus. Two
    # implementations of one rule is a rot vector unless something checks they
    # still agree, so something does.
    found: set[str] = set()
    repeats: dict[str, int] = {}
    for heading in headings:
        stripped = _without_tags(heading)
        variants = (heading, stripped) if stripped != heading else (heading,)
        primary = None
        for variant in variants:
            cleaned = _heading_text(variant)
            kept = re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", cleaned))
            plain = kept.strip("-")
            if plain:
                found.add(plain)
            if kept != plain:
                found.add(kept)
            dashed = re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "-", cleaned)).strip("-")
            if dashed:
                found.add(dashed)
            if primary is None:
                primary = plain
        if primary:
            repeats[primary] = repeats.get(primary, 0) + 1
    for slug, count in repeats.items():
        for suffix in range(1, count):
            found.add(f"{slug}-{suffix}")

    found |= {a.lower() for a in _EXPLICIT_ANCHOR.findall(text)}
    found |= {a.lower() for a in _ATTR_ANCHOR.findall(text)}
    found |= {a.lower() for a in _MYST_TARGET.findall(text)}
    found |= {a.lower() for a in _DIRECTIVE_LABEL.findall(text)}
    return found - {""}


def _disambiguated(headings: list[str]) -> set[str]:
    """The `-1`, `-2` suffixes a renderer adds when a slug repeats.

    Two headings reading the same thing cannot share an id, so every renderer
    numbers the later ones. Hugo's deployment page carries a `matchers`
    definition term and a `## Matchers` section, and links to the second as
    `#matchers-1`.

    Offered only from the SECOND occurrence onward, because that is when a
    renderer starts numbering; inventing `-1` for a slug that occurs once would
    forgive an anchor that really is dead.
    """
    seen: dict[str, int] = {}
    for heading in headings:
        found = _slug(heading)
        if found:
            seen[found] = seen.get(found, 0) + 1
    return {f"{found}-{n}" for found, count in seen.items()
            for n in range(1, count)}
