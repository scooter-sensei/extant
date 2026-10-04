"""CommonMark's other code block, and the three constructs that redefine it.

`prose()` blanked fenced blocks and inline spans and nothing else, so a
four-space-indented block - the other half of CommonMark's code - was read as
prose and its claims were checked. Measured on 2026-09-22 with markdown-it-py's
`commonmark` preset over the 152 visible corpus clones: blanking every block
the reference finds would silence 23,540 lines' worth of findings, and 31 of
the 101 in ordinary documents are PROSE, because three constructs indent a body
by four spaces and render it as text:

* mkdocs-material's admonitions and content tabs - `!!! note`, `=== "tab"` -
  whose body is the widget's content (uv 6, ruff 1, dosbox-staging 4);
* MDX and JSX elements - `<Step>`, `<TabItem>`, `<Frame>` - whose children are
  indented by convention (bun 21, goose 2);
* definition lists - `:   text` - whose body is the definition (bazel's
  versioned command-line reference, 21,384 lines).

So what ships is CommonMark MINUS those three, and `.mdx` not at all: measured
the same way, that silences the same 70 findings in ordinary documents that
were hand-read as genuine code - terminal transcripts, generated HTTP examples,
markdown syntax samples - and not one of the 31.

The tests below are one pair per rule: the code it must blank, and the prose it
must not.
"""
from __future__ import annotations

import pytest


def _lines(text: str, *, mdx: bool = False) -> set[int]:
    from extant.blocks import indented_code_lines
    return set(indented_code_lines(text, mdx=mdx))


# --------------------------------------------------------------------------
# 1. The block itself
# --------------------------------------------------------------------------

def test_a_top_level_indented_block_is_code() -> None:
    """Four spaces after a blank line, which is the whole of the shape moby's
    vagrant walkthrough and restic's README are written in."""
    text = ("Check that it works:\n"
            "\n"
            "    $ docker network ls\n"
            "    4275f8b3a821   none   null\n"
            "\n"
            "Prose again.\n")
    assert _lines(text) == {3, 4}


def test_an_indented_run_cannot_interrupt_a_paragraph() -> None:
    """CommonMark: without a blank line above it, the indentation is a lazy
    continuation of the paragraph and the text is prose."""
    text = ("A sentence that wraps\n"
            "    onto the next line at four spaces.\n")
    assert _lines(text) == set()


def test_a_blank_line_does_not_end_a_block() -> None:
    """It ends at the first non-blank line indented less, and blank lines in
    the middle belong to it - the shape of every transcript with a gap in it."""
    text = ("Output:\n"
            "\n"
            "    first\n"
            "\n"
            "    second\n"
            "\n"
            "Prose.\n")
    assert _lines(text) == {3, 4, 5}


def test_a_tab_counts_as_four_columns() -> None:
    """go's doc/README.md writes its examples with a tab, and bun's MDX
    indents with tabs throughout."""
    text = ("Use these forms:\n"
            "\n"
            "\t[#12345](/issue/12345)\n"
            "\n"
            "Prose.\n")
    assert _lines(text) == {3}


# --------------------------------------------------------------------------
# 2. Containers, which move the column the indentation is measured from
# --------------------------------------------------------------------------

def test_four_spaces_under_a_list_item_is_a_continuation_paragraph() -> None:
    """A list item's content starts at column 2, so four spaces is two past
    it - prose. This is the false negative the whole measurement was for."""
    text = ("- An item:\n"
            "\n"
            "    still the item, at four spaces.\n")
    assert _lines(text) == set()


def test_six_spaces_under_a_list_item_is_code() -> None:
    """Four past the content column, which is what CommonMark asks for."""
    text = ("- An item:\n"
            "\n"
            "      $ a command\n")
    assert _lines(text) == {3}


def test_a_block_quote_marker_is_stripped_before_the_indent_counts() -> None:
    """`> ` is not indentation; the four spaces after it are."""
    text = ("> Output:\n"
            ">\n"
            ">     $ a command\n"
            "\n"
            "Prose.\n")
    assert _lines(text) == {3}


def test_a_quoted_paragraph_is_not_code() -> None:
    """The other half of the pair above: one space after `>` is prose."""
    text = ("> A quoted sentence,\n"
            ">\n"
            "> and another.\n")
    assert _lines(text) == set()


# --------------------------------------------------------------------------
# 3. The three constructs that redefine four spaces, and .mdx
# --------------------------------------------------------------------------

def test_an_admonition_body_is_prose() -> None:
    """mkdocs-material renders `!!! note` and its indented body as text. uv,
    ruff and dosbox-staging hold 11 real findings in one."""
    text = ("!!! note\n"
            "\n"
            "    The [`keyring-provider`](../settings.md#keyring) setting can be used.\n"
            "\n"
            "Prose.\n")
    assert _lines(text) == set()


def test_a_content_tab_body_is_prose() -> None:
    """`=== \"tab\"` is the same construct with a different marker."""
    text = ('=== "macOS"\n'
            "\n"
            "    See [the guide](guide.md) for the detail.\n")
    assert _lines(text) == set()


def test_a_definition_list_body_is_prose() -> None:
    """`:   text` is a definition, and bazel's versioned command-line
    reference writes 21,384 lines of them - every one holding anchor links
    the site renders."""
    text = ("`--[no]autodetect_server_javabase` default: \"true\"\n"
            ":   When passed, Bazel does not fall back.\n"
            "\n"
            "    Tags:\n"
            "    [`affects_outputs`](#effect_tag_AFFECTS_OUTPUTS)\n")
    assert _lines(text) == set()


def test_a_jsx_element_body_is_prose() -> None:
    """Docusaurus and Mintlify indent a component's children; goose and bun
    hold 23 real findings inside one."""
    text = ("<Step title=\"Create a migration\">\n"
            "\n"
            "    Generate the migration, which writes a `.sql` file to [prisma](prisma/).\n"
            "\n"
            "</Step>\n")
    assert _lines(text) == set()


def test_an_html_block_body_is_prose() -> None:
    """The same for plain HTML, which a README uses for a details block."""
    text = ("<details>\n"
            "\n"
            "    See [the guide](guide.md).\n"
            "\n"
            "</details>\n")
    assert _lines(text) == set()


def test_mdx_has_no_indented_code_at_all() -> None:
    """MDX removed the construct: four spaces there is never a code block,
    whatever else is true of the document."""
    text = ("Prose.\n"
            "\n"
            "    $ a command that LOOKS like code\n")
    assert _lines(text, mdx=True) == set()
    assert _lines(text, mdx=False) == {3}


def test_an_indented_block_after_an_admonition_closes_with_it() -> None:
    """The suppression is the construct's body, not the rest of the document:
    once the indentation returns to the marker's column, an indented block
    below is code again."""
    text = ("!!! note\n"
            "\n"
            "    Prose in the admonition.\n"
            "\n"
            "Back at the margin:\n"
            "\n"
            "    $ a command\n")
    assert _lines(text) == {7}


def test_an_html_block_runs_to_a_blank_line_not_to_a_dedent() -> None:
    """CommonMark ends an HTML block at a BLANK line, and a card grid has
    none in it: every tag sits at its own indentation and the closing ones
    dedent. Measured against the reference parser over the 152 visible corpus
    clones on 2026-09-22, treating the body as ending at a dedent claimed
    109,293 lines as code that the reference calls raw HTML - SWE-agent's
    documentation index alone is thirty of them - because a `</div>` that
    dedents past the opener released the suppression and was then read as
    the start of an indented block.
    """
    text = ('<div class="grid cards">\n'
            '  <div class="card">\n'
            '    <a href="install.md">\n'
            '        <span class="title">Installation</span>\n'
            '      </div>\n'
            '      <p class="description">See [the guide](guide.md).</p>\n'
            '    </div>\n'
            '</div>\n')
    assert _lines(text) == set()


def test_an_indented_block_after_an_html_block_is_code_again() -> None:
    """The other half: the blank line ends the HTML block, so what follows is
    read as it would be anywhere else."""
    text = ("<div>\n"
            "  <span>Title</span>\n"
            "</div>\n"
            "\n"
            "Then:\n"
            "\n"
            "    $ a command\n")
    assert _lines(text) == {7}


def test_an_html_comment_runs_to_its_terminator() -> None:
    """A comment is an HTML block that ends at `-->` rather than at a blank
    line, and its body is indented as often as not - a pull-request template
    is the common case. Measured against the reference parser over the 152
    visible corpus clones on 2026-09-22: not recognising it left 1,216 lines
    called code here that the reference calls comment content, superpowers'
    own template among them.
    """
    text = ("<!-- Describe the change.\n"
            "\n"
            "     - Would this help somebody on [another project](other.md)?\n"
            "     - Is it tool-specific? -->\n"
            "\n"
            "Then:\n"
            "\n"
            "    $ a command\n")
    assert _lines(text) == {8}


def test_a_lazily_continued_list_item_stays_open() -> None:
    """A paragraph inside a list item may wrap onto a line indented LESS than
    the item's content - CommonMark calls it lazy continuation and the item
    stays open. Treating that wrap as a dedent closed the item, and the
    four-space lines below it then measured from the margin and read as code.

    kubernetes' `staging/README.md` is the case: a numbered step wraps to
    column 0, and the nested bullets under it hold links the site renders.
    Measured against the reference parser over the 152 visible corpus clones
    on 2026-09-22 at 1,058 lines, kubernetes' changelogs and moby's versioned
    API documents between them.
    """
    text = ("3. Once the repository exists,\n"
            "update the publishing bot by editing:\n"
            "\n"
            "    - [`rules.yaml`](/staging/publishing/rules.yaml):\n"
            "    Make sure the dependencies reflect the staging repositories.\n")
    assert _lines(text) == set()


def test_a_real_dedent_after_a_blank_line_still_closes_the_item() -> None:
    """The other half: a blank line ends the paragraph, so a line back at the
    margin closes the item and an indented run below it is code again."""
    text = ("3. A step.\n"
            "\n"
            "Back at the margin:\n"
            "\n"
            "    $ a command\n")
    assert _lines(text) == {5}


def test_a_pre_or_script_block_runs_to_its_closing_tag() -> None:
    """`<pre>`, `<script>`, `<style>` and `<textarea>` are the HTML blocks
    CommonMark ends at their own closing tag rather than at a blank line, and
    they are the ones whose bodies are indented and full of blank lines.

    The whole of the corpus disagreement that survived the other four rules
    was this: bazel's output-directory tree inside a `<pre>`, and dosbox's
    and rust's `<script>` bodies - 994 lines on 2026-09-22. They are read as
    they were before this module existed, which is what matching the
    reference means here.
    """
    text = ("<pre>\n"
            "  tree/\n"
            "\n"
            "    deeper/   <== still the diagram\n"
            "</pre>\n"
            "\n"
            "Then:\n"
            "\n"
            "    $ a command\n")
    assert _lines(text) == {9}


def test_a_no_break_space_is_content_not_blankness() -> None:
    """CommonMark's blank line is spaces and tabs only. Python's `.strip()`
    also removes U+00A0 and the rest of Unicode's whitespace, so a line
    holding one read as empty and the block around it was discarded.

    moby's versioned API documents are written that way - `Query
    Parameters:` followed by an indented no-break space - and that one
    character is most of the 2,035 lines the reference called code and this
    module did not on 2026-09-22.
    """
    text = ("Query Parameters:\n"
            "\n"
            "    \xa0\n"
            "\n"
            "-   **all** - show all containers\n")
    assert _lines(text) == {3}


def test_an_html_opener_inside_an_indented_block_is_code() -> None:
    """A line indented into an open block is its content whatever it holds.
    The comment and verbatim-tag checks ran BEFORE the block was continued,
    so an indented `<!--` in an HTML example left the block - and, never
    terminated in the sample, turned every later line into comment, so the
    next real block was read as prose. Found by the review of pull request
    #16; CommonMark and markdown-it-py agree the whole run is code."""
    text = ("An HTML template:\n"
            "\n"
            "    <!-- start of the template\n"
            "    <pre>\n"
            "    <div>body</div>\n"
            "\n"
            "Then run:\n"
            "\n"
            "    $ make docs\n")
    assert _lines(text) == {3, 4, 5, 9}


def test_the_document_is_split_once_however_many_blocks_it_holds() -> None:
    """`_last_nonblank` split the whole document again at the end of every
    block: O(lines x blocks), 1.22 s on moby's 5,345-line v1.24 API document
    and paid twice per document, once for each stripped copy. Counted
    rather than timed, so the test cannot flake: the text is a `str` that
    counts its own `splitlines` calls."""
    class Counting(str):
        calls = 0

        def splitlines(self, keepends: bool = False) -> list[str]:
            Counting.calls += 1
            return super().splitlines(keepends)

    text = Counting("".join(f"Step {n}:\n\n    $ run {n}\n\n" for n in range(50)))
    assert len(_lines(text)) == 50
    assert Counting.calls == 1, f"split {Counting.calls} times for 50 blocks"


# --------------------------------------------------------------------------
# 6. A fence's content is not structure
#
# This scanner could not see fences: `text.py` decided them in a loop of its
# own, and the lines inside one reached this state machine as if they were
# markup. Found by the audit of tranche 17's design on 2026-09-27, with
# markdown-it-py agreeing on each expected set below; one scanner for both
# kinds of code block is the repair.
# --------------------------------------------------------------------------

def test_a_comment_opener_inside_a_fence_does_not_hide_later_code() -> None:
    """An HTML example in a fence opened a comment here that nothing closed,
    and every indented block after it was read as prose."""
    text = ("Intro.\n"
            "\n"
            "```html\n"
            "<!-- a comment example\n"
            "```\n"
            "\n"
            "Text.\n"
            "\n"
            "    real indented code\n")
    assert _lines(text) == {9}


def test_a_pre_opener_inside_a_fence_does_not_hide_later_code() -> None:
    """The same with a verbatim tag, which runs to a `</pre>` that never
    comes."""
    text = ("Intro.\n"
            "\n"
            "```html\n"
            "<pre>\n"
            "```\n"
            "\n"
            "    real indented code\n"
            "\n"
            "more\n")
    assert _lines(text) == {7}


def test_an_indented_block_straight_after_a_closing_fence_is_code() -> None:
    """A closing fence is not a paragraph, so nothing is open for the next
    line to continue lazily; this scanner saw a line of text there."""
    text = ("Intro.\n"
            "\n"
            "```\n"
            "code\n"
            "```\n"
            "    indented after a fence\n")
    assert _lines(text) == {6}


@pytest.mark.parametrize("text, expected", [
    ("Text\n"
     "```\n"
     "code\n"
     "```\n"
     "    indented after a fence\n", {5}),
    ("- item text\n"
     "  ```\n"
     "  code\n"
     "  ```\n"
     "      indented after a fence\n", {5}),
])
def test_a_fence_that_interrupts_a_paragraph_ends_it(text: str, expected: set[int]) -> None:
    """The test above has a blank line before its fence, so no paragraph is
    open to begin with and cannot show whether opening a fence ENDS one. A
    fence may interrupt a paragraph, and CommonMark then reads a four-space
    line after its closer as code, at the margin and inside a list item alike
    - markdown-it-py agrees on both. Found by the audit of the built tranche
    on 2026-09-28: dropping the reset when a fence opens survived every
    test."""
    assert _lines(text) == expected


# --------------------------------------------------------------------------
# 7. What mutmut found that no test held (Phase 63)
#
# mutmut 3.8.0 mutated every function of extant/blocks.py on 2026-10-02 and
# 67 of its 427 mutants survived the whole suite. Read one by one, 37 were
# real behaviour no test pinned, in sixteen shapes; the rest were
# equivalent, or contrived, and are recorded in the design rationale's part
# on keeping the tool honest. One test per shape, each watched red against
# every mutant of its shape. The expected sets are the renderer's -
# markdown-it-py 4.0.0's `commonmark` preset and micromark agreeing on
# each - except where a test says it holds a recorded divergence instead.
# --------------------------------------------------------------------------

def test_a_closing_tag_with_text_after_it_still_closes_a_pre_block() -> None:
    """`</pre>` ends the block wherever it sits on the line - CommonMark's
    end condition is that the line CONTAINS it - so the indented block
    after it is code. Read from the wrong offset, the tag was missed and
    the `<pre>` swallowed the rest of the document."""
    text = ("<pre>\n"
            "x\n"
            "</pre> after\n"
            "\n"
            "    code\n")
    assert _lines(text) == {5}


@pytest.mark.parametrize("closer, expected", [
    ("</pre >", set()),
    ("</pre\t>", set()),
    ("</PRE>", {5}),
])
def test_a_pre_block_ends_only_at_the_literal_closing_tag(
        closer: str, expected: set[int]) -> None:
    """CommonMark ends a `<pre>` block at a line CONTAINING `</pre>`, in any
    case, and at nothing else: `</pre >` is an end tag to a browser, but
    the markdown block runs on, so the lines after it are raw HTML, not
    code, and the claims in them are read - markdown-it-py and micromark
    agree. Read as a close, the indented line below was code and blanked:
    a claim silenced. Found by the mutmut cross-check (Phase 63), whose
    mutant agreed with the renderer and the tree did not; repaired in
    Phase 65."""
    text = ("<pre>\n"
            "x\n"
            f"{closer}\n"
            "\n"
            "    code\n")
    assert _lines(text) == expected


@pytest.mark.parametrize("text, expected", [
    # A tab after a tab reaches the NEXT stop: two tabs are eight columns,
    # four past `10. `'s content column, so the line is code in the item.
    ("10. item\n"
     "\n"
     "\t\tcode\n", {3}),
    # A tab after one space reaches column four, not five: two past `- `'s
    # content column, which is a paragraph in the item and not code.
    ("- item\n"
     "\n"
     " \tcontinued\n", set()),
])
def test_a_tab_after_other_indentation_reaches_the_next_stop(
        text: str, expected: set[int]) -> None:
    """The tab tests above all start a line with a tab, where reaching the
    next stop and adding four agree. After a space or another tab they do
    not, and only the stop is CommonMark's."""
    assert _lines(text) == expected


@pytest.mark.parametrize("text, line, is_code", [
    # Four spaces after the marker put the content at column five, so a
    # line at eight is three past it: a paragraph, not code.
    ("-    item\n"
     "\n"
     "        code\n", 3, False),
    # Five put it one space after the marker - column two - so six is code.
    # Line 1 is the recorded divergence: CommonMark makes the marker line's
    # own content indented code, and this module reads it as a paragraph
    # (design/code-blocks.md, "What is left unread in the other direction").
    ("-     code\n"
     "\n"
     "      more\n", 3, True),
])
def test_four_spaces_after_a_marker_set_the_column_and_five_do_not(
        text: str, line: int, is_code: bool) -> None:
    """One to four spaces after a list marker are where its content starts;
    five or more mean the content is indented code one space after the
    marker, and the column falls back there."""
    assert (line in _lines(text)) is is_code


def test_a_caller_naming_no_format_gets_the_markdown_reading() -> None:
    """`mdx` defaults to False in both entry points, which text.py's
    comment states - a caller that named no path gets indented code, since
    nothing then says the document is MDX. Every caller in the package
    passes it, so nothing else would notice the default turning."""
    from extant.blocks import code_lines, indented_code_lines
    text = "text\n\n    code\n"
    assert code_lines(text).indented == {3}
    assert indented_code_lines(text) == {3}


def test_an_indented_block_on_the_first_line_is_code() -> None:
    """Nothing is open above line 1, so it starts a block like any other -
    and a block on line 1 keeps line 1 when its trailing blanks are cut."""
    assert _lines("    code on line 1\n") == {1}


def test_a_comment_indented_inside_an_item_is_an_html_block() -> None:
    """`<!--` four columns in, under `- `, is two past the item's content
    column, so it opens an HTML block there - not indented code, which
    would need six. Measured from the margin instead of the item, the
    comment was read as a paragraph and the code below it as its
    continuation."""
    text = ("- item\n"
            "\n"
            "    <!-- c -->\n"
            "      code\n")
    assert _lines(text) == {4}


def test_a_comment_closed_on_its_own_line_does_not_run_on() -> None:
    """`<!-- one line -->` opens and closes on one line. Taken as still
    open, it ran to the next `-->` anywhere below and took the code with
    it."""
    text = ("<!-- one line -->\n"
            "\n"
            "    code\n")
    assert _lines(text) == {3}


@pytest.mark.parametrize("text, expected", [
    ("<!-- one line -->\n"
     "    code\n", {2}),
    ("<pre>x</pre>\n"
     "    code\n", {2}),
    # The `<div>` is an HTML block, not a paragraph, so `x` at the margin
    # ends the item rather than continuing it, and the four-space line
    # after the blank is code at the margin.
    ("- item\n"
     "\n"
     "  <div>\n"
     "x\n"
     "\n"
     "    code\n", {6}),
    ("- ```\n"
     "  x\n"
     "  ```\n"
     "      code\n", {4}),
])
def test_an_indented_line_straight_after_a_non_paragraph_block_is_code(
        text: str, expected: set[int]) -> None:
    """The fence test above, for the other blocks that end without leaving
    a paragraph open: a one-line comment, a one-line `<pre>`, an HTML
    opener, and a fence on a list marker's line. Indented code cannot
    interrupt a paragraph, so taking any of them for one hid the code."""
    assert _lines(text) == expected


def test_a_pre_block_closed_on_its_own_line_does_not_run_on() -> None:
    """`<pre>x</pre>` is a whole verbatim block. Taken as still open, it ran
    to the next `</pre>`, which here never comes."""
    text = ("<pre>x</pre>\n"
            "\n"
            "    code\n")
    assert _lines(text) == {3}


def test_a_nested_element_does_not_raise_the_boundary() -> None:
    """A RECORDED DIVERGENCE, not CommonMark's answer: an element's indented
    body is prose here (bun's `<Step>` children, rendered as text by the
    MDX sites that write them), and CommonMark would call line 5 code.
    Within that rule, the OUTERMOST opener's column is the boundary - a
    nested `<Step>` at two does not raise it, so closing the inner element
    at two does not end the outer one's body."""
    text = ("<Steps>\n"
            "  <Step>\n"
            "  </Step>\n"
            "\n"
            "    body\n"
            "</Steps>\n")
    assert _lines(text) == set()


def test_a_closing_tag_under_an_html_opener_opens_no_indented_block() -> None:
    """CommonMark reads both indented lines as the paragraph's continuation
    - nothing at four columns interrupts one - so neither is code. This
    scanner reaches the same answer by reading the `<div>` as raw HTML,
    which only a blank line ends; forgetting that, the `</div>` that
    dedents to the opener's column released the body and opened an
    indented block - `code_lines`' own 109,293-line case, in two lines."""
    text = ("text\n"
            "    <div>\n"
            "    </div>\n")
    assert _lines(text) == set()
