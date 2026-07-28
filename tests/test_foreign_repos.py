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
