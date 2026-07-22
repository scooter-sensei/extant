"""Collector and validator for the /handoff session-handoff system.

    .venv/Scripts/python tools/handoff_collect.py --collect --out bundle.json
    .venv/Scripts/python tools/handoff_collect.py --archive
    .venv/Scripts/python tools/handoff_collect.py --validate NEXT_SESSION.md
    .venv/Scripts/python tools/handoff_collect.py --verify

Deterministic half of the handoff system: everything here is mechanical and
tested. Prose is written by the subagent, never by this script. See
docs/superpowers/specs/2026-07-20-handoff-system-design.md.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# This file is used two ways: imported as `tools.handoff_collect` (tests, where
# the repo root is on sys.path) and run directly as a script (the hooks and the
# /handoff command, where only tools/ is). The first import fails in the second
# case, so fall back to the sibling module.
try:
    from tools.handoff_config import load_config
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI tests
    from handoff_config import load_config

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every project-specific value is resolved once, here, from .handoff.toml beside
# the repo root - falling back to defaults that reproduce this project's
# behaviour exactly, so a repo without a config file sees no change. The names
# below stay module-level constants because the whole module and its tests refer
# to them directly; only their SOURCE moved.
#
# Porting warning, stated at length in tools/handoff_config.py: three of these
# patterns were derived by MEASURING this repo's documents. Copy them to another
# project without re-measuring and the validator matches nothing while appearing
# healthy. Run `--init` against the target repo instead of guessing.
CONFIG = load_config(REPO_ROOT)

HANDOFF_DOC = CONFIG.handoff_doc
ARCHIVE_DOC = CONFIG.archive_doc
RETAIN_ENTRIES = CONFIG.retain_entries
TRUNK = CONFIG.trunk
_ARCHIVE_HEADER = CONFIG.archive_header


def _git(repo: Path, *args: str) -> str:
    """Run a git command in `repo`, returning stdout. Raises on non-zero."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


_PHASE_TASK = CONFIG.phase_task
# GA-2: the fallback REQUIRES a literal "Phase " prefix. An unanchored
# \d+\.\d+ matches library versions - the real commit "PySide6 6.11 QML load
# guard" on main would otherwise be filed under phase "6.11".
_PHASE_BARE = CONFIG.phase_bare


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
    """SHA of the most recent commit touching the handoff doc, else ''.

    Derived from the repo rather than stored, so there is no marker file or tag
    that can drift out of sync with reality.
    """
    out = _git(repo, "log", "-1", "--format=%H", "--", HANDOFF_DOC)
    return out.strip()


def commits_since(repo: Path, boundary: str) -> list[dict[str, str]]:
    """Commits after `boundary` (exclusive), oldest first, phase-labelled."""
    rev_range = f"{boundary}..HEAD" if boundary else "HEAD"
    out = _git(repo, "log", "--reverse", "--format=%H%x00%s", rev_range)
    commits: list[dict[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\x00")
        commits.append({"sha": sha, "subject": subject, "phase": parse_phase(subject)})
    return commits


_TODO_MARKER = CONFIG.todo_markers
# M-b: this tool's own source and its tests DISCUSS the markers TODO/FIXME/
# XXX at length, in comments, docstrings, and string literals - including
# them would report phantom findings on every real run that touches this
# file. Same "noise trains the reader to ignore the section" failure GA-5
# already exists to prevent, just reintroduced by the tool scanning itself.
_TODO_SCAN_EXCLUDED_FILES = {"tools/handoff_collect.py"}
_TODO_SCAN_EXCLUDED_DIR_PREFIX = "tests/tools/"

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
    /handoff step 1. A worktree-run suite would also be wrong even where a
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
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    merged = set(_git(repo, "branch", "--merged", TRUNK).replace("*", "").split())
    all_branches = set(_git(repo, "branch", "--format=%(refname:short)").split())
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
_SECTION_HEADER = re.compile(
    "^" + re.escape(CONFIG.entry_prefix.split()[0]) + " ", re.MULTILINE
)
_BASE_HEADER = CONFIG.base_header
_PHASE_PREFIX = CONFIG.entry_prefix
_POINTER_PREFIX = CONFIG.pointer_prefix


def split_entries(text: str) -> tuple[str, list[tuple[str, str]], str]:
    """Split a handoff doc into (preamble, [(kind, text)], reference base).

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
    doc = repo / HANDOFF_DOC
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
    real handoff documents with zero false positives.
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
    the EX-8 note in docs/superpowers/plans/2026-07-20-handoff-system.md for
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
    handoff document plus its archive carries ~60 references. Batching takes
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
        if not line.rstrip().endswith("missing")
    }


def validate_references(repo: Path, text: str) -> list[Finding]:
    """Every referenced SHA must still resolve; a dead reference is useless."""
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


_LIVE_PHRASES = CONFIG.live_phrases
_BRANCH_TOKEN = CONFIG.branch_token


def _is_merged(repo: Path, branch: str) -> bool:
    try:
        _git(repo, "merge-base", "--is-ancestor", branch, TRUNK)
        return True
    except subprocess.CalledProcessError:
        return False


def _branch_exists(repo: Path, branch: str) -> bool:
    try:
        _git(repo, "rev-parse", "--verify", branch)
        return True
    except subprocess.CalledProcessError:
        return False


# Requires the SHA to FOLLOW the phrase, and requires an explicit `main`
# target. Both restrictions were taken from the real corpus: every genuine
# merge claim in it reads "Merged/SHIPPED to `main` at `<sha>`", while the one
# near-miss ("branched from main @ `a1fc502` (the docs landed directly on main
# first)") carries its SHA BEFORE the phrase and refers to something else. A
# claim without a stated target cannot be falsified against main at all, so it
# is deliberately not matched.
_MERGE_CLAIM = CONFIG.merge_claim


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
    """
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _MERGE_CLAIM.finditer(line):
            sha = match.group(1)
            if not _sha_exists(repo, sha):
                continue
            if not _is_merged(repo, sha):
                findings.append(Finding(
                    number, "false-merge-claim",
                    f"claims work merged to {TRUNK} at `{sha}`, but that commit "
                    f"is not an ancestor of {TRUNK}",
                ))
    return findings


# Keyed on OPERATIVE markers, not on path shape. Measured against the real
# corpus: of 88 path-shaped tokens across the two documents, 23 do not exist -
# and every one of those 23 is legitimate. `core/settings.py` appears under
# "Phase 8 - COMPLETE" describing that phase's layout (the file became a
# package); `core/updater.py` appears under deferred Phase 10 work and has
# never existed; the archive says "the old `modules/_base.py`", explicitly
# marking it deleted. A rule keyed on path shape would emit 23 findings, all
# false, and would be the first rule in this validator to break the guarantee
# that it never cries wolf.
#
# What is actually falsifiable is a path offered as a POINTER - "the plan is
# at X", "read X", "see X". If that path is missing, the reader following it
# gets nothing. All 21 operative pointers in the corpus currently resolve.
#
# Both separator styles are matched deliberately: the defect that motivated
# this rule was `C:\\Users\\...\\stateless-waddling-rossum.md` in CLAUDE.md, a
# Windows absolute path, which a forward-slash-only pattern would have missed.
_PATH_POINTER = CONFIG.path_pointer
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
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for raw in _PATH_POINTER.findall(line):
            target = Path(raw) if _ABSOLUTE.match(raw) else repo / raw
            if not target.exists():
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
            exists = _branch_exists(repo, branch)
            if exists and not _is_merged(repo, branch):
                continue  # genuinely still open: the claim is true
            line = text.count("\n", 0, start + match.start()) + 1
            if exists:
                detail = f"claims `{branch}` unmerged, but it is an ancestor of {TRUNK}"
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


def _strip_code_fences(text: str) -> str:
    """Blank out fenced code, preserving line numbers.

    A README demonstrating link syntax inside a code block is showing an
    example, not making a promise, and checking it would produce exactly the
    kind of false positive that gets a validator ignored.
    """
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else line)
    return "\n".join(out)


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
    for number, line in enumerate(_strip_code_fences(text).splitlines(), start=1):
        for raw in _MD_LINK.findall(line):
            if _EXTERNAL.match(raw) or raw.startswith("#"):
                continue
            target = raw.split("#", 1)[0]
            if not target:
                continue
            resolved = Path(target) if _ABSOLUTE.match(target) else base / target
            if resolved.exists():
                continue
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
    for number, line in enumerate(_strip_code_fences(text).splitlines(), start=1):
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


def validate_branch_mentions(repo: Path, text: str) -> list[Finding]:
    """A branch named in the newest entry that git has never heard of.

    Newest entry only, for the same reason live claims are: older entries name
    branches that were correct when written. Deletion after merge is normal and
    is never reported, because the merge commit still names the branch.
    """
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
            if _branch_exists(repo, branch) or _named_in_merge_history(repo, branch):
                continue
            line = text.count("\n", 0, start + match.start()) + 1
            findings.append(Finding(
                line, "unknown-branch",
                f"names `{branch}`, which does not exist and appears in no "
                f"merge commit (a typo, or work that was never integrated)",
            ))
    return findings


_RELEASE_TAG = CONFIG.release_tag


def validate_release_tags(repo: Path, text: str) -> list[Finding]:
    """"Released in v2.1" where no such tag exists, or it is not on trunk.

    Measured as absent from the corpus this was built against, so its
    denominator honestly reports 0 here. It is included for projects that keep
    a CHANGELOG, where this is the usual way a release is claimed, and it is
    falsifiable in exactly the way a merge claim is.
    """
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
            if not _is_merged(repo, f"refs/tags/{tag}"):
                findings.append(Finding(
                    number, "dead-release-tag",
                    f"tag `{tag}` exists but is not an ancestor of {TRUNK}",
                ))
    return findings


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
_MISSING_PATH = "__handoff_selftest_missing__.md"
_FAKE_BRANCH_LEAF = "handoff-selftest-no-such-branch"


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
    """Repoint a real merge claim at a commit that is NOT an ancestor of trunk.

    A nonexistent SHA will not do. The rule deliberately skips claims whose
    commit does not resolve, leaving those to `dead-sha`, so probing with zeros
    proves nothing and reports a working rule as broken. Found by running the
    selftest and watching this rule stay silent, which is the entire point of
    having one.
    """
    try:
        out = _git(repo, "rev-list", "--all", "--not", TRUNK, "-n", "1")
    except (subprocess.CalledProcessError, OSError):
        return None
    other = out.strip().splitlines()
    if not other:
        return None  # nothing off-trunk exists here to probe with
    return _sub_group(text, _MERGE_CLAIM, 1, other[0])


def _probe_pointer(repo: Path, text: str) -> str | None:
    return _sub_group(text, _PATH_POINTER, 1, _MISSING_PATH)


def _probe_tag(repo: Path, text: str) -> str | None:
    return _sub_group(text, _RELEASE_TAG, 1, "v0.0.0-handoff-selftest")


def _probe_md_link(repo: Path, text: str) -> str | None:
    for match in _MD_LINK.finditer(_strip_code_fences(text)):
        raw = match.group(1)
        if _EXTERNAL.match(raw) or raw.startswith("#"):
            continue
        start, end = match.span(1)
        return text[:start] + _MISSING_PATH + text[end:]
    return None


def _probe_md_anchor(repo: Path, text: str) -> str | None:
    for match in _MD_LINK.finditer(_strip_code_fences(text)):
        if not match.group(1).startswith("#"):
            continue
        start, end = match.span(1)
        return text[:start] + "#handoff-selftest-no-such-heading" + text[end:]
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
    branches_in_newest = len(_BRANCH_TOKEN.findall(newest)) if newest else 0
    links = [raw for line in _strip_code_fences(text).splitlines()
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
        falsifiable="is the named branch an ancestor of trunk, or gone entirely?",
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
        falsifiable="is the claimed commit an ancestor of trunk?",
        probe=_probe_merge,
    ),
    Rule(
        kind="dead-release-tag",
        check=validate_release_tags,
        scope="whole-file",
        in_archive=True,
        falsifiable="does the tag exist, and is it an ancestor of trunk?",
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
             has_entries: bool = True) -> list[Finding]:
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
    """
    findings: list[Finding] = []
    for rule in RULES:
        if (in_archive or not has_entries) and not rule.in_archive:
            continue
        findings += rule.check(repo, text)  # type: ignore[operator]
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handoff_collect", description="Collect and validate handoff facts."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--collect", action="store_true", help="emit bundle.json")
    mode.add_argument("--archive", action="store_true", help="split old entries out")
    mode.add_argument("--validate", metavar="FILE", help="validate a handoff document")
    mode.add_argument("--verify", action="store_true", help="validate the committed doc")
    mode.add_argument("--selftest", action="store_true",
                      help="corrupt one real claim per rule and confirm each fires")
    parser.add_argument("--out", metavar="PATH", help="bundle output path")
    parser.add_argument("--suite-json", metavar="PATH", help="reuse a completed suite run")
    parser.add_argument("--sha-map", metavar="PATH", help="filter-repo commit-map")
    parser.add_argument("--repo", metavar="PATH", default=str(REPO_ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    global _LINK_BASE
    parser = build_parser()
    args = parser.parse_args(argv)
    repo = Path(args.repo)
    # Configuration is read once at import, relative to THIS FILE, which is
    # correct when the tool sits at tools/ inside the repository it checks. Run
    # from anywhere else with --repo, git operations follow --repo while the
    # config does not, so .handoff.toml in the target is silently ignored. Say
    # so on stderr rather than let the two disagree quietly.
    # Narrowed to the case where a real config file is actually being ignored.
    # Warning whenever the paths merely differ would fire on every run against a
    # repository that has no config at all, where nothing is lost and the
    # defaults are what was wanted. A validator that cries wolf stops being read
    # applies to its own diagnostics too.
    ignored_config = repo / ".handoff.toml"
    if (repo.resolve() != REPO_ROOT.resolve() and ignored_config.is_file()
            and str(ignored_config) != CONFIG.source):
        print(f"NOTE: settings came from {CONFIG.source}, so {ignored_config} was "
              f"NOT read. Configuration loads relative to this script; install it "
              f"into that repository as tools/ for its own settings to apply.",
              file=sys.stderr)
    if args.selftest:
        target = repo / HANDOFF_DOC
        if not target.is_file():
            print(f"no such document: {target}")
            print(f"  handoff_doc is '{CONFIG.handoff_doc}', from {CONFIG.source}")
            return 1
        with open(target, encoding="utf-8", newline="") as fh:
            text = fh.read()
        _LINK_BASE = target.parent
        lines, fired, unprobeable = selftest(repo, text)
        print(f"selftest: probing {len(RULES)} rules against {HANDOFF_DOC}\n")
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
        out = Path(args.out) if args.out else repo / "handoff_bundle.json"
        with open(out, "w", encoding="utf-8", newline="") as fh:
            json.dump(bundle, fh, indent=2)
        if bundle["nothing_to_hand_off"]:
            print("nothing to hand off: no commits since the last handoff")
        print(out)
        return 0
    if args.archive:
        counts = archive(repo)
        print(f"retained={counts['retained']} archived={counts['archived']}")
        return 0
    if args.verify:
        args.validate = str(repo / HANDOFF_DOC)
    if args.validate == "":
        # M-a: argparse still counts --validate as "provided" (satisfying
        # the required mutually-exclusive group) even when its value is the
        # empty string, so this is a genuinely reachable state, not dead
        # code. It must not fall through to an implicit `None` return -
        # SystemExit(None) is exit code 0, a silent false success for a
        # nonsensical invocation.
        parser.error("--validate requires a non-empty FILE path")
    if args.validate:
        target = Path(args.validate)
        if not target.is_file():
            # A traceback here is a poor answer to a common situation: the
            # document lives elsewhere in this project, or the config points at
            # the wrong name. Say which file was expected and where it came from.
            print(f"no such document: {target}")
            print(f"  handoff_doc is '{CONFIG.handoff_doc}', from {CONFIG.source}")
            print("  set handoff_doc in .handoff.toml, or pass --validate <path>")
            return 1
        with open(target, encoding="utf-8", newline="") as fh:
            text = fh.read()
        # Relative links resolve against the document, not the repo root.
        _LINK_BASE = target.parent
        mapping = load_sha_map(args.sha_map) if args.sha_map else None
        if mapping is not None:
            text, changed = translate_shas(text, mapping)
            if changed:
                with open(target, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
                print(f"translated {changed} stale SHA reference(s) in {target}")
        findings = validate(repo, text)
        for finding in findings:
            print(finding.render())
        exit_code = 1 if findings else 0

        # The denominator. Without it a clean run and a run that checked nothing
        # print identically - the failure that recurred five times in one day.
        # A rule reporting 0 examined is either genuinely absent from this
        # document or broken, and the reader has to be able to tell.
        examined = count_examined(repo, text)
        summary = ", ".join(f"{kind} {n}" for kind, n in examined.items() if kind != "possible-secret")
        blind = [kind for kind, n in examined.items() if n == 0 and kind != "possible-secret"]
        print(f"checked {Path(args.validate).name}: {summary}"
              f" ({examined['possible-secret']} lines scanned for secrets)")
        if blind:
            print("  NOTE: these rules matched nothing at all - either this "
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
                    print(f"translated {archive_changed} stale SHA reference(s) in {ARCHIVE_DOC}")
            archive_findings = validate(repo, archive_text, in_archive=True)
            for finding in archive_findings:
                print(f"{ARCHIVE_DOC}: {finding.render()}")
            if archive_findings:
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
                print(f"{relative}: listed in extra_docs but does not exist")
                exit_code = 1
                continue
            with open(extra, encoding="utf-8", newline="") as fh:
                extra_text = fh.read()
            _LINK_BASE = extra.parent
            extra_findings = validate(repo, extra_text, has_entries=False)
            for finding in extra_findings:
                print(f"{relative}: {finding.render()}")
            examined_extra = count_examined(repo, extra_text)
            checked = ", ".join(f"{kind} {n}" for kind, n in examined_extra.items()
                                if kind != "possible-secret" and n)
            print(f"checked {relative}: {checked or 'nothing applicable'}")
            if extra_findings:
                exit_code = 1
        _LINK_BASE = None

        return exit_code
    # M-a: unreachable. The mutually-exclusive group is required, and every
    # member (collect, archive, verify, validate-non-empty) returns above;
    # validate-empty-string calls parser.error above, which exits. No state
    # argparse can produce falls through to here.
    raise AssertionError(f"unreachable: argparse guarantees one mode; got {args}")


if __name__ == "__main__":
    raise SystemExit(main())
