"""Which markdown trees a generator compiles into a website, and where files are.

Two questions live here, and they are the same question from two directions:
what does this repository actually contain on disk, and which parts of it does
some documentation generator turn into routes. A link inside a generated tree
is a ROUTE rather than a path, so the filesystem cannot settle it and the
guarantee says a rule that cannot be settled must not judge.

Nothing in this module is public, because nothing outside the package calls it
yet. Its callers today are the link, anchor, branch and live-claim rules, all
of which are still in extant_collect.py; they become siblings in Task 9, and
whatever they reach for here is promoted in the commit that creates the caller.
Reading `text.py` from here is a sibling call already, which is why
`current_document`, `anchors` and `ORDER_PREFIX` are public over there.

`_ABSOLUTE` arrived with this module rather than going to `rules/path_pointer`
as the plan had it. Nothing else names it: `resolve_reference` is its only
reader, and once that moved here, leaving the pattern behind would have meant
this module importing the shim.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from extant.refs import tracked_markdown
from extant.scope import Context
from extant.text import ORDER_PREFIX, anchors, current_document

__all__ = [
    "_ABSOLUTE", "_FILEISH", "_GLOBAL_ANCHOR_CONFIGS", "_PARTIAL_CONFIGS",
    "_SITE_CONFIGS", "_SITE_DIRS", "_SITE_MARKERS_IN_FILE", "_actual_case",
    "_has_global_anchors", "_has_partial_anchors", "_listdir",
    "_numbered_docs_scopes", "_numbered_docs_tree", "_partial_anchors",
    "_project_anchors", "_site_dirs", "_site_scopes",
    "_top_level", "in_site_tree", "is_generated_site",
    "looks_like_a_path", "resolve_reference",
]

# An absolute path, which resolves against the filesystem root rather than
# against the citing document.
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")


# A branch name and a file path are THE SAME SHAPE: `prefix/name`. That is not
# a hypothetical collision. The installer's fallback pattern for a repository
# with no dominant branch prefix is `([\w.-]+/[^`]+)`, which matches
# `docs/arch.md` exactly as readily as `feature/checkout`.
#
# It went unnoticed for as long as `branch_token` fed only `stale-live-claim`,
# because that rule gates on a live phrase appearing in the same entry first, so
# the loose pattern almost never reached a check. `unknown-branch` has no such
# gate and inherited the looseness, reporting a renamed design document as a
# branch that never existed. Measured on a real installed repository, first run,
# which is the only reason it was caught before release.
#
# The extension test requires the first character after the dot to be a LETTER,
# so `docs/arch.md` is excluded while a genuine `release/v1.2` is not. Erring
# toward silence here is deliberate: a missed typo costs a reader nothing, and a
# file reported as a phantom branch is the kind of false positive that gets a
# validator switched off.
_FILEISH = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")


# Directory listings, cached only while validate() says it is safe to. Both the
# cache and the "is this repository static" flag that governs it now live on the
# run scope, where their lifetimes are written down beside them; see
# `RunScope.dircache` and `RunScope.stable`.
def _listdir(ctx: Context, directory: Path) -> set[str]:
    cache = ctx.run.dircache
    if cache is None:
        return {entry.name for entry in directory.iterdir()}
    names = cache.get(directory)
    if names is None:
        names = {entry.name for entry in directory.iterdir()}
        cache[directory] = names
    return names


def _actual_case(ctx: Context, base: Path, relative: str) -> str | None:
    """The on-disk spelling of `relative`, or None if no such file exists.

    Windows and macOS resolve `docs/PLAN.md` to `docs/plan.md` without
    complaint; Linux does not. A document that passes on a developer's laptop
    therefore fails in CI, or worse, passes in CI and misleads every Linux
    reader. Comparing each component against the real directory entry gives the
    same answer on every platform, which is the only useful kind.

    `Path.resolve()` is deliberately avoided: on Windows it silently rewrites a
    path to its on-disk case, which would make this function agree with the bug
    it exists to find.
    """
    probe = base
    parts: list[str] = []
    for part in Path(relative).parts:
        if part in (".", ".."):
            probe = probe / part
            parts.append(part)
            continue
        try:
            names = _listdir(ctx, probe)
        except OSError:
            return None
        if part in names:
            exact = part
        else:
            matches = [n for n in names if n.lower() == part.lower()]
            if not matches:
                return None
            exact = matches[0]
        parts.append(exact)
        probe = probe / exact
    return "/".join(parts)


def resolve_reference(ctx: Context, base: Path,
                       raw: str) -> tuple[bool, str | None]:
    """(exists_portably, on_disk_spelling_if_it_differs)."""
    if _ABSOLUTE.match(raw):
        return Path(raw).exists(), None
    actual = _actual_case(ctx, base, raw)
    if actual is None:
        return False, None
    normalised = Path(raw).as_posix()
    return (True, None) if actual == normalised else (False, actual)


# Configs that mean "this markdown tree is compiled into a website".
#
# It matters because a link in such a tree is a ROUTE, not a path. VitePress
# serves `docs/` as the site root, so `/guide/features.html` is a real link to
# `docs/guide/features.md`; MkDocs drops the extension, so `../advanced/
# transports` is a real link to `transports.md`. Neither is a file, so the
# filesystem cannot settle either, and the guarantee says a rule that cannot
# be settled must not judge.
#
# Measured across nine repositories: exactly the three that ship one of these
# files - vite (VitePress), httpx (MkDocs), rust-lang/rfcs (mdBook) - produced
# every route-shaped false positive, 331 of them. The six with no such config
# produced none, and in those `/CONTRIBUTING.md` really does mean repo root,
# which is how GitHub renders it.
_SITE_CONFIGS = (
    "mkdocs.yml", "mkdocs.yaml", "book.toml", "_config.yml",
    "docusaurus.config.js", "docusaurus.config.ts",
    "docs/.vitepress/config.ts", "docs/.vitepress/config.js",
    ".vitepress/config.ts", ".vitepress/config.js",
    "hugo.toml", "hugo.yaml",
    # Astro powers Starlight, whose docs link by route: withastro/starlight
    # reported 235 of its own `/de/reference/configuration/` links as dead
    # files. MyST builds a site from `myst.yml` the same way.
    "astro.config.mjs", "astro.config.ts", "astro.config.js",
    "myst.yml", "antora.yml", "conf.py",
    # Next.js routes by file path, so a markdown link inside one is a route.
    # Nextra builds on it: shuding/nextra reported 227 of its own links dead,
    # every one extensionless or root-relative, declaring `docs/next.config.ts`.
    "next.config.js", "next.config.ts", "next.config.mjs",
    # Mintlify serves `.mdx` by route from a single declaration.
    # humanlayer/humanlayer keeps `docs/mint.json` and reported 5 of its own
    # `/core/require-approval` links dead. Only `mint.json` is listed: the
    # newer `docs.json` spelling is too generic a filename to treat as a
    # signature, and no repository measured here carries one.
    "mint.json",
    # Fern serves `.mdx` by route from `fern/docs.yml`, and its pages link to
    # each other with site-absolute routes throughout. Skyvern keeps
    # `fern/fern.config.json` beside it and raised 52 findings, every one a
    # `/api-reference/...` route that works on the published documentation.
    # `fern.config.json` is the signature rather than `docs.yml`, which is too
    # generic a filename to treat as one.
    "fern.config.json",
)


# Generators whose configuration lives INSIDE another file rather than in one
# of its own, so existence is not enough and the content decides.
#
# Elixir declares ExDoc as a dependency in mix.exs. phoenixframework/phoenix
# does exactly that and links to `Mix.Tasks.Phx.Gen.Auth.html` and to sibling
# guides by bare name, both of which ExDoc resolves and the filesystem cannot:
# 104 findings, every one a link that works on hexdocs.
_SITE_MARKERS_IN_FILE = (
    ("mix.exs", "ex_doc"),
    # Docsify ships no config of its own: one `index.html` loads the script and
    # every page is a route resolved at runtime. docsifyjs/docsify keeps its at
    # `docs/index.html`, which is why the marker search below walks _SITE_DIRS
    # rather than looking only at the root.
    ("index.html", "docsify"),
    # Mintlify RENAMED `mint.json` to `docs.json`, so a current Mintlify site
    # declares itself in a file whose name says nothing. Listing `docs.json`
    # among the filename signatures would suppress link checking for any
    # project that happens to keep an unrelated `docs/docs.json`, which is why
    # it was left out. Content decides instead: Mintlify writes its own schema
    # URL into the file, and nothing else does.
    ("docs.json", "mintlify.com"),
)


# Where a generator config sits. The site is often a subdirectory of a project
# that is mostly something else: jekyll/jekyll keeps its own documentation site
# under `docs/` with `docs/_config.yml`, so a root-only search missed it and
# reported 138 of its site routes as dead files.
# `docs-website` and `documentation` added from a held-out corpus: haystack
# keeps `docs-website/docusaurus.config.js` and svelte keeps its pages under
# `documentation/`. Between them those two directories held 5,120 findings
# that a detected generator would already have silenced.
_SITE_DIRS = ("", "docs", "site", "www", "website", "docs-website",
              "documentation", "fern")


# Generators whose cross-reference namespace is the PROJECT, not the page.
#
# MyST and Sphinx resolve `#label` against every document at once, so a target
# defined in `site-options.md` is reachable as `#site-options` from anywhere.
# executablebooks/mystmd relies on that throughout: 168 of its findings name a
# label that exists, just not in the file doing the linking.
#
# Deliberately NOT applied to every generated site. Measured on encode/httpx,
# which is MkDocs and therefore per-page: a blanket project-wide union forgave
# two of its three genuinely dead anchors, trading real signal for quiet. The
# namespace is a property of the generator, so the generator decides.
_GLOBAL_ANCHOR_CONFIGS = ("myst.yml", "conf.py", "antora.yml")


def _has_global_anchors(ctx: Context) -> bool:
    key = str(ctx.repo)
    if key not in ctx.run.global_ns:
        # The same directory list as `is_generated_site`, deliberately. Two
        # searches for "where does this project keep its generator config"
        # that disagree is a latent bug, and this exact shape has been a
        # shipped one twice: root-only missed jekyll's `docs/_config.yml`, and
        # then the marker search missed docsify's `docs/index.html`. Measured
        # across 30 repositories it changes nothing today; it exists so the
        # two cannot answer differently about the same repository tomorrow.
        ctx.run.global_ns[key] = any((d / name).is_file()
                                     for d in _site_dirs(ctx)
                                     for name in _GLOBAL_ANCHOR_CONFIGS)
    return ctx.run.global_ns[key]


# Hugo alone, because the convention is Hugo's. Its `_`-prefixed content
# directories are not routable pages; they are fragments composed into other
# pages by a shortcode, so a term defined in `_common/configuration/locale.md`
# is an anchor on whatever page includes it. 23 of hugoDocs' 23 remaining
# same-document findings were exactly that.
#
# NOT generalised to every `_` directory, and the measurement is why: seven of
# 38 corpus repositories have markdown under one, and they mean different
# things. Jekyll's `_posts` are whole pages. Docusaurus's `__tests__` is
# fixtures. Treating those as ambient anchors would forgive real findings in
# four repositories to fix one.
_PARTIAL_CONFIGS = ("hugo.toml", "hugo.yaml", "hugo.json")


def _has_partial_anchors(ctx: Context) -> bool:
    key = str(ctx.repo)
    if key not in ctx.run.partial_ns:
        ctx.run.partial_ns[key] = any((d / name).is_file()
                                      for d in _site_dirs(ctx)
                                      for name in _PARTIAL_CONFIGS)
    return ctx.run.partial_ns[key]


def _partial_anchors(ctx: Context) -> set[str]:
    """Anchors from fragment files, which belong to every page that includes one."""
    key = str(ctx.repo)
    if key not in ctx.run.partial_anchors:
        found: set[str] = set()
        try:
            for rel in tracked_markdown(ctx):
                if not any(part.startswith("_") for part in rel.split("/")[:-1]):
                    continue
                try:
                    with open(ctx.repo / rel, encoding="utf-8", newline="") as fh:
                        found |= anchors(fh.read())
                except (OSError, UnicodeDecodeError):
                    continue
        except (OSError, subprocess.CalledProcessError):
            found = set()
        ctx.run.partial_anchors[key] = found
    return ctx.run.partial_anchors[key]


def _project_anchors(ctx: Context) -> set[str]:
    """Every anchor offered by every tracked markdown file in the project."""
    key = str(ctx.repo)
    if key not in ctx.run.project_anchors:
        found: set[str] = set()
        try:
            for rel in tracked_markdown(ctx):
                path = ctx.repo / rel
                try:
                    with open(path, encoding="utf-8", newline="") as fh:
                        found |= anchors(fh.read())
                except (OSError, UnicodeDecodeError):
                    continue
        except (OSError, subprocess.CalledProcessError):
            found = set()
        ctx.run.project_anchors[key] = found
    return ctx.run.project_anchors[key]


def _site_dirs(ctx: Context) -> list[Path]:
    """Every directory a generator config can sit in, one level of nesting deep.

    A site is often a subdirectory of a subdirectory. aider keeps a Jekyll site
    at `aider/website/_config.yml` - a package directory, and the site inside
    it - so a search that only tried `website/` found nothing and the whole
    repository was judged as plain. It reported 29 of its own asset links dead,
    every one of them served by Jekyll from `aider/website/assets/`.

    Bounded to ONE extra level on purpose, and to the same directory names. An
    unbounded walk would scan every directory in the repository to answer a
    question asked on every run, and a config found ten levels down is likelier
    to be a fixture or a vendored copy than this project's site.
    """
    dirs = [ctx.repo / d for d in _SITE_DIRS]
    for name in _SITE_DIRS:
        if name:
            dirs.extend(ctx.repo.glob(f"*/{name}"))
            # And one level INSIDE a site directory, which is the mirror of
            # the case above and was missing. llama_index declares MkDocs at
            # `docs/api_reference/mkdocs.yml`; the search reached `*/docs`
            # but never `docs/*`, so 1,227 route links were judged as files.
            # Still bounded to one level, and still to the same names, so
            # `a/b/c/website/` stays out of reach.
            dirs.extend(d for d in (ctx.repo / name).glob("*") if d.is_dir())
    return dirs


def is_generated_site(ctx: Context) -> bool:
    """Does this repository compile its markdown into a website?"""
    return bool(_site_scopes(ctx))


def _site_scopes(ctx: Context) -> set[str]:
    """Top-level directories a generator governs, or {""} for the whole repo.

    Recorded rather than reduced to a yes/no, because a monorepo is not one
    site. astro declares Astro under `examples/*` and llama_index declares
    MkDocs under `docs/`; treating either as "this repository is a site"
    stopped the route suppressions at the repository boundary and silenced
    six real defects in `packages/astro/src/core/render/README.md` and
    `llama-index-integrations/.../README.md`, which no site builds.

    Top-level and not the exact directory, because a config often sits one
    level inside the tree it governs: llama_index declares MkDocs at
    `docs/api_reference/mkdocs.yml` while the pages it serves live under
    `docs/src/content/docs/`. Scoping to `docs/` covers both.
    """
    key = str(ctx.repo)
    if key not in ctx.run.site:
        scopes: set[str] = set()
        for directory in _site_dirs(ctx):
            declared = any((directory / name).is_file()
                           for name in _SITE_CONFIGS)
            if not declared:
                for name, marker in _SITE_MARKERS_IN_FILE:
                    path = directory / name
                    try:
                        if path.is_file() and marker in path.read_text(
                                encoding="utf-8", errors="replace"):
                            declared = True
                            break
                    except OSError:
                        continue
            if declared:
                top = _top_level(ctx, directory)
                if top is not None:
                    scopes.add(top)
        scopes |= _numbered_docs_scopes(ctx)
        ctx.run.site[key] = scopes
    return ctx.run.site[key]


def _top_level(ctx: Context, directory: Path) -> str | None:
    """The first path segment of `directory` under the repo; "" for the root.

    None when the two cannot be related, which the caller drops rather than
    treating as the root. Returning "" on failure would mean "a generator
    governs this whole repository", the most permissive answer available, so
    a junction or a permission error would silently switch every route
    suppression on. `_site_dirs` builds these paths from `ctx.repo` itself,
    so
    the plain comparison succeeds; `resolve()` is the fallback, not the
    first move, because on Windows it can rewrite one side of a pair.
    """
    for candidate, base in ((directory, ctx.repo),
                            (directory.resolve(), ctx.repo.resolve())):
        try:
            relative = candidate.relative_to(base)
        except (ValueError, OSError):
            continue
        parts = relative.as_posix().split("/")
        return parts[0] if parts and parts[0] not in (".", "") else ""
    return None


def in_site_tree(ctx: Context) -> bool:
    """Is the document being validated inside a tree some generator builds?

    A repository with a site somewhere is not a repository whose every
    markdown file is a page. When the caller has not said which document is
    being read, this answers True, which keeps every existing caller and the
    whole-repository question behaving as before.
    """
    scopes = _site_scopes(ctx)
    if not scopes or "" in scopes:
        return bool(scopes)
    document = current_document(ctx.doc)
    if document is None:
        return True
    return document.split("/")[0] in scopes


def _numbered_docs_scopes(ctx: Context) -> set[str]:
    """Top-level directories holding a numbered documentation tree."""
    return {top for top, count in _numbered_docs_tree(ctx).items() if count >= 3}


def _numbered_docs_tree(ctx: Context) -> dict[str, int]:
    """A directory whose documents are NUMBERED for presentation order.

        documentation/docs/07-misc/01-best-practices.md
        documentation/docs/07-misc/02-testing.md
        documentation/docs/07-misc/04-custom-elements.md

    Nothing reads a prefix like that except a generator building an ordered
    site, and the pages then link to each other by the stripped name. This is
    the signal for a project whose site is built from ANOTHER repository, so
    no config exists here to find: svelte's pages live here and svelte.dev
    builds them, which left 64 of its own `/docs/svelte` links judged as
    files.

    Three in one directory, not one. A single `01-intro.md` beside ordinary
    filenames is somebody numbering one document; a directory of them is a
    convention with a consumer.
    """
    key = str(ctx.repo)
    if key not in ctx.run.numbered:
        per_dir: dict[str, int] = {}
        try:
            for path in tracked_markdown(ctx):
                head, _, leaf = path.rpartition("/")
                if not ORDER_PREFIX.match(leaf):
                    continue
                # Bounded to the conventional documentation directories, for
                # the reason `_site_dirs` bounds its own search: something
                # found deep inside a package is likelier to be a fixture
                # than this project's site.
                #
                # Unbounded, this declared all of `packages/` a documentation
                # site on the strength of three numbered `.mdx` files in
                # `packages/astro/test/fixtures/content/src/content/blog/`,
                # and route suppression then hid three real defects in
                # `packages/astro/src/core/render/README.md`.
                top = head.split("/")[0] if head else ""
                if top and top not in _SITE_DIRS:
                    continue
                per_dir[head] = per_dir.get(head, 0) + 1
        except (OSError, subprocess.CalledProcessError):
            per_dir = {}
        # Reported per TOP-LEVEL directory, keeping the largest run found
        # under each, so the threshold is still "three in one directory" but
        # the answer says which part of the repository it governs.
        tops: dict[str, int] = {}
        for directory, count in per_dir.items():
            top = directory.split("/")[0] if "/" in directory else directory
            tops[top] = max(tops.get(top, 0), count)
        ctx.run.numbered[key] = tops
    return ctx.run.numbered[key]


def looks_like_a_path(ctx: Context, token: str) -> bool:
    """True when a token is better explained as a file than as a branch."""
    return bool(_FILEISH.search(token)) or (ctx.repo / token).exists()
