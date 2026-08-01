"""A recorded finding forgives the occurrences it recorded, not every future one.

The fingerprint excludes the line number on purpose, so that reflowing a
paragraph does not un-suppress everything. The cost was that one recorded
finding forgave the same claim pasted anywhere, forever - `smoke.py` listed
that in EXPECTED as a by-design consequence.

Bounding the amnesty by occurrence count keeps the churn-immunity and removes
the unbounded part. The line number stays out of the fingerprint.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = PACKAGE_ROOT / "plugin" / "skills" / "extant" / "install.py"

DEAD = "deadbeef1234567"
ONE = f"# Legacy\n\nShipped in `{DEAD}`.\n"
TWO = f"# Legacy\n\nShipped in `{DEAD}`.\nAnd again in `{DEAD}`.\n"


def _repo(tmp_path: Path, body: str) -> Path:
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


def test_the_recorded_entry_states_its_count(tmp_path) -> None:
    repo = _repo(tmp_path, ONE)
    verify(repo, "--write-baseline")
    recorded = json.loads((repo / ".extant-baseline.json").read_text(encoding="utf-8"))
    entries = [e for e in recorded["findings"] if DEAD in e["detail"]]
    assert entries, recorded["findings"]
    assert entries[0]["count"] == 1, entries[0]


def test_two_occurrences_record_one_entry_counting_two(tmp_path) -> None:
    """One fingerprint, not two entries. A baseline is reviewed by humans and
    duplicating an entry per occurrence would make it unreadable."""
    repo = _repo(tmp_path, TWO)
    verify(repo, "--write-baseline")
    recorded = json.loads((repo / ".extant-baseline.json").read_text(encoding="utf-8"))
    entries = [e for e in recorded["findings"] if DEAD in e["detail"]]
    assert len(entries) == 1, entries
    assert entries[0]["count"] == 2, entries[0]


def test_a_second_copy_beyond_what_was_recorded_still_fails(tmp_path) -> None:
    """The loophole this closes. Record once, paste again, and the paste used
    to be forgiven forever because the fingerprint ignores the line number."""
    repo = _repo(tmp_path, ONE)
    verify(repo, "--write-baseline")
    assert verify(repo, "--baseline").returncode == 0, "the recorded one is forgiven"

    with open(repo / "README.md", "w", encoding="utf-8", newline="") as fh:
        fh.write(TWO)
    subprocess.run(["git", "commit", "-am", "docs: paste it again"], cwd=repo,
                   capture_output=True, check=True)

    done = verify(repo, "--baseline")
    assert done.returncode == 1, (
        "a second copy beyond the recorded count must not be forgiven:\n"
        + done.stdout + done.stderr
    )


def test_the_recorded_occurrences_are_still_forgiven(tmp_path) -> None:
    """The control. A bound that forgave nothing would fail every ratcheted
    run, which is the opposite failure and just as useless."""
    repo = _repo(tmp_path, TWO)
    verify(repo, "--write-baseline")
    done = verify(repo, "--baseline")
    assert done.returncode == 0, (
        "both recorded occurrences must stay suppressed:\n" + done.stdout + done.stderr
    )


def test_an_old_baseline_without_counts_still_loads(tmp_path) -> None:
    """Baselines already exist in projects that adopted this. An entry written
    before counts existed must keep working, forgiving one occurrence."""
    repo = _repo(tmp_path, ONE)
    verify(repo, "--write-baseline")
    path = repo / ".extant-baseline.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))
    for entry in recorded["findings"]:
        entry.pop("count", None)
    path.write_text(json.dumps(recorded, indent=2) + "\n", encoding="utf-8")

    done = verify(repo, "--baseline")
    assert done.returncode == 0, (
        "a pre-count baseline must still suppress:\n" + done.stdout + done.stderr
    )
