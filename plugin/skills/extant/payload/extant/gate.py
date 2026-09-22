"""The modes that GATE: check one document's claims and decide an exit code.

The counterpart to extant/sweep.py, which holds the modes that survey and
report without gating. Three modes live here, differing only in where the text
comes from:

* `--validate FILE` reads a document from the working tree, plus the archive
  and every `extra_docs` entry.
* `--verify` is that, aimed at the document `.extant.toml` names.
* `--check-text` reads ONE document from stdin, so a caller holding a draft
  that is not on disk yet can ask the same question about it.

Everything after the last document is `_finish`, shared by all three, because
the output promises - the denominator, the suppressed count, a raised rule
never exiting 0 - have to hold identically however the text arrived.

They were in extant/cli.py until `run_validate` reached 295 lines against the
303-line ceiling in tests/test_module_quality.py, with `--check-text` still to
be written. That module's docstring argued the modes belonged together because
each was "a handful of lines over machinery that already exists", and that
argument was true of `--collect`, `--archive`, `--search` and `--selftest`,
which stayed. It stopped being true of this one some time before the ceiling
noticed.

What made the split possible was moving the baseline bookkeeping to
`report.Collector`. Four locals - the recorded entries, what has been matched,
the occurrences already spent, the suppressed tally - were held together only
by a nested closure, and a function cannot be split around a closure over its
own locals.
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path, PurePosixPath
from typing import Callable, TextIO

from extant import refs, session
from extant.commits import load_sha_map, translate_shas
from extant.config import StatusConfig
from extant.finding import Finding, rel
from extant.git import has_commit_graph, is_partial, is_shallow
from extant.refs import renamed_to
from extant.registry import RULE_ERRORS
from extant.report import (
    BASELINE_NAME, Collector, load_baseline, render_findings, write_baseline,
)
from extant.scope import RunScope
from extant.sites import reference_path, relative_spelling, resolve_reference
from extant.links import link_sites
from extant.text import format_for, prose

__all__ = ["report_denominators", "report_index_note",
           "report_repository_notes", "run_check_text", "run_validate",
           "suggest_renames"]

# What `--check-text` calls the document when `--as-path` was not given.
# Named rather than blank: every diagnostic line here begins "checked <name>",
# and a blank one reads as a bug in the tool rather than as a deliberate
# absence of a path.
STDIN_NAME = "<stdin>"


def suggest_renames(repo: Path, base: Path, text: str, relative: str,
                    findings: list[Finding]) -> str:
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
    ctx = session.context(repo)

    # THE INVARIANT: a patch is only ever offered for a claim a rule REPORTED.
    # Before this, `suggest_renames` scanned the document itself, with a filter
    # that differed from the rule's five ways - so it offered to rewrite a link
    # split across a newline that `--validate` had just declared clean, while
    # exiting 0. A patch is an edit to somebody's prose; the authority for it
    # has to be a finding, not a second opinion.
    #
    # Taken from the findings BEFORE the baseline is applied, deliberately. A
    # baselined finding is still wrong - it is only not new - and keying this
    # on what survived suppression would have quietly coupled the patch
    # generator to the baseline, so adopting one would stop offering repairs
    # for everything it forgave.
    linked = {f.subject for f in findings
              if f.kind == "dead-md-link" and f.subject}
    pointed = {f.subject for f in findings
               if f.kind == "dead-path-pointer" and f.subject}

    for _number, raw, target, _html in link_sites(ctx.doc, text):
        if target not in linked or resolve_reference(ctx, base, target)[0]:
            continue
        # `target` is what RESOLVES; `raw` is what the document actually says,
        # and the replacement below matches text on the page. They differ for a
        # percent-encoded link, and there the two cannot be reconciled without
        # GUESSING an encoding for the replacement - `docs/new guide.md` has to
        # go back as `docs/new%20guide.md` to stay a working link, and choosing
        # that spelling is authoring rather than checking. Refused, explicitly:
        # the finding is still reported, and no patch is offered for it.
        path_part = raw.split("#", 1)[0].split("?", 1)[0]
        if path_part != target:
            continue
        # Looked up under the path the link RESOLVES to and spelled back
        # RELATIVE TO THE DOCUMENT, the two halves of one fact: the map's keys
        # and answers are repository-relative, a link is relative to its page.
        # Asked as written, `[it](old.md)` in `docs/` found nothing; answered
        # as written, it would have been repointed at `docs/new.md`, which from
        # `docs/` names `docs/docs/new.md`. A root-relative link stays rooted.
        rooted = target.startswith("/")
        named = (target.lstrip("/") if rooted
                 else reference_path(repo, base, target) or target)
        moved = renamed_to(ctx, named)
        if moved:
            spelled = "/" + moved if rooted else relative_spelling(repo, base, moved)
            # The fragment or query survives the move. `[x](a.md#install)` is
            # repointed to `[x](b.md#install)`, which the previous code could
            # not do at all: it replaced on the fragment-stripped target, so
            # `](a.md)` matched nothing in a document that says `](a.md#install)`
            # and the patch came out empty.
            replacements.append((raw, spelled + raw[len(path_part):]))

    for raw in ctx.config.path_pointer.findall(prose(ctx.doc, text)):
        if raw not in pointed or resolve_reference(ctx, repo, raw)[0]:
            continue
        # The rule's own order: from the root as written, then from beside
        # the document, spelled back the way each was asked.
        moved = renamed_to(ctx, raw)
        if moved:
            replacements.append((raw, moved))
            continue
        if base != repo:
            beside_path = reference_path(repo, base, raw)
            moved = renamed_to(ctx, beside_path) if beside_path is not None else None
            if moved:
                replacements.append((raw, relative_spelling(repo, base, moved)))

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


def report_denominators(diag: Callable[[str], None], repo: Path, name: str,
                        examined: dict[str, int],
                        index_incomplete: bool = False) -> int:
    """The counts, and everything that qualifies them. Returns the mark
    `session.report_rule_errors` hands back - how many rule errors have been
    printed so far - for the next call to continue from. It was annotated
    as a boolean from the split that made this module on 2026-08-31, while
    every caller passed it on as the mark; the type checker was the first
    reader to notice.

    `index_incomplete` is the one qualifier the caller has to carry in: it is
    a fact of the run scope the document was examined under, read there with
    `session.ancestry_incomplete()` before the scope closed, because this
    prints after it has.

    Split out of `run_validate` when the shallow-repository note took that
    function one line past the ceiling in tests/test_module_quality.py. The
    block was always one thing - here is what was counted, and here is every
    reason a count might not mean what it looks like - so it reads better named
    than it did inline.

    Public since the split that made this module: `--check-text` prints the
    same block for the same reason, and a leading underscore on a name another
    mode reaches for is a false claim about the boundary.
    """
    summary = ", ".join(f"{kind} {n}" for kind, n in examined.items())
    blind = [kind for kind, n in examined.items() if n == 0]
    diag(f"checked {name}: {summary}")
    # Beside the denominators, because that is where a reader looks to
    # decide whether a quiet rule was quiet or broken.
    errors_reported = session.report_rule_errors(diag)
    if blind:
        diag("  NOTE: these rules matched nothing at all - either this "
             "document makes no such claims, or the pattern is wrong: "
             + ", ".join(blind))
    report_repository_notes(diag, repo, index_incomplete)
    return errors_reported


def report_repository_notes(diag: Callable[[str], None], repo: Path,
                            index_incomplete: bool = False) -> None:
    """What the checkout is, when that changes what a count means.

    Split out of `report_denominators` when `--introduced-since` needed the
    same two notes under a different denominator line: a gate on a depth-
    limited pull-request checkout has every older SHA dead, and the note is
    what separates that from a document full of invented ones. One
    implementation, so the two modes cannot describe one checkout in two
    voices - and `--sweep` prints them through it too, since tranche 10 of
    the internals review; it had printed neither, on the mode most often
    pointed at a repository nobody here had seen.

    The first two are read from the checkout. The third is handed in: whether
    an ancestry index reached its bound is a fact of the run scope, and this
    prints after that scope has closed.
    """
    # Beside the denominators for the same reason they are printed at all: a
    # `dead-sha` count taken from a shallow clone describes the slice that was
    # cloned rather than the repository, and a reader cannot tell those apart
    # from the number alone.
    if is_shallow(repo):
        # "shallow repository" rather than "shallow clone", and not for style.
        # tests/harnesses/smoke.py scans this package's operational source for
        # the shapes a network call takes, and the verb for copying a remote
        # repository is one of them. That scan keeps string literals on
        # purpose, because a git subcommand only ever reaches git as one, so a
        # scan that dropped them would be permanently clean and permanently
        # useless. It therefore cannot tell a sentence from an argument, and
        # the word in a message here read as a network operation in a tool
        # that opens no sockets. tests/test_module_quality.py now runs the
        # same scan in the suite, so the next one fails before a push.
        #
        # It is also the better term: `git rev-parse --is-shallow-repository`
        # is what git calls the question, and a linked worktree of a shallow
        # checkout is not itself a copy of anything.
        diag("  NOTE: this is a shallow repository, so commit SHAs were "
             "checked against the history present locally rather than "
             "against everything upstream.")
    # The same shape from the other direction: the history is all here and
    # some of the OBJECTS are not. They stay not here - `environment()` in
    # extant/git.py refuses the retrieval git would otherwise do mid-command
    # - so a rename hint or a blob-reading rule answers from less than the
    # repository holds, and the reader is told so rather than left to infer
    # it from a hint that did not appear. Worded without the words the
    # network-shape scan refuses in a literal, as the note above is.
    if is_partial(repo):
        diag("  NOTE: this is a partial repository, so objects not present "
             "locally were left missing rather than retrieved over the "
             "network. A rename hint or a blob-reading rule answers from "
             "what is here.")
    if index_incomplete:
        report_index_note(diag, repo)


def report_index_note(diag: Callable[[str], None], repo: Path) -> None:
    """The third note, and the only one the run pays for rather than the
    reader. Called once the caller knows an ancestry index reached
    `refs.INDEX_BOUND` in some scope of the run.

    An index that reached the bound settles every question past it by
    walking, and a commit-graph would make each of those walks
    near-constant-time - measured on rust (extant/git.py, `has_commit_graph`)
    at 7.5x on the index, 27x on the batch and 77x on `merge-base`. Printed
    only when BOTH hold - an index that came back incomplete AND no graph -
    because a bound the history merely exceeds is not a cost anyone paid,
    and a repository that has the file is already paying nothing. Nothing is
    written: this tool checks and never authors, a stranger's `.git` least of
    all, so the note names the command and stops.

    Its own function, unlike the shallow and partial notes, because
    `run_validate` examines the archive and every extra document in scopes
    of their own after the primary's notes have printed; an index built only
    there would otherwise go unmentioned.
    """
    if has_commit_graph(repo):
        return
    diag("  NOTE: the ancestry index reached its bound of "
         f"{refs.INDEX_BOUND:,} commits and this repository has no "
         "commit-graph, so every question past the bound was settled "
         "by walking the history; `git commit-graph write --reachable` "
         "would answer those near-instantly. Nothing was written here.")


def _diagnostic_stream(args: argparse.Namespace) -> TextIO:
    """Where human output goes, given what stdout has to stay pure for.

    A SARIF document with a progress line prepended is not a SARIF document,
    and a patch with log lines in it is rejected by `git apply` along with
    everything else in the file. stdout carries ONE machine-readable thing at a
    time; everything human moves to stderr in both cases.
    """
    return (sys.stderr if (args.format == "sarif" or args.suggest_fixes)
            else sys.stdout)


def _sha_map(args: argparse.Namespace) -> tuple[dict[str, str] | None, bool]:
    """The `--sha-map` mapping: (mapping or None, whether the run may go on).

    A TRACEBACK IS A POOR ANSWER TO A COMMON SITUATION. `run_validate` makes
    that argument one screen below for a document that is not there, and this
    flag had the opposite behaviour: `load_sha_map` opened the path directly,
    so naming a map that does not exist exited with FileNotFoundError, a stack
    trace, and nothing a reader could act on.

    Naming one that is not there is the ORDINARY way to reach this flag rather
    than an exotic one. The README's own invocation is
    `--sha-map .git/filter-repo/commit-map`, and that path does not exist until
    somebody has actually run `git filter-repo` - so a user who copies the
    documented line before rewriting anything, or who runs it from the wrong
    directory, gets the traceback rather than the sentence.

    ONE FUNCTION, TWO CALLERS, because `--validate` and `--check-text` both
    read this flag and must refuse identically. Two spellings of one refusal is
    the "one claim, two scanners" shape this project keeps finding, and here it
    would be invisible: both call sites looked correct.

    The exit code the callers use for a refusal is 2, which the CLI already
    documents as "the configuration is unreadable" - a map named on the command
    line and not readable is that, not a finding and not a clean run.
    """
    if not args.sha_map:
        return None, True
    try:
        return load_sha_map(args.sha_map), True
    except (OSError, UnicodeDecodeError) as exc:
        # REPORTS WHAT IT CAUGHT, which is the one shape a wide handler is
        # allowed in here: the degraded path names itself rather than printing
        # what a healthy one prints.
        print(f"cannot read the rewrite map at {args.sha_map} "
              f"({exc.__class__.__name__}). --sha-map takes the commit-map "
              f"that `git filter-repo` writes, usually at "
              f".git/filter-repo/commit-map.", file=sys.stderr)
        return None, False


def _open_baseline(
    repo: Path, args: argparse.Namespace
) -> tuple[dict[str, dict[str, str]] | None, Path]:
    """(recorded entries, resolved path), or (None, path) if it would not load.

    None means STOP - the caller returns 2 - rather than "no baseline", which
    is the distinction `load_baseline` raises for: a typo'd path that read as
    an empty baseline would turn a ratcheted run back into an ordinary one
    without saying so.
    """
    # --baseline-check implies reading one, so it does not also need
    # --baseline. Both fall back to the conventional filename.
    # Against the REPO, not the process cwd. A hook or a CI step runs
    # from wherever it likes and passes --repo, and a relative baseline
    # would then be looked for somewhere else entirely - reported as
    # missing, or worse, silently a different file.
    path = Path(args.baseline or BASELINE_NAME)
    if not path.is_absolute():
        path = repo / path
    # Recording a baseline must see everything, so suppression is off while
    # writing one. Otherwise a second --write-baseline against an existing
    # baseline would record only what that baseline had missed, quietly
    # shrinking it each time it was run.
    if not (args.baseline or args.baseline_check) or args.write_baseline:
        return {}, path
    try:
        return load_baseline(path), path
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return None, path


def _finish(diag: Callable[[str], None], repo: Path, args: argparse.Namespace,
            found: Collector, baseline_path: Path, examined: dict[str, int],
            exit_code: int, errors_reported: int) -> int:
    """Everything after the last document: formats, baseline, rule errors.

    Shared by both gating modes rather than written twice, because every one of
    these is a promise about output that has to hold identically however the
    text arrived. A `--check-text` that quietly skipped the suppressed count,
    or reported a clean exit over a raised rule, would be a second answer to a
    question this tool is supposed to have one answer to.
    """
    # Machine formats are emitted in one block, after every document has
    # been read, because SARIF is a single JSON value and annotations are
    # easier to read grouped than interleaved with progress lines.
    if args.format != "text":
        # `examined` is the primary document's denominator, the same figure
        # the `checked ...` diagnostic prints. A machine consumer of the
        # SARIF could not see it at all before.
        for line in render_findings(found.located, args.format, repo,
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
        written = write_baseline(path, found.located)
        diag(f"recorded {written} finding(s) in {rel(repo, path)}")
        diag("Each is still wrong. They are excluded from future runs so "
             "that NEW ones are visible; prune them with --baseline-check.")
        return 0

    if found.baselined:
        # Stated on every run, in both directions. "no findings" and "no new
        # findings, 40 suppressed" are different facts, and a baseline that
        # hides its own size is the denominator failure this project exists
        # to surface, reintroduced by one of its own features.
        diag(f"{len(found.located)} new finding(s), {found.suppressed} "
             f"suppressed by {rel(repo, baseline_path)}")

    # Anything a later pass raised, which belongs to no `checked ...` line of
    # its own.
    session.report_rule_errors(diag, errors_reported)
    if RULE_ERRORS:
        # An errored run NEVER exits 0. A partial answer that reports
        # success is the failure this whole project exists to prevent, and
        # it is the one thing that would make per-rule isolation worse than
        # letting the traceback out.
        exit_code = 1

    if args.baseline_check:
        stale = found.stale()
        diag(f"\nbaseline: {len(found.baselined)} entr(y/ies), "
             f"{len(found.matched)} still occur, {len(stale)} do not")
        for entry in stale:
            diag(f"  STALE  {entry['path']}: [{entry['kind']}] {entry['detail']}")
        if stale:
            diag("\nThese no longer happen: the claim was fixed, or deleted. "
                 "Remove them, or the baseline keeps forgiving something that "
                 "is not there.")
            exit_code = 1

    return exit_code


def run_validate(repo: Path, args: argparse.Namespace,
                 status: StatusConfig) -> int:
    """`--validate FILE` / `--verify`: check one document's claims and gate.

    Also validates the archive and any `extra_docs`, applies `--sha-map`
    translation, and handles baselining and `--suggest-fixes`. The output
    tail - machine formats, the baseline summary, rule errors - is `_finish`,
    shared with `--check-text` so the two cannot answer differently.
    """
    stream = _diagnostic_stream(args)

    def diag(*parts: object) -> None:
        print(*parts, file=stream)

    target = Path(args.validate)
    if not target.is_file():
        # A traceback here is a poor answer to a common situation: the
        # document lives elsewhere in this project, or the config points at
        # the wrong name. Say which file was expected and where it came from.
        diag(f"no such document: {target}")
        diag(f"  primary_doc is '{status.primary_doc}', from "
             f"{status.source}")
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
    session.set_document(link_base=target.parent)
    mapping, readable = _sha_map(args)
    if not readable:
        return 2
    if mapping is not None:
        text, changed = translate_shas(text, mapping)
        if changed:
            with open(target, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            diag(f"translated {changed} stale SHA reference(s) in {target}")
    baselined, baseline_path = _open_baseline(repo, args)
    if baselined is None:
        return 2
    found = Collector(baselined,
                      echo=(lambda line: print(line, file=stream))
                      if args.format == "text" else None)

    # Which document this is, for rules that key on the FILENAME. Set
    # before validate rather than passed into it: validate restores the
    # value it found on entry, so count_examined below still sees the
    # document the rules just read. Without this, manifest-floor-mismatch
    # works in --sweep and is silent in --verify, and reports 0 examined
    # beside 0 findings - the exact conflation the denominator exists to
    # prevent. Found by running the gate, not by any test.
    session.set_document(doc_path=rel(repo, target))
    # ONE run scope across the whole run, or one per document, and `--sha-map`
    # is what decides. A stable scope promises the checkout does not change
    # while it is held, and with a map this mode REWRITES documents between
    # reads - the archive is translated and written back after the primary
    # document was examined - so there the scope stays per document, opened
    # after each rewrite. Without a map nothing here writes until the
    # baseline, after every scope has closed, and one scope spans every
    # document. The review's 5.7 measured the difference on this
    # repository: the ref table and the trunk index were each built twice
    # per `--verify`, once for the status document and once for the one
    # extra document carrying a release claim, 101 ms of a 700 ms run.
    # tests/test_spawn_budget.py asserts both arms - once per run without a
    # map, once per asking document with one.
    #
    # Either way the scope spans both halves of examining a document. The
    # two calls ask the same repository the same questions - the origin
    # remote, most visibly - and without a scope spanning them the second
    # re-asked everything the first had already learned. Measured on this
    # repository's own document: 7 git processes for one --verify, of which
    # `remote get-url origin` was two.
    def document_scope() -> contextlib.AbstractContextManager[RunScope | None]:
        if mapping is None:
            return contextlib.nullcontext()
        return session.run_scope()

    whole_run = (session.run_scope() if mapping is None
                 else contextlib.nullcontext())
    with whole_run:
        with document_scope():
            findings = session.validate(repo, text)
            exit_code = 1 if found.record(rel(repo, target), findings,
                                          primary=True) else 0

            # The denominator. Without it a clean run and a run that checked
            # nothing print identically - the failure that recurred five
            # times in one day. A rule reporting 0 examined is either
            # genuinely absent from this document or broken, and the reader
            # has to be able to tell.
            examined = session.count_examined(repo, text)
            # Read INSIDE the scope, which is the whole reason the note it
            # feeds took a year to print: the index is a fact of the scope,
            # and the notes print after the scope has closed.
            index_incomplete = session.ancestry_incomplete()
        errors_reported = report_denominators(
            diag, repo, Path(args.validate).name, examined, index_incomplete)

        # --verify/--validate used to read only their target file, so
        # content moved into the archive by --archive escaped validation
        # forever: a dead reference or a stale live-claim could sit there
        # unreported indefinitely. Validate it too, whenever it exists.
        # The archive and the extras are examined after the repository notes
        # have printed beside the primary document. An index that reached its
        # bound only there is still a cost the run paid, so the flag is
        # gathered across them and the one note printed once, at the end.
        extras_incomplete = False
        archive_doc = session.config().archive_doc
        archive_path = repo / archive_doc
        if archive_path.exists():
            with open(archive_path, encoding="utf-8", newline="") as fh:
                archive_text = fh.read()
            if mapping is not None:
                archive_text, archive_changed = translate_shas(archive_text,
                                                               mapping)
                if archive_changed:
                    with open(archive_path, "w", encoding="utf-8",
                              newline="") as fh:
                        fh.write(archive_text)
                    diag(f"translated {archive_changed} stale SHA "
                         f"reference(s) in {archive_doc}")
            session.set_document(doc_path=archive_doc)
            # Opened after the rewrite above, when it is a scope of its own,
            # and held so the index flag can be read before it closes.
            with document_scope():
                archive_findings = session.validate(repo, archive_text,
                                                    in_archive=True)
                extras_incomplete |= session.ancestry_incomplete()
            if found.record(archive_doc, archive_findings, primary=False):
                exit_code = 1

        # Extra documents: CLAUDE.md, AGENTS.md, a README. They carry the
        # same kinds of checkable claim and rot the same way, but have no
        # dated entries, so the entry-scoped rules are skipped exactly as
        # they are for the archive. A project whose status lives in a
        # tracker rather than a document still gets these checked, which is
        # most of the reason the setting exists.
        for relative in status.extra_docs:
            extra = repo / relative
            if not extra.is_file():
                # A configured document that is absent is itself a finding,
                # not a log line: a machine consumer has to see it too, or a
                # broken extra_docs entry disappears from every format but
                # the human one. Line 1, because there is no file to point
                # into.
                if found.record(relative, [Finding(
                    1, "missing-document",
                    "listed in extra_docs but does not exist",
                )], primary=False):
                    exit_code = 1
                continue
            with open(extra, encoding="utf-8", newline="") as fh:
                extra_text = fh.read()
            session.set_document(link_base=extra.parent, doc_path=relative)
            # Findings and denominator are two halves of one examination and
            # must not re-ask git the same questions, whichever scope this is.
            with document_scope():
                extra_findings = session.validate(repo, extra_text,
                                                  has_entries=False)
                new_extra = found.record(relative, extra_findings,
                                         primary=False)
                examined_extra = session.count_examined(repo, extra_text)
                extras_incomplete |= session.ancestry_incomplete()
            # Repository-scoped rules do not run for an extra document, so
            # reporting their candidate count here claims coverage that was
            # not provided. A denominator that overstates is worse than
            # none: it is the reassuring number, not the honest one.
            skipped = {rule.kind for rule in session.RULES
                       if rule.scope == "repository"}
            # Zero counts are REPORTED, not filtered. "examined 0" and "not
            # applicable here" are different facts, and dropping the zeros
            # made an extra document look fully covered while a rule sat
            # blind - the exact conflation the primary summary avoids.
            checked = ", ".join(f"{kind} {n}"
                                for kind, n in examined_extra.items()
                                if kind not in skipped)
            diag(f"checked {relative}: {checked or 'nothing applicable'}")
            errors_reported = session.report_rule_errors(diag, errors_reported)
            if new_extra:
                exit_code = 1
    session.set_document(link_base=None)
    if extras_incomplete and not index_incomplete:
        report_index_note(diag, repo)

    if args.suggest_fixes:
        # Written to stdout as a patch and never applied. In sarif mode the
        # document must stay pure JSON, so the patch goes to stderr instead
        # of corrupting it.
        patch = suggest_renames(repo, target.parent, text,
                                rel(repo, target), findings)
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

    return _finish(diag, repo, args, found, baseline_path, examined,
                   exit_code, errors_reported)


def _read_stdin(diag: Callable[[str], None]) -> str | None:
    """The document, or None when stdin did not carry a usable one.

    Read as BYTES and decoded here rather than through `sys.stdin`, for two
    reasons that are the same reason. `_survivable_output` reconfigures the
    streams with `errors="replace"`, and a document decoded that way would be
    silently corrupted before any rule saw it - findings about bytes that are
    not there, which is precisely what the file path refuses to do. And the
    console encoding a process inherits has nothing to do with the encoding of
    a document piped into it.
    """
    try:
        raw = sys.stdin.buffer.read()
    except (OSError, ValueError, AttributeError):
        # No usable stdin at all - a detached process, or a caller that
        # replaced the stream with something that has no buffer. Reported
        # rather than treated as an empty document, because a run that
        # examined nothing must not print what a clean run prints.
        diag("--check-text: could not read stdin")
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print(f"stdin: not valid UTF-8 ({exc.reason} at byte {exc.start}). "
              f"The document must be text.", file=sys.stderr)
        return None
    if not text.strip():
        # Nothing arrived. Measured before this guard existed: an empty stdin
        # printed every rule at 0 and exited 0, which is "nothing was checked"
        # wearing the exact appearance of "nothing was wrong" - the one
        # conflation this whole tool exists to remove, reintroduced by its
        # newest mode.
        #
        # And it is the likely failure rather than an exotic one: this mode is
        # invoked from hooks and harnesses through a pipe, and a pipe that
        # delivers nothing is a plumbing mistake, not an empty document
        # somebody meant to check.
        print("--check-text: nothing arrived on stdin. Pipe the document in, "
              "or use --validate for a file. An empty document would report "
              "every rule as clean, which is not the same as checking one.",
              file=sys.stderr)
        return None
    return text


def _inside_repo(relative: str) -> bool:
    """Is this a repository-relative path that stays inside the repository?

    Lexical, and deliberately: the path names a document that does not exist,
    so there is nothing on disk to resolve it against, and `resolve()` would
    answer about a file rather than about the claim. `..` is refused wherever
    it appears rather than only at the front, because `docs/../../x` escapes
    just as surely and reads as though it does not.
    """
    if not relative or PurePosixPath(relative).is_absolute():
        return False
    spelled = relative.replace("\\", "/")
    # A drive letter or a UNC root is absolute on Windows and not on POSIX, so
    # `PurePosixPath` alone would let `C:/Windows/win.ini` through on both.
    if ":" in spelled.split("/", 1)[0] or spelled.startswith("//"):
        return False
    return ".." not in PurePosixPath(spelled).parts


def _note_the_missing_path(diag: Callable[[str], None]) -> None:
    """Say which rules cannot answer, when no `--as-path` was given.

    This is the one thing `--check-text` could get quietly wrong. A document
    with no path is not the same document read from disk: `manifest-floor-
    mismatch` keys on the FILENAME and goes silent, markdown links and anchors
    resolve against the repository root rather than the document's directory,
    and the markup language falls back to markdown because nothing says
    otherwise - which would run the two markdown-only rules over
    reStructuredText, where `[text](url)` occurs in ordinary code.

    None of that is wrong. All of it is a narrower question than `--validate`
    asks, and a narrower question that does not announce itself is the silent
    scope reduction this whole tool exists to refuse. So it is stated, once,
    beside the denominators that would otherwise look like a clean pass.
    """
    diag("  NOTE: no --as-path, so this document has no location. Rules that "
         "key on the filename see nothing, relative links resolve against the "
         "repository root rather than the document's directory, and the markup "
         "is assumed to be markdown.")


def run_check_text(repo: Path, args: argparse.Namespace,
                   status: StatusConfig) -> int:
    """`--check-text`: check a document arriving on stdin, and gate.

    The same rules, the same denominators, the same formats and the same
    baseline as `--validate` - over text that need not be on disk. That is the
    whole of it, and the smallness is the point: it is the primitive under any
    caller holding a draft, and it carries no assumption of its own.

    Three things `--validate` does are deliberately absent, each because it
    needs a file:

    * no archive and no `extra_docs` pass. One document arrived; inventing two
      more to read from disk beside it would answer a question nobody asked.
    * no `--sha-map` rewriting. That mode writes the translated document back,
      and there is nothing here to write back to. The translation is still
      APPLIED to the text in memory, so the findings match what the repaired
      document would produce.
    * `--suggest-fixes` needs `--as-path`, because a patch names the file it
      applies to. Without one it says so rather than emitting a diff against
      a filename it made up.
    """
    stream = _diagnostic_stream(args)

    def diag(*parts: object) -> None:
        print(*parts, file=stream)

    text = _read_stdin(diag)
    if text is None:
        return 1

    relative = args.as_path or None
    if relative is not None and not _inside_repo(relative):
        # An asserted path is a claim about where this document would live, and
        # one that leaves the repository is a claim the rest of the run cannot
        # honour: relative links would resolve against a directory git knows
        # nothing about, and every finding would be labelled with a location
        # that means nothing to any reader or machine consumer. Measured
        # accepting `../../../etc/passwd` and `C:/Windows/win.ini` and printing
        # `checked ../../../etc/passwd` over findings from piped text.
        print(f"--as-path must be a path inside the repository, written "
              f"relative to its root. Got {args.as_path!r}.", file=sys.stderr)
        return 2
    name = relative or STDIN_NAME
    # Set in BOTH directions, never left as whatever ran last. `set_document`
    # replaces only the fields it is given, so a mode that assigns them on one
    # branch and not the other inherits the previous document's location - the
    # exact bug `--sweep` had, one level up.
    #
    # With a path, this is what `--validate` sets, taken from the path the
    # caller asserts rather than from one on disk: the directory relative links
    # resolve against, the filename the keyed rules read, and the markup
    # language. Without one, all three are explicitly absent.
    session.set_document(
        link_base=(repo / relative).parent if relative else None,
        doc_path=relative,
        doc_format=format_for(relative) if relative else "markdown")
    mapping, readable = _sha_map(args)
    if not readable:
        return 2
    if mapping is not None:
        text, changed = translate_shas(text, mapping)
        if changed:
            diag(f"translated {changed} stale SHA reference(s) in {name} "
                 f"(in memory; --check-text writes no file)")

    baselined, baseline_path = _open_baseline(repo, args)
    if baselined is None:
        return 2
    found = Collector(baselined,
                      echo=(lambda line: print(line, file=stream))
                      if args.format == "text" else None)

    # One scope across both halves, for the reason `run_validate` gives: the
    # findings and the denominator are two views of one examination and must
    # not re-ask git the same questions.
    with session.run_scope():
        # The same call `--validate` makes, entry-scoped rules included. Tying
        # them to `--as-path` was written first and is wrong: whether a
        # document carries dated entries is a property of the TEXT, and a
        # status document piped in without a path still has them. If it has
        # none, those rules report 0 examined and the denominator says so,
        # which is the honest answer rather than a silently narrower run.
        findings = session.validate(repo, text)
        exit_code = 1 if found.record(name, findings, primary=True) else 0
        examined = session.count_examined(repo, text)
        index_incomplete = session.ancestry_incomplete()
    errors_reported = report_denominators(diag, repo, name, examined,
                                          index_incomplete)
    if not relative:
        _note_the_missing_path(diag)
    session.set_document(link_base=None)

    if args.suggest_fixes:
        if not relative:
            diag("no rename suggestions: --suggest-fixes needs --as-path, "
                 "because a patch has to name the file it applies to")
        else:
            patch = suggest_renames(repo, (repo / relative).parent, text,
                                    relative, findings)
            if patch:
                # BYTES, for the reason `run_validate` gives: print() rewrites
                # newlines on Windows and git apply rejects the mixed endings.
                sys.stdout.buffer.write(patch.encode("utf-8"))
                sys.stdout.buffer.flush()
            else:
                diag("no rename suggestions: nothing references a file git "
                     "recorded as moved")

    return _finish(diag, repo, args, found, baseline_path, examined,
                   exit_code, errors_reported)
