"""Repeated work that was being done once per DOCUMENT.

Everything here is a cost contract rather than a behaviour one, which is
exactly why it needs pinning: reverting any of it produces identical findings,
so no ordinary test can notice, and the only symptom is a tool that got slower
between releases without anybody being able to say when.

Both were found by profiling a sweep rather than by reading the code. The first
was 70 percent of a 400-document run; the second turned 20 distinct questions
about the filesystem into 128,000 Path objects.

The safety half is asserted alongside the speed half in both cases. A cache
that is never invalidated is a correctness bug wearing a performance costume,
so what is pinned is the SCOPE - held for exactly as long as the repository is
known to be static, and released afterwards.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def test_the_remote_is_asked_for_once_rather_than_once_per_document(
        git_repo, monkeypatch) -> None:
    """`_own_remote` answers a question about the REPOSITORY.

    It was being called once per document by the pinned-ref rule. Profiled over
    400 documents, that was 11.3 seconds of a 16.2 second sweep - 70 percent of
    the run spent spawning `git remote get-url` to receive the same string.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")

    calls: list[tuple[str, ...]] = []
    real = hc._git_soft

    def counted(target, *args):
        calls.append(args)
        return real(target, *args)

    monkeypatch.setattr(hc, "_git_soft", counted)
    # A fresh ambient scope, rather than clearing the one cache this test
    # knows the name of. `_own_remote` is called DIRECTLY here, so what it
    # memoises into is whatever scope the module is holding.
    hc._SCOPE = hc.RunScope()
    try:
        first = hc._own_remote(repo)
        for _ in range(20):
            hc._own_remote(repo)
    finally:
        hc._SCOPE = hc.RunScope()

    remote_calls = [c for c in calls if c[:1] == ("remote",)]
    assert len(remote_calls) == 1, (
        f"21 lookups spawned {len(remote_calls)} git processes; the remote "
        "cannot change while one process runs"
    )
    # A second repository must still be asked about separately, or the cache is
    # answering for the wrong project - which would be a correctness bug and
    # the reason this is keyed by path rather than being a single value.
    assert first == hc._own_remote(repo)


def test_no_origin_is_a_cached_answer_not_a_cache_miss(git_repo, monkeypatch) -> None:
    """`None` means "this repository has no origin", which is a real answer.

    Storing it in a dict that is probed with `if not cached` would re-ask every
    time and cache nothing, on precisely the repositories where the pinned-ref
    rule does the least useful work.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")

    calls: list[tuple[str, ...]] = []
    real = hc._git_soft

    def counted(target, *args):
        calls.append(args)
        return real(target, *args)

    monkeypatch.setattr(hc, "_git_soft", counted)
    hc._SCOPE = hc.RunScope()
    try:
        assert hc._own_remote(repo) is None, "the fixture has no origin"
        for _ in range(10):
            hc._own_remote(repo)
    finally:
        hc._SCOPE = hc.RunScope()

    remote_calls = [c for c in calls if c[:1] == ("remote",)]
    assert len(remote_calls) == 1, (
        f"a None answer was re-fetched {len(remote_calls)} times"
    )


def test_the_remote_is_re_read_between_validate_calls(git_repo) -> None:
    """Memoising the origin must not outlive the call, and once it did.

    The first version of this cache was never reset, on the reasoning that a
    remote cannot change while a process runs. That holds for the CLI and not
    for a library caller or a test - and the resulting failure was the silent
    kind this project exists to prevent, rather than a wrong answer anyone
    would see. A repository whose origin was added between two validations kept
    answering None, so `dead-pinned-ref` examined nothing and reported clean.

    Found by CodeRabbit reviewing the change that introduced it.
    """
    import subprocess
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    subprocess.run(["git", "tag", "v1.0"], cwd=repo, check=True,
                   capture_output=True)

    doc = ("# R\n\n```yaml\nrepos:\n"
           "  - repo: https://github.com/acme/widget\n"
           "    rev: v9.9.9\n    hooks:\n      - id: w\n```\n")
    before = [f.kind for f in hc.validate(repo, doc, has_entries=False)]
    assert "dead-pinned-ref" not in before, (
        "with no origin the pin is not ours to judge: " + str(before)
    )

    subprocess.run(["git", "remote", "add", "origin",
                    "https://github.com/acme/widget"], cwd=repo, check=True,
                   capture_output=True)

    after = [f.kind for f in hc.validate(repo, doc, has_entries=False)]
    assert "dead-pinned-ref" in after, (
        "the snippet now pins a tag in THIS repository that does not exist, so "
        "an origin added between two calls must be seen: " + str(after)
    )


def test_a_sweep_still_shares_the_remote_across_documents(git_repo) -> None:
    """The reset above must not undo the reason the cache exists.

    Per-call is correct outside a sweep and would be ruinous inside one: the
    origin lookup was 70 percent of a 400-document run. The stable scope is
    what reconciles the two, so both halves are asserted - re-read between
    calls, shared within a survey.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    commit("docs/a.md", "# A\n", "chore: a")
    commit("docs/b.md", "# B\n", "chore: b")

    calls: list[tuple[str, ...]] = []
    real = hc._git_soft
    hc._git_soft = lambda target, *args: (calls.append(args), real(target, *args))[1]
    try:
        hc.run_sweep(repo, "text")
    finally:
        hc._git_soft = real

    remote_calls = [c for c in calls if c[:1] == ("remote",)]
    assert len(remote_calls) <= 1, (
        f"a 3-document sweep asked for the origin {len(remote_calls)} times; "
        "the stable scope is meant to make that once"
    )


def test_a_sweep_holds_one_cache_scope_and_gives_it_back(git_repo) -> None:
    """The scope is the safety argument, so the scope is what gets asserted.

    `validate()` rebuilds its caches per call because the repository may have
    moved on between two of them. A sweep reads many documents from one static
    checkout and writes nothing, so it declares the repository stable for its
    duration - and must hand that promise back afterwards, or every later
    caller in the process silently inherits a cache with no owner.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/a.md", "# A\n\nSee [x](gone-a.md).\n", "chore: a")
    commit("docs/b.md", "# B\n\nSee [y](gone-b.md).\n", "chore: b")

    assert hc._SCOPE.stable is False, "the default must be off"
    assert hc._SCOPE.dircache is None, "caching is off outside a declared scope"

    hc.run_sweep(repo, "text")

    assert hc._SCOPE.stable is False, (
        "the sweep kept the repository marked stable after finishing, so every "
        "later validate() in this process would reuse stale answers"
    )
    assert hc._SCOPE.dircache is None, (
        "directory listings outlived the scope that owned them"
    )


def test_the_scope_is_released_even_when_a_document_explodes(
        git_repo, monkeypatch) -> None:
    """A crash mid-sweep must not leave the process holding a stale cache.

    This is the half a `try/finally` exists for, and the half that is easy to
    write without and never notice, because the happy path restores it anyway.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("docs/a.md", "# A\n", "chore: a")

    def exploding(*args, **kwargs):
        raise RuntimeError("rule blew up")

    monkeypatch.setattr(hc, "validate", exploding)
    try:
        hc.run_sweep(repo, "text")
    except RuntimeError:
        pass
    else:                                                   # pragma: no cover
        raise AssertionError("the fixture did not raise, so nothing was proven")

    assert hc._SCOPE.stable is False, "a crash left the repository marked stable"
    assert hc._SCOPE.dircache is None, "a crash left directory listings cached"
    # The document is replaced per file inside the
    # loop, and were restored only after it - so a rule that raised left the
    # process resolving relative links against the last swept document's
    # directory. Flagged by CodeRabbit; the restore moved into the finally.
    assert hc._DOC.link_base is None, (
        "a crash left the link base pointing at the last swept document"
    )
    assert hc._DOC.doc_format == "markdown", (
        f"a crash left the document format as {hc._DOC.doc_format!r}, so the next "
        "validation would skip the markdown rules"
    )


def test_validate_outside_a_sweep_still_gets_fresh_answers(git_repo) -> None:
    """The documented promise the scope suspends, still holding everywhere else.

    A caller that creates a file between two checks must see the new answer.
    That is why caching is off by default, and it is the property the sweep
    scope borrows - so it has to be demonstrably intact after one has run.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n\nSee [x](docs/later.md).\n", "chore: init")

    hc.run_sweep(repo, "text")          # opens and closes a scope

    text = "# R\n\nSee [x](docs/later.md).\n"
    before = [f.kind for f in hc.validate(repo, text, has_entries=False)]
    assert "dead-md-link" in before, before

    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "later.md").write_text("# Later\n", encoding="utf-8")

    after = [f.kind for f in hc.validate(repo, text, has_entries=False)]
    assert "dead-md-link" not in after, (
        "a file created between two validate() calls was not seen, so the "
        "per-call cache scope is not being reset: " + str(after)
    )


def test_ancestry_is_re_read_between_validate_calls(git_repo) -> None:
    """The filesystem is only half of what these caches hold.

    `scope.dircache` uses None to mean "off", so failing to reset it merely turns
    caching off - slower, still correct, and invisible to a test. The ancestry
    and ref indexes are plain dicts that default to empty, so failing to reset
    THOSE makes them permanent: every later call in the process answers from
    whatever the first one happened to see.

    This has to go through a MERGE claim. The obvious version used a release
    tag, and it pinned nothing at all: at the time `validate_release_tags`
    shelled out to git directly and never touched these indexes, so the test
    passed with the reset deleted. Picking the rule that actually reads the
    cache is the whole content of this test.

    The release-tag rule has since grown caches of its own - the ref table, the
    tag prefixes and the integration refs - so the version that would once have
    proved nothing would now prove something. It is still the wrong test for
    THIS cache, which is why the two below exist separately rather than this
    one being loosened to cover them.
    """
    import subprocess
    import extant_collect as hc
    repo, commit = git_repo

    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True,
                              capture_output=True, text=True).stdout.strip()

    commit("README.md", "# R\n", "chore: init")
    git("checkout", "-q", "-b", "feature")
    sha = commit("feature.md", "# F\n", "feat: work")
    git("checkout", "-q", "main")

    text = ("# Status\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
            f"Merged to `main` at `{sha}`.\n\n## 1. Ref\n")
    before = [f.kind for f in hc.validate(repo, text)]
    assert "false-merge-claim" in before, (
        "the commit is not on main yet, so the claim is false: " + str(before)
    )

    git("merge", "--no-ff", "-m", "merge feature", "feature")

    after = [f.kind for f in hc.validate(repo, text)]
    assert "false-merge-claim" not in after, (
        "a merge performed between two validate() calls was not seen, so the "
        "ancestry index is outliving the call that built it: " + str(after)
    )


def test_tags_are_re_read_between_validate_calls(git_repo) -> None:
    """The tag list and the prefix convention read from it are per-call too.

    Both are plain dicts that default to empty, so a missing reset makes them
    permanent rather than merely slow - the failure mode `_OWN_REMOTE` already
    had once, where the answer stays whatever the first call happened to see.
    A release cut between two validations is the ordinary way that happens.
    """
    import subprocess
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo, check=True,
                   capture_output=True)

    # The never-tagged branch is opt-in, and this test needs it: it proves the
    # tag list is re-read by cutting a tag between two validations.
    hc._RELEASE_CLAIMS_ARE_OURS = True
    text = "# R\n\nReleased in v2.0.0 last week.\n"
    before = [f.kind for f in hc.validate(repo, text, has_entries=False)]
    assert "dead-release-tag" in before, (
        "v2.0.0 does not exist yet, so the claim is false: " + str(before)
    )

    subprocess.run(["git", "tag", "v2.0.0"], cwd=repo, check=True,
                   capture_output=True)

    after = [f.kind for f in hc.validate(repo, text, has_entries=False)]
    assert "dead-release-tag" not in after, (
        "a tag cut between two validate() calls was not seen, so the tag list "
        "is outliving the call that built it: " + str(after)
    )


def test_integration_refs_are_asked_for_once_not_once_per_claim(
        git_repo, monkeypatch) -> None:
    """`_integration_refs` answers a question about the REPOSITORY.

    It was consulted once per claim and each miss spawned a `for-each-ref`.
    Measured on a document with 200 release claims and 30 tags: 11.6 seconds
    before, 1.2 after - and the 11.6 was in the shipped tool, not introduced
    by the change that found it.

    A cost contract, so no ordinary test can see it: reverting the cache gives
    identical findings and only a tool that got slower between releases.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    import subprocess
    for n in range(3):
        subprocess.run(["git", "tag", f"v1.{n}.0"], cwd=repo, check=True,
                       capture_output=True)

    calls: list[tuple[str, ...]] = []
    real = hc._git

    def counted(target, *args):
        calls.append(args)
        return real(target, *args)

    monkeypatch.setattr(hc, "_git", counted)
    text = ("# R\n\n"
            + "".join(f"- shipped in v1.{n % 3}.0 that week.\n"
                      for n in range(40)))
    hc.validate(repo, text, has_entries=False)

    scans = [c for c in calls if c[:1] == ("for-each-ref",)]
    assert len(scans) <= 1, (
        f"40 release claims spawned {len(scans)} `for-each-ref` processes; the "
        "branch list cannot change while one validation runs"
    )


def test_one_ref_scan_answers_branches_tags_and_lookups(git_repo, monkeypatch) -> None:
    """Branches, tags and ref lookups are ONE `for-each-ref`, not four calls.

    Measured on this project's own status document: a validate spawned eight
    git subprocesses, and three asked what a single ref scan already answers -
    two `rev-parse --verify` and one `tag -l`, beside the `for-each-ref` that
    was running anyway. Routing them through one table took the validate from
    8 spawns to 6, and from about 261 ms to 214.

    A cost contract, so no ordinary test can see it: reverting gives identical
    findings and only a tool that got slower between releases.
    """
    import subprocess as sp
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    for n in range(3):
        sp.run(["git", "tag", f"v1.{n}.0"], cwd=repo, check=True,
               capture_output=True)

    calls: list[str] = []
    real = sp.run

    def counted(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "git":
            calls.append(" ".join(str(x) for x in cmd[1:3]))
        return real(cmd, *a, **k)

    monkeypatch.setattr(sp, "run", counted)
    hc._SCOPE = hc.RunScope()
    hc._tags(repo)
    hc._integration_refs(repo)
    hc._resolve_ref(repo, "main")
    hc._resolve_ref(repo, "v1.1.0")

    scans = [c for c in calls if c.startswith("for-each-ref")]
    assert len(scans) == 1, (
        f"four questions about refs spawned {len(scans)} ref scans; one table "
        f"answers all of them"
    )
    assert not [c for c in calls if c.startswith("tag ")], (
        "`tag -l` ran even though the ref table already lists the tags"
    )


def test_a_bare_name_resolves_the_way_git_resolves_it(git_repo) -> None:
    """Git tries `refs/tags/<name>` BEFORE `refs/heads/<name>` for a bare name.

    A repository with a branch and a tag of the same name is rare and real, and
    reading the table heads-first would resolve it to a different commit than
    `rev-parse` does - which surfaces once, in somebody else's repository, as a
    merge claim reported false.
    """
    import subprocess as sp
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: a")
    sp.run(["git", "checkout", "-q", "-b", "clash"], cwd=repo, check=True,
           capture_output=True)
    other = commit("b.py", "b = 1\n", "chore: b")
    sp.run(["git", "checkout", "-q", "main"], cwd=repo, check=True,
           capture_output=True)
    # A TAG named `clash`, pointing somewhere else than the branch `clash`.
    sp.run(["git", "tag", "clash", "HEAD"], cwd=repo, check=True,
           capture_output=True)

    hc._SCOPE = hc.RunScope()
    ours = hc._resolve_ref(repo, "clash")
    theirs = sp.run(["git", "rev-parse", "--verify", "--quiet", "clash^{commit}"],
                    cwd=repo, capture_output=True, text=True).stdout.strip()
    assert ours == theirs, (
        f"the table resolved `clash` to {ours}, git resolves it to {theirs}; "
        f"the branch commit is {other}"
    )


def test_the_ref_table_is_re_read_between_validate_calls(git_repo) -> None:
    """Same lifetime as every other answer git gives here. A branch created
    between two validations must be seen, or the table is a correctness bug
    wearing a performance costume."""
    import subprocess as sp
    import extant_collect as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")

    # Asserted through a RULE, not by reading the table afterwards. `validate`
    # puts the caller's scope back in `finally`, so inspecting the table after
    # the call sees the ambient scope and says nothing about the object the
    # call itself used. The first version of this test did exactly that and
    # failed against correct code.
    text = ("# R\n\n## Phase 1 - x (in progress, 2026-01-01)\n\n"
            "Work is NOT yet merged on `feature/new`.\n\n## 1. Ref\n")

    hc._SCOPE = hc.RunScope()
    before = [f.kind for f in hc.validate(repo, text)]
    assert "unknown-branch" in before, (
        "the branch does not exist yet, so it must be reported: " + str(before))

    sp.run(["git", "branch", "feature/new"], cwd=repo, check=True,
           capture_output=True)

    after = [f.kind for f in hc.validate(repo, text)]
    assert "unknown-branch" not in after, (
        "a branch created between two validate() calls was not seen, so the "
        "ref table is outliving the call that built it: " + str(after))


def test_the_pointer_sites_memo_outlives_the_call_but_not_the_next_one(
        git_repo, monkeypatch) -> None:
    """The one memo that is NOT a field of the run scope, and why.

    Both halves are asserted, because each alone permits the other's bug.

    It must SURVIVE the call: `count_examined` computes the denominator for the
    document `validate` has just read, and runs immediately after it returns.
    A value tied to the call's scope would be thrown away exactly when it is
    needed, and the rule and the denominator would each scan the document once.
    That is the version that was written first, where it silently halved
    nothing - measured on pytest's 308 documents at 617 calls and 1.19s.

    It must NOT survive the NEXT call: the sites are derived from line counts
    and from resolving each target on disk, so a caller validating the same
    text OBJECT twice across a changed checkout would otherwise answer from the
    checkout that moved on. Identity keying alone cannot see that, which is why
    it is invalidated whenever a fresh scope opens rather than left pure.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a\nb\nc\nd\ne\n", "chore: a")

    calls: list[str] = []
    real = hc._line_pointer_sites_uncached

    def counted(target, text):
        calls.append(text)
        return real(target, text)

    monkeypatch.setattr(hc, "_line_pointer_sites_uncached", counted)

    # The SAME string object throughout: that is what the memo keys on, so
    # passing an equal-but-distinct string would make both halves pass for the
    # wrong reason.
    text = "See `a.py:3` for the detail.\n"
    hc.validate(repo, text, has_entries=False)
    assert len(calls) == 1, f"the rule itself scanned {len(calls)} times"

    hc.count_examined(repo, text)
    assert len(calls) == 1, (
        f"the denominator rescanned the document the rule had just scanned "
        f"({len(calls)} scans); the memo did not survive validate() returning")

    hc.validate(repo, text, has_entries=False)
    assert len(calls) == 2, (
        f"a second validate() reused a memo built against an earlier scope "
        f"({len(calls)} scans); a checkout that changed in between would be "
        f"answered from the one before it")
