"""Tests for tools/extant_config.py - the portability layer."""
from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def test_defaults_reproduce_this_projects_behaviour(tmp_path):
    """A repo with no .extant.toml must behave exactly as before the config
    layer existed. If this drifts, every existing test is silently testing a
    different configuration than the tool ships with.

    Checked against an EMPTY directory rather than the package root, which now
    carries a `.extant.toml` of its own. The `.git` marker bounds the upward
    search, so this cannot accidentally pick up a config from some parent
    directory on the machine running it.
    """
    from extant_config import load_config
    import extant_collect as h
    (tmp_path / ".git").mkdir()
    cfg = load_config(tmp_path)
    assert cfg.source == "defaults"
    assert cfg.primary_doc == h.PRIMARY_DOC
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
    from extant_config import load_config
    cfg = load_config(PACKAGE_ROOT)
    with open(PACKAGE_ROOT / cfg.primary_doc, encoding="utf-8", newline="") as fh:
        doc = fh.read()

    assert cfg.merge_claim.findall(doc), "merge_claim matches nothing on the real document"
    assert cfg.branch_token.findall(doc), "branch_token matches nothing"
    assert cfg.path_pointer.findall(doc), "path_pointer matches nothing"
    assert "{" not in cfg.merge_claim.pattern.replace("{7,40}", ""), \
        "unsubstituted template braces left in the compiled pattern"


def test_toml_overrides_are_applied(tmp_path):
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        '[extant]\n'
        'primary_doc = "HANDOFF.md"\n'
        'trunk = "trunk"\n'
        'retain_entries = 5\n'
        'entry_prefix = "## Release "\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.primary_doc == "HANDOFF.md"
    assert cfg.retain_entries == 5
    assert cfg.entry_prefix == "## Release "
    assert cfg.source.endswith(".extant.toml")
    # merge_claim no longer embeds the trunk name: a claim says which branch it
    # means, and the rule checks that branch. So the pattern must match BOTH,
    # capturing the ref, where the old trunk-interpolated one matched only the
    # configured branch and was blind to every claim about any other.
    assert cfg.merge_claim.groups == 2, "the ref must be captured alongside the sha"
    for branch in ("trunk", "main", "develop"):
        match = cfg.merge_claim.search(f"shipped to `{branch}` at `abc1234`")
        assert match, f"a claim about `{branch}` was not matched at all"
        assert match.group(1) == f"`{branch}`", "group 1 must be the ref, backticks kept"
        assert match.group(2) == "abc1234"


def test_unknown_keys_are_reported_not_swallowed(tmp_path):
    """A typo'd key that quietly does nothing is the same class of failure as a
    pattern that matches nothing."""
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        '[extant]\nhandof_doc = "typo.md"\n', encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert any("handof_doc" in w for w in cfg.warnings)
    assert cfg.primary_doc == "NEXT_SESSION.md"  # unchanged by the typo


def test_config_without_a_status_table_still_loads(tmp_path):
    """Accept a bare top-level table too, so a minimal config need not nest."""
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text('primary_doc = "FLAT.md"\n', encoding="utf-8")
    assert load_config(tmp_path).primary_doc == "FLAT.md"


def test_regex_in_a_basic_string_gives_an_actionable_error(tmp_path):
    """A regex in a double-quoted TOML string fails to parse, and the bare
    decoder error names only a line and column. porting.md explicitly asks
    people to hand-write these patterns, so the error must state the cause and
    the fix rather than leaving them to guess."""
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        '[extant]\nbranch_token = "`(feat/[^`]+)`"\nmerge_claim = "x\\s+y"\n',
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
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        "[extant]\nbranch_token = '`((?:feature|fix)/[^`]+)`'\n", encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.branch_token.search("on branch `feature/x` now")


def test_suite_command_defaults_to_pytest():
    from extant_config import load_config
    cfg = load_config(PACKAGE_ROOT)
    assert "{python}" in " ".join(cfg.suite_command)
    assert "pytest" in " ".join(cfg.suite_command)


def test_a_non_python_runner_can_be_configured(tmp_path):
    """A JS, Rust or .NET project must be able to use the measured path. The
    counts come from configured patterns, so any runner that prints totals
    works."""
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        "[extant]\n"
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
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        "[extant]\n"
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
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        "[extant]\nphase_task = ''\nphase_bare = ''\n", encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.phase_task is None and cfg.phase_bare is None


def test_plans_dir_can_be_switched_off(tmp_path):
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        "[extant]\nplans_dir = ''\n", encoding="utf-8"
    )
    assert load_config(tmp_path).plans_dir == ""


def test_a_duplicate_key_is_not_blamed_on_regex_quoting(tmp_path):
    """Every hint must fit the error it is attached to.

    The escape hint used to be unconditional, so a duplicate key produced
    "Cannot overwrite a value" followed by a confident paragraph about regex
    quoting. That is worse than no hint: the reader checks their quotes, finds
    them correct, and has no next move. Found by an end-to-end scenario run,
    not by any unit test.
    """
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text(
        "trunk = 'main'\nbranch_token = '`a/b`'\nbranch_token = '`c/d`'\n",
        encoding="utf-8",
    )

    try:
        load_config(tmp_path)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("invalid TOML was accepted")

    assert "same key is set twice" in message, message
    assert "basic* string" not in message, (
        "a duplicate key was blamed on regex quoting:\n" + message
    )


def test_an_escape_error_still_gets_the_quoting_hint(tmp_path):
    """The other half: narrowing the hint must not remove it where it applies."""
    from extant_config import load_config
    # Raw string: the FILE must literally contain a backslash-d inside a
    # double-quoted TOML string, which is what makes the decoder reject it.
    (tmp_path / ".extant.toml").write_text(
        r'branch_token = "`(\d+)/x`"' + "\n", encoding="utf-8",
    )

    try:
        load_config(tmp_path)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("invalid TOML was accepted")

    assert "LITERAL strings" in message, message


def test_an_unrecognised_toml_error_gets_a_generic_hint(tmp_path):
    """A cause the dispatch does not know must fall back honestly rather than
    guessing, which is the whole point of the change."""
    from extant_config import load_config
    (tmp_path / ".extant.toml").write_text("this is not toml at all\n", encoding="utf-8")

    try:
        load_config(tmp_path)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("invalid TOML was accepted")

    assert "not valid TOML" in message, message
    assert "basic* string" not in message, message


def test_top_level_keys_survive_a_status_subtable(tmp_path):
    """Writing [extant.consistency.x] must not discard settings above it.

    TOML turns that header into a `status` key, and choosing between the two
    locations silently dropped every top-level setting: the file looked
    configured and was not. Found by trying to configure a README-only project,
    which is the case this tool most wants to serve.
    """
    from extant_config import load_config
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        'primary_doc = "README.md"\n'
        'extra_docs = ["CONTRIBUTING.md"]\n'
        "\n[extant.consistency.node]\n"
        + r'"README.md" = ' + "'" + r'Node (\d+)' + "'\n"
        + r'"package.json" = ' + "'" + r'node.*?(\d+)' + "'\n",
        encoding="utf-8")

    cfg = load_config(tmp_path)

    assert cfg.primary_doc == "README.md", "a top-level key was discarded"
    assert cfg.extra_docs == ("CONTRIBUTING.md",)
    assert "node" in cfg.consistency


def test_a_key_set_in_both_places_is_refused(tmp_path):
    """Two homes for one setting means the wrong one can be read while the
    right one sits there looking correct."""
    from extant_config import load_config
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text(
        'primary_doc = "TOP.md"\n\n[extant]\nprimary_doc = "NESTED.md"\n',
        encoding="utf-8")

    try:
        load_config(tmp_path)
    except ValueError as exc:
        assert "both at the top level" in str(exc), exc
    else:
        raise AssertionError("a key defined twice was accepted")


# --- older interpreters -------------------------------------------------------
#
# `tomllib` arrived in 3.11 and enterprise distributions are years behind it:
# RHEL 9 and Debian 11 ship 3.9, Ubuntu 22.04 LTS ships 3.10. Nothing else in
# the payload needs 3.11, so requiring it would exclude those for one import.
#
# Run as SUBPROCESSES with the module blocked at import, because that is the
# only honest way to exercise a fallback on an interpreter that does not need
# it. Monkeypatching the name after import tests a different thing entirely.

import subprocess
import sys
import textwrap

PAYLOAD = str(Path(__file__).resolve().parents[1]
              / "plugin" / "skills" / "extant" / "payload")

_BLOCK = textwrap.dedent('''
    import sys
    class _Blocker:
        def find_spec(self, name, target=None, path=None):
            if name in ("tomllib", "tomli"):
                raise ModuleNotFoundError("No module named " + repr(name))
            return None
    sys.meta_path.insert(0, _Blocker())
    sys.path.insert(0, %r)
''') % PAYLOAD


def _without_toml(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", _BLOCK + textwrap.dedent(script)],
                          capture_output=True, text=True)


def test_the_module_imports_with_no_toml_parser_at_all() -> None:
    """Failing at import would deny the whole tool to someone who needs no config.

    A wrong implementation with a bare `import tomllib` raises here, and every
    command becomes unavailable on 3.9 and 3.10 over a file the user may not
    even have.
    """
    result = _without_toml("import extant_config as c; print('TOMLLIB', c.tomllib)")

    assert result.returncode == 0, result.stderr
    assert "TOMLLIB None" in result.stdout


def test_defaults_work_with_no_parser_and_no_config_file(tmp_path) -> None:
    """A repository with no config never parses TOML: the defaults are Python.

    So the degradation is precise rather than wholesale - the tool is fully
    usable on 3.9 for anyone who has not written a config file.
    """
    result = _without_toml(f"""
        import pathlib, extant_config as c
        cfg = c.load_config(pathlib.Path({str(tmp_path)!r}))
        print("DOC", cfg.primary_doc, "SOURCE", cfg.source)
    """)

    assert result.returncode == 0, result.stderr
    assert "DOC NEXT_SESSION.md" in result.stdout
    assert "SOURCE defaults" in result.stdout


def test_a_config_file_with_no_parser_names_the_remedy(tmp_path) -> None:
    """The one case that must fail, and it must fail with a sentence.

    Silently ignoring a config file the user wrote would be the worst outcome
    available: the tool would run on defaults while they believed it was
    running on their settings, which is this project's defining failure. A bare
    ModuleNotFoundError naming a module they never imported is barely better.
    """
    (tmp_path / ".git").mkdir()
    (tmp_path / ".extant.toml").write_text('primary_doc = "README.md"\n',
                                           encoding="utf-8")

    result = _without_toml(f"""
        import pathlib, extant_config as c
        c.load_config(pathlib.Path({str(tmp_path)!r}))
    """)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "pip install tomli" in combined, combined
    assert "3.11" in combined, combined
    assert ".extant.toml" in combined, combined
