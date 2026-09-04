"""A copied fixture repository must be indistinguishable from a built one.

The speed is the reason for the change; this is the thing that must not
regress. A fixture that is subtly not equivalent produces 498 tests passing
against a repository shape nobody intended - the quiet failure this project's
denominators exist to make visible, arriving in the machinery that produces the
inputs rather than in the code being tested.

So each template is compared against a repository built the long way, on every
property a rule can read: the same HEAD, the same branches and tags, `fsck`
clean, no absolute path baked into its config, and - the one that decides
whether these fixtures are usable at all - independent of the template
afterwards, in both directions.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from conftest import committer, init_repo

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACKAGE_ROOT / "plugin" / "skills" / "extant" / "payload"))


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout.strip()


def described(repo: Path) -> dict[str, str]:
    """Everything about a repository that any rule here can ask git."""
    return {
        "head": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "refs": git(repo, "for-each-ref",
                    "--format=%(refname)\t%(objectname)\t%(objecttype)"),
        # Trees and subjects, not parents: two commits made a moment apart are
        # different objects, so their ids and therefore their children's parent
        # ids differ between any two builds - copied or not. What a rule reads
        # is the CONTENT and the shape, so those are what is compared, with the
        # shape reduced to how many parents each commit has.
        "log": git(repo, "log", "--all", "--format=%T %s"),
        "graph": " ".join(
            str(len(line.split()))
            for line in git(repo, "log", "--all", "--format=%P").splitlines()),
        "tree": git(repo, "ls-tree", "-r", "HEAD", "--name-only"),
        "status": git(repo, "status", "--porcelain"),
    }


def test_a_copied_repository_answers_what_a_built_one_answers(
        git_repo, tmp_path) -> None:
    """The base shape, compared against one built the long way.

    Built with the SAME helpers the template uses, so what is being compared is
    copying against not copying - not this helper against a second one written
    to look like it.
    """
    copied, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    commit("docs/plan.md", "# Plan\n", "docs: plan")
    git(copied, "tag", "v1.0.0")

    built = tmp_path / "built"
    init_repo(built)
    long_way = committer(built)
    long_way("a.py", "a = 1\n", "chore: init")
    long_way("docs/plan.md", "# Plan\n", "docs: plan")
    git(built, "tag", "v1.0.0")

    one, other = described(copied), described(built)
    # The commit ids differ - two commits a moment apart are different objects,
    # which is true of two built repositories as well. Everything the ids are
    # made OF is compared instead.
    differing = {k: (one[k], other[k]) for k in one
                 if one[k] != other[k] and k not in ("head", "refs")}
    print(f"compared {len(one)} properties of a copied repository "
          f"against a built one")
    assert not differing, differing
    assert one["branch"] == other["branch"] == "main"
    assert (len(one["refs"].splitlines())
            == len(other["refs"].splitlines()) == 2)


def test_a_copied_repository_passes_fsck(git_repo) -> None:
    """A copy that is not a valid repository would fail LOUDLY here and quietly
    everywhere else - a rule asking git a question of a broken object store
    gets an error, which several rules turn into "cannot tell, stay silent"."""
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    done = subprocess.run(["git", "fsck", "--strict"], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8")
    print(done.stdout + done.stderr)
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_copy_advances_without_touching_the_template(
        empty_repo_template, git_repo) -> None:
    """Independence, in both directions, which is what makes a template safe.

    A template that acquires the first test's commits hands the second test a
    repository nobody wrote, and every test after that one is running against
    a shape that depends on collection order.
    """
    repo, commit = git_repo
    before = sorted(p.name for p in empty_repo_template.rglob("*")
                    if p.is_file())

    commit("a.py", "a = 1\n", "chore: init")
    git(repo, "branch", "topic")
    git(repo, "tag", "v9.9.9")

    after = sorted(p.name for p in empty_repo_template.rglob("*") if p.is_file())
    print(f"template holds {len(after)} files, unchanged: {before == after}")
    assert before == after
    assert git(empty_repo_template, "for-each-ref") == "", (
        "the template gained a ref from a test that used a copy of it")


def test_a_copy_bakes_no_path_of_the_template_into_its_config(
        empty_repo_template, git_repo) -> None:
    """An absolute path in the copy's config points the copy at the template.

    It would not fail visibly: git would go on answering, about the wrong
    directory, which is the failure mode this whole change has to avoid.
    """
    repo, _commit = git_repo
    config = (repo / ".git" / "config").read_text(encoding="utf-8")
    print(config)
    assert str(empty_repo_template) not in config
    assert str(empty_repo_template.parent) not in config


def test_the_staged_payload_is_what_the_installer_would_have_copied(
        git_repo) -> None:
    """`_install_into` stages once and copies; the result must not have changed.

    Compared against the payload directory itself rather than against a second
    copy, so a staging step that dropped a file, or kept this checkout's
    bytecode, is caught by the same assertion.
    """
    from conftest import PAYLOAD, _install_into

    repo, _commit = git_repo
    tools = _install_into(repo)

    installed = sorted(p.relative_to(tools).as_posix()
                       for p in tools.rglob("*") if p.is_file())
    expected = sorted(
        ["extant_collect.py"]
        + [("extant/" + p.relative_to(PAYLOAD / "extant").as_posix())
           for p in (PAYLOAD / "extant").rglob("*")
           if p.is_file() and "__pycache__" not in p.parts])
    print(f"installed {len(installed)} files")
    assert installed == expected
    assert not [name for name in installed if "__pycache__" in name]
    assert (tools / "extant_collect.py").read_bytes() == (
        (PAYLOAD / "extant_collect.py").read_bytes())


def test_installing_twice_gives_two_independent_copies(git_repo,
                                                       tmp_path) -> None:
    """The staged template must not become shared state between two repos."""
    from conftest import _install_into

    repo, _commit = git_repo
    second = tmp_path / "second"
    second.mkdir()

    first_tools = _install_into(repo)
    second_tools = _install_into(second)
    (first_tools / "extant_collect.py").write_text("# scribbled\n",
                                                   encoding="utf-8")

    assert (second_tools / "extant_collect.py").read_text(
        encoding="utf-8") != "# scribbled\n"
