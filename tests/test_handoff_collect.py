"""Tests for tools/handoff_collect.py - the /handoff collector and validator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "handoff"
TOOL = SKILL_ROOT / "payload" / "handoff_collect.py"


def test_fixture_builds_a_repo_with_commits(git_repo):
    repo, commit = git_repo
    sha = commit("a.txt", "hello", "feat: test - first")
    assert len(sha) == 40
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout
    assert "feat: test - first" in log


def test_cli_help_exits_zero():
    result = subprocess.run(
        [sys.executable, str(TOOL), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--collect" in result.stdout


def test_parse_phase_from_task_suffix():
    from handoff_collect import parse_phase
    assert parse_phase("feat: voice - reload mailbox (9.6 Task 5)") == "9.6"
    assert parse_phase("refactor: settings - retire banner (9.6 Task 9)") == "9.6"


def test_parse_phase_from_bare_version():
    from handoff_collect import parse_phase
    assert parse_phase("docs: plan - Phase 9.5b core runtime") == "9.5b"


def test_parse_phase_unknown_when_absent():
    from handoff_collect import parse_phase
    assert parse_phase("chore: tidy imports") == "unknown"


def test_parse_phase_ignores_library_versions():
    """GA-2 regression: a real commit subject from main. A library version is
    not a phase number."""
    from handoff_collect import parse_phase
    subject = "fix: ui - System-tab Column anchor + PySide6 6.11 QML load guard"
    assert parse_phase(subject) == "unknown"


def test_boundary_is_last_commit_touching_the_handoff_doc(git_repo):
    from handoff_collect import find_boundary
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "old handoff\n", "docs: handoff - phase 1")
    boundary = commit("NEXT_SESSION.md", "newer handoff\n", "docs: handoff - phase 2")
    commit("src.py", "x = 1\n", "feat: thing - after the handoff")
    assert find_boundary(repo) == boundary


def test_boundary_empty_when_doc_has_no_history(git_repo):
    from handoff_collect import find_boundary
    repo, commit = git_repo
    commit("src.py", "x = 1\n", "feat: thing - only commit")
    assert find_boundary(repo) == ""


def test_commits_since_boundary_excludes_the_boundary_itself(git_repo):
    from handoff_collect import commits_since, find_boundary
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - phase 1")
    commit("a.py", "a = 1\n", "feat: a - thing (9.6 Task 1)")
    commit("b.py", "b = 1\n", "feat: b - other (9.6 Task 2)")
    result = commits_since(repo, find_boundary(repo))
    subjects = [c["subject"] for c in result]
    assert subjects == ["feat: a - thing (9.6 Task 1)", "feat: b - other (9.6 Task 2)"]
    assert all(c["phase"] == "9.6" for c in result)


def test_scan_todos_finds_markers_in_changed_files(git_repo):
    from handoff_collect import find_boundary, scan_todos
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - base")
    commit("a.py", "x = 1\n# TODO: fix this\n", "feat: a - with todo")
    todos = scan_todos(repo, find_boundary(repo))
    assert len(todos) == 1
    assert todos[0]["file"] == "a.py"
    assert todos[0]["line"] == 2
    assert "fix this" in todos[0]["text"]


def test_scan_todos_ignores_markdown(git_repo):
    """GA-5: docs legitimately contain the word TODO; only code counts."""
    from handoff_collect import find_boundary, scan_todos
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - base")
    commit("docs/plan.md", "- [ ] TODO: an example marker in a plan\n",
           "docs: plan - with a todo")
    assert scan_todos(repo, find_boundary(repo)) == []


def test_scan_todos_ignores_unchanged_files(git_repo):
    from handoff_collect import find_boundary, scan_todos
    repo, commit = git_repo
    commit("old.py", "# TODO: ancient\n", "feat: old - pre-existing todo")
    commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - base")
    commit("new.py", "y = 2\n", "feat: new - clean")
    assert scan_todos(repo, find_boundary(repo)) == []


def test_scan_todos_excludes_its_own_source_and_tests(git_repo):
    """M-b: the tool's own source and its tests DISCUSS the markers
    TODO/FIXME/XXX at length, in comments and strings - this file and its
    test file both do. Without this exclusion, every real run touching
    either would report phantom findings, the exact "noise trains the reader
    to ignore the section" failure GA-5 already exists to prevent."""
    from handoff_collect import find_boundary, scan_todos
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - base")
    commit("tools/handoff_collect.py", "# TODO: discusses the marker\n",
           "feat: tool - change")
    commit("tests/tools/test_handoff_collect.py", "# FIXME: discusses the marker\n",
           "feat: tool - test change")
    commit("tests/tools/conftest.py", "# XXX: discusses the marker\n",
           "feat: tool - conftest change")
    assert scan_todos(repo, find_boundary(repo)) == []


def test_parse_pytest_summary_reads_a_real_green_line():
    """GA-1 regression: verbatim pytest output from this repo."""
    from handoff_collect import parse_pytest_summary
    line = "====================== 2262 passed in 597.70s (0:09:57) ======================="
    result = parse_pytest_summary(line)
    assert result["passed"] == 2262
    assert result["failed"] == 0
    assert result["duration_s"] == 597.70


def test_parse_pytest_summary_reads_failures():
    from handoff_collect import parse_pytest_summary
    result = parse_pytest_summary("=========== 3 failed, 2259 passed in 601.20s ===========")
    assert result["passed"] == 2259
    assert result["failed"] == 3


def test_run_suite_prefers_supplied_json(git_repo, tmp_path):
    import json
    from handoff_collect import run_suite
    repo, _ = git_repo
    supplied = tmp_path / "suite.json"
    supplied.write_text(json.dumps({"passed": 2262, "failed": 0, "duration_s": 597.7}))
    result = run_suite(repo, str(supplied))
    assert result["passed"] == 2262
    assert result["source"] == "supplied"


def test_run_suite_raises_when_venv_missing(tmp_path):
    """I-3 regression: git worktrees have no .venv of their own (it is
    gitignored and exists only in the main repo), so the measured path used
    to raise an uncaught FileNotFoundError, crashing /handoff step 1 in the
    normal case (phase work happens in worktrees by project convention).
    tmp_path has no .venv and is not even a git repo - this must fail before
    any git or subprocess interaction is attempted."""
    from handoff_collect import run_suite
    with pytest.raises(RuntimeError, match="--suite-json"):
        run_suite(tmp_path, None)


def test_read_plan_splits_checked_and_unchecked_steps(git_repo):
    from handoff_collect import read_plan
    repo, commit = git_repo
    plan = (
        "# Plan\n\n### Task 1\n\n- [x] **Step 1: done thing**\n"
        "- [ ] **Step 2: pending thing**\n- [x] **Step 3: also done**\n"
    )
    commit("docs/superpowers/plans/2026-07-20-thing.md", plan, "docs: plan - thing")
    result = read_plan(repo)
    assert result["path"].endswith("2026-07-20-thing.md")
    assert len(result["completed"]) == 2
    assert len(result["remaining"]) == 1
    assert "pending thing" in result["remaining"][0]


def test_read_plan_picks_the_newest_by_date_prefix(git_repo):
    from handoff_collect import read_plan
    repo, commit = git_repo
    commit("docs/superpowers/plans/2026-01-01-old.md", "- [x] old\n", "docs: plan - old")
    commit("docs/superpowers/plans/2026-07-20-new.md", "- [ ] new\n", "docs: plan - new")
    assert read_plan(repo)["path"].endswith("2026-07-20-new.md")


def test_read_plan_tolerates_no_plans_dir(git_repo):
    """I-2: return-shape update. `checkbox_tracking` was added to every
    read_plan() return path (see test_read_plan_checkbox_tracking_*), so this
    exact-equality assertion is updated to include the new key rather than
    dropped, per the fix's explicit requirement."""
    from handoff_collect import read_plan
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - no plans dir")
    assert read_plan(repo) == {
        "path": "", "completed": [], "remaining": [], "checkbox_tracking": False,
    }


def test_read_plan_checkbox_tracking_true_when_some_checked(git_repo):
    from handoff_collect import read_plan
    repo, commit = git_repo
    plan = "# Plan\n\n- [x] done thing\n- [ ] pending thing\n"
    commit("docs/superpowers/plans/2026-07-20-thing.md", plan, "docs: plan - thing")
    assert read_plan(repo)["checkbox_tracking"] is True


def test_read_plan_checkbox_tracking_false_when_none_checked(git_repo):
    """I-2 regression: this project does not maintain plan checkboxes in
    practice (25 of 27 real plans have zero checked boxes, including the plan
    for work that just shipped), so a plan with unchecked boxes but NO
    checked ones must report checkbox_tracking=False - signalling to the
    handoff command that `remaining` reflects an unmaintained file, not
    outstanding work."""
    from handoff_collect import read_plan
    repo, commit = git_repo
    plan = "# Plan\n\nProse only; boxes never checked off.\n- [ ] pending thing\n"
    commit("docs/superpowers/plans/2026-07-20-thing.md", plan, "docs: plan - thing")
    result = read_plan(repo)
    assert result["checkbox_tracking"] is False
    assert result["remaining"] == ["pending thing"]


def test_collect_assembles_bundle(git_repo, tmp_path):
    import json
    from handoff_collect import collect
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - base")
    commit("a.py", "a = 1\n", "feat: a - thing (9.6 Task 1)")
    supplied = tmp_path / "suite.json"
    supplied.write_text(json.dumps({"passed": 10, "failed": 0, "duration_s": 1.0}))
    bundle = collect(repo, suite_json=str(supplied))
    assert bundle["commits"][0]["phase"] == "9.6"
    assert bundle["suite"]["passed"] == 10
    assert bundle["git"]["branch"] == "main"
    assert "boundary_sha" in bundle
    assert "plan" in bundle


def test_collect_reports_nothing_to_hand_off(git_repo, tmp_path):
    import json
    from handoff_collect import collect
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - base")
    supplied = tmp_path / "suite.json"
    supplied.write_text(json.dumps({"passed": 1, "failed": 0, "duration_s": 0.1}))
    bundle = collect(repo, suite_json=str(supplied))
    assert bundle["commits"] == []
    assert bundle["nothing_to_hand_off"] is True


SAMPLE_DOC = (
    "# Cerene - Next Session Handoff\n\nIntro line.\n\n"
    "## Phase 9.6 - newest\n\nsix\n\n"
    "## Phase 9.5b - second\n\nfive-b\n\n"
    "## Phase 9.5a - third\n\nfive-a\n\n"
    "## Phase 9.4 - fourth\n\nfour\n\n"
    "## Phase 9.3 - fifth\n\nthree\n\n"
    "## 1. Project at a glance\n\nreference\n"
)


INTERLEAVED_DOC = (
    "# Cerene - Next Session Handoff\n\nIntro.\n\n"
    "## Phase 9.6 - newest\n\nsix\n\n"
    "## Phase 9.5b - second\n\nfive-b\n\n"
    "## Phase 9.5a - third\n\nfive-a\n\n"
    "## Architecture roadmap (graph-grounded)\n\nROADMAP BODY\n\n"
    "## Phase 9.4 - fourth\n\nfour\n\n"
    "## 1. Project at a glance\n\nreference\n"
)


def test_split_entries_separates_preamble_entries_and_base():
    from handoff_collect import split_entries
    preamble, segments, base = split_entries(SAMPLE_DOC)
    assert "Next Session Handoff" in preamble
    assert len(segments) == 5
    assert all(kind == "phase" for kind, _ in segments)
    assert segments[0][1].startswith("## Phase 9.6")
    assert base.startswith("## 1. Project at a glance")


def test_split_entries_classifies_interleaved_reference_sections():
    """GA-4: the real doc has '## Architecture roadmap' between phase entries."""
    from handoff_collect import split_entries
    _, segments, _ = split_entries(INTERLEAVED_DOC)
    kinds = [kind for kind, _ in segments]
    assert kinds == ["phase", "phase", "phase", "other", "phase"]


def test_archive_never_archives_a_reference_section(git_repo):
    """GA-4 regression: reference material must survive in NEXT_SESSION.md even
    when the phase entry preceding it gets archived."""
    from handoff_collect import archive
    repo, commit = git_repo
    commit("NEXT_SESSION.md", INTERLEAVED_DOC, "docs: handoff - interleaved")
    counts = archive(repo, retain=3)
    assert counts["archived"] == 1
    with open(repo / "NEXT_SESSION.md", encoding="utf-8", newline="") as fh:
        remaining = fh.read()
    assert "ROADMAP BODY" in remaining
    assert "## Phase 9.4" not in remaining
    with open(repo / "docs" / "handoff-archive.md", encoding="utf-8", newline="") as fh:
        assert "ROADMAP BODY" not in fh.read()


def test_archive_detects_loss_of_duplicate_lines(monkeypatch, git_repo):
    """GA-3 regression: a set-membership guard cannot see duplicate-line loss,
    because one surviving copy satisfies it. Drive a REAL duplicate-line-loss
    scenario through archive() itself - via a monkeypatched split_entries
    that silently drops one instance of a repeated "---" rule from a moved
    chunk - and assert the multiset guard fires fail-closed: it raises
    before either file is written, so NEXT_SESSION.md is byte-for-byte
    unchanged and the archive file is never created.

    "---" (not a blank line) is the target deliberately: the code itself
    legitimately ADDS several blank lines via the archive header and the
    pointer block, so a 1-line blank-line deficit would be invisible to the
    Counter guard (comfortably absorbed by that surplus) without proving
    anything. "---" appears nowhere in the code's own additions, so losing
    one of its six copies is an unambiguous, undiluted deficit.
    """
    import handoff_collect as handoff_collect
    from handoff_collect import archive

    doc = (
        "# Cerene - Next Session Handoff\n\nIntro line.\n\n---\n\n"
        "## Phase 9.6 - newest\n\nsix\n\n---\n\n"
        "## Phase 9.5b - second\n\nfive-b\n\n---\n\n"
        "## Phase 9.5a - third\n\nfive-a\n\n---\n\n"
        "## Phase 9.4 - fourth\n\nfour\n\n---\n\n"
        "## Phase 9.3 - fifth\n\nthree\n\n---\n\n"
        "## 1. Project at a glance\n\nreference\n"
    )
    repo, commit = git_repo
    commit("NEXT_SESSION.md", doc, "docs: handoff - duplicate rule")
    with open(repo / "NEXT_SESSION.md", "rb") as fh:
        before = fh.read()

    real_split_entries = handoff_collect.split_entries

    def buggy_split_entries(text):
        # retain=3 keeps segments[0:3] (9.6, 9.5b, 9.5a) and moves the rest,
        # so segments[-1] (9.3) lands in `moved`. Drop its "---" line only -
        # the other five copies (preamble + 9.6/9.5b/9.5a/9.4) survive
        # untouched, so a naive `line in remaining or line in archived`
        # membership check would NOT have caught this loss.
        preamble, segments, base = real_split_entries(text)
        kind, chunk = segments[-1]
        lines = chunk.split("\n")
        assert lines.count("---") == 1
        lines.remove("---")
        segments[-1] = (kind, "\n".join(lines))
        return preamble, segments, base

    monkeypatch.setattr(handoff_collect, "split_entries", buggy_split_entries)

    with pytest.raises(RuntimeError):
        archive(repo, retain=3)

    with open(repo / "NEXT_SESSION.md", "rb") as fh:
        after = fh.read()
    assert after == before, "guard must fail closed: no partial write on loss"
    assert not (repo / "docs" / "handoff-archive.md").exists()


def test_archive_retains_newest_three_and_moves_the_rest(git_repo):
    from handoff_collect import archive
    repo, commit = git_repo
    commit("NEXT_SESSION.md", SAMPLE_DOC, "docs: handoff - sample")
    counts = archive(repo, retain=3)
    assert counts["retained"] == 3
    assert counts["archived"] == 2
    with open(repo / "NEXT_SESSION.md", encoding="utf-8", newline="") as fh:
        remaining = fh.read()
    assert "## Phase 9.6" in remaining
    assert "## Phase 9.5a" in remaining
    assert "## Phase 9.4" not in remaining
    assert "## 1. Project at a glance" in remaining
    with open(repo / "docs" / "handoff-archive.md", encoding="utf-8", newline="") as fh:
        archived = fh.read()
    assert "## Phase 9.4" in archived
    assert "## Phase 9.3" in archived


def test_archive_conserves_every_original_line(git_repo):
    """Multiset check, not set membership: membership alone would still pass
    if a DUPLICATED line (e.g. a repeated blank line) were dropped, since one
    surviving copy elsewhere satisfies `in`. remaining/archived legitimately
    contain lines original didn't (the archive header, the pointer block), so
    full symmetric equality isn't the right property - but no line ORIGINAL
    contributed may be undercounted, which is exactly what a one-directional
    Counter residual on original's own lines proves."""
    from collections import Counter
    from handoff_collect import archive
    repo, commit = git_repo
    commit("NEXT_SESSION.md", SAMPLE_DOC, "docs: handoff - sample")
    original = Counter(SAMPLE_DOC.splitlines())
    archive(repo, retain=3)
    with open(repo / "NEXT_SESSION.md", encoding="utf-8", newline="") as fh:
        remaining = Counter(fh.read().splitlines())
    with open(repo / "docs" / "handoff-archive.md", encoding="utf-8", newline="") as fh:
        archived = Counter(fh.read().splitlines())
    missing = original - remaining - archived
    assert not missing, f"line(s) lost: {missing!r}"


def test_archive_is_a_noop_when_nothing_to_move(git_repo):
    from handoff_collect import archive
    repo, commit = git_repo
    short = "# Head\n\n## Phase 9.6 - only\n\nsix\n\n## 1. Base\n\nref\n"
    commit("NEXT_SESSION.md", short, "docs: handoff - short")
    counts = archive(repo, retain=3)
    assert counts["archived"] == 0
    assert not (repo / "docs" / "handoff-archive.md").exists()


def test_archive_preserves_crlf(git_repo):
    from handoff_collect import archive
    repo, commit = git_repo
    commit("NEXT_SESSION.md", SAMPLE_DOC.replace("\n", "\r\n"), "docs: handoff - crlf")
    archive(repo, retain=3)
    with open(repo / "NEXT_SESSION.md", "rb") as fh:
        raw = fh.read()
    assert b"\r\n" in raw
    assert b"\n\n" not in raw.replace(b"\r\n", b"")


def test_archive_is_idempotent_across_repeated_runs(git_repo):
    """Task-4 fix-pass-3 regression: a stale '## Archive pointer' block must
    never accumulate. The bug: split_entries files the pointer under "other"
    (GA-6's own top-level header), GA-4 keeps every "other" segment inline
    forever, and nothing ever removed the PRIOR run's pointer before a fresh
    one was appended - so N archive runs left N stacked pointer blocks
    permanently in NEXT_SESSION.md, the doc every session is required to
    read first. Confirmed by simulation: 1 block after run 1, 2 after run 2,
    3 after run 3, none ever removed.

    Runs archive() twice back to back, simulating two handoffs, and checks:
    the pointer count never exceeds one, archive ordering across the two
    runs stays newest-first, and the conservation guard does not falsely
    raise on the second run even though the on-disk file it reads already
    contains a stale pointer left by the first.
    """
    from handoff_collect import _ARCHIVE_HEADER, archive
    repo, commit = git_repo
    run1_doc = (
        "# Cerene - Next Session Handoff\n\nIntro line.\n\n"
        "## Phase 9.6 - run1 newest\n\nrun1-body-A\n\n"
        "## Phase 9.5b - run1 second\n\nrun1-body-B\n\n"
        "## Phase 9.5a - run1 third\n\nrun1-body-C\n\n"
        "## Phase 9.4 - run1 fourth\n\nrun1-body-D\n\n"
        "## Phase 9.3 - run1 fifth\n\nrun1-body-E\n\n"
        "## 1. Project at a glance\n\nreference\n"
    )
    commit("NEXT_SESSION.md", run1_doc, "docs: handoff - run1 base")

    first = archive(repo, retain=3)
    assert first["archived"] == 2

    with open(repo / "NEXT_SESSION.md", encoding="utf-8", newline="") as fh:
        after_first = fh.read()
    assert after_first.count("## Archive pointer") == 1

    # Simulate the next handoff: a new phase entry is always PREPENDED to
    # NEXT_SESSION.md, ahead of whatever run 1 retained (including its
    # pointer block, still sitting inline at this point).
    run2_doc = after_first.replace(
        "## Phase 9.6 - run1 newest",
        "## Phase 9.7 - run2 newest\n\nrun2-body-A\n\n## Phase 9.6 - run1 newest",
        1,
    )
    commit("NEXT_SESSION.md", run2_doc, "docs: handoff - run2 base")

    second = archive(repo, retain=3)
    assert second["archived"] == 1

    with open(repo / "NEXT_SESSION.md", encoding="utf-8", newline="") as fh:
        after_second = fh.read()
    assert after_second.count("## Archive pointer") == 1
    assert "run1-body-B" in after_second      # 9.5b: still retained (3rd newest)
    assert "run1-body-C" not in after_second  # 9.5a: fell out of the window this run

    with open(repo / "docs" / "handoff-archive.md", encoding="utf-8", newline="") as fh:
        archived = fh.read()
    assert archived.count(_ARCHIVE_HEADER) == 1
    assert "## Archive pointer" not in archived
    # Newest-first across runs: what THIS run archived (9.5a) must land
    # above what the FIRST run archived (9.4, then 9.3).
    assert archived.index("run1-body-C") < archived.index("run1-body-D") < archived.index("run1-body-E")


def test_find_sha_candidates_requires_backticks_and_a_digit():
    from handoff_collect import find_sha_candidates
    text = "merged at `7544a63` but not decade or `facade` or `deadbeef` or bare 7544a63\n"
    found = [token for _, token in find_sha_candidates(text)]
    assert found == ["7544a63"]
    # deadbeef is 8 chars, all hex a-f, zero digits: only the digit check rejects it


def test_find_bare_sha_candidates_requires_digit_and_letter():
    """I-1(a): the discrimination measured against the real documents - a
    bare token needs BOTH a digit and a letter. An all-digit run (a year, a
    test count) and an all-letter hex-looking word must not match, even
    though both are individually valid hex and within the length bound."""
    from handoff_collect import find_bare_sha_candidates
    text = (
        "bare sha bead123 here, a plain year 2026072 alone, "
        "and hex word deadbeef alone\n"
    )
    found = [token for _, token in find_bare_sha_candidates(text)]
    assert found == ["bead123"]


def test_find_bare_sha_candidates_skips_backticked_spans():
    """I-1(a): a token already inside backticks must not also surface as a
    bare candidate - its span overlaps a `_BACKTICKED` span on the same
    line, so it is skipped here (and reported, if dead, only once via
    find_sha_candidates / the "dead-sha" path)."""
    from handoff_collect import find_bare_sha_candidates
    text = "backticked `abc1234` must not appear as bare, but bead123 must\n"
    found = [token for _, token in find_bare_sha_candidates(text)]
    assert found == ["bead123"]


def test_find_bare_sha_candidates_excludes_a_hex_run_embedded_in_a_longer_word():
    """I-1(a): word-boundary anchoring on both sides. A hex-shaped run glued
    to trailing non-hex word characters (an identifier, not a token) must
    produce no match at all, not a truncated match of the hex-looking
    prefix."""
    from handoff_collect import find_bare_sha_candidates
    text = "identifier deadbeefzz is not a sha-shaped token\n"
    assert find_bare_sha_candidates(text) == []


def test_validate_references_flags_a_dead_sha(git_repo):
    from handoff_collect import validate_references
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - thing")
    findings = validate_references(repo, "See `deadbee1` for details.\n")
    assert len(findings) == 1
    assert findings[0].kind == "dead-sha"
    assert "deadbee1" in findings[0].detail


def test_validate_references_accepts_a_live_sha(git_repo):
    from handoff_collect import validate_references
    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "feat: a - thing")
    assert validate_references(repo, f"See `{sha}` for details.\n") == []


def test_validate_references_flags_a_bare_dead_sha(git_repo):
    """I-1(b): a SHA written without backticks that does not resolve must be
    flagged - this is exactly the class of reference that previously
    escaped --verify entirely."""
    from handoff_collect import validate_references
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - thing")
    findings = validate_references(repo, "merged at deadbee1 without backticks\n")
    assert len(findings) == 1
    assert findings[0].kind == "bare-dead-sha"
    assert "deadbee1" in findings[0].detail


def test_validate_references_accepts_a_bare_live_sha(git_repo):
    """I-1(b): a bare SHA that RESOLVES is merely unstyled, not broken -
    flagging it would be noise, so it must produce no finding at all."""
    from handoff_collect import validate_references
    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "feat: a - thing")
    token = sha[:7]
    assert validate_references(repo, f"merged at {token} without backticks\n") == []


def test_bare_dead_sha_inside_backticks_is_not_double_reported(git_repo):
    """I-1(a): a dead SHA that IS backticked must be reported once, via the
    existing dead-sha path - not a second time as bare-dead-sha, since its
    span overlaps the backticked span and find_bare_sha_candidates skips
    it."""
    from handoff_collect import validate_references
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - thing")
    findings = validate_references(repo, "See `deadbee1` for details.\n")
    assert len(findings) == 1
    assert findings[0].kind == "dead-sha"


def test_translate_shas_rewrites_using_the_commit_map(tmp_path):
    from handoff_collect import load_sha_map, translate_shas
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text("7544a63aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa f7d48c3bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n")
    mapping = load_sha_map(str(map_file))
    text, count = translate_shas("merged at `7544a63` today\n", mapping)
    assert count == 1
    assert "`f7d48c3`" in text


def test_translate_shas_leaves_ambiguous_prefixes_alone(tmp_path):
    """GA-6: two old SHAs share the prefix, so neither may win."""
    from handoff_collect import load_sha_map, translate_shas
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text(
        "abc1234aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1111111ccccccccccccccccccccccccccccccccc\n"
        "abc1234bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2222222ddddddddddddddddddddddddddddddddd\n"
    )
    mapping = load_sha_map(str(map_file))
    text, count = translate_shas("see `abc1234` here\n", mapping)
    assert count == 0
    assert "`abc1234`" in text


def test_sha_map_translates_a_bare_dead_sha(tmp_path):
    """I-1(c): the sharpest requirement in the fix - a bare dead SHA must be
    repairable by --sha-map, not just flaggable. Kept BARE (no backticks
    added) and at its original length, since translate_shas repairs the
    reference, it does not add styling the author never wrote."""
    from handoff_collect import load_sha_map, translate_shas
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text("dead0001" + "a" * 32 + " f00d0001" + "b" * 32 + "\n")
    mapping = load_sha_map(str(map_file))
    text, count = translate_shas("merged at dead0001 without backticks today\n", mapping)
    assert count == 1
    assert "f00d0001" in text
    assert "dead0001" not in text
    assert "`f00d0001`" not in text  # bare in, bare out -- no backticks added


def test_translate_shas_leaves_ambiguous_bare_prefix_alone(tmp_path):
    """I-1(c): the bare path must honour the same GA-6 ambiguity rule as the
    backticked path -- two old SHAs sharing the bare token's prefix, so
    neither translation may win."""
    from handoff_collect import load_sha_map, translate_shas
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text(
        "abc1234aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 1111111ccccccccccccccccccccccccccccccccc\n"
        "abc1234bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 2222222ddddddddddddddddddddddddddddddddd\n"
    )
    mapping = load_sha_map(str(map_file))
    text, count = translate_shas("see abc1234 here, bare and ambiguous\n", mapping)
    assert count == 0
    assert "abc1234" in text


def test_live_claim_flags_a_branch_that_actually_merged(git_repo):
    from handoff_collect import validate_live_claims
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "checkout", "-b", "claude/feature"], cwd=repo, check=True,
                   capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "--no-ff", "claude/feature", "-m", "merge"],
                   cwd=repo, check=True, capture_output=True)
    text = "## Phase 9.9 - thing\n\nOn branch `claude/feature`. NOT yet merged.\n"
    findings = validate_live_claims(repo, text)
    assert len(findings) == 1
    assert findings[0].kind == "stale-live-claim"
    assert "claude/feature" in findings[0].detail


def test_live_claim_accepts_a_genuinely_unmerged_branch(git_repo):
    from handoff_collect import validate_live_claims
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "branch", "claude/feature"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "checkout", "claude/feature"], cwd=repo, check=True,
                   capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    text = "## Phase 9.9 - thing\n\nOn branch `claude/feature`. NOT yet merged.\n"
    assert validate_live_claims(repo, text) == []


def test_historical_facts_never_flag(git_repo):
    """The false-positive test. If this ever fails, the tool stops being trusted."""
    from handoff_collect import validate
    repo, commit = git_repo
    sha = commit("NEXT_SESSION.md", "handoff\n", "docs: handoff - base")
    text = (
        f"## Phase 9.5b - done\n\nMerged at `{sha[:7]}`. Suite was 2238 passed, "
        "0 failures. Previously 2218. Completed 2026-07-15.\n"
    )
    assert validate(repo, text) == []


def test_scan_secrets_flags_a_token_shaped_string():
    from handoff_collect import scan_secrets
    findings = scan_secrets("key is sk-abcdefghijklmnopqrstuvwxyz012345\n")
    assert len(findings) == 1
    assert findings[0].kind == "possible-secret"


def test_scan_secrets_ignores_ordinary_prose():
    from handoff_collect import scan_secrets
    assert scan_secrets("The suite passed 2262 tests in 597 seconds.\n") == []


def test_verify_mode_returns_nonzero_on_a_bad_doc(git_repo):
    from handoff_collect import main
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "See `deadbee1` for details.\n", "docs: handoff - bad")
    assert main(["--verify", "--repo", str(repo)]) == 1


def test_verify_mode_returns_zero_on_a_clean_doc(git_repo):
    from handoff_collect import main
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "Nothing falsifiable here.\n", "docs: handoff - clean")
    assert main(["--verify", "--repo", str(repo)]) == 0


def test_main_errors_on_empty_validate_path(git_repo):
    """M-a: argparse still counts --validate as "provided" (satisfying the
    required mutually-exclusive group) even when given an empty string, so
    this state is genuinely reachable -- not the dead code the trailing
    `raise NotImplementedError` this replaces assumed it to be. It must exit
    non-zero via parser.error rather than silently falling through to an
    implicit `None` return, which SystemExit would report as exit code 0."""
    from handoff_collect import main
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    with pytest.raises(SystemExit) as exc_info:
        main(["--validate", "", "--repo", str(repo)])
    assert exc_info.value.code == 2


def test_scan_secrets_flags_a_project_scoped_key():
    from handoff_collect import scan_secrets
    findings = scan_secrets("key is sk-proj-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6\n")
    assert len(findings) == 1
    assert findings[0].kind == "possible-secret"


def test_validate_includes_secret_findings(git_repo):
    from handoff_collect import validate
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    text = "## Phase 9.9 - thing\n\nSecret: sk-abcdefghijklmnopqrstuvwxyz012345\n"
    findings = validate(repo, text)
    secret_findings = [f for f in findings if f.kind == "possible-secret"]
    assert len(secret_findings) == 1
    assert secret_findings[0].kind == "possible-secret"


def test_live_claim_flags_a_branch_that_no_longer_exists(git_repo):
    """Change 1(b): the false negative from the acceptance run. The old rule
    required `_branch_exists(...) and _is_merged(...)`, so a branch that was
    merged and then deleted (exactly what happened to
    `claude/phase-9-6-live-apply`) made the condition False and the stale
    claim was never caught. Under the pre-fix logic this text produces zero
    findings; discriminates because the fix adds a dedicated
    branch-does-not-exist case that must fire here."""
    from handoff_collect import validate_live_claims
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "checkout", "-b", "claude/ghost"], cwd=repo, check=True,
                   capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "--no-ff", "claude/ghost", "-m", "merge"],
                   cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-d", "claude/ghost"], cwd=repo, check=True,
                   capture_output=True)
    text = "## Phase 9.9 - thing\n\nOn branch `claude/ghost`. NOT yet merged.\n"
    findings = validate_live_claims(repo, text)
    assert len(findings) == 1
    assert findings[0].kind == "stale-live-claim"
    assert "claude/ghost" in findings[0].detail
    assert "no longer exists" in findings[0].detail


def test_live_claim_ignores_a_stale_claim_in_an_older_entry(git_repo):
    """Change 1(a): the 9.5a false-positive regression guard. The newest
    entry is deliberately benign; the live phrase plus a merged branch sit in
    the OLDER entry instead. Discriminates because under the pre-fix logic
    (which checked every phase segment unconditionally) this text produces
    one finding for the older entry; after the fix, only the first
    (newest) phase segment is ever checked, so it must produce none."""
    from handoff_collect import validate_live_claims
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "checkout", "-b", "claude/old-feature"], cwd=repo, check=True,
                   capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "--no-ff", "claude/old-feature", "-m", "merge"],
                   cwd=repo, check=True, capture_output=True)
    text = (
        "## Phase 9.9 - newest, benign\n\nNothing live here.\n\n"
        "## Phase 9.8 - older\n\nOn branch `claude/old-feature`. NOT yet merged, "
        "retained below only as written history.\n"
    )
    assert validate_live_claims(repo, text) == []


def test_live_claim_newest_entry_true_claim_stays_silent(git_repo):
    """Change 1(b), the 'no finding' branch: a branch that exists but is
    genuinely still unmerged, named in the NEWEST entry (the only one ever
    checked). The claim is true, so no finding. An older sibling entry with
    unrelated prose is included so this exercises segment selection in a
    multi-entry document rather than a single trivially-newest entry. Note:
    this does NOT discriminate against the pre-fix code -- exists-and-not-
    merged also failed the old `and`-condition, so old and new logic agree on
    this exact input. What it pins instead is a plausible incorrect rewrite
    of the new three-way branch logic that flags any mentioned branch
    regardless of merge status (paired with the next test, which requires a
    positive finding on the same shape of document, to pin the newest-segment
    selection itself)."""
    from handoff_collect import validate_live_claims
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "branch", "claude/still-open"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "checkout", "claude/still-open"], cwd=repo, check=True,
                   capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    text = (
        "## Phase 9.9 - newest\n\nOn branch `claude/still-open`. NOT yet merged.\n\n"
        "## Phase 9.8 - older\n\nSome unrelated historical note.\n"
    )
    assert validate_live_claims(repo, text) == []


def test_live_claim_newest_entry_merged_branch_flags(git_repo):
    """Change 1(b) existing-behavior preserved: a branch that exists and IS
    merged, named in the newest entry, with an older sibling entry present --
    exactly one finding. The older sibling carries no live phrase, so the
    pre-fix code also produces exactly this one finding here (it does not by
    itself discriminate old vs. new). What it DOES pin: the newest-only
    restriction must still actually check the newest segment. A
    segment-selection bug (off-by-one, wrong index, the 'already checked'
    flag initialised true too early) would silently drop this finding to
    zero, since no other segment in the document qualifies -- so this test
    fails loudly under that class of bug even though it doesn't distinguish
    the historical pre-fix behavior."""
    from handoff_collect import validate_live_claims
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "checkout", "-b", "claude/actually-merged"], cwd=repo, check=True,
                   capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "--no-ff", "claude/actually-merged", "-m", "merge"],
                   cwd=repo, check=True, capture_output=True)
    text = (
        "## Phase 9.9 - newest\n\nOn branch `claude/actually-merged`. NOT yet merged.\n\n"
        "## Phase 9.8 - older\n\nSome unrelated historical note.\n"
    )
    findings = validate_live_claims(repo, text)
    assert len(findings) == 1
    assert findings[0].kind == "stale-live-claim"
    assert "claude/actually-merged" in findings[0].detail
    assert "ancestor of main" in findings[0].detail


def test_verify_flags_a_dead_sha_that_lives_only_in_the_archive(git_repo, capsys):
    """Change 2: before this fix, --verify/--validate read only their target
    file, so content moved into docs/handoff-archive.md escaped validation
    entirely. A dead SHA present ONLY in the archive must still surface, and
    the printed finding must be labelled with the archive's repo-relative
    path so a reader can tell which document it refers to. Discriminates:
    under the pre-fix main(), --verify reads only NEXT_SESSION.md (clean
    here), so this would return 0 with no mention of the archive at all."""
    from handoff_collect import ARCHIVE_DOC, main
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "Nothing falsifiable here.\n", "docs: handoff - clean")
    commit(ARCHIVE_DOC, "Archived history: see `deadbee1` for details.\n",
           "docs: archive - with a dead sha")

    result = main(["--verify", "--repo", str(repo)])

    captured = capsys.readouterr()
    assert result == 1
    assert ARCHIVE_DOC in captured.out
    assert "deadbee1" in captured.out


def test_sha_map_translates_a_dead_sha_inside_the_archive_file(git_repo, tmp_path):
    """Change 2: --sha-map must rewrite stale SHAs inside the archive too,
    not just the primary target -- otherwise the tool reports archive
    findings it has no way to fix. Discriminates: under the pre-fix main(),
    sha-map translation only ever touched the --validate/--verify target, so
    the archive file on disk would be left with `dead0001` untouched."""
    from handoff_collect import ARCHIVE_DOC, main
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "Nothing falsifiable here.\n", "docs: handoff - clean")
    commit(ARCHIVE_DOC, "Archived history: merged at `dead0001` long ago.\n",
           "docs: archive - with a dead sha")
    old_sha = "dead0001" + "a" * 32
    new_sha = "f00d0001" + "b" * 32
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text(f"{old_sha} {new_sha}\n")

    main(["--verify", "--repo", str(repo), "--sha-map", str(map_file)])

    with open(repo / ARCHIVE_DOC, encoding="utf-8", newline="") as fh:
        content = fh.read()
    assert "`f00d0001`" in content
    assert "dead0001" not in content


def test_translate_shas_finds_a_sha_after_an_odd_backtick_line(tmp_path):
    """Regression for the whole-text/per-line phase-shift defect found against
    the real NEXT_SESSION.md. `_BACKTICKED`'s `[^`]+` matches newlines, so the
    pre-fix implementation (`_BACKTICKED.sub(replace, text)` over the whole
    text) pairs backticks ACROSS line boundaries. A single stray backtick on
    an earlier line is odd, so it gets paired as an "opening" backtick with
    whatever backtick comes next in the document -- here, the SHA's own
    opening backtick -- and that pairing spans the newline in between and is
    rejected by `_looks_like_sha` (it contains a newline and prose). That
    consumes BOTH backticks, leaving only the SHA's lone closing backtick in
    the remainder of the text: too few backticks (one) to ever form another
    match, so the SHA is invisible to a whole-text scan, not merely
    mismatched. find_sha_candidates (which scans strictly per line) reports
    it correctly regardless, since each line's backticks only ever pair
    among themselves. Discriminates: verified by temporarily restoring the
    old `_BACKTICKED.sub(replace, text)` whole-text implementation -- the
    assertions below FAIL against it (count == 0, no translation) and PASS
    against the per-line fix.
    """
    from handoff_collect import load_sha_map, translate_shas
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text(
        "1234567aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa f7d48c3bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
    )
    mapping = load_sha_map(str(map_file))
    text = (
        "line one has a stray backtick here: `\n"
        "commit `1234567` is the real one\n"
    )
    new_text, count = translate_shas(text, mapping)
    assert count == 1
    assert "`f7d48c3`" in new_text


def test_translate_shas_and_find_sha_candidates_agree_on_tokenization(tmp_path):
    """The invariant the fix establishes, not just one example of it: every
    SHA-shaped backticked token find_sha_candidates reports (scanning
    per line) must also be found and translated by translate_shas, in a
    single document that interleaves odd-backtick lines (phase-shift traps),
    non-SHA backticked spans (a path, a flag, a quoted string), and a
    backticked hex token that is deliberately NOT SHA-shaped (no digit --
    same red herring as test_find_sha_candidates_requires_backticks_and_a_digit)
    among three real SHA-shaped tokens.
    """
    from handoff_collect import find_sha_candidates, load_sha_map, translate_shas

    doc = (
        "Odd backtick trap number one: `\n"
        "Config lives at `core/config.py`, flag is `--verbose`.\n"
        "Another odd one: `\n"
        "First commit `abc1234` landed; quoted text \"like `this`\" too.\n"
        "Not a sha, no digit: `deadbeef`.\n"
        "Second commit `def5678` followed shortly after.\n"
        "Yet another odd backtick: `\n"
        "Final commit `9999999` closes it out.\n"
    )

    candidates = find_sha_candidates(doc)
    tokens = [token for _, token in candidates]
    assert tokens == ["abc1234", "def5678", "9999999"]

    old_shas = {
        "abc1234": "abc1234" + "a" * 33,
        "def5678": "def5678" + "b" * 33,
        "9999999": "9999999" + "c" * 33,
    }
    new_shas = {
        "abc1234": "1110000" + "d" * 33,
        "def5678": "2220000" + "e" * 33,
        "9999999": "3330000" + "f" * 33,
    }
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text("\n".join(f"{old_shas[t]} {new_shas[t]}" for t in tokens) + "\n")
    mapping = load_sha_map(str(map_file))

    new_text, count = translate_shas(doc, mapping)

    assert count == len(tokens)
    for token in tokens:
        assert f"`{new_shas[token][: len(token)]}`" in new_text


def test_bare_candidates_and_translation_agree_on_tokenization(tmp_path):
    """I-1: the bare-token counterpart of
    test_translate_shas_and_find_sha_candidates_agree_on_tokenization. The
    brief requires an invariant test in that spirit: every bare token
    find_bare_sha_candidates reports (and validate_references would flag, if
    dead) must be one translate_shas can also see and repair -- otherwise
    adding the bare-dead-sha finding without extending translation to match
    recreates exactly the EX-8 defect (a finding class the validator reports
    that --sha-map is structurally unable to fix).

    Mirrors the backticked test's shape: a backticked SHA that must stay
    untouched by bare scanning, a plain-number and a hex-only-word red
    herring (same discriminating logic as
    test_find_bare_sha_candidates_requires_digit_and_letter), and two real
    bare SHA-shaped tokens on different lines.
    """
    from handoff_collect import find_bare_sha_candidates, load_sha_map, translate_shas

    doc = (
        "Backticked `abc1234` must be ignored by bare scanning.\n"
        "Bare sha bead123 sits here; plain year 2026072 and hex "
        "word deadbeef must not count.\n"
        "Second bare sha facade12 follows on another line.\n"
    )

    candidates = find_bare_sha_candidates(doc)
    tokens = [token for _, token in candidates]
    assert tokens == ["bead123", "facade12"]

    old_shas = {
        "bead123": "bead123" + "a" * 33,
        "facade12": "facade12" + "b" * 32,
    }
    new_shas = {
        "bead123": "1110000" + "d" * 33,
        "facade12": "22200000" + "e" * 32,
    }
    map_file = tmp_path / "commit-map.txt"
    map_file.write_text("\n".join(f"{old_shas[t]} {new_shas[t]}" for t in tokens) + "\n")
    mapping = load_sha_map(str(map_file))

    new_text, count = translate_shas(doc, mapping)

    assert count == len(tokens)
    for token in tokens:
        assert new_shas[token][: len(token)] in new_text
    assert "`abc1234`" in new_text  # untouched: backticked, not in the map


def test_archive_is_exempt_from_live_claim_checking(git_repo):
    """The archive is history by construction, so its newest entry is not a
    live claim. Without the exemption, an archived entry that honestly records
    its own past 'not yet merged' status is flagged for saying so - the exact
    false positive the newest-entry scoping exists to prevent."""
    from handoff_collect import validate
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "branch", "claude/old"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "checkout", "claude/old"], cwd=repo, check=True,
                   capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "--no-ff", "claude/old", "-m", "merge"],
                   cwd=repo, check=True, capture_output=True)

    archived = (
        "# Archive\n\n## Phase 9.0 - retired\n\n"
        "Was on `claude/old`. NOT yet merged, retained as written history.\n"
    )
    assert validate(repo, archived) != []                          # live doc: flagged
    assert validate(repo, archived, in_archive=True) == []  # archive: exempt


def test_archive_exemption_still_checks_references_and_secrets(git_repo):
    """The exemption is narrow: dead references and leaked credentials do not
    become acceptable by being archived."""
    from handoff_collect import validate
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    findings = validate(repo, "See `deadbee1`.\nkey sk-abcdefghijklmnopqrstuvwxyz012345\n",
                        in_archive=True)
    kinds = {f.kind for f in findings}
    assert "dead-sha" in kinds
    assert "possible-secret" in kinds


def test_resolve_shas_agrees_with_per_token_checking(git_repo):
    """The batched resolver replaced ~60 subprocess spawns with one call. Its
    only real risk is disagreeing with the per-token path it replaced, so pin
    the equivalence directly on a mix of live and dead tokens."""
    from handoff_collect import _resolve_shas, _sha_exists
    repo, commit = git_repo
    live_full = commit("a.py", "a = 1\n", "feat: a - first")
    live_short = live_full[:7]
    tokens = [live_full, live_short, "deadbee1", "0000000", live_short]
    batched = _resolve_shas(repo, tokens)
    per_token = {t for t in set(tokens) if _sha_exists(repo, t)}
    assert batched == per_token
    assert live_short in batched
    assert "deadbee1" not in batched


def test_resolve_shas_handles_no_tokens(git_repo):
    from handoff_collect import _resolve_shas
    repo, _ = git_repo
    assert _resolve_shas(repo, []) == set()


def _repo_with_unmerged_branch(git_repo):
    """(repo, merged_sha, unmerged_sha) - one commit on main, one stranded on a
    branch that was never merged."""
    repo, commit = git_repo
    merged = commit("a.py", "a = 1\n", "feat: a - on main")
    subprocess.run(["git", "checkout", "-b", "claude/stranded"], cwd=repo, check=True,
                   capture_output=True)
    unmerged = commit("b.py", "b = 1\n", "feat: b - never merged")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    return repo, merged, unmerged


def test_false_merge_claim_is_flagged(git_repo):
    """The dangerous direction: claiming work landed when it did not."""
    from handoff_collect import validate_merge_claims
    repo, _, unmerged = _repo_with_unmerged_branch(git_repo)
    findings = validate_merge_claims(
        repo, f"**Status:** SHIPPED. Merged to `main` at `{unmerged[:7]}` via `--no-ff`.\n")
    assert len(findings) == 1
    assert findings[0].kind == "false-merge-claim"
    assert unmerged[:7] in findings[0].detail


def test_true_merge_claim_stays_silent(git_repo):
    from handoff_collect import validate_merge_claims
    repo, merged, _ = _repo_with_unmerged_branch(git_repo)
    assert validate_merge_claims(
        repo, f"Merged to `main` at `{merged[:7]}` via `--no-ff`.\n") == []


def test_merge_claim_with_dead_sha_is_not_double_reported(git_repo):
    """A dead SHA is already a dead-sha finding; adding 'not an ancestor of
    main' about a commit that does not exist would only confuse."""
    from handoff_collect import validate_merge_claims
    repo, _, _ = _repo_with_unmerged_branch(git_repo)
    assert validate_merge_claims(repo, "Merged to `main` at `deadbee1`.\n") == []


def test_merge_claim_matches_the_real_corpus_phrasings(git_repo):
    """A rule that misses the wording actually used is worthless. These four
    lines are taken verbatim from NEXT_SESSION.md and the archive."""
    from handoff_collect import validate_merge_claims
    repo, _, unmerged = _repo_with_unmerged_branch(git_repo)
    s = unmerged[:7]
    for line in (
        f"**Ship status:** SHIPPED. Merged to `main` at `{s}` via `--no-ff`; feature branch deleted.",
        f"**Status: SHIPPED.** Merged to `main` at `{s}` via `--no-ff` on 2026-07-18",
        f"**Status:** SHIPPED to `main` at `{s}` on 2026-06-04. 33 commits merged.",
        f"the `/handoff` slash command are **merged to `main` at `{s}`** via `--no-ff`",
    ):
        assert validate_merge_claims(repo, line + "\n"), f"missed: {line[:50]}"


def test_merge_claim_ignores_a_sha_that_precedes_the_phrase(git_repo):
    """Real near-miss from the corpus: the SHA belongs to 'branched from', not
    to the 'landed on main' phrase that follows it."""
    from handoff_collect import validate_merge_claims
    repo, _, unmerged = _repo_with_unmerged_branch(git_repo)
    line = f"branched from main @ `{unmerged[:7]}` (the spec + plan docs landed directly on main first)\n"
    assert validate_merge_claims(repo, line) == []


def test_merge_claims_are_checked_in_the_archive_too(git_repo):
    """Live claims are exempt in the archive; merge claims are NOT, because a
    factual claim about the past stays falsifiable at any age."""
    from handoff_collect import validate
    repo, _, unmerged = _repo_with_unmerged_branch(git_repo)
    text = f"## Phase 9.0 - retired\n\nMerged to `main` at `{unmerged[:7]}`.\n"
    kinds = {f.kind for f in validate(repo, text, in_archive=True)}
    assert "false-merge-claim" in kinds


def test_dead_path_pointer_is_flagged(git_repo):
    from handoff_collect import validate_path_pointers
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    findings = validate_path_pointers(
        repo, "**Plan:** `docs/plans/never-written.md`\n")
    assert len(findings) == 1
    assert findings[0].kind == "dead-path-pointer"


def test_live_path_pointer_stays_silent(git_repo):
    from handoff_collect import validate_path_pointers
    repo, commit = git_repo
    commit("docs/plans/real.md", "# plan\n", "docs: plan - real")
    assert validate_path_pointers(repo, "**Plan:** `docs/plans/real.md`\n") == []


def test_descriptive_path_mentions_are_not_flagged(git_repo):
    """The finding that shaped this rule: of 88 path-shaped tokens in the real
    documents, 23 do not exist and ALL 23 are legitimate - historical layout,
    deferred work, or a file explicitly described as deleted. A shape-keyed
    rule would emit 23 false positives and break the never-cry-wolf guarantee.
    These three lines are the real corpus patterns."""
    from handoff_collect import validate_path_pointers
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    for line in (
        "| Core settings | `core/settings.py` | `SETTINGS_DEFAULTS` dict, `set_many()` |",
        "- `core/updater.py` - `UpdateChecker(CereneThread)`: fetches releases",
        "the module contract now lives in the kernel, replacing the old `modules/_base.py`.",
    ):
        assert validate_path_pointers(repo, line + "\n") == [], f"false positive: {line[:45]}"


def test_path_pointer_catches_a_windows_absolute_path(git_repo):
    """The defect that motivated this rule was a Windows absolute path in
    CLAUDE.md; a forward-slash-only pattern would have missed it."""
    from handoff_collect import validate_path_pointers
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    line = r"For task specs, read `C:\Users\priya\.claude\plans\stateless-waddling-rossum.md`."
    findings = validate_path_pointers(repo, line + "\n")
    assert len(findings) == 1
    assert "stateless-waddling-rossum" in findings[0].detail


def test_path_pointers_are_checked_in_the_archive_too(git_repo):
    from handoff_collect import validate
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    text = "## Phase 9.0 - retired\n\n**Design:** `docs/specs/gone.md`\n"
    kinds = {f.kind for f in validate(repo, text, in_archive=True)}
    assert "dead-path-pointer" in kinds


# --- the rule registry -------------------------------------------------------

def test_every_rule_declares_a_falsifiable_question():
    """The admission test, made enforceable. A rule belongs only if it can be
    answered yes/no by git or the filesystem. Previously that lived in prose and
    in the author's head, so nothing stopped a rule that inspects numbers or
    dates being added - and such a rule cries wolf, which is the one failure
    that destroys the validator's value."""
    from handoff_collect import RULES
    assert RULES, "registry must not be empty"
    for rule in RULES:
        assert rule.falsifiable.strip(), f"{rule.kind} declares no falsifiable question"
        assert rule.falsifiable.rstrip().endswith("?"), (
            f"{rule.kind}: falsifiable must be phrased as a question, got "
            f"{rule.falsifiable!r}"
        )
        assert rule.scope in {"whole-file", "newest-entry", "repository"}, rule.scope


def test_registry_covers_every_kind_the_validator_can_emit():
    """A rule reachable through validate() but absent from the registry would
    have undeclared scope and archive semantics - exactly the implicit state the
    registry exists to remove."""
    from handoff_collect import RULES
    declared = {r.kind for r in RULES}
    # bare-dead-sha is emitted by the same rule that emits dead-sha.
    emitted = {"dead-sha", "stale-live-claim", "false-merge-claim",
               "dead-path-pointer", "possible-secret"}
    assert emitted <= declared, f"undeclared kinds: {emitted - declared}"


def test_only_non_whole_file_rules_are_archive_exempt():
    """Pins the asymmetry deliberately. A merge claim or dead reference does not
    become acceptable by being retired; only a claim about the CURRENT state
    stops being meaningful once an entry is history.

    The exemption tracks SCOPE exactly, which is not a coincidence. A
    newest-entry rule reads "the newest entry", which in the archive means the
    most recently retired one, so a present-tense reading is wrong by
    construction. A repository-scoped rule reads no document at all, so running
    it again per archive and per extra document would report one disagreement
    several times. Whole-file rules apply everywhere and are never exempt.
    """
    from handoff_collect import RULES
    exempt = {r.kind for r in RULES if not r.in_archive}
    not_whole_file = {r.kind for r in RULES if r.scope != "whole-file"}
    assert exempt == {"stale-live-claim", "unknown-branch", "inconsistent-artifact"}, (
        f"unexpected archive exemptions: {exempt}"
    )
    assert exempt == not_whole_file, (
        f"archive exemption must track scope exactly; "
        f"exempt={exempt} non-whole-file={not_whole_file}"
    )


def test_archive_mode_skips_exactly_the_exempt_rules(git_repo):
    """Behavioural counterpart: the registry's declaration must actually govern
    what runs, not merely describe it."""
    from handoff_collect import RULES, validate
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    subprocess.run(["git", "branch", "claude/old"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "claude/old"], cwd=repo, check=True, capture_output=True)
    commit("b.py", "b = 1\n", "feat: b - on branch")
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "--no-ff", "claude/old", "-m", "m"],
                   cwd=repo, check=True, capture_output=True)

    text = ("## Phase 9.0 - retired\n\nOn `claude/old`. NOT yet merged.\n"
            "See `docs/gone.md`.\n")
    live = {f.kind for f in validate(repo, text)}
    archived = {f.kind for f in validate(repo, text, in_archive=True)}
    assert "stale-live-claim" in live and "stale-live-claim" not in archived
    # everything non-exempt must survive archiving
    assert "dead-path-pointer" in live and "dead-path-pointer" in archived


# --- cross-platform interpreter resolution -----------------------------------

def test_finds_a_posix_layout_interpreter(git_repo):
    """The bug this fixes: only .venv/Scripts/python.exe was ever tried, so on
    macOS and Linux - where the interpreter is .venv/bin/python - nothing was
    found, and the git hook skipped silently on every commit while appearing
    installed and healthy."""
    from handoff_collect import find_python
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    assert find_python(repo) is None

    posix = repo / ".venv" / "bin"
    posix.mkdir(parents=True)
    (posix / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    found = find_python(repo)
    assert found is not None and found.name == "python"


def test_finds_a_windows_layout_interpreter(git_repo):
    from handoff_collect import find_python
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    win = repo / ".venv" / "Scripts"
    win.mkdir(parents=True)
    (win / "python.exe").write_text("", encoding="utf-8")
    found = find_python(repo)
    assert found is not None and found.name == "python.exe"


def test_python3_layout_is_tried_when_python_is_absent(git_repo):
    """Some POSIX venvs ship only python3."""
    from handoff_collect import find_python
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    posix = repo / ".venv" / "bin"
    posix.mkdir(parents=True)
    (posix / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
    found = find_python(repo)
    assert found is not None and found.name == "python3"


def test_missing_interpreter_error_names_what_it_tried(git_repo):
    """An error that only says 'not found' leaves the reader guessing which of
    three layouts was expected."""
    from handoff_collect import run_suite
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    try:
        run_suite(repo, None)
    except RuntimeError as exc:
        message = str(exc)
        assert "Scripts" in message and "bin" in message
        assert "--suite-json" in message
    else:
        raise AssertionError("expected a RuntimeError")


def test_count_examined_reports_the_denominator(git_repo):
    """Zero findings and zero checked print identically without this. That
    ambiguity produced five separate silent failures in one session, so the
    counts are load-bearing, not cosmetic."""
    from handoff_collect import count_examined
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    text = (
        "## Phase 9.1 - x (DONE, 2026-01-01)\n\n"
        "Merged to `main` at `deadbee1`. See `docs/plan.md`.\n"
        "Also `cafe1234` and bare deadbee2 here.\n"
    )
    counts = count_examined(repo, text)
    assert counts["dead-sha"] >= 2, "should have seen the backticked SHAs"
    assert counts["false-merge-claim"] == 1
    assert counts["dead-path-pointer"] == 1
    assert counts["possible-secret"] == len(text.splitlines())


def test_count_examined_reports_zero_when_a_rule_has_nothing_to_check(git_repo):
    """A rule with nothing to examine must report 0, not be omitted - that is
    the signal distinguishing 'no such claims here' from 'pattern is broken'."""
    from handoff_collect import count_examined
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a - base")
    counts = count_examined(repo, "## Phase 1 - nothing falsifiable at all\n")
    assert counts["dead-sha"] == 0
    assert counts["false-merge-claim"] == 0
    assert counts["dead-path-pointer"] == 0
    # Pinned against the registry rather than a hardcoded list, so a rule added
    # WITHOUT a denominator fails here. A silent rule is invisible in exactly
    # the way this whole tool exists to prevent, and a literal set would have to
    # be edited by the same person who forgot.
    from handoff_collect import RULES
    assert set(counts) == {rule.kind for rule in RULES}, (
        "every rule must report a denominator; missing: "
        f"{ {r.kind for r in RULES} - set(counts) }"
    )
