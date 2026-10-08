"""What `--collect` hands off, compared WHOLE.

D7 found 139 of collect.py's 480 mutants alive after the whole suite: 49
in `collect`, 37 in `run_suite`, 19 in `read_plan`, 13 in `scan_todos`.
The tests asserted single fields of the bundle - the files a TODO was
found in, whether the suite was supplied - so a renamed key, a branch
resolved the wrong way, a TODO scan that stopped early or a measured
suite run in the wrong directory went unseen.

Three repositories, each compared whole: one with a boundary and work
after it, built to reach every branch of the bundle; one on an unborn
branch; one whose status document has never been committed, so there is
no boundary. Beside them, the errors the suite runner raises and the
pieces the bundle is built from, where a branch is only reachable from a
setting the bundle's own fixtures do not set.
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from extant import collect, session

CAFE = "caf" + chr(0xE9)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout


def _init(root: Path, branch: str = "main") -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", branch)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")
    return repo


def _commit(repo: Path, files: dict[str, bytes], message: str) -> str:
    for name, data in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _bundle(repo: Path, suite_json: str | None = None) -> dict[str, Any]:
    session.reload_config(repo)
    return collect.collect(repo, suite_json, session.config(), session.CONFIG)


def test_a_bundle_with_a_boundary_is_compared_whole(tmp_path: Path) -> None:
    """The boundary is the last commit touching the status document; every
    commit after it is listed with the phase its subject names - the bare
    `Phase` pattern is switched off, so only the task suffix counts. The
    suite is MEASURED, by a command that reads a file beside it, so it must
    run in the repository. TODOs are read from the code files the work
    changed: past an excluded file that sorts first, not in an excluded
    directory or in markdown, and a file that is not UTF-8 named apart. The
    newest plan's boxes, one of them not ASCII. A branch merged into the
    trunk is not listed; one that is not, is."""
    python = Path(sys.executable).as_posix()
    repo = _init(tmp_path)
    boundary = _commit(repo, {
        ".extant.toml": (
            'primary_doc = "STATUS.md"\n'
            "phase_bare = ''\n"
            'plans_dir = "docs/plans"\n'
            'todo_exclude_files = ["_skip.py"]\n'
            'todo_exclude_dirs = ["vendor/"]\n'
            f"venv_python = '{python}'\n"
            "suite_command = ['{python}', '-c', "
            "'import sys; print(open(\"result.txt\").read()); sys.exit(3)']\n"
        ).encode(),
        "STATUS.md": b"# Status\n",
        "result.txt": b"7 passed, 2 failed in 1.25s\n",
        "docs/plans/2026-01-01-old.md": b"- [x] done long ago\n",
        "docs/plans/2026-02-01-new.md":
            ("- [x] wrote it\n- [ ] ship it\n  - [x] " + CAFE + "\n").encode(),
    }, "docs: status")
    first = _commit(repo, {"_skip.py": b"# TODO: excluded file\n",
                           "a.py": b"x = 1  # TODO: tidy\n"},
                    "feat: thing (9.6 Task 5)")
    _git(repo, "branch", "feature/merged")
    second = _commit(repo, {"vendor/v.py": b"# TODO: excluded directory\n",
                            "b.py": b"# caf\xe9\n",
                            "notes.md": b"TODO: not code\n"}, "Phase 9.5b fix")
    _git(repo, "checkout", "-q", "-b", "feature/open")
    _commit(repo, {"c.py": b"y = 2\n"}, "feat: open work")
    _git(repo, "checkout", "-q", "main")

    assert _bundle(repo) == {
        "boundary_sha": boundary,
        "commits": [
            {"sha": first, "subject": "feat: thing (9.6 Task 5)", "phase": "9.6"},
            {"sha": second, "subject": "Phase 9.5b fix", "phase": "unknown"}],
        "nothing_to_hand_off": False,
        "suite": {"passed": 7, "failed": 2, "duration_s": 1.25,
                  "source": "measured", "exit_code": 3},
        "todos": [{"file": "a.py", "line": 1, "text": "x = 1  # TODO: tidy"}],
        "todos_unread": [{"file": "b.py",
                          "why": "not valid UTF-8 (invalid continuation byte at byte 5)"}],
        "plan": {"path": "docs/plans/2026-02-01-new.md",
                 "completed": ["wrote it", CAFE], "remaining": ["ship it"],
                 "checkbox_tracking": True},
        "git": {"branch": "main", "unmerged_branches": ["feature/open"]},
    }


def test_a_bundle_on_an_unborn_branch_is_compared_whole(tmp_path: Path) -> None:
    """No commit, so no boundary, no work and no branch to compare - and the
    branch the first commit WILL be on, as `git status` names it. The plan
    switched off is said to be off; a supplied suite result is read as
    UTF-8 whatever the platform's locale."""
    repo = _init(tmp_path, branch="trunkless")
    (repo / ".extant.toml").write_bytes(b'plans_dir = ""\n')
    supplied = tmp_path / "suite.json"
    supplied.write_bytes(json.dumps({"passed": 4, "note": CAFE},
                                    ensure_ascii=False).encode("utf-8"))

    assert _bundle(repo, str(supplied)) == {
        "boundary_sha": "",
        "commits": [],
        "nothing_to_hand_off": True,
        "suite": {"passed": 4, "note": CAFE, "source": "supplied"},
        "todos": [],
        "todos_unread": [],
        "plan": {"path": "", "completed": [], "remaining": [], "enabled": False},
        "git": {"branch": "trunkless", "unmerged_branches": []},
    }


def test_a_bundle_with_no_boundary_lists_every_commit(tmp_path: Path) -> None:
    """The status document was never committed, so there is no boundary:
    every commit is work to hand off, every tracked code file is read, and
    the plan directory the default names is absent."""
    repo = _init(tmp_path)
    first = _commit(repo, {"t.py": b"# TODO: here\n"}, "feat: a (9.6 Task 5)")
    second = _commit(repo, {"u.py": b"z = 3\n"}, "fix: b")
    supplied = tmp_path / "suite.json"
    supplied.write_text('{"passed": 1}', encoding="utf-8")

    assert _bundle(repo, str(supplied)) == {
        "boundary_sha": "",
        "commits": [
            {"sha": first, "subject": "feat: a (9.6 Task 5)", "phase": "9.6"},
            {"sha": second, "subject": "fix: b", "phase": "unknown"}],
        "nothing_to_hand_off": False,
        "suite": {"passed": 1, "source": "supplied"},
        "todos": [{"file": "t.py", "line": 1, "text": "# TODO: here"}],
        "todos_unread": [],
        "plan": {"path": "", "completed": [], "remaining": [],
                 "checkbox_tracking": False},
        "git": {"branch": "main", "unmerged_branches": []},
    }


def test_a_suite_with_no_interpreter_says_what_it_tried(tmp_path: Path) -> None:
    status = dataclasses.replace(session.CONFIG, venv_python="",
                                 suite_command=("{python}", "-m", "pytest"))
    tried = "\n  ".join(str(p) for p in collect._python_candidates(tmp_path, status))
    with pytest.raises(RuntimeError) as raised:
        collect.run_suite(tmp_path, None, status)
    assert str(raised.value) == (
        "no project interpreter found, and suite_command needs one "
        "({python} -m pytest). Tried:\n  " + tried + "\n"
        "If this is a worktree, that is expected - .venv is gitignored and "
        "exists only in the main working tree. Pass --suite-json <path> with a "
        "result measured there, or set suite_command to something that does "
        "not use {python}.")


def test_a_suite_command_that_cannot_run_says_so(tmp_path: Path) -> None:
    status = dataclasses.replace(session.CONFIG,
                                 suite_command=("no-such-command-zz9", "-q"))
    with pytest.raises(RuntimeError) as raised:
        collect.run_suite(tmp_path, None, status)
    message = str(raised.value)
    assert message.startswith("suite_command not runnable: no-such-command-zz9 -q ("), message
    assert message.endswith("). Check the command exists on PATH, or pass --suite-json."), message


def test_a_summary_missing_a_count_reads_zero(tmp_path: Path) -> None:
    """A runner that prints no `passed` and no duration: each reads 0."""
    assert collect.parse_pytest_summary("3 failed", session.CONFIG) == {
        "passed": 0, "failed": 3, "duration_s": 0.0}


def test_each_phase_pattern_works_with_the_other_off() -> None:
    """Only both off means "no phases here" (None); one off leaves the
    other to answer, and "unknown" when it does not. Each variant is built
    from the shipped defaults, which set both."""
    base = session.config()
    assert base.phase_task is not None and base.phase_bare is not None
    no_bare = dataclasses.replace(base, phase_bare=None)
    assert collect.parse_phase("feat: thing (9.6 Task 5)", no_bare) == "9.6"
    assert collect.parse_phase("Phase 9.5b fix", no_bare) == "unknown"
    no_task = dataclasses.replace(base, phase_task=None)
    assert collect.parse_phase("feat: thing (9.6 Task 5)", no_task) == "unknown"
    assert collect.parse_phase("Phase 9.5b fix", no_task) == "9.5b"
    neither = dataclasses.replace(base, phase_task=None, phase_bare=None)
    assert collect.parse_phase("Phase 9.5b fix", neither) is None


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs POSIX permissions and a user they bind")
def test_a_code_file_that_cannot_be_opened_is_named_with_why(tmp_path: Path) -> None:
    """Not readable at all - not merely undecodable - and the scan goes on
    past it to the files after it."""
    repo = _init(tmp_path)
    _commit(repo, {"STATUS.md": b"# Status\n"}, "docs: status")
    _commit(repo, {"a.py": b"# a\n", "b.py": b"# TODO: after\n"}, "feat: two")
    (repo / "a.py").chmod(0)
    session.reload_config(repo)
    try:
        unread: list[dict[str, str]] = []
        found = collect.scan_todos(repo, _git(repo, "rev-parse", "HEAD~1").strip(),
                                   session.config(), unread=unread)
    finally:
        (repo / "a.py").chmod(0o644)
    assert (found, unread) == (
        [{"file": "b.py", "line": 1, "text": "# TODO: after"}],
        [{"file": "a.py", "why": "could not be read (PermissionError)"}])
