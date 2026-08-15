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
* `current_document`, `_blank`, `_blank_uncached`, `strip_code` and `prose` take
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
in and reads nothing else, so it is a pure memo that self-invalidates and has
no lifetime to state.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from extant.refs import tracked_markdown
from extant.scope import Context, DocScope

# The thirteen names with a consumer outside this module are public; the
# twenty-eight with none keep their underscore. That line is MEASURED rather
# than chosen by taste: each of the thirteen is read today by shim code that
# Task 9 turns into a rule module or into registry/sweep/cli, at which point it
# becomes a sibling and an underscore on it would be a false claim about the
# boundary - and a hard failure of
# test_no_module_reaches_past_another_modules_surface. Three of them,
# `current_document`, `anchors` and `ORDER_PREFIX`, are already read by
# sites.py in this same task.
#
# The private ones are listed here too, following extant/collect.py, which
# keeps `_CHECKED` and `_VENV_LAYOUTS` in its own `__all__`: the shim
# re-exports them under their historical names for the tests and the mutation
# harness, so they are part of what this module hands out even though no
# sibling should call them.
__all__ = [
    "ORDER_PREFIX", "_ATTR_ANCHOR", "_DIRECTIVE_LABEL", "_EXPLICIT_ANCHOR",
    "_EXTERNAL", "_FENCE", "_HEADING", "_INLINE_CODE", "_LANGUAGE_DIR",
    "_MARKDOWN_ONLY", "_MD_LINK", "_MYST_TARGET", "_NESTED_HEADING",
    "_ROUTE_DEPTH", "_RST_DIRECTIVE", "_RST_DOCTEST", "_RST_INLINE",
    "_RST_LITERAL_INTRO", "_SETEXT_RULE", "_STRIPPED", "_blank", "_blank_rst",
    "_blank_uncached", "_definition_terms", "_disambiguated", "_heading_text",
    "_route_name", "_setext_headings", "_slug", "_slug_keeping_edges",
    "_slug_punctuation_to_dash", "_translation_tree", "_without_tags",
    "anchors", "current_document", "format_for", "numbered_document",
    "percent_decoded", "prose", "strip_code", "unique_basename",
]

# Markdown link syntax is fixed by the format, not by any project's habits, so
# unlike the prose patterns this one is not configurable. There is no corpus to
# measure: `[text](target)` means the same thing everywhere.
_MD_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+?)\s*\)")
# ANY URI scheme, not an enumerated few. phoenixframework/phoenix links to
# `irc://irc.libera.chat/elixir`, and a named list will always be missing the
# next scheme somebody uses - slack:, vscode:, ssh:, matrix:. Two or more
# characters before the colon so a Windows drive letter is not mistaken for
# one; a relative path does not carry a colon before its first slash.
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]+:|//)", re.I)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
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
_MARKDOWN_ONLY = {"dead-md-link", "dead-md-anchor"}


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


def _blank(doc: DocScope, text: str, *, inline: bool) -> str:
    cached = _STRIPPED.get(inline)
    if cached is not None and cached[0] is text:
        return cached[1]
    result = _blank_uncached(doc, text, inline=inline)
    _STRIPPED[inline] = (text, result)
    return result


def _blank_uncached(doc: DocScope, text: str, *, inline: bool) -> str:
    if doc.doc_format == "rst":
        return _blank_rst(text, inline=inline)
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
            out.append(" " * len(line))
            continue
        if inside:
            out.append(" " * len(line))
        elif inline:
            out.append(_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line))
        else:
            out.append(line)
    return "\n".join(out)


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
    lines = text.splitlines()
    out: list[str] = []
    block_indent: int | None = None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            # A blank line does not end a literal block; a return to the
            # opening indentation does.
            if not stripped or indent > block_indent:
                out.append(" " * len(line))
                continue
            block_indent = None
        if _RST_DOCTEST.match(line):
            out.append(" " * len(line))
            continue
        if _RST_DIRECTIVE.match(line) or _RST_LITERAL_INTRO.search(line):
            block_indent = indent
            out.append(" " * len(line))
            continue
        out.append(_RST_INLINE.sub(lambda m: " " * len(m.group(0)), line)
                   if inline else line)
    return "\n".join(out)


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


def _definition_terms(text: str) -> list[str]:
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
    lines = text.splitlines()
    terms: list[str] = []
    for index, line in enumerate(lines[:-1]):
        if not line.strip() or line.startswith((" ", "\t", "#", ">", "-", "*", "|", "=")):
            continue
        if re.match(r"^:\s", lines[index + 1]):
            terms.append(line.strip())
    return terms


_SETEXT_RULE = re.compile(r"^(?:=+|-{2,})\s*$")


def _setext_headings(text: str) -> list[str]:
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
    lines = text.splitlines()
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
    headings = [m.group(1) for line in text.splitlines()
                if (m := _HEADING.match(line) or _NESTED_HEADING.match(line))]
    headings += _definition_terms(text)
    headings += _setext_headings(text)
    # Every spelling a renderer might produce: two slug conventions, each over
    # the heading as written and with angle-bracket markup removed. Offering a
    # spelling that no renderer uses costs nothing - a fragment matching none
    # of them is still dead - while missing one reports a working link as
    # broken, which is the failure that matters.
    variants = [v for h in headings for v in (h, _without_tags(h))]
    found = {_slug(v) for v in variants}
    found |= {_slug_punctuation_to_dash(v) for v in variants}
    found |= {_slug_keeping_edges(v) for v in variants}
    found |= {a.lower() for a in _EXPLICIT_ANCHOR.findall(text)}
    found |= {a.lower() for a in _ATTR_ANCHOR.findall(text)}
    found |= {a.lower() for a in _MYST_TARGET.findall(text)}
    found |= {a.lower() for a in _DIRECTIVE_LABEL.findall(text)}
    found |= _disambiguated(headings)
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
