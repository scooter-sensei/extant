"""Which lines of a markdown document are an INDENTED code block.

CommonMark has two kinds of code block and `text.py` only ever recognised one.
A fence is unmistakable; four spaces is not, because four spaces means
something different inside a list item, inside a block quote, and inside three
constructs that CommonMark has never heard of but that most documentation is
written with. That is why this is a module rather than a pattern, and why it
exists at all rather than the rule being "blank anything indented by four".

MEASURED BEFORE IT WAS WRITTEN, on 2026-09-22, with markdown-it-py's
`commonmark` preset as the oracle over the 152 visible corpus clones. Blanking
every block that reference parser finds would silence 23,540 lines carrying
findings - and of the 101 in ordinary documents, 31 are PROSE:

* `!!! note` and `=== "tab"` indent a body that mkdocs-material renders as
  text (uv 6, ruff 1, dosbox-staging 4);
* `<Step>`, `<TabItem>` and `<Frame>` indent their children, which Docusaurus
  and Mintlify render as text (bun 21, goose 2);
* `:   text` is a definition list, and bazel's versioned command-line
  reference writes 21,384 lines of them, every one holding anchor links.

So what this implements is CommonMark MINUS those three, and nothing at all for
`.mdx`, where the construct does not exist. Measured the same way, that keeps
exactly the 70 ordinary findings hand-read as genuine code - terminal
transcripts, generated HTTP examples, markdown syntax samples - and none of the
31. The alternative designs are recorded in references/design.md with their
numbers: the faithful one is refused there, and the narrower "top level only"
one selects the same findings as this on the whole corpus, so the container
model below is what happens the day a list item does hold a real command.

PURE, and read by `text.py` alone. It asks nothing of git, the filesystem or
the configuration, so a line's verdict depends on the document and nothing
else - which is what lets `text.py` memoise the blanked copy on the text.
"""
from __future__ import annotations

import re

__all__ = ["TAB_STOP", "_ADMONITION", "_COMMENT_OPEN", "_DEFINITION", "_HTML_OPEN",
           "_STARTS_A_BLOCK", "_VERBATIM_OPEN", "_closing",
           "_LIST_ITEM",
           "_QUOTE", "indented_code_lines", "_content_column", "_visible_indent"]

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
# The four elements CommonMark ends at their OWN closing tag rather than
# at a blank line - and the ones whose bodies are indented, hold blank
# lines, and start at the margin: a directory diagram in a `<pre>`, a
# page script, a stylesheet.
_VERBATIM_OPEN = re.compile(r"^<(?P<tag>pre|script|style|textarea)(?:[\s/>]|$)", re.I)
# What is never a lazy continuation: a heading, a fence, a thematic
# break, or a new list marker. Everything else on a line under an open
# paragraph continues it, however far left it starts.
_STARTS_A_BLOCK = re.compile(r"^(?:#{1,6}[ 	]|`{3,}|~{3,}|[-*_]{3,}\s*$|(?:[-*+]|\d{1,9}[.)])(?:[ 	]|$))")


def _closing(tag: str, line: str) -> bool:
    """Does this line hold `</tag>`, whatever its case or spacing?"""
    lowered = line.lower()
    at = lowered.find("</" + tag)
    return at >= 0 and lowered[at + len(tag) + 2:].lstrip().startswith(">")


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


def indented_code_lines(text: str, *, mdx: bool = False) -> frozenset[int]:
    """The 1-based line numbers of every line inside an indented code block.

    Blank lines inside a block are included, because they belong to it and
    blanking them changes nothing; the caller blanks what this returns.
    """
    if mdx:
        return frozenset()
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
    verbatim: str | None = None   # inside <pre>, <script>, <style>, <textarea>
    paragraph = False          # is a paragraph open on the line above?
    block: list[int] | None = None   # the run being collected, if any
    start = 0                  # the column a run has to beat to continue
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
        if verbatim is not None:
            # Runs to its OWN closing tag, through blank lines and through
            # lines back at the margin. bazel's output-directory tree sits in
            # a `<pre>` whose first line starts at column zero and which holds
            # blank lines; every other state here would have been released by
            # one or the other, and the 27 lines of diagram below read as code.
            if _closing(verbatim, line):
                verbatim = None
            continue
        if comment:
            # Everything up to and including the terminator is the comment's,
            # whatever its indentation and whatever blank lines it holds.
            if "-->" in line:
                comment = False
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
        if may_open_html and _COMMENT_OPEN.match(rest):
            comment = "-->" not in line[line.index("<!--"):]
            paragraph = False
            continue
        opener = _VERBATIM_OPEN.match(rest) if may_open_html else None
        if opener is not None:
            tag = opener.group("tag").lower()
            verbatim = None if _closing(tag, rest) else tag
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
        if indent >= margin + 4 and governed is None and not paragraph and not html:
            block = [number]
            start = indent
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
            # A marker with text after it opens a paragraph, so an indented
            # run on the next line is its continuation rather than code; a
            # bare marker does not.
            paragraph = bool(rest[item.end():].strip())
            continue
        paragraph = True
    if block is not None:
        code.update(n for n in block if n <= _last_nonblank(lines, block))
    return frozenset(code)


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
