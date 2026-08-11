"""Sweep a directory of real repositories and report what was examined.

    python tests/harnesses/corpus.py <corpus-dir> [--baseline FILE] [--update]

Every false-positive class this project has fixed came from running against
somebody else's repository. That work was done with throwaway shell loops, and
the loops were wrong three times in one session:

  - three repositories were handed to Python as Git Bash paths (`/c/Users/...`)
    which Windows reads as `C:\\c\\Users\\...`; they failed an `is_dir()` test
    and a `continue` skipped them, and the script printed a confident total for
    six repositories while naming nine.
  - two clones failed on Windows MAX_PATH and left an empty index. `ls-files`
    reported no markdown, and the conclusion "helm and vite have no
    documentation" was one step away.
  - a repository whose checkout never completed reported "swept 0 markdown
    files", which reads exactly like a clean repository.

And then this file made the same mistake itself. It counted findings by looking
for `": line "`, which is the PREFIXED shape a sweep uses outside the primary
document - so every finding in the vetted document counted as zero. Measured on
a one-document repository: the sweep reported 1 finding and this reported 0.
The blind spot was exactly the half that gates.

The common shape is a measurement that omits something without saying so. So
the rule here is that a repository which cannot be measured is a FAILURE, never
an omission: preconditions are asserted before anything is counted, and a
corpus with an unusable member exits non-zero no matter how healthy the rest
looks.

`--baseline` compares against a recorded count per repository and reports the
delta, which is how a fix is shown to have moved what it claimed to move and
nothing else. `--update` rewrites that file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

COLLECTOR = (Path(__file__).resolve().parent.parent.parent / "plugin" / "skills"
             / "extant" / "payload" / "extant_collect.py")
SWEPT = re.compile(r"swept (\d+) markdown file")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def usable(repo: Path) -> str | None:
    """Why this repository cannot be measured, or None if it can.

    Checked BEFORE any counting. Each of these has produced a wrong number in
    practice, and each is silent if you only look at the sweep's output.
    """
    if not repo.is_dir():
        return "not a directory"
    if not (repo / ".git").exists():
        return "not a git repository"
    if not _git(repo, "rev-parse", "HEAD").strip():
        return "no HEAD; the clone did not complete"
    tracked = _git(repo, "ls-tree", "-r", "--name-only", "HEAD")
    if not tracked.strip():
        return "HEAD's tree is empty"
    return None


# A finding renders bare in the primary document and path-prefixed everywhere
# else, so matching only the prefixed shape undercounts silently - the one
# error this harness is least entitled to make.
FINDING = re.compile(r"(?:^|: )line \d+: \[([a-z-]+)\]")


def toolchain(repo: Path) -> str:
    """Which generator this repository declares, and which namespace it implies.

    The single largest determinant of what a sweep reports. Detection being
    wrong is worth more than any individual rule: blind, starlight reported 235
    of its own working links as dead; universally on, every real dead link in a
    plain repository stops being reported.

    Recorded per repository so that a corpus run says WHY a count moved, and so
    that detection silently changing on somebody else's repository is visible
    here rather than inferred later from a number that drifted.
    """
    payload = COLLECTOR.parent
    if str(payload) not in sys.path:
        sys.path.insert(0, str(payload))
    try:
        import extant_collect as ec
    except ImportError as exc:                                  # pragma: no cover
        return f"unknown ({exc.__class__.__name__})"
    if not ec._is_generated_site(repo):
        return "none"
    if ec._has_global_anchors(repo):
        return "site/project-ns"
    if ec._has_partial_anchors(repo):
        return "site/partials"
    return "site/page-ns"


def sweep(repo: Path) -> tuple[int, int, dict[str, int], dict[str, str]]:
    """(files swept, findings, findings by kind, digest of each kind's text).

    Raises if nothing was reported."""
    result = subprocess.run(
        [sys.executable, str(COLLECTOR), "--repo", str(repo), "--sweep"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = result.stdout + result.stderr
    if "Traceback" in result.stderr:
        raise RuntimeError(f"{repo.name}: the tool crashed\n{result.stderr[-600:]}")
    match = SWEPT.search(out)
    if not match:
        # No denominator means the run said nothing about what it looked at,
        # and a findings count without one is the failure this file exists to
        # prevent. Refuse it rather than record a number.
        raise RuntimeError(f"{repo.name}: no denominator in output\n{out[-600:]}")
    kinds: dict[str, int] = {}
    # The finding TEXT per rule, digested below. A count alone cannot see a
    # verdict that changed in place: a release claim once moved from "no such
    # tag exists" to "on no integration branch" - a different question about
    # the same line - with the totals identical either side.
    seen: dict[str, list[str]] = {}
    for line in out.splitlines():
        found = FINDING.search(line)
        if found:
            kind = found.group(1)
            kinds[kind] = kinds.get(kind, 0) + 1
            seen.setdefault(kind, []).append(line.strip())
    digests = {
        kind: hashlib.sha256(
            "\n".join(sorted(lines)).encode("utf-8")).hexdigest()[:12]
        for kind, lines in seen.items()
    }
    return int(match.group(1)), sum(kinds.values()), kinds, digests


def examined(repo: Path) -> dict[str, int]:
    """How many candidates each RULE looked at, summed over the repository.

    The other denominator, and the one that decides whether a corpus can gate a
    change at all. `files swept` says the run happened; this says which rules it
    reached. A widening measured where the rule never fires reports no new false
    positives from a denominator of zero, and that reads exactly like a widening
    that is safe.

    It is not hypothetical. Eight coverage widenings were surveyed against 30
    repositories and six aimed at rules with a denominator of zero across all
    3,821 files - the merge-claim pattern matches nothing anyone else writes.
    Without this column that survey would have shipped them as harmless.
    """
    sys.path.insert(0, str(COLLECTOR.parent))
    import extant_collect as hc

    totals: dict[str, int] = {}
    previous_format = hc._DOC.doc_format
    try:
        for relative in hc.tracked_markdown(repo):
            try:
                text = (repo / relative).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # Set per document, because `count_examined` reads it. Most of what
            # it counts now comes from `_prose`, which strips reStructuredText
            # by indentation and markdown by fences - so without this every
            # `.rst` file was stripped as though it were markdown, and numpy
            # alone carries 555 of them. The counts were wrong in the column
            # this harness exists to provide.
            hc._set_document(doc_format=hc._format_for(relative))
            for kind, count in hc.count_examined(repo, text).items():
                totals[kind] = totals.get(kind, 0) + count
    finally:
        hc._set_document(doc_format=previous_format)
    return totals


def formats(repo: Path) -> dict[str, int]:
    """Tracked documentation files by extension.

    Yield tracks the novelty of a repository's doc TOOLCHAIN rather than its
    size, and format is half of that: `.rst` behaves nothing like `.md`, and
    numpy alone carries 555 of them. A corpus that reports only a total cannot
    show which half of it a change touched.
    """
    counts: dict[str, int] = {}
    for path in _git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines():
        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if suffix in ("md", "markdown", "mdx", "rst"):
            counts[suffix] = counts.get(suffix, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", help="directory holding cloned repositories")
    parser.add_argument("--baseline", metavar="FILE",
                        help="compare per-repository counts against this file")
    parser.add_argument("--update", action="store_true",
                        help="rewrite the baseline from this run")
    args = parser.parse_args(argv)

    root = Path(args.corpus)
    if not root.is_dir():
        print(f"no such corpus directory: {root}", file=sys.stderr)
        return 2
    repos = sorted(p for p in root.iterdir() if p.is_dir())
    if not repos:
        print(f"{root} contains no repositories", file=sys.stderr)
        return 2

    broken: list[tuple[str, str]] = []
    results: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    looked: dict[str, int] = {}
    by_format: dict[str, int] = {}
    print(f"{'repository':<24} {'files':>7} {'rst':>5} {'findings':>9}  toolchain")
    for repo in repos:
        reason = usable(repo)
        if reason:
            broken.append((repo.name, reason))
            print(f"{repo.name:<24} {'-':>7} {'-':>5} {'UNUSABLE':>9}  {reason}")
            continue
        try:
            files, findings, kinds, digests = sweep(repo)
        except RuntimeError as exc:
            broken.append((repo.name, str(exc).splitlines()[0]))
            print(f"{repo.name:<24} {'-':>7} {'-':>5} {'FAILED':>9}")
            continue
        shapes = formats(repo)
        for suffix, count in shapes.items():
            by_format[suffix] = by_format.get(suffix, 0) + count
        for kind, count in kinds.items():
            totals[kind] = totals.get(kind, 0) + count
        for kind, count in examined(repo).items():
            looked[kind] = looked.get(kind, 0) + count
        # Per RULE, not just a total: a change that moves findings from one
        # rule to another leaves the total alone. Denominators too, because
        # a widening can treble what a rule examines while reporting the
        # same findings - which is exactly what the merge-claim widening
        # did, 3 examined to 35 with nothing added.
        results[repo.name] = {
            "files": files, "findings": findings,
            "by_rule": dict(sorted(kinds.items())),
            "digest": dict(sorted(digests.items())),
            "examined": dict(sorted(examined(repo).items())),
        }
        print(f"{repo.name:<24} {files:>7} {shapes.get('rst', 0):>5} "
              f"{findings:>9}  {toolchain(repo)}")

    files = sum(r["files"] for r in results.values())
    findings = sum(r["findings"] for r in results.values())
    print(f"\nmeasured {len(results)} of {len(repos)} repositories: "
          f"{files} markdown files, {findings} findings")
    if by_format:
        print("  by format:   " + ", ".join(
            f"{suffix} {count}" for suffix, count in sorted(by_format.items())))
    # Which RULES produced the findings, not just how many. Measured across 41
    # repositories, 91% were link or anchor findings and 8% git-history - but on
    # agent-written plan documents that inverts almost exactly. A total alone
    # cannot show which of those a corpus is made of, and the mix is the thing
    # that says what a change to one rule will actually move.
    if totals:
        print("  by rule:     " + ", ".join(
            f"{kind} {count}" for kind, count in
            sorted(totals.items(), key=lambda kv: -kv[1])))
    # Found over EXAMINED, per rule. See `examined` for why the second number
    # is the one that says whether this corpus can gate a change.
    if looked:
        # `bare-dead-sha` shares `dead-sha`'s denominator, because
        # count_examined counts backticked and bare SHA candidates together.
        # Printing its findings against a denominator of zero, or omitting
        # them, would misreport the busiest rule in the corpus.
        shared = {"bare-dead-sha": "dead-sha"}
        found: dict[str, int] = {}
        for kind, count in totals.items():
            found[shared.get(kind, kind)] = found.get(shared.get(kind, kind), 0) + count
        print("  found/examined per rule:")
        for kind in sorted(looked, key=lambda k: -looked[k]):
            note = "  (incl. bare)" if kind == "dead-sha" else ""
            print(f"    {kind:<24} {found.get(kind, 0):>6} / {looked[kind]}{note}")
        blind = [k for k, n in sorted(looked.items()) if n == 0]
        if blind:
            print("  CANNOT GATE A CHANGE to these - nothing here exercises "
                  "them: " + ", ".join(blind))

    baseline_path = Path(args.baseline) if args.baseline else None
    if baseline_path and args.update:
        baseline_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
        print(f"wrote {baseline_path} for {len(results)} repositories")
    elif baseline_path and baseline_path.is_file():
        previous = json.loads(baseline_path.read_text(encoding="utf-8"))
        moved = [(name, previous[name]["findings"], r["findings"])
                 for name, r in sorted(results.items())
                 if name in previous and previous[name]["findings"] != r["findings"]]
        missing = sorted(set(previous) - set(results))
        print(f"compared {len(results)} against {len(previous)} recorded: "
              f"{len(moved)} changed, {len(missing)} no longer measured")
        for name, was, now in moved:
            print(f"  {name:<22} {was} -> {now}")

        # THREE THINGS A TOTAL CANNOT SEE, each of which happened during the
        # work that added them:
        #
        #   by_rule   findings moving BETWEEN rules. A narrowing removed 19
        #             `dead-release-tag` while a widening was adding elsewhere;
        #             a total nets those off and reports nothing.
        #   digest    a verdict changing IN PLACE. One release claim went from
        #             "no such tag exists" to "on no integration branch" - a
        #             different question about the same line - with identical
        #             counts either side.
        #   examined  COVERAGE. Making a merge claim's commit optional took one
        #             rule from 3 candidates examined to 35 and added no
        #             finding at all. A findings diff calls that "no change",
        #             which is the opposite of what happened.
        # Three populations, not two. A repository ABSENT from the baseline is
        # new and has nothing to compare against; one PRESENT without
        # `by_rule` was recorded before per-rule detail existed. Counting the
        # first as the second told the reader to re-run with --update to
        # deepen a record that does not exist yet.
        detailed = [n for n in results if "by_rule" in previous.get(n, {})]
        shallow = [n for n in results
                   if n in previous and "by_rule" not in previous[n]]
        if shallow:
            # Never compare less than advertised without saying so.
            print(f"  NOTE: {len(shallow)} repository(ies) were recorded "
                  f"before per-rule detail existed, so only their totals were "
                  f"compared. Re-run with --update to deepen it.")
        for name in sorted(detailed):
            was, now = previous[name], results[name]
            for label, key in (("rule", "by_rule"), ("examined", "examined")):
                old_map, new_map = was.get(key, {}), now.get(key, {})
                for rule in sorted(set(old_map) | set(new_map)):
                    a, b = old_map.get(rule, 0), new_map.get(rule, 0)
                    if a != b:
                        print(f"  {name:<22} {label:<8} {rule:<22} "
                              f"{a} -> {b}")
            old_dig, new_dig = was.get("digest", {}), now.get("digest", {})
            for rule in sorted(set(old_dig) & set(new_dig)):
                if (old_dig[rule] != new_dig[rule]
                        and was.get("by_rule", {}).get(rule)
                        == now.get("by_rule", {}).get(rule)):
                    print(f"  {name:<22} REWORDED {rule}: same count, "
                          f"different text")
        if missing:
            # A repository dropping out of the corpus silently is how a
            # regression hides. It is reported, and it fails the run.
            print(f"  NO LONGER MEASURED: {', '.join(missing)}")
            broken.extend((name, "recorded previously, absent now") for name in missing)

    if broken:
        print(f"\n{len(broken)} repository(ies) could not be measured, so the "
              f"totals above are incomplete:", file=sys.stderr)
        for name, reason in broken:
            print(f"  {name}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
