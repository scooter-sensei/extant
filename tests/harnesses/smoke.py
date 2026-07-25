"""Adversarial smoke test: try to break handoff-validator.

Not a confirmation pass. Each probe attempts a specific abuse or edge case and
reports what actually happened, so a loophole shows up as a finding rather than
as an absence of noise.

Categories: crash robustness, false positives, false negatives (gaming), and
cross-platform divergence.
"""
from __future__ import annotations

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


def note(severity: str, probe: str, detail: str) -> None:
    ISSUES.append((severity, probe, detail))
    print(f"  {severity:<8} {probe}")
    for line in detail.strip().splitlines()[:4]:
        print(f"           | {line}")


def ok(probe: str, detail: str = "") -> None:
    CLEAN.append(probe)
    print(f"  ok       {probe}" + (f"  ({detail})" if detail else ""))


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
    shutil.copytree(PKG / "plugin/skills/handoff/payload", repo / "tools")
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
    return sh(repo, PY, str(repo / "tools/handoff_collect.py"),
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
    shutil.copytree(PKG / "plugin/skills/handoff/payload", d / "tools")
    write(d, "NEXT_SESSION.md", ENTRY.format("Reference `0000000000000000000000000000000000000000`."))
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
    write(repo, ".handoff.toml", "branch_token = '`((a+)+b)`'\n")
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
        "Merged to `main` at `0000000000000000000000000000000000000000`.\n"
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
    write(repo, ".handoff.toml", "branch_token = '`([\\w.-]+/[^`]+)`'\n")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "Work is on `--output=/tmp/pwned/x`."))
    commit(repo, "init")
    res = tool(repo, "--validate", "NEXT_SESSION.md", timeout=60)
    leaked = Path("/tmp/pwned").exists()
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
        "Reference `0000000000000000000000000000000000000000`."))
    commit(repo, "init")
    before = tool(repo, "--validate", "NEXT_SESSION.md")
    write(repo, "NEXT_SESSION.md", ENTRY.format("Nothing to see."))
    after = tool(repo, "--validate", "NEXT_SESSION.md")
    if before.returncode == 1 and after.returncode == 0:
        note("BY-DESIGN", "deleting a claim makes the document pass",
             "documented and mitigated only by the /handoff workflow reporting "
             "first-run findings; the validator alone cannot tell repair from "
             "erasure")
    else:
        ok("claim deletion", f"{before.returncode} -> {after.returncode}")


def p_pattern_that_matches_nothing() -> None:
    print("\n[gaming] a config whose patterns match nothing")
    repo = new_repo("blind")
    write(repo, ".handoff.toml",
          "merge_claim = 'ZZZZ_NEVER_MATCHES_{trunk}'\n"
          "path_pointer = 'ZZZZ_NEVER'\n")
    write(repo, "NEXT_SESSION.md", ENTRY.format(
        "Merged to `main` at `0000000000000000000000000000000000000000`.\n"
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
        "import handoff_collect as h, pathlib\n"
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


def main() -> int:
    ARENA.mkdir(parents=True, exist_ok=True)
    probes = [p_empty_repo, p_detached_head, p_no_git_at_all, p_binary_document,
              p_large_document, p_pathological_regex, p_claims_in_code_fences,
              p_case_sensitivity, p_symlink, p_wrong_entry_header,
              p_argument_injection, p_deleting_the_claim,
              p_pattern_that_matches_nothing, p_library_link_base]
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
