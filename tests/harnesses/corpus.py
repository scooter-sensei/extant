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


def sweep(repo: Path) -> tuple[int, int]:
    """(markdown files swept, findings). Raises if the tool did not report."""
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
    findings = sum(1 for line in out.splitlines() if ": line " in line)
    return int(match.group(1)), findings


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
    print(f"{'repository':<24} {'files':>7} {'findings':>9}")
    for repo in repos:
        reason = usable(repo)
        if reason:
            broken.append((repo.name, reason))
            print(f"{repo.name:<24} {'-':>7} {'UNUSABLE':>9}  {reason}")
            continue
        try:
            files, findings = sweep(repo)
        except RuntimeError as exc:
            broken.append((repo.name, str(exc).splitlines()[0]))
            print(f"{repo.name:<24} {'-':>7} {'FAILED':>9}")
            continue
        results[repo.name] = {"files": files, "findings": findings}
        print(f"{repo.name:<24} {files:>7} {findings:>9}")

    files = sum(r["files"] for r in results.values())
    findings = sum(r["findings"] for r in results.values())
    print(f"\nmeasured {len(results)} of {len(repos)} repositories: "
          f"{files} markdown files, {findings} findings")

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
