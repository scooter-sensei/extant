"""`tests/harnesses/fuzz.py`'s driver: repositories examined side by side.

The driver builds and checks several repositories at once and must print
exactly what it printed one at a time, because the CI fuzz legs are compared
line for line and a seed has to name one corpus. What is pinned here is the
helper that makes that possible: results come back in plan order whatever
order they finish in, one job is the old loop exactly, and stopping early
leaves nothing queued. Whether the whole harness prints the same thing both
ways is checked by running one seed both ways, which is too slow for a test.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent / "harnesses"))


def _fuzz() -> ModuleType:
    """Imported late: `fuzz.py` pulls in the other harness modules."""
    import fuzz
    return fuzz


def test_results_come_back_in_plan_order_whatever_finishes_first() -> None:
    """Catches results yielded as they complete rather than as planned.

    The driver zips them against the plan, so an out-of-order result would
    be printed, counted and saved against another repository's index - a
    fault reported on a repository that does not have it.
    """
    fuzz = _fuzz()
    delays = [0.3, 0.0, 0.2, 0.0, 0.1]

    def examine(i: int) -> int:
        time.sleep(delays[i])
        return i

    assert list(fuzz.examined_in_order(list(range(5)), examine, 4)) == \
        [0, 1, 2, 3, 4]


def test_several_jobs_really_run_at_once() -> None:
    """Catches a pool that quietly runs one repository at a time.

    Two examines meet at a barrier, which only opens if both are running
    together; one job at a time would wait out its timeout and raise.
    """
    fuzz = _fuzz()
    met = threading.Barrier(2, timeout=10)

    def examine(i: int) -> int:
        met.wait()
        return i

    assert list(fuzz.examined_in_order([0, 1], examine, 2)) == [0, 1]


def test_one_job_is_the_old_loop_in_this_thread() -> None:
    """Catches `--jobs 1` going through a pool after all.

    A pool would build the next repository while the driver is still
    shrinking the last violation, which the serial driver never did.
    """
    fuzz = _fuzz()
    here = threading.get_ident()
    seen: list[int] = []

    def examine(i: int) -> int:
        seen.append(threading.get_ident())
        return i

    results = fuzz.examined_in_order([0, 1, 2], examine, 1)
    assert seen == []          # lazy: nothing examined before it is asked for
    assert next(results) == 0 and seen == [here]
    assert list(results) == [1, 2] and seen == [here] * 3


def test_stopping_early_cancels_what_was_queued() -> None:
    """Catches a driver that raised still building every repository left.

    The interpreter would wait for the whole queue before reporting the
    failure, and the arena would fill with repositories nobody judged.
    """
    fuzz = _fuzz()
    started: list[int] = []

    def examine(i: int) -> int:
        started.append(i)
        time.sleep(0.2)
        return i

    results = fuzz.examined_in_order(list(range(20)), examine, 2)
    assert next(results) == 0
    results.close()
    assert len(started) < 20, f"all {len(started)} were examined anyway"
