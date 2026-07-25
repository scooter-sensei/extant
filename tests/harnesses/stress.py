"""Stress and load testing: find where handoff-validator falls over.

Deliberately aimed at the WEAK points rather than at comfortable ones. The
merge-claim rule was optimised by asking git once per distinct commit, so the
adversarial case is a document where every claim names a different commit and
that deduplication buys nothing. The case-sensitivity check lists a directory
per path component, so the adversarial case is thousands of links in a deep
tree. A benchmark that avoids those is measuring the wrong thing.

Reports peak memory as well as time. A tool that is fast because it holds a
10 MB document and every intermediate list in memory at once has not solved the
problem, it has moved it.

    python tests/harnesses/stress.py <extracted-package> <scratch-dir>

Expect this to take a while. Each case builds a real repository.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

PKG = Path(sys.argv[1])
ARENA = Path(sys.argv[2])
PY = sys.executable

RESULTS: list[tuple[str, str, str]] = []   # (case, measurement, verdict)


def sh(cwd: Path, *args: str, timeout: int = 600):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def new_repo(name: str) -> Path:
    repo = ARENA / name
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "T")
    sh(repo, "git", "config", "gc.auto", "0")
    shutil.copytree(PKG / "plugin/skills/handoff/payload", repo / "tools")
    return repo


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def bulk_commits(repo: Path, count: int) -> list[str]:
    """Create `count` commits quickly via fast-import, returning their SHAs.

    A loop of `git commit` costs roughly 50 ms each on Windows, which is four
    minutes for 5000 commits and dwarfs the thing being measured.
    """
    lines = ["blob", "mark :1", "data 2", "x\n"]
    for n in range(1, count + 1):
        msg = f"feat: bulk commit {n}"
        lines += [
            f"commit refs/heads/main",
            f"mark :{n + 100}",
            "committer T <t@t> 1700000000 +0000",
            f"data {len(msg)}",
            msg,
        ]
        if n > 1:
            lines.append(f"from :{n + 99}")
        lines.append(f"M 100644 :1 file{n % 50}.txt")
        lines.append("")
    # BYTES, not text. With text=True Python translates "\n" to "\r\n" on the
    # pipe under Windows, and fast-import rejects the stream with
    # "unsupported command: blob?" - the ? being the carriage return it choked
    # on. Encoding explicitly keeps the line endings the protocol requires.
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    proc = subprocess.run(["git", "fast-import", "--quiet"], cwd=repo,
                          input=payload, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"fast-import failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
    sh(repo, "git", "reset", "--hard", "main")
    out = sh(repo, "git", "log", "--format=%h", "-n", str(count)).stdout
    return [s for s in out.split() if s]


def report(case: str, measurement: str, verdict: str) -> None:
    RESULTS.append((case, measurement, verdict))
    print(f"  {measurement:<34} {verdict}")


def run_timed(repo: Path, *args: str, budget: float, timeout: int = 600):
    """Time a subprocess run and judge it against a budget in seconds."""
    start = time.perf_counter()
    try:
        proc = sh(repo, PY, str(repo / "tools/handoff_collect.py"),
                  "--repo", str(repo), *args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, timeout
    return proc, time.perf_counter() - start


def verdict_for(elapsed: float, budget: float) -> str:
    if elapsed is None:
        return "TIMED OUT"
    if elapsed > budget * 3:
        return f"{elapsed:6.1f}s  FAR OVER budget {budget}s"
    if elapsed > budget:
        return f"{elapsed:6.1f}s  over budget {budget}s"
    return f"{elapsed:6.1f}s  ok (budget {budget}s)"


# ------------------------------------------------------ 1. distinct SHA density
def case_distinct_shas() -> None:
    """The adversarial case for the merge-claim optimisation.

    Deduplication by commit is what made that rule fast. A document naming a
    DIFFERENT commit every time gets no benefit from it, so this is where the
    fix's real cost shows.
    """
    print("\n[1] 2000 merge claims, every one a DISTINCT commit")
    repo = new_repo("stress-shas")
    shas = bulk_commits(repo, 2000)
    print(f"      built {len(shas)} commits")
    body = "\n".join(f"Merged to `main` at `{s}`." for s in shas)
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n\n## 1. Ref\n")
    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=30)
    report("distinct-shas", f"{len(shas)} distinct merge claims",
           verdict_for(elapsed, 30))
    if proc:
        findings = [l for l in proc.stdout.splitlines() if l.startswith("line ")]
        report("distinct-shas", "false positives on true claims",
               "none" if not findings else f"{len(findings)} UNEXPECTED")


# ------------------------------------------------------------ 2. huge document
def case_huge_document() -> None:
    print("\n[2] 100,000-line document (~7 MB)")
    repo = new_repo("stress-doc")
    shas = bulk_commits(repo, 5)
    body = []
    for n in range(100_000):
        if n % 50 == 0:
            body.append(f"Merged to `main` at `{shas[0]}`.")
        elif n % 50 == 25:
            body.append("See [tool](tools/handoff_collect.py) for detail.")
        else:
            body.append(f"Prose line {n}, nothing falsifiable, just words to scan.")
    text = ("# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
            + "\n".join(body) + "\n\n## 1. Ref\n")
    write(repo, "NEXT_SESSION.md", text)
    size_mb = len(text.encode("utf-8")) / 1_048_576
    print(f"      document is {size_mb:.1f} MB")
    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=30)
    report("huge-document", f"{size_mb:.1f} MB / 100k lines", verdict_for(elapsed, 30))


# ------------------------------------------------------------ 3. large history
def case_large_repository() -> None:
    print("\n[3] 5000 commits, 500 branches, 200 tags")
    repo = new_repo("stress-repo")
    shas = bulk_commits(repo, 5000)
    for n in range(500):
        sh(repo, "git", "branch", f"feature/topic-{n}", shas[n % len(shas)])
    for n in range(200):
        sh(repo, "git", "tag", f"v{n // 10}.{n % 10}", shas[n % len(shas)])
    print("      history built")
    body = ("Work continues on `feature/topic-7`.\n"
            "Work is NOT yet merged on `feature/topic-9`.\n"
            f"Merged to `main` at `{shas[100]}`.\n"
            "Released in v3.5 already.\n"
            "Released in v99.9 supposedly.\n")
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n## 1. Ref\n")
    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=15)
    report("large-repo", "5000 commits / 500 branches", verdict_for(elapsed, 15))
    if proc:
        report("large-repo", "phantom tag v99.9 still caught",
               "yes" if "v99.9" in proc.stdout else "NO - rule went blind at scale")


# --------------------------------------------------------- 4. many unique paths
def case_many_paths() -> None:
    """The adversarial case for the case-sensitivity check, which lists a
    directory per path component and caches nothing."""
    print("\n[4] 3000 distinct links across a deep directory tree")
    repo = new_repo("stress-paths")
    bulk_commits(repo, 3)
    for n in range(3000):
        write(repo, f"docs/a{n % 10}/b{n % 20}/c{n % 30}/f{n}.md", "# x\n")
    body = "\n".join(
        f"See [doc {n}](docs/a{n % 10}/b{n % 20}/c{n % 30}/f{n}.md)."
        for n in range(3000))
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n\n## 1. Ref\n")
    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=30)
    report("many-paths", "3000 existing links, deep tree", verdict_for(elapsed, 30))
    if proc:
        findings = [l for l in proc.stdout.splitlines() if l.startswith("line ")]
        report("many-paths", "false positives on real files",
               "none" if not findings else f"{len(findings)} UNEXPECTED")


# ------------------------------------------------------------- 5. huge archive
def case_huge_archive() -> None:
    print("\n[5] archive with 500 entries, validated alongside the document")
    repo = new_repo("stress-archive")
    shas = bulk_commits(repo, 5)
    entries = "".join(
        f"## Phase {n} - work (shipped, 2026-01-01)\n\n"
        f"Merged to `main` at `{shas[0]}`.\nBody line for entry {n}.\n\n"
        for n in range(500))
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 501 - now (in progress, 2026-01-01)\n\nx\n\n## 1. Ref\n")
    write(repo, "docs/handoff-archive.md", f"# Archive\n\n{entries}")
    proc, elapsed = run_timed(repo, "--verify", budget=20)
    report("huge-archive", "500 archived entries", verdict_for(elapsed, 20))


# ---------------------------------------------------------- 6. many extra docs
def case_many_extra_docs() -> None:
    print("\n[6] 50 extra documents")
    repo = new_repo("stress-extra")
    bulk_commits(repo, 3)
    names = []
    for n in range(50):
        name = f"docs/guide{n}.md"
        write(repo, name, f"# Guide {n}\n\nSee [x](missing{n}.md).\n")
        names.append(name)
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\nx\n\n## 1. Ref\n")
    listed = ", ".join(f'"{n}"' for n in names)
    write(repo, ".handoff.toml", f"extra_docs = [{listed}]\n")
    proc, elapsed = run_timed(repo, "--verify", budget=25)
    report("many-extra-docs", "50 extra documents", verdict_for(elapsed, 25))
    if proc:
        found = proc.stdout.count("dead-md-link")
        report("many-extra-docs", "all 50 broken links reported",
               "yes" if found >= 50 else f"only {found} of 50")


# ------------------------------------------------------------ 7. pathological
def case_pathological_shapes() -> None:
    print("\n[7] one very long line, and deeply nested inline code")
    repo = new_repo("stress-shapes")
    shas = bulk_commits(repo, 3)
    long_line = "word " * 200_000                       # ~1 MB single line
    ticks = "`x` " * 50_000                             # many inline spans
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
          f"{long_line}\n{ticks}\n\n## 1. Ref\n")
    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md",
                              budget=20, timeout=180)
    report("pathological", "1 MB single line + 50k inline spans",
           verdict_for(elapsed, 20))


# ----------------------------------------------------------------- 8. memory
def case_memory() -> None:
    print("\n[8] peak memory on the 100,000-line document")
    repo = ARENA / "stress-doc"
    doc = repo / "NEXT_SESSION.md"
    if not doc.is_file():
        report("memory", "peak memory", "SKIPPED (case 2 did not run)")
        return
    script = f'''
import sys, tracemalloc, pathlib
sys.path.insert(0, r"{repo / 'tools'}")
import handoff_collect as h
repo = pathlib.Path(r"{repo}")
text = pathlib.Path(r"{doc}").read_text(encoding="utf-8")
h._LINK_BASE = repo
tracemalloc.start()
h.validate(repo, text)
current, peak = tracemalloc.get_traced_memory()
doc_mb = len(text.encode("utf-8")) / 1048576
print(f"{{doc_mb:.1f}} {{peak / 1048576:.1f}}")
'''
    proc = sh(repo, PY, "-c", script, timeout=600)
    try:
        doc_mb, peak_mb = (float(x) for x in proc.stdout.split())
    except ValueError:
        report("memory", "peak memory", f"could not measure: {proc.stderr[:120]}")
        return
    ratio = peak_mb / doc_mb if doc_mb else 0
    verdict = (f"{peak_mb:.0f} MB peak for a {doc_mb:.1f} MB document "
               f"({ratio:.1f}x)")
    if ratio > 20:
        verdict += "  HIGH"
    report("memory", "peak allocation", verdict)


# ------------------------------------------------------ 9. repeated invocation
def case_repeated() -> None:
    print("\n[9] 40 back-to-back validations (hook firing repeatedly)")
    repo = new_repo("stress-repeat")
    shas = bulk_commits(repo, 20)
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
          f"Merged to `main` at `{shas[0]}`.\n\n## 1. Ref\n")
    start = time.perf_counter()
    for _ in range(40):
        sh(repo, PY, str(repo / "tools/handoff_collect.py"),
           "--repo", str(repo), "--validate", "NEXT_SESSION.md")
    elapsed = time.perf_counter() - start
    report("repeated", "40 runs", f"{elapsed:6.1f}s total, "
           f"{elapsed / 40 * 1000:.0f} ms each")


def main() -> int:
    ARENA.mkdir(parents=True, exist_ok=True)
    cases = [case_distinct_shas, case_huge_document, case_large_repository,
             case_many_paths, case_huge_archive, case_many_extra_docs,
             case_pathological_shapes, case_memory, case_repeated]
    for case in cases:
        try:
            case()
        except Exception as exc:                                # noqa: BLE001
            report(case.__name__, "case itself failed", f"RAISED {exc!r}")
            print(f"  RAISED {exc!r}")

    print("\n" + "=" * 68)
    # SKIPPED counts as flagged. A case that did not run is not a case that
    # passed, and reporting it as one is the exact conflation this project
    # exists to prevent.
    bad = [r for r in RESULTS if any(w in r[2] for w in
                                     ("OVER", "over budget", "TIMED OUT", "RAISED",
                                      "UNEXPECTED", "NO -", "HIGH", "only",
                                      "SKIPPED", "could not measure"))]
    print(f"{len(cases)} cases, {len(RESULTS)} measurements: "
          f"{len(RESULTS) - len(bad)} within expectations, {len(bad)} flagged")
    if bad:
        print("\nFLAGGED:")
        for case, measurement, verdict in bad:
            print(f"  {case:<18} {measurement:<34} {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
