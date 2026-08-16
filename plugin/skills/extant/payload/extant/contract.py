"""What every rule must state about itself.

Separate from extant/registry.py, which COLLECTS the rules, and the separation
is forced rather than tidy. The registry imports every rule module to read its
`RULE`; a rule module has to import this class to build one. With both in one
file that is a cycle, and it is not the harmless kind: importing a rule module
before the registry leaves the registry mid-import, so `module.RULE` does not
exist yet and Python raises

    AttributeError: partially initialized module 'extant.rules.sha' has no
    attribute 'RULE' (most likely due to a circular import)

That is not hypothetical - it fired on the first run of the shim, which reaches
`extant.rules.sha` before it reaches `extant.registry`. Written as one module
the arrangement works only while every entry point happens to import in one
particular order, which is a property nobody can see at the call site.

This file imports nothing from this package, so nothing here can ever be half
of a cycle.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Rule"]


def _no_denominator(ctx: object, text: str) -> int:
    """The default `examined`, and it refuses rather than answering zero.

    A rule with no denominator would otherwise report 0 candidates, which is
    the one number this whole tool exists to stop being ambiguous: "0 examined"
    and "0 found" print identically, so a rule that never states how many
    candidates it looked at is indistinguishable from a rule with nothing to
    look at. Raising makes the omission arrive as a crash on the first
    `count_examined`, in the commit that added the rule, rather than as a
    reassuring zero for the rest of the project's life.
    """
    raise NotImplementedError(
        "this rule states no denominator, so count_examined cannot report how "
        "many candidates it looked at")


@dataclass(frozen=True)
class Rule:
    """One validation rule and the properties that decide where it applies.

    These were previously implicit - carried in a boolean parameter, in
    docstrings, and in the author's head. Declaring them makes the design's own
    constraints checkable: a test asserts every rule states its `falsifiable`
    question, so a rule that cannot be answered by git or the filesystem cannot
    be added quietly.
    """

    kind: str          # the finding kind it emits, for cross-checking
    check: object      # (ctx, text) -> list[Finding]
    scope: str         # "whole-file" | "newest-entry"
    in_archive: bool   # does it still hold once an entry is retired?
    falsifiable: str   # the exact git/filesystem question asked. REQUIRED.
    # (ctx, text) -> text with one deliberate falsehood, or None when the
    # document offers nothing to corrupt. REQUIRED, and why --selftest exists:
    # a rule that cannot state how to make itself fire cannot be shown to work.
    probe: object
    # (ctx, text) -> how many candidates this rule LOOKED AT here, findings
    # aside. It lives on the rule because the module that finds a rule's
    # candidates is the only one that can count the same population; the one
    # central table this replaces could, and did, drift from what the rules
    # actually read. See `_no_denominator` for why the default raises.
    examined: object = _no_denominator
    # For a REPOSITORY-scoped rule: the repo-relative file that DECLARES
    # the claim being checked. Such a finding is about the repository and
    # belongs to no document, so a sweep has nothing to attribute it to;
    # `--verify` prints it under whichever document happened to be in hand,
    # which is the primary one. Naming the declaring file is more useful
    # than either. Left None for document-scoped rules, which carry their
    # own path already.
    subject_file: str | None = None
