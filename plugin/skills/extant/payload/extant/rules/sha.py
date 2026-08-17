"""dead-sha: does the commit this document names still exist?

The scanning half - which tokens in a document are SHA-shaped, and which of
them git has - is extant/commits.py, because `false-merge-claim` reads the same
tokens and one batch has to serve both. What is here is this rule's own: which
of those candidates is worth a finding, how many it looked at, how to make it
fire, and the `--sha-map` rewriter that repairs what it reports.
"""
from __future__ import annotations

import re

from extant.commits import (
    BACKTICKED, BARE_SHA_TOKEN, document_shas, find_bare_sha_candidates,
    find_sha_candidates, looks_like_bare_sha, looks_like_sha, spans_overlap,
)
from extant.contract import Rule
from extant.finding import Finding
from extant.probes import sub_group
from extant.scope import Context
from extant.text import prose

__all__ = ["RULE", "check", "examined", "load_sha_map", "probe",
           "translate_shas"]

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
    # anything below; see `_document_sha_tokens` for why a wider batch cannot
    # move a finding.
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


def load_sha_map(path: str) -> dict[str, str]:
    """Parse a git-filter-repo commit-map (old SHA, whitespace, new SHA)."""
    mapping: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    return mapping


def _translated_value(token: str, mapping: dict[str, str]) -> str | None:
    """New value for `token` via prefix match, or None if it must stay put.

    GA-6: an AMBIGUOUS prefix - two old SHAs sharing it - is left untranslated
    rather than resolved by dict order. Picking a winner silently would rewrite
    a reference to point at the wrong commit, and a wrong SHA is worse than a
    dead one: the dead one is visibly broken, the wrong one reads as correct.
    Shared by both the backticked and bare translation paths below, so both
    apply the same ambiguity rule.
    """
    hits = [new for old, new in mapping.items() if old.startswith(token)]
    return hits[0][: len(token)] if len(hits) == 1 else None


def translate_shas(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Rewrite dead SHAs - backticked AND bare (I-1c) - to their post-rewrite
    values, matched by prefix.

    Ambiguous prefixes are left alone; see `_translated_value`. Ambiguous or
    otherwise unresolved tokens stay dead and get reported by `check`.

    Tokenizes per line, exactly like find_sha_candidates and
    find_bare_sha_candidates. `BACKTICKED`'s `[^`]+` matches newlines, so
    subbing over the whole text at once pairs backticks ACROSS line
    boundaries - an odd number of backticks on an earlier line shifts every
    pairing after it out of phase with the per-line scan find_sha_candidates
    (and `check`) rely on, making some backticked SHAs invisible
    here even though they are reported as findings elsewhere. Scanning line
    by line keeps the two in agreement by construction.
    `splitlines(keepends=True)` + `"".join(...)` preserves line endings
    byte-for-byte, so a no-op translation is a no-op on disk.

    I-1(c): a bare token is repaired in place, at its original length, and
    stays bare - this rewrites the SHA, it does not add styling the author
    never wrote. This half is not optional: adding `bare-dead-sha` findings
    (I-1b) without also extending translation to reach them would recreate
    EX-8 - a class of reference the validator reports that --sha-map is
    structurally unable to fix. The backtick substitution runs first on each
    line; it preserves length and leaves the backtick characters themselves
    untouched, so the backtick spans re-scanned afterwards for the bare pass
    land at the same offsets either way.

    Not a rule function, and it is here rather than beside the CLI because it
    is the repair for exactly what `check` reports: the two read the same
    tokens through the same scanners, and separating them is how a class of
    finding ends up unfixable.
    """
    count = 0

    def replace_backticked(match: "re.Match[str]") -> str:
        nonlocal count
        token = match.group(1)
        if not looks_like_sha(token):
            return match.group(0)
        new = _translated_value(token, mapping)
        if new is None:
            return match.group(0)
        count += 1
        return f"`{new}`"

    def replace_bare(line: str) -> str:
        nonlocal count
        backticked_spans = [m.span() for m in BACKTICKED.finditer(line)]
        pieces: list[str] = []
        cursor = 0
        for match in BARE_SHA_TOKEN.finditer(line):
            if spans_overlap(match.span(), backticked_spans):
                continue
            token = match.group(0)
            if not looks_like_bare_sha(token):
                continue
            new = _translated_value(token, mapping)
            if new is None:
                continue
            pieces.append(line[cursor: match.start()])
            pieces.append(new)
            cursor = match.end()
            count += 1
        pieces.append(line[cursor:])
        return "".join(pieces)

    lines = []
    for line in text.splitlines(keepends=True):
        line = BACKTICKED.sub(replace_backticked, line)
        line = replace_bare(line)
        lines.append(line)
    return "".join(lines), count


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
