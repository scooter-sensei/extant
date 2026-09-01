"""dead-sha: does the commit this document names still exist?

The scanning half - which tokens in a document are SHA-shaped, and which of
them git has - is extant/commits.py, because `false-merge-claim` reads the same
tokens and one batch has to serve both. What is here is this rule's own: which
of those candidates is worth a finding, how many it looked at, and how to
make it fire.

The `--sha-map` rewriter went to extant/commits.py in Task 10. It repairs
exactly what this rule reports, which is why it must stay beside the scanners
both halves read - but it is a command-line feature that rewrites documents,
not a question this rule asks, and a rule module owning one made this the only
rule the CLI imported directly.
"""
from __future__ import annotations

import re

from extant.commits import (
    document_shas, find_bare_sha_candidates, find_sha_candidates, rewrite_hint,
)
from extant.contract import Rule
from extant.finding import Finding
from extant.probes import sub_group
from extant.scope import Context
from extant.text import prose

__all__ = ["RULE", "check", "examined", "probe"]

# A changesets release note. The id is minted by the tool, not by git.
#
#     - 8b82179: Fix auto imports and code actions not working
#
# It is hex-shaped, seven characters, and resolves to nothing because it never
# named a commit. 50 findings on the held-out corpus, all in one project's
# generated changelogs.
#
# The line shape ALONE is not enough - `- abc1234: fixed the parser` is how a
# person writes a real commit reference - so this is gated on the repository
# actually using the tool, which is a directory that either exists or does not.
_CHANGESET_ENTRY = re.compile(r"^\s*[-*]\s+[0-9a-f]{6,40}:\s")


def _uses_changesets(ctx: Context) -> bool:
    """Does this repository mint release notes with changesets?"""
    key = str(ctx.repo)
    if key not in ctx.run.changesets:
        ctx.run.changesets[key] = (ctx.repo / ".changeset").is_dir()
    return ctx.run.changesets[key]


def _sha_sites(ctx: Context, text: str) -> list[tuple[int, str, bool]]:
    """Every SHA reference this rule will resolve, and whether it is bare.

    THE scanner. `check` judges what this returns and `examined` counts it, so
    the two cannot describe different populations. `examined` already read
    PROSE for that reason - counting the raw document reported candidates the
    rule never looked at, and rust-lang/rfcs printed `dead-sha 23` where the
    rule read 11 - but it stopped one skip short of `check`.

    A CHANGESET ENTRY is that skip, and it is the whole of the difference.
    `.changeset/` release notes open each line with the changeset id, which is
    hex and shaped exactly like a short commit. The rule steps over such a line
    rather than reporting every release note as full of dead references, so it
    resolves none of those tokens - and counting them said it had.

    Backticked candidates come first, so the findings keep the order they were
    reported in before this was one function.
    """
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
    sites: list[tuple[int, str, bool]] = [
        (number, token, False) for number, token in find_sha_candidates(text)]
    bare = find_bare_sha_candidates(text)
    if bare:
        lines = text.splitlines()
        changesets = _uses_changesets(ctx)
        for number, token in bare:
            line = lines[number - 1] if 0 < number <= len(lines) else ""
            if changesets and _CHANGESET_ENTRY.match(line):
                continue
            sites.append((number, token, True))
    return sites


def check(ctx: Context, text: str) -> list[Finding]:
    """Every referenced SHA must still resolve; a dead reference is useless."""
    findings: list[Finding] = []
    # The document's tokens rather than only this rule's sites, so the whole
    # document costs one batch. Only the sites decide anything below; see
    # `_document_sha_tokens` in extant/commits.py for why a wider batch cannot
    # move a finding.
    alive = document_shas(ctx, prose(ctx.doc, text))
    # A dead SHA is usually not a mistake anybody made. Measured 2026-08-30 on
    # a real agent-written project: 12 of its 12 dead references were killed by
    # ONE `git filter-repo` run, and every one of them is named in the
    # commit-map that run left in `.git`. So where the repository can say what
    # a reference became, the finding says it - see `rewrite_hint`.
    #
    # It rides in `repair` rather than in `detail` because `detail` is the
    # baseline fingerprint; extant/finding.py has the whole argument.
    for number, token, bare in _sha_sites(ctx, text):
        # I-1(b): a bare token that RESOLVES is merely unstyled, not broken -
        # flagging it would be noise, so only a token that fails to resolve is
        # worth a finding, whichever shape it was written in.
        if token in alive:
            continue
        if not bare:
            findings.append(
                Finding(number, "dead-sha",
                        f"`{token}` does not resolve in this repo",
                        subject=token, repair=rewrite_hint(ctx, token))
            )
            continue
        # Both kinds get the hint, or the class is only half repairable.
        # `translate_shas` learned bare tokens for exactly that reason and
        # records it as EX-8: reporting a shape the repair cannot reach is how
        # a finding becomes permanent.
        findings.append(Finding(
            number, "bare-dead-sha",
            f"`{token}` is un-backticked and does not resolve; "
            "backtick real SHAs so they are checked",
            subject=token, repair=rewrite_hint(ctx, token),
        ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Both candidate kinds, from the one scanner `check` reads.

    Computed from PROSE, because that is what the rule reads - claims inside
    code are examples, not promises - and counting the raw document reported
    candidates the rule never looked at. Measured 2026-08-04: rust-lang/rfcs
    reported `dead-sha 23` where the rule read 11, so more than half that
    denominator was fenced example output. An overstated denominator is the
    worst of the three numbers available: it is the one that reassures.

    That argument was right and stopped one skip early: a changeset entry is
    also a candidate the rule never resolves. See `_sha_sites`, which both
    halves read now rather than each running the scan its own way.
    """
    return len(_sha_sites(ctx, text))


# A letter is required now that an all-digit run reads as a number rather than
# a commit, so forty zeroes would be corrupted into something no rule looks at
# and `--selftest` would report dead-sha silent when the rule was fine.
_DEAD_SHA = "dead" + "0" * 36


def probe(ctx: Context, text: str) -> str | None:
    return sub_group(text, re.compile(r"`([0-9a-f]{7,40})`"), 1, _DEAD_SHA)


RULE = Rule(
    kind="dead-sha",
    sequence=1,   # first in the pre-refactor examined: dict literal
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does `git cat-file -e <sha>^{commit}` succeed?",
    probe=probe,
    examined=examined,
)
