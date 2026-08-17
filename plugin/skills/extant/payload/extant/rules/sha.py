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
    document_shas, find_bare_sha_candidates, find_sha_candidates,
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


def check(ctx: Context, text: str) -> list[Finding]:
    """Every referenced SHA must still resolve; a dead reference is useless."""
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
    findings: list[Finding] = []
    backticked = find_sha_candidates(text)
    bare = find_bare_sha_candidates(text)
    # The document's tokens rather than only this rule's two lists, so the
    # whole document costs one batch. Only `backticked` and `bare` decide
    # anything below; see `_document_sha_tokens` in extant/commits.py for why
    # a wider batch cannot move a finding.
    alive = document_shas(ctx, text)
    for number, token in backticked:
        if token not in alive:
            findings.append(
                Finding(number, "dead-sha",
                        f"`{token}` does not resolve in this repo",
                        subject=token)
            )
    # I-1(b): a bare token that RESOLVES is merely unstyled, not broken -
    # flagging it would be noise, so only a bare token that fails to resolve
    # is worth a finding.
    lines = text.splitlines()
    changesets = _uses_changesets(ctx)
    for number, token in bare:
        if token in alive:
            continue
        line = lines[number - 1] if 0 < number <= len(lines) else ""
        if changesets and _CHANGESET_ENTRY.match(line):
            continue
        findings.append(Finding(
            number, "bare-dead-sha",
            f"`{token}` is un-backticked and does not resolve; "
            "backtick real SHAs so they are checked",
            subject=token,
        ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Both candidate kinds, counted the way `check` finds them.

    Computed from PROSE, because that is what the rule reads - claims inside
    code are examples, not promises - and counting the raw document reported
    candidates the rule never looked at. Measured 2026-08-04: rust-lang/rfcs
    reported `dead-sha 23` where the rule read 11, so more than half that
    denominator was fenced example output. An overstated denominator is the
    worst of the three numbers available: it is the one that reassures.
    """
    text = prose(ctx.doc, text)
    return len(find_sha_candidates(text)) + len(find_bare_sha_candidates(text))


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
