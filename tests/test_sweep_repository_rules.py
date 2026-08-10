"""Repository-scoped rules in `--sweep`, which is where they were silent.

`inconsistent-artifact` and `raw-lfs-blob` answer questions about the
REPOSITORY rather than about any document, so `validate` runs them only on the
primary pass, guarded by `has_entries`. In a sweep `has_entries` is
`relative == CONFIG.primary_doc`, so in any repository that does not carry a
configured status document - which is nearly every repository a sweep is
pointed at, since a sweep needs no configuration at all - neither rule ever
ran.

That was invisible: a rule examining nothing and a rule finding nothing print
the same zero. It showed up as `0 / 0` for both rules across all three Phase 3
corpora, a result previously read as "no corpus repository had a consistency
block".

The gate itself is right and stays. Its purpose is that one repository-wide
disagreement must not be reported once per swept document. What was wrong was
tying "once" to a document that usually does not exist.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
COLLECTOR = PAYLOAD / "extant_collect.py"


def sweep(repo: Path, collector: Path | None = None) -> str:
    done = subprocess.run(
        [sys.executable, str(collector or COLLECTOR),
         "--repo", str(repo), "--sweep"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    return done.stdout + done.stderr


def commit_raw(repo: Path, rel: str, content: str, message: str) -> None:
    """Commit a file BYPASSING the LFS clean filter.

    Where git-lfs is installed an ordinary `git add` silently converts the file
    to a pointer, so a test writing it normally would commit a correct pointer
    and prove nothing. `--no-filters` reproduces the real cause: a commit made
    from a clone whose LFS filter was never installed.
    """
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    sha = subprocess.run(["git", "hash-object", "-w", "--no-filters", rel],
                         cwd=repo, capture_output=True, text=True,
                         check=True).stdout.strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                    f"100644,{sha},{rel}"], cwd=repo, capture_output=True,
                   check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo,
                   capture_output=True, check=True)


@pytest.fixture()
def lfs_repo_without_a_status_document(git_repo):
    """An LFS fault, some markdown, and deliberately NO status document.

    The absence is the point. With `NEXT_SESSION.md` present the rule runs and
    the gap is invisible, which is why this went unnoticed for so long.
    """
    repo, commit = git_repo
    commit(".gitattributes", "*.png filter=lfs diff=lfs merge=lfs -text\n",
           "chore: track binaries in LFS")
    commit("README.md", "# demo\n\nnothing claimed here\n", "docs: readme")
    commit_raw(repo, "art/logo.png", "not a pointer, a real file\n",
               "feat: add the logo raw")
    assert not (repo / "NEXT_SESSION.md").exists()
    return repo, commit


def test_a_raw_lfs_blob_is_reported_by_a_sweep(
        lfs_repo_without_a_status_document) -> None:
    """The gap. Catches repository-scoped rules gated on a document that a
    swept repository has no reason to contain."""
    repo, _ = lfs_repo_without_a_status_document
    assert "raw-lfs-blob" in sweep(repo)


def test_the_repository_finding_is_reported_once_not_once_per_document(
        lfs_repo_without_a_status_document) -> None:
    """The reason the gate exists, which the fix must not undo.

    One repository-wide disagreement reported once per swept markdown file is
    the noise the `has_entries` guard was written to prevent. Catches a fix
    that simply removes the guard.
    """
    repo, commit = lfs_repo_without_a_status_document
    for name in ("a.md", "b.md", "c.md"):
        commit(f"docs/{name}", f"# {name}\n\nnothing here\n", f"docs: {name}")
    output = sweep(repo)
    assert output.count("raw-lfs-blob]") == 1, output


def test_a_repository_with_no_fault_stays_silent(git_repo) -> None:
    """Catches a fix that reports the rule rather than its findings.

    Matched on `[raw-lfs-blob]`, the bracketed form a rendered FINDING carries,
    rather than on the bare kind. The sweep now names every rule on its
    denominator line whether it fired or not, which is the point of that line -
    so the bare name appears on a clean run by design, and asserting its
    absence would fail for the right output.
    """
    repo, commit = git_repo
    commit("README.md", "# demo\n\nnothing claimed\n", "docs: readme")
    output = sweep(repo)
    assert "[raw-lfs-blob]" not in output, output
    # The denominator line is expected, and says the rule ran and saw nothing.
    assert "raw-lfs-blob 0" in output, output


def test_an_inconsistent_artifact_is_reported_by_a_sweep(git_repo) -> None:
    """The same gap for the other repository-scoped rule.

    The payload is copied into `tools/` because configuration loads relative to
    the SCRIPT, not to `--repo`. Run from the source tree it would read THIS
    project's `.extant.toml` and the target's consistency block would never be
    seen, so the test would pass or fail for a reason unrelated to the sweep.
    """
    repo, commit = git_repo
    commit("a.toml", 'version = "1.0.0"\n', "chore: a")
    commit("b.toml", 'version = "2.0.0"\n', "chore: b")
    commit("README.md", "# demo\n\nnothing claimed\n", "docs: readme")
    commit(".extant.toml",
           '[extant.consistency.version]\n'
           '"a.toml" = \'version = "([0-9.]+)"\'\n'
           '"b.toml" = \'version = "([0-9.]+)"\'\n',
           "chore: consistency block")
    tools = repo / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("extant_collect.py", "extant_config.py"):
        shutil.copyfile(PAYLOAD / name, tools / name)
    # The shim's version handshake (Task 1) imports `extant` at module load,
    # so a bare shim copy with no package beside it now crashes with
    # ModuleNotFoundError instead of running. Copy the package too.
    shutil.copytree(PAYLOAD / "extant", tools / "extant",
                    ignore=shutil.ignore_patterns("__pycache__"))
    output = sweep(repo, collector=tools / "extant_collect.py")
    assert "settings came from defaults" not in output, (
        f"the target's config was not read, so this proves nothing:\n{output}")
    assert "inconsistent-artifact" in output, output


def test_a_sweep_still_cannot_fail_the_build(
        lfs_repo_without_a_status_document) -> None:
    """The README promises a sweep never gates, and a repository finding sits
    in no configured document, so it must not change that.

    Catches a fix that routes these findings into the vetted section, which
    would turn a survey command into one that fails CI for repositories that
    never opted in.
    """
    repo, _ = lfs_repo_without_a_status_document
    done = subprocess.run(
        [sys.executable, str(COLLECTOR), "--repo", str(repo), "--sweep"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    assert "raw-lfs-blob" in done.stdout + done.stderr
    assert done.returncode == 0, done.stdout + done.stderr
