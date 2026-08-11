"""Per-call caches: how long an answer git gave is allowed to live.

Both tests here exist because the full mutation campaign found them missing.
154 mutations, 152 killed, and the two survivors were both in this code - one
a documented correctness property with no test, the other a property no
document can exercise at all.

The lifetime rule is the same for every one of these caches: an answer git
gave is held for ONE call and thrown away after. Held longer, a repository
that changed between two calls keeps resolving to what it used to be. Rebuilt
more often, nothing is wrong and everything is slower.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PAYLOAD = (Path(__file__).resolve().parent.parent / "plugin" / "skills"
           / "extant" / "payload")
sys.path.insert(0, str(PAYLOAD))


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def test_a_tag_created_between_two_calls_is_seen_by_the_second(git_repo) -> None:
    """The reason the tag list is reset per call, stated in a comment beside it
    and until this test was written guarded by nothing.

    The comment reads: "A tag created between two validate() calls would
    otherwise keep resolving to nothing." The mutation that makes the tag list
    outlive its call SURVIVED the full campaign, which is that sentence being
    true and unguarded at the same time.

    Named `_TAGS` when it was written, and that name was wrong by then: since
    6c5c29c routed branches, tags and ref lookups through one `for-each-ref`,
    `_tags()` has read the shared ref table and `_TAGS` was read by nothing at
    all. It survived four commits as a global that was cleared, saved and
    restored in four places while holding nothing, and was deleted when the
    caches became a RunScope. What actually carries this property is
    `scope.ref_table`. The test never changed, because the BEHAVIOUR it pins
    never did - which is the argument for pinning behaviour rather than a name.

    One process, two calls, a tag created in between. Anything that caches the
    tag list across the boundary reports the second claim dead.
    """
    import extant_collect as hc
    hc._RELEASE_CLAIMS_ARE_OURS = True
    repo, commit = git_repo
    commit("a.py", "a = 1\n", "feat: a")
    git(repo, "tag", "v1.0")

    first = hc.validate(repo, "Released in v1.0.\n", has_entries=False)
    assert [f.kind for f in first if f.kind == "dead-release-tag"] == []

    # The repository changes between the two calls, exactly as it does when a
    # hook runs after `git tag` in the same session.
    git(repo, "tag", "v2.0")

    second = hc.validate(repo, "Released in v2.0.\n", has_entries=False)
    assert [f.kind for f in second if f.kind == "dead-release-tag"] == [], (
        "a tag created since the previous call resolved to nothing, which "
        "means the tag list outlived the call that built it")


# The integration-ref cache (`scope.integration`, formerly `_INTEGRATION`) has
# NO test here, deliberately, and the reason is worth more than a weak one
# would be.
#
# Its mutation survived the full campaign, and three attempts to close it all
# failed for different reasons. Counting `_ref_table` proves nothing: that has
# a cache of its own underneath and is built once either way. Counting
# `_resolve_ref` proves nothing either: the merge-claim rule legitimately
# resolves the ref each claim names, so a four-claim document resolves the
# trunk four times whether this cache exists or not - that assertion fails on
# UNMUTATED code, which is how the third attempt was caught.
#
# What remains is a memoisation whose saved work is indistinguishable from
# work other call sites do for their own reasons. It is a micro-optimisation
# over an already-cached ref table, and no cheap test isolates it. Writing one
# that passes without pinning it would be worse than none, which is the
# failure this file exists to record twice already.
