"""The suite's `--order-seed` option: a third order, on purpose.

CI runs the suite in file order on Linux and in each file's order on Windows
(`-n auto --dist loadfile`), and on 2026-09-28 a test that left a raising
rule's entry in `RULE_ERRORS` was invisible to both - two orders agreeing
shows those two orders agree, not that every order does. The autouse guard
in conftest.py closes that one class. `--order-seed N` is the instrument for
the classes nobody has found yet: it shuffles the collected tests with seed
N, and one Linux leg in CI runs the suite that way a second time.

These tests pin the three properties that leg depends on. A seed must
actually move tests, or the step is a second file-order run printing what a
shuffled one prints. The same seed must give the same order, or a failure
on CI cannot be reproduced here - and xdist refuses to start when its
workers collect different orders. And no seed must mean no change, because
the serial file-order run stays the definition of correctness.
"""
from __future__ import annotations

import functools
import subprocess
import sys

from conftest import PACKAGE_ROOT

# Eleven tests: 11! orders, so a seeded shuffle that happened to come back
# unchanged is a one-in-forty-million accident rather than a flake. Chosen
# because it collects without touching git.
_TARGET = "tests/test_module_quality.py"
# The seed the shuffled CI step runs, so these tests exercise that very order.
_SEED = "--order-seed=20260928"


def _collect(*options: str) -> tuple[str, ...]:
    """The node ids pytest would run, in the order it would run them."""
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only",
         "-p", "no:cacheprovider", _TARGET, *options],
        cwd=PACKAGE_ROOT, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    ids = tuple(line for line in done.stdout.splitlines() if "::" in line)
    # An empty list compares equal to an empty list: the instrument would
    # then "agree" with itself having measured nothing.
    assert len(ids) >= 10, f"collected {len(ids)} from {_TARGET}:\n{done.stdout}"
    return ids


# Each collection is a pytest start, and five of them made these the slowest
# tests of a serial Linux run (2026-09-28, 14 seconds under WSL). Three are
# enough: file order and the seed once each, shared, and one fresh process
# for the test whose point is that a SECOND process agrees.
_collected = functools.lru_cache(maxsize=None)(_collect)


def test_an_order_seed_moves_the_tests_and_loses_none() -> None:
    plain = _collected()
    shuffled = _collected(_SEED)
    assert sorted(shuffled) == sorted(plain), "a shuffle must be a permutation"
    assert shuffled != plain, "the seed ran the tests in file order"


def test_one_seed_gives_one_order() -> None:
    assert _collect(_SEED) == _collected(_SEED)


def test_without_a_seed_the_suite_keeps_its_file_order() -> None:
    plain = _collected()
    names = [node.split("::", 1)[1] for node in plain]
    source = (PACKAGE_ROOT / _TARGET).read_text(encoding="utf-8")
    positions = [source.index(f"def {name}(") for name in names]
    assert positions == sorted(positions), names
