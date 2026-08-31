"""The commit-map a history rewrite leaves behind, read to explain a dead SHA.

Measured on a real agent-written project 2026-08-30, and the measurement is
why this exists. That repository carried 12 distinct dead SHAs. Asked the
obvious way - `rev-parse`, `cat-file`, every reflog, `fsck --unreachable` -
all 12 answered "never present anywhere in this clone", which reads as
"invented". All 12 are in `.git/filter-repo/commit-map`, a 623-entry file git
wrote during a trailer purge and left in place:

    8633e79 -> 99575ef   a515dde -> 8470d71   1317dfc -> 02746fd  ...

So the dominant cause of this project's largest finding class is a history
rewrite, the answer is on disk, and nothing looked. `--sha-map` could already
repair it, given the path by hand, and is named exactly once in the whole
repository - in a release note.

What is pinned here is the reporting half only. Finding the map does NOT
rewrite anything: `--sha-map` remains the explicit opt-in for that, because a
validation run that edits documents on its own is the authoring this tool
refuses.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

ZERO = "0" * 40


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def write_map(gitdir: Path, pairs: list[tuple[str, str]]) -> Path:
    """A commit-map in the spelling git-filter-repo writes: old, space, new."""
    target = gitdir / "filter-repo" / "commit-map"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("old                                      new\n")
        for old, new in pairs:
            fh.write(f"{old} {new}\n")
    return target


def findings(repo: Path, text: str) -> list:
    from extant import session as hc
    with hc.run_scope():
        return hc.validate(repo, text, has_entries=False)


# --- finding the shared git directory -----------------------------------------

def test_common_git_dir_of_a_plain_checkout_is_its_own_dot_git(git_repo) -> None:
    from extant.git import common_git_dir
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    assert common_git_dir(repo) == repo / ".git"


def test_common_git_dir_of_a_linked_worktree_is_the_shared_one(git_repo) -> None:
    """A worktree's `.git` is a FILE, and the map lives in the ORIGINAL clone.

    This is the same walk `is_shallow` already does, and it is here rather
    than only there because a rewrite map found relative to the worktree's own
    git directory would be found in no worktree at all - which reads exactly
    like a repository that was never rewritten.
    """
    from extant.git import common_git_dir
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    linked = repo.parent / "linked"
    git(repo, "worktree", "add", str(linked), "-b", "side")
    assert (linked / ".git").is_file(), "fixture did not produce a linked worktree"
    assert common_git_dir(linked) == common_git_dir(repo)


def test_common_git_dir_is_none_when_there_is_no_git_directory(tmp_path) -> None:
    from extant.git import common_git_dir
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert common_git_dir(plain) is None


def test_finding_the_map_costs_no_git_subprocess(git_repo, monkeypatch) -> None:
    """The spawn budget has no spare margin, so this may not spend one.

    Resolved from the filesystem for the same reason `is_shallow` is: it is a
    stat, and a `rev-parse --git-common-dir` that failed would have to be
    interpreted.
    """
    from extant import git as gitmod
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    write_map(repo / ".git", [("a" * 40, "b" * 40)])

    def refuse(*args, **kwargs):
        raise AssertionError(f"spawned a subprocess: {args}")

    monkeypatch.setattr(subprocess, "run", refuse)
    assert gitmod.rewrite_map_path(repo) is not None


# --- what the finding says ----------------------------------------------------

def test_a_dead_sha_the_map_knows_names_its_replacement(git_repo) -> None:
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    dead = "abc1234"
    write_map(repo / ".git", [(dead + "0" * 33, live)])
    found = findings(repo, f"Merged the fix in `{dead}`.\n")
    assert [f.kind for f in found] == ["dead-sha"]
    assert live[:7] in found[0].render(), found[0].render()
    assert "rewrite map" in found[0].render()


def test_the_detail_is_unchanged_so_recorded_baselines_still_match(git_repo) -> None:
    """The repair rides OUTSIDE the fingerprint, exactly as `subject` does.

    `report.fingerprint` hashes (path, kind, detail). Folding the repair into
    `detail` would silently invalidate every `dead-sha` entry in every baseline
    already recorded, and a baseline that stops matching does not fail loudly -
    it re-reports findings a project had agreed to leave alone, which is how a
    reader learns to ignore the output.
    """
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    dead = "abc1234"
    without = findings(repo, f"Merged the fix in `{dead}`.\n")
    write_map(repo / ".git", [(dead + "0" * 33, live)])
    with_map = findings(repo, f"Merged the fix in `{dead}`.\n")
    assert without[0].detail == with_map[0].detail
    assert with_map[0].repair is not None
    assert with_map[0].render() != without[0].render()


def test_no_map_leaves_the_finding_exactly_as_it_was(git_repo) -> None:
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    found = findings(repo, "Merged the fix in `abc1234`.\n")
    assert [f.kind for f in found] == ["dead-sha"]
    assert found[0].repair is None
    assert found[0].render() == "line 1: [dead-sha] `abc1234` does not resolve in this repo"


def test_a_bare_dead_sha_is_repaired_too(git_repo) -> None:
    """Both halves, or the class is only half fixable.

    `translate_shas` learned bare tokens for this reason and records it as
    EX-8: reporting a kind of reference the repair cannot reach is how a
    finding becomes permanent. The same argument applies to the hint.
    """
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    dead = "abc1234"
    write_map(repo / ".git", [(dead + "0" * 33, live)])
    found = findings(repo, f"Fixed in {dead} last week.\n")
    assert [f.kind for f in found] == ["bare-dead-sha"]
    assert live[:7] in found[0].render()


def test_an_ambiguous_prefix_offers_no_replacement(git_repo) -> None:
    """Two old SHAs sharing the prefix: say nothing rather than pick one.

    `_translated_value` already refuses to resolve this, and the reason
    transfers unchanged - a wrong SHA is worse than a dead one, because the
    dead one is visibly broken and the wrong one reads as correct.
    """
    repo, commit = git_repo
    first = commit("a.py", "a = 1\n", "feat: a").strip()
    second = commit("b.py", "b = 2\n", "feat: b").strip()
    write_map(repo / ".git", [("abc1234" + "0" * 33, first),
                              ("abc1234" + "1" * 33, second)])
    found = findings(repo, "Merged the fix in `abc1234`.\n")
    assert [f.kind for f in found] == ["dead-sha"]
    assert found[0].repair is None, found[0].render()


def test_a_commit_the_rewrite_dropped_is_named_as_removed(git_repo) -> None:
    """filter-repo maps a dropped commit to forty zeroes.

    Reporting that verbatim would offer the reader a SHA to paste that names
    nothing. Not exercised by the repository this was measured on - its purge
    dropped no commits - so the behaviour is pinned here rather than observed.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    write_map(repo / ".git", [("abc1234" + "0" * 33, ZERO)])
    found = findings(repo, "Merged the fix in `abc1234`.\n")
    assert found[0].repair is not None
    assert "removed" in found[0].repair
    assert "0000" not in found[0].repair


def test_a_map_that_cannot_be_read_says_so_in_the_finding(git_repo) -> None:
    """A map present and unreadable must not read as a map absent.

    The degraded path names itself, which is the only shape of broad catch
    this project allows. Silently treating it as "no rewrite here" is the
    failure mode every other cache in this package is written to avoid.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    target = write_map(repo / ".git", [("abc1234" + "0" * 33, "b" * 40)])
    target.write_bytes(b"\xff\xfe not utf-8 \x00\x01")
    found = findings(repo, "Merged the fix in `abc1234`.\n")
    assert found[0].repair is not None, "an unreadable map was passed over in silence"
    assert "could not" in found[0].repair.lower()


def test_the_map_is_read_once_per_run_not_once_per_document(git_repo,
                                                            monkeypatch) -> None:
    """Its lifetime is the run's, like every other answer the disk gave.

    A sweep validates every tracked document in one run scope, and re-reading
    a map with one line per commit once per file is the cost `--sweep` already
    took ownership of the directory listings to avoid.
    """
    from extant import commits, session as hc
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    write_map(repo / ".git", [("abc1234" + "0" * 33, live)])
    reads = []
    real = commits.load_sha_map

    def counting(path):
        reads.append(path)
        return real(path)

    monkeypatch.setattr(commits, "load_sha_map", counting)
    with hc.run_scope():
        for _ in range(3):
            hc.validate(repo, "Merged the fix in `abc1234`.\n", has_entries=False)
    assert len(reads) == 1, f"read the map {len(reads)} times in one run"


def test_the_map_is_not_read_when_no_sha_is_dead(git_repo, monkeypatch) -> None:
    """One line per commit is a real file on a real repository.

    Nothing needs explaining when nothing is dead, so a clean document pays
    nothing. This is what makes the size of the map somebody else's problem
    only on runs that already have findings.
    """
    from extant import commits, session as hc
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    write_map(repo / ".git", [("abc1234" + "0" * 33, live)])
    reads = []
    monkeypatch.setattr(commits, "load_sha_map",
                        lambda path: reads.append(path) or {})
    with hc.run_scope():
        hc.validate(repo, f"Merged the fix in `{live[:7]}`.\n", has_entries=False)
    assert reads == [], "read the rewrite map for a document with no dead SHA"


def test_every_format_a_person_reads_carries_the_repair(git_repo) -> None:
    """When one output misrepresents something, the siblings are where to look.

    `format_github`'s own docstring records that lesson: a severity fix landed
    in SARIF and was missed in the annotations for one commit. The same shape
    applies here - a repair visible only in the text output would be absent
    from the pull request, which is the place a reviewer actually reads.

    And the fingerprints must NOT move with it, in either format, or the
    baseline stops matching in exactly the formats a CI pipeline uses.
    """
    from extant.finding import Located
    from extant.report import fingerprint, format_github, format_sarif
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    dead = "abc1234"
    write_map(repo / ".git", [(dead + "0" * 33, live)])
    found = findings(repo, f"Merged the fix in `{dead}`.\n")
    item = Located("STATUS.md", found[0], True)

    assert live[:7] in format_github([item])[0], "the annotation dropped it"
    assert live[:7] in format_sarif([item], repo), "the SARIF message dropped it"
    assert fingerprint("STATUS.md", found[0].kind, found[0].detail) in \
        format_sarif([item], repo), "the SARIF fingerprint moved with the repair"


def test_discovery_never_rewrites_the_document(git_repo, tmp_path) -> None:
    """Reporting only. `--sha-map` stays the explicit opt-in for the repair.

    The whole authority of this tool is that it checks claims and never writes
    them, and a validation run that quietly edited prose because it found a
    file in `.git` would be the largest possible violation of it.
    """
    repo, commit = git_repo
    live = commit("a.py", "a = 1\n", "feat: a").strip()
    write_map(repo / ".git", [("abc1234" + "0" * 33, live)])
    doc = repo / "STATUS.md"
    body = "Merged the fix in `abc1234`.\n"
    with open(doc, "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    subprocess.run([sys.executable, str(PAYLOAD / "extant_collect.py"),
                    "--validate", str(doc), "--repo", str(repo)],
                   capture_output=True, text=True)
    assert doc.read_text(encoding="utf-8") == body
