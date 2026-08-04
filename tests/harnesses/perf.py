"""Performance measurement for extant.

The questions below, in descending order of how much they matter. No count
here: the list grows and a number in prose does not.

1. What does the post-commit hook add to EVERY commit? If that number is bad,
   people uninstall the tool and the other three stop mattering.
2. Does validation scale linearly with document size, or is there an n-squared
   hiding in a rule?
3. Does it scale with REPOSITORY size - commits, branches, tags?
4. Which rule actually costs the time?
5. What does a baseline cost on every run, where it is most needed?
6. What does each output format cost?
7. What does `--sweep` cost, whose unit of work is the repository?
8. What does one generator config file cost a single `--validate`?
9. What does `--deleted-since` add, against a plain `--verify`?
10. What does a document full of CLAIMS cost, as opposed to one full of links?

Reports absolute numbers and the scaling ratio, because "1.2 seconds" means
nothing without knowing whether it becomes 12 or 120 at ten times the size.

The last two were added after the anchor work, and the second of them is the
reason to re-run this after any change to a rule's INPUTS rather than only to
its logic. Every repository built here had been generator-free, so the eager
project-wide anchor union - reached by one `conf.py` existing - was invisible
to a harness whose whole job is finding costs like it. Eagerly it cost about
400 ms per run at 1600 files, paid by a post-commit hook, and measuring it is
what got it fixed: the union is built on demand now, and section 8 measures all three
paths so that the remaining cost is visible rather than declared absent.
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
    shutil.copytree(PKG / "plugin/skills/extant/payload", repo / "tools")
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
            body.append(f"**Design:** `tools/extant_collect.py`")
        elif n % 20 == 10:
            body.append(f"See [tool](tools/extant_collect.py) for detail.")
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
        elapsed = timed(lambda: sh(repo, PY, str(repo / "tools/extant_collect.py"),
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
                + "**Design:** `tools/extant_collect.py`\n")
        write(repo, "NEXT_SESSION.md",
              f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n## 1. Ref\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "docs")
        elapsed = timed(lambda: sh(repo, PY, str(repo / "tools/extant_collect.py"),
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
import extant_collect as h
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
print(f"  {{'TOTAL':<20}} {{total:7.3f}}s   over {{len(rows)}} rules")
# Findings, not work: a rule can examine two hundred claims and
# correctly report none. This line said "unexercised", which was wrong
# in exactly the way the project warns about - conflating "found
# nothing" with "did nothing". The denominator is what separates them,
# and --verify prints that.
quiet = [kind for kind, _, n in rows if n == 0]
if quiet:
    print(f"  produced no findings ({{len(quiet)}}/{{len(rows)}}), which is not the same as")
    print(f"  having examined nothing - run --verify for the denominator")
start = time.perf_counter()
h.count_examined(repo, text)
print(f"  {{'count_examined':<20}} {{time.perf_counter()-start:7.3f}}s  (denominator)")
'''
    res = sh(repo, PY, "-c", script)
    print(res.stdout.rstrip() or res.stderr[:600])


# ------------------------------------------------------- 5. the baseline's cost
def baseline_cost() -> None:
    """What suppression adds to a run that pays it on every commit.

    A baseline is adopted by big neglected repositories, which are exactly the
    ones where a slow hook gets uninstalled. Reading and fingerprinting cannot
    be free, so the question is whether it is close enough to free to leave
    switched on.
    """
    print("\n=== 5. What a baseline costs per run ===")
    repo = new_repo("perf-baseline")
    write(repo, "NEXT_SESSION.md", "# S\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "init")
    body = "\n".join(f"Ref {n} at `{n:040d}`." for n in range(1000))
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n\n## 1. Ref\n")

    def validate(*extra: str):
        def run():
            sh(repo, PY, str(repo / "tools/extant_collect.py"), "--repo",
               str(repo), "--validate", "NEXT_SESSION.md", *extra)
        return run

    plain = timed(validate(), runs=3)
    sh(repo, PY, str(repo / "tools/extant_collect.py"), "--repo", str(repo),
       "--validate", "NEXT_SESSION.md", "--write-baseline")
    recorded = (repo / ".extant-baseline.json")
    entries = recorded.read_text(encoding="utf-8").count('"fingerprint"') \
        if recorded.is_file() else 0
    suppressed = timed(validate("--baseline"), runs=3)
    print(f"  1000 findings, no baseline : {plain*1000:7.0f} ms")
    print(f"  same, {entries:>4} suppressed     : {suppressed*1000:7.0f} ms")
    delta = suppressed - plain
    print(f"  cost of suppression        : {delta*1000:+7.0f} ms")
    if entries == 0:
        print("  verdict                    : NOT MEASURED - no baseline written")
    else:
        print("  verdict                    : "
              + ("negligible" if abs(delta) < 0.1 else
                 "noticeable" if abs(delta) < 0.5 else "SIGNIFICANT"))


# ------------------------------------------------------ 6. output format cost
def format_cost() -> None:
    """Formatting is pure CPU on the way out, and SARIF builds a whole object
    graph the text path never constructs."""
    print("\n=== 6. What each output format costs (1000 findings) ===")
    repo = new_repo("perf-format")
    write(repo, "NEXT_SESSION.md", "# S\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "init")
    body = "\n".join(f"See [d {n}](docs/gone-{n}.md)." for n in range(1000))
    write(repo, "NEXT_SESSION.md",
          f"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{body}\n\n## 1. Ref\n")
    for fmt in ("text", "github", "sarif"):
        elapsed = timed(lambda f=fmt: sh(
            repo, PY, str(repo / "tools/extant_collect.py"), "--repo",
            str(repo), "--validate", "NEXT_SESSION.md", f"--format={f}"), runs=3)
        out = sh(repo, PY, str(repo / "tools/extant_collect.py"), "--repo",
                 str(repo), "--validate", "NEXT_SESSION.md", f"--format={fmt}")
        kb = len(out.stdout.encode("utf-8")) / 1024
        print(f"  {fmt:<8} {elapsed:6.2f}s   {kb:8.0f} KB on stdout")


# ------------------------------------------------------------- 7. the sweep
def corpus_repo(name: str, files: int) -> Path:
    """A repository of `files` committed markdown documents."""
    repo = new_repo(name)
    for n in range(files):
        write(repo, f"docs/section{n % 20}/page{n}.md",
              f"# Page {n}\n\n## Detail {n}\n\nSee [next](page{n + 1}.md).\n"
              f"Jump to [detail](#detail-{n}).\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "corpus")
    return repo


def sweep_scaling() -> None:
    """`--sweep` reads every tracked markdown file, so its cost scales with the
    REPOSITORY rather than with one document.

    This is the mode a newcomer runs first, on the biggest repository they have,
    with no configuration and no patience - and it is the only mode whose cost
    nobody here had measured. It shipped in 0.13.0, and the harness that exists
    to ask "is this fast enough to leave installed" predates it by a week.
    """
    print("\n=== 7. Scaling of --sweep with REPOSITORY size ===")
    print(f"  {'files':>7} {'time':>9} {'ms/file':>9}  ratio")
    previous = None
    for files in (100, 400, 1600):
        repo = corpus_repo(f"perf-sweep-{files}", files)
        elapsed = timed(lambda: sh(repo, PY, str(repo / "tools/extant_collect.py"),
                                   "--repo", str(repo), "--sweep"), runs=3)
        ratio = "" if previous is None else f"x{elapsed/previous:.2f} for x4 files"
        print(f"  {files:>7} {elapsed:>8.2f}s {elapsed/files*1000:>8.1f}  {ratio}")
        previous = elapsed
    # A sweep is not a hook, so slow here is a worse first impression rather
    # than a reason to uninstall. Stated because the budget differs from every
    # other section's and a reader should not carry the hook's over.
    print("  (a survey run by hand, not per commit - seconds are affordable here)")


# --------------------------------------------- 8. what one config file costs
def generator_cliff() -> None:
    """What a single `conf.py` costs a repository validating ONE document.

    `validate_md_anchors` asks `_has_global_anchors` before it examines a single
    link, and on a hit unions in every anchor from every tracked markdown file.
    The union is CORRECT - MyST and Sphinx resolve labels project-wide, so the
    page is the wrong namespace and 168 of mystmd's findings proved it - but it
    is built eagerly, for a document that may contain no anchor links at all.

    The trigger is one file existing. `conf.py` is Sphinx's, which makes this
    the ordinary case across a large slice of Python projects rather than an
    exotic one, and it was paid on every post-commit hook run. Nothing else in
    this harness could see it: every other repository built here has no
    generator config, so every other number on the page is the cheap path.

    The union is now built ON DEMAND, so the three columns measure different
    things and all three are worth having:

      plain    - no generator, nothing ambient to consult
      local    - a generator, and a fragment the document defines itself
      ambient  - a generator, and a fragment that lives in ANOTHER file

    Only the third can force the union to be built, because only there can the
    answer change a finding. The middle column is what most documents actually
    do, and it is where the eager version spent roughly 400 ms at 1600 files
    for nothing. Reporting only that column would replace one misleading number
    with another, so the cost that remains is measured beside it.
    """
    print("\n=== 8. What one generator config costs a single --validate ===")
    print(f"  {'files':>7} {'plain':>9} {'local':>9} {'ambient':>9}   "
          f"{'local-cost':>10} {'ambient-cost':>12}")
    for files in (100, 400, 1600):
        repo = corpus_repo(f"perf-cliff-{files}", files)
        # A SMALL document either way. The point is that the cost does not come
        # from what is being validated.
        local_doc = ("# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
                     "Jump to [detail](#1-ref).\n\n## 1. Ref\n\nx\n")
        # `## Detail 42` lives in docs/section2/page42.md, so resolving this
        # one REQUIRES the project-wide union.
        ambient_doc = ("# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
                       "Jump to [detail](#detail-42).\n\n## 1. Ref\n\nx\n")
        write(repo, "NEXT_SESSION.md", local_doc)
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "doc")

        def validate():
            sh(repo, PY, str(repo / "tools/extant_collect.py"), "--repo",
               str(repo), "--validate", "NEXT_SESSION.md")

        plain = timed(validate, runs=3)
        write(repo, "conf.py", "project = 'x'\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "sphinx")
        local = timed(validate, runs=3)
        write(repo, "NEXT_SESSION.md", ambient_doc)
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "cross-file fragment")
        ambient = timed(validate, runs=3)
        print(f"  {files:>7} {plain:>8.2f}s {local:>8.2f}s {ambient:>8.2f}s   "
              f"{(local - plain) * 1000:>+9.0f} ms {(ambient - plain) * 1000:>+11.0f} ms")
    print("  (only the ambient column can force the union to be built)")


# ------------------------------------------------ 10. a document full of CLAIMS
def claim_scaling() -> None:
    """The section that would have caught an 11.6-second rule.

    Every other document this harness builds carries almost no release claim,
    so section 4 reported `dead-release-tag` at 8 ms and 2.6% of a run that
    never exercised it. A purpose-built document with 200 of them took 11.6
    seconds, because `_integration_refs` spawned a `for-each-ref` per claim -
    in the SHIPPED tool, measured at the same 11.6 seconds against the previous
    release, rather than in the change that found it.

    ms/claim is the column that matters and the reason this is not just
    another total. A git call reached from inside a per-claim loop holds it
    FLAT while the count grows; hoisting the call out makes it fall. A total
    alone shows a big number and cannot say which.

    This is the third time a cost was invisible here for want of the right
    fixture - the anchor union was the first, `--deleted-since` the second -
    and each time the harness measured the inputs it knew how to build.
    """
    print("\n=== 10. Scaling with the number of CLAIMS in a document ===")
    repo = new_repo("perf-claims")
    write(repo, "NEXT_SESSION.md", "# S\n")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "init")
    for n in range(30):
        sh(repo, "git", "tag", f"v1.{n}.0")

    print(f"   {'claims':>8} {'time':>9} {'ms/claim':>10}  ratio")
    previous = None
    for claims in (25, 100, 400):
        body = ["# Status\n", "\n## Phase 1 - x (complete, 2026-01-01)\n\n"]
        body += [f"- The fix was released in v1.{n % 30}.0 that week.\n"
                 for n in range(claims)]
        write(repo, "NEXT_SESSION.md", "".join(body))
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", f"docs: {claims} claims")
        seconds = timed(lambda: sh(repo, PY,
                                   str(repo / "tools" / "extant_collect.py"),
                                   "--verify", "--repo", str(repo)))
        ratio = f"x{seconds / previous:.2f} for x4 claims" if previous else ""
        print(f"   {claims:>8} {seconds:8.2f}s {seconds / claims * 1000:9.1f}"
              f"   {ratio}")
        previous = seconds
    print("   (a flat ms/claim means a git call per claim; it should FALL)")


# -------------------------------------------------- 9. what a deletion scan costs
def deleted_since_cost() -> None:
    """`--deleted-since` re-validates the PREVIOUS version of each document.

    That is the one mode whose work scales with how much a commit changed, and
    the reason it only re-reads documents that actually differ: an unchanged
    document cannot have lost a claim, so skipping it is a correctness
    simplification as much as a saving.

    Measured beside a plain `--verify` so the cost of adopting it in a hook is
    legible rather than assumed.
    """
    print("\n=== 9. What --deleted-since costs, against --verify ===")
    print(f"  {'changed docs':>13} {'verify':>9} {'deleted-since':>15} {'delta':>9}")
    for changed in (1, 10, 50):
        repo = new_repo(f"perf-deleted-{changed}")
        names = [f"docs/note{n}.md" for n in range(changed)]
        for name in names:
            write(repo, name, "# Note\n\nNothing claimed here.\n")
        write(repo, "NEXT_SESSION.md",
              "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\nx\n\n## 1. Ref\n")
        extras = ", ".join(f'"{n}"' for n in names)
        write(repo, ".extant.toml", f"extra_docs = [{extras}]\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "init")
        # Change every configured document, so the mode has the most to do.
        for name in names:
            write(repo, name, "# Note\n\nRewritten today.\n")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", "rewrite")

        verify = timed(lambda: sh(repo, PY, str(repo / "tools/extant_collect.py"),
                                  "--repo", str(repo), "--verify"), runs=3)
        scan = timed(lambda: sh(repo, PY, str(repo / "tools/extant_collect.py"),
                                "--repo", str(repo), "--deleted-since", "HEAD~1"),
                     runs=3)
        print(f"  {changed:>13} {verify:>8.2f}s {scan:>14.2f}s "
              f"{(scan - verify) * 1000:>+8.0f} ms")
    print("  (it validates the OLD version of each CHANGED document, so the "
          "cost tracks the commit rather than the repository)")


def main() -> int:
    ARENA.mkdir(parents=True, exist_ok=True)
    hook_latency()
    document_scaling()
    repo_scaling()
    per_rule()
    baseline_cost()
    format_cost()
    sweep_scaling()
    generator_cliff()
    deleted_since_cost()
    claim_scaling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
