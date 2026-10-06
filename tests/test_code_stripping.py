"""The offset contract `strip_code` states, and did not keep.

`strip_code` and `prose` blank code with SPACES rather than removing it, and
their docstrings say why: "both the line count and every character offset
survive", so a caller may take a span from the stripped text and use it against
the original. Two callers do exactly that - the `dead-md-link` and
`dead-md-anchor` probes splice `match.span(1)` from the stripped text into the
untouched document.

The contract was not kept. Both blanking paths ran `text.splitlines()` and
rejoined with `"\\n"`, which drops the real terminator and reinstates a bare
newline: every `\\r\\n` lost a character, and a trailing newline was lost even on
LF input. On this repository's own status document that was 1627 characters, so
on a CRLF checkout every offset past the first line was wrong and both probes
spliced into the wrong place. The probe then reported that it had corrupted a
real match while the rule, reading an untouched claim, correctly found nothing -
`--selftest` exiting 1 on Windows and 0 on Linux for the same commit.

CI could not see it. The runners check out LF, where the only casualty is the
final newline and every offset a probe cares about still lines up.

These tests pin the contract itself rather than the two probes, because the
contract is what the next caller will rely on.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from conftest import GitRepo

if TYPE_CHECKING:
    from extant.scope import DocScope

DOC = (
    "# Title\r\n"
    "\r\n"
    "Prose with `inline code` in it.\r\n"
    "\r\n"
    "```python\r\n"
    "x = [a link](target.md)\r\n"
    "```\r\n"
    "\r\n"
    "A [real link](docs/plan.md) after the fence.\r\n"
)


def _doc_scope(fmt: str = "markdown") -> DocScope:
    from extant import session as hc
    hc.set_document(doc_format=fmt)
    return hc._DOC


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_strip_code_preserves_the_length_of_the_document(newline: str) -> None:
    """The promise in the docstring, stated as the equality it claims.

    Length is the whole of it: the function only ever replaces a run of
    characters with the same number of spaces, so any difference means a
    terminator was rewritten and every offset after it has moved.
    """
    from extant.text import strip_code
    text = DOC.replace("\r\n", newline)

    stripped = strip_code(_doc_scope(), text)

    assert len(stripped) == len(text), (
        f"{len(text) - len(stripped)} character(s) lost with "
        f"{newline!r} terminators; every offset after the first is now wrong")


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_prose_preserves_the_length_of_the_document(newline: str) -> None:
    """`prose` shares the blanking path and states the same promise."""
    from extant.text import prose
    text = DOC.replace("\r\n", newline)

    assert len(prose(_doc_scope(), text)) == len(text)


def test_a_span_taken_from_the_stripped_text_lands_on_the_original() -> None:
    """The property the two probes actually depend on, on CRLF.

    Length equality alone would be satisfied by a function that shifted
    characters around without losing any. What a probe needs is that a match
    found in the stripped text sits at the SAME index in the original, which is
    what makes `text[:start] + replacement + text[end:]` replace the thing that
    was matched.
    """
    from extant.links import MD_LINK
    from extant.text import strip_code
    text = DOC                                   # CRLF, as Windows checks out

    stripped = strip_code(_doc_scope(), text)
    match = next(m for m in MD_LINK.finditer(stripped)
                 if not m.group(1).startswith("#"))
    start, end = match.span(1)

    assert text[start:end] == match.group(1), (
        f"stripped text matched {match.group(1)!r} at {start}:{end}, but the "
        f"original holds {text[start:end]!r} there")
    # The fenced link must not be the one found: it is code, so it is blanked.
    assert match.group(1) == "docs/plan.md"


def test_the_trailing_newline_survives() -> None:
    """The LF casualty, which is small enough to have gone unnoticed.

    One character, at the very end, so no probe ever mis-spliced because of it
    on Linux. It is still the same defect as the CRLF loss - the rejoin decides
    the terminator instead of preserving it - and pinning only the CRLF half
    would leave a fix free to keep dropping this one.
    """
    from extant.text import strip_code
    text = "# Title\n\nSome prose.\n"

    assert strip_code(_doc_scope(), text).endswith("\n")


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_rst_stripping_preserves_the_length_too(newline: str) -> None:
    """The reStructuredText path is a second copy of the same loop.

    It carries the same sentence in its docstring - "line numbers and offsets
    survive for every rule that shares this" - and had the same defect. Fixing
    only the markdown path would leave an rst document mis-spliced in exactly
    the way this whole file is about.
    """
    from extant.text import strip_code
    text = ("Title\r\n"
            "=====\r\n"
            "\r\n"
            "A literal block::\r\n"
            "\r\n"
            "    x = [a link](target.md)\r\n"
            "\r\n"
            "Prose with ``inline`` after it.\r\n").replace("\r\n", newline)

    assert len(strip_code(_doc_scope("rst"), text)) == len(text)


# --------------------------------------------------------------------------
# What closes a fence, and what opens one. Measured 2026-09-22 against
# markdown-it-py's `commonmark` preset over the 152 visible corpus clones:
# 1,498 documents hold a line the reference parser calls fence content and
# this stripper does not blank, and 41 findings sit on those lines - claims
# the tool checked out of a code block.
# --------------------------------------------------------------------------

def _prose(text: str, fmt: str = "markdown") -> str:
    from extant.text import prose
    return prose(_doc_scope(fmt), text)


def test_a_longer_fence_is_not_closed_by_a_shorter_one() -> None:
    """CommonMark closes a fence only with the same character, at least as
    long as the opener. The toggle closed on any run of three, so a
    four-backtick block quoting a three-backtick one went OUT OF PHASE and
    everything after the inner fence was read as prose.

    aider's posts and superpowers' plan documents are full of it - a
    transcript of a session that itself shows fenced code - and that is where
    16 of the 41 findings measured on the corpus come from.
    """
    text = ("````\n"
            "Here is what the assistant wrote:\n"
            "```python\n"
            "x = 1\n"
            "```\n"
            "Merged at a1b2c3d, it says.\n"
            "````\n"
            "\n"
            "Real prose, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "a claim inside the outer fence was read as prose"
    assert "d4e5f6a" in blanked, "prose after the block was blanked"


def test_a_fence_inside_a_block_quote_is_still_a_fence() -> None:
    """`_FENCE` anchored on optional whitespace only, so `> ```' never matched
    and the quoted block was read as prose from its first line to its last.
    fxamacker/cbor's README quotes a hex dump that way, and moby and
    kubernetes each vendor it.
    """
    text = ("> Output:\n"
            "> ```\n"
            "> hex(JSON): 7b22466f6f223a7b22517578223a7b7d7d7d\n"
            "> ```\n"
            "\n"
            "Prose after, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "7b22466f6f223a7b22517578223a7b7d7d7d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_fence_with_an_info_string_does_not_close_one() -> None:
    """A closing fence carries no info string, so ```` ```python ```` inside a
    fenced block is content rather than the end of it."""
    text = ("```\n"
            "$ cat example.md\n"
            "```python\n"
            "merged at a1b2c3d\n"
            "```\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked


def test_an_ordinary_fence_still_closes(git_repo: GitRepo) -> None:
    """The other half: the common case must be untouched, and a claim after a
    plain fence is still read."""
    text = ("Before, merged at a1b2c3d.\n"
            "```\n"
            "inside b2c3d4e\n"
            "```\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "b2c3d4e" not in blanked
    assert "a1b2c3d" in blanked and "d4e5f6a" in blanked


def test_a_tilde_fence_is_not_closed_by_backticks() -> None:
    """The character has to match too: a backtick run inside a tilde block is
    content, and the tilde block runs to its own closer."""
    text = ("~~~\n"
            "```\n"
            "merged at a1b2c3d\n"
            "```\n"
            "~~~\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_fence_inside_a_block_quote_ends_when_the_quote_does() -> None:
    """A container's end closes every block inside it, a fence included.

    Recognising `> ```' as a fence was half the repair; the other half is
    that the quote can end before any closer arrives - a pasted message cut
    off mid-block - and CommonMark closes the fence with it. Without that
    the fence stayed open and blanked the prose after the quote. Found by the
    identity gate on 2026-09-26 rather than by a test: aider's chat-history
    fixture lost 129 findings the reference parser calls prose, all after one
    quoted fence that its message never closed.
    """
    text = ("> ```\n"
            "> code the message never closed\n"
            "\n"
            "Prose after the quote, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "d4e5f6a" in blanked, "the quote ended and the fence did not"
    assert "never closed" not in blanked, "the quoted fence's content was read"


def test_a_line_that_leaves_the_quote_ends_its_fence_too() -> None:
    """The same without a blank line between: the first line without the
    quote marker is outside the quote, whatever it says."""
    text = ("> ```\n"
            "> quoted code\n"
            "Unquoted prose, merged at d4e5f6a.\n")
    assert "d4e5f6a" in _prose(text)


def test_a_fence_indented_four_past_its_opener_is_content() -> None:
    """CommonMark's closer may be indented at most three columns, measured
    from where the block's content starts - so a fence line four or more
    columns deeper than its opener is the block's CONTENT, an example of a
    fence shown inside a fence. Closing on it put the stripper out of phase,
    and the real closer then opened a fence that ran to the end of the
    document: mini-swe-agent's admonition example and superpowers' reviewer
    template both, found by the old-against-new measurement on 2026-09-26.
    """
    text = ("```markdown\n"
            "Show this to the reader:\n"
            "\n"
            "    ```\n"
            "    an example fence, merged at a1b2c3d\n"
            "    ```\n"
            "```\n"
            "\n"
            "Prose after, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "the example inside the fence was read"
    assert "d4e5f6a" in blanked, "the prose after the fence was blanked"


def test_a_backtick_run_with_a_backtick_after_it_is_inline_code() -> None:
    """A backtick fence's info string may not contain a backtick, so a line
    that opens with three backticks and closes them later is an inline code
    span, not a fence. kubernetes' changelogs write commands that way, and
    reading one as a fence blanked every entry below it.
    """
    # The backticks START the line, as they do in kubernetes' changelog -
    # which is what makes the line look like a fence at all.
    text = ("* Federation secret, if upgrading:\n"
            "    ```$ kubectl get secret federation-apiserver-secret```\n"
            "* Fixed in the release merged at d4e5f6a.\n")
    assert "d4e5f6a" in _prose(text)


@pytest.mark.parametrize("text", [
    ("* Federation secret, if upgrading:\n"
     "    ```$ kubectl get secret federation-apiserver-secret```\n"
     "  Then fixed in the release merged at d4e5f6a.\n"),
    ("```$ kubectl get secret federation-apiserver-secret```\n"
     "Then fixed in the release merged at d4e5f6a.\n"),
])
def test_an_inline_span_opens_no_fence_where_no_container_would_end_one(text: str) -> None:
    """The test above stopped being able to see the rule it pins. Since a
    fence ends with the list item it opened in, the next entry's marker ends
    whatever the span would have opened, so a scanner that read the span as a
    fence passes it anyway - the mutation campaign of 2026-09-28 found that,
    `_opens` answering True everywhere and surviving. These are the lines no
    container's end reaches: a continuation inside the same item, and the
    same span at the margin with no item at all."""
    assert "d4e5f6a" in _prose(text)


# --------------------------------------------------------------------------
# A fence ends when its container does
#
# CommonMark closes every block inside a container when the container ends,
# and a fence is a block. The block-quote half of that shipped in Phase 53;
# the list item, the HTML comment and the four verbatim HTML tags are
# Phase 55's, when fence detection moved into `extant/blocks.py` beside the
# container model the indented scanner already kept. Measured on 2026-09-27
# against markdown-it-py's `commonmark` preset over the 152 visible corpus
# clones: 3,372 lines on GitHub-rendered documents, one clone per repository,
# were blanked because a list item's end did not close the fence opened in it
# - kubernetes' changelogs 3,087 of them, then aider, moby, PX4 and bazel -
# and the MDX oracle (@mdx-js/mdx 3) agrees with CommonMark on every
# list-item shape below.
# --------------------------------------------------------------------------

def _prose_at(text: str, path: str) -> str:
    from extant import session as hc
    from extant.text import prose
    hc.set_document(doc_format="markdown", doc_path=path)
    return prose(hc._DOC, text)


def test_a_list_items_end_closes_a_fence_opened_in_it() -> None:
    """kubernetes' CHANGELOG-1.18.md at line 1310: an entry pastes terminal
    output in a fence it never closes, and the next entry's marker - back at
    the margin - ends the item and the fence with it. The toggle ran the
    fence on until the next backtick run and blanked every entry between,
    each of them a pull-request link."""
    text = ("- Fix kubectl printer ([#94](https://x/pull/94))\n"
            "  ```sh\n"
            "  $ kubectl get event, merged at a1b2c3d\n"
            "  LAST SEEN   TYPE\n"
            "- Azure: fix a bug, merged at d4e5f6a.\n"
            "- Fix a concurrent map write, merged at e5f6a7b.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "the fence's content was read"
    assert "d4e5f6a" in blanked and "e5f6a7b" in blanked, (
        "the entries after the item were blanked")


def test_a_nested_items_end_closes_its_fence_and_not_the_outer_item() -> None:
    """The container that ends is the INNER item: a sibling marker at the
    outer item's content column closes the nested item and its fence, and
    the outer item goes on."""
    text = ("- a\n"
            "  - b\n"
            "    ```\n"
            "    merged at a1b2c3d\n"
            "  - c, merged at d4e5f6a\n"
            "Outside, merged at e5f6a7b.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked and "e5f6a7b" in blanked


def test_blank_lines_inside_an_items_fence_do_not_end_it() -> None:
    """The other half: a blank line never ends a list item, so a fence in one
    runs across it to its own closer."""
    text = ("- a\n"
            "  ```\n"
            "  first\n"
            "\n"
            "  merged at a1b2c3d\n"
            "  ```\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_fence_on_a_list_markers_line_opens_one() -> None:
    """kubernetes' CHANGELOG-1.31.md writes ``- ```` with the fence straight
    after the marker. `_FENCE` never matched a line beginning `- `, so the
    content was read, the indented closer then OPENED a fence, and the prose
    after the item was blanked instead - out of phase both ways."""
    text = ("- ```sh\n"
            "  merged at a1b2c3d\n"
            "  ```\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "the fence's content was read"
    assert "d4e5f6a" in blanked, "the prose after the item was blanked"


@pytest.mark.parametrize("opener", ["1. ```bash", "- a\n    * ```bash"])
def test_an_ordered_or_nested_marker_opens_one_too(opener: str) -> None:
    """The ordered marker, and dspy's release checklist, whose nested `*`
    carries the fence."""
    indent = " " * (3 if opener.startswith("1.") else 6)
    text = (opener + "\n"
            + indent + "merged at a1b2c3d\n"
            + indent + "```\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_closer_dedented_out_of_its_item_opens_a_fence_of_its_own() -> None:
    """The rule has a second consequence, and it is the renderer's rather
    than a choice: a closer indented less than the item's content is not in
    the item, so the item - and the fence - end on that line, and the closer
    then OPENS a fence at the margin, which runs to the next closing fence or,
    as here, to the end of the document when none follows.
    GitHub renders it that way and so does MDX 3; PX4's ko, uk and zh
    translations of one page are this shape. Pinned so a later "fix" has
    to argue with both renderers first."""
    text = ("- a\n"
            "  ```\n"
            "  merged at a1b2c3d\n"
            "```\n"
            "Rendered as code, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" not in blanked, "the renderer shows this line as code"


@pytest.mark.parametrize("content", ["   > Parsing: GTS Root R1",
                                     "   >&2 echo launching"])
def test_a_prompt_inside_an_items_fence_does_not_end_the_item(content: str) -> None:
    """Inside a fence a `>` is content - a `diff` line, a shell prompt, a
    redirect - not a block-quote marker, so it cannot make a line look
    dedented out of the item. The first version of the container rule
    stripped it and closed the fence there: node's root-certificate notes,
    cpython's mimalloc readme and openfoodfacts' VS Code page, found by the
    delta against the shipped stripper on 2026-09-27."""
    text = ("1. Run it:\n"
            "   ```text\n"
            + content + ", merged at a1b2c3d\n"
            "   ```\n"
            "\n"
            "   Then commit, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "the fence ended at a `>` inside it"
    assert "d4e5f6a" in blanked, "the real closer opened a fence"


def test_a_list_items_end_inside_a_block_quote_closes_its_fence() -> None:
    """The quote markers come off first, and the item inside the quote ends
    the same way - while the quote itself goes on."""
    text = ("> - a\n"
            ">   ```\n"
            ">   merged at a1b2c3d\n"
            "> Still quoted, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_comments_end_closes_a_fence_opened_in_it() -> None:
    """An HTML comment is a block CommonMark ends at `-->`, so a fence begun
    inside one ends there too. The lines inside stay blanked - commented-out
    code is invisible either way - but the toggle ran the fence past the
    terminator and silenced the document after it (bun, qmk, deno)."""
    text = ("<!--\n"
            "```\n"
            "hidden, merged at a1b2c3d\n"
            "-->\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "a fence inside a comment stopped being blanked"
    assert "d4e5f6a" in blanked, "the fence outlived the comment"


def test_a_fence_closed_inside_a_comment_is_still_blanked() -> None:
    """The recorded divergence: CommonMark calls it HTML, not a fence, and
    this keeps blanking it, because nothing inside is rendered."""
    text = ("<!--\n"
            "```\n"
            "hidden, merged at a1b2c3d\n"
            "```\n"
            "-->\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_pre_blocks_end_closes_a_fence_opened_in_it() -> None:
    """`<pre>`, `<script>`, `<style>` and `<textarea>` end at their own closing
    tag - the comment's mechanism with a different terminator, which
    `extant/blocks.py` already tracked for the indented scanner."""
    text = ("<pre>\n"
            "```\n"
            "raw, merged at a1b2c3d\n"
            "</pre>\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_fence_at_four_inside_an_admonition_body_is_a_fence() -> None:
    """A governed body indents its children, and mkdocs renders a fence
    there as a fence - not as the four-space code CommonMark would call it.
    Today's behaviour, pinned now that fences and indentation are one
    scanner and one could quietly win over the other."""
    text = ("!!! note\n"
            "    ```bash\n"
            "    merged at a1b2c3d\n"
            "    ```\n"
            "\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_an_mdx_fence_opens_at_eight_spaces() -> None:
    """MDX has no indented code, so a fence opens at any indentation - the
    MDX oracle parses this one as a fence at eight spaces."""
    text = ("Text\n"
            "\n"
            "        ```bash\n"
            "        merged at a1b2c3d\n"
            "        ```\n"
            "\n"
            "After, merged at d4e5f6a.\n")
    blanked = _prose_at(text, "docs/page.mdx")
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def test_a_list_items_end_closes_a_fence_in_mdx_too() -> None:
    """The list model never ran on an `.mdx` file - the indented scanner
    returned before it - and MDX shares CommonMark's list items, so the
    container rule has to reach them."""
    text = ("- Install\n"
            "  ```bash\n"
            "  merged at a1b2c3d\n"
            "- Configure, merged at d4e5f6a.\n")
    blanked = _prose_at(text, "docs/page.mdx")
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


# --------------------------------------------------------------------------
# What mutmut found that no test held, in the fence half of blocks.py
# (Phase 63). The method is in tests/test_indented_code.py's last section;
# the expected values are markdown-it-py's and micromark's, except where a
# test says it holds a recorded divergence.
# --------------------------------------------------------------------------

def _code(text: str) -> tuple[set[int], set[int]]:
    from extant.blocks import code_lines
    found = code_lines(text)
    return set(found.fenced), set(found.indented)


def test_a_comment_terminator_inside_a_fence_is_content() -> None:
    """An HTML example in a fence holds a whole comment. Its `-->` is fence
    content and ends nothing - only a comment the fence OPENED in ends at
    one - so the fence runs to its own closer. Taken as an end, the fence
    closed at the example and its own closer opened another, which ran to
    the end of the document."""
    text = ("```html\n"
            "<!-- a comment -->\n"
            "still code, merged at a1b2c3d\n"
            "```\n"
            "Prose, merged at d4e5f6a.\n")
    blanked = _prose(text)
    assert "a1b2c3d" not in blanked, "the fence ended at the example's -->"
    assert "d4e5f6a" in blanked, "the fence's closer opened another"


def test_a_comment_that_ended_a_fence_has_ended_too() -> None:
    """A fence opened inside a comment ends at the comment's `-->`, and the
    comment ends with it: the indented block below is code. Kept open, the
    comment swallowed it. Lines 2 to 4 are the recorded divergence - a
    fence inside a comment is still blanked - and line 6 is CommonMark's."""
    text = ("<!--\n"
            "```\n"
            "x\n"
            "-->\n"
            "\n"
            "    code\n")
    assert _code(text) == ({2, 3, 4}, {6})


@pytest.mark.parametrize("text, expected", [
    # Top level: Docusaurus writes a title into the info string.
    ('```js title="docs/x.md"\n'
     "code\n"
     "```\n", {1, 2, 3}),
    # On a list marker's line.
    ('- ```js title="docs/x.md"\n'
     "  code\n"
     "  ```\n", {1, 2, 3}),
    # Inside a `<pre>` and inside a comment: the recorded divergence, a
    # fence CommonMark calls HTML and this module still blanks, opener and
    # all.
    ("<pre>\n"
     "```js\n"
     "code\n"
     "```\n"
     "</pre>\n", {2, 3, 4}),
    ("<!--\n"
     "```js\n"
     "code\n"
     "```\n"
     "-->\n", {2, 3, 4}),
])
def test_a_fences_opening_line_is_one_of_its_lines(
        text: str, expected: set[int]) -> None:
    """The opener is the fence's, and so is its info string - a path in a
    Docusaurus `title="..."` is the example's, not a claim. Each of the four
    places a fence opens adds the opener's own line; left out, it was the
    one line of the block read as prose."""
    fenced, _ = _code(text)
    assert fenced == expected


@pytest.mark.parametrize("text, expected", [
    # Five spaces after the marker: the fence is the content of an indented
    # block, not a fence, so `text` below is the item's paragraph. Line 1 is
    # the recorded divergence (design/code-blocks.md): CommonMark makes it
    # indented code, and this module reads it as a paragraph.
    ("-     ```\n"
     "  text\n", {2: False}),
    # Four is still the marker's own line, and the fence opens there.
    ("-    ```\n"
     "     x\n"
     "     ```\n"
     "prose\n", {1: True, 2: True, 3: True, 4: False}),
    # A tilde fence opens on the marker's line as a backtick one does.
    ("- ~~~\n"
     "  x\n"
     "  ~~~\n"
     "prose\n", {1: True, 2: True, 3: True, 4: False}),
    # Unclosed, it ends where its item does.
    ("- ```\n"
     "  x\n"
     "prose\n", {1: True, 2: True, 3: False}),
])
def test_a_fence_on_a_markers_line_opens_where_commonmark_says(
        text: str, expected: dict[int, bool]) -> None:
    """``- ```` opens a fence on the marker's line when one to four spaces
    separate them, with either fence character, and the item's end closes
    it. Each boundary had a mutation no test noticed."""
    fenced, indented = _code(text)
    assert {line: line in fenced | indented for line in expected} == expected


def test_prose_after_a_closed_fence_in_a_block_quote_is_prose() -> None:
    """A fence in a block quote closes at a closer at the same quote depth,
    and the quote goes on: the next quoted line is prose and a later quoted
    indented block is code. Counted wrongly, the closer was never seen and
    the fence ran to the end of the quote."""
    text = ("> ```\n"
            "> code\n"
            "> ```\n"
            "> prose\n"
            ">\n"
            ">     code\n")
    assert _code(text) == ({1, 2, 3}, {6})


# The same, for text.py's half of the blanking (Phase 63). Expected values
# are docutils 0.23's for reStructuredText.

@pytest.mark.parametrize("raw, expected", [
    ("x\r\n", ("x", "\r\n")),
    ("x\n", ("x", "\n")),
    ("x\r", ("x", "\r")),
    ("x", ("x", "")),
])
def test_a_line_is_split_from_its_exact_terminator(
        raw: str, expected: tuple[str, str]) -> None:
    """Every spelling of a break is carried through, a bare CR included.
    UNREACHABLE through `strip_code` and `prose` today, and measured so:
    `_blank` rewrites every lone CR to LF before this runs, and the mutation
    that drops the CR spelling changed none of ten bare-CR documents blanked
    either way, nor any of 4,732 corpus documents. This holds the
    function's own contract, so that removing the normalisation upstream
    cannot quietly turn a CR into a blanked space."""
    from extant.text import _line_and_terminator
    assert _line_and_terminator(raw) == expected


def test_strip_code_blanks_an_rst_inline_literal_and_prose_keeps_it() -> None:
    """``...`` is code in reStructuredText as backticks are in markdown, so
    `strip_code` blanks it; `prose` keeps inline code in either language,
    because claims are written there. Handed the wrong flag, the rst path
    blanked nothing inline, and 412 of the 4,732 corpus documents the
    mutmut cross-check read were blanked differently."""
    text = "Run ``git checkout a1b2c3d`` now, merged at d4e5f6a.\n"
    stripped = _stripped(text, "rst")
    assert "a1b2c3d" not in stripped
    assert "d4e5f6a" in stripped
    assert "a1b2c3d" in _prose(text, "rst")


def test_an_rst_literal_block_ends_where_the_indentation_returns() -> None:
    """The test in tests/test_rst.py holds the block's content; this holds
    its END. A line back at the introducing paragraph's indentation is prose
    again, and every way of mismeasuring that ran the block to the end of
    the document."""
    text = ("Example::\n"
            "\n"
            "    code, merged at a1b2c3d\n"
            "\n"
            "Back to prose, merged at d4e5f6a.\n")
    blanked = _prose(text, "rst")
    assert "a1b2c3d" not in blanked
    assert "d4e5f6a" in blanked


def _stripped(text: str, fmt: str) -> str:
    from extant.text import strip_code
    return strip_code(_doc_scope(fmt), text)
