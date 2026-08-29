"""How many git processes a run is allowed to start.

Nothing in this project has ever counted them, and the cost is on the record:
one `git remote get-url` per document went unnoticed until it was 70 per cent
of a sweep. A rule that adds one call per document costs 30 ms x N and no
correctness test notices.

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
MEASURED = 6
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
      get-url`, and which `count_examined` asks for a second time.

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
        f"- `PR #1 merged into main at {claim_only}`\n\n"
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
        f"{len(spawns)} git processes for one document. Each costs about 30 ms "
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
    # 13, with no spare margin, for the same measured reason CEILING carries
    # none above: with a spare, this exact regression - a `with run_scope():`
    # quietly deleted from main() - left the budget green. If this grows
    # because of a genuine new question, raise the number here and say why in
    # the commit; if it grows because a run_scope() was removed, that is the
    # regression this test exists to catch.
    #
    # Was 12. Phase 25 gave NEXT_SESSION.md a branch claim - the entry names
    # the branch the work was done on - and `unknown-branch` answers that with
    # one `rev-parse --verify <branch>`. That is a question this document did
    # not previously ask, not a scope that stopped being held: the other twelve
    # are unchanged, and the ref table, rev-list and tag lookups still appear
    # exactly twice, once per validate() + count_examined() pair. A removed
    # run_scope() would have duplicated those instead, which is the difference
    # this comment exists to record.
    assert len(spawns) <= 13, (
        f"{len(spawns)} git processes for --verify on this repository, above "
        f"the 13 measured with run_scope() wrapping main()'s own validate() "
        f"+ count_examined() pairs. If this is a genuine new question, raise "
        f"the number here and say why in the commit; if a `with run_scope():` "
        f"was removed from main(), that is the regression this test exists "
        f"to catch.")
