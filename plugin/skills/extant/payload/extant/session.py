"""The ambient run state, and the `(repo, text)` API that reads it.

Everything here was module-level state in extant_collect.py, and it is here
rather than deleted because something still has to hold it: configuration is
read ONCE at import and derived from in twenty-one places, and a rule's answers
are memoised for the lifetime of a call that spans several modules. The rules
themselves stopped reading any of it in Task 9 - they take a `Context` - so
what survives is the layer that BUILDS that Context for a caller who has a
repository and a string and nothing else.

That is the whole justification for this module, and it is worth stating
plainly because the alternative looks tempting: thread a Context from `main()`
down through every call and keep no state at all. Two things stop that being
this task's job. Configuration genuinely IS process-wide - `reload_config` is
what makes the pre-commit install path work, and it has to reach every derived
value at once - and `validate(repo, text)` is the API a library caller uses,
which the docstring on `validate` has argued since before the split.

What is NOT here: any rule, any formatter, any mode. Those are extant/rules/*,
extant/report.py and extant/sweep.py + extant/cli.py, and none of them may put
state back.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator

from extant import registry as _registry
from extant.config import Config, load_config
from extant.finding import Finding
from extant.git import CountingGit, Git, SubprocessGit   # noqa: F401
#                      ^ CountingGit and SubprocessGit are re-exported: the
#                        tests that pin a memoisation contract install one of
#                        these in place of `_GIT` below.
from extant.registry import RULE_ERRORS, RULES, Rule, forget_memos
from extant.scope import Context, DocScope, RunScope
from extant.text import MARKDOWN_ONLY

__all__ = [
    "ARCHIVE_DOC", "CONFIG", "Config", "Context", "CountingGit", "DocScope",
    "PRIMARY_DOC", "REPO_ROOT", "RETAIN_ENTRIES", "RULES", "RULE_ERRORS",
    "Rule", "RunScope", "SubprocessGit", "TRUNK", "context", "count_examined",
    "document", "install_document", "reload_config", "report_rule_errors",
    "rule_applies", "run_scope", "selftest", "set_document", "validate",
]

# Two levels up from extant/session.py, which is the repository root in both
# layouts this ships in: `tools/extant/session.py` in an installed project, and
# `plugin/skills/extant/payload/extant/session.py` in this one. The shim used
# `parent.parent` from one level shallower and resolved to the same directory,
# so nothing moved except the count.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Every project-specific value is resolved once, here, from .extant.toml beside
# the repo root - falling back to defaults that reproduce this project's
# behaviour exactly, so a repo without a config file sees no change. The names
# below stay module-level constants because the whole module and its tests refer
# to them directly; only their SOURCE moved.
#
# Porting warning, stated at length in extant/config.py: three of these
# patterns were derived by MEASURING this repo's documents. Copy them to another
# project without re-measuring and the validator matches nothing while appearing
# healthy. Run `--init` against the target repo instead of guessing.
#
# A malformed file raises ValueError from here, at IMPORT. The plain-language
# message a person running the tool sees is printed by extant_collect.py, which
# is the only file that can know it is being RUN rather than imported - burying
# the explanation under a stack that names tomllib internals just makes the
# reader work for it. Importers still get the exception untouched, which is what
# lets the tests see it rather than a dead interpreter.
CONFIG = load_config(REPO_ROOT)


# The two objects that hold everything this tool used to keep in twenty-six
# cache globals and three per-document ones. Their lifetimes are stated on the
# classes; what is stated here is why any module-level name survives at all.
#
# A caller with a repository and a string has nowhere else to put them. The
# rules take a Context now, so the state is no longer reachable from a rule -
# `context()` below is the only thing that reads these, and it reads them at
# CALL time so a rebind is seen.
#
# What changed when the scopes arrived is the NUMBER of names and who resets
# them. `validate()` swaps ONE name and puts ONE name back, so a nested call
# cannot half-clear a caller's view: it builds its own object, and the outer one
# is untouched because it is a different object. The previous shape saved
# thirteen names and restored twelve, by hand, and the two bugs its comments
# recorded were both a name somebody forgot to add to one of the two lists.
#
# `_SCOPE` is never None. A rule called DIRECTLY, without going through
# validate(), reads a Context built from this ambient scope and memoises into
# it, which is what the module globals did and what several tests assert by
# clearing one field and counting subprocesses. `dircache` is None here, so
# directory listings stay uncached outside a call - see the field's own comment.
_SCOPE = RunScope()
_DOC = DocScope()

# The third installed name, beside the two scopes. `Context.git` carries this
# same object, which is how a rule reaches git at all.
#
# Swapping ONE name is what lets a test see what the rules ask git without
# wrapping module functions by hand, and that is not a tidiness point. The
# hand-wrapping it replaces counted a soft call twice, because `_git_soft`
# delegates to `_git`; the same mistake put the spawn figure this budget
# defends 40 percent too high the first time it was measured.
_GIT: Git = SubprocessGit()


def set_document(**changes: object) -> None:
    """Replace the current document, changing only what is named.

    A setter rather than three assignments at each call site, because the
    three values move together and the old code proved they do not stay
    together on their own: `--sweep` set two of them per file and restored
    them after the loop, so a rule that raised left the process resolving
    relative links against the last swept document's directory.
    """
    global _DOC
    _DOC = replace(_DOC, **changes)      # type: ignore[arg-type]


def document() -> DocScope:
    """The document currently installed.

    A reader, so that `--sweep` and `--deleted-since` can save one and put it
    back without naming this module's global. Both of them replace the document
    per file and both have to restore it on the failing path; see `run_sweep`
    for the bug that taught them to.
    """
    return _DOC


def install_document(doc: DocScope) -> None:
    """Put back a whole document saved earlier. The other half of `document`."""
    global _DOC
    _DOC = doc


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
# mapping from this tool's historical global names to those fields, and
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


# None means unbounded, which is the default and the historical behaviour.
# See `extant.rules.consistency._search_with_limit` for why an unbounded
# default is right rather than an oversight.
#
# ANNOTATED, NOT ASSIGNED. `_apply_config()` runs at import, above this line,
# and sets this from `consistency_timeout_seconds`. An assignment here then ran
# afterwards and silently replaced the configured bound with None, so the
# opt-in was inert on every CLI run: the config parsed, the value reached
# CONFIG, and the global the rule actually reads never saw it. An annotation
# binds no value, so the one `_apply_config` set survives.
#
# The rule reads `ctx.config.consistency_timeout` now rather than this name,
# so a test that needs a different bound has to go through the built Config -
# see the `reconfigure` fixture in tests/conftest.py. This stays because
# `_CONFIG_DERIVED` names it and the suite reads it.
_CONSISTENCY_TIMEOUT: float | None


def context(repo: Path) -> Context:
    """This module's ambient state, as the object every rule takes.

    Reads `_ACTIVE`, `_SCOPE`, `_DOC` and `_GIT` at CALL time rather than
    closing over them, and that is load-bearing rather than stylistic:
    `validate()` REBINDS `_SCOPE` and `_DOC` for the duration of a call and
    `run_scope()` rebinds `_SCOPE` for the duration of a sweep. A Context built
    once at import would pin whichever objects existed then, which is the
    memoisation-lifetime bug extant/scope.py exists to make unrepresentable,
    reintroduced one layer up.

    TRAP: patching a CONFIG-DERIVED global on this module (`TRUNK`,
    `_BRANCH_TOKEN`, `_RELEASE_TAG`, ...) does NOT reach any rule, because
    every rule reads the built Config through `ctx.config`. It has not reached
    one since Task 9 moved the last rule out; the seven names the suite used to
    patch that way all go through the `reconfigure` fixture now, which writes
    the built Config and the globals together. A test that needs a different
    value must use that fixture or call `reload_config`.
    """
    return Context(config=_ACTIVE, run=_SCOPE, doc=_DOC, repo=repo, git=_GIT)


def count_examined(repo: Path, text: str) -> dict[str, int]:
    """Per-rule denominators. See extant.registry.count_examined.

    A fold over the registry now, rather than one dict of thirteen entries
    maintained here. The dict guarded against forgetting a rule; asking each
    rule removes the opportunity, because the module that finds a rule's
    candidates is the module that counts them and the two can no longer
    describe different populations.
    """
    return _registry.count_examined(context(repo), text)


def report_rule_errors(emit, mark: int = 0) -> int:
    """Name every rule that RAISED since `mark`, and return the new mark.

    Printed where the denominators are printed, not to a log. That placement is
    the whole safety argument for catching a rule's exception at all: a rule
    that crashed and was quietly skipped reports no findings, which is
    byte-identical to a clean document, so the ONLY thing separating the two is
    that the reader is told. The caller must also refuse to exit 0 - see
    `RULE_ERRORS`.

    Taking a mark rather than draining the list, because `--verify` reads
    several documents and each one's errors belong beside its own `checked ...`
    line; the list itself has to survive to the end, where the exit code is
    decided.
    """
    for kind, message in RULE_ERRORS[mark:]:
        emit(f"  ERRORED: {kind} raised {message}. A rule that raised has not "
             f"found nothing, it has failed to look, so this run is not a pass.")
    return len(RULE_ERRORS)


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
    ctx = context(repo)
    for rule in RULES:
        probed = rule.probe(ctx, text)  # type: ignore[operator]
        if probed is None:
            unprobeable += 1
            lines.append(f"  {rule.kind:<20} NO PROBE       nothing to corrupt "
                         f"(no such claim here, or the repository offers "
                         f"nothing to corrupt it with)")
            continue
        findings = [f for f in rule.check(ctx, probed)  # type: ignore[operator]
                    if f.kind == rule.kind]
        if findings:
            fired += 1
            lines.append(f"  {rule.kind:<20} FIRED")
        else:
            lines.append(f"  {rule.kind:<20} DID NOT FIRE   corrupted a real "
                         f"match and the rule stayed silent")
    return lines, fired, unprobeable


def rule_applies(rule: Rule, in_archive: bool, has_entries: bool) -> bool:
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
    if _DOC.doc_format != "markdown" and rule.kind in MARKDOWN_ONLY:
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
    global _SCOPE
    previous_scope = _SCOPE
    _SCOPE = RunScope(stable=True)
    _SCOPE.dircache = {}
    forget_memos()
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
        forget_memos()


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
    global _SCOPE, _DOC
    outer_scope, outer_doc = _SCOPE, _DOC
    # A fresh scope per call, unless a caller has declared the repository static
    # and taken ownership of this one. The nesting bug the old block existed to
    # prevent cannot be written here: a nested call gets its OWN object, so the
    # outer call's answers are not cleared, not half-cleared, and not dependent
    # on this function remembering to put them back.
    scope = outer_scope if outer_scope.stable else RunScope()
    # Only what the caller actually SAID is overridden. `doc_format` is never a
    # parameter and is inherited unchanged, because `deleted_claims` and
    # `run_sweep` (both in extant/sweep.py) set it around the call rather than
    # through it - deriving it from `doc` here would silently re-read a `.rst`
    # document as markdown.
    doc_scope = DocScope(
        link_base=base if base is not None else outer_doc.link_base,
        doc_format=outer_doc.doc_format,
        doc_path=doc if doc is not None else outer_doc.doc_path)
    ctx = Context(config=_ACTIVE, run=scope, doc=doc_scope, repo=repo, git=_GIT)
    # Installed as well as passed, because a rule may reach a helper that this
    # call did not hand a Context to - and because the tests that clear one
    # scope field and count subprocesses read the installed name.
    _SCOPE, _DOC = ctx.run, ctx.doc
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
        forget_memos()
    try:
        findings: list[Finding] = []
        for rule in RULES:
            if not rule_applies(rule, in_archive, has_entries):
                continue
            try:
                findings += rule.check(ctx, text)      # type: ignore[operator]
            except Exception as exc:                   # noqa: BLE001
                # Deliberately broad, and deliberately not silent. A rule that
                # raises has not "found nothing"; it has failed to LOOK, and
                # those two print identically unless it is said out loud. The
                # run continues so the other twelve rules still report, and
                # `RULE_ERRORS` is what every caller reads to name this rule
                # beside the denominators and to refuse to exit 0.
                #
                # This is the one place in this codebase where the broad form
                # is correct, and it is correct ONLY because of those two
                # things. The convention forbidding it exists to stop errors
                # vanishing, which is precisely what this does not do: swallow
                # the exception and drop the record, and a crashed rule becomes
                # a clean document.
                RULE_ERRORS.append(
                    (rule.kind, f"{exc.__class__.__name__}: {exc}"))
        return findings
    finally:
        _SCOPE, _DOC = outer_scope, outer_doc
