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
    for cache in (hc._SITE, hc._GLOBAL_NS, hc._PARTIAL_NS):
        cache.clear()
    return [f.kind for f in hc.validate_md_links(repo, text)]


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


def test_a_plain_repository_still_judges_routes(git_repo) -> None:
    """The control that matters most. Blind, starlight reported 235 of its own
    working links as dead; universally on, every genuinely dead link in a plain
    repository stops being reported. Detection must stay a property of the
    repository."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")

    assert "dead-md-link" in _kinds(repo, "See [docs](/reference/config/).\n")
