"""Everything detect.py observes, compared WHOLE, on repositories built to
reach each of its branches.

D7 ran mutmut over the installer side and found 393 of detect.py's 747
mutants surviving the whole suite. Each observer had been asserted on
piecemeal - a key here, a value there - so a mutant that moved the
confidence, the evidence or another branch's output went unseen. These
tests compare the complete Observation lists, and the complete notes
find_wide_documents returns.

Every expected value is derived from the fixture and the observer's stated
rule, not pasted from a run: the release default is the shipped pattern, a
branch count is the names the fixture creates, a stratum count follows
strata.py's patterns. Each fixture says what it is built to reach.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Sequence

import pytest

import detect
from detect import (Observation, detect_branch_pattern, detect_commit_convention,
                    detect_release_tag, detect_trunk, find_documents,
                    find_wide_documents, inspect_document)

RELEASE_DEFAULT = (r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+"
                   r"`?(v?\d+\.\d+(?:[\w.-]*[\w])?)`?")
ANY_SLASHED = r"`([\w.-]+/[^`]+)`"
OFF = "switched off rather than inheriting another project's pattern"


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True, input=stdin).stdout


def _repo(root: Path, branch: str = "main") -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", branch)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")
    return repo


def _commits(repo: Path, subjects: Sequence[str | bytes]) -> None:
    """One empty commit per subject on the current branch, oldest first, in
    ONE git process: the floors below need histories of up to 501 commits,
    and a `git commit` each would be 501 processes. A subject given as bytes
    is written as those bytes, for one that is not UTF-8."""
    branch = _git(repo, "symbolic-ref", "HEAD").strip().encode("ascii")
    stream = []
    for subject in subjects:
        message = subject if isinstance(subject, bytes) else subject.encode("utf-8")
        stream.append(b"commit %s\ncommitter T <t@t> 1700000000 +0000\ndata %d\n%s\n"
                      % (branch, len(message), message))
    subprocess.run(["git", "fast-import", "--quiet"], cwd=repo, input=b"".join(stream),
                   capture_output=True, check=True)


def _refs(repo: Path, *names: str) -> None:
    """Each ref created at HEAD, in one git process."""
    head = _git(repo, "rev-parse", "HEAD").strip()
    subprocess.run(["git", "update-ref", "--stdin"], cwd=repo, capture_output=True,
                   check=True, input="".join(f"create {name} {head}\n" for name in names)
                   .encode("utf-8"))


def _tickets_and_remotes(root: Path) -> Path:
    """Ticket ids in four of ten subjects; slash prefixes and ticket keys in
    branch names, three of each once remote-tracking refs count; origin/HEAD
    naming the trunk; two v-prefixed tags."""
    repo = _repo(root)
    _commits(repo, ["ABC-1 start", "ABC-2 parse", "tidy", "ABC-3 render",
                    "ABC-4 ship", "notes", "more notes", "docs", "readme",
                    "license"])
    _refs(repo, *(f"refs/heads/{b}" for b in ("feature/a", "feature/b",
                                              "ABC-12-login", "ABC-13-logout")),
          *(f"refs/remotes/origin/{r}" for r in ("main", "feature/c", "ABC-14-export")),
          "refs/tags/v1.0.0", "refs/tags/v1.1.0")
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return repo


def _many_prefixes(root: Path) -> Path:
    """Two slash prefixes and two ticket keys, each seen exactly twice - the
    floor, max(2, 11 // 20); a name with two slashes, whose prefix is its
    FIRST component; three trunk candidates; ticket ids in three of ten
    subjects - the other floor, max(3, 10 // 10)."""
    repo = _repo(root)
    _commits(repo, ["ABC-1 a", "ABC-2 b", "ABC-3 c", *["plain"] * 7])
    _refs(repo, *(f"refs/heads/{b}" for b in (
        "develop", "trunk", "feature/a", "feature/b", "fix/c", "fix/d/e",
        "ABC-1-x", "ABC-2-y", "XY-3-z", "XY-4-w")))
    return repo


def _detached_checkout(root: Path) -> Path:
    """HEAD detached, as a pull request's CI checkout leaves it, on a
    repository whose only branch is no trunk name: `git branch` lists the
    detached HEAD as a line of its own."""
    repo = _repo(root, branch="work")
    _commits(repo, ["start"])
    _git(repo, "checkout", "-q", "--detach")
    return repo


def _phases_and_prefixed_tags(root: Path) -> Path:
    """(version Task N) markers in three of five subjects; two tag prefixes
    the default does not cover, beside the two it does (`v`, and none);
    main AND develop locally; flat branch names."""
    repo = _repo(root)
    _commits(repo, ["add parser (1.2 task 1)", "add renderer (1.2 task 2)",
                    "wire cli (1.3 task 1)", "tidy", "docs"])
    _refs(repo, "refs/heads/develop", "refs/heads/foo", "refs/heads/bar",
          "refs/tags/release-1.0", "refs/tags/release-1.1", "refs/tags/v2.0",
          "refs/tags/api@3.0", "refs/tags/4.0")
    return repo


def _conventional_and_bare(root: Path) -> Path:
    """Conventional types in five counts (the evidence lists the top four);
    three bare 'Phase N.N' subjects; a current branch no trunk list names; a
    tag with no version shape."""
    repo = _repo(root, branch="work")
    _commits(repo, ["feat: a"] * 5 + ["fix: b"] * 4 + ["docs: c"] * 3
             + ["chore: d"] * 2 + ["test: e"]
             + ["Phase 1.2 done", "Phase 1.3 done", "Phase 2.0 done"]
             + ["misc", "misc again"])
    _git(repo, "tag", "build-7")
    return repo


def _non_ascii_and_not_utf8(root: Path) -> Path:
    """A trunk that exists locally and alone; a non-ASCII branch prefix,
    which reads back as itself only if git's output is decoded as UTF-8 -
    Windows' locale would not; one subject in latin-1, which is no UTF-8 at
    all and must be replaced, not raised on (AGENTS.md, "Decode at a boundary
    you control"); no grouping key and no conventional type, and one bare
    'Phase N.N', below the floor of three."""
    repo = _repo(root, branch="master")
    _commits(repo, ["start", "Phase 1.2 begun", b"caf\xe9"])
    _refs(repo, "refs/heads/f\u00e9/a", "refs/heads/f\u00e9/b")
    return repo


def _no_history(root: Path) -> Path:
    """No commit, no branch, no tag."""
    return _repo(root)


_HISTORIES: dict[str, tuple[Callable[[Path], Path], list[Observation]]] = {
    "tickets-and-remotes": (_tickets_and_remotes, [
        Observation("release_tag", RELEASE_DEFAULT, "derived",
                    "2 tags, all v-prefixed or bare"),
        Observation("trunk", "main", "derived", "origin/HEAD -> main"),
        Observation("branch_token", "`((?:feature)/[^`]+|(?:ABC)-\\d+[^`]*)`",
                    "derived",
                    "8 branches sampled; slash prefixes: feature/ x3; "
                    "ticket keys: ABC- x3"),
        Observation("phase_task", r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b", "derived",
                    "4/10 subjects carry a ticket id; grouping by ticket"),
    ]),
    "phases-and-prefixed-tags": (_phases_and_prefixed_tags, [
        Observation("release_tag",
                    r"(?:released|shipped|tagged)\s+(?:in|as|at)\s+"
                    r"`?((?:api@|release\-|v|)\d+\.\d+(?:[\w.-]*[\w])?)`?",
                    "derived", "5 tags; also matches api@N.N, release-N.N"),
        Observation("trunk", "main", "guessed",
                    "branch exists locally; also present: develop"),
        Observation("branch_token", ANY_SLASHED, "guessed",
                    "4 branches, no repeated prefix; matching any slashed name"),
        Observation("phase_task", r"\((\d+(?:\.\d+)+[a-z]?)\s+\w+\b", "derived",
                    "3/5 subjects carry a (version Task N) marker"),
    ]),
    "conventional-and-bare": (_conventional_and_bare, [
        Observation("release_tag", RELEASE_DEFAULT, "default",
                    "1 tag, none version-shaped"),
        Observation("trunk", "work", "guessed",
                    "no conventional trunk found; using current branch"),
        Observation("branch_token", ANY_SLASHED, "guessed",
                    "1 branch, no repeated prefix; matching any slashed name"),
        Observation("phase_task", "", "unknown",
                    "no grouping key found in 20 subjects (conventional-commit "
                    "types present: feat: x5, fix: x4, docs: x3, chore: x2); "
                    + OFF),
        Observation("phase_bare", r"\bPhase (\d+\.\d+[a-z]?)", "derived",
                    "3/20 subjects name a bare 'Phase N.N'"),
    ]),
    "many-prefixes": (_many_prefixes, [
        Observation("release_tag", RELEASE_DEFAULT, "default",
                    "no version-shaped tags here"),
        Observation("trunk", "main", "guessed",
                    "branch exists locally; also present: develop, trunk"),
        Observation("branch_token",
                    "`((?:feature|fix)/[^`]+|(?:ABC|XY)-\\d+[^`]*)`", "derived",
                    "11 branches sampled; slash prefixes: feature/ x2, fix/ x2; "
                    "ticket keys: ABC- x2, XY- x2"),
        Observation("phase_task", r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b", "derived",
                    "3/10 subjects carry a ticket id; grouping by ticket"),
    ]),
    "detached-checkout": (_detached_checkout, [
        Observation("release_tag", RELEASE_DEFAULT, "default",
                    "no version-shaped tags here"),
        Observation("trunk", "main", "unknown", "could not determine a trunk branch"),
        Observation("branch_token", ANY_SLASHED, "guessed",
                    "1 branch, no repeated prefix; matching any slashed name"),
        Observation("phase_task", "", "unknown",
                    "no grouping key found in 1 subject; " + OFF),
        Observation("phase_bare", "", "unknown",
                    "0/1 subjects name a bare 'Phase N.N'; " + OFF),
    ]),
    "non-ascii-and-not-utf8": (_non_ascii_and_not_utf8, [
        Observation("release_tag", RELEASE_DEFAULT, "default",
                    "no version-shaped tags here"),
        Observation("trunk", "master", "derived", "branch exists locally"),
        Observation("branch_token", "`((?:f\u00e9)/[^`]+)`", "derived",
                    "3 branches sampled; slash prefixes: f\u00e9/ x2"),
        Observation("phase_task", "", "unknown",
                    "no grouping key found in 3 subjects; " + OFF),
        Observation("phase_bare", "", "unknown",
                    "1/3 subjects name a bare 'Phase N.N'; " + OFF),
    ]),
    "no-history": (_no_history, [
        Observation("release_tag", RELEASE_DEFAULT, "default",
                    "no version-shaped tags here"),
        Observation("trunk", "main", "unknown", "could not determine a trunk branch"),
        Observation("branch_token", None, "default",
                    "no branches found to sample, so the shipped pattern applies"),
        Observation("phase_task", "", "unknown", "no commit history to sample; " + OFF),
        Observation("phase_bare", "", "unknown", "no commit history to sample; " + OFF),
    ]),
}


@pytest.mark.parametrize("name", sorted(_HISTORIES))
def test_every_observation_on_a_history_compared_whole(
        tmp_path: Path, name: str) -> None:
    build, expected = _HISTORIES[name]
    repo = build(tmp_path)
    observed = [detect_release_tag(repo), detect_trunk(repo),
                detect_branch_pattern(repo), *detect_commit_convention(repo)]
    assert observed == expected


# Each grouping key must clear a floor that grows with the sample:
# max(3, n // 20) for the (version Task N) marker and the bare 'Phase N.N',
# max(3, n // 10) for a ticket id. Each case sits ON a boundary, at a count
# where n // 20 and n / 20 (or n // 21) disagree, so rounding the quotient
# either way moves the answer. And the sample stops at COMMIT_SAMPLE.
_PHASEY = r"\((\d+(?:\.\d+)+[a-z]?)\s+\w+\b"


def _subjects(marked: str, count: int, n: int) -> list[str]:
    return [marked] * count + ["plain"] * (n - count)


def _ungrouped(n: int) -> Observation:
    return Observation("phase_task", "", "unknown",
                       f"no grouping key found in {n} subjects; {OFF}")


def _no_bare(bare: int, n: int) -> Observation:
    return Observation("phase_bare", "", "unknown",
                       f"{bare}/{n} subjects name a bare 'Phase N.N'; {OFF}")


_FLOORS: dict[str, tuple[list[str], list[Observation]]] = {
    "marker-3-of-62": (_subjects("x (1.2 task 1)", 3, 62), [
        Observation("phase_task", _PHASEY, "derived",
                    "3/62 subjects carry a (version Task N) marker")]),
    "marker-3-of-80": (_subjects("x (1.2 task 1)", 3, 80),
                       [_ungrouped(80), _no_bare(0, 80)]),
    "bare-3-of-62": (_subjects("Phase 1.2", 3, 62), [
        _ungrouped(62),
        Observation("phase_bare", r"\bPhase (\d+\.\d+[a-z]?)", "derived",
                    "3/62 subjects name a bare 'Phase N.N'")]),
    "bare-3-of-80": (_subjects("Phase 1.2", 3, 80), [_ungrouped(80), _no_bare(3, 80)]),
    "ticket-3-of-35": (_subjects("ABC-1 x", 3, 35), [
        Observation("phase_task", r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b", "derived",
                    "3/35 subjects carry a ticket id; grouping by ticket")]),
    "ticket-3-of-40": (_subjects("ABC-1 x", 3, 40), [_ungrouped(40), _no_bare(0, 40)]),
    "sample-of-501": (["plain"] * 501, [_ungrouped(500), _no_bare(0, 500)]),
}


@pytest.mark.parametrize("name", sorted(_FLOORS))
def test_each_grouping_floor_at_its_boundary(tmp_path: Path, name: str) -> None:
    subjects, expected = _FLOORS[name]
    repo = _repo(tmp_path)
    _commits(repo, subjects)
    assert detect_commit_convention(repo) == expected


def test_the_branch_floor_grows_with_the_sample(tmp_path: Path) -> None:
    """62 names: the floor is max(2, 62 // 20), 3, so `b/` (three) clears it
    and `a/` (two) does not - where 62 / 20 would drop `b/` and 62 // 21
    would keep `a/`."""
    repo = _repo(tmp_path)
    _commits(repo, ["start"])
    _refs(repo, *(f"refs/heads/{name}" for name in (
        "a/1", "a/2", "b/1", "b/2", "b/3", *(f"n{i}" for i in range(56)))))
    assert detect_branch_pattern(repo) == Observation(
        "branch_token", "`((?:b)/[^`]+)`", "derived",
        "62 branches sampled; slash prefixes: b/ x3")


def test_every_status_document_is_found_in_order(tmp_path: Path) -> None:
    """detect.py:303-325: each directory in its order, each name in its
    order, a directory that is absent (docs/) skipped rather than ending the
    search."""
    repo = _tracked(tmp_path, ["STATUS.md", "NEXT_SESSION.md", "doc/HANDOFF.md",
                               ".github/STATUS.md", "notes/CHANGELOG.md",
                               "elsewhere/STATUS.md"])
    assert find_documents(repo) == [repo / "NEXT_SESSION.md", repo / "STATUS.md",
                                    repo / "doc/HANDOFF.md", repo / ".github/STATUS.md",
                                    repo / "notes/CHANGELOG.md"]


def _tracked(root: Path, paths: list[str]) -> Path:
    repo = _repo(root)
    for path in paths:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write("# x\n")
    _git(repo, "add", "-A")
    return repo


_MIXED = ["README.md", "CHANGELOG.md", "LICENSE", "docs/guide.md", "docs/setup.v2.md",
          "docs/vendor/lib.md", "docs/vendor/other.md", "docs/api/index.md",
          "docs/a/b/c/deep.md", "notes/x.md", "src/readme.txt"]
_EACH = "  each becomes an extra_docs entry; a moved file will be reported as missing"


def test_wide_documents_on_a_mixed_tree_compared_whole(tmp_path: Path) -> None:
    """Root and docs/ kept to depth 3 (deep.md is at depth 4), and the root
    alone at depth 0; notes/ is no documentation directory; the suffix is
    what follows the LAST dot (setup.v2.md), and a name with no dot at all
    (LICENSE) is no document; two documents vendored and one each generated
    and historical, so the exclusions are ordered by count before name; and
    one path git QUOTES - added to the index alone, so no file with a double
    quote in its name exists on any platform."""
    repo = _tracked(tmp_path, _MIXED)
    blob = _git(repo, "hash-object", "-w", "--stdin", stdin="# q\n").strip()
    _git(repo, "-c", "core.protectNTFS=false", "update-index", "--add",
         "--cacheinfo", f"100644,{blob},docs/a\"b.md")
    quoted = ("  1 tracked path(s) left out: git quoted them, and a quoted "
              "spelling names no file on disk")
    assert find_wide_documents(repo, 3) == (
        ["README.md", "docs/guide.md", "docs/setup.v2.md"], [
            "--wide-docs: 3 documents (root 1, docs/ 2), ordinary stratum only, depth 3",
            "  2 excluded as vendored, 1 excluded as generated, "
            "1 excluded as historical-record",
            quoted, _EACH])
    assert find_wide_documents(repo, 0) == (["README.md"], [
        "--wide-docs: 1 document (root 1, docs/ 0), ordinary stratum only, depth 0",
        "  1 excluded as historical-record", quoted, _EACH])


def test_wide_documents_at_the_root_only_compared_whole(tmp_path: Path) -> None:
    """notes/x.md is a document, but under no documentation directory, so it
    neither counts nor silences the root-only note."""
    repo = _tracked(tmp_path, ["README.md", "notes/x.md", "src/main.py"])
    assert find_wide_documents(repo, 3) == (["README.md"], [
        "--wide-docs: 1 document (root 1, docs/ 0), ordinary stratum only, depth 3",
        "  no tracked documents under docs/, doc/, documentation/, website/, "
        "site/; root documents only",
        _EACH,
    ])


def test_wide_documents_with_nothing_ordinary_is_an_answer(tmp_path: Path) -> None:
    repo = _tracked(tmp_path, ["docs/api/index.md", "CHANGELOG.md"])
    assert find_wide_documents(repo, 3) == ([], [
        "--wide-docs: 0 documents (root 0, docs/ 0), ordinary stratum only, depth 3",
        "  1 excluded as generated, 1 excluded as historical-record",
        "  no ordinary documents found; writing NO extra_docs key - an empty "
        "list is a claim, and there is nothing to claim",
    ])


def test_a_negative_depth_is_refused(tmp_path: Path) -> None:
    repo = _tracked(tmp_path, ["README.md"])
    assert find_wide_documents(repo, -1) == (None, ["--wide-docs: -1 is not a depth"])


def test_an_empty_index_is_refused_whole(tmp_path: Path) -> None:
    assert find_wide_documents(_tracked(tmp_path, []), 3) == (None, [
        "--wide-docs: git ls-files reported no tracked paths",
        "  REFUSED. An empty index reads exactly like a repository with nothing "
        "to check, which is a clean sweep on a repository nobody looked at.",
    ])


@pytest.mark.parametrize("source, why", [
    (None, "strata.py not found at {path}"),
    ("x = 1\n", "{path} has no classify()"),
])
def test_a_broken_strata_module_is_refused_whole(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        source: str | None, why: str) -> None:
    """test_wide_docs.py runs the missing module through the installer and
    asserts on pieces; here the whole account, with the path it names - for
    a module that is absent, and for one that loads with nothing to call."""
    strata = tmp_path / "strata.py"
    if source is not None:
        strata.write_text(source, encoding="utf-8")
    monkeypatch.setattr(detect, "_STRATA_PATH", strata)
    repo = _tracked(tmp_path, ["README.md"])
    assert find_wide_documents(repo, 3) == (None, [
        "--wide-docs: " + why.format(path=strata.as_posix()),
        "  REFUSED. Without the ordinary/vendored/generated/historical split "
        "this enumerates every tracked document, which measured WORSE than "
        "configuring nothing (0.081 findings per pinned path, against 0.106 "
        "today).",
    ])


STATUS = ("# Status\n\n"
          "## Release 4 - export (shipped, 2026-07-22)\n\n"
          "Merged into `main` at `abc1234`.\n\n"
          "## Release 3 - search (shipped, 2026-06-01)\n\n"
          "Shipped to `main` at `def5678`.\n\n"
          "## Notes\n\nNot an entry.\n")


def test_a_status_document_is_measured_whole(tmp_path: Path) -> None:
    """Dated headers score 2 each, the rest 1; two merge phrasings with two
    different verbs into one target."""
    doc = tmp_path / "STATUS.md"
    with open(doc, "w", encoding="utf-8", newline="") as fh:
        fh.write(STATUS)
    assert inspect_document(doc) == {
        "path": doc,
        "lines": 13,
        "header_scores": [("## Release", 4), ("# Status", 1), ("## Notes", 1)],
        "merge_verbs": ["merged", "shipped"],
        "merge_count": 2,
        "merge_targets": [("main", 2)],
    }


def test_a_document_that_is_not_all_utf8_is_still_measured(tmp_path: Path) -> None:
    """A non-ASCII header reads back as itself only if the file is decoded
    as UTF-8, which Windows' locale would not do; a latin-1 byte must be
    replaced rather than raised on, or the installer dies on a document
    written before its project moved to UTF-8."""
    doc = tmp_path / "STATUS.md"
    doc.write_bytes(b"## R\xc3\xa9lease 2 (2026-07-01)\n\n"
                    b"## R\xc3\xa9lease 1 (2026-06-01)\n\ncaf\xe9\n")
    assert inspect_document(doc) == {
        "path": doc, "lines": 5, "header_scores": [("## R\u00e9lease", 4)],
        "merge_verbs": [], "merge_count": 0, "merge_targets": []}
