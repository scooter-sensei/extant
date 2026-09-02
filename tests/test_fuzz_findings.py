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
import re
import shutil
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


# --- seed 20260824, property DENOMINATOR: one fault reported twice ------


def _lfs_repo(git_repo) -> Path:
    """A raw blob at a path `.gitattributes` routes through an LFS filter.

    Written past the filter with `hash-object --no-filters` and straight into
    the index, because `git add` cannot produce this shape on a machine with
    git-lfs installed: the clean filter converts the file on the way in and a
    correct pointer reaches the tree, so the rule finds nothing and the test
    passes without testing anything. `_lfs_finalize` in
    tests/harnesses/fuzz_shapes.py records the two configurations that fail
    more quietly still.
    """
    repo, commit = git_repo
    commit(".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n",
           "chore: route the binaries through LFS")
    commit("NEXT_SESSION.md", "# S\n\nNothing to see.\n",
           "docs: a status document with no claims")
    blob = repo / "asset-raw.bin"
    blob.write_bytes(b"not a pointer, just bytes\n" + b"x" * 300)
    run = ["git", "-C", str(repo)]
    sha = subprocess.run(run + ["hash-object", "-w", "--no-filters", "--",
                                "asset-raw.bin"],
                         capture_output=True, text=True).stdout.strip()
    subprocess.run(run + ["update-index", "--add", "--cacheinfo",
                          f"100644,{sha},asset-raw.bin"], capture_output=True)
    subprocess.run(run + ["commit", "-qm", "chore: a raw blob under a filter"],
                   capture_output=True)
    return repo


def test_a_repository_rule_reports_its_one_fault_once(git_repo) -> None:
    """One repository, one raw blob, one finding.

    A repository-scoped rule reads no document, and `--sweep` ran it twice:
    once inside the pass for whichever document was primary, and once in its
    own repository pass. The same blob printed bare and again under
    `.gitattributes:`, against a denominator that counts the governed file
    once - so found was 2 from examined 1. `inconsistent-artifact` is the same
    rule shape and did the same.

    Catches a fix that leaves the rule running twice.
    """
    repo = _lfs_repo(git_repo)
    doc = json.loads(_sweep(repo, "--format=sarif").stdout)

    found = [r for r in doc["runs"][0]["results"]
             if r["ruleId"] == "raw-lfs-blob"]
    assert len(found) == 1, doc["runs"][0]["results"]
    assert _examined(doc)["raw-lfs-blob"] >= len(found), _examined(doc)


def test_that_fault_is_attributed_to_the_file_that_declares_it(
        git_repo) -> None:
    """WHERE the surviving copy points, which is the half a count cannot see.

    The two copies were not interchangeable: one was attributed to the status
    document that happens to be primary, and one to `.gitattributes`, which is
    the file the answer actually lives in. Dropping either would have made the
    count right; only one of them sends a reader to the right file.

    Catches a fix that de-duplicated by keeping the document-attributed copy,
    and one that dropped the repository pass instead of the per-document run.
    """
    repo = _lfs_repo(git_repo)
    lines = [line for line in _sweep(repo).stdout.splitlines()
             if "[raw-lfs-blob]" in line]

    assert len(lines) == 1, lines
    assert lines[0].startswith(".gitattributes:"), lines[0]


# --- seed 4242, property CRASH: a mode that only ever crashed ----------

DOC = "# Status\n\n## Phase 1 - x\n\nWork.\n"


def _installed(repo: Path) -> Path:
    """Copy the payload in as `tools/`, which is how a real project holds it.

    Needed rather than tidy. `extant_collect.py` loads settings RELATIVE TO
    ITSELF - it says so on stderr when they differ - so driving the payload in
    place with `--repo <tmp>` reads THIS project's `.extant.toml` and answers
    about the wrong configuration. `_sweep` above escapes that only because
    `--sweep` needs no config at all.
    """
    shutil.copytree(PAYLOAD, repo / "tools", dirs_exist_ok=True)
    return repo / "tools" / "extant_collect.py"


def _collect(repo: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(_installed(repo)), "--collect", *extra,
         "--repo", str(repo)],
        cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_collect_without_a_project_interpreter_reports_rather_than_crashes(
        git_repo) -> None:
    """No `.venv`, so `suite_command` cannot resolve - and that is not a bug.

    `run_suite` raises RuntimeError here on purpose, and its docstring says the
    point was to replace "an uncaught FileNotFoundError crashing /extant step
    1" with something actionable. The message became actionable and the crash
    did not go away: nothing caught it, so a carefully written paragraph
    arrived inside a traceback.

    It survived because `--collect` was one of four modes `fuzz.py` never ran.
    Every generated repository lacks a `.venv`, so this was not an edge case
    there - it was the mode's ONLY behaviour, and the first fuzz run that
    included `--collect` reported CRASH on it.

    Catches a fix that removes the message, and one that lets the exception
    back out.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")

    done = _collect(repo)

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert "no project interpreter found" in done.stderr, done.stderr


def test_collect_writes_a_bundle_when_the_suite_command_needs_no_interpreter(
        git_repo) -> None:
    """The other half, and the reason the generator now sets `suite_command`.

    Without a runnable command every `--collect` run declines at the same
    point, so the mode exercises argument parsing rather than the 350 lines of
    collect.py behind it. This pins that the path past the refusal still works,
    so a fix to the refusal cannot quietly break the case it guards.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n'
        'suite_command = ["git", "--version"]\n', encoding="utf-8")

    done = _collect(repo)

    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert (repo / "status_bundle.json").is_file(), done.stdout
    json.loads((repo / "status_bundle.json").read_text(encoding="utf-8"))


# --- seed 20260824, property CRASH: the one mode that rewrites --------

def _archive(repo: Path):
    return subprocess.run(
        [sys.executable, str(_installed(repo)), "--archive", "--repo", str(repo)],
        cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_archive_refuses_an_undecodable_document_rather_than_crashing(
        git_repo) -> None:
    """A UTF-16 status document met the only irreversible write in the product.

    Every other mode guards this read - `--validate`, `--verify`, `--selftest`
    and `--check-text` all report "not valid UTF-8" and refuse. `--archive` let
    the exception out, so an undecodable document produced an unhandled
    traceback from `entries.archive` instead of a diagnostic.

    Nothing had been written when it raised, since the read is the first thing
    `archive` does. What was wrong is that a crash is not an answer, and this
    mode's crash is indistinguishable from one that failed halfway through
    rewriting the document.

    It survived because `--archive` was one of four modes `fuzz.py` never ran,
    and because no generated repository had ever carried a document that was
    not UTF-8. Stage 6 added both, and the pinned CI seed found it.

    Catches a fix that lets the exception back out, and one that "helpfully"
    reads with errors="replace" - which would archive corrupted text.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")
    doc = repo / "NEXT_SESSION.md"
    doc.write_bytes(DOC.encode("utf-16"))
    before = doc.read_bytes()

    done = _archive(repo)

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert done.returncode == 1, (done.returncode, done.stdout, done.stderr)
    assert "not valid UTF-8" in done.stderr, done.stderr
    assert doc.read_bytes() == before, "the document was modified"


# --- Stage 6 gap audit: a CR-only document lost two rules --------------

ENTRY_DOC = (
    "# Status\n\n## Phase 2 - newest\n\n"
    "Work continued on `claude/never-existed` this phase.\n"
    "Branch `claude/also-gone` is NOT yet merged.\n\n"
    "## Phase 1 - old\n\nEarlier.\n"
)


def _validate(repo: Path):
    return subprocess.run(
        [sys.executable, str(_installed(repo)), "--validate", "NEXT_SESSION.md",
         "--repo", str(repo)],
        cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def _denominators(out: str) -> dict:
    counts = {}
    for part in out.split("checked NEXT_SESSION.md:")[-1].split("\n")[0].split(","):
        bits = part.strip().rsplit(" ", 1)
        if len(bits) == 2 and bits[1].isdigit():
            counts[bits[0]] = int(bits[1])
    return counts


def test_entry_rules_read_a_document_written_with_bare_carriage_returns(
        git_repo) -> None:
    """The same claims, in three line endings, examined the same number of times.

    `^` in a MULTILINE pattern follows a NEWLINE, and a bare `\r` is not one,
    so `split_entries` found no sections in a CR-only document and every rule
    that reads the newest entry examined ZERO candidates. Measured before the
    fix: LF reported `stale-live-claim 2, unknown-branch 2` and CR-only
    reported 0 and 0, printed beside every other rule's honest count.

    That is the exact conflation this project exists to remove - "nothing was
    checked" wearing the appearance of "nothing was wrong" - and it was
    arriving inside the denominator built to prevent it. `entries.archive`
    already normalised for this reason and said so; the fix lived in one of six
    callers.

    Asserts the DENOMINATOR, not the findings, because the denominator is the
    half that was lying. Catches a fix that normalises by collapsing CRLF too,
    which would shrink the text and move every offset.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY_DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")
    doc = repo / "NEXT_SESSION.md"

    seen = {}
    for name, body in (("lf", ENTRY_DOC),
                       ("crlf", ENTRY_DOC.replace("\n", "\r\n")),
                       ("cr", ENTRY_DOC.replace("\n", "\r"))):
        doc.write_bytes(body.encode("utf-8"))
        seen[name] = _denominators(_validate(repo).stdout)

    for name, counts in seen.items():
        assert counts.get("stale-live-claim") == 2, (name, counts)
        assert counts.get("unknown-branch") == 2, (name, counts)


def test_normalising_a_bare_cr_does_not_move_any_offset(git_repo) -> None:
    """Line numbers survive the normalisation, which is why it is length-preserving.

    A CR-only document reports its findings at the lines they are actually on.
    Collapsing `\r\n` as well would shrink the text and shift every offset
    after the first line ending - the `strip_code` contract, broken once
    already on this axis at a cost of 1627 characters.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY_DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")
    doc = repo / "NEXT_SESSION.md"

    lines = {}
    for name, body in (("lf", ENTRY_DOC),
                       ("crlf", ENTRY_DOC.replace("\n", "\r\n")),
                       ("cr", ENTRY_DOC.replace("\n", "\r"))):
        doc.write_bytes(body.encode("utf-8"))
        lines[name] = sorted(
            int(n) for n in re.findall(r"^line (\d+): \[unknown-branch\]",
                                       _validate(repo).stdout, re.M))

    assert lines["lf"] == [5, 6], lines
    assert lines["crlf"] == lines["lf"], lines
    assert lines["cr"] == lines["lf"], lines


def _sha_map_run(repo: Path, map_path: str, *extra: str):
    """Drive `--sha-map` through the real entry point, as a consumer would."""
    return subprocess.run(
        [sys.executable, str(_installed(repo)), "--validate",
         "NEXT_SESSION.md", "--sha-map", map_path, *extra,
         "--repo", str(repo)],
        cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_sha_map_naming_a_missing_file_reports_rather_than_crashes(
        git_repo) -> None:
    """`--sha-map` opened its path directly, so a map that is not there crashed.

    `load_sha_map` called `open()` with no handler above it, so naming a map
    that does not exist exited with an uncaught FileNotFoundError, a stack
    trace, and nothing a reader could act on. `run_validate` argues one screen
    above that "a traceback here is a poor answer to a common situation" for a
    missing document; this flag had the opposite behaviour for the same shape
    of mistake.

    It is a COMMON situation rather than an exotic one. The README's own
    invocation is `--sha-map .git/filter-repo/commit-map`, and that path does
    not exist until somebody has actually run `git filter-repo` - so copying
    the documented line before rewriting anything reaches this, as does running
    it from the wrong directory.

    It survived because `--sha-map` was a flag `fuzz.py` never passed. The
    `commit-map` axis had been writing a map and confirming that `dead-sha`
    consults it, which is the rule's half; nothing had ever exercised the
    rewriter's half. Adding the mode found this on the first run.

    Catches a fix that removes the message, and one that lets the exception
    back out.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")

    done = _sha_map_run(repo, ".git/filter-repo/commit-map")

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert "cannot read the rewrite map" in done.stderr, done.stderr
    # A REFUSAL IS STRUCTURAL, not just a message: nothing on stdout, the
    # diagnostic on stderr, a non-zero exit. `fuzz.py` recognises a refusal by
    # exactly that shape, so a fix that printed this to stdout would be counted
    # as a run that concluded.
    assert not done.stdout.strip(), done.stdout


def test_check_text_refuses_an_unreadable_sha_map_the_same_way(
        git_repo) -> None:
    """The second call site, which is the half that makes this one finding.

    `--validate` and `--check-text` both read `--sha-map`, and both opened it
    directly. Fixing one would leave the other crashing on the same input -
    "one claim, two scanners", which is the defect this project keeps finding
    and which hides especially well here because both call sites looked right.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")

    done = subprocess.run(
        [sys.executable, str(_installed(repo)), "--check-text",
         "--as-path", "NEXT_SESSION.md", "--sha-map", "nowhere/commit-map",
         "--repo", str(repo)],
        cwd=str(repo), input=DOC,
        capture_output=True, text=True, encoding="utf-8", errors="replace")

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert done.returncode == 2, (done.returncode, done.stdout, done.stderr)
    assert "cannot read the rewrite map" in done.stderr, done.stderr
    assert not done.stdout.strip(), done.stdout


def test_sha_map_still_rewrites_the_document_when_the_map_is_there(
        git_repo) -> None:
    """The other half of the fix: refusing must not have cost the repair.

    A guard that turned a crash into a refusal for EVERY input would pass the
    two tests above and silently disable the flag - the fail-open shape one
    level up. So this pins the success path: a dead SHA claimed, a real
    commit-map beside it, and the document rewritten in place to name the
    replacement.
    """
    repo, commit = git_repo
    dead = "deadbeef1234" + "0" * 28
    doc = (f"# Status\n\nRecorded at `{dead[:12]}` in the log.\n\n"
           f"## Phase 1 - x\n\nWork.\n")
    commit("NEXT_SESSION.md", doc, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True).stdout.strip()
    map_dir = repo / ".git" / "filter-repo"
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "commit-map").write_text(f"old new\n{dead} {head}\n",
                                        encoding="utf-8")

    done = _sha_map_run(repo, str(map_dir / "commit-map"))

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    rewritten = (repo / "NEXT_SESSION.md").read_text(encoding="utf-8")
    assert head[:12] in rewritten, rewritten
    assert dead[:12] not in rewritten, rewritten


def _search(repo: Path, needle: str = "Phase"):
    """Drive `--search` through the real entry point, as a consumer would."""
    return subprocess.run(
        [sys.executable, str(_installed(repo)), "--search", needle,
         "--repo", str(repo)],
        cwd=str(repo),
        capture_output=True, text=True, encoding="utf-8", errors="replace")


CONFIG = 'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n'


def test_search_on_a_utf16_document_reports_rather_than_crashes(
        git_repo) -> None:
    """`--search` read its documents with no handler, so UTF-16 killed it.

    The same finding as `--archive` above, one mode over and found the same
    way. `search_entries` opened both documents with `encoding="utf-8"` and
    nothing above the call, so a status document that is not UTF-8 exited with
    a UnicodeDecodeError out of `codecs` rather than the sentence `--validate`
    prints for the same file.

    It survived because the pairing needs a mode and an encoding that had never
    been drawn together: `--search` was one of the four modes `fuzz.py` never
    ran until Stage 6, and the encoding axis is what first built a document
    that was not UTF-8. Adding `--sha-map` reshuffled the (git state, mode)
    walk, the pair came up, and the fuzzer reported CRASH.

    Catches a fix that lets the exception back out, and one that reads with
    errors="replace" - which would search silently corrupted text and report
    matches against bytes that are not there.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(CONFIG, encoding="utf-8")
    (repo / "NEXT_SESSION.md").write_bytes(DOC.encode("utf-16"))

    done = _search(repo)

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert done.returncode == 1, (done.returncode, done.stdout, done.stderr)
    assert "not valid UTF-8" in done.stderr, done.stderr
    assert "NEXT_SESSION.md" in done.stderr, done.stderr
    # A refusal is STRUCTURAL, not just a message: `fuzz.py` recognises one by
    # a non-zero exit with nothing on stdout and a diagnostic on stderr, so a
    # fix that printed this to stdout would be counted as a run that concluded.
    assert not done.stdout.strip(), done.stdout


def test_search_names_the_archive_when_the_archive_is_the_bad_one(
        git_repo) -> None:
    """It must name the document that failed, not the one it guessed.

    `--search` reads TWO documents - the live one and the archive - which is
    the whole reason it beats `grep`, and it is also why the `--archive` fix
    could not simply be copied. That one catches the bare UnicodeDecodeError at
    the CLI boundary and names `primary_doc`, which is safe only because it
    reads one document; done here it would report the live document as
    undecodable whenever the ARCHIVE was the unreadable one.

    A diagnostic naming the wrong file is a false claim about the repository,
    which is the one thing this tool exists not to make - so the path travels
    out with the error.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(CONFIG, encoding="utf-8")
    archive = repo / "docs" / "status-archive.md"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(DOC.encode("utf-16"))

    done = _search(repo)

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert done.returncode == 1, (done.returncode, done.stdout, done.stderr)
    assert "status-archive.md" in done.stderr, done.stderr


def test_search_still_finds_entries_when_both_documents_are_readable(
        git_repo) -> None:
    """The other half: refusing must not have cost the search.

    A guard that refused for every input would pass both tests above and
    silently disable the mode - the fail-open shape one level up.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(CONFIG, encoding="utf-8")

    done = _search(repo)

    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert "Phase 1" in done.stdout, done.stdout


def test_archive_on_a_missing_document_reports_rather_than_crashes(
        git_repo) -> None:
    """`primary_doc` naming a file that is not there, at the irreversible write.

    `entries.archive` opens `primary_doc` as the first thing it does, and
    nothing above the call looked. So a config naming a document that does not
    exist - a typo, a file not created yet, a `primary_doc` left pointing at one
    that was renamed - reached the only irreversible file operation in the
    product with an unhandled FileNotFoundError.

    `run_validate` refuses the same input three functions away and says which of
    the two things to fix, naming the setting AND where it was read from. "No
    such file" alone does not tell anyone whether the config or the document is
    wrong.

    This is the SECOND way into the same crash. The first was an undecodable
    document, above, found when `--archive` joined the fuzzer's modes; this one
    needs the deliberately broken config as well, which is a different draw. It
    reproduced at about one seed in five and was the last property violation the
    harness reported against the shipped tool.

    Catches a fix that lets the exception back out, and one that reports without
    naming the setting.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", DOC, "docs: a status document")
    (repo / ".extant.toml").write_text(
        'primary_doc = "missing-on-purpose.md"\ntrunk = "main"\n',
        encoding="utf-8")

    done = _archive(repo)

    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert done.returncode == 1, (done.returncode, done.stdout, done.stderr)
    assert "no such document" in done.stderr, done.stderr
    assert "missing-on-purpose.md" in done.stderr, done.stderr
    # The SETTING and its SOURCE, not just the path: the reader has to be able
    # to tell which of the two is the thing to change.
    assert "primary_doc is" in done.stderr, done.stderr
    assert ".extant.toml" in done.stderr, done.stderr
    # Structurally a refusal - nothing on stdout - because `fuzz.py` recognises
    # one that way, and because this mode's stdout carries `retained=/archived=`.
    assert not done.stdout.strip(), done.stdout


def test_archive_still_archives_when_the_document_is_there(git_repo) -> None:
    """The other half: guarding the read must not have disabled the write.

    A guard that refused for every input would pass the test above and silently
    stop archiving - the fail-open shape one level up, in the one operation here
    that cannot be undone.
    """
    repo, commit = git_repo
    entries = "\n".join(
        [f"## Phase {n} - x\n\nWork {n}.\n" for n in range(9, 0, -1)])
    commit("NEXT_SESSION.md", f"# Status\n\n{entries}", "docs: many entries")
    (repo / ".extant.toml").write_text(
        'primary_doc = "NEXT_SESSION.md"\ntrunk = "main"\n', encoding="utf-8")

    done = _archive(repo)

    assert done.returncode == 0, (done.returncode, done.stdout, done.stderr)
    assert "retained=" in done.stdout, done.stdout
    assert "archived=" in done.stdout, done.stdout
