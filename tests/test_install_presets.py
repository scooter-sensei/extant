"""Preset behaviour, which had no tests at all until this file.

That absence is why the bug below shipped. The five presets were checked by
hand before 0.5.0, every one of them in a repository that already had a
detectable status document - so `readme`, the preset whose entire purpose is a
project with NO such document, was never once exercised in the only situation
it exists for. It failed there, and nothing said so for two releases.

The installer is run as a SUBPROCESS rather than imported, because that is how
a user meets it: the exit code and the file it leaves behind are the contract,
and a test that calls internals can pass while the command still refuses to
run.
"""
from __future__ import annotations

import subprocess
import sys
try:
    import tomllib
except ModuleNotFoundError:      # Python < 3.11, see requirements-dev.txt
    import tomli as tomllib
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
INSTALLER = SKILL_ROOT / "install.py"


def run_installer(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--repo", str(repo), *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def make_repo(tmp_path: Path, **files: str) -> Path:
    """A git repo containing exactly `files` and no status document."""
    repo = tmp_path / "proj"
    repo.mkdir()
    for name, body in files.items():
        path = repo / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(body)
    for cmd in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                ["config", "user.name", "T"], ["add", "-A"],
                ["commit", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, capture_output=True, check=True)
    return repo


def config_of(repo: Path) -> dict:
    """The effective settings, merged the way the loader merges them.

    Settings may sit at the top level or under `[extant]`, and the loader reads
    both. A helper that looked in only one place would pass or fail on where
    the installer happens to put them rather than on what it decided, and the
    installer does use the table form.
    """
    with open(repo / ".extant.toml", "rb") as fh:
        data = tomllib.load(fh)
    nested = data.get("extant", {})
    top = {k: v for k, v in data.items() if k != "extant"}
    return {**top, **nested}


README = "# Demo\n\nShipped in `deadbeef1234567`.\n"
CONTRIBUTING = "# Contributing\n\nRun the setup script.\n"


def test_readme_preset_works_with_no_status_document(tmp_path) -> None:
    """The bug this file was written for.

    `--preset readme` is documented as "no status file needed", and it names
    README.md. But README.md is not a status-document name, so detection found
    nothing and the installer exited 1 BEFORE the preset was ever consulted.
    The preset advertised that it needed no status document and then demanded
    one.

    A wrong implementation that reinstates the early bailout fails here with
    exit 1 and "no status document found".
    """
    repo = make_repo(tmp_path, **{"README.md": README, "CONTRIBUTING.md": CONTRIBUTING})

    result = run_installer(repo, "--preset", "readme")

    assert result.returncode == 0, (
        "--preset readme must work on a project with no status document, "
        f"which is the only case it exists for.\n{result.stdout}\n{result.stderr}"
    )
    assert config_of(repo)["primary_doc"] == "README.md"


def test_readme_preset_adds_the_extra_document_it_names(tmp_path) -> None:
    """Catches a preset that sets the primary document and drops the rest."""
    repo = make_repo(tmp_path, **{"README.md": README, "CONTRIBUTING.md": CONTRIBUTING})

    assert run_installer(repo, "--preset", "readme").returncode == 0

    assert config_of(repo)["extra_docs"] == ["CONTRIBUTING.md"]


def test_an_explicit_preset_outranks_a_detected_document(tmp_path) -> None:
    """Asking for a preset is an instruction, so it wins on the document.

    This test asserted the opposite first, on the strength of a docstring
    saying a preset "never overrides something MEASURED". That rule is real but
    it is about the trunk name and branch shape, which the repository owns.
    Which file to check is the user's call, and they made it by passing the
    flag.
    """
    repo = make_repo(tmp_path, **{
        "NEXT_SESSION.md": "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n",
        "README.md": README,
    })

    assert run_installer(repo, "--preset", "readme").returncode == 0

    assert config_of(repo)["primary_doc"] == "README.md"


def test_the_archive_is_placed_beside_the_document_the_preset_chose(tmp_path) -> None:
    """Catches the document being switched AFTER its neighbours were derived.

    The archive is placed beside the primary document and the evidence quotes
    that document's length, both computed from whatever was chosen first. Fold
    a preset in afterwards and those keep describing the previous file: the
    preset points primary_doc at the README in the root while the archive sits
    in `docs/`, beside a document no longer being checked.

    A wrong implementation that applies the preset after `observe` puts
    `docs/status-archive.md` here.
    """
    repo = make_repo(tmp_path, **{
        "docs__NEXT_SESSION.md": "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n",
        "README.md": README,
    })

    assert run_installer(repo, "--preset", "readme").returncode == 0

    cfg = config_of(repo)
    assert cfg["primary_doc"] == "README.md"
    assert cfg["archive_doc"] == "status-archive.md", (
        "the archive was placed beside the document the preset replaced"
    )


def test_a_preset_skips_extra_documents_that_are_absent(tmp_path) -> None:
    """A preset must not name a file the project does not have.

    Its first act would then be a false positive, reporting a missing document
    the user never claimed to keep, which is the fastest way to teach someone
    to ignore a validator.
    """
    repo = make_repo(tmp_path, **{"README.md": README})     # no CONTRIBUTING.md

    assert run_installer(repo, "--preset", "readme").returncode == 0

    assert "CONTRIBUTING.md" not in config_of(repo).get("extra_docs", [])


def test_no_document_and_no_preset_still_fails_and_says_what_to_do(tmp_path) -> None:
    """The fix must not turn the genuine no-document case into a silent pass.

    Without a preset there is nothing to check, so exiting 0 would install a
    validator that validates nothing - the exact shape this project exists to
    surface. It must fail, and the message must name the way out.
    """
    repo = make_repo(tmp_path, **{"notes.txt": "nothing here\n"})

    result = run_installer(repo)

    assert result.returncode == 1
    assert "--preset readme" in result.stdout, (
        "the failure must name the option that resolves it"
    )


def run_validator(repo: Path) -> subprocess.CompletedProcess[str]:
    """The installed copy, run the way the hooks run it."""
    return subprocess.run(
        [sys.executable, str(repo / "tools" / "extant_collect.py"),
         "--repo", str(repo), "--verify"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


# The files each preset's consistency checks compare, agreeing, plus the edit
# that makes one pair disagree. Written in the real formats rather than in a
# shape convenient for the regex, because a pattern that only matches the
# fixture is the failure this project exists to surface.
#
# The README here is deliberately CLAIM-FREE. The shared one carries a dead SHA
# for the tests above, and reusing it made the "agreeing files must pass" half
# fail on that instead - passing for a reason that had nothing to do with the
# consistency check, which is the mirror image of the bug being guarded.
CLEAN_README = "# Demo\n\nAn ordinary project with nothing falsifiable in it.\n"

CONSISTENCY_CASES = {
    "ml": (
        {
            "README.md": CLEAN_README,
            "pyproject.toml": '[project]\nname = "m"\nversion = "2.3.0"\nrequires-python = ">=3.11"\n',
            "environment.yml": "name: env\ndependencies:\n  - python=3.11\n  - numpy\n",
            "CHANGELOG.md": "# Changelog\n\n## 2.3.0 (2026-01-01)\n\nstuff\n",
        },
        ("environment.yml", "python=3.11", "python=3.10"),
    ),
    "legacy-web": (
        {
            "README.md": CLEAN_README,
            ".nvmrc": "v20.11.0\n",
            "package.json": '{\n  "name": "app",\n  "version": "2.3.0",\n  "engines": { "node": ">=20" }\n}\n',
            "CHANGELOG.md": "# Changelog\n\n## 2.3.0 (2026-01-01)\n\nstuff\n",
        },
        (".nvmrc", "v20.11.0", "v18.19.0"),
    ),
    # Each fixture below carries the neighbouring field that must NOT be
    # captured, because that is where these ecosystems trap a naive pattern.
    "go": (
        {
            "README.md": CLEAN_README,
            # `toolchain` is an EXACT build version beside `go`, which is a
            # minimum language version. Capturing the wrong one compares an
            # exact pin against a floor.
            "go.mod": ("module github.com/acme/widget\n\ngo 1.22\n\n"
                       "toolchain go1.22.5\n"),
            # Written the modern way: syntax directive, --platform, stage name.
            "Dockerfile": ("# syntax=docker/dockerfile:1\n"
                           "FROM --platform=$BUILDPLATFORM golang:1.22 AS build\n"
                           "WORKDIR /src\n"),
        },
        ("Dockerfile", "golang:1.22", "golang:1.21"),
    ),
    "jvm": (
        {
            "README.md": CLEAN_README,
            "gradle.properties": "org.gradle.jvmargs=-Xmx2g\ngroup=com.acme\nversion=3.4.1\n",
            "CHANGELOG.md": "# Changelog\n\n## 3.4.1 (2026-01-01)\n\nstuff\n",
        },
        ("gradle.properties", "version=3.4.1", "version=3.5.0"),
    ),
    "k8s": (
        {
            "README.md": CLEAN_README,
            # appVersion is 4.2.1 and the chart version is 1.8.0. Helm's own
            # documentation says these are unrelated, so a check that paired
            # them would fire on this perfectly correct chart.
            "Chart.yaml": ("apiVersion: v2\nname: widget\ntype: application\n"
                           'version: 1.8.0\nappVersion: "4.2.1"\n'),
            "CHANGELOG.md": "# Changelog\n\n## 1.8.0 (2026-01-01)\n\nstuff\n",
        },
        ("Chart.yaml", "version: 1.8.0", "version: 1.9.0"),
    ),
    "monorepo": (
        {
            "README.md": CLEAN_README,
            "package.json": ('{\n  "name": "root",\n  "private": true,\n'
                             '  "version": "3.4.1",\n  "workspaces": ["packages/*"]\n}\n'),
            "CHANGELOG.md": "# Changelog\n\n## 3.4.1 (2026-01-01)\n\nstuff\n",
        },
        ("CHANGELOG.md", "## 3.4.1", "## 3.5.0"),
    ),
    "mobile": (
        {
            "README.md": CLEAN_README,
            # versionCode and CURRENT_PROJECT_VERSION are build counters that
            # differ between platforms by design. Only the marketing version is
            # the same app, and only it is compared.
            "android__app__build.gradle": ("android {\n    defaultConfig {\n"
                                           "        versionCode 412\n"
                                           '        versionName "4.2.1"\n    }\n}\n'),
            "ios__App.xcodeproj__project.pbxproj": (
                "\t\t\t\tCURRENT_PROJECT_VERSION = 412;\n"
                "\t\t\t\tMARKETING_VERSION = 4.2.1;\n"),
        },
        ("android/app/build.gradle", 'versionName "4.2.1"', 'versionName "4.3.0"'),
    ),
}


@pytest.mark.parametrize("preset", sorted(CONSISTENCY_CASES))
def test_preset_consistency_check_fires_when_the_files_disagree(preset, tmp_path) -> None:
    """The half that matters: a check that cannot fail is not a check.

    Both directions are asserted. Clean files must pass, because a check that
    reports on everything is indistinguishable from one that works; then one
    file is edited so the pair genuinely disagrees, and the run must fail and
    name the check.

    A wrong implementation whose pattern matches nothing passes BOTH halves of
    a one-directional test while checking nothing at all.
    """
    files, (target, before, after) = CONSISTENCY_CASES[preset]
    repo = make_repo(tmp_path, **files)

    assert run_installer(repo, "--preset", preset).returncode == 0

    clean = run_validator(repo)
    assert clean.returncode == 0, (
        f"agreeing files must pass:\n{clean.stdout}\n{clean.stderr}"
    )

    path = repo / target
    text = path.read_text(encoding="utf-8")
    assert before in text, f"fixture anchor {before!r} missing from {target}"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace(before, after))

    broken = run_validator(repo)
    assert broken.returncode == 1, (
        f"{preset} did not notice {target} disagreeing:\n{broken.stdout}"
    )
    assert "inconsistent-artifact" in broken.stdout


def test_a_preset_skips_a_consistency_check_whose_files_are_absent(tmp_path) -> None:
    """Found by mutation: emitting the check regardless left the suite green.

    A check naming a file the project does not have reports a finding on the
    very first run, about a document the reader never claimed to keep. That is
    the fastest way to teach somebody to ignore a validator, and no test noticed
    it was possible.

    Here the `ml` preset wants `pyproject.toml` and `environment.yml` for its
    Python-version check. Only one is present, so the check must not be written.
    """
    repo = make_repo(tmp_path, **{
        "README.md": CLEAN_README,
        "pyproject.toml": '[project]\nname = "m"\nversion = "1.0.0"\nrequires-python = ">=3.11"\n',
        # environment.yml deliberately absent
    })

    result = run_installer(repo, "--preset", "ml")

    assert result.returncode == 0, result.stdout
    checks = config_of(repo).get("consistency", {})
    assert "python_version" not in checks, (
        "a check was emitted naming environment.yml, which does not exist here"
    )
    assert "skipped" in result.stdout, "the skip must be reported, not silent"


def test_a_preset_actually_switches_off_what_it_disables(tmp_path) -> None:
    """Also found by mutation: nothing asserted the `disable` list did anything.

    A README has no dated entries, so the phase-grouping and plan-scanning
    settings have nothing to act on. Left switched ON they are patterns that
    match nothing, which is this project's defining failure: a rule reporting a
    clean run forever while examining zero candidates.

    An empty string means OFF, distinct from the key being absent, which would
    fall back to the default and switch the feature back on.
    """
    repo = make_repo(tmp_path, **{"README.md": CLEAN_README})

    assert run_installer(repo, "--preset", "readme").returncode == 0

    cfg = config_of(repo)
    for key in ("phase_task", "phase_bare", "plans_dir"):
        assert cfg.get(key) == "", (
            f"{key} is {cfg.get(key)!r}, so a feature with nothing to act on "
            f"is still switched on"
        )


def test_enterprise_preset_collects_the_long_lived_documents(tmp_path) -> None:
    """Its value is the document set, so that is what is pinned.

    An LTS project's oldest links live in its policy and upgrade notes. This
    preset carries no consistency check, because "enterprise" names an audience
    rather than a language and there is no manifest common to all of them.
    """
    repo = make_repo(tmp_path, **{
        "README.md": README,
        "SECURITY.md": "# Security\n\nSupported versions are listed here.\n",
        "UPGRADING.md": "# Upgrading\n\nSee the notes.\n",
    })

    assert run_installer(repo, "--preset", "enterprise").returncode == 0

    extras = config_of(repo)["extra_docs"]
    assert "SECURITY.md" in extras
    assert "UPGRADING.md" in extras
    # Absent ones must not be named, or the first run reports a document the
    # project never claimed to keep.
    assert "SUPPORT.md" not in extras
    assert "MIGRATION.md" not in extras


def _document_presets() -> list[str]:
    """Every preset that names its own document, read from PRESETS itself.

    Derived rather than listed. The hardcoded version went three releases
    without the presets added after it, so a new preset shipped untested by the
    one test whose whole job is "does this preset produce a config the tool can
    read". A list of names in a test is a claim about the code, and it rots the
    same way any other claim does.
    """
    sys.path.insert(0, str(SKILL_ROOT))
    from install import PRESETS

    return sorted(name for name, preset in PRESETS.items()
                  if preset.get("primary_doc"))


@pytest.mark.parametrize("preset", _document_presets())
def test_every_document_preset_writes_loadable_toml(preset, tmp_path) -> None:
    """Catches an installer that emits a config the tool then refuses to read.

    It has happened: a preset switching a feature off wrote `plans_dir = ` with
    nothing after it, which is not valid TOML. The parse below is the whole
    assertion - an installer that writes a broken config is worse than one that
    writes none.
    """
    repo = make_repo(tmp_path, **{
        "README.md": README,
        "CONTRIBUTING.md": CONTRIBUTING,
        "package.json": '{"name":"x","version":"1.0.0"}\n',
        "pyproject.toml": '[project]\nname = "x"\nversion = "1.0.0"\n',
        "Cargo.toml": '[package]\nname = "x"\nversion = "1.0.0"\n',
        "CHANGELOG.md": "# Changelog\n\n## 1.0.0\n",
    })

    result = run_installer(repo, "--preset", preset)

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == "README.md"


def test_an_unrecognised_observation_still_renders_valid_toml(tmp_path) -> None:
    """The renderer quotes by an allowlist of KEY NAMES, which cannot cover a
    key nobody has thought of yet.

    `release_tag` landed in the fallback branch the day it was added and was
    written unquoted. That is not valid TOML, so the tool refused to read the
    config and every rule in it went silent at once, on a run that otherwise
    looked entirely normal. The allowlist was updated, but the trap is the
    fallback: the next observation added lands there too.

    A wrong implementation writes the value bare and this fails to parse.
    """
    import sys

    sys.path.insert(0, str(SKILL_ROOT))
    from detect import DERIVED, Observation
    from install import render_config

    rendered = render_config([
        Observation("primary_doc", "README.md", DERIVED, "measured"),
        # A regex-valued key the allowlist has never heard of.
        Observation("some_future_pattern", r"^\d+\.\d+\s+(\w+)$", DERIVED, "invented"),
    ])

    parsed = tomllib.loads(rendered)["extant"]
    assert parsed["some_future_pattern"] == r"^\d+\.\d+\s+(\w+)$", (
        "the value survived quoting but did not round-trip intact"
    )


# --- other agents -------------------------------------------------------------

def test_the_installer_writes_the_cross_platform_skill(tmp_path) -> None:
    """Agent Skills is an open standard, and `.agents/skills/` is where it lives.

    One SKILL.md is read by Codex, Gemini CLI, Copilot, Cursor and Kimi Code as
    well as Claude. The validator itself was never Claude-specific - it is
    Python, git hooks and a pre-commit entry - but exactly one line of the
    installer decided where the agent-facing instructions went, and it pointed
    at `.claude/` alone. That single path was the whole of "only works with
    Claude".

    A wrong implementation that reverts to writing only the slash command
    leaves every other agent with no instructions at all.
    """
    repo = make_repo(tmp_path, **{"README.md": CLEAN_README})

    result = run_installer(repo, "--preset", "readme")

    assert result.returncode == 0, result.stdout
    skill = repo / ".agents" / "skills" / "extant" / "SKILL.md"
    assert skill.is_file(), (
        f"no cross-platform skill written:\n{result.stdout}"
    )
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---"), "a skill needs YAML frontmatter to be discovered"
    assert "name: extant" in text
    assert "description:" in text, "the description is what an agent matches on"


def test_no_claude_directory_appears_in_a_repo_with_no_sign_of_claude(tmp_path) -> None:
    """The one Claude-only artifact must not be written unasked.

    `.agents/skills/` is the open standard and is always written. The slash
    command is the opposite: only Claude Code can read it, and it was created
    unconditionally, so installing into a Codex or Cursor project planted a
    `.claude/` directory its owner never asked for and could not use. That one
    directory is most of what "tightly coupled to Claude" ever pointed at.

    A wrong implementation that writes it anyway fails here, and so does one
    that skips it SILENTLY - a file that does not appear is invisible, so the
    run has to say the command exists and name the flag that produces it.
    """
    repo = make_repo(tmp_path, **{"README.md": CLEAN_README})

    result = run_installer(repo, "--preset", "readme")

    assert result.returncode == 0, result.stdout
    assert not (repo / ".claude").exists(), (
        f"a .claude directory was created in a repo with no Claude evidence:\n"
        f"{result.stdout}"
    )
    assert "--claude-command" in result.stdout, (
        f"skipping it was not reported, so nobody can discover the flag:\n"
        f"{result.stdout}"
    )
    # The point of the change: the tool-agnostic half is untouched.
    assert (repo / ".agents" / "skills" / "extant" / "SKILL.md").is_file(), (
        "gating the slash command must not gate the open-standard skill"
    )


def test_claude_evidence_brings_the_slash_command_back(tmp_path) -> None:
    """A repo that does use Claude Code still gets the command, unprompted.

    Otherwise the fix for over-installing would be a regression for everyone it
    was already working for. Both evidence shapes are checked because a rule
    keyed on only one of them would silently do nothing for half of them.
    """
    for marker, contents in (("CLAUDE.md", "# House rules\n"), (".claude/x", "")):
        base = tmp_path / marker.replace("/", "_").replace(".", "")
        base.mkdir()
        repo = make_repo(base, **{"README.md": CLEAN_README,
                                  marker.replace("/", "__"): contents})

        result = run_installer(repo, "--preset", "readme")

        assert result.returncode == 0, result.stdout
        assert (repo / ".claude" / "commands" / "extant.md").is_file(), (
            f"evidence {marker} did not produce the slash command:\n{result.stdout}"
        )


def test_the_slash_command_can_be_forced_and_suppressed(tmp_path) -> None:
    """Both overrides work, which is why the flag has three states and not two.

    A plain store_true could not distinguish "left at the default" from
    "explicitly off", so there would be no way to decline the file in a repo
    that does carry Claude evidence.
    """
    (tmp_path / "forced").mkdir()
    bare = make_repo(tmp_path / "forced", **{"README.md": CLEAN_README})
    forced = run_installer(bare, "--preset", "readme", "--claude-command")
    assert forced.returncode == 0, forced.stdout
    assert (bare / ".claude" / "commands" / "extant.md").is_file(), (
        f"--claude-command did not write it:\n{forced.stdout}"
    )

    (tmp_path / "suppressed").mkdir()
    evident = make_repo(tmp_path / "suppressed",
                        **{"README.md": CLEAN_README, "CLAUDE.md": "# rules\n"})
    off = run_installer(evident, "--preset", "readme", "--no-claude-command")
    assert off.returncode == 0, off.stdout
    assert not (evident / ".claude").exists(), (
        f"--no-claude-command was ignored in a repo with evidence:\n{off.stdout}"
    )


def test_no_hook_ships_advice_only_one_agent_can_follow(tmp_path) -> None:
    """The guard's help text is read by whoever it just blocked.

    It suggested `git worktree add .claude/worktrees/<name>`, which is this
    project's own habit rather than a general one, and it reached every
    repository that installed the hooks. `../<name>` is the ordinary git idiom
    and works anywhere, including for people with no agent at all.
    """
    repo = make_repo(tmp_path, **{"README.md": CLEAN_README})
    assert run_installer(repo, "--preset", "readme").returncode == 0

    guard = (repo / "tools" / "hooks" / "main-tree-guard").read_text(encoding="utf-8")
    assert ".claude" not in guard, (
        "the shipped guard still names a Claude-specific path in its advice"
    )
    assert "git worktree add ../" in guard, (
        "the replacement advice is missing, so the guard now suggests nothing"
    )


def test_the_cross_platform_skill_is_rendered_for_this_repo(tmp_path) -> None:
    """Rendered from the same observations as the slash command, not copied.

    A verbatim template would tell every project it was some other project, and
    would leave `{{DOC}}` in the prose an agent reads as instructions. The
    installer already had that bug once, for the Claude command file.
    """
    repo = make_repo(tmp_path, **{"README.md": CLEAN_README})

    assert run_installer(repo, "--preset", "readme").returncode == 0

    text = (repo / ".agents" / "skills" / "extant" / "SKILL.md").read_text(
        encoding="utf-8")

    assert repo.name in text, "the skill does not name the project it was written for"
    assert "{{" not in text, f"unsubstituted placeholder left in the skill:\n{text}"
    assert "README.md" in text, "the skill does not name the document it checks"


def test_both_agent_files_describe_the_same_document(tmp_path) -> None:
    """The Claude command and the portable skill must not diverge.

    They are rendered from one set of observations for exactly this reason: two
    files telling two agents to check two different documents is the failure
    this project exists to surface, shipped by its own installer.

    `--claude-command` because this fixture carries no sign of Claude Code and
    the slash command is no longer written without one. The flag is the point
    of the test rather than a workaround: it is the only way to get both files
    into one repository, which is the only way to compare them.
    """
    repo = make_repo(tmp_path, **{
        "README.md": CLEAN_README,
        "docs__STATUS.md": "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n",
    })

    assert run_installer(repo, "--doc", "docs/STATUS.md",
                         "--claude-command").returncode == 0

    command = (repo / ".claude" / "commands" / "extant.md").read_text(encoding="utf-8")
    skill = (repo / ".agents" / "skills" / "extant" / "SKILL.md").read_text(
        encoding="utf-8")

    assert "docs/STATUS.md" in command, command[:400]
    assert "docs/STATUS.md" in skill, skill[:400]


def test_a_hand_edited_agent_skill_is_not_overwritten(tmp_path) -> None:
    """Re-running setup must not silently discard local edits.

    The generated skill is a file humans then add to: a team's own conventions,
    an extra document to watch, a note about which suite to run. Setup is
    otherwise idempotent by rewriting, so without this guard a second run - and
    every hook-triggered one after it - would erase that work with no warning
    and no diff to notice. `--force` remains the way to take the new version.

    Added because a mutation campaign deleted the guard and the whole suite
    stayed green: the smoke harness noticed, but nothing in pytest did, and a
    behaviour only a hand-run harness pins is a behaviour that regresses
    between campaigns.
    """
    repo = make_repo(tmp_path, **{"README.md": CLEAN_README})
    assert run_installer(repo, "--preset", "readme").returncode == 0

    skill = repo / ".agents" / "skills" / "extant" / "SKILL.md"
    edited = skill.read_text(encoding="utf-8") + "\nLOCAL: also check RELEASES.md\n"
    skill.write_text(edited, encoding="utf-8")

    second = run_installer(repo, "--preset", "readme")

    assert second.returncode == 0, second.stdout
    assert skill.read_text(encoding="utf-8") == edited, (
        "a re-run overwrote a hand-edited skill:\n" + second.stdout
    )
    assert "already exists" in second.stdout, (
        "the run said nothing about leaving the existing file alone:\n"
        + second.stdout
    )

    forced = run_installer(repo, "--preset", "readme", "--force")

    assert forced.returncode == 0, forced.stdout
    assert skill.read_text(encoding="utf-8") != edited, (
        "--force did not replace the file, so there is no way to take an update"
    )


def test_every_value_type_the_installer_can_emit_round_trips() -> None:
    """The generalisation of the test above, written after it missed one.

    That test proved the fallback quotes a STRING of an unknown key. The next
    observation added was a BOOLEAN - `release_claims_name_our_tags` - and the
    fallback wrote Python's `True`, which TOML rejects. The installer produced
    a config the tool refused to read, silencing every rule at once: the third
    time this function has shipped exactly that, after `plans_dir = ` with
    nothing after it and `release_tag` written bare.

    Each fix added the branch for the type that had just bitten. So this asks
    the general question instead - does EVERY value type the installer can emit
    survive a parse - and a new type has to be added here to be trusted.
    """
    import sys

    sys.path.insert(0, str(SKILL_ROOT))
    from detect import DERIVED, Observation
    from install import render_config

    rendered = render_config([
        Observation("primary_doc", "README.md", DERIVED, "measured"),
        Observation("a_true_flag", True, DERIVED, "boolean, the type that bit"),
        Observation("a_false_flag", False, DERIVED, "and its other value"),
        Observation("a_number", 7, DERIVED, "integer"),
        Observation("a_list", ["one", "two"], DERIVED, "list of strings"),
        Observation("a_string", "plain words", DERIVED, "unlisted string key"),
    ])

    parsed = tomllib.loads(rendered)["extant"]
    assert parsed["a_true_flag"] is True, rendered
    assert parsed["a_false_flag"] is False, rendered
    assert parsed["a_number"] == 7, rendered
    assert parsed["a_list"] == ["one", "two"], rendered
    assert parsed["a_string"] == "plain words", rendered


def test_the_installer_asserts_release_claims_are_local() -> None:
    """Installing extant INTO a repository is the assertion the setting wants.

    `release_claims_name_our_tags` is off by default because a version in prose
    can name a package rather than a tag - wrong 19 times in 26 across 15
    projects. None of that applies to a project checking its OWN document, and
    the installer is the one place that knows which case it is in.
    """
    import sys

    sys.path.insert(0, str(SKILL_ROOT))
    from detect import DERIVED, Observation
    from install import render_config

    rendered = render_config([
        Observation("primary_doc", "README.md", DERIVED, "measured"),
        Observation("release_claims_name_our_tags", True, DERIVED, "own repo"),
    ])
    assert tomllib.loads(rendered)["extant"]["release_claims_name_our_tags"] is True


def test_the_installer_emits_a_merge_claim_that_names_its_own_ref(tmp_path) -> None:
    """The installed config OVERRIDES the default, so the collector supporting
    two trunks is not enough on its own.

    This regressed once already: the rule learned to check a claim against the
    branch the claim names, and every freshly installed project kept the old
    single-trunk behaviour because the installer went on writing `{trunk}` into
    `.extant.toml`.

    Found again by a mutation campaign, as a SURVIVOR - the gitflow scenario
    catches it, and nothing in the unit suite did, so a campaign that runs only
    pytest reported "no test noticed". Both statements were true.
    """
    import subprocess
    import sys

    sys.path.insert(0, str(SKILL_ROOT))
    from install import observe

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    doc = repo / "STATUS.md"
    doc.write_text(
        "# Status\n\n## Phase 1 - x (done, 2026-01-01)\n\n"
        "Merged to `develop` at `abc1234`.\n"
        "Merged into `main` at `def5678`.\n",
        encoding="utf-8")

    obs, _info = observe(repo, doc)
    claim = next((o for o in obs if o.key == "merge_claim" and o.value), None)
    assert claim is not None, "the installer derived no merge_claim at all"

    import re
    # IGNORECASE, because that is how the collector compiles it.
    pattern = re.compile(str(claim.value), re.IGNORECASE)
    assert pattern.groups >= 1, (
        f"a one-group pattern means the target is hard-coded: {claim.value!r}"
    )
    # The point of the two-group form: the REF is captured, so a claim about
    # `develop` is checked against `develop` rather than against a trunk.
    found = pattern.findall("Merged to `develop` at `abc1234`.")
    assert found and "develop" in str(found[0]), (
        f"the pattern did not capture the ref the claim names: {claim.value!r}"
    )
    # And the commit may be written BARE, as the default allows since 0.16.1.
    # The installed config overrides the default, so a narrow pattern here
    # silently undoes that fix for every freshly installed project - which is
    # exactly how the single-trunk regression happened, one release earlier.
    bare = pattern.findall("Merged into main at 6ff1f4ac and shipped.")
    assert bare, (
        f"the installer's pattern still demands backticks round the commit, "
        f"so an installed project misses `merged into main at 6ff1f4ac`: "
        f"{claim.value!r}"
    )


def test_a_preset_consistency_check_needs_its_files_to_exist(tmp_path) -> None:
    """A check naming an absent file reports a finding on the first run, which
    teaches the reader that this tool complains about nothing.

    Also a mutation SURVIVOR: covered by a scenario, uncovered by the unit
    suite.
    """
    import sys

    sys.path.insert(0, str(SKILL_ROOT))
    from install import apply_preset

    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    # A python preset wants pyproject.toml; give the repo neither that nor any
    # other file its consistency check names.
    (repo / "README.md").write_text("# R\n", encoding="utf-8")

    obs, _notes = apply_preset("python", [], repo)
    emitted = [o for o in obs if o.key == "consistency" and o.value]
    for o in emitted:
        for _check, sources in dict(o.value).items():   # type: ignore[arg-type]
            for path in sources:
                assert (repo / path).is_file(), (
                    f"emitted a consistency check naming {path!r}, which this "
                    f"repository does not have"
                )

    # THE DENOMINATOR. Without this the test above passes on a preset that
    # emits no consistency check at all, for any reason - which is exactly
    # what it did: `apply_preset` returned zero of them, the loop never ran,
    # and the mutation survived a test written to catch it.
    (repo / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## 1.0.0\n", encoding="utf-8")
    obs, _notes = apply_preset("python", [], repo)
    present = [o for o in obs if o.key == "consistency" and o.value]
    assert present, (
        "with both files present and both patterns matching, the preset must "
        "emit its consistency check - otherwise the assertion above is vacuous"
    )
