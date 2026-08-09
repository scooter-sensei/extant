"""The ten false-positive classes a held-out corpus exposed, and their fixes.

Forty repositories disjoint from the 92 that designed these rules produced
7,658 findings on 2026-08-08. 582 were real. The other 7,067 fell into exactly
ten mechanical shapes, none of which the design corpus contained, and each is
narrowed here.

Every test comes in a PAIR: one proving the false positive is gone, one
proving the rule still fires on the real defect it exists for. A narrowing
tested only by its silence cannot be told apart from a rule that stopped
working, which is the failure mode this whole project is about.

Counts in the docstrings are what that class produced on the held-out corpus.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _clear() -> None:
    """Drop every per-repository cache between tests.

    `_DIRCACHE` is None until a caller sets it, so this skips anything that is
    not a live mapping rather than assuming they all are.
    """
    import extant_collect as hc
    for name in ("_SITE", "_GLOBAL_NS", "_PARTIAL_NS", "_BASENAMES", "_ROUTES",
                 "_CHANGESETS", "_NUMBERED", "_TARGET_ANCHORS", "_DIRCACHE"):
        cache = getattr(hc, name, None)
        if hasattr(cache, "clear"):
            cache.clear()


def _links(repo, text) -> list[str]:
    import extant_collect as hc
    _clear()
    return [f.subject for f in hc.validate_md_links(repo, text)]


def _shas(repo, text) -> list[str]:
    import extant_collect as hc
    _clear()
    return [f.subject for f in hc.validate_references(repo, text)]


def _anchors(repo, text) -> list[str]:
    import extant_collect as hc
    _clear()
    return [f.subject for f in hc.validate_md_anchors(repo, text)]


def _pointers(repo, text) -> list[str]:
    import extant_collect as hc
    _clear()
    return [f.subject for f in hc.validate_path_pointers(repo, text)]


# --------------------------------------------------------------------------
# 1. A leading slash is a site root, never a repository root.  6,360 findings
# --------------------------------------------------------------------------

def test_a_site_declared_one_level_down_is_detected(git_repo) -> None:
    """The largest class by far: 83% of everything the sweep reported.

    The shape was never the problem. Detection simply did not reach the
    layout: haystack keeps `docs-website/docusaurus.config.js`, and the
    directory search knew `docs`, `site`, `www` and `website` only.

    A blanket skip on root-absolute links was tried first and two existing
    tests refused it, correctly - in a repository that builds no site such a
    link really is dead. Widening detection removes the findings and leaves
    the rule.
    """
    repo, commit = git_repo
    commit("docs-website/docusaurus.config.js", "module.exports = {}\n", "seed")
    commit("README.md", "x\n", "second")
    text = "See [reference](/reference/data-classes-api) for details.\n"
    assert _links(repo, text) == []


def test_a_site_declared_inside_docs_is_detected(git_repo) -> None:
    """llama_index declares MkDocs at `docs/api_reference/mkdocs.yml`.

    The search reached `*/docs` but never `docs/*`, which is the mirror of a
    case it already handled. 1,227 route links were judged as files.
    """
    repo, commit = git_repo
    commit("docs/api_reference/mkdocs.yml", "site_name: x\n", "seed")
    commit("README.md", "x\n", "second")
    assert _links(repo, "See [api](/python/framework/instrumentation).\n") == []


def test_fern_declares_a_site(git_repo) -> None:
    """Fern serves `.mdx` by route from `fern/docs.yml`.

    Found by the tree-scoping change rather than by the original sweep:
    scoping suppression to the tree a generator governs correctly stopped
    treating all of Skyvern as a site, and then correctly reported 52
    `/api-reference/...` routes under `fern/` that no config had claimed.
    """
    repo, commit = git_repo
    commit("fern/fern.config.json", '{"organization": "x"}\n', "seed")
    commit("fern/docs/intro.mdx", "# Intro\n", "second")
    assert _links(repo, "See [create](/api-reference/browser/create).\n") == []


def test_a_numbered_docs_tree_is_a_site(git_repo) -> None:
    """svelte's pages are built by svelte.dev, so no config exists here.

    Nothing reads an ordering prefix except a generator building an ordered
    site, so the prefix is the declaration.
    """
    repo, commit = git_repo
    for name in ("01-best-practices", "02-testing", "04-custom-elements"):
        commit(f"documentation/docs/07-misc/{name}.md", "# x\n", name)
    assert _links(repo, "See the [tutorial](/tutorial).\n") == []


def test_a_bare_name_does_not_resolve_across_translation_trees(
        git_repo, monkeypatch) -> None:
    """The regression the corpus caught, which widening detection caused.

    fastapi builds a separate site per language and keeps `newsletter.md`
    only in English. Once detection reached `docs/en/mkdocs.yml`, the
    pre-existing bare-name suppression started matching every translated
    page's broken link against the English file, and 68 real defects across
    ten languages went quiet.

    Counting within the citing document's own language tree restores them.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/en/mkdocs.yml", "site_name: x\n", "seed")
    commit("docs/en/docs/newsletter.md", "# News\n", "en")
    for lang in ("de", "es", "fr"):
        commit(f"docs/{lang}/docs/index.md", "# Index\n", lang)
    monkeypatch.setattr(hc, "_DOC_PATH", "docs/de/docs/help.md")
    monkeypatch.setattr(hc, "_LINK_BASE", repo / "docs" / "de" / "docs")
    assert _links(repo, "See the [newsletter](newsletter.md).\n") == [
        "newsletter.md"]


def test_a_bare_name_still_resolves_inside_its_own_tree(
        git_repo, monkeypatch) -> None:
    """The English page linking to the English file is fine, and the
    suppression this narrows must still work where it was right."""
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/en/mkdocs.yml", "site_name: x\n", "seed")
    commit("docs/en/guides/newsletter.md", "# News\n", "en")
    for lang in ("de", "es", "fr"):
        commit(f"docs/{lang}/docs/index.md", "# Index\n", lang)
    monkeypatch.setattr(hc, "_DOC_PATH", "docs/en/docs/help.md")
    monkeypatch.setattr(hc, "_LINK_BASE", repo / "docs" / "en" / "docs")
    assert _links(repo, "See the [newsletter](newsletter.md).\n") == []


def test_a_lone_language_shaped_directory_is_not_a_tree(
        git_repo, monkeypatch) -> None:
    """Recognised by siblings, not by the name. A single `docs/id/` is an
    "id" directory, and treating it as a language would split a namespace
    that a flat-namespace generator really does resolve across.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/mkdocs.yml", "site_name: x\n", "seed")
    commit("docs/id/contexts.md", "# Contexts\n", "one")
    # Three ordinary sibling directories, so the count alone would cross the
    # threshold. Only the language SHAPE keeps `id` from being read as a
    # translation tree, and without those three the mutation that deletes
    # that check still leaves one sibling and the test passes regardless -
    # which is exactly what the mutation run reported the first time.
    for name in ("guides", "reference", "tutorials"):
        commit(f"docs/{name}/index.md", "# Index\n", name)
    monkeypatch.setattr(hc, "_DOC_PATH", "docs/guides/authn.md")
    monkeypatch.setattr(hc, "_LINK_BASE", repo / "docs" / "guides")
    assert _links(repo, "See [contexts](contexts.md).\n") == []


def test_a_readme_outside_the_site_tree_is_still_judged(
        git_repo, monkeypatch) -> None:
    """A repository with a site somewhere is not a repository whose every
    markdown file is a page.

    Detecting a site and then applying route suppression repository-wide
    silenced six real defects in source-tree READMEs that no site builds:
    `packages/astro/src/core/render/README.md` links to `../endpoint/`, a
    directory that does not exist, and llama_index's integration READMEs link
    to a `LICENSE` that is not beside them.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/mkdocs.yml", "site_name: x\n", "seed")
    # Exactly ONE `guide.md` in the repository. A second copy makes the
    # bare-name check false on its own, and the test then passes whether the
    # scoping works or not - which is how it first survived the mutation that
    # reverts this line.
    commit("docs/guide.md", "# Guide\n", "docs")
    commit("packages/core/README.md", "# Core\n", "pkg")
    monkeypatch.setattr(hc, "_DOC_PATH", "packages/core/README.md")
    monkeypatch.setattr(hc, "_LINK_BASE", repo / "packages" / "core")
    assert _links(repo, "See [the guide](guide.md).\n") == ["guide.md"]


def test_a_page_inside_the_site_tree_is_still_suppressed(
        git_repo, monkeypatch) -> None:
    """The other side of the same scoping, so it cannot become a blanket
    re-enable."""
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/mkdocs.yml", "site_name: x\n", "seed")
    commit("docs/reference/guide.md", "# Guide\n", "docs")
    monkeypatch.setattr(hc, "_DOC_PATH", "docs/intro.md")
    monkeypatch.setattr(hc, "_LINK_BASE", repo / "docs")
    assert _links(repo, "See [the guide](guide.md).\n") == []


def test_a_numbered_fixture_deep_in_a_package_is_not_a_site(git_repo) -> None:
    """Bounded to the conventional documentation directories, for the reason
    `_site_dirs` bounds its own config search.

    Unbounded, three numbered `.mdx` files in
    `packages/astro/test/fixtures/content/src/content/blog/` declared all of
    `packages/` a documentation site, and route suppression then hid three
    real defects in `packages/astro/src/core/render/README.md`.
    """
    import extant_collect as hc
    repo, commit = git_repo
    for name in ("1-one", "2-two", "3-three"):
        commit(f"packages/app/test/fixtures/content/{name}.md", "# x\n", name)
    commit("packages/app/README.md", "# App\n", "readme")
    monkeypatch_free = repo / "packages" / "app"
    hc._DOC_PATH = "packages/app/README.md"
    hc._LINK_BASE = monkeypatch_free
    try:
        assert _links(repo, "See [endpoint](../endpoint/).\n") == ["../endpoint/"]
    finally:
        hc._DOC_PATH = None
        hc._LINK_BASE = None


def test_a_uuid_inside_an_identifier_is_not_a_sha(git_repo) -> None:
    """`\\b` fails between an underscore and a hex digit, so a UUID embedded in
    an identifier was not recognised and its trailing field read as a SHA."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = "DEBUG Session ID: conversation_f43eb21b-84cb-49e7-90fb-56595df594e6\n"
    assert _shas(repo, text) == []


def test_an_ordinary_bare_sha_still_fires(git_repo) -> None:
    """The control for the UUID change.

    The token that was wrongly reported is the UUID's LAST field, preceded by
    a dash rather than by the underscore - `_BARE_SHA_TOKEN` has always
    rejected hex behind a word character, which is why widening `_UUID` was
    the fix and not narrowing that. This pins that widening did not also
    swallow a plain reference.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    assert _shas(repo, "See 9dc767d0aa11 for the fix.\n") == ["9dc767d0aa11"]


def test_a_uuid_without_a_prefix_is_still_skipped(git_repo) -> None:
    """The case that already worked, kept working."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = "Session f43eb21b-84cb-49e7-90fb-56595df594e6 finished.\n"
    assert _shas(repo, text) == []


def test_one_numbered_file_is_not_a_site(git_repo) -> None:
    """Three in a directory, not one. Somebody numbering a single document is
    not a convention with a consumer, and treating it as one would silence
    root-absolute links across ordinary repositories.
    """
    repo, commit = git_repo
    commit("docs/01-intro.md", "# Intro\n", "seed")
    commit("docs/guide.md", "# Guide\n", "second")
    assert _links(repo, "See [gone](/reference/config).\n") == [
        "/reference/config"]


def test_root_absolute_link_still_resolves_when_the_file_is_there(git_repo) -> None:
    """Silence must not come from having stopped looking.

    A root-absolute target that DOES name a file still resolves, so the
    suppression above is reached only after the filesystem has been asked.
    """
    repo, commit = git_repo
    commit("docs/guide.md", "# Guide\n", "seed")
    assert _links(repo, "See [guide](/docs/guide.md).\n") == []


def test_a_relative_dead_link_still_fires(git_repo) -> None:
    """The rule's whole point, unaffected by the narrowing above."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    assert _links(repo, "See [gone](docs/missing.md).\n") == ["docs/missing.md"]


# --------------------------------------------------------------------------
# 2. A docs tree that orders pages by filename prefix.        139 findings
# --------------------------------------------------------------------------

def test_ordering_prefix_is_stripped_from_the_route(git_repo) -> None:
    """svelte links to `04-custom-elements.md` as `custom-elements`.

    The prefix is the evidence that something strips it, so this needs no
    generator detection.
    """
    repo, commit = git_repo
    commit("documentation/docs/07-misc/04-custom-elements.md", "# CE\n", "seed")
    text = "See the [options](custom-elements) for details.\n"
    assert _links(repo, text) == []


def test_an_unprefixed_document_does_not_answer_to_a_bare_name(git_repo) -> None:
    """Without this the narrowing becomes `_unique_basename` with its gate
    removed, silencing a link to `foo` anywhere a `foo.md` exists at all.

    Mutation check: deleting the `_ORDER_PREFIX` guard in
    `_numbered_document` turns this test red.
    """
    repo, commit = git_repo
    commit("elsewhere/unrelated/setup.md", "# Setup\n", "seed")
    assert _links(repo, "See [setup](setup).\n") == ["setup"]


def test_two_documents_answering_one_route_are_not_guessed(git_repo) -> None:
    """Exactly one match, never "at least one"."""
    repo, commit = git_repo
    commit("docs/01-a/02-setup.md", "# A\n", "seed")
    commit("docs/02-b/03-setup.md", "# B\n", "second")
    assert _links(repo, "See [setup](setup).\n") == ["setup"]


# --------------------------------------------------------------------------
# 3. A SHA that is link text for somebody else's commit.       192 findings
# --------------------------------------------------------------------------

def test_a_sha_linked_to_a_commit_url_is_not_this_repos_claim(git_repo) -> None:
    """Changesets writes release notes this way, and a monorepo that absorbed
    another project keeps citing the original. The URL states whose commit it
    is; `_URL` has always dropped a BARE hex run inside a link target for that
    reason, and the backticked path never had the equivalent.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = ("- [#159](https://github.com/withastro/adapters/pull/159) "
            "[`adb8bf2a4caeead9a1a255740c7abe8666a6f852`]"
            "(https://github.com/withastro/adapters/commit/"
            "adb8bf2a4caeead9a1a255740c7abe8666a6f852) Thanks!\n")
    assert _shas(repo, text) == []


def test_a_backticked_sha_with_no_link_still_fires(git_repo) -> None:
    """The qualification is the link, not the backticks."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = "Fixed in `adb8bf2a4caeead9a1a255740c7abe8666a6f852`.\n"
    assert _shas(repo, text) == ["adb8bf2a4caeead9a1a255740c7abe8666a6f852"]


# --------------------------------------------------------------------------
# 4. A hex run inside a filename is part of the filename.      144 findings
# --------------------------------------------------------------------------

def test_a_hash_prefixed_asset_name_is_not_a_sha(git_repo) -> None:
    """Documentation platforms mint asset names by prefixing a content hash.

    `83f686b` has a word boundary either side and is valid hex, so it read as
    an abbreviated commit.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = '<ClickableImage src="/img/83f686b-Pipeline_Illustrations_1_1.png" />\n'
    assert _shas(repo, text) == []


def test_a_bare_sha_beside_an_image_still_fires(git_repo) -> None:
    """The suppression covers the filename span, not the whole line."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = 'See ![x](/img/83f686b-chart.png) fixed in 9dc767d0aa11 today.\n'
    assert _shas(repo, text) == ["9dc767d0aa11"]


def test_the_asset_pattern_is_not_quadratic() -> None:
    """A long line must not hang the scan.

    Written first as `[\\w./~-]*\\.(ext)`, this pattern took 321,822 ms on one
    120,000-character line: an unbounded run restarts at every position, so a
    long path or a base64 data URI is quadratic. The longest markdown line in
    the earlier corpus was 123,427 characters, which makes that a hang waiting
    for a real document rather than a theoretical concern.

    Anchoring to the start of a path-like run and bounding its length brought
    the same input to under 5 ms. The budget here is deliberately loose - two
    orders of magnitude of headroom - because this is a guard against
    catastrophic backtracking, not a benchmark.
    """
    import time
    import extant_collect as hc
    worst = 0.0
    for line in ("a" * 120000,
                 "abc/def." * 15000,
                 "![x](data:image/png;base64," + "A" * 120000 + ")",
                 "0123456789abcdef" * 7500):
        started = time.perf_counter()
        hc._ASSET_PATH.findall(line)
        worst = max(worst, time.perf_counter() - started)
    assert worst < 1.0, f"slowest line took {worst:.1f}s; the bound is gone"


def test_the_asset_pattern_still_matches_a_real_asset() -> None:
    """The speed fix must not have been achieved by matching nothing."""
    import extant_collect as hc
    line = '<ClickableImage src="/img/83f686b-Pipeline_1_1.png" alt="x" />'
    assert hc._ASSET_PATH.findall(line) == ["/img/83f686b-Pipeline_1_1.png"]


# --------------------------------------------------------------------------
# 5. A ref pinned to another repository.                        14 findings
# --------------------------------------------------------------------------

def test_an_action_pinned_by_sha_is_not_this_repos_commit(git_repo) -> None:
    """`owner/repo@` names whose commit it is, and it is not this one's.

    Pinning an action by SHA is what security guidance asks for, so a rule
    that punishes it is actively unhelpful.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = "    uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd\n"
    assert _shas(repo, text) == []


# --------------------------------------------------------------------------
# 6. A changeset id was minted by a tool, not by git.           50 findings
# --------------------------------------------------------------------------

def test_a_changeset_entry_is_not_a_commit_reference(git_repo) -> None:
    """Gated on the repository actually using the tool, because the line shape
    alone is how a person writes a REAL commit reference too.
    """
    repo, commit = git_repo
    commit(".changeset/config.json", '{"changelog": "x"}\n', "seed")
    text = "- 8b82179: Fix auto imports and code actions not working\n"
    assert _shas(repo, text) == []


def test_the_same_line_still_fires_without_changesets(git_repo) -> None:
    """The gate is the directory, not the wording.

    Mutation check: dropping the `_uses_changesets` condition turns this red,
    which is what stops the narrowing swallowing real references everywhere.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = "- 8b82179: Fix auto imports and code actions not working\n"
    assert _shas(repo, text) == ["8b82179"]


# --------------------------------------------------------------------------
# 7. Thirty-two hex characters is a digest.                     45 findings
# --------------------------------------------------------------------------

def test_a_thirty_two_character_hex_run_is_not_a_commit(git_repo) -> None:
    """MD5 and a dash-free UUID are both 32. Git abbreviations run 7 to 12 and
    a full object name is 40, so nothing legitimate sits at exactly 32.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = "- Example: `c55168be3874490ef0565d9779ecd5a6`\n"
    assert _shas(repo, text) == []


def test_a_forty_character_hex_run_still_fires(git_repo) -> None:
    """The exclusion is a length, and it must not have taken the neighbours."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    full = "c55168be3874490ef0565d9779ecd5a6c55168be"
    assert _shas(repo, f"- Example: `{full}`\n") == [full]


# --------------------------------------------------------------------------
# 8. A pointer resolves beside the document that cites it.      61 findings
# --------------------------------------------------------------------------

def test_a_pointer_resolves_relative_to_its_own_document(git_repo, monkeypatch) -> None:
    """A nested SKILL.md saying "see `references/cli.md`" was reported dead
    while the file sat in the very next directory entry.

    `validate_md_links` had resolved relative to the document all along; the
    inconsistency between the two rules was the bug.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("skills/imagegen/references/cli.md", "# CLI\n", "seed")
    monkeypatch.setattr(hc, "_LINK_BASE", repo / "skills" / "imagegen")
    assert _pointers(repo, "See `references/cli.md` for the flags.\n") == []


def test_a_pointer_to_nothing_still_fires(git_repo, monkeypatch) -> None:
    """Neither the root nor the document's directory has it."""
    import extant_collect as hc
    repo, commit = git_repo
    commit("skills/imagegen/SKILL.md", "x\n", "seed")
    monkeypatch.setattr(hc, "_LINK_BASE", repo / "skills" / "imagegen")
    assert _pointers(repo, "See `references/gone.md` for the flags.\n") == [
        "references/gone.md"]


def test_a_pointer_that_is_link_text_defers_to_its_url(git_repo, monkeypatch) -> None:
    """`read [`PULL_REQUEST_TEMPLATE.md`](./.github/PULL_REQUEST_TEMPLATE.md)`.

    The text names the file, the URL says where it is. Reading the text as a
    pointer and resolving it against the repository root reported a link that
    works. The link beside it is the authority, exactly as `_LINKED_SHA`
    treats a SHA that is link text.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit(".github/PULL_REQUEST_TEMPLATE.md", "# PR\n", "seed")
    monkeypatch.setattr(hc, "_LINK_BASE", repo)
    text = ("You MUST read [`PULL_REQUEST_TEMPLATE.md`]"
            "(./.github/PULL_REQUEST_TEMPLATE.md) first.\n")
    assert _pointers(repo, text) == []


def test_link_text_still_fires_when_the_url_is_dead_too(git_repo, monkeypatch) -> None:
    """Deferring to the URL is not the same as ignoring the claim.

    Roo-Code cites an `ADDING-EVALS.md` that is absent both as text and as
    URL, and that one is still a real defect.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    monkeypatch.setattr(hc, "_LINK_BASE", repo)
    text = "See [`packages/evals/ADDING-EVALS.md`](packages/evals/ADDING-EVALS.md).\n"
    assert _pointers(repo, text) == ["packages/evals/ADDING-EVALS.md"]


def test_a_root_relative_pointer_is_unaffected(git_repo) -> None:
    """The original behaviour, with no document directory set."""
    repo, commit = git_repo
    commit("docs/plan.md", "# Plan\n", "seed")
    assert _pointers(repo, "Design: `docs/plan.md`\n") == []


# --------------------------------------------------------------------------
# 9. An emoji heading keeps a leading dash in its anchor.       58 findings
# --------------------------------------------------------------------------

def test_an_emoji_heading_anchors_with_a_leading_dash(git_repo) -> None:
    """GitHub does not trim the edges of a slug. The emoji is dropped and the
    space after it still becomes a dash, so the anchor opens with one.

    Both spellings are offered rather than the old one replaced, because
    renderers that DO trim exist and a fragment matching neither is still dead.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = ("See [Component structure](#-component-structure).\n"
            "\n"
            "## \N{BRICK} Component structure\n")
    assert _anchors(repo, text) == []


def test_the_trimmed_spelling_still_works(git_repo) -> None:
    """Adding a variant must not have cost the one that was already right."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = ("See [Component structure](#component-structure).\n"
            "\n"
            "## \N{BRICK} Component structure\n")
    assert _anchors(repo, text) == []


def test_the_untrimmed_slug_contributes_only_what_trimming_loses() -> None:
    """Pinned on the function directly, because no behavioural test can see it.

    Offering a spelling nobody uses only ever SUPPRESSES, so a version of this
    that also returned the trimmed form produces no finding to catch it. What
    it does instead is stand in for `_slug`: the mutation that stops `_slug`
    stripping punctuation SURVIVED while this returned both, because
    `build.target` still offered `buildtarget` from here.

    A check that another check silently covers is a check nobody is running,
    and the only way to hold this one is to state the contract.
    """
    import extant_collect as hc
    # Nothing for trimming to lose, so it contributes nothing and cannot
    # substitute for `_slug`.
    assert hc._slug_keeping_edges("build.target") == ""
    assert hc._slug_keeping_edges("Plain heading") == ""
    # An emoji is dropped and the space after it still becomes a dash, which
    # trimming would remove. That spelling is this function's whole purpose.
    assert hc._slug_keeping_edges("\N{BRICK} Component structure") == (
        "-component-structure")


def test_an_anchor_matching_no_spelling_still_fires(git_repo) -> None:
    """Two extra spellings are still not all of them."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = ("See [nothing](#no-such-section).\n"
            "\n"
            "## \N{BRICK} Component structure\n")
    assert _anchors(repo, text) == ["#no-such-section"]


# --------------------------------------------------------------------------
# 10. Setext headings are headings.                              3 findings
# --------------------------------------------------------------------------

def test_underlined_headings_offer_anchors(git_repo) -> None:
    """A document written entirely in this style offered NO anchors at all,
    so every link into it read as dead. The failure is total rather than
    partial, which is what makes 3 findings worth a fix.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = ("See [limits](#limitations).\n"
            "\n"
            "Limitations\n"
            "-----------\n"
            "\n"
            "Some prose.\n")
    assert _anchors(repo, text) == []


def test_frontmatter_does_not_invent_a_heading(git_repo) -> None:
    """The closing `---` of YAML frontmatter follows a non-blank line, which
    would otherwise promote `title: something` to a heading and offer an
    anchor the document does not have.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = ("---\n"
            "title: Something\n"
            "---\n"
            "\n"
            "See [it](#title-something).\n")
    assert _anchors(repo, text) == ["#title-something"]


def test_a_dead_anchor_in_a_setext_document_still_fires(git_repo) -> None:
    """Parsing more headings must not mean accepting every fragment."""
    repo, commit = git_repo
    commit("README.md", "x\n", "seed")
    text = ("See [gone](#no-such-thing).\n"
            "\n"
            "Limitations\n"
            "-----------\n")
    assert _anchors(repo, text) == ["#no-such-thing"]
