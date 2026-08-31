"""Regressions found by `tests/harnesses/fuzz.py`, one test per finding.

The fuzzer builds hostile repositories at random and checks properties that
hold whatever the right answer is. When one of those properties breaks, the
repository that broke it is reduced to a case here, so the finding becomes a
permanent part of the suite rather than something that depends on a seed
coming up again.

This file is meant to GROW. A fuzzer whose findings are fixed and forgotten
teaches the suite nothing; the accumulation is the point. Each test names the
seed that found it and the property that failed.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _sweep(repo: Path, *extra: str):
    """Drive the real entry point, so the test sees what a consumer sees."""
    return subprocess.run(
        [sys.executable, str(PAYLOAD / "extant_collect.py"), "--sweep",
         *extra, "--repo", str(repo)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def _repo_without_markdown(git_repo) -> Path:
    repo, commit = git_repo
    commit("f.txt", "not a document\n", "chore: a file git tracks")
    return repo


# --- seed 1, property FORMATS: a machine format went silent ------------

def test_a_sweep_with_no_documents_still_emits_a_sarif_document(git_repo) -> None:
    """Empty stdout and "I examined nothing" are different facts.

    The fuzzer generated a repository git tracked no markdown in and asked for
    SARIF. stdout was zero bytes. A consumer cannot tell that from a tool that
    crashed, an upload step pointed at the wrong path, or a binary that was
    never installed - and GitHub rejects an empty SARIF file outright, so a
    project whose glob matched nothing got a failed upload rather than a report
    reading zero.

    Catches a return that skips the machine format, which is what it did.
    """
    repo = _repo_without_markdown(git_repo)
    done = _sweep(repo, "--format=sarif")

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip(), "SARIF stdout was empty for a zero-document sweep"
    doc = json.loads(done.stdout)
    assert doc["runs"], doc
    assert doc["runs"][0].get("results") == [], doc["runs"][0].get("results")


def test_that_sarif_document_carries_a_denominator_of_zero(git_repo) -> None:
    """A report with no results has to say how much it looked at.

    Zero results and zero documents examined are the same output without this,
    which is the conflation the whole tool exists to refuse. Catches a fix that
    emitted the envelope and left the counts out.
    """
    repo = _repo_without_markdown(git_repo)
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)
    run = doc["runs"][0]
    examined = (run.get("properties", {}).get("examined")
                or (run.get("invocations") or [{}])[0]
                .get("properties", {}).get("examined"))
    assert examined is not None, "no examined denominator in the SARIF run"
    assert examined, "the examined map is empty, so it names no rule"
    assert all(n == 0 for n in examined.values()), examined


def test_the_text_sweep_is_unchanged_by_that_fix(git_repo) -> None:
    """The diagnostic belonged on stderr and still does.

    Text output was already honest here - it says so in a sentence. Catches a
    fix that started printing a machine document into a human run, or that
    moved the sentence to stdout.
    """
    repo = _repo_without_markdown(git_repo)
    done = _sweep(repo)

    assert done.returncode == 0
    assert done.stdout == "", f"text sweep wrote to stdout: {done.stdout!r}"
    assert "git tracks none in this repository" in done.stderr, done.stderr


def test_a_sweep_that_does_find_documents_is_untouched(git_repo) -> None:
    """The guard must apply only to the empty case.

    Catches a fix that took the early return for every sweep, which would make
    every SARIF report empty - a far worse version of the bug.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# s\n\nSee `src/gone.py` for detail.\n",
           "docs: a document with one dead pointer")
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)
    results = doc["runs"][0]["results"]
    assert len(results) == 1, results
    assert results[0]["ruleId"] == "dead-path-pointer", results[0]


# --- seed 20260824, property DENOMINATOR: found > examined --------------


def _examined(doc: dict) -> dict:
    """The per-rule denominators out of a SARIF run, wherever they are."""
    run = doc["runs"][0]
    return (run.get("properties", {}).get("examined")
            or (run.get("invocations") or [{}])[0]
            .get("properties", {}).get("examined"))


def _anchor_repo(git_repo, link: str) -> Path:
    repo, commit = git_repo
    commit("docs/note.md", "# Note\n\n## A real heading\n\ntext\n",
           "docs: a note with one heading")
    commit("NEXT_SESSION.md", f"# S\n\nJump to {link}.\n",
           "docs: a document that links into it")
    return repo


def test_a_cross_file_anchor_is_counted_by_the_rule_that_judges_it(
        git_repo) -> None:
    """A finding against a denominator of zero says two opposite things.

    `dead-md-anchor` judges `[x](docs/note.md#heading)` and its denominator
    counted only bare `#fragment` links, so a cross-file anchor was reported
    while the same run said the rule examined nothing and named it in the
    "these rules examined nothing anywhere here" list. That is the severe
    direction of the one-claim-one-scanner defect: not a rule that is quiet,
    but a rule that speaks and is then reported as never having looked.

    Catches a fix that reports the finding without counting the site.
    """
    repo = _anchor_repo(git_repo, "[x](docs/note.md#no-such-heading)")
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)

    found = [r for r in doc["runs"][0]["results"]
             if r["ruleId"] == "dead-md-anchor"]
    assert len(found) == 1, doc["runs"][0]["results"]
    examined = _examined(doc)
    assert examined["dead-md-anchor"] >= len(found), examined

    note = [line for line in _sweep(repo).stderr.splitlines()
            if "examined nothing anywhere here" in line]
    assert not [line for line in note if "dead-md-anchor" in line], note


def test_the_widened_denominator_counts_sites_rather_than_hashes(
        git_repo) -> None:
    """Both callers must read the sites the rule can DECIDE, not every `#`.

    A denominator that counted anchors the rule declines to judge would be
    the same defect pointed the other way: coverage reported where none was
    provided. A cross-file anchor that resolves is examined and clean; one
    whose file is not there is `dead-md-link`'s finding, so this rule neither
    reports it nor counts it.

    Catches a fix that made `examined` count every fragment link it saw.
    """
    live = _anchor_repo(git_repo, "[x](docs/note.md#a-real-heading)")
    doc = json.loads(_sweep(live, "--format=sarif").stdout)
    assert not [r for r in doc["runs"][0]["results"]
                if r["ruleId"] == "dead-md-anchor"], doc["runs"][0]["results"]
    assert _examined(doc)["dead-md-anchor"] == 1, _examined(doc)


def test_an_anchor_on_a_file_that_is_not_there_is_still_not_counted(
        git_repo) -> None:
    """The other half of the same property, in its own case.

    `dead-md-link` owns a target that does not resolve, and this rule has
    always declined to judge one. A denominator that counted it would claim
    the anchor had been checked against a file nothing read.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# S\n\nJump to [x](docs/gone.md#heading).\n",
           "docs: an anchor on a file that is not there")
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)

    kinds = [r["ruleId"] for r in doc["runs"][0]["results"]]
    assert kinds == ["dead-md-link"], kinds
    assert _examined(doc)["dead-md-anchor"] == 0, _examined(doc)


def _floor_repo(git_repo, stated: str) -> Path:
    repo, commit = git_repo
    commit("pyproject.toml", '[project]\nname = "w"\nrequires-python = ">=3.9"\n',
           "chore: a manifest that declares a floor")
    commit("README.md", f"# Widget\n\nRequires Python {stated} or later.\n",
           "docs: a README that states one")
    commit("NEXT_SESSION.md", "# S\n\nNothing.\n", "docs: a status document")
    return repo


def test_a_sweep_counts_the_manifest_floor_claims_it_reports(git_repo) -> None:
    """The same conflation reached through the survey rather than the rule.

    `manifest-floor-mismatch` keys on WHICH document it is reading, and a
    sweep passed the path to `validate` alone - which scopes it to that call
    and puts the ambient document back. `count_examined` then ran against a
    document with no path, so the survey printed the README's contradiction
    and `manifest-floor-mismatch 0` beside it. `--verify` was already right,
    which is what made this survive: the rule works, and only the survey's
    denominator could not see it.

    Catches a fix applied to the rule instead of to the caller that lost the
    document.
    """
    repo = _floor_repo(git_repo, "3.7")
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)

    found = [r for r in doc["runs"][0]["results"]
             if r["ruleId"] == "manifest-floor-mismatch"]
    assert len(found) == 1, doc["runs"][0]["results"]
    examined = _examined(doc)
    assert examined["manifest-floor-mismatch"] >= len(found), examined


def test_a_sweep_counts_a_floor_the_manifest_agrees_with(git_repo) -> None:
    """Examined is the population, not the findings.

    A denominator that only appeared when the rule spoke would report perfect
    coverage of exactly what was wrong and nothing else. The agreeing README
    is examined and clean, which is the number a reader needs to tell a quiet
    rule from a blind one.
    """
    repo = _floor_repo(git_repo, "3.9")
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)

    assert not [r for r in doc["runs"][0]["results"]
                if r["ruleId"] == "manifest-floor-mismatch"], (
        doc["runs"][0]["results"])
    assert _examined(doc)["manifest-floor-mismatch"] == 1, _examined(doc)
