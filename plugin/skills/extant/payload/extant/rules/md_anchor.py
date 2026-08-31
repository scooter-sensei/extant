"""dead-md-anchor: does the heading this fragment names exist?"""
from __future__ import annotations

from pathlib import Path

from extant.contract import Rule
from extant.finding import Finding, rel
from extant.scope import Context
from extant.sites import (
    has_global_anchors, has_partial_anchors, partial_anchors, project_anchors,
)
from extant.text import EXTERNAL, MD_LINK, anchors, strip_code

__all__ = ["RULE", "check", "examined", "probe"]


def _target_anchors(ctx: Context, path: Path) -> set[str] | None:
    """Anchors offered by another document, or None if it cannot be read."""
    key = str(path)
    if key not in ctx.run.target_anchors:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                ctx.run.target_anchors[key] = anchors(fh.read())
        except (OSError, UnicodeDecodeError):
            ctx.run.target_anchors[key] = None
    return ctx.run.target_anchors[key]


def _fragment_sites(
    ctx: Context, text: str
) -> list[tuple[int, str, str, Path | None, set[str] | None]]:
    """Every fragment link this rule can DECIDE, and what decides it.

    THE scanner. `check` reports the sites that fail and `examined` counts
    them all, so the two cannot describe different populations - which they
    did. `check` has judged cross-file fragments since the docstring below
    argued for them; the denominator went on counting bare `#fragment` links
    alone, from a second pass of its own. A document whose only anchor link
    pointed at another file therefore reported a finding against
    `examined=0`, and the run then named this rule among those that
    "examined nothing at all". A finding against a zero denominator is worse
    than no denominator: it prints as coverage that was never provided, about
    the one rule that had just spoken.

    Each entry is (line number, the raw link, its lowercased fragment, the
    markdown file that must offer it, the anchors that file offers). The last
    two are None TOGETHER, and mean the fragment names a heading in this
    document.

    A site the rule cannot decide is not returned at all, and so is neither
    judged nor counted: an external URL, an empty fragment, a target that is
    not markdown or does not resolve exactly as written - `dead-md-link` owns
    that one - and a file that could not be read.
    """
    repo = ctx.repo
    base = ctx.doc.link_base or repo
    sites: list[tuple[int, str, str, Path | None, set[str] | None]] = []
    for number, line in enumerate(strip_code(ctx.doc, text).splitlines(),
                                  start=1):
        if "#" not in line or "[" not in line:
            continue
        for raw in MD_LINK.findall(line):
            if "#" not in raw or EXTERNAL.match(raw):
                continue
            target, _, fragment = raw.partition("#")
            fragment = fragment.lower()
            if not fragment:
                continue
            if not target:
                sites.append((number, raw, fragment, None, None))
                continue
            if target.startswith("/"):
                resolved = repo / target.lstrip("/")
            else:
                resolved = base / target
            if resolved.suffix.lower() not in (".md", ".markdown"):
                continue
            if not resolved.is_file():
                continue          # dead-md-link's finding, not this rule's
            offered = _target_anchors(ctx, resolved)
            if offered is None:
                continue
            sites.append((number, raw, fragment, resolved, offered))
    return sites


def check(ctx: Context, text: str) -> list[Finding]:
    """`#fragment` links pointing at no such heading, in this file or another.

    This used to check same-document fragments only, on the reasoning that a
    fragment on another file needs that file's renderer slug rules and so is a
    guess rather than a fact. That reasoning was sound and applied just as
    much to the same-document case, which shipped anyway - the asymmetry was
    never justified, and two things have since removed most of the guess.
    Headings are now slugged under BOTH common conventions, and a cross-file
    fragment is only judged when its path resolves to a real markdown file
    exactly as written.

    That last condition keeps this conservative on purpose. An extensionless
    or routed target in a generated site never resolves, so it is never judged
    here; `dead-md-link` already declines to judge it for the same reason, and
    a missing file is that rule's finding rather than this one's.

    Measured across nine repositories: 26 cross-file anchors resolve to a real
    file, 3 of them name a heading that does not exist, and all 3 are the same
    rot - a heading renamed and its inbound links left behind. httpx links to
    `#customizing-authentication` where the heading reads "Custom
    authentication schemes".
    """
    repo = ctx.repo
    own = anchors(text)

    # The ambient set is built ON DEMAND, and the demand is rare.
    #
    # It is consulted for one shape only - a bare `#fragment` that the document
    # does not define itself - and most fragments resolve inside their own
    # page. Building it eagerly meant a repository declaring a project-wide
    # namespace read every tracked markdown file on EVERY run, including a
    # post-commit hook, to validate a document that might contain no anchor
    # links at all.
    #
    # The trigger is one file existing, and for Sphinx that file is `conf.py`,
    # so this was the ordinary case across a large slice of Python projects
    # rather than an exotic one. Measured before the change, on a document held
    # identical while only the config was added: +42 ms at 100 files, +128 ms
    # at 400, +421 ms at 1600. Flat in the document, linear in the repository.
    #
    # Deferring makes the cost proportional to the number of fragments that are
    # ABOUT to be reported, which is the only time the answer can change a
    # finding. Behaviour is unchanged: `x in own or x in ambient` is the same
    # test as `x in (own | ambient)`.
    ambient: set[str] | None = None

    def ambient_anchors() -> set[str]:
        nonlocal ambient
        if ambient is None:
            if has_global_anchors(ctx):
                ambient = project_anchors(ctx)
            elif has_partial_anchors(ctx):
                ambient = partial_anchors(ctx)
            else:
                ambient = set()
        return ambient

    findings: list[Finding] = []
    for number, raw, fragment, resolved, offered in _fragment_sites(ctx, text):
        if resolved is None:
            if fragment in own or fragment in ambient_anchors():
                continue
            findings.append(Finding(
                number, "dead-md-anchor",
                f"links to `{raw}`, but this document has no such heading",
                subject=raw,
            ))
            continue
        if fragment in offered:
            continue
        findings.append(Finding(
            number, "dead-md-anchor",
            f"links to `{raw}`, but `{rel(repo, resolved)}` has no such "
            "heading",
            subject=raw,
        ))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Every fragment link the rule can decide, from the one scanner.

    It used to count bare `#fragment` links from a pass of its own, which
    excluded every cross-file anchor `check` judges - so the two numbers
    described different populations and a real finding was reported against
    zero examined. See `_fragment_sites`.
    """
    return len(_fragment_sites(ctx, text))


def probe(ctx: Context, text: str) -> str | None:
    for match in MD_LINK.finditer(strip_code(ctx.doc, text)):
        if not match.group(1).startswith("#"):
            continue
        start, end = match.span(1)
        return text[:start] + "#extant-selftest-no-such-heading" + text[end:]
    return None


RULE = Rule(
    kind="dead-md-anchor",
    sequence=8,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does this document contain a heading with that anchor?",
    probe=probe,
    examined=examined,
)
