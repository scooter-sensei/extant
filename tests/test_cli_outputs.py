"""What the command line's own modes print, compared WHOLE.

D7 found 115 of cli.py's 934 mutants alive after the whole suite: 46 in
`run_selftest`, 26 in `--search`, the entry reader beneath it and the
error it raises, 18 in the console script's argument handling, 17 in
`--collect`, 8 in `--archive`'s two refusals. The tests asserted that a
mode ran and a phrase appeared, so a line moved to the wrong stream, a
count computed wrongly or a bundle written with other bytes went unseen.

`--selftest`'s probes are session.py's and worded there; what this file
pins of it is cli.py's half - the header, the counts and what they imply,
the closing notes and the exit code - by handing it fixed results, and the
document it installs for the probes, by reading it back from inside.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from extant import session
from extant.cli import cli, main
from extant.files import OutsideRepository, inside

# Not ASCII, and the second half of L-stroke's UTF-8 is a byte cp1252 does
# not define, so text read with the locale on Windows fails outright rather
# than arriving as mojibake an entry count would not notice.
CAFE = "Caf" + chr(0xE9) + " " + chr(0x141)


def _repo(root: Path, files: dict[str, bytes], *, commit: bool = False) -> Path:
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for name, data in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if commit:
        for args in (["config", "user.email", "t@t"], ["config", "user.name", "T"],
                     ["add", "-A"], ["commit", "-qm", "status"]):
            subprocess.run(["git", *args], cwd=repo, check=True)
    return repo


CONFIG = b'primary_doc = "STATUS.md"\narchive_doc = "docs/status-archive.md"\n'

STATUS = ("# Status\n\n"
          "## Phase 3 - Third (2026-03-01)\n\nNothing about it.\n\n"
          "## Phase 2 - " + CAFE + " (2026-02-01)\n\n"
          "We decided to keep it.\nLine two of the decision.\nLine three.\n"
          "Line four.\nLine five, past the excerpt.\n").encode("utf-8")
ARCHIVE = b"# Archive\n\n## Phase 1 - First (2026-01-01)\n\nDecided long ago.\n"


# --- --search -------------------------------------------------------------------

def test_search_prints_matching_entries_and_its_denominator(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Entries, newest first, from the live document and then the archive -
    past an entry that does not match - each with four lines of excerpt,
    the header read as UTF-8 whatever the locale."""
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": STATUS,
                            "docs/status-archive.md": ARCHIVE})
    assert main(["--search", "decided", "--repo", str(repo)]) == 0
    out, err = capsys.readouterr()
    assert (out, err) == ((
        "STATUS.md: ## Phase 2 - " + CAFE + " (2026-02-01)\n"
        "    We decided to keep it.\n    Line two of the decision.\n"
        "    Line three.\n    Line four.\n\n"
        "docs/status-archive.md: ## Phase 1 - First (2026-01-01)\n"
        "    Decided long ago.\n\n"
        "2 match(es) in 3 entries across 2 document(s)\n"), "")


def test_search_full_prints_every_line_of_the_entry(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": STATUS})
    assert main(["--search", "keep", "--full", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out == (
        "STATUS.md: ## Phase 2 - " + CAFE + " (2026-02-01)\n"
        "    \n    We decided to keep it.\n    Line two of the decision.\n"
        "    Line three.\n    Line four.\n    Line five, past the excerpt.\n\n"
        "1 match(es) in 2 entries across 1 document(s)\n")


def test_search_reads_the_archive_when_the_document_is_missing(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "docs/status-archive.md": ARCHIVE})
    assert main(["--search", "decided", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out == (
        "docs/status-archive.md: ## Phase 1 - First (2026-01-01)\n"
        "    Decided long ago.\n\n"
        "1 match(es) in 1 entries across 1 document(s)\n")


def test_search_with_no_entries_says_why_it_found_none(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG,
                            "STATUS.md": b"# Status\n\nNo entries here.\n"})
    assert main(["--search", "anything", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out == (
        "0 match(es) in 0 entries across 1 document(s)\n"
        "  NOTE: no entries were found to search. Either these documents have "
        "none, or entry_prefix does not match their headers.\n")


def test_search_needs_something_to_look_for(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": STATUS})
    with pytest.raises(SystemExit) as stopped:
        main(["--search", "   ", "--repo", str(repo)])
    assert stopped.value.code == 2
    assert capsys.readouterr().err.endswith(
        "extant_collect: error: --search needs something to look for\n")


def test_search_names_a_document_that_is_not_utf8(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": b"\xff# x\n"})
    assert main(["--search", "x", "--repo", str(repo)]) == 1
    assert capsys.readouterr() == ("", (
        f"{repo / 'STATUS.md'}: not valid UTF-8 (invalid start byte at byte 0). "
        "The status document must be a text file.\n"))


# --- --selftest -------------------------------------------------------------------

def _stubbed_selftest(monkeypatch: pytest.MonkeyPatch, result: tuple[Any, ...],
                      seen: dict[str, Any]) -> None:
    def fake(repo: Path, text: str) -> tuple[Any, ...]:
        document = session.document()
        seen.update(text=text, link_base=document.link_base,
                    doc_path=document.doc_path, doc_format=document.doc_format)
        return result

    monkeypatch.setattr(session, "selftest", fake)


def test_selftest_reports_its_counts_and_what_they_imply(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Every rule accounted for, nothing silent: the probe lines, the counts,
    the one note no-probe needs, exit 0 - and the probes were handed the
    document as UTF-8 with its CRLF endings kept, installed with its
    directory, name and language."""
    crlf = STATUS.replace(b"\n", b"\r\n")
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": crlf})
    seen: dict[str, Any] = {}
    _stubbed_selftest(monkeypatch, (["  dead-sha            FIRED",
                                     "  raw-lfs-blob        NO PROBE"], 7, 6, 0, 0), seen)
    assert main(["--selftest", "--repo", str(repo)]) == 0
    assert capsys.readouterr() == ((
        "selftest: probing 13 rules against STATUS.md\n\n"
        "  dead-sha            FIRED\n  raw-lfs-blob        NO PROBE\n\n"
        "  7 fired, 6 had nothing to corrupt, 0 could not be run, 0 stayed silent\n"
        "  'No probe' is not a failure by itself, but a rule that cannot be "
        "exercised is also not known to work.\n"), "")
    assert seen == {"text": crlf.decode("utf-8"), "link_base": repo,
                    "doc_path": "STATUS.md", "doc_format": "markdown"}


def test_selftest_with_silent_and_errored_rules_fails(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Thirteen rules: 5 fired, 2 had no probe, 1 raised, 2 were not run, so
    3 stayed silent - said, with each note it calls for, and exit 1."""
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": STATUS})
    _stubbed_selftest(monkeypatch, ([], 5, 2, 1, 2), {})
    assert main(["--selftest", "--repo", str(repo)]) == 1
    assert capsys.readouterr().out == (
        "selftest: probing 13 rules against STATUS.md\n\n\n"
        "  5 fired, 2 had nothing to corrupt, 1 could not be run, 3 stayed "
        "silent, 2 not run here\n"
        "  A rule that stays silent after a real match is corrupted is not "
        "working. Check its pattern against this document.\n"
        "  A rule that could not be run has not been shown to work either - see "
        "the ERRORED line(s) above for what it raised.\n"
        "  'No probe' is not a failure by itself, but a rule that cannot be "
        "exercised is also not known to work.\n")


def test_selftest_without_its_document_says_where_the_name_came_from(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG})
    assert main(["--selftest", "--repo", str(repo)]) == 1
    assert capsys.readouterr() == ("", (
        f"no such document: {repo / 'STATUS.md'}\n"
        f"  primary_doc is 'STATUS.md', from {session.CONFIG.source}\n"))


def test_selftest_refuses_a_document_outside_the_repository(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "outside.md").write_bytes(STATUS)
    repo = _repo(tmp_path, {".extant.toml": b'primary_doc = "../outside.md"\n'})
    target = repo / "../outside.md"
    with pytest.raises(OutsideRepository) as refused:
        inside(repo, target)
    assert main(["--selftest", "--repo", str(repo)]) == 1
    assert capsys.readouterr() == ("", f"not reading {target}: {refused.value}\n")


def test_selftest_refuses_a_document_that_is_not_utf8(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": b"\xff# x\n"})
    assert main(["--selftest", "--repo", str(repo)]) == 1
    assert capsys.readouterr() == ("", (
        f"{repo / 'STATUS.md'}: not valid UTF-8 (invalid start byte at byte 0). "
        "The status document must be a text file.\n"))


# --- --collect and --archive -------------------------------------------------------

def test_collect_writes_the_bundle_indented_with_lf_endings(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Nothing since the status document, so it says so before naming the
    file it wrote - the supplied result, not a measured one."""
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": STATUS}, commit=True)
    supplied = tmp_path / "suite.json"
    supplied.write_text('{"passed": 1}', encoding="utf-8")
    out = tmp_path / "bundle.json"
    assert main(["--collect", "--suite-json", str(supplied), "--out", str(out),
                 "--repo", str(repo)]) == 0
    assert capsys.readouterr() == (
        f"nothing to hand off: no commits since the last status\n{out}\n", "")
    written = out.read_bytes()
    bundle = json.loads(written)
    assert written == json.dumps(bundle, indent=2).encode("ascii")
    assert (bundle["nothing_to_hand_off"], bundle["suite"]) == (
        True, {"passed": 1, "source": "supplied"})


def test_collect_writes_beside_the_repository_by_default(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG, "STATUS.md": STATUS}, commit=True)
    supplied = tmp_path / "suite.json"
    supplied.write_text('{"passed": 1}', encoding="utf-8")
    assert main(["--collect", "--suite-json", str(supplied), "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.endswith(f"\n{repo / 'status_bundle.json'}\n")
    assert (repo / "status_bundle.json").is_file()


def test_archive_without_its_document_says_what_to_fix(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path, {".extant.toml": CONFIG})
    assert main(["--archive", "--repo", str(repo)]) == 1
    assert capsys.readouterr() == ("", (
        f"no such document: {repo / 'STATUS.md'}\n"
        f"  primary_doc is 'STATUS.md', from {session.CONFIG.source}\n"
        "  set primary_doc in .extant.toml, or create the document\n"))


# --- the console script ------------------------------------------------------------

def test_the_console_script_reads_a_mode_given_with_an_equals_sign(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`--search=TEXT` is a mode even when TEXT holds `=`, so no `--verify`
    is put in front of it; `--repo=PATH` is honoured as given, and found
    as `--repo` when PATH holds `=` too."""
    parent = tmp_path / "a=b"
    parent.mkdir()
    repo = _repo(parent, {".extant.toml": CONFIG, "STATUS.md": STATUS})
    monkeypatch.setattr(sys, "argv", ["extant", "--search=keep=it", f"--repo={repo}"])
    assert cli() == 0
    assert capsys.readouterr().out == "0 match(es) in 2 entries across 1 document(s)\n"


def test_the_console_script_refuses_repo_with_no_path(
        capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["extant", "--repo"])
    with pytest.raises(SystemExit) as stopped:
        cli()
    assert stopped.value.code == 2
    assert capsys.readouterr().err.endswith(
        "extant_collect: error: --repo requires a PATH\n")
