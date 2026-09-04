"""What `resolve_ref` answers, and what it no longer spawns a process to ask.

Two separate things live here, and they are separate on purpose.

THE COST. `resolve_ref` tries the ref table before shelling out, and carries a
comment citing the measurement that put it there. The table is keyed by SHORT
name (`v0.25.0`); `dead-release-tag` asks about a QUALIFIED one
(`refs/tags/v0.25.0`), because that is the spelling `integrated_by` needs. Every
one of those lookups missed and fell through to a subprocess: 14 of the 24 git
processes a `--verify` over this repository spawned were the same
`rev-parse --verify --quiet refs/tags/vX^{commit}` the table already held. On
Windows a spawn is 36 ms, so that was more than half a second per commit, paid
by a git hook.

THE ANSWER. Widening the table's reach also widens whatever the table gets
wrong, so the peel is checked here too. `ref_table` claimed `%(*objectname)` is
"the same dereference `^{commit}` performs" and it is not: for a tag pointing at
a TREE or a BLOB - both legal, both rare - `^{commit}` resolves to nothing while
the table happily reported the tree's or blob's object id. That divergence
predates this change; what this change does is make the table state the contract
it already claimed, by recording a ref only when what it would return is a
commit.

No corpus repository is expected to carry such a tag, so `fuzz --differential`
cannot demonstrate any of it. These build the tags by hand instead.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def git(repo: Path, *args: str, stdin: str = "") -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, input=stdin, capture_output=True, text=True,
        encoding="utf-8", check=True,
    ).stdout.strip()


def counted(monkeypatch, spawns: list[str]) -> None:
    """Record every git command line, then run it for real.

    The whole line rather than the subcommand, for the reason
    tests/test_spawn_budget.py gives: two different questions can share a
    prefix, and a count that cannot tell them apart reports duplicates that are
    not duplicates.
    """
    real = subprocess.run

    def record(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            spawns.append(" ".join(str(c) for c in cmd[1:]))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", record)


@pytest.fixture()
def tagged(git_repo):
    """A repository with one tag and one branch, on different commits."""
    repo, commit = git_repo
    first = commit("a.py", "a = 1\n", "chore: init")
    git(repo, "tag", "-a", "-m", "release", "v1.0.0")
    second = commit("b.py", "b = 2\n", "feat: b")
    git(repo, "branch", "topic")
    return repo, first, second


def test_a_qualified_ref_resolves_to_what_its_bare_name_resolves_to(tagged) -> None:
    """The equivalence the whole change rests on, for both kinds of ref.

    Compared against `rev-parse` itself rather than against the bare spelling
    alone, so a table that agrees with itself and with nothing else fails here.
    """
    from extant import session as hc
    from extant import refs

    repo, first, second = tagged
    with hc.run_scope():
        ctx = hc.context(repo)
        for bare, qualified in (("v1.0.0", "refs/tags/v1.0.0"),
                                ("topic", "refs/heads/topic")):
            expected = git(repo, "rev-parse", "--verify", bare + "^{commit}")
            assert refs.resolve_ref(ctx, bare) == expected, bare
            assert refs.resolve_ref(ctx, qualified) == expected, qualified


def test_a_qualified_ref_costs_no_process_the_table_already_paid_for(
        monkeypatch, tagged) -> None:
    """The 14 spawns, pinned shut.

    Counted AFTER the table is built, because building it is the one call this
    is meant to replace fourteen of, and counting it here would hide the very
    thing under test behind a number that never reaches zero.
    """
    from extant import session as hc
    from extant import refs

    repo, _first, _second = tagged
    spawns: list[str] = []
    with hc.run_scope():
        ctx = hc.context(repo)
        refs.ref_table(ctx)
        counted(monkeypatch, spawns)
        assert refs.resolve_ref(ctx, "refs/tags/v1.0.0") is not None
        assert refs.resolve_ref(ctx, "refs/heads/topic") is not None

    print(f"two qualified lookups against a built table: {spawns}")
    assert spawns == [], (
        "a qualified ref still fell through to a subprocess for an answer the "
        "ref table is holding")


def test_a_qualified_tag_ref_never_resolves_to_a_branch_of_that_name(
        git_repo) -> None:
    """The failure mode of looking in `tags or heads` for a qualified ref.

    A repository carrying both `refs/tags/dup` and `refs/heads/dup` is the only
    input that separates "strip the prefix and look in either table" from
    "strip the prefix and look in the one it named". The first is silently
    wrong here and identical everywhere else, which is what makes this fixture
    worth building rather than assuming.
    """
    from extant import session as hc
    from extant import refs

    repo, commit = git_repo
    first = commit("a.py", "a = 1\n", "chore: init")
    git(repo, "tag", "dup")
    second = commit("b.py", "b = 2\n", "feat: b")
    git(repo, "branch", "dup")

    assert first != second
    with hc.run_scope():
        ctx = hc.context(repo)
        assert refs.resolve_ref(ctx, "refs/tags/dup") == first
        assert refs.resolve_ref(ctx, "refs/heads/dup") == second
        # And a BARE name keeps git's own precedence, which is the tag.
        assert refs.resolve_ref(ctx, "dup") == first


def test_a_spelling_no_table_holds_still_falls_through_to_git(tagged) -> None:
    """A raw SHA, `HEAD` and `main~1` are legitimate inputs and no table has them.

    The table is a fast path, not a replacement. A version of this change that
    returned None on a table miss would report every SHA-anchored claim dead.
    """
    from extant import session as hc
    from extant import refs

    repo, first, second = tagged
    with hc.run_scope():
        ctx = hc.context(repo)
        assert refs.resolve_ref(ctx, second) == second
        assert refs.resolve_ref(ctx, second[:8]) == second
        assert refs.resolve_ref(ctx, "HEAD") == second
        assert refs.resolve_ref(ctx, "HEAD~1") == first
        assert refs.resolve_ref(ctx, "no-such-ref-anywhere") is None


def _tag_a_non_commit(repo: Path) -> tuple[str, str]:
    """Tag a blob and a tree. Both are legal; neither peels to a commit."""
    blob = git(repo, "hash-object", "-w", "--stdin", stdin="not a commit\n")
    git(repo, "tag", "blobtag", blob)
    tree = git(repo, "mktree", stdin=f"100644 blob {blob}\tfile\n")
    git(repo, "tag", "-a", "-m", "a tree", "treetag", tree)
    return blob, tree


def test_a_tag_pointing_at_a_tree_or_a_blob_resolves_to_nothing(git_repo) -> None:
    """`ref_table` said `%(*objectname)` is what `^{commit}` does. It is not.

    `^{commit}` on a tag that names a tree or a blob resolves to NOTHING - there
    is no commit to reach - while the table reported the tree's or the blob's
    own object id, which is not a commit and appears in no rev-list. Both
    spellings are checked, because the lightweight tag exercises `%(objectname)`
    and the annotated one `%(*objectname)`, and the two failed differently.

    Stated as a behaviour change rather than folded into a cost claim: on a
    repository carrying such a tag, a bare name that used to answer with a
    non-commit object id now answers with nothing.
    """
    from extant import session as hc
    from extant import refs

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    _tag_a_non_commit(repo)

    with hc.run_scope():
        ctx = hc.context(repo)
        heads, tags = refs.ref_table(ctx)
        assert "blobtag" not in tags, tags
        assert "treetag" not in tags, tags
        for spelling in ("blobtag", "refs/tags/blobtag",
                         "treetag", "refs/tags/treetag"):
            assert refs.resolve_ref(ctx, spelling) is None, spelling


def test_the_table_agrees_with_rev_parse_about_every_ref_in_the_repository(
        git_repo) -> None:
    """The equivalence proof, run rather than quoted.

    Commit tags, annotated and lightweight, a branch, and the two non-commit
    tags above - every ref this repository has, compared one at a time against
    the answer git itself gives.
    """
    from extant import session as hc
    from extant import refs

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    git(repo, "tag", "light")
    git(repo, "tag", "-a", "-m", "annotated", "heavy")
    commit("b.py", "b = 2\n", "feat: b")
    git(repo, "branch", "topic")
    _tag_a_non_commit(repo)

    names = git(repo, "for-each-ref", "--format=%(refname)").splitlines()
    assert len(names) >= 6, names
    with hc.run_scope():
        ctx = hc.context(repo)
        divergences = []
        for full in names:
            short = full.split("/", 2)[2]
            expected = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", full + "^{commit}"],
                cwd=repo, capture_output=True, text=True, encoding="utf-8",
            ).stdout.strip() or None
            for spelling in (short, full):
                got = refs.resolve_ref(ctx, spelling)
                if got != expected:
                    divergences.append((spelling, expected, got))
    print(f"compared {len(names) * 2} spellings of {len(names)} refs "
          f"against rev-parse")
    assert not divergences, divergences


def test_a_pin_that_names_a_real_tag_asks_no_process_of_its_own(
        monkeypatch, git_repo) -> None:
    """`dead-pinned-ref` went to git directly and never reached `resolve_ref`.

    Same question, same tags-before-heads precedence git itself uses, and one
    fewer process per pin. A README pinning several revs of its own repository
    paid a spawn for each.
    """
    from extant import session as hc
    from extant import refs
    from extant.rules import pinned_ref

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    git(repo, "tag", "v1.0.0")
    git(repo, "remote", "add", "origin", "https://github.com/acme/widget")
    text = ("```yaml\n"
            "repos:\n"
            "  - repo: https://github.com/acme/widget\n"
            "    rev: v1.0.0\n"
            "    rev: v1.0.0\n"
            "```\n")

    spawns: list[str] = []
    with hc.run_scope():
        ctx = hc.context(repo)
        refs.ref_table(ctx)
        pinned_ref._own_remote(ctx)
        counted(monkeypatch, spawns)
        assert pinned_ref.check(ctx, text) == []

    print(f"two pins against a built table: {spawns}")
    assert spawns == [], "a pin still spawned a process for a tag in the table"


def test_a_pin_naming_a_version_that_does_not_exist_is_still_reported(
        git_repo) -> None:
    """The other direction, so the test above cannot pass by going silent."""
    from extant import session as hc
    from extant.rules import pinned_ref

    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")
    git(repo, "remote", "add", "origin", "https://github.com/acme/widget")
    text = ("```yaml\n"
            "repos:\n"
            "  - repo: https://github.com/acme/widget\n"
            "    rev: v9.9.9\n"
            "```\n")

    with hc.run_scope():
        findings = pinned_ref.check(hc.context(repo), text)

    assert [f.kind for f in findings] == ["dead-pinned-ref"], findings
    assert findings[0].subject == "v9.9.9"
