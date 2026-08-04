"""`--sweep`: survey every tracked markdown file, gate only on configured ones.

The mode exists because the demonstration that shows what this tool is for -
findings across a whole repository, from a standing start - was not a command.
It took a hand-written shell loop over `git ls-files`, which nobody discovers.

The tests that matter here are the ones about what a sweep does NOT do.
Checking every markdown file in extant's own repository produces findings that
are ALL false: `abc1234` and `v2.1` are the example claims inside the documents
that document the rules. The exact count is not written down, because nothing
here verifies it and it moves whenever a document is edited. So the partition between configured and unreviewed is
not presentation, it is the difference between a useful survey and a validator
that cries wolf on first contact.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

COLLECTOR = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
             / "extant" / "payload" / "extant_collect.py")

# A dead SHA and a dead link per document, so a sweep that reads only the first
# file, or only the configured ones, is distinguishable from one that reads
# everything.
#
# Every SHA here contains a DIGIT on purpose. `_looks_like_sha` requires one,
# so that hex-shaped English words - `deadbeef`, `facade`, `decade` - are not
# read as commits. A fixture using `deadbee` produced no finding and looked
# exactly like a broken sweep.
ROTTED = "# {title}\n\nShipped in `{sha}`.\nSee [the plan](docs/{missing}.md).\n"


def sweep(repo: Path, *args: str,
          collector: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(collector or COLLECTOR),
         "--repo", str(repo), "--sweep", *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )


def install_collector(repo: Path) -> Path:
    """Copy the collector in as `tools/`, the way it actually ships.

    Configuration is discovered relative to the SCRIPT, so a collector run from
    this source tree against a temporary repository reads THIS project's
    `.extant.toml` and says so. Any test about the target's own configuration
    has to use the installed shape or it silently tests the wrong settings.
    """
    tools = repo / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("extant_collect.py", "extant_config.py"):
        shutil.copyfile(COLLECTOR.parent / name, tools / name)
    return tools / "extant_collect.py"


@pytest.fixture
def rotted_repo(git_repo) -> Path:
    """Three markdown files, each carrying one dead claim, none configured."""
    repo, commit = git_repo
    commit("README.md", ROTTED.format(title="Project", sha="dead1ee", missing="a"),
           "chore: readme")
    commit("docs/plan.md", ROTTED.format(title="Plan", sha="badf00d", missing="b"),
           "chore: plan")
    commit("docs/spec.md", ROTTED.format(title="Spec", sha="0badc0d", missing="c"),
           "chore: spec")
    return repo


def test_a_sweep_needs_no_configuration_at_all(rotted_repo) -> None:
    """The first-run command. No `.extant.toml`, nothing written, findings shown.

    A wrong implementation that requires `primary_doc` to exist reports
    "no such document: NEXT_SESSION.md" and finds nothing, which is exactly
    what `--verify` does and exactly why this mode was added.
    """
    result = sweep(rotted_repo)

    assert "no such document" not in result.stdout + result.stderr, result.stdout
    combined = result.stdout + result.stderr
    for name in ("README.md", "docs/plan.md", "docs/spec.md"):
        assert name in combined, f"{name} was never swept:\n{combined}"
    for sha in ("dead1ee", "badf00d", "0badc0d"):
        assert sha in combined, (
            f"a sweep that reads every file must report {sha}:\n{combined}"
        )


def test_the_sweep_reports_its_denominator(rotted_repo) -> None:
    """How many files were looked at, split by whether they gate.

    "0 findings" and "0 files examined" print identically without this, and a
    sweep is where that is easiest to get wrong: a glob matching nothing would
    report a clean repository in a cheerful voice.
    """
    result = sweep(rotted_repo)

    combined = result.stdout + result.stderr
    assert "swept 3 markdown file(s)" in combined, combined
    assert "0 configured" in combined, (
        f"nothing is configured here, and the summary has to say so:\n{combined}"
    )
    assert "3 unreviewed" in combined, combined


def test_unreviewed_findings_never_decide_the_exit_code(rotted_repo) -> None:
    """The whole design. Measured, not a preference.

    On extant's own repository every finding outside the configured set is an
    illustrative claim in a document about claim-checking. Gating on those would
    make the first run of the tool a wall of false positives.

    A wrong implementation that exits 1 on any finding fails here.
    """
    result = sweep(rotted_repo)

    assert result.returncode == 0, (
        "three unreviewed documents with dead claims must not fail a run:\n"
        + result.stdout + result.stderr
    )
    # Nothing is configured here, so the summary says that rather than the
    # promote-a-file line. Both state that unreviewed findings cannot fail.
    assert "nothing here can fail" in result.stdout + result.stderr, (
        result.stdout + result.stderr
    )


def test_a_configured_document_does_decide_the_exit_code(rotted_repo) -> None:
    """Promoting a file into `extra_docs` is what turns a survey into a gate.

    This is the adoption path the summary line advertises, so it has to work:
    read the unreviewed findings, decide a file is real, list it, and from then
    on it fails the build. A wrong implementation that never gates makes the
    configured/unreviewed split cosmetic.
    """
    installed = install_collector(rotted_repo)
    (rotted_repo / ".extant.toml").write_text(
        'extra_docs = ["docs/plan.md"]\n', encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=rotted_repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: config"], cwd=rotted_repo,
                   check=True, capture_output=True)

    result = sweep(rotted_repo, collector=installed)
    assert "was NOT read" not in result.stdout + result.stderr, (
        "the target's own config was not picked up, so this test would be "
        "measuring the wrong settings:\n" + result.stdout + result.stderr
    )

    assert result.returncode == 1, (
        "a configured document with a dead SHA must fail the run:\n"
        + result.stdout + result.stderr
    )
    combined = result.stdout + result.stderr
    assert "1 configured" in combined, combined
    # Still surveyed, still not gating: the other two are unchanged.
    assert "unreviewed" in combined


def test_untracked_and_ignored_files_are_not_swept(rotted_repo) -> None:
    """`git ls-files`, not a filesystem walk.

    A build directory full of generated markdown, a vendored dependency, or a
    scratch note would otherwise be reported as project documentation. Using
    git's own index means the exclusion needs no skip-list to maintain, which
    is the kind of list that silently stops matching.
    """
    (rotted_repo / "scratch.md").write_text(
        ROTTED.format(title="Scratch", sha="feedfac", missing="d"), encoding="utf-8")
    (rotted_repo / "build").mkdir()
    (rotted_repo / "build" / "generated.md").write_text(
        ROTTED.format(title="Gen", sha="cafebab", missing="e"), encoding="utf-8")

    result = sweep(rotted_repo)

    combined = result.stdout + result.stderr
    assert "swept 3 markdown file(s)" in combined, (
        f"untracked files were swept:\n{combined}"
    )
    assert "feedfac" not in combined and "cafebab" not in combined, combined


def test_sweep_refuses_a_baseline_rather_than_ignoring_it(rotted_repo) -> None:
    """A baseline suppresses findings; a survey exists to show them.

    Accepting the flag and quietly doing nothing with it would let someone read
    "3 findings" while forty were hidden. Refusing costs one line of output and
    removes a whole class of wrong answer.
    """
    result = sweep(rotted_repo, "--baseline")

    assert result.returncode == 2, (
        f"expected a refusal, got {result.returncode}:\n"
        + result.stdout + result.stderr
    )
    assert "--baseline" in result.stderr, result.stderr


def test_an_empty_repository_says_so_instead_of_passing_quietly(git_repo) -> None:
    """Zero files swept is a fact worth printing, not a clean bill of health."""
    repo, commit = git_repo
    commit("main.py", "print('hi')\n", "chore: init")

    result = sweep(repo)

    assert result.returncode == 0
    assert "swept 0 markdown files" in result.stdout + result.stderr, (
        result.stdout + result.stderr
    )


def test_a_file_that_cannot_be_decoded_is_named_not_skipped(git_repo) -> None:
    """A file that could not be read is not a file with no findings.

    The two are indistinguishable in an exit code, so a sweep that skips a
    latin-1 document quietly under-reports on every repository holding one -
    and the denominator would still say it examined that file, which is the
    worse half: the count claims coverage the run did not have.

    Found by a mutation campaign. Replacing the `unreadable.append(...)` with a
    bare `continue` changed the behaviour and the entire suite stayed green,
    because nothing here had ever handed the sweep a file it could not decode.
    """
    repo, commit = git_repo
    commit("README.md", "# R\n\nFine.\n", "chore: init")
    # Not valid UTF-8 in any position, and tracked, so the sweep must meet it.
    (repo / "broken.md").write_bytes(b"# Caf\xe9\n\nSee [x](gone.md).\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "chore: latin-1"], cwd=repo,
                   check=True, capture_output=True)

    result = sweep(repo)

    combined = result.stdout + result.stderr
    assert "could not be read" in combined, (
        "an undecodable file has to be reported as such:\n" + combined
    )
    assert "broken.md" in combined, (
        "and it has to be NAMED, or nobody can act on it:\n" + combined
    )
