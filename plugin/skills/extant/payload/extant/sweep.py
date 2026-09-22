"""The first-run survey, `--sweep`, and the machinery every survey-shaped mode
shares.

Three modes answer a question about MANY documents rather than one. `--sweep`
is the first-run command: it needs no configuration, writes nothing, says what
is rotting in a repository nobody here has seen before, and reports without
gating. `--deleted-since` asks the opposite question - which claims were true
enough to be written down, are false today, and are no longer written anywhere
- and lives in extant/deleted_since.py since 2026-09-14, when this module
reached its line ceiling; it never gates either. `--introduced-since`, in
extant/introduced_since.py since the same day, is the survey that GATES: it
reads the documents a range changed through `survey` below and fails on the
findings that sit on lines the range wrote.

What stays here is what makes a survey honest rather than reassuring: the
exclusion patterns and their per-pattern counts, the vetted/unvetted split, and
the per-document denominators. Every one of those exists because a survey that
examined nothing prints exactly what a clean survey prints.

The ambient state both modes set around each document - which file is being
read, and in which markup language - lives in extant/session.py. This module
saves it and puts it back, on the failing path too; see `run_sweep` for the bug
that taught it to.

NEITHER SURVEY MAY RE-CHECK ONLY THE DOCUMENTS THAT CHANGED, however tempting
that gets each time this module is profiled: a claim dies because the
REPOSITORY changed, not the document, so an incremental survey reports clean on
exactly the deleted branch or moved file this tool exists to catch.
`--introduced-since` reads only the changed documents and is not an exception
to this: its question - which claims did this change WRITE - lives in changed
documents by construction, it prints how many tracked documents it left
unread, and its own docstring says why a survey may not borrow the shortcut.
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from extant import refs, session
# ALIASED, because `text` is what every function here calls the document
# it is reading. Imported under its own name the module was shadowed by
# the first local assignment in `run_sweep`, and the failure was an
# AttributeError on a str several lines later rather than anything
# naming the import.
from extant import text as markup
from extant import strata
from extant.config import StatusConfig, normalise_document
from extant.finding import Finding, Located
from extant.gate import report_repository_notes
from extant.registry import RULE_ERRORS
from extant.report import (
    format_sweep_sections, render_findings, sweep_entry_note,
)

__all__ = [
    "apply_exclusions", "excluded_documents", "partition_documents",
    "run_sweep", "survey",
]

if TYPE_CHECKING:
    # What one worker hands back per document, and what `survey` gathers them
    # into keyed by path with the path dropped: the findings, the reason the
    # file could not be read or None, the denominators, the rule errors
    # raised while reading it, and whether an ancestry index reached its
    # bound. Named for the checker only - the block never runs - because a
    # module-level alias would be evaluated on import and `str | None` is
    # not an expression Python 3.9 can evaluate.
    _Result = tuple[str, list[Finding], str | None, dict[str, int],
                    list[tuple[str, str]], bool]
    _ByPath = dict[str, tuple[list[Finding], str | None, dict[str, int],
                              list[tuple[str, str]], bool]]

# Below this many documents a survey is faster in one process than in eight.
# Measured 2026-08-23 on 12 cores, best of three, cache-free, over generated
# corpora of the shape this tool actually reads:
#
#     40 docs  1985ms -> 1915ms  1.04x
#     60 docs  2586ms -> 2242ms  1.15x
#    100 docs  4143ms -> 2367ms  1.75x
#    150 docs  5988ms -> 3065ms  1.95x
#    200 docs  7808ms -> 3279ms  2.38x
#
# The floor is 100 rather than the 40 where the curve first leaves zero,
# because a process pool brings failure modes a loop does not have - spawn
# restrictions, sandboxes, unpicklable state - and 4% is not worth buying any
# of them. By 100 the gain is 1.75x, which is.
_PARALLEL_FLOOR = 100
_MAX_WORKERS = 8

# Per worker process, entered once by the initializer. A survey asks the same
# repository the same questions for every document, and the scope is what lets
# each process answer them once instead of once per file.
_WORKER_SCOPE = None


# The one normaliser, imported rather than written again here. This module had
# FIVE spellings of "a configured document name" and they disagreed; `gate.py`
# had a sixth by having none. It now happens once, where the settings are read,
# so the names arriving on `session.CONFIG` are already normalised and the
# calls below are idempotent - kept because a reader comparing a configured
# name against a tracked path should see the question being asked.
_normalise = normalise_document


def _worker_init(config: StatusConfig, key: str,
                 tracked: list[str] | None) -> None:
    """Give a freshly spawned worker the config, a run scope of its own, and
    the tracked list the parent already took.

    `install_config`, never `session.CONFIG = config`. The bare assignment sat
    here for eight releases and reached no rule; that function records what it
    cost and why re-reading the configuration here would be wrong rather than
    merely slower.

    The list is seeded into the scope under the key `refs.tracked_markdown`
    reads it back by, so a worker whose documents reach `sites.py` answers
    from the parent's `ls-tree` instead of running its own - the review's
    5.6, traced on ruff's clone as five listings for one survey, the parent's
    and four re-asks at 46 ms each. It is the same list the survey was built
    from, so nothing a worker reads can differ from what the parent read.
    None when the caller took no listing, and the worker then asks as it
    always did.
    """
    global _WORKER_SCOPE
    session.install_config(config)
    _WORKER_SCOPE = session.run_scope()
    scope = _WORKER_SCOPE.__enter__()
    if tracked is not None:
        scope.tracked_markdown[key] = tracked


def _validate_one(repo: Path, relative: str, is_primary: bool) -> _Result:
    """Everything one document contributes to a survey.

    The ONE implementation, called by the sequential path and by the workers
    alike. Two copies of this - one per path - is how a survey acquires two
    behaviours and only ever exercises one of them; the parallel and serial
    results have to be the same result or the mode is not worth having.

    Returns (relative, findings, unreadable_or_None, examined, rule_errors,
    index_incomplete) - the last a fact of the scope this ran under, carried
    out because a worker's scope dies with the worker and the parent prints
    the note.
    The errors are RETURNED rather than only appended, because in a worker
    `RULE_ERRORS` is a list in a process the parent cannot see. The sequential
    caller must therefore ignore what it gets back - the append already
    happened in its own process - and only the parallel caller re-adds them.
    """
    path = repo / relative
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        # Counted and named, never skipped quietly. A file that could not be
        # read is not a file with no findings, and printing the same thing for
        # both is the conflation this tool is about.
        return (relative, [], f"{relative} ({exc.__class__.__name__})", {}, [],
                False)

    mark = len(RULE_ERRORS)
    # All three, and the PATH is the one that was missing. It used to be
    # passed to `validate` instead, which scopes it to that call and puts the
    # ambient document back on the way out - so `count_examined` below ran
    # against a document with no path, and every rule that keys on WHICH file
    # it is reading counted nothing. `manifest-floor-mismatch` reported the
    # README's contradiction and `examined=0` in the same sweep, and was then
    # named among the rules that "examined nothing anywhere here". Set on the
    # document rather than passed, so both halves read one file. `gate.py`
    # carries the same comment for `--verify`, where this was found first.
    session.set_document(link_base=path.parent,
                         doc_format=markup.format_for(relative),
                         doc_path=relative)
    # `repository_rules=False`: this survey runs those in `run_sweep`, once,
    # attributed to the file that declares them. Without it they ran HERE as
    # well, for whichever document was primary - so a single raw LFS blob
    # printed twice, bare and again under `.gitattributes:`, against a
    # denominator counting the governed file once. `inconsistent-artifact`
    # did the same. The exclusion was already written on the denominator
    # below, by hand; this is the half the findings loop could not say.
    findings = session.validate(repo, text, has_entries=is_primary,
                                repository_rules=False)
    # The denominator, per rule. Counted only for rules that actually READ
    # this document: a sweep skips entry-scoped rules outside the primary file
    # and markdown-only rules for `.rst`, and `count_examined` knows nothing
    # about either. Summing it whole would report link candidates in a
    # document where no link rule ran.
    #
    # The SAME predicate the findings above were selected by, arguments and
    # all. Restating one of its clauses here is how the two came to disagree.
    #
    # Handed to `count_examined` as well as applied to its answer, since
    # 2026-09-15. Every rule was being asked for its denominator and the
    # ones this predicate refuses were then dropped on the floor: on ruff,
    # which has no primary document, that was the two entry-scoped rules'
    # `split_entries` walk on all 650 documents, twice each, and the
    # repository rule's configuration load once per document - 0.63 s of a
    # 5.9 s sequential sweep, 11%, buying nothing that was printed.
    applies = functools.partial(session.rule_applies, in_archive=False,
                                has_entries=is_primary, repository_rules=False)
    counted = session.count_examined(repo, text, applies)
    examined = {rule.kind: counted[rule.kind] for rule in session.RULES
                if applies(rule)}
    return (relative, findings, None, examined, list(RULE_ERRORS[mark:]),
            session.ancestry_incomplete())


def _validate_chunk(args: tuple[Path, list[tuple[str, bool]]]) -> list[_Result]:
    """A batch of documents in one worker, so the scope is reused across them."""
    repo, items = args
    return [_validate_one(repo, relative, is_primary)
            for relative, is_primary in items]


def _sequential(repo: Path, tasks: list[tuple[str, bool]]) -> _ByPath:
    """Every document, one after another, in this process."""
    gathered = {}
    for relative, is_primary in tasks:
        name, findings, unread, counts, errors, incomplete = _validate_one(
            repo, relative, is_primary)
        gathered[name] = (findings, unread, counts, errors, incomplete)
    return gathered


def survey(repo: Path,
           tasks: list[tuple[str, bool]],
           tracked: list[str] | None = None) -> tuple[_ByPath, int, str | None]:
    """Validate every task. Returns (by_path, workers_used, fallback_reason),
    where each `by_path` value is (findings, unreadable_or_None, examined,
    rule_errors, index_incomplete).

    `workers_used` is 0 for a single-process survey, and the caller PRINTS it.
    Which path ran is not an implementation detail: these are two pieces of
    machinery that have to produce one answer, and a reader who cannot tell
    which one produced theirs has no way to report a difference between them.

    Public since `--introduced-since` became its second caller: that mode
    surveys the documents a range changed through exactly this machinery,
    and a sibling may not import an underscore name.

    `tracked` is the tracked-document list the caller already took from
    `refs.tracked_markdown`, handed to every worker so none re-lists the tree
    for itself; `--sweep` passes the one it built the survey from, and
    `--introduced-since` passes nothing, because its parent lists no tree.
    """
    cpus = os.cpu_count() or 1
    if len(tasks) < _PARALLEL_FLOOR or cpus < 2:
        return _sequential(repo, tasks), 0, None

    workers = min(_MAX_WORKERS, cpus)
    size = max(1, len(tasks) // (workers * 4))
    batches = [(repo, tasks[i:i + size]) for i in range(0, len(tasks), size)]
    gathered: _ByPath = {}
    try:
        # IMPORTED HERE, and inside the `try` rather than above it. `cli.py`
        # imports this module for `--sweep`, so every `--verify` from a git
        # hook paid for a worker pool it can never reach - one process, one
        # primary document and its extras, by construction. Measured on this
        # machine as whole-interpreter wall time, median of 9: a bare
        # interpreter is 36.3 ms, importing `extant.cli` takes it to 159.2, and
        # adding `concurrent.futures` to that costs 20.7 ms more. Standalone it
        # reports 82.3, but that includes `logging` and `traceback`, which this
        # package loads anyway - so the marginal figure is the honest one.
        # Inside the `try` because an ImportError is one more way a pool fails
        # to start, and the handler below is already the right answer to all of
        # them: fall back, and SAY SO. Lazy imports have precedent here -
        # `tomllib` in config.py, `difflib` in gate.py, `importlib` in
        # registry.py - and no quality test forbids them.
        import concurrent.futures

        with concurrent.futures.ProcessPoolExecutor(
                max_workers=workers, initializer=_worker_init,
                initargs=(session.CONFIG, str(repo), tracked)) as pool:
            for produced in pool.map(_validate_chunk, batches):
                for relative, findings, unread, counts, errors, incomplete in produced:
                    gathered[relative] = (findings, unread, counts, errors,
                                          incomplete)
    except Exception as exc:                       # noqa: BLE001
        # Broad deliberately, and tolerable only because it is ANNOUNCED. A
        # pool can fail for reasons that have nothing to do with this tool: a
        # sandbox that forbids spawning, a config that will not pickle, a
        # worker the OS killed. Falling back to the loop is the right answer
        # to every one of them. Falling back QUIETLY is not - the survey would
        # go on printing the summary of a clean run while the machinery it
        # reports using had stopped running, which is the shape this project
        # exists to refuse.
        return _sequential(repo, tasks), 0, "%s: %s" % (exc.__class__.__name__, exc)
    return gathered, workers, None


def _report_empty_survey(repo: Path, fmt: str) -> int:
    """A survey of a repository git tracks no markdown in.

    The diagnostic goes to stderr in every format. What matters is that a
    MACHINE format still emits its document.

    An empty stdout and a report saying "I examined nothing" are different
    facts, and a consumer cannot tell them apart: the first also describes a
    tool that crashed, an upload step pointed at the wrong path, or a binary
    that was never installed. GitHub rejects an empty SARIF file outright, so a
    project whose glob matched nothing got a failed upload rather than a report
    reading zero. That is this module's own subject aimed at itself, one level
    up in the wire format.

    A REFUSAL is the opposite case and stays silent: a run that declined to
    start produced no result, and emitting a document there would assert a
    clean scan that never happened. This branch ran and concluded, so it
    reports.

    `examined` is all zeros because that is true - with no document to read, no
    rule ran. The keys come from the registry rather than from
    `count_examined`, which would ask git questions an unborn HEAD cannot
    answer, and an unborn HEAD is exactly what reaches here.

    Found by tests/harnesses/fuzz.py on its first run.
    """
    if fmt != "text":
        for line in render_findings([], fmt, repo,
                                    examined={rule.kind: 0
                                              for rule in session.RULES},
                                    run_kind="sweep")[0]:
            print(line)
    print("swept 0 markdown files: git tracks none in this repository",
          file=sys.stderr)
    return 0


def summarise_strata(items: list[Located], paths: list[str]) -> list[str]:
    """The per-stratum breakdown, or nothing when it would say nothing.

    Measured on 50 repositories: a sweep reports 54,790 findings and 4,431 of
    them are in ordinary documents. Printing only the first number is the
    misleading count this whole change exists to remove - so the ordinary
    figure leads and the rest is broken out and labelled, never hidden.

    EACH ROW CARRIES ITS DENOMINATOR, for the reason `contract.py` makes a
    missing one raise: "2 historical-record findings" and "2 findings from the
    only changelog in this repository" print identically otherwise, and the
    second is the one that tells a reader whether to care. `paths` is every
    document the sweep looked at, so the documents column is the population
    and not just the documents that happened to produce a finding.

    Returns lines rather than printing, so the caller keeps ownership of `out`
    and the whole thing is testable without capturing stdout.
    """
    findings: dict[str, int] = {}
    hit: dict[str, set[str]] = {}
    for item in items:
        findings[item.stratum] = findings.get(item.stratum, 0) + 1
        hit.setdefault(item.stratum, set()).add(item.path)
    swept: dict[str, int] = {}
    for path in paths:
        name = strata.classify(path)
        swept[name] = swept.get(name, 0) + 1

    ordinary = findings.get("ordinary", 0)
    elsewhere = sum(n for name, n in findings.items() if name != "ordinary")
    if not elsewhere:
        return []
    lines = [f"  {ordinary} finding(s) in ordinary documents; "
             f"{elsewhere} elsewhere:"]
    for name in strata.ORDER:
        if name == "ordinary" or not findings.get(name):
            continue
        lines.append(f"    {name}  {findings[name]} finding(s) in "
                     f"{len(hit.get(name, ()))} of {swept.get(name, 0)} "
                     f"document(s)")
    return lines


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
    try:
        paths = refs.tracked_markdown(session.context(repo))
    except (subprocess.CalledProcessError, OSError):
        # An UNBORN HEAD has no tree to list, so `git ls-tree HEAD` exits
        # 128 and the error reached the user as a traceback. A repository
        # someone has just created is a legitimate thing to point a
        # first-run survey at, and the honest answer is the same one a
        # repository with no markdown gets.
        paths = []
    if not paths:
        return _report_empty_survey(repo, fmt)

    # The listing as `tracked_markdown` returned it, BEFORE exclusions, kept
    # for the scopes below: what a rule reading the tracked list would get
    # by asking git again, seeded so nothing here asks again. It is the
    # listing above, taken outside any scope and so memoised nowhere.
    tracked = paths
    tracked_total = len(paths)
    paths, excluded_counts, conflicting = apply_exclusions(paths)
    if conflicting:
        return 1
    if not paths:
        print(f"swept 0 markdown files: exclude_paths removed all "
              f"{tracked_total} that git tracks", file=sys.stderr)
        return 0

    vetted, unvetted = partition_documents(repo, paths)
    primary = _normalise(session.CONFIG.primary_doc)
    sections: list[tuple[str, list[str], bool]] = [
        ("vetted", vetted, True), ("unvetted", unvetted, False)]
    results: dict[str, list[Located]] = {"vetted": [], "unvetted": [],
                                         "repository": []}
    unreadable: list[str] = []
    # Dispatched to the survey and produced no result at all.
    unreturned: list[str] = []

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
    previous_document = session.document()
    with session.run_scope() as scope:
        # The tracked list this survey was built from, seeded into the scope
        # a sequential survey reads through, and handed to the workers of a
        # parallel one, so the tree is listed ONCE per survey. It was listed
        # once more by every process whose documents reached `sites.py`.
        scope.tracked_markdown[str(repo)] = tracked
        try:
            # Seeded here, inside the stable scope, for two reasons at once: it
            # fixes the printing ORDER to the one `--verify` uses, so the two modes
            # can be read side by side, and its repository-scoped entries are the
            # counts those rules get - they are the repository's candidates, not
            # any document's, so they are read once rather than per file.
            repository_examined = session.count_examined(repo, "")
            examined: dict[str, int] = {kind: 0 for kind in repository_examined}
            tasks = [(relative, relative == primary)
                     for _label, group, _gates in sections for relative in group]
            gathered, workers, fallback = survey(repo, tasks, tracked=tracked)

            # OR-ed across every document's outcome, because a worker's scope
            # is not this one: the flag is the only way its index's bound
            # reaches the note printed below.
            index_incomplete = False
            for label, group, _gates in sections:
                for relative in group:
                    outcome = gathered.get(relative)
                    if outcome is None:
                        # A document that went out and did not come back is not
                        # a document with no findings. Skipping it here would
                        # let a survey lose a file and still print the summary
                        # of a clean one, so it is collected and named beside
                        # the unreadable ones instead.
                        unreturned.append(relative)
                        continue
                    findings, unread, doc_examined, errors, incomplete = outcome
                    index_incomplete = index_incomplete or incomplete
                    # Only from a worker. In this process the append inside
                    # `_validate_one` already happened, and adding them again
                    # would report every rule error twice.
                    if workers and errors:
                        RULE_ERRORS.extend(errors)
                    if unread is not None:
                        unreadable.append(unread)
                        continue
                    # `_gates` is the section's own flag: vetted documents decide
                    # the exit code, unreviewed ones are surveyed and reported.
                    # Carrying it here is what lets SARIF publish a survey finding
                    # as a note rather than an error.
                    results[label].extend(
                        Located(relative, f, primary=(relative == primary),
                                gating=_gates,
                                stratum=strata.classify(relative))
                        for f in findings)
                    for kind, count in doc_examined.items():
                        examined[kind] += count

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
            for rule in session.RULES:
                if rule.scope != "repository":
                    continue
                # Repository findings are surveyed and never gate - the section
                # heading says "not gated" and the exit code honours it, so the
                # machine format must say the same thing.
                # Isolated exactly as the per-document loop in `validate` is,
                # and for the same reason: these run outside it, so a
                # repository rule that raised would take down a whole survey
                # rather than one rule of it.
                try:
                    produced = rule.check(session.context(repo), "")
                except Exception as exc:                   # noqa: BLE001
                    RULE_ERRORS.append(
                        (rule.kind, f"{exc.__class__.__name__}: {exc}"))
                    produced = []
                results["repository"].extend(
                    Located(rule.subject_file or ".", finding, primary=False,
                            gating=False,
                            stratum=strata.classify(rule.subject_file or "."))
                    for finding in produced)
                examined[rule.kind] = repository_examined[rule.kind]
        finally:
            # The DOCUMENT only. The run scope hands itself back, on the
            # failing path too; this is the half that is per-file, and
            # restoring it only after the loop left the last swept document
            # installed whenever a rule raised.
            session.install_document(previous_document)

    # Diagnostics follow the convention the other modes use: stdout unless
    # SARIF, where stdout must carry nothing but one JSON value. Writing the
    # summary to stderr unconditionally interleaved it AHEAD of the findings,
    # because the two streams flush independently.
    out = sys.stderr if fmt == "sarif" else sys.stdout
    # ALL THREE keys, named once and read four times below. Spelling the
    # concatenation out at each use is how the `swept ...` line and the
    # per-stratum breakdown came to be summed from different sets.
    everything = results["vetted"] + results["unvetted"] + results["repository"]
    if fmt == "text":
        section_lines, entries = format_sweep_sections(results)
        for line in section_lines:
            print(line, file=out)
    else:
        entries = 0
        for line in render_findings(everything, fmt, repo,
                                    examined=examined, run_kind="sweep")[0]:
            print(line)

    # The denominator, per section. "0 findings" and "0 files looked at" print
    # identically without it, and a sweep is the mode where that is easiest to
    # get wrong: a wrong glob would report a clean repository.
    print(f"\nswept {len(paths)} markdown file(s): "
          f"{len(vetted)} configured ({len(results['vetted'])} finding(s)), "
          f"{len(unvetted)} unreviewed ({len(results['unvetted'])} finding(s))",
          file=out)
    for line in sweep_entry_note(entries, len(everything)):
        print(line, file=out)
    # Summing only `vetted` and `unvetted` would under-report by however many
    # repository-scoped findings the run produced, and the breakdown would
    # silently stop matching the `swept ...` line directly above it - a table
    # that does not add up, which is the one failure a reader would not notice
    # because each row looks reasonable alone. Hence `everything`.
    for line in summarise_strata(everything, paths):
        print(line, file=out)
    # Which machinery produced the numbers above. A parallel survey and a
    # serial one are required to agree, and the only way a disagreement gets
    # reported is if the reader can say which one they ran.
    if workers:
        print(f"  surveyed across {workers} worker process(es)", file=out)
    if fallback is not None:
        print(f"  NOTE: the parallel survey could not start, so every "
              f"document was read in this process instead: {fallback}",
              file=out)
    # Never folded into the unreadable count: a file that could not be READ
    # and a file that was dispatched and never came back are different
    # failures, and the second one means the survey lost a document rather
    # than judged it.
    if unreturned:
        print(f"  {len(unreturned)} document(s) were dispatched and returned "
              f"no result, so they were NOT examined: "
              f"{', '.join(sorted(unreturned))}", file=out)
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
    repository_rules = sum(1 for rule in session.RULES
                           if rule.scope == "repository")
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
    # Beside the denominators, for the reason `report_rule_errors` (session.py)
    # gives: a rule that crashed reports no findings, which is what a clean
    # survey looks like. A sweep is where that matters most - hundreds of
    # documents, one malformed input - and it is exactly why isolation was
    # worth adding here.
    session.report_rule_errors(lambda line: print(line, file=out))
    # What the checkout is, beside the denominators as every gating mode has
    # them. The survey printed neither the shallow nor the partial note for
    # a year - on the mode most often pointed at a repository nobody here had
    # seen, where a wall of dead SHAs from a depth-limited copy is exactly
    # what a reader needs told. 139 of the 152 corpus clones are partial.
    report_repository_notes(lambda line: print(line, file=out), repo,
                            index_incomplete)
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
    # An errored run never exits 0, even in the mode whose findings do not
    # gate. "Nothing failed here" and "a rule could not be run" are different
    # answers and a survey must not give the first when it means the second.
    # `unreturned` gates, and `unreadable` deliberately does not. The two look
    # alike and are not: a file that cannot be decoded is a fact about the
    # REPOSITORY, reported and survived, while a document dispatched to the
    # survey that came back with nothing is a fact about this TOOL. Exiting 0
    # there would report a clean run for work that did not happen, which is
    # the conflation every denominator in this file exists to refuse.
    return 1 if (results["vetted"] or RULE_ERRORS or unreturned) else 0


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
    # A trailing slash names a DIRECTORY, as it does in a .gitignore, so a
    # file of that name is not matched and everything beneath it is. The
    # matcher took the file too until 2026-09-20, when git's own matcher was
    # fed every tracked path of 152 corpus clones beside it: five
    # disagreements in 793,684 distinct paths, every one a Debian packaging
    # FILE called `docs` or `vendor`, none of them a document. Closed so the
    # two agree on every shape this docstring claims.
    directory_only = pattern.endswith("/")
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
    # What may follow the matched name: something beneath it, or nothing when
    # the name itself may be the file - never nothing for a directory pattern.
    beneath = r"(?:/.*)" if directory_only else r"(?:/.*)?"
    if anchored:
        # Rooted at the repository. A directory pattern also covers what is
        # underneath it, which is what a reader means by excluding a folder.
        source = rf"^{core}{beneath}$"
    else:
        # A bare name is a segment anywhere, and everything beneath it.
        source = rf"^(?:.*/)?{core}{beneath}$"
    try:
        return re.compile(source)
    except re.error:
        return None


def apply_exclusions(paths: list[str]) -> tuple[list[str], dict[str, int], list[str]]:
    """The configured skip-list, applied to `paths`, and the contradictions it
    produced: (kept, {pattern: how many it matched}, configured documents the
    patterns removed).

    One implementation for the two modes that survey many documents - the
    sweep and `--introduced-since` - so the per-pattern counts and the
    refusal below cannot come to disagree between them, which is the
    two-scanners shape this project keeps finding.

    A CONFIGURED document that an exclusion REMOVED is a contradiction, not a
    preference: one setting says gate on this file and another says never
    read it. Reported rather than resolved, because either answer silently
    overrides something the author wrote. Printed here, once, and returned
    so the caller decides the exit code.

    Keyed on what was actually removed, never on "configured but missing".
    `primary_doc` defaults to a filename most repositories do not have, so
    comparing against the configured set alone reported a conflict for a
    document no exclusion had touched - a different condition, which
    `--verify` already names as "no such document".
    """
    if not session.CONFIG.exclude_paths:
        return paths, {}, []
    present = {p.replace("\\", "/") for p in paths}
    kept, counts = excluded_documents(paths, session.CONFIG.exclude_paths)
    configured = {_normalise(session.CONFIG.primary_doc),
                  *(_normalise(d) for d in session.CONFIG.extra_docs)}
    remaining = {p.replace("\\", "/") for p in kept}
    conflicting = sorted((configured & present) - remaining - {""})
    for document in conflicting:
        print(f"CONFLICT: `{document}` is configured to be checked and "
              f"also matches exclude_paths; excluding it would silently "
              f"stop gating on a document you asked to gate on",
              file=sys.stderr)
    return kept, counts, conflicting


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
    vetted_names = {session.CONFIG.primary_doc, session.CONFIG.archive_doc,
                    *session.CONFIG.extra_docs}
    normalised = {_normalise(name) for name in vetted_names if name}
    vetted = [p for p in paths if p in normalised]
    return vetted, [p for p in paths if p not in normalised]
