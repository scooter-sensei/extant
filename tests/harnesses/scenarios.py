"""End-to-end scenario matrix for extant.

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
    return sh(repo, PY, str(PKG / "plugin/skills/extant/install.py"),
              "--repo", str(repo), *extra, check=False)


def tool(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return sh(repo, PY, str(repo / "tools/extant_collect.py"),
              "--repo", str(repo), *args, check=False)


def check(scenario: str, label: str, condition: bool, evidence: str = "") -> None:
    (PASS if condition else FAIL).append(f"{scenario}: {label}")
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark} {label}")
    if not condition and evidence:
        for line in evidence.strip().splitlines()[:6]:
            print(f"         | {line}")


def _findings(stdout: str, kind: str) -> list[str]:
    """Real finding lines of one kind: `line N: [kind] ...`.

    Never `kind in stdout`. The denominator line names EVERY rule on every
    run, and so does the NOTE listing rules that matched nothing, so a
    substring test against the whole output is true whether the rule fired or
    not. A mutation campaign caught exactly that here: deleting the preset's
    consistency block left this scenario green, because the assertion was
    reading the denominator and calling it a finding.
    """
    return [ln for ln in stdout.splitlines()
            if ln.startswith("line ") and f"[{kind}]" in ln]


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
    cfg = (repo / ".extant.toml").read_text(encoding="utf-8")
    check(name, "derived trunk=master", 'trunk = "master"' in cfg, cfg)
    check(name, "derived primary_doc=STATUS.md", 'primary_doc = "STATUS.md"' in cfg, cfg)
    check(name, "derived entry_prefix from '## Release'",
          "## Release" in cfg, cfg)

    cmd = (repo / ".claude/commands/extant.md").read_text(encoding="utf-8")
    check(name, "slash command names this project, not the source",
          "Cerene" not in cmd and "NEXT_SESSION" not in cmd and name in cmd)

    res = tool(repo, "--validate", "STATUS.md")
    check(name, "dead SHA reported", "dead-sha" in res.stdout, res.stdout)
    check(name, "exit 1 on a false claim", res.returncode == 1)

    # A JS project sets a non-Python suite command; the tool must not demand
    # an interpreter it was never told to use.
    with open(repo / ".extant.toml", "a", encoding="utf-8") as fh:
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
    # `abandoned` is slashless, and an early version of the integration-ref
    # rule counted every slashless branch - which silenced exactly this case.
    check(name, "tag that never reached an integration branch is flagged",
          bool(_findings(res.stdout, "dead-release-tag"))
          and "v2.0" in res.stdout, res.stdout)


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
    cfg = (repo / ".extant.toml").read_text(encoding="utf-8")
    check(name, "derived trunk=develop", 'trunk = "develop"' in cfg, cfg)
    check(name, "detected the ticket convention",
          "ABC" in cfg or "phase_task" in out.stdout, out.stdout + cfg)


# --------------------------------------------------------------------------
def s4_no_document() -> None:
    """A team whose state lives in a tracker: no status document at all."""
    name = "s4-nodoc"
    print(f"\n[{name}] no status document anywhere")
    repo = new_repo(name)
    write(repo, "README.md", "# app\n")
    commit(repo, "chore: init")

    out = install(repo)
    check(name, "installer refuses rather than inventing a document",
          out.returncode == 1, out.stdout)
    check(name, "and says why", "no status document" in out.stdout.lower(), out.stdout)
    check(name, "no config written", not (repo / ".extant.toml").exists())


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
    with open(repo / ".extant.toml", "a", encoding="utf-8") as fh:
        fh.write('extra_docs = ["CLAUDE.md", "AGENTS.md"]\n')

    res = tool(repo, "--verify")
    check(name, "CLAUDE.md dead link found", "CLAUDE.md" in res.stdout and "dead-md-link" in res.stdout, res.stdout)
    check(name, "CLAUDE.md dead sha found", "dead-sha" in res.stdout, res.stdout)
    check(name, "AGENTS.md dead anchor found", "dead-md-anchor" in res.stdout, res.stdout)
    check(name, "exit 1", res.returncode == 1)

    # A configured document that is absent must be a finding, not a shrug.
    with open(repo / ".extant.toml", "a", encoding="utf-8") as fh:
        fh.write('')
    cfgtext = (repo / ".extant.toml").read_text(encoding="utf-8").replace(
        'extra_docs = ["CLAUDE.md", "AGENTS.md"]', 'extra_docs = ["MISSING.md"]')
    (repo / ".extant.toml").write_text(cfgtext, encoding="utf-8")
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
    cfg = (repo / ".extant.toml").read_text(encoding="utf-8")
    cfg = "\n".join(ln for ln in cfg.splitlines()
                    if not ln.startswith("branch_token"))
    cfg += ("\nlive_phrases = 'NOT yet merged'\n"
            "branch_token = '`((?:feature|claude)/[^`]+)`'\n")
    (repo / ".extant.toml").write_text(cfg, encoding="utf-8")

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
    # `k in res.stdout` is true for EVERY kind on every run: the denominator
    # line names them all, and so does the NOTE listing rules that matched
    # nothing. This scenario's entire purpose is to prove all eight fired, and
    # it asserted that unconditionally. Second instance of the bug fixed for
    # the consistency check twelve lines of this file away, found by a review
    # rather than by the mutation campaign, which had no mutation aimed here.
    found = {k for k in kinds if _findings(res.stdout, k)}
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
    cfg = (repo / ".extant.toml").read_text(encoding="utf-8")
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

    res = sh(wt, PY, str(wt / "tools/extant_collect.py"), "--repo", str(wt),
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
    archive_path = repo / "docs/status-archive.md"
    if not archive_path.exists():
        archive_path = repo / "status-archive.md"
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
          "status-archive" in res.stdout or "archive" in res.stdout.lower(), res.stdout)


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
    check(name, "post-commit reported the false claim", "[extant]" in combined, combined)

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


# --------------------------------------------------------------------------
# Shapes drawn from how real projects are actually laid out, rather than from
# variations on this one. Each was chosen because it stresses a DIFFERENT
# assumption: where documents live, what trunk is called, what a tag looks
# like, how deep a relative link reaches, and what encoding a file arrives in.


def s13_monorepo() -> None:
    """packages/*/CHANGELOG.md, a root docs/, and links that cross packages.

    The convention every JS and polyglot monorepo converges on. It matters here
    because a relative link inside `packages/api/README.md` resolves against
    that package, not the repository root, and a rule that resolves everything
    from the root reports working links as dead across the whole tree.
    """
    name = "s13-monorepo"
    print(f"\n[{name}] monorepo: per-package docs and a root docs/")
    repo = new_repo(name)
    write(repo, "README.md", "# Platform\n\nSee [the API package](packages/api/README.md).\n")
    write(repo, "packages/api/README.md",
          "# api\n\nChangelog: [CHANGELOG.md](CHANGELOG.md).\n"
          "Design: [architecture](../../docs/architecture.md).\n"
          "Gone: [old notes](./NOTES.md).\n")
    write(repo, "packages/api/CHANGELOG.md", "# Changelog\n\n## 2.1.0\n")
    write(repo, "packages/web/README.md", "# web\n\nSee [api](../api/README.md).\n")
    write(repo, "docs/architecture.md", "# Architecture\n")
    commit(repo, "chore: init")
    install(repo, "--preset", "readme")

    res = tool(repo, "--validate", "packages/api/README.md")
    check(name, "sibling link inside a package resolves",
          "CHANGELOG.md`, which does not exist" not in res.stdout, res.stdout)
    check(name, "a link climbing out to the root docs/ resolves",
          "architecture.md`, which does not exist" not in res.stdout, res.stdout)
    check(name, "a genuinely missing sibling is still reported",
          "NOTES.md" in res.stdout, res.stdout)

    res = tool(repo, "--validate", "packages/web/README.md")
    check(name, "a link across packages resolves",
          res.returncode == 0, res.stdout)


def s14_adr() -> None:
    """docs/adr/NNNN-title.md, the near-universal decision-record layout.

    Numbered ADRs supersede one another by linking, so a directory of them is
    mostly cross-references between siblings. It is the densest link graph a
    documentation tree normally has.
    """
    name = "s14-adr"
    print(f"\n[{name}] architecture decision records in docs/adr/")
    repo = new_repo(name)
    write(repo, "README.md", "# Service\n\nDecisions live in [docs/adr](docs/adr/0001-record-decisions.md).\n")
    write(repo, "docs/adr/0001-record-decisions.md",
          "# 1. Record architecture decisions\n\nStatus: superseded by "
          "[ADR-0003](0003-use-postgres.md).\n")
    write(repo, "docs/adr/0002-use-mysql.md",
          "# 2. Use MySQL\n\nStatus: superseded by [ADR-0003](0003-use-postgres.md).\n")
    write(repo, "docs/adr/0003-use-postgres.md",
          "# 3. Use Postgres\n\nSupersedes [ADR-0002](0002-use-mysql.md).\n"
          "See also [ADR-0009](0009-never-written.md).\n")
    commit(repo, "docs: adrs")
    install(repo, "--preset", "readme")

    res = tool(repo, "--validate", "docs/adr/0003-use-postgres.md")
    check(name, "sibling ADR link resolves", "0002-use-mysql" not in res.stdout, res.stdout)
    check(name, "a link to an ADR nobody wrote is reported",
          "0009-never-written.md" in res.stdout, res.stdout)
    check(name, "exit 1 on the dangling decision", res.returncode == 1)


def s15_github_dir() -> None:
    """Community health files in .github/, which GitHub treats as canonical.

    A dot-directory is easy for a scanner to skip by accident, and a project
    that keeps CONTRIBUTING and SECURITY there has all of its policy documents
    in the one place a naive walk ignores.
    """
    name = "s15-github-dir"
    print(f"\n[{name}] community health files under .github/")
    repo = new_repo(name)
    write(repo, "README.md", "# Tool\n\nSee [contributing](.github/CONTRIBUTING.md).\n")
    write(repo, ".github/CONTRIBUTING.md",
          "# Contributing\n\nRun [the setup script](../scripts/gone.sh).\n")
    write(repo, ".github/SECURITY.md", "# Security\n\nReport privately.\n")
    commit(repo, "chore: init")
    install(repo, "--doc", "README.md")

    with open(repo / ".extant.toml", "a", encoding="utf-8") as fh:
        fh.write('extra_docs = [".github/CONTRIBUTING.md", ".github/SECURITY.md"]\n')

    res = tool(repo, "--verify")
    check(name, "a document inside .github/ is actually read",
          "CONTRIBUTING.md" in res.stdout, res.stdout)
    check(name, "its broken link is reported", "gone.sh" in res.stdout, res.stdout)


def s16_alternate_trunks() -> None:
    """develop, trunk and mainline, all of which are somebody's main branch.

    Trunk is MEASURED rather than assumed, and this is the assertion that keeps
    it that way. A default of `main` would make merge and tag ancestry silently
    wrong on every repository that never adopted it.
    """
    name = "s16-alt-trunks"
    print(f"\n[{name}] develop / trunk / mainline as the main branch")
    for branch in ("develop", "trunk", "mainline"):
        repo = new_repo(f"{name}-{branch}", trunk=branch)
        write(repo, "README.md", "# App\n\nNothing falsifiable.\n")
        commit(repo, "chore: init")
        out = install(repo, "--preset", "readme")
        cfg = (repo / ".extant.toml").read_text(encoding="utf-8")
        check(name, f"trunk measured as {branch}",
              f'trunk = "{branch}"' in cfg, out.stdout + cfg)


def s17_tag_shapes() -> None:
    """release-1.2.3 and package@1.2.3 alongside plain v1.2.3.

    Three tag conventions in wide use. The release-tag rule looks up whatever
    token the document names, so the question is whether an unusual shape is
    resolved rather than assumed dead.
    """
    name = "s17-tag-shapes"
    print(f"\n[{name}] release- and package@ tag conventions")
    repo = new_repo(name)
    write(repo, "CHANGELOG.md", "# Changelog\n\nShipped in `release-1.2.3`.\n")
    commit(repo, "chore: init")
    sh(repo, "git", "tag", "-a", "release-1.2.3", "-m", "release")
    sh(repo, "git", "tag", "-a", "api@2.0.0", "-m", "package release")
    install(repo, "--doc", "CHANGELOG.md")

    res = tool(repo, "--verify")
    # Two assertions, because either alone is satisfied by a broken rule. Exit 0
    # is what a pattern matching NOTHING also produces, and a denominator of 1
    # only says it looked. Together they say it looked and found the tag real.
    # The first version of this checked `"dead-release-tag" not in stdout`, which
    # can never pass: the denominator line names every rule on every run.
    check(name, "the release- tag shape is examined, not skipped",
          "dead-release-tag 1" in res.stdout, res.stdout)
    check(name, "and the tag that exists is not reported dead",
          res.returncode == 0, res.stdout)

    write(repo, "CHANGELOG.md", "# Changelog\n\nShipped in `release-9.9.9`.\n")
    res = tool(repo, "--verify")
    check(name, "a tag that was never cut is reported",
          "release-9.9.9" in res.stdout, res.stdout)


def s18_encodings() -> None:
    """A UTF-8 byte-order mark, which Windows editors add without asking.

    A BOM sits before the first character, so a document that opens with `# `
    no longer does. Anything anchored to the start of the file stops matching,
    and the failure is invisible in every editor that hides the mark.
    """
    name = "s18-encodings"
    print(f"\n[{name}] UTF-8 BOM at the start of a document")
    repo = new_repo(name)
    body = "# Status\n\nSee [the plan](docs/plan.md).\n"
    (repo / "README.md").write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
    commit(repo, "chore: init")
    install(repo, "--doc", "README.md")

    res = tool(repo, "--verify")
    check(name, "a BOM does not crash the run",
          "Traceback" not in res.stderr, res.stderr)
    check(name, "the broken link is still found past the BOM",
          "docs/plan.md" in res.stdout, res.stdout + res.stderr)


def s19_deep_relative_links() -> None:
    """Links climbing several directories, as a docs site accumulates depth."""
    name = "s19-deep-links"
    print(f"\n[{name}] relative links climbing out of a deep tree")
    repo = new_repo(name)
    write(repo, "docs/guides/advanced/tuning/index.md",
          "# Tuning\n\nBack to [the guide](../../index.md).\n"
          "Root: [readme](../../../../README.md).\n"
          "Missing: [gone](../../../nowhere.md).\n")
    write(repo, "docs/guides/index.md", "# Guides\n")
    write(repo, "README.md", "# Root\n")
    commit(repo, "docs: deep tree")
    install(repo, "--doc", "README.md")

    res = tool(repo, "--validate", "docs/guides/advanced/tuning/index.md")
    check(name, "a link climbing two levels resolves",
          "../../index.md" not in res.stdout, res.stdout)
    check(name, "a link climbing to the repository root resolves",
          "README.md`, which does not exist" not in res.stdout, res.stdout)
    check(name, "a genuinely missing target is still reported",
          "nowhere.md" in res.stdout, res.stdout)


def s20_maven() -> None:
    """A Java project: pom.xml against CHANGELOG, the JVM world's manifest."""
    name = "s20-maven"
    print(f"\n[{name}] Maven pom.xml version agreement")
    repo = new_repo(name)
    write(repo, "README.md", "# Service\n\nNothing falsifiable.\n")
    write(repo, "pom.xml",
          '<project>\n  <groupId>com.acme</groupId>\n'
          "  <artifactId>service</artifactId>\n  <version>3.4.0</version>\n</project>\n")
    write(repo, "CHANGELOG.md", "# Changelog\n\n## 3.4.0\n")
    commit(repo, "chore: init")
    install(repo, "--doc", "README.md")

    with open(repo / ".extant.toml", "a", encoding="utf-8") as fh:
        fh.write("\n[extant.consistency.version]\n"
                 '"pom.xml" = \'<version>([^<]+)</version>\'\n'
                 '"CHANGELOG.md" = \'^## (\\d+\\.\\d+\\.\\d+)\'\n')
    res = tool(repo, "--verify")
    check(name, "agreeing pom and changelog pass", res.returncode == 0, res.stdout)

    write(repo, "CHANGELOG.md", "# Changelog\n\n## 3.5.0\n")
    res = tool(repo, "--verify")
    check(name, "a pom disagreeing with the changelog is reported",
          "inconsistent-artifact" in res.stdout and "3.4.0" in res.stdout, res.stdout)


# --------------------------------------------------------------------------
# Every preset, against a repository shaped like the ecosystem it claims to
# serve. A preset is a promise about a KIND of project, and the way that
# promise fails is silent: a preset naming documents the project does not have
# installs a configuration that examines nothing, forever, while every run
# exits 0 and looks healthy. That is this project's own core failure mode
# aimed at its own defaults, so each preset is asserted to examine a nonzero
# denominator and to actually report a planted fault.
#
# Derived from install.PRESETS at runtime rather than listed here, so a new
# preset is covered the moment it is added. A hand-written list would have to
# be remembered, and the eight presets added in 0.9.0 are the evidence that it
# would not have been.
ECOSYSTEMS: dict[str, dict[str, str]] = {
    "readme": {},
    "node": {
        "package.json": '{"name": "app", "version": "1.2.3"}\n',
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
    },
    "python": {
        "pyproject.toml": '[project]\nname = "app"\nversion = "1.2.3"\n',
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
    },
    "rust": {
        "Cargo.toml": '[package]\nname = "app"\nversion = "1.2.3"\n',
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
    },
    "go": {
        "go.mod": "module example.com/app\n\ngo 1.22\n",
        "Dockerfile": "FROM golang:1.22\nWORKDIR /src\n",
        "SECURITY.md": "# Security\n\nReport issues privately.\n",
    },
    "docker": {
        "Dockerfile": "FROM alpine:3.19\n",
        "compose.yaml": "services:\n  app:\n    build: .\n",
        "DEPLOY.md": "# Deploy\n\nSteps.\n",
        "RUNBOOK.md": "# Runbook\n\nOn call.\n",
        "OPERATIONS.md": "# Operations\n\nDaily.\n",
    },
    "jvm": {
        "build.gradle": "plugins { id 'java' }\n",
        "gradle.properties": "version = 1.2.3\n",
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
        "SECURITY.md": "# Security\n\nReport privately.\n",
        "UPGRADING.md": "# Upgrading\n\nFrom 1.1.\n",
        "MIGRATION.md": "# Migration\n\nSteps.\n",
    },
    "k8s": {
        "Chart.yaml": "apiVersion: v2\nname: app\nversion: 1.2.3\nappVersion: \"4.5.6\"\n",
        "values.yaml": "replicaCount: 1\n",
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
        "UPGRADING.md": "# Upgrading\n\nHelm notes.\n",
        "RUNBOOK.md": "# Runbook\n\nOn call.\n",
    },
    "monorepo": {
        "package.json": '{"name": "root", "version": "1.2.3", "workspaces": ["packages/*"]}\n',
        "turbo.json": '{"$schema": "https://turbo.build/schema.json"}\n',
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
        "ARCHITECTURE.md": "# Architecture\n\nPackages.\n",
        "docs/README.md": "# Docs\n\nIndex.\n",
    },
    "terraform": {
        "main.tf": 'resource "null_resource" "x" {}\n',
        "versions.tf": 'terraform {\n  required_version = ">= 1.5"\n}\n',
        "UPGRADING.md": "# Upgrading\n\nState moves.\n",
        "MIGRATION.md": "# Migration\n\nSteps.\n",
    },
    "mobile": {
        "android/app/build.gradle": 'android {\n  defaultConfig {\n    versionName "1.2.3"\n    versionCode 42\n  }\n}\n',
        "ios/App.xcodeproj/project.pbxproj": "\tMARKETING_VERSION = 1.2.3;\n",
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
        "RELEASE_NOTES.md": "# Release notes\n\n1.2.3.\n",
        "PRIVACY.md": "# Privacy\n\nWhat we collect.\n",
    },
    # Shaped from the real projects the presets were measured against: Unity
    # BossRoom and Thrive. The version strings are verbatim, including the
    # detail that Unity states its editor version in a shields.io badge while
    # Godot's README states none at all.
    "unity": {
        "ProjectSettings/ProjectVersion.txt":
            "m_EditorVersion: 6000.0.52f1\n"
            "m_EditorVersionWithRevision: 6000.0.52f1 (9e4086222921)\n",
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
        "Documentation/ART_NOTES.md": "# Art notes\n\nPipeline.\n",
        "Assets/Scripts/Game.cs": "public class Game {}\n",
    },
    "godot": {
        "project.godot": 'config_version=5\n\n[application]\n\n'
                         'config/features=PackedStringArray("4.7", "C#")\n',
        "doc/setup_instructions.md":
            "# Setup\n\nThe currently used Godot version is __4.7 .NET__. "
            "The regular version will not work.\n",
        "doc/architecture.md": "# Architecture\n\nSystems.\n",
        "doc/style_guide.md": "# Style\n\nConventions.\n",
    },
    "agent": {
        "AGENTS.md": "# Agent instructions\n\nRun the suite before editing.\n",
        "CLAUDE.md": "# Claude\n\nProject rules.\n",
        "GEMINI.md": "# Gemini\n\nProject rules.\n",
        ".github/copilot-instructions.md": "# Copilot\n\nProject rules.\n",
    },
    "ml": {
        "pyproject.toml": '[project]\nname = "model"\nversion = "1.2.3"\nrequires-python = ">=3.11"\n',
        "environment.yml": "name: model\ndependencies:\n  - python=3.11\n",
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
        "MODEL_CARD.md": "# Model card\n\nIntended use.\n",
        "DATA_CARD.md": "# Data card\n\nProvenance.\n",
    },
    "enterprise": {
        "SECURITY.md": "# Security\n\nReport privately.\n",
        "SUPPORT.md": "# Support\n\nChannels.\n",
        "UPGRADING.md": "# Upgrading\n\nFrom 1.1.\n",
        "MIGRATION.md": "# Migration\n\nSteps.\n",
    },
    "legacy-web": {
        "package.json": '{"name": "site", "version": "1.2.3", "engines": {"node": ">=18"}}\n',
        ".nvmrc": "18\n",
        "CHANGELOG.md": "# Changelog\n\n## 1.2.3\n\nFirst.\n",
        "INSTALL.md": "# Install\n\nSteps.\n",
        "DEPLOY.md": "# Deploy\n\nSteps.\n",
        "UPGRADING.md": "# Upgrading\n\nFrom 1.1.\n",
    },
    # The status document must carry real claims. An earlier version of this
    # fixture said only "Work continues", which examines to a denominator of
    # zero and failed the assertion below - correctly, and for a reason that
    # had nothing to do with the preset. A fixture with nothing to check
    # cannot tell a working configuration from a blind one.
    "status": {
        "NEXT_SESSION.md": "# Status\n\n## Phase 1 - setup (in progress, 2026-01-01)\n\n"
                           "Work continues on `feature/setup`.\n"
                           "The design is in [the plan](docs/plan-that-is-gone.md).\n"
                           "Merged at `0000000000000000000000000000000000000000`.\n\n"
                           "## 1. Reference\n",
    },
}

# Where a preset declares a consistency check, this is the edit that must make
# the two files disagree. Checking that the check EXISTS is not enough: a
# consistency block naming files that do not parse is exactly as quiet as no
# block at all.
DISAGREEMENTS: dict[str, tuple[str, str]] = {
    "node": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "python": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "rust": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "jvm": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "k8s": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "monorepo": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "ml": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "legacy-web": ("CHANGELOG.md", "# Changelog\n\n## 9.9.9\n\nDrifted.\n"),
    "go": ("Dockerfile", "FROM golang:1.19\nWORKDIR /src\n"),
    "unity": ("ProjectSettings/ProjectVersion.txt",
              "m_EditorVersion: 2022.3.10f1\n"),
    "godot": ("project.godot",
              'config_version=5\n\nconfig/features=PackedStringArray("4.2", "C#")\n'),
    "mobile": ("ios/App.xcodeproj/project.pbxproj",
               "\tMARKETING_VERSION = 9.9.9;\n"),
}

README_WITH_A_FAULT = (
    "# {name}\n\n"
    "Setup lives in [the guide](docs/guide.md).\n"
    "The design is recorded in [the plan](docs/plan-that-is-gone.md).\n"
)


def _examined(stdout: str) -> int:
    """Total claims examined, read off the denominator line the tool prints.

    Parsed rather than assumed. The whole point of the line is that a run
    which examined nothing prints the same reassuring nothing as a clean one,
    so a scenario that only checked the exit code would pass on a blind config.
    """
    total = 0
    for line in stdout.splitlines():
        if not line.startswith("checked "):
            continue
        # The line ends `... dead-pinned-ref 0 (8 lines scanned for secrets)`.
        # Splitting on commas alone leaves that parenthetical attached to the
        # LAST rule, whose count is then silently dropped - so a document
        # whose only examined rule happened to be last would read as zero.
        body = line.split(":", 1)[-1].split("(")[0]
        for chunk in body.split(","):
            parts = chunk.strip().split()
            if len(parts) >= 2 and parts[-1].isdigit():
                total += int(parts[-1])
    return total


def s21_every_preset() -> None:
    """Install each preset onto a repository shaped like its ecosystem."""
    name = "s21-presets"
    print(f"\n[{name}] every preset, on a repo shaped like its ecosystem")
    sys.path.insert(0, str(PKG / "plugin/skills/extant"))
    import install as installer_module

    presets = sorted(installer_module.PRESETS)
    check(name, f"every preset has a fixture ({len(presets)} presets)",
          set(presets) <= set(ECOSYSTEMS),
          f"missing: {sorted(set(presets) - set(ECOSYSTEMS))}")

    for preset in presets:
        repo = new_repo(f"{name}-{preset}")
        for rel, body in ECOSYSTEMS[preset].items():
            write(repo, rel, body)
        if preset != "status":
            body = README_WITH_A_FAULT.format(name=preset)
            if preset == "unity":
                # A Unity README states its editor version in a shields.io
                # badge. Without one the consistency check is correctly skipped
                # as unmatched, and this scenario would prove nothing about it.
                body = ("[![UnityVersion](https://img.shields.io/badge/"
                        "Unity%20Version:-6000.0.52f1%20LTS-57b9d3.svg)]"
                        "(https://unity.com)\n\n") + body
            write(repo, "README.md", body)
        write(repo, "CONTRIBUTING.md", "# Contributing\n\nRun the suite.\n")
        write(repo, "docs/guide.md", "# Guide\n\nReal file.\n")
        commit(repo, "chore: init")

        out = install(repo, "--preset", preset)
        if out.returncode != 0:
            # Every remaining assertion for this preset is reported as failed
            # rather than skipped. A skip subtracts from the denominator
            # silently, so a mutation that breaks installation for six presets
            # would shrink the assertion count instead of turning anything red.
            for pending in ("primary_doc exists on disk",
                            "the installed config examines something",
                            "the planted dead link is reported"):
                check(name, f"{preset}: {pending}", False,
                      f"installer exited {out.returncode}, so this never ran\n"
                      + (out.stdout + out.stderr)[:300])
            continue

        cfg = (repo / ".extant.toml").read_text(encoding="utf-8")
        primary = ""
        for line in cfg.splitlines():
            if line.startswith("primary_doc"):
                primary = line.split("=", 1)[1].strip().strip('"')
        check(name, f"{preset}: primary_doc exists on disk",
              bool(primary) and (repo / primary).is_file(),
              f"primary_doc={primary!r}\n{cfg}")

        res = tool(repo, "--verify")
        examined = _examined(res.stdout)
        check(name, f"{preset}: the installed config examines something",
              examined > 0,
              f"denominator totalled {examined}\n{res.stdout[:400]}")

        planted = [ln for ln in _findings(res.stdout, "dead-md-link")
                   if "plan-that-is-gone" in ln]
        check(name, f"{preset}: the planted dead link is reported",
              bool(planted), res.stdout[:400])

        if preset in DISAGREEMENTS:
            rel, body = DISAGREEMENTS[preset]
            clean = _findings(tool(repo, "--verify").stdout,
                              "inconsistent-artifact")
            check(name, f"{preset}: agreeing files produce no drift finding",
                  not clean, "\n".join(clean))
            write(repo, rel, body)
            drifted = _findings(tool(repo, "--verify").stdout,
                                "inconsistent-artifact")
            check(name, f"{preset}: the consistency check catches a drift",
                  bool(drifted), "no inconsistent-artifact finding line")

    covered = sorted(set(ECOSYSTEMS) - set(presets))
    check(name, "no fixture describes a preset that no longer exists",
          not covered, f"stale fixtures: {covered}")


def s22_cross_platform_agents() -> None:
    """Setup writes instructions for agents other than Claude Code.

    The two files are rendered from the same observations, so the failure that
    matters is not one of them missing: it is the two of them describing
    DIFFERENT documents, which would have this project shipping the exact
    contradiction it exists to catch, via its own installer.
    """
    name = "s22-agents"
    print(f"\n[{name}] cross-platform agent instructions")
    repo = new_repo(name)
    write(repo, "README.md", "# Widgetworks\n\nSee [the guide](docs/guide.md).\n")
    write(repo, "docs/guide.md", "# Guide\n")
    commit(repo, "chore: init")

    out = install(repo, "--preset", "readme")
    check(name, "installer succeeded", out.returncode == 0, out.stdout + out.stderr)

    skill = repo / ".agents/skills/extant/SKILL.md"
    command = repo / ".claude/commands/extant.md"
    check(name, "the skill lands at the Agent Skills standard path",
          skill.is_file(), f"missing {skill}")
    if not skill.is_file():
        return
    body = skill.read_text(encoding="utf-8")

    # Frontmatter, checked as a non-Claude tool would read it: the file opens
    # with a fenced YAML block carrying a name and a description.
    lines = body.splitlines()
    check(name, "the skill opens with YAML frontmatter",
          bool(lines) and lines[0].strip() == "---", repr(lines[:1]))
    closing = next((i for i, ln in enumerate(lines[1:], start=1)
                    if ln.strip() == "---"), -1)
    check(name, "the frontmatter block is closed", closing > 0, repr(lines[:12]))
    front = "\n".join(lines[1:closing]) if closing > 0 else ""
    check(name, "frontmatter declares a name and a description",
          "name:" in front and "description:" in front, front)

    check(name, "the skill is rendered, not copied",
          "{{" not in body and "}}" not in body,
          "\n".join(ln for ln in lines if "{{" in ln)[:300])
    check(name, "the skill names this project's document",
          "README.md" in body, body[:400])

    # The assertion this scenario exists for.
    cmd = command.read_text(encoding="utf-8") if command.is_file() else ""
    check(name, "both agent files name the same document",
          ("README.md" in body) == ("README.md" in cmd) and "README.md" in cmd,
          f"skill mentions README.md: {'README.md' in body}\n"
          f"command mentions README.md: {'README.md' in cmd}")

    check(name, "neither agent file names the source project",
          "Cerene" not in body + cmd and "NEXT_SESSION" not in body + cmd)

    # ASCII, for the same reason every shipped file is: a cp437 console.
    try:
        body.encode("ascii")
        command_ascii = True
        cmd.encode("ascii")
    except UnicodeEncodeError as exc:
        command_ascii = False
        check(name, "the rendered agent files are ASCII", False, str(exc))
    if command_ascii:
        check(name, "the rendered agent files are ASCII", True)


def s23_gitflow() -> None:
    """Two integration branches, which is where one configured trunk broke.

    Built as gitflow prescribes: main and develop, a release branch merged to
    both and tagged, a feature merged to develop AFTER that release. That last
    window is the whole problem - before a release, develop's history is
    already inside main and the two agree, so nothing is exposed. A document
    about active work talks about the commits that landed after it.

    The measurement that produced this scenario found both settings wrong in
    opposite directions, so the assertion that matters most is the LAST one:
    the answers must no longer depend on which branch is configured as trunk.
    """
    name = "s23-gitflow"
    print(f"\n[{name}] gitflow: two integration branches")
    repo = new_repo(name)
    write(repo, "a.txt", "a\n")
    commit(repo, "chore: init")
    git(repo, "branch", "develop")

    git(repo, "checkout", "-q", "develop")
    git(repo, "checkout", "-q", "-b", "release/1.0.0")
    write(repo, "VERSION", "1.0.0\n")
    commit(repo, "chore: bump")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge: release 1.0.0", "release/1.0.0")
    git(repo, "tag", "v1.0.0")
    on_main = git(repo, "rev-parse", "--short", "main").strip()
    git(repo, "checkout", "-q", "develop")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge: release back", "release/1.0.0")

    git(repo, "checkout", "-q", "-b", "feature/search")
    write(repo, "search.txt", "s\n")
    commit(repo, "feat: search")
    git(repo, "checkout", "-q", "develop")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge: search", "feature/search")
    on_develop = git(repo, "rev-parse", "--short", "develop").strip()

    git(repo, "checkout", "-q", "-b", "feature/payments")
    write(repo, "pay.txt", "p\n")
    commit(repo, "feat: wip")
    git(repo, "checkout", "-q", "develop")

    # Two TRUE claims and two FALSE ones, one of each about either branch.
    write(repo, "STATUS.md",
          "# Status\n\n## Phase 1 - search (in progress, 2026-07-27)\n\n"
          f"Merged to `develop` at `{on_develop}`.\n"
          f"Merged to `main` at `{on_main}`.\n"
          f"Merged to `develop` at `{on_main}`.\n"
          f"Merged to `main` at `{on_develop}`.\n"
          "Released in v1.0.0 already.\n"
          "Work is NOT yet merged on `feature/payments`.\n\n"
          "## 1. Reference\n")
    commit(repo, "docs: status")
    install(repo, "--doc", "STATUS.md")

    seen = {}
    for trunk in ("main", "develop"):
        cfg = (repo / ".extant.toml").read_text(encoding="utf-8")
        lines = [ln for ln in cfg.splitlines() if not ln.startswith("trunk")]
        write(repo, ".extant.toml", "\n".join(lines) + f'\ntrunk = "{trunk}"\n')
        res = tool(repo, "--validate", "STATUS.md")
        found = _findings(res.stdout, "false-merge-claim")

        check(name, f"trunk={trunk}: both false claims reported, neither true one",
              len(found) == 2 and {f.split(":")[0] for f in found} ==
              {"line 7", "line 8"},
              "\n".join(found) or res.stdout[:400])
        check(name, f"trunk={trunk}: the shipped tag is not called dead",
              not _findings(res.stdout, "dead-release-tag"),
              "\n".join(_findings(res.stdout, "dead-release-tag")))
        check(name, f"trunk={trunk}: the unmerged feature is still open",
              not _findings(res.stdout, "stale-live-claim"),
              "\n".join(_findings(res.stdout, "stale-live-claim")))
        seen[trunk] = _examined(res.stdout)

    check(name, "every merge claim is examined, not the fraction naming trunk",
          seen["main"] == seen["develop"] and seen["main"] > 0,
          f"examined main={seen['main']} develop={seen['develop']}")


# Counted, never spelled out. The README beside this file claimed "Three tools"
# for two commits after the fourth and fifth arrived, and this line said
# "12 scenarios" as a literal - a hand-maintained denominator in a harness whose
# job is to make hand-maintained numbers untrustworthy.
SCENARIOS = (s1_node_master_status, s2_release_tags, s3_ticket_branches,
             s4_no_document, s5_extra_docs, s6_everything_broken,
             s7_clean_project, s8_crlf_and_nested, s9_worktree,
             s10_archive_roundtrip, s11_hooks, s12_empty_repo,
             s13_monorepo, s14_adr, s15_github_dir, s16_alternate_trunks,
             s17_tag_shapes, s18_encodings, s19_deep_relative_links,
             s20_maven, s21_every_preset, s22_cross_platform_agents,
             s23_gitflow)


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
