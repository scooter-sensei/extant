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

Two more here are what a faster campaign would expose: the node id a
`--parallel` kill is confirmed by, and a rewrite that stale bytecode cannot
hide.

The rest pin the environment every suite runs in, which is what took a
steady-state campaign from 1,700 s to 1,160 s on 2026-10-01 with identical
verdicts: no plugin autoload, no `git maintenance` child per commit, git
called past Git for Windows' launcher, and a temp root of its own that is
removed off the critical path.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "harnesses"))
import mutate  # noqa: E402


def _scratch_suite(tmp_path: Path, body: str) -> Path:
    (tmp_path / "test_scratch.py").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_suite_that_outlives_its_bound_is_reported_hung(tmp_path: Path) -> None:
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
        tmp_path: Path) -> None:
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


def test_a_suite_inside_its_bound_answers_as_before(tmp_path: Path) -> None:
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


def test_a_failing_test_is_rerun_by_the_name_pytest_printed(tmp_path: Path) -> None:
    """Catches `--parallel`'s confirmation reading a node id it cannot rerun.

    pytest drops the " - message" tail of a short-summary line with no room
    left at 80 columns, and 84 per cent of this suite's node ids leave none.
    On Windows such a line ends in the carriage return the console wrote, the
    pattern kept it, and the rerun asked for a test that does not exist: exit
    4, not 1. Every such kill then fell through to a whole serial suite. The
    verdict survived it; the time did not - on five anchors on 2026-09-30,
    `--parallel` took longer than serial. The literal line fails on every
    platform; the rerun fails where the console writes CRLF.
    """
    name = "test_" + "a_name_that_leaves_no_room_for_the_message_" * 2
    root = _scratch_suite(tmp_path, f"def {name}():\n    assert False\n")
    node = f"test_scratch.py::{name}"
    assert mutate._FAILED_NODE.findall(f"FAILED {node}\r\n") == [node]

    _code, out = mutate.run_suite(root, sys.executable,
                                  ["-q", "-rfE", "-p", "no:cacheprovider"])
    nodes = mutate._FAILED_NODE.findall(out)
    assert nodes == [node], nodes
    code, _out = mutate.run_suite(root, sys.executable, targets=nodes)
    assert code == mutate._TESTS_FAILED, f"the rerun exited {code}"


def test_a_rewrite_in_the_same_second_is_never_served_stale_bytecode(
        tmp_path: Path) -> None:
    """Catches a mutant that never runs, and a restore that runs the mutant.

    CPython trusts a cached .pyc while the source keeps its size and its
    whole-second mtime (bpo-31772, still open). Most anchors change a file's
    size; 13 of the 357 on 2026-09-30 did not - one character for another.
    Written and restored inside one second, the mutant's suite imported the
    ORIGINAL's bytecode, a false SURVIVED, or the restored file went on
    running the mutant's. Measured with a fast suite: 29 and 21 cycles of 50.
    A campaign's suites take minutes, which is all that kept it latent, so
    anything that makes a mutant cheap exposes it. The sleep starts the
    cycles just past a second boundary, so the writes below share one.
    """
    target = tmp_path / "target.py"
    original, mutant = "FLAG = '-z'\n", "FLAG = '-Z'\n"
    env = {k: v for k, v in os.environ.items()
           if k != "PYTHONDONTWRITEBYTECODE"}

    def imported() -> str:
        return subprocess.run(
            [sys.executable, "-c", "import target; print(target.FLAG)"],
            cwd=tmp_path, env=env, capture_output=True, text=True,
            check=True).stdout.strip()

    mutate.write_source(target, original)
    assert imported() == "-z"
    time.sleep(1.02 - time.time() % 1)
    for _ in range(3):
        mutate.write_source(target, mutant)
        ran_mutant = imported()
        mutate.write_source(target, original)
        ran_original = imported()
        assert (ran_mutant, ran_original) == ("-Z", "-z")


def test_a_hung_mutant_is_killed_and_says_so(tmp_path: Path) -> None:
    """A mutant whose suite hangs is a KILL - the suite did not pass - but a
    weak one, so `run_mutant` reports it as hung for the campaign to name."""
    root = _scratch_suite(tmp_path, "import time\n\n\ndef test_waits():\n"
                                    "    time.sleep(60)\n")
    green, _flipped, hung = mutate.run_mutant(root, sys.executable,
                                              parallel=False, bound=3)
    assert (green, hung) == (False, True)


def test_every_suite_runs_with_plugin_autoload_off(tmp_path: Path) -> None:
    """Catches `run_suite` starting pytest with every plugin the operator has
    installed. The suite needs none of them, and importing them cost 0.44 s
    per pytest start on 2026-09-30 - a campaign starts hundreds."""
    root = _scratch_suite(
        tmp_path, "import os\n\n\ndef test_env():\n"
                  "    assert os.environ.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD') == '1'\n")
    code, out = mutate.run_suite(root, sys.executable,
                                 ["-q", "-p", "no:cacheprovider"])
    assert code == 0, out


def test_a_parallel_suite_still_loads_xdist(tmp_path: Path) -> None:
    """Catches `--parallel` left relying on autoload. With autoload off, `-n`
    is an unknown option unless xdist is named - and a usage error at the
    baseline reads as SUITE IS ALREADY RED."""
    pytest.importorskip("xdist")
    root = _scratch_suite(tmp_path, "def test_passes():\n    assert True\n")
    code, out = mutate.run_suite(root, sys.executable, mutate._PARALLEL)
    assert code == 0, out


def test_a_git_child_of_the_suite_runs_no_auto_maintenance(tmp_path: Path) -> None:
    """Catches the suite's commits each starting `git maintenance run --auto`.

    1,580 of them in one run of the suite, and none does anything in a
    repository this size: `gc.auto` wants 6,700 loose objects. A commit took
    95 ms with its child and 60 ms without, and the detached child goes on
    writing inside `.git` while the fixture is being removed.
    """
    root = _scratch_suite(
        tmp_path, "import subprocess\n\n\ndef test_config():\n"
                  "    got = subprocess.run(['git', 'config', '--get', 'maintenance.auto'],\n"
                  "                         capture_output=True, text=True).stdout.strip()\n"
                  "    assert got == 'false', repr(got)\n")
    code, out = mutate.run_suite(root, sys.executable,
                                 ["-q", "-p", "no:cacheprovider"])
    assert code == 0, out


def test_maintenance_is_appended_to_the_operators_own_git_config() -> None:
    """Catches the setting written over the operator's `GIT_CONFIG_COUNT`.

    git reads the triplet from index 0 to count-1, so writing index 0 would
    drop whatever the operator injected - CI trusts its checkout through
    `safe.directory` that way. A count git cannot parse is left exactly as it
    is, the rule `environment()` in extant/git.py follows for the same reason:
    git refuses it in the parent too.
    """
    env = mutate.child_environment(
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory",
         "GIT_CONFIG_VALUE_0": "*"}, platform="linux")
    assert [env[k] for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0",
                             "GIT_CONFIG_VALUE_0", "GIT_CONFIG_KEY_1",
                             "GIT_CONFIG_VALUE_1")] == [
        "2", "safe.directory", "*", "maintenance.auto", "false"]
    bogus = mutate.child_environment({"GIT_CONFIG_COUNT": "x"}, platform="linux")
    assert bogus["GIT_CONFIG_COUNT"] == "x" and "GIT_CONFIG_KEY_0" not in bogus


def _fake_git_for_windows(tmp_path: Path) -> Path:
    """The two git.exe files and the usr/bin a Git for Windows install has."""
    root = tmp_path / "Git"
    for sub in ("cmd", "mingw64/bin"):
        (root / sub).mkdir(parents=True)
        (root / sub / "git.exe").write_bytes(b"")
    (root / "usr" / "bin").mkdir(parents=True)
    return root


def test_git_is_called_past_the_windows_launcher(tmp_path: Path) -> None:
    """Catches every git call paying Git for Windows' launcher.

    `Git/cmd/git.exe` only sets a few variables and starts
    `Git/mingw64/bin/git.exe` as a second process: 59 ms against 33 ms per
    call on 2026-09-30, and the suite makes about 6,000. So the real binary
    goes first, with what the launcher would have set around it - its two
    directories on PATH, `MSYSTEM`, and `PLINK_PROTOCOL` only where unset.
    """
    root = _fake_git_for_windows(tmp_path)
    path = os.pathsep.join([str(tmp_path / "elsewhere"), str(root / "cmd"),
                            str(tmp_path / "after")])
    env = mutate.child_environment({"PATH": path}, platform="win32")
    assert env["PATH"].split(os.pathsep) == [
        str(root / "mingw64" / "bin"), str(root / "usr" / "bin"),
        *path.split(os.pathsep)]
    assert (env["MSYSTEM"], env["PLINK_PROTOCOL"]) == ("MINGW64", "ssh")
    kept = mutate.child_environment({"PATH": path, "PLINK_PROTOCOL": "plink"},
                                    platform="win32")
    assert kept["PLINK_PROTOCOL"] == "plink"


def test_the_path_is_left_alone_where_git_is_already_direct(tmp_path: Path) -> None:
    """Git Bash already puts the real binary first, and no other platform has
    a launcher: there is nothing to reroute, so PATH is not touched."""
    root = _fake_git_for_windows(tmp_path)
    direct = os.pathsep.join([str(root / "mingw64" / "bin"), str(root / "cmd")])
    assert mutate.child_environment({"PATH": direct}, platform="win32")["PATH"] == direct
    launcher = str(root / "cmd")
    unix = mutate.child_environment({"PATH": launcher}, platform="linux")
    assert unix["PATH"] == launcher and "MSYSTEM" not in unix


_GIT_FOR_WINDOWS = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git"


@pytest.mark.skipif(sys.platform != "win32"
                    or not (_GIT_FOR_WINDOWS / "cmd" / "git.exe").is_file(),
                    reason="needs Git for Windows' launcher")
def test_a_suite_on_windows_finds_the_real_git_first(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same, end to end: PATH as PowerShell gives it, launcher first, and
    the suite's own `git` must still be the real binary."""
    monkeypatch.setenv("PATH", os.pathsep.join([str(_GIT_FOR_WINDOWS / "cmd"),
                                                os.environ.get("PATH", "")]))
    root = _scratch_suite(
        tmp_path, "import shutil\nfrom pathlib import Path\n\n\ndef test_which():\n"
                  "    (Path(__file__).parent / 'which.txt').write_text(shutil.which('git'))\n")
    code, out = mutate.run_suite(root, sys.executable,
                                 ["-q", "-p", "no:cacheprovider"])
    assert code == 0, out
    found = Path((tmp_path / "which.txt").read_text()).parent
    assert os.path.normcase(str(found)) == os.path.normcase(
        str(_GIT_FOR_WINDOWS / "mingw64" / "bin")), found


def test_every_suite_gets_its_own_temp_root_and_it_is_removed(tmp_path: Path) -> None:
    """Catches the suite using pytest's shared numbered root, and a removal
    that stops at git's read-only objects.

    pytest keeps its three newest `pytest-N` directories and the next process
    to EXIT deletes the oldest. After a whole suite that is thousands of
    repositories, and the deletion cost 36-65 s - inside whichever run exited
    next, a single kill check included. A root of the run's own is removed
    by the harness instead, off the critical path. On Windows `rmtree`
    refuses a read-only file (WinError 5), and git writes every loose object
    read-only; with `ignore_errors` the refusal is silent and the tree stays.
    """
    root = _scratch_suite(
        tmp_path, "import os, stat\nfrom pathlib import Path\n\n\n"
                  "def test_writes(tmp_path):\n"
                  "    obj = tmp_path / 'object'\n"
                  "    obj.write_text('x')\n"
                  "    os.chmod(obj, stat.S_IREAD)\n"
                  "    (Path(__file__).parent / 'where.txt').write_text(str(tmp_path))\n")
    code, out = mutate.run_suite(root, sys.executable,
                                 ["-q", "-p", "no:cacheprovider"])
    assert code == 0, out
    used = Path((tmp_path / "where.txt").read_text())
    assert "pytest-of-" not in str(used), f"pytest's shared root was used: {used}"
    mutate.finish_cleanup()
    assert not used.exists(), f"left behind: {used}"
