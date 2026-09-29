"""The mutation harness's own bound: a mutant that hangs the suite is reported,
not waited for.

`run_suite` ran pytest with no timeout, so a mutation that made one test wait
forever - a git child reading stdin, a pool that never returns - hung the whole
campaign, which is hours long and runs unattended. pytest's
`faulthandler_timeout` (pytest.ini) names the test that is stuck; it does not
end it. Ending it is this harness's job, because the harness is what waits.
Chosen in Phase 57 over the pytest-timeout plugin: no dependency, no
`--strict-config` error where the plugin is not loaded, and no whole-process
exit on Windows that the harness would have counted as a kill it could not name.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "harnesses"))
import mutate  # noqa: E402


def _scratch_suite(tmp_path: Path, body: str) -> Path:
    (tmp_path / "test_scratch.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_suite_that_outlives_its_bound_is_reported_hung(tmp_path) -> None:
    """Catches `run_suite` waiting forever, and a hang read as a pass or as an
    ordinary failure: it returns None for the exit code, which is neither."""
    root = _scratch_suite(tmp_path, "import time\n\n\ndef test_waits():\n"
                                    "    time.sleep(60)\n")
    started = time.perf_counter()
    code, _out = mutate.run_suite(root, sys.executable,
                                  ["-q", "-p", "no:cacheprovider"], bound=3)
    took = time.perf_counter() - started
    assert code is None, f"a hung suite reported exit code {code}"
    assert took < 30, f"the bound of 3 s was not honoured: {took:.1f} s"


def test_the_bound_holds_when_a_grandchild_keeps_the_output_open(
        tmp_path) -> None:
    """Catches the bound waiting on processes the suite started.

    An xdist worker is started with its own stdin and stdout and inherits
    pytest's stderr, so it holds the harness's pipe. On Windows,
    `subprocess.run` answers a timeout by killing pytest and then reading the
    pipes to their end - which is when the last holder exits, and a worker
    stuck in a hung test never does. So `--parallel` on Windows, where the
    campaigns run, waited forever exactly as it did before the bound. This
    starts a grandchild the same way. Found by the review of the built
    tranche, 2026-09-29.
    """
    root = _scratch_suite(
        tmp_path,
        "import subprocess, sys, time\n\n\n"
        "def test_waits():\n"
        "    subprocess.Popen([sys.executable, '-c', 'import time; "
        "time.sleep(90)'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)\n"
        "    time.sleep(60)\n")
    started = time.perf_counter()
    code, _out = mutate.run_suite(root, sys.executable,
                                  ["-q", "-s", "-p", "no:cacheprovider"],
                                  bound=3)
    took = time.perf_counter() - started
    assert code is None, f"a hung suite reported exit code {code}"
    assert took < 30, f"the bound of 3 s was not honoured: {took:.1f} s"


def test_a_suite_inside_its_bound_answers_as_before(tmp_path) -> None:
    """The bound changes nothing for a suite that finishes."""
    root = _scratch_suite(tmp_path, "def test_passes():\n    assert True\n")
    code, _out = mutate.run_suite(root, sys.executable,
                                  ["-q", "-p", "no:cacheprovider"], bound=60)
    assert code == 0


def test_the_suite_names_a_hung_test_at_three_times_the_slowest() -> None:
    """Catches `faulthandler_timeout` removed, or set below the evidence.

    The number is three times the slowest test measured on any CI leg:
    `test_a_repository_rule_reports_its_one_fault_once`, 17.01 s on the
    Windows 3.10 leg in tranche 18's first run, under `-n auto` - and 4.20 and
    5.73 s on the same leg in the next two, so a single run is not the number
    and the worst of three is. Below it, a slow leg names a healthy test as
    hung; the setting ends nothing, so above it costs only a later name.
    """
    import configparser
    ini = configparser.ConfigParser()
    ini.read(Path(__file__).resolve().parent.parent / "pytest.ini",
             encoding="utf-8")
    assert ini.has_option("pytest", "faulthandler_timeout"), (
        "pytest.ini no longer names a hung test")
    assert float(ini.get("pytest", "faulthandler_timeout")) >= 3 * 17.01


def test_a_hung_mutant_is_killed_and_says_so(tmp_path) -> None:
    """A mutant whose suite hangs is a KILL - the suite did not pass - but a
    weak one, so `run_mutant` reports it as hung for the campaign to name."""
    root = _scratch_suite(tmp_path, "import time\n\n\ndef test_waits():\n"
                                    "    time.sleep(60)\n")
    green, _flipped, hung = mutate.run_mutant(root, sys.executable,
                                              parallel=False, bound=3)
    assert (green, hung) == (False, True)
