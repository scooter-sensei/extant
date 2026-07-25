"""Performance measurement for handoff-validator.

Four questions, in descending order of how much they matter:

1. What does the post-commit hook add to EVERY commit? If that number is bad,
   people uninstall the tool and the other three stop mattering.
2. Does validation scale linearly with document size, or is there an n-squared
   hiding in a rule?
3. Does it scale with REPOSITORY size - commits, branches, tags?
4. Which rule actually costs the time?

Reports absolute numbers and the scaling ratio, because "1.2 seconds" means
nothing without knowing whether it becomes 12 or 120 at ten times the size.
"""
from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

PKG = Path(sys.argv[1])
ARENA = Path(sys.argv[2])
PY = sys.executable


def sh(cwd: Path, *args: str, check: bool = False):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def new_repo(name: str) -> Path:
    import shutil
    repo = ARENA / name
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    sh(repo, "git", "init", "-q", "-b", "main")
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "T")
    sh(repo, "git", "config", "commit.gpgsign", "false")
    shutil.copytree(PKG / "plugin/skills/handoff/payload", repo / "tools")
    return repo


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def timed(fn, runs: int = 3) -> float:
    """Median of `runs`, to blunt one-off noise."""
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - start)
    return statistics.median(samples)


def document(lines: int, repo: Path, real_sha: str) -> str:
    """A document of roughly `lines` lines carrying proportional claims."""
    body = []
    for n in range(lines):
        if n % 20 == 0:
            body.append(f"Merged to `main` at `{real_sha}`.")
        elif n % 20 == 5:
            body.append(f"**Design:** `tools/handoff_collect.py`")
        elif n % 20 == 10:
            body.append(f"See [tool](tools/handoff_collect.py) for detail.")
        elif n % 20 == 15:
            body.append(f"Jump to [ref](#1-reference).")
        else:
            body.append(f"Ordinary prose line {n} with no falsifiable claim in it.")
    return ("# Status\n\n## Phase 9 - perf (in progress, 2026-07-22)\n\n"
            + "\n".join(body) + "\n\n## 1. Reference\n\nReference material.\n")


# --------------------------------------------------------------- 1. hook cost
def hook_latency() -> None:
    print("\n=== 1. What the hooks add to every commit ===")
    repo = new_repo("perf-hook")
    write(repo, "NEXT_SESSION.md", document(200, repo, "0" * 40))
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "init")
    sha = sh(repo, "git", "rev-parse", "--short", "HEAD").stdout.strip()
    write(repo, "NEXT_SESSION.md", document(200, repo, sha))
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "real sha")

    def commit_once(tag: str):
        def run():
            write(repo, f"f_{tag}_{time.time_ns()}.txt", "x\n")
            sh(repo, "git", "add", "-A")
            sh(repo, "git", "commit", "-qm", f"chore: {tag}")
        return run

    bare = timed(commit_once("bare"), runs=5)
    installed = sh(repo, "sh", "tools/hooks/install")
    if installed.returncode != 0:
        print("  hook install failed:", installed.stderr[:200])
        return
    hooked = timed(commit_once("hooked"), runs=5)
    overhead = hooked - bare
    print(f"  commit without hooks : {bare*1000:7.0f} ms")
    print(f"  commit with hooks    : {hooked*1000:7.0f} ms")
    print(f"  overhead per commit  : {overhead*1000:7.0f} ms   <- paid every time")
    verdict = ("negligible" if overhead < 0.3 else
               "noticeable" if overhead < 1.0 else
               "PEOPLE WILL UNINSTALL IT")
    print(f"  verdict              : {verdict}")


# ---------------------------------------------------- 2. document size scaling
def document_scaling() -> None:
    print("\n=== 2. Scaling with DOCUMENT size ===")
    repo = new_repo("perf-doc")
    write(repo, "NEXT_SESSION.md", "# S\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "init")
    sha = sh(repo, "git", "rev-parse", "--short", "HEAD").stdout.strip()

    print(f"  {'lines':>7} {'time':>9} {'ms/line':>9}  ratio")
    previous = None
    for lines in (250, 1000, 4000, 16000):
        write(repo, "NEXT_SESSION.md", document(lines, repo, sha))
        elapsed = timed(lambda: sh(repo, PY, str(repo / "tools/handoff_collect.py"),
                                   "--repo", str(repo), "--validate", "NEXT_SESSION.md"),
                        runs=3)
        ratio = "" if previous is None else f"x{elapsed/previous:.2f} for x4 size"
        print(f"  {lines:>7} {elapsed:>8.2f}s {elapsed/lines*1000:>8.2f}  {ratio}")
        previous = elapsed
    print("  (linear would hold ms/line flat and show about x4 per step)")


# -------------------------------------------------------- 3. repo size scaling
def repo_scaling() -> None:
    print("\n=== 3. Scaling with REPOSITORY size ===")
    for commits, branches in ((50, 5), (400, 40)):
        repo = new_repo(f"perf-repo-{commits}")
        write(repo, "NEXT_SESSION.md", "# S\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "init")
        for n in range(commits):
            sh(repo, "git", "commit", "-q", "--allow-empty", "-m", f"feat: work {n}")
        for n in range(branches):
            sh(repo, "git", "branch", f"feature/topic-{n}")
        sh(repo, "git", "tag", "v1.0")
        sha = sh(repo, "git", "rev-parse", "--short", "HEAD").stdout.strip()
        body = ("Merged to `main` at `%s`.\n" % sha
                + "Work continues on `feature/topic-1`.\n" * 10
                + "Released in v1.0 already.\n"
                + "**Design:** `tools/handoff_collect.py`\n")
        write(repo, "NEXT_SESSION.md",
              f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n## 1. Ref\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "docs")
        elapsed = timed(lambda: sh(repo, PY, str(repo / "tools/handoff_collect.py"),
                                   "--repo", str(repo), "--validate", "NEXT_SESSION.md"),
                        runs=3)
        print(f"  {commits:>4} commits, {branches:>3} branches : {elapsed:6.2f}s")
    print("  (branch and tag rules query history; watch for growth here)")


# ------------------------------------------------------------ 4. per-rule cost
def per_rule() -> None:
    print("\n=== 4. Where the time actually goes (4000-line document) ===")
    repo = new_repo("perf-rules")
    write(repo, "NEXT_SESSION.md", "# S\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "init")
    for n in range(60):
        sh(repo, "git", "commit", "-q", "--allow-empty", "-m", f"feat: work {n}")
    for n in range(20):
        sh(repo, "git", "branch", f"feature/topic-{n}")
    sha = sh(repo, "git", "rev-parse", "--short", "HEAD").stdout.strip()
    write(repo, "NEXT_SESSION.md", document(4000, repo, sha))

    script = f'''
import sys, time, pathlib
sys.path.insert(0, r"{repo / 'tools'}")
import handoff_collect as h
repo = pathlib.Path(r"{repo}")
text = pathlib.Path(r"{repo / 'NEXT_SESSION.md'}").read_text(encoding="utf-8")
h._LINK_BASE = repo
rows = []
for rule in h.RULES:
    start = time.perf_counter()
    found = rule.check(repo, text)
    rows.append((rule.kind, time.perf_counter() - start, len(found)))
total = sum(r[1] for r in rows)
for kind, secs, n in sorted(rows, key=lambda r: -r[1]):
    share = 100 * secs / total if total else 0
    print(f"  {{kind:<20}} {{secs:7.3f}}s  {{share:5.1f}}%  {{n:>5}} findings")
print(f"  {{'TOTAL':<20}} {{total:7.3f}}s")
start = time.perf_counter()
h.count_examined(repo, text)
print(f"  {{'count_examined':<20}} {{time.perf_counter()-start:7.3f}}s  (denominator)")
'''
    res = sh(repo, PY, "-c", script)
    print(res.stdout.rstrip() or res.stderr[:600])


def main() -> int:
    ARENA.mkdir(parents=True, exist_ok=True)
    hook_latency()
    document_scaling()
    repo_scaling()
    per_rule()
    return 0


if __name__ == "__main__":
    sys.exit(main())
