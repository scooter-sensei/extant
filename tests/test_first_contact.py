"""Failures a user meets on first contact, and one silently dead setting.

All four were found by a CodeRabbit review of the whole repository on
2026-08-04 and reproduced before being believed. Three are crashes on inputs
nobody thinks to try: a repository with no commits, and a repository that does
not carry the configured status document. The fourth is worse than a crash,
because it looks like success - a configured setting that the code reading it
never saw.

Each test names the wrong implementation it would catch.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import _install_into

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
COLLECTOR = PAYLOAD / "extant_collect.py"


def run(repo: Path, *args: str, collector: Path | None = None):
    return subprocess.run(
        [sys.executable, str(collector or COLLECTOR), "--repo", str(repo),
         *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace")


def _write(path: Path, body: str) -> None:
    """`open(newline="")`, not `write_text(newline=...)`.

    That keyword needs Python 3.10 and this project supports 3.9, which
    `test_no_pathlib_newline_argument` enforces. It caught this file.
    """
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(body)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def test_a_sweep_of_a_repository_with_no_commits_says_so(tmp_path) -> None:
    """An UNBORN HEAD has no tree, so `git ls-tree HEAD` exits 128.

    That reached the user as a CalledProcessError traceback. A repository
    someone has just created is a legitimate thing to point a first-run survey
    at, and `--sweep` is the command documented for exactly that moment.
    """
    repo = tmp_path / "fresh"
    repo.mkdir()
    git(repo, "init", "-q")
    done = run(repo, "--sweep")
    combined = done.stdout + done.stderr
    assert "Traceback" not in combined, combined
    assert "swept 0 markdown files" in combined, combined
    assert done.returncode == 0, combined


def test_selftest_without_the_primary_document_reports_it(tmp_path) -> None:
    """`diag` is defined 87 lines further down the same function.

    Calling it from this branch raised UnboundLocalError, so the message
    explaining which document was missing never printed. Catches reintroducing
    the helper call, and catches losing the non-zero exit.
    """
    repo = tmp_path / "nodoc"
    repo.mkdir()
    git(repo, "init", "-q")
    _write(repo / "README.md", "# x\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "init")
    done = run(repo, "--selftest")
    combined = done.stdout + done.stderr
    assert "Traceback" not in combined, combined
    assert "no such document" in combined, combined
    assert "primary_doc is" in combined, combined
    assert done.returncode == 1, combined


def test_a_configured_consistency_timeout_reaches_the_global(tmp_path) -> None:
    """The setting was inert on every CLI run, and looked configured.

    `_apply_config()` runs at import and sets `_CONSISTENCY_TIMEOUT`; a later
    module-level ASSIGNMENT then replaced it with None. The config parsed, the
    value reached CONFIG, and the global the rule actually reads never saw it.

    Run as a subprocess with the payload in `tools/`, because that is the only
    arrangement in which the target repository's own config is read at all -
    configuration loads relative to the SCRIPT, not to `--repo`.
    """
    repo = tmp_path / "timed"
    _install_into(repo)
    git(repo, "init", "-q")
    _write(repo / ".extant.toml", "consistency_timeout_seconds = 5.0\n")
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'tools');"
         " from extant import session as hc;"
         " print(hc.CONFIG.consistency_timeout_seconds, hc._CONSISTENCY_TIMEOUT)"],
        cwd=repo, capture_output=True, text=True)
    assert done.stdout.split() == ["5.0", "5.0"], (
        f"config and the global disagree: {done.stdout!r} {done.stderr!r}")


def test_write_baseline_resolves_against_the_repository(tmp_path) -> None:
    """A relative `--write-baseline` was resolved against the process cwd.

    The READ path resolves against `--repo`, so a git hook - which passes
    `--repo` and runs from wherever the commit was made - wrote a baseline
    that the next `--baseline` could not find. Catches the two paths drifting
    apart again.
    """
    repo = tmp_path / "based"
    repo.mkdir()
    git(repo, "init", "-q")
    _write(repo / "NEXT_SESSION.md", "# s\n\n**Plan:** `docs/gone.md`\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "init")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # `--validate` gets an ABSOLUTE path and `--write-baseline` a relative
    # one, deliberately. Only the second is under test; passing both relative
    # made the run fail to find the document at all, which would have proved
    # nothing about where the baseline lands.
    done = subprocess.run(
        [sys.executable, str(COLLECTOR), "--repo", str(repo),
         "--validate", str(repo / "NEXT_SESSION.md"),
         "--write-baseline", "base.json"],
        cwd=elsewhere, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    assert (repo / "base.json").is_file(), (
        f"baseline was not written into the repository:\n"
        f"{done.stdout}{done.stderr}")
    assert not (elsewhere / "base.json").exists(), (
        "baseline was written next to the process cwd instead")
