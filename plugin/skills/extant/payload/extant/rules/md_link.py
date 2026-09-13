"""dead-md-link: does the file this document links to exist?"""
from __future__ import annotations

from pathlib import Path

from extant.contract import Rule
from extant.finding import Finding
from extant.probes import MISSING_PATH
from extant.refs import renamed_to
from extant.scope import Context
from extant.sites import in_site_tree, is_generated_site, resolve_reference
from extant.links import EXTERNAL, MD_LINK, link_destination, link_sites
from extant.text import numbered_document, strip_code, unique_basename
# `probe` below keeps its own MD_LINK scan rather than reading `link_sites`,
# and the difference is real rather than an oversight: it has to SPLICE a
# corrupted target back into the document, so it needs the match POSITION that
# `finditer` gives and a list of sites cannot. It is not a second reader of the
# same claim - it decides nothing and reports nothing.

__all__ = ["RULE", "check", "examined", "probe"]


def _link_sites(ctx: Context, text: str) -> list[tuple[int, str]]:
    """Every link this rule will TRY to decide, and the target it decides on.

    THE scanner. `check` judges what this returns and `examined` counts it,
    so the two cannot describe different populations - which they did.
    `examined` ran a pass of its own that counted every non-external,
    non-anchor link, including shapes that `check` refuses in every
    repository. A document made only of them printed `dead-md-link 2` beside
    no findings, which reads as two links examined and clean when none was
    examined at all. That is the quiet direction of the defect and the worse
    one: nobody investigates a run with no findings.

    The scan itself now lives in `links.link_sites`, because it had acquired a
    SECOND reader - `gate.suggest_renames` - and two readers of one claim that
    scan differently is the recurring defect here. This is the adapter that
    keeps the rule's own shape: `check` and `examined` want (line, target) and
    have no use for the raw spelling, which exists for the patch generator
    that has to find the link again in the document.

    ONE refusal is applied here rather than in the scanner, because it needs
    the repository: a raw HTML `href` or `src` inside a tree a generator
    builds is resolved by the BROWSER against the rendered page's URL, which
    the filesystem cannot settle. `<img src="../../img/x.png">` in
    `docs/user-guide/theme.md` reaches `docs/img/x.png` on the MkDocs site
    and nothing relative to the file; the same target in a markdown image is
    rewritten by the generator and still names the file. Refused HERE, not in
    `check`, so a site the rule will not judge is not counted either.
    """
    in_site = None
    sites: list[tuple[int, str]] = []
    for number, _raw, target, html in link_sites(ctx.doc, text):
        if html:
            if in_site is None:
                in_site = in_site_tree(ctx)
            if in_site:
                continue
        sites.append((number, target))
    return sites


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
    for number, target in _link_sites(ctx, text):
        # A leading slash means the repository root, which is how GitHub
        # renders it. Resolved against the DOCUMENT it reported
        # `/.github/AI_POLICY.md` dead in psf/requests while the file sat
        # right there.
        rooted_case = None
        if target.startswith("/"):
            rooted = target.lstrip("/")
            # BOTH halves of the answer, not just the boolean. Taking `[0]`
            # threw away the on-disk spelling, and the fall-through below then
            # asked `resolve_reference` about a target still carrying its
            # leading slash - which is the absolute branch, so it answered
            # `Path("/docs/guide.md").exists()` about the filesystem root and
            # returned no suggestion. A root-relative link whose only fault was
            # its case was therefore reported as "does not exist" about a file
            # that does, sending the reader to look for a missing document
            # instead of fixing two letters.
            if rooted:
                rooted_exists, rooted_case = resolve_reference(ctx, repo, rooted)
                if rooted_exists:
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
            # `_site_dirs` and `_numbered_docs_tree` (all in
            # extant/sites.py) were widened to see all three, which
            # removes the findings without removing the rule.
        exists, actual_case = resolve_reference(ctx, base, target)
        if exists:
            continue
        # The suggestion the root-relative probe above already found. `target`
        # still carries its leading slash here, so the call on the line above
        # took the absolute branch and can never produce one.
        actual_case = actual_case or rooted_case
        # In a compiled docs tree the remaining shapes are site routes
        # rather than files: an extensionless target or an absolute path
        # from the site root. Neither can be settled by the filesystem, so
        # neither is judged. See `_SITE_CONFIGS` in extant/sites.py for the
        # measurement. The third, a `.html` target, is refused in
        # `_link_sites` instead, because it is refused unconditionally and
        # so is not a site the rule can decide at all.
        #
        # These two still need the gate. In a plain repository
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
    """Every link the rule will try to decide, from the one scanner.

    It used to run a pass of its own, which counted a `@ref` macro and a
    `.html` page - both refused by `check` in every repository - so the two
    halves described different populations and coverage was reported where
    none was provided. See `_link_sites`, which reads the CODE-STRIPPED
    document for both callers: a link inside a fence is an example of the
    syntax, and this project's own README documents the rule with a backticked
    example link that was reported as dead before inline spans were stripped.
    """
    return len(_link_sites(ctx, text))


def probe(ctx: Context, text: str) -> str | None:
    for match in MD_LINK.finditer(strip_code(ctx.doc, text)):
        raw = link_destination(match.group(1))
        if EXTERNAL.match(raw) or raw.startswith("#"):
            continue
        start, end = match.span(1)
        return text[:start] + MISSING_PATH + text[end:]
    return None


RULE = Rule(
    kind="dead-md-link",
    sequence=7,   # matches the pre-refactor examined: dict literal's order
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="does the linked file exist on disk?",
    probe=probe,
    examined=examined,
)
