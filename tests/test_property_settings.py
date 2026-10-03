"""How the properties in tests/test_properties.py run, held from outside them.

Three things decide what a property can find, and none of them lives in the
property module, so none can be held there - a mutation that skipped the
module would skip a guard written inside it too. Each of the first two
SURVIVED the whole suite as a mutation in Phase 62's gap audit:

- WHETHER it runs. The module skips below 3.10, where no Hypothesis
  installs. A skip prints as an `s`: with the bound moved to (3, 99) every
  property skipped on every leg, the suite stayed green, and only `-ra`'s
  summary line said so.
- UNDER WHICH PROFILE. tests/conftest.py loads `ci` unless a run asks for
  another. A conftest that registered it and never loaded it, or loaded one
  that drew at random, left the suite green as well.
- ON WHAT THE DRAWS DEPEND. Derandomized is not deterministic while
  Hypothesis mines constants from whatever the process has imported;
  tests/conftest.py holds that pool empty, and the third test asks whether
  it still is.
"""
from __future__ import annotations

import importlib
import sys

import pytest

RUNS = sys.version_info >= (3, 10)
NO_HYPOTHESIS = "no Hypothesis installs below 3.10"


def test_the_properties_skip_below_3_10_and_run_from_it() -> None:
    """Imported as collection imports it, so a skip raised there is the skip
    pytest would print. Already imported, it is simply returned; a module
    that skipped at collection is not in `sys.modules` and raises again."""
    try:
        importlib.import_module("test_properties")
    except pytest.skip.Exception as skipped:
        assert not RUNS, (f"the properties skip on {sys.version.split()[0]}: "
                          f"{skipped}")
    else:
        assert RUNS, "the properties ran below 3.10, where nothing installs them"


@pytest.mark.skipif(not RUNS, reason=NO_HYPOTHESIS)
def test_the_ci_profile_is_loaded_unless_a_run_asks_for_another(
        pytestconfig: pytest.Config) -> None:
    """Derandomized, no database, the budget the module's costs were measured
    at, and Hypothesis's own CI suppression of the `too_slow` health check -
    a timing check, which is no verdict on a slow runner."""
    from hypothesis import HealthCheck, settings
    asked = pytestconfig.getoption("hypothesis_profile", None)
    current = settings.get_current_profile_name()
    if asked:
        assert current == asked, (current, asked)
        return
    assert current == "ci", current
    loaded = settings.default
    assert loaded is not None
    assert loaded.derandomize is True
    assert loaded.database is None
    assert loaded.max_examples == 500
    assert loaded.deadline is None
    assert HealthCheck.too_slow in loaded.suppress_health_check, \
        loaded.suppress_health_check


# A module Hypothesis would mine: strings it may draw for the property below
# (over its alphabet, no longer than its bound) and integers outside the
# small range it already favours. Its name and directory hold no `test`,
# which is what Hypothesis takes for test code and leaves alone.
FRESH = "drawn_constants_probe"
CONSTANTS = (
    'WORDS = ["ab#`", "#b#a", "`a`b`", "a#a#a", "``#b", "bb##aa", "#`#`"]\n'
    "NUMBERS = [123456, 987654, 4242, 31337, 271828]\n"
)


@pytest.mark.skipif(not RUNS, reason=NO_HYPOTHESIS)
def test_a_derandomized_property_draws_the_same_whatever_was_imported(
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """One property, run twice derandomized, with a fresh module of
    constants imported between the runs: the same examples, in the same
    order. With the pool mined, the second run drew the new constants -
    which is how the draws came to depend on which files a worker had run
    before, and on running a test alone."""
    from hypothesis import given, settings
    from hypothesis import strategies as st
    drawn: list[tuple[str, int]] = []

    @settings(max_examples=200, derandomize=True, database=None)
    @given(st.text(alphabet="ab#`", max_size=8), st.integers(0, 10**6))
    def draw(text: str, number: int) -> None:
        drawn.append((text, number))

    draw()
    first = list(drawn)
    drawn.clear()
    home = tmp_path_factory.mktemp("constants")
    (home / f"{FRESH}.py").write_text(CONSTANTS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(home))
    try:
        importlib.import_module(FRESH)
        draw()
    finally:
        sys.modules.pop(FRESH, None)
    assert len(first) == 200
    changed = [i for i, (a, b) in enumerate(zip(first, drawn)) if a != b]
    assert drawn == first, (f"{len(changed)} of {len(first)} draws moved, "
                            f"first at {changed[:1]}")
