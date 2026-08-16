"""A catastrophically backtracking pattern becomes an error, not a hang.

Three approaches were considered and rejected before this one, and they are
recorded so nobody spends the afternoon rediscovering them:

  - A watchdog thread cannot work. `re` does not release the GIL while
    matching, so the watchdog never gets scheduled.
  - Static rejection of "dangerous" constructs is a heuristic, and its false
    positives reject patterns that work today. For that user it is worse than
    the hang.
  - An always-on subprocess costs one spawn per pattern, and `stress.py` case
    11 puts 200 files through this rule.

So process isolation is the mechanism and the option is off by default.
"""
from __future__ import annotations

import concurrent.futures
import re
import sys
import time
from pathlib import Path

import pytest


def _with_deadline(call, *, seconds: float):
    """Run `call`, failing the test rather than hanging the suite.

    The thread cannot be killed - `re` holds the GIL while matching, which is
    the whole reason this feature uses a subprocess - so the worker is left to
    finish on a daemon executor while the test reports the timeout. That is
    acceptable here and would not be in production code: the point is that a
    regression in the very timeout under test must surface as ONE failed test
    rather than as a suite that never returns.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(call)
    try:
        return future.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        pytest.fail(f"did not return within {seconds}s: the timeout it is "
                    f"meant to prove has regressed")
    finally:
        pool.shutdown(wait=False)

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

# A nested quantifier over an overlapping alternation, fed a string whose tail
# cannot match. The classic shape: the engine explores 2**40 paths and does not
# finish this side of the heat death of the universe.
EVIL = r"(a+)+b"
FEEDS = "a" * 40 + "c"

VALUE = re.compile(r'"v": "([^"]+)"')


def test_a_timeout_turns_a_hang_into_a_finding(
        git_repo, monkeypatch, reconfigure) -> None:
    import extant_collect as hc
    from extant.rules import consistency as rule
    repo, commit = git_repo
    commit("a.txt", FEEDS, "chore: a")
    commit("b.txt", FEEDS, "chore: b")

    pattern = re.compile(EVIL)
    monkeypatch.setattr(rule, "_consistency_for", lambda _ctx: {
        "evil": (("a.txt", pattern), ("b.txt", pattern)),
    })
    # Through the built Config, not the module global. The rule reads
    # `ctx.config.consistency_timeout` since it became
    # extant/rules/consistency.py, so setting the global alone leaves the
    # bound at its unbounded default - and this test then runs the
    # catastrophic pattern below with nothing to stop it.
    reconfigure(consistency_timeout=2.0)

    # A test for "it gives up" must not itself be able to hang forever. If the
    # timeout regresses, the catastrophic pattern below backtracks without
    # bound and this test would run until the whole suite was killed, which
    # reports as an infrastructure problem rather than as this bug.
    started = time.perf_counter()
    findings = _with_deadline(lambda: hc.validate_consistency(repo, ""),
                              seconds=60)
    elapsed = time.perf_counter() - started

    assert elapsed < 60, f"it did not give up: {elapsed:.0f}s"
    assert any("gave up" in f.detail for f in findings), [f.detail for f in findings]


def test_the_default_spawns_nothing(git_repo, monkeypatch, reconfigure) -> None:
    """The control, and the reason this is opt-in.

    If the default reached for a subprocess, every user would pay a spawn per
    pattern for a problem almost none of them have - 200 of them in this
    project's own stress case.
    """
    import extant_collect as hc
    from extant.rules import consistency as rule
    repo, commit = git_repo
    commit("a.json", '{"v": "1"}\n', "chore: a")
    commit("b.json", '{"v": "2"}\n', "chore: b")

    monkeypatch.setattr(rule, "_consistency_for", lambda _ctx: {
        "v": (("a.json", VALUE), ("b.json", VALUE)),
    })
    reconfigure(consistency_timeout=None)

    spawned: list[object] = []
    real_run = hc.subprocess.run

    def watched(*args, **kwargs):
        spawned.append(args)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(hc.subprocess, "run", watched)

    findings = hc.validate_consistency(repo, "")
    assert any("disagree" in f.detail for f in findings), [f.detail for f in findings]
    assert not spawned, f"the default spawned {len(spawned)} process(es)"


def test_a_bounded_search_still_returns_the_captured_value(
        git_repo, monkeypatch, reconfigure) -> None:
    """The other control. A timeout that broke normal matching would make every
    consistency check report a disagreement between a value and nothing."""
    import extant_collect as hc
    from extant.rules import consistency as rule
    repo, commit = git_repo
    commit("a.json", '{"v": "1.2.3"}\n', "chore: a")
    commit("b.json", '{"v": "1.2.3"}\n', "chore: b")

    monkeypatch.setattr(rule, "_consistency_for", lambda _ctx: {
        "v": (("a.json", VALUE), ("b.json", VALUE)),
    })
    reconfigure(consistency_timeout=10.0)

    findings = hc.validate_consistency(repo, "")
    assert not findings, (
        "two files agreeing under a bounded search must produce nothing: "
        + str([f.detail for f in findings])
    )
