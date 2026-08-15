"""What git says about this repository: refs, ancestry, renames, objects.

Every function here answers a question ABOUT A REPOSITORY rather than about a
document, which is what separates this module from `text.py` beside it. None of
them is a rule, and none may import one: three of the bodies below were pulled
out of what will become rule modules precisely so that a rule never has to
reach into another rule.

The three that were moved for that reason, and where they came from:

* rename detection (`_rename_map`, `renamed_to`) sat with the live-claim rule,
  and both `dead-md-link` and `dead-path-pointer` were calling into it.
* object resolution (`_sha_exists`, `resolve_shas`, `_batch_shas`) sat with the
  SHA rule, and the merge rule was calling into it.
* `_named_in_merge_history` sat among the site helpers, which is where the
  branch rule happened to need it.

Each is a git-history question rather than a property of whichever rule needed
it first, so this is where a reader looks for it.

THREE MORE ARRIVED HERE THAT THE PLAN PUT ELSEWHERE, and the reason is the same
leaf rule rather than a change of mind:

* `_SHA_SHAPE` is listed with the SHA rule for Task 9, but `_reachable_from`
  below tests it to tell an abbreviated commit from a branch name. Left where
  it was, this module would import a rule.
* `tracked_markdown` is listed with the sweep driver for Task 10, and both
  `text.py` and `sites.py` ask it which documents exist. Left there, two leaves
  would import the driver that calls them.
* `_batch_shas` is listed nowhere at all. It is `resolve_shas`'s own batching
  helper and cannot stay behind without this module importing the shim.

`_batch_shas` is also the one place in this package that runs git through
subprocess directly rather than through the seam, because `cat-file
--batch-check` is fed on stdin and `Git.run(repo, *args)` cannot express that.
tests/test_scope.py names it and counts it, so the gap is a number somebody
chose rather than one nobody noticed.

Every function takes the `Context` it reads instead of a module global. The
repository is `ctx.repo`, git is `ctx.git`, memoised answers live on `ctx.run`
with their lifetime stated there, and the configured trunk is `ctx.config`.
"""
from __future__ import annotations

import re
import subprocess

from extant.scope import Context

__all__ = [
    "_INTEGRATION_NAMES", "_SHA_SHAPE", "_ancestor_index", "_branch_exists",
    "_named_in_merge_history", "_reachable_from", "_ref_table", "_rename_map",
    "_resolve_ref", "_sha_exists", "integrated_by", "integration_refs",
    "renamed_to", "resolve_shas", "tracked_markdown",
]

_SHA_SHAPE = re.compile(r"^[0-9a-f]{7,40}$")


def _sha_exists(ctx: Context, sha: str) -> bool:
    try:
        ctx.git.run(ctx.repo, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


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
            known[(repo_key, token)] = token in alive
    return {token for token in unique if known[(repo_key, token)]}


def _batch_shas(ctx: Context, unique: list[str]) -> set[str]:
    """The batch itself. Separate only so the memo above stays readable."""
    payload = "".join(f"{token}^{{commit}}\n" for token in unique)
    proc = subprocess.run(
        ["git", "cat-file", "--batch-check"],
        cwd=ctx.repo, input=payload, capture_output=True, text=True, encoding="utf-8",
    )
    lines = proc.stdout.splitlines()
    if len(lines) != len(unique):
        return {token for token in unique if _sha_exists(ctx, token)}
    return {
        token for token, line in zip(unique, lines)
        # Explicit success only. `<input> missing` is one failure shape;
        # `<input> ambiguous` is another, and "does not end in missing" let
        # it through as though the object had resolved.
        if len(line.split()) == 3 and not line.rstrip().endswith("missing")
    }


def _branch_exists(ctx: Context, branch: str) -> bool:
    try:
        ctx.git.run(ctx.repo, "rev-parse", "--verify", branch)
        return True
    except subprocess.CalledProcessError:
        return False


def _ancestor_index(ctx: Context, ref: str) -> dict[str, list[str]] | None:
    """Every commit reachable from `ref`, indexed by its 7-character prefix.

    ONE `git rev-list` answers what would otherwise be one
    `git merge-base --is-ancestor` per claim. Measured on a 5000-commit
    repository: rev-list costs 125 ms and returns 205 KB, while a single
    merge-base costs about 100 ms. The batch therefore pays for itself at two
    distinct commits and wins by roughly 800x at two thousand, which took that
    stress case from 105 seconds to about a second.

    Used unconditionally rather than above some threshold, deliberately. A
    size-based switch would create a second path that only runs on large inputs,
    which is precisely the code that never gets exercised by a test.

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
        out = ctx.git.run(ctx.repo, "rev-list", ref)
    except (subprocess.CalledProcessError, OSError):
        ctx.run.ancestors[key] = None
        return None
    index: dict[str, list[str]] = {}
    for full in out.split():
        index.setdefault(full[:7], []).append(full)
    ctx.run.ancestors[key] = index
    return index


def _reachable_from(ctx: Context, rev: str, ref: str) -> bool:
    """Is `rev` an ancestor of `ref`? Batched through the index when possible."""
    index = _ancestor_index(ctx, ref)
    if index is None:
        try:
            ctx.git.run(ctx.repo, "merge-base", "--is-ancestor", rev, ref)
            return True
        except (subprocess.CalledProcessError, OSError):
            return False
    if _SHA_SHAPE.match(rev):
        # A document carries an abbreviated commit; rev-list returns full ones.
        # `startswith` covers the 40-character case too, which is its own prefix.
        return any(full.startswith(rev) for full in index.get(rev[:7], ()))
    # A branch or tag name: resolve it once, then answer from the index.
    resolved = _resolve_ref(ctx, rev)
    return bool(resolved) and resolved in index.get(resolved[:7], ())


def _resolve_ref(ctx: Context, ref: str) -> str | None:
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
    heads, tags = _ref_table(ctx)
    # TAGS BEFORE HEADS, because that is git's precedence for a bare name:
    # `refs/tags/<name>` is tried before `refs/heads/<name>`. Reversing it
    # would resolve a repository that has both to a different commit than
    # `rev-parse` does, which is the kind of divergence that shows up once, in
    # somebody else's repository, as a merge claim reported false.
    resolved = tags.get(ref) or heads.get(ref)
    if resolved is None:
        # Not a plain branch or tag name: a raw SHA, a remote-tracking ref,
        # `HEAD`, `main~3`. Those still need git, and still cost a spawn.
        try:
            resolved = ctx.git.run(ctx.repo, "rev-parse", "--verify", "--quiet",
                                   f"{ref}^{{commit}}").strip() or None
        except (subprocess.CalledProcessError, OSError):
            resolved = None
    ctx.run.refs[key] = resolved
    return resolved


def _ref_table(ctx: Context) -> tuple[dict[str, str], dict[str, str]]:
    """Every local branch and tag, by short name, with annotated tags peeled.

    One subprocess answers what `rev-parse --verify` per ref, `tag -l` and
    `for-each-ref refs/heads` were each asking separately. `%(*objectname)` is
    the peeled commit for an annotated tag and empty otherwise, which is the
    same dereference `^{commit}` performs - without it an annotated tag yields
    the tag object's own SHA, which appears in no rev-list.

    Held for one call, like every other answer git gives here.
    """
    key = str(ctx.repo)
    if key not in ctx.run.ref_table:
        heads: dict[str, str] = {}
        tags: dict[str, str] = {}
        try:
            out = ctx.git.run(ctx.repo, "for-each-ref",
                              "--format=%(refname)\t%(objectname)\t%(*objectname)",
                              "refs/heads", "refs/tags")
        except (subprocess.CalledProcessError, OSError):
            out = ""
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            full, obj, peeled = parts
            commit = peeled or obj
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
    present = set(_ref_table(ctx)[0])
    for name in _INTEGRATION_NAMES:
        if name in present and name not in refs:
            refs.append(name)
    ctx.run.integration[key] = [ref for ref in refs
                                if _resolve_ref(ctx, ref) is not None]
    return ctx.run.integration[key]


def integrated_by(ctx: Context, rev: str, *, exclude: str = "") -> list[str]:
    """Which integration refs contain `rev`.

    `exclude` drops one ref from consideration, and it is load-bearing rather
    than tidy: without it a slashless topic branch is trivially an ancestor of
    itself, so every live claim about one would be reported as already merged.
    """
    return [ref for ref in integration_refs(ctx)
            if ref != exclude and _reachable_from(ctx, rev, ref)]


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
    """
    key = str(ctx.repo)
    if key in ctx.run.renames:
        return ctx.run.renames[key]
    mapping: dict[str, str] = {}
    try:
        out = ctx.git.run(ctx.repo, "log", "--diff-filter=R", "--name-status",
                          "--format=", "-n", "200")
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


def _named_in_merge_history(ctx: Context, branch: str) -> bool:
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
    out = ctx.git.run(ctx.repo, "ls-tree", "-r", "-z", "--name-only", "HEAD")
    return sorted(p for p in out.split("\0")
                  if p.strip() and p.rsplit(".", 1)[-1] in ("md", "markdown", "mdx", "rst"))
