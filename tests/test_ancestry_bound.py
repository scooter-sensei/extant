"""The ancestry index is bounded, and the batch answers what lies past the bound.

`_ancestor_index` used to hold EVERY commit reachable from a ref. Measured on
2026-09-15 without a commit-graph, which no clone in the corpus has and no
fresh CI checkout does: rust's 338,850 commits cost 10.6 s and 77 MB per ref
per worker. The index is now `rev-list -n INDEX_BOUND+1 REF`, full-SHA
membership in a frozenset, and a flag saying whether it is complete. A hit is
proof either way. A miss on a complete index is a no with no spawn. A miss on
an incomplete one is settled by ONE `rev-list --stdin --not REF` per rule and
ref, fed full SHAs, whose output is the exclusive history of the inputs - an
input that is printed is not an ancestor, one that is not printed is.

Every test here runs the SAME question under a bound of one, a bound in the
middle and the default, because the docstring that used to argue against a
size switch was right about one thing: a path that only runs on large inputs
is a path no test exercises. So the tests exercise it.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

HEX40 = re.compile(r"^[0-9a-f]{40}$")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def _ancestor_of(repo: Path, rev: str, ref: str) -> bool:
    """Git itself, not another product function."""
    return subprocess.run(["git", "merge-base", "--is-ancestor", rev, ref],
                          cwd=repo, capture_output=True).returncode == 0


def _entry(body: str) -> str:
    return (f"# Status\n\n## Phase 1 - work (in progress, 2026-01-01)\n\n"
            f"{body}\n\n## 1. Layout\n")


def _history(git_repo) -> tuple[Path, dict[str, str]]:
    """main: c1 c2 c3 [merge topic: t1 t2] c4 c5; side: s1 s2 s3, never merged.

    Ancestors of main include the root, a second-parent commit and the tip -
    the three shapes a date-ordered walk and a prefix cut treat differently.
    """
    repo, commit = git_repo
    ids: dict[str, str] = {}
    for n in (1, 2, 3):
        ids[f"c{n}"] = commit(f"c{n}.py", f"c = {n}\n", f"feat: c{n}")
    git(repo, "checkout", "-q", "-b", "feature/topic")
    for n in (1, 2):
        ids[f"t{n}"] = commit(f"t{n}.py", f"t = {n}\n", f"feat: t{n}")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge topic", "feature/topic")
    ids["merge"] = git(repo, "rev-parse", "HEAD").strip()
    for n in (4, 5):
        ids[f"c{n}"] = commit(f"c{n}.py", f"c = {n}\n", f"feat: c{n}")
    git(repo, "checkout", "-q", "-b", "feature/side")
    for n in (1, 2, 3):
        ids[f"s{n}"] = commit(f"s{n}.py", f"s = {n}\n", f"feat: s{n}")
    git(repo, "checkout", "-q", "main")
    return repo, ids


def _spawns(monkeypatch) -> list[tuple[list[str], bytes | str | None]]:
    """Every git process at the subprocess boundary: (argv, stdin payload)."""
    real = subprocess.run
    seen: list[tuple[list[str], bytes | str | None]] = []

    def counted(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            seen.append(([str(c) for c in cmd[1:]], kw.get("input")))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counted)
    return seen


def _batches(seen) -> list[tuple[list[str], bytes | str | None]]:
    return [(argv, payload) for argv, payload in seen if "--stdin" in argv
            and argv[0] == "rev-list"]


BOUNDS = (1, 3, None)   # None means the shipped default


def _bound(monkeypatch, value):
    from extant import refs
    if value is not None:
        monkeypatch.setattr(refs, "INDEX_BOUND", value)
    return refs.INDEX_BOUND


# --- the index itself --------------------------------------------------------

def test_a_hit_is_proof_and_a_miss_asks_only_past_the_bound(git_repo, monkeypatch) -> None:
    from extant import refs
    from extant import session as hc
    repo, ids = _history(git_repo)
    seen = _spawns(monkeypatch)

    _bound(monkeypatch, 2)
    with hc.run_scope():
        ctx = hc.context(repo)
        index = refs._ancestor_index(ctx, "main")
        assert index is not None
        assert index.complete is False, "eleven commits behind a bound of two"
        assert len(index.commits) == 3, "the bound plus one, so the cut is visible"
        assert ids["c5"] in index.commits, "the tip is the first line of any rev-list"
        assert ids["c1"] not in index.commits, "the root lies past the bound"
        assert refs.reachable_from(ctx, ids["c1"], "main") is True
        assert refs.reachable_from(ctx, ids["t1"], "main") is True, "second parent"
        assert refs.reachable_from(ctx, ids["s2"], "main") is False
        assert refs.reachable_from(ctx, ids["c5"], "main") is True
    for name in ("c1", "t1", "s2", "c5"):
        assert _ancestor_of(repo, ids[name], "main") is (name != "s2")
    assert [argv for argv, _ in seen if argv[:2] == ["rev-list", "-n"]] == [
        ["rev-list", "-n", "3", "main"]], "one bounded rev-list per ref per scope"


def test_the_default_bound_indexes_a_small_history_completely(git_repo, monkeypatch) -> None:
    from extant import refs
    from extant import session as hc
    repo, ids = _history(git_repo)
    seen = _spawns(monkeypatch)
    with hc.run_scope():
        ctx = hc.context(repo)
        index = refs._ancestor_index(ctx, "main")
        assert index is not None and index.complete is True
        assert len(index.commits) == 8
        assert refs.reachable_from(ctx, ids["c1"], "main") is True
        assert refs.reachable_from(ctx, ids["s3"], "main") is False
    assert _batches(seen) == [], "a complete index answers a miss without a spawn"
    assert [argv for argv, _ in seen if argv[0] == "rev-list"] == [
        ["rev-list", "-n", str(refs.INDEX_BOUND + 1), "main"]]


# --- the rules, under every bound -------------------------------------------

@pytest.mark.parametrize("bound", BOUNDS)
def test_the_merge_rule_answers_the_same_under_every_bound(git_repo, monkeypatch, bound) -> None:
    from extant import session as hc
    from extant.rules import merge as rule_merge
    repo, ids = _history(git_repo)
    _bound(monkeypatch, bound)
    text = (f"- Merged to `main` at `{ids['c1'][:9]}`.\n"
            f"- Merged to `main` at `{ids['t1'][:9]}`.\n"
            f"- Merged to `main` at `{ids['c5'][:9]}`.\n"
            f"- Merged to `main` at `{ids['s2'][:9]}`.\n")
    with hc.run_scope():
        findings = rule_merge.check(hc.context(repo), text)
    assert [(f.kind, f.line, f.subject) for f in findings] == [
        ("false-merge-claim", 4, ids["s2"][:9])]


@pytest.mark.parametrize("bound", BOUNDS)
def test_the_release_rule_answers_the_same_under_every_bound(git_repo, monkeypatch, bound) -> None:
    from extant import session as hc
    from extant.rules import release_tag as rule_release
    repo, ids = _history(git_repo)
    git(repo, "tag", "-a", "-m", "one", "v1.0.0", ids["c2"])
    git(repo, "tag", "v1.1.0", ids["t2"])
    git(repo, "tag", "v9.9.9", ids["s3"])
    _bound(monkeypatch, bound)
    text = "Shipped in v1.0.0, then shipped in v1.1.0, and shipped in v9.9.9.\n"
    with hc.run_scope():
        findings = rule_release.check(hc.context(repo), text)
    assert [(f.kind, f.subject) for f in findings] == [("dead-release-tag", "v9.9.9")]
    assert "on no integration branch" in findings[0].detail


@pytest.mark.parametrize("bound", BOUNDS)
def test_the_live_claim_rule_answers_the_same_under_every_bound(git_repo, monkeypatch, bound) -> None:
    from extant import session as hc
    from extant.rules import live_claim as rule_live
    repo, ids = _history(git_repo)
    _bound(monkeypatch, bound)
    text = _entry("`feature/topic` is NOT yet merged, and `feature/side` is "
                  "NOT yet merged either.")
    with hc.run_scope():
        findings = rule_live.check(hc.context(repo), text)
    assert [(f.kind, f.subject) for f in findings] == [
        ("stale-live-claim", "feature/topic")]
    assert "ancestor of main" in findings[0].detail


# --- the batch: one per rule and ref, full SHAs, none when nothing misses ----

def test_one_batch_per_rule_and_ref_fed_full_shas(git_repo, monkeypatch) -> None:
    from extant import session as hc
    from extant.rules import merge as rule_merge
    from extant.rules import release_tag as rule_release
    repo, ids = _history(git_repo)
    git(repo, "tag", "v1.0.0", ids["c2"])
    git(repo, "tag", "v9.9.9", ids["s3"])
    _bound(monkeypatch, 1)
    seen = _spawns(monkeypatch)
    merge_text = (f"- Merged to `main` at `{ids['c1'][:9]}`.\n"
                  f"- Merged to `main` at `{ids['t1'][:9]}`.\n"
                  f"- Merged to `main` at `{ids['s2'][:9]}`.\n")
    with hc.run_scope():
        ctx = hc.context(repo)
        rule_merge.check(ctx, merge_text)
        after_merge = len(_batches(seen))
        rule_release.check(ctx, "Shipped in v1.0.0 and shipped in v9.9.9.\n")
    batches = _batches(seen)
    assert after_merge == 1, "three merge claims, one ref, ONE batch"
    assert len(batches) == 2, "the release rule's tags are a second batch on the same ref"
    for argv, payload in batches:
        assert argv == ["rev-list", "--stdin", "--not", "main"], argv
        assert isinstance(payload, bytes), "fed as bytes; text mode writes CRLF on Windows"
        lines = payload.decode("ascii").split("\n")
        assert lines[-1] == "" and all(HEX40.match(line) for line in lines[:-1]), lines
    fed = set(batches[0][1].decode("ascii").split())
    assert fed == {ids["c1"], ids["t1"], ids["s2"]}, (
        "the abbreviated claims were widened to the full SHAs cat-file returned")


def test_nothing_is_fed_that_the_index_already_holds(git_repo, monkeypatch) -> None:
    from extant import session as hc
    from extant.rules import merge as rule_merge
    repo, ids = _history(git_repo)
    _bound(monkeypatch, 1)
    seen = _spawns(monkeypatch)
    with hc.run_scope():
        findings = rule_merge.check(
            hc.context(repo), f"Merged to `main` at `{ids['c5'][:9]}`.\n")
    assert findings == []
    assert _batches(seen) == [], "the tip is the first line of the bounded index"


def test_a_settled_answer_is_not_asked_twice_in_one_run(git_repo, monkeypatch) -> None:
    from extant import session as hc
    from extant.rules import merge as rule_merge
    repo, ids = _history(git_repo)
    _bound(monkeypatch, 1)
    seen = _spawns(monkeypatch)
    text = f"Merged to `main` at `{ids['c1'][:9]}` and at `{ids['s1'][:9]}`.\n"
    with hc.run_scope():
        ctx = hc.context(repo)
        rule_merge.check(ctx, text)
        rule_merge.check(ctx, text)
    assert len(_batches(seen)) == 1, "the second document's misses were already settled"


# --- the abort, the memo's key, and the token memo --------------------------

def test_an_aborted_batch_falls_back_to_one_merge_base_per_miss(git_repo, monkeypatch) -> None:
    from extant import refs
    from extant import session as hc
    from extant.git import CountingGit, SubprocessGit
    repo, ids = _history(git_repo)
    _bound(monkeypatch, 1)
    real = subprocess.run

    def aborting(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git" and "--stdin" in cmd:
            return subprocess.CompletedProcess(cmd, 128, b"", b"fatal: bad revision\n")
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", aborting)
    counting = CountingGit(SubprocessGit())
    monkeypatch.setattr(hc, "_GIT", counting)
    with hc.run_scope():
        ctx = hc.context(repo)
        refs.settle_ancestry(ctx, [(ids["c1"], "main"), (ids["s2"], "main")])
        assert refs.reachable_from(ctx, ids["c1"], "main") is True
        assert refs.reachable_from(ctx, ids["s2"], "main") is False
    asked = [c for c in counting.calls if c[:2] == ("merge-base", "--is-ancestor")]
    assert sorted(c[2] for c in asked) == sorted([ids["c1"], ids["s2"]]), (
        "the fallback is one merge-base per miss, and it answered")


def test_settled_answers_are_keyed_by_repository(git_repo, tmp_path, monkeypatch) -> None:
    """Two repositories with a `main` each, one run scope, a commit only one
    of them holds: the first repository's yes must not leak into the second."""
    import shutil
    from extant import refs
    from extant import session as hc
    repo, ids = _history(git_repo)
    other = tmp_path / "other"
    shutil.copytree(repo, other)
    (other / "z.py").write_text("z = 1\n", encoding="utf-8")
    git(other, "add", "z.py")
    git(other, "commit", "-q", "-m", "feat: only in other")
    only_there = git(other, "rev-parse", "HEAD").strip()
    _bound(monkeypatch, 1)
    with hc.run_scope():
        assert refs.reachable_from(hc.context(other), only_there, "main") is True
        assert refs.reachable_from(hc.context(repo), only_there, "main") is False


def test_tokens_are_memoised_as_the_full_sha_git_returned(git_repo) -> None:
    from extant import refs
    from extant import session as hc
    repo, ids = _history(git_repo)
    git(repo, "tag", "-a", "-m", "one", "v1.0.0", ids["c2"])
    with hc.run_scope():
        ctx = hc.context(repo)
        alive = refs.resolve_shas(ctx, [ids["c1"][:9], "deadbeefdead"])
        assert alive == {ids["c1"][:9]}
        assert ctx.run.shas[(str(repo), ids["c1"][:9])] == ids["c1"]
        assert ctx.run.shas[(str(repo), "deadbeefdead")] is None
        assert refs.commit_id(ctx, ids["c1"][:9]) == ids["c1"]
        assert refs.commit_id(ctx, ids["c1"]) == ids["c1"]
        assert refs.commit_id(ctx, "deadbeefdead") is None
        assert refs.commit_id(ctx, "main") == ids["c5"]
        assert refs.commit_id(ctx, "refs/tags/v1.0.0") == ids["c2"], "peeled"
        assert refs.commit_id(ctx, "no-such-ref") is None


def test_a_token_not_yet_resolved_is_resolved_the_way_dead_sha_resolves_it(
        git_repo, monkeypatch) -> None:
    """One token, one resolver: a SHA-shaped rev that no batch has seen goes
    through `cat-file --batch-check`, never through the ref table."""
    from extant import refs
    from extant import session as hc
    repo, ids = _history(git_repo)
    seen = _spawns(monkeypatch)
    with hc.run_scope():
        ctx = hc.context(repo)
        assert refs.reachable_from(ctx, ids["t2"][:9], "main") is True
    assert [argv for argv, _ in seen if argv[0] == "cat-file"] == [
        ["cat-file", "--batch-check"]]
    assert not [argv for argv, _ in seen if argv[:2] == ["rev-parse", "--verify"]]
