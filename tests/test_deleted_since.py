"""Claims removed while still false are reported, and never gate.

The mechanism is one idea: take each configured document as it stood at `ref`
and validate it against TODAY's git. Every finding that survives is a claim
which is false right now, so there is no separate "is it still false" step.

This mode does not gate, and that is a design decision rather than caution.
Whether a deletion is evasion or repair is a question about intent, and git
cannot settle it - a document that deletes a false claim now tells the truth,
which is the tool's whole purpose. Reporting the fact is falsifiable. Judging
it is not, so a human does that.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

DEAD = "dead" + "0" * 36
OTHER = "beef" + "1" * 36
ENTRY = "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{}\n\n## 1. Ref\n"


def _run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def test_a_deleted_false_claim_is_reported(git_repo) -> None:
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Nothing to see here."), "docs: remove")

    gone, examined, _skipped, _bad = sweep.deleted_claims(repo, "HEAD~1")
    assert examined == 1, f"examined {examined} documents"
    assert [f for f in gone if f.finding.subject == DEAD], [f.finding for f in gone]


def test_a_claim_that_became_true_is_not_reported(git_repo) -> None:
    """The mechanism's whole point, and the reason there is no separate
    still-false check. Validating the OLD text against TODAY's git means a
    claim whose underlying fact was fixed produces no finding to begin with."""
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md",
           ENTRY.format("Work continues on `feature/pending`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Done."), "docs: remove")
    # The branch now exists, so the old text's claim is true today.
    _run(repo, "branch", "feature/pending")

    gone, _examined, _skipped, _bad = sweep.deleted_claims(repo, "HEAD~1")
    assert not [f for f in gone if "feature/pending" in f.finding.detail], (
        [f.finding.detail for f in gone]
    )


def test_relocating_to_the_archive_is_not_a_deletion(git_repo) -> None:
    """`--archive` moves entries out of the live document by design. The token
    stays findable, so archiving must not look like hiding."""
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("docs/status-archive.md",
           f"# Archive\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nMerged at `{DEAD}`.\n",
           "docs: archive it")
    commit("NEXT_SESSION.md", ENTRY.format("Moved to the archive."), "docs: relocate")

    gone, _examined, _skipped, _bad = sweep.deleted_claims(repo, "HEAD~1")
    assert not [f for f in gone if f.finding.subject == DEAD], (
        "the token is still findable in the archive: " + str([f.finding for f in gone])
    )


def test_moving_a_claim_into_a_fence_is_a_deletion(git_repo) -> None:
    """Fenced code is exempt from every claim rule, so a fence silences them
    all. Without prose-scoping on the haystack it would silence this too."""
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md",
           ENTRY.format(f"```\nMerged at `{DEAD}`.\n```"), "docs: hide it")

    gone, _examined, _skipped, _bad = sweep.deleted_claims(repo, "HEAD~1")
    assert [f for f in gone if f.finding.subject == DEAD], (
        "a claim moved into a fence is still a claim withdrawn from prose"
    )


def test_an_unchanged_document_is_not_re_read(git_repo) -> None:
    """Cost, and correctness. A document that did not change cannot have lost
    a claim, so skipping it is not merely an optimisation."""
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("other.txt", "unrelated\n", "chore: touch something else")

    _gone, examined, _skipped, _bad = sweep.deleted_claims(repo, "HEAD~1")
    assert examined == 0, "the document did not change; it must not be re-read"


def test_the_mode_never_gates(git_repo, capsys) -> None:
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Gone."), "docs: remove")

    assert sweep.run_deleted_since(repo, "HEAD~1", "text") == 0
    printed = capsys.readouterr()
    assert "examined" in printed.out + printed.err, "the denominator must print"


def test_a_rule_that_raises_is_named_even_though_the_mode_never_gates(
        git_repo, capsys, monkeypatch) -> None:
    """The gap `run_sweep` and `--validate` already closed, missing here.

    `deleted_claims` calls `session.validate()` once per changed document, the
    same call `cli.main()` makes for `--validate` and `run_sweep` makes per
    swept file - and both of those name a crashed rule in their output, beside
    the denominator, per registry.py's RULE_ERRORS contract. This mode never
    reported it: `session.validate()` still records the failure in
    RULE_ERRORS, but nothing here ever called `session.report_rule_errors`, so
    a rule that failed to look printed no differently from a rule that looked
    and found nothing.

    Non-gating is correct and deliberate here - see the module docstring - so
    this does NOT assert a non-zero exit, unlike the equivalent test in
    test_rule_contract.py. It only asserts the failure is SAID.
    """
    from extant import session as hc
    from extant import sweep

    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format("Gone."), "docs: remove")

    def explode(ctx, text):
        raise RuntimeError("deliberate")

    import dataclasses

    broken = dataclasses.replace(hc.RULES[0], check=explode)
    monkeypatch.setattr(hc, "RULES", (broken,) + hc.RULES[1:])

    code = sweep.run_deleted_since(repo, "HEAD~1", "text")
    printed = capsys.readouterr()
    combined = printed.out + printed.err

    assert code == 0, (
        "this mode must never gate, crashed rule or not - see the module "
        "docstring on why intent is not this tool's to judge")
    assert "ERRORED" in combined and broken.kind in combined, (
        f"the crashed rule was not named in the output, so its silence is "
        f"indistinguishable from a clean run finding nothing to report:\n"
        f"{combined}")
    assert "RuntimeError: deliberate" in combined, (
        f"the exception was recorded without saying what it was:\n{combined}")


def test_a_missing_ref_is_reported_not_crashed(git_repo, capsys) -> None:
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format("x"), "docs: init")

    assert sweep.run_deleted_since(repo, "no-such-ref", "text") == 0
    printed = capsys.readouterr()
    assert "examined" in printed.out + printed.err


def test_sarif_stdout_is_a_document_even_with_nothing_to_report(
        git_repo, capsys) -> None:
    """SARIF's contract is that stdout is one valid document, always.

    A machine consumer handed zero bytes fails its upload rather than reading
    "no results", so a clean run looks exactly like a broken one. `--sweep` and
    `--validate` both emit an empty document here; this mode emitted nothing
    at all until it was measured against them.
    """
    import json
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format("Nothing wrong."), "docs: init")

    assert sweep.run_deleted_since(repo, "HEAD", "sarif") == 0
    printed = capsys.readouterr()
    parsed = json.loads(printed.out)
    assert parsed["runs"][0]["results"] == [], parsed["runs"][0]["results"]
    assert "examined" in printed.err, (
        "the denominator belongs on stderr in SARIF mode, or it corrupts the "
        "document on stdout"
    )


def test_a_correction_that_swaps_the_token_is_reported(git_repo) -> None:
    """Recorded deliberately, so nobody later 'fixes' it into a heuristic.

    Replacing a dead SHA with a different dead SHA removes the first one, and
    the first one is still dead. From git's side that is indistinguishable
    from hiding it, and guessing which it was is exactly the intent question
    this mode refuses to answer. It reports; the reader decides. This is also
    why it does not gate.
    """
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD}`."), "docs: claim")
    commit("NEXT_SESSION.md", ENTRY.format(f"Merged at `{OTHER}`."), "docs: swap")

    gone, _examined, _skipped, _bad = sweep.deleted_claims(repo, "HEAD~1")
    assert [f for f in gone if f.finding.subject == DEAD], (
        "the removed token is still dead, so it is reported"
    )
