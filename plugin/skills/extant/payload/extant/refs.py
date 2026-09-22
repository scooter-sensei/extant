"""What git says about this repository: refs, ancestry, renames, objects.

Every function here answers a question ABOUT A REPOSITORY rather than about a
document, which is what separates this module from `text.py` beside it. None of
them is a rule, and none may import one: three of the bodies below were pulled
out of what will become rule modules precisely so that a rule never has to
reach into another rule.

The three that were moved for that reason, and where they came from:

* rename detection (`_rename_map`, `renamed_to`) sat with the live-claim rule,
  and both `dead-md-link` and `dead-path-pointer` were calling into it.
* object resolution (`_sha_of`, `resolve_shas`, `_batch_shas`) sat with the
  SHA rule, and the merge rule was calling into it.
* `named_in_merge_history` sat among the site helpers, which is where the
  branch rule happened to need it.

Each is a git-history question rather than a property of whichever rule needed
it first, so this is where a reader looks for it.

THREE MORE ARRIVED HERE THAT THE PLAN PUT ELSEWHERE, and the reason is the same
leaf rule rather than a change of mind:

* `SHA_SHAPE` is listed with the SHA rule for Task 9, but `reachable_from`
  below tests it to tell an abbreviated commit from a branch name. Left where
  it was, this module would import a rule.
* `tracked_markdown` is listed with the sweep driver for Task 10, and both
  `text.py` and `sites.py` ask it which documents exist. Left there, two leaves
  would import the driver that calls them.
* `_batch_shas` is listed nowhere at all. It is `resolve_shas`'s own batching
  helper and cannot stay behind without this module importing the shim.

`_batch_shas` and `_settle` are the two places in this module that run git
through subprocess directly rather than through the seam, because `cat-file
--batch-check` and `rev-list --stdin` are fed on stdin and
`Git.run(repo, *args)` cannot express that. tests/test_scope.py names them
and counts them, so the gap is a number somebody chose rather than one nobody
noticed.

Every function takes the `Context` it reads instead of a module global. The
repository is `ctx.repo`, git is `ctx.git`, memoised answers live on `ctx.run`
with their lifetime stated there, and the configured trunk is `ctx.config`.
"""
from __future__ import annotations

import re
import subprocess

from extant.git import environment
from extant.scope import AncestryIndex, Context

# Eight of these names lost their underscore in Task 9, when the rules became
# modules of this package and their calls into here became SIBLING calls. That
# is the rule the whole package follows - a name is public when a sibling
# module calls it - and `test_no_module_reaches_past_another_modules_surface`
# turns reaching for an underscore name across that boundary into a hard
# failure, so the choice was between promoting them and lying about the
# boundary. `_ancestor_index`, `_rename_map`, `_settle` and `_sha_of` keep
# theirs: each has exactly one caller, and it is in this file.
__all__ = [
    "DOCUMENT_SUFFIXES", "INDEX_BOUND", "SHA_SHAPE", "_INTEGRATION_NAMES",
    "_Ancestry", "_ancestor_index",
    "_from_table",
    "_rename_map", "_settle", "_sha_of", "branch_exists", "commit_id",
    "integrated_by",
    "integration_refs",
    "named_in_merge_history", "settle_ancestry", "reachable_from",
    "ref_table", "renamed_to",
    "resolve_ref", "resolve_shas", "tracked_markdown",
]

SHA_SHAPE = re.compile(r"^[0-9a-f]{7,40}$")

# How many commits of a ref's history the ancestry index holds, and the
# number was measured before it was chosen. `rev-list` without a commit-graph
# - the state of every one of 195 corpus clones and of every fresh CI
# checkout - walks about 33 microseconds per commit on this machine, so a
# full index of rust's 338,850 commits cost 10.6 s and 77 MB per ref per
# worker, and `-n` bounds that walk linearly: 20,001 commits in 0.68 s,
# 50,001 in 1.6 s, 100,001 in 3.1 s. At fifty thousand, 179 of the 195 clones
# are indexed completely and pay exactly what they paid before, one spawn per
# ref per run; the sixteen above it pay at most 1.6 s and about 6 MB per ref
# per worker, and settle what the index cannot hold through `_settle`. A
# module constant rather than a setting, because a knob nobody turns is dead
# configuration; the tests set it to one so the path past the bound runs on
# every fixture rather than only on a repository nobody tests against.
INDEX_BOUND = 50_000

# The file suffixes a survey reads. Named, because two other places have to
# agree with this tuple exactly: `_HISTORICAL` in extant/strata.py carries
# the same four spellings in a pattern, and `--introduced-since` hands them
# to `git diff` as pathspecs so the diff it reads covers the documents the
# sweep reads and no others.
DOCUMENT_SUFFIXES = ("md", "markdown", "mdx", "rst")


def _sha_of(ctx: Context, token: str) -> str | None:
    """The full commit id one token names, or None; the per-token spawn the
    batch below falls back to when its line count disagrees with its input."""
    try:
        return ctx.git.run(ctx.repo, "rev-parse", "--verify", "--quiet",
                           f"{token}^{{commit}}").strip() or None
    except (subprocess.CalledProcessError, OSError):
        return None


def resolve_shas(ctx: Context, tokens: list[str]) -> set[str]:
    """Which of `tokens` resolve to commits, in ONE git call instead of N.

    `git cat-file --batch-check` reads object names on stdin and emits exactly
    one line per input, in order: `<sha> <type> <size>` when it resolves, or
    `<input> missing` when it does not. Only the ORDER ties an output line back
    to its input, because a resolved line reports the full SHA rather than the
    abbreviation that was fed in - so this zips the two and bails out to the
    per-token path if the counts ever disagree.

    Worth the care: on Windows each subprocess spawn costs ~40 ms, and a real
    status document plus its archive carries ~60 references. Batching takes
    `--verify` from about 2.6 s to under half a second, which is what makes it
    cheap enough to run from a git hook on every commit.

    Answered from the run scope wherever it can be, because ONE call per rule
    is not the same as one call per document. Two rules ask - see
    `_document_sha_tokens` - and each was spawning its own batch even for
    tokens the other had already resolved. Whether a commit exists is a fact
    about the repository, identical whoever asks, so the answer is kept per
    TOKEN and the batch below carries only what has not been asked yet. The
    lifetime is stated on `RunScope.shas`.

    THE FULL SHA IS KEPT, not a boolean, because the ancestry index answers by
    full-SHA membership now and the batch line already carries it. A memo of
    booleans would have `reachable_from` spawn a `rev-parse` per abbreviated
    token to learn what this call had just been told.
    """
    unique = sorted(set(tokens))
    if not unique:
        return set()
    known = ctx.run.shas
    repo_key = str(ctx.repo)
    unasked = [token for token in unique if (repo_key, token) not in known]
    if unasked:
        alive = _batch_shas(ctx, unasked)
        # Every token asked about is recorded, including the ones that did not
        # resolve. A dict written only on success is a cache that misses
        # forever on precisely the tokens this rule reports, which is the
        # `_OWN_REMOTE` mistake in a second place: `None` and "not resolved"
        # are ANSWERS, not misses.
        for token in unasked:
            known[(repo_key, token)] = alive.get(token)
    return {token for token in unique if known[(repo_key, token)] is not None}


def _batch_shas(ctx: Context, unique: list[str]) -> dict[str, str]:
    """The batch itself, token -> the full commit id it names, resolved ones
    only. Separate only so the memo above stays readable."""
    payload = "".join(f"{token}^{{commit}}\n" for token in unique)
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=ctx.repo, input=payload, capture_output=True, text=True, encoding="utf-8",
        env=environment(),
    )
    lines = proc.stdout.splitlines()
    if len(lines) != len(unique):
        found = {token: _sha_of(ctx, token) for token in unique}
        return {token: sha for token, sha in found.items() if sha is not None}
    resolved: dict[str, str] = {}
    for token, line in zip(unique, lines):
        parts = line.split()
        # Explicit success only. `<input> missing` is one failure shape;
        # `<input> ambiguous` is another, and "does not end in missing" let
        # it through as though the object had resolved. The first field of a
        # success line is the object `^{commit}` peeled to - a commit, its own
        # id for a raw SHA and the tagged commit's for an annotated tag.
        if len(parts) == 3 and parts[1] == "commit":
            resolved[token] = parts[0]
    return resolved


def commit_id(ctx: Context, rev: str) -> str | None:
    """The full commit id `rev` names here, or None.

    ONE TOKEN, ONE RESOLVER. A SHA-shaped rev is resolved the way `dead-sha`
    resolves it - through the `cat-file` batch and its per-token memo - and a
    name through the ref table and its `rev-parse` fallback. Sending a token
    down the name path would look up a seven-character hex string in the tag
    table first, which is where a tag named like a prefix would answer for a
    commit; sending it through the batch answers with git's own precedence,
    once, and records the answer where the rule that found it already looks.
    """
    if SHA_SHAPE.match(rev):
        resolve_shas(ctx, [rev])
        return ctx.run.shas[(str(ctx.repo), rev)]
    return resolve_ref(ctx, rev)


def branch_exists(ctx: Context, branch: str) -> bool:
    """Does a BRANCH by this name exist?

    It asked `rev-parse --verify <name>` for a long time, and that follows
    git's tags-before-heads precedence, so it answered True for a TAG named
    like a branch. This docstring called that a behaviour question wearing a
    performance fix's clothing and asked for a corpus measurement before it
    changed. Measured on 2026-09-16 over the 152 visible corpus clones: 23
    names in 7 repositories are both a branch and a tag - `v1.10.2`,
    `package-2.1.0`, `release-2013.1`, release lines tagged at their own name
    - so the divergence is real, and the two rules that ask this question ask
    about branches: `unknown-branch` wants a branch or a merge commit naming
    one, and a live claim about a tag is a live claim about nothing.

    Three answers, in the order git itself would look:

      * a LOCAL head of that name, from the ref table one `for-each-ref` has
        already built for the call - no process, which is the spawn the old
        docstring declined to save for free;
      * a name that is only a TAG, which git's precedence would have accepted:
        asked once more, for a remote-tracking branch under `refs/remotes/`
        exactly where `rev-parse` would have found one had the tag not been
        in the way;
      * a spelling neither table holds - `origin/feature`, `HEAD`, a SHA -
        which is `rev-parse --verify` as before, so nothing a document names
        today stops existing.
    """
    heads, tags = ref_table(ctx)
    if branch in heads:
        return True
    candidates = ([f"refs/remotes/{branch}", f"refs/remotes/{branch}/HEAD"]
                  if branch in tags else [branch])
    for candidate in candidates:
        try:
            ctx.git.run(ctx.repo, "rev-parse", "--verify", "--quiet", candidate)
            return True
        except subprocess.CalledProcessError:
            continue
    return False


class _Ancestry:
    """What one ref's history has answered so far, in one run scope.

    `commits` is the bounded index: the first `INDEX_BOUND + 1` commits
    `rev-list` printed, so a member is an ancestor whatever else is true.
    `complete` says whether that was the whole history, in which case a
    non-member is not an ancestor and nothing need be asked. `settled` holds
    what `_settle` has since learned about commits past the bound, keyed by
    full SHA - the memo the batches fill, so a sweep asks about each commit
    at most once per ref however many documents cite it.

    One object rather than three scope fields, because the three share one
    lifetime and one key, and a reader who finds them apart would have to
    prove they cannot disagree.
    """
    __slots__ = ("commits", "complete", "settled")

    def __init__(self, commits: frozenset[str], complete: bool) -> None:
        self.commits = commits
        self.complete = complete
        self.settled: dict[str, bool] = {}


def _ancestor_index(ctx: Context, ref: str) -> AncestryIndex | None:
    """The newest `INDEX_BOUND + 1` commits reachable from `ref`, as full SHAs.

    ONE `git rev-list` answers what would otherwise be one
    `git merge-base --is-ancestor` per claim. Measured on a 5000-commit
    repository: rev-list costs 125 ms and returns 205 KB, while a single
    merge-base costs about 100 ms. The batch therefore pays for itself at two
    distinct commits and wins by roughly 800x at two thousand, which took that
    stress case from 105 seconds to about a second.

    BOUNDED, since 2026-09-15, and the docstring that stood here argued against
    exactly that: "a size-based switch would create a second path that only
    runs on large inputs, which is precisely the code that never gets
    exercised by a test". The argument was right and the answer is not to
    leave the walk unbounded but to exercise the path: `INDEX_BOUND` is a
    constant tests/test_ancestry_bound.py sets to one, so every rule that asks
    ancestry runs past the bound on every fixture, and the mutation campaign
    holds anchors on both sides of it. What the bound buys is in the constant's
    own comment; what it costs is that a history longer than the bound settles
    its older commits through `_settle`, one batch per rule and ref.

    ONE MORE LINE THAN THE BOUND is asked for, so that "incomplete" is a fact
    the output states - a history of exactly the bound's length would
    otherwise be indistinguishable from a cut one, and the cut would then be
    answered as a complete index answers: no, without asking.

    Membership is by FULL SHA. The index used to bucket commits by their
    seven-character prefix so an abbreviated token could be matched with
    `startswith`; every rev that reaches here now carries its full id -
    `commit_id` reads it from the `cat-file` memo or the ref table - so the
    buckets and the scan went, and with them 77 MB of lists on rust's history
    against 42 MB for the strings alone, unbounded; bounded, about 6 MB.

    Keyed by ref because "integrated" is no longer one question about one
    branch. Re-measured on the gitflow fixture: two rev-lists cost 61 ms
    together while a single merge-base costs 29 ms, so indexing every
    integration ref pays for itself from three examined items onward - and a
    document that names branches and tags at all names more than three.

    Returns None when the ref cannot be resolved - an unborn branch, a deleted
    one, or a misconfigured name - so the caller can fall back to asking per
    commit and get the same answer it always did.
    """
    key = (str(ctx.repo), ref)
    if key in ctx.run.ancestors:
        return ctx.run.ancestors[key]
    try:
        out = ctx.git.run(ctx.repo, "rev-list", "-n", str(INDEX_BOUND + 1), ref)
    except (subprocess.CalledProcessError, OSError):
        ctx.run.ancestors[key] = None
        return None
    listed = out.split()
    index = _Ancestry(frozenset(listed), complete=len(listed) <= INDEX_BOUND)
    ctx.run.ancestors[key] = index
    return index


def reachable_from(ctx: Context, rev: str, ref: str) -> bool:
    """Is `rev` an ancestor of `ref`? From the index, else from what
    `_settle` learned, else by settling this one rev on its own.

    The last of those is one spawn per question, which is the shape the index
    exists to remove: a rule that asks past the bound should have called
    `settle_ancestry` with everything it is about to ask, so the misses go
    out in one batch. Kept as the answer of last resort rather than an error,
    because a slow right answer is still a right answer - and
    tests/test_spawn_budget.py is what notices the slowness.
    """
    index = _ancestor_index(ctx, ref)
    if index is None:
        try:
            ctx.git.run(ctx.repo, "merge-base", "--is-ancestor", rev, ref)
            return True
        except (subprocess.CalledProcessError, OSError):
            return False
    commit = commit_id(ctx, rev)
    if commit is None:
        return False
    if commit in index.commits:
        return True
    if index.complete:
        return False
    if commit not in index.settled:
        _settle(ctx, index, [commit], ref)
    return index.settled[commit]


def settle_ancestry(ctx: Context, questions: list[tuple[str, str]]) -> None:
    """Settle every (rev, ref) in `questions` that the index cannot, one batch
    per ref, so the `reachable_from` calls that follow spawn nothing.

    Called by a rule before its judging loop with everything the loop will
    ask. Nothing here changes an answer: a rev the index holds is not fed, a
    rev already settled is not fed again, a ref with a complete index or no
    index at all is left to `reachable_from`, which answers those without a
    batch. What it changes is the spawn count, from one per claim to one per
    ref per rule - and on the 92 per cent of histories the bound covers, to
    none at all beyond the index itself.
    """
    # The index travels with its misses rather than being looked up again
    # below: the loop has just proved it exists and is incomplete, and a
    # second read of the memo would have to prove that twice.
    pending: dict[str, tuple[AncestryIndex, list[str]]] = {}
    for rev, ref in questions:
        index = _ancestor_index(ctx, ref)
        if index is None or index.complete:
            continue
        commit = commit_id(ctx, rev)
        if commit is None or commit in index.commits or commit in index.settled:
            continue
        misses = pending.setdefault(ref, (index, []))[1]
        if commit not in misses:
            misses.append(commit)
    for ref, (index, misses) in pending.items():
        _settle(ctx, index, misses, ref)


def _settle(ctx: Context, index: AncestryIndex, commits: list[str], ref: str) -> None:
    """One `rev-list --stdin --not REF` for every commit the bounded index
    could not place, recorded on `index.settled`.

    THE OUTPUT IS THE EXCLUSIVE HISTORY OF THE INPUTS, not a list of answers,
    and the review that proposed this call had that half wrong: it passed
    `--no-walk` and reported output "proportional to the answer", but
    `--no-walk` has no effect once a `--not` makes the arguments a range - on
    git 2.53 the output with and without it is byte-identical. What the call
    does print is every commit reachable from an input and not from REF. So
    an input that is printed is not an ancestor, an input that is not printed
    is one, and for a document whose claims are all true the output is empty.
    Measured on rust without a commit-graph, 50 inputs: 0.63 s when every
    input is within a thousand first-parent commits of the tip, 7.9 s when
    one is near the root, against 10.6 s for the unbounded index the bound
    replaced.

    FED FULL SHAS, and only ones this run has already resolved as commits -
    through the `cat-file` batch or the ref table - which is what makes the
    abort the review warned about unreachable by construction: one input git
    cannot resolve fails the whole call with exit 128 and nothing on stdout,
    and a full id of a commit this repository holds cannot be that input.
    Should it happen anyway - the repository changed under the run - the
    fallback is the one `reachable_from` has always had, a `merge-base
    --is-ancestor` per commit, so the answer is the same and only the spawn
    count is not.

    Bytes in and bytes out. `subprocess` in text mode writes the payload with
    the platform's line ending, which on Windows hands git `\\r\\n`; git
    happens to tolerate it, and `_batch_shas` has been relying on that
    tolerance. This site does not. The output is hex and newlines, so the
    decode cannot fail; it is done here, where a reader can see it.
    """
    payload = b"".join(commit.encode("ascii") + b"\n" for commit in commits)
    try:
        proc = subprocess.run(
            ["git", "rev-list", "--stdin", "--not", ref],
            cwd=ctx.repo, input=payload, capture_output=True,
            env=environment(),
        )
    except OSError:
        proc = None
    if proc is not None and proc.returncode == 0:
        printed = set(proc.stdout.decode("ascii", "replace").split())
        for commit in commits:
            index.settled[commit] = commit not in printed
        return
    for commit in commits:
        try:
            ctx.git.run(ctx.repo, "merge-base", "--is-ancestor", commit, ref)
            index.settled[commit] = True
        except (subprocess.CalledProcessError, OSError):
            index.settled[commit] = False


def _from_table(ref: str, heads: dict[str, str],
                tags: dict[str, str]) -> str | None:
    """What the ref table says about this SPELLING of a ref, or None.

    A QUALIFIED ref names its own table and is looked up in that one alone.
    Falling back to `tags or heads` for it would resolve `refs/tags/x` to a
    BRANCH called `x` on a repository carrying both - a different commit than
    the caller asked for, and the kind of divergence that shows up once, in
    somebody else's repository, as a merge claim reported false.

    Qualified spellings are not a corner case here: `dead-release-tag` asks
    about `refs/tags/<v>` because that is what `integrated_by` needs, and every
    one of those lookups used to miss this table and spawn a `rev-parse`. On
    this repository, 14 of the 24 git processes a `--verify` started were that
    one question. Measured on this machine, one `git rev-parse` costs 28.27 ms
    (median of 20), and removing 19 of the 24 took a whole `--verify` from
    1477 ms to 729 - about 39 ms per spawn removed.
    """
    if ref.startswith("refs/tags/"):
        return tags.get(ref[len("refs/tags/"):])
    if ref.startswith("refs/heads/"):
        return heads.get(ref[len("refs/heads/"):])
    # TAGS BEFORE HEADS, because that is git's precedence for a bare name:
    # `refs/tags/<name>` is tried before `refs/heads/<name>`. Reversing it
    # would resolve a repository that has both to a different commit than
    # `rev-parse` does, which is the kind of divergence that shows up once, in
    # somebody else's repository, as a merge claim reported false.
    return tags.get(ref) or heads.get(ref)


def resolve_ref(ctx: Context, ref: str) -> str | None:
    """The full commit SHA a ref points at, or None if it does not resolve.

    `^{commit}` dereferences an annotated tag to the commit it tags, which is
    what every ancestry question here means. Without it a tag object's own SHA
    is returned and never appears in any rev-list.

    Memoised for the same reason the index is: a document repeats the same
    branch name on every claim, and resolving it once per MENTION reintroduced
    exactly the per-claim subprocess that batching exists to remove. There is a
    test asserting the process count, and it caught this.
    """
    key = (str(ctx.repo), ref)
    if key in ctx.run.refs:
        return ctx.run.refs[key]
    # The ref TABLE first, which one `for-each-ref` builds for the whole call.
    # Measured on this repository's own status document, a validate spawned
    # eight git subprocesses and three of them asked questions this table
    # already answers: two `rev-parse --verify` and one `tag -l`, beside the
    # `for-each-ref` that was being run anyway.
    heads, tags = ref_table(ctx)
    resolved = _from_table(ref, heads, tags)
    if resolved is None:
        # A TABLE MISS IS NOT AN ANSWER. Raw SHAs, `HEAD`, `main~3` and
        # remote-tracking refs are legitimate inputs no table holds, so this
        # stays a fast path rather than a replacement - a version that returned
        # None here would report every SHA-anchored claim dead. Those still
        # need git, and still cost a spawn.
        try:
            resolved = ctx.git.run(ctx.repo, "rev-parse", "--verify", "--quiet",
                                   f"{ref}^{{commit}}").strip() or None
        except (subprocess.CalledProcessError, OSError):
            resolved = None
    ctx.run.refs[key] = resolved
    return resolved


def ref_table(ctx: Context) -> tuple[dict[str, str], dict[str, str]]:
    """Every local branch and tag that names a COMMIT, by short name, peeled.

    One subprocess answers what `rev-parse --verify` per ref, `tag -l` and
    `for-each-ref refs/heads` were each asking separately. `%(*objectname)` is
    the peeled object for an annotated tag and empty otherwise - without it an
    annotated tag yields the tag object's own SHA, which appears in no rev-list.

    THE TYPE IS READ TOO, and this docstring used to claim it did not need to
    be: that peel was "the same dereference `^{commit}` performs". It is not.
    A tag may name any object, and for one naming a tree or a blob `^{commit}`
    resolves to NOTHING while the peel happily yields the tree's or the blob's
    id - not a commit, and in no rev-list either:

        goodtag   rev-parse=2e7c7b432863   peel=2e7c7b432863   agrees
        treetag   rev-parse=None           peel=959186c87f11   diverges
        blobtag   rev-parse=None           peel=47d05ff6403c   diverges

    So a ref is recorded only when what would be returned IS a commit, which
    makes the table match the contract it was already asserting. That is a
    BEHAVIOUR CHANGE and it is stated as one: on a repository holding such a
    tag, a name that used to resolve to a non-commit object id now resolves to
    nothing, which is what git says. Such tags are legal, rare, and invisible
    to the corpus - `fuzz --differential` would report no difference and prove
    nothing - so tests/test_ref_resolution.py builds them with `hash-object`
    and `mktree` instead.

    Held for one call, like every other answer git gives here.
    """
    key = str(ctx.repo)
    if key not in ctx.run.ref_table:
        heads: dict[str, str] = {}
        tags: dict[str, str] = {}
        try:
            out = ctx.git.run(
                ctx.repo, "for-each-ref",
                "--format=%(refname)\t%(objectname)\t%(objecttype)"
                "\t%(*objectname)\t%(*objecttype)",
                "refs/heads", "refs/tags")
        except (subprocess.CalledProcessError, OSError):
            out = ""
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) != 5:
                continue
            full, obj, kind, peeled, peeled_kind = parts
            commit = peeled or obj
            # The type of the object that WOULD be returned, chosen by the same
            # `peeled or obj` the line above uses, so the two cannot disagree
            # about which object is being described.
            if (peeled_kind or kind) != "commit":
                continue
            if full.startswith("refs/heads/"):
                heads[full[len("refs/heads/"):]] = commit
            elif full.startswith("refs/tags/"):
                tags[full[len("refs/tags/"):]] = commit
        ctx.run.ref_table[key] = (heads, tags)
    return ctx.run.ref_table[key]


# The branch names the mainstream flows actually integrate into: gitflow and
# git-flow-avh use main/master plus develop/development, GitHub flow uses
# main/master alone, and `trunk` appears in Subversion-descended repositories.
# Only names that EXIST in the repository are used.
_INTEGRATION_NAMES = ("main", "master", "develop", "development", "trunk")


# Memoised on the run scope for the lifetime of one call, exactly like the
# ancestry indexes: the same handful of refs is asked for once per claim, and
# each miss was a `for-each-ref` SUBPROCESS. Two of this project's worst
# measured costs have been a subprocess per claim - ancestry was 17.7 of 18.0
# seconds once - so a git call reached from inside a per-claim loop is the
# shape to watch. See `RunScope.integration`.


def integration_refs(ctx: Context) -> list[str]:
    """The branches this repository integrates work INTO.

    Why this exists: three rules used to ask "is X an ancestor of trunk",
    meaning three different things by it, and on a two-trunk repository each
    answer was wrong in a different direction. Measured on a gitflow fixture,
    with trunk=main a false "merged to develop" claim was invisible; with
    trunk=develop a genuinely shipped release tag was reported dead.

    A CONVENTIONAL NAME LIST, not a shape rule. The first version of this asked
    only whether the name had a slash in it, on the reasoning that topic
    branches are prefixed and long-lived ones are bare. That is true of the
    prefixes, and useless in the other direction: an existing test cuts a tag
    on a branch called `abandoned` and expects the release to be reported as
    never shipped. Slashless, so the shape rule called it an integration branch
    and went silent - turning a caught falsehood into a missed one. Every
    `gh-pages`, `experiment` or `old-master` is the same trap.

    The narrower list degrades safely. A project whose second integration
    branch has an unconventional name simply gets today's behaviour, and the
    rule this all exists for - false-merge-claim - does not consult this list
    at all, because a merge claim names its own ref.

    The configured trunk is always included, even if it is unconventional or
    has a slash, because a project that named its trunk has said so - but only
    if it EXISTS. A trunk that is not in this repository cannot settle whether
    anything reached it, and returning it anyway made every caller answer "no"
    to a question it had never asked. symfony has no `main` and no `master`;
    its branches are version numbers and its default is `8.2`, so with the
    default configuration every one of its release tags was reported as
    shipped on nothing. Measured across 30 repositories, 3 are in that
    position - laravel/framework on `13.x` and slate on `migration-notice`
    are the others - so this is roughly a tenth of real projects, not a
    corner.

    An EMPTY list is therefore meaningful and callers must treat it as "cannot
    settle" rather than as "integrated nowhere".
    """
    key = str(ctx.repo)
    if key in ctx.run.integration:
        return ctx.run.integration[key]
    refs = [ctx.config.trunk]
    # The shared ref table, not a second `for-each-ref` of its own.
    present = set(ref_table(ctx)[0])
    for name in _INTEGRATION_NAMES:
        if name in present and name not in refs:
            refs.append(name)
    ctx.run.integration[key] = [ref for ref in refs
                                if resolve_ref(ctx, ref) is not None]
    return ctx.run.integration[key]


def integrated_by(ctx: Context, rev: str, *, exclude: str = "") -> list[str]:
    """Which integration refs contain `rev`.

    `exclude` drops one ref from consideration, and it is load-bearing rather
    than tidy: without it a slashless topic branch is trivially an ancestor of
    itself, so every live claim about one would be reported as already merged.
    """
    return [ref for ref in integration_refs(ctx)
            if ref != exclude and reachable_from(ctx, rev, ref)]


# Cached per repository on the run scope, because the query below cannot be
# narrowed with a pathspec and so is the expensive one here. Keyed by path, and
# only ever read after a pointer has already been found dead.


def _rename_map(ctx: Context) -> dict[str, str]:
    """Recent renames, old path to new.

    NOT narrowed with a pathspec, and that is deliberate rather than sloppy.
    `git log --diff-filter=R -- <old path>` returns NOTHING: once rename
    detection has run, history simplification no longer considers that commit
    to touch the old name. Measured directly, since the pathspec version looked
    obviously correct and silently found nothing on a repository where the
    rename was two commits old.

    `-M` IS PASSED, since 2026-09-16, because `git log --name-status` detects
    renames only when the repository's `diff.renames` says so, and asked
    without it this map was empty on any project that set that to false -
    no hint, no note, and nothing to say the hint had been possible. Found
    when a corpus identity gate showed 0 outputs changing where a count had
    predicted 2: every one of the 152 visible corpus clones carries
    `diff.renames=false`, written by the clone script, so on that corpus the
    hint had never once fired. The environment this process starts with
    already frees the answer from `core.quotePath`; this frees it from
    `diff.renames`. It costs nothing where detection was already on, and a
    partial clone fails the same way with or without it - rename detection
    reads blob content, lazy fetching is refused, and the failure lands in
    the `except` below as it always did.

    `-n 200` bounds the COMMITS walked, not the renames found - on this
    repository every rename sits inside the last 200 of 355 commits. Raising
    it was measured and refused on 2026-09-16: of 501 dead link and pointer
    findings on the nine full clones, 2 name a target renamed beyond the
    window, and one of those would have been hinted WRONGLY, a vendored
    README's `CONTRIBUTING.md` matched to this repository's own moved file.
    """
    key = str(ctx.repo)
    if key in ctx.run.renames:
        return ctx.run.renames[key]
    mapping: dict[str, str] = {}
    try:
        out = ctx.git.run(ctx.repo, "log", "--diff-filter=R", "--name-status",
                          "--format=", "-n", "200", "-M")
    except (subprocess.CalledProcessError, OSError):
        out = ""
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].startswith("R"):
            mapping.setdefault(parts[1], parts[2])
    ctx.run.renames[key] = mapping
    return mapping


def renamed_to(ctx: Context, missing: str) -> str | None:
    """Where git says a now-missing path ended up, or None.

    Reporting a pointer as dead is correct but unhelpful when the file was
    merely renamed and git knows exactly where it went. Rename chains are
    followed, so a file moved twice still resolves to where it actually is.
    """
    mapping = _rename_map(ctx)
    current = missing.replace("\\", "/")
    seen = {current}
    while current in mapping:
        current = mapping[current]
        if current in seen:  # a rename cycle; report the last honest step
            break
        seen.add(current)
    return None if current == missing.replace("\\", "/") else current


def named_in_merge_history(ctx: Context, branch: str) -> bool:
    """Did a merge commit ever mention this branch?

    THE MEASUREMENT THAT MADE THIS RULE POSSIBLE. Every one of the four branches
    named in the source project's current document had already been deleted, so
    a plain "does this branch exist" check would have produced four findings and
    four false positives on its first run: the same shape as the path rule that
    was nearly shipped keyed on appearance.

    All four were still named in merge commits. That is what separates "merged
    and cleaned up", which is ordinary hygiene, from "never existed", which is
    a typo or an invented name and worth reporting.
    """
    try:
        out = ctx.git.run(ctx.repo, "log", "--merges", "--fixed-strings",
                          "--grep", branch, "--format=%H", "-n", "1")
    except (subprocess.CalledProcessError, OSError):
        return True  # cannot tell: stay silent rather than accuse
    return bool(out.strip())


def tracked_markdown(ctx: Context) -> list[str]:
    """Every markdown file git tracks, repo-relative, sorted.

    Git rather than a filesystem walk, so anything gitignored, vendored into an
    ignored directory, or sitting untracked in a working tree is out by
    construction rather than by a skip-list somebody has to maintain.

    HEAD's TREE, not the index. `ls-files` reads the index, which is empty when
    a checkout did not complete - a sparse checkout, a partial clone, or on
    Windows a repository whose paths exceed MAX_PATH. Measured on a helm clone
    in that state: `ls-files` reported 0 markdown files and this returned a
    clean sweep, while HEAD's tree held 96. That is the exact bug this project
    already fixed once for `raw-lfs-blob`, reintroduced in a new rule, and it
    is the worst shape available - a silent all-clear on a repository nobody
    checked. Files listed here but absent from the working tree are counted and
    named as unreadable by the caller rather than passed over.
    """
    key = str(ctx.repo)
    if ctx.run.dircache is not None and key in ctx.run.tracked_markdown:
        return ctx.run.tracked_markdown[key]
    # Deliberately unguarded. An `ls-tree` that fails must raise here: the
    # paragraph above is about a silent all-clear on a repository nobody
    # checked, and returning [] on error is precisely how one is produced.
    out = ctx.git.run(ctx.repo, "ls-tree", "-r", "-z", "--name-only", "HEAD")
    files = sorted(p for p in out.split("\0")
                   if p.strip() and p.rsplit(".", 1)[-1] in DOCUMENT_SUFFIXES)
    if ctx.run.dircache is not None:
        ctx.run.tracked_markdown[key] = files
    return files
