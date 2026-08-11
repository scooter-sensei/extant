"""Generator detection, extended from a held-out corpus.

Ten repositories the original narrowing never saw produced 951 findings, and
526 of them were route-shaped links in projects whose generator extant did not
recognise - noise the existing suppression would already have removed if
detection had reached them.

Each change here is keyed on a measurement recorded beside it, never on the
shape of a link.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _kinds(repo, text):
    import extant_collect as hc
    hc._SCOPE = hc.RunScope()
    return [f.kind for f in hc.validate_md_links(repo, text)]


def _anchor_kinds(repo, text):
    import extant_collect as hc
    hc._SCOPE = hc.RunScope()
    return [f.kind for f in hc.validate_md_anchors(repo, text)]


def test_a_html_target_is_never_judged(git_repo) -> None:
    """MEASURED, not reasoned about: across 20 repositories in two corpora,
    407 markdown links point at a `.html` target and NOT ONE resolves to a
    checked-in file. A link to `.html` is a link to a rendered page.

    Judging them cost 276 findings on rails alone, whose guides compile
    `guides/source/*.md` into HTML with a bespoke builder that ships none of
    the generator configs this tool detects.

    Unconditional on purpose. Gating it on generator detection is what made
    those 276 fire, and the measurement says the gate protects nothing here.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" not in _kinds(
        repo, "See [the guide](getting_started.html).\n")


def test_a_missing_markdown_file_is_still_judged(git_repo) -> None:
    """The control. If the .html exemption widened to every extension, the
    rule would stop doing its job entirely."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" in _kinds(repo, "See [the plan](docs/gone.md).\n")


def test_a_nextjs_app_routes_by_path(git_repo) -> None:
    """Nextra builds on Next.js, which routes by file path, so a markdown link
    inside one is a route rather than a file.

    Measured on shuding/nextra: 227 findings, every one an extensionless or
    root-relative target, in a repository declaring `docs/next.config.ts`.
    """
    repo, commit = git_repo
    commit("docs/next.config.ts", "export default {}\n", "chore: next")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" not in _kinds(repo, "See [docs](/docs/getting-started).\n")


def test_docsify_is_declared_inside_its_index_html(git_repo) -> None:
    """Docsify ships no config of its own: a single `index.html` loads the
    script and every page is a route resolved at runtime.

    Measured on docsifyjs/docsify: 23 route-shaped findings under `docs/`,
    which is where its `index.html` lives - so the marker search has to look
    in the same subdirectories as the config search, not only at the root.
    """
    repo, commit = git_repo
    commit("docs/index.html",
           '<script src="//cdn.jsdelivr.net/npm/docsify@4"></script>\n',
           "chore: docsify")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" not in _kinds(repo, "See [quickstart](/quickstart).\n")


def test_an_unrelated_index_html_is_not_a_generator(git_repo) -> None:
    """The control for the marker. An `index.html` that says nothing about
    docsify must not silence route checking, or the signature is decoration."""
    repo, commit = git_repo
    commit("docs/index.html", "<html><body>hello</body></html>\n", "chore: page")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" in _kinds(repo, "See [quickstart](/quickstart).\n")


def test_a_site_one_directory_deeper_is_still_found(git_repo) -> None:
    """A site is often a subdirectory of a subdirectory.

    Measured on Aider-AI/aider, which keeps a Jekyll site at
    `aider/website/_config.yml`: a package directory, and the site inside it.
    Searching only `website/` found nothing, so the whole repository was judged
    as plain and 29 of its own asset links were reported dead - every one of
    them served by Jekyll out of `aider/website/assets/`.
    """
    repo, commit = git_repo
    commit("pkg/website/_config.yml", "title: x\n", "chore: jekyll")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" not in _kinds(repo, "See [assets](/assets/logo.png).\n")


def test_the_deeper_search_stops_at_one_level(git_repo) -> None:
    """The bound, which is the half that keeps this a signature.

    An unbounded walk would scan every directory in the repository to answer a
    question asked on every run, and a config found four levels down is
    likelier to be a fixture or a vendored copy than this project's own site.
    """
    repo, commit = git_repo
    commit("a/b/c/website/_config.yml", "title: x\n", "chore: nested")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" in _kinds(repo, "See [assets](/assets/logo.png).\n")


def test_mintlify_declares_itself_in_mint_json(git_repo) -> None:
    """Mintlify serves `.mdx` by route from a single declaration.

    Measured on humanlayer/humanlayer, which keeps `docs/mint.json` and
    reported 5 of its own `/core/require-approval` links dead.
    """
    repo, commit = git_repo
    commit("docs/mint.json", '{"name": "x"}\n', "chore: mintlify")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" not in _kinds(repo, "See [core](/core/require-approval).\n")


def test_an_unrelated_json_under_docs_is_not_a_generator(git_repo) -> None:
    """The control. `docs.json` is too generic a NAME to be a signature.

    Treating the filename alone as one would silently stop link checking for
    any project that keeps an unrelated `docs/docs.json`, which is a false
    negative and the worst kind: the tool would report a clean sweep.
    """
    repo, commit = git_repo
    commit("docs/docs.json", '{"name": "x"}\n', "chore: data")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" in _kinds(repo, "See [core](/core/require-approval).\n")


def test_a_mintlify_docs_json_is_recognised_by_its_content(git_repo) -> None:
    """Mintlify renamed `mint.json` to `docs.json`, so a current site declares
    itself in a file whose name says nothing.

    Content decides, through `_SITE_MARKERS_IN_FILE`: Mintlify writes its own
    schema URL into the file and nothing else does. Catches both halves -
    dropping the marker makes a real Mintlify site report its routes dead,
    and promoting `docs.json` to a filename signature breaks the control
    above.
    """
    repo, commit = git_repo
    commit("docs/docs.json",
           '{"$schema": "https://mintlify.com/docs.json", "name": "x"}\n',
           "chore: mintlify")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" not in _kinds(repo, "See [core](/core/require-approval).\n")


def test_the_namespace_search_looks_exactly_where_detection_does(git_repo) -> None:
    """Two searches for "where does this project keep its generator config"
    must not be able to disagree about the same repository.

    Measured across 30 repositories, aligning them changes nothing today. It
    is here because this exact shape has been a SHIPPED bug twice already:
    root-only missed jekyll's `docs/_config.yml`, and then the marker search
    missed docsify's `docs/index.html`. A third spelling of the same search,
    left one level shallower than the other two, is the next one.
    """
    repo, commit = git_repo
    commit("pkg/docs/conf.py", "project = 'x'\n", "chore: sphinx")
    commit("other.md", "# Widget\n\ntext\n", "docs: other")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-anchor" not in _anchor_kinds(repo, "See [w](#widget).\n")


def test_a_repository_declaring_no_namespace_still_judges_anchors(git_repo) -> None:
    """The control. Without a generator config anywhere, a fragment this
    document does not define is still reported - otherwise the alignment above
    would have silenced the rule rather than located it."""
    repo, commit = git_repo
    commit("other.md", "# Widget\n\ntext\n", "docs: other")
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-anchor" in _anchor_kinds(repo, "See [w](#widget).\n")


def test_a_plain_repository_still_judges_routes(git_repo) -> None:
    """The control that matters most. Blind, starlight reported 235 of its own
    working links as dead; universally on, every genuinely dead link in a plain
    repository stops being reported. Detection must stay a property of the
    repository."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" in _kinds(repo, "See [docs](/reference/config/).\n")
