"""Release claims read against the conventions a repository actually uses.

Measured on a 30-repository corpus, `dead-release-tag` and `dead-pinned-ref`
fired four times between them and every one was wrong. Each cause here is a
project habit rather than an author's error, so the tests name the repository
the habit was measured on.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def _reset():
    import extant_collect as hc
    # One fresh scope, not a list of cache names to keep in step with the
    # code. The list form went stale silently: `_TAGS` stayed in it for four
    # commits after `_tags()` stopped reading it.
    hc._SCOPE = hc.RunScope()
    # These tests are about RESOLVING a claimed version against the tags a
    # repository really uses, so they assert what `release_claims_name_our_tags`
    # asserts: the claims are about this repository. The default is off, and
    # the two tests at the bottom of this file are the ones that pin that.
    hc._RELEASE_CLAIMS_ARE_OURS = True


def _tags(repo, text):
    from extant_collect import validate_release_tags
    _reset()
    return [f.kind for f in validate_release_tags(repo, text)]


# --- the prefix a project puts before its version ----------------------------

def test_a_claim_resolves_under_the_prefix_this_repository_uses(git_repo) -> None:
    """Half the ecosystem tags `v1.2.3` and half tags `1.2.3`.

    Measured: black tags `18.3a0`, poetry `0.1.0`, ruff and uv likewise, all
    bare; symfony tags `v8.0.0`. A claim written in the other convention
    resolved to nothing, so the rule reported a release that had shipped.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "2.1.0")            # tagged BARE, claimed with a `v`

    assert "dead-release-tag" not in _tags(repo, "Released in v2.1.0.\n")


def test_the_other_direction_too(git_repo) -> None:
    """Tagged with a `v`, claimed bare. symfony's shape."""
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v2.1.0")

    assert "dead-release-tag" not in _tags(repo, "Released in 2.1.0.\n")


def test_a_version_that_was_never_tagged_is_still_reported(git_repo) -> None:
    """The control. Prefix trying must not forgive a release that never
    happened, or the rule stops doing anything at all."""
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v2.1.0")

    assert "dead-release-tag" in _tags(repo, "Released in 9.9.9.\n")


def test_a_claim_naming_a_series_rather_than_a_tag(git_repo) -> None:
    """A claim names a series far more often than it names a tag.

    Symfony's own bug-triage guide says work "shipped in 8.0" and no tag is
    called that - the tags are `v8.0.0`, `v8.0.1` and so on. Reporting that as
    a dead release is pedantry about a number, not a fact about git.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v8.0.0")

    assert "dead-release-tag" not in _tags(repo, "Shipped in 8.0 last year.\n")


def test_a_series_that_matches_no_tag_is_still_reported(git_repo) -> None:
    """The control for the series case. `8.5` must not be forgiven by `v8.0.0`
    merely because both begin with an 8."""
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v8.0.0")

    assert "dead-release-tag" in _tags(repo, "Shipped in 8.5 last year.\n")


def test_a_pattern_capturing_the_whole_tag_name_still_resolves(git_repo) -> None:
    """A project can configure `release_tag` to capture its entire tag name.

    The installer derives exactly such a pattern from repositories tagging
    `release-1.2.3` or `api@2.0.0`, and for those the captured text IS the tag.
    Trying this repository's prefixes FIRST turns `release-1.2.3` into
    `release-release-1.2.3`, resolves nothing, and reports a shipped release as
    dead - verified by reconstructing the pre-fix order, which returns None
    here.

    Every other test in this file uses a bare or `v`-prefixed version, so none
    of them could have caught it. The scenario harness did.
    """
    import re
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "-a", "release-1.2.3", "-m", "release")
    git(repo, "tag", "-a", "api@2.0.0", "-m", "package")

    previous = hc._RELEASE_TAG
    hc._RELEASE_TAG = re.compile(r"[Ss]hipped in `([\w.@-]+)`")
    try:
        assert "dead-release-tag" not in _tags(repo, "Shipped in `release-1.2.3`.\n")
        # The control, under the same pattern: a tag that was never cut.
        assert "dead-release-tag" in _tags(repo, "Shipped in `release-9.9.9`.\n")
    finally:
        hc._RELEASE_TAG = previous


def test_a_literal_tag_name_beginning_with_v_is_not_mangled(git_repo) -> None:
    """The case that makes trying the literal spelling FIRST load-bearing.

    A mutation campaign found the first version of this file could not tell
    the two mechanisms apart: both a literal-first lookup and an empty entry in
    the prefix list satisfied `release-1.2.3`, so removing either left the
    suite green and both mutations SURVIVED.

    Resolving that is what produced this test and deleted the empty prefix. A
    tag whose name merely BEGINS with `v` is the case only literal-first
    handles: `removeprefix("v")` turns `vendor-1.0` into `endor-1.0`, and no
    prefix this repository uses reconstructs it. The empty entry was dead code
    - a tag starting with a digit already derives `""` as its prefix.
    """
    import re
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "-a", "vendor-1.0", "-m", "vendored")

    previous = hc._RELEASE_TAG
    hc._RELEASE_TAG = re.compile(r"[Ss]hipped in `([\w.@-]+)`")
    try:
        assert "dead-release-tag" not in _tags(repo, "Shipped in `vendor-1.0`.\n")
        assert "dead-release-tag" in _tags(repo, "Shipped in `vendor-9.9`.\n")
    finally:
        hc._RELEASE_TAG = previous


# --- an integration branch that is not there ---------------------------------

def test_a_tag_is_not_judged_when_no_integration_branch_exists(git_repo) -> None:
    """symfony has no `main` and no `master`; its branches are version numbers
    and its default is `8.2`. With the default configuration the rule asked
    whether each tag was an ancestor of a branch that does not exist, got
    "no", and reported every release as shipped on nothing.

    Measured across 30 repositories: 3 are in this position - laravel/framework
    on `13.x` and slate on `migration-notice` are the others - so it is about a
    tenth of real projects.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v2.1.0")
    git(repo, "branch", "-m", "8.2")     # no main, no master, as symfony has

    assert "dead-release-tag" not in _tags(repo, "Released in v2.1.0.\n")


def test_a_tag_on_no_branch_is_still_reported_when_a_trunk_exists(git_repo) -> None:
    """The control. Where an integration branch DOES exist, a tag that never
    reached it is still the finding this rule is for - a release abandoned or
    rewritten away."""
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "checkout", "-q", "-b", "abandoned")
    commit("b.py", "b = 1\n", "feat: b")
    git(repo, "tag", "v2.1.0")
    git(repo, "checkout", "-q", "main")

    assert "dead-release-tag" in _tags(repo, "Released in v2.1.0.\n")


# --- how a pin is written ----------------------------------------------------

def _pins(repo, text):
    from extant_collect import validate_pinned_refs
    import extant_collect as hc
    hc._SCOPE = hc.RunScope()
    return [f.kind for f in validate_pinned_refs(repo, text)]


def test_an_empty_rev_is_a_placeholder_not_a_broken_pin(git_repo) -> None:
    """`rev: ''` is pre-commit's OWN documented placeholder - the state a
    snippet ships in for `pre-commit autoupdate` to fill.

    python-poetry/poetry ships two of them in `docs/pre-commit-hooks.md`, and
    both were reported as pins that do not exist. Reporting it accuses a
    project of following the idiom its own tool prescribes.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "remote", "add", "origin", "https://github.com/o/r")

    text = ("```yaml\n-   repo: https://github.com/o/r\n"
            "    rev: ''  # add version here\n    hooks: []\n```\n")
    assert _pins(repo, text) == []


def test_a_quoted_rev_is_the_same_pin_as_a_bare_one(git_repo) -> None:
    """`rev: 'v1.2.3'` names the same tag as `rev: v1.2.3`, and looking it up
    with the quotes attached finds nothing.

    Measured across 30 repositories: 69 bare, 4 quoted, 2 empty. No quoted one
    happened to govern its own repository, so this was a false positive waiting
    on the first project to pin itself that way.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v1.2.3")
    git(repo, "remote", "add", "origin", "https://github.com/o/r")

    text = ("```yaml\n-   repo: https://github.com/o/r\n"
            "    rev: 'v1.2.3'\n    hooks: []\n```\n")
    assert _pins(repo, text) == []


def test_a_quoted_rev_that_does_not_exist_is_still_reported(git_repo) -> None:
    """The control. Stripping quotes must not stop the rule reading the pin."""
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "remote", "add", "origin", "https://github.com/o/r")

    text = ("```yaml\n-   repo: https://github.com/o/r\n"
            "    rev: 'v9.9.9'\n    hooks: []\n```\n")
    assert _pins(repo, text) == ["dead-pinned-ref"]


# --- how a merge claim writes its commit ------------------------------------

def _merge(repo, text):
    from extant_collect import validate_merge_claims
    import extant_collect as hc
    hc._SCOPE = hc.RunScope()
    return [f.kind for f in validate_merge_claims(repo, text)]


def test_a_merge_claim_may_write_its_commit_without_backticks(git_repo) -> None:
    """The rule's largest measured blind spot.

    basilisk-labs/agentplane writes 32 claims as
    `PR #499 merged into main at 6ff1f4ac` - ref and commit both bare - and the
    rule examined ZERO of them across 7,489 documentation files, because the
    pattern required the commit in backticks. Widened, the corpus goes from 3
    claims examined to 35 and gains no findings: all 32 are true.
    """
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "chore: init")     # main must exist to branch off
    git(repo, "checkout", "-q", "-b", "feature")
    sha = commit("f.py", "f = 1\n", "feat: work")
    git(repo, "checkout", "-q", "main")

    text = f"PR #1 merged into main at {sha[:8]}.\n"
    assert "false-merge-claim" in _merge(repo, text), (
        "the commit is not on main, and a bare-spelled claim must be judged")

    git(repo, "merge", "--no-ff", "-q", "-m", "merge", "feature")
    assert "false-merge-claim" not in _merge(repo, text)


def test_a_longer_hex_run_is_not_truncated_into_a_commit(git_repo) -> None:
    """The boundary the closing backtick used to provide.

    Without a trailing guard, `at 0123...` of 46 hex characters matches its
    first 40 and the rule reports a commit nobody wrote.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")

    long_hex = "0" * 46
    assert not hc._MERGE_CLAIM.findall(f"merged to main at {long_hex}\n")


# --- whose release is it, anyway ---------------------------------------------

def test_a_claimed_release_that_was_never_tagged_is_silent_by_default(git_repo) -> None:
    """The default, and the measurement behind it.

    "No such tag exists" is not a question git can settle. A version in prose
    can name a git tag, an npm or PyPI release, a sub-package, a plugin, or
    somebody else's toolchain, and nothing in the sentence says which. Measured
    across 15 repositories that write prose release claims, treating every one
    as a local tag was wrong 19 times out of 26: eugenelim/agent-ready-repo
    tags `credbroker-v0.4.0` and writes "shipped as 0.27.0"; 10CG/Aria tags to
    v1.5.0 and cites its plugin's v1.17.3 through v1.24.1.

    A range test was tried instead and does not separate the cases - two false
    positives sit inside the repository's own tag range - so this is opt-in
    rather than narrowed.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v1.0.0")

    _reset()
    hc._RELEASE_CLAIMS_ARE_OURS = False          # the shipped default
    from extant_collect import validate_release_tags
    kinds = [f.kind for f in validate_release_tags(repo, "Released in v9.9.9.\n")]
    assert "dead-release-tag" not in kinds, kinds


def test_the_settleable_half_is_checked_whatever_the_setting(git_repo) -> None:
    """The half that needs no assertion: the tag IS here, and it shipped on
    nothing. That was right 7 times out of 7 on the same corpus, so it is
    always checked - turning the setting off must not disable the rule."""
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "checkout", "-q", "-b", "abandoned")
    commit("b.py", "b = 1\n", "feat: b")
    git(repo, "tag", "v2.1.0")
    git(repo, "checkout", "-q", "main")

    _reset()
    hc._RELEASE_CLAIMS_ARE_OURS = False
    from extant_collect import validate_release_tags
    kinds = [f.kind for f in validate_release_tags(repo, "Released in v2.1.0.\n")]
    assert "dead-release-tag" in kinds, kinds


def test_an_annotated_tag_resolves_to_the_commit_it_tags(git_repo) -> None:
    """An annotated tag is an OBJECT, and its own SHA is in no rev-list.

    `^{commit}` dereferences it; the ref table gets the same answer from
    `%(*objectname)`, which is empty for a lightweight tag and the peeled
    commit for an annotated one. Drop the peel and every annotated release
    resolves to the tag object, is an ancestor of nothing, and gets reported as
    having shipped on no integration branch - a false positive on every
    correctly tagged project.

    Found as a mutation SURVIVOR: nothing in the suite had noticed, because
    every other fixture here uses lightweight tags.
    """
    import extant_collect as hc
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "-a", "v3.0.0", "-m", "annotated release")

    hc._SCOPE = hc.RunScope()
    resolved = hc._resolve_ref(repo, "v3.0.0")
    head = hc._resolve_ref(repo, "main")
    assert resolved == head, (
        f"the annotated tag resolved to {resolved}, not to the commit it tags "
        f"({head}) - so it is an ancestor of nothing"
    )

    # And the rule that depends on it stays quiet, which is the point.
    assert "dead-release-tag" not in _tags(repo, "Released in v3.0.0.\n")
