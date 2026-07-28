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
