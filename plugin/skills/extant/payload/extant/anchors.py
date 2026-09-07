"""What anchors a document offers: heading text, slugs, the anchor set.

Cut out of `text.py`, which answers four separable questions and had run out of
room to answer any of them at greater length - it sat at 923 lines against a
923-line ceiling, so the next line added to it failed
`tests/test_module_quality.py`. This is the third of the four, and the one with
the cleanest edge: nothing left behind in `text.py` reads a single name defined
here.

Everything here is PURE. A heading goes in, a slug comes out; no repository, no
run, no ambient state. That is why the split is possible at all, and it is
worth keeping: a function here can be tested by calling it.

The five private patterns moved WITH the code rather than being imported back
out of `text.py`. `tests/test_module_quality.py` forbids one module importing
another's underscore names, so leaving them behind would have meant either
promoting five patterns nothing else reads or reaching through the wall. They
have exactly one reader each, `anchors()`, and they are now beside it.

`HEADING` is the one name still imported from `text.py`, and it stays there
because `rules/manifest_floor.py` reads it too - it is a fact about markdown
syntax rather than part of this machinery.
"""
from __future__ import annotations

import re

from extant.text import HEADING

# Two names are public and the rule is the one every module here follows: a
# name is public when a sibling calls it. `anchors` is called by `sites.py` and
# by `rules/md_anchor.py`; everything else below has readers only in this file.
# The private names are listed anyway, as the record of what this module owns,
# following `text.py` and `collect.py`.
__all__ = [
    "_ATTR_ANCHOR", "_DIRECTIVE_LABEL", "_EXPLICIT_ANCHOR", "_MYST_TARGET",
    "_NESTED_HEADING", "_SETEXT_RULE", "_definition_terms", "_disambiguated",
    "_heading_text", "_setext_headings", "_slug", "_slug_keeping_edges",
    "_slug_punctuation_to_dash", "_without_tags",
    "anchors",
]

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
