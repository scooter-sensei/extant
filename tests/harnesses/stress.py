"""Stress and load testing: find where extant falls over.

Deliberately aimed at the WEAK points rather than at comfortable ones. The
merge-claim rule was optimised by asking git once per distinct commit, so the
adversarial case is a document where every claim names a different commit and
that deduplication buys nothing. The case-sensitivity check lists a directory
per path component, so the adversarial case is thousands of links in a deep
tree. A benchmark that avoids those is measuring the wrong thing.

The same reasoning picked the newer cases. `_target_anchors` memoises per path,
so the case that matters is two thousand links into two thousand DIFFERENT
files, where that cache buys nothing. And one `conf.py` turns a single
`--validate` into a read of every tracked file in the repository, so the shape
worth measuring is a small document in a large tree rather than a large one.

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
    shutil.copytree(PKG / "plugin/skills/extant/payload", repo / "tools")
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
    """Time a subprocess run.

    `budget` is accepted and not used here: every caller passes the same value
    to `verdict_for`, which does the judging. Kept rather than removed so the
    call site reads as one measurement against one budget, and documented
    rather than left to look like a bug.
    """
    start = time.perf_counter()
    try:
        proc = sh(repo, PY, str(repo / "tools/extant_collect.py"),
                  "--repo", str(repo), *args, timeout=timeout)
    except subprocess.TimeoutExpired:
        # None, not `timeout`. Returning the budget made a run that was
        # KILLED at the limit print the same elapsed time as one that
        # finished exactly at it, and `verdict_for` already has a branch
        # for None that says TIMED OUT.
        return None, None
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
            body.append("See [tool](tools/extant_collect.py) for detail.")
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
        # The "no such tag" half of this rule is opt-in, and this fixture
        # writes no config, so silence here means the DEFAULT rather than any
        # failure of scale. The old wording blamed 5000 commits for a
        # configuration answer, which is a gotcha with the wrong cause -
        # worse than none, because it gets believed.
        write(repo, ".extant.toml",
              "[extant]\nrelease_claims_name_our_tags = true\n")
        proc, _ = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=15)
        report("large-repo", "phantom tag v99.9 still caught",
               "yes" if proc and "v99.9" in proc.stdout
               else "NO - the rule went blind at 5000 commits")


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
    write(repo, "docs/status-archive.md", f"# Archive\n\n{entries}")
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
    write(repo, ".extant.toml", f"extra_docs = [{listed}]\n")
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
import extant_collect as h
repo = pathlib.Path(r"{repo}")
text = pathlib.Path(r"{doc}").read_text(encoding="utf-8")
h._set_document(link_base=repo)
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
        sh(repo, PY, str(repo / "tools/extant_collect.py"),
           "--repo", str(repo), "--validate", "NEXT_SESSION.md")
    elapsed = time.perf_counter() - start
    report("repeated", "40 runs", f"{elapsed:6.1f}s total, "
           f"{elapsed / 40 * 1000:.0f} ms each")


# ------------------------------------------------- new surfaces (0.4.0)
def case_search_large_archive() -> None:
    """Search reads BOTH documents fully and splits them into entries."""
    print("\n[10] --search across a 2000-entry archive")
    repo = new_repo("stress-search")
    bulk_commits(repo, 3)
    entries = "".join(
        f"## Phase {n} - work {n} (shipped, 2026-01-01)\n\n"
        f"Body for entry {n}. Some prose about decisions taken.\n"
        f"{'The checkout rewrite happened here.' if n == 1500 else ''}\n\n"
        for n in range(2000))
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 2001 - now (in progress, 2026-01-01)\n\nx\n\n## 1. Ref\n")
    write(repo, "docs/status-archive.md", f"# Archive\n\n{entries}")
    proc, elapsed = run_timed(repo, "--search", "checkout rewrite", budget=20)
    report("search", "2000-entry archive", verdict_for(elapsed, 20))
    if proc:
        report("search", "found the one matching entry",
               "yes" if "Phase 1500" in proc.stdout else "NO - missed it at scale")


def case_consistency_many_files() -> None:
    """The consistency rule opens and scans every configured file."""
    print("\n[11] 200 files in one consistency check")
    repo = new_repo("stress-consistency")
    bulk_commits(repo, 3)
    lines = ["[extant.consistency.version]"]
    for n in range(200):
        write(repo, f"pkg/mod{n}/meta.json", '{"version": "1.2.3"}\n')
        lines.append(f'"pkg/mod{n}/meta.json" = ' + "'" + r'"version": "([^"]+)"' + "'")
    write(repo, ".extant.toml", "\n".join(lines) + "\n")
    write(repo, "NEXT_SESSION.md", "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\nx\n\n## 1. Ref\n")
    proc, elapsed = run_timed(repo, "--verify", budget=20)
    report("consistency", "200 files agreeing", verdict_for(elapsed, 20))
    if proc:
        # Matched against FINDING lines, not against stdout as a whole. The
        # rule's name appears in the denominator summary on every clean run
        # too, so searching the raw output reported a false positive about
        # false positives - the check was wrong in exactly the way it was
        # written to detect.
        findings = [ln for ln in proc.stdout.splitlines() if ln.startswith("line ")]
        report("consistency", "no false positives across 200 files",
               "none" if not findings else f"UNEXPECTED: {findings[0][:80]}")
    # Now make exactly one disagree, and confirm it is still found at scale.
    write(repo, "pkg/mod137/meta.json", '{"version": "9.9.9"}\n')
    proc, elapsed = run_timed(repo, "--verify", budget=20)
    if proc:
        report("consistency", "the one odd file out of 200 is named",
               "yes" if "mod137" in proc.stdout else "NO - lost at scale")


def case_suggest_fixes_many_renames() -> None:
    """A patch spanning hundreds of renamed references must still apply."""
    print("\n[12] 500 renamed references in one document")
    repo = new_repo("stress-fixes")
    for n in range(500):
        write(repo, f"docs/old{n}.md", f"# doc {n}\n")
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
          + "\n".join(f"See [doc {n}](docs/old{n}.md)." for n in range(500))
          + "\n\n## 1. Ref\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "init")
    for n in range(500):
        sh(repo, "git", "mv", f"docs/old{n}.md", f"docs/new{n}.md")
    sh(repo, "git", "commit", "-qm", "rename all")
    proc, elapsed = run_timed(repo, "--verify", "--suggest-fixes", budget=60)
    report("suggest-fixes", "500 renamed references", verdict_for(elapsed, 60))
    if proc and proc.stdout.strip():
        (repo / "big.patch").write_bytes(proc.stdout.encode("utf-8"))
        applied = sh(repo, "git", "apply", "big.patch")
        report("suggest-fixes", "the 500-change patch applies",
               "yes" if applied.returncode == 0
               else f"NO - {applied.stderr.strip()[:80]}")
    else:
        report("suggest-fixes", "a patch was produced at all", "NO - empty")


# ------------------------------------------------------- 13. a large baseline
def case_huge_baseline() -> None:
    """The baseline exists FOR big neglected repositories, so the scale that
    matters is the one it was built for.

    It is read on every run, including the post-commit hook, and every finding
    is fingerprinted against it. A baseline that made the tool slow would be
    slowest exactly where it is most needed, which is the shape of failure
    worth measuring rather than assuming.
    """
    print("\n[13] a 5000-entry baseline, read on every run")
    repo = new_repo("stress-baseline")
    shas = bulk_commits(repo, 3)
    # A LETTER is required for a token to be read as a SHA - an all-digit run
    # is a number, which is why INT64_MAX is not a commit. This fixture used
    # `{n:040d}`, so every one of the 5000 was skipped and the case recorded a
    # 0-entry baseline while its own label said 5000. It measured the cost of
    # reading an empty file, and reported it as the cost of reading a big one.
    body = "\n".join(f"Ref {n} at `a{n:039d}`." for n in range(5000))
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n\n## 1. Ref\n")

    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md",
                              "--write-baseline", budget=30)
    report("huge-baseline", "recording 5000 findings", verdict_for(elapsed, 30))
    path = repo / ".extant-baseline.json"
    if not path.is_file():
        report("huge-baseline", "the baseline was written", "NO - absent")
        return
    size_mb = path.stat().st_size / 1_048_576
    entries = path.read_text(encoding="utf-8").count('"fingerprint"')
    report("huge-baseline", f"{entries} entries, {size_mb:.1f} MB",
           "ok" if entries >= 4900 else f"only {entries} recorded")

    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md",
                              "--baseline", budget=20)
    report("huge-baseline", "validating against it", verdict_for(elapsed, 20))
    if proc:
        report("huge-baseline", "everything recorded is suppressed",
               "yes" if proc.returncode == 0
               else f"NO - exit {proc.returncode}")

    # One NEW claim among 5000 forgiven ones must still surface. A ratchet that
    # loses the new finding at scale is worse than no ratchet, because the
    # project believes it is covered.
    text = (repo / "NEXT_SESSION.md").read_text(encoding="utf-8")
    write(repo, "NEXT_SESSION.md",
          text.replace("## 1. Ref", "Added today: `abcdefabcdefabcdefabcdef1234567890abcdef`.\n\n## 1. Ref"))
    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md",
                              "--baseline", budget=20)
    if proc:
        found = "abcdefabcdef" in proc.stdout and proc.returncode == 1
        report("huge-baseline", "one new claim among 5000 forgiven",
               "still reported" if found else "NO - lost in the baseline")

    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md",
                              "--baseline", "--baseline-check", budget=25)
    report("huge-baseline", "--baseline-check over 5000 entries",
           verdict_for(elapsed, 25))


# ------------------------------------------------------ 14. large SARIF output
def case_huge_sarif() -> None:
    """SARIF is what a CI upload consumes, so its SIZE is a real limit.

    GitHub rejects a SARIF file over 10 MB, and the failure arrives as a red
    upload step long after the run that produced it. Serialising thousands of
    findings is also the one path where the whole result set is held in memory
    as objects and again as JSON.
    """
    print("\n[14] SARIF and GitHub output for 5000 findings")
    repo = new_repo("stress-sarif")
    bulk_commits(repo, 3)
    body = "\n".join(f"See [doc {n}](docs/missing-{n}.md)." for n in range(5000))
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n\n## 1. Ref\n")

    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md",
                              "--format=sarif", budget=40)
    report("huge-sarif", "serialising 5000 findings", verdict_for(elapsed, 40))
    if not proc:
        return
    size_mb = len(proc.stdout.encode("utf-8")) / 1_048_576
    report("huge-sarif", f"SARIF payload {size_mb:.1f} MB",
           "ok (under the 10 MB upload limit)" if size_mb < 10
           else f"HIGH - {size_mb:.1f} MB exceeds GitHub's 10 MB limit")
    import json as _json
    try:
        results = _json.loads(proc.stdout)["runs"][0]["results"]
        report("huge-sarif", f"{len(results)} results parsed back",
               "ok" if len(results) >= 4900 else f"only {len(results)}")
    except (ValueError, KeyError, IndexError) as exc:
        report("huge-sarif", "the payload parses as JSON", f"NO - {exc}")

    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md",
                              "--format=github", budget=40)
    report("huge-sarif", "5000 GitHub annotations", verdict_for(elapsed, 40))
    if proc:
        annotations = sum(1 for ln in proc.stdout.splitlines()
                          if ln.startswith("::"))
        report("huge-sarif", f"{annotations} annotation lines",
               "ok" if annotations >= 4900 else f"only {annotations}")


# -------------------------------------------------------- 15. many pinned refs
def case_many_pinned_refs() -> None:
    """A README documenting many install routes.

    This rule reads INSIDE code fences, which the others skip, so a page dense
    with install snippets is its worst case and nothing else here exercises
    it. Each pin governed by this repository costs a `rev-parse`.
    """
    print("\n[15] 500 install snippets pinning this repository")
    repo = new_repo("stress-pins")
    bulk_commits(repo, 3)
    sh(repo, "git", "remote", "add", "origin",
       "https://github.com/example/extant.git")
    blocks = []
    for n in range(500):
        blocks.append(
            "```yaml\nrepos:\n  - repo: https://github.com/example/extant\n"
            f"    rev: v0.{n}.0\n    hooks:\n      - id: extant\n```\n")
    write(repo, "README.md", "# P\n\n" + "\n".join(blocks))
    write(repo, ".extant.toml", 'primary_doc = "README.md"\n')
    proc, elapsed = run_timed(repo, "--validate", "README.md", budget=45)
    report("many-pins", "500 pins, none resolving", verdict_for(elapsed, 45))
    if proc:
        fired = [ln for ln in proc.stdout.splitlines()
                 if ln.startswith("line ") and "[dead-pinned-ref]" in ln]
        report("many-pins", f"{len(fired)} dead pins reported",
               "ok" if len(fired) >= 450 else f"only {len(fired)} of 500")


# --------------------------------------------------------- 16. the whole sweep
def _finding_lines(stdout: str) -> list[str]:
    """Finding lines only, never the denominator.

    A sweep prints `path.md: line N: [kind] ...` for anything outside the
    primary document and `line N: [kind] ...` inside it, while the summary
    names rules too. Counting occurrences of a rule name in raw stdout is how
    an assertion ends up reading the denominator and calling it a finding,
    which this harness has already done once.
    """
    import re
    return [ln for ln in stdout.splitlines()
            if re.search(r"(^|: )line \d+: \[", ln)]


def case_sweep_whole_repo() -> None:
    """`--sweep`'s unit of work is the REPOSITORY, not a document.

    Every other case here validates one file. This is the mode where cost is
    the number of files, and it is the one a newcomer points at the largest
    repository they own before they have configured anything.
    """
    print("\n[16] --sweep over 3000 tracked markdown files")
    repo = new_repo("stress-sweep")
    for n in range(3000):
        write(repo, f"docs/s{n % 30}/page{n}.md",
              f"# Page {n}\n\n## Detail {n}\n\nJump to [d](#detail-{n}).\n")
    # One planted fault in a CONFIGURED document, so the exit code has
    # something to gate on and the run proves it still gates at this size.
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
          "See [gone](docs/no-such-file.md).\n\n## 1. Ref\n")
    write(repo, ".extant.toml", 'primary_doc = "NEXT_SESSION.md"\n')
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "corpus")

    # Budget from measurement, not from taste: 32.7s on Windows, 2026-07-29,
    # after the per-document work was hoisted out of the loop. It was 134s
    # before that, and the budget was 180s - which is the trap a stale budget
    # sets. Nothing failed, nothing could have, and a 4x regression would have
    # fitted inside it unnoticed. Re-measure a budget when the thing it watches
    # gets faster, not only when it gets slower.
    #
    # Set above the observed number rather than at it, because a budget met
    # only on a quiet machine gets rerun on red, then ignored, then deleted.
    proc, elapsed = run_timed(repo, "--sweep", budget=60, timeout=600)
    report("sweep", "3000 files surveyed", verdict_for(elapsed, 60))
    if not proc:
        return
    # The denominator is the whole point of the mode. A wrong glob or an index
    # read would report a clean repository, and the timing above would look
    # BETTER for it - which is why this assertion sits next to the measurement
    # rather than in the unit suite alone.
    report("sweep", "the denominator names 3001 files",
           "yes" if "swept 3001 markdown file(s)" in proc.stdout
           else f"NO - {[l for l in proc.stdout.splitlines() if 'swept' in l][:1]}")
    report("sweep", "the planted fault still gates",
           "yes" if proc.returncode == 1 else f"NO - exit {proc.returncode}")


# ------------------------------------------- 17. the eager project-wide union
def case_global_anchor_union() -> None:
    """The project-wide anchor union, at the size that makes it expensive.

    When a repository declares a generator whose namespace is the project,
    resolving one fragment can require reading every tracked markdown file.
    That is correct - MyST and Sphinx resolve labels project-wide - and it is
    the only place where validating ONE small document costs the whole
    repository.

    The document here links to a fragment defined in ANOTHER file, which is
    what forces the union to be built. That detail is the case: the union
    became lazy, so a document whose fragments resolve locally no longer
    touches it at all, and the earlier version of this case - which linked to
    a heading in its own body - would now measure a code path it never
    reaches. A load test aimed at a branch that is no longer taken reports a
    comfortable number and exercises nothing.

    Sphinx projects all carry a `conf.py`, so this remains an ordinary shape
    rather than an adversarial one.
    """
    print("\n[17] a cross-file fragment, 3000 files, and a conf.py")
    repo = new_repo("stress-union")
    for n in range(3000):
        write(repo, f"docs/s{n % 30}/page{n}.md", f"# Page {n}\n\n## Detail {n}\n")
    # `## Detail 42` lives in one of those files, not in this one.
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
          "Jump to [r](#detail-42).\n\n## 1. Ref\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "corpus")
    proc, plain = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=15)
    report("global-union", "no generator declared", verdict_for(plain, 15))
    # Without a generator the namespace is the page, so this fragment is dead.
    # Asserted because it is what proves the two runs differ in KIND and not
    # only in duration.
    # Matched against FINDING lines, never against stdout as a whole. The
    # denominator names every rule on every run, so `"dead-md-anchor" in
    # stdout` is true whether the rule fired or not - it reported this union
    # as broken while the tool was resolving the anchor correctly. That is the
    # same defect `_finding_lines` was added to prevent, made three times in
    # the case that has the helper sitting directly above it.
    if proc:
        report("global-union", "per-page namespace calls it dead",
               "yes" if _finding_lines(proc.stdout) else "NO - forgiven anyway")

    write(repo, "conf.py", "project = 'x'\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "sphinx")
    # Measured 29.2s on Windows, 2026-07-29, so the budget is 60s.
    #
    # perf.py measures the same effect in the low hundreds of milliseconds for
    # 1600 files, and the two do NOT contradict each other: this is a single COLD run over files that
    # were written moments ago, and perf takes the median of three, so its
    # second and third runs read a warm cache. On Windows, with a scanner in
    # front of 3000 new files, that gap is most of the difference.
    #
    # This case barely moved when the rest of the sweep got four times faster,
    # which is the expected shape rather than a disappointment: the union reads
    # every tracked file, so it is bound by cold I/O and not by the per-document
    # work that was hoisted out.
    #
    # Both numbers are worth having, and this is the one shaped like a hook:
    # a post-commit run happens once and pays whatever the cache does not.
    proc, sphinx = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=60)
    report("global-union", "the same document, with conf.py",
           verdict_for(sphinx, 60))
    if plain and sphinx:
        report("global-union", "cost of the union",
               f"{(sphinx - plain):+6.1f}s for 3000 files")
    if proc:
        report("global-union", "project namespace resolves it",
               "yes" if not _finding_lines(proc.stdout)
               else "NO - the union did not reach the other file")
    # The union must not swallow a real finding. A project-wide namespace that
    # forgives everything is the same failure as a baseline that does.
    if proc:
        text = (repo / "NEXT_SESSION.md").read_text(encoding="utf-8")
        write(repo, "NEXT_SESSION.md",
              text.replace("[r](#detail-42)", "[r](#no-such-anchor-anywhere)"))
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "dead anchor")
        proc, _ = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=60)
        report("global-union", "a genuinely dead anchor still reported",
               "yes" if proc and _finding_lines(proc.stdout)
               else "NO - the union forgave it")


# ----------------------------------------- 18. cross-file anchors, uncached
def case_distinct_cross_file_anchors() -> None:
    """The adversarial case for the cross-file anchor cache.

    `_target_anchors` memoises per PATH, so a document linking into the same
    file repeatedly costs one read. A document linking into two thousand
    DIFFERENT files gets nothing from that cache and opens two thousand files -
    the same shape as the distinct-SHA case for merge claims, and the reason
    that one is in this harness.
    """
    print("\n[18] 2000 anchor links into 2000 DISTINCT files")
    repo = new_repo("stress-xfile")
    bulk_commits(repo, 3)
    for n in range(2000):
        write(repo, f"docs/t{n}.md", f"# Target {n}\n\n## Section {n}\n\nx\n")
    body = "\n".join(f"See [t {n}](docs/t{n}.md#section-{n})." for n in range(2000))
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n\n## 1. Ref\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "targets")
    proc, elapsed = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=45)
    report("cross-file-anchors", "2000 distinct target files",
           verdict_for(elapsed, 45))
    if proc:
        report("cross-file-anchors", "false positives on live anchors",
               "none" if not _finding_lines(proc.stdout)
               else f"{len(_finding_lines(proc.stdout))} UNEXPECTED")
        # And one that is genuinely dead, so the rule is shown to be awake.
        text = (repo / "NEXT_SESSION.md").read_text(encoding="utf-8")
        write(repo, "NEXT_SESSION.md",
              text.replace("docs/t1500.md#section-1500", "docs/t1500.md#gone"))
        proc, _ = run_timed(repo, "--validate", "NEXT_SESSION.md", budget=45)
        report("cross-file-anchors", "the one dead anchor among 2000 is found",
               "yes" if proc and "#gone" in proc.stdout else "NO - lost at scale")


# ------------------------------------------------------- 19. a large rst tree
def case_rst_corpus() -> None:
    """reStructuredText at scale, where the markdown rules must stay silent.

    Reading `.rst` as markdown does not degrade, it invents: 23 of numpy's
    findings and all ten of Sphinx's came from exactly that, every one false.
    numpy carries 555 rst files, so this is the ordinary size of the case
    rather than an extreme of it.
    """
    print("\n[19] 2000 reStructuredText files in a sweep")
    repo = new_repo("stress-rst")
    for n in range(2000):
        # Constructs markdown would misread: rst hyperlinks and inline
        # literals, whose punctuation overlaps markdown's link syntax.
        write(repo, f"docs/p{n}.rst",
              f"Page {n}\n{'=' * (5 + len(str(n)))}\n\n"
              f"See `the guide <https://example.com/{n}>`_ and ``[x](y.md)``.\n\n"
              f".. _label-{n}:\n\nSection {n}\n{'-' * (8 + len(str(n)))}\n\nBody.\n")
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\nx\n\n## 1. Ref\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "rst corpus")
    # Measured 22.3s on Windows, 2026-07-29 (93.6s before the per-document
    # work was hoisted out of the sweep loop).
    proc, elapsed = run_timed(repo, "--sweep", budget=45, timeout=600)
    report("rst", "2000 rst files swept", verdict_for(elapsed, 45))
    if not proc:
        return
    report("rst", "all 2001 files counted",
           "yes" if "swept 2001 markdown file(s)" in proc.stdout
           else "NO - rst files were not swept")
    # The literal `[x](y.md)` above is a markdown link inside an rst literal.
    # If the markdown rules ran, every one of these files reports a dead link.
    report("rst", "markdown link rules stayed out of rst",
           "yes" if not _finding_lines(proc.stdout)
           else f"{len(_finding_lines(proc.stdout))} findings - rst read as markdown")


# ------------------------------------------- 20. a deletion scan over history
def case_deleted_since_large_archive() -> None:
    """`--deleted-since` re-validates the PREVIOUS version of every changed
    document, so its worst case is a large document that changed.

    A 2000-entry archive is the shape that exists in practice: a project that
    has been running this for years and archives on every phase. One claim is
    removed from it, and the scan must still find that one - a mode that loses
    the finding at scale is worse than no mode, because the project believes it
    is covered.
    """
    print("\n[20] --deleted-since across a 2000-entry archive")
    repo = new_repo("stress-deleted")
    shas = bulk_commits(repo, 5)
    dead = "dead" + "0" * 36
    entries = "".join(
        f"## Phase {n} - work (shipped, 2026-01-01)\n\n"
        f"Merged to `main` at `{shas[0]}`.\nBody line for entry {n}.\n\n"
        for n in range(2000))
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 2001 - now (in progress, 2026-01-01)\n\n"
          f"Merged at `{dead}`.\n\n## 1. Ref\n")
    write(repo, "docs/status-archive.md", f"# Archive\n\n{entries}")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "docs: a large archive and one dead claim")

    # Remove the one false claim, leaving the archive untouched.
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 2001 - now (in progress, 2026-01-01)\n\n"
          "Cleaned up.\n\n## 1. Ref\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "docs: remove it")

    proc, elapsed = run_timed(repo, "--deleted-since", "HEAD~1", budget=60,
                              timeout=600)
    report("deleted-since", "2000-entry archive, one claim removed",
           verdict_for(elapsed, 60))
    if not proc:
        return
    combined = proc.stdout + proc.stderr
    report("deleted-since", "the removed claim is still found at scale",
           "yes" if dead in combined else "NO - lost among 2000 entries")
    # The archive did not change, so it must not be re-read. That is the
    # difference between scanning a commit and scanning a repository.
    report("deleted-since", "the unchanged archive was skipped",
           "yes" if "examined 1 changed document" in combined
           else f"NO - {[l for l in combined.splitlines() if 'examined' in l][:1]}")
    report("deleted-since", "it never gates",
           "yes" if proc.returncode == 0 else f"NO - exit {proc.returncode}")


def main() -> int:
    ARENA.mkdir(parents=True, exist_ok=True)
    cases = [case_distinct_shas, case_huge_document, case_large_repository,
             case_many_paths, case_huge_archive, case_many_extra_docs,
             case_pathological_shapes, case_memory, case_repeated,
             case_search_large_archive, case_consistency_many_files,
             case_suggest_fixes_many_renames, case_huge_baseline,
             case_huge_sarif, case_many_pinned_refs,
             case_sweep_whole_repo, case_global_anchor_union,
             case_distinct_cross_file_anchors, case_rst_corpus,
             case_deleted_since_large_archive]
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
