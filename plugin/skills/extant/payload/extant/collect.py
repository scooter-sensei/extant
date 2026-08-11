"""The --collect handoff bundle.

Shares nothing with validation. It reached the same file as the rules for
historical reasons and is separated here so that working on a rule never
requires reading it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


# The seam, one module-level instance, rather than the underscore names this
# file used to qualify. Two things go away with them.
#
# The first is a boundary violation the gate could not see. Reaching for a
# private helper as a module ATTRIBUTE slipped past
# test_no_module_reaches_past_another_modules_surface, which reads imports and
# so only catches the `from extant.git import` spelling. Both helpers are
# private again now that git.py declares Git/SubprocessGit/CountingGit, and
# nothing here names either.
#
# The second is a trap this comment used to describe rather than fix. Call
# sites qualifying the helper off the git MODULE meant a test patching the same
# name on the SHIM intercepted nothing here - a different module object - so a
# test written against collect(), find_boundary(), commits_since() or
# changed_files() would exercise the real function and pass while testing
# nothing. Swap `_GIT` and every one of the four is covered, by the same
# CountingGit the shim's tests use.
from extant.git import CountingGit, Git, SubprocessGit    # noqa: F401
#                      ^ re-exported so a test can install one here.

# Configuration arrives as an ARGUMENT to every function here that needs it,
# and these are the two types it comes in. `Config` carries what is DERIVED
# from a project's settings; `StatusConfig` is the settings themselves, needed
# by the four functions below that read a value nothing was ever derived from
# (`suite_command`, `venv_python`, `plans_dir`, the three `suite_*` patterns).
#
# A module-level import is safe here where it was not for the shim's CONFIG:
# these are classes, fixed for the life of the process, not a name that
# `reload_config` rebinds. extant/config.py imports nothing from this package,
# so there is no cycle either.
from extant.config import Config, StatusConfig

# Installed, not imported at each call site, so a test can replace it. See the
# note above the git import for the trap that was there before it could be.
_GIT: Git = SubprocessGit()

__all__ = [
    "_CHECKED", "_PYTEST_DURATION", "_PYTEST_FAILED", "_PYTEST_PASSED",
    "_UNCHECKED", "_VENV_LAYOUTS", "_python_candidates", "changed_files",
    "collect", "commits_since", "find_boundary", "find_python", "parse_phase",
    "parse_pytest_summary", "read_plan", "run_suite", "scan_todos",
]


def parse_phase(subject: str, config: Config) -> str | None:
    """Grouping key from a commit subject, 'unknown', or None if disabled.

    Prefers the explicit `(9.6 Task 5)` suffix this project uses; falls back to
    an explicit `Phase 9.5b` mention. Never guesses from a bare version token.

    Returns None when BOTH patterns are switched off, which is the honest answer
    for a project with no phase or ticket cadence. Labelling every commit
    "unknown" there would be a Cerene habit imposed on a repo that never had
    one, and the installer leaves these unset when it detects no convention.
    """
    if config.phase_task is None and config.phase_bare is None:
        return None
    if config.phase_task is not None:
        match = config.phase_task.search(subject)
        if match:
            return match.group(1)
    if config.phase_bare is not None:
        match = config.phase_bare.search(subject)
        if match:
            return match.group(1)
    return "unknown"


def find_boundary(repo: Path, config: Config) -> str:
    """SHA of the most recent commit touching the status doc, else ''.

    Derived from the repo rather than stored, so there is no marker file or tag
    that can drift out of sync with reality.
    """
    try:
        return _GIT.run(repo, "log", "-1", "--format=%H", "--",
                         config.primary_doc).strip()
    except subprocess.CalledProcessError:
        # A repository with no commits at all: `git log` exits 128 rather than
        # returning nothing, so this is not the same as "the document has never
        # been committed". Both mean the same thing here - there is no boundary
        # - and an unborn branch is a legitimate state for a repository someone
        # has just started, not an error worth a traceback.
        return ""


def commits_since(repo: Path, boundary: str, config: Config) -> list[dict[str, str]]:
    """Commits after `boundary` (exclusive), oldest first, phase-labelled."""
    rev_range = f"{boundary}..HEAD" if boundary else "HEAD"
    try:
        out = _GIT.run(repo, "log", "--reverse", "--format=%H%x00%s", rev_range)
    except subprocess.CalledProcessError:
        return []  # unborn branch: no commits to report
    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\x00")
        commits.append({"sha": sha, "subject": subject,
                        "phase": parse_phase(subject, config)})
    return commits


# GA-1: separate anchored patterns, NOT one regex of optional groups. A single
# all-optional pattern matches the bare "in 597.70s" tail and silently reports
# passed=0 for a green suite.
_PYTEST_PASSED = re.compile(r"(\d+) passed")
_PYTEST_FAILED = re.compile(r"(\d+) failed")
_PYTEST_DURATION = re.compile(r"\bin ([\d.]+)s")


def parse_pytest_summary(output: str, status: StatusConfig) -> dict[str, object]:
    """Parse a suite summary using the configured patterns.

    Named for pytest because that is this project's runner, but the patterns are
    configurable: jest, vitest, cargo test and dotnet test all print counts that
    a regex can pick up. Pure, so the measured path stays testable without
    paying for a full run.

    Takes the settings rather than a Config: nothing is derived from the three
    `suite_*` patterns, so a derived copy of them would be a second name for
    one value. Taken as an ARGUMENT rather than read off a module, because
    `reload_config` REBINDS the caller's settings object rather than mutating
    it - a reference captured at import would keep describing whichever project
    the module was first imported in.
    """
    passed = status.suite_passed.search(output)
    failed = status.suite_failed.search(output)
    duration = status.suite_duration.search(output)
    return {
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "duration_s": float(duration.group(1)) if duration else 0.0,
    }


def changed_files(repo: Path, boundary: str) -> list[str]:
    """Repo-relative paths changed since `boundary`."""
    if not boundary:
        out = _GIT.run(repo, "ls-files")
    else:
        out = _GIT.run(repo, "diff", "--name-only", f"{boundary}..HEAD")
    return [line for line in out.splitlines() if line.strip()]


def scan_todos(repo: Path, boundary: str, config: Config) -> list[dict[str, object]]:
    """TODO/FIXME/XXX markers in files changed since `boundary`."""
    markers = config.todo_marker
    excluded_files = config.todo_excluded_files
    excluded_dirs = config.todo_excluded_dir_prefix
    found: list[dict[str, object]] = []
    for rel in changed_files(repo, boundary):
        if rel in excluded_files or rel.startswith(excluded_dirs):
            continue
        path = repo / rel
        # GA-5: code files only. Including .md makes the tool report its own
        # plan's example markers and every TODO written inside a spec as a
        # finding - noise that trains the reader to ignore the section.
        if not path.is_file() or path.suffix not in {".py", ".qml"}:
            continue
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                lines = fh.read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, text in enumerate(lines, start=1):
            if markers.search(text):
                found.append({"file": rel, "line": number, "text": text.strip()})
    return found


# Virtualenv layouts differ by platform: Windows puts the interpreter in
# Scripts/ with a .exe suffix, POSIX in bin/ without one. Hardcoding the Windows
# form meant the validator could not run on macOS or Linux at all - and the git
# hook, which skipped silently when no interpreter was found, installed cleanly
# there and then checked NOTHING. A tool that appears healthy while doing
# nothing is the precise failure this system exists to prevent, so the search
# covers every layout and the callers report what they tried.
_VENV_LAYOUTS = (
    ("Scripts", "python.exe"),   # Windows
    ("bin", "python"),           # POSIX
    ("bin", "python3"),          # POSIX, where `python` is unversioned
)


def _python_candidates(repo: Path, status: StatusConfig) -> list[Path]:
    """Every interpreter location worth trying, most specific first."""
    candidates: list[Path] = []
    if status.venv_python:
        candidates.append(repo / status.venv_python)
    for directory, name in _VENV_LAYOUTS:
        candidates.append(repo / ".venv" / directory / name)
    return candidates


def find_python(repo: Path, status: StatusConfig) -> Path | None:
    """The project's interpreter, or None. Honours the configured path first."""
    for candidate in _python_candidates(repo, status):
        if candidate.is_file():
            return candidate.resolve()
    return None


def run_suite(repo: Path, suite_json: str | None,
              status: StatusConfig) -> dict[str, object]:
    """Suite result, either supplied or produced by a real run.

    Exactly one source is used and the bundle records which, so a reader can
    tell a fresh measurement from a reused one.

    I-3: phase work happens in git worktrees by project convention, and a
    worktree has no `.venv` of its own (it is gitignored and exists only in
    the main repo) - so the measured path must fail with an actionable
    RuntimeError instead of an uncaught FileNotFoundError crashing
    /extant step 1. A worktree-run suite would also be wrong even where a
    .venv happens to exist: tests/test_startup_time.py spawns subprocesses
    that inherit pytest's cwd, and running from a worktree produces roughly
    20 spurious failures. --suite-json is the only correct path there.
    """
    if suite_json:
        with open(suite_json, encoding="utf-8") as fh:
            data = json.load(fh)
        data["source"] = "supplied"
        return data
    command = list(status.suite_command)
    # Only resolve an interpreter if the configured command actually wants one.
    # A JS, Rust or .NET project runs ["npm", "test"] or ["cargo", "test"] and
    # should not be blocked by the absence of a Python virtualenv.
    if any("{python}" in part for part in command):
        python = find_python(repo, status)
        if python is None:
            tried = "\n  ".join(str(p) for p in _python_candidates(repo, status))
            raise RuntimeError(
                "no project interpreter found, and suite_command needs one "
                f"({' '.join(command)}). Tried:\n  " + tried + "\n"
                "If this is a worktree, that is expected - .venv is gitignored "
                "and exists only in the main working tree. Pass --suite-json "
                "<path> with a result measured there, or set suite_command to "
                "something that does not use {python}."
            )
        # Absolute path required: on Windows a relative args[0] resolves against
        # the CALLING process's cwd, not the `cwd=` passed to subprocess.run, so
        # a relative interpreter path is wrong even when a .venv is present.
        command = [part.replace("{python}", str(python)) for part in command]

    try:
        proc = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"suite_command not runnable: {' '.join(command)} ({exc}). "
            "Check the command exists on PATH, or pass --suite-json."
        ) from exc
    result = parse_pytest_summary(proc.stdout, status)
    result["source"] = "measured"
    result["exit_code"] = proc.returncode
    return result


_CHECKED = "- [x]"
_UNCHECKED = "- [ ]"


def read_plan(repo: Path, status: StatusConfig) -> dict[str, object]:
    """Completed vs remaining steps in the newest phase plan.

    Plans are date-prefixed (YYYY-MM-DD), so lexical sort is chronological.

    I-2: this project does not maintain plan checkboxes in practice (25 of 27
    real plans under docs/superpowers/plans/ have zero checked boxes, even
    for shipped work), so `remaining` being non-empty must not be read as
    "outstanding work" - it may just mean the file was never checked off.
    `checkbox_tracking` makes the bundle self-describing instead of asking a
    reader (or a fresh session) to infer that distinction: it is True only
    when at least one `- [x]` was actually found in the plan.
    """
    empty = {"path": "", "completed": [], "remaining": [], "checkbox_tracking": False}
    # An empty plans_dir switches the feature off, rather than reporting an
    # empty plan for a project that has no such convention at all.
    if not status.plans_dir:
        return {"path": "", "completed": [], "remaining": [], "enabled": False}
    plans_dir = repo / status.plans_dir
    if not plans_dir.is_dir():
        return dict(empty)
    plans = sorted(plans_dir.glob("*.md"))
    if not plans:
        return dict(empty)
    latest = plans[-1]
    completed: list[str] = []
    remaining: list[str] = []
    with open(latest, encoding="utf-8", newline="") as fh:
        for line in fh.read().splitlines():
            stripped = line.strip()
            if stripped.startswith(_CHECKED):
                completed.append(stripped[len(_CHECKED):].strip())
            elif stripped.startswith(_UNCHECKED):
                remaining.append(stripped[len(_UNCHECKED):].strip())
    return {
        "path": str(latest.relative_to(repo)).replace("\\", "/"),
        "completed": completed,
        "remaining": remaining,
        "checkbox_tracking": bool(completed),
    }


def collect(repo: Path, suite_json: str | None, config: Config,
            status: StatusConfig) -> dict[str, object]:
    """Assemble the full fact bundle. No prose, ever.

    Takes both halves of the configuration because it calls functions on both
    sides of the split: `config` for what a project's settings imply, `status`
    for the three settings nothing implies anything about.
    """
    boundary = find_boundary(repo, config)
    try:
        branch = _GIT.run(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except subprocess.CalledProcessError:
        # An unborn branch has no resolvable HEAD. `git symbolic-ref` still
        # knows the name the first commit WILL be on, which is more useful than
        # "unknown" and is what `git status` reports in the same situation.
        try:
            branch = _GIT.run(repo, "symbolic-ref", "--short",
                              "HEAD").strip() or "unknown"
        except subprocess.CalledProcessError:
            branch = "unknown"
    merged = set(_GIT.soft(repo, "branch", "--merged",
                           config.trunk).replace("*", "").split())
    all_branches = set(_GIT.soft(repo, "branch", "--format=%(refname:short)").split())
    commits = commits_since(repo, boundary, config)
    return {
        "boundary_sha": boundary,
        "commits": commits,
        "nothing_to_hand_off": not commits,
        "suite": run_suite(repo, suite_json, status),
        "todos": scan_todos(repo, boundary, config),
        "plan": read_plan(repo, status),
        "git": {
            "branch": branch,
            "unmerged_branches": sorted(all_branches - merged),
        },
    }
