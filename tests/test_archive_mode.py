"""`--archive`, which nothing has ever driven through the CLI.

Every existing archive test calls `entries.archive()` directly with an explicit
`retain`, which leaves two things unexercised, and they are the same two the
`--search` break lived in:

* `run_archive()` itself - whether the mode is wired to the parser at all, and
  whether it hands `archive()` the DERIVED Config. That is the exact shape that
  shipped broken in `--search`: a mode nothing drove end to end, passing the raw
  `StatusConfig` where the derived object was needed. `--archive` reaches
  `split_entries` through the same funnel.
* `retain=None`, the documented fallback to `config.retain_entries`. Every call
  in the suite passes `3`, so the branch that reads the setting has never run.
  The docstring on `archive()` explains at length why the fallback is read
  inside the call rather than written as a parameter default - and nothing was
  checking that it stayed that way.

The subprocess tests here go through the shipped entry point for the reason
tests/test_search_mode.py exists: an in-process call skips argparse and the
config load, which is where the last mode of this kind broke.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOL = (Path(__file__).resolve().parent.parent / "plugin" / "skills" / "extant"
        / "payload" / "extant_collect.py")

# Five phase entries and a base section, so the default retain of 3 leaves two
# to move. Newest first, which is the order the archive relies on.
FIVE_ENTRIES = (
    "# Status\n\n"
    "## Phase 5 - fifth (2026-05-01)\n\nbody five\n\n"
    "## Phase 4 - fourth (2026-04-01)\n\nbody four\n\n"
    "## Phase 3 - third (2026-03-01)\n\nbody three\n\n"
    "## Phase 2 - second (2026-02-01)\n\nbody two\n\n"
    "## Phase 1 - first (2026-01-01)\n\nbody one\n\n"
    "## 1. Reference\n\nreference body\n"
)


def run_tool(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), "--repo", str(repo), *args],
                          cwd=repo, capture_output=True, text=True, encoding="utf-8")


def _read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def test_archive_mode_reports_what_it_moved(git_repo) -> None:
    """The mode is wired, runs, and prints its denominator.

    `retained=` and `archived=` are that denominator: "archived nothing because
    there was nothing to move" and "archived nothing because the mode is broken"
    print the same empty success otherwise.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", FIVE_ENTRIES, "docs: five entries")

    result = run_tool(repo, "--archive")

    combined = result.stdout + result.stderr
    assert "Traceback" not in combined, combined
    assert result.returncode == 0, combined
    assert "retained=3 archived=2" in result.stdout, result.stdout


def test_archive_mode_actually_relocates_the_oldest_entries(git_repo) -> None:
    """The counts are an aggregate; this is the thing they claim.

    Asserted separately because a mode that printed `archived=2` while writing
    nothing would satisfy the test above completely. The two failures are
    different and only one of them loses work.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", FIVE_ENTRIES, "docs: five entries")

    result = run_tool(repo, "--archive")
    assert result.returncode == 0, result.stdout + result.stderr

    live = _read(repo / "NEXT_SESSION.md")
    archived = _read(repo / "docs" / "status-archive.md")

    assert "## Phase 5" in live and "## Phase 3" in live
    assert "## Phase 2" not in live and "## Phase 1" not in live
    assert "## Phase 2" in archived and "## Phase 1" in archived
    # Newest first in the archive too, so a later run can prepend above it.
    assert archived.index("## Phase 2") < archived.index("## Phase 1")
    # GA-4: the reference section is not history and never moves.
    assert "## 1. Reference" in live
    assert "## 1. Reference" not in archived


def test_archive_mode_never_stacks_a_second_pointer(git_repo) -> None:
    """Two real runs, with a new entry written between them.

    The second run has to actually MOVE something for this to mean anything,
    and getting that wrong is how the first version of this test passed against
    a deliberately broken build. Running `--archive` twice over an UNCHANGED
    document returns early - the retained count already equals the window - so
    nothing is written the second time and a stale pointer could not have been
    duplicated whatever the code did. Staging a sixth entry first is what puts
    the pointer path back in the run.

    The bug it guards: `split_entries` files the pointer under "other", every
    "other" segment is kept inline forever, and nothing removed the LAST run's
    pointer before appending this run's - so N runs left N stacked blocks in
    the document every session is required to read first.

    Through the CLI rather than through `entries.archive()`, because the prefix
    that identifies a stale pointer comes from the config a real invocation
    loads from the repository.
    """
    repo, commit = git_repo
    commit("NEXT_SESSION.md", FIVE_ENTRIES, "docs: five entries")

    first = run_tool(repo, "--archive")
    assert "retained=3 archived=2" in first.stdout, first.stdout
    assert _read(repo / "NEXT_SESSION.md").count("## Archive pointer") == 1

    # The next session prepends its entry above everything the last run kept,
    # the pointer block included.
    staged = _read(repo / "NEXT_SESSION.md").replace(
        "## Phase 5 - fifth (2026-05-01)",
        "## Phase 6 - sixth (2026-06-01)\n\nbody six\n\n"
        "## Phase 5 - fifth (2026-05-01)", 1)
    commit("NEXT_SESSION.md", staged, "docs: a sixth entry")

    second = run_tool(repo, "--archive")

    combined = second.stdout + second.stderr
    assert "Traceback" not in combined, combined
    assert second.returncode == 0, combined
    assert "archived=1" in second.stdout, second.stdout

    live = _read(repo / "NEXT_SESSION.md")
    assert live.count("## Archive pointer") == 1, live
    archived = _read(repo / "docs" / "status-archive.md")
    assert "## Archive pointer" not in archived, archived
    # Newest-first across runs: what this run moved sits above run one's.
    assert archived.index("## Phase 3") < archived.index("## Phase 2"), archived


def test_archive_without_a_retain_reads_the_configured_value(git_repo,
                                                             reconfigure) -> None:
    """`retain=None` means "however many this project keeps".

    The value is read from the Config INSIDE the call. Written the other way -
    as a parameter default - the expression evaluates once at import and freezes
    whatever the module was configured with then, so `reload_config` could
    change the setting and this function would go on using the stale one. A
    configured 1 against a default of 3 is what tells those two apart: a frozen
    default retains 3 here.
    """
    from extant import entries
    repo, commit = git_repo
    commit("NEXT_SESSION.md", FIVE_ENTRIES, "docs: five entries")

    config = reconfigure(retain_entries=1)
    counts = entries.archive(repo, None, config)

    assert counts["retained"] == 1, counts
    assert counts["archived"] == 4, counts
    live = _read(repo / "NEXT_SESSION.md")
    assert "## Phase 5" in live
    assert "## Phase 4" not in live


def test_split_entries_refuses_the_raw_settings_object() -> None:
    """The guard on the funnel every archive and rule passes a config through.

    `StatusConfig` is the parsed settings and `Config` is what is derived from
    them; they are similar enough that passing the wrong one is a repeatable
    mistake rather than a typo, and it is exactly what shipped broken in
    `--search`. Unchecked, the next line raises a bare AttributeError naming a
    field that sounds like a misspelling, which sends the reader somewhere else
    entirely - so the message has to name the actual cause and the way out.
    """
    from extant import entries, session

    with pytest.raises(TypeError) as caught:
        entries.split_entries("# doc\n\n## Phase 1 - x\n\nbody\n", session.CONFIG)

    message = str(caught.value)
    assert "StatusConfig" in message, message
    assert "Config.build" in message, message
