"""Collector and validator for the /extant session-status workflow.

    .venv/Scripts/python tools/extant_collect.py --collect --out bundle.json
    .venv/Scripts/python tools/extant_collect.py --archive
    .venv/Scripts/python tools/extant_collect.py --validate NEXT_SESSION.md
    .venv/Scripts/python tools/extant_collect.py --verify

Deterministic half of the status workflow: everything here is mechanical and
tested. Prose is written by the subagent, never by this script. See
docs/superpowers/specs/2026-07-20-status-system-design.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# This file is used two ways: imported as `tools.extant_collect` (tests, where
# the repo root is on sys.path) and run directly as a script (the hooks and the
# /extant command, where only tools/ is). The first import fails in the second
# case, so fall back to the sibling module.
try:
    from tools.extant_config import load_config
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI tests
    from extant_config import load_config

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every project-specific value is resolved once, here, from .extant.toml beside
# the repo root - falling back to defaults that reproduce this project's
# behaviour exactly, so a repo without a config file sees no change. The names
# below stay module-level constants because the whole module and its tests refer
# to them directly; only their SOURCE moved.
#
# Porting warning, stated at length in tools/extant_config.py: three of these
# patterns were derived by MEASURING this repo's documents. Copy them to another
# project without re-measuring and the validator matches nothing while appearing
# healthy. Run `--init` against the target repo instead of guessing.
try:
    CONFIG = load_config(REPO_ROOT)
except ValueError as _config_error:
    # Configuration is read at import, so a malformed .extant.toml surfaces as
    # a traceback before main() ever runs. The explanation is already in the
    # message; burying it under a stack that names tomllib internals just makes
    # the reader work for it. Print it plainly when this is being RUN, and
    # re-raise untouched when it is being imported, so tests still see the
    # exception rather than a dead interpreter.
    if __name__ == "__main__":
        print(f"extant: cannot read configuration\n\n{_config_error}", file=sys.stderr)
        raise SystemExit(2) from None
    raise


def _git_soft(repo: Path, *args: str) -> str:
    """Run git, returning "" instead of raising when the command fails.

    For FACT GATHERING, where the absence of an answer is itself a legitimate
    answer. A repository with no commits has no HEAD, no trunk ref and no
    branches, so `git log`, `git rev-parse HEAD` and `git branch --merged main`
    all exit 128 - not because anything is wrong, but because someone has just
    run `git init`.

    Deliberately NOT used by the validation rules. There, a git command that
    fails means a claim could not be checked, and silently treating that as
    "no finding" is the exact shape of failure this project exists to prevent.
    """
    try:
        return _git(repo, *args)
    except (subprocess.CalledProcessError, OSError):
        return ""


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, returning stdout. Raises on non-zero."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


def parse_phase(subject: str) -> str | None:
    """Grouping key from a commit subject, 'unknown', or None if disabled.

    Prefers the explicit `(9.6 Task 5)` suffix this project uses; falls back to
    an explicit `Phase 9.5b` mention. Never guesses from a bare version token.

    Returns None when BOTH patterns are switched off, which is the honest answer
    for a project with no phase or ticket cadence. Labelling every commit
    "unknown" there would be a Cerene habit imposed on a repo that never had
    one, and the installer leaves these unset when it detects no convention.
    """
    if _PHASE_TASK is None and _PHASE_BARE is None:
        return None
    if _PHASE_TASK is not None:
        match = _PHASE_TASK.search(subject)
        if match:
            return match.group(1)
    if _PHASE_BARE is not None:
        match = _PHASE_BARE.search(subject)
        if match:
            return match.group(1)
    return "unknown"


def find_boundary(repo: Path) -> str:
    """SHA of the most recent commit touching the status doc, else ''.

    Derived from the repo rather than stored, so there is no marker file or tag
    that can drift out of sync with reality.
    """
    try:
        return _git(repo, "log", "-1", "--format=%H", "--", PRIMARY_DOC).strip()
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
        out = _git(repo, "log", "--reverse", "--format=%H%x00%s", rev_range)
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
    passed = CONFIG.suite_passed.search(output)
    failed = CONFIG.suite_failed.search(output)
    duration = CONFIG.suite_duration.search(output)
    return {
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "duration_s": float(duration.group(1)) if duration else 0.0,
    }


def changed_files(repo: Path, boundary: str) -> list[str]:
    """Repo-relative paths changed since `boundary`."""
    if not boundary:
        out = _git(repo, "ls-files")
    else:
        out = _git(repo, "diff", "--name-only", f"{boundary}..HEAD")
    return [line for line in out.splitlines() if line.strip()]


def scan_todos(repo: Path, boundary: str) -> list[dict[str, object]]:
    """TODO/FIXME/XXX markers in files changed since `boundary`."""
    found: list[dict[str, object]] = []
    for rel in changed_files(repo, boundary):
        if rel in _TODO_SCAN_EXCLUDED_FILES or rel.startswith(_TODO_SCAN_EXCLUDED_DIR_PREFIX):
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
            if _TODO_MARKER.search(text):
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
    candidates: list[Path] = []
    if CONFIG.venv_python:
        candidates.append(repo / CONFIG.venv_python)
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
    if suite_json:
        with open(suite_json, encoding="utf-8") as fh:
            data = json.load(fh)
        data["source"] = "supplied"
        return data
    command = list(CONFIG.suite_command)
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
    empty = {"path": "", "completed": [], "remaining": [], "checkbox_tracking": False}
    # An empty plans_dir switches the feature off, rather than reporting an
    # empty plan for a project that has no such convention at all.
    if not CONFIG.plans_dir:
        return {"path": "", "completed": [], "remaining": [], "enabled": False}
    plans_dir = repo / CONFIG.plans_dir
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
    boundary = find_boundary(repo)
    try:
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except subprocess.CalledProcessError:
        # An unborn branch has no resolvable HEAD. `git symbolic-ref` still
        # knows the name the first commit WILL be on, which is more useful than
        # "unknown" and is what `git status` reports in the same situation.
        try:
            branch = _git(repo, "symbolic-ref", "--short",
                          "HEAD").strip() or "unknown"
        except subprocess.CalledProcessError:
            branch = "unknown"
    merged = set(_git_soft(repo, "branch", "--merged", TRUNK).replace("*", "").split())
    all_branches = set(_git_soft(repo, "branch", "--format=%(refname:short)").split())
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


# Derived from CONFIG rather than from _PHASE_PREFIX, which is defined below
# this line - referring to it here is a NameError at import.
#
# Built through a helper so that `reload_config` can rebuild it. Everything
# else derived from CONFIG goes through the _CONFIG_DERIVED table and is
# refreshed by name; this one is COMPUTED rather than copied, so it was missed,
# and kept its import-time value forever. That matters on the one path
# `reload_config` exists for: installed as a package by the pre-commit
# framework, where configuration is re-read for the target repository. A
# project whose `entry_prefix` is not the default got the right prefix
# everywhere and the wrong section splitter.
def _section_header(prefix: str) -> re.Pattern[str]:
    return re.compile("^" + re.escape(prefix.split()[0]) + " ", re.MULTILINE)


# EVERY module global derived from configuration, and the only place any of
# them is set. Import and `reload_config` both call `_apply_config`, so the two
# cannot describe different sets - which is the whole point.
#
# They used to be nineteen assignments scattered over 1,500 lines, with a
# SECOND list inside reload_config naming which ones to refresh. The same
# information written twice is an invitation to divergence, and it was
# accepted: `_SECTION_HEADER` is COMPUTED from `entry_prefix` rather than
# copied, the second list only knew about copies, and it went stale on every
# reload. Installed as a package by the pre-commit framework - the one path
# reload_config exists for - a project with a non-default heading level got
# the right prefix everywhere and a splitter looking for the wrong one.
#
# Builders rather than field names, so a computed value is expressed the same
# way as a copied one and neither can be the special case that gets forgotten.
_CONFIG_DERIVED: dict[str, Callable[[StatusConfig], object]] = {
    "PRIMARY_DOC": lambda c: c.primary_doc,
    "ARCHIVE_DOC": lambda c: c.archive_doc,
    "RETAIN_ENTRIES": lambda c: c.retain_entries,
    "TRUNK": lambda c: c.trunk,
    "_ARCHIVE_HEADER": lambda c: c.archive_header,
    "_BASE_HEADER": lambda c: c.base_header,
    "_PHASE_PREFIX": lambda c: c.entry_prefix,
    "_POINTER_PREFIX": lambda c: c.pointer_prefix,
    "_PHASE_TASK": lambda c: c.phase_task,
    "_PHASE_BARE": lambda c: c.phase_bare,
    "_TODO_MARKER": lambda c: c.todo_markers,
    "_LIVE_PHRASES": lambda c: c.live_phrases,
    "_BRANCH_TOKEN": lambda c: c.branch_token,
    # Keyed on OPERATIVE markers, never on path shape. Measured against the
    # real corpus: of 88 path-shaped tokens, 23 do not exist and every one of
    # those 23 is legitimate - a completed phase describing its own layout,
    # deferred work never built, a file explicitly described as deleted. A
    # shape-keyed rule would emit 23 findings, all false. What is falsifiable
    # is a path offered as a POINTER: "the plan is at X", "read X", "see X".
    "_PATH_POINTER": lambda c: c.path_pointer,
    # Requires the SHA to FOLLOW the phrase, so a SHA belonging to a
    # neighbouring clause is not misread. It no longer requires the target to
    # be `main`: the claim names its own ref and is checked against that.
    "_MERGE_CLAIM": lambda c: c.merge_claim,
    "_RELEASE_TAG": lambda c: c.release_tag,
    # COMPUTED, not copied. These three are why this table holds builders.
    "_SECTION_HEADER": lambda c: _section_header(c.entry_prefix),
    "_TODO_SCAN_EXCLUDED_FILES": lambda c: set(c.todo_exclude_files),
    "_TODO_SCAN_EXCLUDED_DIR_PREFIX": lambda c: tuple(c.todo_exclude_dirs),
}


def _apply_config() -> None:
    """Set every configuration-derived global from the current CONFIG."""
    for name, build in _CONFIG_DERIVED.items():
        globals()[name] = build(CONFIG)


_apply_config()


def split_entries(text: str) -> tuple[str, list[tuple[str, str]], str]:
    """Split a status doc into (preamble, [(kind, text)], reference base).

    GA-4: splits on EVERY top-level section, not just `## Phase `. Sections
    classified "other" are reference material interleaved among the phase
    entries, and archiving them as history would lose them.
    """
    base_match = _BASE_HEADER.search(text)
    base_start = base_match.start() if base_match else len(text)
    body, base = text[:base_start], text[base_start:]

    starts = [m.start() for m in _SECTION_HEADER.finditer(body)]
    if not starts:
        return body, [], base
    preamble = body[: starts[0]]
    bounds = starts + [len(body)]
    segments: list[tuple[str, str]] = []
    for index in range(len(starts)):
        chunk = body[bounds[index]: bounds[index + 1]]
        kind = "phase" if chunk.startswith(_PHASE_PREFIX) else "other"
        segments.append((kind, chunk))
    return preamble, segments, base


def archive(repo: Path, retain: int = RETAIN_ENTRIES) -> dict[str, int]:
    """Move all but the newest `retain` phase entries into the archive doc.

    Fails closed if any original line would be lost. This is the only
    irreversible file operation in the system, so conservation is asserted
    rather than trusted.
    """
    doc = repo / PRIMARY_DOC
    with open(doc, encoding="utf-8", newline="") as fh:
        original = fh.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    normalised = original.replace("\r\n", "\n")

    preamble, segments, base = split_entries(normalised)

    # Idempotency: the pointer this function writes below is tool-generated
    # bookkeeping, not content - a PRIOR run's pointer must never survive
    # into this run's output, kept inline or archived. split_entries files
    # it under "other" (GA-6's own top-level header), and GA-4 keeps every
    # "other" segment inline forever, so without this a stale pointer would
    # ride along unchanged while a fresh one gets appended alongside it: N
    # runs, N stacked pointer blocks, none ever removed.
    live_segments = [
        (kind, chunk) for kind, chunk in segments
        if not chunk.startswith(_POINTER_PREFIX)
    ]
    stale_pointer_text = "".join(
        chunk for _, chunk in segments if chunk.startswith(_POINTER_PREFIX)
    )

    phase_count = sum(1 for kind, _ in live_segments if kind == "phase")
    if phase_count <= retain:
        return {"retained": phase_count, "archived": 0}

    kept: list[str] = []
    moved: list[str] = []
    seen = 0
    for kind, chunk in live_segments:
        if kind != "phase":
            kept.append(chunk)  # GA-4: reference sections are never archived
            continue
        (kept if seen < retain else moved).append(chunk)
        seen += 1

    # GA-6: the pointer gets its own top-level `## ` header so a later
    # split_entries() classifies it as a standalone "other" segment instead
    # of gluing it onto the tail of whichever phase chunk precedes it - an
    # un-headered pointer would otherwise end up embedded inside that
    # entry's body once the entry itself is archived.
    pointer = (
        "## Archive pointer\n\n"
        f"> Entries older than the newest {retain} live in `{ARCHIVE_DOC}`.\n\n"
    )
    remaining = preamble + "".join(kept) + pointer + base

    archive_path = repo / ARCHIVE_DOC
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if archive_path.exists():
        with open(archive_path, encoding="utf-8", newline="") as fh:
            existing = fh.read().replace("\r\n", "\n")
    # GA-6: new phase entries are always PREPENDED to NEXT_SESSION.md, so
    # whatever falls out of the retain window on THIS run is chronologically
    # newer than anything archived on a prior run. `moved` (already
    # newest-first, per split_entries order) must land directly under the
    # header, above everything previously archived - never appended after it.
    existing_body = existing.removeprefix(_ARCHIVE_HEADER)
    archived_text = _ARCHIVE_HEADER + "".join(moved) + existing_body

    # GA-3: multiset comparison. A set-membership check cannot detect the loss
    # of DUPLICATE lines - blanks, "---" rules - because one surviving copy
    # satisfies it. Counter subtraction keeps only positive residuals.
    #
    # The baseline is `normalised` with the stale pointer's own lines
    # subtracted, NOT rebuilt from `live_segments` (preamble + join + base).
    # Those two are equal whenever split_entries partitions losslessly - but
    # anchoring to `normalised` keeps the guard independent of split_entries
    # itself, so it still catches a bug THERE (see
    # test_archive_detects_loss_of_duplicate_lines, which monkeypatches
    # split_entries to drop a line and asserts this guard still fires). A
    # live_segments-rebuilt baseline would launder that exact class of bug:
    # both the baseline and remaining+archived would be built from the same
    # corrupted segments and agree with each other, silently.
    #
    # Subtracting the stale pointer's lines here - rather than comparing
    # against the raw on-disk text as-is - is what makes idempotent archive
    # runs possible: on run 2+, `normalised` (read fresh from disk) already
    # contains run 1's pointer block, which this run deliberately discards
    # (never placed in `kept` or `moved` above). Without this subtraction
    # the guard would see that discarded block's lines as "lost" and raise
    # a false positive on every run after the first.
    cleaned_baseline = (
        Counter(normalised.splitlines()) - Counter(stale_pointer_text.splitlines())
    )
    lost = (
        cleaned_baseline
        - Counter(remaining.splitlines())
        - Counter(archived_text.splitlines())
    )
    if lost:
        raise RuntimeError(
            f"archive would lose {sum(lost.values())} line(s); "
            f"examples: {list(lost)[:3]}"
        )

    with open(doc, "w", encoding="utf-8", newline="") as fh:
        fh.write(remaining.replace("\n", newline))
    with open(archive_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(archived_text.replace("\n", newline))
    return {"retained": retain, "archived": len(moved)}


_BACKTICKED = re.compile(r"`([^`]+)`")
_SHA_SHAPE = re.compile(r"^[0-9a-f]{7,40}$")
# I-1: SHA-shaped tokens written WITHOUT backticks. Anchored both sides with
# \b so a hex-looking run embedded inside a longer word (an identifier, a
# version tag) never matches - \w includes both hex letters and non-hex
# letters/digits/underscore, so there is no \b between e.g. "deadbeef" and a
# following "zz", and the whole run correctly fails to match at all rather
# than matching a truncated prefix of it.
_BARE_SHA_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    detail: str

    def render(self) -> str:
        return f"line {self.line}: [{self.kind}] {self.detail}"


@dataclass(frozen=True)
class Located:
    """A finding plus the document it came from.

    The file used to live only in the print statement that rendered a finding,
    which was enough for a human reading a terminal and not enough for anything
    else. A machine format has to say WHICH file every result belongs to, so
    the pairing is now carried in the data rather than reconstructed at the
    moment of printing.
    """

    path: str          # repo-relative, forward slashes, for machine consumers
    finding: Finding
    primary: bool      # the document asked for, as opposed to archive/extra


def _looks_like_sha(token: str) -> bool:
    return bool(_SHA_SHAPE.match(token)) and any(ch.isdigit() for ch in token)


def _looks_like_bare_sha(token: str) -> bool:
    """Shape test for a token found OUTSIDE backticks (I-1).

    Requires a letter as well as a digit - unlike `_looks_like_sha` (applied
    only to backticked tokens), which requires just a digit. Backticks are
    themselves a signal the author meant a SHA; bare text has no such signal,
    so the extra letter requirement is needed to exclude a plain number (a
    year, a test count) that `_looks_like_sha` alone would wrongly accept.
    The digit requirement excludes a hex-looking English word the same way it
    already does for `_looks_like_sha`. Measured against ~2600 lines of the
    real status documents with zero false positives.
    """
    return any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)


def _spans_overlap(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(s < end and start < e for s, e in others)


def find_sha_candidates(text: str) -> list[tuple[int, str]]:
    """(line number, token) for every backticked SHA-shaped token."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for token in _BACKTICKED.findall(line):
            if _looks_like_sha(token):
                out.append((number, token))
    return out


def find_bare_sha_candidates(text: str) -> list[tuple[int, str]]:
    """(line number, token) for every SHA-shaped token OUTSIDE backticks.

    I-1: a SHA written without backticks previously escaped both
    `validate_references` and `translate_shas` entirely. Scanned per line,
    consistent with `find_sha_candidates` and the rest of the module - see
    the EX-8 note in docs/superpowers/plans/2026-07-20-status-system.md for
    why a whole-text scan drifts out of phase with backtick pairing.

    "Outside backticks" is computed per line: the spans `_BACKTICKED` covers
    on that line are found first, and any bare candidate whose span overlaps
    one of them is skipped, so a token already inside backticks is never
    double-counted here.
    """
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        backticked_spans = [m.span() for m in _BACKTICKED.finditer(line)]
        for match in _BARE_SHA_TOKEN.finditer(line):
            if _spans_overlap(match.span(), backticked_spans):
                continue
            token = match.group(0)
            if _looks_like_bare_sha(token):
                out.append((number, token))
    return out


def _sha_exists(repo: Path, sha: str) -> bool:
    try:
        _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def _resolve_shas(repo: Path, tokens: list[str]) -> set[str]:
    """Which of `tokens` resolve to commits, in ONE git call instead of N.

    `git cat-file --batch-check` reads object names on stdin and emits exactly
    one line per input, in order: `<sha> <type> <size>` when it resolves, or
    `<input> missing` when it does not. Only the ORDER ties an output line back
    to its input, because a resolved line reports the full SHA rather than the
    abbreviation that was fed in - so this zips the two and bails out to the
    per-token path if the counts ever disagree.

    Worth the care: on Windows each subprocess spawn costs ~40 ms, and a real
    status document plus its archive carries ~60 references. Batching takes
    `--verify` from about 2.6 s to under half a second, which is what makes it
    cheap enough to run from a git hook on every commit.
    """
    unique = sorted(set(tokens))
    if not unique:
        return set()
    payload = "".join(f"{token}^{{commit}}\n" for token in unique)
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=repo, input=payload, capture_output=True, text=True, encoding="utf-8",
    )
    lines = proc.stdout.splitlines()
    if len(lines) != len(unique):
        return {token for token in unique if _sha_exists(repo, token)}
    return {
        token for token, line in zip(unique, lines)
        # Explicit success only. `<input> missing` is one failure shape;
        # `<input> ambiguous` is another, and "does not end in missing" let
        # it through as though the object had resolved.
        if len(line.split()) == 3 and not line.rstrip().endswith("missing")
    }


def validate_references(repo: Path, text: str) -> list[Finding]:
    """Every referenced SHA must still resolve; a dead reference is useless."""
    # Claims inside code are examples, not promises. See _prose.
    text = _prose(text)
    findings: list[Finding] = []
    backticked = find_sha_candidates(text)
    bare = find_bare_sha_candidates(text)
    alive = _resolve_shas(repo, [t for _, t in backticked] + [t for _, t in bare])
    for number, token in backticked:
        if token not in alive:
            findings.append(
                Finding(number, "dead-sha", f"`{token}` does not resolve in this repo")
            )
    # I-1(b): a bare token that RESOLVES is merely unstyled, not broken -
    # flagging it would be noise, so only a bare token that fails to resolve
    # is worth a finding.
    for number, token in bare:
        if token not in alive:
            findings.append(Finding(
                number, "bare-dead-sha",
                f"`{token}` is un-backticked and does not resolve; "
                "backtick real SHAs so they are checked",
            ))
    return findings


def load_sha_map(path: str) -> dict[str, str]:
    """Parse a git-filter-repo commit-map (old SHA, whitespace, new SHA)."""
    mapping: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    return mapping


def _translated_value(token: str, mapping: dict[str, str]) -> str | None:
    """New value for `token` via prefix match, or None if it must stay put.

    GA-6: an AMBIGUOUS prefix - two old SHAs sharing it - is left untranslated
    rather than resolved by dict order. Picking a winner silently would rewrite
    a reference to point at the wrong commit, and a wrong SHA is worse than a
    dead one: the dead one is visibly broken, the wrong one reads as correct.
    Shared by both the backticked and bare translation paths below, so both
    apply the same ambiguity rule.
    """
    hits = [new for old, new in mapping.items() if old.startswith(token)]
    return hits[0][: len(token)] if len(hits) == 1 else None


def translate_shas(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Rewrite dead SHAs - backticked AND bare (I-1c) - to their post-rewrite
    values, matched by prefix.

    Ambiguous prefixes are left alone; see `_translated_value`. Ambiguous or
    otherwise unresolved tokens stay dead and get reported by
    validate_references.

    Tokenizes per line, exactly like find_sha_candidates and
    find_bare_sha_candidates. `_BACKTICKED`'s `[^`]+` matches newlines, so
    subbing over the whole text at once pairs backticks ACROSS line
    boundaries - an odd number of backticks on an earlier line shifts every
    pairing after it out of phase with the per-line scan find_sha_candidates
    (and validate_references) rely on, making some backticked SHAs invisible
    here even though they are reported as findings elsewhere. Scanning line
    by line keeps the two in agreement by construction.
    `splitlines(keepends=True)` + `"".join(...)` preserves line endings
    byte-for-byte, so a no-op translation is a no-op on disk.

    I-1(c): a bare token is repaired in place, at its original length, and
    stays bare - this rewrites the SHA, it does not add styling the author
    never wrote. This half is not optional: adding `bare-dead-sha` findings
    (I-1b) without also extending translation to reach them would recreate
    EX-8 - a class of reference the validator reports that --sha-map is
    structurally unable to fix. The backtick substitution runs first on each
    line; it preserves length and leaves the backtick characters themselves
    untouched, so the backtick spans re-scanned afterwards for the bare pass
    land at the same offsets either way.
    """
    count = 0

    def replace_backticked(match: re.Match[str]) -> str:
        nonlocal count
        token = match.group(1)
        if not _looks_like_sha(token):
            return match.group(0)
        new = _translated_value(token, mapping)
        if new is None:
            return match.group(0)
        count += 1
        return f"`{new}`"

    def replace_bare(line: str) -> str:
        nonlocal count
        backticked_spans = [m.span() for m in _BACKTICKED.finditer(line)]
        pieces: list[str] = []
        cursor = 0
        for match in _BARE_SHA_TOKEN.finditer(line):
            if _spans_overlap(match.span(), backticked_spans):
                continue
            token = match.group(0)
            if not _looks_like_bare_sha(token):
                continue
            new = _translated_value(token, mapping)
            if new is None:
                continue
            pieces.append(line[cursor: match.start()])
            pieces.append(new)
            cursor = match.end()
            count += 1
        pieces.append(line[cursor:])
        return "".join(pieces)

    lines = []
    for line in text.splitlines(keepends=True):
        line = _BACKTICKED.sub(replace_backticked, line)
        line = replace_bare(line)
        lines.append(line)
    return "".join(lines), count


def _branch_exists(repo: Path, branch: str) -> bool:
    try:
        _git(repo, "rev-parse", "--verify", branch)
        return True
    except subprocess.CalledProcessError:
        return False


# Ancestry indexes and resolved refs, for the duration of ONE validate() call.
# Saved and restored rather than cleared, exactly as _DIRCACHE is: git state can
# change between validations, so an index that outlived the call would answer
# from a repository that no longer exists in that shape.
#
# Keyed by (repo, ref), never by ref alone. Keying by name looked sufficient and
# was not: rules are also called directly, without going through validate(), so
# nothing resets the cache between two repositories that both have a branch
# called `main` - and the second one is then answered from the first one's
# history. The suite caught it as a TRUE merge claim reported false.
_ANCESTORS: dict[tuple[str, str], dict[str, list[str]] | None] = {}
_REFS: dict[tuple[str, str], str | None] = {}
# The LFS survey walks the whole tree, and BOTH the rule and the
# denominator need it. Computing it twice doubled the cost of the most
# expensive rule here for no benefit.
_LFS: dict[str, list[tuple[str, str]]] = {}


def _ancestor_index(repo: Path, ref: str) -> dict[str, list[str]] | None:
    """Every commit reachable from `ref`, indexed by its 7-character prefix.

    ONE `git rev-list` answers what would otherwise be one
    `git merge-base --is-ancestor` per claim. Measured on a 5000-commit
    repository: rev-list costs 125 ms and returns 205 KB, while a single
    merge-base costs about 100 ms. The batch therefore pays for itself at two
    distinct commits and wins by roughly 800x at two thousand, which took that
    stress case from 105 seconds to about a second.

    Used unconditionally rather than above some threshold, deliberately. A
    size-based switch would create a second path that only runs on large inputs,
    which is precisely the code that never gets exercised by a test.

    Keyed by ref because "integrated" is no longer one question about one
    branch. Re-measured on the gitflow fixture: two rev-lists cost 61 ms
    together while a single merge-base costs 29 ms, so indexing every
    integration ref pays for itself from three examined items onward - and a
    document that names branches and tags at all names more than three.

    Returns None when the ref cannot be resolved - an unborn branch, a deleted
    one, or a misconfigured name - so the caller can fall back to asking per
    commit and get the same answer it always did.
    """
    key = (str(repo), ref)
    if key in _ANCESTORS:
        return _ANCESTORS[key]
    try:
        out = _git(repo, "rev-list", ref)
    except (subprocess.CalledProcessError, OSError):
        _ANCESTORS[key] = None
        return None
    index: dict[str, list[str]] = {}
    for full in out.split():
        index.setdefault(full[:7], []).append(full)
    _ANCESTORS[key] = index
    return index


def _reachable_from(repo: Path, rev: str, ref: str) -> bool:
    """Is `rev` an ancestor of `ref`? Batched through the index when possible."""
    index = _ancestor_index(repo, ref)
    if index is None:
        try:
            _git(repo, "merge-base", "--is-ancestor", rev, ref)
            return True
        except (subprocess.CalledProcessError, OSError):
            return False
    if _SHA_SHAPE.match(rev):
        # A document carries an abbreviated commit; rev-list returns full ones.
        # `startswith` covers the 40-character case too, which is its own prefix.
        return any(full.startswith(rev) for full in index.get(rev[:7], ()))
    # A branch or tag name: resolve it once, then answer from the index.
    resolved = _resolve_ref(repo, rev)
    return bool(resolved) and resolved in index.get(resolved[:7], ())


def _resolve_ref(repo: Path, ref: str) -> str | None:
    """The full commit SHA a ref points at, or None if it does not resolve.

    `^{commit}` dereferences an annotated tag to the commit it tags, which is
    what every ancestry question here means. Without it a tag object's own SHA
    is returned and never appears in any rev-list.

    Memoised for the same reason the index is: a document repeats the same
    branch name on every claim, and resolving it once per MENTION reintroduced
    exactly the per-claim subprocess that batching exists to remove. There is a
    test asserting the process count, and it caught this.
    """
    key = (str(repo), ref)
    if key in _REFS:
        return _REFS[key]
    try:
        resolved = _git(repo, "rev-parse", "--verify", "--quiet",
                        f"{ref}^{{commit}}").strip() or None
    except (subprocess.CalledProcessError, OSError):
        resolved = None
    _REFS[key] = resolved
    return resolved


# The branch names the mainstream flows actually integrate into: gitflow and
# git-flow-avh use main/master plus develop/development, GitHub flow uses
# main/master alone, and `trunk` appears in Subversion-descended repositories.
# Only names that EXIST in the repository are used.
_INTEGRATION_NAMES = ("main", "master", "develop", "development", "trunk")


def _integration_refs(repo: Path) -> list[str]:
    """The branches this repository integrates work INTO.

    Why this exists: three rules used to ask "is X an ancestor of trunk",
    meaning three different things by it, and on a two-trunk repository each
    answer was wrong in a different direction. Measured on a gitflow fixture,
    with trunk=main a false "merged to develop" claim was invisible; with
    trunk=develop a genuinely shipped release tag was reported dead.

    A CONVENTIONAL NAME LIST, not a shape rule. The first version of this asked
    only whether the name had a slash in it, on the reasoning that topic
    branches are prefixed and long-lived ones are bare. That is true of the
    prefixes, and useless in the other direction: an existing test cuts a tag
    on a branch called `abandoned` and expects the release to be reported as
    never shipped. Slashless, so the shape rule called it an integration branch
    and went silent - turning a caught falsehood into a missed one. Every
    `gh-pages`, `experiment` or `old-master` is the same trap.

    The narrower list degrades safely. A project whose second integration
    branch has an unconventional name simply gets today's behaviour, and the
    rule this all exists for - false-merge-claim - does not consult this list
    at all, because a merge claim names its own ref.

    The configured trunk is always included, even if it is unconventional or
    has a slash, because a project that named its trunk has said so.
    """
    refs = [TRUNK]
    try:
        out = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    except (subprocess.CalledProcessError, OSError):
        return refs
    present = set(out.split())
    for name in _INTEGRATION_NAMES:
        if name in present and name not in refs:
            refs.append(name)
    return refs


def _integrated_by(repo: Path, rev: str, *, exclude: str = "") -> list[str]:
    """Which integration refs contain `rev`.

    `exclude` drops one ref from consideration, and it is load-bearing rather
    than tidy: without it a slashless topic branch is trivially an ancestor of
    itself, so every live claim about one would be reported as already merged.
    """
    return [ref for ref in _integration_refs(repo)
            if ref != exclude and _reachable_from(repo, rev, ref)]


def validate_merge_claims(repo: Path, text: str) -> list[Finding]:
    """Claims that work merged to main, re-checked against git ancestry.

    The inverse of the live-claim rule, and the more dangerous direction: a
    stale "still outstanding" claim makes a reader do redundant work, whereas a
    false "merged at X" tells the next session that work LANDED when it did
    not - so they build on a foundation that isn't there.

    Unlike live claims, this is checked WHOLE-FILE and in the archive too. A
    live status is only meaningful for the current phase, but "merged at X" is
    a permanent claim about the past: it should be true forever, in any entry,
    at any age. That asymmetry is deliberate.

    A claim whose SHA does not resolve is skipped, not double-reported -
    `validate_references` already flags it as a dead reference, and "this
    commit is not an ancestor of main" would be a confusing second finding
    about a commit that does not exist.

    THE CLAIM NAMES ITS OWN REF, and that is what gets checked. "Merged to `X`
    at `Y`" is self-describing, so asking git whether Y is on X needs no
    configuration and is strictly more precise than comparing against one
    globally configured trunk. Measured on a gitflow fixture, the old form was
    blind to half of a real project's claims in either setting: with
    trunk=main a false "merged to develop" claim went unexamined, and with
    trunk=develop a false "merged to main" claim did. Both are caught now, and
    the denominator counts every claim rather than the fraction that happened
    to name the configured branch.

    A two-group pattern means (ref, sha). A one-group pattern is the older
    contract and still means (sha), checked against trunk exactly as before, so
    a project that customised `merge_claim` keeps working.
    """
    # Claims inside code are examples, not promises. See _prose.
    text = _prose(text)
    named = _MERGE_CLAIM.groups >= 2
    claims: list[tuple[int, str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _MERGE_CLAIM.finditer(line):
            if named:
                # The pattern keeps any backticks so the rule can tell a
                # deliberate ref from a word of prose. See _claimed_ref.
                claims.append((number, match.group(1), match.group(2)))
            else:
                claims.append((number, TRUNK, match.group(1)))
    if not claims:
        return []

    # TWO git subprocesses PER CLAIM was 98% of total validation time, measured
    # on a 4000-line document: 17.7 of 18.0 seconds, and most of the 1.8s the
    # post-commit hook added to every commit. `validate_references` had already
    # solved half of this by batching existence checks, and the optimisation was
    # simply never carried across.
    #
    # Existence now goes through the same batched `git cat-file --batch-check`,
    # and ancestry is asked once per DISTINCT commit rather than once per
    # mention - documents repeat the same SHA constantly. Deliberately scoped to
    # this call rather than memoised across the process: git state can change
    # between validations, and a cache that outlives the run would answer from
    # a repository that no longer exists in that shape.
    resolved = _resolve_shas(repo, [sha for _n, _r, sha in claims])
    merged: dict[tuple[str, str], bool] = {}
    findings: list[Finding] = []
    for number, raw_ref, sha in claims:
        ref, quoted = _claimed_ref(raw_ref)
        if sha not in resolved:
            continue
        if _resolve_ref(repo, ref) is None:
            # The named branch is not here NOW, which is not the same as never
            # having been: gitflow deletes every release and feature branch on
            # merge. Asking git for the branch by name cannot tell those apart,
            # and neither can the merge-message rescue `unknown-branch` uses -
            # a squash merge or a custom `-m` erases the name entirely. This
            # probe reported a legitimately deleted `release/1.2.0` as invented.
            #
            # So ask the SUBSTANTIVE question instead: did this work land
            # anywhere at all? A missing branch plus an integrated commit is a
            # stale or misspelt name on a claim that is true in substance, and
            # silence is right. A missing branch plus a commit on no
            # integration branch is a claim that work landed when it did not,
            # which is the whole point of the rule.
            #
            # This also keeps the rule from being defeated by a typo. Evading
            # it requires the commit to be genuinely integrated, at which point
            # there is no false claim left to hide.
            if not quoted:
                continue        # a bare word, likelier prose than a ref
            if not _integrated_by(repo, sha):
                findings.append(Finding(
                    number, "false-merge-claim",
                    f"claims work merged to `{ref}` at `{sha}`, but this "
                    f"repository has no such branch and that commit is on no "
                    f"integration branch either",
                ))
            continue
        key = (ref, sha)
        if key not in merged:
            merged[key] = _reachable_from(repo, sha, ref)
        if not merged[key]:
            findings.append(Finding(
                number, "false-merge-claim",
                f"claims work merged to {ref} at `{sha}`, but that commit "
                f"is not an ancestor of {ref}",
            ))
    return findings


def _claimed_ref(raw: str) -> tuple[str, bool]:
    """The ref a merge claim names, and whether the author backticked it.

    Backticks are the whole signal. `` merged to `develp` at `abc` `` is a
    claim about a specific branch and a typo in it must be reported; "merged to
    the branch at `abc`" is prose, and treating `the` as a missing branch would
    be the noise that gets a validator ignored. Requiring backticks outright
    would instead lose every project that writes the branch name bare, so the
    pattern accepts both and the rule distinguishes them here.
    """
    if len(raw) >= 2 and raw.startswith("`") and raw.endswith("`"):
        return raw[1:-1], True
    return raw, False


_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/])")


def validate_path_pointers(repo: Path, text: str) -> list[Finding]:
    """Paths offered as pointers must resolve; a pointer to nothing is useless.

    Only OPERATIVE references are checked - a path introduced by "Plan:",
    "Design:", "see", or "read". A path merely MENTIONED ("we deleted X",
    "Phase 8 had X", "Phase 10 will add X") is description or intent, not a
    pointer, and flagging it would be noise. See the note above `_PATH_POINTER`
    for the corpus measurement behind that distinction.

    Checked whole-file and in the archive, like merge claims: a pointer is an
    operative promise at any age, and archiving an entry does not make its
    broken pointer work.
    """
    # Claims inside code are examples, not promises. See _prose.
    text = _prose(text)
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for raw in _PATH_POINTER.findall(line):
            exists, actual_case = _resolve_reference(repo, repo, raw)
            if not exists:
                if actual_case:
                    detail = (f"points at `{raw}`, but the file on disk is "
                              f"`{actual_case}`; the case differs, which fails "
                              f"on a case-sensitive filesystem")
                else:
                    detail = f"points at `{raw}`, which does not exist"
                    moved = _renamed_to(repo, raw)
                    if moved:
                        detail += f"; git shows it renamed to `{moved}`"
                findings.append(Finding(number, "dead-path-pointer", detail))
    return findings


def validate_live_claims(repo: Path, text: str) -> list[Finding]:
    """Present-tense status claims, re-checked against git.

    Only a small closed set of phrases is inspected. Nothing here looks at
    numbers or dates, which is what keeps historical facts structurally immune
    to false positives.

    Only the NEWEST phase entry is ever checked for a live-status claim.
    Phase entries are stored newest-first, so the newest is the first segment
    whose kind is "phase"; every phase entry after it is historical by
    definition and must never produce a finding, no matter what it says. The
    cursor/line walk still advances over EVERY segment (phase or not) so
    reported line numbers stay correct - only the checking itself is
    restricted to that first phase segment.
    """
    # Claims inside code are examples, not promises. See _prose.
    text = _prose(text)
    findings: list[Finding] = []
    _, segments, _ = split_entries(text)
    cursor = 0
    newest_checked = False
    for kind, entry in segments:
        start = text.index(entry, cursor)
        cursor = start + len(entry)  # advance for every segment, phase or not
        if kind != "phase" or newest_checked:
            continue
        newest_checked = True
        if not _LIVE_PHRASES.search(entry):
            continue
        for match in _BRANCH_TOKEN.finditer(entry):
            branch = match.group(1)
            # Same path/branch ambiguity as `unknown-branch`. Harder to reach
            # here, because a live phrase must appear in the entry first, but
            # the pattern is equally capable of matching a file and the
            # consequence would be a confident falsehood about a document.
            if _looks_like_a_path(repo, branch):
                continue
            exists = _branch_exists(repo, branch)
            # "Merged" means landed on an integration branch, and which one is
            # measured rather than configured. Against a single-trunk repo that
            # is the same question as before; on a gitflow repo with trunk=main
            # it is the difference between noticing that a feature reached
            # develop and silently accepting a stale claim about it.
            holders = _integrated_by(repo, branch, exclude=branch) if exists else []
            if exists and not holders:
                continue  # genuinely still open: the claim is true
            line = text.count("\n", 0, start + match.start()) + 1
            if exists:
                detail = (f"claims `{branch}` unmerged, but it is an ancestor of "
                          f"{', '.join(holders)}")
            else:
                detail = (
                    f"claims `{branch}` unmerged, but that branch no longer exists "
                    "(merged and cleaned up, or the claim is stale)"
                )
            findings.append(Finding(line, "stale-live-claim", detail))
    return findings


# Cached per repository, because the query below cannot be narrowed with a
# pathspec and so is the expensive one here. Keyed by path, and only ever read
# after a pointer has already been found dead.
_RENAMES: dict[str, dict[str, str]] = {}


def _rename_map(repo: Path) -> dict[str, str]:
    """Recent renames, old path to new.

    NOT narrowed with a pathspec, and that is deliberate rather than sloppy.
    `git log --diff-filter=R -- <old path>` returns NOTHING: once rename
    detection has run, history simplification no longer considers that commit
    to touch the old name. Measured directly, since the pathspec version looked
    obviously correct and silently found nothing on a repository where the
    rename was two commits old.
    """
    key = str(repo)
    if key in _RENAMES:
        return _RENAMES[key]
    mapping: dict[str, str] = {}
    try:
        out = _git(repo, "log", "--diff-filter=R", "--name-status",
                   "--format=", "-n", "200")
    except (subprocess.CalledProcessError, OSError):
        out = ""
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            mapping.setdefault(parts[1], parts[2])
    _RENAMES[key] = mapping
    return mapping


def _renamed_to(repo: Path, missing: str) -> str | None:
    """Where git says a now-missing path ended up, or None.

    Reporting a pointer as dead is correct but unhelpful when the file was
    merely renamed and git knows exactly where it went. Rename chains are
    followed, so a file moved twice still resolves to where it actually is.
    """
    mapping = _rename_map(repo)
    current = missing.replace("\\", "/")
    seen = {current}
    while current in mapping:
        current = mapping[current]
        if current in seen:  # a rename cycle; report the last honest step
            break
        seen.add(current)
    return None if current == missing.replace("\\", "/") else current


# Markdown link syntax is fixed by the format, not by any project's habits, so
# unlike the prose patterns this one is not configurable. There is no corpus to
# measure: `[text](target)` means the same thing everywhere.
_MD_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+?)\s*\)")
_EXTERNAL = re.compile(r"^(?:https?:|mailto:|ftp:|tel:|data:|//)", re.I)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_EXPLICIT_ANCHOR = re.compile(r"""(?:name|id)\s*=\s*["']([^"']+)["']""")
_FENCE = re.compile(r"^\s*(```|~~~)")

# A relative link resolves against the FILE that contains it, not the repository
# root, and the rule signature (repo, text) carries no path. main() sets this
# before validating each document. Single-threaded CLI code, set in one place.
_LINK_BASE: Path | None = None


_INLINE_CODE = re.compile(r"`[^`\n]*`")


def _strip_code(text: str) -> str:
    """Blank out fenced blocks AND inline code spans, preserving line numbers.

    A README demonstrating link syntax is showing an example, not making a
    promise, and checking it produces exactly the kind of false positive that
    gets a validator ignored.

    Inline spans were missed at first, and this project's own README caught it:
    the table row documenting this very rule contains a backticked example
    link, and the rule reported it as dead. Documentation ABOUT links is the
    most predictable place for example links to appear, which makes it the last
    place a link checker can afford to be naive.

    Blanked with SPACES rather than emptied, so both the line count and every
    character offset survive. Rules that report a line by counting newlines up
    to a match offset therefore keep working on the stripped text, which is what
    lets every claim rule share this instead of only the link rules.
    """
    return _blank(text, inline=True)


# Nine rules each stripped the same document independently: 1.22 of 6.4 seconds
# on a 100,000-line file, spent producing nine identical copies. Keyed on object
# IDENTITY rather than equality, which is what makes this safe without a
# lifecycle: every rule in one validate() receives the same str object, and a
# different object simply misses. No hashing of a 5 MB string, and at most two
# entries retained.
_STRIPPED: dict[bool, tuple[str, str]] = {}


def _blank(text: str, *, inline: bool) -> str:
    cached = _STRIPPED.get(inline)
    if cached is not None and cached[0] is text:
        return cached[1]
    result = _blank_uncached(text, inline=inline)
    _STRIPPED[inline] = (text, result)
    return result


def _blank_uncached(text: str, *, inline: bool) -> str:
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
            out.append(" " * len(line))
            continue
        if inside:
            out.append(" " * len(line))
        elif inline:
            out.append(_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line))
        else:
            out.append(line)
    return "\n".join(out)


def _prose(text: str) -> str:
    """Text with FENCED BLOCKS removed, for rules that check claims.

    A fenced block is an example or captured output, not a promise. A README
    showing the expected format, or a pasted `git log`, was being read as a
    claim about the commits in it.

    Inline code is deliberately KEPT here, unlike in the link rules. Claims are
    written inside backticks by convention - "merged to `main` at `abc1234`",
    "**Design:** `docs/plan.md`" - so blanking inline spans would delete the
    very thing these rules exist to check. Applying the link rules' stripping
    wholesale turned eight tests red at once, which is a cheaper way to learn it
    than shipping a validator that silently checks nothing.

    NOT used by the secret scan either, for the opposite reason: a credential
    pasted inside a fence is still a committed credential. That rule is about
    what the file CONTAINS, not what it claims.
    """
    return _blank(text, inline=False)


def _slug(title: str) -> str:
    """Approximate the heading-to-anchor conversion used by common renderers."""
    text = re.sub(r"`([^`]*)`", r"\1", title.strip().lower())
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text).strip("-")


def _anchors(text: str) -> set[str]:
    """Every fragment this document offers, from headings and explicit anchors."""
    found = {_slug(m.group(1)) for line in text.splitlines()
             if (m := _HEADING.match(line))}
    found |= {a.lower() for a in _EXPLICIT_ANCHOR.findall(text)}
    return found - {""}


def validate_md_links(repo: Path, text: str) -> list[Finding]:
    """Relative markdown links whose target file is gone.

    Distinct from `dead-path-pointer`, which needs a backticked path introduced
    by an operative marker. A markdown link needs no such hedging: linking to a
    file IS the operative use, so there is no false-positive class here of the
    kind that forced the path rule to be keyed on markers.

    External links are skipped deliberately. Checking them needs the network,
    which would break the deterministic-local guarantee and make a green run
    depend on someone else's uptime.
    """
    base = _LINK_BASE or repo
    findings: list[Finding] = []
    for number, line in enumerate(_strip_code(text).splitlines(), start=1):
        for raw in _MD_LINK.findall(line):
            if _EXTERNAL.match(raw) or raw.startswith("#"):
                continue
            target = raw.split("#", 1)[0]
            if not target:
                continue
            exists, actual_case = _resolve_reference(repo, base, target)
            if exists:
                continue
            if actual_case:
                detail = (f"links to `{target}`, but the file on disk is "
                          f"`{actual_case}`; the case differs, which fails on a "
                          f"case-sensitive filesystem")
            else:
                detail = f"links to `{target}`, which does not exist"
                moved = _renamed_to(repo, target)
                if moved:
                    detail += f"; git shows it renamed to `{moved}`"
            findings.append(Finding(number, "dead-md-link", detail))
    return findings


def validate_md_anchors(repo: Path, text: str) -> list[Finding]:
    """Same-document `#fragment` links pointing at no such heading.

    Checked only for fragments with no file part, so the answer lives entirely
    in the text being validated. A fragment on another file would require
    reading that file and reproducing its renderer's slug rules, which is a
    guess rather than a fact.
    """
    available = _anchors(text)
    findings: list[Finding] = []
    for number, line in enumerate(_strip_code(text).splitlines(), start=1):
        for raw in _MD_LINK.findall(line):
            if not raw.startswith("#") or len(raw) < 2:
                continue
            fragment = raw[1:].lower()
            if fragment in available:
                continue
            findings.append(Finding(
                number, "dead-md-anchor",
                f"links to `{raw}`, but this document has no such heading",
            ))
    return findings


def _named_in_merge_history(repo: Path, branch: str) -> bool:
    """Did a merge commit ever mention this branch?

    THE MEASUREMENT THAT MADE THIS RULE POSSIBLE. Every one of the four branches
    named in the source project's current document had already been deleted, so
    a plain "does this branch exist" check would have produced four findings and
    four false positives on its first run: the same shape as the path rule that
    was nearly shipped keyed on appearance.

    All four were still named in merge commits. That is what separates "merged
    and cleaned up", which is ordinary hygiene, from "never existed", which is
    a typo or an invented name and worth reporting.
    """
    try:
        out = _git(repo, "log", "--merges", "--fixed-strings", "--grep", branch,
                   "--format=%H", "-n", "1")
    except (subprocess.CalledProcessError, OSError):
        return True  # cannot tell: stay silent rather than accuse
    return bool(out.strip())


# A branch name and a file path are THE SAME SHAPE: `prefix/name`. That is not
# a hypothetical collision. The installer's fallback pattern for a repository
# with no dominant branch prefix is `([\w.-]+/[^`]+)`, which matches
# `docs/arch.md` exactly as readily as `feature/checkout`.
#
# It went unnoticed for as long as `branch_token` fed only `stale-live-claim`,
# because that rule gates on a live phrase appearing in the same entry first, so
# the loose pattern almost never reached a check. `unknown-branch` has no such
# gate and inherited the looseness, reporting a renamed design document as a
# branch that never existed. Measured on a real installed repository, first run,
# which is the only reason it was caught before release.
#
# The extension test requires the first character after the dot to be a LETTER,
# so `docs/arch.md` is excluded while a genuine `release/v1.2` is not. Erring
# toward silence here is deliberate: a missed typo costs a reader nothing, and a
# file reported as a phantom branch is the kind of false positive that gets a
# validator switched off.
_FILEISH = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")


# Directory listings, cached only while validate() says it is safe to.
#
# The case check lists a directory per path component, so 3000 links four levels
# deep cost 12,000 listings and 0.88 of 6.4 seconds. Within one validate() the
# filesystem is assumed stable, which every rule here already assumes.
#
# None means CACHING IS OFF, which is the state whenever a rule is called
# directly rather than through validate(). That matters: a caller that creates a
# file between two checks must see the new answer, and a cache with no owner
# would quietly hand back the old one. Correctness is the default; speed is
# opted into by the one function that knows the scope.
_DIRCACHE: dict[Path, set[str]] | None = None


def _listdir(directory: Path) -> set[str]:
    if _DIRCACHE is None:
        return {entry.name for entry in directory.iterdir()}
    names = _DIRCACHE.get(directory)
    if names is None:
        names = {entry.name for entry in directory.iterdir()}
        _DIRCACHE[directory] = names
    return names


def _actual_case(base: Path, relative: str) -> str | None:
    """The on-disk spelling of `relative`, or None if no such file exists.

    Windows and macOS resolve `docs/PLAN.md` to `docs/plan.md` without
    complaint; Linux does not. A document that passes on a developer's laptop
    therefore fails in CI, or worse, passes in CI and misleads every Linux
    reader. Comparing each component against the real directory entry gives the
    same answer on every platform, which is the only useful kind.

    `Path.resolve()` is deliberately avoided: on Windows it silently rewrites a
    path to its on-disk case, which would make this function agree with the bug
    it exists to find.
    """
    probe = base
    parts: list[str] = []
    for part in Path(relative).parts:
        if part in (".", ".."):
            probe = probe / part
            parts.append(part)
            continue
        try:
            names = _listdir(probe)
        except OSError:
            return None
        if part in names:
            exact = part
        else:
            matches = [n for n in names if n.lower() == part.lower()]
            if not matches:
                return None
            exact = matches[0]
        parts.append(exact)
        probe = probe / exact
    return "/".join(parts)


def _resolve_reference(repo: Path, base: Path, raw: str) -> tuple[bool, str | None]:
    """(exists_portably, on_disk_spelling_if_it_differs)."""
    if _ABSOLUTE.match(raw):
        return Path(raw).exists(), None
    actual = _actual_case(base, raw)
    if actual is None:
        return False, None
    normalised = Path(raw).as_posix()
    return (True, None) if actual == normalised else (False, actual)


def _looks_like_a_path(repo: Path, token: str) -> bool:
    """True when a token is better explained as a file than as a branch."""
    return bool(_FILEISH.search(token)) or (repo / token).exists()


def validate_branch_mentions(repo: Path, text: str) -> list[Finding]:
    """A branch named in the newest entry that git has never heard of.

    Newest entry only, for the same reason live claims are: older entries name
    branches that were correct when written. Deletion after merge is normal and
    is never reported, because the merge commit still names the branch.
    """
    # Claims inside code are examples, not promises. See _prose.
    text = _prose(text)
    findings: list[Finding] = []
    _, segments, _ = split_entries(text)
    cursor = 0
    newest_checked = False
    for kind, entry in segments:
        start = text.index(entry, cursor)
        cursor = start + len(entry)
        if kind != "phase" or newest_checked:
            continue
        newest_checked = True
        for match in _BRANCH_TOKEN.finditer(entry):
            branch = match.group(1)
            if _looks_like_a_path(repo, branch):
                continue  # a file reference caught by a path-shaped pattern
            if _branch_exists(repo, branch) or _named_in_merge_history(repo, branch):
                continue
            line = text.count("\n", 0, start + match.start()) + 1
            findings.append(Finding(
                line, "unknown-branch",
                f"names `{branch}`, which does not exist and appears in no "
                f"merge commit (a typo, or work that was never integrated)",
            ))
    return findings


def validate_release_tags(repo: Path, text: str) -> list[Finding]:
    """"Released in v2.1" where no such tag exists, or it shipped on nothing.

    Measured as absent from the corpus this was built against, so its
    denominator honestly reports 0 here. It is included for projects that keep
    a CHANGELOG, where this is the usual way a release is claimed, and it is
    falsifiable in exactly the way a merge claim is.

    "On an integration branch" rather than "an ancestor of trunk", because a
    release tag lives on the RELEASE line and that is not always the branch a
    project integrates into day to day. Measured on a gitflow fixture with
    trunk=develop, the old question reported a genuinely shipped `v1.2.0` as
    dead: the tag sits on main's release merge, and develop received the
    release branch rather than that commit. A tag reachable from no integration
    branch at all is still reported, which is the case this rule exists for -
    a tag created for a release that was abandoned or rewritten away.
    """
    # Claims inside code are examples, not promises. See _prose.
    text = _prose(text)
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for tag in _RELEASE_TAG.findall(line):
            try:
                _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}")
            except (subprocess.CalledProcessError, OSError):
                findings.append(Finding(
                    number, "dead-release-tag",
                    f"claims release `{tag}`, but no such tag exists",
                ))
                continue
            if not _integrated_by(repo, f"refs/tags/{tag}"):
                findings.append(Finding(
                    number, "dead-release-tag",
                    f"tag `{tag}` exists but is on no integration branch "
                    f"({', '.join(_integration_refs(repo))})",
                ))
    return findings


# An install snippet pins a version. `repo:` and `rev:` are pre-commit's fixed
# syntax rather than any project's habit, so like markdown link syntax there is
# nothing here to measure and nothing to configure.
_PIN_REPO = re.compile(r"^\s*(?:-\s*)?repo:\s*(\S+)")
_PIN_REV = re.compile(r"^\s*rev:\s*([^\s#]+)")


def _normalise_remote(url: str) -> str | None:
    """A remote URL reduced to `owner/name`, lowercased.

    Both spellings of the same repository must compare equal: an SSH remote
    reads `git@github.com:owner/name.git` and the URL a README tells people to
    use reads `https://github.com/owner/name`.
    """
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    parts = [p for p in url.replace(":", "/").split("/") if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else None


def _own_remote(repo: Path) -> str | None:
    """This repository as `owner/name`, or None when it has no origin."""
    return _normalise_remote(_git_soft(repo, "remote", "get-url", "origin"))


def _pinned_refs(repo: Path, text: str) -> list[tuple[int, str]]:
    """Every `rev:` pin governed by a `repo:` naming THIS repository.

    The governing `repo:` is what keeps this rule honest. A project documenting
    somebody else's pre-commit hook writes `rev: v4.5.0` for a tag that lives in
    somebody else's repository, and checking that here would report a finding on
    a line that is perfectly correct. Only pins aimed at us are answerable, so
    only those are asked about.
    """
    own = _own_remote(repo)
    if own is None:
        return []
    found: list[tuple[int, str]] = []
    governing: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        match = _PIN_REPO.match(line)
        if match:
            governing = _normalise_remote(match.group(1))
            continue
        match = _PIN_REV.match(line)
        if match and governing == own:
            found.append((number, match.group(1)))
    return found


def validate_pinned_refs(repo: Path, text: str) -> list[Finding]:
    """An install snippet pinning a version of THIS repository that does not exist.

    The one rule that deliberately reads INSIDE code blocks. Every other claim
    rule blanks them first, because an example in a fence is not a promise - but
    an install snippet is the opposite of an example. It is the one block on the
    page a reader will copy verbatim, and a version that does not exist fails
    for them on first use.

    This exists because it happened twice here. A README pinned `rev: v0.5.0`
    for a fortnight while the repository had no tags at all, and the rule that
    would have caught the claim in prose - `dead-release-tag` - cannot see into
    a fence by design. The blind spot was documented, understood, and still cost
    two broken instructions.

    Fenced and indented blocks both work, and neither is parsed: the `repo:` and
    `rev:` shape does not occur in prose, so matching them line by line covers
    every block style without needing to know where blocks begin.
    """
    findings: list[Finding] = []
    for number, ref in _pinned_refs(repo, text):
        try:
            _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        except (subprocess.CalledProcessError, OSError):
            findings.append(Finding(
                number, "dead-pinned-ref",
                f"install snippet pins `{ref}`, which does not exist here; "
                f"anyone copying this block gets an error",
            ))
    return findings


def _consistency_for(repo: Path) -> dict[str, tuple[tuple[str, object], ...]]:
    """The consistency block belonging to the repository being checked."""
    try:
        return load_config(repo).consistency
    except ValueError:
        return {}


def validate_consistency(repo: Path, text: str) -> list[Finding]:
    """Named values that must agree across several files in the repository.

    THE RULE THAT CAME FROM THIS PROJECT'S OWN FAILURE. Three manifests
    advertised version 0.1.0 while the CHANGELOG documented 0.3.0. Anyone
    installing was told they were getting the first release. Nothing here could
    catch it, because no rule inspects numbers.

    That restriction still stands, and this does not weaken it. The forbidden
    question is whether a number is CORRECT - "the suite was 2238" has nothing
    to be checked against, so a rule that tried would cry wolf. Asking whether
    two files CONTRADICT EACH OTHER is a different question with a definite
    answer, needing nothing but the filesystem. Every value here is compared to
    another value in the same repository, never to a judgement about the world.

    `text` is ignored: this is about the repository, not the document. It runs
    once per validation, on the primary pass only, or the same disagreement
    would be reported once per document checked.
    """
    # Configuration comes from the REPOSITORY BEING CHECKED, not from the
    # module-level CONFIG every other rule uses. This rule reads files by path,
    # so pointing it at one repository while holding another's file list is
    # meaningless - and it happened immediately: every temporary repository in
    # the test suite inherited this project's own version-consistency block and
    # was told four files were missing.
    #
    # Cheap, because it is one small TOML parse per validation, and only for
    # this rule.
    try:
        consistency = _consistency_for(repo)
    except ValueError:
        # A malformed config in the target repo is reported by the loader on the
        # path that reads it for real; re-raising here would turn a validation
        # run into a crash about a different repository's settings.
        return []

    findings: list[Finding] = []
    for name, sources in consistency.items():
        seen: dict[str, list[str]] = {}
        for relative, pattern in sources:
            target = repo / relative
            if not target.is_file():
                findings.append(Finding(
                    1, "inconsistent-artifact",
                    f"consistency check `{name}` reads `{relative}`, "
                    f"which does not exist",
                ))
                continue
            content = target.read_text(encoding="utf-8", errors="replace")
            match = pattern.search(content)
            if match is None:
                # A pattern matching nothing is the silent failure this project
                # is about: the check would pass forever having compared one
                # value with itself.
                findings.append(Finding(
                    1, "inconsistent-artifact",
                    f"consistency check `{name}` found no value in `{relative}`; "
                    f"the pattern matches nothing, so nothing is being compared",
                ))
                continue
            seen.setdefault(match.group(1), []).append(relative)

        if len(seen) > 1:
            parts = "; ".join(
                f"`{value}` in {', '.join(files)}" for value, files in sorted(seen.items())
            )
            findings.append(Finding(
                1, "inconsistent-artifact",
                f"`{name}` disagrees across files: {parts}",
            ))
    return findings


# A Git LFS pointer is a small text stub. The spec fixes the first line, which
# is the whole test - no LFS binary is invoked and no network is touched.
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
# Pointers are ~130 bytes. Anything larger under an LFS filter cannot be one,
# so its size alone settles the question and its content is never read. That is
# what keeps this affordable on a repository with thousands of binaries.
_LFS_POINTER_MAX = 1024


def _lfs_is_configured(repo: Path) -> bool:
    """Cheap gate: does this repository route anything through LFS at all?

    One file read, so a project with no `.gitattributes` - which is most of
    them - pays nothing for this rule beyond that.
    """
    try:
        text = (repo / ".gitattributes").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any("filter=lfs" in line and not line.lstrip().startswith("#")
               for line in text.splitlines())


def _lfs_governed(repo: Path) -> list[tuple[str, str]]:
    """(path, blob sha) for every tracked file the LFS filter governs.

    `git check-attr --stdin` answers for every path in ONE call. Asking per
    file is the same mistake the merge-claim rule made before it was batched,
    and a game repository has thousands of assets rather than a document's
    handful of claims.

    Attributes are read rather than the patterns re-implemented, because
    `.gitattributes` composes: nested files, negations and later rules
    overriding earlier ones. Re-deriving that from the text would be a second,
    worse implementation of something git already exposes.
    """
    key = str(repo)
    if key in _LFS:
        return _LFS[key]
    if not _lfs_is_configured(repo):
        _LFS[key] = []
        return []
    # HEAD's tree, not the index. This runs after a commit, so the committed
    # state is the thing being judged - and reading the index made the rule
    # examine ZERO files on a repository whose checkout had not completed,
    # while `.gitattributes` sat right there saying 47 patterns were LFS. A
    # denominator of 0 on a project full of assets is the shape of failure this
    # rule exists to report, so it must not be the rule's own behaviour.
    try:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "HEAD"], cwd=repo,
            capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (subprocess.CalledProcessError, OSError):
        _LFS[key] = []
        return []   # unborn HEAD: nothing is committed to judge
    blobs: dict[str, str] = {}
    for record in listing.split("\0"):
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if path and len(parts) >= 3 and parts[1] == "blob":
            blobs[path] = parts[2]
    if not blobs:
        _LFS[key] = []
        return []
    # BYTES and NUL separators, for two separate reasons that both bit here.
    #
    # `text=True` makes Python translate "\n" to "\r\n" on the pipe under
    # Windows, so git received every path with a trailing carriage return,
    # treated it as a literal path character, and answered `unspecified`. Only
    # the LAST path - the one with no trailing newline - was matched. The rule
    # then reported 1 examined out of 4 and found the single real problem
    # anyway, so it looked perfect. Had the bad file sorted first it would have
    # printed 0 findings over 0 examined and read as a clean repository.
    #
    # `-z` removes the other half: without it git QUOTES any path containing a
    # space or a non-ASCII character, and game projects are full of both, so a
    # line-and-colon parse would silently skip exactly those assets.
    payload = ("\0".join(blobs) + "\0").encode("utf-8")
    try:
        raw = subprocess.run(
            ["git", "check-attr", "-z", "--stdin", "filter"], cwd=repo,
            input=payload, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        _LFS[key] = []
        return []
    fields = raw.decode("utf-8", "replace").split("\0")
    governed = []
    # `-z` emits a flat NUL-separated stream of (path, attribute, value).
    for i in range(0, len(fields) - 2, 3):
        path, _attr, value = fields[i], fields[i + 1], fields[i + 2]
        if value == "lfs" and path in blobs:
            governed.append((path, blobs[path]))
    _LFS[key] = governed
    return governed


def validate_lfs_storage(repo: Path, text: str) -> list[Finding]:
    """A file `.gitattributes` says lives in LFS, stored as a raw blob instead.

    `.gitattributes` is a document making a falsifiable claim: it says files
    matching these patterns are stored as LFS pointers. That claim can be
    false, and when it is, nothing says so. Git accepts the commit, the engine
    loads the asset, and the repository quietly carries a real binary in its
    history forever - where removing it means rewriting history.

    It happens two ways, both ordinary: a binary committed BEFORE
    `.gitattributes` covered its extension, and a commit made from a clone with
    no LFS filter installed. Neither produces a warning from anything.

    Deliberately NOT the other direction. "Is the LFS object present locally"
    looks like the same question and is unusable: a fresh CI checkout without
    `git lfs pull` holds zero objects, so that rule would report every asset in
    the project as missing on every run. Measured, not assumed.

    Reads no document, like `inconsistent-artifact`, and is silent on any
    repository that does not use LFS.
    """
    findings: list[Finding] = []
    governed = _lfs_governed(repo)
    if not governed:
        return findings
    sizes: dict[str, int] = {}
    # Bytes again, and for the same reason: a "\r" appended to each SHA makes
    # every one of them unresolvable, and cat-file would report nothing.
    request = ("\n".join(sha for _p, sha in governed) + "\n").encode("ascii")
    try:
        out = subprocess.run(
            ["git", "cat-file", "--batch-check=%(objectname) %(objectsize)"],
            cwd=repo, input=request, capture_output=True,
            check=True).stdout.decode("utf-8", "replace")
    except (subprocess.CalledProcessError, OSError):
        return findings
    for line in out.split("\n"):
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            sizes[parts[0]] = int(parts[1])

    # Only blobs small enough to BE a pointer need their contents read; anything
    # larger under an LFS filter is settled by its size alone. Those reads are
    # then batched into one `cat-file --batch`, because one subprocess per file
    # cost 40 seconds on a 7802-file project - which is not a slow hook, it is
    # an uninstalled one. Exactly the mistake the merge-claim rule already made.
    small = [sha for _p, sha in governed
             if 0 < sizes.get(sha, 0) <= _LFS_POINTER_MAX]
    pointers: set[str] = set()
    if small:
        request = ("\n".join(dict.fromkeys(small)) + "\n").encode("ascii")
        try:
            stream = subprocess.run(["git", "cat-file", "--batch"], cwd=repo,
                                    input=request, capture_output=True,
                                    check=True).stdout
        except (subprocess.CalledProcessError, OSError):
            return findings
        # `<sha> blob <size>\n<content>\n`, repeated. Parsed by declared length
        # rather than by splitting on newlines, because blob content is
        # arbitrary bytes and may contain them.
        cursor = 0
        while cursor < len(stream):
            end = stream.find(b"\n", cursor)
            if end == -1:
                break
            header = stream[cursor:end].split()
            cursor = end + 1
            if len(header) != 3 or not header[2].isdigit():
                break
            length = int(header[2])
            if stream[cursor:cursor + len(_LFS_POINTER)] == _LFS_POINTER:
                pointers.add(header[0].decode("ascii", "replace"))
            cursor += length + 1

    for path, sha in governed:
        size = sizes.get(sha)
        if size is None or sha in pointers:
            continue
        findings.append(Finding(
            1, "raw-lfs-blob",
            f"`{path}` is tracked by an LFS filter but stored as a raw "
            f"{size}-byte blob, so it is committed into git itself",
        ))
    return findings


def _probe_lfs_storage(repo: Path, text: str) -> str | None:
    """No probe. This rule reads the repository, never the document.

    `--selftest` corrupts a claim in the prose and re-runs; there is no prose
    here to corrupt. Reported as "no probe" rather than passed off as working,
    which is the same treatment `inconsistent-artifact` gets.
    """
    return None


_SECRET_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
)


def scan_secrets(text: str) -> list[Finding]:
    """Secret-shaped tokens. Runs before any commit is attempted."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for shape in _SECRET_SHAPES:
            match = shape.search(line)
            if match:
                findings.append(Finding(
                    number, "possible-secret",
                    f"token resembling a credential: {match.group(0)[:8]}...",
                ))
                break
    return findings


_DEAD_SHA = "0" * 40
_MISSING_PATH = "__extant_selftest_missing__.md"
_FAKE_BRANCH_LEAF = "extant-selftest-no-such-branch"


def _sub_group(text: str, pattern: re.Pattern[str], group: int, value: str) -> str | None:
    """Replace one capture of the first match, or None if nothing matched."""
    match = pattern.search(text)
    if not match:
        return None
    start, end = match.span(group)
    return text[:start] + value + text[end:]


def _probe_sha(repo: Path, text: str) -> str | None:
    return _sub_group(text, re.compile(r"`([0-9a-f]{7,40})`"), 1, _DEAD_SHA)


def _probe_merge(repo: Path, text: str) -> str | None:
    """Repoint a real merge claim at a commit that is on NO integration branch.

    A nonexistent SHA will not do. The rule deliberately skips claims whose
    commit does not resolve, leaving those to `dead-sha`, so probing with zeros
    proves nothing and reports a working rule as broken. Found by running the
    selftest and watching this rule stay silent, which is the entire point of
    having one.

    The SHA moved to group 2 when claims became self-describing, and this probe
    kept corrupting group 1 - which is now the branch NAME. It replaced
    `develop` with a commit hash, the pattern stopped matching, and the rule
    went quiet. The selftest reported `false-merge-claim DID NOT FIRE` against
    a rule that was working perfectly, which is the failure a selftest is
    supposed to make impossible rather than cause. The group index is derived
    from the pattern now, so a one-group custom pattern still probes correctly.

    Excluding every integration ref rather than only trunk, because a commit
    merged to `develop` is a true claim there and would prove nothing.
    """
    excluded = _integration_refs(repo)
    try:
        out = _git(repo, "rev-list", "--all", "--not", *excluded, "-n", "1")
    except (subprocess.CalledProcessError, OSError):
        return None
    other = out.strip().splitlines()
    if not other:
        return None  # nothing off-trunk exists here to probe with
    return _sub_group(text, _MERGE_CLAIM, _MERGE_CLAIM.groups, other[0])


def _probe_pointer(repo: Path, text: str) -> str | None:
    return _sub_group(text, _PATH_POINTER, 1, _MISSING_PATH)


def _probe_tag(repo: Path, text: str) -> str | None:
    return _sub_group(text, _RELEASE_TAG, 1, "v0.0.0-extant-selftest")


def _probe_pinned_ref(repo: Path, text: str) -> str | None:
    """Repoint a real install pin at a version that does not exist.

    Located by line rather than by pattern, because only a pin governed by a
    `repo:` naming this repository is checked at all. Corrupting the first
    `rev:` on the page would prove nothing if that one belongs to somebody
    else's hook, and would report a working rule as broken.
    """
    pins = _pinned_refs(repo, text)
    if not pins:
        return None
    number, ref = pins[0]
    lines = text.splitlines(keepends=True)
    target = lines[number - 1]
    lines[number - 1] = target.replace(ref, "v0.0.0-extant-selftest", 1)
    return "".join(lines)


def _probe_md_link(repo: Path, text: str) -> str | None:
    for match in _MD_LINK.finditer(_strip_code(text)):
        raw = match.group(1)
        if _EXTERNAL.match(raw) or raw.startswith("#"):
            continue
        start, end = match.span(1)
        return text[:start] + _MISSING_PATH + text[end:]
    return None


def _probe_md_anchor(repo: Path, text: str) -> str | None:
    for match in _MD_LINK.finditer(_strip_code(text)):
        if not match.group(1).startswith("#"):
            continue
        start, end = match.span(1)
        return text[:start] + "#extant-selftest-no-such-heading" + text[end:]
    return None


def _probe_branch_in_newest(repo: Path, text: str) -> str | None:
    """Point the first branch token of the newest entry at a name git never saw."""
    _, segments, _ = split_entries(text)
    for kind, entry in segments:
        if kind != "phase":
            continue
        match = _BRANCH_TOKEN.search(entry)
        if not match:
            return None
        leaf = match.group(1).split("/", 1)
        fake = f"{leaf[0]}/{_FAKE_BRANCH_LEAF}" if len(leaf) > 1 else _FAKE_BRANCH_LEAF
        start, end = match.span(1)
        return text.replace(entry, entry[:start] + fake + entry[end:], 1)
    return None


def _probe_live_claim(repo: Path, text: str) -> str | None:
    """Only probeable if the document actually makes a live claim.

    A synthetic phrase would be written in THIS project's default vocabulary
    and would tell an adopter with different wording nothing except that the
    default matches the default.
    """
    _, segments, _ = split_entries(text)
    newest = next((s for kind, s in segments if kind == "phase"), "")
    if not newest or not _LIVE_PHRASES.search(newest):
        return None
    return _probe_branch_in_newest(repo, text)


def _probe_consistency(repo: Path, text: str) -> str | None:
    """Not probeable by corrupting text, and honest about it.

    Every other probe mutates the document. This rule never reads the document,
    so no edit to `text` can make it fire. Returning None reports NO PROBE
    rather than inventing a pass, which keeps --selftest's report true.
    """
    return None


def _probe_secret(repo: Path, text: str) -> str | None:
    """Shape-based and universal, so a synthetic probe is honest here."""
    return text + "\n\nsk-" + "A1b2C3d4E5f6G7h8I9j0K1l2" + "\n"


@dataclass(frozen=True)
class Rule:
    """One validation rule and the properties that decide where it applies.

    These were previously implicit - carried in a boolean parameter, in
    docstrings, and in the author's head. Declaring them makes the design's own
    constraints checkable: a test asserts every rule states its `falsifiable`
    question, so a rule that cannot be answered by git or the filesystem cannot
    be added quietly.
    """

    kind: str          # the finding kind it emits, for cross-checking
    check: object      # (repo, text) -> list[Finding]
    scope: str         # "whole-file" | "newest-entry"
    in_archive: bool   # does it still hold once an entry is retired?
    falsifiable: str   # the exact git/filesystem question asked. REQUIRED.
    # (repo, text) -> text with one deliberate falsehood, or None when the
    # document offers nothing to corrupt. REQUIRED, and why --selftest exists:
    # a rule that cannot state how to make itself fire cannot be shown to work.
    probe: object


def _secret_rule(repo: Path, text: str) -> list[Finding]:
    """Adapter: secrets need no repo, but the registry wants one signature."""
    return scan_secrets(text)


def count_examined(repo: Path, text: str) -> dict[str, int]:
    """How many candidates each rule actually LOOKED AT, findings aside.

    The denominator, and the reason it exists: five separate times in one day a
    check reported success while examining nothing - patterns that matched
    nothing on a foreign repo, a hook that found no interpreter, a config value
    nothing read, a worktree survey resolving to the wrong repo, a lint whose
    skip-list excluded every file. Every one printed exactly what success
    prints, because "zero findings" and "zero checked" are the same output.

    Reporting the denominator makes those two states visibly different. A rule
    showing 0 examined is either genuinely absent from this document or broken,
    and the reader needs to know which.
    """
    backticked = len(find_sha_candidates(text))
    bare = len(find_bare_sha_candidates(text))
    _, segments, _ = split_entries(text)
    newest = next((s for kind, s in segments if kind == "phase"), "")
    # Counts what the rules actually inspect, not what the pattern matched.
    # Path-shaped tokens are skipped by both branch rules, so counting them here
    # would overstate the denominator - and a denominator that overstates is
    # worse than none, because it reports coverage that does not exist.
    branches_in_newest = sum(
        1 for token in (_BRANCH_TOKEN.findall(newest) if newest else [])
        if not _looks_like_a_path(repo, token)
    )
    links = [raw for line in _strip_code(text).splitlines()
             for raw in _MD_LINK.findall(line)]
    return {
        "dead-sha": backticked + bare,
        "stale-live-claim": branches_in_newest,
        "unknown-branch": branches_in_newest,
        "false-merge-claim": len(_MERGE_CLAIM.findall(text)),
        "dead-release-tag": len(_RELEASE_TAG.findall(text)),
        "dead-path-pointer": len(_PATH_POINTER.findall(text)),
        "dead-md-link": sum(1 for raw in links
                            if not _EXTERNAL.match(raw) and not raw.startswith("#")),
        "dead-md-anchor": sum(1 for raw in links if raw.startswith("#")),
        "inconsistent-artifact": sum(
            len(sources) for sources in _consistency_for(repo).values()),
        # Counted the same way the rule finds them, so a repository with no
        # origin remote reports 0 examined rather than a silent pass.
        "dead-pinned-ref": len(_pinned_refs(repo, text)),
        # Paths under an LFS filter. A project not using LFS reports 0, which
        # is the honest answer rather than a quiet pass.
        "raw-lfs-blob": len(_lfs_governed(repo)),
        "possible-secret": len(text.splitlines()),
    }


# THE ADMISSION TEST for anything added here: it must answer a yes/no question
# to git or the filesystem, and produce zero false positives on the real corpus.
# A rule that inspects numbers or dates fails it - historical facts are true
# when written and stale forever after, so checking them cries wolf, and a
# validator that cries wolf stops being read.
RULES: tuple[Rule, ...] = (
    Rule(
        kind="dead-sha",
        check=validate_references,
        scope="whole-file",
        in_archive=True,
        falsifiable="does `git cat-file -e <sha>^{commit}` succeed?",
        probe=_probe_sha,
    ),
    Rule(
        kind="stale-live-claim",
        check=validate_live_claims,
        scope="newest-entry",
        in_archive=False,
        falsifiable="is the named branch on an integration branch, or gone entirely?",
        probe=_probe_live_claim,
    ),
    Rule(
        kind="unknown-branch",
        check=validate_branch_mentions,
        scope="newest-entry",
        in_archive=False,
        falsifiable="does the branch exist, or appear in any merge commit?",
        probe=_probe_branch_in_newest,
    ),
    Rule(
        kind="false-merge-claim",
        check=validate_merge_claims,
        scope="whole-file",
        in_archive=True,
        falsifiable="is the claimed commit an ancestor of the ref the claim names?",
        probe=_probe_merge,
    ),
    Rule(
        kind="dead-release-tag",
        check=validate_release_tags,
        scope="whole-file",
        in_archive=True,
        falsifiable="does the tag exist, and is it on an integration branch?",
        probe=_probe_tag,
    ),
    Rule(
        kind="dead-path-pointer",
        check=validate_path_pointers,
        scope="whole-file",
        in_archive=True,
        falsifiable="does the referenced path exist on disk?",
        probe=_probe_pointer,
    ),
    Rule(
        kind="dead-md-link",
        check=validate_md_links,
        scope="whole-file",
        in_archive=True,
        falsifiable="does the linked file exist on disk?",
        probe=_probe_md_link,
    ),
    Rule(
        kind="dead-md-anchor",
        check=validate_md_anchors,
        scope="whole-file",
        in_archive=True,
        falsifiable="does this document contain a heading with that anchor?",
        probe=_probe_md_anchor,
    ),
    Rule(
        kind="inconsistent-artifact",
        check=validate_consistency,
        scope="repository",
        in_archive=False,
        falsifiable="do the configured files state the same value?",
        probe=_probe_consistency,
    ),
    Rule(
        kind="dead-pinned-ref",
        check=validate_pinned_refs,
        scope="whole-file",
        in_archive=True,
        falsifiable="does `git rev-parse <ref>` resolve, for a pin naming this repository?",
        probe=_probe_pinned_ref,
    ),
    Rule(
        kind="raw-lfs-blob",
        check=validate_lfs_storage,
        scope="repository",
        in_archive=False,
        falsifiable="does every path under an LFS filter store a pointer?",
        probe=_probe_lfs_storage,
    ),
    Rule(
        kind="possible-secret",
        check=_secret_rule,
        scope="whole-file",
        in_archive=True,
        falsifiable="does the text match a known credential shape?",
        probe=_probe_secret,
    ),
)


def selftest(repo: Path, text: str) -> tuple[list[str], int, int]:
    """Corrupt one real claim per rule and confirm the rule notices.

    The question this answers is the one --verify cannot: not "is the document
    clean" but "would these rules see a problem if there were one". A pattern
    that matches nothing exits 0 forever and looks healthy, and the denominator
    only reports that it examined nothing. This proves the rest.

    Probes mutate an ACTUAL match rather than injecting invented prose, so what
    is exercised is this project's configuration against this project's writing.
    A synthetic probe written in the default vocabulary would only ever prove
    that the defaults match the defaults.
    """
    lines: list[str] = []
    fired = unprobeable = 0
    for rule in RULES:
        probed = rule.probe(repo, text)  # type: ignore[operator]
        if probed is None:
            unprobeable += 1
            lines.append(f"  {rule.kind:<20} NO PROBE       nothing to corrupt "
                         f"(no such claim here, or the repository offers "
                         f"nothing to corrupt it with)")
            continue
        findings = [f for f in rule.check(repo, probed)  # type: ignore[operator]
                    if f.kind == rule.kind]
        if findings:
            fired += 1
            lines.append(f"  {rule.kind:<20} FIRED")
        else:
            lines.append(f"  {rule.kind:<20} DID NOT FIRE   corrupted a real "
                         f"match and the rule stayed silent")
    return lines, fired, unprobeable


def validate(repo: Path, text: str, *, in_archive: bool = False,
             has_entries: bool = True, base: Path | None = None) -> list[Finding]:
    """Run every rule that applies to this KIND of document.

    The caller says what the document IS; the registry decides which rules
    follow. That replaces a `check_live_claims` boolean which forced every
    caller to know the rule list, and which would have needed a second boolean
    for the next rule with different archive semantics.

    Why `in_archive` changes anything at all: live-claim checking inspects the
    newest entry, on the premise that it is the CURRENT one and its
    present-tense status is therefore falsifiable. In the archive every entry is
    historical by construction, so the newest is merely the most recently
    retired - and running the rule there resurrects exactly the false positive
    the newest-entry scoping was introduced to kill.

    Every other rule still applies to the archive. A dead reference is worthless
    to a reader regardless of age, a false merge claim does not become true by
    being retired, and a leaked credential does not become safe.

    `has_entries` is the same idea reached from the other side. An extra
    document such as a README or CLAUDE.md has no dated entries at all, so
    "the newest entry" names nothing and the entry-scoped rules would be
    reasoning about an empty string. They are skipped for the same reason.

    `base` is the DIRECTORY the text came from, because a relative markdown link
    resolves against its own file rather than against the repository root. The
    CLI has always passed this via a module global; a library caller had no way
    to supply it, so `docs/HANDOFF.md` linking to a sibling `plan.md` was
    reported dead through the API and fine through the CLI. Passing it here
    makes the two agree, and leaving it None keeps the old repo-root behaviour
    for callers that have no particular file in mind.
    """
    global _LINK_BASE, _DIRCACHE, _ANCESTORS, _REFS, _LFS
    previous, previous_cache = _LINK_BASE, _DIRCACHE
    previous_ancestors, previous_refs, previous_lfs = _ANCESTORS, _REFS, _LFS
    if base is not None:
        _LINK_BASE = base
    # Directory listings may be reused for the duration of this call and no
    # longer. Restoring rather than clearing keeps a nested call honest.
    _DIRCACHE = {}
    # Ancestry indexes have exactly the same lifetime and the same reason for
    # it: three rules now ask about the same handful of refs, so building each
    # index once per call is the whole performance argument, and holding one
    # any longer would answer from a repository that may have moved on.
    _ANCESTORS = {}
    _REFS = {}
    _LFS = {}
    try:
        findings: list[Finding] = []
        primary = not in_archive and has_entries
        for rule in RULES:
            if rule.scope == "repository" and not primary:
                # Repository-wide, so it must not be repeated for the archive
                # and every extra document; the disagreement is the same one.
                continue
            if (in_archive or not has_entries) and not rule.in_archive:
                continue
            findings += rule.check(repo, text)  # type: ignore[operator]
        return findings
    finally:
        _LINK_BASE = previous
        _DIRCACHE = previous_cache
        _ANCESTORS = previous_ancestors
        _REFS = previous_refs
        _LFS = previous_lfs


FORMATS = ("text", "github", "sarif")
_TOOL_URI = "https://github.com/scooter-sensei/extant"


def _rel(repo: Path, path: Path) -> str:
    """Repo-relative POSIX path.

    Both machine formats locate a result by path, and both want it relative to
    the repository root with forward slashes. A Windows absolute path in a
    SARIF upload resolves to nothing on the server, so this is not cosmetic.
    """
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _fingerprint(path: str, kind: str, detail: str) -> str:
    """Stable identity for a finding, deliberately EXCLUDING the line number.

    GitHub uses partialFingerprints to recognise the same result across runs.
    Folding the line number in would make every finding brand new the moment
    text above it shifted, which is the churn the field exists to prevent.
    """
    payload = f"{path}\x00{kind}\x00{detail}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:32]


BASELINE_NAME = ".extant-baseline.json"


def _baseline_entry(item: Located) -> dict[str, str]:
    """One recorded finding, written so a human can review the diff.

    The fingerprint alone would be enough to match on, and would make the file
    unreadable. A baseline is a list of things a project has agreed to leave
    broken for now, which is exactly the kind of file that must be legible in
    review - otherwise it becomes a place to hide things, which is the fair
    objection to having one at all.
    """
    return {
        "fingerprint": _fingerprint(item.path, item.finding.kind, item.finding.detail),
        "path": item.path,
        "kind": item.finding.kind,
        "detail": item.finding.detail,
    }


def load_baseline(path: Path) -> dict[str, dict[str, str]]:
    """Recorded findings, keyed by fingerprint.

    A missing file is an error rather than an empty baseline. Treating it as
    empty would silently suppress nothing while the caller believed suppression
    was active, so a typo'd path would turn a ratcheted run back into an
    ordinary one without saying so.
    """
    if not path.is_file():
        raise ValueError(
            f"no baseline at {path}. Record one with --write-baseline, or drop "
            f"--baseline to check everything."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["findings"]
        return {e["fingerprint"]: e for e in entries}
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"{path} is not a baseline this version can read: {exc}") from exc


def write_baseline(path: Path, located: list[Located]) -> int:
    """Record every current finding. Returns how many were written."""
    entries = [_baseline_entry(item) for item in located]
    document = {
        "version": 1,
        "tool": "extant",
        "note": ("Findings this project has accepted for now. Each is still "
                 "wrong; they are simply not new. Prune with --baseline-check."),
        "findings": sorted(entries, key=lambda e: (e["path"], e["kind"], e["detail"])),
    }
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(document, fh, indent=2, ensure_ascii=True)
        fh.write("\n")
    return len(entries)


def _gh_escape(value: str, *, prop: bool = False) -> str:
    """Escape a workflow-command string.

    GitHub parses `::error k=v,k=v::message`, so a raw comma or colon inside a
    property silently truncates the annotation, and a newline in the message
    ends the command early. Paths and details here contain backticks and
    punctuation routinely, so this is the ordinary case rather than a corner.
    """
    out = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if prop:
        out = out.replace(":", "%3A").replace(",", "%2C")
    return out


def format_github(located: list[Located]) -> list[str]:
    """GitHub Actions annotations, which surface inline on the pull request."""
    return [
        f"::error file={_gh_escape(item.path, prop=True)},"
        f"line={item.finding.line},"
        f"title={_gh_escape(item.finding.kind, prop=True)}"
        f"::{_gh_escape(item.finding.detail)}"
        for item in located
    ]


def format_sarif(located: list[Located]) -> str:
    """SARIF 2.1.0, the format code-scanning tools interchange.

    The rule descriptors are generated from the registry, so a rule's
    `falsifiable` question becomes its published description. That is the same
    field the admission test already requires, which means a rule cannot reach
    this output without having stated the exact question it asks.
    """
    kinds = {rule.kind: rule for rule in RULES}
    seen: list[str] = []
    for item in located:
        if item.finding.kind not in seen:
            seen.append(item.finding.kind)

    descriptors = []
    for kind in seen:
        rule = kinds.get(kind)
        question = rule.falsifiable if rule else "not a registry rule"
        descriptors.append({
            "id": kind,
            "shortDescription": {"text": kind.replace("-", " ")},
            "fullDescription": {"text": f"Checks: {question}"},
            "help": {"text": f"This finding is falsifiable: {question}"},
        })

    results = []
    for item in located:
        results.append({
            "ruleId": item.finding.kind,
            "level": "error",
            "message": {"text": item.finding.detail},
            "partialFingerprints": {
                "statusClaim/v1": _fingerprint(
                    item.path, item.finding.kind, item.finding.detail),
            },
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": item.path},
                    "region": {"startLine": max(1, item.finding.line)},
                },
            }],
        })

    return json.dumps({
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "extant",
                "informationUri": _TOOL_URI,
                "rules": descriptors,
            }},
            "results": results,
        }],
    }, indent=2)


def format_text(located: list[Located]) -> list[str]:
    """The original human output, unchanged.

    A finding in the requested document prints bare; anything from the archive
    or an extra document is prefixed with its path. That asymmetry is preserved
    deliberately rather than tidied: it is what a reader of the primary case
    already expects, and what the existing tests pin.
    """
    return [
        item.finding.render() if item.primary
        else f"{item.path}: {item.finding.render()}"
        for item in located
    ]


def render_findings(located: list[Located], fmt: str) -> tuple[list[str], bool]:
    """Render for `fmt`. Returns the lines and whether they belong on stdout.

    SARIF has to be the ONLY thing on stdout or it is not parseable JSON, so
    the caller sends every human diagnostic to stderr in that mode. Text and
    annotation output are line-oriented and mix freely.
    """
    if fmt == "sarif":
        return [format_sarif(located)], True
    if fmt == "github":
        return format_github(located), True
    return format_text(located), True


def suggest_renames(repo: Path, base: Path, text: str, relative: str) -> str:
    """A unified diff repointing references at where git says the file went.

    Emitted to stdout as a PATCH, never written. That is not caution for its own
    sake: this tool's authority rests entirely on the fact that it checks claims
    and never writes them. A validator that edits prose can be wrong in a new
    way - it can author a falsehood itself - and the first time it did, nothing
    would be left to catch it.

    A patch keeps the boundary and loses nothing. `git apply` is one command,
    the diff is reviewable before it is applied, and the decision stays with the
    person whose document it is.

    Only renames GIT RECORDED are offered. A path that is merely missing gets no
    suggestion, because guessing where it went is exactly the authoring this
    refuses to do.
    """
    replacements: list[tuple[str, str]] = []

    for raw in _MD_LINK.findall(_strip_code(text)):
        if _EXTERNAL.match(raw) or raw.startswith("#"):
            continue
        target = raw.split("#", 1)[0]
        if not target or _resolve_reference(repo, base, target)[0]:
            continue
        moved = _renamed_to(repo, target)
        if moved:
            replacements.append((target, moved))

    for raw in _PATH_POINTER.findall(_prose(text)):
        if _resolve_reference(repo, repo, raw)[0]:
            continue
        moved = _renamed_to(repo, raw)
        if moved:
            replacements.append((raw, moved))

    if not replacements:
        return ""

    updated = text
    for old, new in dict.fromkeys(replacements):
        # Replaced only where the path is USED as a reference - inside a link
        # target or a backticked pointer - rather than anywhere the characters
        # happen to appear. A bare replace would also rewrite prose discussing
        # the old name, which is often the very sentence explaining the move.
        updated = updated.replace(f"]({old})", f"]({new})")
        updated = updated.replace(f"`{old}`", f"`{new}`")

    if updated == text:
        return ""

    import difflib
    diff = difflib.unified_diff(
        text.splitlines(keepends=True), updated.splitlines(keepends=True),
        fromfile=f"a/{relative}", tofile=f"b/{relative}", n=3,
    )
    return "".join(diff)


def search_entries(repo: Path, query: str) -> list[tuple[str, str, str]]:
    """Entries mentioning `query`, newest first, as (document, header, body).

    Returns whole ENTRIES rather than matching lines, which is the entire point
    and the only reason this beats `grep`. A decision is recorded in a dated
    entry with the reasoning around it; a naked line out of the middle tells you
    a phrase exists and not what was decided or when.

    Searches the live document and the archive together, because the whole
    problem is that entries move from one to the other. Somebody looking for a
    decision does not know, and should not need to know, whether it has been
    retired yet.
    """
    needle = query.lower()
    results: list[tuple[str, str, str]] = []
    for relative in (PRIMARY_DOC, ARCHIVE_DOC):
        path = repo / relative
        if not path.is_file():
            continue
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        _, segments, _ = split_entries(text)
        for kind, entry in segments:
            if kind != "phase" or needle not in entry.lower():
                continue
            header = entry.splitlines()[0].strip() if entry.strip() else "(untitled)"
            results.append((relative, header, entry))
    return results


def reload_config(repo: Path) -> None:
    """Re-read configuration for `repo` and refresh everything derived from it.

    Configuration is read at import, relative to this file, which is right when
    the tool sits at `tools/` inside the repository it checks. Installed as a
    package - which is what the pre-commit framework does - `__file__` is inside
    site-packages, where there is no repository and no `.extant.toml`. Without
    this the hook would validate `NEXT_SESSION.md` in every project on earth and
    report a healthy run for the ones that keep no such file.
    """
    global CONFIG
    CONFIG = load_config(repo)
    # The SAME call the module makes at import. There is no second list here
    # to fall behind the first, which is what let a computed value go stale.
    _apply_config()


def cli() -> int:
    """Console-script entry point, used by the pre-commit hook.

    Differs from `main` in two ways, both because a hook invokes the command
    bare from the repository being committed to:

    - no mode given means `--verify`
    - `--repo` defaults to the CURRENT DIRECTORY rather than to wherever the
      package was installed
    """
    argv = list(sys.argv[1:])
    modes = {"--collect", "--archive", "--validate", "--verify",
             "--selftest", "--search"}
    if not any(arg.split("=", 1)[0] in modes for arg in argv):
        argv.insert(0, "--verify")
    if not any(arg.split("=", 1)[0] == "--repo" for arg in argv):
        repo = Path.cwd()
        argv += ["--repo", str(repo)]
    else:
        index = next(i for i, a in enumerate(argv) if a.split("=", 1)[0] == "--repo")
        raw = argv[index]
        if "=" in raw:
            repo = Path(raw.split("=", 1)[1])
        elif index + 1 < len(argv):
            repo = Path(argv[index + 1])
        else:
            # `extant --repo` with nothing after it. Reaching for argv[i+1]
            # raised IndexError before argparse could say what was wrong.
            build_parser().error("--repo requires a PATH")
    reload_config(repo)
    return main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extant_collect", description="Collect and validate status facts."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collect", action="store_true", help="emit bundle.json")
    mode.add_argument("--archive", action="store_true", help="split old entries out")
    mode.add_argument("--validate", metavar="FILE", help="validate a status document")
    mode.add_argument("--verify", action="store_true", help="validate the committed doc")
    mode.add_argument("--selftest", action="store_true",
                      help="corrupt one real claim per rule and confirm each fires")
    mode.add_argument("--search", metavar="TEXT",
                      help="find past entries mentioning TEXT, live and archived")
    parser.add_argument("--full", action="store_true",
                        help="with --search, print whole entries rather than excerpts")
    parser.add_argument("--suggest-fixes", action="store_true",
                        help="with --validate/--verify, print a patch repointing "
                             "renamed files. Writes nothing; pipe to `git apply`.")
    parser.add_argument("--out", metavar="PATH", help="bundle output path")
    parser.add_argument("--suite-json", metavar="PATH", help="reuse a completed suite run")
    parser.add_argument("--sha-map", metavar="PATH", help="filter-repo commit-map")
    parser.add_argument("--repo", metavar="PATH", default=str(REPO_ROOT))
    parser.add_argument("--format", choices=FORMATS, default="text",
                        help="findings output: text, github annotations, or SARIF")
    # A ratchet, for adopting on a repository that already has years of prose.
    # The first run on an old project reports everything at once, CI goes red,
    # and the tool comes back out. Recording what is already there means new
    # claims are checked from day one without a week of archaeology first.
    parser.add_argument("--baseline", metavar="PATH", nargs="?",
                        const=BASELINE_NAME,
                        help=f"suppress findings recorded in PATH "
                             f"(default {BASELINE_NAME}). New ones still fail.")
    parser.add_argument("--write-baseline", metavar="PATH", nargs="?",
                        const=BASELINE_NAME,
                        help=f"record every current finding to PATH (default "
                             f"{BASELINE_NAME}) and exit 0. Never implicit.")
    parser.add_argument("--baseline-check", action="store_true",
                        help="report baseline entries that no longer occur, so "
                             "a granted amnesty cannot outlive its finding")
    return parser


def main(argv: list[str] | None = None) -> int:
    global _LINK_BASE
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    # Configuration is read once at import, relative to THIS FILE, which is
    # correct when the tool sits at tools/ inside the repository it checks. Run
    # from anywhere else with --repo, git operations follow --repo while the
    # config does not, so .extant.toml in the target is silently ignored. Say
    # so on stderr rather than let the two disagree quietly.
    # Narrowed to the case where a real config file is actually being ignored.
    # Warning whenever the paths merely differ would fire on every run against a
    # repository that has no config at all, where nothing is lost and the
    # defaults are what was wanted. A validator that cries wolf stops being read
    # applies to its own diagnostics too.
    ignored_config = repo / ".extant.toml"
    # Compared as resolved paths, not as strings. The upward search means the
    # config found from the script's own location is very often the same file
    # this names, and a string comparison called them different over a
    # separator - producing a warning that said the file it had just read was
    # not read.
    same_file = (ignored_config.is_file() and CONFIG.source != "defaults"
                 and ignored_config.resolve() == Path(CONFIG.source).resolve())
    if repo.resolve() != REPO_ROOT.resolve() and ignored_config.is_file() and not same_file:
        print(f"NOTE: settings came from {CONFIG.source}, so {ignored_config} was "
              f"NOT read. Configuration loads relative to this script; install it "
              f"into that repository as tools/ for its own settings to apply.",
              file=sys.stderr)
    if args.search is not None:
        if not args.search.strip():
            parser.error("--search needs something to look for")
        results = search_entries(repo, args.search)
        for relative, header, entry in results:
            print(f"{relative}: {header}")
            body = entry.splitlines()[1:]
            if args.full:
                for line in body:
                    print(f"    {line}")
            else:
                # A few lines of context, because the header alone rarely says
                # what was decided. --full prints the entry when it does not.
                excerpt = [ln for ln in body if ln.strip()][:4]
                for line in excerpt:
                    print(f"    {line.strip()[:96]}")
            print()
        # The denominator again: "no matches" and "searched nothing" print the
        # same blank otherwise, and the second happens whenever a document is
        # missing or its entry header does not match the configured prefix.
        searched = sum(
            1 for relative in (PRIMARY_DOC, ARCHIVE_DOC) if (repo / relative).is_file())
        total = 0
        for relative in (PRIMARY_DOC, ARCHIVE_DOC):
            path = repo / relative
            if path.is_file():
                with open(path, encoding="utf-8", newline="") as fh:
                    total += sum(1 for kind, _ in split_entries(fh.read())[1]
                                 if kind == "phase")
        print(f"{len(results)} match(es) in {total} entries "
              f"across {searched} document(s)")
        if total == 0:
            print("  NOTE: no entries were found to search. Either these "
                  "documents have none, or entry_prefix does not match their "
                  "headers.")
        return 0

    if args.selftest:
        target = repo / PRIMARY_DOC
        if not target.is_file():
            # diag, not print: in SARIF mode stdout carries nothing but JSON.
            diag(f"no such document: {target}")
            diag(f"  primary_doc is '{CONFIG.primary_doc}', from {CONFIG.source}")
            return 1
        try:
            with open(target, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except UnicodeDecodeError as exc:
            # A document that is not valid UTF-8 is a situation to report, not
            # to crash on. Reading it with errors="replace" instead would let
            # every rule run against silently corrupted text and report findings
            # about bytes that are not there.
            print(f"{target}: not valid UTF-8 ({exc.reason} at byte "
                  f"{exc.start}). The status document must be a text file.",
                  file=sys.stderr)
            return 1
        _LINK_BASE = target.parent
        lines, fired, unprobeable = selftest(repo, text)
        print(f"selftest: probing {len(RULES)} rules against {PRIMARY_DOC}\n")
        for line in lines:
            print(line)
        silent = len(RULES) - fired - unprobeable
        print(f"\n  {fired} fired, {unprobeable} had nothing to corrupt, "
              f"{silent} stayed silent")
        if silent:
            print("  A rule that stays silent after a real match is corrupted is "
                  "not working. Check its pattern against this document.")
        if unprobeable:
            print("  'No probe' is not a failure by itself, but a rule that "
                  "cannot be exercised is also not known to work.")
        _LINK_BASE = None
        return 1 if silent else 0
    if args.collect:
        bundle = collect(repo, suite_json=args.suite_json)
        out = Path(args.out) if args.out else repo / "status_bundle.json"
        with open(out, "w", encoding="utf-8", newline="") as fh:
            json.dump(bundle, fh, indent=2)
        if bundle["nothing_to_hand_off"]:
            print("nothing to hand off: no commits since the last status")
        print(out)
        return 0
    if args.archive:
        counts = archive(repo)
        print(f"retained={counts['retained']} archived={counts['archived']}")
        return 0
    if args.verify:
        args.validate = str(repo / PRIMARY_DOC)
    if args.validate == "":
        # M-a: argparse still counts --validate as "provided" (satisfying
        # the required mutually-exclusive group) even when its value is the
        # empty string, so this is a genuinely reachable state, not dead
        # code. It must not fall through to an implicit `None` return -
        # SystemExit(None) is exit code 0, a silent false success for a
        # nonsensical invocation.
        parser.error("--validate requires a non-empty FILE path")
    if args.validate:
        # Human diagnostics go to stderr when stdout must be pure JSON. A SARIF
        # document with a progress line prepended is not a SARIF document.
        # stdout carries ONE machine-readable thing at a time. SARIF must be
        # the only JSON there, and a patch must be the only patch there or
        # `... | git apply` receives log lines and rejects the lot. Everything
        # human moves to stderr in both cases.
        stream = (sys.stderr if (args.format == "sarif" or args.suggest_fixes)
                  else sys.stdout)

        def diag(*parts: object) -> None:
            print(*parts, file=stream)

        target = Path(args.validate)
        if not target.is_file():
            # A traceback here is a poor answer to a common situation: the
            # document lives elsewhere in this project, or the config points at
            # the wrong name. Say which file was expected and where it came from.
            diag(f"no such document: {target}")
            diag(f"  primary_doc is '{CONFIG.primary_doc}', from {CONFIG.source}")
            diag("  set primary_doc in .extant.toml, or pass --validate <path>")
            return 1
        try:
            with open(target, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except UnicodeDecodeError as exc:
            # A document that is not valid UTF-8 is a situation to report, not
            # to crash on. Reading it with errors="replace" instead would let
            # every rule run against silently corrupted text and report findings
            # about bytes that are not there.
            print(f"{target}: not valid UTF-8 ({exc.reason} at byte "
                  f"{exc.start}). The status document must be a text file.",
                  file=sys.stderr)
            return 1
        # Relative links resolve against the document, not the repo root.
        _LINK_BASE = target.parent
        mapping = load_sha_map(args.sha_map) if args.sha_map else None
        if mapping is not None:
            text, changed = translate_shas(text, mapping)
            if changed:
                with open(target, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                diag(f"translated {changed} stale SHA reference(s) in {target}")
        located: list[Located] = []
        # Recording a baseline must see everything, so suppression is off while
        # writing one. Otherwise a second --write-baseline against an existing
        # baseline would record only what that baseline had missed, quietly
        # shrinking it each time it was run.
        baselined: dict[str, dict[str, str]] = {}
        # --baseline-check implies reading one, so it does not also need
        # --baseline. Both fall back to the conventional filename.
        # Against the REPO, not the process cwd. A hook or a CI step runs
        # from wherever it likes and passes --repo, and a relative baseline
        # would then be looked for somewhere else entirely - reported as
        # missing, or worse, silently a different file.
        baseline_path = Path(args.baseline or BASELINE_NAME)
        if not baseline_path.is_absolute():
            baseline_path = repo / baseline_path
        if (args.baseline or args.baseline_check) and not args.write_baseline:
            try:
                baselined = load_baseline(baseline_path)
            except ValueError as exc:
                print(exc, file=sys.stderr)
                return 2
        matched: set[str] = set()
        suppressed = 0

        def record(path: str, items: list[Finding], *, primary: bool) -> int:
            """Collect for the machine formats; print inline for the human one.

            Text output stays interleaved with its summaries, which is what a
            reader following along expects and what the existing tests pin. The
            machine formats are emitted in one block at the end instead.

            Returns the count of findings that were NOT baselined, which is what
            decides the exit code. A baselined finding is still wrong; it is
            simply not new.
            """
            nonlocal suppressed
            new = 0
            for finding in items:
                item = Located(path, finding, primary)
                fingerprint = _fingerprint(path, finding.kind, finding.detail)
                if fingerprint in baselined:
                    matched.add(fingerprint)
                    suppressed += 1
                    continue
                new += 1
                located.append(item)
                if args.format == "text":
                    print(format_text([item])[0], file=stream)
            return new

        findings = validate(repo, text)
        exit_code = 1 if record(_rel(repo, target), findings, primary=True) else 0

        # The denominator. Without it a clean run and a run that checked nothing
        # print identically - the failure that recurred five times in one day.
        # A rule reporting 0 examined is either genuinely absent from this
        # document or broken, and the reader has to be able to tell.
        examined = count_examined(repo, text)
        summary = ", ".join(f"{kind} {n}" for kind, n in examined.items() if kind != "possible-secret")
        blind = [kind for kind, n in examined.items() if n == 0 and kind != "possible-secret"]
        diag(f"checked {Path(args.validate).name}: {summary}"
             f" ({examined['possible-secret']} lines scanned for secrets)")
        if blind:
            diag("  NOTE: these rules matched nothing at all - either this "
                 "document makes no such claims, or the pattern is wrong: "
                 + ", ".join(blind))

        # --verify/--validate used to read only their target file, so content
        # moved into the archive by --archive escaped validation forever: a
        # dead reference or a stale live-claim could sit there unreported
        # indefinitely. Validate it too, whenever it exists.
        archive_path = repo / ARCHIVE_DOC
        if archive_path.exists():
            with open(archive_path, encoding="utf-8", newline="") as fh:
                archive_text = fh.read()
            if mapping is not None:
                archive_text, archive_changed = translate_shas(archive_text, mapping)
                if archive_changed:
                    with open(archive_path, "w", encoding="utf-8", newline="") as fh:
                        fh.write(archive_text)
                    diag(f"translated {archive_changed} stale SHA reference(s) in {ARCHIVE_DOC}")
            archive_findings = validate(repo, archive_text, in_archive=True)
            if record(ARCHIVE_DOC, archive_findings, primary=False):
                exit_code = 1

        # Extra documents: CLAUDE.md, AGENTS.md, a README. They carry the same
        # kinds of checkable claim and rot the same way, but have no dated
        # entries, so the entry-scoped rules are skipped exactly as they are for
        # the archive. A project whose status lives in a tracker rather than a
        # document still gets these checked, which is most of the reason the
        # setting exists.
        for relative in CONFIG.extra_docs:
            extra = repo / relative
            if not extra.is_file():
                # A configured document that is absent is itself a finding, not
                # a log line: a machine consumer has to see it too, or a broken
                # extra_docs entry disappears from every format but the human
                # one. Line 1, because there is no file to point into.
                if record(relative, [Finding(
                    1, "missing-document",
                    "listed in extra_docs but does not exist",
                )], primary=False):
                    exit_code = 1
                continue
            with open(extra, encoding="utf-8", newline="") as fh:
                extra_text = fh.read()
            _LINK_BASE = extra.parent
            extra_findings = validate(repo, extra_text, has_entries=False)
            new_extra = record(relative, extra_findings, primary=False)
            examined_extra = count_examined(repo, extra_text)
            # Repository-scoped rules do not run for an extra document, so
            # reporting their candidate count here claims coverage that was
            # not provided. A denominator that overstates is worse than none:
            # it is the reassuring number, not the honest one.
            skipped = {rule.kind for rule in RULES if rule.scope == "repository"}
            # Zero counts are REPORTED, not filtered. "examined 0" and "not
            # applicable here" are different facts, and dropping the zeros
            # made an extra document look fully covered while a rule sat
            # blind - the exact conflation the primary summary avoids.
            checked = ", ".join(f"{kind} {n}" for kind, n in examined_extra.items()
                                if kind != "possible-secret"
                                and kind not in skipped)
            diag(f"checked {relative}: {checked or 'nothing applicable'}")
            if new_extra:
                exit_code = 1
        _LINK_BASE = None

        if args.suggest_fixes:
            # Written to stdout as a patch and never applied. In sarif mode the
            # document must stay pure JSON, so the patch goes to stderr instead
            # of corrupting it.
            patch = suggest_renames(repo, target.parent, text, _rel(repo, target))
            if patch:
                # Written as BYTES, because print() rewrites newlines on
                # Windows. A patch for a document that uses LF then arrives
                # with CRLF, git apply rejects the mixed endings, and a patch
                # that cannot be applied is not a feature.
                sys.stdout.buffer.write(patch.encode("utf-8"))
                sys.stdout.buffer.flush()
            else:
                diag("no rename suggestions: nothing references a file git "
                     "recorded as moved")

        # Machine formats are emitted in one block, after every document has
        # been read, because SARIF is a single JSON value and annotations are
        # easier to read grouped than interleaved with progress lines.
        if args.format != "text":
            for line in render_findings(located, args.format)[0]:
                print(line)

        if args.write_baseline:
            # Explicit, never implicit. A baseline that rewrote itself on every
            # verify would ratchet the wrong way: each run would forgive
            # whatever it had just found, and the check would decay to nothing
            # while continuing to report success.
            path = Path(args.write_baseline)
            written = write_baseline(path, located)
            diag(f"recorded {written} finding(s) in {_rel(repo, path)}")
            diag("Each is still wrong. They are excluded from future runs so "
                 "that NEW ones are visible; prune them with --baseline-check.")
            return 0

        if baselined:
            # Stated on every run, in both directions. "no findings" and "no new
            # findings, 40 suppressed" are different facts, and a baseline that
            # hides its own size is the denominator failure this project exists
            # to surface, reintroduced by one of its own features.
            diag(f"{len(located)} new finding(s), {suppressed} suppressed by "
                 f"{_rel(repo, baseline_path)}")

        if args.baseline_check:
            stale = [entry for fingerprint, entry in sorted(baselined.items())
                     if fingerprint not in matched]
            diag(f"\nbaseline: {len(baselined)} entr(y/ies), {len(matched)} still "
                 f"occur, {len(stale)} do not")
            for entry in stale:
                diag(f"  STALE  {entry['path']}: [{entry['kind']}] {entry['detail']}")
            if stale:
                diag("\nThese no longer happen: the claim was fixed, or deleted. "
                     "Remove them, or the baseline keeps forgiving something that "
                     "is not there.")
                exit_code = 1

        return exit_code
    # M-a: unreachable. The mutually-exclusive group is required, and every
    # member (collect, archive, verify, validate-non-empty) returns above;
    # validate-empty-string calls parser.error above, which exits. No state
    # argparse can produce falls through to here.
    raise AssertionError(f"unreachable: argparse guarantees one mode; got {args}")


if __name__ == "__main__":
    raise SystemExit(main())
