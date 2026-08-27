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
