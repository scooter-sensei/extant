"""The two survey modes: `--sweep` and `--deleted-since`.

Both answer a question about MANY documents rather than one, and both report
without gating. `--sweep` is the first-run command: it needs no configuration,
writes nothing, and says what is rotting in a repository nobody here has seen
before. `--deleted-since` asks the opposite question - which claims were true
enough to be written down, are false today, and are no longer written anywhere.

They share this module because they share the machinery that makes a survey
honest rather than reassuring: the exclusion patterns and their per-pattern
counts, the vetted/unvetted split, and the per-document denominators. Every one
of those exists because a survey that examined nothing prints exactly what a
clean survey prints.

The ambient state both modes set around each document - which file is being
read, and in which markup language - lives in extant/session.py. This module
saves it and puts it back, on the failing path too; see `run_sweep` for the bug
that taught it to.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from extant import refs, session
# ALIASED, because `text` is what every function here calls the document
# it is reading. Imported under its own name the module was shadowed by
# the first local assignment in `run_sweep`, and the failure was an
# AttributeError on a str several lines later rather than anything
# naming the import.
from extant import text as markup
from extant.finding import Located
from extant.registry import RULE_ERRORS
from extant.report import format_text, render_findings

__all__ = [
    "deleted_claims", "excluded_documents", "partition_documents",
    "run_deleted_since", "run_sweep",
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
        print("swept 0 markdown files: git tracks none in this repository",
              file=sys.stderr)
        return 0

    tracked_total = len(paths)
    excluded_counts: dict[str, int] = {}
    if session.CONFIG.exclude_paths:
        present = {p.replace("\\", "/") for p in paths}
        paths, excluded_counts = excluded_documents(
            paths, session.CONFIG.exclude_paths)
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
        configured = {session.CONFIG.primary_doc.replace("\\", "/"),
                      *(d.replace("\\", "/")
                        for d in session.CONFIG.extra_docs)}
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
    primary = session.CONFIG.primary_doc.replace("\\", "/")
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
    previous_document = session.document()
    with session.run_scope():
        try:
            # Seeded here, inside the stable scope, for two reasons at once: it
            # fixes the printing ORDER to the one `--verify` uses, so the two modes
            # can be read side by side, and its repository-scoped entries are the
            # counts those rules get - they are the repository's candidates, not
            # any document's, so they are read once rather than per file.
            repository_examined = session.count_examined(repo, "")
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
                    session.set_document(link_base=path.parent,
                                         doc_format=markup.format_for(relative))
                    findings = session.validate(repo, text,
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
                    counted = session.count_examined(repo, text)
                    for rule in session.RULES:
                        if rule.scope == "repository":
                            continue        # counted once, below
                        if session.rule_applies(rule, False, relative == primary):
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
                    produced = rule.check(session.context(repo), "")  # type: ignore[operator]
                except Exception as exc:                   # noqa: BLE001
                    RULE_ERRORS.append(
                        (rule.kind, f"{exc.__class__.__name__}: {exc}"))
                    produced = []
                results["repository"].extend(
                    Located(rule.subject_file or ".", finding, primary=False,
                            gating=False)
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
    return 1 if (results["vetted"] or RULE_ERRORS) else 0


def _document_at(repo: Path, ref: str, relative: str) -> str | None:
    """A document as it stood at `ref`, or None if it was not there.

    A previous version that is not valid UTF-8 raises rather than returning
    None, because "absent" and "unreadable" are different facts and the caller
    counts them separately. Decoding it with errors="replace" would be worse
    than either: every rule would then run against silently corrupted text and
    report findings about bytes that are not there.
    """
    # BYTES, then decoded here. `_git` in extant/git.py passes text=True,
    # which makes subprocess decode inside a reader THREAD - so invalid UTF-8
    # raises where no caller can catch it. The observed result was the worst
    # of both: a UnicodeDecodeError traceback printed from the thread, the process
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
        ctx = session.context(repo)
        out = ctx.git.run(ctx.repo, "diff", "--name-only", ref, "HEAD")
    except (subprocess.CalledProcessError, OSError):
        return []
    changed = {line.strip().replace("\\", "/") for line in out.splitlines()
               if line.strip()}
    return [c for c in candidates if c.replace("\\", "/") in changed]


def _configured_documents() -> list[str]:
    """Primary, archive and extras, in that order, skipping any left unset."""
    return [d for d in (session.CONFIG.primary_doc, session.CONFIG.archive_doc,
                        *session.CONFIG.extra_docs) if d]


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
                parts.append(markup.prose(session.document(), handle.read()))
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
        previous_format = session.document().doc_format
        session.set_document(doc_format=markup.format_for(relative))
        try:
            was = session.validate(
                repo, previous, base=(repo / relative).parent,
                has_entries=(relative == session.CONFIG.primary_doc))
        finally:
            session.set_document(doc_format=previous_format)
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
    # Beside the denominator, for the reason `report_rule_errors` (session.py)
    # gives: a rule that crashed reports no findings, which is what a clean
    # run looks like here too, since this mode has no findings at all when it
    # is healthy. `deleted_claims` calls `session.validate()` once per changed
    # document and every raise it catches lands in RULE_ERRORS - Task 9's
    # isolation runs here exactly as it does for `--validate` and `--sweep` -
    # but nothing downstream of it ever named the rule until now. Reporting
    # does NOT gate this mode; see the docstring above for why intent is not
    # this tool's to judge. A rule that failed to look is still worth saying
    # out loud even when nothing here would have failed the build anyway.
    session.report_rule_errors(lambda line: print(line, file=out))
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
    vetted_names = {session.CONFIG.primary_doc, session.CONFIG.archive_doc,
                    *session.CONFIG.extra_docs}
    normalised = {name.replace("\\", "/").lstrip("./") for name in vetted_names if name}
    vetted = [p for p in paths if p in normalised]
    return vetted, [p for p in paths if p not in normalised]
