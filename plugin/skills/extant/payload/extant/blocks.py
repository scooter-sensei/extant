"""Which lines of a markdown document are CODE: fenced, or indented.

CommonMark has two kinds of code block, and until Phase 55 they had two
scanners that could not see each other. `text.py` decided fences in a loop of
its own with no container model, so the end of a list item never closed a
fence opened inside it: kubernetes' changelogs paste terminal output into an
entry, never close the fence, and every entry after it was blanked. Measured
on 2026-09-27 against markdown-it-py's `commonmark` preset over the 152
visible corpus clones, that was 3,372 lines on GitHub-rendered documents that
the renderer shows as prose, one clone per repository (3,652 counting the
corpus's duplicate tiers). This module HAD the container model and could
not see fences, so a fence's content reached it as markup: an HTML example in
a fence opened a comment nothing closed, and every indented block after it
was read as prose. One scanner now, one container model, both kinds of block.

INDENTED CODE was measured before it was written, on 2026-09-22, the same
way. Blanking every block that reference parser finds would silence 23,540
lines carrying findings - and of the 101 in ordinary documents, 31 are PROSE:

* `!!! note` and `=== "tab"` indent a body that mkdocs-material renders as
  text (uv 6, ruff 1, dosbox-staging 4);
* `<Step>`, `<TabItem>` and `<Frame>` indent their children, which Docusaurus
  and Mintlify render as text (bun 21, goose 2);
* `:   text` is a definition list, and bazel's versioned command-line
  reference writes 21,384 lines of them, every one holding anchor links.

So indented code is CommonMark MINUS those three, and nothing at all for
`.mdx`, where the construct does not exist. Measured the same way, that keeps
exactly the 70 ordinary findings hand-read as genuine code - terminal
transcripts, generated HTTP examples, markdown syntax samples - and none of
the 31. The alternative designs are recorded in references/design.md with
their numbers.

FENCES are CommonMark's, containers included - a fence ends when the list
item, block quote, HTML comment or verbatim tag it opened in ends - with two
divergences recorded rather than repaired, each a renderer the reference is
not. A fence opens at ANY indentation: MDX has no indented code, so there it
is a fence at eight spaces, inside a JSX element's children or continuing a
paragraph, and mkdocs renders one in an admonition's body; CommonMark's "at
most three spaces" is right on GitHub and wrong on MDX sites - a fence opened
continuing a paragraph put 43 lines behind it on GitHub-rendered `.md` and 157
on MDX sites, where MDX opens it too - and this module cannot tell which
renderer a `.md` file has. And
a fence inside an HTML comment or a verbatim tag is still blanked, though
CommonMark calls it HTML: nothing inside one is rendered, and 1,014 lines of
commented-out code, one clone per repository, are not claims. The line holding the terminator is the
comment's, so it is blanked with the rest.

PURE, and read by `text.py` alone. It asks nothing of git, the filesystem or
the configuration, so a line's verdict depends on the document and nothing
else - which is what lets `text.py` memoise the blanked copy on the text.
"""
from __future__ import annotations

import re
from typing import NamedTuple

__all__ = ["TAB_STOP", "CodeLines", "_ADMONITION", "_COMMENT_OPEN", "_DEFINITION",
           "_FENCE", "_HTML_OPEN", "_QUOTE_PREFIX",
           "_STARTS_A_BLOCK", "_VERBATIM_OPEN", "_closes", "_closing", "_columns",
           "_LIST_ITEM", "_opener", "_opens", "_quote_depth",
           "_QUOTE", "code_lines", "indented_code_lines", "_content_column", "_visible_indent"]

# A tab advances to the next multiple of four, which is what CommonMark says
# and what every renderer does. bun's MDX indents with tabs throughout and
# go's doc/README.md writes its examples with one, so this is not academic.
TAB_STOP = 4

# `- `, `* `, `+ `, `1. `, `1) ` - the marker whose width decides where a list
# item's content begins, and therefore where its code would have to start.
_LIST_ITEM = re.compile(r"^(?P<marker>[-*+]|\d{1,9}[.)])(?P<spaces>[ \t]+|$)")
# One block-quote marker: `>` and the one optional space CommonMark absorbs.
_QUOTE = re.compile(r"^ {0,3}>[ ]?")
# mkdocs-material's admonitions and content tabs.
_ADMONITION = re.compile(r"^(?:!!!|\?\?\?\+?|===)(?:[ \t]|$)")
# A definition list's body. `:` then whitespace, which is python-markdown's
# `def_list` and MDX's alike.
_DEFINITION = re.compile(r"^:(?:[ \t]|$)")
# An HTML or JSX element opening a block: `<details>`, `<Step title="...">`.
# A closing tag does not open a body, and neither does an inline `<br/>` in
# the middle of a sentence, which is why this anchors at the line's start.
_HTML_OPEN = re.compile(r"^<[A-Za-z][\w.:-]*(?:[\s/>]|$)")
# A comment is an HTML block too, and the one CommonMark ends at a
# terminator rather than at a blank line. Its body is indented as often
# as not - a pull-request template is the common case, and superpowers'
# own is where the corpus found this.
_COMMENT_OPEN = re.compile(r"^<!--")
# The four elements CommonMark ends at a closing tag rather than at a blank
# line - and the ones whose bodies are indented, hold blank lines, and start
# at the margin: a directory diagram in a `<pre>`, a page script, a
# stylesheet. Any of the four closing tags ends any of the four blocks.
_VERBATIM_TAGS = ("pre", "script", "style", "textarea")
_VERBATIM_OPEN = re.compile(r"^<(?:" + "|".join(_VERBATIM_TAGS) + r")(?:[\s/>]|$)", re.I)
# What is never a lazy continuation: a heading, a fence, a thematic
# break, or a new list marker. Everything else on a line under an open
# paragraph continues it, however far left it starts.
_STARTS_A_BLOCK = re.compile(r"^(?:#{1,6}[ 	]|`{3,}|~{3,}|[-*_]{3,}\s*$|(?:[-*+]|\d{1,9}[.)])(?:[ 	]|$))")

# A fence, with everything needed to tell its CLOSER from another opener:
# the block-quote markers in front of it, the character, how many of them,
# and whatever follows on the line. Matched against the RAW line, quote
# markers and all, so the depth it counts is the one `_quote_depth` counts.
#
# The pattern was `^\s*(```|~~~)` until 2026-09-22 and the loop TOGGLED on
# every match, which got three things wrong, each measured that day against
# markdown-it-py's `commonmark` preset over the 152 visible corpus clones -
# 1,498 documents held a line the reference calls fence content and the
# stripper did not blank, with 41 findings on those lines:
#
# * a longer fence was closed by a shorter one, so a four-backtick block
#   quoting a three-backtick one went out of phase and the rest of it was
#   read as prose. Every agent transcript of a session that itself shows
#   code is this shape - 16 of the 41 are aider's posts and superpowers'
#   plans;
# * a tilde block was closed by backticks and the other way about;
# * a fence inside a block quote was never seen at all, because `\s*` does
#   not match `> `. fxamacker/cbor's README quotes a hex dump that way and
#   both moby and kubernetes vendor it.
_FENCE = re.compile(r"^(?P<quote>(?:\s*>)*)(?P<indent>\s*)(?P<run>(?P<char>`|~)(?P=char){2,})(?P<rest>.*)$")
# The same block-quote prefix on ANY line, so a fence opened inside a quote
# can tell when the quote has ended - see `_quote_depth`.
_QUOTE_PREFIX = re.compile(r"^(?:\s*>)*")


class CodeLines(NamedTuple):
    """The 1-based numbers of the lines inside each kind of code block."""

    fenced: frozenset[int]
    indented: frozenset[int]


def _closing(line: str) -> bool:
    """Does this line hold `</pre>`, `</script>`, `</style>` or `</textarea>`,
    in any case? That is CommonMark's end condition for all four verbatim
    blocks, whichever of them opened - the closing tag "need not match the
    start tag".

    Literal tags only: `</pre >` is an end tag to a browser, but CommonMark
    ends the markdown block only at `</pre>`, and markdown-it-py and
    micromark both run it on. Read as a close, the lines after it were
    scanned as markdown and an indented one blanked as code, where the
    renderer shows raw HTML - a claim silenced. Found by the mutmut
    cross-check (Phase 63), whose mutant agreed with the renderer where this
    did not; repaired in Phase 65. And any of the four: reading only the
    opener's own tag ran a `<pre>` on past `</script>`, so the code after it
    was read as raw HTML - the converse, found by Phase 65's gap audit and
    repaired with it.
    """
    lowered = line.lower()
    return any(("</" + tag + ">") in lowered for tag in _VERBATIM_TAGS)


def _visible_indent(line: str) -> tuple[int, str]:
    """(columns of indentation, the rest), counting a tab to the next stop."""
    columns = 0
    for index, char in enumerate(line):
        if char == " ":
            columns += 1
        elif char == "\t":
            columns += TAB_STOP - (columns % TAB_STOP)
        else:
            return columns, line[index:]
    return columns, ""


def _content_column(indent: int, rest: str) -> int | None:
    """Where a list item's content starts, or None if this is not one.

    The marker's width plus the spaces after it, clamped the way CommonMark
    clamps: one to four spaces put the content there, and five or more mean
    the content is an indented code block starting one space after the marker.
    """
    found = _LIST_ITEM.match(rest)
    if found is None:
        return None
    spaces, _ = _visible_indent(found.group("spaces"))
    width = len(found.group("marker"))
    return indent + width + (spaces if 1 <= spaces <= 4 else 1)


def code_lines(text: str, *, mdx: bool = False) -> CodeLines:
    """Every line inside a fenced or an indented code block, by kind.

    A fence's opener and closer are its lines, and so are the blank lines
    inside either kind of block, because they belong to it and blanking them
    changes nothing; the caller blanks what this returns. `mdx` switches off
    indented code, which MDX does not have, and HTML comments and verbatim
    tags - `<pre>` is JSX there and a comment is a parse error to MDX 3 - and
    nothing else: MDX shares CommonMark's list items and block quotes, and the
    MDX oracle (@mdx-js/mdx 3) ends a fence with its list item exactly as
    markdown-it-py does. Docusaurus accepts comments in `.mdx` all the same
    (`mdx1Compat.comments` defaults to true), so for its sites the comment
    half of that switch is wrong in principle; measured, no fenced line of any
    `.mdx` on the corpus depends on it (`m17_mdx_comments.py`, 2026-09-28).
    """
    fenced: set[int] = set()
    code: set[int] = set()
    # The innermost open list item's content column, or 0 at the margin. A
    # list rather than a single value because a nested item restores the outer
    # one's column when it closes.
    columns: list[int] = []
    # The column at which a construct that redefines indentation was opened -
    # everything indented past it is that construct's body, not code - or None.
    governed: int | None = None
    # A RAW HTML block, which CommonMark ends at a blank line rather than at a
    # dedent. The two are different mechanisms and both are needed: a card
    # grid written without blank lines is raw HTML to its last `</div>`, and a
    # closing tag that dedents past its opener would otherwise release the
    # suppression above and be read as the start of an indented block. That
    # was measured against the reference parser on 2026-09-22 at 109,293 lines
    # claimed as code that the reference calls HTML - SWE-agent's
    # documentation index alone is thirty of them.
    html = False
    comment = False            # inside an HTML comment, which ends at `-->`
    verbatim = False           # inside <pre>, <script>, <style>, <textarea>
    paragraph = False          # is a paragraph open on the line above?
    block: list[int] | None = None   # the run being collected, if any
    start = 0                  # the column a run has to beat to continue
    # The fence this scanner is inside, as (character, length, quote depth,
    # indentation) - what `_closes` compares a candidate closer with - or
    # None. Beside it, how many list items were open when it opened, since
    # the end of any of them ends it too. A fence opened inside a comment or
    # a verbatim tag holds no item: that block's terminator ends it instead.
    opened: tuple[str, int, int, int] | None = None
    items = 0
    # Split ONCE and handed to `_last_nonblank`, which split the whole
    # document again at the end of every block: O(lines x blocks), 1.22 s on
    # moby's 5,345-line v1.24 API document, found by the review of PR #16.
    lines = text.splitlines()
    for number, raw in enumerate(lines, start=1):
        line = raw
        while True:
            quoted = _QUOTE.match(line)
            if quoted is None:
                break
            line = line[quoted.end():]
        indent, rest = _visible_indent(line)
        blank = not rest
        fence = _FENCE.match(raw)
        if opened is not None and _container_ended(opened, items, raw, columns):
            # A container's end closes every block inside it, a fence
            # included, and this line is read as it would be anywhere else.
            opened = None
        if opened is not None:
            # A fence's content is never markup: nothing on this line opens
            # a comment, an item or a block, which is what the indented
            # scanner got wrong for as long as it could not see fences.
            fenced.add(number)
            if comment and "-->" in line:
                # The comment this fence opened in has ended, and the fence
                # with it: the toggle ran on past the terminator and silenced
                # the document after it - bun, qmk and deno.
                comment, opened = False, None
            elif verbatim and _closing(line):
                verbatim, opened = False, None
            elif fence is not None and _closes(fence, opened):
                opened = None
            continue
        if verbatim:
            # Runs to a closing tag, through blank lines and through lines
            # back at the margin. bazel's output-directory tree sits in a
            # `<pre>` whose first line starts at column zero and which holds
            # blank lines; every other state here would have been released by
            # one or the other, and the 27 lines of diagram below read as code.
            if _closing(line):
                verbatim = False
            elif fence is not None and _opens(fence):
                opened, items = _opener(fence), 0
                fenced.add(number)
            continue
        if comment:
            # Everything up to and including the terminator is the comment's,
            # whatever its indentation and whatever blank lines it holds. A
            # fence inside is still blanked, and ends when the comment does.
            if "-->" in line:
                comment = False
            elif fence is not None and _opens(fence):
                opened, items = _opener(fence), 0
                fenced.add(number)
            continue
        # CommonMark starts an HTML block only on a line indented less than
        # four past its container; four or more is indented code, so an
        # HTML example's `<!--` or `<pre>` is code. Read as an opener it
        # left its block and, unterminated, swallowed every later line, so
        # the next real block read as prose - found by the review of pull
        # request #16. Inside a governed body - a JSX element, an
        # admonition - indented tags are that body's markup, as always.
        container_column = columns[-1] if columns else 0
        may_open_html = indent < container_column + 4 or governed is not None
        if not mdx and may_open_html and _COMMENT_OPEN.match(rest):
            comment = "-->" not in line[line.index("<!--"):]
            paragraph = False
            continue
        opener = _VERBATIM_OPEN.match(rest) if may_open_html and not mdx else None
        if opener is not None:
            verbatim = not _closing(rest)
            paragraph = False
            continue
        if block is not None:
            # A blank line does not end a block; a non-blank line indented
            # less than it opened at does.
            if blank or indent >= start:
                block.append(number)
                continue
            code.update(n for n in block if n <= _last_nonblank(lines, block))
            block = None
        if blank:
            paragraph = False
            html = False
            continue
        # Close whatever this line has dedented out of - unless it is the
        # LAZY CONTINUATION of a paragraph inside the container, which may be
        # indented less than the container's content and does not close it.
        # A line that starts a block of its own is never a continuation, so a
        # heading or a new marker still closes the item.
        if not paragraph or _STARTS_A_BLOCK.match(rest):
            while columns and indent < columns[-1]:
                columns.pop()
        if governed is not None and indent <= governed:
            governed = None
        margin = columns[-1] if columns else 0
        if indent >= margin + 4 and not mdx and governed is None and not paragraph and not html:
            block = [number]
            start = indent
            continue
        if fence is not None and _opens(fence):
            # After the dedent above, so the items still open are exactly the
            # ones holding this fence; after the indented check, so a fence
            # line inside an indented block is that block's content.
            opened, items = _opener(fence), len(columns)
            fenced.add(number)
            paragraph = False
            continue
        # Not code: decide what this line opens for the lines below it.
        if _ADMONITION.match(rest) or _DEFINITION.match(rest) or _HTML_OPEN.match(rest):
            # The OUTERMOST opener's column is the boundary, so a nested tag
            # does not raise it and a closing tag at the outer level clears it.
            governed = indent if governed is None else min(governed, indent)
            html = html or bool(_HTML_OPEN.match(rest))
            paragraph = False
            continue
        item = _LIST_ITEM.match(rest)
        content = _content_column(indent, rest)
        if item is not None and content is not None:
            columns.append(content)
            after = rest[item.end():]
            # Five spaces or more after the marker make the content indented
            # code, which a fence line inside is content of - `_content_column`
            # clamps the same way.
            spaces, _ = _visible_indent(item.group("spaces"))
            on_marker = (_FENCE.match(after)
                         if spaces <= 4 and after.startswith(("```", "~~~")) else None)
            if on_marker is not None and _opens(on_marker):
                # ``- ```` - the item's first block is a fence, opening at the
                # item's content column. `_FENCE` anchors at the line's start
                # and never matched here, so the content was read and the
                # item's indented closer then OPENED a fence: kubernetes'
                # CHANGELOG-1.31.md and dspy's release checklist.
                opened = (on_marker.group("char"), len(on_marker.group("run")),
                          _quote_depth(raw), content)
                items = len(columns)
                fenced.add(number)
                paragraph = False
                continue
            # A marker with text after it opens a paragraph, so an indented
            # run on the next line is its continuation rather than code; a
            # bare marker does not.
            paragraph = bool(after.strip())
            continue
        paragraph = True
    if block is not None:
        code.update(n for n in block if n <= _last_nonblank(lines, block))
    return CodeLines(frozenset(fenced), frozenset(code))


def indented_code_lines(text: str, *, mdx: bool = False) -> frozenset[int]:
    """The 1-based line numbers of every line inside an indented code block.

    The indented half of `code_lines`, which is the whole of what this module
    answered before fences joined it. `.mdx` has none by construction.
    """
    return code_lines(text, mdx=mdx).indented


def _container_ended(opened: tuple[str, int, int, int], items: int, raw: str,
                     columns: list[int]) -> bool:
    """Has a container holding the open fence ENDED on this line?

    The block quote it opened in, first: a pasted message cut off mid-block is
    the common case - aider's chat-history fixture lost 129 findings in prose
    after one, found by the identity gate on 2026-09-26. Then the list item:
    a non-blank line indented less than the item's content is not in it, and
    no lazy continuation reaches into a fence. That second half has two
    consequences and both are the renderer's: an unclosed fence ends where
    its item does (kubernetes), and a closer dedented out of its item ends the
    item there and then OPENS a fence of its own, which runs to the next
    closing fence - swallowing the author's next opener - or to the end of the
    document when none follows. GitHub renders it so, and so does MDX 3.

    The indentation is measured past the quote markers the fence opened
    under and NO others: inside a fence a `>` is content - a shell prompt,
    a `diff` line, a `>&2` redirect - and stripping it as a marker read the
    line as dedented out of its item. node's root-certificate notes, cpython's
    mimalloc readme and openfoodfacts' VS Code page, found by the delta
    against the shipped stripper on 2026-09-27.
    """
    if opened[2] and _quote_depth(raw) < opened[2]:
        return True
    if not items:
        return False
    line = raw
    for _ in range(opened[2]):
        quoted = _QUOTE.match(line)
        if quoted is None:
            break
        line = line[quoted.end():]
    indent, rest = _visible_indent(line)
    return bool(rest) and indent < columns[items - 1]


def _quote_depth(line: str) -> int:
    """How many block-quote markers open this line, counted the way `_FENCE`
    counts them for the fence that opened, so the two compare like for like."""
    found = _QUOTE_PREFIX.match(line)
    return found.group(0).count(">") if found else 0


def _columns(indent: str) -> int:
    """How wide a run of indentation is, a tab reaching the next stop of four."""
    return len(indent.expandtabs(4))


def _opener(fence: "re.Match[str]") -> tuple[str, int, int, int]:
    """What `_closes` needs to know about the fence this line opens."""
    return (fence.group("char"), len(fence.group("run")),
            fence.group("quote").count(">"), _columns(fence.group("indent")))


def _opens(fence: "re.Match[str]") -> bool:
    """Is this a fence at all, rather than a line that starts like one?

    CommonMark: a backtick fence's info string may not contain a backtick. A
    line that opens with three and closes them later is an inline code span -
    kubernetes' changelogs write `` ```$ kubectl get secret ...``` `` that way -
    and reading it as a fence blanked every entry below it until a closer
    happened along. Measured on 2026-09-26 among the 1,042 prose lines the
    first version of this stripper silenced that the old toggle had read.
    """
    return not (fence.group("char") == "`" and "`" in fence.group("rest"))


def _closes(fence: "re.Match[str]", opened: tuple[str, int, int, int]) -> bool:
    """Does this fence line end the block `opened` started?

    Five conditions. The same character, a run at least as long, and the same
    block-quote depth were measured when the toggle was replaced. A closing
    fence carries no info string, so ```` ```python ```` inside a fenced block
    is content. And a closer may sit at most three columns deeper than its
    opener - four or more is the block's CONTENT, a fence shown inside a
    fence. Closing on that put the stripper out of phase and the real closer
    then opened a fence that ran to the end of the document: mini-swe-agent's
    admonition example and superpowers' reviewer template, found by the
    old-against-new measurement on 2026-09-26.
    """
    char, length, quote, indent = opened
    return (fence.group("char") == char
            and len(fence.group("run")) >= length
            and fence.group("quote").count(">") == quote
            and not fence.group("rest").strip()
            and _columns(fence.group("indent")) < indent + 4)


def _last_nonblank(lines: list[str], block: list[int]) -> int:
    """The last line of `block` that holds anything.

    Trailing blank lines sit between the block and whatever follows, and
    CommonMark does not count them as part of it. Including them would blank
    nothing (they are empty) but would report a block one or two lines longer
    than it is, which matters to the test that compares this with the
    reference parser line for line.
    """
    for number in reversed(block):
        # `strip(" 	")` rather than `strip()`: CommonMark's blank line is
        # spaces and tabs, and Python's default also removes U+00A0 and the
        # other Unicode whitespace. A line holding a no-break space is
        # CONTENT, and moby's versioned API documents are full of them.
        if 0 < number <= len(lines) and lines[number - 1].strip(" 	"):
            return number
    return block[0] - 1
