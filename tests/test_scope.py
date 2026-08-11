"""Scopes replace the save-and-restore discipline in validate().

Every test here corresponds to a comment in the code being replaced, each of
which records a real bug: a nested call that cleared the caller's caches and
never gave them back, a tag created between two calls resolving to nothing, an
origin added between two calls leaving dead-pinned-ref examining nothing.

The behavioural half of that lives in tests/test_cache_lifetime.py and
tests/test_caching.py, which pin the properties through the RULES. What is
pinned here is the SHAPE that makes those properties structural rather than
guarded: two scopes are two objects, and a fresh one carries nothing.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parent.parent / "plugin" / "skills" / "extant" / "payload"
sys.path.insert(0, str(PAYLOAD))

# The inventory, and where each of the 26 module-level caches went. Written out
# because the count is the denominator of the emptiness test below, and a bare
# number nobody can reconstruct is a denominator that stops meaning anything the
# first time somebody adds a cache.
#
#   22  became RunScope fields (the list in scope.py, in this order)
#    3  stayed module-level in extant_collect.py: _STRIPPED, _BARE_SHAS and
#       _POINTER_SITES. The first two are keyed on the IDENTITY of the text
#       passed in and read nothing else about the repository, so they are pure
#       memos that self-invalidate; giving them a scope would be a lifetime
#       they do not have. _POINTER_SITES is not pure - it reads the filesystem
#       through _line_count - but its consumer, count_examined, runs AFTER
#       validate() returns, so a value tied to the call's scope would be
#       discarded exactly when it is needed. See the comment beside it.
#    1  was deleted: _TAGS has been dead since 6c5c29c rewired _tags() through
#       _ref_table, and only the save-and-restore choreography still named it.
CACHE_FIELDS = 22

# Not a cache. `stable` says whether a caller has taken ownership of this
# scope's lifetime for many documents, which is the old `_STABLE_SCOPE` boolean
# moved onto the object it describes. Excluded from the count above so the
# denominator keeps counting what it says it counts.
NOT_A_CACHE = {"stable"}


def test_a_nested_run_scope_does_not_disturb_the_outer_one() -> None:
    """The bug the save-and-restore block exists to prevent, now structural.

    Written against `ref_table` rather than a tag cache because `_TAGS` was
    dead and is gone; `_REF_TABLE` is what actually answers "which tags exist"
    and so is what the tag-lifetime property now rides on.
    """
    from extant.scope import RunScope

    outer = RunScope()
    outer.ref_table["/repo"] = ({}, {"v1.0": "abc1234"})
    inner = RunScope()
    inner.ref_table["/repo"] = ({}, {"v2.0": "def5678"})
    assert outer.ref_table["/repo"] == ({}, {"v1.0": "abc1234"}), (
        "a second scope reached into the first, which is what module globals "
        "did and what objects are supposed to make impossible")


def test_every_cache_is_empty_in_a_fresh_scope() -> None:
    """A scope that carries anything over has the lifetime bug by another name.

    Reports the denominator: a RunScope that grew a field this test does not
    know about would otherwise pass while covering nothing.
    """
    from extant.scope import RunScope

    scope = RunScope()
    caches = [f for f in dataclasses.fields(scope) if f.name not in NOT_A_CACHE]
    assert len(caches) == CACHE_FIELDS, (
        f"{len(caches)} cache fields, expected {CACHE_FIELDS}. A cache was "
        f"added or removed without the inventory at the top of this file being "
        f"updated, and this test would otherwise pass while counting something "
        f"else: {[f.name for f in caches]}")
    nonempty = [f.name for f in caches if getattr(scope, f.name)]
    print(f"checked {len(caches)} cache fields on a fresh RunScope")
    assert not nonempty, f"these start non-empty: {nonempty}"


def test_directory_listings_start_switched_off_rather_than_empty() -> None:
    """`dircache` is the one field whose empty value is not `{}`.

    None means CACHING IS OFF, which is the state whenever a rule is called
    directly rather than through validate(): a caller that creates a file
    between two checks must see the new answer, and a cache with no owner would
    quietly hand back the old one. An empty dict would silently opt every
    direct caller into a cache nobody owns, and the symptom is a stale answer
    rather than a failure.
    """
    from extant.scope import RunScope

    assert RunScope().dircache is None, (
        "a fresh scope has directory caching ON, so a rule called outside "
        "validate() would answer from a listing nothing invalidates")


def test_a_stable_scope_is_off_by_default() -> None:
    """The narrowness is the safety argument, so the default is asserted.

    `--sweep` is the only caller that declares a repository static, and it
    opens no file for writing. Every other caller keeps the per-call promise,
    which only holds while this defaults to False.
    """
    from extant.scope import RunScope

    assert RunScope().stable is False


def test_doc_scope_carries_the_three_per_document_values() -> None:
    from extant.scope import DocScope

    scope = DocScope(link_base=Path("/repo/docs"), doc_format="rst",
                     doc_path="docs/a.rst")
    assert (scope.link_base, scope.doc_format, scope.doc_path) == (
        Path("/repo/docs"), "rst", "docs/a.rst")


def test_an_unset_doc_scope_says_markdown_and_nothing_else() -> None:
    """The defaults are the module globals' import-time values, exactly.

    `doc_format` matters most: `_rule_applies` skips the markdown-only rules
    whenever it is not "markdown", so a default of "md" - a plausible spelling
    that is not this one - would silently switch off `dead-md-link` and
    `dead-md-anchor` for every caller that never sets a format.
    """
    from extant.scope import DocScope

    blank = DocScope()
    assert (blank.link_base, blank.doc_format, blank.doc_path) == (
        None, "markdown", None)


def test_a_doc_scope_cannot_be_edited_in_place() -> None:
    """Frozen, so a caller REPLACES the document rather than mutating one.

    The three values move together. The old code set them one at a time around
    a loop and restored them after it, which left the last swept document's
    directory installed whenever a rule raised part-way through.
    """
    from extant.scope import DocScope

    try:
        DocScope().doc_format = "rst"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("DocScope is no longer frozen")


def test_context_carries_one_run_and_one_document() -> None:
    """What every rule receives from Task 9 onward.

    Built by validate() today and read only to install the two scopes, because
    the shim's rules are still functions taking (repo, text) and cannot be
    handed anything. Asserting the shape now is what keeps Task 9 from having
    to invent it.
    """
    from extant.scope import Context, DocScope, RunScope

    run, doc = RunScope(), DocScope(doc_path="a.md")
    ctx = Context(config=None, run=run, doc=doc, repo=Path("/repo"))
    assert ctx.run is run and ctx.doc is doc
    assert ctx.repo == Path("/repo")
    assert ctx.git is None, (
        "Context.git holds the Git interface Task 7 introduces; until then the "
        "shim's rules call the module-level _git and _git_soft, and a field "
        "pretending otherwise would be a false surface")
