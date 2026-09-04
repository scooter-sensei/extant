"""How many git processes a run is allowed to start.

Nothing in this project has ever counted them, and the cost is on the record:
one `git remote get-url` per document went unnoticed until it was 70 per cent
of a sweep. A rule that adds one call per document costs about 28 ms x N -
measured here, median of 20 - and no correctness test notices.

Counted at the subprocess boundary, not at the wrapper. `_git_soft` delegates
to `_git`, so counting wrapper entries double-counts every soft call, and that
mistake was made while measuring for this plan. It is also the only vantage
point that sees BOTH populations: the calls routed through `ctx.git` and the
six that run git through subprocess directly because a stdin-fed batch does not
fit `run(repo, *args)`. A budget that counted only the seam would be a budget
with a hole in exactly the most expensive place - the `cat-file` batches.

The document below is not a minimal one, deliberately. A fixture that reaches
one rule spawns one process and passes any ceiling it is given, so this one is
built to reach every rule that asks git anything: a resolvable SHA, a dead one,
a merge claim, a release claim, and a self-pin. Five rules, six spawns, and
that coverage is what makes the ceiling mean something - the brief's own
fixture reached two of them and would have passed at three spawns while
reporting a budget of six.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))

# What this fixture spawns today, and the ceiling is exactly that, with no
# headroom.
#
# The plan asked for one spare, and that was tried and abandoned here for a
# measured reason rather than a stylistic one: with a spare, adding a
# gratuitous `git status` to a rule left the budget GREEN. The spare's own
# stated purpose was that "a rule legitimately gaining a question is a decision
# someone makes rather than an accident", and a spare is precisely what lets
# the first such gain in as an accident. Zero headroom makes the decision
# unavoidable: gain a question, come here, raise the number, say why in the
# commit. That is the whole mechanism.
#
# Six rather than the five measured on this repository's own document, and the
# difference is coverage rather than drift. That document carries no
# self-pinning install snippet, so `dead-pinned-ref` never reached git there;
# this fixture adds one, which is the sixth spawn. Both numbers come from the
# same place - one validate() plus one count_examined(), counted at the
# subprocess boundary - and the before/after on the real document was 7 to 5.
# Against the code as it stood at cad97bb this fixture spawns 8, so both
# assertions below have been watched failing on real code rather than only on
# a mutation.
#
# FOUR SINCE THE SPAWN WORK, and it is lowered here rather than left passing.
# The assertion is `<=`, so three of these four could have gone away in silence
# and left this green - which is exactly the spare the paragraph above refuses,
# arriving by omission instead of by decision. What went:
#
#   -2  `rev-parse --verify --quiet <ref>^{commit}`. `resolve_ref` looks a
#       QUALIFIED ref up in the table it already built, and `dead-pinned-ref`
#       asks `resolve_ref` instead of asking git itself. On this repository's
#       own document that was 14 of 24 spawns.
#   -1  `remote get-url origin`, read out of the config file by `remote_url`
#       with a guard that falls back to the spawn for any syntax it declines
#       to parse.
#   +1  `log --diff-filter=R`, which is new COVERAGE rather than a new cost -
#       see the dead pointer in `_document` below and the note there on why
#       the fixture grew instead of the floor shrinking.
MEASURED = 4
CEILING = MEASURED


def _document(sha: str, claim_only: str, dead: str) -> str:
    """A document that makes every git-asking rule ask something.

    Each line is here for a named reason, and removing any of them silently
    lowers what this budget covers:

    * the backticked live SHA and the dead one reach `dead-sha`, which is the
      `cat-file --batch-check` batch;
    * "merged to `main` at" reaches `false-merge-claim`, which is the ref scan
      and the ancestry `rev-list`;
    * "shipped in v1.0.0" reaches `dead-release-tag`, which is the tag lookup;
    * the pre-commit block reaches `dead-pinned-ref`, which is `remote
      get-url`, and which `count_examined` asks for a second time;
    * the missing design document reaches `dead-path-pointer`, which asks
      `renamed_to` where the file went and is the `log --diff-filter=R` scan.

    THE LAST ONE IS NEW, and it is a re-fixturing rather than an addition for
    its own sake. Answering the remote from the config file took this document
    from four spawns to three, and the duplicate-pinning test below asserts a
    FLOOR of four so that it cannot report "no repeats" about a fixture that
    reached nothing. Lowering that floor would have kept the suite green by
    making the guard weaker, which is the move it exists to prevent - so the
    document gained a rule instead. `dead-path-pointer` was not covered here at
    all before, and it is the only remaining rule in this package that spawns a
    process of its own.

    `claim_only` is the load-bearing one and is the reason this fixture is not
    smaller. It appears ONLY inside a fully backticked phrase, copied in shape
    from a real corpus repository rather than invented, so `_BACKTICKED`
    captures the whole sentence and the commit inside it is not a backticked
    TOKEN; being inside backticks, it is not a bare candidate either. Only the
    merge-claim rule sees it.

    That is what separates the two possible fixes. A per-token memo would still
    have left the claim rule spawning its own batch for this one token, so the
    document's union has to be resolved in one go. Written with `sha` in both
    places instead, the test would pass against a memo alone and would not pin
    what it says it pins.
    """
    return (
        f"## Phase 1 - the seam (complete, 2026-01-01)\n\n"
        f"- The work was merged to `main` at `{sha}`.\n"
        f"- Shipped in v1.0.0 that week.\n"
        f"- See `{sha}` and bare {dead} for the detail.\n"
        f"- `PR #1 merged into main at {claim_only}`\n"
        f"- **Design:** `docs/gone.md`\n\n"
        f"```yaml\n"
        f"repos:\n"
        f"  - repo: https://github.com/acme/widget\n"
        f"    rev: v1.0.0\n"
        f"```\n"
    )


def _counted_run(monkeypatch, spawns: list[str]):
    """Record the WHOLE command line of every git process, then run it for real.

    The whole line rather than `git <sub>`, because the coarse form cannot tell
    two different questions apart. `dead-release-tag` asks for
    `refs/tags/v1.0.0^{commit}` and `dead-pinned-ref` asks for
    `v1.0.0^{commit}`; both start `rev-parse --verify` and neither is a repeat
    of the other. Keying on the prefix reported a duplicate that was not one,
    which is the direction of error that gets a check disabled.

    It still catches every real duplicate below, because both of those were
    byte-identical command lines: two `remote get-url origin`, and two
    `cat-file --batch-check` whose inputs differ on STDIN rather than in argv.
    """
    real = subprocess.run

    def counted(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            spawns.append(" ".join(str(c) for c in cmd[1:]))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counted)


def _repo_with_a_document(git_repo):
    """A repository whose origin is itself, holding the document above."""
    repo, commit = git_repo
    sha = commit("a.py", "a = 1\n", "feat: a").strip()[:9]
    # A SECOND commit, so the claim-only reference names a different object
    # from the one the SHA rule already asks about. Reusing the first would
    # make the union indistinguishable from a per-token memo; see `_document`.
    claim_only = commit("b.py", "b = 2\n", "feat: b").strip()[:9]
    # An origin, so `dead-pinned-ref` has something to govern the pin with.
    # Without one `_pinned_refs` returns early and the rule examines nothing -
    # which is a passing budget covering one rule fewer, invisibly.
    subprocess.run(["git", "remote", "add", "origin",
                    "https://github.com/acme/widget"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo, check=True,
                   capture_output=True)
    text = _document(sha, claim_only, "deadbee1")
    commit("NEXT.md", text, "feat: doc")
    return repo, text


def test_a_single_validation_stays_within_its_spawn_budget(
        monkeypatch, git_repo) -> None:
    from extant import session as hc

    repo, text = _repo_with_a_document(git_repo)
    spawns: list[str] = []
    _counted_run(monkeypatch, spawns)

    with hc.run_scope():
        hc.validate(repo, text, doc="NEXT.md")
        hc.count_examined(repo, text)

    assert spawns, "no git processes were spawned; this test would pass vacuously"
    print(f"checked one validate + count_examined: {len(spawns)} git spawns "
          f"against a ceiling of {CEILING}")
    for cmd in spawns:
        print(f"    git {cmd}")
    assert len(spawns) <= CEILING, (
        f"{len(spawns)} git processes for one document. Each costs about 28 ms "
        f"on Windows and this multiplies by every file in a sweep. If the new "
        f"call is necessary, raise CEILING here and say why in the commit.")


def test_the_same_question_is_not_asked_twice(monkeypatch, git_repo) -> None:
    """The two duplicates measured before the refactor, pinned shut.

    `remote get-url origin` ran twice because `validate()` opens a scope per
    call and drops it, so `count_examined` - the other half of examining the
    same document - started cold and re-asked. `run_scope()` is what spans the
    two halves.

    `cat-file --batch-check` ran twice for a different reason than the plan
    first recorded, and the corrected one is the point of the last line of the
    fixture document. It was never backticked-versus-bare: those two candidate
    kinds have shared one batch since the rule was written. It was one batch
    per RULE - `dead-sha` for its tokens and `false-merge-claim` for the commit
    each claim names - and the sets overlap without matching. Measured on this
    repository's own document: 29 tokens against 2, sharing 1. Resolving the
    document's union in one batch is what closes it, and a per-token memo alone
    would not have: the claim in `PR #1 merged into main at <sha>` is inside
    backticks as a phrase, so it is not a backticked token and not a bare one
    either.
    """
    from extant import session as hc

    repo, text = _repo_with_a_document(git_repo)
    spawns: list[str] = []
    _counted_run(monkeypatch, spawns)

    with hc.run_scope():
        hc.validate(repo, text, doc="NEXT.md")
        hc.count_examined(repo, text)

    # The denominator, and not a formality. This assertion can only report an
    # ABSENCE of repeats, so a fixture that spawned nothing would satisfy it
    # while covering nothing at all.
    assert len(spawns) >= 4, (
        f"only {len(spawns)} git spawn(s); with this few the fixture is not "
        f"reaching the rules whose duplicate questions this pins: {spawns}")
    repeated = {c for c in spawns if spawns.count(c) > 1}
    print(f"checked {len(spawns)} spawns for repeats: {spawns}")
    assert not repeated, f"asked twice in one run: {sorted(repeated)}"


def _explain_the_remote(spawns: list[str]) -> None:
    """Say why `remote_url` declined, when it did, WITHOUT printing the config.

    This exists because the count above is now environment-dependent and the
    environment that disagreed was a CI runner, where the only evidence
    available is a log. Five `remote get-url origin` calls mean the config fast
    path declined five times, and every candidate reason was reasoned about and
    reproduced locally without reproducing the decline - so the runner is asked
    directly instead.

    NOTHING HERE PRINTS A CONFIG VALUE. A checkout on a GitHub runner carries
    `http.<url>.extraheader` holding an authorization token, and a test that
    dumped `.git/config` to a public log to explain a spawn count would be a
    far worse defect than the one it was diagnosing. Only booleans, key names
    and section names come out.
    """
    if not any("remote get-url" in cmd for cmd in spawns):
        return
    from extant.git import _UNSETTLED_BY, _own_git_dir, common_git_dir, remote_url

    root = Path(".")
    shared = common_git_dir(root)
    own = _own_git_dir(root)
    print(f"  the remote was spawned for; diagnosing the fast path:")
    print(f"    common_git_dir  : {'found' if shared else 'None'}")
    print(f"    _own_git_dir    : {'found' if own else 'None'}")
    print(f"    remote_url      : "
          f"{'answered' if remote_url(root, 'origin') else 'declined'}")
    if own is not None:
        print(f"    config.worktree : {(own / 'config.worktree').is_file()}")
    if shared is None:
        return
    try:
        text = (shared / "config").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"    config unreadable: {exc.__class__.__name__}")
        return
    low = text.lower()
    print(f"    guard words     : "
          f"{[w for w in _UNSETTLED_BY if w in low] or 'none matched'}")
    print(f"    sections        : "
          f"{[l.strip() for l in text.splitlines() if l.strip().startswith('[')]}")
    print(f"    keys, all sections: "
          f"{sorted({l.split('=')[0].strip() for l in text.splitlines() if '=' in l})}")


def test_the_verify_cli_stays_within_its_own_spawn_budget(monkeypatch) -> None:
    """`main()`'s OWN use of run_scope(), not the fixture's.

    The two tests above open `hc.run_scope()` themselves and call `validate()`
    and `count_examined()` directly, so they pin the CONTEXT MANAGER working
    correctly - never whether `main()` actually opens one around its own two
    call sites (the primary document, and each extra document in its loop).
    That is a real hole, demonstrated by hand: delete `with run_scope():`
    from `main()` and both tests above stay green while `--verify` on this
    repository regresses. Only a test that drives `main()` itself can see
    that regression, so this one does - against the repository this checkout
    actually is, `--repo "."`, rather than a fixture, because the point is
    `main()`'s real argument parsing and control flow, not a synthetic
    document built to reach every rule.

    Tied to this repository's own git history as a result - its tags, its
    `extra_docs`, how many documents --verify touches - so it will need
    re-measuring if that history changes what --verify does here. This
    repository's suite already accepts that kind of upkeep for tests that
    read its own real files rather than a fixture (test_docs_match_code.py
    checks README.md, SKILL.md and pyproject.toml directly); this test
    extends the same idea to a spawn count instead of a document. Measured
    at the time of writing: 12 spawns.

    `conftest.py`'s `neutral_config` is autouse and has already pointed
    `CONFIG` at an empty temp directory by the time this test body runs -
    deliberately, so ordinary tests are not coupled to this repository's own
    `.extant.toml` (its extra_docs, most of all). This test is the declared
    exception: its whole point IS this repository's real configuration, since
    that is what decides how many documents --verify touches and therefore
    how many spawns are budgeted. `reload_config(hc.REPO_ROOT)` re-does
    exactly what import did, and `neutral_config`'s own teardown restores
    CONFIG afterward regardless of what this test does to it - it saves
    before neutralising and unconditionally puts that back, not whatever was
    live when the test ended - so nothing leaks to the next test.
    """
    from extant import session as hc
    from extant import cli

    hc.reload_config(hc.REPO_ROOT)

    spawns: list[str] = []
    real = subprocess.run

    def counted(cmd, *a, **kw):
        if cmd and str(cmd[0]) == "git":
            spawns.append(" ".join(str(c) for c in cmd[1:]))
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", counted)

    exit_code = cli.main(["--verify", "--repo", "."])

    assert spawns, "no git processes were spawned; this test would pass vacuously"
    print(f"checked hc.main(['--verify', '--repo', '.']): {len(spawns)} git "
          f"spawn(s), exit code {exit_code}")
    for cmd in spawns:
        print(f"    git {cmd}")
    _explain_the_remote(spawns)
    # 24, with no spare margin, for the same measured reason CEILING carries
    # none above: with a spare, this exact regression - a `with run_scope():`
    # quietly deleted from main() - left the budget green. If this grows
    # because of a genuine new question, raise the number here and say why in
    # the commit; if it grows because a run_scope() was removed, that is the
    # regression this test exists to catch.
    #
    # 23 since 0.24.1, and the jump is a DECISION rather than drift. Ten
    # entries used to say "This work is version X.Y.Z", which `release_tag`
    # does not read - it matches a version only after `released`, `shipped` or
    # `tagged` followed by `in`, `as` or `at` - so every historical release
    # claim in this file sat there looking checked and read by nothing. They
    # now say "shipped in X.Y.Z" and are checked, at ONE SPAWN PER DISTINCT TAG
    # CLAIMED: fifteen claims naming thirteen distinct tags, and thirteen
    # `rev-parse --verify --quiet refs/tags/vX^{commit}` - the lookup is per
    # TAG, not per claim, so a claim naming a tag another claim already named
    # is free. That is the number to reach for before adding another: a new
    # claim about an already-claimed release costs nothing, a new one about a
    # new release costs a spawn on the command the post-commit hook runs after
    # every commit.
    #
    # 24 since 0.25.0, and this is that cost being paid rather than drift.
    # Phase 26 claims "shipped in 0.25.0", a tag no earlier entry names, so it
    # buys one `rev-parse --verify --quiet refs/tags/v0.25.0^{commit}` and
    # nothing else. Checked against the alternative before raising the number,
    # because the two causes look identical from the count alone: the ref
    # table and `rev-list main` each still appear exactly twice, so no
    # `run_scope()` went missing. A future release entry costs one more; a
    # future entry about 0.25.0 costs nothing.
    #
    # TWO of the fifteen took a different wording, and the difference is the
    # point. Both say "no version was cut for that work, so it remained ...
    # 0.19.0" - a statement that no release happened. "Shipped in 0.19.0" would
    # have asserted one that did not, so they say "remained RELEASED AS 0.19.0"
    # instead: same meaning, and `release_tag` reads it. They were left
    # unchecked for a while on the belief that no faithful checkable wording
    # existed, which was a failure of imagination rather than a property of the
    # rule - the trigger words are `released`, `shipped` and `tagged`, and only
    # one of the three had been tried.
    #
    # The shape of the regression is unchanged by any of this: the ref table,
    # the rev-list and the remote lookups still appear exactly TWICE, once per
    # validate() + count_examined() pair, where a deleted `with run_scope():`
    # duplicates them. Count those, not the total, before raising this again.
    #
    # It went to 13 once before and came back down. Phase 25 also named the
    # branch the work was written on, `unknown-branch` answered with a
    # `rev-parse --verify <branch>`, and that claim was true only in the
    # checkout that wrote it - `--verify` failed on CI against a clone, so the
    # claim came out and its spawn with it. Both raises are the shape a
    # legitimate one takes and neither is the shape of the regression: the ref
    # table, the rev-list and the remote lookups still appear exactly TWICE,
    # once per validate() + count_examined() pair. A deleted `with run_scope():`
    # duplicates those instead, which is what to look for before raising this
    # number again.
    #
    # FIVE SINCE THE SPAWN WORK, from 24, and every one of the nineteen that
    # went was a question this repository already had the answer to:
    #
    #   -14  `rev-parse --verify --quiet refs/tags/vX^{commit}`, one per
    #        DISTINCT tag claimed. `resolve_ref` tried the ref table before
    #        shelling out and the table is keyed by SHORT name, so every
    #        qualified lookup missed by construction. It reads both spellings
    #        now, so the whole paragraph above about a new release entry
    #        costing a spawn no longer holds: a release claim is free.
    #    -5  `remote get-url origin`, one per document, read out of the config
    #        file instead - which is why widening this mode's RunScope was
    #        refused rather than taken.
    #
    # AND THE TOTAL STOPPED BEING THE THING TO ASSERT, which is what a red CI
    # run taught rather than a review. Before this work every question was
    # spawned unconditionally, so the count was a constant. Two of them are now
    # conditional on the CHECKOUT rather than on the code:
    #
    #   `remote get-url origin`   0 where `remote_url` can read the config, 5
    #                             where it declines. A GitHub Actions runner
    #                             declines: measured, its `.git/config` carries
    #                             four `[includeIf "gitdir:..."]` sections and a
    #                             `config.worktree` beside it, and either alone
    #                             is a reason this cannot know whether the
    #                             remote is redefined elsewhere. The guard is
    #                             working; the count simply is not a constant.
    #   the trunk lookup          `rev-list main` where a local `main` exists,
    #                             `rev-parse --verify --quiet main^{commit}`
    #                             where it does not, and NEITHER on a checkout
    #                             where `main` does not resolve at all. A
    #                             pull_request checkout is a detached merge ref,
    #                             so this varies by how CI checks out.
    #
    # Measured: 5 on a developer checkout, 5 on a fresh clone - the same total
    # by two different routes, `rev-list main` there and
    # `rev-parse --verify --quiet main^{commit}` here - and 8 on a runner.
    # A ceiling of 8 would hold everywhere and hand both of the others three
    # spare - exactly the headroom the top of this file refuses - so the total
    # is not what is asserted any more. What is asserted is the INVARIANT part
    # exactly, and then that everything else is one of the two questions above
    # and nothing new. A genuine new question still fails here in every
    # environment; a checkout that answers one of these for free does not.
    from extant.config import load_config

    trunk = hc._ACTIVE.trunk
    # REPO_ROOT rather than ".", so the count does not depend on where pytest
    # was invoked from - the same reason `reload_config` above takes it.
    documents = 1 + len(load_config(hc.REPO_ROOT).extra_docs)

    # EXACT COMMANDS, not prefixes, and each kind counted. A first version of
    # this allowed anything starting `rev-parse --verify --quiet `, which reads
    # as harmless and is not: the fourteen tag lookups this whole change
    # removed have exactly that prefix. Reverting the qualified-ref fix took
    # this command from 5 spawns to 19 and left this test GREEN, because all
    # fourteen matched the allowance. A loose prefix in an allowlist is a hole
    # shaped like the regression it was written next to.
    kinds = {
        "ref table": [c for c in spawns if c.startswith("for-each-ref ")],
        "sha batch": [c for c in spawns if c == "cat-file --batch-check"],
        "remote": [c for c in spawns if c == "remote get-url origin"],
        # Two spellings of ONE question - which commits the trunk contains.
        # `rev-list` where a local trunk branch exists, `rev-parse` where it
        # does not and the name has to be resolved first.
        "trunk": [c for c in spawns
                  if c in (f"rev-list {trunk}",
                           f"rev-parse --verify --quiet {trunk}^{{commit}}")],
    }
    accounted = [c for group in kinds.values() for c in group]
    print("  " + ", ".join(f"{name} x{len(group)}"
                           for name, group in kinds.items()))

    # The invariants. Neither varies by checkout, and both are the regression
    # this test exists to catch: a deleted `with run_scope():` rebuilds the ref
    # table per document, and two rules resolving their own SHAs re-batch.
    assert len(kinds["ref table"]) == 2, (
        f"the ref table was built {len(kinds['ref table'])} times, not twice - "
        f"once per validate() + count_examined() pair. More than two means a "
        f"`with run_scope():` was removed from main() and every document is "
        f"rebuilding it; this is the regression this test exists to catch.")
    assert len(kinds["sha batch"]) == 1, (
        f"{len(kinds['sha batch'])} `cat-file --batch-check` calls; the "
        f"document's SHA union is resolved in one batch, and a second means "
        f"two rules are each spawning their own again.")

    # The two the CHECKOUT decides, bounded rather than allowed. Zero on a
    # checkout that answers them for free, and never more than one per document
    # or one per validate/count_examined pair.
    assert len(kinds["remote"]) in (0, documents), (
        f"{len(kinds['remote'])} `remote get-url origin` for {documents} "
        f"documents: it is one per document where the config cannot be read "
        f"and none where it can, so any other number is a new shape.")
    assert len(kinds["trunk"]) <= 2, (
        f"{len(kinds['trunk'])} trunk lookups; it is memoised per run scope, "
        f"so more than one per validate() + count_examined() pair means the "
        f"memo stopped working.")

    unexpected = [c for c in spawns if c not in accounted]
    assert not unexpected, (
        f"--verify asked something new: {sorted(set(unexpected))}. If it is a "
        f"genuine new question, add it above and say why in the commit - "
        f"including the fourteen `rev-parse --verify --quiet refs/tags/...` "
        f"lookups, which is what this catches if the ref table stops being "
        f"read for qualified refs.")
