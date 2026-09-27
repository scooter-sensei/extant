"""Nothing is read from outside the checkout, whatever the repository names.

Every name this tool opens comes from the repository - the tracked list, a
pull request's diff, a link, a `path:line` pointer, `.extant.toml` - and on a
pull request from a fork the repository is somebody else's. Found by the review
of pull request #16 on 2026-09-27: a consistency source spelled `.git/config`
or an absolute path was joined onto the root and read, and the rule PRINTS what
its pattern captured; and a tracked document that is a symbolic link was
followed wherever it led, `/dev/zero` included. `extant/files.py` holds the
one check; these pin it at the readers.

The symlink tests skip where the platform will not make one - Windows without
the privilege, which is this project's development machine - and run on Linux,
which is where CI and the action run. The two tests that need no link run
everywhere, and they are the ones a fork could reach by configuration alone.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

SECRET = "s3cr3t-token-value"


def _verify(repo: Path, capsys) -> tuple[int, str]:
    from extant import cli
    code = cli.main(["--verify", "--repo", str(repo)])
    out = capsys.readouterr()
    return code, out.out + out.err


def _link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not permit symlink creation here")


def _commit_link(repo: Path, name: str) -> None:
    """Commit the link itself; the fixture's helper writes content, which
    would write THROUGH the link."""
    import subprocess
    for args in (["add", name], ["commit", "-q", "-m", f"docs: {name} as a link"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


# --------------------------------------------------------------------------
# 1. By configuration alone - reachable on every platform
# --------------------------------------------------------------------------

def test_a_consistency_source_in_the_git_directory_is_not_read(git_repo, capsys) -> None:
    """`.git/config` is where actions/checkout persists the job's credential,
    and it sits INSIDE the checkout's directory, so a check that the path
    stays under the root is not enough on its own."""
    import subprocess
    repo, commit = git_repo
    subprocess.run(["git", "config", "extant.secret", SECRET], cwd=repo, check=True)
    commit("STATUS.md", "# Status\n\n## Phase 1 - work (2026-09-27)\n\nDone.\n",
           "docs: status")
    commit(".extant.toml",
           'primary_doc = "STATUS.md"\n\n'
           "[extant.consistency.leak]\n"
           "\".git/config\" = 'secret = (\\S+)'\n"
           "\"STATUS.md\" = '(Done)'\n", "chore: config")

    code, out = _verify(repo, capsys)

    assert SECRET not in out, out
    assert "leads into the git directory" in out, out
    assert code == 1, out


def test_a_consistency_source_outside_the_checkout_is_not_read(git_repo, capsys,
                                                               tmp_path) -> None:
    """An absolute source replaced the root it was joined onto."""
    repo, commit = git_repo
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "secret.txt").write_text(f"token={SECRET}\n", encoding="utf-8")
    commit("STATUS.md", "# Status\n\n## Phase 1 - work (2026-09-27)\n\nDone.\n",
           "docs: status")
    commit(".extant.toml",
           'primary_doc = "STATUS.md"\n\n'
           "[extant.consistency.leak]\n"
           f"\"{(outside / 'secret.txt').as_posix()}\" = 'token=(\\S+)'\n"
           "\"STATUS.md\" = '(Done)'\n", "chore: config")

    code, out = _verify(repo, capsys)

    assert SECRET not in out, out
    assert "leads outside the repository" in out, out
    assert code == 1, out


def test_inside_answers_for_the_names_that_are_not_links(tmp_path) -> None:
    from extant.files import OutsideRepository, inside
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text("x", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")

    assert inside(repo, repo / "docs" / "a.md") == repo / "docs" / "a.md"
    # Missing is returned untouched, for `open` to report as it always has.
    assert inside(repo, repo / "gone.md") == repo / "gone.md"
    for refused in (repo / ".." / "outside.md", repo / ".git" / "config",
                    repo / "docs", tmp_path / "outside.md"):
        with pytest.raises(OutsideRepository):
            inside(repo, refused)


# --------------------------------------------------------------------------
# 2. Through a symbolic link - Linux, where the links are real
# --------------------------------------------------------------------------

def test_a_link_that_stays_inside_is_followed(tmp_path) -> None:
    """`CLAUDE.md -> AGENTS.md` is the common case, and moby's own."""
    from extant.files import inside
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("x", encoding="utf-8")
    _link(repo / "CLAUDE.md", repo / "AGENTS.md")
    assert inside(repo, repo / "CLAUDE.md") == repo / "CLAUDE.md"


def test_a_swept_document_linked_out_of_the_checkout_is_unreadable(
        git_repo, capsys, tmp_path) -> None:
    """Counted and named as unreadable, and none of its bytes judged."""
    from extant import session
    from extant.sweep import run_sweep
    repo, commit = git_repo
    outside = tmp_path / "elsewhere.md"
    outside.write_text(f"See `src/{SECRET}.py`.\n", encoding="utf-8")
    commit("README.md", "# Readme\n", "docs: readme")
    _link(repo / "notes.md", outside)
    _commit_link(repo, "notes.md")

    session.reload_config(repo)
    run_sweep(repo, "text")
    out = capsys.readouterr()
    text = out.out + out.err

    assert SECRET not in text, text
    assert "notes.md (OutsideRepository)" in text, text


@pytest.mark.skipif(not os.path.exists("/dev/zero"), reason="needs /dev/zero")
def test_a_link_target_that_never_ends_is_not_read(git_repo, capsys) -> None:
    """`x.md -> /dev/zero` read forever: `md_anchor` read a fragment link's
    target whole, and `resolve_reference` settles the spelling, not where the
    bytes are. The document naming it must still be checked, and finish."""
    repo, commit = git_repo
    commit("STATUS.md", "# Status\n\n## Phase 1 - work (2026-09-27)\n\n"
           "See [the part](zero.md#part).\n", "docs: status")
    _link(repo / "zero.md", Path("/dev/zero"))
    _commit_link(repo, "zero.md")
    commit(".extant.toml", 'primary_doc = "STATUS.md"\n', "chore: config")

    code, out = _verify(repo, capsys)

    assert "checked STATUS.md" in out, out


def test_an_extra_document_linked_out_of_the_checkout_is_a_finding(
        git_repo, capsys, tmp_path) -> None:
    """A configured document this will not read gates, as a missing one
    does, and says why."""
    repo, commit = git_repo
    outside = tmp_path / "elsewhere.md"
    outside.write_text(f"{SECRET}\n", encoding="utf-8")
    commit("STATUS.md", "# Status\n\n## Phase 1 - work (2026-09-27)\n\nDone.\n",
           "docs: status")
    _link(repo / "AGENTS.md", outside)
    _commit_link(repo, "AGENTS.md")
    commit(".extant.toml",
           'primary_doc = "STATUS.md"\nextra_docs = ["AGENTS.md"]\n',
           "chore: config")

    code, out = _verify(repo, capsys)

    assert SECRET not in out, out
    assert "missing-document" in out and "not read" in out, out
    assert code == 1, out
