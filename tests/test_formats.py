"""Machine-readable output: GitHub annotations and SARIF.

These formats are pure rendering of findings that already exist, so there is no
new false-positive surface here. What there IS, is a set of ways to be subtly
wrong that a human reader would never notice: a comma inside an annotation
property silently truncates it, a progress line on stdout makes SARIF
unparseable, and a fingerprint that includes the line number makes every
finding look new the moment text above it shifts.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"


def located(path: str, line: int, kind: str, detail: str, primary: bool = True,
            gating: bool = True, subject: str | None = None):
    from extant_collect import Finding, Located
    return Located(path, Finding(line, kind, detail, subject), primary, gating)


# --- GitHub annotations ------------------------------------------------------

def test_github_annotation_carries_file_line_and_rule() -> None:
    """Catches an annotation missing its location, which GitHub renders as a
    bare log line instead of attaching it to the diff."""
    from extant_collect import format_github

    lines = format_github([located("NEXT_SESSION.md", 6, "dead-sha", "`abc` is gone")])

    assert lines == [
        "::error file=NEXT_SESSION.md,line=6,title=dead-sha::`abc` is gone"
    ]


def test_github_escapes_commas_and_colons_in_properties() -> None:
    """THE bug this escaping exists to prevent.

    GitHub parses `::error k=v,k=v::message`. A raw comma in a filename ends
    the property list early and the annotation lands on the wrong line, or
    nowhere. Silent, and invisible unless you read the rendered PR.
    """
    from extant_collect import format_github

    line = format_github([located("docs/a,b:c.md", 2, "dead-sha", "x")])[0]

    assert "file=docs/a%2Cb%3Ac.md" in line
    # The separator between properties and message must still be the only
    # literal colon pair in the command.
    assert line.count("::") == 2


def test_github_escapes_newlines_in_the_message() -> None:
    """A newline in a detail would end the workflow command early, turning the
    rest of the message into an unrelated log line."""
    from extant_collect import format_github

    line = format_github([located("a.md", 1, "k", "first\nsecond")])[0]

    assert "%0A" in line
    assert line.count("\n") == 0


# --- SARIF -------------------------------------------------------------------

def sarif_of(items) -> dict:
    from extant_collect import format_sarif
    return json.loads(format_sarif(items))


def test_sarif_has_every_field_github_requires() -> None:
    """Pins the required set rather than trusting that it looks right.

    GitHub code scanning rejects an upload missing any of these, and the
    rejection happens server-side, long after the run that produced it.
    """
    doc = sarif_of([located("NEXT_SESSION.md", 6, "dead-sha", "`abc` is gone")])

    assert doc["version"] == "2.1.0"
    assert doc["$schema"]
    run = doc["runs"][0]
    assert run["tool"]["driver"]["name"] == "extant"
    assert run["tool"]["driver"]["rules"], "rule descriptors are required"
    result = run["results"][0]
    assert result["ruleId"] == "dead-sha"
    assert result["message"]["text"]
    assert result["partialFingerprints"], "required to track identity across runs"
    location = result["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "NEXT_SESSION.md"
    assert location["region"]["startLine"] == 6


def test_sarif_rule_descriptions_come_from_the_registry() -> None:
    """The published description IS the falsifiable question.

    Catches descriptors invented separately from the rules, which would drift
    apart silently. The admission test already forces every rule to state its
    question; this makes that statement the thing users read.
    """
    from extant_collect import RULES

    doc = sarif_of([located("a.md", 1, "dead-sha", "x")])
    descriptor = doc["runs"][0]["tool"]["driver"]["rules"][0]
    question = next(r.falsifiable for r in RULES if r.kind == "dead-sha")

    assert question in descriptor["fullDescription"]["text"]
    assert question in descriptor["help"]["text"]


def test_fingerprint_helper_distinguishes_what_it_should() -> None:
    """The helper in isolation: same inputs same answer, different inputs not.

    NOTE that this alone would pass against a caller that folds the line number
    in before calling, which is the mutation that actually matters. The test
    below covers that; this one only pins the helper.
    """
    from extant_collect import _fingerprint

    baseline = _fingerprint("a.md", "dead-sha", "`abc` is gone")
    assert baseline == _fingerprint("a.md", "dead-sha", "`abc` is gone")
    assert baseline != _fingerprint("b.md", "dead-sha", "`abc` is gone")
    assert baseline != _fingerprint("a.md", "dead-md-link", "`abc` is gone")
    assert baseline != _fingerprint("a.md", "dead-sha", "`xyz` is gone")


def test_the_same_finding_on_a_different_line_keeps_its_fingerprint() -> None:
    """The design decision, pinned THROUGH THE REAL PATH.

    partialFingerprints exist so GitHub can tell 'the same problem, moved' from
    'a new problem'. Folding the line in defeats that: inserting a paragraph at
    the top of a document would re-report every finding below it as new.

    Written this way after the direct-helper version was mutated against and
    stayed green. The bug lives in what the CALLER passes, so the assertion has
    to run through format_sarif rather than reach past it.
    """
    before = sarif_of([located("a.md", 6, "dead-sha", "`abc` is gone")])
    after = sarif_of([located("a.md", 91, "dead-sha", "`abc` is gone")])

    fp_before = before["runs"][0]["results"][0]["partialFingerprints"]
    fp_after = after["runs"][0]["results"][0]["partialFingerprints"]

    assert fp_before == fp_after, (
        "the same finding at a new line must keep its identity; the line number "
        "is leaking into the fingerprint"
    )
    # And it must still be a real discriminator, not a constant.
    other = sarif_of([located("a.md", 6, "dead-sha", "`xyz` is gone")])
    assert fp_before != other["runs"][0]["results"][0]["partialFingerprints"]


def test_sarif_of_a_clean_document_is_still_valid() -> None:
    """An empty result set must be a well-formed SARIF document, not an empty
    string. A consumer that always parses stdout would otherwise break on
    exactly the runs that went well."""
    doc = sarif_of([])

    assert doc["version"] == "2.1.0"
    assert doc["runs"][0]["results"] == []


def test_a_finding_that_cannot_fail_the_build_is_not_an_error() -> None:
    """SARIF published EVERY finding at `level: error` while a sweep exited 0.

    The README promises a sweep cannot fail your build and the exit code
    honours it, so a team uploading survey results to code scanning got a wall
    of errors for findings the tool itself calls advisory. The exit code was
    right and the machine format contradicted it.
    """
    survey = sarif_of([located("a.md", 1, "dead-sha", "x", gating=False)])
    gate = sarif_of([located("a.md", 1, "dead-sha", "x", gating=True)])

    assert survey["runs"][0]["results"][0]["level"] == "note"
    assert survey["runs"][0]["results"][0]["properties"]["gates"] is False
    # The control. A fix that downgraded everything would satisfy the line
    # above and quietly stop reporting real failures as failures.
    assert gate["runs"][0]["results"][0]["level"] == "error"
    assert gate["runs"][0]["results"][0]["properties"]["gates"] is True


def test_sarif_carries_the_denominator(tmp_path) -> None:
    """Every other output states what was examined; this one did not.

    A consumer seeing zero results could not distinguish a clean repository
    from a run that checked nothing - the conflation this project exists to
    remove, in its own machine-readable output.
    """
    from extant_collect import format_sarif

    doc = json.loads(format_sarif([], examined={"dead-sha": 12, "raw-lfs-blob": 0}))
    run = doc["runs"][0]

    assert run["properties"]["examined"]["dead-sha"] == 12
    notes = [n["message"]["text"]
             for n in run["invocations"][0]["toolExecutionNotifications"]]
    assert any("dead-sha 12" in n for n in notes), notes
    # A rule that examined nothing is named, not left for the reader to spot
    # in a long line - the same NOTE the text output prints.
    assert any("raw-lfs-blob" in n and "nothing" in n for n in notes), notes


def test_sarif_points_at_the_claim_not_just_the_line(tmp_path) -> None:
    """A bare line number makes an alert that shows no context.

    The snippet is what a code-scanning UI renders, and the columns underline
    the token the claim is about, which `Finding.subject` already carries.
    """
    from extant_collect import format_sarif

    (tmp_path / "a.md").write_text(
        "# Doc\n\nShipped in `abc1234` last week.\n", encoding="utf-8")

    doc = json.loads(format_sarif(
        [located("a.md", 3, "dead-sha", "`abc1234` is gone", subject="abc1234")],
        tmp_path))
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]

    assert region["startLine"] == 3
    assert region["snippet"]["text"] == "Shipped in `abc1234` last week."
    assert region["startColumn"] == 13, region
    assert region["endColumn"] == 20, region


def test_a_missing_file_costs_the_snippet_and_nothing_else(tmp_path) -> None:
    """Presentation degrades; correctness does not. A wrong snippet would
    misreport where a finding is, so anything unreadable is omitted."""
    from extant_collect import format_sarif

    doc = json.loads(format_sarif(
        [located("gone.md", 3, "dead-sha", "x")], tmp_path))
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]

    assert region["startLine"] == 3
    assert "snippet" not in region


def test_a_very_long_line_cannot_bloat_the_upload(tmp_path) -> None:
    """GitHub rejects a SARIF upload over 10 MB, and the longest single
    markdown line in the 39-repository corpus is 123,427 characters.

    One cited base64 image or minified block would have carried the whole line
    into the document, and the rejection arrives long after the run that caused
    it. Columns are dropped when the token sits past the cap rather than
    pointing outside the text a reader can see.
    """
    from extant_collect import format_sarif

    (tmp_path / "a.md").write_text("x" * 120_000 + " `abc1234`\n", encoding="utf-8")

    doc = json.loads(format_sarif(
        [located("a.md", 1, "dead-sha", "gone", subject="abc1234")], tmp_path))
    region = doc["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]

    assert len(region["snippet"]["text"]) < 500, len(region["snippet"]["text"])
    assert "startColumn" not in region, "the token is past the cap"
    # The control: a short line keeps its columns, so the cap has not simply
    # disabled the feature.
    (tmp_path / "b.md").write_text("Shipped in `abc1234`.\n", encoding="utf-8")
    short = json.loads(format_sarif(
        [located("b.md", 1, "dead-sha", "gone", subject="abc1234")], tmp_path))
    assert short["runs"][0]["results"][0]["locations"][0][
        "physicalLocation"]["region"]["startColumn"] == 13


def test_a_sweep_and_a_verify_upload_do_not_replace_each_other() -> None:
    """Code scanning keys runs by `automationDetails.id`. Without one, the
    second upload of the day silently supersedes the first."""
    from extant_collect import format_sarif

    sweep = json.loads(format_sarif([], run_kind="sweep"))
    verify = json.loads(format_sarif([]))

    assert sweep["runs"][0]["automationDetails"]["id"] == "extant/sweep"
    assert verify["runs"][0]["automationDetails"]["id"] == "extant/verify"


# --- end to end --------------------------------------------------------------

def run_in(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )


def build_repo(repo: Path, commit) -> None:
    import shutil
    commit("NEXT_SESSION.md",
           "# Status\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
           "Shipped at `deadbeef1234567`.\n\n## 1. Layout\n", "docs: status")
    shutil.copytree(SKILL_ROOT / "payload", repo / "tools")


def test_sarif_mode_puts_nothing_but_json_on_stdout(git_repo) -> None:
    """THE requirement that makes SARIF usable in a pipeline.

    The denominator summary is genuinely useful and genuinely not JSON. It goes
    to stderr in this mode. Catches a diagnostic line leaking into the document,
    which turns a valid upload into a parse error at the far end.
    """
    repo, commit = git_repo
    build_repo(repo, commit)

    result = run_in(repo, "--validate", "NEXT_SESSION.md", "--format=sarif")

    doc = json.loads(result.stdout)  # raises if anything else was printed
    assert doc["runs"][0]["results"], "expected the dead SHA to be reported"
    assert "checked NEXT_SESSION.md" in result.stderr, (
        "the denominator must still be reported, on stderr"
    )
    assert result.returncode == 1


def test_github_mode_emits_one_annotation_per_finding(git_repo) -> None:
    repo, commit = git_repo
    build_repo(repo, commit)

    result = run_in(repo, "--validate", "NEXT_SESSION.md", "--format=github")

    annotations = [ln for ln in result.stdout.splitlines() if ln.startswith("::")]
    assert len(annotations) == 1
    assert "file=NEXT_SESSION.md" in annotations[0]
    assert "title=dead-sha" in annotations[0]


def test_text_remains_the_default_and_is_unchanged(git_repo) -> None:
    """Catches a formatter rewrite that quietly changes the human output.

    Everything that reads this tool today reads the text form, including the
    git hook that greps its output.
    """
    repo, commit = git_repo
    build_repo(repo, commit)

    result = run_in(repo, "--validate", "NEXT_SESSION.md")

    assert "line 5: [dead-sha]" in result.stdout
    assert "::error" not in result.stdout
    assert not result.stdout.lstrip().startswith("{")
