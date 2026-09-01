"""A denominator may not count a site its rule refuses to judge.

The suite already has the OTHER direction well covered: a finding reported
against a denominator of zero, which prints as a rule speaking and being
listed among those that never looked. `tests/test_fuzz_findings.py` holds
three of those.

This file holds the quiet direction, and the project's own fixes call it the
worse one. `_fragment_sites` in the anchor rule and `_floor_claims` in the
manifest rule both say so in as many words: a denominator that includes sites
the rule cannot decide "reports coverage that does not exist", and it does it
on a run with no findings at all - which nobody investigates. The reassuring
answer, in the tool built to refuse it.

Structural enforcement of the same property lives in
`tests/test_module_quality.py::test_no_rule_counts_what_it_will_not_judge`,
which is what stops the class coming back in a rule nobody wrote a case for
here. These are the behavioural cases: what the number actually is.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import _install_into                        # noqa: E402

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _sweep(repo: Path, *extra: str):
    """Drive the real entry point, from the repository under test.

    INSTALLED as `tools/` rather than run out of this source tree, because
    configuration is discovered relative to the SCRIPT: run from here against a
    temporary repository it reads EXTANT's own `.extant.toml`, and
    `release_claims_name_our_tags = true` there would decide a case these tests
    mean to exercise against the defaults.
    """
    tool = _install_into(repo) / "extant_collect.py"
    return subprocess.run(
        [sys.executable, str(tool), "--sweep", *extra, "--repo", str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def _examined(repo: Path) -> dict:
    """The per-rule denominators out of a SARIF run, wherever they are."""
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)
    run = doc["runs"][0]
    return (run.get("properties", {}).get("examined")
            or (run.get("invocations") or [{}])[0]
            .get("properties", {}).get("examined"))


def _found(repo: Path, kind: str) -> list:
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)
    return [r for r in doc["runs"][0]["results"] if r["ruleId"] == kind]


# --- dead-md-link: a second scan of the document -------------------------


def test_links_the_rule_never_judges_are_not_counted_as_examined(
        git_repo) -> None:
    """`examined` scanned the document itself instead of reading the scanner.

    `check` refuses both of these unconditionally, in every repository: `@`
    opens a Documenter.jl macro rather than a path, and a `.html` target is a
    rendered page that resolves to no checked-in file - measured at 407 across
    two corpora, none of which existed. `examined` counted every non-external,
    non-anchor link regardless, so a document made only of them printed
    "dead-md-link 2" beside no findings, which reads as two links examined and
    clean. Zero were examined. JuliaLang/julia carries 1,779 `@ref` links.

    Catches a denominator that scans the document a second time.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# S\n\nA cross reference [to a symbol](@ref).\n\n"
           "A rendered page [the guide](guides/intro.html).\n",
           "docs: two links this rule never judges")

    assert _found(repo, "dead-md-link") == []
    assert _examined(repo)["dead-md-link"] == 0, _examined(repo)


def test_a_link_the_rule_does_judge_is_still_counted(git_repo) -> None:
    """The guard on the case above, because narrowing can empty a count.

    A resolvable link is examined and clean and must still be counted; a dead
    one is examined and reported. Both are sites the rule decides.
    """
    repo, commit = git_repo
    commit("docs/note.md", "# Note\n", "docs: a real file")
    commit("NEXT_SESSION.md",
           "# S\n\nSee [here](docs/note.md) and [gone](docs/absent.md).\n",
           "docs: one link that resolves and one that does not")

    assert len(_found(repo, "dead-md-link")) == 1
    assert _examined(repo)["dead-md-link"] == 2, _examined(repo)


# --- stale-live-claim: a gate the denominator did not read ---------------


def _entry(body: str) -> str:
    return f"# Status\n\n## Phase 1 - The work (shipped, 2026-09-01)\n\n{body}\n"


def test_an_entry_making_no_live_claim_examines_no_live_claims(
        git_repo) -> None:
    """The rule returns before reading a single token, and counted them anyway.

    `check` requires a live phrase in the newest entry and gives up on the
    whole entry when there is none - so on a document like this it inspects
    zero branch tokens. `examined` counted them regardless and its docstring
    defended that as "candidates this rule looked at and passed over", which
    is not what the control flow does: it never reaches the loop.

    The output said `stale-live-claim 1` beside no findings, which reads as
    one live claim examined and sound. There was no live claim to examine.

    `unknown-branch` reads the same entry with no such gate, so it really does
    examine the token - and the two rules reporting DIFFERENT numbers here is
    the point, not a discrepancy. Same document, different questions.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           _entry("The work landed on `claude/some-work`, which is done."),
           "docs: an entry naming a branch and claiming nothing about it")
    subprocess.run(["git", "branch", "claude/some-work"], cwd=repo, check=True)

    examined = _examined(repo)
    assert examined["stale-live-claim"] == 0, examined
    assert examined["unknown-branch"] == 1, examined


def test_an_entry_that_does_make_a_live_claim_still_counts_it(
        git_repo) -> None:
    """The guard: the gate must narrow the count, not empty it.

    With a live phrase present the rule reads every branch token in the entry,
    so the denominator is the same population `unknown-branch` reports.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           _entry("`claude/some-work` is NOT yet merged."),
           "docs: an entry that does make a live claim")
    subprocess.run(["git", "branch", "claude/some-work"], cwd=repo, check=True)

    examined = _examined(repo)
    assert examined["stale-live-claim"] == 1, examined
    assert examined["unknown-branch"] == 1, examined


# --- false-merge-claim: a skip after the shared scanner -------------------


def test_a_merge_claim_on_a_sha_that_does_not_resolve_is_not_counted(
        git_repo) -> None:
    """`dead-sha` owns this claim, and the count said this rule read it too.

    The rule skips a claim whose commit does not resolve, deliberately and for
    a stated reason: reporting "not an ancestor of main" about a commit that
    does not exist is a confusing second finding. But `examined` counted every
    claim the PATTERN matched, so the skip never reached the denominator. On
    this project's own NEXT_SESSION.md that printed 5 where the rule could
    decide 3 - coverage claimed over two claims nothing looked at.

    Catches a denominator taken from the scanner rather than from the sites.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# S\n\nWork merged to `main` at `deadbeefcafe1234567`.\n",
           "docs: a merge claim on a commit that is not there")

    kinds = sorted(r["ruleId"] for r in _found(repo, "dead-sha")
                   + _found(repo, "false-merge-claim"))
    assert kinds == ["dead-sha"], kinds
    assert _examined(repo)["false-merge-claim"] == 0, _examined(repo)


def test_a_merge_claim_the_rule_can_settle_is_still_counted(git_repo) -> None:
    """The guard: a claim naming a real ref and a real commit is examined.

    True or false, this one the rule decides, so it must appear in the
    denominator. Here it is true - the commit is on `main` - which is the
    examined-and-clean case a narrowed count is likeliest to lose.
    """
    repo, commit = git_repo
    sha = commit("docs/note.md", "# Note\n", "docs: something to cite")
    commit("NEXT_SESSION.md",
           f"# S\n\nWork merged to `main` at `{sha[:12]}`.\n",
           "docs: a merge claim this repository can settle")

    assert _found(repo, "false-merge-claim") == []
    assert _examined(repo)["false-merge-claim"] == 1, _examined(repo)


# --- dead-release-tag: two skips after the shared scanner -----------------


def test_a_release_claim_this_project_does_not_own_is_not_counted(
        git_repo) -> None:
    """Off by default, and the count read as though it were on.

    `release_claims_name_our_tags` says every version this document names is
    one of OUR tags, so a version with no tag is a dead release. It is off by
    default and most projects leave it off, because a README naming a
    dependency's version is not a claim about this repository. With it off the
    rule cannot decide an unresolvable version at all - and counted it anyway,
    reporting coverage of a claim it declined to judge.

    Catches a denominator taken before the setting is read.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# S\n\nThe adapter shipped in `9.9.9`.\n",
           "docs: a version this repository has no tag for")

    assert _found(repo, "dead-release-tag") == []
    assert _examined(repo)["dead-release-tag"] == 0, _examined(repo)


def test_a_release_claim_backed_by_a_real_tag_is_still_counted(
        git_repo) -> None:
    """The guard: a version with a tag behind it is a claim the rule settles.

    The tag is on `main`, so this is the examined-and-clean case - the one a
    narrowed denominator is likeliest to lose, because nothing in the findings
    points at it.
    """
    repo, commit = git_repo
    commit("docs/note.md", "# Note\n", "docs: something to tag")
    subprocess.run(["git", "tag", "v1.2.3"], cwd=repo, check=True)
    commit("NEXT_SESSION.md", "# S\n\nThis work shipped in `1.2.3`.\n",
           "docs: a version this repository does tag")

    assert _found(repo, "dead-release-tag") == []
    assert _examined(repo)["dead-release-tag"] == 1, _examined(repo)


# --- dead-sha: the narrow skip, and the guard that it stays narrow --------


def test_a_changeset_entry_the_rule_steps_over_is_not_counted(
        git_repo) -> None:
    """A changesets repository mints these, and no author wrote them.

    `.changeset/` release notes open each line with the changeset id, which is
    hex and looks exactly like a short commit. The rule steps over such a line
    rather than reporting every release note as full of dead references - and
    counted it regardless, so the denominator claimed the token had been
    resolved when the rule never asked.

    Narrow, and it is the whole of this rule's overstatement: every other
    candidate here is judged.
    """
    repo, commit = git_repo
    commit(".changeset/config.json", '{"changelog": "@changesets/cli"}\n',
           "chore: this project mints release notes with changesets")
    commit("NEXT_SESSION.md",
           "# S\n\n- abc1234def56: Fixed the thing\n",
           "docs: a changeset entry, not a commit reference")

    # `bare-dead-sha` is the kind an un-backticked token reports under; the
    # rule's own kind, and so its denominator, is `dead-sha`.
    assert _found(repo, "bare-dead-sha") == []
    assert _examined(repo)["dead-sha"] == 0, _examined(repo)


def test_the_same_line_is_counted_and_reported_without_changesets(
        git_repo) -> None:
    """The control, and it is what makes the case above mean anything.

    Identical bytes in a repository that does NOT use changesets are a bare
    reference to a commit that does not resolve: examined, and reported. A
    denominator that dropped the token in both repositories would pass the
    assertion above while having stopped reading the shape entirely.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# S\n\n- abc1234def56: Fixed the thing\n",
           "docs: the same line, with no .changeset directory")

    assert len(_found(repo, "bare-dead-sha")) == 1
    assert _examined(repo)["dead-sha"] == 1, _examined(repo)
