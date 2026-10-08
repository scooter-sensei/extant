"""What `--introduced-since` reports, compared WHOLE.

D7 found 142 of introduced_since.py's 574 mutants alive after the whole
suite, 93 of them in `run_introduced_since`: the tests asserted single
lines of its report, and not at all which stream each went to. In SARIF
mode the report's lines go to stderr and the document alone to stdout, so
a line printed to the wrong stream corrupts the upload while every
`in out` assertion still passes.

One range, built to reach every branch the report has at once, with two of
everything the report counts or lists: claims on lines the range wrote and
on lines it did not, a document line that reads like a diff header between
two hunks, a binary document with spaces and " and " in its name and a
deleted one, an excluded document beside a pattern that cannot exclude
anything, two documents with a bare carriage return and two that are not
UTF-8, one the range left alone, a pattern switched off and two
repository rules. The report's own wording is written here once; a line
another module words - the NOTE lines `session.zero_notes` writes, the
unusable-pattern line, the fallback NOTE - is built by that module's
function from the arguments this report must hand it, written out.
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import raising_rule

from extant import report, session, sweep
from extant.exclusions import unusable_note
from extant.introduced_since import run_introduced_since
from extant.sweep import fallback_note

DEAD = "dead" + "0" * 36
DEAD_TOO = "beef" + "1" * 36
DEAD_THREE = "cafe" + "2" * 36

# Registry order, every rule but the two repository-scoped ones.
EXAMINED = {"dead-sha": 5, "stale-live-claim": 0, "unknown-branch": 0,
            "false-merge-claim": 0, "dead-release-tag": 0, "dead-path-pointer": 0,
            "dead-md-link": 0, "dead-md-anchor": 0, "dead-pinned-ref": 0,
            "manifest-floor-mismatch": 0, "dead-line-pointer": 0}
ENTRY_RULES = {"stale-live-claim", "unknown-branch"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _write(repo: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _init(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")
    return repo


def _commit(repo: Path, files: dict[str, bytes], message: str) -> None:
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)


def _range(root: Path) -> Path:
    """The base commit, branch `base`, and the range on top of it."""
    repo = _init(root)
    _commit(repo, {
        ".extant.toml": b'exclude_paths = ["excluded/**", "!keep.md"]\n'
                        b'merge_claim = ""\n\n'
                        b'[extant.consistency.version]\n'
                        b'"one.txt" = \'v(\\S+)\'\n'
                        b'"two.txt" = \'v(\\S+)\'\n',
        "docs/a.md": (f"# A\n\nOld claim `{DEAD_TOO}`.\n\n"
                      f"Middle `{DEAD_THREE}`.\n").encode(),
        "docs/keep.md": b"# Keep\n",
        "cats and dogs.md": b"# Pets\n\x00\n",
        "gone.md": b"# Gone\n\x00\n",
        "excluded/x.md": b"# X\n",
        "cr.md": b"# CR\n",
        "cr2.md": b"# CR2\n",
        "bad.md": b"# Bad\n",
        "bad2.md": b"# Bad2\n",
    }, "base")
    _git(repo, "branch", "base")
    (repo / "gone.md").unlink()
    _commit(repo, {
        # Two hunks, the first holding a line that arrives as `+++ b/...`.
        "docs/a.md": (f"# A\n++ b/elsewhere.md\n\nOld claim `{DEAD_TOO}`.\n\n"
                      f"Middle `{DEAD_THREE}`.\n\nMerged at `{DEAD}`.\n").encode(),
        "cats and dogs.md": b"# Pets\n\x00\nmore\n",
        "excluded/x.md": f"# X\n\nMerged at `{DEAD}`.\n".encode(),
        "cr.md": f"# CR\rone\r\nMerged at `{DEAD}`.\nAnd `{DEAD_TOO}`.\n".encode(),
        "cr2.md": b"# CR2\rtwo\r\n",
        "bad.md": b"# Bad\n\nCaf\xe9.\n",
        "bad2.md": b"# Bad2\n\xff\n",
    }, "the range")
    return repo


def _gate(repo: Path, fmt: str) -> int:
    session.reload_config(repo)
    return run_introduced_since(repo, "base", fmt)


def _notes(examined: dict[str, int], ran: set[str], *,
           primary_read: bool = False) -> list[str]:
    """The NOTE lines, from the arguments the report must hand
    `session.zero_notes`."""
    return session.zero_notes(
        examined, ran, did="examined nothing in the changed documents",
        claims="they make no such claims", primary_read=primary_read,
        absent="it is not among the changed documents", read="changed")


# The rules that read the range's documents: not the entry rules, which
# read only the primary document, and not the one `merge_claim = ""` turns
# off.
RAN = set(EXAMINED) - ENTRY_RULES - {"false-merge-claim"}


def _report(repo: Path, *, workers: int = 0, fallback: str | None = None) -> str:
    """Every line the report prints after the findings, in order."""
    base = _git(repo, "rev-parse", "base").strip()
    lines = [
        "",
        f"examined 5 changed document(s) since base (merge base {base[:7]}): "
        "10 introduced line(s), 1 finding(s) on them",
        "  1 tracked document(s) the range did not change were not read",
        "  examined: " + ", ".join(f"{kind} {n}" for kind, n in EXAMINED.items()),
        *_notes(EXAMINED, RAN),
        "  2 repository-wide rule(s) not run: their findings sit at a line "
        "nothing wrote, so --verify and --sweep run them (inconsistent-artifact, "
        "raw-lfs-blob)",
        "  2 finding(s) in the changed document(s) sit on lines the range did "
        "not touch and do not gate; --sweep shows them",
        "  excluded 1 of 6 changed document(s) via 2 exclude_paths pattern(s)",
        "        0 !keep.md",
        "        1 excluded/**",
        str(unusable_note(["!keep.md", "excluded/**"])),
        "  2 changed document(s) hold a bare carriage return, which this tool "
        "counts as a line break and git does not; 2 finding(s) there were "
        "surveyed and do not gate: cr.md, cr2.md",
        "  1 changed document(s) git reads as binary and were not examined: "
        "cats and dogs.md",
    ]
    if workers:
        lines.append(f"  surveyed across {workers} worker process(es)")
    lines.extend(fallback_note(fallback))
    lines.append("  2 could not be read: bad.md (UnicodeDecodeError), "
                 "bad2.md (UnicodeDecodeError)")
    return "\n".join(lines) + "\n"


FOUND = (f"docs/a.md: line 8: [dead-sha] `{DEAD}` does not resolve in this "
         "repo\n")


def _sarif(out: str, *, also: list[str] | None = None) -> None:
    """The one run on stdout: the finding with its snippet, the denominator
    and the NOTE lines (and any line `also` adds), the rule switched off,
    named as this mode's run."""
    run: dict[str, Any] = json.loads(out)["runs"][0]
    assert run["automationDetails"] == {"id": "extant/introduced-since"}
    assert [(r["ruleId"], r["level"], r["properties"],
             r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],
             r["locations"][0]["physicalLocation"]["region"]["startLine"],
             r["locations"][0]["physicalLocation"]["region"]["snippet"]["text"])
            for r in run["results"]] == [
        ("dead-sha", "error", {"gates": True, "stratum": "ordinary"},
         "docs/a.md", 8, f"Merged at `{DEAD}`.")]
    summary = ", ".join(f"{kind} {n}" for kind, n in EXAMINED.items())
    assert run["invocations"] == [{
        "executionSuccessful": True,
        "toolExecutionNotifications": [
            {"level": "note", "message": {"text": f"examined: {summary}"}},
            *({"level": "warning",
               "message": {"text": line.strip().removeprefix("NOTE: ")}}
              for line in _notes(EXAMINED, RAN) + (also or []))],
        "ruleConfigurationOverrides": [
            {"descriptor": {"id": "false-merge-claim", "index": 1},
             "configuration": {"enabled": False}}],
    }]
    assert run["properties"] == {"examined": EXAMINED}


def test_the_text_report_is_compared_whole(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """With GitHub's SARIF limit at 0, so the one finding would be cut from
    a SARIF run: the text report names no such cut, because it has none."""
    monkeypatch.setattr(report, "SARIF_RESULT_LIMIT", 0)
    repo = _range(tmp_path)
    code = _gate(repo, "text")
    out, err = capsys.readouterr()
    assert (code, out, err) == (1, FOUND + _report(repo), "")


def test_in_sarif_the_document_alone_is_on_stdout(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The report moves to stderr whole, and stdout holds one SARIF run."""
    repo = _range(tmp_path)
    code = _gate(repo, "sarif")
    out, err = capsys.readouterr()
    assert (code, err) == (1, _report(repo))
    _sarif(out)


def test_a_parallel_survey_says_how_many_workers_read_it(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The same run from a pool, which adds one line - to stderr, with the
    rest of the report."""
    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 1)
    repo = _range(tmp_path)
    code = _gate(repo, "sarif")
    out, err = capsys.readouterr()
    workers = min(sweep._MAX_WORKERS, os.cpu_count() or 1)
    assert (code, err) == (1, _report(repo, workers=workers))
    _sarif(out)


def test_a_pool_that_cannot_start_is_said_to_have_fallen_back(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Every document read in this process instead, and the reason said in
    the report and in the SARIF both."""
    def refused(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no pool here")

    monkeypatch.setattr(sweep, "_PARALLEL_FLOOR", 1)
    monkeypatch.setattr(concurrent.futures, "ProcessPoolExecutor", refused)
    repo = _range(tmp_path)
    code = _gate(repo, "sarif")
    out, err = capsys.readouterr()
    reason = "OSError: no pool here"
    assert (code, err) == (1, _report(repo, fallback=reason))
    _sarif(out, also=fallback_note(reason))


def test_a_range_that_changes_the_primary_document(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The primary document is surveyed as the primary - its newest entry
    read by the entry rules - and the NOTE lines say it was among the
    changed documents."""
    repo = _init(tmp_path)
    _commit(repo, {".extant.toml": b'primary_doc = "STATUS.md"\n',
                   "STATUS.md": b"# Status\n\n## Phase 1\n\nStarted.\n"}, "base")
    _git(repo, "branch", "base")
    _commit(repo, {"STATUS.md": b"# Status\n\n## Phase 2\n\nStill going.\n\n"
                                b"## Phase 1\n\nStarted.\n"}, "status")

    code = _gate(repo, "text")
    out = capsys.readouterr().out

    base = _git(repo, "rev-parse", "base").strip()
    examined = dict.fromkeys(EXAMINED, 0)
    assert (code, out) == (0, "\n".join([
        "",
        f"examined 1 changed document(s) since base (merge base {base[:7]}): "
        "4 introduced line(s), 0 finding(s) on them",
        "  0 tracked document(s) the range did not change were not read",
        "  examined: " + ", ".join(f"{kind} 0" for kind in examined),
        *_notes(examined, set(examined), primary_read=True),
        "  1 repository-wide rule(s) not run: their findings sit at a line "
        "nothing wrote, so --verify and --sweep run them (raw-lfs-blob)",
    ]) + "\n")


def test_a_changed_primary_document_with_no_dated_entry(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Read, and holding nothing the entry rules can read: the NOTE says the
    document holds no entry, not that it was left out of the range."""
    repo = _init(tmp_path)
    _commit(repo, {".extant.toml": b'primary_doc = "STATUS.md"\n',
                   "STATUS.md": b"# Status\n"}, "base")
    _git(repo, "branch", "base")
    _commit(repo, {"STATUS.md": b"# Status\n\nNothing dated yet.\n"}, "status")

    code = _gate(repo, "text")
    out = capsys.readouterr().out

    examined = dict.fromkeys(EXAMINED, 0)
    notes = _notes(examined, set(examined) - ENTRY_RULES, primary_read=True)
    assert code == 0, out
    assert "\n".join(notes) in out, out


def test_a_claim_written_into_a_vendored_document_says_so_in_sarif(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """It gates like any written claim, and its result carries the stratum
    a consumer filters on."""
    repo = _init(tmp_path)
    _commit(repo, {"vendor/lib/README.md": b"# Lib\n"}, "base")
    _git(repo, "branch", "base")
    _commit(repo, {"vendor/lib/README.md":
                   f"# Lib\n\nMerged at `{DEAD}`.\n".encode()}, "claim")

    code = _gate(repo, "sarif")
    out = capsys.readouterr().out
    assert code == 1
    assert [r["properties"] for r in json.loads(out)["runs"][0]["results"]] == [
        {"gates": True, "stratum": "vendored"}]


def test_a_range_that_changes_no_markdown(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The markdown rules read no changed document, and the NOTE lines say
    which kind of document none was."""
    repo = _init(tmp_path)
    _commit(repo, {"guide.rst": b"Guide\n=====\n"}, "base")
    _git(repo, "branch", "base")
    _commit(repo, {"guide.rst": b"Guide\n=====\n\nMore.\n"}, "rst")

    code = _gate(repo, "text")
    out = capsys.readouterr().out

    base = _git(repo, "rev-parse", "base").strip()
    examined = dict.fromkeys(EXAMINED, 0)
    ran = set(examined) - ENTRY_RULES - {"dead-md-link", "dead-md-anchor"}
    assert (code, out) == (0, "\n".join([
        "",
        f"examined 1 changed document(s) since base (merge base {base[:7]}): "
        "2 introduced line(s), 0 finding(s) on them",
        "  0 tracked document(s) the range did not change were not read",
        "  examined: " + ", ".join(f"{kind} 0" for kind in examined),
        *_notes(examined, ran),
        "  1 repository-wide rule(s) not run: their findings sit at a line "
        "nothing wrote, so --verify and --sweep run them (raw-lfs-blob)",
    ]) + "\n")


def test_a_rule_that_raised_is_named_once_on_stderr_beside_the_sarif(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A raised rule is named in the report - on stderr in this mode, and
    once - and the SARIF on stdout says the run did not succeed."""
    repo = _init(tmp_path)
    _commit(repo, {"notes.md": b"# Notes\n"}, "base")
    _git(repo, "branch", "base")
    _commit(repo, {"notes.md": b"# Notes\n\nMore.\n"}, "edit")
    with raising_rule() as broken:
        session.reload_config(repo)
        code = run_introduced_since(repo, "base", "sarif")
    out, err = capsys.readouterr()
    run = json.loads(out)["runs"][0]
    assert code == 1
    assert run["invocations"][0]["executionSuccessful"] is False
    line = (f"  ERRORED: {broken.kind} raised RuntimeError: deliberate. A rule "
            "that raised has not found nothing, it has failed to look, so this "
            "run is not a pass.")
    assert err.count("ERRORED:") == 1, err
    assert f"\n{line}\n" in err, err


def test_the_documents_the_survey_lost_are_named_and_fail_the_run(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A document dispatched and never returned - a worker that died - was
    not examined, and a run that lost one cannot pass. The documents after
    it are still read: the one claim that gates is in the last of them."""
    from extant import introduced_since
    from extant.sweep import survey as real

    def losing(*args: Any, **kwargs: Any) -> Any:
        gathered, workers, fallback = real(*args, **kwargs)
        return ({k: v for k, v in gathered.items() if k not in ("cr.md", "cr2.md")},
                workers, fallback)

    monkeypatch.setattr(introduced_since, "survey", losing)
    repo = _range(tmp_path)
    code = _gate(repo, "sarif")
    _out, err = capsys.readouterr()
    assert code == 1
    assert ": 10 introduced line(s), 1 finding(s) on them\n" in err, err
    assert ("\n  2 document(s) were dispatched and returned no result, so they "
            "were NOT examined: cr.md, cr2.md\n") in err, err


def test_a_diff_git_cannot_produce_refuses_and_says_why(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial repository whose base tree the transport left out cannot
    diff; the refusal names the base by seven characters, as every other
    line of the report does, and writes nothing to stdout."""
    from extant import introduced_since

    def failing(repo: Path, base: str) -> Any:
        raise subprocess.CalledProcessError(128, ["git", "diff"])

    monkeypatch.setattr(introduced_since, "introduced_lines", failing)
    repo = _range(tmp_path)
    base = _git(repo, "rev-parse", "base").strip()
    code = _gate(repo, "sarif")
    out, err = capsys.readouterr()
    assert (code, out, err) == (2, "", (
        f"--introduced-since base: git diff against {base[:7]} failed "
        "(CalledProcessError), so there is no range to gate on.\n"))


@pytest.mark.skipif(sys.platform != "linux",
                    reason="only Linux names a file with bytes that are not UTF-8")
def test_a_document_whose_name_is_not_utf8_does_not_stop_the_gate(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """git writes such a name raw, since `core.quotePath` is off; the diff's
    header is decoded with replacement, so the gate goes on and says it
    could not read the document rather than stopping on the name."""
    repo = _init(tmp_path)
    name = os.fsdecode(b"caf\xe9.md")
    (repo / name).write_bytes(b"# Cafe\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "base")
    (repo / name).write_bytes(f"# Cafe\n\nMerged at `{DEAD}`.\n".encode())
    _git(repo, "commit", "-qam", "claim")

    code = _gate(repo, "text")
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.endswith("  1 could not be read: caf" + chr(0xFFFD)
                        + ".md (FileNotFoundError)\n"), out


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_a_document_that_leaves_the_checkout_is_unreadable_not_unmapped(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A changed document that is a link out of the checkout is refused
    wherever it is opened: counted as unreadable, and not said to hold a
    bare carriage return, which is a question about bytes nobody read."""
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"# Outside\r\n")
    repo = _init(tmp_path)
    _commit(repo, {"plain.md": b"# Plain\n"}, "base")
    _git(repo, "branch", "base")
    (repo / "link.md").symlink_to(outside)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "a link")

    code = _gate(repo, "text")
    out = capsys.readouterr().out
    assert code == 0, out
    assert "bare carriage return" not in out, out
    assert out.endswith("  1 could not be read: link.md (OutsideRepository)\n"), out
