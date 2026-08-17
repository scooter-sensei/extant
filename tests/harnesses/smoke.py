"""Adversarial smoke test: try to break extant.

Not a confirmation pass. Each probe attempts a specific abuse or edge case and
reports what actually happened, so a loophole shows up as a finding rather than
as an absence of noise.

Categories: crash robustness, false positives, false negatives (gaming), and
cross-platform divergence.

Exits 1 when a probe raises a flag that is not in EXPECTED below, and also
when an EXPECTED flag stops being raised. The second half is the point: a
probe that quietly stops exercising anything reports exactly what a healthy
one does.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PKG = Path(sys.argv[1])
ARENA = Path(sys.argv[2])
PY = sys.executable

ISSUES: list[tuple[str, str, str]] = []   # (severity, probe, detail)
CLEAN: list[str] = []

# Flags this harness is expected to raise, each a documented design decision
# rather than a defect. A run raising anything else has found a regression; a
# run that stops raising one of these has a probe that no longer probes. Both
# exit 1.
#
# This is deliberately NOT "whatever was failing when CI was wired up". One
# flag that appeared on the first run was a SECURITY hit on the word "clone"
# occurring inside a prose comment, and that was fixed in the probe rather
# than listed here. Recording a false positive as expected would make the
# ledger the thing that hides the bug.
#
# KNOWN BLIND SPOT, found by removing a rule. This ledger fails a run when an
# expected flag DISAPPEARS, and that is genuinely useful. It cannot see a flag
# that keeps appearing for a different reason than it used to.
#
# `possible-secret` was deleted in 0.14.0, and the probe that flagged "a
# baseline can suppress a live credential" went on flagging it: its condition
# was `returncode == 0 and "possible-secret" not in stdout`, and with the rule
# gone the second half is trivially true while the first held for an unrelated
# dead SHA. The ledger reported 0 new and 0 missing and looked healthy while
# the probe tested nothing at all.
#
# So a flag surviving is weaker evidence than a flag vanishing. When a rule is
# removed, its probes have to be removed with it rather than left to keep
# reporting.
# Two entries left here after the hardening work, and both departures are
# instructive.
#
# "a recorded finding forgives future copies of itself" went when the baseline
# started recording an occurrence count. The ledger reported it MISSING, which
# is how a fix announces itself here.
#
# "a check can list the same file under two spellings" went for a worse reason:
# its probe never tested anything. It called note() unconditionally in an else
# branch, checking only that the tool had not crashed, so it declared the
# loophole open whether or not it was. That is the harness committing the
# failure it exists to detect - an assertion indistinguishable from a
# declaration. The probe now checks both routes and flags only if neither is
# caught.
EXPECTED = {
    "deleting a claim makes the document pass",
}

# Observations that depend on the machine rather than on the code, so neither
# their presence nor their absence is a result. The backtracking probe either
# finishes inside its timeout or does not, and that turns on how loaded the
# runner is, not on whether the tool changed.
TOLERATED = {
    "pathological user regex",
}


def note(severity: str, probe: str, detail: str) -> None:
    ISSUES.append((severity, probe, detail))
    print(f"  {severity:<8} {probe}")
    for line in detail.strip().splitlines()[:4]:
        print(f"           | {line}")


def ok(probe: str, detail: str = "") -> None:
    CLEAN.append(probe)
    print(f"  ok       {probe}" + (f"  ({detail})" if detail else ""))


def _operational_source(sources: list[str]) -> tuple[str, int]:
    """Strip prose from Python source, keeping every operational literal.

    Takes one string per FILE, not one big concatenated string, and parses
    each separately. Concatenating raw source first and parsing once breaks
    the moment two files both open with `from __future__ import annotations` -
    which every file in this package does - because that import is only legal
    as a module's first statement; a second copy of it after another file's
    code is a SyntaxError, not two harmless imports.

    Returns the surviving code, joined, and the number of git call sites
    across every file, so a scan over it can state what it examined.

    Comments and docstrings have to go, because they discuss the very things a
    scan looks for: a sentence reading "a commit made from a clone" is prose
    about git, not a call to it, and it was enough to make the network probe
    report a SECURITY finding against a tool that opens no sockets.

    Ordinary string literals have to STAY, because a git subcommand appears
    only ever as one - `_git(repo, "fetch", ...)`. Stripping all strings would
    leave a scan that is permanently clean and therefore permanently useless,
    which is the same failure wearing the opposite mask.

    The call-site pattern matches `.run(`/`.soft(` attribute calls as well as
    bare `_git`/`_git_soft` names. A modularisation gave every git operation a
    seam - extant/git.py's Git/SubprocessGit/CountingGit - and calls now read
    `_GIT.run(repo, ...)` or `ctx.git.soft(...)` throughout the package rather
    than a bare `_git(...)` the old pattern looked for; that pattern alone
    found the two calls still inside git.py itself and nothing else, which
    read as "almost nothing" beside the 30-odd real call sites the scan is
    meant to be counting. The wider pattern also happens to catch the direct
    `subprocess.run(...)` calls documented in CountingGit's docstring as
    bypassing the Git interface entirely (extant/rules/lfs.py, extant/refs.py,
    extant/sweep.py) - a truthful bonus, since those are exactly the kind of
    call this probe exists to notice, not a deliberate second target.
    """
    codes: list[str] = []
    call_sites = 0
    for source in sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                continue
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                node.body[0] = ast.Pass()
        call_sites += sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name)
                 and node.func.id in ("_git", "_git_soft"))
                or (isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("run", "soft"))
            )
        )
        codes.append(ast.unparse(ast.fix_missing_locations(tree)))
    return "\n".join(codes), call_sites


def sh(cwd: Path, *args: str, check: bool = False, timeout: int = 120):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check,
                          timeout=timeout)


def new_repo(name: str, trunk: str = "main") -> Path:
    repo = ARENA / name
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    sh(repo, "git", "init", "-q", "-b", trunk)
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "T")
    shutil.copytree(PKG / "plugin/skills/extant/payload", repo / "tools")
    return repo


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def commit(repo: Path, msg: str) -> str:
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", msg)
    return sh(repo, "git", "rev-parse", "--short", "HEAD").stdout.strip()


def tool(repo: Path, *args: str, timeout: int = 120):
    return sh(repo, PY, str(repo / "tools/extant_collect.py"),
              "--repo", str(repo), *args, timeout=timeout)


ENTRY = "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n{}\n\n## 1. Ref\n"


# ---------------------------------------------------------------- robustness
def p_empty_repo() -> None:
    print("\n[robustness] repository with NO commits")
    repo = new_repo("empty")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing yet."))
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    if "Traceback" in res.stderr:
        note("CRASH", "no commits: validate", res.stderr)
    else:
        ok("no commits: validate", f"exit {res.returncode}")
    res = tool(repo, "--collect", "--out", str(repo / "b.json"),
               "--suite-json", str(repo / "s.json"))
    write(repo, "s.json", '{"passed":1,"failed":0,"duration_s":1}')
    res = tool(repo, "--collect", "--out", str(repo / "b.json"),
               "--suite-json", str(repo / "s.json"))
    if "Traceback" in res.stderr:
        note("CRASH", "no commits: collect", res.stderr)
    else:
        ok("no commits: collect", f"exit {res.returncode}")


def p_detached_head() -> None:
    print("\n[robustness] detached HEAD")
    repo = new_repo("detached")
    write(repo, "NEXT_SESSION.md", ENTRY.format("x"))
    sha = commit(repo, "init")
    sh(repo, "git", "checkout", "-q", "--detach")
    res = tool(repo, "--verify")
    if "Traceback" in res.stderr:
        note("CRASH", "detached HEAD", res.stderr)
    else:
        ok("detached HEAD", f"exit {res.returncode}")


def p_no_git_at_all() -> None:
    print("\n[robustness] directory that is not a git repository")
    d = ARENA / "notgit"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copytree(PKG / "plugin/skills/extant/payload", d / "tools")
    write(d, "NEXT_SESSION.md", ENTRY.format("Reference `dead000000000000000000000000000000000000`."))
    res = tool(d, "--validate", "NEXT_SESSION.md")
    if "Traceback" in res.stderr:
        note("CRASH", "not a git repo", res.stderr)
    else:
        ok("not a git repo", f"exit {res.returncode}")


def p_binary_document() -> None:
    print("\n[robustness] document containing invalid UTF-8")
    repo = new_repo("binary")
    (repo / "NEXT_SESSION.md").write_bytes(
        b"# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n\xff\xfe binary \x00 here\n\n## 1. Ref\n")
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    if "Traceback" in res.stderr:
        note("CRASH", "invalid UTF-8 document", res.stderr)
    else:
        ok("invalid UTF-8 document", f"exit {res.returncode}")


def p_large_document() -> None:
    print("\n[performance] large document")
    repo = new_repo("large")
    body = "\n".join(
        f"Line {n} with `abcdef{n:07d}` and [link](docs/f{n}.md) and `docs/g{n}.md`."
        for n in range(4000))
    write(repo, "NEXT_SESSION.md", ENTRY.format(body))
    commit(repo, "init")
    start = time.time()
    res = tool(repo, "--validate", "NEXT_SESSION.md", timeout=300)
    elapsed = time.time() - start
    if "Traceback" in res.stderr:
        note("CRASH", "4000-line document", res.stderr)
    elif elapsed > 120:
        note("SLOW", "4000-line document", f"took {elapsed:.0f}s")
    else:
        ok("4000-line document", f"{elapsed:.1f}s, exit {res.returncode}")


def p_pathological_regex() -> None:
    print("\n[performance] catastrophic-backtracking config")
    repo = new_repo("redos")
    write(repo, ".extant.toml", "branch_token = '`((a+)+b)`'\n")
    write(repo, "NEXT_SESSION.md", ENTRY.format("`" + "a" * 40 + "`"))
    commit(repo, "init")
    try:
        start = time.time()
        res = tool(repo, "--validate", "NEXT_SESSION.md", timeout=45)
        ok("pathological user regex", f"{time.time()-start:.1f}s, exit {res.returncode}")
    except subprocess.TimeoutExpired:
        note("HANG", "pathological user regex",
             "a config-supplied pattern can hang the tool indefinitely "
             "(user-supplied, but a hang is a worse failure than an error)")


# ---------------------------------------------------------- false positives
def p_claims_in_code_fences() -> None:
    print("\n[false positive] claims inside fenced code blocks")
    repo = new_repo("fences")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "Example of the format:\n\n"
        "```\n"
        "Merged to `main` at `dead000000000000000000000000000000000000`.\n"
        "**Design:** `docs/example-not-real.md`\n"
        "```\n"))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    fired = [ln for ln in res.stdout.splitlines() if ln.startswith("line ")]
    if fired:
        note("FALSE-POS", "documentation examples inside a code fence are checked",
             "\n".join(fired) + "\n(links are fence-stripped; SHA and path rules are not)")
    else:
        ok("code fences ignored by all rules")


def p_case_sensitivity() -> None:
    print("\n[portability] path case sensitivity")
    repo = new_repo("case")
    write(repo, "docs/plan.md", "# plan\n")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "See [plan](docs/PLAN.md).\n**Design:** `Docs/plan.md`"))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    fired = [ln for ln in res.stdout.splitlines() if ln.startswith("line ")]
    insensitive = not fired
    if insensitive:
        note("PORTABILITY", "wrong-case paths accepted on this filesystem",
             "docs/PLAN.md and Docs/plan.md both passed. On a case-sensitive "
             "filesystem (Linux CI, most servers) these are dead links, so a "
             "document can be green locally and red in CI, or vice versa.")
    else:
        ok("wrong-case paths reported", f"{len(fired)} finding(s)")


def p_symlink() -> None:
    print("\n[edge] symlinked and traversing targets")
    repo = new_repo("links")
    write(repo, "docs/real.md", "# real\n")
    try:
        os.symlink(repo / "docs/real.md", repo / "docs/alias.md")
        made = True
    except (OSError, NotImplementedError):
        made = False
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "See [alias](docs/alias.md).\nSee [up](../../../../etc/passwd).\n"
        "See [broken](docs/dangling.md).\n"))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    if "Traceback" in res.stderr:
        note("CRASH", "symlink/traversal targets", res.stderr)
    else:
        detail = f"symlink created={made}, exit {res.returncode}"
        if "etc/passwd" in res.stdout:
            detail += "; traversing link reported as dead (no filesystem probe leak)"
        ok("symlink/traversal targets", detail)


# ----------------------------------------------------------- false negatives
def p_wrong_entry_header() -> None:
    print("\n[gaming] entry header that does not match the configured prefix")
    repo = new_repo("header")
    write(repo, "NEXT_SESSION.md",
          "# S\n\n### Phase 1 - x (in progress, 2026-01-01)\n\n"
          "Work is NOT yet merged on `feature/phantom`.\n\n## 1. Ref\n")
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    if "stale-live-claim" in res.stdout or "unknown-branch" in res.stdout:
        ok("wrong header still checked")
    else:
        blind = "NOTE:" in res.stdout
        note("SILENT-SKIP" if not blind else "SILENT-SKIP-NOTED",
             "a mistyped entry header disables the entry rules",
             f"exit {res.returncode}; denominator NOTE present={blind}. "
             "Nothing says the document HAS entries the tool could not see.")


def p_argument_injection() -> None:
    print("\n[hardening] branch token that looks like a git option")
    repo = new_repo("inject")
    write(repo, ".extant.toml", "branch_token = '`([\\w.-]+/[^`]+)`'\n")
    # A path under ARENA, removed first. `/tmp/pwned` is shared: a leftover
    # from any earlier run reports a leak that did not happen, and on Windows
    # it resolves somewhere the probe never writes, so the check would pass
    # without ever having been able to fail.
    target = (ARENA / "inject-side-effect").resolve()
    shutil.rmtree(target, ignore_errors=True)
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        f"Work is on `--output={target.as_posix()}/x`."))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md", timeout=60)
    leaked = target.exists()
    if "Traceback" in res.stderr:
        note("CRASH", "option-shaped branch token", res.stderr)
    elif leaked:
        note("SECURITY", "option-shaped branch token reached git as an option",
             "a document controlled the git command line")
    else:
        ok("option-shaped branch token", f"exit {res.returncode}, no side effect")


def p_deleting_the_claim() -> None:
    print("\n[gaming] passing by deleting the claim")
    repo = new_repo("delete")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "Reference `dead000000000000000000000000000000000000`."))
    commit(repo, "init")
    before = tool(repo, "--validate", "NEXT_SESSION.md")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing to see."))
    after = tool(repo, "--validate", "NEXT_SESSION.md")
    if before.returncode == 1 and after.returncode == 0:
        note("BY-DESIGN", "deleting a claim makes the document pass",
             "documented and mitigated only by the /extant workflow reporting "
             "first-run findings; the validator alone cannot tell repair from "
             "erasure")
    else:
        ok("claim deletion", f"{before.returncode} -> {after.returncode}")


def p_pattern_that_matches_nothing() -> None:
    print("\n[gaming] a config whose patterns match nothing")
    repo = new_repo("blind")
    write(repo, ".extant.toml",
          "merge_claim = 'ZZZZ_NEVER_MATCHES_{trunk}'\n"
          "path_pointer = 'ZZZZ_NEVER'\n")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "Merged to `main` at `dead000000000000000000000000000000000000`.\n"
        "**Design:** `docs/absent.md`"))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    if "NOTE:" in res.stdout and "false-merge-claim" in res.stdout:
        ok("blind patterns named in the denominator")
    else:
        note("SILENT", "blind patterns not surfaced", res.stdout)


def p_library_link_base() -> None:
    print("\n[api] validate() called as a library, not through main()")
    repo = new_repo("libapi")
    write(repo, "docs/plan.md", "# plan\n")
    write(repo, "docs/HANDOFF.md", ENTRY.format("See [plan](plan.md)."))
    commit(repo, "init")
    script = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "import pathlib\n"
        "from extant import session as h\n"
        "repo = pathlib.Path(r'%s')\n"
        "doc = pathlib.Path(r'%s')\n"
        "text = doc.read_text(encoding='utf-8')\n"
        "print('default:', [f.kind for f in h.validate(repo, text)])\n"
        "print('based:  ', [f.kind for f in h.validate(repo, text, base=doc.parent)])\n"
        % (repo / "tools", repo, repo / "docs/HANDOFF.md")
    )
    res = sh(repo, PY, "-c", script)
    default_line = next((l for l in res.stdout.splitlines() if l.startswith("default:")), "")
    based_line = next((l for l in res.stdout.splitlines() if l.startswith("based:")), "")
    if "dead-md-link" in based_line:
        note("API", "base= does not fix relative link resolution",
             f"{default_line}\n{based_line}")
    elif "dead-md-link" in default_line:
        ok("library link resolution",
           "repo-root by default, correct with base=; the parameter exists and works")
    else:
        note("HARNESS", "probe setup did not reproduce the default behaviour",
             res.stdout + res.stderr)


# ------------------------------------------------- new surfaces (0.4.0)
def p_consistency_abuse() -> None:
    """The consistency rule reads arbitrary configured paths. What can that be
    pointed at, and does it fail safely?"""
    print("\n[consistency] paths outside the repo, and a self-referential check")
    repo = new_repo("consistency-abuse")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing."))
    write(repo, ".extant.toml",
          "[extant.consistency.escape]\n"
          "\"../../../etc/passwd\" = 'root:(x)'\n"
          "\"NEXT_SESSION.md\" = 'Phase (1)'\n")
    commit(repo, "init")
    res = tool(repo, "--verify")
    if "Traceback" in res.stderr:
        note("CRASH", "consistency pointed outside the repository", res.stderr)
    else:
        ok("consistency pointed outside the repository",
           f"exit {res.returncode}, reported rather than crashed")

    # A check whose two files are the same file: it can only agree with itself.
    #
    # TWO routes, and they are caught by different mechanisms. The string
    # spelling is rejected at config load, by path normalisation. A case
    # variant on a case-insensitive filesystem reaches the same file without
    # any string differing, so only the filesystem can settle it.
    #
    # This probe used to call note() unconditionally in an else branch and
    # declare the loophole open regardless of what the tool did. It reported
    # exactly the same thing before and after the loophole was closed, which is
    # the defect this whole harness exists to make visible, committed by the
    # harness itself.
    write(repo, ".extant.toml",
          "[extant.consistency.same]\n"
          "\"NEXT_SESSION.md\" = 'Phase (1)'\n"
          "\"./NEXT_SESSION.md\" = 'Phase (1)'\n")
    commit(repo, "same file twice")
    res = tool(repo, "--verify")
    combined = res.stdout + res.stderr
    if "Traceback" in res.stderr:
        note("CRASH", "consistency check listing one file twice", res.stderr)
    elif "lists the same file twice" in combined:
        ok("two spellings of one path are rejected at config load")
    else:
        note("BY-DESIGN", "a check can list the same file under two spellings",
             "it then always agrees, which is a vacuous pass:\n" + combined[:300])

    write(repo, ".extant.toml",
          "[extant.consistency.same]\n"
          "\"NEXT_SESSION.md\" = 'Phase (1)'\n"
          "\"next_session.md\" = 'Phase (1)'\n")
    commit(repo, "same file by case variant")
    res = tool(repo, "--verify")
    combined = res.stdout + res.stderr
    if "Traceback" in res.stderr:
        note("CRASH", "consistency check listing one file by case", res.stderr)
    elif "are the same file" in combined:
        ok("a case variant reaching one file is reported")
    elif "lists the same file twice" in combined:
        ok("the case variant was rejected at config load instead")
    elif "which does not exist" in combined:
        # On a case-SENSITIVE filesystem these are genuinely two files and the
        # second is absent, which the rule reports as a missing source. That is
        # the correct answer there, so it is not a finding.
        #
        # This branch was described in a comment and not written, so the probe
        # fell through to note() and failed CI on Linux while passing on
        # Windows. A probe verified on one filesystem has been verified on one
        # filesystem.
        ok("on a case-sensitive filesystem these are two files, and the "
           "missing one is reported")
    else:
        note("BY-DESIGN", "a check can list the same file under two spellings",
             "a case variant reached one file and was not reported:\n"
             + combined[:300])


def p_search_abuse() -> None:
    print("\n[search] regex metacharacters, huge queries, empty archive")
    repo = new_repo("search-abuse")
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
          "Costs $5.00 (approx) [bracketed] a.*b\n\n## 1. Ref\n")
    commit(repo, "init")
    for query, label in ((".*", "regex wildcard"), ("[", "unbalanced bracket"),
                         ("$5.00 (approx)", "literal metacharacters"),
                         ("x" * 5000, "5000-character query")):
        res = tool(repo, "--search", query, timeout=60)
        if "Traceback" in res.stderr:
            note("CRASH", f"search: {label}", res.stderr)
            return
    ok("search survives metacharacters and huge queries",
       "treated as literal text, never compiled as a pattern")

    res = tool(repo, "--search", "nothing here at all")
    if "0 match" in res.stdout:
        ok("search reports its denominator on a miss")
    else:
        note("SILENT", "search miss prints no denominator", res.stdout)


def p_suggest_fixes_abuse() -> None:
    print("\n[suggest-fixes] does it ever write, and can the patch be trusted?")
    repo = new_repo("fixes-abuse")
    write(repo, "docs/plan.md", "# plan\n")
    write(repo, "NEXT_SESSION.md",
          "# S\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
          "See [plan](docs/plan.md).\n\n## 1. Ref\n")
    commit(repo, "init")
    sh(repo, "git", "mv", "docs/plan.md", "docs/design.md")
    sh(repo, "git", "commit", "-qm", "rename")

    before = (repo / "NEXT_SESSION.md").read_bytes()
    res = tool(repo, "--verify", "--suggest-fixes")
    after = (repo / "NEXT_SESSION.md").read_bytes()
    if before != after:
        note("SECURITY", "suggest-fixes MODIFIED the document",
             "it must only ever emit a patch")
    else:
        ok("suggest-fixes wrote nothing")

    patch = repo / "p.patch"
    patch.write_bytes(res.stdout.encode("utf-8"))
    applied = sh(repo, "git", "apply", "p.patch")
    if applied.returncode != 0:
        note("BROKEN", "the emitted patch does not apply", applied.stderr)
    else:
        ok("the emitted patch applies cleanly")

    # A document with no findings at all must not emit a stray patch.
    repo2 = new_repo("fixes-clean")
    write(repo2, "NEXT_SESSION.md", ENTRY.format("Nothing falsifiable."))
    commit(repo2, "init")
    res = tool(repo2, "--verify", "--suggest-fixes")
    if res.stdout.strip():
        note("NOISE", "suggest-fixes printed to stdout with nothing to fix",
             res.stdout[:200])
    else:
        ok("nothing to fix produces an empty patch channel")


def p_config_discovery_abuse() -> None:
    """The upward search must not escape the repository."""
    print("\n[config] does the upward search leak out of the repo?")
    outer = ARENA / "config-outer"
    shutil.rmtree(outer, ignore_errors=True)
    (outer / "inner").mkdir(parents=True)
    write(outer, ".extant.toml", 'primary_doc = "OUTER_WINS.md"\n')
    repo = new_repo("config-outer/inner/repo")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing."))
    commit(repo, "init")
    res = tool(repo, "--verify")
    if "OUTER_WINS" in res.stdout + res.stderr:
        note("SECURITY", "a parent directory's config was inherited",
             "the search escaped the repository root")
    else:
        ok("config search stops at the repository root",
           "an outer .extant.toml was not inherited")


# ------------------------------------------------- new surfaces (0.7.0-0.10.0)
# The baseline is the most abusable thing here by a wide margin. Every other
# feature reports MORE; this one reports less on purpose, which makes every
# probe below a question about whether the amnesty can quietly grow to cover
# everything. "Does suppression work" is the easy half and is already a unit
# test. What follows is the other half.
# A letter, because an all-digit run reads as a number rather than a commit:
# forty zeroes stopped being SHA-shaped and two probes quietly had nothing to
# find. Both reported HARNESS rather than passing, which is the distinction
# this file exists to make.
DEAD_SHA = "dead" + "0" * 36


def p_baseline_forgives_a_repaste() -> None:
    """The fingerprint excludes the line number on purpose, so that reflowing a
    paragraph does not un-suppress everything. The cost of that choice is that
    the SAME claim pasted somewhere new is also already forgiven."""
    print("\n[baseline] the same dead claim, pasted again after recording")
    repo = new_repo("baseline-repaste")
    write(repo, "NEXT_SESSION.md", ENTRY.format(f"Reference `{DEAD_SHA}`."))
    commit(repo, "init")
    tool(repo, "--validate", "NEXT_SESSION.md", "--write-baseline")

    write(repo, "NEXT_SESSION.md", ENTRY.format(
        f"Reference `{DEAD_SHA}`.\n\n"
        f"A paragraph added today, citing `{DEAD_SHA}` all over again."))
    res = tool(repo, "--validate", "NEXT_SESSION.md", "--baseline")
    if res.returncode == 0:
        note("BY-DESIGN", "a recorded finding forgives future copies of itself",
             "the fingerprint is (path, kind, detail) with no line number, so "
             "one amnesty covers every future occurrence of that exact claim "
             "in that file. Line-number fingerprints would trade this for "
             "un-suppressing on every reflow, which is worse.")
    else:
        ok("a new copy of a recorded claim is still reported",
           f"exit {res.returncode}")


def p_baseline_failure_modes() -> None:
    """Every way of getting a baseline wrong must be LOUD.

    This is the project's own core failure mode aimed at itself: if a typo'd
    path or a corrupt file degraded to "suppress nothing" or "suppress
    everything", CI would stay green and nobody would learn that the ratchet
    had stopped working. Exit codes are asserted rather than message text,
    because the exit code is what CI reads.
    """
    print("\n[baseline] corrupt, missing and empty baselines")
    repo = new_repo("baseline-broken")
    write(repo, "NEXT_SESSION.md", ENTRY.format(f"Reference `{DEAD_SHA}`."))
    commit(repo, "init")

    plain = tool(repo, "--validate", "NEXT_SESSION.md")
    if plain.returncode != 1:
        note("HARNESS", "the unsuppressed document did not report a finding",
             f"exit {plain.returncode}; nothing below can be trusted")
        return

    write(repo, "bad.json", "not json at all\n")
    write(repo, "empty.json", '{"version": 1, "findings": []}\n')
    cases = [
        ("corrupt", ("--baseline", "bad.json"), 2),
        ("missing", ("--baseline", "nope.json"), 2),
        ("empty", ("--baseline", "empty.json"), 1),
    ]
    for label, args, expected in cases:
        res = tool(repo, "--validate", "NEXT_SESSION.md", *args)
        if res.returncode == expected:
            ok(f"a {label} baseline exits {expected}, not 0")
        elif res.returncode == 0:
            note("SILENT", f"a {label} baseline makes the run pass",
                 "a broken suppression file turned a failing document green, "
                 "which is indistinguishable from having fixed it")
        else:
            note("UNEXPECTED", f"a {label} baseline exits {res.returncode}",
                 f"expected {expected}: {res.stderr.strip()[:200]}")


def p_baseline_theatre() -> None:
    """A baseline recorded on a clean document protects nothing, and looks
    exactly like one that protects a great deal."""
    print("\n[baseline] a baseline with nothing in it")
    repo = new_repo("baseline-theatre")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing falsifiable here."))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md", "--write-baseline")
    body = (repo / ".extant-baseline.json").read_text(encoding="utf-8")
    empty = '"findings": []' in body.replace("\n", "").replace("  ", "")
    said_zero = "0 finding" in (res.stdout + res.stderr)
    if empty and not said_zero:
        note("SILENT", "an empty baseline is written without saying it is empty",
             "the file exists, the flag was accepted, and the project now "
             "believes it has a ratchet")
    else:
        ok("recording nothing is reported as nothing",
           f"empty={empty}, stated={said_zero}")


def p_sarif_stdout_purity() -> None:
    """SARIF's contract is that stdout is JSON and NOTHING else.

    A single stray diagnostic makes the file unparseable, and the way that
    surfaces is a CI upload step failing days later with no obvious cause. The
    document here carries content designed to break a naive serialiser.
    """
    print("\n[sarif] hostile content, and whether stdout stays parseable")
    repo = new_repo("sarif-purity")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        'See [a](docs/quote"and\\backslash.md).\n'
        "See [b](docs/inj%0A::add-mask::hidden.md).\n"
        "See [c](docs/tab\tand-control.md).\n"
        f"Reference `{DEAD_SHA}`.\n"))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md", "--format=sarif")
    import json as _json
    try:
        parsed = _json.loads(res.stdout)
        results = parsed["runs"][0]["results"]
    except (ValueError, KeyError, IndexError) as exc:
        note("BROKEN", "SARIF stdout is not parseable JSON",
             f"{exc}\nfirst 200 bytes: {res.stdout[:200]!r}")
        return
    if not results:
        note("HARNESS", "SARIF parsed but contained no results",
             "the probe document produced nothing to serialise, so purity was "
             "not actually exercised")
        return
    ok("SARIF stdout parses with hostile content in the findings",
       f"{len(results)} results")
    if res.stderr.strip():
        ok("human diagnostics went to stderr", f"{len(res.stderr)} bytes")
    else:
        note("SILENT", "SARIF mode printed no diagnostics anywhere",
             "the denominator is the thing that distinguishes a clean run from "
             "a blind one, and in SARIF mode it has nowhere to go but stderr")


def p_github_annotation_injection() -> None:
    """Can a DOCUMENT forge a GitHub workflow command?

    Findings are interpolated into `::error ...::message`, and the document
    controls both the path and the detail. A command must begin at the start
    of a line, so forgery reduces to injecting a newline.

    The first version of this probe proved NOTHING. It put `%0A` in a link and
    called that a newline, but that is already the escaped spelling: it passed
    through unchanged, and passed just as happily with the escaper deleted. A
    markdown link cannot contain a raw newline in the first place, so the
    payload was unreachable by construction.

    What IS reachable, and what this asserts, is that the escaper demonstrably
    ran: a literal `%` in a path must come out as `%25`. That is the same
    function that neutralises `\\n`, so observing it work on the character a
    document CAN carry is the evidence available. Asserting the absence of
    forged commands alone would be a check that passes when nothing happened.
    """
    print("\n[github] a document trying to write its own workflow commands")
    repo = new_repo("gh-inject")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "See [a](docs/pct%0A-and-colon:comma,x.md).\n"
        "See [b](docs/y%25::add-mask::PWNED.md).\n"
        f"Reference `{DEAD_SHA}`.\n"))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md", "--format=github")
    lines = res.stdout.splitlines()
    commands = [ln for ln in lines if ln.startswith("::")]
    if not commands:
        note("HARNESS", "no annotations were emitted at all",
             "nothing below was exercised; the probe document produced no "
             "findings to interpolate")
        return

    # The proof moved when link targets began being percent-DECODED before
    # resolution. `%0A` in the document is now a real newline by the time it
    # reaches a finding, so the escaper turning it back into `%0A` is the
    # demonstration, and a literal `%` surviving as `%25` is the other half.
    # Previously the document text was interpolated raw and the same escaper
    # double-encoded it to `%250A`, which is what this used to look for.
    escaped = [ln for ln in commands if "%0A" in ln or "%25" in ln]
    if not escaped:
        note("BROKEN", "the annotation escaper did not run",
             "a decoded newline and a literal % both came through untouched, "
             "so nothing is neutralising workflow-command syntax")
    else:
        ok("the escaper demonstrably ran", f"{len(escaped)} annotation(s) "
           "carry an escaped newline or %, proving the path was not "
           "interpolated raw")

    forged = [ln for ln in commands
              if not ln.startswith("::error") and not ln.startswith("::warning")]
    multiline = [ln for ln in commands if "\n" in ln or "\r" in ln]
    if forged or multiline:
        note("SECURITY", "a document forged a GitHub workflow command",
             "\n".join((forged + multiline)[:3]))
    else:
        ok("document content cannot start a new workflow command",
           f"{len(commands)} annotations, every one an ::error")


def p_offline() -> None:
    """The tool must never reach the network.

    It runs in a post-commit hook. A hook that resolves a pin by asking a
    remote would hang behind a corporate proxy, leak repository names to
    whoever answers, and fail closed on a plane. `dead-pinned-ref` is the rule
    that would be tempting to implement that way, since it validates an
    install snippet pointing at a real forge.

    Probed two ways, because either alone is weak: a source scan can miss a
    call it does not know the shape of, and a behavioural run can pass because
    the network happened to be reachable.
    """
    print("\n[network] does anything phone home?")
    # The SHIM plus the PACKAGE, not the shim alone. The shim used to hold
    # every git call directly; a modularisation moved them all behind
    # extant/git.py's Git/SubprocessGit seam, so the shim shrank to 68 lines
    # of version-check-then-import with no git call left in it to find. A scan
    # reading only the shim after that refactor was examining the right file
    # for an era that ended - not wrong about what it saw, silent about where
    # the thing it was looking for had gone.
    payload = PKG / "plugin/skills/extant/payload"
    scanned = [payload / "extant_collect.py",
              *sorted((payload / "extant").rglob("*.py"))]
    code, call_sites = _operational_source(
        [p.read_text(encoding="utf-8") for p in scanned])
    remote_ops = ("ls-remote", "fetch", "clone", "urlopen", "http.client",
                  "requests.", "socket.create_connection", "git.push")
    hits = [op for op in remote_ops if op in code]
    if call_sites < 5:
        note("HARNESS", "the git call-site scan found almost nothing",
             f"{call_sites} sites across {len(scanned)} file(s); the pattern "
             "is probably wrong, so a clean result here means nothing")
    elif hits:
        note("SECURITY", "a network operation appears in the validator",
             f"found {hits} across {call_sites} git call sites")
    else:
        ok("no network operation in the validator",
           f"scanned {call_sites} git call sites for {len(remote_ops)} shapes "
           f"({len(code)} chars of code, prose excluded)")

    repo = new_repo("offline")
    write(repo, "README.md",
          "# P\n\n```yaml\nrepos:\n  - repo: https://github.com/nobody/extant\n"
          "    rev: v9.9.9-does-not-exist\n    hooks:\n      - id: extant\n```\n")
    write(repo, ".extant.toml", 'primary_doc = "README.md"\n')
    commit(repo, "init")
    sh(repo, "git", "remote", "add", "origin",
       "https://github.com/nobody/extant.git")
    env = dict(os.environ, http_proxy="http://127.0.0.1:1",
               https_proxy="http://127.0.0.1:1", GIT_TERMINAL_PROMPT="0")
    start = time.time()
    try:
        res = subprocess.run(
            [PY, str(repo / "tools/extant_collect.py"), "--repo", str(repo),
             "--validate", "README.md"],
            cwd=repo, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=45, env=env)
        elapsed = time.time() - start
        if "dead-pinned-ref" not in res.stdout:
            note("HARNESS", "the pin probe produced no pinned-ref output",
                 "the rule did not engage, so this proved nothing about the "
                 "network")
        else:
            ok("a dead pin behind a black-hole proxy resolves locally",
               f"{elapsed:.1f}s, exit {res.returncode}")
    except subprocess.TimeoutExpired:
        note("HANG", "validating a pin hung with the network unavailable",
             "the rule is reaching a remote, which makes every commit depend "
             "on connectivity")


def p_install_over_existing_agent_files() -> None:
    """Setup writes agent instructions to two paths. Both are files a human
    edits afterwards, so the question is what a re-run does to that work."""
    print("\n[install] re-running setup over hand-edited agent files")
    repo = new_repo("reinstall")
    write(repo, "README.md", "# P\n\nSee [docs](docs/guide.md).\n")
    write(repo, "docs/guide.md", "# guide\n")
    commit(repo, "init")
    # --claude-command because the probe is about BOTH agent files, and this
    # fixture has no sign of Claude Code, so the slash command is not written
    # by default. Without the flag this probe would silently test one file.
    first = sh(repo, PY, str(PKG / "plugin/skills/extant/install.py"),
               "--repo", str(repo), "--preset", "readme", "--claude-command")
    skill = repo / ".agents/skills/extant/SKILL.md"
    command = repo / ".claude/commands/extant.md"
    if not skill.is_file():
        note("HARNESS", "setup did not write the cross-platform skill",
             (first.stdout + first.stderr)[:400])
        return
    # Asserted, not assumed. This line named the command file for its whole
    # existence without ever checking it was there, so it would have gone on
    # reporting "both" after the file stopped being written.
    if not command.is_file():
        note("HARNESS", "setup did not write the slash command even when asked",
             (first.stdout + first.stderr)[:400])
        return
    ok("setup wrote both agent files",
       f"{skill.relative_to(repo).as_posix()}, "
       f"{command.relative_to(repo).as_posix()}")

    marker = "\n\nLOCAL NOTE: our team also checks the release notes.\n"
    skill.write_text(skill.read_text(encoding="utf-8") + marker,
                     encoding="utf-8")
    second = sh(repo, PY, str(PKG / "plugin/skills/extant/install.py"),
                "--repo", str(repo), "--preset", "readme")
    kept = marker.strip() in skill.read_text(encoding="utf-8")
    if kept:
        ok("a re-run preserved the local edit")
    else:
        note("BY-DESIGN", "a re-run overwrites hand-edited agent instructions",
             "setup is idempotent by rewriting, so local additions to the "
             "generated skill are lost without warning. Whether that is right "
             "depends on whether these files are generated artifacts or "
             "starting points, and nothing states which. "
             f"(re-run exit {second.returncode})")


# ------------------------------------------------------------------- sweep
def p_sweep_nothing_to_sweep() -> None:
    """A repository with no markdown must SAY it swept nothing.

    This is the project's signature failure aimed at its newest mode. "0
    findings" and "0 files examined" both exit 0 and both print reassuringly,
    and a sweep is the easiest place in the tool to produce the second by
    accident - a wrong glob, an index read on an incomplete checkout, a
    pathspec that matches nothing. The exit code cannot tell them apart, so
    the diagnostic has to.
    """
    print("\n[sweep] a repository with no markdown at all")
    repo = new_repo("sweep-empty")
    write(repo, "src/main.py", "x = 1\n")
    commit(repo, "init")
    res = tool(repo, "--sweep")
    combined = res.stdout + res.stderr
    if res.returncode != 0:
        note("BROKEN", "sweeping a repo with no markdown fails",
             f"exit {res.returncode}\n{combined[:200]}")
    elif "0 markdown files" in combined or "swept 0" in combined:
        ok("an empty sweep says so rather than exiting quietly")
    else:
        note("SILENT", "a sweep that examined nothing printed no denominator",
             f"exit 0 with no statement of what was looked at:\n{combined[:200]}")


def p_sweep_unreadable_file() -> None:
    """A file that could not be read is not a file with no findings.

    The two are indistinguishable in an exit code, and a sweep that skips a
    latin-1 document quietly under-reports on every repository holding one.
    """
    print("\n[sweep] a tracked file that is not valid UTF-8")
    repo = new_repo("sweep-unreadable")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing yet."))
    write(repo, ".extant.toml", 'primary_doc = "NEXT_SESSION.md"\n')
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    # Bytes that are not valid UTF-8 in any position.
    (repo / "docs" / "latin1.md").write_bytes(
        b"# Caf\xe9\n\nSee [x](gone.md).\n")
    commit(repo, "init")
    res = tool(repo, "--sweep")
    combined = res.stdout + res.stderr
    if "could not be read" in combined and "latin1.md" in combined:
        ok("an undecodable file is counted and named, not skipped")
    elif "swept 2 markdown file" in combined:
        note("SILENT", "an unreadable file was counted as examined",
             "the denominator says 2 files, but one of them could not be "
             f"decoded and produced no findings:\n{combined[:200]}")
    else:
        note("SILENT", "an unreadable file vanished from the sweep",
             f"neither named nor counted:\n{combined[:300]}")


def p_sweep_gates_only_on_configured() -> None:
    """The vetted/unvetted split is the whole design, and both halves are
    load-bearing.

    Gating on unreviewed documents would turn every example claim in every
    README into a build failure - measured at 18 findings on this repository,
    all false. Gating on nothing would make the mode incapable of failing,
    which reads exactly like a clean run.
    """
    print("\n[sweep] whether an unreviewed document can fail the build")
    repo = new_repo("sweep-gating")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing wrong here."))
    write(repo, "docs/example.md",
          f"# Examples\n\nA dead link: [x](no-such-file.md).\n"
          f"A dead commit: `{DEAD_SHA}`.\n")
    write(repo, ".extant.toml", 'primary_doc = "NEXT_SESSION.md"\n')
    commit(repo, "init")
    res = tool(repo, "--sweep")
    combined = res.stdout + res.stderr
    if res.returncode == 0 and "example.md" in combined:
        ok("an unreviewed document is surveyed but does not gate")
    elif res.returncode == 0:
        note("SILENT", "an unreviewed document was not even surveyed",
             f"exit 0, and nothing named it:\n{combined[:300]}")
    else:
        note("NOISE", "an unreviewed document failed the build",
             "example claims in unconfigured files would break every CI run "
             f"that adopts --sweep:\n{combined[:300]}")

    # And the other direction, which is the half that makes the mode useful.
    write(repo, "NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD_SHA}`."))
    commit(repo, "break the configured doc")
    res = tool(repo, "--sweep")
    if res.returncode == 1:
        ok("a configured document still gates")
    else:
        note("BROKEN", "a configured document stopped gating",
             f"exit {res.returncode} with a dead claim in primary_doc")


def p_sweep_sarif_purity() -> None:
    """Sweep has two output channels and a summary that must not collide.

    The summary was written to stderr unconditionally at one point, which
    interleaved it AHEAD of the findings because the streams flush
    independently. In SARIF the same mistake is fatal rather than untidy.
    """
    print("\n[sweep] SARIF from a sweep, across multiple documents")
    repo = new_repo("sweep-sarif")
    write(repo, "NEXT_SESSION.md", ENTRY.format(f"Merged at `{DEAD_SHA}`."))
    write(repo, "docs/a.md", "# A\n\nSee [x](gone-a.md).\n")
    write(repo, "docs/b.md", "# B\n\nSee [y](gone-b.md).\n")
    write(repo, ".extant.toml", 'primary_doc = "NEXT_SESSION.md"\n')
    commit(repo, "init")
    res = tool(repo, "--sweep", "--format=sarif")
    import json as _json
    try:
        results = _json.loads(res.stdout)["runs"][0]["results"]
    except (ValueError, KeyError, IndexError) as exc:
        note("BROKEN", "sweep SARIF stdout is not parseable JSON",
             f"{exc}\nfirst 200 bytes: {res.stdout[:200]!r}")
        return
    if not results:
        note("HARNESS", "sweep SARIF parsed but held no results",
             "nothing was serialised, so purity was not exercised")
        return
    ok("sweep SARIF stdout parses", f"{len(results)} results")
    # Findings from several documents share one SARIF run, so each must carry
    # its own path or a reader cannot tell them apart.
    locations = {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
                 for r in results if r.get("locations")}
    if len(locations) >= 2:
        ok("findings carry the document they came from", f"{len(locations)} paths")
    else:
        note("BROKEN", "every sweep finding reports the same path",
             f"a multi-document sweep collapsed to {locations}")
    if "swept" not in res.stderr:
        note("SILENT", "sweep SARIF printed no denominator to stderr",
             "stdout must stay pure JSON, so stderr is the only place the "
             "count of examined files can go, and it went nowhere")


def p_sweep_site_config_that_is_a_directory() -> None:
    """Generator detection turns on one filename existing, and that filename is
    attacker-adjacent in the mildest sense: it is a name anyone might use.

    A DIRECTORY called `mkdocs.yml` must not switch the tool into site mode,
    where route-shaped links stop being checked. The guard is `.is_file()`,
    and this is the probe that would notice it becoming `.exists()`.

    The payload has to be a ROUTE, which is the thing site mode actually
    suppresses: root-relative, `.html`, or extensionless. The first version of
    this probe used a plain `docs/gone.md`, which no generator setting has ever
    controlled - so it passed against the bug it was written to catch, and only
    a deliberate mutation showed that up. A probe aimed slightly beside its
    target is the most comfortable kind of nothing.
    """
    print("\n[sweep] a directory named like a generator config")
    repo = new_repo("sweep-fakeconfig")
    (repo / "mkdocs.yml").mkdir(parents=True, exist_ok=True)
    write(repo, "mkdocs.yml/keep.txt", "not a config\n")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "See [route](/reference/config/).\nSee [file](docs/gone.md)."))
    write(repo, ".extant.toml", 'primary_doc = "NEXT_SESSION.md"\n')
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    # The plain file link is the control: it is reported whatever the generator
    # setting says, so its absence means the rule is off for some other reason
    # and the route result below would be meaningless.
    if "docs/gone.md" not in res.stdout:
        note("HARNESS", "the control link was not reported",
             "dead-md-link is not running at all here, so nothing this probe "
             f"says about site mode can be trusted:\n{res.stdout[:300]}")
        return
    if "/reference/config/" in res.stdout:
        ok("a directory named mkdocs.yml does not enable site mode")
    else:
        note("BLIND", "a directory named like a config disabled route checking",
             "creating a DIRECTORY called mkdocs.yml was enough to stop "
             "route-shaped links being judged, while a real config file is "
             f"what that is meant to require:\n{res.stdout[:300]}")


def p_deleted_since_abuse() -> None:
    """The new mode's error paths. It promises to exit 0 on every input, and a
    mode that gates by accident is worse than one that never reports."""
    print("\n[deleted-since] a bad ref, a first commit, and an undecodable old version")
    repo = new_repo("deleted-abuse")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing yet."))
    commit(repo, "init")

    res = tool(repo, "--deleted-since", "no-such-ref-anywhere")
    combined = res.stdout + res.stderr
    if res.returncode != 0:
        note("BROKEN", "a nonexistent ref made the deletion scan gate",
             f"exit {res.returncode}\n{combined[:200]}")
    elif "examined" in combined:
        ok("a nonexistent ref reports what it examined and exits 0")
    else:
        note("SILENT", "a nonexistent ref printed no denominator", combined[:200])

    # The first commit has no parent, so HEAD~1 does not resolve. Same shape,
    # different cause, and both must be survivable rather than a traceback.
    res = tool(repo, "--deleted-since", "HEAD~1")
    combined = res.stdout + res.stderr
    if "Traceback" in res.stderr:
        note("CRASH", "a first commit crashed the deletion scan", res.stderr[:300])
    elif res.returncode == 0 and "examined" in combined:
        ok("a repository with no previous commit is handled")
    else:
        note("BROKEN", "the deletion scan on a first commit",
             f"exit {res.returncode}\n{combined[:200]}")

    # An old version that is not valid UTF-8. The mode reads history, so it
    # meets bytes the working tree no longer has.
    (repo / "NEXT_SESSION.md").write_bytes(b"# S\n\nCaf\xe9 \xff\xfe broken\n")
    commit(repo, "latin-1 in history")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Repaired."))
    commit(repo, "repair")
    res = tool(repo, "--deleted-since", "HEAD~1")
    if "Traceback" in res.stderr:
        note("CRASH", "an undecodable previous version crashed the scan",
             res.stderr[:300])
    elif res.returncode == 0:
        ok("an undecodable previous version is survived")
    else:
        note("BROKEN", "an undecodable previous version gated",
             f"exit {res.returncode}")


def main() -> int:
    ARENA.mkdir(parents=True, exist_ok=True)
    probes = [p_empty_repo, p_detached_head, p_no_git_at_all, p_binary_document,
              p_large_document, p_pathological_regex, p_claims_in_code_fences,
              p_case_sensitivity, p_symlink, p_wrong_entry_header,
              p_argument_injection, p_deleting_the_claim,
              p_pattern_that_matches_nothing, p_library_link_base,
              p_consistency_abuse, p_search_abuse, p_suggest_fixes_abuse,
              p_config_discovery_abuse,
              p_baseline_forgives_a_repaste,
              p_baseline_failure_modes, p_baseline_theatre,
              p_sarif_stdout_purity, p_github_annotation_injection,
              p_offline, p_install_over_existing_agent_files,
              p_sweep_nothing_to_sweep, p_sweep_unreadable_file,
              p_sweep_gates_only_on_configured, p_sweep_sarif_purity,
              p_sweep_site_config_that_is_a_directory,
              p_deleted_since_abuse]
    for probe in probes:
        try:
            probe()
        except Exception as exc:                                # noqa: BLE001
            note("HARNESS", probe.__name__, f"probe itself raised {exc!r}")

    print("\n" + "=" * 66)
    total = len(CLEAN) + len(ISSUES)
    print(f"{len(probes)} probes, {total} observations: {len(CLEAN)} clean, "
          f"{len(ISSUES)} flagged")
    if ISSUES:
        print("\nFLAGGED:")
        for sev, probe, _ in ISSUES:
            print(f"  {sev:<10} {probe}")

    raised = {probe for _, probe, _ in ISSUES}
    unexpected = sorted(raised - EXPECTED - TOLERATED)
    missing = sorted(EXPECTED - raised)

    # The denominator. Without it a run that probed nothing at all prints the
    # same reassuring summary as a run that probed everything and found it
    # sound, which is the failure this whole project is about.
    print(f"\nchecked {len(raised)} distinct flags against {len(EXPECTED)} "
          f"expected and {len(TOLERATED)} tolerated: "
          f"{len(unexpected)} new, {len(missing)} missing")

    if unexpected:
        print("\nNEW - never accepted, so this run fails:")
        for probe in unexpected:
            print(f"  {probe}")
    if missing:
        print("\nMISSING - an accepted flag stopped appearing. Either the "
              "behaviour was fixed, in which case delete it from EXPECTED, or "
              "its probe stopped exercising anything:")
        for probe in missing:
            print(f"  {probe}")

    return 1 if (unexpected or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
