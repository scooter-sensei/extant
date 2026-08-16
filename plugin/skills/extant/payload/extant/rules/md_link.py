"""dead-md-link: does the file this document links to exist?"""
from __future__ import annotations

from pathlib import Path

from extant.contract import Rule
from extant.finding import Finding
from extant.probes import MISSING_PATH
from extant.refs import renamed_to
from extant.scope import Context
from extant.sites import in_site_tree, is_generated_site, resolve_reference
from extant.text import (
    EXTERNAL, MD_LINK, numbered_document, percent_decoded, strip_code,
    unique_basename,
)

__all__ = ["RULE", "check", "examined", "probe"]


def check(ctx: Context, text: str) -> list[Finding]:
    """Relative markdown links whose target file is gone.

    Distinct from `dead-path-pointer`, which needs a backticked path introduced
    by an operative marker. A markdown link needs no such hedging: linking to a
    file IS the operative use, so there is no false-positive class here of the
    kind that forced the path rule to be keyed on markers.

    External links are skipped deliberately. Checking them needs the network,
    which would break the deterministic-local guarantee and make a green run
    depend on someone else's uptime.
    """
    repo = ctx.repo
    base = ctx.doc.link_base or repo
    findings: list[Finding] = []
    for number, line in enumerate(strip_code(ctx.doc, text).splitlines(), start=1):
        for raw in MD_LINK.findall(line):
            if EXTERNAL.match(raw) or raw.startswith("#"):
                continue
            target = raw.split("#", 1)[0]
            if not target:
                continue
            # `@` opens a generator macro, not a path. Documenter.jl writes
            # `[text](@ref)` for a cross-reference and JuliaLang/julia carries
            # 1,779 of them - every single one reported as a dead file, and 96%
            # of that repository's findings.
            if target.startswith("@"):
                continue
            # A markdown link percent-encodes characters that are awkward in a
            # URL, and the file on disk carries the decoded name.
            # nlohmann/json documents `operator[]` and links to it as
            # `operator%5B%5D.md`, which is the same file spelled for a browser.
            target = percent_decoded(target)
            # A leading slash means the repository root, which is how GitHub
            # renders it. Resolved against the DOCUMENT it reported
            # `/.github/AI_POLICY.md` dead in psf/requests while the file sat
            # right there.
            if target.startswith("/"):
                rooted = target.lstrip("/")
                if rooted and resolve_reference(ctx, repo, rooted)[0]:
                    continue
                # A root-relative target with no extension is a site route, and
                # it is settleable without knowing the generator: append `.md`
                # from the repository root and see. microsoft/vscode-docs links
                # to `/api/ux-guidelines/views` throughout, and that file is
                # right there as `api/ux-guidelines/views.md`.
                #
                # Silenced only when the document demonstrably EXISTS, so the
                # 220 of its links that resolve to nothing are still reported.
                # Measured before widening: 635 findings match this shape and
                # every one is in that repository, so no other project's links
                # change meaning.
                bare = rooted.rstrip("/")
                if bare and not Path(bare).suffix and (
                        resolve_reference(ctx, repo, bare + ".md")[0]
                        or resolve_reference(ctx, repo, bare + "/index.md")[0]):
                    continue
                # Deliberately NOT skipped unconditionally here.
                #
                # A held-out corpus produced 6,360 findings of this shape and
                # not one was a real defect, which argued for a blanket skip.
                # Two existing tests refuse it in as many words -
                # "detection must stay a property of the repository", "so the
                # fix above cannot become a blanket skip" - and they are
                # right: in a repository that builds no site, a root-relative
                # link to a missing file is dead and worth saying so.
                #
                # The cause was never the shape, it was DETECTION failing to
                # reach three layouts: haystack declares Docusaurus in
                # `docs-website/`, llama_index declares MkDocs in
                # `docs/api_reference/`, and svelte numbers its documents for
                # a site built from another repository. `_SITE_DIRS`,
                # `_site_dirs` and `_numbered_docs_tree` were widened to see
                # all three, which removes the findings without removing the
                # rule.
            exists, actual_case = resolve_reference(ctx, base, target)
            if exists:
                continue
            # In a compiled docs tree the remaining shapes are site routes
            # rather than files: an extensionless target, a `.html` target, or
            # an absolute path from the site root. None can be settled by the
            # filesystem, so none is judged. See _SITE_CONFIGS for the
            # measurement.
            # A `.html` target is a rendered page, in every repository and
            # not only in a detected one. MEASURED across 20 repositories in
            # two corpora: 407 markdown links point at a `.html` target and
            # NOT ONE resolves to a checked-in file. Gating this on generator
            # detection is what made rails report 276 of its own guide links
            # dead - its guides compile to HTML with a bespoke builder that
            # ships none of the configs detected below.
            if target.endswith(".html"):
                continue
            # The other two shapes still need the gate. In a plain repository
            # an extensionless target can be a real file - LICENSE, Makefile -
            # so silencing those everywhere would stop the rule working.
            # The two shapes are gated DIFFERENTLY, because they fail
            # differently.
            #
            # A leading slash is never a path in this repository, wherever
            # the document sits: GitHub resolves it against github.com and a
            # generator resolves it against the site root. So once the
            # repository is known to build a site at all, this is a route.
            if target.startswith("/") and is_generated_site(ctx):
                continue
            # An extensionless target CAN be a real file - LICENSE, Makefile,
            # a directory - so this one asks whether THIS document is a page
            # rather than whether the repository builds a site somewhere. A
            # monorepo builds one from `docs/` and still keeps ordinary
            # READMEs in `packages/`, whose relative links are files.
            if not Path(target).suffix and in_site_tree(ctx):
                continue
            # A generator that flattens its guides into one namespace resolves
            # a sibling by bare name from any depth. Phoenix links to
            # `contexts.md` from `guides/authn_authz/`, and the file lives at
            # `guides/data_modelling/contexts.md`; ExDoc finds it, a relative
            # path does not. Accepted only when the basename is UNIQUE in the
            # repository, so this stays a filesystem fact rather than a guess
            # about which of several candidates was meant.
            if in_site_tree(ctx) and unique_basename(ctx, target):
                continue
            # A docs tree that ORDERS its pages by filename prefix strips that
            # prefix from the route. svelte keeps
            # `documentation/docs/07-misc/04-custom-elements.md` and links to
            # it as `custom-elements` from a sibling page; the file is right
            # there and the link works on svelte.dev.
            #
            # Not gated on generator detection, because the prefix IS the
            # evidence - a repository that numbers its documents this way has
            # something consuming the order. Kept to a UNIQUE match for the
            # same reason `unique_basename` is: two files answering to one
            # route say nothing about which was meant. 139 findings on the
            # held-out corpus, all of them working links.
            if numbered_document(ctx, target):
                continue
            if actual_case:
                detail = (f"links to `{target}`, but the file on disk is "
                          f"`{actual_case}`; the case differs, which fails on a "
                          f"case-sensitive filesystem")
            else:
                detail = f"links to `{target}`, which does not exist"
                moved = renamed_to(ctx, target)
                if moved:
                    detail += f"; git shows it renamed to `{moved}`"
            findings.append(Finding(number, "dead-md-link", detail,
                                    subject=target))
    return findings


def examined(ctx: Context, text: str) -> int:
    """Every link this rule would judge: not external, not a bare fragment.

    Counted from the CODE-STRIPPED document, like the check, because a link
    inside a fence is an example of the syntax - this project's own README
    documents the rule with a backticked example link, and the rule reported it
    as dead before inline spans were stripped.
    """
    return sum(1 for line in strip_code(ctx.doc, text).splitlines()
               for raw in MD_LINK.findall(line)
               if not EXTERNAL.match(raw) and not raw.startswith("#"))


def probe(ctx: Context, text: str) -> str | None:
    for match in MD_LINK.finditer(strip_code(ctx.doc, text)):
        raw = match.group(1)
        if EXTERNAL.match(raw) or raw.startswith("#"):
            continue
        start, end = match.span(1)
        return text[:start] + MISSING_PATH + text[end:]
    return None


RULE = Rule(
    kind="dead-md-link",
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does the linked file exist on disk?",
    probe=probe,
    examined=examined,
)
