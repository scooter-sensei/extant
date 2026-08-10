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


# Not `from extant.git import _git, _git_soft`: test_module_quality.py's
# test_no_module_reaches_past_another_modules_surface bans any sibling module
# importing another sibling's underscore name, and both names ARE underscore
# names (git.py's own __all__ comment explains why). Importing the module
# instead and qualifying every call site as git._git(...) is a same-behaviour,
# gate-clean substitute; the alternative was weakening the gate, which was
# ruled out.
from extant import git

__all__ = [
    "_CHECKED", "_PYTEST_DURATION", "_PYTEST_FAILED", "_PYTEST_PASSED",
    "_UNCHECKED", "_VENV_LAYOUTS", "_python_candidates", "changed_files",
    "collect", "commits_since", "find_boundary", "find_python", "parse_phase",
    "parse_pytest_summary", "read_plan", "run_suite", "scan_todos",
]


def parse_phase(subject: str) -> str | None:
    """Grouping key from a commit subject, 'unknown', or None if disabled.

    Prefers the explicit `(9.6 Task 5)` suffix this project uses; falls back to
    an explicit `Phase 9.5b` mention. Never guesses from a bare version token.

    Returns None when BOTH patterns are switched off, which is the honest answer
    for a project with no phase or ticket cadence. Labelling every commit
    "unknown" there would be a Cerene habit imposed on a repo that never had
    one, and the installer leaves these unset when it detects no convention.
    """
    # Task 5 scaffolding: _PHASE_TASK and _PHASE_BARE are config-derived
    # globals that stay on extant_collect until Task 5 moves config plumbing
    # into the package. Imported here, inside the function, because at module
    # level this is a circular import: extant_collect imports extant.collect
    # at load time, before _apply_config() has set these. The whole module is
    # imported (not the names) because "extant_collect" string-prefix-matches
    # "extant" in both test_module_quality.py gates (import-cycle detection
    # and the private-import ban), which misreads `from extant_collect import
    # _PHASE_TASK` as a same-package import of an underscore name.
    import extant_collect
    if extant_collect._PHASE_TASK is None and extant_collect._PHASE_BARE is None:
        return None
    if extant_collect._PHASE_TASK is not None:
        match = extant_collect._PHASE_TASK.search(subject)
        if match:
            return match.group(1)
    if extant_collect._PHASE_BARE is not None:
        match = extant_collect._PHASE_BARE.search(subject)
        if match:
            return match.group(1)
    return "unknown"


def find_boundary(repo: Path) -> str:
    """SHA of the most recent commit touching the status doc, else ''.

    Derived from the repo rather than stored, so there is no marker file or tag
    that can drift out of sync with reality.
    """
    # Task 5 scaffolding (see parse_phase for why this is a whole-module
    # import done inside the function).
    import extant_collect
    try:
        return git._git(repo, "log", "-1", "--format=%H", "--",
                         extant_collect.PRIMARY_DOC).strip()
    except subprocess.CalledProcessError:
        # A repository with no commits at all: `git log` exits 128 rather than
        # returning nothing, so this is not the same as "the document has never
        # been committed". Both mean the same thing here - there is no boundary
        # - and an unborn branch is a legitimate state for a repository someone
        # has just started, not an error worth a traceback.
        return ""


def commits_since(repo: Path, boundary: str) -> list[dict[str, str]]:
    """Commits after `boundary` (exclusive), oldest first, phase-labelled."""
    rev_range = f"{boundary}..HEAD" if boundary else "HEAD"
    try:
        out = git._git(repo, "log", "--reverse", "--format=%H%x00%s", rev_range)
    except subprocess.CalledProcessError:
        return []  # unborn branch: no commits to report
    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\x00")
        commits.append({"sha": sha, "subject": subject, "phase": parse_phase(subject)})
    return commits


# GA-1: separate anchored patterns, NOT one regex of optional groups. A single
# all-optional pattern matches the bare "in 597.70s" tail and silently reports
# passed=0 for a green suite.
_PYTEST_PASSED = re.compile(r"(\d+) passed")
_PYTEST_FAILED = re.compile(r"(\d+) failed")
_PYTEST_DURATION = re.compile(r"\bin ([\d.]+)s")


def parse_pytest_summary(output: str) -> dict[str, object]:
    """Parse a suite summary using the configured patterns.

    Named for pytest because that is this project's runner, but the patterns are
    configurable: jest, vitest, cargo test and dotnet test all print counts that
    a regex can pick up. Pure, so the measured path stays testable without
    paying for a full run.
    """
    # Task 5 scaffolding (see parse_phase for why this is a whole-module
    # import done inside the function).
    import extant_collect
    passed = extant_collect.CONFIG.suite_passed.search(output)
    failed = extant_collect.CONFIG.suite_failed.search(output)
    duration = extant_collect.CONFIG.suite_duration.search(output)
    return {
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "duration_s": float(duration.group(1)) if duration else 0.0,
    }


def changed_files(repo: Path, boundary: str) -> list[str]:
    """Repo-relative paths changed since `boundary`."""
    if not boundary:
        out = git._git(repo, "ls-files")
    else:
        out = git._git(repo, "diff", "--name-only", f"{boundary}..HEAD")
    return [line for line in out.splitlines() if line.strip()]


def scan_todos(repo: Path, boundary: str) -> list[dict[str, object]]:
    """TODO/FIXME/XXX markers in files changed since `boundary`."""
    # Task 5 scaffolding: _TODO_MARKER, _TODO_SCAN_EXCLUDED_FILES and
    # _TODO_SCAN_EXCLUDED_DIR_PREFIX are config-derived globals that stay on
    # extant_collect until Task 5 (see parse_phase for why this is a
    # whole-module import done inside the function).
    import extant_collect
    found: list[dict[str, object]] = []
    for rel in changed_files(repo, boundary):
        if (rel in extant_collect._TODO_SCAN_EXCLUDED_FILES
                or rel.startswith(extant_collect._TODO_SCAN_EXCLUDED_DIR_PREFIX)):
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
            if extant_collect._TODO_MARKER.search(text):
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


def _python_candidates(repo: Path) -> list[Path]:
    """Every interpreter location worth trying, most specific first."""
    # Task 5 scaffolding (see parse_phase for why this is a whole-module
    # import done inside the function).
    import extant_collect
    candidates: list[Path] = []
    if extant_collect.CONFIG.venv_python:
        candidates.append(repo / extant_collect.CONFIG.venv_python)
    for directory, name in _VENV_LAYOUTS:
        candidates.append(repo / ".venv" / directory / name)
    return candidates


def find_python(repo: Path) -> Path | None:
    """The project's interpreter, or None. Honours the configured path first."""
    for candidate in _python_candidates(repo):
        if candidate.is_file():
            return candidate.resolve()
    return None


def run_suite(repo: Path, suite_json: str | None) -> dict[str, object]:
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
    # Task 5 scaffolding (see parse_phase for why this is a whole-module
    # import done inside the function).
    import extant_collect
    if suite_json:
        with open(suite_json, encoding="utf-8") as fh:
            data = json.load(fh)
        data["source"] = "supplied"
        return data
    command = list(extant_collect.CONFIG.suite_command)
    # Only resolve an interpreter if the configured command actually wants one.
    # A JS, Rust or .NET project runs ["npm", "test"] or ["cargo", "test"] and
    # should not be blocked by the absence of a Python virtualenv.
    if any("{python}" in part for part in command):
        python = find_python(repo)
        if python is None:
            tried = "\n  ".join(str(p) for p in _python_candidates(repo))
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
    result = parse_pytest_summary(proc.stdout)
    result["source"] = "measured"
    result["exit_code"] = proc.returncode
    return result


_CHECKED = "- [x]"
_UNCHECKED = "- [ ]"


def read_plan(repo: Path) -> dict[str, object]:
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
    # Task 5 scaffolding (see parse_phase for why this is a whole-module
    # import done inside the function).
    import extant_collect
    empty = {"path": "", "completed": [], "remaining": [], "checkbox_tracking": False}
    # An empty plans_dir switches the feature off, rather than reporting an
    # empty plan for a project that has no such convention at all.
    if not extant_collect.CONFIG.plans_dir:
        return {"path": "", "completed": [], "remaining": [], "enabled": False}
    plans_dir = repo / extant_collect.CONFIG.plans_dir
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


def collect(repo: Path, suite_json: str | None = None) -> dict[str, object]:
    """Assemble the full fact bundle. No prose, ever."""
    # Task 5 scaffolding (see parse_phase for why this is a whole-module
    # import done inside the function).
    import extant_collect
    boundary = find_boundary(repo)
    try:
        branch = git._git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except subprocess.CalledProcessError:
        # An unborn branch has no resolvable HEAD. `git symbolic-ref` still
        # knows the name the first commit WILL be on, which is more useful than
        # "unknown" and is what `git status` reports in the same situation.
        try:
            branch = git._git(repo, "symbolic-ref", "--short",
                              "HEAD").strip() or "unknown"
        except subprocess.CalledProcessError:
            branch = "unknown"
    merged = set(git._git_soft(repo, "branch", "--merged",
                                extant_collect.TRUNK).replace("*", "").split())
    all_branches = set(git._git_soft(repo, "branch", "--format=%(refname:short)").split())
    commits = commits_since(repo, boundary)
    return {
        "boundary_sha": boundary,
        "commits": commits,
        "nothing_to_hand_off": not commits,
        "suite": run_suite(repo, suite_json),
        "todos": scan_todos(repo, boundary),
        "plan": read_plan(repo),
        "git": {
            "branch": branch,
            "unmerged_branches": sorted(all_branches - merged),
        },
    }
