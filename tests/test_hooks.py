"""Behavioural tests for the shell git hooks.

The hooks are the only part of the handoff system with no Python to test, and
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

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = PACKAGE_ROOT / "payload" / "hooks"
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


@requires_sh
def test_guard_allows_commit_on_trunk(git_repo) -> None:
    """Catches a guard that blocks unconditionally, making commits impossible."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Handoff\n", "init")

    result = run_guard(repo)

    assert result.returncode == 0, f"blocked a commit on trunk: {result.stderr}"


@requires_sh
def test_guard_blocks_off_trunk_commit_in_main_tree(git_repo) -> None:
    """Catches a guard that never fires - the state it actually shipped in."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Handoff\n", "init")
    git(repo, "checkout", "-q", "-b", "topic")

    result = run_guard(repo)

    assert result.returncode == 1
    assert "BLOCKED" in result.stderr


@requires_sh
def test_guard_reads_trunk_from_config(git_repo) -> None:
    """The regression test for the bug this file exists because of.

    The guard hardcoded `main`, so on a repo whose .handoff.toml correctly said
    `trunk = "master"` it blocked every commit on that repo's real trunk. A
    guard that ignores the config passes every other test in this file.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Handoff\n", "init")
    git(repo, "branch", "-m", "master")
    (repo / ".handoff.toml").write_text('trunk = "master"\n', encoding="utf-8")

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
    commit("NEXT_SESSION.md", "# Handoff\n", "init")
    git(repo, "branch", "-m", "master")
    (repo / ".handoff.toml").write_text('trunk = "master"\n', encoding="utf-8")
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
    commit("NEXT_SESSION.md", "# Handoff\n", "init")
    worktree = tmp_path / "wt"
    git(repo, "worktree", "add", "-q", str(worktree), "-b", "feat")

    result = run_guard(worktree)

    assert result.returncode == 0, f"blocked a worktree commit: {result.stderr}"


VERIFY_HOOK = HOOKS_DIR / "handoff-verify"


def run_verify_hook(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(VERIFY_HOOK)], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8",
    )


@requires_sh
def test_verify_hook_reads_the_configured_document(git_repo) -> None:
    """Catches a hook that guards its work with a hardcoded document name.

    handoff-verify tested `[ -f NEXT_SESSION.md ]` before doing anything, while
    --verify, which it then invokes, reads handoff_doc from .handoff.toml. Any
    project that called its document something else fell through the "nothing to
    validate" exit, so the hook installed cleanly and validated nothing for its
    entire life -- silently, because that exit is the legitimate one.

    Asserted through the missing-document path, which needs no interpreter and
    no real collector, so the test stays fast and deterministic.
    """
    repo, commit = git_repo
    commit("README.md", "# repo\n", "init")
    (repo / "tools").mkdir(exist_ok=True)
    (repo / "tools" / "handoff_collect.py").write_text("", encoding="utf-8")
    (repo / ".handoff.toml").write_text('handoff_doc = "STATUS.md"\n', encoding="utf-8")

    result = run_verify_hook(repo)

    combined = result.stdout + result.stderr
    assert "STATUS.md" in combined, (
        "the hook ignored handoff_doc and looked for some other document: "
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
    (repo / "tools" / "handoff_collect.py").write_text("", encoding="utf-8")

    result = run_verify_hook(repo)

    assert (result.stdout + result.stderr).strip() == "", "nagged a repo with no handoff doc"


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
    # referencing nothing at all -- the ambiguity the whole handoff system exists
    # to remove.
    assert referenced, "found no hook references in tools/hooks/install"

    missing = sorted(name for name in referenced if not (HOOKS_DIR / name).is_file())
    assert not missing, (
        f"tools/hooks/install references {sorted(referenced)}; "
        f"missing from tools/hooks/: {missing}"
    )
