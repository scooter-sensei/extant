"""Settings load from the repository you point at, not from beside the tool.

The README listed the opposite under "what it cannot do": configuration was
read once at import, relative to the tool's own file, so a run against
another repository used the tool's settings and printed a NOTE saying the
target's `.extant.toml` was NOT read. The console script `cli()` had already
learned to re-read from `--repo`; `main()`, which the installed shim and the
hooks run, had not. The review's 6.6 asked how many corpus repositories would
find a configuration under each rule: 0 of 152 track a `.extant.toml` and 0
a `[tool.extant]`, so the corpus cannot separate the rules and the question
is one of semantics. Answered here: both entry points read the target, the
NOTE has no condition left to report, and it is gone.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def _configured(repo: Path, commit) -> None:
    commit("STATUS.md", "# Status\n\n## Phase 1 - work (2026-09-16)\n\nDone.\n",
           "docs: status")
    commit(".extant.toml", 'primary_doc = "STATUS.md"\n', "chore: config")


def test_main_reads_the_configuration_of_the_repository_it_is_pointed_at(
        git_repo, capsys) -> None:
    """The shim's entry point, run against a repository with its own settings,
    checks the document those settings name and prints no note about them."""
    from extant import cli
    repo, commit = git_repo
    _configured(repo, commit)

    code = cli.main(["--verify", "--repo", str(repo)])

    out = capsys.readouterr()
    combined = out.out + out.err
    assert "checked STATUS.md" in combined, combined
    assert "NOT read" not in combined and "settings came from" not in combined, combined
    assert code == 0, combined


def test_the_console_script_and_the_shim_read_the_same_settings(
        git_repo, capsys, monkeypatch) -> None:
    """One reload, in the one place both entry points pass through."""
    from extant import cli
    from extant import session as hc
    repo, commit = git_repo
    _configured(repo, commit)

    # The shim's path FIRST, so it cannot inherit what the console script's
    # reload left behind.
    cli.main(["--verify", "--repo", str(repo)])
    via_shim = capsys.readouterr()
    shim_source = hc.CONFIG.source
    monkeypatch.setattr(sys, "argv", ["extant", "--repo", str(repo)])
    cli.cli()
    via_script = capsys.readouterr()

    assert "checked STATUS.md" in via_shim.out + via_shim.err, via_shim
    assert "checked STATUS.md" in via_script.out + via_script.err, via_script
    assert shim_source == hc.CONFIG.source == str(repo / ".extant.toml")


def test_a_repository_without_settings_gets_the_defaults_not_the_tools_own(
        git_repo, capsys) -> None:
    """The other half: pointed at a repository with no configuration, the run
    uses the defaults - not whatever the tool's own checkout configures."""
    from extant import cli
    from extant import session as hc
    repo, commit = git_repo
    commit("NEXT_SESSION.md", "# Status\n\n## Phase 1 - work (2026-09-16)\n\nDone.\n",
           "docs: status")

    cli.main(["--verify", "--repo", str(repo)])

    assert hc.CONFIG.source == "defaults", hc.CONFIG.source
    assert "checked NEXT_SESSION.md" in "".join(capsys.readouterr())
