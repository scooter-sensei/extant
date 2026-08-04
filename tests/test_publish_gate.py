"""The publish gate: no green tests run for this commit, no upload.

`publish.yml` triggers on a tag and never consulted `tests.yml`, so a red suite
did not stop a release. 0.19.0 went to PyPI that way. PyPI does not allow
replacing a released version, which makes this the one gate in the project
whose failure cannot be undone by a follow-up commit.

The case these tests exist for is the EMPTY one. A gate that reads "no runs
found" as "no failures found" passes hardest exactly when its subject was never
checked, and that state is reachable in normal use: tag first, push second.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / ".github" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import require_green_tests as gate  # noqa: E402


def run(status: str, conclusion: str | None, url: str = "http://run/1") -> dict:
    return {"status": status, "conclusion": conclusion, "html_url": url}


def test_no_run_for_this_commit_fails() -> None:
    """The case the gate exists for, and the one a naive implementation gets
    wrong: an empty list is not a clean result."""
    verdict, sentence = gate.decide([])
    assert verdict == gate.FAIL, sentence
    assert "no tests run exists" in sentence


def test_a_successful_run_passes() -> None:
    """The control. A gate that failed on everything would satisfy the test
    above while being equally useless."""
    verdict, _ = gate.decide([run("completed", "success")])
    assert verdict == gate.PASS


def test_a_failed_run_blocks_the_publish() -> None:
    verdict, sentence = gate.decide([run("completed", "failure")])
    assert verdict == gate.FAIL, sentence
    assert "failure" in sentence


@pytest.mark.parametrize("conclusion", ["cancelled", "timed_out", "startup_failure",
                                        "action_required", "stale", None])
def test_only_success_counts_as_green(conclusion) -> None:
    """Anything that is not `success` blocks. Written as a list rather than as
    `!= "failure"` because a cancelled run is not a passing one, and that is
    the shape a hand-written check gets wrong."""
    verdict, _ = gate.decide([run("completed", conclusion)])
    assert verdict == gate.FAIL, conclusion


def test_an_unfinished_run_is_pending_not_a_pass() -> None:
    """In progress must not be read as either answer. Reading it as success
    publishes against a suite that has not finished; reading it as failure
    makes tagging a race against the runner."""
    verdict, _ = gate.decide([run("in_progress", None)])
    assert verdict == gate.PENDING


def test_a_rerun_supersedes_the_attempt_it_replaced() -> None:
    """Newest first, as the API returns them. Requiring every historical
    attempt to be green would make a failed-then-fixed commit permanently
    unpublishable."""
    verdict, _ = gate.decide([run("completed", "success", "http://run/2"),
                              run("completed", "failure", "http://run/1")])
    assert verdict == gate.PASS


def test_a_fresh_failure_after_a_pass_still_blocks() -> None:
    """The same rule in the direction that must not be lenient."""
    verdict, _ = gate.decide([run("completed", "failure", "http://run/2"),
                              run("completed", "success", "http://run/1")])
    assert verdict == gate.FAIL


def test_missing_configuration_fails_rather_than_skips(monkeypatch, capsys) -> None:
    """An unconfigured gate that passes is indistinguishable from a working
    one. Catches the `if not token: return 0` shape, which is how a check ends
    up green on every run while reading nothing."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    assert gate.main([]) == 1
    assert "missing" in capsys.readouterr().out


def test_the_denominator_is_printed(monkeypatch, capsys) -> None:
    """How many runs were examined, not just the verdict. Without it a gate
    that queried the wrong workflow name reports the same silence as one that
    looked and found nothing wrong."""
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(gate, "fetch",
                        lambda *a, **k: [run("completed", "success")])

    assert gate.main(["--repo", "o/r", "--sha", "abc123def456"]) == 0
    out = capsys.readouterr().out
    assert "1 run(s) found" in out, out
    assert "abc123def456"[:12] in out, out


def test_a_network_failure_blocks_rather_than_allows(monkeypatch, capsys) -> None:
    """Asking and not getting an answer is not the same as getting a good one."""
    monkeypatch.setenv("GITHUB_TOKEN", "x")

    def explode(*_a, **_k):
        raise OSError("connection reset")

    monkeypatch.setattr(gate, "fetch", explode)
    assert gate.main(["--repo", "o/r", "--sha", "abc123"]) == 1
    assert "could not read workflow runs" in capsys.readouterr().out


def test_it_gives_up_rather_than_waiting_forever(monkeypatch, capsys) -> None:
    """A pending run must not hang the job indefinitely, and must fail when it
    runs out of patience rather than falling through to success."""
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(gate, "fetch", lambda *a, **k: [run("in_progress", None)])
    monkeypatch.setattr(gate.time, "sleep", lambda _s: None)

    assert gate.main(["--repo", "o/r", "--sha", "abc123",
                      "--timeout-seconds", "0"]) == 1
    assert "timed out" in capsys.readouterr().out
