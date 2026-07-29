"""reStructuredText: read for claims, never for markdown syntax.

The Sphinx ecosystem is invisible to a markdown-only sweep, and it is not a
small corner: numpy carries 555 `.rst` against 14 `.md`, Sphinx 472 against 3,
pytest 298 against 6.

Adding the extension alone was not enough and the corpus said so. Sweeping
those repositories produced 84 findings and almost none were real, for two
reasons this file pins.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _kinds(repo, text, fmt="rst"):
    import extant_collect as hc
    hc._DOC_FORMAT = fmt
    try:
        return [f.kind for f in hc.validate(repo, text, has_entries=False)]
    finally:
        hc._DOC_FORMAT = "markdown"


def test_rst_is_swept(git_repo) -> None:
    """numpy is 555 rst against 14 md. A markdown-only glob sees 14."""
    import extant_collect as hc
    repo, commit = git_repo
    commit("doc/guide.rst", "Guide\n=====\n", "chore: rst")
    commit("README.md", "# R\n", "chore: md")

    assert sorted(hc.tracked_markdown(repo)) == ["README.md", "doc/guide.rst"]


def test_markdown_link_syntax_is_not_applied_to_rst(git_repo) -> None:
    """`[x](y)` is markdown's alone, and in Python it is a subscript then a
    call. numpy writes `np.dtype[mp.mpf](dps=100)` in a doctest, and every one
    of its 23 link findings was that shape - false by construction, not by
    accident, which is why the rule is skipped rather than tuned.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "Call ``np.dtype[mp.mpf](dps=100)`` to build it.\n"

    assert "dead-md-link" not in _kinds(repo, text)


def test_the_same_text_is_still_checked_as_markdown(git_repo) -> None:
    """The skip follows the FORMAT, not the syntax, or it would switch the
    link rule off for markdown documents that mention Python."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" in _kinds(repo, "See [the plan](docs/gone.md).\n",
                                    fmt="markdown")


def test_an_rst_literal_block_is_not_prose(git_repo) -> None:
    """A block opens with a line ending in `::` and runs until the indentation
    returns. Left in place, numpy's `float64('1e10000')` was read as a commit.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ("Example::\n\n    value = float64('deadbee1')\n    other = 'cafe1234'\n"
            "\nBack to prose.\n")

    assert not [k for k in _kinds(repo, text) if "sha" in k]


def test_an_rst_doctest_is_not_prose(git_repo) -> None:
    """`>>>` opens a doctest, which is code however it is indented."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ">>> commit = 'deadbee1'\n>>> print(commit)\n"

    assert not [k for k in _kinds(repo, text) if "sha" in k]


def test_a_claim_in_rst_prose_is_still_checked(git_repo) -> None:
    """The half that makes rst support worth having. Stripping code must not
    become stripping the document: a dead SHA in ordinary prose still fires,
    which is what these repositories are full of."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "The rewrite landed in ``deadbee1`` last spring.\n"

    assert [k for k in _kinds(repo, text) if "sha" in k], "rst prose is not exempt"


def test_the_filename_decides_the_format() -> None:
    """`_format_for` is the dispatch, and nothing above ever calls it.

    Every test in this file sets `_DOC_FORMAT` by hand, which is convenient and
    leaves the thing that chooses it completely unpinned. A mutation campaign
    made `_format_for` return "markdown" for every path and the whole suite
    stayed green: the rules were correct for a format nothing would ever
    select, which is a feature that works in tests and not in the product.
    """
    import extant_collect as hc

    assert hc._format_for("docs/guide.rst") == "rst"
    assert hc._format_for("docs/GUIDE.RST") == "rst", "the suffix is case-folded"
    for markdown in ("README.md", "docs/a.markdown", "docs/b.mdx", "Makefile"):
        assert hc._format_for(markdown) == "markdown", markdown


def test_the_markdown_link_rule_is_gated_by_format_not_only_by_literals(
        git_repo) -> None:
    """Two mechanisms suppress a markdown link in rst, and only one is the point.

    `_MARKDOWN_ONLY` skips the rule outright; rst literal-stripping blanks
    ``...`` spans before any rule sees them. The existing test above puts its
    payload INSIDE a literal, so it passes with the format gate deleted - the
    stripping alone carries it. Emptying `_MARKDOWN_ONLY` survived a mutation
    campaign for exactly that reason.

    So this one puts the link in bare prose, where stripping cannot reach it
    and only the gate can. In rst that text is not a link at all: it is a
    subscript followed by a call, which is what numpy's doctests are full of.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "Call np.dtype[mp.mpf](dps=100) to build it.\n"

    assert "dead-md-link" not in _kinds(repo, text, fmt="rst")
    # The control: the identical bytes ARE a link in markdown, so a rule that
    # simply stopped working would pass the assertion above for no reason.
    assert "dead-md-link" in _kinds(repo, text, fmt="markdown"), (
        "if this fails the rule is off entirely and the rst assertion above "
        "proves nothing"
    )
