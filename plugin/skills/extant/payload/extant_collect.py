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
    _INTEGRATION_NAMES,              # neither reads any ambient state)
    SHA_SHAPE as _SHA_SHAPE,         # promoted in Task 9: extant/commits.py
)                                    # is a sibling and reads it


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


# Splitting a status document into entries, and retiring the old ones, is
# extant/entries.py now. Both keep their public names: they were never
# underscored, they are what `--archive` and the /extant command call, and the
# rule the rest of this package follows would promote them anyway.
from extant import entries as _entries


def split_entries(text: str) -> tuple[str, list[tuple[str, str]], str]:
    """Split a status doc into (preamble, [(kind, text)], reference base)."""
    return _entries.split_entries(text, _ACTIVE)


def archive(repo: Path, retain: int | None = None) -> dict[str, int]:
    """Move all but the newest `retain` phase entries into the archive doc.

    TRAP, and it is worth a line here because a test depends on it: `archive`
    calls the `split_entries` in extant/entries.py, NOT the wrapper above.
    Swapping this module's `split_entries` no longer reaches it. The test that
    proves the conservation guard is independent of the splitter swaps
    `extant.entries.split_entries` for exactly that reason.
    """
    return _entries.archive(repo, retain, _ACTIVE)


# Which commits a document CITES, and which of them git has, is
# extant/commits.py now. It is a module of its own rather than part of either
# rule that reads them: `dead-sha` and `false-merge-claim` share one
# `cat-file --batch-check` over the document's UNION, so neither can own the
# other's scanner without a rule importing a rule - which is what the leaf gate
# forbids and what housed rename detection inside the live-claim rule once
# already.
#
# Five names lost their underscore over there, and only five, because the rule
# modules call exactly those. This file is deliberately NOT counted as a
# sibling - it sits outside the package and Task 10 deletes it - so the
# historical spellings survive here as aliases and the suite's call surface
# does not move.
from extant.commits import (          # noqa: F401  (re-exported as they are:
    _ASSET_PATH, _LINKED_SHA,         # patterns and pure helpers, no state)
    _PINNED_REF, _URL, _UUID, _find_bare_sha_candidates, _is_digest_length,
    find_bare_sha_candidates, find_sha_candidates,
)
from extant.commits import (          # noqa: F401  (promoted for the rule
    BACKTICKED as _BACKTICKED,        # modules, re-exported under the old
    BARE_SHA_TOKEN as _BARE_SHA_TOKEN,                            # spellings)
    looks_like_bare_sha as _looks_like_bare_sha,
    looks_like_sha as _looks_like_sha,
    spans_overlap as _spans_overlap,
)

# The MODULE as well, for the reason `_collect` and `_refs` are imported this
# way: the wrappers below look each function up at call time, so a test may
# swap one there and see this module's callers go through the replacement.
from extant import commits as _commits


from extant.finding import Finding, Located  # noqa: F401


# The dead-sha rule is extant/rules/sha.py now: its check, its denominator, its
# probe and the `--sha-map` rewriter that repairs exactly what it reports. The
# wrappers below keep this module's `(repo, text)` call surface, which is what
# the suite and the RULES tuple further down already use.
from extant.rules import sha as _rule_sha

from extant.rules.sha import load_sha_map, translate_shas  # noqa: F401
#                            ^ re-exported unchanged: neither reads ambient
#                              state, and `main()` calls both by these names.


def _merge_claims(prose: str) -> list[tuple[int, str, str]]:
    """(line, ref, sha) for every merge claim. See extant.commits.merge_claims."""
    return _commits.merge_claims(_ACTIVE, prose)


def _document_sha_tokens(prose: str) -> list[str]:
    """Every SHA-shaped token in this document a rule will ask git about."""
    return _commits._document_sha_tokens(_ACTIVE, prose)


def _document_shas(repo: Path, prose: str) -> set[str]:
    """Which of this document's SHA-shaped tokens resolve to commits."""
    return _commits.document_shas(_ctx(repo), prose)


def _uses_changesets(repo: Path) -> bool:
    """Does this repository mint release notes with changesets?"""
    return _rule_sha._uses_changesets(_ctx(repo))


def validate_references(repo: Path, text: str) -> list[Finding]:
    """Every referenced SHA must still resolve; a dead reference is useless."""
    return _rule_sha.check(_ctx(repo), text)


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
# suite patches - the re-grep that comment asks for - TWO of the seven
# gained a reader that left this file in Task 8, and one of those two keeps
# a reader here as well:
#
#   TRUNK             read in the package by `integration_refs`
#                     (extant/refs.py) and by `collect()` (extant/collect.py) -
#                     AND still read here, by the one-group back-compat path in
#                     `_merge_claims` at line 630, which never moved. A name
#                     with a reader in both places is not a clean member of
#                     either bucket: tests/test_multi_trunk.py sets it at four
#                     sites, and only the one exercising `_merge_claims`
#                     directly ever depended on the value reaching anywhere.
#                     The other three exercise `integration_refs` and passed
#                     regardless of whether it did, because the gitflow fixture
#                     carries both `main` and `develop`, so
#                     `_INTEGRATION_NAMES` finds the same set whichever name
#                     seeds it and only the ORDER differs. All four now go
#                     through `reload_config` rather than a module-attribute
#                     patch, which reaches both buckets at once and is what the
#                     fourth site actually needs.
#   _SECTION_HEADER   read by `split_entries`, patched once, at
#                     test_packaging.py:521 - which calls `reload_config`
#                     rather than assigning the global, so it rebuilds
#                     `_ACTIVE` too and reaches the package unharmed.
#
# The other five - _BRANCH_TOKEN, _CONSISTENCY_TIMEOUT, _MERGE_CLAIM,
# _RELEASE_TAG, _RELEASE_CLAIMS_ARE_OURS - are still read by rules in this
# file, so patching them still works. Re-grep again when those rules move in
# Task 9; that is the whole reason this count is written out by name.
#
# A test that needs a different value from a MOVED reader must call
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
    return _refs.branch_exists(_ctx(repo), branch)


def _ancestor_index(repo: Path, ref: str) -> dict[str, list[str]] | None:
    """Every commit reachable from `ref`, indexed by 7-character prefix."""
    return _refs._ancestor_index(_ctx(repo), ref)


def _reachable_from(repo: Path, rev: str, ref: str) -> bool:
    """Is `rev` an ancestor of `ref`?"""
    return _refs.reachable_from(_ctx(repo), rev, ref)


def _resolve_ref(repo: Path, ref: str) -> str | None:
    """The full commit SHA a ref points at, or None."""
    return _refs.resolve_ref(_ctx(repo), ref)


def _ref_table(repo: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Every local branch and tag, by short name, annotated tags peeled."""
    return _refs.ref_table(_ctx(repo))


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
    return _refs.named_in_merge_history(_ctx(repo), branch)


def tracked_markdown(repo: Path) -> list[str]:
    """Every markdown file git tracks, repo-relative, sorted."""
    return _refs.tracked_markdown(_ctx(repo))


# The false-merge-claim rule is extant/rules/merge.py now. It reads the same
# claims extant/commits.py finds for the SHA batch, which is why that scanner
# is a module of its own rather than either rule's property.
from extant.rules import merge as _rule_merge

from extant.rules.merge import _claimed_ref  # noqa: F401  (re-exported: pure,
#                                              reads nothing ambient)


def validate_merge_claims(repo: Path, text: str) -> list[Finding]:
    """Claims that work merged to main, re-checked against git ancestry."""
    return _rule_merge.check(_ctx(repo), text)


def _probe_merge(repo: Path, text: str) -> str | None:
    """Repoint a real merge claim at a commit on no integration branch."""
    return _rule_merge.probe(_ctx(repo), text)


# The dead-path-pointer rule is extant/rules/path_pointer.py now.
from extant.rules import path_pointer as _rule_pointer


def validate_path_pointers(repo: Path, text: str) -> list[Finding]:
    """Paths offered as pointers must resolve; a pointer to nothing is useless."""
    return _rule_pointer.check(_ctx(repo), text)


def _probe_pointer(repo: Path, text: str) -> str | None:
    """Repoint a real pointer at a path that does not exist."""
    return _rule_pointer.probe(_ctx(repo), text)


# The stale-live-claim rule is extant/rules/live_claim.py now.
from extant.rules import live_claim as _rule_live


def validate_live_claims(repo: Path, text: str) -> list[Finding]:
    """Present-tense status claims, re-checked against git."""
    return _rule_live.check(_ctx(repo), text)


def _probe_live_claim(repo: Path, text: str) -> str | None:
    """Corrupt a branch token, but only where a live claim is actually made."""
    return _rule_live.probe(_ctx(repo), text)


# Reading a document - what is code, what is prose, what anchors it offers -
# is extant/text.py now. The patterns are re-exported unchanged; the functions
# that read ambient state are wrapped, because the package takes the state as
# an argument and this module's callers still pass `(repo, text)`.
#
# THREE of these names lost their underscore, and only three, because sites.py
# calls exactly three of them. That is the rule every module in this package
# follows: a name is public when a SIBLING calls it, and keeps its underscore
# when it does not. The rest are read by this module and by nothing else, and
# this module is not a sibling - it sits outside the package, which is what
# test_no_module_reaches_past_another_modules_surface says in its own comment,
# and Task 10 deletes it. Promoting a name for a caller about to disappear is a
# rename at both ends and no boundary made clearer.
#
# The historical spellings survive here, because this module's job is that its
# call surface does not move under the suite or under an adopter's script.
from extant.text import (            # noqa: F401  (re-exported as they are:
    _ATTR_ANCHOR, _DIRECTIVE_LABEL,  # patterns and pure functions, no state)
    _EXPLICIT_ANCHOR, _FENCE, _INLINE_CODE, _LANGUAGE_DIR,
    _MARKDOWN_ONLY, _MYST_TARGET, _NESTED_HEADING, _ROUTE_DEPTH,
    _RST_DIRECTIVE, _RST_DOCTEST, _RST_INLINE, _RST_LITERAL_INTRO,
    _SETEXT_RULE, _STRIPPED, _blank_rst, _definition_terms, _disambiguated,
    _format_for, _heading_text, _route_name,
    _setext_headings, _slug, _slug_keeping_edges, _slug_punctuation_to_dash,
    _without_tags,
)
from extant.text import (            # noqa: F401  (promoted for a sibling
    EXTERNAL as _EXTERNAL,           # that calls them - sites.py for the first
    HEADING as _HEADING,             # three, a rule module for the rest - and
    MD_LINK as _MD_LINK,
    ORDER_PREFIX as _ORDER_PREFIX,   # re-exported here under the old spelling)
    anchors as _anchors,             # (the three that take ambient state are
    percent_decoded as _percent_decoded,   # wrapped below, not aliased here)
)

# The MODULE as well, so the wrappers below look each function up at call time
# and a test may swap one there. Same reason `_collect` and `_refs` are
# imported this way.
from extant import text as _text


def _current_document() -> str | None:
    """The document under validation, as a forward-slashed relative path."""
    return _text.current_document(_DOC)


def _blank(text: str, *, inline: bool) -> str:
    return _text._blank(_DOC, text, inline=inline)


def _blank_uncached(text: str, *, inline: bool) -> str:
    return _text._blank_uncached(_DOC, text, inline=inline)


def _strip_code(text: str) -> str:
    """Blank out fenced blocks AND inline code spans, preserving line numbers."""
    return _text.strip_code(_DOC, text)


def _prose(text: str) -> str:
    """Text with FENCED BLOCKS removed, for rules that check claims."""
    return _text.prose(_DOC, text)


def _unique_basename(repo: Path, target: str) -> bool:
    """Does exactly one tracked markdown file carry this basename?"""
    return _text.unique_basename(_ctx(repo), target)


def _translation_tree(repo: Path, path: str) -> str:
    """Which parallel language tree this path belongs to, or "" for none."""
    return _text._translation_tree(_ctx(repo), path)


def _numbered_document(repo: Path, target: str) -> bool:
    """Does exactly one tracked document answer to this route once prefixes go?"""
    return _text.numbered_document(_ctx(repo), target)


# The dead-md-link rule is extant/rules/md_link.py now.
from extant.rules import md_link as _rule_md_link


def validate_md_links(repo: Path, text: str) -> list[Finding]:
    """Relative markdown links whose target file is gone."""
    return _rule_md_link.check(_ctx(repo), text)


def _probe_md_link(repo: Path, text: str) -> str | None:
    """Repoint the first non-external link at a file that does not exist."""
    return _rule_md_link.probe(_ctx(repo), text)


# The dead-md-anchor rule is extant/rules/md_anchor.py now, and `_rel` went
# with it as far as extant/finding.py: the rule NAMES the other document in its
# finding detail, and a detail string is a shipped wire format - the baseline
# fingerprint hashes it - so the rule and the formatters below must not spell a
# path two different ways.
from extant.finding import rel as _rel     # noqa: F401  (re-exported under the
#                                            old spelling; pure path arithmetic)

from extant.rules import md_anchor as _rule_md_anchor


def _target_anchors(repo: Path, path: Path) -> set[str] | None:
    """Anchors offered by another document, or None if it cannot be read."""
    return _rule_md_anchor._target_anchors(_ctx(repo), path)


def validate_md_anchors(repo: Path, text: str) -> list[Finding]:
    """`#fragment` links pointing at no such heading, in this file or another."""
    return _rule_md_anchor.check(_ctx(repo), text)


def _probe_md_anchor(repo: Path, text: str) -> str | None:
    """Repoint the first fragment at a heading no document offers."""
    return _rule_md_anchor.probe(_ctx(repo), text)


# Where files actually are, and which markdown trees a generator compiles into
# a website, are extant/sites.py now. The constants are re-exported unchanged;
# every function is wrapped, because each of them read `_SCOPE` or `repo` off
# this module and the package takes both on a Context instead.
#
# Not one of these names lost its underscore, and that is the same rule text.py
# followed rather than a different one: a name goes public when a SIBLING
# MODULE calls it. Nothing in the package calls into sites.py at all - its
# callers are the link, anchor, branch and live-claim rules, which are still in
# this file. Task 9 turns those into extant/rules/*.py, and each name they
# reach for is promoted in the commit that creates the caller, where the
# promotion is justified by a caller that exists rather than by anticipation.
from extant.sites import (           # noqa: F401  (re-exported as they are:
    _ABSOLUTE, _FILEISH,             # constants, and none of them read state)
    _GLOBAL_ANCHOR_CONFIGS, _PARTIAL_CONFIGS, _SITE_CONFIGS, _SITE_DIRS,
    _SITE_MARKERS_IN_FILE,
)

from extant import sites as _sites


def _listdir(directory: Path) -> set[str]:
    """Directory entries, cached only while validate() says it is safe to."""
    return _sites._listdir(_ctx(REPO_ROOT), directory)


def _actual_case(base: Path, relative: str) -> str | None:
    """The on-disk spelling of `relative`, or None if no such file exists."""
    return _sites._actual_case(_ctx(REPO_ROOT), base, relative)


def _resolve_reference(repo: Path, base: Path, raw: str) -> tuple[bool, str | None]:
    """(exists_portably, on_disk_spelling_if_it_differs)."""
    return _sites.resolve_reference(_ctx(repo), base, raw)


def _has_global_anchors(repo: Path) -> bool:
    """Does this generator resolve `#label` against every document at once?"""
    return _sites.has_global_anchors(_ctx(repo))


def _has_partial_anchors(repo: Path) -> bool:
    """Does this generator compose fragment files into other pages?"""
    return _sites.has_partial_anchors(_ctx(repo))


def _partial_anchors(repo: Path) -> set[str]:
    """Anchors from fragment files, which belong to every page that includes one."""
    return _sites.partial_anchors(_ctx(repo))


def _project_anchors(repo: Path) -> set[str]:
    """Every anchor offered by every tracked markdown file in the project."""
    return _sites.project_anchors(_ctx(repo))


def _site_dirs(repo: Path) -> list[Path]:
    """Every directory a generator config can sit in, one level of nesting deep."""
    return _sites._site_dirs(_ctx(repo))


def _is_generated_site(repo: Path) -> bool:
    """Does this repository compile its markdown into a website?"""
    return _sites.is_generated_site(_ctx(repo))


def _site_scopes(repo: Path) -> set[str]:
    """Top-level directories a generator governs, or {""} for the whole repo."""
    return _sites._site_scopes(_ctx(repo))


def _top_level(repo: Path, directory: Path) -> str | None:
    """The first path segment of `directory` under `repo`; "" for the root."""
    return _sites._top_level(_ctx(repo), directory)


def _in_site_tree(repo: Path) -> bool:
    """Is the document being validated inside a tree some generator builds?"""
    return _sites.in_site_tree(_ctx(repo))


def _numbered_docs_scopes(repo: Path) -> set[str]:
    """Top-level directories holding a numbered documentation tree."""
    return _sites._numbered_docs_scopes(_ctx(repo))


def _numbered_docs_tree(repo: Path) -> dict[str, int]:
    """A directory whose documents are NUMBERED for presentation order."""
    return _sites._numbered_docs_tree(_ctx(repo))


def _looks_like_a_path(repo: Path, token: str) -> bool:
    """True when a token is better explained as a file than as a branch."""
    return _sites.looks_like_a_path(_ctx(repo), token)


# The unknown-branch rule is extant/rules/branch.py now.
from extant.rules import branch as _rule_branch


def validate_branch_mentions(repo: Path, text: str) -> list[Finding]:
    """A branch named in the newest entry that git has never heard of."""
    return _rule_branch.check(_ctx(repo), text)


def _probe_branch_in_newest(repo: Path, text: str) -> str | None:
    """Point the first branch token of the newest entry at a name git never saw.

    See extant.probes.branch_in_newest. It moved there because BOTH branch
    rules probe this way and the live-claim probe called this one directly,
    which is a rule reaching into a rule.
    """
    return _probes.branch_in_newest(_ctx(repo), text)


# The dead-release-tag rule is extant/rules/release_tag.py now.
from extant.rules import release_tag as _rule_tag


def validate_release_tags(repo: Path, text: str) -> list[Finding]:
    """"Released in v2.1" where no such tag exists, or it shipped on nothing."""
    return _rule_tag.check(_ctx(repo), text)


def _tags(repo: Path) -> set[str]:
    """Every tag in this repository, read once."""
    return _rule_tag._tags(_ctx(repo))


def _tag_prefixes(repo: Path) -> list[str]:
    """What this repository puts BEFORE a version number in a tag."""
    return _rule_tag._tag_prefixes(_ctx(repo))


def _released_tag(repo: Path, version: str) -> str | None:
    """The real tag a release claim names, or None if there is none."""
    return _rule_tag._released_tag(_ctx(repo), version)


def _probe_tag(repo: Path, text: str) -> str | None:
    """Repoint a real release claim at a version nothing tagged."""
    return _rule_tag.probe(_ctx(repo), text)


# The dead-pinned-ref rule is extant/rules/pinned_ref.py now, and it took the
# last two `_GIT` call sites any RULE still had in this file with it.
from extant.rules import pinned_ref as _rule_pin

from extant.rules.pinned_ref import (   # noqa: F401  (re-exported as they are:
    _PIN_QUOTES, _PIN_REPO, _PIN_REV,   # patterns, constants and one pure
    _normalise_remote,                  # function, none reading state)
)


def _own_remote(repo: Path) -> str | None:
    """This repository as `owner/name`, or None when it has no origin."""
    return _rule_pin._own_remote(_ctx(repo))


def _pinned_refs(repo: Path, text: str) -> list[tuple[int, str]]:
    """Every `rev:` pin governed by a `repo:` naming THIS repository."""
    return _rule_pin._pinned_refs(_ctx(repo), text)


def validate_pinned_refs(repo: Path, text: str) -> list[Finding]:
    """An install snippet pinning a version of THIS repo that does not exist."""
    return _rule_pin.check(_ctx(repo), text)


def _probe_pinned_ref(repo: Path, text: str) -> str | None:
    """Corrupt one pin the rule would actually read. See the rule's own probe
    for why it is located by line rather than by pattern."""
    return _rule_pin.probe(_ctx(repo), text)


# The inconsistent-artifact rule is extant/rules/consistency.py now.
from extant.rules import consistency as _rule_consistency

from extant.rules.consistency import (  # noqa: F401  (re-exported as they are:
    _Captured, _file_identity,          # pure, and neither reads any ambient
    _search_with_limit,                 # state)
)


def _consistency_for(repo: Path) -> dict[str, tuple[tuple[str, object], ...]]:
    """The consistency block belonging to the repository being checked."""
    return _rule_consistency._consistency_for(_ctx(repo))


def validate_consistency(repo: Path, text: str) -> list[Finding]:
    """Named values that must agree across several files in the repository."""
    return _rule_consistency.check(_ctx(repo), text)


def _probe_consistency(repo: Path, text: str) -> str | None:
    """No probe: this rule reads the repository, never the document."""
    return _rule_consistency.probe(_ctx(repo), text)


# None means unbounded, which is the default and the historical behaviour.
# See `extant.rules.consistency._search_with_limit` for why an unbounded
# default is right rather than an oversight.
#
# ANNOTATED, NOT ASSIGNED. `_apply_config()` runs at import, far above this
# line, and sets this from `consistency_timeout_seconds`. An assignment here
# then ran afterwards and silently replaced the configured bound with None,
# so the opt-in was inert on every CLI run: the config parsed, the value
# reached CONFIG, and the global the rule actually reads never saw it. An
# annotation binds no value, so the one `_apply_config` set survives.
#
# The rule reads `ctx.config.consistency_timeout` now rather than this name,
# so a test that needs a different bound has to go through the built Config -
# see the `reconfigure` fixture in tests/conftest.py. This stays because
# `_CONFIG_DERIVED` names it and the suite reads it.
_CONSISTENCY_TIMEOUT: float | None


# The raw-lfs-blob rule is extant/rules/lfs.py now, and it took four of this
# file's five direct `subprocess.run(["git", ...])` call sites with it - the
# two `cat-file` batches, the `ls-tree -r -z` and the `check-attr -z --stdin`
# paired with it. They still bypass the seam over there, and tests/test_scope.py
# still counts them; what changed is which file they are counted in.
from extant.rules import lfs as _rule_lfs

from extant.rules.lfs import (         # noqa: F401  (re-exported as they are:
    _LFS_POINTER, _LFS_POINTER_MAX,    # two constants from the LFS spec)
)


def _lfs_is_configured(repo: Path) -> bool:
    """Cheap gate: does this repository route anything through LFS at all?"""
    return _rule_lfs._lfs_is_configured(_ctx(repo))


def _lfs_governed(repo: Path) -> list[tuple[str, str]]:
    """(path, blob sha) for every tracked file the LFS filter governs."""
    return _rule_lfs._lfs_governed(_ctx(repo))


def validate_lfs_storage(repo: Path, text: str) -> list[Finding]:
    """A file `.gitattributes` says lives in LFS, stored as a raw blob instead."""
    return _rule_lfs.check(_ctx(repo), text)


def _probe_lfs_storage(repo: Path, text: str) -> str | None:
    """No probe. This rule reads the repository, never the document."""
    return _rule_lfs.probe(_ctx(repo), text)


# The manifest-floor-mismatch rule is extant/rules/manifest_floor.py now.
from extant.rules import manifest_floor as _rule_floor

from extant.rules.manifest_floor import (   # noqa: F401  (re-exported as they
    _ENTRY_DOC, _FLOOR_CLAIM, _FLOOR_LANGS,  # are: patterns, tables and pure
    _FLOOR_LABEL, _FLOOR_LOWER, _FLOOR_MANIFESTS, _FLOOR_OPERATORS,
    _FLOOR_SUFFIXES, _FLOOR_THIRD_PARTY, _FLOOR_VERB, _HISTORICAL_DOC,
    _LABEL_LINE, _declared_floor, _version,   # functions, none reading state)
)


def _manifest_floors(repo: Path) -> dict[str, tuple[str, str, str]]:
    """Each ecosystem's declared floor: language -> (spec, file, enforcement)."""
    return _rule_floor._manifest_floors(_ctx(repo))


def _floor_claims(repo: Path, text: str
                  ) -> list[tuple[int, str, tuple[int, ...], tuple[int, ...]]]:
    """Floor statements this rule would actually inspect in this document."""
    return _rule_floor._floor_claims(_ctx(repo), text)


def validate_manifest_floors(repo: Path, text: str) -> list[Finding]:
    """A documented version floor against the manifest that declares it."""
    return _rule_floor.check(_ctx(repo), text)


def _probe_manifest_floor(repo: Path, text: str) -> str | None:
    """Repoint a real floor statement at a version no manifest can declare."""
    return _rule_floor.probe(_ctx(repo), text)


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


# The machinery more than one probe needs is extant/probes.py now, because
# `stale-live-claim`'s probe called `unknown-branch`'s probe outright and four
# rules corrupt a document through the same one-capture substitution. Both
# marker strings are re-exported under their historical spellings; `_DEAD_SHA`
# went to extant/rules/sha.py instead, being the one that has a single owner.
from extant.probes import (           # noqa: F401  (re-exported as they are:
    FAKE_BRANCH_LEAF as _FAKE_BRANCH_LEAF,   # marker strings and one pure
    MISSING_PATH as _MISSING_PATH,           # function, none reading state)
    sub_group as _sub_group,
)

from extant import probes as _probes


def _probe_sha(repo: Path, text: str) -> str | None:
    """Corrupt one backticked SHA. See extant.rules.sha.probe."""
    return _rule_sha.probe(_ctx(repo), text)


# `Rule` is extant/contract.py now, re-exported by extant/registry.py beside
# the registry it declares. The class had to leave this file for the rule
# modules to construct one without importing the shim, which is the same leaf
# argument that moved rename detection and object resolution into
# extant/refs.py.
from extant.registry import Rule      # noqa: F401  (re-exported: the suite
#                                       builds one, and RULES below is a
#                                       tuple of them)


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
    links = [raw for line in _strip_code(text).splitlines()
             for raw in _MD_LINK.findall(line)]
    return {
        # Asked of the rule module, which finds these candidates and so is the
        # only place that can count them over the same population.
        "dead-sha": _rule_sha.examined(_ctx(repo), text),
        "stale-live-claim": _rule_live.examined(_ctx(repo), text),
        "unknown-branch": _rule_branch.examined(_ctx(repo), text),
        "false-merge-claim": _rule_merge.examined(_ctx(repo), text),
        "dead-release-tag": _rule_tag.examined(_ctx(repo), text),
        "dead-path-pointer": _rule_pointer.examined(_ctx(repo), text),
        "dead-md-link": _rule_md_link.examined(_ctx(repo), text),
        "dead-md-anchor": _rule_md_anchor.examined(_ctx(repo), text),
        "inconsistent-artifact": _rule_consistency.examined(_ctx(repo), text),
        "dead-pinned-ref": _rule_pin.examined(_ctx(repo), text),
        "raw-lfs-blob": _rule_lfs.examined(_ctx(repo), text),
        "manifest-floor-mismatch": _rule_floor.examined(_ctx(repo), text),
        # Pointers whose target this repository tracks and can count. One
        # naming a file we do not have is not counted: the rule cannot
        # decide it, and `dead-path-pointer` already asks whether a path
        # exists. On a 39-repository corpus that was 51 of 6,525.
        "dead-line-pointer": len(_line_pointer_sites(repo, text)),
    }


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
