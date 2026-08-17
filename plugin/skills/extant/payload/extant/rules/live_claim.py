"""stale-live-claim: is the branch this document calls unmerged still open?

Rename detection used to live here, because `dead-md-link` and
`dead-path-pointer` both needed it and this is where it was written first. It
is extant/refs.py now, which is why neither of those rules has to import this
one - see `test_rules_are_leaves`.
"""
from __future__ import annotations

from extant.contract import Rule
from extant.entries import split_entries
from extant.finding import Finding
from extant.probes import branch_in_newest
from extant.refs import branch_exists, integrated_by
from extant.scope import Context
from extant.sites import looks_like_a_path
from extant.text import prose

__all__ = ["RULE", "check", "examined", "probe"]


def check(ctx: Context, text: str) -> list[Finding]:
    """Present-tense status claims, re-checked against git.

    Only a small closed set of phrases is inspected. Nothing here looks at
    numbers or dates, which is what keeps historical facts structurally immune
    to false positives.

    Only the NEWEST phase entry is ever checked for a live-status claim.
    Phase entries are stored newest-first, so the newest is the first segment
    whose kind is "phase"; every phase entry after it is historical by
    definition and must never produce a finding, no matter what it says. The
    cursor/line walk still advances over EVERY segment (phase or not) so
    reported line numbers stay correct - only the checking itself is
    restricted to that first phase segment.
    """
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
    findings: list[Finding] = []
    _, segments, _ = split_entries(text, ctx.config)
    cursor = 0
    newest_checked = False
    for kind, entry in segments:
        start = text.index(entry, cursor)
        cursor = start + len(entry)  # advance for every segment, phase or not
        if kind != "phase" or newest_checked:
            continue
        newest_checked = True
        if not ctx.config.live_phrases.search(entry):
            continue
        for match in ctx.config.branch_token.finditer(entry):
            branch = match.group(1)
            # Same path/branch ambiguity as `unknown-branch`. Harder to reach
            # here, because a live phrase must appear in the entry first, but
            # the pattern is equally capable of matching a file and the
            # consequence would be a confident falsehood about a document.
            if looks_like_a_path(ctx, branch):
                continue
            exists = branch_exists(ctx, branch)
            # "Merged" means landed on an integration branch, and which one is
            # measured rather than configured. Against a single-trunk repo that
            # is the same question as before; on a gitflow repo with trunk=main
            # it is the difference between noticing that a feature reached
            # develop and silently accepting a stale claim about it.
            holders = integrated_by(ctx, branch, exclude=branch) if exists else []
            if exists and not holders:
                continue  # genuinely still open: the claim is true
            line = text.count("\n", 0, start + match.start()) + 1
            if exists:
                detail = (f"claims `{branch}` unmerged, but it is an ancestor of "
                          f"{', '.join(holders)}")
            else:
                detail = (
                    f"claims `{branch}` unmerged, but that branch no longer exists "
                    "(merged and cleaned up, or the claim is stale)"
                )
            findings.append(Finding(line, "stale-live-claim", detail,
                                    subject=branch))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Branch tokens in the NEWEST entry, path-shaped ones excluded.

    Counts what the rule actually inspects, not what the pattern matched.
    Path-shaped tokens are skipped by the check above, so counting them here
    would overstate the denominator - and a denominator that overstates is
    worse than none, because it reports coverage that does not exist.

    The live phrase itself is deliberately NOT a condition. A newest entry that
    names branches and makes no live claim has candidates this rule looked at
    and passed over, which is a different fact from a document with no branches
    in it at all; `unknown-branch` reads exactly the same population, which is
    why the two rules report the same number.
    """
    _, segments, _ = split_entries(prose(ctx.doc, text), ctx.config)
    newest = next((s for kind, s in segments if kind == "phase"), "")
    if not newest:
        return 0
    return sum(1 for token in ctx.config.branch_token.findall(newest)
               if not looks_like_a_path(ctx, token))


def probe(ctx: Context, text: str) -> str | None:
    """Only probeable if the document actually makes a live claim.

    A synthetic phrase would be written in THIS project's default vocabulary
    and would tell an adopter with different wording nothing except that the
    default matches the default.
    """
    _, segments, _ = split_entries(text, ctx.config)
    newest = next((s for kind, s in segments if kind == "phase"), "")
    if not newest or not ctx.config.live_phrases.search(newest):
        return None
    return branch_in_newest(ctx, text)


RULE = Rule(
    kind="stale-live-claim",
    sequence=2,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="newest-entry",
    in_archive=False,
    falsifiable="is the named branch on an integration branch, or gone entirely?",
    probe=probe,
    examined=examined,
)
