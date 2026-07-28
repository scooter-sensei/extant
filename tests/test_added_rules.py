"""The rules added after the first release, and the selftest that probes them.

Each test names the wrong implementation it would catch. The false-positive
guards matter more than the positive cases here: the branch rule in particular
was nearly shipped in a form that produced four findings and four false
positives on the first corpus it was measured against.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
TOOL = SKILL_ROOT / "payload" / "extant_collect.py"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def _ancestor_of(repo: Path, rev: str, ref: str) -> bool:
    """Ask git directly. An oracle built from the code under test proves only
    that the code agrees with itself."""
    return subprocess.run(["git", "merge-base", "--is-ancestor", rev, ref],
                          cwd=repo, capture_output=True).returncode == 0


def run_tool(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), "--repo", str(repo), *args],
                          cwd=repo, capture_output=True, text=True, encoding="utf-8")


# --- markdown links ----------------------------------------------------------

def test_md_link_to_a_missing_file_is_flagged(git_repo) -> None:
    """Catches the gap that motivated this rule: a plain markdown link was
    invisible, because the path rule only sees backticked paths after an
    operative marker."""
    from extant_collect import validate_md_links
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")

    findings = validate_md_links(repo, "See [the plan](docs/gone.md) for detail.\n")

    assert [f.kind for f in findings] == ["dead-md-link"]
    assert "docs/gone.md" in findings[0].detail


def test_md_link_to_an_existing_file_is_silent(git_repo) -> None:
    """The false-positive guard. A rule that flags working links is worse than
    no rule, because it trains people to ignore the output."""
    from extant_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")

    assert validate_md_links(repo, "See [the plan](docs/plan.md).\n") == []


def test_external_links_are_never_checked(git_repo) -> None:
    """Catches a rule that reaches the network.

    Checking external links would make a green run depend on someone else's
    uptime and rate limits, turning a deterministic check into a coin flip.
    """
    from extant_collect import validate_md_links
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
    from extant_collect import validate_md_links
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = "| `[a link](to/a/file.md)` whose file is gone | checks it |\n"

    assert validate_md_links(repo, text) == []


def test_a_real_link_beside_an_example_is_still_caught(git_repo) -> None:
    """The other half: stripping inline code must not swallow the whole line.

    Without this, the fix above could be 'ignore any line containing a
    backtick', which would blind the rule wherever prose mixes the two.
    """
    from extant_collect import validate_md_links
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
    from extant_collect import validate_md_links
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
    from extant_collect import validate_md_anchors
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
    from extant_collect import validate_md_anchors
    repo, _ = git_repo

    text = "## Setup Guide\n\nJump to [it](#Setup-Guide).\n"

    assert validate_md_anchors(repo, text) == []


def test_anchor_with_no_matching_heading_is_flagged(git_repo) -> None:
    from extant_collect import validate_md_anchors
    repo, _ = git_repo

    findings = validate_md_anchors(repo, "## Layout\n\nSee [x](#nonexistent).\n")

    assert [f.kind for f in findings] == ["dead-md-anchor"]


def test_a_release_claim_ending_a_sentence_is_not_broken_by_the_full_stop(git_repo) -> None:
    """Ordinary English broke this rule.

    The version tail was greedy and swallowed the period that ends the
    sentence, so "Released in v2.1." looked for a tag literally named `v2.1.`
    and reported a false positive on a correct claim. Every existing fixture
    happened to continue the sentence after the version, so nothing caught it
    until the tool read its own status document and accused it. A wrong
    implementation that restores the greedy tail fails here.
    """
    from extant_collect import validate_release_tags
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v2.1")

    assert validate_release_tags(repo, "Released in v2.1.\n") == []
    assert validate_release_tags(repo, "Released in v2.1, and then more.\n") == []
    # The other direction: a genuinely absent tag must still be reported, and
    # the trailing period must not become part of the name it reports.
    findings = validate_release_tags(repo, "Released in v9.9.\n")
    assert [f.kind for f in findings] == ["dead-release-tag"], findings
    assert "`v9.9`" in findings[0].detail, findings[0].detail


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
    from extant_collect import validate_branch_mentions
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
    from extant_collect import validate_branch_mentions
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
    import extant_collect as hc
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
    import extant_collect as hc
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
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    monkeypatch.setattr(hc, "_BRANCH_TOKEN", re.compile(r"`([\w.-]+/[^`]+)`"))

    findings = hc.validate_branch_mentions(
        repo, _entry("Work is on `release/v1.2`."))

    assert [f.kind for f in findings] == ["unknown-branch"]


def test_branch_rule_ignores_older_entries(git_repo) -> None:
    """Scoped to the newest entry, like live claims. Older entries name branches
    that were correct when written, and flagging them is noise."""
    from extant_collect import validate_branch_mentions
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    text = ("# Status\n\n## Phase 2 - now (in progress, 2026-02-01)\n\nNothing.\n\n"
            "## Phase 1 - then (shipped, 2026-01-01)\n\nWas on `feature/never`.\n")

    assert validate_branch_mentions(repo, text) == []


# --- release tags ------------------------------------------------------------

def test_missing_release_tag_is_flagged(git_repo) -> None:
    from extant_collect import validate_release_tags
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
    from extant_collect import validate_release_tags
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "checkout", "-q", "-b", "abandoned")
    commit("b.py", "b = 1\n", "feat: never merged")
    git(repo, "tag", "v2.0")
    git(repo, "checkout", "-q", "main")

    findings = validate_release_tags(repo, "Released in v2.0 last week.\n")

    assert [f.kind for f in findings] == ["dead-release-tag"]
    # `abandoned` is slashless, and an earlier version of the integration-ref
    # rule counted any slashless branch - which silenced exactly this case.
    assert "on no integration branch" in findings[0].detail
    assert "abandoned" not in findings[0].detail


def test_existing_tag_on_trunk_is_silent(git_repo) -> None:
    """Catches a rule that flags real releases, which would make it unusable for
    the CHANGELOG-keeping projects it exists to serve."""
    from extant_collect import validate_release_tags
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
    import extant_collect
    from extant_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/old.md", "# old\n", "docs: add")
    git(repo, "mv", "docs/old.md", "docs/new.md")
    git(repo, "commit", "-qm", "docs: rename")
    extant_collect._RENAMES.clear()

    findings = validate_md_links(repo, "See [it](docs/old.md).\n")

    assert len(findings) == 1
    assert "renamed to `docs/new.md`" in findings[0].detail


# --- the registry and the selftest -------------------------------------------

def test_every_rule_declares_a_probe() -> None:
    """A rule that cannot say how to make itself fire cannot be shown to work.

    The same reasoning as the existing `falsifiable` requirement: declaring it
    in the registry is what stops a rule being added that nothing can exercise.
    """
    from extant_collect import RULES

    assert RULES, "the registry is empty; this test would pass vacuously"
    missing = [r.kind for r in RULES if not callable(r.probe)]
    assert not missing, f"rules with no usable probe: {missing}"


def test_selftest_fires_every_probeable_rule(git_repo) -> None:
    """The end-to-end check that the probes actually corrupt what they claim to.

    Written after the merge-claim probe was found to be wrong: it replaced a
    SHA with zeros, but the rule skips claims whose commit does not resolve, so
    a working rule was reported as silent.
    """
    from extant_collect import selftest
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
    from extant_collect import validate
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
    import extant_collect as hc
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
    outside a repository reads that repository's .extant.toml not at all. The
    tool says so on stderr; this test exercises the real installation instead.
    """
    import shutil
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n\n## Phase 1 - x (done, 2026-01-01)\n\nNothing.\n",
           "docs: status")
    shutil.copytree(SKILL_ROOT / "payload", repo / "tools")
    (repo / ".extant.toml").write_text('extra_docs = ["CLAUDE.md"]\n', encoding="utf-8")
    (repo / "CLAUDE.md").write_text("See [design](docs/absent.md).\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
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
    from extant_collect import validate_references, validate_path_pointers
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
    from extant_collect import validate_references
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
    from extant_collect import scan_secrets

    findings = scan_secrets("```\nexport KEY=sk-A1b2C3d4E5f6G7h8I9j0K1l2m3\n```\n")

    assert [f.kind for f in findings] == ["possible-secret"]


def test_wrong_case_path_is_reported_even_on_a_case_insensitive_filesystem(git_repo) -> None:
    """Windows and macOS resolve `docs/PLAN.md` to `docs/plan.md`; Linux does not.

    Without this, a document passes on a developer's laptop and fails in CI, or
    passes in CI while misleading every Linux reader. The check compares against
    the real directory entry so the answer is the same everywhere.
    """
    from extant_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")

    findings = validate_md_links(repo, "See [plan](docs/PLAN.md).\n")

    assert [f.kind for f in findings] == ["dead-md-link"]
    assert "case differs" in findings[0].detail
    assert "docs/plan.md" in findings[0].detail


def test_correct_case_path_stays_silent(git_repo) -> None:
    """The guard against a case check that flags everything."""
    from extant_collect import validate_md_links
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")

    assert validate_md_links(repo, "See [plan](docs/plan.md).\n") == []


def test_collect_survives_a_repository_with_no_commits(git_repo, tmp_path) -> None:
    """`git log` exits 128 on an unborn branch rather than returning nothing.

    A freshly initialised repository is a legitimate state for someone just
    starting, not an error deserving a traceback.
    """
    from extant_collect import commits_since, find_boundary
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
    from extant_collect import validate
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
    import extant_collect as hc
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
    import extant_collect as hc
    repo, commit = git_repo
    on_trunk = [commit(f"a{n}.py", f"a = {n}\n", f"feat: on trunk {n}")[:9]
                for n in range(3)]
    git(repo, "checkout", "-q", "-b", "abandoned")
    off_trunk = [commit(f"b{n}.py", f"b = {n}\n", f"feat: off trunk {n}")[:9]
                 for n in range(3)]
    git(repo, "checkout", "-q", "main")

    index = hc._ancestor_index(repo, "main")
    assert index, "no ancestor index built; the rest would prove nothing"

    def batched(sha: str) -> bool:
        return any(full.startswith(sha) for full in index.get(sha[:7], ()))

    for sha in on_trunk:
        assert batched(sha) is True, f"{sha} is on trunk but the batch said no"
        # Independent oracle: git itself, not another product function.
        assert _ancestor_of(repo, sha, "main") is True
    for sha in off_trunk:
        assert batched(sha) is False, (
            f"{sha} is NOT on trunk but the batch said yes; false-merge-claim "
            f"would go silently blind"
        )
        assert _ancestor_of(repo, sha, "main") is False


def test_a_false_merge_claim_is_still_reported_through_the_batch(git_repo) -> None:
    """End to end, because the two halves above could both be right while the
    rule that consumes them is wired wrong."""
    from extant_collect import validate_merge_claims
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
    import extant_collect as hc
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
    import extant_collect as hc
    repo, _ = git_repo
    original = "Text with `code` in it.\n"
    duplicate = "".join(original)  # equal content, distinct object

    assert original == duplicate and original is not duplicate

    first = hc._prose(original)
    hc._prose(duplicate)
    cached_for, _cached_value = hc._STRIPPED[False]

    assert cached_for is duplicate, "the later call should own the cache entry"
    assert hc._prose(original) == first, "content must round-trip either way"


# --- cross-artifact consistency ----------------------------------------------

CONSISTENCY_CFG = (
    "[extant.consistency.version]\n"
    + r'"a.json" = ' + "'" + r'"version": "([^"]+)"' + "'\n"
    + r'"CHANGELOG.md" = ' + "'" + r'^## (\d+\.\d+\.\d+)' + "'\n"
)


def test_files_that_agree_are_silent(git_repo) -> None:
    """The false-positive guard, and the one that decides whether this rule is
    usable at all. A consistency check that fires on a correct repository would
    be the first rule here to cry wolf."""
    from extant_collect import validate_consistency
    repo, commit = git_repo
    (repo / ".extant.toml").write_text(CONSISTENCY_CFG, encoding="utf-8")
    (repo / "a.json").write_text('{"version": "2.1.0"}\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 2.1.0 (2026-01-01)\n",
                                       encoding="utf-8")

    assert validate_consistency(repo, "") == []


def test_files_that_disagree_are_reported_with_both_values(git_repo) -> None:
    """THE bug this rule exists for: three manifests said 0.1.0 while the
    CHANGELOG said 0.3.0, and nothing could catch it because no rule inspects
    numbers. Comparing files to EACH OTHER is a different question."""
    from extant_collect import validate_consistency
    repo, commit = git_repo
    (repo / ".extant.toml").write_text(CONSISTENCY_CFG, encoding="utf-8")
    (repo / "a.json").write_text('{"version": "0.1.0"}\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 2.1.0 (2026-01-01)\n",
                                       encoding="utf-8")

    findings = validate_consistency(repo, "")

    assert [f.kind for f in findings] == ["inconsistent-artifact"]
    detail = findings[0].detail
    assert "0.1.0" in detail and "2.1.0" in detail, detail
    assert "a.json" in detail and "CHANGELOG.md" in detail, detail


def test_a_pattern_that_matches_nothing_is_reported(git_repo) -> None:
    """Silence here would be the worst outcome: the check would compare one
    value against itself and pass forever, which is the exact failure the
    denominator was introduced to make visible."""
    from extant_collect import validate_consistency
    repo, commit = git_repo
    (repo / ".extant.toml").write_text(CONSISTENCY_CFG, encoding="utf-8")
    (repo / "a.json").write_text('{"release": "2.1.0"}\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 2.1.0 (2026-01-01)\n",
                                       encoding="utf-8")

    findings = validate_consistency(repo, "")

    assert len(findings) == 1
    assert "matches nothing" in findings[0].detail


def test_a_missing_file_is_reported(git_repo) -> None:
    from extant_collect import validate_consistency
    repo, commit = git_repo
    (repo / ".extant.toml").write_text(CONSISTENCY_CFG, encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("# Changelog\n\n## 2.1.0 (2026-01-01)\n",
                                       encoding="utf-8")

    findings = validate_consistency(repo, "")

    assert any("does not exist" in f.detail for f in findings), findings


def test_no_consistency_config_means_no_findings(git_repo) -> None:
    """Off unless configured. The files and patterns are per-project, and a
    guessed default would accuse an innocent repository."""
    from extant_collect import validate_consistency
    repo, commit = git_repo

    assert validate_consistency(repo, "") == []


def test_the_rule_reads_the_repo_under_test_not_the_installed_one(git_repo) -> None:
    """Configuration must come from the repository being checked.

    This rule reads files by path, so holding one project's file list while
    pointed at another is meaningless. It happened immediately: every temporary
    repository in this suite inherited the real project's version block and was
    told four files were missing.
    """
    from extant_collect import validate_consistency
    repo, commit = git_repo
    commit("README.md", "# x\n", "init")

    assert validate_consistency(repo, "") == [], (
        "a repo with no consistency config produced findings, so the rule is "
        "reading someone else's configuration"
    )


def test_a_one_file_check_is_rejected_at_load(tmp_path) -> None:
    """A check listing one file can only ever agree with itself.

    Accepting it would produce a rule that passes forever while appearing to
    compare something, which is this project's defining failure mode.
    """
    from extant_config import load_config
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        "[extant.consistency.version]\n\"only.json\" = '\"v\": \"(.+)\"'\n",
        encoding="utf-8")

    try:
        load_config(tmp_path)
    except ValueError as exc:
        assert "at least two" in str(exc), exc
    else:
        raise AssertionError("a single-file consistency check was accepted")


def test_a_pattern_without_a_capture_group_is_rejected(tmp_path) -> None:
    """No capture group means no value to compare."""
    from extant_config import load_config
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        "[extant.consistency.version]\n"
        "\"a.json\" = 'version'\n\"b.json\" = 'version'\n", encoding="utf-8")

    try:
        load_config(tmp_path)
    except ValueError as exc:
        assert "capture group" in str(exc), exc
    else:
        raise AssertionError("a pattern with no capture group was accepted")


# --- search and suggested fixes ----------------------------------------------

def test_search_returns_whole_entries_from_both_documents(git_repo) -> None:
    """Whole entries, not matching lines, and both documents at once.

    Returning lines would make this a worse `grep`. A decision lives in a dated
    entry with its reasoning; a line from the middle says a phrase exists and
    not what was decided. Both documents are searched because the entire
    problem is that entries MOVE from one to the other, and the person looking
    does not know which side of that move they are on.
    """
    from extant_collect import search_entries
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# S\n\n## Phase 2 - now (in progress, 2026-02-01)\n\n"
           "Nothing about that here.\n\n## 1. Ref\n", "docs: live")
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "status-archive.md").write_text(
        "# Archive\n\n## Phase 1 - checkout (shipped, 2026-01-01)\n\n"
        "We chose the queue approach for checkout.\n\n", encoding="utf-8")

    results = search_entries(repo, "queue approach")

    assert len(results) == 1
    document, header, body = results[0]
    assert "archive" in document
    assert "Phase 1" in header
    assert "queue approach" in body


def test_search_is_case_insensitive_and_misses_cleanly(git_repo) -> None:
    from extant_collect import search_entries
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
           "The Checkout Rewrite landed.\n\n## 1. Ref\n", "docs: live")

    # The QUERY must carry mixed case, not just the document. Lowercasing an
    # already-lowercase query is a no-op, so the original version of this test
    # passed against a case-sensitive implementation - found by mutation.
    assert len(search_entries(repo, "ChEcKoUt ReWrItE")) == 1
    assert len(search_entries(repo, "checkout rewrite")) == 1
    assert search_entries(repo, "kubernetes") == []


def test_suggested_fix_is_a_patch_and_writes_nothing(git_repo) -> None:
    """The boundary this tool's authority rests on.

    It checks claims and never writes them. A validator that edits prose can be
    wrong in a new way - it can author a falsehood itself - and nothing would be
    left to catch that. A patch keeps the boundary: reviewable, one command to
    apply, and the decision stays with whoever owns the document.
    """
    from extant_collect import suggest_renames
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")
    text = "See [plan](docs/plan.md).\n"
    doc = repo / "NEXT_SESSION.md"
    doc.write_text(text, encoding="utf-8")
    git(repo, "mv", "docs/plan.md", "docs/design.md")
    git(repo, "commit", "-qm", "docs: rename")
    hc._RENAMES.clear()

    patch = suggest_renames(repo, repo, text, "NEXT_SESSION.md")

    assert patch, "a recorded rename produced no suggestion"
    assert "-See [plan](docs/plan.md)." in patch
    assert "+See [plan](docs/design.md)." in patch
    assert doc.read_text(encoding="utf-8") == text, (
        "the document was modified; this must only ever emit a patch"
    )


def test_a_merely_missing_file_gets_no_suggestion(git_repo) -> None:
    """Only renames GIT RECORDED are offered. Guessing where a file went is
    exactly the authoring this refuses to do."""
    from extant_collect import suggest_renames
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    hc._RENAMES.clear()

    assert suggest_renames(repo, repo, "See [x](docs/never-existed.md).\n",
                           "NEXT_SESSION.md") == ""


def test_prose_mentioning_the_old_path_is_left_alone(git_repo) -> None:
    """Replaced only where a path is USED as a reference.

    A bare find-and-replace would also rewrite the sentence explaining the move,
    which is frequently the one sentence a reader most needs intact.
    """
    from extant_collect import suggest_renames
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")
    git(repo, "mv", "docs/plan.md", "docs/design.md")
    git(repo, "commit", "-qm", "docs: rename")
    hc._RENAMES.clear()
    text = "See [plan](docs/plan.md).\nWe renamed docs/plan.md last week.\n"

    patch = suggest_renames(repo, repo, text, "NEXT_SESSION.md")

    assert "+See [plan](docs/design.md)." in patch
    # The prose line must not appear as a changed line at all.
    changed = [ln for ln in patch.splitlines()
               if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
    assert not any("last week" in ln for ln in changed), changed


def test_suggest_fixes_puts_nothing_but_the_patch_on_stdout(git_repo) -> None:
    """`--suggest-fixes | git apply` must work, so stdout carries only a patch.

    Found by mutation immediately after building the feature: making findings
    share stdout with the patch broke no test, because the pipe had only ever
    been checked by hand. git apply receives log lines and rejects the lot, and
    a patch that cannot be applied is not a feature.
    """
    import shutil
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")
    commit("NEXT_SESSION.md",
           "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
           "See [plan](docs/plan.md).\n\n## 1. Ref\n", "docs: status")
    git(repo, "mv", "docs/plan.md", "docs/design.md")
    git(repo, "commit", "-qm", "docs: rename")
    shutil.copytree(SKILL_ROOT / "payload", repo / "tools")

    result = subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), "--verify", "--suggest-fixes"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )

    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines, "no patch was produced"
    assert all(ln.startswith(("---", "+++", "@@", "+", "-", " ")) for ln in lines), (
        "stdout carries something that is not part of a patch:\n"
        + "\n".join(ln for ln in lines
                    if not ln.startswith(("---", "+++", "@@", "+", "-", " ")))
    )
    assert "dead-md-link" in result.stderr, (
        "findings should still be reported, on stderr"
    )


def test_the_suggested_patch_actually_applies(git_repo) -> None:
    """The only test of this feature that matters. A patch git rejects is
    worthless however well-formed it looks, and the first version was rejected:
    print() rewrote its newlines on Windows."""
    import shutil
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")
    commit("NEXT_SESSION.md",
           "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
           "**Design:** `docs/plan.md`\n\n## 1. Ref\n", "docs: status")
    git(repo, "mv", "docs/plan.md", "docs/design.md")
    git(repo, "commit", "-qm", "docs: rename")
    shutil.copytree(SKILL_ROOT / "payload", repo / "tools")

    produced = subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), "--verify", "--suggest-fixes"],
        cwd=repo, capture_output=True, encoding="utf-8", text=True,
    )
    with open((repo / "fix.patch"), "w", encoding="utf-8", newline="") as fh:
        fh.write(produced.stdout)

    applied = subprocess.run(["git", "apply", "fix.patch"], cwd=repo,
                             capture_output=True, text=True, encoding="utf-8")

    assert applied.returncode == 0, f"git apply rejected the patch: {applied.stderr}"
    assert "docs/design.md" in (repo / "NEXT_SESSION.md").read_text(encoding="utf-8")


def test_the_same_file_under_two_spellings_is_rejected(tmp_path) -> None:
    """`a.md` and `./a.md` are one file, and a file always agrees with itself.

    TOML keeps them as distinct keys, so the two-file minimum passes and the
    check compares nothing while appearing configured. Found by an adversarial
    probe rather than by reasoning about the format.
    """
    from extant_config import load_config
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        "[extant.consistency.version]\n"
        "\"a.md\" = 'v: (.+)'\n\"./a.md\" = 'v: (.+)'\n", encoding="utf-8")

    try:
        load_config(tmp_path)
    except ValueError as exc:
        assert "same file twice" in str(exc), exc
    else:
        raise AssertionError("one file listed twice was accepted as a check")


def test_two_genuinely_different_files_still_load(tmp_path) -> None:
    """The guard must not reject a legitimate pair whose paths merely look
    similar."""
    from extant_config import load_config
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        "[extant.consistency.version]\n"
        "\"a.md\" = 'v: (.+)'\n\"./docs/a.md\" = 'v: (.+)'\n", encoding="utf-8")

    checks = load_config(tmp_path).consistency

    assert len(checks["version"]) == 2


def test_suggest_renames_writes_no_file_at_all(git_repo) -> None:
    """Not merely "does not change the document" - writes NOTHING.

    The earlier test asserted the document was untouched, so a version that
    created some other file passed it. Found by mutation. The promise this
    feature makes is that it emits a patch and touches the working tree not at
    all, and that is what has to be pinned.
    """
    from extant_collect import suggest_renames
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")
    git(repo, "mv", "docs/plan.md", "docs/design.md")
    git(repo, "commit", "-qm", "docs: rename")
    hc._RENAMES.clear()
    before = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}

    patch = suggest_renames(repo, repo, "See [plan](docs/plan.md).\n", "DOC.md")

    after = {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}
    assert patch, "the setup produced no patch, so this proves nothing"
    assert after == before, f"files appeared or vanished: {after ^ before}"


# --- configuration discovery -------------------------------------------------

def test_config_is_found_by_searching_upward(tmp_path) -> None:
    """Installed as tools/, the config sits beside the script. Run from
    anywhere else it does not, and looking only beside the script found nothing
    while reporting a healthy run against defaults - which is how this project
    discovered it could not configure its own tool."""
    from extant_config import load_config
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text('primary_doc = "FOUND.md"\n', encoding="utf-8")
    nested = tmp_path / "plugin" / "skills" / "payload"
    nested.mkdir(parents=True)

    assert load_config(nested).primary_doc == "FOUND.md"


def test_config_search_stops_at_the_repository_root(tmp_path) -> None:
    """A project nested inside another checkout must not inherit the outer
    project's settings. Wrong settings that look deliberate are a worse failure
    than the missing-config one this search was added to fix."""
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text('primary_doc = "OUTER.md"\n', encoding="utf-8")
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / ".git").mkdir()

    cfg = load_config(inner)

    assert cfg.source == "defaults", (
        f"the search escaped the repository root and read {cfg.source}"
    )
    assert cfg.primary_doc != "OUTER.md"


# --- install snippets --------------------------------------------------------
#
# The one rule that reads INSIDE code blocks. Every other claim rule blanks them
# first, because an example in a fence is not a promise. An install snippet is
# the opposite: the one block on the page a reader copies verbatim.


def _pinned(repo: Path, doc: str,
            remote: str | None = "https://github.com/acme/widget") -> None:
    """A repo whose origin is `remote`, with `doc` as its primary document.

    The payload is copied in as `tools/`, because that is the shape it is
    installed in and the only one where settings resolve to the repository
    being checked rather than to wherever the script happens to live.
    """
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "T")
    if remote:
        git(repo, "remote", "add", "origin", remote)
    with open((repo / "README.md"), "w", encoding="utf-8", newline="") as fh:
        fh.write(doc)
    with open(repo / ".extant.toml", "w", encoding="utf-8", newline="") as fh:
        fh.write('primary_doc = "README.md"\n')
    shutil.copytree(SKILL_ROOT / "payload", repo / "tools")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "init")


def run_installed(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """The installed copy, which reads the checked repository's own settings."""
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


OWN_SNIPPET = (
    "# Widget\n\n"
    "```yaml\n"
    "repos:\n"
    "  - repo: https://github.com/acme/widget\n"
    "    rev: {ref}\n"
    "    hooks:\n"
    "      - id: widget\n"
    "```\n"
)


def test_a_pin_naming_this_repo_must_resolve(tmp_path) -> None:
    """The bug this rule exists for, twice over in this project's own history.

    A README pinned a tag for a fortnight while the repository had no tags at
    all. `dead-release-tag` cannot see it, because the snippet is fenced and
    fences are exempt from claim rules by design.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _pinned(repo, OWN_SNIPPET.format(ref="v9.9.9"))

    result = run_installed(repo, "--verify")

    assert result.returncode == 1, result.stdout
    assert "dead-pinned-ref" in result.stdout
    assert "v9.9.9" in result.stdout
    # The line number is what a reader navigates by, and nothing pinned it
    # until a mutation shifted every report by one and the suite stayed green.
    # `rev:` is the sixth line of OWN_SNIPPET.
    assert "line 6:" in result.stdout, (
        f"the finding must point at the pin's own line:\n{result.stdout}"
    )


def test_a_pin_naming_someone_elses_repo_is_left_alone(tmp_path) -> None:
    """The false-positive guard, and the reason the rule tracks `repo:` at all.

    A project documenting a third-party hook pins a tag living in somebody
    else's repository. Checking it here reports a finding on a line that is
    perfectly correct, which is how a validator earns a reputation for noise.

    A wrong implementation that matches `rev:` alone fails here.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _pinned(repo,
            "# Widget\n\n"
            "```yaml\n"
            "repos:\n"
            "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
            "    rev: v4.5.0\n"
            "```\n")

    result = run_installed(repo, "--verify")

    assert result.returncode == 0, result.stdout
    assert "dead-pinned-ref 0" in result.stdout, (
        "a third-party pin must not even be counted as examined"
    )


def test_an_ssh_remote_matches_the_https_url_a_readme_shows(tmp_path) -> None:
    """Catches a comparison done on the raw URL string.

    Clones over SSH have `git@github.com:acme/widget.git` as their origin while
    the README tells people to use the https URL. Compared literally these are
    different repositories, and the rule would silently check nothing.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _pinned(repo, OWN_SNIPPET.format(ref="v9.9.9"),
            remote="git@github.com:acme/widget.git")

    result = run_installed(repo, "--verify")

    assert result.returncode == 1, result.stdout
    assert "dead-pinned-ref" in result.stdout


def test_a_pin_that_resolves_is_not_reported(tmp_path) -> None:
    """The other direction. A rule that fires on everything is not a rule."""
    repo = tmp_path / "r"
    repo.mkdir()
    _pinned(repo, OWN_SNIPPET.format(ref="v1.0.0"))
    git(repo, "tag", "-a", "v1.0.0", "-m", "release")

    result = run_installed(repo, "--verify")

    assert result.returncode == 0, result.stdout
    assert "dead-pinned-ref 1" in result.stdout, (
        "the pin must be examined, not merely absent from the findings"
    )


def test_indented_snippets_are_checked_too(tmp_path) -> None:
    """A CHANGELOG written with four-space blocks rather than fences.

    Both styles carry install instructions, and this project's own CHANGELOG
    uses the indented one, so a fence-only implementation would miss the file
    where half its pins live.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _pinned(repo,
            "# Widget\n\n"
            "Install:\n\n"
            "    repos:\n"
            "      - repo: https://github.com/acme/widget\n"
            "        rev: v9.9.9\n")

    result = run_installed(repo, "--verify")

    assert result.returncode == 1, result.stdout
    assert "dead-pinned-ref" in result.stdout


def test_a_repo_with_no_origin_reports_nothing_examined(tmp_path) -> None:
    """Without an origin there is no way to know which pins are ours.

    The honest answer is 0 examined, which the denominator line then shows,
    rather than a clean run that looks like a verdict.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _pinned(repo, OWN_SNIPPET.format(ref="v9.9.9"), remote=None)

    result = run_installed(repo, "--verify")

    assert result.returncode == 0, result.stdout
    assert "dead-pinned-ref 0" in result.stdout
