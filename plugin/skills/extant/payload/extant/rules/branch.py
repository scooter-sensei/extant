"""unknown-branch: is the branch this document names one git has ever seen?"""
from __future__ import annotations

from extant.contract import Rule
from extant.entries import split_entries
from extant.finding import Finding
from extant.probes import branch_in_newest
from extant.refs import branch_exists, named_in_merge_history
from extant.scope import Context
from extant.sites import looks_like_a_path
from extant.text import prose

__all__ = ["RULE", "check", "examined", "probe"]


def check(ctx: Context, text: str) -> list[Finding]:
    """A branch named in the newest entry that git has never heard of.

    Newest entry only, for the same reason live claims are: older entries name
    branches that were correct when written. Deletion after merge is normal and
    is never reported, because the merge commit still names the branch.
    """
    findings: list[Finding] = []
    for line, branch in _branch_sites(ctx, text):
        if branch_exists(ctx, branch) or named_in_merge_history(ctx, branch):
            continue
        findings.append(Finding(
            line, "unknown-branch",
            f"names `{branch}`, which does not exist and appears in no "
            f"merge commit (a typo, or work that was never integrated)",
            subject=branch,
        ))
    return findings


def _branch_sites(ctx: Context, text: str) -> list[tuple[int, str]]:
    """Every branch the newest entry names, and its line.

    THE scanner. `check` judges what this returns and `examined` counts it. The
    two agreed here, having been written together and kept in step by hand -
    which is the arrangement that drifts, and did in three other rules. Reading
    one function is what stops the next edit moving only one of them.

    `stale-live-claim` walks the same entry and keeps its OWN copy of this,
    because a rule may not import another rule - see `test_rules_are_leaves`.
    The two populations are deliberately different anyway: that rule reads only
    an entry making a live claim, and this one reads every branch named.

    Only the NEWEST phase entry, for the same reason live claims are: older
    entries name branches that were correct when written. The walk still
    advances over every segment before it so the line numbers stay right.
    A path-shaped token is not returned and so is neither judged nor counted.
    """
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
    _, segments, _ = split_entries(text, ctx.config)
    sites: list[tuple[int, str]] = []
    cursor = 0
    for kind, entry in segments:
        start = text.index(entry, cursor)
        cursor = start + len(entry)
        if kind != "phase":
            continue
        for match in ctx.config.branch_token.finditer(entry):
            branch = match.group(1)
            if looks_like_a_path(ctx, branch):
                continue  # a file reference caught by a path-shaped pattern
            sites.append(
                (text.count("\n", 0, start + match.start()) + 1, branch))
        break        # the newest phase entry, and never another
    return sites


def examined(ctx: Context, text: str) -> int:
    """Every branch the newest entry names, from the one scanner.

    This used to walk the entry itself, in a second pass that agreed with
    `check` only because the two were written together. It no longer reports
    the same number as `stale-live-claim` on every document and should not:
    that rule reads only an entry that makes a live claim, and this one reads
    every branch named. Each rule's denominator is tied to the code that reads
    it, so if one rule's skip-list widens, its own count moves and the other's
    does not. See `_branch_sites`.
    """
    return len(_branch_sites(ctx, text))


def probe(ctx: Context, text: str) -> str | None:
    """Point the first branch token of the newest entry at a name git never saw.

    The body is extant/probes.py, because `stale-live-claim` probes the same
    way and used to reach into this rule to do it.
    """
    return branch_in_newest(ctx, text)


RULE = Rule(
    kind="unknown-branch",
    sequence=3,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="newest-entry",
    in_archive=False,
    falsifiable="does the branch exist, or appear in any merge commit?",
    probe=probe,
    examined=examined,
)
