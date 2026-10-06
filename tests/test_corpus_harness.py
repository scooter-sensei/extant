"""`tests/harnesses/corpus.py`'s per-rule denominators - the column it exists for.

The harness is run by hand against a directory of clones, so no CI job runs
it, and no test called it: 179e5b1 (2026-08-17), moving the modes out of the
shim, left `examined()` naming the session module by an alias only another
function had imported, and binding `text` to each document while
`text.format_for` still meant the module. Every run since raised NameError on
its first repository. `mypy --strict` over the harnesses found it (Phase 66).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent / "harnesses"))


def test_examined_counts_each_claim_once_in_the_format_it_is_written(
        git_repo: tuple[Path, Callable[[str, str, str], str]]) -> None:
    """One path pointer in prose in a markdown file, and the same sentence in
    a reStructuredText literal block - two spaces in after `::`, which
    markdown would read as a paragraph. Counted per document in its own
    format, the literal block is code and only the markdown claim is
    examined; counted as markdown throughout, both would be, which is the
    numpy miscount the per-document format exists to prevent."""
    import corpus
    repo, commit = git_repo
    commit("README.md", "Read `docs/plan.md` first.\n", "docs: a pointer")
    commit("guide.rst", "Example::\n\n  Read `docs/plan.md` first.\n", "docs: an example")
    assert corpus.examined(repo)["dead-path-pointer"] == 1
