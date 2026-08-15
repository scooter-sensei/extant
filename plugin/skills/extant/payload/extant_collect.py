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
import os
import re
import subprocess
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator

# A shim older or newer than the package beside it is a half-finished upgrade.
# It has to fail here, loudly, because the alternative is running whichever
# version happened to survive and reporting nothing unusual.
#
# FIRST, before any other package import. See the note above: an import error
# from a stale package would otherwise mask this with a worse message.
_SHIM_VERSION = "0.22.0"
try:
    from extant import __version__ as _PACKAGE_VERSION
except ImportError:                                  # pragma: no cover
    from tools.extant import __version__ as _PACKAGE_VERSION
if _PACKAGE_VERSION != _SHIM_VERSION:
    raise SystemExit(
        f"extant: version mismatch - tools/extant_collect.py is {_SHIM_VERSION} "
        f"and tools/extant/ is {_PACKAGE_VERSION}. Re-run the installer with "
        f"--force to replace both.")

# This file is used two ways: imported as `tools.extant_collect` (tests, where
# the repo root is on sys.path) and run directly as a script (the hooks and the
# /extant command, where only tools/ is). The second form is the one that needs
# a fallback, so it comes second.
#
# The BARE name is tried first, and the order is load-bearing rather than
# stylistic. `extant/collect.py` imports `extant.config` directly, with no
# fallback; if this line preferred `tools.extant.config` the same file would be
# imported twice under two module names, and the shim's `Config` would then be
# a different class from the one the package builds and passes around. Two
# copies of a config layer is precisely the failure this refactor removes.
try:
    from extant.config import Config, load_config
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI tests
    # ModuleNotFoundError only, not the broader ImportError. extant/config.py
    # can EXIST and still fail this import - a syntax error, a bad import
    # inside it - and ImportError catches that case too, silently falling
    # back to tools.extant.config instead of raising. That fallback is the
    # two-config-modules confusion this import order exists to prevent
    # (see the comment above), arriving by a different door: not two
    # packages both present, but one broken and masked by the other.
    from tools.extant.config import Config, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every project-specific value is resolved once, here, from .extant.toml beside
# the repo root - falling back to defaults that reproduce this project's
# behaviour exactly, so a repo without a config file sees no change. The names
# below stay module-level constants because the whole module and its tests refer
# to them directly; only their SOURCE moved.
#
# Porting warning, stated at length in tools/extant/config.py: three of these
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


from extant.git import CountingGit, Git, SubprocessGit   # noqa: F401
#                      ^ re-exported: the tests that pin a memoisation contract
#                        install one of these in place of `_GIT` below.


# The MODULE, because the ten functions that take configuration are wrapped
# further down and a wrapper must look the name up on the module object at call
# time. Binding the functions here instead would freeze whichever object
# existed at import, which is the same rebinding trap this file's config
# comments describe one layer up.
from extant import collect as _collect

from extant.collect import (          # noqa: F401  (re-exported as they are:
    _CHECKED, _PYTEST_DURATION, _PYTEST_FAILED, _PYTEST_PASSED, _UNCHECKED,
    _VENV_LAYOUTS, changed_files,     # these take no configuration)
)

from extant.scope import Context, DocScope, RunScope

# The MODULE, for the reason `_collect` above is imported as one: the wrappers
# further down look each function up on it at call time, so a test may swap one
# there and see the shim's own callers go through the replacement.
from extant import refs as _refs

from extant.refs import (            # noqa: F401  (re-exported as they are:
    _INTEGRATION_NAMES, _SHA_SHAPE,  # neither reads any ambient state)
)


# The two objects that hold everything this module used to keep in twenty-six
# cache globals and three per-document ones. Their lifetimes are stated on the
# classes; what is stated here is why any module-level name survives at all.
#
# The rules are still functions taking `(repo, text)`. They carry no argument
# through which a scope could be handed to them, so the scope they read has to
# be reachable from the module - which is exactly the situation the old globals
# were in, and exactly what Task 9 ends by giving every rule a `Context`.
#
# What changed is the NUMBER of names and who resets them. `validate()` swaps
# ONE name and puts ONE name back, so a nested call cannot half-clear a caller's
# view: it builds its own object, and the outer one is untouched because it is a
# different object. The previous shape saved thirteen names and restored twelve,
# by hand, and the two bugs its comments recorded were both a name somebody
# forgot to add to one of the two lists.
#
# `_SCOPE` is never None. A rule called DIRECTLY, without going through
# validate(), reads this ambient scope and memoises into it, which is what the
# module globals did and what several tests assert by clearing one field and
# counting subprocesses. `dircache` is None here, so directory listings stay
# uncached outside a call - see the field's own comment.
_SCOPE = RunScope()
_DOC = DocScope()

# The third installed name, beside the two scopes and there for the same
# reason: a rule taking `(repo, text)` has no argument through which a Git
# could be handed to it. `Context.git` carries this same object, and Task 9
# makes that the route once the rules take a Context.
#
# Swapping ONE name is what lets a test see what the rules ask git without
# wrapping module functions by hand, and that is not a tidiness point. The
# hand-wrapping it replaces counted a soft call twice, because `_git_soft`
# delegates to `_git`; the same mistake put the spawn figure this budget
# defends 40 percent too high the first time it was measured.
_GIT: Git = SubprocessGit()


def _set_document(**changes: object) -> None:
    """Replace the current document, changing only what is named.

    A setter rather than three assignments at each call site, because the
    three values move together and the old code proved they do not stay
    together on their own: `--sweep` set two of them per file and restored
    them after the loop, so a rule that raised left the process resolving
    relative links against the last swept document's directory.
    """
    global _DOC
    _DOC = replace(_DOC, **changes)      # type: ignore[arg-type]


# The live Config, and the values the package's functions are handed. Assigned
# by `_apply_config` and nowhere else: a module-level `_ACTIVE =
# Config.build(CONFIG)` here would read CONFIG outside the single writer, which
# is both the bug this shape prevents and a test failure - the AST check in
# test_packaging.py::test_configuration_is_applied_in_exactly_one_place flags
# any module-level assignment whose value reads CONFIG, `_CONFIG_DERIVED`
# excepted. Declared None and filled in below.
_ACTIVE: Config | None = None

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
# The DERIVING moved to `Config.build`, which is now the one place a computed
# value is expressed at all; the reasons each of these takes the shape it does
# moved with it, to the fields in extant/config.py. What is left here is the
# mapping from this module's historical global names to those fields, and
# nothing else. Every entry reads the SAME built Config, so a global and
# `_ACTIVE` cannot describe different configurations.
_CONFIG_DERIVED: dict[str, Callable[[Config], object]] = {
    "PRIMARY_DOC": lambda c: c.primary_doc,
    "ARCHIVE_DOC": lambda c: c.archive_doc,
    "RETAIN_ENTRIES": lambda c: c.retain_entries,
    "TRUNK": lambda c: c.trunk,
    "_CONSISTENCY_TIMEOUT": lambda c: c.consistency_timeout,
    "_ARCHIVE_HEADER": lambda c: c.archive_header,
    "_BASE_HEADER": lambda c: c.base_header,
    "_PHASE_PREFIX": lambda c: c.phase_prefix,
    "_POINTER_PREFIX": lambda c: c.pointer_prefix,
    "_PHASE_TASK": lambda c: c.phase_task,
    "_PHASE_BARE": lambda c: c.phase_bare,
    "_TODO_MARKER": lambda c: c.todo_marker,
    "_LIVE_PHRASES": lambda c: c.live_phrases,
    "_BRANCH_TOKEN": lambda c: c.branch_token,
    "_PATH_POINTER": lambda c: c.path_pointer,
    "_MERGE_CLAIM": lambda c: c.merge_claim,
    "_RELEASE_TAG": lambda c: c.release_tag,
    "_RELEASE_CLAIMS_ARE_OURS": lambda c: c.release_claims_are_ours,
    "_SECTION_HEADER": lambda c: c.section_header,
    "_TODO_SCAN_EXCLUDED_FILES": lambda c: c.todo_excluded_files,
    "_TODO_SCAN_EXCLUDED_DIR_PREFIX": lambda c: c.todo_excluded_dir_prefix,
}


def _apply_config() -> None:
    """Set every configuration-derived global from the current CONFIG."""
    global _ACTIVE
    _ACTIVE = Config.build(CONFIG)
    # From `_ACTIVE`, not from a per-name rebuild: one build feeds both, so
    # there is no arrangement in which a global and `_ACTIVE` disagree.
    for name, build in _CONFIG_DERIVED.items():
        globals()[name] = build(_ACTIVE)


_apply_config()


# The package's collect functions take their configuration as an argument. These
# wrappers supply this module's, and exist because `tools/extant_collect.py` is
# the installed entry point: its call surface is what the suite and any adopter
# script already use, so changing arity here would be an API break in the one
# file whose job is compatibility.
#
# Each reads `_ACTIVE` or `CONFIG` at CALL time rather than closing over a value
# at definition time, so a `reload_config` between import and call is picked up.
# That is the same rebinding trap extant/collect.py's own comments describe.
#
# `_ACTIVE` where a value was DERIVED, `CONFIG` where it never was: nothing was
# ever derived from `suite_command`, `venv_python`, `plans_dir` or the three
# `suite_*` patterns, so they are read straight off the settings object. Adding
# them to Config would mean two names for one value.
#
# TRAP for a test written after this: patching a derived global on this module
# (`hc._PHASE_TASK`, `hc.TRUNK`, `hc.PRIMARY_DOC`, ...) no longer reaches these
# functions, because they read the built Config instead. Measured at 3df1245 by
# grepping tests/ (43 files) for both `monkeypatch.setattr(<alias>, "NAME"` and
# bare `<alias>.NAME =` assignment (aliases the suite imports this module
# under: hc, ec, h, extant_collect), against all 21 names in `_CONFIG_DERIVED`:
# 7 of the 21 are patched, at 28 sites in 8 files - TRUNK (4, all in
# test_multi_trunk.py), _BRANCH_TOKEN (4: test_added_rules.py x3 plus
# test_multi_trunk.py:238), _CONSISTENCY_TIMEOUT (3, test_consistency_timeout.py),
# _MERGE_CLAIM (1, test_multi_trunk.py:270), _RELEASE_TAG (4,
# test_release_conventions.py), _RELEASE_CLAIMS_ARE_OURS (11, across
# test_added_rules.py, test_caching.py, test_cache_lifetime.py,
# test_finding_subject.py and test_release_conventions.py), and
# _SECTION_HEADER (1, test_packaging.py:521). Nothing breaks today because
# every one of those 7 is read by a rule that still lives in this file -
# re-grep before trusting this count, because it stops being true as rules
# move to the package. A test needing a different value must call
# `reload_config`.
def parse_phase(subject: str) -> str | None:
    """Grouping key from a commit subject. See extant.collect.parse_phase."""
    return _collect.parse_phase(subject, _ACTIVE)


def find_boundary(repo: Path) -> str:
    """SHA of the last commit touching the status doc, else ''."""
    return _collect.find_boundary(repo, _ACTIVE)


def commits_since(repo: Path, boundary: str) -> list[dict[str, str]]:
    """Commits after `boundary` (exclusive), oldest first, phase-labelled."""
    return _collect.commits_since(repo, boundary, _ACTIVE)


def parse_pytest_summary(output: str) -> dict[str, object]:
    """Parse a suite summary using the configured patterns."""
    return _collect.parse_pytest_summary(output, CONFIG)


def scan_todos(repo: Path, boundary: str) -> list[dict[str, object]]:
    """TODO/FIXME/XXX markers in files changed since `boundary`."""
    return _collect.scan_todos(repo, boundary, _ACTIVE)


def _python_candidates(repo: Path) -> list[Path]:
    """Every interpreter location worth trying, most specific first."""
    return _collect._python_candidates(repo, CONFIG)


def find_python(repo: Path) -> Path | None:
    """The project's interpreter, or None."""
    return _collect.find_python(repo, CONFIG)


def run_suite(repo: Path, suite_json: str | None) -> dict[str, object]:
    """Suite result, either supplied or produced by a real run."""
    return _collect.run_suite(repo, suite_json, CONFIG)


def read_plan(repo: Path) -> dict[str, object]:
    """Completed vs remaining steps in the newest phase plan."""
    return _collect.read_plan(repo, CONFIG)


def collect(repo: Path, suite_json: str | None = None) -> dict[str, object]:
    """Assemble the full fact bundle. No prose, ever."""
    return _collect.collect(repo, suite_json, _ACTIVE, CONFIG)


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


def archive(repo: Path, retain: int | None = None) -> dict[str, int]:
    """Move all but the newest `retain` phase entries into the archive doc.

    `retain` defaults to None rather than to RETAIN_ENTRIES, because a
    default expression is evaluated once at import. Written the other way it
    froze whatever the module was configured with at import time, so
    `reload_config` could update the global and this function would go on
    using the stale one.

    Fails closed if any original line would be lost. This is the only
    irreversible file operation in the system, so conservation is asserted
    rather than trusted.
    """
    if retain is None:
        retain = RETAIN_ENTRIES
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
# I-1: SHA-shaped tokens written WITHOUT backticks. Anchored both sides with
# \b so a hex-looking run embedded inside a longer word (an identifier, a
# version tag) never matches - \w includes both hex letters and non-hex
# letters/digits/underscore, so there is no \b between e.g. "deadbeef" and a
# following "zz", and the whole run correctly fails to match at all rather
# than matching a truncated prefix of it.
# `(?<![#\w])` so a CSS colour is not read as a commit. `#646cffaa` is an
# eight-digit hex with alpha, and vitejs/vite carries it inside a drop-shadow
# in prose that no code fence covers. A `#` prefix means colour far more often
# than it means anything git would recognise, and a real SHA reference is never
# written that way.
_BARE_SHA_TOKEN = re.compile(r"(?<![#\w])[0-9a-f]{7,40}\b")


from extant.finding import Finding, Located  # noqa: F401


def _looks_like_sha(token: str) -> bool:
    """Shape test for a BACKTICKED token.

    A letter is required as well as a digit, matching the bare test. An
    all-digit run is a number: nlohmann/json documents the limits of its
    integer types and `9223372036854775807` is INT64_MAX, not a commit, but
    every character in it is valid hex.

    The cost is stated rather than hidden. A real seven-character SHA is
    all-digits about 4% of the time, and those go unchecked now. That is the
    better side of the trade - a missed check is silent, while flagging every
    large number in a document is the noise that gets a validator ignored.
    """
    return (bool(_SHA_SHAPE.match(token))
            and not _is_digest_length(token)
            and any(ch.isdigit() for ch in token)
            and any(ch.isalpha() for ch in token))


def _is_digest_length(token: str) -> bool:
    """Exactly 32 hex characters, which is a digest and not a commit.

    MD5 and a UUID with its dashes removed are both 32. Git abbreviations run
    7 to 12 in practice and a full object name is 40, so nothing legitimate
    sits at exactly 32 - and anything that did would RESOLVE, which produces
    no finding either way. Only unresolvable tokens are reported, and an
    unresolvable 32-character hex run is an API key, a content hash or an id.

    Measured on the held-out corpus: 45 findings, every one a documented
    example value. lobe-chat writes `Example: c55168be3874490ef0565d9779ecd5a6`
    beside an API key setting.
    """
    return len(token) == 32


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
    return (not _is_digest_length(token)
            and any(ch.isdigit() for ch in token)
            and any(ch.isalpha() for ch in token))


# Hex inside a URL belongs to somebody else's repository.
#
# `https://github.com/pyca/service-identity/blob/fa91bf55.../AI_POLICY.md` and
# `https://gist.github.com/user/d56764d7...` are a cross-repo permalink and a
# gist id. Neither is a commit THIS repository has any opinion about, and the
# core guarantee is that a rule only asks questions git can settle - which
# means git in this repo, about this repo.
#
# Measured, not supposed: of 301 bare-SHA findings across rust-lang/rfcs,
# requests and httpx, 287 sat inside a URL. Left in, the rule reported a wall
# of findings on every project that links to another project's source, which
# is most of them.
_URL = re.compile(r"(?:https?://|ftp://|git@)\S+", re.I)
# A UUID is not a commit, and it is made of pieces that look like one.
#
# `ContentId: dd7207b0-cf8b-4ed6-8c75-941834179dca` sits in the YAML
# frontmatter of every page in microsoft/vscode-docs. Split on the hyphens, the
# 8- and 12-character groups are valid hex with both a letter and a digit, so
# each was read as a short SHA that does not resolve.
#
# 750 of the 789 bare-SHA findings across 40 repositories were fragments of
# one, every one in that repository. Matched whole and skipped whole, because
# skipping the groups individually would also silence a genuine SHA that
# happened to sit beside a hyphen.
# The left edge is a negative lookbehind for HEX, not a word boundary.
#
# `\b` fails between an underscore and a hex digit, because both are word
# characters, so a UUID embedded in an identifier was not recognised as one:
# `conversation_f43eb21b-84cb-49e7-90fb-56595df594e6` slipped past and its
# trailing 12-character field was read as a short SHA. Four findings in one
# agent's debug log. A real abbreviated SHA is not preceded by another hex
# character, so this costs nothing it used to catch.
_UUID = re.compile(
    r"(?<![0-9a-fA-F])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
    r"-[0-9a-f]{12}\b", re.I)
# A hex run inside a FILENAME is part of the filename.
#
# Documentation platforms mint asset names by prefixing a content hash:
# `<ClickableImage src="/img/83f686b-Pipeline_Illustrations_1_1.png" />`. The
# hash is seven valid hex characters with a word boundary on each side, so it
# read as an abbreviated commit that does not resolve. Measured on the
# held-out corpus: 144 findings, all of them in one documentation site, none
# of them a commit.
#
# Matches the whole path-like run so the span covers any hex inside it, which
# is why this is a skip SPAN rather than a token test.
# The lookbehind and the length bound are both load-bearing, not tidiness.
# Written first as `[\w./~-]*\.(ext)`, this took 322 SECONDS on one
# 120,000-character line: the unbounded run restarts at every position, and a
# long path or a base64 data URI is quadratic. The longest markdown line in
# the earlier corpus was 123,427 characters, so that was a hang waiting for a
# document rather than a theoretical concern. Anchoring to the START of a
# path-like run and bounding its length brings the same line under 20 ms.
_ASSET_PATH = re.compile(
    r"(?<![\w./~-])[\w./~-]{0,200}\.(?:png|jpe?g|gif|svg|webp|avif|ico|bmp|"
    r"pdf|mp4|webm|mov|woff2?|ttf|eot|css|js|mjs|map|zip|tar|gz|whl)\b", re.I)
# A ref pinned to a repository that is not this one.
#
# `uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd` pins a
# workflow to a commit in `actions/checkout`. The `owner/repo@` prefix names
# whose commit it is, and it is not this repository's, so this repository
# cannot answer for it - the same reasoning `_URL` already applies to a
# cross-repo permalink. 14 findings on the held-out corpus, every one an
# action pinned by SHA, which is the practice security guidance asks for.
_PINNED_REF = re.compile(r"(?<![\w./-])[\w.-]+/[\w.-]+@[0-9a-f]{7,40}\b", re.I)


def _spans_overlap(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(s < end and start < e for s, e in others)


# A backticked SHA that is the VISIBLE TEXT of a link to somebody's commit.
#
# The changesets tool writes release notes this way, and a monorepo that
# absorbed another project keeps citing the original:
#
#     - [#159](https://github.com/withastro/adapters/pull/159)
#       [`adb8bf2a4caeead9a1a255740c7abe8666a6f852`](https://github.com/withastro/adapters/commit/adb8bf2a...)
#
# The URL states whose commit it is. `_URL` already drops a bare hex run
# inside a link target for exactly this reason - "hex inside a URL belongs to
# somebody else's repository" - but the backticked path never had the
# equivalent, so the same SHA was checked against the wrong repository purely
# because it was also written as link text. 192 findings on the held-out
# corpus, 162 of them in one changelog tree.
#
# Deliberately does NOT compare owners. Neither does the `_URL` rule it
# mirrors, and it cannot: a document does not reliably state which repository
# it is in. A link to this repository's own commit is unaffected in practice,
# because a SHA that resolves produces no finding to suppress.
_LINKED_SHA = re.compile(
    r"\[\s*`([0-9a-fA-F]{6,40})`\s*\]\(\s*[^)\s]*?"
    r"/(?:commit|commits|blob|tree|pull|compare)/[^)\s]*\)", re.I)


def find_sha_candidates(text: str) -> list[tuple[int, str]]:
    """(line number, token) for every backticked SHA-shaped token."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        qualified = [m.span(1) for m in _LINKED_SHA.finditer(line)]
        for match in _BACKTICKED.finditer(line):
            if _spans_overlap(match.span(1), qualified):
                continue
            token = match.group(1)
            if _looks_like_sha(token):
                out.append((number, token))
    return out


# Same idiom and same reasoning as `_STRIPPED` above: keyed on object IDENTITY,
# so a different string simply misses and no lifecycle is needed. Added when the
# sweep began reporting a per-rule denominator, which made `count_examined` a
# second caller for the same document - this function and `_line_pointer_sites`
# were then the two most expensive things in a sweep, each computed twice over
# identical bytes. Measured on pytest's 308 documents: 617 calls, 1.20s.
_BARE_SHAS: tuple[str, list[tuple[int, str]]] | None = None


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
    global _BARE_SHAS
    if _BARE_SHAS is not None and _BARE_SHAS[0] is text:
        return _BARE_SHAS[1]
    result = _find_bare_sha_candidates(text)
    _BARE_SHAS = (text, result)
    return result


def _find_bare_sha_candidates(text: str) -> list[tuple[int, str]]:
    """The scan itself. Separate only so the cache above stays readable."""
    out: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        skip_spans = [m.span() for m in _BACKTICKED.finditer(line)]
        skip_spans += [m.span() for m in _URL.finditer(line)]
        skip_spans += [m.span() for m in _UUID.finditer(line)]
        skip_spans += [m.span() for m in _ASSET_PATH.finditer(line)]
        skip_spans += [m.span() for m in _PINNED_REF.finditer(line)]
        for match in _BARE_SHA_TOKEN.finditer(line):
            if _spans_overlap(match.span(), skip_spans):
                continue
            token = match.group(0)
            if _looks_like_bare_sha(token):
                out.append((number, token))
    return out


def _document_sha_tokens(prose: str) -> list[str]:
    """Every SHA-shaped token in this document that a rule will ask git about.

    The UNION, gathered once so a document costs ONE `cat-file --batch-check`
    rather than one per rule that reads SHAs. Two rules read them:
    `validate_references`, for its backticked and bare candidates, and
    `validate_merge_claims`, for the commit each claim names.

    GATHERING THE TOKENS IS NOT GATHERING THE CANDIDATES, and that distinction
    is the whole safety argument. Each rule still finds its own candidates and
    decides its own findings from them; what is shared is only the question put
    to git, which is per token and gives the same answer whoever asks. A larger
    batch cannot change any token's answer, so nothing here can move a finding.

    Measured on this repository's own document before it existed: 29 tokens in
    one batch and 2 in another, overlapping in 1. A per-token memo alone would
    therefore have left two subprocesses, because the odd token out is real
    rather than an artefact - `PR #499 merged into main at 6ff1f4ac` backticks
    the whole phrase, so the commit inside it is neither a backticked TOKEN nor
    a bare one, and only the claim rule ever sees it.

    Takes PROSE, because both callers blank code blocks before reading and
    passing raw text here would resolve tokens from fences that no rule reads.
    """
    tokens = [token for _number, token in find_sha_candidates(prose)]
    tokens += [token for _number, token in find_bare_sha_candidates(prose)]
    tokens += [sha for _number, _ref, sha in _merge_claims(prose)]
    return tokens


def _document_shas(repo: Path, prose: str) -> set[str]:
    """Which of this document's SHA-shaped tokens resolve to commits."""
    return _resolve_shas(repo, _document_sha_tokens(prose))


def _merge_claims(prose: str) -> list[tuple[int, str, str]]:
    """(line, ref, sha) for every merge claim, ref as written.

    Split out of `validate_merge_claims` so `_document_sha_tokens` can see the
    commits a claim names without reimplementing how a claim is found. One
    reader of `_MERGE_CLAIM`, so a project that customises the pattern cannot
    end up with the batch and the rule disagreeing about what a claim is.

    A two-group pattern means (ref, sha). A one-group pattern is the older
    contract and still means (sha), checked against trunk exactly as before.
    """
    named = _MERGE_CLAIM.groups >= 2
    claims: list[tuple[int, str, str]] = []
    for number, line in enumerate(prose.splitlines(), start=1):
        for match in _MERGE_CLAIM.finditer(line):
            if named:
                # The pattern keeps any backticks so the rule can tell a
                # deliberate ref from a word of prose. See _claimed_ref.
                claims.append((number, match.group(1), match.group(2)))
            else:
                claims.append((number, TRUNK, match.group(1)))
    return claims


# A changesets release note. The id is minted by the tool, not by git.
#
#     - 8b82179: Fix auto imports and code actions not working
#
# It is hex-shaped, seven characters, and resolves to nothing because it never
# named a commit. 50 findings on the held-out corpus, all in one project's
# generated changelogs.
#
# The line shape ALONE is not enough - `- abc1234: fixed the parser` is how a
# person writes a real commit reference - so this is gated on the repository
# actually using the tool, which is a directory that either exists or does not.
_CHANGESET_ENTRY = re.compile(r"^\s*[-*]\s+[0-9a-f]{6,40}:\s")


def _uses_changesets(repo: Path) -> bool:
    """Does this repository mint release notes with changesets?"""
    key = str(repo)
    if key not in _SCOPE.changesets:
        _SCOPE.changesets[key] = (repo / ".changeset").is_dir()
    return _SCOPE.changesets[key]


def validate_references(repo: Path, text: str) -> list[Finding]:
    """Every referenced SHA must still resolve; a dead reference is useless."""
    # Claims inside code are examples, not promises. See _prose.
    text = _prose(text)
    findings: list[Finding] = []
    backticked = find_sha_candidates(text)
    bare = find_bare_sha_candidates(text)
    # The document's tokens rather than only this rule's two lists, so the
    # whole document costs one batch. Only `backticked` and `bare` decide
    # anything below; see `_document_sha_tokens` for why a wider batch cannot
    # move a finding.
    alive = _document_shas(repo, text)
    for number, token in backticked:
        if token not in alive:
            findings.append(
                Finding(number, "dead-sha",
                        f"`{token}` does not resolve in this repo",
                        subject=token)
            )
    # I-1(b): a bare token that RESOLVES is merely unstyled, not broken -
    # flagging it would be noise, so only a bare token that fails to resolve
    # is worth a finding.
    lines = text.splitlines()
    changesets = _uses_changesets(repo)
    for number, token in bare:
        if token in alive:
            continue
        line = lines[number - 1] if 0 < number <= len(lines) else ""
        if changesets and _CHANGESET_ENTRY.match(line):
            continue
        findings.append(Finding(
            number, "bare-dead-sha",
            f"`{token}` is un-backticked and does not resolve; "
            "backtick real SHAs so they are checked",
            subject=token,
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


# The git questions the rules ask, answered by extant/refs.py now. These
# wrappers supply the Context the package takes and keep this module's call
# surface at `(repo, ...)`, which is what every rule below and the suite
# already use; Task 9 hands the rules a Context of their own and Task 10
# deletes these along with the rest of the shim.
#
# `_ctx` reads `_ACTIVE`, `_SCOPE`, `_DOC` and `_GIT` at CALL time rather than
# closing over them, and that is load-bearing rather than stylistic:
# `validate()` REBINDS `_SCOPE` and `_DOC` for the duration of a call and
# `run_scope()` rebinds `_SCOPE` for the duration of a sweep. A Context built
# once at import would pin whichever objects existed then, which is the
# memoisation-lifetime bug extant/scope.py exists to make unrepresentable,
# reintroduced one layer up.
#
# TRAP, and it is the one extant/collect.py's own wrapper block warned would
# arrive here: patching a CONFIG-DERIVED global on this module no longer
# reaches the functions below, because they read the built Config through
# `ctx.config`. Re-measured for this move against the seven derived names the
# suite patches - the re-grep that comment asks for - exactly one has a reader
# that moved: `TRUNK`, read by `integration_refs`, patched at four sites in
# tests/test_multi_trunk.py. All four still pass, and not because the patch
# still works: the gitflow fixture carries both `main` and `develop`, so
# `_INTEGRATION_NAMES` finds the same set whichever name seeds it and only the
# ORDER differs. That is precisely why it is written down here instead of left
# to be discovered. A test that needs a different trunk must call
# `reload_config`.
def _ctx(repo: Path) -> Context:
    """This module's ambient state, as the object the package takes."""
    return Context(config=_ACTIVE, run=_SCOPE, doc=_DOC, repo=repo, git=_GIT)


def _sha_exists(repo: Path, sha: str) -> bool:
    """Does this token name a commit here? See extant.refs._sha_exists."""
    return _refs._sha_exists(_ctx(repo), sha)


def _resolve_shas(repo: Path, tokens: list[str]) -> set[str]:
    """Which of `tokens` resolve to commits, in ONE git call instead of N."""
    return _refs.resolve_shas(_ctx(repo), tokens)


def _branch_exists(repo: Path, branch: str) -> bool:
    """Does this branch resolve here?"""
    return _refs._branch_exists(_ctx(repo), branch)


def _ancestor_index(repo: Path, ref: str) -> dict[str, list[str]] | None:
    """Every commit reachable from `ref`, indexed by 7-character prefix."""
    return _refs._ancestor_index(_ctx(repo), ref)


def _reachable_from(repo: Path, rev: str, ref: str) -> bool:
    """Is `rev` an ancestor of `ref`?"""
    return _refs._reachable_from(_ctx(repo), rev, ref)


def _resolve_ref(repo: Path, ref: str) -> str | None:
    """The full commit SHA a ref points at, or None."""
    return _refs._resolve_ref(_ctx(repo), ref)


def _ref_table(repo: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Every local branch and tag, by short name, annotated tags peeled."""
    return _refs._ref_table(_ctx(repo))


def _integration_refs(repo: Path) -> list[str]:
    """The branches this repository integrates work INTO."""
    return _refs.integration_refs(_ctx(repo))


def _integrated_by(repo: Path, rev: str, *, exclude: str = "") -> list[str]:
    """Which integration refs contain `rev`."""
    return _refs.integrated_by(_ctx(repo), rev, exclude=exclude)


def _rename_map(repo: Path) -> dict[str, str]:
    """Recent renames, old path to new."""
    return _refs._rename_map(_ctx(repo))


def _renamed_to(repo: Path, missing: str) -> str | None:
    """Where git says a now-missing path ended up, or None."""
    return _refs.renamed_to(_ctx(repo), missing)


def _named_in_merge_history(repo: Path, branch: str) -> bool:
    """Did a merge commit ever mention this branch?"""
    return _refs._named_in_merge_history(_ctx(repo), branch)


def tracked_markdown(repo: Path) -> list[str]:
    """Every markdown file git tracks, repo-relative, sorted."""
    return _refs.tracked_markdown(_ctx(repo))


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
    claims = _merge_claims(text)
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
    #
    # The DOCUMENT's tokens, not this rule's, and only for the git question -
    # the claims above are still this rule's own and decide every finding
    # below. A wider batch cannot move any token's answer, and asking for the
    # document's union is what makes the whole document cost one batch instead
    # of one per rule. See `_document_sha_tokens`.
    resolved = _document_shas(repo, text)
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
            if not _integration_refs(repo):
                continue        # no integration branch here to have taken it
            if not _integrated_by(repo, sha):
                findings.append(Finding(
                    number, "false-merge-claim",
                    f"claims work merged to `{ref}` at `{sha}`, but this "
                    f"repository has no such branch and that commit is on no "
                    f"integration branch either",
                    subject=sha,
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
                subject=sha,
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
# A backticked path that is the VISIBLE TEXT of a markdown link.
#
#     read [`PULL_REQUEST_TEMPLATE.md`](./.github/PULL_REQUEST_TEMPLATE.md)
#
# The text names the file; the URL says where it is. This rule read the text
# as a pointer, resolved it against the repository root, and reported a link
# that works. Same shape as `_LINKED_SHA` one rule over, and settled the same
# way: the link BESIDE it is the authority, so if that resolves there is
# nothing to report.
#
# Measured on the held-out corpus: 4 findings have this shape and the URL
# resolves in 3. The fourth is Roo-Code citing an `ADDING-EVALS.md` that is
# absent both ways, and it is still reported.
_LINKED_PATH = re.compile(r"\[\s*`([^`]+)`\s*\]\(\s*([^)\s]+)")


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
    # Resolved from the repository root AND from the directory holding the
    # document, because both are how people write these.
    #
    # The rule used to try the root alone. A nested `SKILL.md` saying "see
    # `references/cli.md`" was reported dead while the file sat in the very
    # next directory entry, because `references/cli.md` does not exist at the
    # root. 61 findings on the held-out corpus, every one of them a pointer a
    # reader can follow, and `validate_md_links` two rules down had resolved
    # relative to the document all along - the inconsistency was the bug.
    #
    # Strictly narrowing: a pointer resolving either way is a working
    # pointer, so nothing that was a real defect stops being one.
    base = _DOC.link_base or repo
    for number, line in enumerate(text.splitlines(), start=1):
        linked = {text_part.strip(): url
                  for text_part, url in _LINKED_PATH.findall(line)}
        for raw in _PATH_POINTER.findall(line):
            url = linked.get(raw)
            if url is not None and not _EXTERNAL.match(url):
                target = _percent_decoded(url.split("#")[0])
                if (_resolve_reference(repo, base, target)[0]
                        or _resolve_reference(repo, repo, target.lstrip("/"))[0]):
                    continue
            exists, actual_case = _resolve_reference(repo, repo, raw)
            if not exists and base != repo:
                beside, beside_case = _resolve_reference(repo, base, raw)
                if beside:
                    continue
                actual_case = actual_case or beside_case
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
                findings.append(Finding(number, "dead-path-pointer", detail,
                                        subject=raw))
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
            findings.append(Finding(line, "stale-live-claim", detail,
                                    subject=branch))
    return findings


# Markdown link syntax is fixed by the format, not by any project's habits, so
# unlike the prose patterns this one is not configurable. There is no corpus to
# measure: `[text](target)` means the same thing everywhere.
_MD_LINK = re.compile(r"\[[^\]]*\]\(\s*([^)\s]+?)\s*\)")
# ANY URI scheme, not an enumerated few. phoenixframework/phoenix links to
# `irc://irc.libera.chat/elixir`, and a named list will always be missing the
# next scheme somebody uses - slack:, vscode:, ssh:, matrix:. Two or more
# characters before the colon so a Windows drive letter is not mistaken for
# one; a relative path does not carry a colon before its first slash.
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]+:|//)", re.I)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
# A heading nested inside a list item. CommonMark renders `- ### Title` as a
# real h3 and gives it an id, which is how a README builds an indented table
# of contents:
#
#     - ### [Getting the project](#getting-the-project-1)
#
# Unity's BossRoom does exactly that, and because the nested copy was invisible
# here the later `## Getting the project` never looked like a repeat, so the
# `-1` a renderer appends was never offered. Twelve findings, and every anchor
# finding that Unity project had.
_NESTED_HEADING = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+#{1,6}\s+(.+?)\s*#*$")
_EXPLICIT_ANCHOR = re.compile(r"""(?:name|id)\s*=\s*["']([^"']+)["']""")
# The attribute syntax pandoc, kramdown and PHP Markdown Extra use to name a
# heading or a span outright: `## Template {#type-template}` and
# `[Inlines]{#inlines-filter}`. It overrides whatever the text would slug to,
# so a document using it has anchors that no amount of slug guessing will
# reach. pandoc's own doc/lua-filters.md carries 368 and accounted for 120 of
# its 149 findings - the largest single class left in a 26-repository corpus.
#
# The JSX-comment spelling is the same declaration with MDX's parser in mind:
# `### \`baseUrl\` {/* #baseUrl */}`. MDX v3 reads a bare `{#id}` as a JSX
# expression, so Docusaurus wraps it in a comment. Same intent, same override,
# and it accounted for most of Docusaurus's 1,078 anchor findings once `.mdx`
# files were swept at all.
_ATTR_ANCHOR = re.compile(r"\{\s*(?:/\*)?\s*#([^\s}*]+)")
# MyST names a target on its own line, immediately before what it labels:
#
#     (a11y:contribute)=
#     ## Contributing
#
# Same idea as the attribute syntax and equally explicit, but it sits outside
# the thing it names, so nothing that reads headings would ever see it.
# executablebooks/mystmd links to `#a11y:contribute` throughout, and those
# labels were 248 of its 275 findings.
_MYST_TARGET = re.compile(r"^\(([^)\s]+)\)=\s*$", re.MULTILINE)
# A directive option naming its block. MyST writes `:label:` and Sphinx writes
# `:name:` inside a fenced directive:
#
#     ```{list-table} Affiliations
#     :label: table-frontmatter-affiliations
#     ```
#
# Same explicit naming as `(target)=`, in the third of three places MyST allows
# it. mystmd links to `#table-frontmatter-affiliations` from another document,
# and the label existed the whole time - in a directive option nothing read.
_DIRECTIVE_LABEL = re.compile(r"^\s*:(?:label|name):\s*(\S+)\s*$", re.MULTILINE)
_FENCE = re.compile(r"^\s*(```|~~~)")

# The three per-document values - the directory a relative link resolves
# against, the document's own path, and its markup language - are one object
# now. `DocScope` in extant/scope.py carries the reason each of them exists,
# which is the same reason in all three cases: a rule signature is
# (repo, text) and can carry none of them.
def _current_document() -> str | None:
    """The document under validation, as a forward-slashed relative path."""
    return _DOC.doc_path.replace("\\", "/") if _DOC.doc_path else None


# Rules whose syntax is markdown's alone. Skipped outside it rather than
# tuned, because there is no version of a markdown link regex that is correct
# on a language which has no markdown links.
_MARKDOWN_ONLY = {"dead-md-link", "dead-md-anchor"}


def _format_for(path: str) -> str:
    """Which markup language a filename is written in."""
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return "rst" if suffix == "rst" else "markdown"


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
    if _DOC.doc_format == "rst":
        return _blank_rst(text, inline=inline)
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


# reStructuredText marks code three ways, and none of them is a fence.
_RST_DIRECTIVE = re.compile(r"^\s*\.\.\s+(?:code-block|code|literalinclude|"
                            r"sourcecode|parsed-literal|math)::")
_RST_LITERAL_INTRO = re.compile(r"::\s*$")
_RST_DOCTEST = re.compile(r"^\s*(?:>>>|\.\.\.)\s")
_RST_INLINE = re.compile(r"``[^`]*``|`[^`]*`(?:_+)?")


def _blank_rst(text: str, *, inline: bool) -> str:
    """The same job for reStructuredText, whose code blocks are indentation.

    A literal block opens with a line ending in `::` or a `.. code-block::`
    directive and runs until the indentation returns; a doctest opens with
    `>>>`. None of that is a fence, so the markdown stripper left every example
    in place and the rules read Python as prose - numpy's
    `float64('1e10000')` became a dead commit, and its
    `np.dtype[mp.mpf](dps=100)` became a dead link.

    Blanked with spaces like the markdown path, so line numbers and offsets
    survive for every rule that shares this.
    """
    lines = text.splitlines()
    out: list[str] = []
    block_indent: int | None = None
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            # A blank line does not end a literal block; a return to the
            # opening indentation does.
            if not stripped or indent > block_indent:
                out.append(" " * len(line))
                continue
            block_indent = None
        if _RST_DOCTEST.match(line):
            out.append(" " * len(line))
            continue
        if _RST_DIRECTIVE.match(line) or _RST_LITERAL_INTRO.search(line):
            block_indent = indent
            out.append(" " * len(line))
            continue
        out.append(_RST_INLINE.sub(lambda m: " " * len(m.group(0)), line)
                   if inline else line)
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


def _unique_basename(repo: Path, target: str) -> bool:
    """Does exactly one tracked markdown file carry this basename?

    Exactly one, never "at least one". Two files called `index.md` say nothing
    about which was meant, and guessing would trade a false positive for a
    silent wrong answer, which is worse.
    """
    name = Path(target).name.lower()
    if not name:
        return False
    key = str(repo)
    if key not in _SCOPE.basenames:
        counts: dict[str, dict[str, int]] = {}
        try:
            for path in tracked_markdown(repo):
                leaf = path.rsplit("/", 1)[-1].lower()
                tree = _translation_tree(repo, path)
                counts.setdefault(tree, {})
                counts[tree][leaf] = counts[tree].get(leaf, 0) + 1
        except (OSError, subprocess.CalledProcessError):
            counts = {}
        _SCOPE.basenames[key] = counts
    # Counted WITHIN the citing document's translation tree, not across the
    # whole repository.
    #
    # A bare-name match is a claim that the generator resolves this name from
    # anywhere, and it does - within one site. fastapi builds a separate site
    # per language and keeps `newsletter.md` only in English, so counting
    # repository-wide made every translated page's link to it "resolve"
    # against a file in a different language's site. That silenced 68 real
    # defects across ten languages the moment fastapi was detected at all.
    #
    # A repository with no translation trees has one bucket and behaves
    # exactly as before, which is what keeps ExDoc's flat namespace working.
    here = _translation_tree(repo, _current_document() or "")
    return _SCOPE.basenames[key].get(here, {}).get(name, 0) == 1

# A directory named for a language: `en`, `de`, `pt`, `zh-hant`, `pt_BR`.
_LANGUAGE_DIR = re.compile(r"^[a-z]{2,3}(?:[-_][A-Za-z]{2,4})?$")


def _translation_tree(repo: Path, path: str) -> str:
    """Which parallel language tree this path belongs to, or "" for none.

    Recognised by SIBLINGS, not by the name alone. `docs/es/` is Spanish
    because `docs/de/`, `docs/fr/` and eleven more sit beside it; a lone
    `docs/id/` would be an "id" directory and is left alone. Three or more
    language-shaped siblings is the threshold, which no repository reaches by
    accident.
    """
    parts = path.replace("\\", "/").split("/")
    for index, part in enumerate(parts[:-1]):
        if not _LANGUAGE_DIR.match(part):
            continue
        parent = "/".join(parts[:index])
        key = (str(repo), parent)
        if key not in _SCOPE.language_siblings:
            directory = repo / parent if parent else repo
            try:
                siblings = sum(1 for child in directory.iterdir()
                               if child.is_dir()
                               and _LANGUAGE_DIR.match(child.name))
            except OSError:
                siblings = 0
            _SCOPE.language_siblings[key] = siblings
        if _SCOPE.language_siblings[key] >= 3:
            return "/".join(parts[:index + 1])
    return ""


# `07-misc`, `04-custom-elements.md`, `1.2-intro.md`: an ordering prefix a
# docs generator strips when it builds the route.
_ORDER_PREFIX = re.compile(r"^\d+(?:\.\d+)*[-_.]")


def _route_name(segment: str) -> str:
    """A path segment with its ordering prefix and `.md` suffix removed."""
    stem = re.sub(r"\.(?:md|markdown|mdx)$", "", segment, flags=re.I)
    return _ORDER_PREFIX.sub("", stem).lower()


def _numbered_document(repo: Path, target: str) -> bool:
    """Does exactly one tracked document answer to this route once prefixes go?

    Compares the WHOLE path segment by segment, not just the basename, so
    `guides/setup` and `reference/setup` stay distinguishable. A bare
    `custom-elements` matches `documentation/docs/07-misc/04-custom-elements.md`
    on its last segment; a two-segment target must match the last two.

    Exactly one match, never "at least one", for the reason
    `_unique_basename` gives: guessing between candidates trades a false
    positive for a silently wrong answer.
    """
    wanted = [_route_name(part) for part in target.strip("/").split("/") if part]
    if not wanted or not wanted[-1]:
        return False
    key = str(repo)
    if key not in _SCOPE.routes:
        routes: dict[str, int] = {}
        try:
            for path in tracked_markdown(repo):
                segments = path.split("/")
                # ONLY documents that actually carry an ordering prefix are
                # indexed. Without that condition this becomes
                # `_unique_basename` with the generator gate removed, and
                # would silence a link to `foo` anywhere `foo.md` happens to
                # exist in an unrelated directory. The prefix is the evidence
                # that something strips it, so no prefix, no claim.
                if not any(_ORDER_PREFIX.match(s) for s in segments):
                    continue
                parts = [_route_name(s) for s in segments]
                # Index every trailing run, so a target of any depth is one
                # dictionary hit rather than a scan.
                for depth in range(1, min(len(parts), _ROUTE_DEPTH) + 1):
                    suffix = "/".join(parts[-depth:])
                    routes[suffix] = routes.get(suffix, 0) + 1
        except (OSError, subprocess.CalledProcessError):
            routes = {}
        _SCOPE.routes[key] = routes
    return _SCOPE.routes[key].get("/".join(wanted[-_ROUTE_DEPTH:]), 0) == 1


_ROUTE_DEPTH = 4


def _percent_decoded(target: str) -> str:
    """A link target with percent-escapes resolved, or unchanged if it has none.

    Left alone when there is nothing to decode, so a path containing a literal
    `%` is never rewritten into something else.
    """
    if "%" not in target:
        return target
    from urllib.parse import unquote
    return unquote(target)


def _heading_text(title: str) -> str:
    """Heading text as rendered: link syntax reduced to its text, code unwrapped.

    A heading may itself be a link. Alamofire's changelog writes
    `## [5.12.0](https://github.com/Alamofire/Alamofire/releases/tag/5.12.0)`
    and indexes it as `#5120`, because a renderer slugs what the reader SEES -
    `5.12.0` - and drops the destination. Folding the URL in instead produced
    `1-0-0-https-github-com-alamofire-...` and called all 119 of that
    repository's changelog anchors dead.
    """
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title.strip())
    return re.sub(r"`([^`]*)`", r"\1", text).lower()


def _without_tags(title: str) -> str:
    """The same heading with angle-bracket markup removed.

    Offered ALONGSIDE the untouched spelling, never instead of it, because the
    two conventions collide head-on and both are real.

    vitejs/vite writes `## resolve.conditions <NonInheritBadge />` and links to
    it as `#resolve-conditions`, so the component tag has to go. Prometheus
    writes `### \\`<relabel_config>\\`` - a YAML placeholder that IS the heading
    - and links to it as `#relabel_config`, so the angle brackets have to stay.
    Stripping unconditionally fixed vite's two and broke fifty of Prometheus's,
    which is the worse trade by far and is why this is additive.
    """
    return re.sub(r"<[^>]*>", " ", title)


def _slug(title: str) -> str:
    """Approximate the heading-to-anchor conversion used by common renderers.

    Each space becomes its own dash rather than a run collapsing to one, which
    is what GitHub does: `### Serialization / Deserialization` drops the slash
    and keeps both surrounding spaces, so the anchor is
    `serialization--deserialization` with two. Collapsing produced one dash and
    called nlohmann/json's own README link dead.
    """
    text = re.sub(r"[^\w\s-]", "", _heading_text(title))
    return re.sub(r"\s", "-", text).strip("-")


def _slug_keeping_edges(title: str) -> str:
    """The same slug with a leading or trailing dash LEFT ON.

    GitHub does not trim the edges, and a heading that opens with an emoji
    therefore anchors with a dash in front: `## <emoji> Component structure`
    is reachable as `#-component-structure`, because the emoji is dropped and
    the space after it still becomes a dash. AutoGPT's contributing guide
    links to its own sections that way and every link works.

    Stripping produced `component-structure`, which matched nothing the
    document offered, so 58 working links on the held-out corpus were reported
    dead. Added as an extra spelling rather than by changing `_slug`, because
    both are real: renderers that DO trim exist, and a fragment matching
    neither spelling is still dead.
    """
    text = re.sub(r"[^\w\s-]", "", _heading_text(title))
    untrimmed = re.sub(r"\s", "-", text)
    # Contributes ONLY the spelling trimming would lose, and nothing when
    # there is no edge to keep.
    #
    # Returning the trimmed form too would duplicate `_slug` and mask it. It
    # did: the mutation that stops `_slug` stripping punctuation SURVIVED
    # once this function existed, because `## build.target` still offered
    # `buildtarget` from here after `_slug` stopped offering it. A check that
    # another check silently covers is a check nobody is running.
    return untrimmed if untrimmed != untrimmed.strip("-") else ""


def _slug_punctuation_to_dash(title: str) -> str:
    """The other common convention: punctuation becomes a separator.

    Renderers disagree here, and both spellings are correct on the site that
    produced them. GitHub DROPS a dot, so `## build.target` offers
    `#buildtarget`; VitePress and several others turn it into a dash, so the
    same heading offers `#build-target`.

    Measured on vitejs/vite, which links to `#build-target` throughout and
    renders correctly: following GitHub's rule alone reported ten dead anchors
    in a documentation site with no broken anchors. Accepting BOTH spellings
    costs nothing that matters - a fragment matching neither is still dead,
    which is why httpx's genuinely broken `#routing` survives this change.
    """
    text = re.sub(r"[^\w\s-]", "-", _heading_text(title))
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _definition_terms(text: str) -> list[str]:
    """Terms of a markdown definition list.

    A term is a plain line whose successor begins with a colon and a space:

        `titleCaseStyle`
        : (`bool`) Whether to capitalize automatic list titles.

    Renderers supporting the extension - Goldmark, PHP Markdown Extra,
    kramdown, pandoc - give each `<dt>` an id the same way they give one to a
    heading, so a term is an anchor source and had been invisible here.

    Measured on the Hugo documentation, which documents every configuration key
    this way: 71 of its 101 same-document anchor findings are terms, and no
    other repository in a 26-project corpus has a single one, so this widens
    nothing anywhere else.

    Excluded openers are the shapes that are already something else - a
    heading, a quote, a list item, a table row, an indented block - because
    each can be followed by a colon line without being a definition list.
    """
    lines = text.splitlines()
    terms: list[str] = []
    for index, line in enumerate(lines[:-1]):
        if not line.strip() or line.startswith((" ", "\t", "#", ">", "-", "*", "|", "=")):
            continue
        if re.match(r"^:\s", lines[index + 1]):
            terms.append(line.strip())
    return terms


_SETEXT_RULE = re.compile(r"^(?:=+|-{2,})\s*$")


def _setext_headings(text: str) -> list[str]:
    """Headings written by underlining rather than with `#`.

        Limitations
        -----------

    CommonMark calls these setext headings and every renderer gives them an
    id, but only ATX headings were parsed here. A document written entirely in
    this style therefore offered NO anchors at all, so every link into it read
    as dead - the failure is total rather than partial, which is what makes it
    worth handling. Found on a vendored README carrying 13 such headings and
    not one `#`.

    YAML frontmatter is skipped first. Its closing `---` follows a non-blank
    line, which would otherwise promote `title: something` to a heading and
    invent an anchor the document does not have.
    """
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() in ("---", "..."):
                start = index + 1
                break
    found: list[str] = []
    for index in range(start, len(lines) - 1):
        title = lines[index].strip()
        if not title or not _SETEXT_RULE.match(lines[index + 1].strip()):
            continue
        # Shapes that are already something else and can be followed by a
        # rule of dashes without being a heading.
        if title.startswith(("#", ">", "-", "*", "+", "|", "=", ":")):
            continue
        if lines[index].startswith((" ", "\t")):
            continue
        found.append(title)
    return found


def _anchors(text: str) -> set[str]:
    """Every fragment this document offers, from headings and explicit anchors."""
    headings = [m.group(1) for line in text.splitlines()
                if (m := _HEADING.match(line) or _NESTED_HEADING.match(line))]
    headings += _definition_terms(text)
    headings += _setext_headings(text)
    # Every spelling a renderer might produce: two slug conventions, each over
    # the heading as written and with angle-bracket markup removed. Offering a
    # spelling that no renderer uses costs nothing - a fragment matching none
    # of them is still dead - while missing one reports a working link as
    # broken, which is the failure that matters.
    variants = [v for h in headings for v in (h, _without_tags(h))]
    found = {_slug(v) for v in variants}
    found |= {_slug_punctuation_to_dash(v) for v in variants}
    found |= {_slug_keeping_edges(v) for v in variants}
    found |= {a.lower() for a in _EXPLICIT_ANCHOR.findall(text)}
    found |= {a.lower() for a in _ATTR_ANCHOR.findall(text)}
    found |= {a.lower() for a in _MYST_TARGET.findall(text)}
    found |= {a.lower() for a in _DIRECTIVE_LABEL.findall(text)}
    found |= _disambiguated(headings)
    return found - {""}


def _disambiguated(headings: list[str]) -> set[str]:
    """The `-1`, `-2` suffixes a renderer adds when a slug repeats.

    Two headings reading the same thing cannot share an id, so every renderer
    numbers the later ones. Hugo's deployment page carries a `matchers`
    definition term and a `## Matchers` section, and links to the second as
    `#matchers-1`.

    Offered only from the SECOND occurrence onward, because that is when a
    renderer starts numbering; inventing `-1` for a slug that occurs once would
    forgive an anchor that really is dead.
    """
    seen: dict[str, int] = {}
    for heading in headings:
        slug = _slug(heading)
        if slug:
            seen[slug] = seen.get(slug, 0) + 1
    return {f"{slug}-{n}" for slug, count in seen.items()
            for n in range(1, count)}


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
    base = _DOC.link_base or repo
    findings: list[Finding] = []
    for number, line in enumerate(_strip_code(text).splitlines(), start=1):
        for raw in _MD_LINK.findall(line):
            if _EXTERNAL.match(raw) or raw.startswith("#"):
                continue
            target = raw.split("#", 1)[0]
            if not target:
                continue
            # `@` opens a generator macro, not a path. Documenter.jl writes
            # `[text](@ref)` for a cross-reference and JuliaLang/julia carries
            # 1,779 of them - every single one reported as a dead file, and 96%
            # of that repository's findings.
            if target.startswith("@"):
                continue
            # A markdown link percent-encodes characters that are awkward in a
            # URL, and the file on disk carries the decoded name.
            # nlohmann/json documents `operator[]` and links to it as
            # `operator%5B%5D.md`, which is the same file spelled for a browser.
            target = _percent_decoded(target)
            # A leading slash means the repository root, which is how GitHub
            # renders it. Resolved against the DOCUMENT it reported
            # `/.github/AI_POLICY.md` dead in psf/requests while the file sat
            # right there.
            if target.startswith("/"):
                rooted = target.lstrip("/")
                if rooted and _resolve_reference(repo, repo, rooted)[0]:
                    continue
                # A root-relative target with no extension is a site route, and
                # it is settleable without knowing the generator: append `.md`
                # from the repository root and see. microsoft/vscode-docs links
                # to `/api/ux-guidelines/views` throughout, and that file is
                # right there as `api/ux-guidelines/views.md`.
                #
                # Silenced only when the document demonstrably EXISTS, so the
                # 220 of its links that resolve to nothing are still reported.
                # Measured before widening: 635 findings match this shape and
                # every one is in that repository, so no other project's links
                # change meaning.
                bare = rooted.rstrip("/")
                if bare and not Path(bare).suffix and (
                        _resolve_reference(repo, repo, bare + ".md")[0]
                        or _resolve_reference(repo, repo, bare + "/index.md")[0]):
                    continue
                # Deliberately NOT skipped unconditionally here.
                #
                # A held-out corpus produced 6,360 findings of this shape and
                # not one was a real defect, which argued for a blanket skip.
                # Two existing tests refuse it in as many words -
                # "detection must stay a property of the repository", "so the
                # fix above cannot become a blanket skip" - and they are
                # right: in a repository that builds no site, a root-relative
                # link to a missing file is dead and worth saying so.
                #
                # The cause was never the shape, it was DETECTION failing to
                # reach three layouts: haystack declares Docusaurus in
                # `docs-website/`, llama_index declares MkDocs in
                # `docs/api_reference/`, and svelte numbers its documents for
                # a site built from another repository. `_SITE_DIRS`,
                # `_site_dirs` and `_numbered_docs_tree` were widened to see
                # all three, which removes the findings without removing the
                # rule.
            exists, actual_case = _resolve_reference(repo, base, target)
            if exists:
                continue
            # In a compiled docs tree the remaining shapes are site routes
            # rather than files: an extensionless target, a `.html` target, or
            # an absolute path from the site root. None can be settled by the
            # filesystem, so none is judged. See _SITE_CONFIGS for the
            # measurement.
            # A `.html` target is a rendered page, in every repository and
            # not only in a detected one. MEASURED across 20 repositories in
            # two corpora: 407 markdown links point at a `.html` target and
            # NOT ONE resolves to a checked-in file. Gating this on generator
            # detection is what made rails report 276 of its own guide links
            # dead - its guides compile to HTML with a bespoke builder that
            # ships none of the configs detected below.
            if target.endswith(".html"):
                continue
            # The other two shapes still need the gate. In a plain repository
            # an extensionless target can be a real file - LICENSE, Makefile -
            # so silencing those everywhere would stop the rule working.
            # The two shapes are gated DIFFERENTLY, because they fail
            # differently.
            #
            # A leading slash is never a path in this repository, wherever
            # the document sits: GitHub resolves it against github.com and a
            # generator resolves it against the site root. So once the
            # repository is known to build a site at all, this is a route.
            if target.startswith("/") and _is_generated_site(repo):
                continue
            # An extensionless target CAN be a real file - LICENSE, Makefile,
            # a directory - so this one asks whether THIS document is a page
            # rather than whether the repository builds a site somewhere. A
            # monorepo builds one from `docs/` and still keeps ordinary
            # READMEs in `packages/`, whose relative links are files.
            if not Path(target).suffix and _in_site_tree(repo):
                continue
            # A generator that flattens its guides into one namespace resolves
            # a sibling by bare name from any depth. Phoenix links to
            # `contexts.md` from `guides/authn_authz/`, and the file lives at
            # `guides/data_modelling/contexts.md`; ExDoc finds it, a relative
            # path does not. Accepted only when the basename is UNIQUE in the
            # repository, so this stays a filesystem fact rather than a guess
            # about which of several candidates was meant.
            if _in_site_tree(repo) and _unique_basename(repo, target):
                continue
            # A docs tree that ORDERS its pages by filename prefix strips that
            # prefix from the route. svelte keeps
            # `documentation/docs/07-misc/04-custom-elements.md` and links to
            # it as `custom-elements` from a sibling page; the file is right
            # there and the link works on svelte.dev.
            #
            # Not gated on generator detection, because the prefix IS the
            # evidence - a repository that numbers its documents this way has
            # something consuming the order. Kept to a UNIQUE match for the
            # same reason `_unique_basename` is: two files answering to one
            # route say nothing about which was meant. 139 findings on the
            # held-out corpus, all of them working links.
            if _numbered_document(repo, target):
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
            findings.append(Finding(number, "dead-md-link", detail,
                                    subject=target))
    return findings


def _target_anchors(path: Path) -> set[str] | None:
    """Anchors offered by another document, or None if it cannot be read."""
    key = str(path)
    if key not in _SCOPE.target_anchors:
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                _SCOPE.target_anchors[key] = _anchors(fh.read())
        except (OSError, UnicodeDecodeError):
            _SCOPE.target_anchors[key] = None
    return _SCOPE.target_anchors[key]


def validate_md_anchors(repo: Path, text: str) -> list[Finding]:
    """`#fragment` links pointing at no such heading, in this file or another.

    This used to check same-document fragments only, on the reasoning that a
    fragment on another file needs that file's renderer slug rules and so is a
    guess rather than a fact. That reasoning was sound and applied just as
    much to the same-document case, which shipped anyway - the asymmetry was
    never justified, and two things have since removed most of the guess.
    Headings are now slugged under BOTH common conventions, and a cross-file
    fragment is only judged when its path resolves to a real markdown file
    exactly as written.

    That last condition keeps this conservative on purpose. An extensionless
    or routed target in a generated site never resolves, so it is never judged
    here; `dead-md-link` already declines to judge it for the same reason, and
    a missing file is that rule's finding rather than this one's.

    Measured across nine repositories: 26 cross-file anchors resolve to a real
    file, 3 of them name a heading that does not exist, and all 3 are the same
    rot - a heading renamed and its inbound links left behind. httpx links to
    `#customizing-authentication` where the heading reads "Custom
    authentication schemes".
    """
    own = _anchors(text)

    # The ambient set is built ON DEMAND, and the demand is rare.
    #
    # It is consulted for one shape only - a bare `#fragment` that the document
    # does not define itself - and most fragments resolve inside their own
    # page. Building it eagerly meant a repository declaring a project-wide
    # namespace read every tracked markdown file on EVERY run, including a
    # post-commit hook, to validate a document that might contain no anchor
    # links at all.
    #
    # The trigger is one file existing, and for Sphinx that file is `conf.py`,
    # so this was the ordinary case across a large slice of Python projects
    # rather than an exotic one. Measured before the change, on a document held
    # identical while only the config was added: +42 ms at 100 files, +128 ms
    # at 400, +421 ms at 1600. Flat in the document, linear in the repository.
    #
    # Deferring makes the cost proportional to the number of fragments that are
    # ABOUT to be reported, which is the only time the answer can change a
    # finding. Behaviour is unchanged: `x in own or x in ambient` is the same
    # test as `x in (own | ambient)`.
    ambient: set[str] | None = None

    def ambient_anchors() -> set[str]:
        nonlocal ambient
        if ambient is None:
            if _has_global_anchors(repo):
                ambient = _project_anchors(repo)
            elif _has_partial_anchors(repo):
                ambient = _partial_anchors(repo)
            else:
                ambient = set()
        return ambient

    base = _DOC.link_base or repo
    findings: list[Finding] = []
    for number, line in enumerate(_strip_code(text).splitlines(), start=1):
        for raw in _MD_LINK.findall(line):
            if "#" not in raw or _EXTERNAL.match(raw):
                continue
            target, _, fragment = raw.partition("#")
            fragment = fragment.lower()
            if not fragment:
                continue
            if not target:
                if fragment in own or fragment in ambient_anchors():
                    continue
                findings.append(Finding(
                    number, "dead-md-anchor",
                    f"links to `{raw}`, but this document has no such heading",
                    subject=raw,
                ))
                continue
            if target.startswith("/"):
                resolved = repo / target.lstrip("/")
            else:
                resolved = base / target
            if resolved.suffix.lower() not in (".md", ".markdown"):
                continue
            if not resolved.is_file():
                continue          # dead-md-link's finding, not this rule's
            offered = _target_anchors(resolved)
            if offered is None or fragment in offered:
                continue
            findings.append(Finding(
                number, "dead-md-anchor",
                f"links to `{raw}`, but `{_rel(repo, resolved)}` has no such "
                "heading",
                subject=raw,
            ))
    return findings


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


# Directory listings, cached only while validate() says it is safe to. Both the
# cache and the "is this repository static" flag that governs it now live on the
# run scope, where their lifetimes are written down beside them; see
# `RunScope.dircache` and `RunScope.stable`.
def _listdir(directory: Path) -> set[str]:
    cache = _SCOPE.dircache
    if cache is None:
        return {entry.name for entry in directory.iterdir()}
    names = cache.get(directory)
    if names is None:
        names = {entry.name for entry in directory.iterdir()}
        cache[directory] = names
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


# Configs that mean "this markdown tree is compiled into a website".
#
# It matters because a link in such a tree is a ROUTE, not a path. VitePress
# serves `docs/` as the site root, so `/guide/features.html` is a real link to
# `docs/guide/features.md`; MkDocs drops the extension, so `../advanced/
# transports` is a real link to `transports.md`. Neither is a file, so the
# filesystem cannot settle either, and the guarantee says a rule that cannot
# be settled must not judge.
#
# Measured across nine repositories: exactly the three that ship one of these
# files - vite (VitePress), httpx (MkDocs), rust-lang/rfcs (mdBook) - produced
# every route-shaped false positive, 331 of them. The six with no such config
# produced none, and in those `/CONTRIBUTING.md` really does mean repo root,
# which is how GitHub renders it.
_SITE_CONFIGS = (
    "mkdocs.yml", "mkdocs.yaml", "book.toml", "_config.yml",
    "docusaurus.config.js", "docusaurus.config.ts",
    "docs/.vitepress/config.ts", "docs/.vitepress/config.js",
    ".vitepress/config.ts", ".vitepress/config.js",
    "hugo.toml", "hugo.yaml",
    # Astro powers Starlight, whose docs link by route: withastro/starlight
    # reported 235 of its own `/de/reference/configuration/` links as dead
    # files. MyST builds a site from `myst.yml` the same way.
    "astro.config.mjs", "astro.config.ts", "astro.config.js",
    "myst.yml", "antora.yml", "conf.py",
    # Next.js routes by file path, so a markdown link inside one is a route.
    # Nextra builds on it: shuding/nextra reported 227 of its own links dead,
    # every one extensionless or root-relative, declaring `docs/next.config.ts`.
    "next.config.js", "next.config.ts", "next.config.mjs",
    # Mintlify serves `.mdx` by route from a single declaration.
    # humanlayer/humanlayer keeps `docs/mint.json` and reported 5 of its own
    # `/core/require-approval` links dead. Only `mint.json` is listed: the
    # newer `docs.json` spelling is too generic a filename to treat as a
    # signature, and no repository measured here carries one.
    "mint.json",
    # Fern serves `.mdx` by route from `fern/docs.yml`, and its pages link to
    # each other with site-absolute routes throughout. Skyvern keeps
    # `fern/fern.config.json` beside it and raised 52 findings, every one a
    # `/api-reference/...` route that works on the published documentation.
    # `fern.config.json` is the signature rather than `docs.yml`, which is too
    # generic a filename to treat as one.
    "fern.config.json",
)


# Generators whose configuration lives INSIDE another file rather than in one
# of its own, so existence is not enough and the content decides.
#
# Elixir declares ExDoc as a dependency in mix.exs. phoenixframework/phoenix
# does exactly that and links to `Mix.Tasks.Phx.Gen.Auth.html` and to sibling
# guides by bare name, both of which ExDoc resolves and the filesystem cannot:
# 104 findings, every one a link that works on hexdocs.
_SITE_MARKERS_IN_FILE = (
    ("mix.exs", "ex_doc"),
    # Docsify ships no config of its own: one `index.html` loads the script and
    # every page is a route resolved at runtime. docsifyjs/docsify keeps its at
    # `docs/index.html`, which is why the marker search below walks _SITE_DIRS
    # rather than looking only at the root.
    ("index.html", "docsify"),
    # Mintlify RENAMED `mint.json` to `docs.json`, so a current Mintlify site
    # declares itself in a file whose name says nothing. Listing `docs.json`
    # among the filename signatures would suppress link checking for any
    # project that happens to keep an unrelated `docs/docs.json`, which is why
    # it was left out. Content decides instead: Mintlify writes its own schema
    # URL into the file, and nothing else does.
    ("docs.json", "mintlify.com"),
)


# Where a generator config sits. The site is often a subdirectory of a project
# that is mostly something else: jekyll/jekyll keeps its own documentation site
# under `docs/` with `docs/_config.yml`, so a root-only search missed it and
# reported 138 of its site routes as dead files.
# `docs-website` and `documentation` added from a held-out corpus: haystack
# keeps `docs-website/docusaurus.config.js` and svelte keeps its pages under
# `documentation/`. Between them those two directories held 5,120 findings
# that a detected generator would already have silenced.
_SITE_DIRS = ("", "docs", "site", "www", "website", "docs-website",
              "documentation", "fern")


# Generators whose cross-reference namespace is the PROJECT, not the page.
#
# MyST and Sphinx resolve `#label` against every document at once, so a target
# defined in `site-options.md` is reachable as `#site-options` from anywhere.
# executablebooks/mystmd relies on that throughout: 168 of its findings name a
# label that exists, just not in the file doing the linking.
#
# Deliberately NOT applied to every generated site. Measured on encode/httpx,
# which is MkDocs and therefore per-page: a blanket project-wide union forgave
# two of its three genuinely dead anchors, trading real signal for quiet. The
# namespace is a property of the generator, so the generator decides.
_GLOBAL_ANCHOR_CONFIGS = ("myst.yml", "conf.py", "antora.yml")


def _has_global_anchors(repo: Path) -> bool:
    key = str(repo)
    if key not in _SCOPE.global_ns:
        # The same directory list as `_is_generated_site`, deliberately. Two
        # searches for "where does this project keep its generator config"
        # that disagree is a latent bug, and this exact shape has been a
        # shipped one twice: root-only missed jekyll's `docs/_config.yml`, and
        # then the marker search missed docsify's `docs/index.html`. Measured
        # across 30 repositories it changes nothing today; it exists so the
        # two cannot answer differently about the same repository tomorrow.
        _SCOPE.global_ns[key] = any((d / name).is_file()
                                    for d in _site_dirs(repo)
                                    for name in _GLOBAL_ANCHOR_CONFIGS)
    return _SCOPE.global_ns[key]


# Hugo alone, because the convention is Hugo's. Its `_`-prefixed content
# directories are not routable pages; they are fragments composed into other
# pages by a shortcode, so a term defined in `_common/configuration/locale.md`
# is an anchor on whatever page includes it. 23 of hugoDocs' 23 remaining
# same-document findings were exactly that.
#
# NOT generalised to every `_` directory, and the measurement is why: seven of
# 38 corpus repositories have markdown under one, and they mean different
# things. Jekyll's `_posts` are whole pages. Docusaurus's `__tests__` is
# fixtures. Treating those as ambient anchors would forgive real findings in
# four repositories to fix one.
_PARTIAL_CONFIGS = ("hugo.toml", "hugo.yaml", "hugo.json")


def _has_partial_anchors(repo: Path) -> bool:
    key = str(repo)
    if key not in _SCOPE.partial_ns:
        _SCOPE.partial_ns[key] = any((d / name).is_file()
                                     for d in _site_dirs(repo)
                                     for name in _PARTIAL_CONFIGS)
    return _SCOPE.partial_ns[key]


def _partial_anchors(repo: Path) -> set[str]:
    """Anchors from fragment files, which belong to every page that includes one."""
    key = str(repo)
    if key not in _SCOPE.partial_anchors:
        found: set[str] = set()
        try:
            for rel in tracked_markdown(repo):
                if not any(part.startswith("_") for part in rel.split("/")[:-1]):
                    continue
                try:
                    with open(repo / rel, encoding="utf-8", newline="") as fh:
                        found |= _anchors(fh.read())
                except (OSError, UnicodeDecodeError):
                    continue
        except (OSError, subprocess.CalledProcessError):
            found = set()
        _SCOPE.partial_anchors[key] = found
    return _SCOPE.partial_anchors[key]


def _project_anchors(repo: Path) -> set[str]:
    """Every anchor offered by every tracked markdown file in the project."""
    key = str(repo)
    if key not in _SCOPE.project_anchors:
        found: set[str] = set()
        try:
            for rel in tracked_markdown(repo):
                path = repo / rel
                try:
                    with open(path, encoding="utf-8", newline="") as fh:
                        found |= _anchors(fh.read())
                except (OSError, UnicodeDecodeError):
                    continue
        except (OSError, subprocess.CalledProcessError):
            found = set()
        _SCOPE.project_anchors[key] = found
    return _SCOPE.project_anchors[key]


def _site_dirs(repo: Path) -> list[Path]:
    """Every directory a generator config can sit in, one level of nesting deep.

    A site is often a subdirectory of a subdirectory. aider keeps a Jekyll site
    at `aider/website/_config.yml` - a package directory, and the site inside
    it - so a search that only tried `website/` found nothing and the whole
    repository was judged as plain. It reported 29 of its own asset links dead,
    every one of them served by Jekyll from `aider/website/assets/`.

    Bounded to ONE extra level on purpose, and to the same directory names. An
    unbounded walk would scan every directory in the repository to answer a
    question asked on every run, and a config found ten levels down is likelier
    to be a fixture or a vendored copy than this project's site.
    """
    dirs = [repo / d for d in _SITE_DIRS]
    for name in _SITE_DIRS:
        if name:
            dirs.extend(repo.glob(f"*/{name}"))
            # And one level INSIDE a site directory, which is the mirror of
            # the case above and was missing. llama_index declares MkDocs at
            # `docs/api_reference/mkdocs.yml`; the search reached `*/docs`
            # but never `docs/*`, so 1,227 route links were judged as files.
            # Still bounded to one level, and still to the same names, so
            # `a/b/c/website/` stays out of reach.
            dirs.extend(d for d in (repo / name).glob("*") if d.is_dir())
    return dirs


def _is_generated_site(repo: Path) -> bool:
    """Does this repository compile its markdown into a website?"""
    return bool(_site_scopes(repo))


def _site_scopes(repo: Path) -> set[str]:
    """Top-level directories a generator governs, or {""} for the whole repo.

    Recorded rather than reduced to a yes/no, because a monorepo is not one
    site. astro declares Astro under `examples/*` and llama_index declares
    MkDocs under `docs/`; treating either as "this repository is a site"
    stopped the route suppressions at the repository boundary and silenced
    six real defects in `packages/astro/src/core/render/README.md` and
    `llama-index-integrations/.../README.md`, which no site builds.

    Top-level and not the exact directory, because a config often sits one
    level inside the tree it governs: llama_index declares MkDocs at
    `docs/api_reference/mkdocs.yml` while the pages it serves live under
    `docs/src/content/docs/`. Scoping to `docs/` covers both.
    """
    key = str(repo)
    if key not in _SCOPE.site:
        scopes: set[str] = set()
        for directory in _site_dirs(repo):
            declared = any((directory / name).is_file()
                           for name in _SITE_CONFIGS)
            if not declared:
                for name, marker in _SITE_MARKERS_IN_FILE:
                    path = directory / name
                    try:
                        if path.is_file() and marker in path.read_text(
                                encoding="utf-8", errors="replace"):
                            declared = True
                            break
                    except OSError:
                        continue
            if declared:
                top = _top_level(repo, directory)
                if top is not None:
                    scopes.add(top)
        scopes |= _numbered_docs_scopes(repo)
        _SCOPE.site[key] = scopes
    return _SCOPE.site[key]


def _top_level(repo: Path, directory: Path) -> str | None:
    """The first path segment of `directory` under `repo`; "" for the root.

    None when the two cannot be related, which the caller drops rather than
    treating as the root. Returning "" on failure would mean "a generator
    governs this whole repository", the most permissive answer available, so
    a junction or a permission error would silently switch every route
    suppression on. `_site_dirs` builds these paths from `repo` itself, so
    the plain comparison succeeds; `resolve()` is the fallback, not the
    first move, because on Windows it can rewrite one side of a pair.
    """
    for candidate, base in ((directory, repo),
                            (directory.resolve(), repo.resolve())):
        try:
            relative = candidate.relative_to(base)
        except (ValueError, OSError):
            continue
        parts = relative.as_posix().split("/")
        return parts[0] if parts and parts[0] not in (".", "") else ""
    return None


def _in_site_tree(repo: Path) -> bool:
    """Is the document being validated inside a tree some generator builds?

    A repository with a site somewhere is not a repository whose every
    markdown file is a page. When the caller has not said which document is
    being read, this answers True, which keeps every existing caller and the
    whole-repository question behaving as before.
    """
    scopes = _site_scopes(repo)
    if not scopes or "" in scopes:
        return bool(scopes)
    document = _current_document()
    if document is None:
        return True
    return document.split("/")[0] in scopes


def _numbered_docs_scopes(repo: Path) -> set[str]:
    """Top-level directories holding a numbered documentation tree."""
    return {top for top, count in _numbered_docs_tree(repo).items() if count >= 3}


def _numbered_docs_tree(repo: Path) -> dict[str, int]:
    """A directory whose documents are NUMBERED for presentation order.

        documentation/docs/07-misc/01-best-practices.md
        documentation/docs/07-misc/02-testing.md
        documentation/docs/07-misc/04-custom-elements.md

    Nothing reads a prefix like that except a generator building an ordered
    site, and the pages then link to each other by the stripped name. This is
    the signal for a project whose site is built from ANOTHER repository, so
    no config exists here to find: svelte's pages live here and svelte.dev
    builds them, which left 64 of its own `/docs/svelte` links judged as
    files.

    Three in one directory, not one. A single `01-intro.md` beside ordinary
    filenames is somebody numbering one document; a directory of them is a
    convention with a consumer.
    """
    key = str(repo)
    if key not in _SCOPE.numbered:
        per_dir: dict[str, int] = {}
        try:
            for path in tracked_markdown(repo):
                head, _, leaf = path.rpartition("/")
                if not _ORDER_PREFIX.match(leaf):
                    continue
                # Bounded to the conventional documentation directories, for
                # the reason `_site_dirs` bounds its own search: something
                # found deep inside a package is likelier to be a fixture
                # than this project's site.
                #
                # Unbounded, this declared all of `packages/` a documentation
                # site on the strength of three numbered `.mdx` files in
                # `packages/astro/test/fixtures/content/src/content/blog/`,
                # and route suppression then hid three real defects in
                # `packages/astro/src/core/render/README.md`.
                top = head.split("/")[0] if head else ""
                if top and top not in _SITE_DIRS:
                    continue
                per_dir[head] = per_dir.get(head, 0) + 1
        except (OSError, subprocess.CalledProcessError):
            per_dir = {}
        # Reported per TOP-LEVEL directory, keeping the largest run found
        # under each, so the threshold is still "three in one directory" but
        # the answer says which part of the repository it governs.
        tops: dict[str, int] = {}
        for directory, count in per_dir.items():
            top = directory.split("/")[0] if "/" in directory else directory
            tops[top] = max(tops.get(top, 0), count)
        _SCOPE.numbered[key] = tops
    return _SCOPE.numbered[key]


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
                subject=branch,
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
            resolved = _released_tag(repo, tag)
            if resolved is None:
                if _RELEASE_CLAIMS_ARE_OURS:
                    findings.append(Finding(
                        number, "dead-release-tag",
                        f"claims release `{tag}`, but no such tag exists",
                        subject=tag,
                    ))
                    continue
                # "NO SUCH TAG EXISTS" IS NOT A QUESTION GIT CAN SETTLE, and
                # this branch used to answer it anyway. A version in prose can
                # name a git tag, an npm or PyPI release, a sub-package, a
                # plugin, or a toolchain somebody else ships, and nothing in
                # the sentence says which.
                #
                # Measured on 15 repositories that write prose release claims,
                # it was wrong 19 times out of 26. eugenelim/agent-ready-repo
                # tags `credbroker-v0.4.0` and writes "shipped as 0.27.0", an
                # npm version; 10CG/Aria tags to v1.5.0 and cites v1.17.3
                # through v1.24.1, its plugin's numbering; rust-lang/rfcs has
                # no tags at all and discusses Rust's releases throughout.
                #
                # A range test was tried and does not separate them - two of
                # the false positives sit inside the repository's own tag
                # range - so there is no narrowing here, only a question the
                # rule should not be asking. `dead-pinned-ref` stays honest on
                # the same problem only because `repo:` names the owner on the
                # line above; prose carries no such marker.
                #
                # The cost is real and stated: a project that claims a release
                # it never tagged is no longer caught. What remains is the
                # half that IS settleable - the tag is here, and it shipped on
                # nothing - which was right 7 times out of 7.
                continue
            if not _integration_refs(repo):
                continue        # no integration branch here to have shipped it
            if not _integrated_by(repo, f"refs/tags/{resolved}"):
                findings.append(Finding(
                    number, "dead-release-tag",
                    f"tag `{resolved}` exists but is on no integration branch "
                    f"({', '.join(_integration_refs(repo))})",
                    subject=tag,
                ))
    return findings


def _tags(repo: Path) -> set[str]:
    """Every tag in this repository, read once."""
    # From the shared ref table rather than its own `tag -l`. Same names, one
    # fewer subprocess; see `_ref_table`.
    return set(_ref_table(repo)[1])


def _tag_prefixes(repo: Path) -> list[str]:
    """What this repository puts BEFORE a version number in a tag.

    Read from `git tag -l` rather than configured, because which convention a
    project uses is a fact git already holds. Measured across 30 repositories:
    black tags `18.3a0`, poetry `0.1.0`, ruff and uv likewise - all bare -
    while symfony tags `v8.0.0`. A claim written in the other convention
    resolves to nothing, so the rule reported a release that had shipped.
    """
    key = str(repo)
    if key not in _SCOPE.tag_prefixes:
        prefixes = set()
        for tag in _tags(repo):
            digit = re.search(r"\d", tag)
            if digit is not None:
                prefixes.add(tag[:digit.start()])
        _SCOPE.tag_prefixes[key] = sorted(prefixes)
    return _SCOPE.tag_prefixes[key]


def _released_tag(repo: Path, version: str) -> str | None:
    """The real tag a release claim names, or None if there is none.

    Two things stand between a claimed version and a tag, and both are the
    project's own habits rather than the author's error.

    The PREFIX: see `_tag_prefixes`. A claimed `v8.0` and a claimed `8.0` mean
    the same release, and which spelling is correct depends on the repository.

    The SERIES: a claim names one far more often than it names a tag. Symfony's
    own triage guide says work "shipped in 8.0" and no tag is called that - the
    tags are `v8.0.0`, `v8.0.1` and so on. A claimed version that is the stem
    of a real tag has therefore shipped, and saying otherwise is pedantry about
    a number rather than a fact about git.
    """
    tags = _tags(repo)
    # LITERALLY FIRST, and this is not an optimisation. A project can configure
    # `release_tag` to capture its whole tag name - the installer derives such
    # a pattern from repositories tagging `release-1.2.3` or `api@2.0.0` - and
    # for those the captured text IS the tag. Trying prefixes first turns
    # `release-1.2.3` into `release-release-1.2.3`, resolves nothing, and
    # reports a shipped release as dead. Caught by the scenario harness rather
    # than by any unit test here, every one of which used a bare or
    # `v`-prefixed version.
    if version in tags:
        return version
    bare = version.removeprefix("v")
    for prefix in _tag_prefixes(repo):
        exact = prefix + bare
        if exact in tags:
            return exact
        series = sorted(tag for tag in tags if tag.startswith(exact + "."))
        if series:
            return series[0]
    return None


# An install snippet pins a version. `repo:` and `rev:` are pre-commit's fixed
# syntax rather than any project's habit, so like markdown link syntax there is
# nothing here to measure and nothing to configure.
# YAML quoting around a rev. Named rather than inlined so the mutation that
# removes it has a legible anchor.
_PIN_QUOTES = "'\""
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
    """This repository as `owner/name`, or None when it has no origin.

    Memoised, because the answer is a property of the REPOSITORY and this is
    asked once per DOCUMENT. `--sweep` therefore spawned one `git remote
    get-url` per file to receive the same string every time: profiled over 400
    documents, that was 11.3 seconds of a 16.2 second run - 70 percent of the
    work, for one answer.

    A remote cannot change while a process runs, and every mode here is a
    single short-lived process. `None` is a real answer, meaning no origin, so
    membership decides rather than truthiness.
    """
    key = str(repo)
    if key not in _SCOPE.own_remote:
        _SCOPE.own_remote[key] = _normalise_remote(
            _GIT.soft(repo, "remote", "get-url", "origin"))
    return _SCOPE.own_remote[key]


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
            # `rev: ''` is pre-commit's OWN documented placeholder - the state
            # a snippet ships in for `pre-commit autoupdate` to fill. It is not
            # a pin that broke; it is the absence of one, and reporting it
            # accuses a project of the idiom its own tool prescribes.
            # python-poetry/poetry ships two, and both were reported.
            #
            # Quotes come off for the same reason a bare rev is accepted:
            # `rev: 'v1.2.3'` is the same pin, and looking it up with the
            # quotes attached finds nothing. Measured across 30 repositories -
            # 69 bare, 4 quoted, 2 empty - so the quoted spelling is a latent
            # false positive waiting on the first project to pin itself
            # that way.
            ref = match.group(1).strip(_PIN_QUOTES)
            if ref:
                found.append((number, ref))
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
            _GIT.run(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        except (subprocess.CalledProcessError, OSError):
            findings.append(Finding(
                number, "dead-pinned-ref",
                f"install snippet pins `{ref}`, which does not exist here; "
                f"anyone copying this block gets an error",
                subject=ref,
            ))
    return findings


def _consistency_for(repo: Path) -> dict[str, tuple[tuple[str, object], ...]]:
    """The consistency block belonging to the repository being checked."""
    try:
        return load_config(repo).consistency
    except ValueError:
        return {}


# None means unbounded, which is the default and the historical behaviour.
# See `_search_with_limit` for why an unbounded default is right rather than
# an oversight.
#
# ANNOTATED, NOT ASSIGNED. `_apply_config()` runs at import, far above this
# line, and sets this from `consistency_timeout_seconds`. An assignment here
# then ran afterwards and silently replaced the configured bound with None,
# so the opt-in was inert on every CLI run: the config parsed, the value
# reached CONFIG, and the global the rule actually reads never saw it. An
# annotation binds no value, so the one `_apply_config` set survives.
_CONSISTENCY_TIMEOUT: float | None


class _Captured:
    """A stand-in exposing the one method the caller uses on a match.

    `_search_with_limit` cannot return a real `re.Match` from a subprocess,
    because a match object holds a reference to the compiled pattern and the
    subject string and does not survive being pickled across a pipe. The caller
    only ever asks for `group(1)`, so that is what this provides.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def group(self, _index: int = 0) -> str:
        return self._value


def _search_with_limit(pattern: "re.Pattern[str]", content: str,
                       timeout: float | None):
    """`pattern.search(content)`, optionally under a wall-clock bound.

    Unbounded by default, and that is deliberate rather than neglected. Python's
    `re` does not release the GIL while matching, so a watchdog thread never
    runs and cannot interrupt a catastrophic backtrack. Process isolation is the
    only mechanism that actually works, and it costs a spawn per pattern -
    which `stress.py` case 11 puts at 200 per verify. Charging every user that
    for a problem almost none of them have is the wrong trade, so it is opt-in.

    Raises TimeoutError when the bound is exceeded. Returns None or an object
    exposing `group(1)`, matching what the caller does with a real match.
    """
    if timeout is None:
        return pattern.search(content)
    program = (
        "import re, sys, json\n"
        "spec = json.loads(sys.stdin.read())\n"
        "found = re.compile(spec['p'], spec['f']).search(spec['c'])\n"
        "sys.stdout.write(json.dumps("
        "found.group(1) if found and found.groups() else None))\n"
    )
    payload = json.dumps({"p": pattern.pattern, "f": pattern.flags,
                          "c": content})
    try:
        done = subprocess.run(
            [sys.executable, "-c", program], input=payload, text=True,
            capture_output=True, timeout=timeout, encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(timeout) from None
    if done.returncode != 0:
        # The child failed for some reason other than time - a pattern the
        # parent compiled but the child could not, say. Fall back rather than
        # invent a finding about a pattern that may be perfectly good.
        return pattern.search(content)
    captured = json.loads(done.stdout or "null")
    return None if captured is None else _Captured(captured)


def _file_identity(path: Path) -> tuple[object, ...]:
    """A value equal for two paths that reach the same file.

    `(st_dev, st_ino)` is the filesystem's own answer, and it handles symlinks,
    hardlinks and case variants uniformly without knowing which it is looking
    at. It is not universally available: FAT32 and some network shares report
    `st_ino` as 0, and keyed on that every file on the volume would compare
    equal - reporting self-comparison on every configuration, which is a false
    positive on every run and worse than the hole this closes.

    A zero inode therefore falls back to the resolved, case-normalised path,
    which still follows symlinks and still collapses case variants on the
    platforms where those exist. A test asserts this distinguishes two
    known-different files before anything is built on it.
    """
    try:
        stat = path.stat()
        if stat.st_ino:
            return ("stat", stat.st_dev, stat.st_ino)
    except OSError:
        pass
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return ("path", os.path.normcase(str(resolved)))


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
        # Two spellings of one path are rejected at config load, by string.
        # A symlink, a hardlink, or a case variant on a case-insensitive
        # filesystem is a genuinely different route to the same bytes, and no
        # string comparison can see it - so the filesystem is asked instead.
        # Such a block agrees with itself forever while appearing to compare
        # two things, which is the shape of failure this project exists to
        # make visible.
        present = [rel for rel, _pattern in sources if (repo / rel).is_file()]
        if len(present) >= 2 and len({_file_identity(repo / rel)
                                      for rel in present}) < 2:
            findings.append(Finding(
                1, "inconsistent-artifact",
                f"consistency check `{name}` reads {len(present)} paths that "
                f"are the same file, so it compares a value with itself",
            ))
            continue
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
            try:
                match = _search_with_limit(pattern, content, _CONSISTENCY_TIMEOUT)
            except TimeoutError:
                # A hang is a worse failure than an error, which is the whole
                # reason the bound exists. Naming the file and the pattern is
                # what makes it actionable.
                findings.append(Finding(
                    1, "inconsistent-artifact",
                    f"consistency check `{name}` gave up on `{relative}` after "
                    f"{_CONSISTENCY_TIMEOUT}s; the pattern backtracks and needs "
                    f"simplifying",
                ))
                continue
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
    if key in _SCOPE.lfs:
        return _SCOPE.lfs[key]
    if not _lfs_is_configured(repo):
        _SCOPE.lfs[key] = []
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
        _SCOPE.lfs[key] = []
        return []   # unborn HEAD: nothing is committed to judge
    blobs: dict[str, str] = {}
    for record in listing.split("\0"):
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if path and len(parts) >= 3 and parts[1] == "blob":
            blobs[path] = parts[2]
    if not blobs:
        _SCOPE.lfs[key] = []
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
        _SCOPE.lfs[key] = []
        return []
    fields = raw.decode("utf-8", "replace").split("\0")
    governed = []
    # `-z` emits a flat NUL-separated stream of (path, attribute, value).
    for i in range(0, len(fields) - 2, 3):
        path, _attr, value = fields[i], fields[i + 1], fields[i + 2]
        if value == "lfs" and path in blobs:
            governed.append((path, blobs[path]))
    _SCOPE.lfs[key] = governed
    return governed


# --- manifest floor mismatch -------------------------------------------
#
# Every pattern below was derived from a 39-repository corpus measured
# 2026-08-04, never from what the wording "should" be. Keyed on shape alone
# the rule disagreed at 169 of 192 sites; 97 of those disagreements sat in
# changelogs and release notes, which are historical records and were true
# when written. Keyed as below it examined 7 sites and found 2 real
# contradictions with no false positives.

# The document a reader consults to learn what must be INSTALLED. A floor
# stated here is a promise to that reader.
_ENTRY_DOC = re.compile(
    r"(^|/)(readme|install|installation|installing|getting[-_ ]?started"
    r"|requirements|prerequisites|quickstart|quick[-_ ]?start)\.[a-z]+$", re.I)

# Redundant with `_ENTRY_DOC` today, since no entry-point name is also
# historical. Both are cheap, and the pair survives someone widening the
# entry-point list without re-reading this comment.
_HISTORICAL_DOC = re.compile(
    r"(changelog|changes|history|news|release[-_ ]?notes?|releases"
    r"|release[-_ ][0-9]|announce|breaking|migration|upgrad|whatsnew"
    r"|what-s-new|_posts|/blog/|deprecat)", re.I)

# The sentence must assert a requirement OF THIS PROJECT. Without this, a
# linter's documentation of what Python itself does in 3.9 reads as the
# linter's own floor - ruff alone produced 50 such sites.
_FLOOR_VERB = re.compile(
    r"\b(requires?|required|requiring|needs?|must have|depends? on"
    r"|compatible with|supports?|supported)\b", re.I)

# A bare `Requirements:` line introducing a list. caddy states its Go floor
# that way, with no verb in the sentence and no matching heading, and keying
# on the verb alone misses it.
_FLOOR_LABEL = re.compile(
    r"^(requirement|prerequisite|dependenc|require|you.ll need|needed)", re.I)

# Something else is the subject: another package, another tool, or the
# language's own behaviour. Structural phrases ONLY. The corpus harness also
# listed package names, which is a memory of one measurement rather than a
# rule; dropping them was verified to leave the result unchanged.
_FLOOR_THIRD_PARTY = re.compile(
    r"\b(upstream|if you|when using|available in|added in|introduced in"
    r"|valid in|works? (?:on|in))\b", re.I)

# WORD BOUNDARIES ARE LOAD-BEARING. Without them, and with re.I, `Go` matches
# inside "Django 4.2", "Mongo 6.0", "cargo 1.75.0", "logo 2.0" and the
# substring `LGO9` of a base64 access key; `Rust` inside "trust 1.0"; `Node`
# inside "anode 5.0"; `PHP` inside "xphp 8.1". Measured on the corpus: 57 of
# 116 harvested `go` sites, 49%, were exactly that. Only `Ruby` was
# accidentally safe.
_FLOOR_LANGS = {
    "Python": r"\bPython\b",
    "Node": r"\bNode(?:\.?js)?\b",
    "Go": r"\bGo(?:lang)?\b",
    "PHP": r"\bPHP\b",
    "Ruby": r"\bRuby\b",
    "Rust": r"\bRust\b",
}

# A floor, not a mention. A bare "Python 3.9" says nothing about a minimum,
# so an operator or a suffix is required.
_FLOOR_CLAIM = {
    name: re.compile(
        rf"{pattern}\s*(?:version\s*)?"
        rf"(>=|>|\^|~)?\s*"
        rf"([0-9]+(?:\.[0-9]+){{0,2}})"
        rf"\s*(\+|or (?:later|newer|above|higher)|and (?:above|later))?",
        re.I)
    for name, pattern in _FLOOR_LANGS.items()
}
_FLOOR_SUFFIXES = {"+", "or later", "or newer", "or above", "or higher",
                   "and above", "and later"}
_FLOOR_OPERATORS = {">=", ">", "^", "~"}

# Where each ecosystem declares its own floor, and what that declaration
# actually DOES. The enforcement column is not decoration: it decides the
# wording of the finding. A contradiction is a contradiction either way, but
# the text must not say an install will fail where the ecosystem says it will
# not.
_FLOOR_MANIFESTS: tuple[tuple[str, str, str, str], ...] = (
    ("Python", "pyproject.toml",
     r"^\s*requires-python\s*=\s*[\"']([^\"']+)[\"']",
     "pip refuses to install"),
    ("Python", "setup.cfg", r"^\s*python_requires\s*=\s*(.+)$",
     "pip refuses to install"),
    ("Node", "package.json", r"[\"']node[\"']\s*:\s*[\"']([^\"']+)[\"']",
     "npm warns unless engine-strict is set"),
    ("Rust", "Cargo.toml",
     r"^\s*rust-version\s*=\s*[\"']([^\"']+)[\"']",
     "cargo errors at build"),
    ("Go", "go.mod", r"^go\s+([0-9.]+)\s*$",
     "the go toolchain downloads a newer version by default"),
    ("PHP", "composer.json", r"[\"']php[\"']\s*:\s*[\"']([^\"']+)[\"']",
     "composer refuses to install"),
    ("Ruby", "*.gemspec",
     r"required_ruby_version\s*=\s*[\"']([^\"']+)[\"']",
     "the gem refuses to install"),
)

_FLOOR_LOWER = re.compile(r"(?:>=|\^|~>?|>)?\s*([0-9]+(?:\.[0-9]+){0,2})")

# A short line ending in a colon, which introduces the list beneath it.
_LABEL_LINE = re.compile(r"^\*{0,2}([A-Za-z][A-Za-z0-9 /_-]{2,40})\*{0,2}:$")


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part.isdigit())


def _declared_floor(spec: str) -> tuple[int, ...] | None:
    """The lowest version a manifest specifier admits.

    Only the FIRST bound is read: `>=3.9,<4.0` has floor 3.9, and folding the
    upper bound in would report every capped manifest as disagreeing with
    every document.

    A DISJUNCTION returns None, which makes the site not-examined rather than
    guessed. vite declares `^20.19.0 || >=22.12.0`; taking the first branch
    would report a document saying "Node 22+" as wrong when the manifest
    admits it. No corpus repository exercised this, so it is unmeasured rather
    than safe, and a rule that stays silent where it cannot decide is the
    whole point of this tool.
    """
    if not spec or "||" in spec:
        return None
    match = _FLOOR_LOWER.search(spec.split(",")[0].strip())
    return _version(match.group(1)) if match else None


def _manifest_floors(repo: Path) -> dict[str, tuple[str, str, str]]:
    """Each ecosystem's declared floor: language -> (spec, file, enforcement).

    Memoised per repository for the lifetime of a validate() call, like every
    other repository fact here. A sweep asks this once per document otherwise,
    and the answer cannot change between them.
    """
    key = str(repo)
    if key in _SCOPE.manifest_floors:
        return _SCOPE.manifest_floors[key]
    found: dict[str, tuple[str, str, str]] = {}
    for language, filename, pattern, enforcement in _FLOOR_MANIFESTS:
        if language in found:
            continue
        candidates = sorted(repo.glob(filename)) + sorted(
            repo.glob(f"*/{filename}"))
        for path in candidates:
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            match = re.search(pattern, content, re.M)
            if match:
                relative = str(path.relative_to(repo)).replace("\\", "/")
                found[language] = (match.group(1).strip(), relative,
                                   enforcement)
                break
    _SCOPE.manifest_floors[key] = found
    return found


def _floor_claims(repo: Path, text: str
                  ) -> list[tuple[int, str, tuple[int, ...], tuple[int, ...]]]:
    """Floor statements this rule would actually inspect in this document.

    The DENOMINATOR, and it is counted after the keying rather than before, so
    a README stating no floor reports 0 examined rather than a quiet pass. The
    rule speaks about roughly 13% of repositories, which makes silence its
    normal output and the denominator the only way to tell a working rule from
    a broken one.

    Returns (line number, language, stated floor, declared floor) per claim,
    with both versions already parsed and known comparable.
    """
    document = _current_document()
    if document is None or not _ENTRY_DOC.search(document):
        return []
    if _HISTORICAL_DOC.search(document):
        return []
    floors = _manifest_floors(repo)
    if not floors:
        return []
    claims: list[tuple[int, str, tuple[int, ...], tuple[int, ...]]] = []
    label = ""
    for number, raw in enumerate(_prose(text).splitlines(), start=1):
        line = raw.strip()
        if _HEADING.match(line):
            # A new section RETIRES the previous label. Without this, every
            # later floor in the document reads as though it were introduced
            # by a "Requirements:" line several sections above it.
            label = ""
            continue
        if _LABEL_LINE.match(line):
            label = line.rstrip(":")
            continue
        operative = bool(_FLOOR_VERB.search(line)) or bool(
            _FLOOR_LABEL.match(label))
        if not operative or _FLOOR_THIRD_PARTY.search(line):
            continue
        seen: set[tuple[str, str]] = set()
        for language, pattern in _FLOOR_CLAIM.items():
            if language not in floors:
                continue
            for match in pattern.finditer(line):
                operator, version, suffix = match.groups()
                stated = (suffix or "").strip().lower()
                if operator not in _FLOOR_OPERATORS and (
                        stated not in _FLOOR_SUFFIXES):
                    continue
                if (language, version) in seen:
                    continue
                spec = floors[language][0]
                declared = _declared_floor(spec)
                stated = _version(version)
                # A site the rule CANNOT DECIDE is not examined. Both sides
                # must state the same precision - "Node 18" against `>= 18`
                # is two coarse statements with nothing to compare - and a
                # disjunction is undecidable by construction. Counting these
                # would report coverage that does not exist, which this file
                # already argues is worse than no denominator at all.
                if declared is None or len(stated) < 2 or len(declared) < 2:
                    continue
                seen.add((language, version))
                claims.append((number, language, stated, declared))
    return claims


def validate_manifest_floors(repo: Path, text: str) -> list[Finding]:
    """A documented version floor against the manifest that declares it.

    Both operands live in this repository and both are declarative, so this
    asks whether two files CONTRADICT EACH OTHER - the question
    `validate_consistency` already established as legal - rather than whether
    a number is correct, which is the question no rule here may ask.

    Only entry-point documents are read. The same statement in a changelog is
    a historical record: "Aider now requires Python >= 3.9" was true the day
    it was written, and the manifest moving on does not make it false.
    """
    findings: list[Finding] = []
    floors = _manifest_floors(repo)
    # Comparability was settled in `_floor_claims`, so every claim reaching
    # here is one the rule can decide. That is deliberate: the denominator and
    # this loop must agree on what "examined" means, or the two numbers
    # describe different populations.
    for number, language, stated, declared in _floor_claims(repo, text):
        if stated == declared:
            continue
        spec, filename, enforcement = floors[language]
        version = ".".join(str(part) for part in stated)
        findings.append(Finding(
            number, "manifest-floor-mismatch",
            f"states {language} {version}, but `{filename}` declares "
            f"`{spec}`; the two contradict each other, and {enforcement}",
            subject=f"{language} {version}"))
    return findings


# --- line pointers ------------------------------------------------------
#
# `core/engine.py:123` where that file has 40 lines. Derived from a
# 39-repository corpus measured 2026-08-04: 7,775 candidate sites, of which
# 6,525 sit outside a code block, 51 name a file this repository actually
# tracks, and 3 cite a line past its end. All three were real - plan documents
# instructing an implementer to edit a line of a file that has since shrunk.
#
# The narrow claim is deliberate. This does NOT ask whether line 123 still
# holds what the document says, which would be judging content and is the
# question no rule here may ask. It asks whether the file has that many lines.
#
# The 6,474 pointers naming something this repository does not track are left
# alone. They are pasted stack traces, third-party paths and example output,
# and whether a path exists is already `dead-path-pointer`'s question - asking
# it again here would report the same fault twice under two names.
_LINE_POINTER = re.compile(
    r"(?<![\w/.\\-])"
    r"((?:[\w.\-]+[/\\])*[\w.\-]+\.[A-Za-z]\w{0,9})"
    r":(\d{1,6})"
    r"(?![\w.])")
# Two narrowings the pattern makes silently, recorded so they are choices
# rather than accidents:
#
# A RANGE is read by its start. `SKILL.md:211-215` is checked at 211, so a
# file of 213 lines is not reported even though 214 and 215 are missing.
# Firing only when the FIRST cited line is already past the end keeps the
# claim unarguable; widening it to the range end is a separate measurement.
#
# Six digits at most. A line number of 1,234,567 does not match at all,
# rather than matching its first six digits and judging the wrong line.
# Documents citing a line past a million are not a population this was
# measured against.

# A generated bundle or a vendored blob is not something a document points
# into, and reading one per pointer is the only cost this rule can incur.
_LINE_COUNT_LIMIT = 2_000_000


def _line_count(repo: Path, relative: str) -> int | None:
    """Lines in a tracked file, or None when it cannot be counted here.

    None means "do not judge": the path is absent, unreadable, or too large to
    be worth reading. A rule that treated None as zero would report every
    binary and every missing file as a pointer past the end.

    Counted in BINARY mode. Decoding first would make a file with one invalid
    byte unreadable, and the question here is how many newlines it has, which
    does not need the text. Memoised for the lifetime of a validate() call,
    like every other repository fact: a document citing forty lines of one
    file would otherwise read it forty times.
    """
    key = f"{repo}\0{relative}"
    if key in _SCOPE.linecount:
        return _SCOPE.linecount[key]
    count: int | None = None
    target = repo / relative
    try:
        if target.is_file() and target.stat().st_size <= _LINE_COUNT_LIMIT:
            with open(target, "rb") as handle:
                count = sum(1 for _ in handle)
    except (OSError, ValueError):
        count = None
    _SCOPE.linecount[key] = count
    return count


# Identity-keyed like `_STRIPPED` and `_BARE_SHAS`, and for the same reason: the
# rule and the denominator ask for the same document's sites in the same pass.
# The repo and the format are compared as well, because unlike those two this
# reads both - a cache that ignored them would answer a question it was never
# asked. Measured on pytest's 308 documents: 617 calls, 1.19s.
_POINTER_SITES: tuple[str, Path, str, list[tuple[int, str, int, int]]] | None = None


def _line_pointer_sites(repo: Path, text: str) -> list[tuple[int, str, int, int]]:
    """Pointers this rule can actually decide, as (line, target, cited, total).

    The DENOMINATOR, computed exactly where the rule computes its findings, so
    the two describe one population. A pointer whose target this repository
    does not track is not counted: the rule cannot decide it, and reporting
    coverage it does not have is worse than reporting none.
    """
    global _POINTER_SITES
    if (_POINTER_SITES is not None and _POINTER_SITES[0] is text
            and _POINTER_SITES[1] == repo
            and _POINTER_SITES[2] == _DOC.doc_format):
        return _POINTER_SITES[3]
    sites = _line_pointer_sites_uncached(repo, text)
    _POINTER_SITES = (text, repo, _DOC.doc_format, sites)
    return sites


def _line_pointer_sites_uncached(
        repo: Path, text: str) -> list[tuple[int, str, int, int]]:
    sites: list[tuple[int, str, int, int]] = []
    for number, line in enumerate(_prose(text).splitlines(), start=1):
        for match in _LINE_POINTER.finditer(line):
            raw, cited = match.group(1), int(match.group(2))
            if cited < 1:
                continue
            exists, _actual = _resolve_reference(repo, repo, raw)
            if not exists:
                continue
            total = _line_count(repo, raw)
            if total is None:
                continue
            sites.append((number, raw, cited, total))
    return sites


def validate_line_pointers(repo: Path, text: str) -> list[Finding]:
    """A cited line number that is past the end of the file it cites.

    The file is here and git tracks it; the line is not. That is settled by
    counting newlines, and nothing about it is a judgement.

    Whole-file and in the archive, like path pointers: a pointer is an
    instruction at any age, and retiring the entry that holds it does not make
    line 211 of a 167-line file exist.
    """
    findings: list[Finding] = []
    for number, raw, cited, total in _line_pointer_sites(repo, text):
        if cited <= total:
            continue
        findings.append(Finding(
            number, "dead-line-pointer",
            f"points at `{raw}:{cited}`, but that file has {total} line"
            f"{'' if total == 1 else 's'}",
            subject=f"{raw}:{cited}"))
    return findings


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
        # An EMPTY file is not a violation. git-lfs passes zero bytes through
        # unchanged rather than writing a pointer, because there is nothing to
        # store, so a 0-byte blob under a filter is LFS behaving correctly.
        #
        # Verified rather than assumed: committing an empty file and a real one
        # under the same filter produces a 0-byte blob and a 126-byte pointer.
        # Measured on o3de/o3de, which declares 123 filters over 2,948 governed
        # files - 44 of its 45 findings were empty test fixtures, and the only
        # true one was an asset planted to check the rule still fires.
        if size == 0:
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


# A letter is required now that an all-digit run reads as a number rather than
# a commit, so forty zeroes would be corrupted into something no rule looks at
# and `--selftest` would report dead-sha silent when the rule was fine.
_DEAD_SHA = "dead" + "0" * 36
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
        out = _GIT.run(repo, "rev-list", "--all", "--not", *excluded, "-n", "1")
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
    # For a REPOSITORY-scoped rule: the repo-relative file that DECLARES
    # the claim being checked. Such a finding is about the repository and
    # belongs to no document, so a sweep has nothing to attribute it to;
    # `--verify` prints it under whichever document happened to be in hand,
    # which is the primary one. Naming the declaring file is more useful
    # than either. Left None for document-scoped rules, which carry their
    # own path already.
    subject_file: str | None = None


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
    # Computed from PROSE, because that is what the rules read. Six of them
    # open with `text = _prose(text)` - claims inside code are examples, not
    # promises - and counting the raw document reported candidates no rule ever
    # looked at. Measured 2026-08-04: rust-lang/rfcs reported `dead-sha 23`
    # where the rule read 11, so more than half that denominator was fenced
    # example output. An overstated denominator is the worst of the three
    # numbers available: it is the one that reassures.
    prose = _prose(text)
    backticked = len(find_sha_candidates(prose))
    bare = len(find_bare_sha_candidates(prose))
    _, segments, _ = split_entries(prose)
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
        "false-merge-claim": len(_MERGE_CLAIM.findall(prose)),
        "dead-release-tag": len(_RELEASE_TAG.findall(prose)),
        "dead-path-pointer": len(_PATH_POINTER.findall(prose)),
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
        # Counted AFTER the keying, not before: a README stating no floor
        # reports 0 examined. This rule speaks about roughly 13% of
        # repositories, so silence is its normal output and the denominator
        # is the only thing separating a working rule from a broken one.
        "manifest-floor-mismatch": len(_floor_claims(repo, text)),
        # Pointers whose target this repository tracks and can count. One
        # naming a file we do not have is not counted: the rule cannot
        # decide it, and `dead-path-pointer` already asks whether a path
        # exists. On a 39-repository corpus that was 51 of 6,525.
        "dead-line-pointer": len(_line_pointer_sites(repo, text)),
    }


def _probe_manifest_floor(repo: Path, text: str) -> str | None:
    """Repoint a real floor statement at a version no manifest can declare.

    Located BY LINE rather than by pattern. `_sub_group` corrupts the first
    match anywhere in the document, and the first "Python 3.9" in a file is
    usually a mention rather than the operative claim the rule reads - so a
    pattern-located probe would corrupt something the rule never looks at and
    then report that the rule did not fire.

    Returns None when this document states no floor the rule would read, which
    is the ordinary case: a status document names no version floor. `--selftest`
    reports that as NO PROBE rather than as a pass. This rule is proven instead
    by its unit tests and by an acceptance run over the measurement corpus.
    """
    claims = _floor_claims(repo, text)
    if not claims:
        return None
    number, language, _stated, _declared = claims[0]
    lines = text.splitlines(keepends=True)
    index = number - 1
    if index >= len(lines):
        return None
    match = _FLOOR_CLAIM[language].search(lines[index])
    if match is None:
        return None
    start, end = match.span(2)
    # 0.0 disagrees with every real floor and still states two components, so
    # it survives the precision guard rather than being skipped as coarse.
    lines[index] = lines[index][:start] + "0.0" + lines[index][end:]
    return "".join(lines)


def _probe_line_pointer(repo: Path, text: str) -> str | None:
    """Push a real line pointer past the end of the file it names.

    Located BY LINE, like the manifest probe: the first `path:number` in a
    document is often inside a transcript that the rule never reads, so a
    pattern-located probe would corrupt something invisible and then report
    that the rule did not fire.

    Returns None when this document cites no line of a file this repository
    tracks, which is the ordinary case.
    """
    sites = _line_pointer_sites(repo, text)
    if not sites:
        return None
    number, raw, cited, total = sites[0]
    lines = text.splitlines(keepends=True)
    index = number - 1
    if index >= len(lines):
        return None
    needle = f"{raw}:{cited}"
    if needle not in lines[index]:
        return None
    lines[index] = lines[index].replace(needle, f"{raw}:{total + 9999}", 1)
    return "".join(lines)


# THE ADMISSION TEST for anything added here: it must answer a yes/no question
# to git or the filesystem, and produce zero false positives on the real corpus.
# A rule that inspects numbers or dates fails it - historical facts are true
# when written and stale forever after, so checking them cries wolf, and a
# validator that cries wolf stops being read.
RULES: tuple[Rule, ...] = (
    Rule(
        kind="dead-line-pointer",
        check=validate_line_pointers,
        scope="whole-file",
        in_archive=True,
        falsifiable="does the cited file have at least that many lines?",
        probe=_probe_line_pointer,
    ),
    Rule(
        kind="manifest-floor-mismatch",
        check=validate_manifest_floors,
        scope="whole-file",
        # Whole-file, so never archive-exempt: the exemption tracks scope
        # exactly and `test_only_non_whole_file_rules_are_archive_exempt`
        # pins that. The flag is moot in practice anyway - what limits this
        # rule is `_ENTRY_DOC`, and an archive is never an entry-point
        # document. A floor offered to a reader is a promise at any age.
        in_archive=True,
        falsifiable="does the manifest for this ecosystem declare a different "
                    "floor than this document states?",
        probe=_probe_manifest_floor,
    ),
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
        subject_file=".extant.toml",
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
        subject_file=".gitattributes",
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


def _rule_applies(rule: Rule, in_archive: bool, has_entries: bool) -> bool:
    """Whether `rule` reads a document in this position.

    ONE definition, because two callers ask the question: the loop that
    produces findings, and the sweep's per-rule denominator. Answered
    separately they drift, and drift UPWARD is the worst of the outcomes -
    a denominator that counts candidates no rule looked at reports coverage
    that was never provided, which is the reassuring number rather than the
    honest one, and is precisely the failure a denominator exists to prevent.

    Reads the current document's FORMAT, so the caller must set the document
    in hand before asking.
    """
    primary = not in_archive and has_entries
    if rule.scope == "repository" and not primary:
        # Repository-wide, so it must not be repeated for the archive and
        # every extra document; the disagreement is the same one. A sweep
        # runs these once outside its document loop instead.
        return False
    if (in_archive or not has_entries) and not rule.in_archive:
        return False
    if _DOC.doc_format != "markdown" and rule.kind in _MARKDOWN_ONLY:
        # Not tuned for the format, skipped for it. `[text](url)` is
        # markdown's syntax; where it does not exist, every match is
        # something else wearing its shape.
        return False
    return True


@contextmanager
def run_scope() -> Iterator[RunScope]:
    """Hold ONE RunScope across several calls that read one static checkout.

    `validate()` opens a scope per call and drops it on the way out, which is
    right for a caller that validates one document and stops. It is wrong for
    the two-call shape every mode actually uses: `validate()` answers WHAT IS
    WRONG and `count_examined()` answers OUT OF HOW MANY, over the same
    document and the same checkout, and the second call was re-asking git what
    the first had already learned. Measured on this repository's own document,
    `--verify` spawned `git remote get-url origin` twice, once per half, out of
    seven git processes for one file.

    NOT opened by `validate()` itself, and that is the point rather than an
    omission. A scope validate() installed and left behind would outlive the
    call that owns it, which is precisely the lifetime bug these objects exist
    to make unrepresentable - and it has already been paid for once, when a
    remote memo with no lifetime made `dead-pinned-ref` examine nothing and
    report clean. The caller that knows two calls belong to one run says so.

    `stable=True`, because that is the flag `validate()` reads to decide
    whether the scope is its own or somebody else's. It carries the promise
    documented on the field: the checkout does not change and nothing inside
    writes to it. `--verify` therefore wraps each document's two halves
    separately rather than the whole run, because it rewrites documents between
    them when `--sha-map` is given.
    """
    global _SCOPE, _POINTER_SITES
    previous_scope = _SCOPE
    _SCOPE = RunScope(stable=True)
    _SCOPE.dircache = {}
    _POINTER_SITES = None
    try:
        yield _SCOPE
    finally:
        # Handed back on the failing path too. A crash inside that left the
        # process holding a scope with no owner would make every later
        # validate() answer from a checkout that has moved on, and the happy
        # path restores it either way - which is what makes this the half that
        # is easy to write without and never notice.
        _SCOPE = previous_scope
        # Dropped rather than restored, with the scope it was derived from. It
        # is deliberately NOT cleared per document inside the scope - counting
        # one file's lines once for a whole survey is the point, and
        # `scope.linecount` rides along - but holding it past the scope would
        # answer from a checkout that may have moved on.
        _POINTER_SITES = None


def validate(repo: Path, text: str, *, in_archive: bool = False,
             has_entries: bool = True, base: Path | None = None,
             doc: str | None = None) -> list[Finding]:
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
    global _SCOPE, _DOC, _POINTER_SITES
    outer_scope, outer_doc = _SCOPE, _DOC
    # A fresh scope per call, unless a caller has declared the repository static
    # and taken ownership of this one. The nesting bug the old block existed to
    # prevent cannot be written here: a nested call gets its OWN object, so the
    # outer call's answers are not cleared, not half-cleared, and not dependent
    # on this function remembering to put them back.
    scope = outer_scope if outer_scope.stable else RunScope()
    # Only what the caller actually SAID is overridden. `doc_format` is never a
    # parameter and is inherited unchanged, because `deleted_claims` and
    # `run_sweep` set it around the call rather than through it - deriving it
    # from `doc` here would silently re-read a `.rst` document as markdown.
    document = DocScope(
        link_base=base if base is not None else outer_doc.link_base,
        doc_format=outer_doc.doc_format,
        doc_path=doc if doc is not None else outer_doc.doc_path)
    # Built here and read immediately below. Task 9 hands this to every rule
    # instead, at which point the two installs it feeds go away with the last
    # module-level scope name.
    context = Context(config=_ACTIVE, run=scope, doc=document, repo=repo, git=_GIT)
    _SCOPE, _DOC = context.run, context.doc
    # Everything below applies to a scope THIS call opened. When the two are the
    # same object a caller has declared the repository static for the duration
    # of many documents and taken ownership of these caches, and touching them
    # here would rebuild the same answers per document - which is precisely what
    # the scope exists to stop. See `RunScope.stable`.
    #
    # That used to be an empty `if` branch with the reasoning in it and an
    # `else` doing the work, which is one more way to write the wrong thing.
    if scope is not outer_scope:
        # Directory listings may be reused for the duration of this call and
        # no longer. The fresh scope above already carries None, so this only
        # has to say that caching is ON for the duration; nothing has to put
        # anything back, because the object itself is dropped on the way out.
        scope.dircache = {}
        # Dropped WITH `scope.linecount`, because it is derived from it.
        # Identity keying alone would be wrong here: a caller validating the
        # same text object twice across a changed checkout is exactly what a
        # fresh `linecount` exists to handle, and a sites cache that outlived
        # it would answer from the checkout that moved on.
        #
        # This is the one memo that could not become a scope FIELD, and the
        # reason is the mirror image of why it has to be dropped here: the
        # caller that needs it, `count_examined`, runs immediately AFTER this
        # returns, by which point a call-scoped value is gone. Tying it to the
        # scope would discard the entry the rules just computed, which is the
        # version that was written first and silently halved nothing. So it is
        # invalidated when a fresh scope opens and deliberately left alone when
        # the call ends - exactly the asymmetry it has always had, now with one
        # name instead of thirteen around it.
        _POINTER_SITES = None
    try:
        findings: list[Finding] = []
        for rule in RULES:
            if not _rule_applies(rule, in_archive, has_entries):
                continue
            findings += rule.check(repo, text)  # type: ignore[operator]
        return findings
    finally:
        _SCOPE, _DOC = outer_scope, outer_doc


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


def _baseline_entry(item: Located, count: int = 1) -> dict[str, object]:
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
        # How many occurrences this amnesty covers. The fingerprint excludes
        # the line number so that reflowing a paragraph does not un-suppress
        # everything, and the price of that was forgiving the same claim pasted
        # anywhere, forever. Bounding the count keeps the churn-immunity and
        # removes the unbounded part.
        "count": count,
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
    # Grouped by fingerprint, not one entry per occurrence. A baseline is a
    # list of things a project has agreed to leave broken and it is read in
    # review, so a repeated claim must stay one legible line with a count.
    tally: dict[str, int] = {}
    first: dict[str, Located] = {}
    for item in located:
        key = _fingerprint(item.path, item.finding.kind, item.finding.detail)
        tally[key] = tally.get(key, 0) + 1
        first.setdefault(key, item)
    entries = [_baseline_entry(first[key], tally[key]) for key in sorted(tally)]
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
    """GitHub Actions annotations, which surface inline on the pull request.

    The severity mirrors the exit code, exactly as SARIF's does. A survey
    finding is a `notice`: `--sweep` and `--deleted-since` both exit 0 by
    design, and annotating them as errors put red marks on a pull request for
    claims the tool had already decided could not fail it.

    This was fixed in SARIF first and missed here for one commit, which is the
    cheaper half of the same lesson: when a misrepresentation is found in one
    output, the sibling formats are where to look next.
    """
    lines = []
    for item in located:
        level = "error" if item.gating else "notice"
        lines.append(
            f"::{level} file={_gh_escape(item.path, prop=True)},"
            f"line={item.finding.line},"
            f"title={_gh_escape(item.finding.kind, prop=True)}"
            f"::{_gh_escape(item.finding.detail)}"
        )
    return lines


def format_sarif(located: list[Located], repo: Path | None = None, *,
                 examined: dict[str, int] | None = None,
                 run_kind: str = "verify") -> str:
    """SARIF 2.1.0, the format code-scanning tools interchange.

    The rule descriptors are generated from the registry, so a rule's
    `falsifiable` question becomes its published description. That is the same
    field the admission test already requires, which means a rule cannot reach
    this output without having stated the exact question it asks.

    `repo` and `examined` are optional so the function stays callable with a
    bare list, which is how the tests exercise it. Their absence costs
    presentation and the denominator, never correctness.
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
            "name": "".join(part.title() for part in kind.split("-")),
            "shortDescription": {"text": kind.replace("-", " ")},
            "fullDescription": {"text": f"Checks: {question}"},
            "help": {
                "text": f"This finding is falsifiable: {question}",
                # GitHub renders the markdown on the alert page and falls back
                # to `text` elsewhere, so both are supplied rather than one.
                "markdown": (
                    f"**{kind}**\n\n"
                    f"This finding is falsifiable, and the question it asks is:\n\n"
                    f"> {question}\n\n"
                    "No rule here judges whether a value is *correct* - only "
                    "whether something a document names still exists or still "
                    f"holds. See [the rule table]({_TOOL_URI}#what-it-covers)."
                ),
            },
            "helpUri": f"{_TOOL_URI}#what-it-covers",
            # Findings that reach `--verify` decide its exit code, so error is
            # the right DEFAULT. A survey result overrides it per result below.
            "defaultConfiguration": {"level": "error"},
            "properties": {
                "tags": ["documentation", rule.scope if rule else "unknown"],
                # Honest rather than flattering: the admission test requires
                # zero false positives on a real corpus before a rule ships.
                "precision": "very-high",
                "problem.severity": "error",
            },
        })

    results = []
    for item in located:
        region: dict[str, object] = {"startLine": max(1, item.finding.line)}
        snippet = _sarif_snippet(repo, item)
        if snippet is not None:
            # The subject is the bare token the claim is about, so pointing at
            # it turns "somewhere on line 12" into the claim itself underlined.
            # Computed against the FULL line, because SARIF columns are offsets
            # into the artifact rather than into the snippet.
            subject = item.finding.subject
            if subject and subject in snippet:
                at = snippet.index(subject)
                # UTF-16 CODE UNITS, because `columnKind` above says so. Python
                # indexes by code point, and the two differ for anything
                # outside the BMP: one emoji before the token shifts every
                # column after it by one. Measured on the corpus, 47 markdown
                # files carry 156 non-BMP characters, so this is a real
                # off-by-N rather than a theoretical one - and declaring a
                # column kind the numbers do not follow is worse than
                # declaring none.
                start = _utf16_len(snippet[:at]) + 1
                width = _utf16_len(subject)
            else:
                start = width = 0
            if 0 < start <= _SARIF_SNIPPET_LIMIT - width:
                region["startColumn"] = start
                region["endColumn"] = start + width
            if len(snippet) > _SARIF_SNIPPET_LIMIT:
                snippet = snippet[:_SARIF_SNIPPET_LIMIT] + " ..."
            region["snippet"] = {"text": snippet}
        results.append({
            "ruleId": item.finding.kind,
            "ruleIndex": seen.index(item.finding.kind),
            # A survey finding is reported and never gates. Publishing it as an
            # error contradicted the exit code and the README both.
            "level": "error" if item.gating else "note",
            "message": {"text": item.finding.detail},
            "partialFingerprints": {
                "statusClaim/v1": _fingerprint(
                    item.path, item.finding.kind, item.finding.detail),
            },
            "properties": {"gates": item.gating},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": item.path},
                    "region": region,
                },
            }],
        })

    run: dict[str, object] = {
        "tool": {"driver": {
            "name": "extant",
            "informationUri": _TOOL_URI,
            "rules": descriptors,
        }},
        # Lets a sweep upload and a verify upload sit side by side in code
        # scanning instead of one silently replacing the other.
        "automationDetails": {"id": f"extant/{run_kind}"},
        "columnKind": "utf16CodeUnits",
        "results": results,
    }
    if examined is not None:
        # THE DENOMINATOR. Every other output states what was examined, and
        # this one did not: a consumer seeing zero results could not tell a
        # clean repository from a run that checked nothing. SARIF carries it as
        # a notification rather than a result, because it is not a finding.
        summary = ", ".join(f"{kind} {n}" for kind, n in examined.items())
        blind = [kind for kind, n in examined.items() if n == 0]
        run["invocations"] = [{
            "executionSuccessful": True,
            "toolExecutionNotifications": [
                {"level": "note",
                 "message": {"text": f"examined: {summary}"}},
                *([{"level": "warning",
                    "message": {"text":
                                "examined nothing, so these rules report "
                                "nothing either: " + ", ".join(blind)}}]
                  if blind else []),
            ],
        }]
        run["properties"] = {"examined": examined}

    return json.dumps({
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [run],
    }, indent=2)


# A snippet exists to give an alert context, and no reader needs more than a
# line's worth. Uncapped it is an upload hazard: the longest single markdown
# line in the 39-repository corpus is 123,427 characters, and GitHub rejects a
# SARIF upload over 10 MB. One base64 image or minified block on a cited line
# would have been enough.
_SARIF_SNIPPET_LIMIT = 400


def _utf16_len(text: str) -> int:
    """Length in UTF-16 code units, which is what SARIF columns count.

    A character outside the Basic Multilingual Plane - an emoji, most of the
    rarer CJK - is one Python character and TWO UTF-16 code units. Anything
    that indexes with `len()` and then declares `columnKind` as
    `utf16CodeUnits` is quietly wrong past the first such character.
    """
    return len(text) + sum(1 for ch in text if ord(ch) > 0xFFFF)


def _sarif_snippet(repo: Path | None, item: Located) -> str | None:
    """The cited line, so an alert shows the claim rather than a line number.

    Optional because `format_sarif` is called in tests and by callers that
    have no repository in hand. A missing snippet costs presentation; a WRONG
    one would misreport where a finding is, so anything unreadable returns
    None rather than a guess.
    """
    if repo is None or item.finding.line < 1:
        return None
    try:
        with open(repo / item.path, encoding="utf-8", errors="replace",
                  newline="") as fh:
            for number, line in enumerate(fh, start=1):
                if number == item.finding.line:
                    return line.rstrip("\r\n")
    except OSError:
        return None
    return None


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


def run_sweep(repo: Path, fmt: str) -> int:
    """Survey every tracked markdown file. Returns the exit code.

    The first-run command: it needs no configuration, writes nothing, and
    answers "what is rotting in here". Reproducing this by hand meant a shell
    loop over `ls-files`, which is not an answer anyone finds on their own.

    Two sections, because they mean different things. Vetted documents are the
    ones configuration names, and findings there GATE - that is the same
    promise `--verify` makes. Unvetted documents have never been reviewed, so
    they are surveyed and reported and deliberately do not affect the exit
    code; see `partition_documents` for the measurement behind that.

    Entry-scoped rules are skipped everywhere except the primary document, for
    the reason `extra_docs` skips them: an arbitrary markdown file has no dated
    entries, so "the newest entry" is a category error rather than a pass.
    """
    global _DOC
    try:
        paths = tracked_markdown(repo)
    except (subprocess.CalledProcessError, OSError):
        # An UNBORN HEAD has no tree to list, so `git ls-tree HEAD` exits
        # 128 and the error reached the user as a traceback. A repository
        # someone has just created is a legitimate thing to point a
        # first-run survey at, and the honest answer is the same one a
        # repository with no markdown gets.
        paths = []
    if not paths:
        print("swept 0 markdown files: git tracks none in this repository",
              file=sys.stderr)
        return 0

    tracked_total = len(paths)
    excluded_counts: dict[str, int] = {}
    if CONFIG.exclude_paths:
        present = {p.replace("\\", "/") for p in paths}
        paths, excluded_counts = excluded_documents(paths, CONFIG.exclude_paths)
        # A CONFIGURED document that an exclusion REMOVED is a contradiction,
        # not a preference: one setting says gate on this file and another
        # says never read it. Reported rather than resolved, because either
        # answer silently overrides something the author wrote.
        #
        # Keyed on what was actually removed, never on "configured but
        # missing". `primary_doc` defaults to a filename most repositories do
        # not have, so comparing against the configured set alone reported a
        # conflict for a document no exclusion had touched - a different
        # condition, which `--verify` already names as "no such document".
        configured = {CONFIG.primary_doc.replace("\\", "/"),
                      *(d.replace("\\", "/") for d in CONFIG.extra_docs)}
        kept = {p.replace("\\", "/") for p in paths}
        conflicting = sorted((configured & present) - kept - {""})
        for document in conflicting:
            print(f"CONFLICT: `{document}` is configured to be checked and "
                  f"also matches exclude_paths; excluding it would silently "
                  f"stop gating on a document you asked to gate on",
                  file=sys.stderr)
        if conflicting:
            return 1
    if not paths:
        print(f"swept 0 markdown files: exclude_paths removed all "
              f"{tracked_total} that git tracks", file=sys.stderr)
        return 0

    vetted, unvetted = partition_documents(repo, paths)
    primary = CONFIG.primary_doc.replace("\\", "/")
    sections: list[tuple[str, list[str], bool]] = [
        ("vetted", vetted, True), ("unvetted", unvetted, False)]
    results: dict[str, list[Located]] = {"vetted": [], "unvetted": [],
                                         "repository": []}
    unreadable: list[str] = []

    # One scope for the whole survey, from the one place that opens one.
    # Every document here is read from the same checkout and nothing below
    # writes to it, so the answers `validate()` otherwise rebuilds per document
    # - directory listings, ancestry indexes, resolved refs, other documents'
    # headings - are the same answers every time.
    #
    # The DOCUMENT is per-file rather than per-scope, and it is saved here
    # because the loop below replaces it. Restoring it only after the loop left
    # it holding the last swept document whenever a rule raised, so the next
    # validation in the process resolved relative links against a directory it
    # never chose. Cheap to get right, invisible when wrong.
    previous_document = _DOC
    with run_scope():
        try:
            # Seeded here, inside the stable scope, for two reasons at once: it
            # fixes the printing ORDER to the one `--verify` uses, so the two modes
            # can be read side by side, and its repository-scoped entries are the
            # counts those rules get - they are the repository's candidates, not
            # any document's, so they are read once rather than per file.
            repository_examined = count_examined(repo, "")
            examined: dict[str, int] = {kind: 0 for kind in repository_examined}
            for label, group, _gates in sections:
                for relative in group:
                    path = repo / relative
                    try:
                        with open(path, encoding="utf-8", newline="") as fh:
                            text = fh.read()
                    except (OSError, UnicodeDecodeError) as exc:
                        # Counted and named, never skipped quietly. A file that
                        # could not be read is not a file with no findings, and
                        # printing the same thing for both is the conflation this
                        # tool is about.
                        unreadable.append(f"{relative} ({exc.__class__.__name__})")
                        continue
                    _set_document(link_base=path.parent,
                                  doc_format=_format_for(relative))
                    findings = validate(repo, text,
                                        has_entries=(relative == primary),
                                        doc=relative)
                    # `_gates` is the section's own flag: vetted documents decide
                    # the exit code, unreviewed ones are surveyed and reported.
                    # Carrying it here is what lets SARIF publish a survey finding
                    # as a note rather than an error.
                    results[label].extend(
                        Located(relative, f, primary=(relative == primary),
                                gating=_gates)
                        for f in findings)

                    # The denominator, per rule, summed over the survey. Counted
                    # only for rules that actually READ this document: a sweep
                    # skips entry-scoped rules outside the primary file and
                    # markdown-only rules for `.rst`, and `count_examined` knows
                    # nothing about either. Summing it whole would report link
                    # candidates in a document where no link rule ran.
                    counted = count_examined(repo, text)
                    for rule in RULES:
                        if rule.scope == "repository":
                            continue        # counted once, below
                        if _rule_applies(rule, False, relative == primary):
                            examined[rule.kind] += counted[rule.kind]

            # Repository-scoped rules answer a question about the REPOSITORY,
            # so they run ONCE here rather than inside the loop above.
            #
            # `validate` runs them only on the primary pass, which in a sweep
            # means the file named by `primary_doc` - and a swept repository
            # usually has no such file, because a sweep needs no configuration
            # at all. So both were silent in every sweep of nearly every
            # repository, and silently: a rule examining nothing and a rule
            # finding nothing print the same zero. It read as 0 / 0 across
            # three corpora and was taken for an absence of faults.
            #
            # The guard was right that one repository-wide disagreement must
            # not be repeated per document, and wrong about what "once" was
            # tied to. Running them here keeps the once and drops the document.
            for rule in RULES:
                if rule.scope != "repository":
                    continue
                # Repository findings are surveyed and never gate - the section
                # heading says "not gated" and the exit code honours it, so the
                # machine format must say the same thing.
                results["repository"].extend(
                    Located(rule.subject_file or ".", finding, primary=False,
                            gating=False)
                    for finding in rule.check(repo, ""))  # type: ignore[operator]
                examined[rule.kind] = repository_examined[rule.kind]
        finally:
            # The DOCUMENT only. The run scope hands itself back, on the
            # failing path too; this is the half that is per-file, and
            # restoring it only after the loop left the last swept document
            # installed whenever a rule raised.
            _DOC = previous_document

    # Diagnostics follow the convention the other modes use: stdout unless
    # SARIF, where stdout must carry nothing but one JSON value. Writing the
    # summary to stderr unconditionally interleaved it AHEAD of the findings,
    # because the two streams flush independently.
    out = sys.stderr if fmt == "sarif" else sys.stdout
    if fmt == "text":
        for label, heading in (
                ("vetted", "CONFIGURED - these decide the exit code"),
                ("unvetted", "UNREVIEWED - surveyed only, not gated"),
                ("repository", "REPOSITORY - about the repository itself, "
                               "not gated")):
            if results[label]:
                print(f"\n{heading}", file=out)
                for line in format_text(results[label]):
                    print(line, file=out)
    else:
        for line in render_findings(
                results["vetted"] + results["unvetted"]
                + results["repository"], fmt, repo,
                examined=examined, run_kind="sweep")[0]:
            print(line)

    # The denominator, per section. "0 findings" and "0 files looked at" print
    # identically without it, and a sweep is the mode where that is easiest to
    # get wrong: a wrong glob would report a clean repository.
    print(f"\nswept {len(paths)} markdown file(s): "
          f"{len(vetted)} configured ({len(results['vetted'])} finding(s)), "
          f"{len(unvetted)} unreviewed ({len(results['unvetted'])} finding(s))",
          file=out)
    # The skip-list's own denominator. A configured exclusion is the one
    # setting here that can make a repository look clean by not looking, so
    # what it removed is printed beside what was read - and a pattern that
    # matched NOTHING is named, because dead configuration reads exactly like
    # a working exclusion and survives every run until somebody counts.
    if excluded_counts:
        removed = sum(excluded_counts.values())
        print(f"  excluded {removed} of {tracked_total} tracked file(s) via "
              f"{len(excluded_counts)} exclude_paths pattern(s)", file=out)
        for pattern, count in sorted(excluded_counts.items()):
            print(f"    {count:5} {pattern}", file=out)
        idle = sorted(p for p, n in excluded_counts.items() if not n)
        if idle:
            print(f"  matched nothing, so they exclude nothing and may be "
                  f"stale: {', '.join(idle)}", file=out)
    # Counted separately, never folded into the document totals: these are
    # findings about the repository, and adding them to a per-file count would
    # report more findings than there are documents to hold them. A rule that
    # ran and found nothing now says so, which is the whole point - the count
    # of rules that RAN is the denominator the silence was hiding.
    repository_rules = sum(1 for rule in RULES if rule.scope == "repository")
    print(f"  {repository_rules} repository-wide rule(s) ran once "
          f"({len(results['repository'])} finding(s))", file=out)
    # One level finer, and the level that matters on a repository nobody here
    # has seen before. "swept 37 files" says the run happened; this says which
    # rules it REACHED. A rule whose pattern matches nothing anyone in this
    # project writes reports a clean survey in exactly the voice of a rule that
    # looked and found nothing, and eight coverage widenings were once measured
    # against 30 repositories where six of them had a denominator of zero.
    print("  examined: " + ", ".join(f"{kind} {n}"
                                     for kind, n in examined.items()), file=out)
    # Zero counts are REPORTED rather than filtered, and named again here. A
    # rule examining nothing across a WHOLE repository is a far stronger signal
    # than the same zero in one document, and it is the one a reader skimming a
    # 13-entry line will miss.
    blind = [kind for kind, n in examined.items() if n == 0]
    if blind:
        print("  NOTE: these rules examined nothing anywhere here - either no "
              "document makes such claims, or the pattern does not match how "
              "this project writes them: " + ", ".join(blind), file=out)
    if unreadable:
        print(f"  {len(unreadable)} could not be read: {', '.join(unreadable)}",
              file=out)
    if not vetted:
        print("  nothing is configured, so nothing here can fail. Set "
              "primary_doc or extra_docs in .extant.toml to gate on a file.",
              file=out)
    elif results["unvetted"]:
        print("  unreviewed findings do not affect the exit code. Some will be "
              "examples rather than claims; move a file into extra_docs once "
              "you have read them.", file=out)
    return 1 if results["vetted"] else 0


def _document_at(repo: Path, ref: str, relative: str) -> str | None:
    """A document as it stood at `ref`, or None if it was not there.

    A previous version that is not valid UTF-8 raises rather than returning
    None, because "absent" and "unreadable" are different facts and the caller
    counts them separately. Decoding it with errors="replace" would be worse
    than either: every rule would then run against silently corrupted text and
    report findings about bytes that are not there.
    """
    # BYTES, then decoded here. `_git` passes text=True, which makes
    # subprocess decode inside a reader THREAD - so invalid UTF-8 raises where
    # no caller can catch it. The observed result was the worst of both: a
    # UnicodeDecodeError traceback printed from the thread, the process
    # continuing, and the document silently counted as examining nothing.
    #
    # Decoding strictly, and letting the error reach the caller, is what makes
    # "unreadable" a fact this mode can report instead of a mess it prints.
    try:
        done = subprocess.run(["git", "show", f"{ref}:{relative}"], cwd=repo,
                              capture_output=True)
    except OSError:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8")


def _changed_between(repo: Path, ref: str, candidates: list[str]) -> list[str]:
    """Only the candidates that actually changed between `ref` and HEAD.

    A document that did not change cannot have lost a claim, so this is a
    correctness simplification as much as it is the difference between doubling
    a verify and not.

    A ref git cannot resolve yields an empty list rather than an exception: the
    mode reports what it examined, and examining nothing because the ref was
    wrong is a legitimate answer as long as the denominator says so.
    """
    try:
        out = _GIT.run(repo, "diff", "--name-only", ref, "HEAD")
    except (subprocess.CalledProcessError, OSError):
        return []
    changed = {line.strip().replace("\\", "/") for line in out.splitlines()
               if line.strip()}
    return [c for c in candidates if c.replace("\\", "/") in changed]


def _configured_documents() -> list[str]:
    """Primary, archive and extras, in that order, skipping any left unset."""
    return [d for d in (CONFIG.primary_doc, CONFIG.archive_doc,
                        *CONFIG.extra_docs) if d]


def _live_prose(repo: Path, documents: list[str]) -> str:
    """Every configured document's PROSE, concatenated, fenced code blanked.

    Prose, not raw text, and the distinction is the whole of condition 2 below.
    A claim moved into a code fence is exempt from every claim rule, so a
    haystack built from raw text would let a fence hide a claim from this mode
    as well as from the others.

    Inline backticks are kept, because a claim is normally written inside them
    and `_prose` blanks fences only. Using `_strip_code` here would blank the
    token in every claim and report the entire document as deleted.
    """
    parts = []
    for relative in documents:
        try:
            with open(repo / relative, encoding="utf-8", newline="") as handle:
                parts.append(_prose(handle.read()))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(parts)


def deleted_claims(repo: Path, ref: str) -> tuple[list[Located], int, int, int]:
    """Claims present at `ref`, false today, and no longer written anywhere.

    Returns (found, examined, skipped_for_no_subject, undecodable). All four
    come from ONE pass: computing any of them in a second loop would
    re-validate every document and double exactly the cost `_changed_between`
    exists to avoid.

    A claim is reported when both hold:

      1. it appears when the OLD text is validated against TODAY's git, which
         means it is false right now, and
      2. its subject appears in no configured document today, as prose

    Condition 1 is why there is no separate still-false check. Condition 2 is
    what keeps `--archive` legitimate and what catches a claim moved into a
    fence.
    """
    documents = _configured_documents()
    haystack = _live_prose(repo, documents)
    found: list[Located] = []
    examined = skipped = undecodable = 0
    for relative in _changed_between(repo, ref, documents):
        try:
            previous = _document_at(repo, ref, relative)
        except UnicodeDecodeError:
            # A previous version that cannot be decoded is not a version with
            # no claims. Counted and reported, never passed over in silence.
            undecodable += 1
            continue
        if previous is None:
            continue
        examined += 1
        # `base` is a parameter; the FORMAT is not, so it is the one piece of
        # document state this has to set - and it is restored in `finally`,
        # because a rule raising part-way would otherwise leave the process
        # reading every later document in the wrong markup language.
        previous_format = _DOC.doc_format
        _set_document(doc_format=_format_for(relative))
        try:
            was = validate(repo, previous, base=(repo / relative).parent,
                           has_entries=(relative == CONFIG.primary_doc))
        finally:
            _set_document(doc_format=previous_format)
        for finding in was:
            if finding.subject is None:
                skipped += 1
                continue
            if finding.subject in haystack:
                continue                    # still written down somewhere
            # `gating=False`: the docstring below says this mode never gates
            # and returns 0. Every other format honoured that and the machine
            # ones did not, publishing a report as an error.
            found.append(Located(relative, finding, primary=False,
                                 gating=False))
    return found, examined, skipped, undecodable


def run_deleted_since(repo: Path, ref: str, fmt: str) -> int:
    """Report claims removed while still false. Never gates: returns 0.

    Whether a removal was evasion or repair is a question about intent, which
    git cannot settle - and a document that deletes a false claim now tells the
    truth, which is this tool's entire purpose. Gating here would fail a build
    on the correct remedy. So this states a fact and lets a reader judge.
    """
    gone, examined, skipped, undecodable = deleted_claims(repo, ref)
    out = sys.stderr if fmt == "sarif" else sys.stdout

    if fmt == "text":
        if gone:
            print(f"\nCLAIMS REMOVED WHILE STILL FALSE (since {ref})", file=out)
            for line in render_findings(gone, fmt)[0]:
                print(line)
    else:
        # ALWAYS, even with nothing to report. SARIF's contract is that stdout
        # is one valid document, and a machine consumer that gets zero bytes
        # fails its upload rather than reading "no results" - which is how a
        # clean run would look like a broken one. `--sweep` and `--validate`
        # both emit an empty document here; this used to emit nothing at all.
        #
        # `repo` is deliberately NOT passed, which is the one place a snippet
        # would be actively wrong rather than merely missing. These findings
        # come from `_document_at(repo, ref, ...)`, so every line number
        # indexes the document AS IT WAS. Reading the current file at that
        # line shows whatever now occupies it - a quotation attributed to a
        # claim that is no longer there.
        for line in render_findings(
                gone, fmt, examined={"documents": examined},
                run_kind="deleted-since")[0]:
            print(line)

    # The denominator. This mode always exits 0, so the count is the only thing
    # separating a clean result from a broken one: "no deletions" and "no
    # documents examined" are otherwise the same output.
    print(f"\nexamined {examined} changed document(s) since {ref}: "
          f"{len(gone)} claim(s) removed while still false, "
          f"{skipped} skipped for carrying no subject", file=out)
    if skipped:
        print("  a skipped finding belongs to a rule that does not yet record "
              "which token it is about, so this mode cannot look for it",
              file=out)
    if undecodable:
        print(f"  {undecodable} previous version(s) could not be decoded and "
              f"were not examined", file=out)
    if gone:
        print("  a swapped or corrected reference looks the same as a hidden "
              "one from git's side. This reports; it does not judge, which is "
              "why it never fails a run.", file=out)
    return 0


def _exclusion_regex(pattern: str) -> re.Pattern[str] | None:
    """Compile one gitignore-shaped path pattern, or None if it is unusable.

    `*` stops at a separator, `**` spans them, `?` matches one non-separator
    character. A pattern with NO separator matches a path segment anywhere, so
    `testdata` covers `hugolib/testdata/x.md` and nobody has to discover that
    `**/testdata/**` was required.

    Deliberately not `fnmatch`, whose `*` crosses `/` silently. A user writing
    `docs/*` to mean "the documents directly in docs" would have excluded the
    whole tree beneath it, and the only evidence would be a smaller number.
    """
    pattern = pattern.strip().replace("\\", "/")
    if not pattern or pattern.startswith("#"):
        return None
    anchored = "/" in pattern.rstrip("/")
    body = pattern.strip("/")
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if body.startswith("**", index):
            # `**/` spans whole segments including none at all; a trailing
            # `**` swallows the rest of the path.
            if body.startswith("**/", index):
                out.append("(?:[^/]+/)*")
                index += 3
            else:
                out.append(".*")
                index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        index += 1
    core = "".join(out)
    if anchored:
        # Rooted at the repository. A directory pattern also covers what is
        # underneath it, which is what a reader means by excluding a folder.
        source = rf"^{core}(?:/.*)?$"
    else:
        # A bare name is a segment anywhere, and everything beneath it.
        source = rf"^(?:.*/)?{core}(?:/.*)?$"
    try:
        return re.compile(source)
    except re.error:
        return None


def excluded_documents(paths: list[str],
                       patterns: tuple[str, ...]) -> tuple[list[str], dict[str, int]]:
    """(kept, {pattern: how many it matched}) for a configured skip-list.

    Returns the per-pattern count rather than a bare list, because a skip-list
    is the single most dangerous thing in a checker of this kind and the ways
    it goes wrong are both silent. One excludes more than intended - this
    project shipped a lint whose skip-list excluded every file it was meant to
    scan and passed on an empty scan. The other is a pattern that matches
    NOTHING, which is dead configuration that reads as a working exclusion
    forever.

    The caller prints both. A count nobody sees is the same as no count.
    """
    matched: dict[str, int] = {pattern: 0 for pattern in patterns}
    compiled = [(pattern, _exclusion_regex(pattern)) for pattern in patterns]
    kept: list[str] = []
    for path in paths:
        normalised = path.replace("\\", "/")
        hit = None
        for pattern, regex in compiled:
            if regex is not None and regex.match(normalised):
                hit = pattern
                break
        if hit is None:
            kept.append(path)
        else:
            matched[hit] += 1
    return kept, matched


def partition_documents(repo: Path, paths: list[str]) -> tuple[list[str], list[str]]:
    """Split tracked markdown into VETTED and UNVETTED.

    Vetted means the configuration names it: `primary_doc`, `archive_doc`, or
    an `extra_docs` entry. Somebody decided that file should be checked and,
    more importantly, decided the others should not.

    That distinction is the whole design of `--sweep`, and it is not a
    nicety. Measured on this repository, checking every markdown file produced
    18 findings and every single one was false - `abc1234` and `v2.1` are the
    example claims in the documents that DOCUMENT the rules, and three more
    were relative paths correct from their own file. A sweep that gated on
    those would be the cry-wolf failure this project exists to prevent,
    shipped as a headline feature.

    So the unvetted half is surveyed and reported, never gated on. The signal
    is deliberately NOT a guess at which SHAs look like placeholders: keying on
    the shape of `abc1234` is exactly the reason-about-the-wording trap that
    this project keeps relearning. Configuration already records the answer.
    """
    vetted_names = {CONFIG.primary_doc, CONFIG.archive_doc, *CONFIG.extra_docs}
    normalised = {name.replace("\\", "/").lstrip("./") for name in vetted_names if name}
    vetted = [p for p in paths if p in normalised]
    return vetted, [p for p in paths if p not in normalised]


def render_findings(located: list[Located], fmt: str, repo: Path | None = None,
                    *, examined: dict[str, int] | None = None,
                    run_kind: str = "verify") -> tuple[list[str], bool]:
    """Render for `fmt`. Returns the lines and whether they belong on stdout.

    SARIF has to be the ONLY thing on stdout or it is not parseable JSON, so
    the caller sends every human diagnostic to stderr in that mode. Text and
    annotation output are line-oriented and mix freely.

    `repo`, `examined` and `run_kind` reach SARIF only. Text and annotation
    output already carry the denominator on their own summary lines.
    """
    if fmt == "sarif":
        return [format_sarif(located, repo, examined=examined,
                             run_kind=run_kind)], True
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


def _mode_flags() -> set[str]:
    """Every flag in the parser's mutually exclusive mode group.

    Read from the parser so that adding a mode cannot leave this behind.
    """
    parser = build_parser()
    flags: set[str] = set()
    for group in parser._mutually_exclusive_groups:      # noqa: SLF001
        for action in group._group_actions:              # noqa: SLF001
            flags.update(action.option_strings)
    return flags


def cli() -> int:
    """Console-script entry point, used by the pre-commit hook.

    Differs from `main` in two ways, both because a hook invokes the command
    bare from the repository being committed to:

    - no mode given means `--verify`
    - `--repo` defaults to the CURRENT DIRECTORY rather than to wherever the
      package was installed
    """
    argv = list(sys.argv[1:])
    # Asked of the parser, never listed here. The duplicate list went stale the
    # moment `--sweep` was added: it was not recognised as a mode, so this
    # inserted `--verify` in front of it and argparse rejected the pair. That
    # shipped in 0.13.0 and broke the exact command the README leads with,
    # because the release gate exercised `--validate` instead of the documented
    # one. A list that has to be kept in step with another list will fall out
    # of step; this cannot.
    modes = _mode_flags()
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
    mode.add_argument("--deleted-since", metavar="REF",
                      help="report claims removed while still false, since "
                           "REF; never gates. Use the merge base in CI, so "
                           "splitting a removal across commits does not hide it")
    mode.add_argument("--sweep", action="store_true",
                      help="survey every tracked markdown file; needs no config")
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


def _survivable_output() -> None:
    """Never die encoding a finding after doing all the work.

    A finding quotes the document, and a document may be in any language.
    Written to a console the process did not choose - cp1252 on a default
    Windows shell, cp437 on an older one - an unencodable character raises
    UnicodeEncodeError and the run dies AFTER the analysis, at the moment of
    reporting it. Found by sweeping jgm/pandoc, whose docs quote Japanese.

    Replacement rather than a forced encoding, because the console genuinely
    cannot render those characters and pretending otherwise produces mojibake;
    a `?` is the honest rendering and the rest of the line still arrives.
    SARIF is the exception: it is a file format rather than console text, so it
    gets UTF-8 and stays faithful.

    This was believed to be handled. `test_a_finding_quoting_non_ascii_does_not
    _crash_the_printer` passes `PYTHONIOENCODING=cp437:replace` in the
    environment, so it was proving that the ENVIRONMENT can cope, not that the
    tool can. Every mode crashed without it.
    """
    sarif = "--format=sarif" in sys.argv or "sarif" in sys.argv
    for stream in (sys.stdout, sys.stderr):
        try:
            if sarif and stream is sys.stdout:
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            # A replaced stream (pytest's capture, a StringIO) may not support
            # reconfigure. Nothing to harden there, and failing here would be
            # worse than the problem.
            pass


def main(argv: list[str] | None = None) -> int:
    _survivable_output()
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
            # stderr directly, NOT `diag`: that helper is defined further
            # down this same function, so calling it here raised
            # UnboundLocalError and `--selftest` on any repository without
            # the primary document ended in a traceback instead of this
            # message. The reason for not using `print` to stdout stands:
            # in SARIF mode stdout carries nothing but JSON.
            print(f"no such document: {target}", file=sys.stderr)
            print(f"  primary_doc is '{CONFIG.primary_doc}', from "
                  f"{CONFIG.source}", file=sys.stderr)
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
        _set_document(link_base=target.parent)
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
        _set_document(link_base=None)
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
    if args.deleted_since:
        return run_deleted_since(repo, args.deleted_since, args.format)
    if args.sweep:
        # Refused rather than ignored. A baseline suppresses findings, and a
        # survey whose whole job is to SHOW them would be silently gutted by
        # one - the user would read "3 findings" and never learn that forty
        # more were hidden. Saying so costs a line; the alternative is the
        # quiet-wrong-answer failure this project is built around.
        conflicting = [name for name, value in (
            ("--baseline", args.baseline), ("--write-baseline", args.write_baseline),
            ("--baseline-check", args.baseline_check),
            ("--suggest-fixes", args.suggest_fixes)) if value]
        if conflicting:
            print(f"--sweep does not support {', '.join(conflicting)}. It is a "
                  "survey of every tracked document, not a gate on one; run "
                  "--verify for the modes that suppress or rewrite.",
                  file=sys.stderr)
            return 2
        return run_sweep(repo, args.format)
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
        _set_document(link_base=target.parent)
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
        # Occurrences already forgiven, per fingerprint, for this run.
        used: dict[str, int] = {}
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
                    # Bounded by what was recorded. An entry written before
                    # counts existed has none, and forgives one - the shape it
                    # had when it was written.
                    allowed = baselined[fingerprint].get("count", 1)
                    try:
                        allowed = int(allowed)
                    except (TypeError, ValueError):
                        allowed = 1
                    if used.get(fingerprint, 0) < max(allowed, 1):
                        used[fingerprint] = used.get(fingerprint, 0) + 1
                        matched.add(fingerprint)
                        suppressed += 1
                        continue
                new += 1
                located.append(item)
                if args.format == "text":
                    print(format_text([item])[0], file=stream)
            return new

        # Which document this is, for rules that key on the FILENAME. Set
        # before validate rather than passed into it: validate restores the
        # value it found on entry, so count_examined below still sees the
        # document the rules just read. Without this, manifest-floor-mismatch
        # works in --sweep and is silent in --verify, and reports 0 examined
        # beside 0 findings - the exact conflation the denominator exists to
        # prevent. Found by running the gate, not by any test.
        _set_document(doc_path=_rel(repo, target))
        # ONE run scope across both halves of examining this document. The two
        # calls below ask the same repository the same questions - the origin
        # remote, most visibly - and without a scope spanning them the second
        # re-asked everything the first had already learned. Measured on this
        # repository's own document: 7 git processes for one --verify, of which
        # `remote get-url origin` was two.
        #
        # Only this pair, not the whole mode. The archive and the extra
        # documents get their own below, because `--sha-map` REWRITES documents
        # between them, and a stable scope promises the checkout does not
        # change while it is held.
        with run_scope():
            findings = validate(repo, text)
            exit_code = 1 if record(_rel(repo, target), findings, primary=True) else 0

            # The denominator. Without it a clean run and a run that checked
            # nothing print identically - the failure that recurred five times
            # in one day. A rule reporting 0 examined is either genuinely
            # absent from this document or broken, and the reader has to be
            # able to tell.
            examined = count_examined(repo, text)
        summary = ", ".join(f"{kind} {n}" for kind, n in examined.items())
        blind = [kind for kind, n in examined.items() if n == 0]
        diag(f"checked {Path(args.validate).name}: {summary}")
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
            _set_document(doc_path=ARCHIVE_DOC)
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
            _set_document(link_base=extra.parent, doc_path=relative)
            # One scope per document, for the reason given at the primary
            # document above: findings and denominator are two halves of one
            # examination and must not re-ask git the same questions.
            with run_scope():
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
                                if kind not in skipped)
            diag(f"checked {relative}: {checked or 'nothing applicable'}")
            if new_extra:
                exit_code = 1
        _set_document(link_base=None)

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
            # `examined` is the primary document's denominator, the same figure
            # the `checked ...` diagnostic prints. A machine consumer of the
            # SARIF could not see it at all before.
            for line in render_findings(located, args.format, repo,
                                        examined=examined)[0]:
                print(line)

        if args.write_baseline:
            # Explicit, never implicit. A baseline that rewrote itself on every
            # verify would ratchet the wrong way: each run would forgive
            # whatever it had just found, and the check would decay to nothing
            # while continuing to report success.
            path = Path(args.write_baseline)
            # Against the REPO, not the process cwd, for the same reason the
            # READ path resolves that way: a git hook passes --repo and runs
            # from wherever the commit was made, so a relative path here
            # wrote a baseline that the next --baseline could not find.
            if not path.is_absolute():
                path = repo / path
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
