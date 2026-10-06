"""`tests/harnesses/fuzz.py --self-check`, the parts that cost nothing to pin.

The self-check itself builds a repository and runs extant dozens of times, so
it runs as a CI step rather than as a test. What is pinned here is the budget
its HANG breakage is observed under: the step was 206 seconds in CI on
2026-10-01, 181 of them that one breakage waiting out the corpus's 90-second
TIMEOUT twice, and the bound that replaced it must stay both short and safe.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "harnesses"))


def _harness():
    """Imported late: `fuzz.py` pulls in the other harness modules."""
    import fuzz
    import fuzz_selfcheck
    return fuzz, fuzz_selfcheck


def test_only_the_hang_breakage_outlasts_the_budget() -> None:
    """Catches the shortened budget reaching a breakage that does not hang.

    A red half run under a short bound can fire HANG on a slow run, and
    `check` returns HANG alone, so the property that breakage exists to
    provoke would never be looked at: NOT OBSERVED, about a property that
    works. And catches the flag going missing from HANG, which costs nothing
    but time - the step's 181 seconds again, with nothing to say so.
    """
    _fuzz, selfcheck = _harness()
    flagged = [item.prop for item in selfcheck.BREAKAGES
               if item.outlasts_the_budget]
    assert flagged == ["HANG"], flagged


@pytest.mark.parametrize("clean, expected", [
    (0.4, 10.0),     # a fast clean half gets the floor, not a bound of 1.2 s
    (5.0, 15.0),     # a slower one, three times what it took
    (60.0, 90.0),    # never more than the corpus's own TIMEOUT
])
def test_the_red_budget_scales_from_the_clean_half(clean, expected) -> None:
    """Catches the budget losing its floor, its scale or its ceiling.

    The floor and the scale are what stop a red half that did NOT hang - a
    breakage that stopped biting - from passing for one on a noisy runner.
    The ceiling keeps a slow clean half from making the self-check slower
    than the corpus's TIMEOUT made it.
    """
    fuzz, selfcheck = _harness()
    assert selfcheck.red_budget(clean, fuzz.TIMEOUT) == expected


def test_a_bound_reaches_every_run_and_is_lifted_however_the_block_ends(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Catches `bounded` not reaching `run_mode`, or leaking past its block.

    The first leaves the HANG breakage paying the full TIMEOUT twice, which
    is the cost this exists to remove. The second is worse: every later
    property would run under a few seconds' budget, and a slow run of any of
    them would report HANG instead of the property it was watching for.
    """
    fuzz, _selfcheck = _harness()
    monkeypatch.setattr(fuzz, "_argv", lambda repo, mode: [
        sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setattr(fuzz, "_stdin_for", lambda repo, mode: None)
    full = fuzz.TIMEOUT

    started = time.perf_counter()
    with pytest.raises(RuntimeError):
        with fuzz.bounded(1):
            assert fuzz.TIMEOUT == 1
            assert fuzz.run_mode(tmp_path, ["--verify"]) is None
            raise RuntimeError("the block ends badly")
    took = time.perf_counter() - started

    assert took < 20, f"run_mode waited {took:.0f} s under a 1 s bound"
    assert fuzz.TIMEOUT == full
