"""Git LFS storage, and the game-engine presets.

Every fact pinned here was measured on a real Unity project (BossRoom, 2704
files, 479 paths under an LFS filter) and a real shipped Godot game (Thrive,
7802 files, 1202 under a filter), not derived from what those engines are
supposed to look like. The measurement contradicted the design three times and
each correction has a test below.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

POINTER = ("version https://git-lfs.github.com/spec/v1\n"
           "oid sha256:" + "a" * 64 + "\nsize 4096\n")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def commit_raw(repo: Path, rel: str, content: str, message: str) -> None:
    """Commit a file BYPASSING the LFS clean filter.

    Necessary, and the reason is the bug itself. Where git-lfs is installed,
    an ordinary `git add` silently converts the file to a pointer, so a test
    that wrote the file normally would commit a correct pointer and prove
    nothing - which is exactly what the first version of these tests did. This
    reproduces the real cause: a commit made from a clone whose LFS filter was
    never installed. `--no-filters` is precisely that condition.
    """
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    sha = subprocess.run(["git", "hash-object", "-w", "--no-filters", rel],
                         cwd=repo, capture_output=True, text=True,
                         check=True).stdout.strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                    f"100644,{sha},{rel}"], cwd=repo, capture_output=True,
                   check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo,
                   capture_output=True, check=True)


@pytest.fixture()
def lfs_repo(git_repo):
    """A repo whose .gitattributes routes binaries to LFS.

    Pointer files are written by hand rather than through the LFS binary,
    because the rule's whole claim is that it needs neither the binary nor the
    network: it reads the pointer header. A fixture requiring git-lfs would be
    testing something the rule does not do.
    """
    repo, commit = git_repo
    (repo / ".gitattributes").write_text(
        "*.png filter=lfs diff=lfs merge=lfs -text\n"
        "*.wav filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    commit(".gitattributes", (repo / ".gitattributes").read_text(encoding="utf-8"),
           "chore: track binaries in LFS")
    return repo, commit


def test_a_binary_stored_raw_under_an_lfs_filter_is_reported(lfs_repo) -> None:
    """The bug this rule exists for, and it is silent everywhere else.

    A binary committed from a clone with no LFS filter installed. Git accepts
    it, the engine loads it, and the repository carries a real binary in its
    history forever. A wrong implementation that only checks whether the file
    exists, or that trusts `.gitattributes` to have been applied, says nothing.
    """
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, _commit = lfs_repo
    commit_raw(repo, "Assets/raw.wav", "RIFF" + "wavdata" * 600,
               "sfx: added from a clone without LFS")

    findings = rule_lfs.check(hc.context(repo), "")

    assert [f.kind for f in findings] == ["raw-lfs-blob"], findings
    assert "Assets/raw.wav" in findings[0].detail


def test_a_proper_pointer_is_silent(lfs_repo) -> None:
    """The direction that stops the rule flagging every asset in the project."""
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, commit = lfs_repo
    commit("Assets/good.png", POINTER, "art: stored through LFS")

    assert rule_lfs.check(hc.context(repo), "") == []


def test_a_file_outside_every_lfs_pattern_is_ignored(lfs_repo) -> None:
    """`.gitattributes` claims nothing about a .cs file, so neither does this."""
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, commit = lfs_repo
    commit("Assets/Script.cs", "class X {}\n", "feat: a script")

    assert rule_lfs.check(hc.context(repo), "") == []


def test_a_repository_without_lfs_is_silent_and_cheap(git_repo) -> None:
    """Most projects do not use LFS and must pay nothing.

    Measured at 0 ms against this repository, against 262 ms for a 7802-file
    Godot project that does use it. The gate is one file read.
    """
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")

    assert rule_lfs.check(hc.context(repo), "") == []
    assert rule_lfs._lfs_governed(hc.context(repo)) == []


def test_the_denominator_counts_every_governed_path(lfs_repo) -> None:
    """The failure that made this rule look perfect while it was 75% blind.

    Paths were piped to `git check-attr` with text=True, so Windows appended a
    carriage return to each one, git treated it as a literal path character and
    answered `unspecified` for all but the LAST path. The survey reported 1 of
    4 governed files and happened to include the one real problem, so the rule
    passed its own test. Had the bad file sorted first it would have printed a
    clean result over an examined count of zero.
    """
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, commit = lfs_repo
    for name in ("a.png", "b.png", "c.wav", "d.wav"):
        commit(f"Assets/{name}", POINTER, f"art: {name}")

    governed = {path for path, _sha in rule_lfs._lfs_governed(hc.context(repo))}

    assert governed == {"Assets/a.png", "Assets/b.png",
                        "Assets/c.wav", "Assets/d.wav"}, governed


def test_a_path_with_a_space_is_still_examined(lfs_repo) -> None:
    """Git QUOTES paths containing spaces or non-ASCII unless asked for `-z`,
    and game projects are full of both. A line-and-colon parse skips exactly
    those assets, silently."""
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, _commit = lfs_repo
    commit_raw(repo, "Assets/Boss Room/hero art.png", "RAWBYTES" * 200,
               "art: spaced path")

    governed = {path for path, _sha in rule_lfs._lfs_governed(hc.context(repo))}
    assert "Assets/Boss Room/hero art.png" in governed, governed
    assert [f.kind for f in rule_lfs.check(hc.context(repo), "")] == ["raw-lfs-blob"]


def test_a_large_raw_binary_is_judged_without_reading_it(lfs_repo) -> None:
    """A blob larger than any pointer is settled by its size alone. That is
    what keeps the rule affordable on a repository of real assets, so it must
    still be REPORTED rather than skipped as unreadable."""
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, _commit = lfs_repo
    commit_raw(repo, "Assets/big.png", "X" * 40000, "art: a real binary, raw")

    findings = rule_lfs.check(hc.context(repo), "")

    assert [f.kind for f in findings] == ["raw-lfs-blob"], findings
    assert "40000-byte" in findings[0].detail


def test_the_rule_reads_the_committed_tree_not_the_index(lfs_repo) -> None:
    """Reading `git ls-files` made the rule examine ZERO paths on a repository
    whose checkout had not completed, while .gitattributes sat there declaring
    47 LFS patterns. It runs after a commit, so the committed tree is the thing
    being judged."""
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, commit = lfs_repo
    commit("Assets/tracked.png", POINTER, "art: committed")
    subprocess.run(["git", "rm", "--cached", "-q", "-r", "."], cwd=repo,
                   capture_output=True, check=True)

    assert not git(repo, "ls-files").strip(), "the index should now be empty"
    assert {p for p, _s in rule_lfs._lfs_governed(hc.context(repo))} == {"Assets/tracked.png"}


# --------------------------------------------------------------- the presets
def test_the_engine_presets_do_not_widen_path_pointer() -> None:
    """The plan was to add asset and source extensions to `path_pointer`.

    Measured against a real Unity project and a real Godot one, that rule
    examines ZERO references in either: game documentation writes paths as
    markdown links, and `path_pointer` requires a backticked path after an
    operative marker. Widening it would have been a no-op that looked like a
    feature, so neither preset touches it. This test exists so that reasoning
    is not quietly undone later.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                           / "plugin" / "skills" / "extant"))
    import install

    for name in ("unity", "godot"):
        preset = install.PRESETS[name]
        assert "path_pointer" not in preset, (
            f"the {name} preset sets path_pointer; measured on real projects "
            "that rule examines nothing, so widening it changes no outcome"
        )


def test_the_engine_presets_check_the_version_files_that_really_hold_it() -> None:
    """Unity states its editor version in a shields.io badge; Godot's README
    states no version at all, so its check reads the setup document. Keyed on
    the wrong file, either check examines nothing forever while exiting 0."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                           / "plugin" / "skills" / "extant"))
    import install

    unity = install.PRESETS["unity"]["consistency"]["unity_version"]
    assert "ProjectSettings/ProjectVersion.txt" in unity
    assert "README.md" in unity

    godot = install.PRESETS["godot"]["consistency"]["godot_version"]
    assert "project.godot" in godot
    assert "README.md" not in godot, (
        "Thrive's README states no Godot version; keyed there this examines nothing"
    )
    assert "doc/setup_instructions.md" in godot


@pytest.mark.parametrize(
    "preset,path,text,expected",
    [
        ("unity", "README.md",
         "[![UnityVersion](https://img.shields.io/badge/Unity%20Version:-6000.0.52f1"
         "%20LTS-57b9d3.svg)](https://unity.com)", "6000.0.52f1"),
        ("unity", "ProjectSettings/ProjectVersion.txt",
         "m_EditorVersion: 6000.0.52f1\nm_EditorVersionWithRevision: 6000.0.52f1 (9e40)\n",
         "6000.0.52f1"),
        ("godot", "doc/setup_instructions.md",
         "The currently used Godot version is __4.7 .NET__. The regular version "
         "will not work.", "4.7"),
        ("godot", "project.godot",
         'config_version=5\nconfig/features=PackedStringArray("4.7", "C#")\n', "4.7"),
    ],
)
def test_each_preset_pattern_matches_the_real_string(preset, path, text, expected) -> None:
    """Verbatim strings from the two projects. A consistency block whose
    patterns match nothing reports agreement vacuously, which is worse than
    having no block at all - so each side is pinned to a real capture."""
    import re
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                           / "plugin" / "skills" / "extant"))
    import install

    checks = install.PRESETS[preset]["consistency"]
    pattern = next(sources[path] for sources in checks.values() if path in sources)

    match = re.search(pattern, text, re.MULTILINE)

    assert match, f"{preset}/{path} pattern matched nothing in the real string"
    assert match.group(1) == expected


def test_an_empty_file_under_a_filter_is_not_a_violation(git_repo) -> None:
    """git-lfs passes zero bytes through rather than writing a pointer.

    There is nothing to store, so a 0-byte blob under an LFS filter is LFS
    behaving correctly. Verified rather than assumed: committing an empty file
    and a real one under the same filter yields a 0-byte blob and a 126-byte
    pointer.

    Measured on o3de/o3de, which declares 123 filters over 2,948 governed
    files: 44 of its 45 findings were empty test fixtures, and the only true
    one was an asset planted to prove the rule still fires.
    """
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, commit = git_repo
    commit(".gitattributes", "*.bnk filter=lfs diff=lfs merge=lfs -text\n", "chore: lfs")

    empty = subprocess.run(["git", "hash-object", "-w", "--no-filters", "--stdin"],
                           cwd=repo, input=b"", capture_output=True,
                           check=True).stdout.decode().strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                    f"100644,{empty},sounds/silent.bnk"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-qm", "empty"], cwd=repo, check=True, capture_output=True)

    assert rule_lfs.check(hc.context(repo), "") == [], (
        "an empty file under an LFS filter is correct storage, not a violation"
    )


def test_a_non_empty_raw_blob_is_still_a_violation(git_repo) -> None:
    """The other half. Skipping by size must not become skipping the rule."""
    from extant import session as hc
    from extant.rules import lfs as rule_lfs
    repo, commit = git_repo
    commit(".gitattributes", "*.bnk filter=lfs diff=lfs merge=lfs -text\n", "chore: lfs")

    blob = subprocess.run(["git", "hash-object", "-w", "--no-filters", "--stdin"],
                          cwd=repo, input=b"x" * 2000, capture_output=True,
                          check=True).stdout.decode().strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo",
                    f"100644,{blob},sounds/loud.bnk"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T",
                    "commit", "-qm", "loud"], cwd=repo, check=True, capture_output=True)

    findings = rule_lfs.check(hc.context(repo), "")

    assert [f.kind for f in findings] == ["raw-lfs-blob"], findings
    assert "sounds/loud.bnk" in findings[0].detail
