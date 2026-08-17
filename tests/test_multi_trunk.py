"""Repositories with more than one integration branch.

Every test here was derived from a measurement against a real gitflow fixture
rather than from what gitflow is supposed to look like. The measurement found
two defects, and they pointed in opposite directions: with `trunk = main` a
FALSE claim about develop was never examined, and with `trunk = develop` a
genuinely shipped release tag was reported dead. Neither setting was correct,
so the fix was not a longer trunk list - it was to stop asking one configured
branch three different questions.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


def short(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--short", ref)


@pytest.fixture()
def gitflow(git_repo):
    """main and develop, a feature merged to develop AFTER the last release.

    That window is the whole problem: before a release, develop's history is
    already inside main via the release merge, so the two branches agree and
    nothing is exposed. A document describing active work talks about the
    commits that landed after it, which are on develop alone.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    git(repo, "branch", "develop")

    git(repo, "checkout", "-q", "develop")
    git(repo, "checkout", "-q", "-b", "release/1.0.0")
    commit("VERSION", "1.0.0\n", "chore: bump")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge: release 1.0.0", "release/1.0.0")
    git(repo, "tag", "v1.0.0")
    on_main = short(repo, "main")
    git(repo, "checkout", "-q", "develop")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge: release back", "release/1.0.0")

    git(repo, "checkout", "-q", "-b", "feature/search")
    commit("search.py", "s = 1\n", "feat: search")
    git(repo, "checkout", "-q", "develop")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge: search", "feature/search")
    on_develop = short(repo, "develop")

    git(repo, "checkout", "-q", "-b", "feature/payments")
    commit("pay.py", "p = 1\n", "feat: wip")
    unmerged = short(repo, "HEAD")
    git(repo, "checkout", "-q", "develop")
    return repo, on_main, on_develop, unmerged


def test_a_false_claim_about_a_non_trunk_branch_is_caught(gitflow) -> None:
    """The defect this whole change exists for.

    `on_main` is not an ancestor of develop, so "merged to `develop` at
    <on_main>" is false. The old rule interpolated the configured trunk into
    its pattern, so with trunk=main this line did not match at all: the claim
    was not judged wrong, it was never examined. A wrong implementation that
    still compares against the configured trunk reports nothing here.
    """
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, on_main, _on_develop, _unmerged = gitflow

    findings = rule_merge.check(ec.context(repo), f"Merged to `develop` at `{on_main}`.\n")

    assert [f.kind for f in findings] == ["false-merge-claim"], findings
    assert "develop" in findings[0].detail


def test_a_true_claim_about_a_non_trunk_branch_is_silent(gitflow) -> None:
    """The other direction, which is what stops the fix above from being a
    rule that simply flags everything it did not used to see."""
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, _on_main, on_develop, _unmerged = gitflow

    assert rule_merge.check(ec.context(repo), f"Merged to `develop` at `{on_develop}`.\n") == []


def test_both_directions_are_checked_in_one_pass(gitflow) -> None:
    """A document naming both branches. Measured on the fixture, either trunk
    setting caught exactly one of these two and was blind to the other."""
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, on_main, on_develop, _unmerged = gitflow

    findings = rule_merge.check(
        ec.context(repo),
        f"Merged to `develop` at `{on_main}`.\n"
        f"Merged to `main` at `{on_develop}`.\n"
    )

    assert len(findings) == 2, [f.detail for f in findings]
    assert {f.line for f in findings} == {1, 2}


def test_prose_after_merged_to_is_not_read_as_a_branch(gitflow) -> None:
    """The cost of letting the claim name its own ref is that the pattern no
    longer anchors on a known branch name, so an unbacticked word sitting where
    a branch would go must not be reported as a missing branch.

    The first version of this test used "merged to the release branch at
    `sha`", which proved nothing: the pattern requires ` at ` to follow the
    word directly, so it never matched and the guard was never reached. A
    mutation campaign removed the guard entirely and this test stayed green.
    `production` is the shape that actually reaches it - one bare word, in
    exactly the right place, that is not a branch here.
    """
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, _on_main, on_develop, unmerged = gitflow

    # Reaches the guard: the pattern matches and `production` does not resolve.
    assert rule_merge.check(
        ec.context(repo), f"Merged to production at `{unmerged}`.\n") == []
    assert rule_merge.check(
        ec.context(repo), f"Merged to the release branch at `{on_develop}`.\n") == []


def test_a_bare_word_that_IS_a_branch_is_still_checked(gitflow) -> None:
    """Ignoring unbackticked words must not become ignoring unbackticked
    CLAIMS. Plenty of documents write the branch name plain, and dropping those
    would trade a false positive for exactly the blindness this change removes.
    """
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, on_main, _on_develop, _unmerged = gitflow

    findings = rule_merge.check(ec.context(repo), f"Merged to develop at `{on_main}`.\n")

    assert [f.kind for f in findings] == ["false-merge-claim"], findings


def test_a_backticked_branch_that_never_existed_is_reported(gitflow) -> None:
    """A typo must not become a way to make a claim unverifiable AND silent.

    The commit here is on no integration branch, so the claim is false in
    substance as well as misspelt.
    """
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, _on_main, _on_develop, unmerged = gitflow

    findings = rule_merge.check(ec.context(repo), f"Merged to `devlop` at `{unmerged}`.\n")

    assert [f.kind for f in findings] == ["false-merge-claim"], findings
    assert "no such branch" in findings[0].detail


def test_a_deleted_branch_whose_work_landed_is_not_accused(gitflow) -> None:
    """Gitflow deletes every release branch on merge, and a squash merge or a
    custom `-m` erases the name from history entirely. Reporting those as
    invented produced a false positive on the fixture. The rule asks the
    substantive question instead: did this work land anywhere?
    """
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, on_main, _on_develop, _unmerged = gitflow
    git(repo, "branch", "-D", "release/1.0.0")

    assert rule_merge.check(ec.context(repo), f"Merged to `release/1.0.0` at `{on_main}`.\n") == []


def test_a_deleted_branch_whose_work_never_landed_still_fires(gitflow) -> None:
    """The other half of the case above. Silence there must come from the
    commit being integrated, not from the branch being missing - otherwise
    deleting a branch would launder every claim that named it."""
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, _on_main, _on_develop, unmerged = gitflow
    git(repo, "branch", "-D", "release/1.0.0")

    findings = rule_merge.check(ec.context(repo), f"Merged to `release/1.0.0` at `{unmerged}`.\n")

    assert [f.kind for f in findings] == ["false-merge-claim"], findings


def test_a_shipped_tag_is_not_reported_dead_from_the_other_trunk(gitflow) -> None:
    """The measured false positive.

    `v1.0.0` sits on main's release merge. develop received the release BRANCH
    back, not that commit, so the tag is not an ancestor of develop - and with
    trunk=develop the old rule called a genuinely shipped release dead. An
    implementation that still asks about one configured trunk fails here.

    Set through `reload_config`, not `monkeypatch.setattr(ec, "TRUNK", ...)`.
    The latter only reaches this module's own globals; `_integration_refs` is a
    package function reading `ctx.config.trunk` off the built Config, which a
    monkeypatched module attribute never touches. That is exactly why the old
    form of this test passed even when a review plugin skipped the patch
    entirely - the module-level TRUNK it set was never read on this path.
    Proven by mutation: temporarily reducing `integration_refs` in
    extant/refs.py to `return [ctx.config.trunk]` (dropping the
    `_INTEGRATION_NAMES` scan) turns this test red with a genuine trunk=develop
    applied, and green again once reverted.
    """
    from extant import session as ec
    from extant.rules import release_tag as rule_release_tag
    repo, _on_main, _on_develop, _unmerged = gitflow

    saved_config, saved_active = ec.CONFIG, ec._ACTIVE
    saved = {name: getattr(ec, name) for name in ec._CONFIG_DERIVED}
    (repo / ".extant.toml").write_text('trunk = "develop"\n', encoding="utf-8")
    try:
        ec.reload_config(repo)
        assert ec.TRUNK == "develop", "reload_config did not apply trunk"

        assert rule_release_tag.check(ec.context(repo), "Released in v1.0.0 last week.\n") == []
    finally:
        ec.CONFIG, ec._ACTIVE = saved_config, saved_active
        for name, value in saved.items():
            setattr(ec, name, value)


def test_a_live_claim_about_work_merged_to_develop_is_flagged(gitflow) -> None:
    """With trunk=main, `feature/search` is not an ancestor of main, so the old
    rule accepted "not yet merged" about work that shipped to develop weeks
    ago. Merged means landed on an integration branch, not on one of them.

    trunk=main is the deliberate choice, not a placeholder - it is also the
    value `neutral_config` already leaves in place, so this alone cannot prove
    configuration is read at all. What it pins is `develop` staying in the
    integration set regardless of which branch is configured as trunk (see
    `integration_refs` in extant/refs.py): the OLD single-trunk rule missed
    this claim precisely when trunk=main, which is why that is the value
    written here rather than trunk=develop. Routed through `reload_config`
    rather than `monkeypatch.setattr(ec, "TRUNK", ...)` for the same reason as
    the test above: the latter never reaches `ctx.config.trunk`.
    """
    from extant import session as ec
    from extant.rules import live_claim as rule_live_claim
    repo, _on_main, _on_develop, _unmerged = gitflow

    saved_config, saved_active = ec.CONFIG, ec._ACTIVE
    saved = {name: getattr(ec, name) for name in ec._CONFIG_DERIVED}
    (repo / ".extant.toml").write_text('trunk = "main"\n', encoding="utf-8")
    try:
        ec.reload_config(repo)
        assert ec.TRUNK == "main", "reload_config did not apply trunk"

        text = ("# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
                "Work is NOT yet merged on `feature/search`.\n\n## 1. Ref\n")

        findings = rule_live_claim.check(ec.context(repo), text)

        assert [f.kind for f in findings] == ["stale-live-claim"], findings
        assert "develop" in findings[0].detail
    finally:
        ec.CONFIG, ec._ACTIVE = saved_config, saved_active
        for name, value in saved.items():
            setattr(ec, name, value)


def test_an_unmerged_feature_is_still_reported_as_open(gitflow) -> None:
    """The false positive the test above could easily buy. `feature/payments`
    is on nothing, and widening what counts as merged must not make every live
    claim stale."""
    from extant import session as ec
    from extant.rules import live_claim as rule_live_claim
    repo, _on_main, _on_develop, _unmerged = gitflow
    text = ("# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
            "Work is NOT yet merged on `feature/payments`.\n\n## 1. Ref\n")

    assert rule_live_claim.check(ec.context(repo), text) == []


def test_an_integration_branch_is_not_merged_into_itself(gitflow, reconfigure) -> None:
    """`develop` is trivially an ancestor of `develop`, so without excluding the
    branch under test every live claim about an integration branch reports as
    already merged. Reachable only with a `branch_token` that matches slashless
    names, which is a configuration choice several projects make, and a
    mutation campaign confirmed nothing else pinned it.

    No trunk override any more (there used to be one,
    `monkeypatch.setattr(ec, "TRUNK", "main")`). `_integrated_by`'s `exclude`
    argument drops `develop` from the candidate set before ancestry is even
    asked, so whichever branch is configured as trunk cannot move the answer -
    checked against trunk="main" (the default), trunk="develop", and a trunk
    that resolves to nothing at all, every one leaves the result at `["main"]`
    after exclusion. A patch that cannot move the outcome under any value pins
    nothing: a review plugin that skipped it left this test green too.
    """
    import re

    from extant import session as ec
    from extant.rules import live_claim as rule_live_claim
    repo, _on_main, _on_develop, _unmerged = gitflow
    reconfigure(branch_token=re.compile(r"`([\w.\-/]+)`"))
    text = ("# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
            "Work is NOT yet merged on `develop`.\n\n## 1. Ref\n")

    # develop genuinely has not reached main here, so the claim is true.
    assert rule_live_claim.check(ec.context(repo), text) == []


def test_integration_refs_ignore_unconventional_branches(gitflow) -> None:
    """An earlier version treated any slashless branch as an integration
    branch, which silently reclassified `gh-pages`, `experiment` and every
    abandoned spike. A tag cut on one of those would then count as shipped."""
    from extant import session as ec
    from extant import refs
    repo, _on_main, _on_develop, _unmerged = gitflow
    git(repo, "branch", "gh-pages")
    git(repo, "branch", "experiment")

    refs = refs.integration_refs(ec.context(repo))

    assert "develop" in refs and "main" in refs
    assert "gh-pages" not in refs and "experiment" not in refs


def test_a_one_group_custom_pattern_keeps_the_old_meaning(gitflow) -> None:
    """Back-compat. A project that customised `merge_claim` before claims
    became self-describing wrote one group, the sha, and meant trunk. Breaking
    those configs would turn a working rule into one that matches nothing.

    Unlike the trunk tests above, this one genuinely needs TRUNK to be right:
    the one-group fallback (`claims.append((number, config.trunk,
    match.group(1)))`) is what supplies the ref the claim does not name.

    BOTH values now go through `reload_config`, and the second one had to.
    `_merge_claims` moved to extant/commits.py in Task 9 and reads
    `config.merge_claim` off the built Config, so the plain `ec._MERGE_CLAIM =
    ...` assignment this used to make no longer reaches it - the rule matched
    nothing and the test reported no findings, which is the exact trap the
    shim's own wrapper block warns would arrive when the rules moved. Writing
    the pattern into `.extant.toml` reaches the Config and the module global
    together, which is the only arrangement in which the two cannot disagree.
    The pattern is a LITERAL string (single quotes) because TOML processes
    escapes in basic strings and would reject the backslashes. Proven by
    mutation: temporarily changing that append to a fixed wrong ref instead of
    `config.trunk` turns this test red, and reverting turns it green.
    """
    from extant import session as ec
    from extant.rules import merge as rule_merge
    repo, on_main, on_develop, _unmerged = gitflow

    saved_config, saved_active = ec.CONFIG, ec._ACTIVE
    saved = {name: getattr(ec, name) for name in ec._CONFIG_DERIVED}
    (repo / ".extant.toml").write_text(
        'trunk = "main"\nmerge_claim = \'landed at `([0-9a-f]{7,40})`\'\n',
        encoding="utf-8")
    try:
        ec.reload_config(repo)
        assert ec.TRUNK == "main", "reload_config did not apply trunk"
        assert ec._ACTIVE.merge_claim.groups == 1, (
            "the one-group pattern did not reach the built Config, so this "
            "test would exercise the default two-group contract instead")

        assert rule_merge.check(ec.context(repo), f"landed at `{on_main}`.\n") == []
        findings = rule_merge.check(ec.context(repo), f"landed at `{on_develop}`.\n")
        assert [f.kind for f in findings] == ["false-merge-claim"], findings
    finally:
        ec.CONFIG, ec._ACTIVE = saved_config, saved_active
        for name, value in saved.items():
            setattr(ec, name, value)


def test_the_ancestry_cache_does_not_leak_between_repositories(git_repo, tmp_path) -> None:
    """Two repositories, both with a branch called `main`.

    The first version keyed the index by ref name alone. Rules are also called
    directly, without validate() resetting anything, so the second repository
    was answered from the first one's history and a TRUE merge claim came back
    false. Caught by the existing suite, and pinned here so it stays caught.
    """
    from extant import session as ec
    from extant.rules import merge as rule_merge
    first, commit = git_repo
    first_sha = commit("a.py", "a = 1\n", "feat: a")[:9]

    second = tmp_path / "second"
    second.mkdir()
    git(second, "init", "-b", "main")
    git(second, "config", "user.email", "t@t")
    git(second, "config", "user.name", "T")
    (second / "b.py").write_text("b = 1\n", encoding="utf-8")
    git(second, "add", "-A")
    git(second, "commit", "-m", "feat: b")
    second_sha = short(second, "HEAD")

    assert rule_merge.check(ec.context(first), f"Merged to `main` at `{first_sha}`.\n") == []
    assert rule_merge.check(ec.context(second), f"Merged to `main` at `{second_sha}`.\n") == [], (
        "the second repository was answered from the first one's index"
    )
