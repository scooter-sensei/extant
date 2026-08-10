"""Per-rule denominators in `--sweep`.

A sweep used to report two numbers: how many files it read, and how many
repository-wide rules ran. Neither says whether a RULE examined anything, so a
sweep of a repository where every pattern matched nothing printed the same
cheerful summary as a sweep of a clean one - the conflation this whole project
exists to remove, still present in its own first-run command.

`--verify` has reported the per-rule count since the beginning. The sweep never
called `count_examined` at all.

The hard part is not the sum. It is that a sweep does not run every rule on
every document: entry-scoped rules are skipped outside the primary document,
markdown-only rules are skipped for `.rst`, and repository-scoped rules run
once for the whole survey. Counting candidates a rule never looked at would
report coverage that does not exist, which is worse than reporting none -
it is the reassuring number rather than the honest one.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
COLLECTOR = PAYLOAD / "extant_collect.py"
sys.path.insert(0, str(PAYLOAD))

# One backticked SHA, one relative link, one branch token inside a phase entry.
# Each is a candidate for a different rule, so a denominator that reports one
# number for all of them is distinguishable from one that counts per rule.
ENTRY = """# Status

## Phase 7 - Widgets (in progress, 2026-08-04)

Work continues on `feature/widgets`.
Shipped in `abc1234`. See [the plan](docs/gone.md).
"""

EXAMINED = re.compile(r"examined: (.+)")


def sweep(repo: Path, collector: Path | None = None) -> str:
    done = subprocess.run(
        [sys.executable, str(collector or COLLECTOR), "--repo", str(repo),
         "--sweep"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    return done.stdout + done.stderr


def counts(output: str) -> dict[str, int]:
    """The `examined:` line, parsed back into a mapping.

    Parsed rather than matched as a substring so a test asserting `dead-sha 3`
    cannot pass against output reading `dead-sha 30`.
    """
    match = EXAMINED.search(output)
    assert match, f"no examined line in:\n{output}"
    out: dict[str, int] = {}
    for item in match.group(1).split(", "):
        kind, _, number = item.rpartition(" ")
        out[kind] = int(number)
    return out


def install_collector(repo: Path) -> Path:
    """Copy the collector in as `tools/`, the way it actually ships.

    Configuration is discovered relative to the SCRIPT. Run from this source
    tree against a temporary repository it reads EXTANT's `.extant.toml` - so
    a test about which documents are primary, or about which branch names are
    recognised, would silently measure this project's settings instead of the
    defaults it means to exercise.
    """
    import shutil
    tools = repo / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("extant_collect.py", "extant_config.py"):
        shutil.copyfile(PAYLOAD / name, tools / name)
    # The shim's version handshake (Task 1) imports `extant` at module load,
    # so a bare shim copy with no package beside it now crashes with
    # ModuleNotFoundError instead of running. Copy the package too.
    shutil.copytree(PAYLOAD / "extant", tools / "extant",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return tools / "extant_collect.py"


@pytest.fixture
def three_documents(git_repo):
    """Three unconfigured documents, each carrying the same three candidates."""
    repo, commit = git_repo
    for name in ("README.md", "docs/a.md", "docs/b.md"):
        commit(name, ENTRY, f"docs: {name}")
    return repo


def test_every_rule_reports_a_denominator(three_documents) -> None:
    """No rule may be absent from the line.

    Imported from RULES rather than written out, so a fourteenth rule that
    forgets its denominator fails here instead of shipping silent.
    """
    import extant_collect as hc

    reported = counts(sweep(three_documents))
    missing = sorted({rule.kind for rule in hc.RULES} - set(reported))
    assert not missing, f"rules with no denominator: {missing}"


def test_candidates_are_summed_across_documents(three_documents) -> None:
    """The sum, which is the point of reporting it at all.

    Catches an implementation that reports only the last document's counts, or
    only the first - both of which look right on a one-document repository.
    """
    reported = counts(sweep(three_documents))
    assert reported["dead-sha"] == 3, reported
    assert reported["dead-md-link"] == 3, reported


def test_a_rule_that_examined_nothing_anywhere_is_named(three_documents) -> None:
    """Zeros are REPORTED, not filtered.

    A rule examining nothing across a whole repository is the loudest possible
    signal that its pattern does not match what this project writes, and
    dropping it from the line is what turns an inert rule into a silent pass.
    Nothing here states a merge claim, so that rule must say so out loud.
    """
    output = sweep(three_documents)
    reported = counts(output)
    assert reported["false-merge-claim"] == 0, reported
    assert "examined nothing" in output, output
    assert "false-merge-claim" in output.split("examined nothing")[1], output


def test_a_markdown_only_rule_is_not_counted_for_an_rst_document(git_repo) -> None:
    """`[text](url)` in an `.rst` file is not a link, and no rule reads it.

    The positive control is in the same test and is what makes it mean
    anything: identical bytes in a `.md` file DO count, so a reported 1 proves
    the candidate was found and the format is what excluded the other one. A
    naive sum over every document reports 2.
    """
    repo, commit = git_repo
    body = "See [the plan](docs/gone.md).\n"
    commit("notes.md", body, "docs: markdown")
    commit("notes.rst", body, "docs: rst")

    reported = counts(sweep(repo))
    assert reported["dead-md-link"] == 1, (
        "the rst document's link-shaped text was counted for a rule that "
        f"never ran on it: {reported}")


def test_an_entry_scoped_rule_is_counted_only_where_it_runs(git_repo) -> None:
    """Entry-scoped rules run on the primary document and nowhere else.

    `NEXT_SESSION.md` is the default primary document, so it needs no
    configuration to be treated as one. The sibling holds the same bytes and no
    rule looks at its branch token. Reporting 2 here would claim the survey
    checked a live claim it never read.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", ENTRY, "docs: status")
    commit("docs/copy.md", ENTRY, "docs: a copy of it")
    installed = install_collector(repo)

    reported = counts(sweep(repo, collector=installed))
    assert reported["stale-live-claim"] == 1, (
        "a branch token outside the primary document is read by no rule, so "
        f"counting it overstates coverage: {reported}")
    # The control: a whole-file rule sees both documents. Without this, an
    # implementation that counted NOTHING outside the primary document would
    # pass the assertion above while reporting a denominator of 1 for
    # everything.
    assert reported["dead-sha"] == 2, reported


def test_a_claim_inside_a_code_block_is_not_counted(git_repo) -> None:
    """The denominator reads PROSE, because six of the rules do.

    They open with `text = _prose(text)` - claims inside code are examples, not
    promises - while `count_examined` scanned the raw document, so every fenced
    sample claim was reported as a candidate no rule had read. Measured on
    rust-lang/rfcs before the fix: `dead-sha 23` where the rule looked at 11.

    Each assertion carries its own positive control: the identical claim sits
    once in prose and once inside the fence, so `1` proves the pattern matches
    and the fence is what excluded the other. The old behaviour reports 2.
    """
    repo, commit = git_repo
    commit("README.md",
           "# demo\n\n"
           "Shipped in `abc1234`. See `docs/real.md`.\n\n"
           "```console\n"
           "Shipped in `dead123`. See `docs/fake.md`.\n"
           "```\n",
           "docs: readme")

    reported = counts(sweep(repo))
    assert reported["dead-sha"] == 1, (
        f"a SHA inside a fence is read by no rule: {reported}")
    assert reported["dead-path-pointer"] == 1, (
        f"a path pointer inside a fence is read by no rule: {reported}")


def test_a_repository_rule_is_counted_once_not_once_per_document(git_repo) -> None:
    """A repository-scoped rule runs once for the whole survey, so its
    candidates are the repository's, not each document's.

    One LFS-governed path and several documents. Counting inside the document
    loop reports one per file, which would say the survey examined the same
    path repeatedly - and on a repository with no markdown at all it would
    report 0 governed paths while `.gitattributes` sat there governing
    hundreds.

    `NEXT_SESSION.md` is here deliberately. Without a PRIMARY document the
    applicability check excludes repository-scoped rules from every file on its
    own, so an implementation that accumulated them per document would produce
    the right answer anyway and this test would pass against it. Verified by
    mutation: with the primary document absent, the wrong implementation
    survives.
    """
    repo, commit = git_repo
    commit(".gitattributes", "*.png filter=lfs diff=lfs merge=lfs -text\n",
           "chore: track binaries in LFS")
    commit("art/logo.png", "version https://git-lfs.github.com/spec/v1\n",
           "feat: add the logo")
    commit("NEXT_SESSION.md", "# Status\n\nnothing claimed here\n",
           "docs: the primary document")
    for name in ("README.md", "docs/a.md", "docs/b.md"):
        commit(name, "# doc\n\nnothing claimed here\n", f"docs: {name}")

    reported = counts(sweep(repo))
    assert reported["raw-lfs-blob"] == 1, (
        f"one governed path, counted once for the sweep: {reported}")
