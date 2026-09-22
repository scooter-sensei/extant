"""`--deleted-since`: claims removed while still false, reported and never gated.

The second survey-shaped mode, and with `--sweep` one of the two that never
gate; `--introduced-since`, the third, does. It takes each configured
document as it stood at a
ref, validates that old text against TODAY's git, and reports every finding
whose subject is no longer written anywhere - so there is no separate "is it
still false" step, and a claim whose fact was repaired produces nothing to
begin with. Whether a removal was evasion or repair is a question about
intent, which git cannot settle, so the mode states the fact and exits 0.

Left extant/sweep.py on 2026-09-14, when the missing-object distinction below
took that module to 962 lines against a 927-line ceiling. The cut is the one
the old module docstring already drew - "the two survey modes" - and the
block moved byte for byte, with the mutation anchors following by path. What
the two modes share stays in sweep.py: the vetted/unvetted split, the
exclusion patterns and their counts, and the per-document denominators.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from extant import session, strata
from extant import text as markup
from extant.config import normalise_document
from extant.finding import Located
from extant.git import environment, is_partial
from extant.report import render_findings

__all__ = ["deleted_claims", "run_deleted_since"]

# The one normaliser, as sweep.py has it: the names on `session.CONFIG` are
# already normalised where the settings are read, so this is idempotent and
# kept so a reader comparing a configured name against a tracked path sees
# the question being asked.
_normalise = normalise_document


class MissingObject(Exception):
    """A previous version the repository names but does not hold.

    Raised by `_document_at` in a PARTIAL repository when the batch answers
    `missing` for a path the tree at `ref` lists: the blob is one the
    transport left out, and `environment()` refuses to go back for it. Not
    an absence - the document was there - and not a decode failure either,
    but it lands in the same "could not be read" count, because that is the
    fact: this mode could not read that version, and saying nothing would
    hide exactly the deleted claim the mode exists to report. Found by the
    audit of the guard, on the fixture in tests/test_partial_repository.py:
    examined 0, unreadable 0, silence.
    """


def _documents_at(repo: Path, ref: str,
                  relatives: list[str]) -> dict[str, bytes | None]:
    """Every listed document as it stood at `ref`, as BYTES, from ONE process.

    One `cat-file --batch` fed `<ref>:<path>` per line, in place of one
    `git show` per document - the review's 4.10, and its decider was the
    spawn count: measured on this repository, `--deleted-since v0.26.1`
    started ten git processes for four changed documents, four of them
    these reads. The batch answers in input order, one record per line -
    `<oid> <type> <size>` then the body, or `<spec> missing` - so the
    records are paired with the names by position and never by parsing the
    echoed name back out of the header, which could hold a space.

    None for a name git gave no blob for. That is three facts under one
    spelling and `_document_at` tells them apart: the path was not there,
    the object is one this partial copy does not hold (git prints `missing`
    for both, and only `ls-tree` can say which), or the name is a TREE at
    `ref` - a directory where the document now is - which `git show` used to
    print as a listing and this mode then validated as a document.

    Names are fed on lines, so a configured document name holding a newline
    cannot be asked here where the one-per-process form could ask it; the
    `-z` batch input that would allow it arrived in git 2.40 and the floor
    is 2.31. Nobody's configuration names such a file, and it is said here
    so that the day one does, the missing answer has an explanation.

    BYTES, decoded by the caller per document. `text=True` makes subprocess
    decode inside a reader THREAD on Windows - so invalid UTF-8 raises where
    no caller can catch it. The observed result was the worst of both: a
    UnicodeDecodeError traceback printed from the thread, the process
    continuing, and the document silently counted as examining nothing.
    `_git` in extant/git.py captures bytes for the same reason, and decodes
    with replacement because it returns git's METADATA; this returns the
    DOCUMENT, where a replaced character would have every rule checking
    text the file does not contain.
    """
    if not relatives:
        return {}
    payload = "".join(f"{ref}:{relative}\n" for relative in relatives)
    try:
        done = subprocess.run(["git", "cat-file", "--batch"], cwd=repo,
                              input=payload.encode("utf-8"),
                              capture_output=True, env=environment())
    except OSError:
        return {relative: None for relative in relatives}
    if done.returncode != 0:
        return {relative: None for relative in relatives}
    found: dict[str, bytes | None] = {}
    out = done.stdout
    at = 0
    for relative in relatives:
        end = out.find(b"\n", at)
        if end < 0:
            found[relative] = None          # git stopped answering early
            continue
        # Read from the END of the header, where the type and the size are.
        # A `missing` line echoes the name, and a name may hold a space -
        # `HEAD~1:docs/my doc.md missing` - so counting fields from the
        # front read that as a blob record whose size was the word
        # `missing`. Found by the audit that closed the tranche.
        header = out[at:end].rsplit(b" ", 2)
        at = end + 1
        if len(header) != 3 or not header[2].isdigit():
            found[relative] = None          # `<spec> missing`, or ambiguous
            continue
        size = int(header[2])
        body = out[at:at + size]
        at += size + 1                      # the record's trailing newline
        found[relative] = body if header[1] == b"blob" else None
    return found


def _document_at(repo: Path, ref: str, relative: str,
                 blob: bytes | None) -> str | None:
    """A document as it stood at `ref`, from the batch's bytes for it, or
    None if it was not there.

    A previous version that is not valid UTF-8 raises rather than returning
    None, because "absent" and "unreadable" are different facts and the caller
    counts them separately. Decoding it with errors="replace" would be worse
    than either: every rule would then run against silently corrupted text and
    report findings about bytes that are not there.

    A version whose OBJECT is not here raises `MissingObject` for the same
    reason, and only a partial repository can produce one: anywhere else a
    `missing` answer is an absent path or a bad ref, and stays None. The
    second question - did the tree at `ref` list this path at all - is
    `ls-tree`, which needs the tree and not the blob, so a `blob:none` copy
    answers it without the transport. A copy that cannot answer it either,
    because its trees are missing too, is reported as unreadable rather
    than absent: "could not be read" is true of it, "was not there" is not
    known to be.

    Decoding strictly, and letting the error reach the caller, is what makes
    "unreadable" a fact this mode can report instead of a mess it prints.
    """
    if blob is None:
        if is_partial(repo) and _listed_at(repo, ref, relative) is not False:
            raise MissingObject(f"{ref}:{relative}")
        return None
    return blob.decode("utf-8")


def _listed_at(repo: Path, ref: str, relative: str) -> bool | None:
    """Whether the tree at `ref` lists `relative`: True, False, or None when
    the tree itself cannot be read - a treeless copy, or a ref that is not
    there. `ls-tree` exits 0 and prints nothing for a path that is not in
    the tree, so an empty answer is a definite one. Through the seam, as
    `_changed_between` is: `run` raises on the failure and returns the
    listing otherwise, which is the whole distinction this needs."""
    try:
        ctx = session.context(repo)
        out = ctx.git.run(ctx.repo, "ls-tree", ref, "--", relative)
    except (subprocess.CalledProcessError, OSError):
        return None
    return bool(out.strip())


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
    return [_normalise(d) for d in (session.CONFIG.primary_doc,
                                    session.CONFIG.archive_doc,
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
    changed = _changed_between(repo, ref, documents)
    previous_versions = _documents_at(repo, ref, changed)
    # ONE scope across every old document. Each is validated against the
    # same checkout and nothing here writes to it, which is the promise
    # `run_scope()` asks for - and this loop never made it, so `validate()`
    # opened a fresh scope per document and re-asked what the last one had
    # learned: on this repository's four changed documents the ref table and
    # the trunk index were each built twice. The same deleted
    # `with session.run_scope():` that tests/test_spawn_budget.py pins for
    # `--verify`, pinned here by tests/test_deleted_since.py.
    with session.run_scope():
        for relative in changed:
            try:
                previous = _document_at(repo, ref, relative,
                                        previous_versions.get(relative))
            except (UnicodeDecodeError, MissingObject):
                # A previous version that cannot be decoded, or that a partial
                # repository does not hold, is not a version with no claims.
                # Counted and reported, never passed over in silence.
                undecodable += 1
                continue
            if previous is None:
                continue
            examined += 1
            # `base` is a parameter; the FORMAT is not, so it is the one piece
            # of document state this has to set - and it is restored in
            # `finally`, because a rule raising part-way would otherwise leave
            # the process reading every later document in the wrong markup
            # language.
            previous_format = session.document().doc_format
            session.set_document(doc_format=markup.format_for(relative))
            try:
                was = session.validate(
                    repo, previous, base=(repo / relative).parent,
                    has_entries=(relative == _normalise(session.CONFIG.primary_doc)))
            finally:
                session.set_document(doc_format=previous_format)
            for finding in was:
                if finding.subject is None:
                    skipped += 1
                    continue
                if finding.subject in haystack:
                    continue                # still written down somewhere
                # `gating=False`: the docstring below says this mode never
                # gates and returns 0. Every other format honoured that and
                # the machine ones did not, publishing a report as an error.
                found.append(Located(relative, finding, primary=False,
                                     gating=False,
                                     stratum=strata.classify(relative)))
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
        print(f"  {undecodable} previous version(s) could not be read - not "
              f"valid UTF-8, or an object this partial repository does not "
              f"hold - and were not examined", file=out)
    if gone:
        print("  a swapped or corrected reference looks the same as a hidden "
              "one from git's side. This reports; it does not judge, which is "
              "why it never fails a run.", file=out)
    return 0
