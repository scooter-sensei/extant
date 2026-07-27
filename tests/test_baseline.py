"""The baseline, which exists to make adoption on an old repository possible.

Point this at a ten-year-old project and the first run reports everything at
once. CI goes red, and the tool comes back out - so the only way to adopt was
to spend a week on decade-old prose first. A baseline records what is already
there, so NEW claims are checked from day one.

The objection to having one is fair: a baseline is a place to hide things, and
this tool's authority rests on not hiding things. Every test here is about the
constraints that answer that objection rather than about the suppression
itself. The suppressed count is always stated, stale entries are reportable,
and nothing is ever recorded implicitly.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
INSTALLER = SKILL_ROOT / "install.py"

ROTTED = ("# Legacy\n\nShipped in `deadbeef1234567`.\n"
          "See [the old guide](docs/gone.md).\n")


def _legacy_repo(tmp_path: Path, body: str = ROTTED) -> Path:
    """A repo with the tool installed and two findings already in it."""
    repo = tmp_path / "legacy"
    repo.mkdir()
    for cmd in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                ["config", "user.name", "T"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True, check=True)
    with open(repo / "README.md", "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo,
                   capture_output=True, check=True)
    subprocess.run([sys.executable, str(INSTALLER), "--repo", str(repo),
                    "--doc", "README.md"], cwd=repo, capture_output=True, check=True)
    return repo


def verify(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), "--verify", *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_a_recorded_finding_stops_failing_the_run(tmp_path) -> None:
    """The point of the feature: adoption without a week of archaeology."""
    repo = _legacy_repo(tmp_path)
    assert verify(repo).returncode == 1, "the fixture should start dirty"

    assert verify(repo, "--write-baseline").returncode == 0
    result = verify(repo, "--baseline")

    assert result.returncode == 0, result.stdout


def test_the_suppressed_count_is_always_stated(tmp_path) -> None:
    """The constraint that answers the objection to baselines existing.

    "no findings" and "no new findings, 40 suppressed" are different facts. A
    baseline that hides its own size is the denominator failure this project
    exists to surface, reintroduced by one of its own features.
    """
    repo = _legacy_repo(tmp_path)
    verify(repo, "--write-baseline")

    result = verify(repo, "--baseline")

    assert "2 suppressed" in result.stdout, result.stdout
    assert "0 new finding" in result.stdout, result.stdout


def test_a_new_finding_still_fails(tmp_path) -> None:
    """A ratchet that forgives new work is not a ratchet.

    A wrong implementation that suppresses by KIND rather than by identity
    passes every test above and silently forgives every future dead link.
    """
    repo = _legacy_repo(tmp_path)
    verify(repo, "--write-baseline")

    with open(repo / "README.md", "a", encoding="utf-8", newline="") as fh:
        fh.write("\nAlso [this one](docs/never-written.md).\n")
    result = verify(repo, "--baseline")

    assert result.returncode == 1, result.stdout
    assert "never-written.md" in result.stdout
    assert "1 new finding" in result.stdout
    assert "2 suppressed" in result.stdout


def test_nothing_is_recorded_without_being_asked(tmp_path) -> None:
    """A baseline that rewrote itself on every run would ratchet the wrong way.

    Each run would forgive whatever it had just found, and the check would decay
    to nothing while continuing to report success - the most expensive possible
    failure for a tool whose whole claim is that silence means something.
    """
    repo = _legacy_repo(tmp_path)

    assert verify(repo).returncode == 1
    assert not (repo / ".extant-baseline.json").exists(), (
        "an ordinary run wrote a baseline"
    )


def test_a_baseline_entry_that_no_longer_occurs_is_reported(tmp_path) -> None:
    """An amnesty must not outlive the thing it forgave.

    Once the claim is fixed, its entry forgives something that is not there, and
    a baseline nobody prunes becomes permanent. It is itself a stale claim,
    which this project is not entitled to keep.
    """
    repo = _legacy_repo(tmp_path)
    verify(repo, "--write-baseline")

    (repo / "docs").mkdir()
    with open(repo / "docs" / "gone.md", "w", encoding="utf-8", newline="") as fh:
        fh.write("# now it exists\n")
    result = verify(repo, "--baseline-check")

    assert result.returncode == 1, result.stdout
    assert "STALE" in result.stdout
    assert "docs/gone.md" in result.stdout
    assert "1 still occur, 1 do not" in result.stdout


def test_a_missing_baseline_is_an_error_not_an_empty_one(tmp_path) -> None:
    """Treating absence as "suppress nothing" is the quiet failure.

    A typo'd path would turn a ratcheted run back into an ordinary one without
    saying so - and on a legacy repository that means a wall of findings the
    reader believes they had already accepted.
    """
    repo = _legacy_repo(tmp_path)

    result = verify(repo, "--baseline", "nope.json")

    assert result.returncode == 2
    assert "no baseline at" in result.stderr, result.stderr


def test_the_recorded_file_is_reviewable(tmp_path) -> None:
    """It is a tracked file that people review, so it must read as prose.

    Fingerprints alone would match correctly and tell a reviewer nothing about
    what their colleague just agreed to leave broken.
    """
    repo = _legacy_repo(tmp_path)
    verify(repo, "--write-baseline")

    data = json.loads((repo / ".extant-baseline.json").read_text(encoding="utf-8"))

    assert data["version"] == 1
    kinds = {e["kind"] for e in data["findings"]}
    assert kinds == {"dead-sha", "dead-md-link"}, data["findings"]
    for entry in data["findings"]:
        assert entry["path"] == "README.md"
        assert entry["detail"], "an entry with no detail is unreviewable"
        assert len(entry["fingerprint"]) == 32


def test_recording_twice_does_not_shrink_the_baseline(tmp_path) -> None:
    """Writing must see everything, including what an existing baseline hides.

    Otherwise a second --write-baseline records only what the first had missed,
    and the file quietly empties itself each time somebody runs it.
    """
    repo = _legacy_repo(tmp_path)
    verify(repo, "--write-baseline")
    first = json.loads((repo / ".extant-baseline.json").read_text(encoding="utf-8"))

    verify(repo, "--write-baseline", "--baseline")
    second = json.loads((repo / ".extant-baseline.json").read_text(encoding="utf-8"))

    assert second["findings"] == first["findings"], (
        "re-recording with a baseline active dropped entries"
    )
