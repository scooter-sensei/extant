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
    from extant import session as hc
    from extant.rules import md_link as rule_md_link
    hc._SCOPE = hc.RunScope()
    return [f.kind for f in rule_md_link.check(hc.context(repo), text)]


def _anchor_kinds(repo, text):
    from extant import session as hc
    from extant.rules import md_anchor as rule_md_anchor
    hc._SCOPE = hc.RunScope()
    return [f.kind for f in rule_md_anchor.check(hc.context(repo), text)]


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


# --- path components, which must not depend on which platform is asking ------


def test_a_reference_is_split_the_same_way_on_every_platform() -> None:
    r"""`Path(x).parts` gave two different answers, and only one leg saw it.

    `Path("Docs\Guide.md").parts` is ("Docs", "Guide.md") on Windows and
    ("Docs\Guide.md",) on POSIX. A pointer written the Windows way therefore
    resolved on a developer's laptop and was reported dead on the Linux CI leg
    - the split verdict `_actual_case` exists to abolish, arriving through the
    standard library rather than through the filesystem, so the careful
    component-by-component comparison never saw it.

    `path_pointer` is the caller that makes this matter: its default pattern is
    `[\w:.\\/-]+`, which deliberately admits `tools\extant\cli.py` and a
    drive letter, because that is how a Windows-authored document writes a
    path.

    A UNIT test on the splitter, deliberately, and this is the one place in the
    suite where that choice needs defending. The behavioural difference is
    invisible on Windows - both spellings already resolve there - so a test
    that only ran the rule would pass on this machine no matter which splitter
    is used, and would go red only on the ubuntu leg. Asserting the split
    itself fails on EVERY platform the moment someone reaches for
    `Path().parts` again.
    """
    from extant.sites import _components

    assert _components(r"Docs\Guide.md") == ["Docs", "Guide.md"]
    assert _components("Docs/Guide.md") == ["Docs", "Guide.md"]
    assert _components(r"tools\extant\cli.py") == ["tools", "extant", "cli.py"]
    # `.` and empty segments are dropped, as `Path().parts` already did; `..`
    # is kept, because `_actual_case` walks it deliberately.
    assert _components("./docs//guide.md") == ["docs", "guide.md"]
    assert _components("../docs/guide.md") == ["..", "docs", "guide.md"]


def test_a_windows_spelled_pointer_resolves(git_repo) -> None:
    """The behavioural half, which is only red on a case-sensitive filesystem.

    Stated rather than implied: on Windows this passed before the fix too. It
    is here because it is the assertion that fails on the ubuntu leg of CI with
    the old splitter, which is the leg the bug lived on.
    """
    from extant import session as hc
    from extant.sites import resolve_reference
    repo, commit = git_repo
    commit("Docs/Guide.md", "# Guide\n", "docs: a guide")
    hc._SCOPE = hc.RunScope()
    ctx = hc.context(repo)

    assert resolve_reference(ctx, repo, r"Docs\Guide.md") == (True, None)
    assert resolve_reference(ctx, repo, "Docs/Guide.md") == (True, None)
    # A case error is still a case error, whichever separator wrote it.
    assert resolve_reference(ctx, repo, r"docs\guide.md") == (False,
                                                              "Docs/Guide.md")


def test_the_anchor_rule_does_not_read_a_file_outside_the_repository(
        git_repo, tmp_path) -> None:
    """`dead-md-anchor` built its own path and asked the filesystem directly.

    `Path(repo) / "C:/x"` is `C:/x`, so a fragment naming an absolute target
    made this rule read a markdown file ANYWHERE on the machine and judge
    against it - and when the fragment did not match, the finding carried the
    absolute path into the CI log, the SARIF location and the pull-request
    annotation. `resolve_reference` had just been repaired for exactly that,
    and this rule bypassed it by not asking.

    Catches a return to any home-grown `is_file()` here.
    """
    from extant import session as hc
    from extant.rules import md_anchor
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret Heading\n\nbody\n", encoding="utf-8")
    hc._SCOPE = hc.RunScope()
    hc.set_document(link_base=repo, doc_path="DOC.md", doc_format="markdown")

    found = md_anchor.check(
        hc.context(repo),
        "[x](%s#no-such-anchor)\n" % outside.as_posix())

    assert found == [], (
        "judged a fragment against a file outside the repository: "
        + "; ".join(f.detail for f in found))


def test_an_absolute_target_is_not_answered_by_the_machines_filesystem(
        git_repo, tmp_path) -> None:
    """A path outside the repository cannot settle a claim about it.

    `resolve_reference` answered an absolute target with `Path(raw).exists()`,
    consulting the machine's filesystem root - so a dead root-relative link was
    silenced for whoever happened to have that path on disk and reported for
    everyone else, and on Windows the match was case-insensitive too.

    `tmp_path` is the probe because it is absolute and certainly exists on
    every platform the suite runs on, which is exactly the condition that used
    to return True. Catches a revert to any filesystem probe here, not just to
    the original one.
    """
    from extant import session as hc
    from extant.sites import resolve_reference
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    hc._SCOPE = hc.RunScope()
    ctx = hc.context(repo)

    assert tmp_path.is_dir(), "the probe path must exist for this to mean anything"
    assert resolve_reference(ctx, repo, str(tmp_path)) == (False, None)
    assert resolve_reference(ctx, repo, "/" + tmp_path.name) == (False, None)


def test_a_root_relative_link_names_the_case_it_should_have_used(git_repo) -> None:
    """"Does not exist" about a file that DOES exist sends the reader hunting.

    A leading slash means the repository root. The rooted probe took only the
    boolean half of that answer and threw the on-disk spelling away, and the
    fall-through then asked `resolve_reference` about a target still carrying
    its slash - the absolute branch, which answers about the filesystem root
    and can never suggest a case. So a root-relative link whose only fault was
    two letters was reported as a missing document.
    """
    from extant import session as hc
    from extant.rules import md_link as rule
    repo, commit = git_repo
    commit("Docs/Guide.md", "# Guide\n", "docs: a guide")
    hc._SCOPE = hc.RunScope()

    found = rule.check(hc.context(repo), "[g](/docs/guide.md)\n")

    assert len(found) == 1, found
    assert "the file on disk is `Docs/Guide.md`" in found[0].detail, found[0].detail
    assert "does not exist" not in found[0].detail, found[0].detail


def test_a_reference_may_not_climb_above_the_repository_root(
        git_repo, tmp_path) -> None:
    """The last of the three ways a reference could leave the repository.

    PHASE 6's audit found three: an absolute path, a drive letter, and the `..`
    walk. The first two were closed by the absolute branch above; this is the
    third. `base / "../../x.md"` was answered by whatever else happened to sit
    on the machine, which is the same "true where you are standing is not true"
    the tool exists to catch.

    A real file is planted OUTSIDE the repository, because a bound tested only
    against a path where nothing exists would pass just as well with no bound
    at all - `_actual_case` returns None for a missing file either way.

    MEASURED before it was applied: over 176 repositories and 77,879 relative
    references, 12 climb above the root and NOT ONE of them resolves, so this
    removes no finding. The number that mattered was the other one - both
    behaviours were run over all 77,879 and ZERO verdicts changed, which is
    what says the depth arithmetic is right.
    """
    from extant import session as hc
    from extant.sites import resolve_reference
    repo, commit = git_repo
    commit("docs/guide.md", "x\n", "chore: init")
    commit("README.md", "x\n", "chore: readme")

    outside = repo.parent / "outside-the-repo.md"
    outside.write_text("secret\n", encoding="utf-8")
    assert outside.is_file(), "the probe file must exist for this to mean anything"

    hc._SCOPE = hc.RunScope()
    ctx = hc.context(repo)

    # From the repository root, one `..` already leaves it.
    assert resolve_reference(ctx, repo, "../outside-the-repo.md") == (False, None)
    # From a subdirectory it takes two, and the first one is legitimate.
    assert resolve_reference(
        ctx, repo / "docs", "../../outside-the-repo.md") == (False, None)


def test_an_ordinary_dot_dot_reference_still_resolves(git_repo) -> None:
    """The blast radius, which is the whole reason the bound was measured.

    Getting the base-versus-repo depth wrong turns every `../README.md` written
    in a subdirectory into a false positive - and a false positive is the
    failure that gets this validator switched off. This is the other half of
    the pair above and must stay green whatever happens to the bound.
    """
    from extant import session as hc
    from extant.sites import _depth_below, resolve_reference
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    commit("docs/deep/guide.md", "x\n", "chore: deep")
    hc._SCOPE = hc.RunScope()
    ctx = hc.context(repo)

    assert resolve_reference(ctx, repo / "docs", "../README.md") == (True, None)
    assert resolve_reference(
        ctx, repo / "docs" / "deep", "../../README.md") == (True, None)
    # A `..` that cancels a segment stays inside and must survive too.
    assert resolve_reference(
        ctx, repo / "docs", "../docs/deep/guide.md") == (True, None)

    # None, not 0, when the base is not below the repository at all. Answering
    # 0 would refuse every `..` for `--validate` on a file outside the repo,
    # trading a machine-dependence for a false positive.
    assert _depth_below(repo, repo) == 0
    assert _depth_below(repo, repo / "docs" / "deep") == 2
    assert _depth_below(repo, repo.parent) is None
