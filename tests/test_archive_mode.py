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

from conftest import GitRepo, Reconfigure

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


def test_archive_mode_reports_what_it_moved(git_repo: GitRepo) -> None:
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


def test_archive_mode_actually_relocates_the_oldest_entries(git_repo: GitRepo) -> None:
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


def test_archive_mode_never_stacks_a_second_pointer(git_repo: GitRepo) -> None:
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


@pytest.mark.parametrize("config, entry, pointer", [
    # The installer derives `entry_prefix` from `^(#{1,4})\s+(\S+)`, so every
    # heading level is installer output rather than exotic configuration.
    ('entry_prefix = "### Session "\n', "### Session", "### Archive pointer"),
    ('entry_prefix = "# Day "\n', "# Day", "# Archive pointer"),
    ('entry_prefix = "#### Week "\n', "#### Week", "#### Archive pointer"),
    # A configured pointer is what is WRITTEN, so it is what is stripped.
    ('pointer_prefix = "## Older entries"\n', "## Phase", "## Older entries"),
], ids=["level-3", "level-1", "level-4", "configured-pointer"])
def test_the_pointer_never_travels_into_the_archive(git_repo: GitRepo, config, entry,
                                                    pointer) -> None:
    """The pointer is written at the entries' own heading level, and is the
    one `pointer_prefix` names.

    It was written as a hard-coded `## Archive pointer` and recognised by
    `pointer_prefix`, while `split_entries` cuts at the heading level
    `entry_prefix` names. With `### ` entries the `## ` pointer is no section
    boundary there: it was glued onto the oldest entry kept, never seen as the
    last run's pointer, and carried into the archive inside that entry when it
    retired - one more stale block per run. A configured `pointer_prefix` was
    never what got written, so it was never stripped either.
    """
    repo, commit = git_repo
    body = "".join(f"{entry} {n} - entry {n} (2026-0{n}-01)\n\nbody {n}\n\n"
                   for n in range(5, 0, -1))
    commit(".extant.toml", config, "chore: config")
    commit("NEXT_SESSION.md", "# Status\n\n" + body, "docs: five entries")

    first = run_tool(repo, "--archive")
    assert "retained=3 archived=2" in first.stdout, (first.stdout, first.stderr)
    staged = _read(repo / "NEXT_SESSION.md").replace(
        f"{entry} 5 ", f"{entry} 6 - entry 6 (2026-06-01)\n\nbody 6\n\n{entry} 5 ", 1)
    commit("NEXT_SESSION.md", staged, "docs: a sixth entry")
    second = run_tool(repo, "--archive")
    assert "archived=1" in second.stdout, (second.stdout, second.stderr)

    live = _read(repo / "NEXT_SESSION.md")
    archived = _read(repo / "docs" / "status-archive.md")
    assert live.count(f"\n{pointer}\n") == 1, live
    assert "pointer" not in archived.lower(), archived
    # And it is still the newest-first archive the plain case produces.
    assert archived.index(f"{entry} 3 ") < archived.index(f"{entry} 2 "), archived


def test_a_section_a_person_wrote_is_never_taken_for_the_pointer(
        git_repo: GitRepo) -> None:
    """The pointer is recognised by its header AND by the one line `archive`
    writes under it, never by the header alone.

    It was any section whose heading STARTS WITH `pointer_prefix`. With the
    default prefixes every `## ` heading is a section, so a reference section
    a person titled "Archive pointer format" was the stale pointer: stripped
    from the live document, put in neither file, and subtracted from the
    conservation guard's baseline as the guard is told to subtract the stale
    pointer - so the one irreversible write deleted it and exited 0.
    """
    repo, commit = git_repo
    written = "How we write pointers: by hand, and only here."
    doc = FIVE_ENTRIES.replace(
        "## Phase 3 ", f"## Archive pointer format\n\n{written}\n\n## Phase 3 ", 1)
    commit("NEXT_SESSION.md", doc, "docs: five entries and a section")

    done = run_tool(repo, "--archive")
    assert "archived=2" in done.stdout, (done.stdout, done.stderr)
    live = _read(repo / "NEXT_SESSION.md")
    archived = _read(repo / "docs" / "status-archive.md")
    assert written in live + archived, (live, archived)


@pytest.mark.parametrize("joiner, added", [
    ("\n", "> And the 2025 entries are in the wiki."),
    # On the generated line itself, ending as it does in a backtick and a
    # full stop - which a reader matching any archive name greedily took
    # for the generated line, and deleted.
    (" ", "Older ones: see `wiki/archive`."),
], ids=["own-line", "same-line"])
def test_a_line_added_under_the_pointer_is_kept(
        git_repo: GitRepo, joiner, added) -> None:
    """A pointer somebody wrote into is no longer only the tool's output, so
    it is kept rather than regenerated over: the next run writes a fresh
    pointer beside it, which is visible, where stripping it deleted a line a
    person wrote. Every pointer this tool has ever written carries exactly
    the one generated line, so recognising that line costs no old pointer."""
    repo, commit = git_repo
    commit("NEXT_SESSION.md", FIVE_ENTRIES, "docs: five entries")
    run_tool(repo, "--archive")
    staged = _read(repo / "NEXT_SESSION.md").replace(
        "live in `docs/status-archive.md`.\n",
        f"live in `docs/status-archive.md`.{joiner}{added}\n", 1).replace(
        "## Phase 5 ", "## Phase 6 - sixth (2026-06-01)\n\nbody six\n\n## Phase 5 ", 1)
    commit("NEXT_SESSION.md", staged, "docs: a sixth entry and a note")

    done = run_tool(repo, "--archive")
    assert "archived=1" in done.stdout, (done.stdout, done.stderr)
    live = _read(repo / "NEXT_SESSION.md")
    archived = _read(repo / "docs" / "status-archive.md")
    assert added in live + archived, (live, archived)


@pytest.mark.parametrize("prefix", ["Phase ", "**Phase "])
def test_a_pointer_under_a_non_heading_prefix_is_never_an_entry(
        git_repo: GitRepo, prefix) -> None:
    """`entry_prefix` need not be a heading, and the pointer is derived from
    its first word: `Phase Archive pointer`, which starts with the entry
    prefix itself. Classified by that prefix alone, it was an ENTRY - one
    more in every count, and after a `retain_entries = 0` archive the only
    one, so the newest-entry rules read the pointer as the newest entry. It
    is classified as the pointer first, by the one reader every count uses.
    """
    from extant import config, entries
    repo, commit = git_repo
    body = "".join(f"{prefix}{n} - entry {n}\n\nbody {n}\n\n" for n in (3, 2, 1))
    commit(".extant.toml", f'entry_prefix = "{prefix}"\nretain_entries = 1\n',
           "chore: config")
    commit("NEXT_SESSION.md", "# Status\n\n" + body, "docs: three entries")

    run_tool(repo, "--archive")
    searched = run_tool(repo, "--search", "body")
    assert "in 3 entries" in searched.stdout, (searched.stdout, searched.stderr)

    commit(".extant.toml", f'entry_prefix = "{prefix}"\nretain_entries = 0\n',
           "chore: keep none")
    run_tool(repo, "--archive")
    built = config.Config.build(config.load_config(repo))
    live = _read(repo / "NEXT_SESSION.md")
    assert built.pointer_prefix in live, live
    assert entries.newest_entry(live, built) is None, live


@pytest.mark.parametrize("retain, archive_doc", [
    (3, "docs/status-archive.md"), (0, "a.md"), (-1, "a.md"),
    (12, "docs/odd `name`.md"),
], ids=["default", "zero", "negative", "backtick"])
def test_every_pointer_the_writer_can_produce_is_recognised(
        retain, archive_doc) -> None:
    """The writer and the reader of the pointer's line sit side by side in
    extant/entries.py, and must agree on everything the writer can produce:
    a pointer the reader misses is kept as a person's section and a fresh
    one is stacked beside it on every run. A negative `retain_entries` is
    accepted by the loader, and nothing stops a backtick in `archive_doc`."""
    import dataclasses
    from extant import entries, session
    built = dataclasses.replace(session._ACTIVE, archive_doc=archive_doc)
    chunk = f"{built.pointer_prefix}\n\n{entries._pointer_line(retain, archive_doc)}\n\n"
    assert entries._is_pointer(chunk, built), chunk


def test_archive_without_a_retain_reads_the_configured_value(
        git_repo: GitRepo, reconfigure: Reconfigure) -> None:
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


def test_a_crash_between_the_two_writes_cannot_lose_an_entry(
        git_repo: GitRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    """The conservation guard proves a VALUE; this proves the WRITE ORDER.

    `archive()` calls itself the only irreversible file operation in the
    system, and it asserts multiset conservation of every line before writing
    anything. That assertion is about two strings in memory. It says nothing
    about a process that dies between the two `open(..., "w")` calls that put
    them on disk, and there is no ordering of those two writes the Counter
    could distinguish.

    Truncating the primary FIRST leaves a window in which the retired entries
    are in neither file - the one outcome the whole function exists to make
    impossible, reached by a route its own guard cannot see. Writing the
    archive first leaves the same crash duplicating them instead, and a
    duplicate is something a reader can repair.

    The crash is injected rather than waited for: the second write-mode open
    raises, which is what a full disk, a revoked permission or a killed
    process all look like from here.
    """
    import builtins

    repo, commit = git_repo
    commit("NEXT_SESSION.md", FIVE_ENTRIES, "docs: five entries")

    real_open = builtins.open
    writes = []

    def failing_open(file, mode="r", *args, **kwargs):
        if "w" in mode:
            writes.append(str(file))
            if len(writes) == 2:
                raise OSError("no space left on device")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", failing_open)

    from extant import entries, session
    config = session.context(repo).config
    with pytest.raises(OSError):
        entries.archive(repo, 3, config)

    monkeypatch.undo()

    # Whatever else happened, Phase 1 and Phase 2 still exist somewhere.
    live = _read(repo / "NEXT_SESSION.md")
    archive_path = repo / "docs" / "status-archive.md"
    archived = _read(archive_path) if archive_path.exists() else ""
    for entry in ("## Phase 1", "## Phase 2"):
        assert entry in live or entry in archived, (
            entry + " survived neither write; " + str(writes))
