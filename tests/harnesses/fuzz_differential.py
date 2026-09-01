"""Stage 4: one corpus, two versions, the findings diffed per repository.

    python tests/harnesses/fuzz.py PKG ARENA --differential [REF|DIR]

WHY THIS NEEDS NO ORACLE

Every other property in this harness has to hold whatever the right answer is,
because a fuzzer cannot know what a generated repository ought to report. This
one sidesteps that entirely: it does not ask what the answer SHOULD be, only
whether it CHANGED. Any difference is either an intended change or a
regression, and a human reads which. That is the cheapest useful oracle there
is, and it is the only one here that can catch a rule quietly going quiet.

It is also the only property that sees a whole class the others cannot. The
metamorphic oracles compare extant against itself under a change that must not
matter - a format, a line ending, a rerun. None of them notices a rule that
stops firing altogether, because a rule that reports nothing is self-consistent
in every one of those comparisons. The previous release is the only reference
here that disagrees with silence.

Offline by construction: `git archive` reads the local object database, and
both versions run against repositories on disk. Nothing contradicts the
`p_offline` smoke probe or the no-network guarantee.

WHY IT REBUILDS RATHER THAN SWAPPING `tools/`

The generated repository CARRIES the payload: `build_from_plan` copies it to
`tools/` and the next `git add -A` commits it. Swapping the directory in place
would leave the working tree dirty against HEAD for one of the two runs, and
two features write claims about `tools/` paths, so the comparison would be
measuring the swap as much as the versions.

So each side gets a pristine repository built from the same plan, at the SAME
arena path, one after the other. The path is not incidental - this harness
learned the hard way that the arena path is an input on Windows, where two runs
of one seed reached the rules in 25 of 35 repositories and then 6 because a
directory was named `arenaPeer2` rather than `arenaPeer`. Building both sides
at one path removes that variable rather than hoping it does not matter.

WHY THE COMPARISON IS NORMALISED, AND WHAT THAT COSTS

Two builds of one plan do not produce the same commit SHAs. They cannot: the
committed `tools/` differs between versions, and `git commit` stamps the
current time, so even HEAD against HEAD gets different hashes. Two features
write a REAL head SHA into the generated document, so the raw output of the two
runs differs on every repository that draws one.

Hex runs are therefore replaced by `<SHA>` and repository paths by `<REPO>`
before anything is compared. The cost is stated rather than hidden: a genuine
change that shows up ONLY as a different SHA is invisible here. Nothing else is
masked - versions are not normalised, because a version is a thing a rule
reports about, and blanking those would hide exactly the `dead-release-tag`
changes this comparison exists to surface.

The tool's own version is dodged differently, by reading SARIF STRUCTURE rather
than text: the results and the denominators, never `tool.driver`. A differential
that reported "the version string changed" on every release would be one nobody
runs twice.

HEAD AGAINST HEAD IS THE CONTROL, AND IT IS NOT CEREMONIAL

`--differential HEAD` compares the working package against an extract of HEAD -
two builds, two sets of commit SHAs, one payload. It must report zero
differences. If normalisation is insufficient the control goes red, which is the
only way to find out that this comparison is reporting noise. Run it before
believing a clean result against a real tag, for the same reason `mutate.py`
treats a non-matching anchor as a harness fault: a comparison that cannot tell
two things apart reports agreement, and agreement is what it is supposed to
mean something.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

# A hex run long enough to be a commit. The same lower bound the tool's own
# bare-SHA scanner uses, so a token this masks is one a rule would have read.
_HEX = re.compile(r"\b[0-9a-f]{7,40}\b")
# Windows prints backslashes and posix forward slashes for the same path, and
# the two versions need not agree with each other about which - `rel()` changed
# spelling once. Both spellings of the repository root collapse to one token.
#
# DEFENSIVE RATHER THAN LOAD-BEARING, and worth saying which: both sides run at
# the SAME arena path, so the repository path is identical between them and
# masking it changes nothing today. It is here for the day the two versions
# spell one path differently, which is a difference about spelling rather than
# about the repository. The hex substitution below is the one the comparison
# cannot work without.


def latest_tag(source: Path) -> str:
    """The most recent tag reachable from HEAD, or "" if there is none.

    `--sort=-v:refname` rather than `describe`, because `describe` answers with
    the nearest tag and this wants the newest RELEASE. On a branch cut before
    the last tag those are different, and comparing against an older release
    than the one that shipped would quietly weaken the check.
    """
    done = subprocess.run(["git", "tag", "--sort=-v:refname", "--merged",
                           "HEAD"], cwd=str(source), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        return ""
    for line in (done.stdout or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def materialise(spec: str, source: Path, into: Path) -> tuple[Path, str]:
    """The package to compare against, as an extracted tree.

    A directory is used as it stands, which is what lets somebody point this at
    a checkout they are holding. Anything else is a git ref, extracted with
    `git archive` - the same way this project's own CI builds the package it
    tests, so the baseline is what the tag SHIPPED rather than what a worktree
    of it happens to contain.

    Extraction goes through `tarfile` rather than the `tar` binary, which
    Windows does not reliably have. Returns (path, a description for the log).
    """
    candidate = Path(spec)
    if candidate.is_dir():
        return candidate.resolve(), f"directory {candidate}"

    done = subprocess.run(["git", "archive", "--format=tar", spec],
                          cwd=str(source), capture_output=True)
    if done.returncode != 0:
        detail = (done.stderr or b"").decode("utf-8", "replace").strip()
        raise ValueError(f"cannot archive {spec!r}: {detail[:200]}")
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        try:
            tar.extractall(str(into), filter="data")
        except TypeError:
            # `filter` arrives in 3.12. The floor here is 3.9, and this archive
            # is one this repository just produced from its own objects.
            tar.extractall(str(into))
    if not (into / "plugin/skills/extant/payload").is_dir():
        raise ValueError(
            f"{spec!r} extracted, but carries no "
            f"plugin/skills/extant/payload - it is not a package this "
            f"harness can install")
    return into.resolve(), f"git ref {spec}"


def normalise(text: str, repo: Path) -> str:
    """One run's output, with the parts that cannot match blanked.

    Order matters: paths first, because a repository path can contain a hex run
    long enough to look like a commit, and masking the hex first would leave
    half a path behind and defeat the path substitution.
    """
    out = text or ""
    native = str(repo)
    for spelling in {native, native.replace("\\", "/"), repo.as_posix()}:
        if spelling:
            out = out.replace(spelling, "<REPO>")
    return _HEX.sub("<SHA>", out)


def fingerprint(repo: Path) -> tuple:
    """What the repository IS, apart from the payload it happens to carry.

    THE CONTROL WENT RED ONCE, UNDER LOAD, AND THIS IS WHY IT COULD. Two builds
    of one plan are only identical if every git command in both of them
    succeeded, and `build_from_plan` checks return codes on the CORE steps
    only - `must()` covers init, add and commit, while the hostile refs, the
    tags and the scaffold go through `sh()`, which does not look. On a busy
    machine one of those can lose a race with an index lock, and the result is
    a repository missing a branch or a tag: a real difference in what the two
    versions were asked about, reported as a difference in what they answered.

    Observed once during a run concurrent with a 35-repository fuzz campaign -
    FINDING 1, EXAMINED 1, OUTPUT 1, one rule in one repository - and not
    reproduced in five clean runs afterwards. Rare is not the same as absent,
    and a differential whose control is intermittently red is worse than one
    that is broken outright: it teaches whoever runs it to discount a red
    result, which is the only signal it has.

    So the two repositories are compared to each other BEFORE their outputs
    are. Ref and tag NAMES rather than their SHAs, because the SHAs must differ
    and the names must not. Tracked paths with `tools/` removed, because that
    is the payload and differing is its whole purpose. The commit count,
    because a lost commit changes every ancestry question in the tool.
    """
    def git(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=str(repo),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        return (done.stdout or "") if done.returncode == 0 else "<failed>"

    refs = sorted(line.strip() for line in
                  git("for-each-ref", "--format=%(refname)").splitlines()
                  if line.strip())
    tracked = sorted(line.strip() for line in
                     git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
                     if line.strip() and not line.strip().startswith("tools/"))
    commits = git("rev-list", "--all", "--count").strip()
    return (tuple(refs), tuple(tracked), commits)


def _sarif_examined(run: dict) -> dict:
    """The per-rule denominators, from wherever this version puts them.

    Two places, because the property moved: `runs[0].properties` now, and
    `invocations[0].properties` in versions that predate it. Reading both is
    what lets this compare across the move instead of reporting every rule as
    having appeared or vanished.
    """
    found = (run.get("properties") or {}).get("examined")
    if found is None:
        invocations = run.get("invocations") or [{}]
        found = (invocations[0].get("properties") or {}).get("examined")
    return found if isinstance(found, dict) else {}


@dataclass(frozen=True)
class Report:
    """What one version said about one repository."""

    findings: tuple           # (ruleId, uri, line, normalised message)
    examined: tuple           # (rule, count), sorted
    mode_exit: int            # exit code of the repository's drawn mode
    mode_text: str            # its normalised stdout+stderr
    sarif_ok: bool            # did the sweep produce parseable SARIF at all
    crashed: bool


def observe(repo: Path, mode, run_mode) -> Report:
    """Run one version against one repository and record what it said.

    TWO runs, and they answer different questions. The SARIF sweep is the
    structured one and sees every repository whatever mode it drew, which is
    the same reason `all_faults` probes with a plain sweep. The drawn mode is
    the unstructured one and is what gives this differential any reach into
    `--selftest` and `--deleted-since`, which emit no SARIF and would otherwise
    never be compared at all.
    """
    crashed = False
    sweep = run_mode(repo, ["--sweep", "--format=sarif"])
    findings: list[tuple] = []
    examined: dict = {}
    sarif_ok = False
    if sweep is not None:
        blob = sweep.stdout or ""
        if "Traceback (most recent call last)" in (blob + (sweep.stderr or "")):
            crashed = True
        try:
            doc = json.loads(blob)
        except (ValueError, TypeError):
            doc = None
        if isinstance(doc, dict) and doc.get("runs"):
            sarif_ok = True
            run = doc["runs"][0]
            examined = _sarif_examined(run)
            for result in run.get("results") or []:
                location = ((result.get("locations") or [{}])[0]
                            .get("physicalLocation") or {})
                uri = (location.get("artifactLocation") or {}).get("uri", "")
                line = (location.get("region") or {}).get("startLine", 0)
                message = ((result.get("message") or {}).get("text") or "")
                findings.append((result.get("ruleId", ""), uri, line,
                                 normalise(message, repo)))

    drawn = run_mode(repo, list(mode))
    if drawn is None:
        mode_exit, mode_text = -1, "<no answer inside the timeout>"
    else:
        mode_exit = drawn.returncode
        blob = (drawn.stdout or "") + (drawn.stderr or "")
        if "Traceback (most recent call last)" in blob:
            crashed = True
        mode_text = normalise(blob, repo)

    return Report(findings=tuple(sorted(findings)),
                  examined=tuple(sorted((k, v) for k, v in examined.items())),
                  mode_exit=mode_exit, mode_text=mode_text,
                  sarif_ok=sarif_ok, crashed=crashed)


def _window(left: str, right: str, width: int = 58) -> str:
    """Both lines from just before the character where they start to differ.

    TRUNCATING FROM THE LEFT PRINTED A DIFFERENCE NOBODY COULD SEE. The
    `examined:` line is the one this reports most often, and it is long: two
    versions disagreeing about the eleventh rule on it produced

        head 'examined: dead-sha 0, stale-live-claim 2, unknown-br' vs
        base 'examined: dead-sha 0, stale-live-claim 2, unknown-br'

    - two identical strings, offered as evidence of a difference, because the
    divergence sat past the cut. A report that shows the reader nothing is the
    shape this whole project exists to refuse, and it does not stop being that
    shape because the underlying finding is real.
    """
    common = 0
    for a, b in zip(left, right):
        if a != b:
            break
        common += 1
    start = max(0, common - 10)
    lead = "..." if start else ""
    return (f"head {lead + left[start:start + width]!r} vs "
            f"base {lead + right[start:start + width]!r}")


def _text_difference(head: str, base: str) -> str:
    """Where two runs' text first parts company, as one short string.

    A whole diff of a 60,000-character noise document is not something anybody
    reads out of a fuzz log. The divergence point plus its line number is
    enough to identify the repository and the mode; the plan is what somebody
    replays to see the rest.
    """
    head_lines, base_lines = head.splitlines(), base.splitlines()
    for number, (left, right) in enumerate(zip(head_lines, base_lines), 1):
        if left != right:
            return f"line {number}: {_window(left, right)}"
    if len(head_lines) != len(base_lines):
        longer, which = ((head_lines, "head") if len(head_lines) > len(base_lines)
                         else (base_lines, "base"))
        extra = longer[min(len(head_lines), len(base_lines))]
        return (f"{which} has {abs(len(head_lines) - len(base_lines))} extra "
                f"line(s), first: {extra.strip()[:70]!r}")
    return "differ in trailing whitespace only"


def compare(head: Report, base: Report) -> list[tuple[str, str]]:
    """Every way these two disagreed, classified.

    FINDING is the one that matters and is listed first for that reason: a
    result present in one version and not the other is a behaviour change in
    what the tool REPORTS. EXAMINED is a denominator change, which this project
    changes deliberately often enough that folding the two together would bury
    the first in the second - the six denominators narrowed in the release
    after 0.25.0 would have printed as thirty-odd differences with the one that
    mattered somewhere among them.

    CRASH and SARIF are separated from both because they are not differences of
    opinion about a repository, they are one version failing to answer.
    """
    out: list[tuple[str, str]] = []

    if head.crashed != base.crashed:
        which = "head" if head.crashed else "base"
        out.append(("CRASH", f"{which} crashed and the other did not"))
    if head.sarif_ok != base.sarif_ok:
        which = "head" if base.sarif_ok else "base"
        out.append(("SARIF", f"{which} produced no parseable SARIF document"))

    gone = [f for f in base.findings if f not in head.findings]
    new = [f for f in head.findings if f not in base.findings]
    for rule, uri, line, message in gone:
        out.append(("FINDING", f"only base reports [{rule}] {uri}:{line} "
                               f"{message[:80]}"))
    for rule, uri, line, message in new:
        out.append(("FINDING", f"only head reports [{rule}] {uri}:{line} "
                               f"{message[:80]}"))

    head_counts, base_counts = dict(head.examined), dict(base.examined)
    for rule in sorted(set(head_counts) | set(base_counts)):
        left, right = head_counts.get(rule), base_counts.get(rule)
        if left != right:
            out.append(("EXAMINED",
                        f"{rule}: head {left} vs base {right}"))

    if head.mode_exit != base.mode_exit:
        out.append(("EXIT", f"drawn mode exited {head.mode_exit} vs "
                            f"{base.mode_exit}"))
    elif head.mode_text != base.mode_text:
        out.append(("OUTPUT", _text_difference(head.mode_text, base.mode_text)))
    return out


def observed(report: Report) -> tuple[int, int]:
    """How much this report actually put on the table: (findings, denominators).

    THE DENOMINATOR OF THE DIFFERENTIAL ITSELF. "0 differences" from a corpus
    where both versions reported nothing at all is not agreement, it is two
    silences compared - and it prints identically to thirty repositories'
    findings matching exactly. Every other check in this harness states what it
    examined for precisely this reason; a comparison is no more exempt than a
    rule is.
    """
    return len(report.findings), len(report.examined)


def summarise(differences: list[tuple[int, str, str]],
              compared: int, unbuilt: int, base_label: str,
              seen: tuple[int, int], mismatched: int = 0) -> None:
    """What the run found, in the shape the other harnesses report.

    The counts are printed whether or not anything differed, because "compared
    0 repositories" and "compared 30 and found nothing" are the two answers
    this file exists to keep apart, and they print identically without it.
    """
    findings_seen, examined_seen = seen
    print()
    print(f"compared {compared} repository(s) against {base_label}")
    print(f"  {findings_seen} finding(s) and {examined_seen} denominator(s) "
          f"were on the table across both versions")
    if unbuilt:
        print(f"  {unbuilt} NOT COMPARED - one side could not be built, so "
              f"the pair was never tested")
    if mismatched:
        print(f"  {mismatched} NOT COMPARED - the two builds were not the "
              f"same repository, so any difference would have been the "
              f"build's, not the tool's. See `fingerprint`.")
    if not differences:
        print("  0 differences")
        if not compared:
            print("  NOTHING WAS COMPARED. That is not a clean result, it is "
                  "an empty one - check the arena path and the baseline.")
        elif not findings_seen and not examined_seen:
            print("  BOTH VERSIONS REPORTED NOTHING ANYWHERE. Two silences "
                  "compared equal, which is not the same fact as two versions "
                  "agreeing - this run holds no evidence either way.")
        return

    by_kind: dict[str, int] = {}
    for _index, kind, _detail in differences:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    order = ["CRASH", "SARIF", "FINDING", "EXAMINED", "EXIT", "OUTPUT"]
    parts = [f"{kind} {by_kind[kind]}" for kind in order if kind in by_kind]
    print(f"  {len(differences)} difference(s): {', '.join(parts)}")
    print()
    print("  A difference is not a failure by itself. Read whether each one is "
          "a change\n  you intended; a FINDING you did not intend is a "
          "regression in what the tool\n  reports, and an EXAMINED you did not "
          "intend is a rule whose reach moved.")
