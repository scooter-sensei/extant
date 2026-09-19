"""`--introduced-since REF`: gate on the claims a change wrote, and no others.

The measured problem this answers is document SELECTION, not the rules. On
the benchmark a default install gates 7 of 5,691 ordinary findings, and every
policy that widens the document set buys reach by pinning paths that later
move - the table in CORPUS.md has that as its `paths pinned` column, the
standing liability each policy accepts. This mode pins nothing: it sweeps the
documents a range changed, keeps the findings that sit on lines the range
WROTE, and fails the run on those. No configured document, no baseline, no
path to keep in step - the diff is the ratchet.

The range is `merge-base(REF, HEAD)` to the WORKING TREE. The working tree,
because that is what the sweep reads: diffed against HEAD instead, a line
added above a committed claim would shift every number the diff reports away
from the ones the findings carry. The merge base, because on a branch that
has diverged from REF a plain `diff REF` shows every line REF has since
deleted as a `+` line - lines this branch never wrote - and on a
pull-request checkout, where HEAD already contains the base, the two are the
same commit.

Three things it deliberately does not do, each said in its output rather
than left to be inferred from a count:

* It gates on claims a change WROTE, never on claims a change BROKE without
  writing them - a heading removed under another document's anchor, a pure
  rename that leaves a moved file's relative links pointing nowhere. Those
  have no `+` line. `--verify` and `--sweep` own them.
* It does not run the repository-scoped rules. Their findings sit at line 1
  of `.gitattributes` or `.extant.toml`, a synthetic line nothing wrote, so
  there is no introduced line to place them on.
* It reads only the documents the range changed, and prints how many tracked
  documents it therefore did not read. extant/sweep.py's docstring forbids a
  SURVEY from re-checking only what changed, because a claim dies when the
  repository changes and not the document; that promise is about describing
  the repository, and this mode's question lives in changed documents by
  construction - an introduced line cannot be anywhere else.

Two shapes of document are named and counted rather than mapped. A document
holding a bare `\\r` is one this tool numbers differently from git - it counts
every spelling of a line break, git counts `\\n` - so its findings are surveyed
and do not gate; measured at 1 of 78,878 corpus documents, and that one a
raster fixture. A document git reads as binary (a NUL byte) prints no hunks
and is not examined at all.

Beside extant/deleted_since.py, and the same shape as that mode - a survey
over `sweep.survey` with its own denominator - with the opposite exit-code
contract: this one gates, so a range it cannot compute is a refusal with
exit 2 rather than an honest zero, because a gate that examined nothing and
passed is the failure this project exists to refuse.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from extant import refs, session, strata
from extant.config import normalise_document
from extant.finding import Located
from extant.gate import report_repository_notes
from extant.git import environment
from extant.registry import RULE_ERRORS
from extant.report import render_findings
from extant.sweep import apply_exclusions, survey

__all__ = ["introduced_lines", "merge_base", "run_introduced_since",
           "unquote_path"]

# `@@ -a,b +c,d @@`: the `+` side is the NEW file, whose numbering is the one
# every finding carries. `d` omitted means one line; `d` of zero is a pure
# deletion and introduces nothing.
_HUNK = re.compile(rb"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# What `git diff` is asked for. Every one of these pins a shape that a
# repository's own configuration could otherwise change under the parser:
# `diff.noprefix` and `diff.mnemonicPrefix` rewrite the `a/` and `b/`
# prefixes, `diff.external` replaces the output wholesale, `diff.context`
# and `diff.interHunkContext` widen the hunks, and a textconv driver would
# hand back something other than the file. `--find-renames` so an edited
# document that also moved is read under the name HEAD's tree holds.
_DIFF = ("diff", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
         "--find-renames", "--inter-hunk-context=0", "--src-prefix=a/",
         "--dst-prefix=b/")

# A carriage return not followed by a line feed: a line break to this tool
# and not to git.
_BARE_CR = re.compile(rb"\r(?!\n)")

# The C escapes git's quote_c_style emits, besides three-digit octal.
_C_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11,
              "\\": 92, '"': 34}
# Exactly three ASCII octal digits, which is the only numeric escape git
# writes; `str.isdigit` would also admit the digits of other scripts.
_OCTAL = re.compile(r"[0-7]{3}")


def unquote_path(raw: str) -> str:
    """A path as git printed it, with git's C-style quoting undone.

    git wraps a path in double quotes when it holds a quote, a backslash or
    a control character, and writes those as C escapes; with `core.quotePath`
    off - which `environment()` in extant/git.py arranges for every process
    - a non-ASCII byte is written raw and never reaches here escaped. An
    unquoted path is returned as it is.
    """
    if len(raw) < 2 or not (raw.startswith('"') and raw.endswith('"')):
        return raw
    body = raw[1:-1]
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out += char.encode("utf-8")
            index += 1
            continue
        index += 1
        escaped = body[index] if index < len(body) else ""
        octal = _OCTAL.match(body, index)
        if escaped in _C_ESCAPES:
            out.append(_C_ESCAPES[escaped])
            index += 1
        elif octal:
            out.append(int(octal.group(), 8) & 0xFF)
            index += 3
        else:
            out += escaped.encode("utf-8")
            index += 1
    return out.decode("utf-8", "replace")


def _new_side(header: bytes, prefix: bytes) -> str | None:
    """The `b/` path a `+++` or `Binary files` line names, or None for
    `/dev/null` - a document the range deleted, which introduced nothing."""
    raw = header[len(prefix):].decode("utf-8", "replace")
    if raw == "/dev/null":
        return None
    path = unquote_path(raw)
    return path[2:] if path.startswith("b/") else path


def merge_base(repo: Path, ref: str) -> str | None:
    """Where the histories of `ref` and HEAD fork, or None when git cannot
    say: a ref that does not resolve, an unborn HEAD, unrelated histories,
    or a depth-limited checkout whose base lies beyond the depth. Through
    the seam, so a spawn budget can see it."""
    try:
        ctx = session.context(repo)
        out = ctx.git.run(ctx.repo, "merge-base", ref, "HEAD")
    except (subprocess.CalledProcessError, OSError):
        return None
    return out.strip() or None


def introduced_lines(repo: Path, base: str) -> tuple[dict[str, set[int]], list[str]]:
    """The lines of every tracked document that the working tree holds and
    `base` does not, keyed by the path HEAD's tree holds; and the changed
    documents git read as binary, which have no lines to report.

    BYTES, split on `\\n` alone, and not read through the seam. `_git` in
    extant/git.py translates every `\\r` in a result to `\\n` - right for the
    metadata it returns, and wrong for a patch, where a document line holding
    a bare `\\r` would be cut in two with the second half arriving bare, no
    `+` in front of it, and a fragment beginning `@@ -` would then parse as a
    hunk header. git's own line discipline is the one the hunk numbers are
    written in, so it is the one this reads.

    A `+++` or `Binary files` line is honoured only OUTSIDE a hunk. Inside
    one, every document line carries a `+` or `-` prefix, so a document that
    quotes a patch appears as `++++ b/x` and never matches - but a document
    line reading `++ b/x` would arrive as `+++ b/x`, which is why the state
    matters rather than the prefix alone.

    Restricted by pathspec to the suffixes `tracked_markdown` reads, so a
    change touching two hundred source files and one document costs one
    small patch rather than a large one.
    """
    done = subprocess.run(
        ["git", *_DIFF, base, "--",
         *(f"*.{suffix}" for suffix in refs.DOCUMENT_SUFFIXES)],
        cwd=repo, capture_output=True, env=environment())
    if done.returncode != 0:
        raise subprocess.CalledProcessError(done.returncode, done.args,
                                            done.stdout, done.stderr)
    lines: dict[str, set[int]] = {}
    binary: list[str] = []
    current: str | None = None
    in_hunk = False
    for raw in done.stdout.split(b"\n"):
        if raw.startswith(b"diff --git "):
            current, in_hunk = None, False
            continue
        match = _HUNK.match(raw)
        if match:
            # A second hunk of the same file arrives in hunk state; every
            # content line between them carries a prefix, so a bare `@@` is
            # always a header.
            if current is not None:
                in_hunk = True
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) is not None else 1
                lines[current].update(range(start, start + count))
            continue
        if in_hunk:
            continue
        if raw.startswith(b"+++ "):
            current = _new_side(raw, b"+++ ")
            if current is not None:
                lines.setdefault(current, set())
        elif raw.startswith(b"Binary files ") and raw.endswith(b" differ"):
            named = _new_side(raw[:-len(b" differ")].rsplit(b" and ", 1)[-1], b"")
            if named is not None:
                binary.append(named)
    return lines, binary


def _holds_bare_cr(path: Path) -> bool:
    try:
        return _BARE_CR.search(path.read_bytes()) is not None
    except OSError:
        return False


def run_introduced_since(repo: Path, ref: str, fmt: str) -> int:
    """Gate on the findings that sit on lines the range wrote. Returns the
    exit code: 1 on a gating finding, a raised rule or a lost document; 2
    when there is no range to gate on; 0 otherwise.

    The refusal is structural - nothing on stdout, the reason on stderr -
    because a SARIF document emitted for a range that was never computed
    would assert a clean scan that never happened.
    """
    out = sys.stderr if fmt == "sarif" else sys.stdout
    base = merge_base(repo, ref)
    if base is None:
        print(f"--introduced-since {ref}: git finds no merge base between "
              f"that ref and HEAD, so there is no range to gate on. The ref "
              f"must resolve here, and on a depth-limited checkout the base "
              f"may lie beyond the depth; see the CI section of the README.",
              file=sys.stderr)
        return 2
    try:
        lines, binary = introduced_lines(repo, base)
    except (subprocess.CalledProcessError, OSError) as exc:
        # REPORTS WHAT IT CAUGHT, the one shape a wide-ish handler is allowed
        # here. A partial repository whose base tree the transport left out
        # lands here, and the message names the cause rather than the run
        # printing what a clean one prints.
        print(f"--introduced-since {ref}: git diff against {base[:7]} failed "
              f"({exc.__class__.__name__}), so there is no range to gate on.",
              file=sys.stderr)
        return 2
    try:
        tracked = refs.tracked_markdown(session.context(repo))
    except (subprocess.CalledProcessError, OSError) as exc:
        # `tracked_markdown` raises deliberately, and the reason it gives -
        # returning [] on error is how a silent all-clear is produced - is
        # the reason this refuses rather than surveying nothing.
        print(f"--introduced-since {ref}: git cannot list HEAD's tree "
              f"({exc.__class__.__name__}), so the changed documents cannot "
              f"be named.", file=sys.stderr)
        return 2

    read_as_binary = set(binary)
    changed = [p for p in tracked if lines.get(p.replace("\\", "/"))]
    binary_documents = [p for p in tracked
                        if p.replace("\\", "/") in read_as_binary]
    # Over the CHANGED documents, not every tracked one, so the counts describe
    # this range - and so the conflict check fires only when a configured
    # document an exclusion removes is in the range. The sentence it prints is
    # "excluding it would silently stop gating on a document you asked to gate
    # on", and outside the range nothing would have gated on it either way.
    kept, excluded_counts, conflicting = apply_exclusions(changed)
    if conflicting:
        return 1
    primary = normalise_document(session.CONFIG.primary_doc)
    # Numbered differently from git, so their findings cannot be placed on
    # git's lines. Surveyed and counted; never gated, never dropped.
    unmapped = [p for p in kept if _holds_bare_cr(repo / p)]
    tasks = [(relative, relative == primary) for relative in kept]

    gating: list[Located] = []
    aside = surveyed = 0
    unreadable: list[str] = []
    unreturned: list[str] = []
    # Registry order, non-repository rules only: the per-document counts
    # `survey` returns already exclude the repository rules, and seeding the
    # keys here is what makes a rule that examined nothing print its zero.
    examined: dict[str, int] = {rule.kind: 0 for rule in session.RULES
                                if rule.scope != "repository"}
    # One run scope for the whole gate, and the document put back on the
    # failing path too - the reason is written out in `run_sweep`.
    previous_document = session.document()
    with session.run_scope():
        try:
            gathered, workers, fallback = survey(repo, tasks)
            for relative, _is_primary in tasks:
                outcome = gathered.get(relative)
                if outcome is None:
                    unreturned.append(relative)
                    continue
                findings, unread, doc_examined, errors = outcome
                if workers and errors:
                    RULE_ERRORS.extend(errors)
                if unread is not None:
                    unreadable.append(unread)
                    continue
                for kind, count in doc_examined.items():
                    examined[kind] += count
                wrote = lines.get(relative.replace("\\", "/"), set())
                for finding in findings:
                    if relative in unmapped:
                        surveyed += 1
                    elif finding.line in wrote:
                        # `primary=False` for every document: nothing here
                        # was asked for by name, so every finding carries
                        # its path, which is what a reader of a gate over a
                        # change needs first.
                        gating.append(Located(relative, finding, primary=False,
                                              gating=True,
                                              stratum=strata.classify(relative)))
                    else:
                        aside += 1
        finally:
            session.install_document(previous_document)

    if fmt == "text":
        for line in render_findings(gating, fmt)[0]:
            print(line, file=out)
    else:
        # ALWAYS, with zero results too: a range that wrote no document is a
        # result, and a machine consumer handed zero bytes fails its upload
        # rather than reading "no results".
        for line in render_findings(gating, fmt, repo, examined=examined,
                                    run_kind="introduced-since")[0]:
            print(line)

    introduced = sum(len(lines.get(p.replace("\\", "/"), ())) for p in kept)
    # The denominator, in three parts: what was read, what was not, and what
    # each rule saw in what was read. "0 findings" and "0 documents changed"
    # print identically without the first two.
    print(f"\nexamined {len(kept)} changed document(s) since {ref} (merge "
          f"base {base[:7]}): {introduced} introduced line(s), "
          f"{len(gating)} finding(s) on them", file=out)
    print(f"  {len(tracked) - len(changed) - len(binary_documents)} tracked "
          f"document(s) the range did not change were not read", file=out)
    print("  examined: " + ", ".join(f"{kind} {n}"
                                     for kind, n in examined.items()), file=out)
    session.report_rule_errors(lambda line: print(line, file=out))
    blind = [kind for kind, n in examined.items() if n == 0]
    if blind:
        print("  NOTE: these rules examined nothing in the changed documents "
              "- either they make no such claims, or the pattern does not "
              "match how this project writes them: " + ", ".join(blind),
              file=out)
    repository_rules = [rule.kind for rule in session.RULES
                        if rule.scope == "repository"]
    print(f"  {len(repository_rules)} repository-wide rule(s) not run: their "
          f"findings sit at a line nothing wrote, so --verify and --sweep "
          f"run them ({', '.join(repository_rules)})", file=out)
    if aside:
        print(f"  {aside} finding(s) in the changed document(s) sit on lines "
              f"the range did not touch and do not gate; --sweep shows them",
              file=out)
    if excluded_counts:
        # The per-pattern counts, as the sweep prints them - but not its
        # "matched nothing, so it may be stale" line. A pattern idle across
        # every tracked document is dead configuration; one idle across the
        # documents a range changed is merely not in this range, and the
        # sweep is where that question is answered.
        removed = sum(excluded_counts.values())
        print(f"  excluded {removed} of {len(changed)} changed document(s) via "
              f"{len(excluded_counts)} exclude_paths pattern(s)", file=out)
        for pattern, count in sorted(excluded_counts.items()):
            print(f"    {count:5} {pattern}", file=out)
    if unmapped:
        print(f"  {len(unmapped)} changed document(s) hold a bare carriage "
              f"return, which this tool counts as a line break and git does "
              f"not; {surveyed} finding(s) there were surveyed and do not "
              f"gate: {', '.join(unmapped)}", file=out)
    if binary_documents:
        print(f"  {len(binary_documents)} changed document(s) git reads as "
              f"binary and were not examined: {', '.join(binary_documents)}",
              file=out)
    report_repository_notes(lambda line: print(line, file=out), repo)
    if workers:
        print(f"  surveyed across {workers} worker process(es)", file=out)
    if fallback is not None:
        print(f"  NOTE: the parallel survey could not start, so every "
              f"document was read in this process instead: {fallback}",
              file=out)
    if unreturned:
        print(f"  {len(unreturned)} document(s) were dispatched and returned "
              f"no result, so they were NOT examined: "
              f"{', '.join(sorted(unreturned))}", file=out)
    if unreadable:
        print(f"  {len(unreadable)} could not be read: {', '.join(unreadable)}",
              file=out)
    # The exit code: a gating finding, a rule that raised, or a document the
    # survey lost. `unreadable` does not gate, for the reason `run_sweep`
    # gives - it is a fact about the repository, reported and survived.
    return 1 if (gating or RULE_ERRORS or unreturned) else 0
