"""Tests for tools/handoff_config.py - the portability layer."""
from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def test_defaults_reproduce_this_projects_behaviour():
    """A repo with no .handoff.toml must behave exactly as before the config
    layer existed. If this drifts, every existing test is silently testing a
    different configuration than the tool ships with."""
    from handoff_config import load_config
    import handoff_collect as h
    cfg = load_config(PACKAGE_ROOT)
    assert cfg.source == "defaults"
    assert cfg.handoff_doc == h.HANDOFF_DOC
    assert cfg.archive_doc == h.ARCHIVE_DOC
    assert cfg.retain_entries == h.RETAIN_ENTRIES
    assert cfg.archive_header == h._ARCHIVE_HEADER
    assert cfg.entry_prefix == h._PHASE_PREFIX
    assert cfg.pointer_prefix == h._POINTER_PREFIX


def test_every_pattern_compiles_and_matches_something_real():
    """The failure this guards against actually happened during development: the
    default merge_claim pattern was written with doubled braces (escaped for
    str.format, but substituted with str.replace), so it compiled fine and
    matched NOTHING. A rule that silently validates nothing is the exact failure
    the design exists to prevent, so assert against the real corpus."""
    from handoff_config import load_config
    cfg = load_config(PACKAGE_ROOT)
    doc = (PACKAGE_ROOT / cfg.handoff_doc).read_text(encoding="utf-8", newline="")

    assert cfg.merge_claim.findall(doc), "merge_claim matches nothing on the real document"
    assert cfg.branch_token.findall(doc), "branch_token matches nothing"
    assert cfg.path_pointer.findall(doc), "path_pointer matches nothing"
    assert "{" not in cfg.merge_claim.pattern.replace("{7,40}", ""), \
        "unsubstituted template braces left in the compiled pattern"


def test_toml_overrides_are_applied(tmp_path):
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        '[handoff]\n'
        'handoff_doc = "HANDOFF.md"\n'
        'trunk = "trunk"\n'
        'retain_entries = 5\n'
        'entry_prefix = "## Release "\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.handoff_doc == "HANDOFF.md"
    assert cfg.retain_entries == 5
    assert cfg.entry_prefix == "## Release "
    assert cfg.source.endswith(".handoff.toml")
    # trunk is interpolated into merge_claim, so overriding it must retarget the rule
    assert "trunk" in cfg.merge_claim.pattern
    assert cfg.merge_claim.search("shipped to `trunk` at `abc1234`")
    assert not cfg.merge_claim.search("shipped to `main` at `abc1234`")


def test_unknown_keys_are_reported_not_swallowed(tmp_path):
    """A typo'd key that quietly does nothing is the same class of failure as a
    pattern that matches nothing."""
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        '[handoff]\nhandof_doc = "typo.md"\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert any("handof_doc" in w for w in cfg.warnings)
    assert cfg.handoff_doc == "NEXT_SESSION.md"  # unchanged by the typo


def test_config_without_a_handoff_table_still_loads(tmp_path):
    """Accept a bare top-level table too, so a minimal config need not nest."""
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text('handoff_doc = "FLAT.md"\n', encoding="utf-8")
    assert load_config(tmp_path).handoff_doc == "FLAT.md"


def test_regex_in_a_basic_string_gives_an_actionable_error(tmp_path):
    """A regex in a double-quoted TOML string fails to parse, and the bare
    decoder error names only a line and column. porting.md explicitly asks
    people to hand-write these patterns, so the error must state the cause and
    the fix rather than leaving them to guess."""
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        '[handoff]\nbranch_token = "`(feat/[^`]+)`"\nmerge_claim = "x\\s+y"\n',
        encoding="utf-8",
    )
    try:
        load_config(tmp_path)
    except ValueError as exc:
        message = str(exc)
        assert "LITERAL strings (single quotes)" in message
        assert "correct" in message
    else:
        raise AssertionError("expected a ValueError explaining the escape problem")


def test_a_literal_string_regex_loads_fine(tmp_path):
    """The documented correct form."""
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        "[handoff]\nbranch_token = '`((?:feature|fix)/[^`]+)`'\n", encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.branch_token.search("on branch `feature/x` now")


def test_suite_command_defaults_to_pytest():
    from handoff_config import load_config
    cfg = load_config(PACKAGE_ROOT)
    assert "{python}" in " ".join(cfg.suite_command)
    assert "pytest" in " ".join(cfg.suite_command)


def test_a_non_python_runner_can_be_configured(tmp_path):
    """A JS, Rust or .NET project must be able to use the measured path. The
    counts come from configured patterns, so any runner that prints totals
    works."""
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        "[handoff]\n"
        'suite_command = ["npm", "test"]\n'
        "suite_passed = '(\\d+) passed'\n"
        "suite_failed = '(\\d+) failed'\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.suite_command == ("npm", "test")
    assert "{python}" not in " ".join(cfg.suite_command)
    jest = "Tests:       3 failed, 12 passed, 15 total"
    assert cfg.suite_passed.search(jest).group(1) == "12"
    assert cfg.suite_failed.search(jest).group(1) == "3"


def test_cargo_and_dotnet_output_can_be_matched(tmp_path):
    """Real output shapes from two other ecosystems."""
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        "[handoff]\n"
        "suite_passed = '(\\d+) passed'\n"
        "suite_failed = '(\\d+) failed'\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    cargo = "test result: ok. 12 passed; 0 failed; 0 ignored"
    assert cfg.suite_passed.search(cargo).group(1) == "12"
    assert cfg.suite_failed.search(cargo).group(1) == "0"


def test_phase_grouping_can_be_switched_off(tmp_path):
    """A project with no phase or ticket cadence must not inherit this one's
    regex and label every commit 'unknown'."""
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        "[handoff]\nphase_task = ''\nphase_bare = ''\n", encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.phase_task is None and cfg.phase_bare is None


def test_plans_dir_can_be_switched_off(tmp_path):
    from handoff_config import load_config
    (tmp_path / ".handoff.toml").write_text(
        "[handoff]\nplans_dir = ''\n", encoding="utf-8"
    )
    assert load_config(tmp_path).plans_dir == ""
