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

import re
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
    from extant import session as hc
    from extant.rules import pinned_ref as rule_pinned_ref
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")

    # Through the seam, not by wrapping the module function. Two things follow
    # from that and both matter here. The rules now reach git only through
    # `_GIT`, so wrapping `_git_soft` by name would intercept nothing and this
    # test would pass while counting an empty list. And CountingGit records one
    # entry per CALL, where the old wrapping saw two for every soft call
    # because `_git_soft` delegates to `_git` - so the numbers below are the
    # questions asked rather than the frames entered.
    counter = hc.CountingGit(hc.SubprocessGit())
    monkeypatch.setattr(hc, "_GIT", counter)
    calls = counter.calls
    # A fresh ambient scope, rather than clearing the one cache this test
    # knows the name of. `_own_remote` is called DIRECTLY here, so what it
    # memoises into is whatever scope the module is holding.
    hc._SCOPE = hc.RunScope()
    try:
        first = rule_pinned_ref._own_remote(hc.context(repo))
        for _ in range(20):
            rule_pinned_ref._own_remote(hc.context(repo))
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
    assert first == rule_pinned_ref._own_remote(hc.context(repo))


def test_no_origin_is_a_cached_answer_not_a_cache_miss(git_repo, monkeypatch) -> None:
    """`None` means "this repository has no origin", which is a real answer.

    Storing it in a dict that is probed with `if not cached` would re-ask every
    time and cache nothing, on precisely the repositories where the pinned-ref
    rule does the least useful work.
    """
    from extant import session as hc
    from extant.rules import pinned_ref as rule_pinned_ref
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")

    counter = hc.CountingGit(hc.SubprocessGit())
    monkeypatch.setattr(hc, "_GIT", counter)
    calls = counter.calls
    hc._SCOPE = hc.RunScope()
    try:
        assert rule_pinned_ref._own_remote(hc.context(repo)) is None, "the fixture has no origin"
        for _ in range(10):
            rule_pinned_ref._own_remote(hc.context(repo))
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
    from extant import session as hc
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


def test_a_resolved_sha_is_re_read_between_validate_calls(
        git_repo, tmp_path) -> None:
    """The same lifetime rule, applied to the cache Task 7 added.

    Whether a SHA resolves is memoised so that two rules asking about
    overlapping tokens cost ONE `cat-file --batch-check` instead of two. That
    is a per-run answer and not a permanent one: an object can arrive between
    two validations, and a cache with no lifetime would keep reporting a live
    reference as dead - a finding against a document that is correct, which is
    the direction of error that gets a validator switched off.

    Dead-then-alive on purpose, and with THE SAME token both times. The other
    direction would pass against a cache that is never written at all, and two
    different tokens would pass against one that is never dropped, because the
    second was never asked about. Only one shape can tell the two apart.

    The object arrives by fetching it from a donor repository rather than by
    committing here, because an abbreviated SHA cannot be written into the
    document before the commit that produces it exists.
    """
    import subprocess
    from extant import session as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")

    donor = tmp_path / "donor"
    donor.mkdir()
    for args in (("init", "-b", "main"),
                 ("config", "user.email", "test@example.com"),
                 ("config", "user.name", "Test")):
        subprocess.run(["git", *args], cwd=donor, check=True,
                       capture_output=True)
    (donor / "a.py").write_text("a = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=donor, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: a"], cwd=donor, check=True,
                   capture_output=True)
    full_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=donor, check=True,
                              capture_output=True, text=True).stdout.strip()
    # `looks_like_sha` (extant/commits.py) refuses a token with no digit or no
    # letter, so a bare `full_sha[:9]` made this test about 1.5% flaky: a
    # random 9-hex-char slice of a real commit hash is all-digit about 0.6% of
    # the time, and all-letter on top of that - either way the token is never
    # even recognised as a SHA candidate, so the "before" assertion below
    # fails for a reason that has nothing to do with the cache this test
    # exists to pin. Widening the prefix - never SUBSTITUTING characters,
    # which would stop it matching the real commit once fetched - makes the
    # token satisfy the shape rule by construction instead of by chance.
    # DO NOT simplify this back to a bare slice.
    sha = full_sha[:9]
    while not (any(ch.isdigit() for ch in sha) and any(ch.isalpha() for ch in sha)):
        sha = full_sha[:len(sha) + 1]
        assert len(sha) <= len(full_sha), (
            f"full commit SHA {full_sha!r} has no digit/letter mix at any "
            "prefix length, which should be practically impossible for a "
            "real git hash")

    doc = f"Landed at `{sha}`.\n"
    before = [f.kind for f in hc.validate(repo, doc, has_entries=False)]
    assert "dead-sha" in before, (
        "the setup is wrong: the donor's commit is not here yet, so this "
        "reference should be reported dead: " + str(before))

    subprocess.run(["git", "fetch", str(donor), "main"], cwd=repo, check=True,
                   capture_output=True)

    after = [f.kind for f in hc.validate(repo, doc, has_entries=False)]
    assert "dead-sha" not in after, (
        "the same token was still reported dead after the object arrived, so "
        "the SHA cache outlived the run it belongs to: " + str(after))


def test_a_sweep_still_shares_the_remote_across_documents(
        git_repo, monkeypatch) -> None:
    """The reset above must not undo the reason the cache exists.

    Per-call is correct outside a sweep and would be ruinous inside one: the
    origin lookup was 70 percent of a 400-document run. The stable scope is
    what reconciles the two, so both halves are asserted - re-read between
    calls, shared within a survey.
    """
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    commit("docs/a.md", "# A\n", "chore: a")
    commit("docs/b.md", "# B\n", "chore: b")

    # `monkeypatch` rather than the bare assign-and-restore this used to do:
    # the old form leaked the wrapper onto the module whenever `run_sweep`
    # raised before its `finally`, and the seam makes the swap a one-liner
    # anyway.
    counter = hc.CountingGit(hc.SubprocessGit())
    monkeypatch.setattr(hc, "_GIT", counter)
    sweep.run_sweep(repo, "text")

    remote_calls = [c for c in counter.calls if c[:1] == ("remote",)]
    assert len(remote_calls) <= 1, (
        f"a 3-document sweep asked for the origin {len(remote_calls)} times; "
        "the stable scope is meant to make that once"
    )
    assert remote_calls, (
        "no remote lookups were recorded at all, so this bound proves "
        "nothing; either the sweep never asked for the origin or _GIT was "
        "not what it asked through"
    )


def test_a_sweep_holds_one_cache_scope_and_gives_it_back(git_repo) -> None:
    """The scope is the safety argument, so the scope is what gets asserted.

    `validate()` rebuilds its caches per call because the repository may have
    moved on between two of them. A sweep reads many documents from one static
    checkout and writes nothing, so it declares the repository stable for its
    duration - and must hand that promise back afterwards, or every later
    caller in the process silently inherits a cache with no owner.
    """
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("docs/a.md", "# A\n\nSee [x](gone-a.md).\n", "chore: a")
    commit("docs/b.md", "# B\n\nSee [y](gone-b.md).\n", "chore: b")

    assert hc._SCOPE.stable is False, "the default must be off"
    assert hc._SCOPE.dircache is None, "caching is off outside a declared scope"

    sweep.run_sweep(repo, "text")

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
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("docs/a.md", "# A\n", "chore: a")

    def exploding(*args, **kwargs):
        raise RuntimeError("rule blew up")

    monkeypatch.setattr(hc, "validate", exploding)
    try:
        sweep.run_sweep(repo, "text")
    except RuntimeError:
        pass
    else:                                                   # pragma: no cover
        raise AssertionError("the fixture did not raise, so nothing was proven")

    assert hc._SCOPE.stable is False, "a crash left the repository marked stable"
    assert hc._SCOPE.dircache is None, "a crash left directory listings cached"
    # The document is replaced per file inside the
    # loop, and was restored only after it - so a rule that raised left the
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
    from extant import session as hc
    from extant import sweep
    repo, commit = git_repo
    commit("README.md", "# R\n\nSee [x](docs/later.md).\n", "chore: init")

    sweep.run_sweep(repo, "text")          # opens and closes a scope

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
    from extant import session as hc
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


def test_tags_are_re_read_between_validate_calls(git_repo, reconfigure) -> None:
    """The tag list and the prefix convention read from it are per-call too.

    Both are plain dicts that default to empty, so a missing reset makes them
    permanent rather than merely slow - the failure mode `_OWN_REMOTE` already
    had once, where the answer stays whatever the first call happened to see.
    A release cut between two validations is the ordinary way that happens.
    """
    import subprocess
    from extant import session as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo, check=True,
                   capture_output=True)

    # The never-tagged branch is opt-in, and this test needs it: it proves the
    # tag list is re-read by cutting a tag between two validations.
    reconfigure(release_claims_are_ours=True)
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
    from extant import session as hc
    repo, commit = git_repo
    commit("README.md", "# R\n", "chore: init")
    import subprocess
    for n in range(3):
        subprocess.run(["git", "tag", f"v1.{n}.0"], cwd=repo, check=True,
                       capture_output=True)

    counter = hc.CountingGit(hc.SubprocessGit())
    monkeypatch.setattr(hc, "_GIT", counter)
    text = ("# R\n\n"
            + "".join(f"- shipped in v1.{n % 3}.0 that week.\n"
                      for n in range(40)))
    hc.validate(repo, text, has_entries=False)

    scans = [c for c in counter.calls if c[:1] == ("for-each-ref",)]
    assert len(scans) <= 1, (
        f"40 release claims spawned {len(scans)} `for-each-ref` processes; the "
        "branch list cannot change while one validation runs"
    )
    assert scans, (
        "no for-each-ref scans were recorded at all, so this bound proves "
        "nothing; either nothing here reached the ref table or _GIT was not "
        "what it asked through"
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
    from extant import session as hc
    from extant import refs
    from extant.rules import release_tag as rule_release_tag
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
    rule_release_tag._tags(hc.context(repo))
    refs.integration_refs(hc.context(repo))
    refs.resolve_ref(hc.context(repo), "main")
    refs.resolve_ref(hc.context(repo), "v1.1.0")

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
    from extant import session as hc
    from extant import refs
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
    ours = refs.resolve_ref(hc.context(repo), "clash")
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
    from extant import session as hc
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
    from extant import session as hc
    repo, commit = git_repo
    commit("a.py", "a\nb\nc\nd\ne\n", "chore: a")

    # Patched on the RULE MODULE, which is the module whose global the memo
    # and its reader both live in. The shim's same-named wrapper is a
    # different object and swapping it reaches nothing - both halves below
    # would then count zero scans, and only the first assertion here would
    # notice. That is why it asserts a count rather than "not rescanned".
    from extant.rules import line_pointer

    calls: list[str] = []
    real = line_pointer._line_pointer_sites_uncached

    def counted(ctx, text):
        calls.append(text)
        return real(ctx, text)

    monkeypatch.setattr(line_pointer, "_line_pointer_sites_uncached", counted)

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


def test_the_candidate_scans_run_once_per_document_not_once_per_caller(
        git_repo, monkeypatch) -> None:
    """Three callers ask the same question about one document; one scan answers.

    `find_sha_candidates` and `merge_claims` are each read by
    `extant.rules.sha.check`/`extant.rules.merge.check`, by that rule's
    `examined`, and by `_document_sha_tokens`, which builds the batched SHA
    resolution both rules share. Each of the three is right on its own - the
    rule contract keeps findings and denominator apart so they describe one
    population, and one batch is what keeps a document at a single `cat-file
    --batch-check` - and together they scanned every document three times over
    identical bytes. Measured on a 29-document sweep before the memo: 89 calls
    each, 0.39s of self time between them.

    Patched on the SCAN rather than on the wrapper, for the reason the pointer
    sites test above gives: patching the memoised name would count zero either
    way and prove nothing.
    """
    from extant import commits
    from extant import session as hc
    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "feat: a")

    sha_scans: list[str] = []
    claim_scans: list[str] = []
    real_sha = commits._find_sha_candidates
    real_claims = commits._merge_claims

    def counted_sha(text):
        sha_scans.append(text)
        return real_sha(text)

    def counted_claims(config, prose):
        claim_scans.append(prose)
        return real_claims(config, prose)

    monkeypatch.setattr(commits, "_find_sha_candidates", counted_sha)
    monkeypatch.setattr(commits, "_merge_claims", counted_claims)

    # The SAME string object for both halves, which is what the memo keys on.
    # An equal-but-distinct string would make this pass for the wrong reason.
    text = f"Merged to `main` at `{sha}`.\n"
    hc.validate(repo, text, has_entries=False)
    hc.count_examined(repo, text)
    assert len(sha_scans) == 1, (
        f"the backticked-SHA scan ran {len(sha_scans)} times for one document")
    assert len(claim_scans) == 1, (
        f"the merge-claim scan ran {len(claim_scans)} times for one document")


def test_a_changed_merge_pattern_is_not_answered_from_the_previous_one(
        reconfigure) -> None:
    """The half of the key that `_STRIPPED` is missing.

    `merge_claims` reads two configured values - the pattern and the trunk -
    as well as the text, and all three are in the key. Keyed on text identity
    alone it would be `_STRIPPED` (extant/text.py) again: that memo's value
    also depends on `doc.doc_format` while its key does not, which is a known
    latent bug recorded there and in extant/scope.py rather than one to copy.

    The same text OBJECT is read twice under two different patterns, which is
    the arrangement an incomplete key cannot survive: it would hand back the
    first pattern's claims the second time and a project that reconfigured
    `merge_claim` would keep being checked against the pattern it replaced.
    """
    from extant import commits
    from extant import session as hc

    text = "Merged to `main` at `abc1234`.\n"
    first = commits.merge_claims(hc._ACTIVE, text)
    assert [sha for _n, _ref, sha in first] == ["abc1234"], (
        "the default pattern did not match the fixture, so the second half "
        "below would pass against any implementation at all")

    changed = reconfigure(merge_claim=re.compile(
        r"landed on (`[^`\n]+`) at `([0-9a-f]{7,40})`", re.IGNORECASE))
    assert commits.merge_claims(changed, text) == [], (
        "the same text object was answered from the previous pattern's memo, "
        "so a reconfigured `merge_claim` would never reach the scanner")


def test_the_path_pointer_scan_runs_once_per_document_not_once_per_caller(
        git_repo, monkeypatch) -> None:
    """Two callers ask the same question about one document; one scan answers.

    The redundancy `f3fb482` removed from `find_sha_candidates` and
    `merge_claims`, left in `dead-path-pointer` because the sweep grew a
    denominator after those were measured. `check` scanned the document line by
    line and `examined` scanned the whole prose blob for the same pointers.

    Profiled by CALLER on a 29-document sweep, which is what the previous pass
    learned to do: `examined` ran 30 times for 0.177 s of `findall` - 5.9 ms
    for one call per document, of which the scan is 5.09 ms and `prose()`,
    which is separately memoised and a hit by the time `examined` runs, is
    0.07.

    Patched on the SCAN rather than on the memoised wrapper, for the reason the
    tests above give: patching the wrapper would count zero either way.
    """
    from extant import session as hc
    from extant.rules import path_pointer as rule_path_pointer
    repo, commit = git_repo
    commit("docs/plan.md", "# plan\n", "docs: plan")

    scans: list[str] = []
    real = rule_path_pointer._path_pointer_sites_uncached

    def counted(ctx, text):
        scans.append(text)
        return real(ctx, text)

    monkeypatch.setattr(rule_path_pointer, "_path_pointer_sites_uncached",
                        counted)

    # The SAME string object for both halves, which is what the memo keys on.
    # An equal-but-distinct string would make this pass for the wrong reason.
    text = "**Plan:** `docs/plan.md` and see `docs/gone.md`.\n"
    hc.validate(repo, text, has_entries=False)
    hc.count_examined(repo, text)
    assert len(scans) == 1, (
        f"the path-pointer scan ran {len(scans)} times for one document")


def test_a_changed_path_pointer_pattern_is_not_answered_from_the_previous_one(
        git_repo, reconfigure) -> None:
    """The half of the key `_STRIPPED` is missing, checked on the new memo.

    `_path_pointer_sites` reads the text, the PATTERN and the document FORMAT,
    and all three are in its key. Keyed on text identity alone it would be
    `_STRIPPED` (extant/text.py) again, whose value depends on `doc.doc_format`
    while its key does not - a known latent bug recorded there rather than one
    to copy.

    Both halves are exercised against the same text OBJECT, which is the
    arrangement an incomplete key cannot survive. The format half runs first,
    because `reconfigure` holds until teardown and would otherwise leave the
    replacement pattern in place for it.
    """
    import re as _re

    from extant import session as hc
    from extant import text as text_mod
    from extant.rules import path_pointer as rule_path_pointer
    repo, _commit = git_repo

    # `Example::` opens a literal block in reStructuredText and is ordinary
    # prose in markdown, so the indented pointer below is code in one reading
    # of this object and a claim in the other.
    #
    # `_STRIPPED` is cleared between the two readings, and that is the point
    # rather than a convenience: it is the memo whose key omits `doc_format`,
    # so left in place it hands the markdown blanking back for the second
    # reading and BOTH answers come out at 1 whatever this rule's key is. That
    # is the known latent bug recorded in extant/scope.py, not this memo's, and
    # clearing it is what isolates the key under test from it. Remove the two
    # lines and this assertion stops discriminating.
    both = "Example::\n\n    see `docs/plan.md` for it\n"
    text_mod._STRIPPED.clear()
    hc.set_document(doc_format="markdown")
    as_markdown = rule_path_pointer.examined(hc.context(repo), both)
    text_mod._STRIPPED.clear()
    hc.set_document(doc_format="rst")
    as_rst = rule_path_pointer.examined(hc.context(repo), both)
    hc.set_document(doc_format="markdown")
    assert (as_markdown, as_rst) == (1, 0), (
        f"the same text object read as markdown and as reStructuredText gave "
        f"{as_markdown} and {as_rst}; a key without the format answers the "
        f"second reading from the first")

    text = "see `docs/plan.md` for it\n"
    first = rule_path_pointer.examined(hc.context(repo), text)
    assert first == 1, (
        f"the default pattern found {first} pointers in the fixture, so the "
        f"half below would pass against any implementation at all")

    # A pattern that requires a marker this line does not carry.
    reconfigure(path_pointer=_re.compile(
        r"(?:\*\*Blueprint:\*\*)[^`\n]{0,40}`([\w./-]+\.md)`", _re.IGNORECASE))
    assert rule_path_pointer.examined(hc.context(repo), text) == 0, (
        "the same text object was answered from the previous pattern's memo, "
        "so a reconfigured `path_pointer` would never reach the scanner")


def test_the_path_pointer_denominator_did_not_move(git_repo) -> None:
    """The count must be what the blob scan it replaced counted.

    `examined` used to run `path_pointer.findall` over the whole prose blob;
    it now sums the per-line scan `check` reads. The two are NOT identical by
    construction - `[^`\n]{0,40}` in the middle of the pattern excludes `\n`
    but not the other separators `str.splitlines` breaks on, so a blob match
    could in principle straddle one - which is why the equality is measured
    here rather than asserted in a comment.

    Measured over this repository's own documents, and over 39 documents and
    58,067 lines from two repositories outside the suite: the same 33 pointers
    both ways. Where they could differ the per-line number is the honest one,
    because a pointer the line loop cannot reach is one `check` never examined.
    This goes red if a pattern edit separates them, which is the event that
    would otherwise move the denominator without saying so.

    The sibling rule `dead-release-tag` was measured the same way and does NOT
    agree: `release_tag` joins its two halves with `\\s+`, which matches a
    newline, so its blob scan finds `shipped\\nas 0.27.0` in this repository's
    CHANGELOG.md and its line loop cannot. It was left alone for that reason.
    """
    import subprocess

    from extant import session as hc
    from extant.rules import path_pointer as rule_path_pointer
    from extant.text import format_for, prose
    repo, commit = git_repo
    commit("README.md", "# r\n", "docs: readme")
    ctx = hc.context(repo)

    # TWO pointers on ONE line, which the corpus below does not happen to
    # contain: without this the count is one per line either way and an
    # `examined` returning the number of matching LINES passes the whole test.
    # Observed doing exactly that before this case was added.
    crowded = "see `docs/a.md` and read `docs/b.md` today\n"
    assert rule_path_pointer.examined(ctx, crowded) == 2, (
        "the denominator counts pointers, not lines carrying one")

    root = Path(__file__).resolve().parent.parent
    listed = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            check=True)
    documents = 0
    lines = 0
    total = 0
    for relative in listed.stdout.splitlines():
        if not relative.lower().endswith((".md", ".mdx", ".rst")):
            continue
        try:
            with open(root / relative, encoding="utf-8", newline="") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        hc.set_document(doc_format=format_for(relative))
        ctx = hc.context(repo)
        blob = len(ctx.config.path_pointer.findall(prose(ctx.doc, text)))
        counted = rule_path_pointer.examined(ctx, text)
        assert counted == blob, (
            f"{relative}: the per-line denominator counts {counted} pointers "
            f"where the blob scan it replaced counted {blob}")
        documents += 1
        lines += len(text.splitlines())
        total += blob
    hc.set_document(doc_format="markdown")
    print(f"compared {documents} documents, {lines} lines, "
          f"{total} pointers counted both ways")
    assert documents >= 5 and total >= 5, (
        f"only {documents} documents and {total} pointers, so agreement here "
        f"would prove nothing; the checkout or the filter is wrong")
