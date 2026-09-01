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


def _live_sites(ctx: Context, text: str) -> list[tuple[int, str]]:
    """Every branch this document makes a live claim about, and its line.

    THE scanner. `check` judges what this returns and `examined` counts it,
    so the two cannot describe different populations - which they did.
    `examined` ran a pass of its own that counted every branch token in the
    newest entry whether or not the entry made a live claim at all, and its
    docstring defended that as "candidates this rule looked at and passed
    over". The control flow says otherwise: with no live phrase present
    `check` gives up on the entry and never reaches the token loop, so it
    inspects none of them. A status document naming branches and claiming
    nothing about them therefore printed `stale-live-claim 1` beside no
    findings, which reads as a live claim examined and found sound.

    `unknown-branch` reads the same tokens with no such gate, so the two
    rules reporting different numbers on such a document is correct: they ask
    different questions of one entry. Reporting the same number was the bug.

    Only the NEWEST phase entry is ever read. Entries are stored newest-first,
    so that is the first segment whose kind is "phase"; every phase entry after
    it is historical by definition and must never produce a finding, no matter
    what it says. The walk still advances over EVERY segment before it, phase
    or not, so the reported line numbers stay correct.

    Claims inside code are examples, not promises - hence `prose`. A token that
    is path-shaped is not returned and so is neither judged nor counted: the
    pattern is equally capable of matching a file, and `dead-path-pointer`
    owns that one.
    """
    text = prose(ctx.doc, text)
    _, segments, _ = split_entries(text, ctx.config)
    sites: list[tuple[int, str]] = []
    cursor = 0
    for kind, entry in segments:
        start = text.index(entry, cursor)
        cursor = start + len(entry)  # advance for every segment, phase or not
        if kind != "phase":
            continue
        if ctx.config.live_phrases.search(entry):
            for match in ctx.config.branch_token.finditer(entry):
                branch = match.group(1)
                if looks_like_a_path(ctx, branch):
                    continue
                sites.append(
                    (text.count("\n", 0, start + match.start()) + 1, branch))
        break        # the newest phase entry, and never another
    return sites


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
    findings: list[Finding] = []
    for line, branch in _live_sites(ctx, text):
        exists = branch_exists(ctx, branch)
        # "Merged" means landed on an integration branch, and which one is
        # measured rather than configured. Against a single-trunk repo that
        # is the same question as before; on a gitflow repo with trunk=main
        # it is the difference between noticing that a feature reached
        # develop and silently accepting a stale claim about it.
        holders = integrated_by(ctx, branch, exclude=branch) if exists else []
        if exists and not holders:
            continue  # genuinely still open: the claim is true
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
    """The live claims this document makes, from the one scanner.

    The live phrase IS a condition, and used not to be. This counted every
    branch token in the newest entry and argued that an entry naming branches
    without claiming anything about them "has candidates this rule looked at
    and passed over" - but `check` gives up on such an entry before the token
    loop, so it looked at none of them. The number that produced was coverage
    reported where none was provided, which the anchor and manifest rules both
    call worse than no denominator at all. See `_live_sites`.

    This no longer matches `unknown-branch` on every document, and should not:
    that rule reads the same tokens without this gate, so on an entry making
    no live claim it examines them and this one does not.
    """
    return len(_live_sites(ctx, text))


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
