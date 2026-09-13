"""What a document links to: every destination markdown, a reference
definition or raw HTML names, and the refusals true of a destination whatever
the repository looks like.

Cut out of `text.py` on 2026-09-13, the way `anchors.py` was on 2026-09-07 and
for the same reason: that module answers separable questions and had run out
of room to answer any of them at greater length. The two CommonMark spellings
`MD_LINK` had been missing - a title after the destination and an
angle-bracketed destination - took it to 918 lines against a 927-line ceiling,
and the link scanner was the block with the cleanest edge. Nothing left in
`text.py` reads a name defined here; this module reads `strip_code` from
there and nothing else.

Everything here is PURE. A line goes in, the destinations on it come out; no
repository, no run. The two readers that DO ask the repository about a link -
`unique_basename` and `numbered_document` - stayed in `text.py` beside the
other Context-taking questions, because they are questions about what the
repository tracks rather than about what the document says.

Three readers, one scanner. `rules/md_link.py` judges what `link_sites`
returns and counts it; `gate.suggest_renames` reads the same list to find
the spelling it will patch; `rules/md_anchor.py` reads `MD_LINK` and
`link_destination` directly because it partitions the destination on its
`#` rather than resolving it. Every destination reaches a filesystem through
`_link_target`, which is where the unconditional refusals live - and
`link_destination` sits in front of every one of them, so no caller reads a
bracket as part of a path.
"""
from __future__ import annotations

import re

from extant.scope import DocScope
from extant.text import strip_code

# Public where a sibling calls it, private otherwise, as everywhere in this
# package. `MD_LINK`, `EXTERNAL`, `link_destination`, `link_sites` and
# `percent_decoded` have readers in the rules and in gate.py; the rest are
# listed as the record of what this module owns, following `text.py`.
__all__ = [
    "_HTML_ATTRIBUTE", "_HTML_TAG_OPEN", "_MD_LINK_SPAN",
    "_REFERENCE_DEFINITION", "_TLD", "_html_references", "_link_target",
    "EXTERNAL", "MD_LINK",
    "link_destination", "link_sites", "percent_decoded",
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
# `[^)\s]+?` was the worse of the two and the reason both are bounded rather
# than just the first. It was lazy, so with no `)` anywhere it expanded to
# the end of the subject once per opener; bounding only `[^\]]*` left 23.5s
# of a measured 23.8s in place. `commits.py` records the same repair for its
# own 322-second incident, so the shape of the fix is precedent here, not
# invention. The class is greedy today - the last paragraph below says why -
# and greedy or lazy, an unbounded run walks to the end of the subject once
# per opener; the bound is what stops that, not the quantifier's direction.
#
# 4096 is the smallest power of two above the longest real instance of EITHER
# half, measured over 694,676 markdown links in 176 repositories: link text
# tops out at 1,278 characters and a target at 3,064. At 4096 the number of
# real links this stops matching is ZERO - and the direction is the safe one
# regardless, because a bound can only ever drop a finding, never invent one,
# and a false positive is the expensive failure here.
#
# TWO SPELLINGS COMMONMARK FIXES, added 2026-09-13 and each bounded the same
# way. A TITLE after the destination - `[t](docs/a.md "The guide")`, in
# double quotes, single quotes or parentheses, after at least one space -
# made the whole link invisible, because the destination class forbade the
# space: measured on 132 repositories, 499 titled links name a local file
# and were examined zero times. An ANGLE-BRACKETED destination,
# `[t](<docs/a b.md>)`, is how the format spells a target holding a space,
# and was read WITH its brackets, so a spaced target was refused and an
# external URL holding a parenthesis - `<https://en.wikipedia.org/wiki/
# Shebang_(Unix)>` - was cut at the parenthesis, failed the external test on
# its leading `<`, and was reported as a dead file: 14 findings on the same
# corpora, every one false. The group still captures the destination AS
# WRITTEN, brackets included, because a patch generator has to find it on
# the page again; `link_destination` below takes them off for everyone that
# resolves it. A bare destination may not open with `<` - CommonMark says a
# destination that opens with one must close with one - so `[t](<docs/a.md)`
# is not a link rather than a link to a file named `<docs/a.md`. Two bare
# words are still not a link: the title must be delimited, or `[t](a.md b.md)`
# would read as a link to `a.md` the author never wrote.
#
# The bare destination is GREEDY now, with a lookahead for the space or
# parenthesis that must follow it, and that is a measured cost decision
# rather than a style one. Lazy, every character of the run tried the
# optional title group before extending by one, and on the `[a](` input
# above the 8,000-opener line went from 1.44s to 2.85s - still bounded, and
# still too close to the five-second margin the timing test allows on a
# slower runner. Greedy with the lookahead, the run is taken in one pass and
# the group is entered once, at its end: 1.09s on the same line, with the
# same result on every shape either arm reads.
_MD_LINK_SPAN = 4096
MD_LINK = re.compile(
    r"\[[^\]]{0,%d}\]\(\s*(<[^<>\n]{0,%d}>|(?!<)[^)\s]{1,%d})(?=[\s)])"
    r"(?:\s+(?:\"[^\"\n]{0,%d}\"|'[^'\n]{0,%d}'|\([^()\n]{0,%d}\)))?\s*\)"
    % ((_MD_LINK_SPAN,) * 6))


def link_destination(raw: str) -> str:
    """The destination a link's parentheses hold, as CommonMark reads it.

    `[t](<docs/a b.md>)` names `docs/a b.md`: the angle brackets are the
    format's spelling for a destination holding a space, not part of it.
    ONE reader, for every caller that takes a destination off `MD_LINK` or
    `_REFERENCE_DEFINITION` - the link scanner, the anchor rule and both
    probes - so no caller can resolve a file named `<docs/a b.md>`, partition
    `<#heading>` on its `#` and read `<` as a file, or apply the external
    refusal to a URL still wearing its bracket. Leaves `raw` itself alone:
    what the document says is what a patch has to find on the page.
    """
    if len(raw) >= 2 and raw[0] == "<" and raw[-1] == ">":
        return raw[1:-1]
    return raw


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


def link_sites(doc: DocScope, text: str) -> list[tuple[int, str, str, bool]]:
    """Every link a caller will TRY to decide: (line, raw, target, html).

    THREE SHAPES read as one population. The inline `[text](target)` link,
    the reference-style definition `[label]: target`, and the `href` of an
    `<a>` or the `src` of an `<img>` written as raw HTML - each names a file
    the way the first does, and the second and third were read by nothing.
    The fourth value says whether a site came from HTML, because ONE refusal
    depends on it and depends on the repository as well: inside a tree a
    generator builds, a relative HTML `src` is resolved by the browser against
    the rendered page's URL, not by the generator against the source file, so
    `../../img/x.png` from `docs/user-guide/theme.md` reaches `docs/img/` on
    the site and nothing on disk. mkdocs/mkdocs writes exactly that and the
    image is there. A markdown link in the same position is rewritten by the
    generator and so still names the file. The rule applies that refusal in
    its adapter, where it can ask which tree the document is in.

    Moved out of `rules/md_link.py` - to `text.py` first, and here with the
    rest of the link scanner on 2026-09-13 - where it was the rule's private
    scanner, because it had grown a SECOND reader: `gate.suggest_renames`
    scanned the same documents for the same links with its own filter, and the
    two disagreed five ways. AGENTS.md names that shape as the recurring defect
    here and gives the remedy - "if a rule needs the same claims twice, give it
    one function and have both callers read it". `test_rules_are_leaves` lets
    only `registry.py` import a rule module, so gate.py could not read it where
    it was; this module is the home it can.

    It belongs here on the merits too, not merely by elimination. Everything it
    reads - `EXTERNAL`, `MD_LINK`, `percent_decoded`, and `strip_code` next
    door - lives in this file or in text.py, and it takes nothing off a
    Context but the DocScope, so nothing had to follow it across. It sat in
    md_link.py by history.

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
    sites: list[tuple[int, str, str, bool]] = []
    for number, line in enumerate(strip_code(doc, text).splitlines(), start=1):
        raws: list[tuple[str, bool]] = []
        if "[" in line and "(" in line:
            raws += [(raw, False) for raw in MD_LINK.findall(line)]
        # A reference-style definition, `[label]: target "title"`, is the
        # same claim as an inline link and was read by nothing. Measured on
        # the visible corpora before it was admitted - 132 repositories,
        # 77,401 documents: 3,171 definitions name a local file, across 75
        # repositories, and the shape had been examined zero times. A
        # footnote, `[^1]: text`, is not one - GFM and pandoc write it with
        # the same colon - so the label may not open with a caret. A
        # destination is read LITERALLY, parentheses included: golang writes
        # `[cockroach#10214]:(cockroach10214_test.go)` 63 times in one
        # testdata README, and CommonMark makes the destination the whole
        # parenthesised run, so the link is dead on GitHub whether or not
        # the file inside the parentheses exists - and there it does not
        # either, every one having since been renamed to `.go`.
        if "[" in line and "]:" in line:
            definition = _REFERENCE_DEFINITION.match(line)
            if definition:
                raws.append((definition.group(1), False))
        # Raw HTML. A README centres its logo with `<img src="...">` and
        # links a sibling with `<a href="...">`, and GitHub resolves both
        # against the file exactly as it resolves a markdown link. Measured
        # on the same corpora: 8,488 local attributes across 86 repositories,
        # 6,714 of them root-absolute site routes that the rule already
        # declines by the same test it applies to markdown. A value holding a
        # brace is a template expression - Jekyll's `{{ site.baseurl }}` -
        # and names no file.
        if "<" in line:
            raws += [(raw, True) for raw in _html_references(line)
                     if "{" not in raw and "}" not in raw]
        for raw, html in raws:
            target = _link_target(raw)
            if target is not None:
                sites.append((number, raw, target, html))
    return sites


# `[label]: destination`, with up to three spaces of indentation and an
# optional title after the destination, which is CommonMark's shape for a
# link reference definition. The destination is a run of non-whitespace or an
# angle-bracketed span, and the caret exclusion is the footnote refusal above.
_REFERENCE_DEFINITION = re.compile(
    r"^ {0,3}\[(?!\^)[^\]]{1,%d}\]:[ \t]*(<[^>]{1,%d}>|[^\s<][^\s]{0,%d})"
    % (_MD_LINK_SPAN, _MD_LINK_SPAN, _MD_LINK_SPAN))
# Where an anchor or image tag opens, and the `href` or `src` inside one. The
# lookbehind keeps `data-href="..."` from reading as `href`.
_HTML_TAG_OPEN = re.compile(r"<(?:a|img)\b", re.I)
_HTML_ATTRIBUTE = re.compile(
    r"(?<![\w-])(?:href|src)\s*=\s*([\"'])([^\"'<>\s]{1,%d})\1" % _MD_LINK_SPAN,
    re.I)


def _html_references(line: str) -> list[str]:
    """The `href` and `src` values of the anchor and image tags on one line.

    ONE walk along the line, tag by tag, rather than one pattern over the
    whole of it. The pattern form - `<a\\b[^>]{0,4096}?href=` - is bounded
    the way `MD_LINK` is and still costs every tag start its whole walk when
    the closing `>` never comes: measured at 12.5 seconds on a 96 KB line of
    `<a `, which is the shape that once cost `MD_LINK` three minutes. Here a
    tag runs from its opening to the next `>`, the scan resumes after that
    `>`, and an opening with no `>` after it is not a tag at all - so no
    character is walked twice and the line costs what it is long.

    The span a tag may occupy is capped at the same 4096 the link patterns
    use; an attribute further from its tag's opening than that is not read,
    which drops a finding and never invents one.
    """
    found: list[str] = []
    position = 0
    while True:
        opened = _HTML_TAG_OPEN.search(line, position)
        if opened is None:
            return found
        closed = line.find(">", opened.end())
        if closed < 0:
            return found
        tag = line[opened.end():min(closed, opened.end() + _MD_LINK_SPAN)]
        found += [m.group(2) for m in _HTML_ATTRIBUTE.finditer(tag)]
        position = closed + 1


def _link_target(raw: str) -> str | None:
    """The path a link target names, or None for one no caller will judge.

    ONE reader of the unconditional refusals, so a second link shape cannot
    admit a target the first refuses. Every refusal here is true of the link
    whatever the repository looks like; anything depending on what is on disk
    stays with the caller.
    """
    # Brackets off FIRST, before any refusal reads the string. Applied after
    # the external test, `<https://cmake.org/>` fails that test on its `<`
    # and is resolved as a file - which is the 14-finding false-positive class
    # this reader was widened for.
    raw = link_destination(raw)
    if EXTERNAL.match(raw) or raw.startswith("#"):
        return None
    # The query string is not part of the filename. `?raw=1` and `?plain=1`
    # are how GitHub serves a file, and leaving them on the target made every
    # such link resolve to nothing and report a file that is plainly there as
    # missing.
    target = raw.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return None
    # `@` opens a generator macro, not a path. Documenter.jl writes
    # `[text](@ref)` for a cross-reference and JuliaLang/julia carries 1,779
    # of them - every single one reported as a dead file, and 96% of that
    # repository's findings.
    if target.startswith("@"):
        return None
    # A markdown link percent-encodes characters that are awkward in a URL,
    # and the file on disk carries the decoded name. nlohmann/json documents
    # `operator[]` and links to it as `operator%5B%5D.md`, which is the same
    # file spelled for a browser.
    target = percent_decoded(target)
    # A `.html` target is a rendered page, in every repository and not only
    # in a detected one. MEASURED across 20 repositories in two corpora: 407
    # markdown links point at a `.html` target and NOT ONE resolves to a
    # checked-in file. Gating this on generator detection is what made rails
    # report 276 of its own guide links dead - its guides compile to HTML
    # with a bespoke builder that ships none of the configs `sites.py`
    # detects.
    #
    # Refused HERE rather than beside the site routes in a rule, because it
    # is refused whatever the repository looks like and whatever is on disk.
    # A caller that would never judge this link must not count it either.
    if target.endswith(".html"):
        return None
    return target


def percent_decoded(target: str) -> str:
    """A link target with percent-escapes resolved, or unchanged if it has none.

    Left alone when there is nothing to decode, so a path containing a literal
    `%` is never rewritten into something else.
    """
    if "%" not in target:
        return target
    from urllib.parse import unquote
    return unquote(target)
