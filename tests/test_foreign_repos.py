"""False-positive classes found by sweeping nine real repositories.

Everything here was measured, not imagined. Before these fixes the corpus -
flask, requests, httpx, rust-lang/rfcs, express, cobra, helm, vite and
prometheus - produced 727 findings, of which roughly nine in ten were false.
After them it produces 66, and the true positives below still fire.

That gap matters more than any single rule. The project's central claim is that
a validator which cries wolf stops being read, and until this corpus existed
that claim had only ever been checked against this repository and one sibling
project, neither of which links to another project's source.

Each test names the repository that exposed the class.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _findings(repo: Path, text: str) -> list[str]:
    import extant_collect as hc
    return [f"{f.kind}:{f.detail}" for f in hc.validate(repo, text, has_entries=False)]


def _kinds(repo: Path, text: str) -> list[str]:
    import extant_collect as hc
    return [f.kind for f in hc.validate(repo, text, has_entries=False)]


# --- hex that belongs to somebody else ---------------------------------------

def test_a_sha_inside_a_url_is_not_this_repos_problem(git_repo) -> None:
    """psf/requests and rust-lang/rfcs. The single biggest false class.

    A permalink into ANOTHER repository carries a 40-hex token that this repo's
    git has never heard of, and never should. 287 of 301 bare-SHA findings
    across the corpus sat inside a URL; left in, the rule fires on every
    project that links to another project's source, which is most of them.

    A wrong implementation that scans the whole line reports both of these.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = (
        "See https://github.com/pyca/service-identity/blob/"
        "fa91bf55cfda64145aa3d202cc84059befb98af4/.github/AI_POLICY.md\n"
        "And https://gist.github.com/florimondmanca/"
        "d56764d78d748eb9f73165da388e546e\n"
    )

    assert not [k for k in _kinds(repo, text) if "sha" in k], _findings(repo, text)


def test_a_bare_sha_outside_a_url_is_still_reported(git_repo) -> None:
    """The other half, or the fix above would be indistinguishable from
    deleting the rule. rust-lang/rfcs writes these in running prose."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "Regression report c85ba3e9cb4620c6ec8273a34cce6707e91778cb vs main.\n"

    assert [k for k in _kinds(repo, text) if "sha" in k], (
        "a bare dead SHA in prose must still be caught"
    )


def test_a_css_colour_is_not_a_commit(git_repo) -> None:
    """vitejs/vite. `#646cffaa` is eight hex digits with an alpha channel,
    written in prose no code fence covers. A `#` prefix means colour."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "<span style='filter: drop-shadow(0 0 0.5em #646cffaa)'>hi</span>\n"

    assert not [k for k in _kinds(repo, text) if "sha" in k], _findings(repo, text)


# --- links ---------------------------------------------------------------

def test_a_root_relative_link_resolves_from_the_repository_root(git_repo) -> None:
    """psf/requests. A leading slash is how GitHub renders repo-root links.

    Resolved against the DOCUMENT instead, the rule called
    `/.github/AI_POLICY.md` dead while the file sat right there.
    """
    repo, commit = git_repo
    commit(".github/AI_POLICY.md", "# policy\n", "chore: policy")
    commit("docs/CONTRIBUTING.md", "x\n", "chore: contributing")
    text = "See our [AI Policy](/.github/AI_POLICY.md).\n"

    assert "dead-md-link" not in _kinds(repo, text), _findings(repo, text)


def test_a_root_relative_link_to_nothing_is_still_reported(git_repo) -> None:
    """In a plain repository, so the fix above cannot become a blanket skip."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "See [gone](/.github/NOT_THERE.md).\n"

    assert "dead-md-link" in _kinds(repo, text), (
        "a root-relative link to a file that does not exist is still dead"
    )


def test_site_routes_are_not_judged_in_a_generated_docs_tree(git_repo) -> None:
    """vitejs/vite (331 of these) and encode/httpx.

    A markdown tree compiled into a website links by ROUTE, not by path.
    `/guide/features.html` and `../advanced/transports` are correct links on
    the rendered site and are not files anywhere, so the filesystem cannot
    settle them and the guarantee says they must not be judged.

    Keyed on a generator config existing, which is measured: the three corpus
    repositories shipping one produced every route-shaped false positive, and
    the six without produced none.
    """
    repo, commit = git_repo
    commit("mkdocs.yml", "site_name: demo\n", "chore: mkdocs")
    commit("docs/index.md", "x\n", "chore: docs")
    text = ("[a](/guide/features.html)\n[b](../advanced/transports)\n"
            "[c](/team)\n")

    assert "dead-md-link" not in _kinds(repo, text), _findings(repo, text)


def test_the_same_links_are_judged_in_a_plain_repository(git_repo) -> None:
    """No generator config, so these are ordinary paths and ordinary rot.

    Without this, the site rule could widen to every repository and silently
    switch the link check off everywhere.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "[b](../advanced/transports)\n"

    assert "dead-md-link" in _kinds(repo, text), _findings(repo, text)


# --- anchors -------------------------------------------------------------

def test_both_heading_slug_conventions_are_accepted(git_repo) -> None:
    """vitejs/vite. Renderers disagree and both spellings are correct.

    GitHub drops a dot, so `## build.target` offers `#buildtarget`; VitePress
    turns it into a dash, so the same heading offers `#build-target`. Following
    one rule reported ten dead anchors in a site with none.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "## build.target\n\nSee [it](#build-target) and [it](#buildtarget).\n"

    assert "dead-md-anchor" not in _kinds(repo, text), _findings(repo, text)


def test_an_anchor_matching_no_heading_is_still_dead(git_repo) -> None:
    """encode/httpx had three real ones, and they must survive the change
    above. `#routing` matches no heading under either convention."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "## Proxy mechanisms\n\nSee the [Routing](#routing) section.\n"

    assert "dead-md-anchor" in _kinds(repo, text), _findings(repo, text)


# --- what gets swept -----------------------------------------------------

def test_the_sweep_reads_the_commit_not_the_index(git_repo) -> None:
    """helm, cloned on Windows where MAX_PATH truncated the checkout.

    `ls-files` reads the INDEX, which is empty after an incomplete checkout -
    a sparse checkout, a partial clone, or a path-length failure. It reported
    0 markdown files while HEAD's tree held 96, and a sweep printed a clean
    all-clear for a repository nothing had looked at.

    This project already fixed exactly this once, for raw-lfs-blob reading the
    index instead of HEAD's tree. It came back in a new rule.
    """
    import extant_collect as hc

    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "chore: plan")
    commit("README.md", "# readme\n", "chore: readme")

    # Empty the index without touching the commit, which is the state a failed
    # checkout leaves behind.
    subprocess.run(["git", "read-tree", "--empty"], cwd=repo, check=True,
                   capture_output=True)
    assert subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                          text=True).stdout.strip() == "", (
        "the index was not emptied, so this test proves nothing"
    )

    found = hc.tracked_markdown(repo)

    assert sorted(found) == ["README.md", "docs/plan.md"], (
        f"HEAD's tree holds both files; got {found}"
    )


# --- cross-file anchors ---------------------------------------------------

def test_a_fragment_on_another_file_is_checked(git_repo) -> None:
    """encode/httpx and prometheus. A heading renamed, inbound links left.

    All three httpx cases are that same rot: the link asks for
    `#customizing-authentication` while the heading reads "Custom
    authentication schemes". Measured across nine repositories, 96 cross-file
    anchors resolve to a real markdown file and 7 name a heading that is not
    there.
    """
    repo, commit = git_repo
    commit("docs/auth.md", "# Auth\n\n## Custom authentication schemes\n", "chore: auth")
    commit("docs/index.md", "x\n", "chore: index")
    text = "See [auth](auth.md#customizing-authentication).\n"

    import extant_collect as hc
    hc._LINK_BASE = repo / "docs"
    try:
        kinds = [f.kind for f in hc.validate(repo, text, has_entries=False)]
    finally:
        hc._LINK_BASE = None
    assert "dead-md-anchor" in kinds, kinds


def test_a_fragment_that_does_exist_elsewhere_is_left_alone(git_repo) -> None:
    """Or the rule above would be indistinguishable from always firing."""
    repo, commit = git_repo
    commit("docs/auth.md", "# Auth\n\n## Custom authentication schemes\n", "chore: auth")
    commit("docs/index.md", "x\n", "chore: index")
    text = "See [auth](auth.md#custom-authentication-schemes).\n"

    import extant_collect as hc
    hc._LINK_BASE = repo / "docs"
    try:
        kinds = [f.kind for f in hc.validate(repo, text, has_entries=False)]
    finally:
        hc._LINK_BASE = None
    assert "dead-md-anchor" not in kinds, kinds


def test_a_fragment_on_a_file_that_is_missing_is_not_this_rules_finding(git_repo) -> None:
    """`dead-md-link` already reports the missing file. Reporting it twice, once
    per rule, would double-count every broken link in a document."""
    repo, commit = git_repo
    commit("docs/index.md", "x\n", "chore: index")
    text = "See [gone](nowhere.md#whatever).\n"

    import extant_collect as hc
    hc._LINK_BASE = repo / "docs"
    try:
        kinds = [f.kind for f in hc.validate(repo, text, has_entries=False)]
    finally:
        hc._LINK_BASE = None
    assert "dead-md-link" in kinds, kinds
    assert "dead-md-anchor" not in kinds, f"double-counted: {kinds}"


def test_angle_bracket_headings_keep_their_anchor(git_repo) -> None:
    """prometheus. `### `<relabel_config>`` is a YAML placeholder, not markup.

    Stripping angle brackets unconditionally to fix vite's component tags
    deleted this heading entirely and turned fifty working links into
    findings. Both spellings are offered now, so both projects are right.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ("## `<relabel_config>`\n\n## resolve.conditions <NonInheritBadge />\n\n"
            "See [a](#relabel_config) and [b](#resolve-conditions).\n")

    assert "dead-md-anchor" not in _kinds(repo, text), _findings(repo, text)


# --- classes found in the second sweep, ten ecosystems --------------------

def test_any_uri_scheme_counts_as_external(git_repo) -> None:
    """phoenixframework/phoenix links to `irc://irc.libera.chat/elixir`.

    The scheme list was enumerated - http, mailto, ftp, tel, data - and an
    enumerated list is always missing the next one somebody uses.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ("[irc](irc://irc.libera.chat/elixir)\n[ssh](ssh://git@host/repo)\n"
            "[vs](vscode://file/x)\n")

    assert "dead-md-link" not in _kinds(repo, text), _findings(repo, text)


def test_a_percent_encoded_path_resolves(git_repo) -> None:
    """nlohmann/json documents `operator[]` and links to
    `operator%5B%5D.md`, which is the same file spelled for a browser."""
    repo, commit = git_repo
    commit("docs/operator[].md", "# op\n", "chore: op")
    commit("docs/index.md", "x\n", "chore: index")

    import extant_collect as hc
    hc._LINK_BASE = repo / "docs"
    try:
        kinds = [f.kind for f in hc.validate(
            repo, "See [op](operator%5B%5D.md).\n", has_entries=False)]
    finally:
        hc._LINK_BASE = None
    assert "dead-md-link" not in kinds, kinds


def test_spaces_do_not_collapse_in_a_slug(git_repo) -> None:
    """nlohmann/json's own README. `### Serialization / Deserialization`
    drops the slash and keeps both spaces, so GitHub's anchor carries two
    dashes. Collapsing the run produced one and called the link dead."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ("### Serialization / Deserialization\n\n"
            "See [it](#serialization--deserialization).\n")

    assert "dead-md-anchor" not in _kinds(repo, text), _findings(repo, text)


def test_a_generator_configured_inside_another_file_is_detected(git_repo) -> None:
    """Elixir declares ExDoc in mix.exs rather than in a config of its own.

    phoenix links to `Mix.Tasks.Phx.Gen.Auth.html`, which ExDoc generates:
    104 findings, every one a link that works on hexdocs.
    """
    repo, commit = git_repo
    commit("mix.exs", 'defp deps do\n  [{:ex_doc, "~> 0.38", only: :docs}]\nend\n',
           "chore: mix")
    commit("guides/a.md", "x\n", "chore: guide")

    import extant_collect as hc
    hc._LINK_BASE = repo / "guides"
    try:
        kinds = [f.kind for f in hc.validate(
            repo, "See [gen](Mix.Tasks.Phx.Gen.Auth.html).\n", has_entries=False)]
    finally:
        hc._LINK_BASE = None
    assert "dead-md-link" not in kinds, kinds


def test_an_all_digit_run_is_a_number_not_a_commit(git_repo) -> None:
    """prometheus documents `9223372036854775807`, which is INT64_MAX.

    Measured over 1,924 markdown files in 17 repositories: of twelve
    backticked hex-shaped tokens, eight were all digits and every one was a
    number - a byte count, a Unix timestamp, an integer limit. Four had a
    letter and were commits.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "Limit is `9223372036854775807` and a page is `1048576` bytes.\n"

    assert not [k for k in _kinds(repo, text) if "sha" in k], _findings(repo, text)


def test_a_flattened_guide_resolves_by_unique_basename(git_repo) -> None:
    """phoenix links to `contexts.md` from `guides/authn_authz/`, and the file
    lives at `guides/data_modelling/contexts.md`. ExDoc flattens its guides
    into one namespace; a relative path does not.

    Only when the basename is unique, so this stays a filesystem fact rather
    than a guess about which of several candidates was meant.
    """
    repo, commit = git_repo
    commit("mix.exs", '{:ex_doc, "~> 0.38"}\n', "chore: mix")
    commit("guides/data_modelling/contexts.md", "# Contexts\n", "chore: contexts")
    commit("guides/authn_authz/auth.md", "x\n", "chore: auth")

    import extant_collect as hc
    hc._LINK_BASE = repo / "guides" / "authn_authz"
    try:
        kinds = [f.kind for f in hc.validate(
            repo, "See [contexts](contexts.md).\n", has_entries=False)]
    finally:
        hc._LINK_BASE = None
    assert "dead-md-link" not in kinds, kinds


def test_an_ambiguous_basename_is_not_guessed(git_repo) -> None:
    """Two files with the same name say nothing about which was meant, so the
    finding stands. Without this the rule above would be a blanket skip."""
    repo, commit = git_repo
    commit("mix.exs", '{:ex_doc, "~> 0.38"}\n', "chore: mix")
    commit("guides/a/index.md", "# one\n", "chore: one")
    commit("guides/b/index.md", "# two\n", "chore: two")
    commit("guides/c/page.md", "x\n", "chore: page")

    import extant_collect as hc
    hc._LINK_BASE = repo / "guides" / "c"
    try:
        kinds = [f.kind for f in hc.validate(
            repo, "See [it](index.md).\n", has_entries=False)]
    finally:
        hc._LINK_BASE = None
    assert "dead-md-link" in kinds, kinds


# --- third sweep: nine more repositories, sixteen ecosystems --------------

def test_output_survives_a_console_that_cannot_encode_it(tmp_path) -> None:
    """jgm/pandoc quotes Japanese, and the run died reporting it.

    A finding quotes the document, and a document may be in any language.
    Written to a cp1252 or cp437 console the process did not choose, an
    unencodable character raised UnicodeEncodeError AFTER the analysis - the
    worst possible moment.

    This was believed handled. The existing unicode test passes
    PYTHONIOENCODING=cp437:replace in the environment, so it proved the
    ENVIRONMENT copes, not the tool. Every mode crashed without it.
    """
    repo = tmp_path / "repo"
    (repo / "tools").mkdir(parents=True)
    for name in ("extant_collect.py", "extant_config.py"):
        shutil.copyfile(PAYLOAD / name, repo / "tools" / name)
    # Escaped, not literal: every shipped file here is ASCII so that output
    # cannot break a cp437 console, which is the same failure this test is
    # about, one layer up.
    japanese = chr(0x98EF) + chr(0x9928)   # a Japanese place name
    (repo / "README.md").write_text(f"# D\n\nSee [x](docs/{japanese}.md).\n",
                                    encoding="utf-8")
    (repo / ".extant.toml").write_text('primary_doc = "README.md"\n', encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "i"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    import os
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    for mode in (["--verify"], ["--sweep"], ["--validate", "README.md"]):
        result = subprocess.run(
            [sys.executable, str(repo / "tools" / "extant_collect.py"),
             "--repo", str(repo), *mode],
            cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env)
        assert "UnicodeEncodeError" not in result.stderr, (
            f"{mode} died encoding its own output:\n{result.stderr}")
        assert result.returncode == 1, (
            f"{mode} should report the dead link: {result.stdout}{result.stderr}")


def test_a_generator_macro_is_not_a_path(git_repo) -> None:
    """JuliaLang/julia. Documenter.jl writes `[text](@ref)` for a
    cross-reference, and 1,779 of them were reported as dead files - 96% of
    that repository's findings. An `@` opens a macro, not a path."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "See [Base.parse](@ref) and [other](@ref other_thing).\n"

    assert "dead-md-link" not in _kinds(repo, text), _findings(repo, text)


def test_a_heading_that_is_itself_a_link_slugs_to_its_text(git_repo) -> None:
    """Alamofire's changelog: `## [5.12.0](https://.../tag/5.12.0)`, indexed
    as `#5120`. A renderer slugs what the reader SEES and drops the
    destination; folding the URL in produced
    `1-0-0-https-github-com-alamofire-...` and called all 119 anchors dead."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ("## [5.12.0](https://github.com/Alamofire/Alamofire/releases/tag/5.12.0)\n\n"
            "- `5.12.x` Releases - [5.12.0](#5120)\n")

    assert "dead-md-anchor" not in _kinds(repo, text), _findings(repo, text)


def test_a_site_config_in_a_subdirectory_is_found(git_repo) -> None:
    """jekyll/jekyll keeps its own site under `docs/` with `docs/_config.yml`.

    A root-only search missed it and reported 138 of its site routes as dead
    files. The site is often a subdirectory of a project that is mostly
    something else.
    """
    repo, commit = git_repo
    commit("docs/_config.yml", "title: docs\n", "chore: jekyll")
    commit("docs/index.md", "x\n", "chore: index")

    import extant_collect as hc
    hc._SITE.clear()
    hc._LINK_BASE = repo / "docs"
    try:
        kinds = [f.kind for f in hc.validate(
            repo, "See [posts](/docs/posts/).\n", has_entries=False)]
    finally:
        hc._LINK_BASE = None
        hc._SITE.clear()
    assert "dead-md-link" not in kinds, kinds


# --- anchor sources a renderer offers that the source does not spell out ---

def test_a_definition_list_term_is_an_anchor(git_repo) -> None:
    """Hugo documents every configuration key as a definition term.

    A renderer supporting the extension gives each `<dt>` an id exactly as it
    gives one to a heading, so a term is an anchor source. 71 of hugoDocs' 101
    same-document findings were terms, and no other repository in a
    26-project corpus has a single one.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ("`titleCaseStyle`\n: (`string`) The capitalization rules.\n\n"
            "See [it](#titlecasestyle).\n")

    assert "dead-md-anchor" not in _kinds(repo, text), _findings(repo, text)


def test_a_colon_line_after_a_heading_is_not_a_definition_term(git_repo) -> None:
    """The exclusions matter, or every heading becomes an anchor twice over
    and a genuinely dead fragment could be forgiven by coincidence."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "## Real heading\n: not a term, the line above is a heading\n\nSee [x](#nonexistent).\n"

    assert "dead-md-anchor" in _kinds(repo, text), _findings(repo, text)


def test_a_repeated_slug_gets_the_numbered_suffix(git_repo) -> None:
    """Two headings reading the same thing cannot share an id, so a renderer
    numbers the later ones. Hugo's deployment page has a `matchers` term and a
    `## Matchers` section, and links to the second as `#matchers-1`."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "## Matchers\n\ntext\n\n## Matchers\n\nSee [second](#matchers-1).\n"

    assert "dead-md-anchor" not in _kinds(repo, text), _findings(repo, text)


def test_a_numbered_suffix_is_not_invented_for_a_unique_slug(git_repo) -> None:
    """Numbering starts at the SECOND occurrence. Offering `-1` for a slug
    that appears once would forgive an anchor that really is dead."""
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = "## Matchers\n\nSee [second](#matchers-1).\n"

    assert "dead-md-anchor" in _kinds(repo, text), _findings(repo, text)


def test_an_explicit_attribute_id_is_an_anchor(git_repo) -> None:
    """pandoc, kramdown and PHP Markdown Extra name a heading outright.

    `## Template {#type-template}` overrides whatever the text would slug to,
    so no amount of slug guessing reaches it. pandoc's doc/lua-filters.md
    carries 368 and they accounted for 120 of its 149 findings.
    """
    repo, commit = git_repo
    commit("README.md", "x\n", "chore: init")
    text = ("## Template {#type-template}\n\n### MetaMap {#pandoc.MetaMap}\n\n"
            "[Inlines]{#inlines-filter}\n\n"
            "See [a](#type-template), [b](#pandoc.metamap), [c](#inlines-filter).\n")

    assert "dead-md-anchor" not in _kinds(repo, text), _findings(repo, text)
