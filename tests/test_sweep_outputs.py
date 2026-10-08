"""What `--sweep` reports, compared WHOLE.

D7 found 140 of sweep.py's 667 mutants alive after the whole suite, 88 of
them in the report `run_sweep` prints and 24 in what it prints for a
repository with no markdown: the tests asserted single lines, and nothing
about which stream each went to. In SARIF mode the report goes to stderr
and stdout carries the document alone, so a line printed to stdout
corrupts the upload while every `in out` assertion passes.

One repository reaches every branch the report has at once: a configured
primary document and a configured extra, each with a claim; two
translations of one page sharing a dead link, which the text groups; a
vendored document, which the per-stratum breakdown names; an excluded
document beside a pattern that cannot exclude anything and two that match
nothing; two documents that are not UTF-8; a pattern switched off; and two
files the consistency rule finds disagreeing. The report's own wording is
written here once; a line another module words - `session.zero_notes`'
NOTE lines, the unusable-pattern line, the fallback NOTE, the note for
rules that read nothing - is built by that module's function from the
arguments this report must hand it, written out.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import raising_rule

from extant import report, session, sweep
from extant.exclusions import unusable_note
from extant.finding import Finding, Located
from extant.sweep import fallback_note, run_sweep, summarise_strata

DEAD = "dead" + "0" * 36
DEAD_TOO = "beef" + "1" * 36
DEAD_THREE = "cafe" + "2" * 36
B = chr(92)

# Registry order: count_examined seeds every rule, repository ones included.
EXAMINED = {"dead-sha": 3, "stale-live-claim": 0, "unknown-branch": 0,
            "false-merge-claim": 0, "dead-release-tag": 0, "dead-path-pointer": 0,
            "dead-md-link": 2, "dead-md-anchor": 0, "inconsistent-artifact": 2,
            "dead-pinned-ref": 0, "raw-lfs-blob": 0, "manifest-floor-mismatch": 0,
            "dead-line-pointer": 0}
# Every rule read something but the one `merge_claim = ""` switches off.
RAN = set(EXAMINED) - {"false-merge-claim"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _repo(root: Path, files: dict[str, bytes]) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")
    for name, data in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _full(root: Path) -> Path:
    return _repo(root, {
        ".extant.toml": (
            'primary_doc = "STATUS.md"\n'
            'extra_docs = ["docs/guide.md"]\n'
            'exclude_paths = ["drafts/**", "!keep.md", "nothing-here/**", '
            '"nor-here/**"]\n'
            'merge_claim = ""\n\n'
            "[extant.consistency.version]\n"
            '"VERSION" = ' + "'(" + B + "S+)'\n"
            '"pyproject.toml" = ' + "'^version = " + '"([^"]+)"' + "'\n").encode(),
        "STATUS.md": (f"# Status\n\n## Phase 1 - Start (2026-01-01)\n\n"
                      f"Merged at `{DEAD}`.\n").encode(),
        "docs/guide.md": f"# Guide\n\nSee `{DEAD_TOO}`.\n".encode(),
        "docs/en/a.md": b"# A\n\nSee [the page](missing.md).\n",
        "docs/ko/a.md": b"# A\n\nSee [the page](missing.md).\n",
        "vendor/lib/README.md": f"# Lib\n\nSee `{DEAD_THREE}`.\n".encode(),
        "drafts/x.md": f"# X\n\nSee `{DEAD}`.\n".encode(),
        "bad.md": b"# Bad\n\nCaf\xe9.\n",
        "bad2.md": b"# Bad2\n\xff\n",
        "VERSION": b"1.0\n",
        "pyproject.toml": b'version = "2.0"\n',
    })


def _sweep(repo: Path, fmt: str) -> int:
    session.reload_config(repo)
    return run_sweep(repo, fmt)


def _notes(examined: dict[str, int], ran: set[str], *,
           primary_read: bool) -> list[str]:
    """The NOTE lines, from the arguments the report must hand
    `session.zero_notes`."""
    return session.zero_notes(
        examined, ran, did="examined nothing anywhere here",
        claims="no document makes such claims", primary_read=primary_read,
        absent="none is here", read="swept")


SECTIONS = [
    "",
    "CONFIGURED - these decide the exit code",
    f"line 5: [dead-sha] `{DEAD}` does not resolve in this repo",
    f"docs/guide.md: line 3: [dead-sha] `{DEAD_TOO}` does not resolve in this repo",
    "",
    "UNREVIEWED - surveyed only, not gated",
    "[dead-md-link] links to `missing.md`, which does not exist   "
    "(2 occurrences in 2 documents)",
    "    docs/en/a.md:3",
    "    docs/ko/a.md:3",
    f"vendor/lib/README.md: line 3: [dead-sha] `{DEAD_THREE}` does not resolve "
    "in this repo",
    "",
    "REPOSITORY - about the repository itself, not gated",
    ".extant.toml: line 1: [inconsistent-artifact] `version` disagrees across "
    "files: `1.0` in VERSION; `2.0` in pyproject.toml",
]


def _summary(*, entries: bool, workers: int = 0, fallback: str | None = None) -> list[str]:
    """Every line after the sections. Only the text groups, so only the text
    says how many entries the findings were reported as."""
    lines = ["",
             "swept 7 markdown file(s): 2 configured (2 finding(s)), "
             "5 unreviewed (3 finding(s))"]
    if entries:
        lines.append("  reported as 5 entr(y/ies): findings differing only in one "
                     "directory segment are grouped, and every document is named")
    lines += ["  5 finding(s) in ordinary documents; 1 elsewhere:",
              "    vendored  1 finding(s) in 1 of 1 document(s)"]
    if workers:
        lines.append(f"  surveyed across {workers} worker process(es)")
    lines += fallback_note(fallback)
    lines += [
        "  excluded 1 of 8 tracked file(s) via 4 exclude_paths pattern(s)",
        "        0 !keep.md",
        "        1 drafts/**",
        "        0 nor-here/**",
        "        0 nothing-here/**",
        str(unusable_note(["!keep.md", "drafts/**", "nor-here/**",
                           "nothing-here/**"])),
        "  matched nothing, so they exclude nothing and may be stale: "
        "nor-here/**, nothing-here/**",
        "  2 repository-wide rule(s) ran once (1 finding(s))",
        "  examined: " + ", ".join(f"{kind} {n}" for kind, n in EXAMINED.items()),
        *_notes(EXAMINED, RAN, primary_read=True),
        "  2 could not be read: bad.md (UnicodeDecodeError), bad2.md "
        "(UnicodeDecodeError)",
        "  unreviewed findings do not affect the exit code. Some will be "
        "examples rather than claims; move a file into extra_docs once you have "
        "read them.",
    ]
    return lines


def _sarif(out: str, *, also: list[str] | None = None) -> None:
    """The one run on stdout: a result per finding, gating as its section
    does, the denominator and the NOTE lines (and any line `also` adds),
    and the rule switched off, named as a sweep's run."""
    run: dict[str, Any] = json.loads(out)["runs"][0]
    assert run["automationDetails"] == {"id": "extant/sweep"}
    located = [(r["ruleId"], r["level"], r["properties"],
                r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
                r["locations"][0]["physicalLocation"]["region"]["startLine"])
               for r in run["results"]]
    ordinary = "ordinary"
    assert located == [
        ("dead-sha", "error", {"gates": True, "stratum": ordinary}, "STATUS.md", 5),
        ("dead-sha", "error", {"gates": True, "stratum": ordinary}, "docs/guide.md", 3),
        ("dead-md-link", "note", {"gates": False, "stratum": ordinary},
         "docs/en/a.md", 3),
        ("dead-md-link", "note", {"gates": False, "stratum": ordinary},
         "docs/ko/a.md", 3),
        ("dead-sha", "note", {"gates": False, "stratum": "vendored"},
         "vendor/lib/README.md", 3),
        ("inconsistent-artifact", "note", {"gates": False, "stratum": ordinary},
         ".extant.toml", 1)]
    assert run["results"][0]["locations"][0]["physicalLocation"]["region"][
        "snippet"] == {"text": f"Merged at `{DEAD}`."}
    summary = ", ".join(f"{kind} {n}" for kind, n in EXAMINED.items())
    assert run["invocations"] == [{
        "executionSuccessful": True,
        "toolExecutionNotifications": [
            {"level": "note", "message": {"text": f"examined: {summary}"}},
            *({"level": "warning",
               "message": {"text": line.strip().removeprefix("NOTE: ")}}
              for line in (also or []) + _notes(EXAMINED, RAN, primary_read=True))],
        "ruleConfigurationOverrides": [
            {"descriptor": {"id": "false-merge-claim", "index": 3},
             "configuration": {"enabled": False}}],
    }]
    assert run["properties"] == {"examined": EXAMINED}


def test_the_text_report_is_compared_whole(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """With GitHub's SARIF limit at 0, so every finding would be cut from a
    SARIF run: the text report names no such cut, because it has none."""
    monkeypatch.setattr(report, "SARIF_RESULT_LIMIT", 0)
    repo = _full(tmp_path)
    code = _sweep(repo, "text")
    out, err = capsys.readouterr()
    assert (code, out, err) == (1, "\n".join(SECTIONS + _summary(entries=True)) + "\n", "")


def test_in_sarif_the_document_alone_is_on_stdout(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _full(tmp_path)
    code = _sweep(repo, "sarif")
    out, err = capsys.readouterr()
    assert (code, err) == (1, "\n".join(_summary(entries=False)) + "\n")
    _sarif(out)


def test_a_parallel_sweep_says_how_many_workers_read_it(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 1)
    repo = _full(tmp_path)
    code = _sweep(repo, "sarif")
    out, err = capsys.readouterr()
    workers = min(sweep._MAX_WORKERS, os.cpu_count() or 1)
    assert (code, err) == (1, "\n".join(_summary(entries=False, workers=workers)) + "\n")
    _sarif(out)


def test_a_pool_that_cannot_start_is_said_to_have_fallen_back(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no pool here")

    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 1)
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", refused)
    repo = _full(tmp_path)
    code = _sweep(repo, "sarif")
    out, err = capsys.readouterr()
    reason = "OSError: no pool here"
    assert (code, err) == (1, "\n".join(_summary(entries=False, fallback=reason)) + "\n")
    _sarif(out, also=fallback_note(reason))


def test_the_documents_the_survey_lost_are_named_and_fail_the_run(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A document dispatched and never returned was not examined, and a run
    that lost one cannot pass. The documents after it are still read: the
    vendored claim is in the last of them."""
    real = sweep.survey

    def losing(*args: Any, **kwargs: Any) -> Any:
        gathered, workers, fallback = real(*args, **kwargs)
        return ({k: v for k, v in gathered.items()
                 if k not in ("docs/en/a.md", "docs/ko/a.md")}, workers, fallback)

    monkeypatch.setattr(sweep, "survey", losing)
    repo = _full(tmp_path)
    code = _sweep(repo, "sarif")
    _out, err = capsys.readouterr()
    assert code == 1
    assert "5 unreviewed (1 finding(s))\n" in err, err
    assert ("\n  2 document(s) were dispatched and returned no result, so they "
            "were NOT examined: docs/en/a.md, docs/ko/a.md\n") in err, err


def test_a_rule_that_raised_is_named_once_on_stderr_beside_the_sarif(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {"notes.md": b"# Notes\n"})
    with raising_rule() as broken:
        session.reload_config(repo)
        code = run_sweep(repo, "sarif")
    out, err = capsys.readouterr()
    assert code == 1
    assert json.loads(out)["runs"][0]["invocations"][0]["executionSuccessful"] is False
    line = (f"  ERRORED: {broken.kind} raised RuntimeError: deliberate. A rule "
            "that raised has not found nothing, it has failed to look, so this "
            "run is not a pass.")
    assert err.count("ERRORED:") == 1, err
    assert f"\n{line}\n" in err, err


def test_an_unconfigured_repository_is_told_nothing_can_fail(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {"notes.md": f"# Notes\n\nSee `{DEAD}`.\n".encode()})
    code = _sweep(repo, "text")
    out = capsys.readouterr().out
    examined = dict.fromkeys(EXAMINED, 0)
    examined["dead-sha"] = 1
    ran = set(examined) - {"stale-live-claim", "unknown-branch",
                           "inconsistent-artifact"}
    assert (code, out) == (0, "\n".join([
        "",
        "UNREVIEWED - surveyed only, not gated",
        f"notes.md: line 3: [dead-sha] `{DEAD}` does not resolve in this repo",
        "",
        "swept 1 markdown file(s): 0 configured (0 finding(s)), 1 unreviewed "
        "(1 finding(s))",
        "  1 repository-wide rule(s) ran once (0 finding(s))",
        "  examined: " + ", ".join(f"{kind} {n}" for kind, n in examined.items()),
        *_notes(examined, ran, primary_read=False),
        "  nothing is configured, so nothing here can fail. Set primary_doc or "
        "extra_docs in .extant.toml to gate on a file.",
    ]) + "\n")


def test_a_repository_of_restructuredtext_says_which_rules_read_none(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The markdown rules read nothing, because nothing here is markdown, and
    the NOTE lines say what kind of document none swept was."""
    repo = _repo(tmp_path, {"guide.rst": b"Guide\n=====\n\nNothing yet.\n"})
    code = _sweep(repo, "text")
    out = capsys.readouterr().out
    examined = dict.fromkeys(EXAMINED, 0)
    ran = set(examined) - {"stale-live-claim", "unknown-branch",
                           "inconsistent-artifact", "dead-md-link", "dead-md-anchor"}
    assert (code, out) == (0, "\n".join([
        "",
        "swept 1 markdown file(s): 0 configured (0 finding(s)), 1 unreviewed "
        "(0 finding(s))",
        "  1 repository-wide rule(s) ran once (0 finding(s))",
        "  examined: " + ", ".join(f"{kind} 0" for kind in examined),
        *_notes(examined, ran, primary_read=False),
        "  nothing is configured, so nothing here can fail. Set primary_doc or "
        "extra_docs in .extant.toml to gate on a file.",
    ]) + "\n")


def test_exclusions_that_remove_everything_are_said_on_stderr(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": b'exclude_paths = ["docs/**"]\n',
                            "docs/x.md": b"# X\n"})
    code = _sweep(repo, "text")
    out, err = capsys.readouterr()
    assert (code, out, err) == (
        0, "", "swept 0 markdown files: exclude_paths removed all 1 that git tracks\n")


@pytest.mark.parametrize("fmt", ["text", "sarif"])
def test_a_repository_with_no_markdown_still_reports(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], fmt: str) -> None:
    """The diagnostic on stderr in every format; a machine format still
    emits its document - every rule at zero, the rules that read nothing
    said apart, the rule switched off named."""
    repo = _repo(tmp_path, {".extant.toml": b'merge_claim = ""\n'})
    code = _sweep(repo, fmt)
    out, err = capsys.readouterr()
    assert (code, err) == (0, "swept 0 markdown files: git tracks none in this "
                              "repository\n")
    if fmt == "text":
        assert out == ""
        return
    run = json.loads(out)["runs"][0]
    zeros = {rule.kind: 0 for rule in session.RULES}
    unread = session.unrun_note(list(session.RULES), primary_read=False,
                                absent="none is here", read="swept")
    assert unread is not None
    assert (run["automationDetails"], run["results"], run["properties"]) == (
        {"id": "extant/sweep"}, [], {"examined": zeros})
    summary = ", ".join(f"{kind} 0" for kind in zeros)
    assert run["invocations"] == [{
        "executionSuccessful": True,
        "toolExecutionNotifications": [
            {"level": "note", "message": {"text": f"examined: {summary}"}},
            {"level": "warning",
             "message": {"text": unread.strip().removeprefix("NOTE: ")}}],
        "ruleConfigurationOverrides": [
            {"descriptor": {"id": "false-merge-claim", "index": 0},
             "configuration": {"enabled": False}},
            {"descriptor": {"id": "inconsistent-artifact", "index": 1},
             "configuration": {"enabled": False}}],
    }]


def test_a_breakdown_with_no_ordinary_finding_says_zero() -> None:
    """Every finding elsewhere: the ordinary count leads anyway, at 0."""
    found = [Located("vendor/x.md", Finding(1, "dead-sha", "d"), False, False,
                     "vendored")]
    assert summarise_strata(found, ["vendor/x.md", "a.md"]) == [
        "  0 finding(s) in ordinary documents; 1 elsewhere:",
        "    vendored  1 finding(s) in 1 of 1 document(s)"]
