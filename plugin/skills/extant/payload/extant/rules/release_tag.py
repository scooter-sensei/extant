"""dead-release-tag: was the version this document claims actually released?"""
from __future__ import annotations

import re

from extant.contract import Rule
from extant.finding import Finding
from extant.probes import sub_group
from extant.refs import integrated_by, integration_refs, ref_table
from extant.scope import Context
from extant.text import prose

__all__ = ["RULE", "check", "examined", "probe"]


def check(ctx: Context, text: str) -> list[Finding]:
    """"Released in v2.1" where no such tag exists, or it shipped on nothing.

    Measured as absent from the corpus this was built against, so its
    denominator honestly reports 0 here. It is included for projects that keep
    a CHANGELOG, where this is the usual way a release is claimed, and it is
    falsifiable in exactly the way a merge claim is.

    "On an integration branch" rather than "an ancestor of trunk", because a
    release tag lives on the RELEASE line and that is not always the branch a
    project integrates into day to day. Measured on a gitflow fixture with
    trunk=develop, the old question reported a genuinely shipped `v1.2.0` as
    dead: the tag sits on main's release merge, and develop received the
    release branch rather than that commit. A tag reachable from no integration
    branch at all is still reported, which is the case this rule exists for -
    a tag created for a release that was abandoned or rewritten away.
    """
    # Claims inside code are examples, not promises. See prose.
    text = prose(ctx.doc, text)
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for tag in ctx.config.release_tag.findall(line):
            resolved = _released_tag(ctx, tag)
            if resolved is None:
                if ctx.config.release_claims_are_ours:
                    findings.append(Finding(
                        number, "dead-release-tag",
                        f"claims release `{tag}`, but no such tag exists",
                        subject=tag,
                    ))
                    continue
                # "NO SUCH TAG EXISTS" IS NOT A QUESTION GIT CAN SETTLE, and
                # this branch used to answer it anyway. A version in prose can
                # name a git tag, an npm or PyPI release, a sub-package, a
                # plugin, or a toolchain somebody else ships, and nothing in
                # the sentence says which.
                #
                # Measured on 15 repositories that write prose release claims,
                # it was wrong 19 times out of 26. eugenelim/agent-ready-repo
                # tags `credbroker-v0.4.0` and writes "shipped as 0.27.0", an
                # npm version; 10CG/Aria tags to v1.5.0 and cites v1.17.3
                # through v1.24.1, its plugin's numbering; rust-lang/rfcs has
                # no tags at all and discusses Rust's releases throughout.
                #
                # A range test was tried and does not separate them - two of
                # the false positives sit inside the repository's own tag
                # range - so there is no narrowing here, only a question the
                # rule should not be asking. `dead-pinned-ref` stays honest on
                # the same problem only because `repo:` names the owner on the
                # line above; prose carries no such marker.
                #
                # The cost is real and stated: a project that claims a release
                # it never tagged is no longer caught. What remains is the
                # half that IS settleable - the tag is here, and it shipped on
                # nothing - which was right 7 times out of 7.
                continue
            if not integration_refs(ctx):
                continue        # no integration branch here to have shipped it
            if not integrated_by(ctx, f"refs/tags/{resolved}"):
                findings.append(Finding(
                    number, "dead-release-tag",
                    f"tag `{resolved}` exists but is on no integration branch "
                    f"({', '.join(integration_refs(ctx))})",
                    subject=tag,
                ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Every release claim the pattern finds, counted over prose."""
    return len(ctx.config.release_tag.findall(prose(ctx.doc, text)))


def _tags(ctx: Context) -> set[str]:
    """Every tag in this repository, read once."""
    # From the shared ref table rather than its own `tag -l`. Same names, one
    # fewer subprocess; see `ref_table`.
    return set(ref_table(ctx)[1])


def _tag_prefixes(ctx: Context) -> list[str]:
    """What this repository puts BEFORE a version number in a tag.

    Read from `git tag -l` rather than configured, because which convention a
    project uses is a fact git already holds. Measured across 30 repositories:
    black tags `18.3a0`, poetry `0.1.0`, ruff and uv likewise - all bare -
    while symfony tags `v8.0.0`. A claim written in the other convention
    resolves to nothing, so the rule reported a release that had shipped.
    """
    key = str(ctx.repo)
    if key not in ctx.run.tag_prefixes:
        prefixes = set()
        for tag in _tags(ctx):
            digit = re.search(r"\d", tag)
            if digit is not None:
                prefixes.add(tag[:digit.start()])
        ctx.run.tag_prefixes[key] = sorted(prefixes)
    return ctx.run.tag_prefixes[key]


def _released_tag(ctx: Context, version: str) -> str | None:
    """The real tag a release claim names, or None if there is none.

    Two things stand between a claimed version and a tag, and both are the
    project's own habits rather than the author's error.

    The PREFIX: see `_tag_prefixes`. A claimed `v8.0` and a claimed `8.0` mean
    the same release, and which spelling is correct depends on the repository.

    The SERIES: a claim names one far more often than it names a tag. Symfony's
    own triage guide says work "shipped in 8.0" and no tag is called that - the
    tags are `v8.0.0`, `v8.0.1` and so on. A claimed version that is the stem
    of a real tag has therefore shipped, and saying otherwise is pedantry about
    a number rather than a fact about git.
    """
    tags = _tags(ctx)
    # LITERALLY FIRST, and this is not an optimisation. A project can configure
    # `release_tag` to capture its whole tag name - the installer derives such
    # a pattern from repositories tagging `release-1.2.3` or `api@2.0.0` - and
    # for those the captured text IS the tag. Trying prefixes first turns
    # `release-1.2.3` into `release-release-1.2.3`, resolves nothing, and
    # reports a shipped release as dead. Caught by the scenario harness rather
    # than by any unit test here, every one of which used a bare or
    # `v`-prefixed version.
    if version in tags:
        return version
    bare = version.removeprefix("v")
    for prefix in _tag_prefixes(ctx):
        exact = prefix + bare
        if exact in tags:
            return exact
        series = sorted(tag for tag in tags if tag.startswith(exact + "."))
        if series:
            return series[0]
    return None


def probe(ctx: Context, text: str) -> str | None:
    return sub_group(text, ctx.config.release_tag, 1, "v0.0.0-extant-selftest")


RULE = Rule(
    kind="dead-release-tag",
    sequence=5,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does the tag exist, and is it on an integration branch?",
    probe=probe,
    examined=examined,
)
