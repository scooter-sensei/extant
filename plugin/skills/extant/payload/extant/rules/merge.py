"""false-merge-claim: did the work this document says landed actually land?

The claim scanner is extant/commits.py, shared with `dead-sha`: both rules ask
git about overlapping sets of commits and one batch has to serve both, so
neither can own the scanner without reaching into the other.
"""
from __future__ import annotations

import subprocess

from extant.commits import document_shas, merge_claims
from extant.contract import Rule
from extant.finding import Finding
from extant.probes import sub_group
from extant.refs import (
    integrated_by, integration_refs, reachable_from, resolve_ref,
)
from extant.scope import Context
from extant.text import prose

__all__ = ["RULE", "check", "examined", "probe"]


def check(ctx: Context, text: str) -> list[Finding]:
    """Claims that work merged to main, re-checked against git ancestry.

    The inverse of the live-claim rule, and the more dangerous direction: a
    stale "still outstanding" claim makes a reader do redundant work, whereas a
    false "merged at X" tells the next session that work LANDED when it did
    not - so they build on a foundation that isn't there.

    Unlike live claims, this is checked WHOLE-FILE and in the archive too. A
    live status is only meaningful for the current phase, but "merged at X" is
    a permanent claim about the past: it should be true forever, in any entry,
    at any age. That asymmetry is deliberate.

    A claim whose SHA does not resolve is skipped, not double-reported -
    `dead-sha` already flags it as a dead reference, and "this commit is not an
    ancestor of main" would be a confusing second finding about a commit that
    does not exist.

    THE CLAIM NAMES ITS OWN REF, and that is what gets checked. "Merged to `X`
    at `Y`" is self-describing, so asking git whether Y is on X needs no
    configuration and is strictly more precise than comparing against one
    globally configured trunk. Measured on a gitflow fixture, the old form was
    blind to half of a real project's claims in either setting: with
    trunk=main a false "merged to develop" claim went unexamined, and with
    trunk=develop a false "merged to main" claim did. Both are caught now, and
    the denominator counts every claim rather than the fraction that happened
    to name the configured branch.

    A two-group pattern means (ref, sha). A one-group pattern is the older
    contract and still means (sha), checked against trunk exactly as before, so
    a project that customised `merge_claim` keeps working.
    """
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
    claims = merge_claims(ctx.config, text)
    if not claims:
        return []

    # TWO git subprocesses PER CLAIM was 98% of total validation time, measured
    # on a 4000-line document: 17.7 of 18.0 seconds, and most of the 1.8s the
    # post-commit hook added to every commit. `dead-sha` had already solved half
    # of this by batching existence checks, and the optimisation was simply
    # never carried across.
    #
    # Existence now goes through the same batched `git cat-file --batch-check`,
    # and ancestry is asked once per DISTINCT commit rather than once per
    # mention - documents repeat the same SHA constantly. Deliberately scoped to
    # this call rather than memoised across the process: git state can change
    # between validations, and a cache that outlives the run would answer from
    # a repository that no longer exists in that shape.
    #
    # The DOCUMENT's tokens, not this rule's, and only for the git question -
    # the claims above are still this rule's own and decide every finding
    # below. A wider batch cannot move any token's answer, and asking for the
    # document's union is what makes the whole document cost one batch instead
    # of one per rule. See `_document_sha_tokens` in extant/commits.py.
    resolved = document_shas(ctx, text)
    merged: dict[tuple[str, str], bool] = {}
    findings: list[Finding] = []
    for number, raw_ref, sha in claims:
        ref, quoted = _claimed_ref(raw_ref)
        if sha not in resolved:
            continue
        if resolve_ref(ctx, ref) is None:
            # The named branch is not here NOW, which is not the same as never
            # having been: gitflow deletes every release and feature branch on
            # merge. Asking git for the branch by name cannot tell those apart,
            # and neither can the merge-message rescue `unknown-branch` uses -
            # a squash merge or a custom `-m` erases the name entirely. This
            # probe reported a legitimately deleted `release/1.2.0` as invented.
            #
            # So ask the SUBSTANTIVE question instead: did this work land
            # anywhere at all? A missing branch plus an integrated commit is a
            # stale or misspelt name on a claim that is true in substance, and
            # silence is right. A missing branch plus a commit on no
            # integration branch is a claim that work landed when it did not,
            # which is the whole point of the rule.
            #
            # This also keeps the rule from being defeated by a typo. Evading
            # it requires the commit to be genuinely integrated, at which point
            # there is no false claim left to hide.
            if not quoted:
                continue        # a bare word, likelier prose than a ref
            if not integration_refs(ctx):
                continue        # no integration branch here to have taken it
            if not integrated_by(ctx, sha):
                findings.append(Finding(
                    number, "false-merge-claim",
                    f"claims work merged to `{ref}` at `{sha}`, but this "
                    f"repository has no such branch and that commit is on no "
                    f"integration branch either",
                    subject=sha,
                ))
            continue
        key = (ref, sha)
        if key not in merged:
            merged[key] = reachable_from(ctx, sha, ref)
        if not merged[key]:
            findings.append(Finding(
                number, "false-merge-claim",
                f"claims work merged to {ref} at `{sha}`, but that commit "
                f"is not an ancestor of {ref}",
                subject=sha,
            ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Every claim the pattern finds, counted by the scanner the rule reads.

    Counted from PROSE, like the check: a merge claim inside a fence is an
    example of the syntax, and counting it would report coverage of a claim no
    rule ever looks at.
    """
    return len(merge_claims(ctx.config, prose(ctx.doc, text)))


def _claimed_ref(raw: str) -> tuple[str, bool]:
    """The ref a merge claim names, and whether the author backticked it.

    Backticks are the whole signal. `` merged to `develp` at `abc` `` is a
    claim about a specific branch and a typo in it must be reported; "merged to
    the branch at `abc`" is prose, and treating `the` as a missing branch would
    be the noise that gets a validator ignored. Requiring backticks outright
    would instead lose every project that writes the branch name bare, so the
    pattern accepts both and the rule distinguishes them here.
    """
    if len(raw) >= 2 and raw.startswith("`") and raw.endswith("`"):
        return raw[1:-1], True
    return raw, False


def probe(ctx: Context, text: str) -> str | None:
    """Repoint a real merge claim at a commit that is on NO integration branch.

    A nonexistent SHA will not do. The rule deliberately skips claims whose
    commit does not resolve, leaving those to `dead-sha`, so probing with zeros
    proves nothing and reports a working rule as broken. Found by running the
    selftest and watching this rule stay silent, which is the entire point of
    having one.

    The SHA moved to group 2 when claims became self-describing, and this probe
    kept corrupting group 1 - which is now the branch NAME. It replaced
    `develop` with a commit hash, the pattern stopped matching, and the rule
    went quiet. The selftest reported `false-merge-claim DID NOT FIRE` against
    a rule that was working perfectly, which is the failure a selftest is
    supposed to make impossible rather than cause. The group index is derived
    from the pattern now, so a one-group custom pattern still probes correctly.

    Excluding every integration ref rather than only trunk, because a commit
    merged to `develop` is a true claim there and would prove nothing.
    """
    excluded = integration_refs(ctx)
    try:
        out = ctx.git.run(ctx.repo, "rev-list", "--all", "--not", *excluded,
                          "-n", "1")
    except (subprocess.CalledProcessError, OSError):
        return None
    other = out.strip().splitlines()
    if not other:
        return None  # nothing off-trunk exists here to probe with
    pattern = ctx.config.merge_claim
    return sub_group(text, pattern, pattern.groups, other[0])


RULE = Rule(
    kind="false-merge-claim",
    sequence=4,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="is the claimed commit an ancestor of the ref the claim names?",
    probe=probe,
    examined=examined,
)
