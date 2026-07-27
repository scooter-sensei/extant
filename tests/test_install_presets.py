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
import tomllib
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
        path.write_text(body, encoding="utf-8", newline="")
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


@pytest.mark.parametrize("preset", ["readme", "node", "python", "rust"])
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
