"""The rules added after the first release, and the selftest that probes them.

Each test names the wrong implementation it would catch. The false-positive
guards matter more than the positive cases here: the branch rule in particular
was nearly shipped in a form that produced four findings and four false
positives on the first corpus it was measured against.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "handoff"
TOOL = SKILL_ROOT / "payload" / "handoff_collect.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def run_tool(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), "--repo", str(repo), *args],
                          cwd=repo, capture_output=True, text=True, encoding="utf-8")


# --- markdown links ----------------------------------------------------------

def test_md_link_to_a_missing_file_is_flagged(git_repo) -> None:
    """Catches the gap that motivated this rule: a plain markdown link was
    invisible, because the path rule only sees backticked paths after an
    operative marker."""
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")

    findings = validate_md_links(repo, "See [the plan](docs/gone.md) for detail.\n")

    assert [f.kind for f in findings] == ["dead-md-link"]
    assert "docs/gone.md" in findings[0].detail


def test_md_link_to_an_existing_file_is_silent(git_repo) -> None:
    """The false-positive guard. A rule that flags working links is worse than
    no rule, because it trains people to ignore the output."""
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")

    assert validate_md_links(repo, "See [the plan](docs/plan.md).\n") == []


def test_external_links_are_never_checked(git_repo) -> None:
    """Catches a rule that reaches the network.

    Checking external links would make a green run depend on someone else's
    uptime and rate limits, turning a deterministic check into a coin flip.
    """
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = ("[docs](https://example.invalid/nope)\n"
            "[mail](mailto:nobody@example.invalid)\n")

    assert validate_md_links(repo, text) == []


def test_example_links_in_inline_code_are_ignored(git_repo) -> None:
    """The false positive this project's own README actually produced.

    The table row documenting this very rule contains a backticked example
    link, and the rule reported it as dead. Documentation ABOUT links is where
    example links live, so this is the predictable case rather than an exotic
    one, and it was found by running the rule against our own front page.
    """
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = "| `[a link](to/a/file.md)` whose file is gone | checks it |\n"

    assert validate_md_links(repo, text) == []


def test_a_real_link_beside_an_example_is_still_caught(git_repo) -> None:
    """The other half: stripping inline code must not swallow the whole line.

    Without this, the fix above could be 'ignore any line containing a
    backtick', which would blind the rule wherever prose mixes the two.
    """
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = "Example `[x](never-real.md)` but see [the plan](docs/gone.md).\n"

    findings = validate_md_links(repo, text)

    assert len(findings) == 1, [f.detail for f in findings]
    assert "docs/gone.md" in findings[0].detail
    assert "never-real.md" not in findings[0].detail


def test_links_inside_code_fences_are_ignored(git_repo) -> None:
    """A README demonstrating link syntax is showing an example, not making a
    promise. Catches a scanner that reads fenced blocks as prose."""
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = "Example:\n\n```markdown\n[label](docs/not-real.md)\n```\n"

    assert validate_md_links(repo, text) == []


# --- anchors -----------------------------------------------------------------

def test_anchor_matching_a_heading_is_silent(git_repo) -> None:
    """Catches a slug function that disagrees with how headings render.

    Punctuation and backticks are dropped and spaces become hyphens, so
    "## 1. Layout `here`" has to resolve for `#1-layout-here`.
    """
    from handoff_collect import validate_md_anchors
    repo, _ = git_repo

    text = "## 1. Layout `here`\n\nJump to [it](#1-layout-here).\n"
    assert validate_md_anchors(repo, text) == []


def test_anchor_matching_is_case_insensitive(git_repo) -> None:
    """Anchors resolve case-insensitively in every renderer that matters.

    Found by mutation: making the comparison case-sensitive broke nothing in the
    suite, because every other anchor test happened to use all-lowercase links.
    A reader who writes `#Setup-Guide` for `## Setup Guide` would have been told
    their working link was dead.
    """
    from handoff_collect import validate_md_anchors
    repo, _ = git_repo

    text = "## Setup Guide\n\nJump to [it](#Setup-Guide).\n"

    assert validate_md_anchors(repo, text) == []


def test_anchor_with_no_matching_heading_is_flagged(git_repo) -> None:
    from handoff_collect import validate_md_anchors
    repo, _ = git_repo

    findings = validate_md_anchors(repo, "## Layout\n\nSee [x](#nonexistent).\n")

    assert [f.kind for f in findings] == ["dead-md-anchor"]


# --- branches ----------------------------------------------------------------

def _entry(body: str) -> str:
    return f"# Status\n\n## Phase 1 - work (in progress, 2026-01-01)\n\n{body}\n\n## 1. Layout\n"


def test_merged_then_deleted_branch_is_not_flagged(git_repo) -> None:
    """THE false-positive guard, and the reason this rule exists in this shape.

    Every one of the four branches named in the corpus this was measured
    against had already been deleted after merging. A rule that only asked
    "does this branch exist" would have produced four findings, all wrong, on
    its first run. Deleting a merged branch is ordinary hygiene.
    """
    from handoff_collect import validate_branch_mentions
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "checkout", "-q", "-b", "feature/done")
    commit("b.py", "b = 1\n", "feat: b")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "feature/done", "-m",
        "Merge branch 'feature/done'")
    git(repo, "branch", "-qD", "feature/done")

    assert validate_branch_mentions(repo, _entry("Shipped on `feature/done`.")) == []


def test_branch_git_never_saw_is_flagged(git_repo) -> None:
    """The positive case: a name that exists in neither refs nor merge history
    is a typo or work that was never integrated."""
    from handoff_collect import validate_branch_mentions
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")

    findings = validate_branch_mentions(repo, _entry("Work is on `feature/never`."))

    assert [f.kind for f in findings] == ["unknown-branch"]


def test_a_file_path_is_not_reported_as_a_branch(git_repo, monkeypatch) -> None:
    """THE false positive this rule shipped with, found on a real install.

    A branch token and a file path are the same shape. The installer's fallback
    pattern for a repository with no dominant branch prefix is
    `([\\w.-]+/[^`]+)`, which matches `docs/arch.md` as readily as
    `feature/checkout`. It stayed invisible while that pattern fed only
    `stale-live-claim`, which gates on a live phrase first; `unknown-branch` has
    no such gate and reported a renamed design document as a phantom branch.

    Reproduced here with the real fallback pattern, not a contrived one.
    """
    import re
    import handoff_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    monkeypatch.setattr(hc, "_BRANCH_TOKEN", re.compile(r"`([\w.-]+/[^`]+)`"))

    findings = hc.validate_branch_mentions(
        repo, _entry("**Design:** `docs/arch.md`"))

    assert findings == [], (
        "a file path was reported as a branch: " + str([f.detail for f in findings])
    )


def test_live_claim_rule_also_refuses_to_treat_a_path_as_a_branch(git_repo, monkeypatch) -> None:
    """The same guard, on the other rule that reads branch tokens.

    Found by mutation after the fix: removing the guard from
    `validate_live_claims` left the suite green, because the false positive had
    only ever been reproduced against `unknown-branch`. Both rules read the same
    loose pattern, so both need the same protection, and a fix applied to one
    of two call sites is the kind of half-repair that looks complete in a diff.
    """
    import re
    import handoff_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    monkeypatch.setattr(hc, "_BRANCH_TOKEN", re.compile(r"`([\w.-]+/[^`]+)`"))

    findings = hc.validate_live_claims(
        repo, _entry("Work is NOT yet merged. **Design:** `docs/arch.md`"))

    assert findings == [], (
        "a file path was reported as an unmerged branch: "
        + str([f.detail for f in findings])
    )


def test_a_genuine_branch_with_a_dotted_name_still_checks(git_repo, monkeypatch) -> None:
    """The other half: excluding paths must not blind the rule to real branches.

    `release/v1.2` ends in a dot and digits. The cheap version of the fix above
    skips anything containing a dot, which would silently stop checking a whole
    naming convention.
    """
    import re
    import handoff_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    monkeypatch.setattr(hc, "_BRANCH_TOKEN", re.compile(r"`([\w.-]+/[^`]+)`"))

    findings = hc.validate_branch_mentions(
        repo, _entry("Work is on `release/v1.2`."))

    assert [f.kind for f in findings] == ["unknown-branch"]


def test_branch_rule_ignores_older_entries(git_repo) -> None:
    """Scoped to the newest entry, like live claims. Older entries name branches
    that were correct when written, and flagging them is noise."""
    from handoff_collect import validate_branch_mentions
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = ("# Status\n\n## Phase 2 - now (in progress, 2026-02-01)\n\nNothing.\n\n"
            "## Phase 1 - then (shipped, 2026-01-01)\n\nWas on `feature/never`.\n")

    assert validate_branch_mentions(repo, text) == []


# --- release tags ------------------------------------------------------------

def test_missing_release_tag_is_flagged(git_repo) -> None:
    from handoff_collect import validate_release_tags
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")

    findings = validate_release_tags(repo, "Released in v9.9.9 last week.\n")

    assert [f.kind for f in findings] == ["dead-release-tag"]


def test_tag_that_exists_but_never_reached_trunk_is_flagged(git_repo) -> None:
    """The half of this rule a mutation campaign found untested.

    A tag existing is not the claim; the claim is that it SHIPPED. A tag cut on
    an abandoned branch satisfies "does this tag exist" and still means the
    release never happened, which is the more misleading of the two failures.
    Dropping the ancestry check left every other test in this file green.
    """
    from handoff_collect import validate_release_tags
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "checkout", "-q", "-b", "abandoned")
    commit("b.py", "b = 1\n", "feat: never merged")
    git(repo, "tag", "v2.0")
    git(repo, "checkout", "-q", "main")

    findings = validate_release_tags(repo, "Released in v2.0 last week.\n")

    assert [f.kind for f in findings] == ["dead-release-tag"]
    assert "not an ancestor" in findings[0].detail


def test_existing_tag_on_trunk_is_silent(git_repo) -> None:
    """Catches a rule that flags real releases, which would make it unusable for
    the CHANGELOG-keeping projects it exists to serve."""
    from handoff_collect import validate_release_tags
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v1.0")

    assert validate_release_tags(repo, "Released in v1.0 last week.\n") == []


# --- rename hints ------------------------------------------------------------

def test_dead_pointer_reports_where_the_file_went(git_repo) -> None:
    """Catches the pathspec bug this was first written with.

    `git log --diff-filter=R -- <old path>` returns NOTHING once rename
    detection has run, so the first version looked correct and silently found
    nothing. Dropping the pathspec is what makes it work.
    """
    import handoff_collect
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/old.md", "# old\n", "docs: add")
    git(repo, "mv", "docs/old.md", "docs/new.md")
    git(repo, "commit", "-qm", "docs: rename")
    handoff_collect._RENAMES.clear()

    findings = validate_md_links(repo, "See [it](docs/old.md).\n")

    assert len(findings) == 1
    assert "renamed to `docs/new.md`" in findings[0].detail


# --- the registry and the selftest -------------------------------------------

def test_every_rule_declares_a_probe() -> None:
    """A rule that cannot say how to make itself fire cannot be shown to work.

    The same reasoning as the existing `falsifiable` requirement: declaring it
    in the registry is what stops a rule being added that nothing can exercise.
    """
    from handoff_collect import RULES

    assert RULES, "the registry is empty; this test would pass vacuously"
    missing = [r.kind for r in RULES if not callable(r.probe)]
    assert not missing, f"rules with no usable probe: {missing}"


def test_selftest_fires_every_probeable_rule(git_repo) -> None:
    """The end-to-end check that the probes actually corrupt what they claim to.

    Written after the merge-claim probe was found to be wrong: it replaced a
    SHA with zeros, but the rule skips claims whose commit does not resolve, so
    a working rule was reported as silent.
    """
    from handoff_collect import selftest
    repo, commit = git_repo
    base = commit("docs/plan.md", "# plan\n", "feat: base").strip()[:9]
    git(repo, "checkout", "-q", "-b", "feature/open")
    commit("w.py", "w = 1\n", "feat: off trunk")
    git(repo, "checkout", "-q", "main")
    text = (
        "# Status\n\n## Phase 1 - work (in progress, 2026-01-01)\n\n"
        "**Design:** `docs/plan.md`\n\n"
        "NOT yet merged; on `feature/open`.\n\n"
        f"Earlier work merged to `main` at `{base}`.\n\n"
        "See [plan](docs/plan.md) and [layout](#1-layout).\n\n## 1. Layout\n"
    )

    lines, fired, unprobeable = selftest(repo, text)

    silent = len(lines) - fired - unprobeable
    assert silent == 0, "a rule stayed silent after its probe:\n" + "\n".join(lines)
    assert fired >= 7, f"only {fired} rules could be exercised:\n" + "\n".join(lines)


def test_entry_scoped_rules_are_skipped_for_documents_with_no_entries(git_repo) -> None:
    """`has_entries=False` must actually govern which rules run.

    A README has no dated entries, so "the newest entry" names nothing and the
    entry-scoped rules would be reasoning about an empty string. Found by
    mutation: ignoring the flag entirely left the suite green, because every
    other extra_docs test used a document with no branch tokens in it.
    """
    from handoff_collect import validate
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = _entry("Work is on `feature/never`.")

    with_entries = validate(repo, text, has_entries=True)
    without = validate(repo, text, has_entries=False)

    assert "unknown-branch" in [f.kind for f in with_entries], (
        "the setup is wrong: this document should trip the rule when it has entries"
    )
    assert "unknown-branch" not in [f.kind for f in without]


def test_selftest_reports_a_rule_that_stays_silent(git_repo, monkeypatch) -> None:
    """A rule that ignores its own probe must be reported, not counted as fired.

    Found by mutation: reporting FIRED unconditionally left the suite green,
    because the existing selftest test only asserted that NOTHING stayed silent.
    That assertion is satisfied trivially by a selftest that can never report
    silence, which makes it exactly the shape of test this project warns about.
    """
    import handoff_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    blind = hc.Rule(
        kind="dead-sha",
        check=lambda _repo, _text: [],   # corrupt anything; notice nothing
        scope="whole-file",
        in_archive=True,
        falsifiable="never answered",
        probe=hc._probe_sha,
    )
    monkeypatch.setattr(hc, "RULES", (blind,))

    lines, fired, unprobeable = hc.selftest(repo, "Shipped at `abc1234567890`.\n")

    assert fired == 0, "a blind rule must not be counted as firing"
    assert unprobeable == 0, "the probe had a real SHA to corrupt"
    assert "DID NOT FIRE" in lines[0]


def test_extra_docs_are_validated(git_repo) -> None:
    """Catches an extra_docs setting that nothing reads, which is the exact
    class of defect this project exists to surface.

    The payload is copied into the repository first, because that is how it is
    actually used and the only arrangement in which its configuration is read.
    Settings load relative to the tool's own location, so running it from
    outside a repository reads that repository's .handoff.toml not at all. The
    tool says so on stderr; this test exercises the real installation instead.
    """
    import shutil
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n\n## Phase 1 - x (done, 2026-01-01)\n\nNothing.\n",
           "docs: status")
    shutil.copytree(SKILL_ROOT / "payload", repo / "tools")
    (repo / ".handoff.toml").write_text('extra_docs = ["CLAUDE.md"]\n', encoding="utf-8")
    (repo / "CLAUDE.md").write_text("See [design](docs/absent.md).\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "handoff_collect.py"),
         "--repo", str(repo), "--validate", "NEXT_SESSION.md"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )

    assert "CLAUDE.md" in result.stdout, result.stdout
    assert "dead-md-link" in result.stdout, result.stdout
    assert result.returncode == 1


# --- loopholes found by the adversarial smoke test ---------------------------

def test_claims_inside_a_code_fence_are_not_checked(git_repo) -> None:
    """A fenced block is an example or pasted output, not a promise.

    A README showing "Merged to `main` at `abc1234`" as the format to follow was
    read as a claim about abc1234. Found by an adversarial probe, not by any
    test, and it is the same false-positive class as the backticked example
    link fixed earlier.
    """
    from handoff_collect import validate_references, validate_path_pointers
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = ("Example of the format:\n\n```\n"
            "Merged to `main` at `0000000000000000000000000000000000000000`.\n"
            "**Design:** `docs/example-not-real.md`\n"
            "```\n")

    assert validate_references(repo, text) == []
    assert validate_path_pointers(repo, text) == []


def test_a_real_claim_in_backticks_is_still_checked(git_repo) -> None:
    """The other half, and the reason inline code is NOT stripped for claims.

    Claims are written in backticks by convention, so blanking inline spans the
    way the link rules do would delete exactly what these rules check. Applying
    that stripping wholesale turned eight tests red at once.
    """
    from handoff_collect import validate_references
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")

    findings = validate_references(
        repo, "Shipped at `0000000000000000000000000000000000000000`.\n")

    assert [f.kind for f in findings] == ["dead-sha"]


def test_a_secret_inside_a_code_fence_is_still_reported(git_repo) -> None:
    """Fenced code is exempt from CLAIM rules, never from the secret scan.

    A credential pasted into a fence is still a committed credential. The
    exemption is about what a document promises, not about what it contains.
    """
    from handoff_collect import scan_secrets

    findings = scan_secrets("```\nexport KEY=sk-A1b2C3d4E5f6G7h8I9j0K1l2m3\n```\n")

    assert [f.kind for f in findings] == ["possible-secret"]


def test_wrong_case_path_is_reported_even_on_a_case_insensitive_filesystem(git_repo) -> None:
    """Windows and macOS resolve `docs/PLAN.md` to `docs/plan.md`; Linux does not.

    Without this, a document passes on a developer's laptop and fails in CI, or
    passes in CI while misleading every Linux reader. The check compares against
    the real directory entry so the answer is the same everywhere.
    """
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")

    findings = validate_md_links(repo, "See [plan](docs/PLAN.md).\n")

    assert [f.kind for f in findings] == ["dead-md-link"]
    assert "case differs" in findings[0].detail
    assert "docs/plan.md" in findings[0].detail


def test_correct_case_path_stays_silent(git_repo) -> None:
    """The guard against a case check that flags everything."""
    from handoff_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")

    assert validate_md_links(repo, "See [plan](docs/plan.md).\n") == []


def test_collect_survives_a_repository_with_no_commits(git_repo, tmp_path) -> None:
    """`git log` exits 128 on an unborn branch rather than returning nothing.

    A freshly initialised repository is a legitimate state for someone just
    starting, not an error deserving a traceback.
    """
    from handoff_collect import commits_since, find_boundary
    repo, _ = git_repo  # created, never committed to

    assert find_boundary(repo) == ""
    assert commits_since(repo, "") == []


def test_a_document_that_is_not_utf8_is_reported_not_crashed(git_repo) -> None:
    """Reading with errors='replace' would let every rule run against silently
    corrupted text and report findings about bytes that are not there."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# S\n", "docs: doc")
    (repo / "NEXT_SESSION.md").write_bytes(b"# S\n\n\xff\xfe binary\n")

    result = run_tool(repo, "--validate", "NEXT_SESSION.md")

    assert result.returncode == 1
    assert "not valid UTF-8" in result.stderr, result.stderr
    assert "Traceback" not in result.stderr


def test_library_callers_can_resolve_links_against_the_document(git_repo) -> None:
    """A relative link resolves against its own file, not the repository root.

    The CLI has always passed this through a module global, so a library caller
    had no way to supply it: `docs/HANDOFF.md` linking to a sibling `plan.md`
    was reported dead through the API and fine through the CLI. Found by an
    adversarial probe calling validate() the way a downstream tool would.
    """
    from handoff_collect import validate
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")
    text = "See [plan](plan.md).\n"

    without_base = [f.kind for f in validate(repo, text, has_entries=False)]
    with_base = [f.kind for f in validate(repo, text, has_entries=False,
                                          base=repo / "docs")]

    assert "dead-md-link" in without_base, (
        "the setup is wrong: plan.md does not exist relative to the repo root"
    )
    assert with_base == [], f"sibling link reported dead despite base: {with_base}"


def test_merge_claims_do_not_spawn_a_git_process_per_mention(git_repo, monkeypatch) -> None:
    """The performance fix, pinned so it cannot silently regress.

    Two git subprocesses per claim was 98 percent of total validation time,
    measured at 17.7 of 18.0 seconds on a 4000-line document. `dead-sha` had
    already solved half of it by batching, and the optimisation was never
    carried across, so the two rules handled identical volume 170x apart.

    Counts invocations rather than seconds: a wall-clock assertion would be
    flaky on a loaded machine and would not say WHY it got slow.
    """
    import handoff_collect as hc
    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "feat: a").strip()[:9]

    calls: list[tuple[str, ...]] = []
    real_git = hc._git

    def counting_git(r, *args):
        calls.append(args)
        return real_git(r, *args)

    monkeypatch.setattr(hc, "_git", counting_git)
    # Twenty mentions of the same commit, which is how documents really read.
    text = "".join(f"Line {n}: merged to `main` at `{sha}`.\n" for n in range(20))

    findings = hc.validate_merge_claims(repo, text)

    assert findings == [], f"the setup is wrong, {sha} is on trunk: {findings}"
    assert len(calls) <= 3, (
        f"{len(calls)} git calls for 20 mentions of one commit; existence should "
        f"batch and ancestry should be asked once per distinct commit: {calls}"
    )


def test_batched_ancestry_agrees_with_git_in_BOTH_directions(git_repo) -> None:
    """The batch must say no as reliably as it says yes.

    Ancestry is answered from one `git rev-list` rather than one merge-base per
    claim, which took 2000 distinct claims from 105 seconds to about one. The
    dangerous failure is not slowness: a batch that always answered True would
    make `false-merge-claim` silently stop firing, and a check comparing only
    on-trunk commits would pass against exactly that bug.

    The first verification run had this hole - the fixture happened to contain
    no off-trunk commits, so it compared 60 commits and proved one direction.
    """
    import handoff_collect as hc
    repo, commit = git_repo
    on_trunk = [commit(f"a{n}.py", f"a = {n}\n", f"feat: on trunk {n}")[:9]
                for n in range(3)]
    git(repo, "checkout", "-q", "-b", "abandoned")
    off_trunk = [commit(f"b{n}.py", f"b = {n}\n", f"feat: off trunk {n}")[:9]
                 for n in range(3)]
    git(repo, "checkout", "-q", "main")

    index = hc._trunk_ancestor_index(repo)
    assert index, "no ancestor index built; the rest would prove nothing"

    def batched(sha: str) -> bool:
        return any(full.startswith(sha) for full in index.get(sha[:7], ()))

    for sha in on_trunk:
        assert batched(sha) is True, f"{sha} is on trunk but the batch said no"
        assert hc._is_merged(repo, sha) is True
    for sha in off_trunk:
        assert batched(sha) is False, (
            f"{sha} is NOT on trunk but the batch said yes; false-merge-claim "
            f"would go silently blind"
        )
        assert hc._is_merged(repo, sha) is False


def test_a_false_merge_claim_is_still_reported_through_the_batch(git_repo) -> None:
    """End to end, because the two halves above could both be right while the
    rule that consumes them is wired wrong."""
    from handoff_collect import validate_merge_claims
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: base")
    git(repo, "checkout", "-q", "-b", "abandoned")
    stray = commit("b.py", "b = 1\n", "feat: never merged")[:9]
    git(repo, "checkout", "-q", "main")

    findings = validate_merge_claims(repo, f"Merged to `main` at `{stray}`.\n")

    assert [f.kind for f in findings] == ["false-merge-claim"]


def test_directory_listings_are_not_cached_outside_validate(git_repo) -> None:
    """Caching is opted into by validate(), never on by default.

    The case check lists a directory per path component, which cost 0.88 of 6.4
    seconds on 3000 links. Caching those listings is safe for the duration of one
    validate() and unsafe outside it: a caller that creates a file between two
    checks must see the new answer. The cache is therefore None unless validate()
    has scoped it, and correctness is what happens when nobody asked for speed.
    """
    import handoff_collect as hc
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")
    text = "See [later](docs/later.md).\n"

    assert hc._DIRCACHE is None, "caching must be off by default"
    first = hc.validate_md_links(repo, text)
    assert [f.kind for f in first] == ["dead-md-link"]

    (repo / "docs" / "later.md").write_text("# later\n", encoding="utf-8")

    assert hc.validate_md_links(repo, text) == [], (
        "a file created between two direct calls was not seen; a stale "
        "directory listing outlived its owner"
    )


def test_stripped_text_cache_keys_on_identity_not_content(git_repo) -> None:
    """Two different strings with equal content must not share a cache entry.

    Identity is what makes the strip cache safe without a lifecycle: every rule
    in one validate() gets the same object, and anything else simply misses.
    Keying on equality would be faster and would silently return the wrong
    stripped text if a caller mutated a document between calls.
    """
    import handoff_collect as hc
    repo, _ = git_repo
    original = "Text with `code` in it.\n"
    duplicate = "".join(original)  # equal content, distinct object

    assert original == duplicate and original is not duplicate

    first = hc._prose(original)
    hc._prose(duplicate)
    cached_for, _cached_value = hc._STRIPPED[False]

    assert cached_for is duplicate, "the later call should own the cache entry"
    assert hc._prose(original) == first, "content must round-trip either way"
