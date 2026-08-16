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
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
    findings: list[Finding] = []
    _, segments, _ = split_entries(text, ctx.config)
    cursor = 0
    newest_checked = False
    for kind, entry in segments:
        start = text.index(entry, cursor)
        cursor = start + len(entry)
        if kind != "phase" or newest_checked:
            continue
        newest_checked = True
        for match in ctx.config.branch_token.finditer(entry):
            branch = match.group(1)
            if looks_like_a_path(ctx, branch):
                continue  # a file reference caught by a path-shaped pattern
            if branch_exists(ctx, branch) or named_in_merge_history(ctx, branch):
                continue
            line = text.count("\n", 0, start + match.start()) + 1
            findings.append(Finding(
                line, "unknown-branch",
                f"names `{branch}`, which does not exist and appears in no "
                f"merge commit (a typo, or work that was never integrated)",
                subject=branch,
            ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """The same population `stale-live-claim` reads, and deliberately so.

    Both rules walk the branch tokens of the newest entry and both skip the
    path-shaped ones, so both report the same denominator. Counting them
    separately here rather than sharing a number is what keeps each rule's
    denominator tied to the code that reads it: if one rule's skip-list ever
    widens, its own count moves and the other's does not.
    """
    _, segments, _ = split_entries(prose(ctx.doc, text), ctx.config)
    newest = next((s for kind, s in segments if kind == "phase"), "")
    if not newest:
        return 0
    return sum(1 for token in ctx.config.branch_token.findall(newest)
               if not looks_like_a_path(ctx, token))


def probe(ctx: Context, text: str) -> str | None:
    """Point the first branch token of the newest entry at a name git never saw.

    The body is extant/probes.py, because `stale-live-claim` probes the same
    way and used to reach into this rule to do it.
    """
    return branch_in_newest(ctx, text)


RULE = Rule(
    kind="unknown-branch",
    check=check,
    scope="newest-entry",
    in_archive=False,
    falsifiable="does the branch exist, or appear in any merge commit?",
    probe=probe,
    examined=examined,
)
