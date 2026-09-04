"""Behavioural tests for the shell git hooks.

The hooks are the only part of the status workflow with no Python to test, and
they failed accordingly: `main-tree-guard` spent its entire life installed but
inert, because the installer's payload list omitted the file while the pre-commit
shim guarded the call with `[ -f ]`. The installer printed a success line, the
guard never ran, and nothing anywhere disagreed.

So these tests run the real script through a real `sh` against real repositories
rather than asserting on its text. Each one names the wrong implementation it
would catch, because a hook test that only checks "exit code is 0 somewhere" is
the same shape as the bug.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _install_into

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
HOOKS_DIR = SKILL_ROOT / "payload" / "hooks"
GUARD = HOOKS_DIR / "main-tree-guard"

# `sh` ships with Git for Windows, so this is present wherever git is. The skip
# is real rather than defensive: without a shell there is nothing to assert. The
# reference test below needs no shell, so hook coverage never silently drops to
# zero on a machine that lacks one.
requires_sh = pytest.mark.skipif(
    shutil.which("sh") is None, reason="no POSIX shell available to run the hook"
)


def run_guard(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run main-tree-guard as git would, from `cwd`."""
    return subprocess.run(
        ["sh", str(GUARD)], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout


def run_installer(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the hook installer from inside `repo`."""
    return subprocess.run(
        ["sh", "tools/hooks/install", *args], cwd=repo,
        capture_output=True, text=True, encoding="utf-8",
    )


@requires_sh
def test_guard_allows_commit_on_trunk(git_repo) -> None:
    """Catches a guard that blocks unconditionally, making commits impossible."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")

    result = run_guard(repo)

    assert result.returncode == 0, f"blocked a commit on trunk: {result.stderr}"


@requires_sh
def test_guard_blocks_off_trunk_commit_in_main_tree(git_repo) -> None:
    """Catches a guard that never fires - the state it actually shipped in."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    git(repo, "checkout", "-q", "-b", "topic")

    result = run_guard(repo)

    assert result.returncode == 1
    assert "BLOCKED" in result.stderr


@requires_sh
def test_guard_reads_trunk_from_config(git_repo) -> None:
    """The regression test for the bug this file exists because of.

    The guard hardcoded `main`, so on a repo whose .extant.toml correctly said
    `trunk = "master"` it blocked every commit on that repo's real trunk. A
    guard that ignores the config passes every other test in this file.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    git(repo, "branch", "-m", "master")
    (repo / ".extant.toml").write_text('trunk = "master"\n', encoding="utf-8")

    result = run_guard(repo)

    assert result.returncode == 0, (
        f"blocked a commit on the configured trunk 'master': {result.stderr}"
    )


@requires_sh
def test_guard_message_names_the_configured_trunk(git_repo) -> None:
    """Catches a guard that reads the config but still says 'main' to the user.

    Advice naming a branch the repo does not have is worse than no advice: it
    sends someone to create one.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    git(repo, "branch", "-m", "master")
    (repo / ".extant.toml").write_text('trunk = "master"\n', encoding="utf-8")
    git(repo, "checkout", "-q", "-b", "topic")

    result = run_guard(repo)

    assert result.returncode == 1
    assert "not 'master'" in result.stderr
    assert "not 'main'" not in result.stderr


@requires_sh
def test_guard_exempts_linked_worktrees(git_repo, tmp_path: Path) -> None:
    """Catches a guard that blocks the very place work is supposed to happen.

    Feature work lives on a topic branch in a linked worktree, which is exactly
    the shape the main-tree rule forbids. Confusing the two would block every
    legitimate commit in the project's normal workflow.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(worktree), "-b", "feat")

    result = run_guard(worktree)

    assert result.returncode == 0, f"blocked a worktree commit: {result.stderr}"


VERIFY_HOOK = HOOKS_DIR / "extant-verify"


def run_verify_hook(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(VERIFY_HOOK), *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8",
    )


def _using_the_tool(repo: Path, doc: str = "STATUS.md") -> None:
    """Enough of an install that the hook reaches its "no document" report.

    Same shape the two tests above use: no interpreter and no real collector,
    so what is under test is the hook's control flow rather than the
    validator's. Reaching that report is the observable that separates "the
    hook ran" from "the hook exited early", which is the whole distinction
    these tests exist for.
    """
    (repo / "tools").mkdir(exist_ok=True)
    (repo / "tools" / "extant_collect.py").write_text("", encoding="utf-8")
    (repo / ".extant.toml").write_text(f'primary_doc = "{doc}"\n', encoding="utf-8")


@requires_sh
def test_verify_hook_reads_the_configured_document(git_repo) -> None:
    """Catches a hook that guards its work with a hardcoded document name.

    extant-verify tested `[ -f NEXT_SESSION.md ]` before doing anything, while
    --verify, which it then invokes, reads primary_doc from .extant.toml. Any
    project that called its document something else fell through the "nothing to
    validate" exit, so the hook installed cleanly and validated nothing for its
    entire life -- silently, because that exit is the legitimate one.

    Asserted through the missing-document path, which needs no interpreter and
    no real collector, so the test stays fast and deterministic.
    """
    repo, commit = git_repo
    commit("README.md", "# repo\n", "init")
    (repo / "tools").mkdir(exist_ok=True)
    (repo / "tools" / "extant_collect.py").write_text("", encoding="utf-8")
    (repo / ".extant.toml").write_text('primary_doc = "STATUS.md"\n', encoding="utf-8")

    result = run_verify_hook(repo)

    combined = result.stdout + result.stderr
    assert "STATUS.md" in combined, (
        "the hook ignored primary_doc and looked for some other document: "
        f"{combined!r}"
    )
    assert "nothing was validated" in combined


@requires_sh
def test_verify_hook_stays_quiet_when_no_document_is_configured(git_repo) -> None:
    """The other half: a repo not using the system must not be nagged.

    Without this, the fix above could be 'warn always', which is the failure
    mode that makes people delete the hook.
    """
    repo, commit = git_repo
    commit("README.md", "# repo\n", "init")
    (repo / "tools").mkdir(exist_ok=True)
    (repo / "tools" / "extant_collect.py").write_text("", encoding="utf-8")

    result = run_verify_hook(repo)

    assert (result.stdout + result.stderr).strip() == "", "nagged a repo with no status doc"


@requires_sh
def test_after_rewrite_still_runs_while_rebase_state_is_present(git_repo) -> None:
    """The one that decides whether post-rewrite is a hook or a decoration.

    Measured on git 2.53.0: when post-rewrite fires at the end of a rebase,
    `rebase-merge/` HAS NOT BEEN TORN DOWN YET. The plain entry point reads
    that directory as "a rebase is in progress" and exits 0, which is correct
    for post-commit - it fires once per replayed commit - and would have made
    post-rewrite installed and inert. That is this repository's oldest bug
    shape, and the reason `main-tree-guard` has tests at all.
    """
    repo, commit = git_repo
    commit("README.md", "# repo\n", "init")
    _using_the_tool(repo)
    (repo / ".git" / "rebase-merge").mkdir()

    plain = run_verify_hook(repo)
    after = run_verify_hook(repo, "--after-rewrite", "rebase")

    assert (plain.stdout + plain.stderr).strip() == "", (
        "post-commit's guard stopped suppressing an in-progress rebase")
    assert "nothing was validated" in (after.stdout + after.stderr), (
        "post-rewrite skipped the rebase it exists to catch, because git had "
        "not removed rebase-merge/ yet")


@requires_sh
def test_after_rewrite_declines_an_amend_post_commit_already_reported(git_repo) -> None:
    """Both hooks fire for `git commit --amend`; only one should report.

    Measured on git 2.53.0: an amend fires post-commit and then post-rewrite,
    and nothing suppresses the first, so wiring both to the same behaviour
    prints the same findings twice for one operation. Two identical reports is
    how a hook teaches its reader to stop reading it.
    """
    repo, commit = git_repo
    commit("README.md", "# repo\n", "init")
    _using_the_tool(repo)

    amend = run_verify_hook(repo, "--after-rewrite", "amend")
    rebase = run_verify_hook(repo, "--after-rewrite", "rebase")

    assert (amend.stdout + amend.stderr).strip() == "", "reported an amend twice"
    assert "nothing was validated" in (rebase.stdout + rebase.stderr), (
        "declining the amend case also silenced the rebase case")


@requires_sh
def test_the_installed_post_rewrite_hook_drains_the_pairs_git_writes(git_repo) -> None:
    """Unread, git blocks on a full pipe and the rebase HANGS.

    post-rewrite is the only hook git feeds on stdin - one `<old> <new>` pair
    per rewritten commit. The pipe buffer is finite and this hook spends a
    second or two validating before it exits, so a long enough rebase fills the
    buffer and git waits forever for a reader that never comes. A hang is a
    worse failure than a missed check, and it would only appear on large
    rebases, which is to say not on anybody's test repository.
    """
    import shutil
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    shutil.copytree(HOOKS_DIR, repo / "tools" / "hooks")
    assert run_installer(repo).returncode == 0

    hook = repo / ".git" / "hooks" / "post-rewrite"
    assert hook.exists(), "the installer did not wire post-rewrite"
    body = hook.read_text(encoding="utf-8")
    assert "cat > /dev/null" in body, "the shim never reads git's pairs"
    assert "--after-rewrite" in body, "the shim did not pass the rewrite kind"

    # And it survives being handed more than it will ever read.
    flood = "".join(f"{'a' * 40} {'b' * 40}\n" for _ in range(5000))
    done = subprocess.run(["sh", str(hook), "rebase"], cwd=repo, input=flood,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr


@requires_sh
def test_default_install_wires_post_rewrite(git_repo) -> None:
    """A rewrite renames every commit at once, so it must be a default hook.

    Measured 2026-08-30 on a real agent-written project: 12 of its 12 dead SHA
    references were created by one `git filter-repo` run. Nothing in the
    advisory set fired at that moment - post-commit is suppressed during the
    rewrite and post-merge never sees it.
    """
    import shutil
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    shutil.copytree(HOOKS_DIR, repo / "tools" / "hooks")

    result = run_installer(repo)

    assert result.returncode == 0, result.stderr
    assert (repo / ".git" / "hooks" / "post-rewrite").exists()
    assert not (repo / ".git" / "hooks" / "pre-commit").exists(), (
        "adding post-rewrite also added something that can block a commit")
    # Re-running must not append a second copy.
    again = run_installer(repo)
    assert "already installed: post-rewrite" in again.stdout, again.stdout
    body = (repo / ".git" / "hooks" / "post-rewrite").read_text(encoding="utf-8")
    assert body.count("extant-verify-hook") == 1, "installed twice"


def test_installer_references_only_hooks_that_exist() -> None:
    """Catches the payload-omission bug directly, and needs no shell to do it.

    `tools/hooks/install` wired a pre-commit pointing at `main-tree-guard` while
    nothing shipped that file. Because the shim skips a missing hook silently,
    the only observable symptom was a check that never ran. This asserts every
    hook the installer names is actually present.
    """
    text = HOOKS_DIR.joinpath("install").read_text(encoding="utf-8")
    referenced = set(re.findall(r"tools/hooks/([A-Za-z0-9_-]+)", text))

    # State the denominator. If the pattern stops matching, this test would pass
    # against an installer referencing nothing but existing files AND against one
    # referencing nothing at all -- the ambiguity the whole status workflow exists
    # to remove.
    assert referenced, "found no hook references in tools/hooks/install"

    missing = sorted(name for name in referenced if not (HOOKS_DIR / name).is_file())
    assert not missing, (
        f"tools/hooks/install references {sorted(referenced)}; "
        f"missing from tools/hooks/: {missing}"
    )


@requires_sh
def test_default_install_does_not_add_a_blocking_hook(git_repo) -> None:
    """The default must never install something that can refuse a commit.

    Every default hook here is advisory: it runs after the commit is already
    recorded, reports, and fails nothing. The trunk guard is different in kind,
    and it is also about git habits rather than about the document, so someone
    who installed a documentation checker would meet it as a rejected commit
    for a reason they never asked about. It used to install by default.
    """
    import shutil
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    shutil.copytree(HOOKS_DIR, repo / "tools" / "hooks")

    result = run_installer(repo)

    assert result.returncode == 0, result.stderr
    hooks = repo / ".git" / "hooks"
    assert (hooks / "post-commit").exists()
    assert (hooks / "post-merge").exists()
    assert not (hooks / "pre-commit").exists(), (
        "the default install added a hook that can block a commit"
    )
    assert "--with-trunk-guard" in result.stdout, (
        "the default should say the guard exists and how to get it"
    )


@requires_sh
def test_the_guard_installs_when_asked_for(git_repo) -> None:
    """Opt-in must actually opt in, or the flag is decoration."""
    import shutil
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    shutil.copytree(HOOKS_DIR, repo / "tools" / "hooks")

    result = run_installer(repo, "--with-trunk-guard")

    assert result.returncode == 0, result.stderr
    assert (repo / ".git" / "hooks" / "pre-commit").exists()
    assert "CAN BLOCK A COMMIT" in result.stdout, (
        "installing a blocking hook must say so plainly"
    )


@requires_sh
def test_an_unknown_flag_is_rejected_rather_than_ignored(git_repo) -> None:
    """A misspelled --with-trunk-guard must not silently install nothing.

    Quietly ignoring an unrecognised option is how someone believes they have
    protection they do not have, which is this project's whole subject.
    """
    import shutil
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n", "init")
    shutil.copytree(HOOKS_DIR, repo / "tools" / "hooks")

    result = run_installer(repo, "--with-trunk-gaurd")

    assert result.returncode == 2, result.stdout + result.stderr
    assert "unknown option" in result.stderr
    assert not (repo / ".git" / "hooks" / "post-commit").exists(), (
        "a rejected invocation must not half-install"
    )


@requires_sh
def test_the_verify_hook_reports_findings_it_actually_found(git_repo) -> None:
    """The formatter, end to end, through the real hook and a real --verify.

    tests/test_hook_builtins.py proves `extant_findings_summary` answers what
    the `grep -c`, `head -5` and `sed` pipeline answered. It cannot prove the
    hook CALLS it, or that COUNT survives from the function into the header
    line and the `if` after the listing - which is the failure the first
    implementation had, and which every unit table would have missed.

    So this one runs the shipped script against a repository holding a document
    with real dead claims, and reads what a developer would see after a commit.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    _install_into(repo)
    (repo / ".extant.toml").write_text('primary_doc = "STATUS.md"\n',
                                       encoding="utf-8")
    dead = "\n".join(f"- Phase {n} landed at `deadbee{n}` and is done."
                     for n in range(1, 8))
    commit("STATUS.md", f"# Status\n\n{dead}\n", "docs: status")

    result = run_verify_hook(repo)

    combined = result.stdout + result.stderr
    print(combined)
    assert result.returncode == 0, "advisory only: the commit already happened"
    assert "STATUS.md has 7 unverified claim(s):" in combined, combined
    # Five listed, indented by two, and then the pointer at the rest - which is
    # the branch COUNT decides in the parent shell.
    listed = [line for line in combined.splitlines() if line.startswith("  ")]
    assert len(listed) == 6, listed
    assert listed[-1].startswith("  ... run:"), listed
    assert all("[dead-sha]" in line for line in listed[:5]), listed


@requires_sh
def test_the_verify_hook_says_nothing_about_a_clean_document(git_repo) -> None:
    """The other direction, so the test above cannot pass by always reporting.

    A hook that printed a summary whether or not anything was wrong is a hook
    people learn to scroll past, and then the one real report goes with it.
    """
    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "chore: init")
    _install_into(repo)
    (repo / ".extant.toml").write_text('primary_doc = "STATUS.md"\n',
                                       encoding="utf-8")
    commit("STATUS.md", f"# Status\n\n- Phase 1 landed at `{sha[:9]}`.\n",
           "docs: status")

    result = run_verify_hook(repo)

    assert (result.stdout + result.stderr).strip() == "", (
        result.stdout + result.stderr)
