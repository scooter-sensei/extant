"""End-to-end scenario matrix for handoff-validator.

Builds a fresh repository per scenario, installs the tool from the COMMITTED
package state, and asserts what should happen. Each check states its
expectation, so a scenario that silently does nothing is distinguishable from
one that passed - the same reason the tool itself reports denominators.

Run against a `git archive HEAD` extract, not the working tree, so what is
tested is what would actually be pushed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PKG = Path(sys.argv[1])          # extracted package
ARENA = Path(sys.argv[2])        # where scenario repos get built
PY = sys.executable

PASS, FAIL = [], []


def sh(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def git(repo: Path, *args: str) -> str:
    return sh(repo, "git", *args).stdout


def new_repo(name: str, trunk: str = "main") -> Path:
    repo = ARENA / name
    if repo.exists():
        shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    sh(repo, "git", "init", "-q", "-b", trunk)
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "T")
    return repo


def write(repo: Path, rel: str, text: str, *, crlf: bool = False) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    # HARNESS BUG, fixed: newline="\r\n" translates the \n inside a literal
    # "\r\n" as well, producing "\r\r\n" and doubling every downstream line
    # count. newline="" writes the string's own endings verbatim.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text if crlf else text.replace("\r\n", "\n"))


def commit(repo: Path, message: str) -> str:
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", message)
    return git(repo, "rev-parse", "--short", "HEAD").strip()


def install(repo: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return sh(repo, PY, str(PKG / "plugin/skills/handoff/install.py"),
              "--repo", str(repo), *extra, check=False)


def tool(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return sh(repo, PY, str(repo / "tools/handoff_collect.py"),
              "--repo", str(repo), *args, check=False)


def check(scenario: str, label: str, condition: bool, evidence: str = "") -> None:
    (PASS if condition else FAIL).append(f"{scenario}: {label}")
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark} {label}")
    if not condition and evidence:
        for line in evidence.strip().splitlines()[:6]:
            print(f"         | {line}")


# --------------------------------------------------------------------------
def s1_node_master_status() -> None:
    """A JavaScript project: master trunk, STATUS.md, npm test, no Python."""
    name = "s1-node"
    print(f"\n[{name}] Node project, master trunk, STATUS.md")
    repo = new_repo(name, trunk="master")
    write(repo, "package.json", '{"name":"app","scripts":{"test":"jest"}}\n')
    write(repo, "STATUS.md",
          "# Status\n\n## Release 3 - checkout (shipped, 2026-07-01)\n\n"
          "Shipped at `deadbeef1234567`.\n\n## 1. Reference\n")
    commit(repo, "chore: init")

    out = install(repo)
    check(name, "installer succeeded", out.returncode == 0, out.stdout + out.stderr)
    cfg = (repo / ".handoff.toml").read_text(encoding="utf-8")
    check(name, "derived trunk=master", 'trunk = "master"' in cfg, cfg)
    check(name, "derived handoff_doc=STATUS.md", 'handoff_doc = "STATUS.md"' in cfg, cfg)
    check(name, "derived entry_prefix from '## Release'",
          "## Release" in cfg, cfg)

    cmd = (repo / ".claude/commands/handoff.md").read_text(encoding="utf-8")
    check(name, "slash command names this project, not the source",
          "Cerene" not in cmd and "NEXT_SESSION" not in cmd and name in cmd)

    res = tool(repo, "--validate", "STATUS.md")
    check(name, "dead SHA reported", "dead-sha" in res.stdout, res.stdout)
    check(name, "exit 1 on a false claim", res.returncode == 1)

    # A JS project sets a non-Python suite command; the tool must not demand
    # an interpreter it was never told to use.
    with open(repo / ".handoff.toml", "a", encoding="utf-8") as fh:
        fh.write('suite_command = ["npm", "test"]\n')
    res = tool(repo, "--collect", "--out", str(repo / "b.json"),
               "--suite-json", str(repo / "suite.json"))
    write(repo, "suite.json", '{"passed": 12, "failed": 0, "duration_s": 3}')
    res = tool(repo, "--collect", "--out", str(repo / "b.json"),
               "--suite-json", str(repo / "suite.json"))
    check(name, "collect works with a JS suite command + supplied result",
          res.returncode == 0 and (repo / "b.json").exists(), res.stdout + res.stderr)
    bundle = json.loads((repo / "b.json").read_text(encoding="utf-8"))
    check(name, "bundle records the suite as supplied, not measured",
          bundle.get("suite", {}).get("source") == "supplied", json.dumps(bundle.get("suite", {})))


# --------------------------------------------------------------------------
def s2_release_tags() -> None:
    """A project that claims releases by tag: the CHANGELOG shape."""
    name = "s2-tags"
    print(f"\n[{name}] release-tag claims, real and false")
    repo = new_repo(name)
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - base (shipped, 2026-01-01)\n\nBase.\n\n## 1. Ref\n")
    commit(repo, "chore: init")
    sh(repo, "git", "tag", "v1.0")
    install(repo)

    write(repo, "NEXT_SESSION.md",
          "# Status\n\n## Phase 2 - now (in progress, 2026-07-01)\n\n"
          "Released in v1.0 already.\nAlso released in v9.9 supposedly.\n\n## 1. Ref\n")
    commit(repo, "docs: claims")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    check(name, "real tag v1.0 not flagged", "v1.0`, but no such tag" not in res.stdout, res.stdout)
    check(name, "phantom tag v9.9 flagged",
          "dead-release-tag" in res.stdout and "v9.9" in res.stdout, res.stdout)

    # A tag that exists but never reached trunk.
    sh(repo, "git", "checkout", "-q", "-b", "abandoned")
    write(repo, "x.txt", "x\n")
    commit(repo, "feat: never merged")
    sh(repo, "git", "tag", "v2.0")
    sh(repo, "git", "checkout", "-q", "main")
    write(repo, "NEXT_SESSION.md",
          "# Status\n\n## Phase 3 - now (in progress, 2026-07-02)\n\n"
          "Released in v2.0 last week.\n\n## 1. Ref\n")
    commit(repo, "docs: claim v2.0")
    res = tool(repo, "--validate", "NEXT_SESSION.md")
    check(name, "tag that never reached trunk is flagged",
          "not an ancestor" in res.stdout, res.stdout)


# --------------------------------------------------------------------------
def s3_ticket_branches() -> None:
    """A team using ticket-prefixed branches on develop."""
    name = "s3-tickets"
    print(f"\n[{name}] ticket branches (ABC-123) on develop")
    repo = new_repo(name, trunk="develop")
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nx\n\n## 1. Ref\n")
    commit(repo, "ABC-1: init")
    for n in range(2, 8):
        sh(repo, "git", "branch", f"ABC-{n}-work")
        write(repo, f"f{n}.txt", "x\n")
        commit(repo, f"ABC-{n}: work")

    out = install(repo)
    cfg = (repo / ".handoff.toml").read_text(encoding="utf-8")
    check(name, "derived trunk=develop", 'trunk = "develop"' in cfg, cfg)
    check(name, "detected the ticket convention",
          "ABC" in cfg or "phase_task" in out.stdout, out.stdout + cfg)


# --------------------------------------------------------------------------
def s4_no_document() -> None:
    """A team whose state lives in a tracker: no handoff document at all."""
    name = "s4-nodoc"
    print(f"\n[{name}] no handoff document anywhere")
    repo = new_repo(name)
    write(repo, "README.md", "# app\n")
    commit(repo, "chore: init")

    out = install(repo)
    check(name, "installer refuses rather than inventing a document",
          out.returncode == 1, out.stdout)
    check(name, "and says why", "no handoff document" in out.stdout.lower(), out.stdout)
    check(name, "no config written", not (repo / ".handoff.toml").exists())


# --------------------------------------------------------------------------
def s5_extra_docs() -> None:
    """CLAUDE.md and AGENTS.md checked alongside the status document."""
    name = "s5-extra"
    print(f"\n[{name}] extra_docs: CLAUDE.md and AGENTS.md")
    repo = new_repo(name)
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n\n## 1. Ref\n")
    write(repo, "CLAUDE.md", "# Guide\n\nSee [design](docs/gone.md).\nCommit `abcdef1234567`.\n")
    write(repo, "AGENTS.md", "# Agents\n\nJump to [nope](#no-such-heading).\n")
    commit(repo, "chore: init")
    install(repo)
    with open(repo / ".handoff.toml", "a", encoding="utf-8") as fh:
        fh.write('extra_docs = ["CLAUDE.md", "AGENTS.md"]\n')

    res = tool(repo, "--verify")
    check(name, "CLAUDE.md dead link found", "CLAUDE.md" in res.stdout and "dead-md-link" in res.stdout, res.stdout)
    check(name, "CLAUDE.md dead sha found", "dead-sha" in res.stdout, res.stdout)
    check(name, "AGENTS.md dead anchor found", "dead-md-anchor" in res.stdout, res.stdout)
    check(name, "exit 1", res.returncode == 1)

    # A configured document that is absent must be a finding, not a shrug.
    with open(repo / ".handoff.toml", "a", encoding="utf-8") as fh:
        fh.write('')
    cfgtext = (repo / ".handoff.toml").read_text(encoding="utf-8").replace(
        'extra_docs = ["CLAUDE.md", "AGENTS.md"]', 'extra_docs = ["MISSING.md"]')
    (repo / ".handoff.toml").write_text(cfgtext, encoding="utf-8")
    res = tool(repo, "--verify")
    check(name, "missing extra_doc reported", "missing-document" in res.stdout, res.stdout)


# --------------------------------------------------------------------------
def s6_everything_broken() -> None:
    """Every rule that can fire, firing at once."""
    name = "s6-broken"
    print(f"\n[{name}] every rule firing")
    repo = new_repo(name)
    write(repo, "docs/plan.md", "# plan\n")
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - base (shipped, 2026-01-01)\n\nbase\n\n## 1. Ref\n")
    base = commit(repo, "chore: init")
    sh(repo, "git", "checkout", "-q", "-b", "feature/open")
    write(repo, "w.txt", "w\n")
    off = commit(repo, "feat: off trunk")
    sh(repo, "git", "checkout", "-q", "main")
    install(repo)
    # HARNESS BUG, fixed: the installer already writes branch_token, and TOML
    # refuses a duplicate key. Drop its line before adding our own rather than
    # appending a second definition.
    cfg = (repo / ".handoff.toml").read_text(encoding="utf-8")
    cfg = "\n".join(ln for ln in cfg.splitlines()
                    if not ln.startswith("branch_token"))
    cfg += ("\nlive_phrases = 'NOT yet merged'\n"
            "branch_token = '`((?:feature|claude)/[^`]+)`'\n")
    (repo / ".handoff.toml").write_text(cfg, encoding="utf-8")

    write(repo, "NEXT_SESSION.md",
          "# Status\n\n## Phase 2 - now (in progress, 2026-07-01)\n\n"
          f"Merged to `main` at `{off}`.\n"                       # false-merge
          "Reference `0000000000000000000000000000000000000000`.\n"  # dead-sha
          "**Design:** `docs/absent.md`\n"                        # dead-path
          "See [plan](docs/absent2.md).\n"                        # dead-md-link
          "Jump to [x](#no-such-heading).\n"                      # dead-md-anchor
          "Work is NOT yet merged on `feature/phantom`.\n"        # unknown-branch
          "Released in v9.9 supposedly.\n"                        # dead-release-tag
          "Token sk-A1b2C3d4E5f6G7h8I9j0K1l2m3\n"                 # secret
          "\n## 1. Ref\n")
    commit(repo, "docs: many claims")

    res = tool(repo, "--validate", "NEXT_SESSION.md")
    kinds = {"dead-sha", "false-merge-claim", "dead-path-pointer", "dead-md-link",
             "dead-md-anchor", "unknown-branch", "dead-release-tag", "possible-secret"}
    found = {k for k in kinds if k in res.stdout}
    check(name, f"all 8 rule kinds fired (got {len(found)}/8: {sorted(found)})",
          found == kinds, res.stdout)
    check(name, "exit 1", res.returncode == 1)

    gh = tool(repo, "--validate", "NEXT_SESSION.md", "--format=github")
    ann = [ln for ln in gh.stdout.splitlines() if ln.startswith("::error")]
    check(name, f"github annotations emitted ({len(ann)})", len(ann) >= 8, gh.stdout)

    sa = tool(repo, "--validate", "NEXT_SESSION.md", "--format=sarif")
    try:
        doc = json.loads(sa.stdout)
        ok = len(doc["runs"][0]["results"]) >= 8
    except Exception as exc:                                    # noqa: BLE001
        ok, doc = False, str(exc)
    check(name, "sarif parses with all results", ok, sa.stdout[:400])

    st = tool(repo, "--selftest")
    check(name, "selftest: no rule stayed silent",
          "0 stayed silent" in st.stdout, st.stdout)


# --------------------------------------------------------------------------
def s7_clean_project() -> None:
    """Everything true. The tool must be quiet and exit 0."""
    name = "s7-clean"
    print(f"\n[{name}] every claim true")
    repo = new_repo(name)
    write(repo, "docs/plan.md", "# plan\n")
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - base (shipped, 2026-01-01)\n\nbase\n\n## 1. Ref\n")
    base = commit(repo, "chore: init")
    install(repo)
    write(repo, "NEXT_SESSION.md",
          "# Status\n\n## Phase 2 - now (in progress, 2026-07-01)\n\n"
          f"Merged to `main` at `{base}`.\n"
          "**Design:** `docs/plan.md`\n"
          "See [plan](docs/plan.md) and [ref](#1-ref).\n"
          "\n## 1. Ref\n")
    commit(repo, "docs: true claims")

    res = tool(repo, "--validate", "NEXT_SESSION.md")
    findings = [ln for ln in res.stdout.splitlines() if ln.startswith("line ")]
    check(name, f"no findings on a true document (got {len(findings)})",
          not findings, res.stdout)
    check(name, "exit 0", res.returncode == 0, res.stdout)
    check(name, "denominator still reported", "checked NEXT_SESSION.md" in res.stdout, res.stdout)


# --------------------------------------------------------------------------
def s8_crlf_and_nested() -> None:
    """A Windows-authored document, nested in docs/, with relative links."""
    name = "s8-crlf"
    print(f"\n[{name}] CRLF document nested in docs/")
    repo = new_repo(name)
    write(repo, "docs/design.md", "# design\r\n", crlf=True)
    write(repo, "docs/HANDOFF.md",
          "# Status\r\n\r\n## Phase 1 - x (in progress, 2026-01-01)\r\n\r\n"
          "See [design](design.md).\r\n"          # relative to the DOC, resolves
          "See [gone](absent.md).\r\n"            # relative to the DOC, missing
          "\r\n## 1. Ref\r\n", crlf=True)
    commit(repo, "chore: init")
    out = install(repo)
    cfg = (repo / ".handoff.toml").read_text(encoding="utf-8")
    check(name, "found the nested document",
          "docs/HANDOFF.md" in cfg, out.stdout + cfg)

    res = tool(repo, "--verify")
    check(name, "sibling link resolves (relative to the document)",
          "design.md`, which does not exist" not in res.stdout, res.stdout)
    check(name, "missing sibling reported", "absent.md" in res.stdout, res.stdout)
    line_ok = any(ln.startswith("line 6:") for ln in res.stdout.splitlines())
    check(name, "line number correct despite CRLF", line_ok, res.stdout)


# --------------------------------------------------------------------------
def s9_worktree() -> None:
    """Validation from inside a linked worktree, where phase work happens."""
    name = "s9-worktree"
    print(f"\n[{name}] linked git worktree")
    repo = new_repo(name)
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
                                   "Reference `0000000000000000000000000000000000000000`.\n\n## 1. Ref\n")
    commit(repo, "chore: init")
    install(repo)
    commit(repo, "chore: install")
    wt = ARENA / f"{name}-wt"
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    sh(repo, "git", "worktree", "add", "-q", str(wt), "-b", "feature/work")

    res = sh(wt, PY, str(wt / "tools/handoff_collect.py"), "--repo", str(wt),
             "--validate", "NEXT_SESSION.md", check=False)
    check(name, "runs inside a worktree", res.returncode in (0, 1), res.stdout + res.stderr)
    check(name, "finds the dead SHA there too", "dead-sha" in res.stdout, res.stdout)
    sh(repo, "git", "worktree", "remove", "--force", str(wt), check=False)


# --------------------------------------------------------------------------
def s10_archive_roundtrip() -> None:
    """Archiving must conserve content and keep validating what it moved."""
    name = "s10-archive"
    print(f"\n[{name}] archive round-trip")
    repo = new_repo(name)
    entries = "".join(
        f"## Phase {n} - work {n} (shipped, 2026-0{n}-01)\n\n"
        f"Entry {n} body with `000000000000000000000000000000000000000{n}`.\n\n"
        for n in range(1, 7)
    )
    write(repo, "NEXT_SESSION.md", f"# Status\n\n{entries}## 1. Ref\n\nReference material.\n")
    commit(repo, "chore: init")
    install(repo)
    before = (repo / "NEXT_SESSION.md").read_text(encoding="utf-8")

    res = tool(repo, "--archive")
    check(name, "archive ran", res.returncode == 0, res.stdout + res.stderr)
    check(name, "reported retained/archived counts",
          "retained=" in res.stdout and "archived=" in res.stdout, res.stdout)

    after = (repo / "NEXT_SESSION.md").read_text(encoding="utf-8")
    archive_path = repo / "docs/handoff-archive.md"
    if not archive_path.exists():
        archive_path = repo / "handoff-archive.md"
    arch = archive_path.read_text(encoding="utf-8") if archive_path.exists() else ""
    check(name, "archive file created", bool(arch), str(list(repo.glob("**/*archive*"))))
    kept = after.count("## Phase ")
    check(name, f"live document trimmed to the cap (kept {kept})", kept == 3, after[:300])
    for n in range(1, 7):
        marker = f"Entry {n} body"
        check(name, f"entry {n} conserved (live or archive)",
              marker in after or marker in arch)
    check(name, "reference section never archived", "## 1. Ref" in after, after[-200:])

    res = tool(repo, "--verify")
    check(name, "archived content still validated",
          "handoff-archive" in res.stdout or "archive" in res.stdout.lower(), res.stdout)


# --------------------------------------------------------------------------
def s11_hooks() -> None:
    """The git hooks, installed and actually firing.

    The trunk guard is OPT-IN, so both halves of that promise are asserted
    here: a default install must be incapable of blocking a commit, and
    `--with-trunk-guard` must actually block one. Checking only the second half
    is what this scenario used to do, and it kept passing after the default
    changed underneath it - the assertion was for the old contract, so it went
    red for the right reason and had to be rewritten rather than re-flagged.
    """
    name = "s11-hooks"
    print(f"\n[{name}] git hooks")
    repo = new_repo(name)
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
                                   "Reference `0000000000000000000000000000000000000000`.\n\n## 1. Ref\n")
    commit(repo, "chore: init")
    install(repo)
    out = sh(repo, "sh", "tools/hooks/install", check=False)
    combined = out.stdout + out.stderr
    check(name, "hook installer ran", out.returncode == 0, combined)
    check(name, "post-commit wired", (repo / ".git/hooks/post-commit").exists())
    check(name, "post-merge wired", (repo / ".git/hooks/post-merge").exists())
    check(name, "default install wires NO blocking hook",
          not (repo / ".git/hooks/pre-commit").exists(), combined)
    check(name, "default names the flag that would add the guard",
          "--with-trunk-guard" in out.stdout, combined)

    write(repo, "x.txt", "x\n")
    sh(repo, "git", "add", "-A")
    res = sh(repo, "git", "commit", "-m", "chore: trigger hooks", check=False)
    combined = res.stdout + res.stderr
    check(name, "commit on trunk allowed", res.returncode == 0, combined)
    check(name, "post-commit reported the false claim", "[handoff]" in combined, combined)

    # Off trunk in the main tree, guard NOT installed: must be allowed through.
    sh(repo, "git", "checkout", "-q", "-b", "topic")
    write(repo, "y.txt", "y\n")
    sh(repo, "git", "add", "-A")
    res = sh(repo, "git", "commit", "-m", "chore: off trunk, unguarded", check=False)
    check(name, "off-trunk commit allowed while the guard is not installed",
          res.returncode == 0, res.stdout + res.stderr)

    # Opt in, and the identical commit must now be refused.
    out = sh(repo, "sh", "tools/hooks/install", "--with-trunk-guard", check=False)
    combined = out.stdout + out.stderr
    check(name, "opt-in installer ran", out.returncode == 0, combined)
    check(name, "opt-in wires the guard", (repo / ".git/hooks/pre-commit").exists(), combined)
    check(name, "opt-in says plainly that it can block",
          "CAN BLOCK A COMMIT" in out.stdout, combined)

    write(repo, "z.txt", "z\n")
    sh(repo, "git", "add", "-A")
    res = sh(repo, "git", "commit", "-m", "chore: off trunk in main tree", check=False)
    check(name, "guard BLOCKS an off-trunk commit in the main tree",
          res.returncode != 0 and "BLOCKED" in (res.stdout + res.stderr),
          res.stdout + res.stderr)

    # A misspelled flag must not quietly install the advisory set and imply the
    # guard came with it.
    out = sh(repo, "sh", "tools/hooks/install", "--with-trunk-gaurd", check=False)
    check(name, "a misspelled flag is refused, not ignored",
          out.returncode == 2, out.stdout + out.stderr)


# --------------------------------------------------------------------------
def s12_empty_repo() -> None:
    """A repository with a document and no history to speak of."""
    name = "s12-minimal"
    print(f"\n[{name}] single-commit repository")
    repo = new_repo(name)
    write(repo, "NEXT_SESSION.md", "# Status\n\n## Phase 1 - x (in progress, 2026-01-01)\n\nNothing.\n\n## 1. Ref\n")
    commit(repo, "init")
    out = install(repo)
    check(name, "installer copes with minimal history", out.returncode == 0, out.stdout)
    res = tool(repo, "--verify")
    check(name, "verify exits 0 on an honest empty document", res.returncode == 0, res.stdout)
    check(name, "blind rules named rather than hidden", "NOTE:" in res.stdout, res.stdout)
    st = tool(repo, "--selftest")
    check(name, "selftest reports nothing silently broken",
          "stayed silent" in st.stdout, st.stdout)


# Counted, never spelled out. The README beside this file claimed "Three tools"
# for two commits after the fourth and fifth arrived, and this line said
# "12 scenarios" as a literal - a hand-maintained denominator in a harness whose
# job is to make hand-maintained numbers untrustworthy.
SCENARIOS = (s1_node_master_status, s2_release_tags, s3_ticket_branches,
             s4_no_document, s5_extra_docs, s6_everything_broken,
             s7_clean_project, s8_crlf_and_nested, s9_worktree,
             s10_archive_roundtrip, s11_hooks, s12_empty_repo)


def main() -> int:
    ARENA.mkdir(parents=True, exist_ok=True)
    for fn in SCENARIOS:
        try:
            fn()
        except Exception as exc:                                # noqa: BLE001
            FAIL.append(f"{fn.__name__}: raised {exc!r}")
            print(f"  FAIL {fn.__name__} raised {exc!r}")

    total = len(PASS) + len(FAIL)
    print(f"\n{'=' * 62}")
    print(f"{len(SCENARIOS)} scenarios, {total} assertions: "
          f"{len(PASS)} passed, {len(FAIL)} FAILED")
    if FAIL:
        print("\nFAILURES:")
        for f in FAIL:
            print(f"  - {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
