"""`--wide-docs`: the document set the installer offers to check.

Measured across the 50-repository benchmark, the gate `install.py` writes
unaided covers 12 findings of the 4,429 the survey sees in ordinary documents,
and 40 of the 45 repositories it agreed to configure would exit 0 forever. That
is a validator teaching its adopters it has nothing to say, and the cause is
document SELECTION rather than the rules.

Two measurements bound every test here, and both are counter-intuitive enough
that nothing but a test will keep them:

  - "just add the root" is WORSE than doing nothing - 0.081 findings per pinned
    path against the status quo's 0.106 - because 52 of its 73 findings are
    root CHANGELOG.md. The `ordinary` restriction is load-bearing, not a
    refinement, which is why the refusal has its own test below.
  - depth 4 is a cliff, not a slope: 16 more findings for 2,220 more pinned
    paths. The boundary test is the only thing pinning the 3.

The installer runs as a SUBPROCESS here for the reason `test_install_presets`
gives for its own: the exit code and the file it leaves behind are the
contract, and a test that calls internals can pass while the command refuses to
run.
"""
from __future__ import annotations

import pytest

import shutil
import subprocess
import sys
try:
    import tomllib
except ModuleNotFoundError:      # Python < 3.11, see requirements-dev.txt
    import tomli as tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
INSTALLER = SKILL_ROOT / "install.py"

README = "# Demo\n\nShipped in `deadbeef1234567`.\n"
README_RST = "Demo\n====\n\nShipped in ``deadbeef1234567``.\n"


def run_installer(repo: Path, *args: str,
                  installer: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(installer or INSTALLER), "--repo", str(repo), *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def make_repo(tmp_path: Path, **files: str) -> Path:
    """A git repo containing exactly `files`. `__` in a name is a directory
    separator, so `docs__a__b__c.md` is `docs/a/b/c.md`."""
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
    """The effective settings, merged the way the loader merges them."""
    with open(repo / ".extant.toml", "rb") as fh:
        data = tomllib.load(fh)
    nested = data.get("extant", {})
    top = {k: v for k, v in data.items() if k != "extant"}
    return {**top, **nested}


# --- what gets enumerated ----------------------------------------------------


def test_depth_three_is_included_and_depth_four_is_not(tmp_path) -> None:
    """The measured cliff, and the only thing that pins it.

    obra/superpowers keeps 29 of its 36 findings at depth 3, under
    `docs/superpowers/plans/` and `docs/superpowers/specs/`, so a one-level
    policy looks straight past the population this tool is for. Depth 4 buys 16
    further findings for 2,220 further pinned paths, because `dead-md-link`'s
    false positives concentrate at depth 4 to 7.
    """
    repo = make_repo(tmp_path, **{
        "README.md": README,
        "docs__one.md": "# One\n",
        "docs__a__two.md": "# Two\n",
        "docs__a__b__three.md": "# Three\n",
        "docs__a__b__c__four.md": "# Four\n",
    })

    assert run_installer(repo, "--wide-docs").returncode == 0

    extras = config_of(repo)["extra_docs"]
    assert "docs/one.md" in extras
    assert "docs/a/two.md" in extras
    assert "docs/a/b/three.md" in extras
    assert "docs/a/b/c/four.md" not in extras, (
        "depth 4 is where dead-md-link's false positives concentrate; the "
        "default depth is 3 and this is the boundary"
    )


def test_an_explicit_depth_moves_the_boundary(tmp_path) -> None:
    """`--wide-docs 4` means four, or the argument is decoration."""
    repo = make_repo(tmp_path, **{
        "README.md": README,
        "docs__a__b__c__four.md": "# Four\n",
    })

    assert run_installer(repo, "--wide-docs", "4").returncode == 0

    assert "docs/a/b/c/four.md" in config_of(repo)["extra_docs"]


def test_only_the_ordinary_stratum_is_enumerated(tmp_path) -> None:
    """The load-bearing restriction, measured rather than assumed.

    Without it the same enumeration yields 0.081 findings per pinned path,
    BELOW the 0.106 the installer manages by configuring one or two files - so
    a version of this feature that skipped the stratum split would be worse
    than not shipping it.
    """
    repo = make_repo(tmp_path, **{
        "README.md": README,
        "docs__guide.md": "# Guide\n",
        "docs__CHANGELOG.md": "# Changes\n",
        "docs__versioned_docs__version-1.0__old.md": "# Old\n",
        "docs__api__generated.md": "# API\n",
        "docs__vendor__theirs.md": "# Theirs\n",
    })

    result = run_installer(repo, "--wide-docs")
    assert result.returncode == 0

    extras = config_of(repo)["extra_docs"]
    assert "docs/guide.md" in extras
    for excluded in ("docs/CHANGELOG.md",
                     "docs/versioned_docs/version-1.0/old.md",
                     "docs/api/generated.md",
                     "docs/vendor/theirs.md"):
        assert excluded not in extras, f"{excluded} is not the ordinary stratum"
    # Counted out loud. An exclusion nobody can see is the shape `strata.py`
    # exists to avoid - a rule going quiet because a tree was hidden reads
    # exactly like a rule that broke.
    assert "excluded as" in result.stdout, result.stdout


def test_zero_documents_writes_no_key_rather_than_an_empty_list(tmp_path) -> None:
    """An empty list is a claim. There is nothing here to claim.

    `extra_docs = []` says the project considered the question and settled on
    none, which is a different statement from the tool having found nothing to
    offer - and the two would be indistinguishable in the written config.
    """
    repo = make_repo(tmp_path, **{"README.md": README, "setup.py": "x = 1\n"})

    result = run_installer(repo, "--wide-docs")
    assert result.returncode == 0

    assert "extra_docs" not in config_of(repo)
    assert "extra_docs = []" not in (repo / ".extant.toml").read_text(encoding="utf-8")


def test_the_primary_document_is_not_also_an_extra(tmp_path) -> None:
    """A document named twice is validated twice and reported twice."""
    repo = make_repo(tmp_path, **{
        "NEXT_SESSION.md": "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n",
        "README.md": README,
    })

    assert run_installer(repo, "--wide-docs").returncode == 0

    config = config_of(repo)
    assert config["primary_doc"] == "NEXT_SESSION.md"
    assert config["extra_docs"] == ["README.md"]


def test_the_archive_is_not_also_an_extra_document(tmp_path) -> None:
    """The archive gets its own pass, so enumerating it gives the file two.

    `gate.py` validates `archive_doc` before it reaches `extra_docs`, and the
    two passes are NOT the same question: the archive runs with
    `in_archive=True` precisely so a retired entry is not judged as a live
    claim. The archive sits beside the primary document - at the root, where
    this enumerates - so a project that keeps one had every finding in it
    printed twice, against a denominator that counted the document once.

    A wrong implementation that de-duplicates only against `primary_doc` puts
    `status-archive.md` in both keys here.
    """
    repo = make_repo(tmp_path, **{
        "NEXT_SESSION.md": "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n",
        "status-archive.md": "# Archive\n\nRetired: [gone](nope/gone.md).\n",
        "README.md": README,
    })

    assert run_installer(repo, "--wide-docs").returncode == 0

    config = config_of(repo)
    assert config["archive_doc"] == "status-archive.md"
    assert "status-archive.md" not in config["extra_docs"], (
        "the archive is validated by its own pass; naming it in extra_docs "
        "reports every finding in it twice"
    )
    assert "README.md" in config["extra_docs"]


def test_wide_docs_appends_to_a_preset_rather_than_replacing_it(tmp_path) -> None:
    """The flag composes: the preset settles the document, the flag widens the
    set. Replacing would silently drop what the preset chose deliberately."""
    repo = make_repo(tmp_path, **{
        "README.md": README,
        "CONTRIBUTING.md": "# Contributing\n\nRun the setup script.\n",
        "docs__guide.md": "# Guide\n",
    })

    assert run_installer(repo, "--preset", "readme", "--wide-docs").returncode == 0

    extras = config_of(repo)["extra_docs"]
    assert "CONTRIBUTING.md" in extras, "the preset's own extra was dropped"
    assert "docs/guide.md" in extras
    assert extras.count("CONTRIBUTING.md") == 1


# --- the nomination, and the precedence around it ----------------------------


def test_wide_docs_alone_nominates_the_root_readme(tmp_path) -> None:
    """The case the flag was extended to cover, and the first one an adopter
    meets.

    `install.py` refuses 35 of the 50 benchmark repositories before any of this
    runs, because no status-shaped document exists. `--wide-docs` on such a
    repository used to enumerate a wide document set and then exit 1 having
    written nothing - the very behaviour it exists to improve, reproduced by
    the new flag.
    """
    repo = make_repo(tmp_path, **{"README.md": README, "docs__guide.md": "# Guide\n"})

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == "README.md"
    # Loud: it is the one place this feature chooses something the user did not.
    assert "nominated by --wide-docs" in result.stdout, result.stdout
    assert "nominated by --wide-docs" in (repo / ".extant.toml").read_text(
        encoding="utf-8"), "the provenance did not reach the config header"


def test_a_root_readme_rst_is_nominated_too(tmp_path) -> None:
    """The suffix, not the heuristic.

    `--wide-docs` nominated on 45 of the 50 benchmark repositories, and all
    five that refused - pytest, django, sphinx, home-assistant, cpython - have
    a root README.rst and no README.md. `rst` is already in the suffix set
    `refs.py`, `strata.py` and `detect.DOC_SUFFIXES` sweep, so those five were
    refused over a spelling of the same file rather than over anything
    measured.
    """
    repo = make_repo(tmp_path, **{"README.rst": README_RST,
                                  "docs__guide.md": "# Guide\n"})

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == "README.rst"
    # The NAME rather than a fixed string: a reader told "README.md" here would
    # have been told the wrong thing about which file gets checked.
    assert "primary_doc <- README.rst (nominated by --wide-docs" in result.stdout, \
        result.stdout
    assert "nominated by --wide-docs" in (repo / ".extant.toml").read_text(
        encoding="utf-8"), "the provenance did not reach the config header"


@pytest.mark.parametrize("suffix", ["md", "markdown", "mdx", "rst"])
def test_every_swept_suffix_can_be_nominated(tmp_path, suffix) -> None:
    """The whole of `detect.DOC_SUFFIXES`, not just the two that motivated it.

    The comment and the refusal message both name four suffixes. Two of them
    had no test, so "the tool reads this suffix already" was an argument the
    suite could not check - and the suffix set is exactly the kind of tuple a
    later change edits in one place.
    """
    repo = make_repo(tmp_path, **{f"README.{suffix}": README,
                                  "docs__guide.md": "# Guide\n"})

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == f"README.{suffix}"


def test_a_lowercase_readme_is_nominated_under_the_name_git_tracks(tmp_path) -> None:
    """The name is READ from git, never constructed, and this is why.

    `(repo / "README.md").is_file()` is case-INSENSITIVE on Windows, so a
    repository tracking `readme.md` matched and the constructed `README.md`
    went into the config - while `--wide-docs` enumeration, which reads git,
    put `readme.md` into `extra_docs`. The same file was then checked twice
    under two spellings and every finding in it counted twice;
    `test_the_primary_document_is_not_also_an_extra` did not catch it because
    its de-duplication is a string comparison. On a case-sensitive filesystem
    the same config instead names a file that does not exist.

    Six corpus repositories track a lowercase root README and no other -
    execa, next.js, openlibrary, Nim, nvda, qmk_firmware - so this is the
    behaviour they get, and it is now the same behaviour on either platform.
    """
    repo = make_repo(tmp_path, **{"readme.md": README, "docs__guide.md": "# Guide\n"})

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    cfg = config_of(repo)
    assert cfg["primary_doc"] == "readme.md", "the name was constructed, not read"
    # The invariant the case mismatch defeated: one file, checked once.
    assert "readme.md" not in cfg.get("extra_docs", [])
    assert "README.md" not in cfg.get("extra_docs", [])


def test_an_untracked_root_readme_is_not_nominated(tmp_path) -> None:
    """A path git has never heard of must not be pinned into a config.

    The filesystem says yes to an untracked README; `.extant.toml` is
    committed, so nominating one writes a `primary_doc` that only exists on
    the machine that ran the installer. Enumeration has always read git -
    `_tracked_paths` - and the nomination now reads the same list, which is
    what keeps the two halves of this feature answering from one source.
    """
    repo = make_repo(tmp_path, **{"docs__guide.md": "# Guide\n"})
    (repo / "README.md").write_text(README, encoding="utf-8")

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 1, result.stdout
    assert not (repo / ".extant.toml").exists()
    assert "--wide-docs found no root README" in result.stdout, result.stdout


def test_readme_md_still_wins_when_both_spellings_exist(tmp_path) -> None:
    """The order is PINNED rather than incidental.

    `detect.DOC_SUFFIXES` states it once and the nomination reads that tuple
    instead of carrying a second list, so this fails if either the tuple is
    reordered or a second order is introduced beside it. Without it the winner
    would be whichever `is_file()` happened to be asked first, which is a
    property of a loop rather than a decision anybody made.
    """
    repo = make_repo(tmp_path, **{"README.md": README, "README.rst": README_RST})

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == "README.md"
    assert "primary_doc <- README.md (nominated by --wide-docs" in result.stdout, \
        result.stdout


def test_an_explicit_doc_outranks_the_nomination(tmp_path) -> None:
    """Weakest last. Wherever the user has spoken, they win."""
    repo = make_repo(tmp_path, **{
        "README.md": README,
        "docs__chosen.md": "# Chosen\n\nShipped in `deadbeef1234567`.\n",
    })

    result = run_installer(repo, "--doc", "docs/chosen.md", "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == "docs/chosen.md"
    assert "nominated by --wide-docs" not in result.stdout


def test_a_preset_document_outranks_the_nomination(tmp_path) -> None:
    """A preset names its document, and the nomination must not claim it.

    Every preset happens to name README.md, so the FILE cannot separate these
    two paths - the attribution can, and it is what a reader of the config sees.
    A nomination that ran unconditionally would relabel a document the preset
    chose deliberately, and the repository below has a detected status document
    as well, so all three of the settled sources are in play at once.
    """
    repo = make_repo(tmp_path, **{
        "NEXT_SESSION.md": "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n",
        "README.md": README,
    })

    result = run_installer(repo, "--preset", "readme", "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == "README.md"
    assert "named by the preset" in result.stdout, result.stdout
    assert "nominated by --wide-docs" not in result.stdout
    assert "nominated by --wide-docs" not in (repo / ".extant.toml").read_text(
        encoding="utf-8")


def test_a_detected_document_outranks_the_nomination(tmp_path) -> None:
    """The third ordering, asserted rather than assumed from the other two."""
    repo = make_repo(tmp_path, **{
        "NEXT_SESSION.md": "# Status\n\n## Phase 1 - x (shipped, 2026-01-01)\n\nNothing.\n",
        "README.md": README,
    })

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 0, result.stdout + result.stderr
    assert config_of(repo)["primary_doc"] == "NEXT_SESSION.md"
    assert "nominated by --wide-docs" not in result.stdout


def test_a_missing_doc_is_still_refused_rather_than_replaced(tmp_path) -> None:
    """Answering a typo with a different file is worse than refusing.

    `--doc docs/typo.md` is a statement about which document matters. If the
    nomination filled in for it, the installer would silently configure the
    README and report success on a command that named something else.
    """
    repo = make_repo(tmp_path, **{"README.md": README})

    result = run_installer(repo, "--doc", "docs/typo.md", "--wide-docs")

    assert result.returncode == 1, result.stdout
    assert not (repo / ".extant.toml").exists()


def test_no_readme_and_no_document_still_refuses_and_names_the_flag(tmp_path) -> None:
    """The existing refusal stands, with one line saying why discovery could
    not help. A flag that appears to do nothing is worse than one that says
    what it looked for."""
    repo = make_repo(tmp_path, **{"docs__guide.md": "# Guide\n",
                                  "GUIDE.rst": "Guide\n=====\n"})

    result = run_installer(repo, "--wide-docs")

    assert result.returncode == 1, result.stdout
    # Names every spelling it looked for, and the root GUIDE.rst is what keeps
    # this a search for a root README rather than for any root document.
    assert "--wide-docs found no root README" in result.stdout, result.stdout
    assert ".rst" in result.stdout, result.stdout


# --- the refusal -------------------------------------------------------------


def test_a_missing_strata_module_refuses_rather_than_degrading(tmp_path) -> None:
    """The load-bearing safety property of the whole feature.

    Unclassified enumeration is not a degraded version of this policy, it is a
    DIFFERENT policy - and the one the measurement rejected, at 0.081 findings
    per pinned path against the 0.106 the installer already manages. A silent
    fallback would therefore ship the worst option under the best option's
    name, and every adopter would see a wider config and a lower yield.

    Asserted on the EXIT CODE as well as the message: a message nobody acts on
    is what an installer prints while writing the file anyway.
    """
    skill = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, skill)
    (skill / "payload" / "extant" / "strata.py").unlink()
    repo = make_repo(tmp_path, **{"README.md": README, "docs__guide.md": "# Guide\n"})

    result = run_installer(repo, "--wide-docs", installer=skill / "install.py")

    assert result.returncode != 0, result.stdout
    assert "strata" in result.stdout, result.stdout
    assert "REFUSED" in result.stdout, result.stdout
    assert not (repo / ".extant.toml").exists(), (
        "a refusal that still writes the config has refused nothing"
    )


def test_an_empty_index_refuses_rather_than_enumerating_nothing(tmp_path) -> None:
    """`refs.py` records this one twice over: an empty index reads exactly like
    a repository with nothing to check.

    `git ls-files` reports nothing on a repository whose checkout did not
    complete - a sparse checkout, a partial clone, or on Windows one whose paths
    exceed MAX_PATH. Enumerating zero documents there and carrying on writes a
    config that says this project has no documentation, which is a clean sweep
    on a repository nobody looked at. It is the worst shape available and this
    project has shipped it twice in other rules.
    """
    repo = tmp_path / "bare"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo,
                   capture_output=True, check=True)

    result = run_installer(repo, "--wide-docs")

    assert result.returncode != 0, result.stdout
    assert "REFUSED" in result.stdout, result.stdout
    assert "ls-files" in result.stdout, result.stdout
    assert not (repo / ".extant.toml").exists()


def test_a_git_quoted_path_is_left_out_and_counted(tmp_path) -> None:
    """A quoted spelling names no file on disk, so pinning it manufactures a
    finding.

    With `core.quotePath` on - the default - git renders a path holding unusual
    bytes as `"caf\\303\\251.md"`, quotes and octal escapes included. Writing
    that into `extra_docs` gives `gate.py` a path it cannot open, and an absent
    entry is a `missing-document` finding by deliberate design: the installer
    would have invented the very thing it exists to detect.

    Counted rather than dropped silently, because a document that vanishes from
    the enumeration with no explanation is the other way to be wrong here.
    """
    repo = make_repo(tmp_path, **{"README.md": README, "docs__guide.md": "# Guide\n"})
    # Built rather than written out: the ASCII rule covers string literals in
    # every file here, tests included, and a filename is the one place a
    # non-ASCII character is the POINT rather than a slip.
    odd = repo / "docs" / ("caf" + chr(0xE9) + ".md")
    with open(odd, "w", encoding="utf-8", newline="") as fh:
        fh.write("# Cafe\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-m", "odd"], cwd=repo, capture_output=True, check=True)
    listed = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True,
                            text=True, check=True).stdout
    if '"' not in listed:                    # git configured not to quote
        return

    result = run_installer(repo, "--wide-docs")
    assert result.returncode == 0, result.stdout

    extras = config_of(repo)["extra_docs"]
    assert "docs/guide.md" in extras
    assert not any('"' in e or "\\3" in e for e in extras), extras
    assert "git quoted" in result.stdout, result.stdout


def test_no_documents_at_all_is_an_answer_rather_than_a_refusal(tmp_path) -> None:
    """A repository whose documentation is all generated is a real result.

    Distinct from the de-duplicated-to-empty case above: there the enumeration
    found something and it was already configured, here it found nothing. Both
    must write no `extra_docs` key, and NEITHER may be reported as a refusal -
    collapsing "could not answer" into "answered none" is what turns every
    failure into a repository that reads as clean.
    """
    repo = make_repo(tmp_path, **{"STATUS.txt": "status\n", "a.py": "x = 1\n"})

    result = run_installer(repo, "--doc", "STATUS.txt", "--wide-docs")

    assert result.returncode == 0, result.stdout
    assert "0 documents" in result.stdout, result.stdout
    assert "REFUSED" not in result.stdout, result.stdout
    assert "extra_docs" not in config_of(repo)


def test_a_negative_depth_is_refused(tmp_path) -> None:
    """Not a depth. Silently reading it as root-only would answer a mistyped
    number with a policy nobody asked for."""
    repo = make_repo(tmp_path, **{"README.md": README, "docs__guide.md": "# Guide\n"})

    result = run_installer(repo, "--wide-docs", "-1")

    assert result.returncode == 1, result.stdout
    assert not (repo / ".extant.toml").exists()


# --- what the written config looks like --------------------------------------


def test_a_long_extra_docs_list_is_written_one_path_per_line(tmp_path) -> None:
    """An unreviewable config is how a wide extra_docs becomes a place nobody
    looks.

    This branch was written for `["CONTRIBUTING.md"]` and the measured policy
    pins 3,305 paths across 50 repositories - hundreds in a single one. Rendered
    on one line that is a multi-kilobyte string in a file whose entire purpose
    is to be read before it is trusted, which is the objection `report.py`
    makes about the baseline.
    """
    repo = make_repo(tmp_path, **{
        "README.md": README,
        **{f"docs__page{n}.md": f"# Page {n}\n" for n in range(6)},
    })

    assert run_installer(repo, "--wide-docs").returncode == 0

    body = (repo / ".extant.toml").read_text(encoding="utf-8")
    assert "extra_docs = [\n" in body, body
    assert '  "docs/page0.md",\n' in body, body
    # Still has to parse, which is the assertion an installer earns nothing
    # without: a config the tool refuses to read silences every rule at once.
    assert len(config_of(repo)["extra_docs"]) == 6
