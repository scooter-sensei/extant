"""What `--selftest` uses to corrupt one real claim, shared between rules.

A probe belongs to its rule and lives in its rule's module. What is here is
only the machinery MORE THAN ONE probe needs, moved out for the reason
`test_rules_are_leaves` exists: `stale-live-claim`'s probe called
`unknown-branch`'s probe outright, which is a rule importing a rule, and four
rules corrupt a document through the same one-capture substitution.

Probes mutate an ACTUAL match rather than injecting invented prose, so what is
exercised is this project's configuration against this project's writing. A
synthetic probe written in the default vocabulary would only ever prove that
the defaults match the defaults - which is why the two values below are marker
strings that no repository could hold by accident, never sentences.
"""
from __future__ import annotations

import re

from extant.entries import split_entries
from extant.scope import Context

__all__ = ["FAKE_BRANCH_LEAF", "MISSING_PATH", "branch_in_newest", "sub_group"]

MISSING_PATH = "__extant_selftest_missing__.md"
FAKE_BRANCH_LEAF = "extant-selftest-no-such-branch"


def sub_group(text: str, pattern: "re.Pattern[str]", group: int,
              value: str) -> str | None:
    """Replace one capture of the first match, or None if nothing matched."""
    match = pattern.search(text)
    if not match:
        return None
    start, end = match.span(group)
    return text[:start] + value + text[end:]


def branch_in_newest(ctx: Context, text: str) -> str | None:
    """Point the first branch token of the newest entry at a name git never saw.

    Shared by `unknown-branch` and `stale-live-claim`: both read the same
    tokens in the same entry, so both are made to fire the same way. It lived
    in the branch rule and the live-claim probe called it there, which is the
    sideways reach this module exists to remove.
    """
    _, segments, _ = split_entries(text, ctx.config)
    for kind, entry in segments:
        if kind != "phase":
            continue
        match = ctx.config.branch_token.search(entry)
        if not match:
            return None
        leaf = match.group(1).split("/", 1)
        fake = (f"{leaf[0]}/{FAKE_BRANCH_LEAF}" if len(leaf) > 1
                else FAKE_BRANCH_LEAF)
        start, end = match.span(1)
        return text.replace(entry, entry[:start] + fake + entry[end:], 1)
    return None
