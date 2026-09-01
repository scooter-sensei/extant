"""Metamorphic oracles: extant compared against ITSELF under a change that
must not matter.

WHY THESE EXIST

A fuzzer has no oracle. It cannot know what a generated repository ought to
report, so the properties it checks have to hold whatever the right answer
turns out to be. `fuzz.py` already had six of those, and two of them - two runs
agreeing, and SARIF agreeing with text - were metamorphic in exactly this
sense. This module is the rest of that idea taken seriously.

The technique is the one behind equivalence modulo inputs: mutate the parts of
an input that provably cannot affect the answer, and require the answer not to
change. Compilers use dead code for the mutable region. Extant has a cleaner
analogue, because `strip_code` blanks a fenced block WITH SPACES so that every
character offset survives - a contract this project's own notes record as
having broken once on CRLF and cost 1627 characters on one document.

So the mutable regions here are: the inside of a code fence, the end of the
document, the line terminator, the file's name, and the presence of unrelated
documents. None of them may move a finding.

WHAT A SKIPPED ORACLE MEANS

Every oracle returns the faults it found AND, when it did not run, why. A
repository whose document already contains an unclosed fence cannot be given
another one without changing what is code and what is prose, so `FENCE` steps
aside there and SAYS SO. That is the same distinction `fuzz.py` draws for a
shape a platform will not build: not tested is not the same as passed, and an
oracle that quietly skipped would be the more comfortable of the two to write
and the one worth less.

WHAT THEY MUST NOT DO

Leave the repository changed. Each oracle restores what it touched in a
`finally`, because the next oracle and the reach ledger both read the same
repository afterwards, and a document left mutated would make every number
after it a measurement of this file rather than of extant.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

__all__ = [
    "DidNotRun", "ORACLES", "Result", "findings_in", "run_all",
    "oracle_baseline", "oracle_crlf", "oracle_denominator_agrees",
    "oracle_fence", "oracle_github", "oracle_mode_agrees",
    "oracle_monotone", "oracle_process", "oracle_relocate", "oracle_shift",
]

PRIMARY = "NEXT_SESSION.md"

# Rules that read the REPOSITORY and no document. They are attributed to
# whichever file the mode decided to hang them on - the sweep names the file
# that declares the fault, `--verify` names the primary document - so any
# oracle comparing two modes has to exclude them or it reports that
# disagreement as a defect on every repository that has one. Which is what the
# first version did, on all of them.
REPOSITORY_RULES = ("raw-lfs-blob", "inconsistent-artifact")


def _document_only(findings):
    return {f for f in findings if f[2] not in REPOSITORY_RULES}


def _own(findings):
    """Only what the document UNDER TEST reported about itself.

    A gating run also reads the archive and every `extra_docs` entry, and
    prints their findings with a path prefix. An oracle that mutates the
    primary document must not then require README.md's findings to have moved
    with it - which is what SHIFT demanded, and reported as a violation on
    every repository configured with a second document.
    """
    return _document_only({f for f in findings if f[0] == ""})


def _matches_head(repo: Path) -> bool:
    """Is the working tree the same as HEAD?

    `--sweep` reads HEAD's tree and the gating modes read the working tree, so
    the two answer about different inputs whenever those differ. Comparing
    them then reports a disagreement that is CORRECT - a repository with no
    commits has an empty tree and a full working directory, and both modes are
    right about what they were asked."""
    # Narrowed to the PRIMARY DOCUMENT rather than the whole tree. Every
    # generated repository carries untracked files - `tools/` is copied
    # into a clone AFTER cloning, and running extant leaves `__pycache__` -
    # so a whole-tree cleanliness test skipped on 6 of 6 repositories and
    # the oracle held nothing at all. What has to match is the file both
    # modes read.
    try:
        done = subprocess.run(
            ["git", "status", "--porcelain", "--", PRIMARY],
            cwd=str(repo), capture_output=True, text=True, timeout=60)
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", PRIMARY],
            cwd=str(repo), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    if done.returncode != 0 or tracked.returncode != 0:
        return False
    return not (done.stdout or "").strip()

# `line 12: [dead-sha] ...`, optionally prefixed by a path. The prefix is
# absent for the PRIMARY document and present for every other, an asymmetry
# `report.py` documents and its tests pin - so a pattern demanding the prefix
# silently sees none of the primary document's findings, which is how the
# existing FORMATS check once accused extant of losing a finding it had
# reported correctly.
FINDING = re.compile(
    r"^(?:(?P<path>[^\n]*?): )?line (?P<line>\d+): \[(?P<kind>[a-z-]+)\] "
    r"(?P<detail>[^\n]*)$", re.M)


class Result:
    """What one oracle concluded: faults, or why it did not run."""

    def __init__(self, faults=None, skipped: str | None = None) -> None:
        self.faults = list(faults or ())
        self.skipped = skipped


def findings_in(out: str):
    """Every finding in an output, as (path, line, kind, detail)."""
    return {(m.group("path") or "", int(m.group("line")),
             m.group("kind"), m.group("detail"))
            for m in FINDING.finditer(out)}


class DidNotRun(Exception):
    """A run this oracle needed never finished.

    `run_mode` returns None when extant exceeds the time budget, and every
    oracle here used to read that as EMPTY OUTPUT. Which compares equal to
    empty output, so a repository where every run timed out reported no
    findings before, no findings after, and a clean pass - measured: FENCE,
    CRLF, MONOTONE and RELOCATE all passed silently while nothing ran at all.

    Raised instead, and caught in `run_all` as a skip, so a hang is reported as
    an oracle that did not decide rather than one that agreed.
    """


def _text(done) -> str:
    if done is None:
        raise DidNotRun("a run did not finish inside the time budget")
    return (done.stdout or "") + (done.stderr or "")


def _stdout(done) -> str:
    """stdout ALONE, for the machine formats.

    SARIF is a document on stdout and diagnostics go to stderr, so the merged
    text never parses as JSON. The first version of DENOM-AGREE reported
    "SARIF did not parse" against perfectly good SARIF for exactly that
    reason - a fault in the oracle presented as a fault in the tool, which is
    the most expensive kind to leave lying around."""
    if done is None:
        raise DidNotRun("a run did not finish inside the time budget")
    return done.stdout or ""


def _validate(run, repo: Path, doc: str = PRIMARY, *extra):
    return run(repo, ["--validate", doc, *extra])


def _readable(repo: Path, name: str = PRIMARY):
    path = repo / name
    try:
        return path, path.read_bytes()
    except OSError:
        return path, None


def _describe(a, b) -> str:
    """The smallest true statement about how two finding sets differ."""
    only_a = sorted(a - b)[:2]
    only_b = sorted(b - a)[:2]
    parts = []
    if only_a:
        parts.append(f"lost {only_a}")
    if only_b:
        parts.append(f"gained {only_b}")
    return "; ".join(parts) or f"{len(a)} vs {len(b)}"


# --- the oracles ------------------------------------------------------

def oracle_fence(run, repo: Path) -> Result:
    """Junk inside a code fence changes nothing.

    `strip_code` blanks a fence with spaces, so what is inside it is not prose
    and cannot be a claim. Appending one at the END of the document also moves
    no line that came before it, so every finding must survive unchanged.

    SKIPPED ON AN UNCLOSED FENCE, and that guard is load-bearing rather than
    cautious. The generator's noise shapes include a fence that never closes;
    in such a document everything after it is already code, and appending
    ``` would CLOSE it and turn the following junk into prose - which can
    create a finding honestly. The oracle would then be reporting its own
    edit.
    """
    path, original = _readable(repo)
    if original is None:
        return Result(skipped="no primary document")
    text = original.decode("utf-8", "replace")
    if text.count("```") % 2:
        return Result(skipped="document has an unclosed fence")
    before = _own(findings_in(_text(_validate(run, repo))))
    try:
        path.write_bytes(original + b"\n```\njunk `src/gone.py` and "
                                    b"[x](nowhere.md)\n```\n")
        after = _own(findings_in(_text(_validate(run, repo))))
    finally:
        path.write_bytes(original)
    if before != after:
        return Result([("FENCE", f"fenced junk changed the findings: "
                                 f"{_describe(before, after)}")])
    return Result()


def oracle_shift(run, repo: Path) -> Result:
    """One line inserted at the top moves every finding down by exactly one.

    This is the line-number contract stated as a property. `line_breaks` and
    `line_number_at` count a break in every spelling precisely because a bare
    carriage return once made every claim report line 1, and nothing until now
    asked whether the numbers move together.
    """
    path, original = _readable(repo)
    if original is None:
        return Result(skipped="no primary document")
    # Document-scoped only. `inconsistent-artifact` and
    # `raw-lfs-blob` read the repository and never the document,
    # so they are pinned at line 1 and DO NOT move when the
    # document does - correctly. Demanding they shift reported a
    # violation on every repository that had one.
    before = _own(findings_in(_text(_validate(run, repo))))
    if not before:
        return Result(skipped="no document findings to move")
    try:
        path.write_bytes(b"\n" + original)
        after = _own(findings_in(_text(_validate(run, repo))))
    finally:
        path.write_bytes(original)
    expected = {(p, n + 1, k, d) for p, n, k, d in before}
    if expected != after:
        return Result([("SHIFT", f"a line inserted at the top did not move "
                                 f"every finding by one: "
                                 f"{_describe(expected, after)}")])
    return Result()


def oracle_crlf(run, repo: Path) -> Result:
    """Rewriting LF to CRLF changes no finding and no line number.

    The contract this project has already broken once. `strip_code` rebuilt
    terminators with `splitlines()` and `"\\n".join`, which is why CRLF cost
    1627 characters on one document, and a rule counting `\\n` reports line 1
    for everything in a file that uses bare carriage returns.
    """
    path, original = _readable(repo)
    if original is None:
        return Result(skipped="no primary document")
    # BOTH DIRECTIONS. Python's text mode writes CRLF on Windows, so every
    # generated document already has it there - and a one-way oracle
    # skipped on 6 of 6 repositories, holding nothing on the one platform
    # whose line endings are the reason this contract exists.
    crlf, lf = b"\r\n", b"\n"
    flipped = (original.replace(crlf, lf) if crlf in original
               else original.replace(lf, crlf))
    if flipped == original:
        return Result(skipped="document has no line breaks to rewrite")
    before = _own(findings_in(_text(_validate(run, repo))))
    try:
        path.write_bytes(flipped)
        after = _own(findings_in(_text(_validate(run, repo))))
    finally:
        path.write_bytes(original)
    if before != after:
        return Result([("CRLF", f"CRLF changed the findings: "
                                f"{_describe(before, after)}")])
    return Result()


def oracle_relocate(run, repo: Path) -> Result:
    """The same document under another name reports the same findings.

    A SIBLING name, never another directory. Relative links and path pointers
    resolve against the citing document, so moving it down a level genuinely
    changes what its links mean - the answer would differ for a correct tool,
    and an oracle demanding otherwise would be wrong rather than strict.
    """
    path, original = _readable(repo)
    if original is None:
        return Result(skipped="no primary document")
    before = _document_only(findings_in(_text(_validate(run, repo))))
    twin = repo / "NEXT_SESSION_twin.md"
    try:
        twin.write_bytes(original)
        after = _document_only(
            findings_in(_text(_validate(run, repo, twin.name))))
    finally:
        twin.unlink(missing_ok=True)
    # The primary document prints its findings bare and every other prefixes
    # its path, so the twin's arrive prefixed. Compare on everything else.
    bare_before = {(n, k, d) for _p, n, k, d in before}
    bare_after = {(n, k, d) for _p, n, k, d in after}
    if bare_before != bare_after:
        return Result([("RELOCATE", f"renaming the document changed its "
                                    f"findings: "
                                    f"{_describe(bare_before, bare_after)}")])
    return Result()


def oracle_monotone(run, repo: Path) -> Result:
    """Adding an unrelated document removes no finding from another one."""
    path, original = _readable(repo)
    if original is None:
        return Result(skipped="no primary document")
    before = _own(findings_in(_text(_validate(run, repo))))
    extra = repo / "unrelated-note.md"
    try:
        extra.write_text("# Unrelated\n\nNothing here makes a claim.\n",
                         encoding="utf-8")
        after = _own(findings_in(_text(_validate(run, repo))))
    finally:
        extra.unlink(missing_ok=True)
    lost = before - after
    if lost:
        return Result([("MONOTONE", f"adding an unrelated document removed "
                                    f"{len(lost)} finding(s): "
                                    f"{sorted(lost)[:2]}")])
    return Result()


def oracle_baseline(run, repo: Path) -> Result:
    """Recording every finding and then honouring that record reports none.

    The baseline is a SUPPRESSION, and this project's own rule is that a
    suppression firing wrongly deletes a real finding silently, where a false
    positive at least appears for somebody to argue with. It had no fuzz
    coverage at all before this.
    """
    first = _text(run(repo, ["--verify"]))
    before = findings_in(first)
    if not before:
        return Result(skipped="nothing to baseline")
    marker = repo / ".extant-baseline-probe.json"
    try:
        written = run(repo, ["--verify", "--write-baseline", marker.name])
        if written is None or not marker.exists():
            return Result(skipped="--write-baseline produced no file")
        done = run(repo, ["--verify", "--baseline", marker.name])
        out = _text(done)
        after = findings_in(out)
    finally:
        marker.unlink(missing_ok=True)
    faults = []
    if after:
        faults.append(("BASELINE", f"{len(after)} finding(s) survived a "
                                   f"baseline recording all {len(before)}: "
                                   f"{sorted(after)[:2]}"))
    if done is not None and done.returncode != 0 and not after:
        faults.append(("BASELINE", f"no findings survived the baseline but "
                                   f"the run exited {done.returncode}"))
    return Result(faults)


def oracle_process(run, repo: Path) -> Result:
    """One process reading two documents agrees with two processes reading one.

    This is the `scope.py` class. That module exists because 26 module-level
    caches had lifetimes nobody could state, and its memo rule turns on whether
    a memo's key is complete; one that reads git or the disk has to be dropped
    in `registry.forget_memos()`. Nothing asked whether the dropping happens,
    because the harness ran one mode per process.

    `--verify` reads the primary document and every `extra_docs` entry in ONE
    process. `--validate` on the same extra document reads it in another. A
    finding that appears in one and not the other is a cache outliving its
    subject.
    """
    extra = repo / "README.md"
    if not extra.exists():
        return Result(skipped="no second document configured")
    verify_out = _text(run(repo, ["--verify"]))
    # THE FILE EXISTING IS NOT THE SAME AS VERIFY READING IT. `--verify` gates
    # on whatever `primary_doc` names, and the generator ships a config
    # pointing at a file that does not exist, so verify refuses outright and
    # reads no document at all - while `--validate README.md` reads README
    # perfectly well. Comparing those reported a disagreement between one mode
    # that answered and one that declined to start.
    if f"checked {extra.name}:" not in verify_out:
        return Result(skipped=f"--verify did not read {extra.name}")
    together = findings_in(verify_out)
    alone = findings_in(_text(_validate(run, repo, extra.name)))
    # Only what each says ABOUT README.md, which is prefixed in the first and
    # bare in the second, since --validate makes it the primary.
    in_verify = {(n, k, d) for p, n, k, d in _document_only(together)
                 if p == extra.name}
    in_alone = {(n, k, d) for p, n, k, d in _document_only(alone) if p == ""}
    if in_verify != in_alone:
        return Result([("PROCESS", f"{extra.name} reports differently in one "
                                   f"process than in its own: "
                                   f"{_describe(in_verify, in_alone)}")])
    return Result()


def oracle_mode_agrees(run, repo: Path) -> Result:
    """`--sweep` and `--verify` agree about the document they both read.

    They already do not, and knowingly: repository-scoped rules are attributed
    to the file that declares them by the sweep and to the primary document by
    verify. That asymmetry is why this oracle compares only findings the two
    can both be held to - those carrying a line in the primary document.
    """
    if not _matches_head(repo):
        return Result(skipped="working tree differs from HEAD, so the two "
                              "modes are reading different inputs")
    swept_out = _text(run(repo, ["--sweep"]))
    verify_out = _text(run(repo, ["--verify"]))
    # Did `--verify` actually read this document? It gates on whatever
    # `primary_doc` names, and the generator deliberately ships a config
    # pointing at a file that does not exist - so verify checked something
    # else entirely while the sweep read every tracked document, and the two
    # were reported as disagreeing when they had answered different questions.
    # Structural rather than a config parse: every document verify reads gets
    # a `checked <name>:` line.
    if f"checked {PRIMARY}:" not in verify_out:
        return Result(skipped=f"--verify did not read {PRIMARY}")
    swept = findings_in(swept_out)
    verified = findings_in(verify_out)
    if not swept and not verified:
        return Result(skipped="neither mode reported anything")
    # The sweep prefixes every path including the primary; verify prints the
    # primary bare. Compare the primary document's findings alone.
    in_sweep = {(n, k, d) for p, n, k, d in _document_only(swept)
                if p in ("", PRIMARY)}
    in_verify = {(n, k, d) for p, n, k, d in _document_only(verified)
                 if p == ""}
    if in_sweep != in_verify:
        return Result([("MODE-AGREE", f"sweep and verify disagree about "
                                      f"{PRIMARY}: "
                                      f"{_describe(in_sweep, in_verify)}")])
    return Result()


def oracle_denominator_agrees(run, repo: Path) -> Result:
    """The denominator SARIF carries equals the one the text run printed.

    `format_sarif` emits `examined: <kind> <n>, ...` as a notification, in the
    same spelling the text run prints, so this needs no new parser. The
    existing FORMATS check compares only RESULT counts - one half of the
    conflation this project exists to refuse, checked, and the other not.
    """
    text_out = _text(run(repo, ["--sweep"]))
    sarif_out = _stdout(run(repo, ["--sweep", "--format=sarif"]))
    if not sarif_out.strip():
        return Result(skipped="sweep emitted no SARIF")
    try:
        doc = json.loads(sarif_out)
    except (json.JSONDecodeError, ValueError):
        return Result([("DENOM-AGREE", "SARIF did not parse")])
    stated = None
    for run_block in doc.get("runs", []):
        for invocation in run_block.get("invocations", []) or []:
            for note in invocation.get("toolExecutionNotifications", []) or []:
                message = (note.get("message") or {}).get("text", "")
                if message.startswith("examined: "):
                    stated = message
    if stated is None:
        return Result(skipped="SARIF carried no denominator")
    from_text = re.search(r"^\s*examined: (.+)$", text_out, re.M)
    if from_text is None:
        return Result(skipped="the text sweep printed no denominator")
    if stated[len("examined: "):].strip() != from_text.group(1).strip():
        return Result([("DENOM-AGREE",
                        f"sarif says {stated[len('examined: '):][:60]!r}, "
                        f"text says {from_text.group(1)[:60]!r}")])
    return Result()


def oracle_github(run, repo: Path) -> Result:
    """The github format reports as many findings as the text run.

    SARIF was cross-checked from the start and this format never was, so a
    third of the output surface was gated on nothing.
    """
    text_out = _text(run(repo, ["--sweep"]))
    gh_out = _text(run(repo, ["--sweep", "--format=github"]))
    text_count = len(findings_in(text_out))
    gh_count = len(re.findall(r"^::(?:error|warning|notice)\s", gh_out, re.M))
    if not text_count and not gh_count:
        return Result(skipped="neither format reported anything")
    if text_count != gh_count:
        return Result([("GITHUB", f"github printed {gh_count} annotation(s), "
                                  f"text printed {text_count} finding(s)")])
    return Result()


# Order matters only for reading the output. The mutating oracles come first
# so that a failure in one is reported before the read-only ones spend spawns.
ORACLES = (
    ("FENCE", oracle_fence),
    ("SHIFT", oracle_shift),
    ("CRLF", oracle_crlf),
    ("RELOCATE", oracle_relocate),
    ("MONOTONE", oracle_monotone),
    ("BASELINE", oracle_baseline),
    ("PROCESS", oracle_process),
    ("MODE-AGREE", oracle_mode_agrees),
    ("DENOM-AGREE", oracle_denominator_agrees),
    ("GITHUB", oracle_github),
)


def run_all(run, repo: Path, only=None):
    """Every oracle over one repository.

    Returns (faults, skipped) where `skipped` maps an oracle's name to the
    reason it did not run, so the caller can print how much of this was
    actually held rather than how much was attempted.
    """
    faults = []
    skipped = {}
    for name, oracle in ORACLES:
        if only is not None and name not in only:
            continue
        try:
            result = oracle(run, repo)
        except DidNotRun as exc:
            skipped[name] = str(exc)
            continue
        except (OSError, ValueError, UnicodeError) as exc:
            # An oracle that raised did not decide anything, and must not be
            # read as one that passed.
            skipped[name] = f"{type(exc).__name__}: {exc}"[:90]
            continue
        faults.extend(result.faults)
        if result.skipped:
            skipped[name] = result.skipped
    return faults, skipped
