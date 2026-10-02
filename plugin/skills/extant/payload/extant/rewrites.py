"""What a history rewrite recorded, and the two things read off it.

A `git filter-repo` run leaves a commit-map and the shipped post-rewrite hook
keeps a journal of every rebase and amend; both are `<old> <new>` per line.
Read here into one mapping, through one ambiguity rule, for the two callers
that need it: the hint `dead-sha` prints beside a dead commit (`rewrite_hint`)
and the `--sha-map` repair (`translate_shas` in extant/commits.py), which
asks `translated_value` for every token it finds.

Out of extant/commits.py on 2026-10-01, moved byte for byte, when the audit's
change to the translator took that module past its 927-line ceiling in
tests/test_module_quality.py. The cut is between FINDING a commit in a
document, which stays there beside every scanner the translator must agree
with, and what a rewrite RECORDED about it, which reads no document at all.
Two names lost their underscore because the translator calls them across
the new boundary: `bucket_index` and `translated_value`. Imports nothing
from extant/commits.py, so the two cannot be a cycle.
"""
from __future__ import annotations

from pathlib import Path

from extant.git import rewrite_journal_path, rewrite_map_path
from extant.scope import Context

__all__ = ["_BUCKET", "_mapped_values", "_read_rewrite_map", "_rewrite_map",
           "_settled_value", "bucket_index", "load_sha_map", "rewrite_hint",
           "translated_value"]


def load_sha_map(path: str) -> dict[str, str]:
    """Parse a rewrite record: old SHA, whitespace, new SHA, per line.

    git-filter-repo's commit-map is exactly that. The post-rewrite journal
    is the same two fields as git writes them to the hook, and git's line
    is `<old> SP <new> [SP <extra-info>]` - so a third field is tolerated
    and ignored rather than making the pair invisible. A line with fewer
    than two fields, or the commit-map's `old new` header, maps nothing a
    SHA-shaped token can match.
    """
    mapping: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) >= 2:
                mapping[parts[0]] = parts[1]
    return mapping


# The shortest abbreviation git will produce, and the shortest a SHA-shaped
# token can be - `SHA_SHAPE` and `BARE_SHA_TOKEN` both require seven. Bucketing
# on exactly that many characters is therefore lossless for every token either
# scanner can hand us, and the fallback below covers anything shorter.
_BUCKET = 7


def bucket_index(mapping: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """Group a commit-map by the first `_BUCKET` characters of its old SHA.

    Built once per map so a lookup reads one bucket instead of the whole
    mapping. Measured before it existed, on a 200,000-entry map: one dead SHA
    in a document cost 704 ms and two hundred cost 4,112 ms, because every
    lookup walked all 200,000 entries. That is O(findings x map), and both
    factors grow with exactly the repositories this is for - a long history
    rewritten by `filter-repo`, and a plan directory full of citations.

    The cost was not new, only newly on the default path: `--sha-map` scanned
    the same way, and nothing but an explicit flag paid for it. Reporting the
    replacement moved it onto every run, which is what made it worth fixing
    rather than noting.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    for old, new in mapping.items():
        index.setdefault(old[:_BUCKET], []).append((old, new))
    return index


def _mapped_values(token: str, mapping: dict[str, str],
                   index: dict[str, list[tuple[str, str]]] | None = None
                   ) -> list[str]:
    """Every full post-rewrite value an old SHA starting with `token` has.

    One list, two readers - the rewriter below and the hint the `dead-sha`
    rule prints - so the ambiguity rule is applied to both by construction
    rather than by two functions agreeing. That is the same argument
    `translate_shas` makes about scanning: one claim, one scanner.

    The index is an optimisation and must never be a second answer. It is
    consulted only for a token at least `_BUCKET` long, where the bucket
    provably holds every old SHA that could start with it; anything shorter,
    or an absent index, walks the mapping exactly as before. Two paths that
    can disagree is the shape this project refuses, so this one cannot: the
    bucketed path is a filter over the same predicate, not a different test.
    """
    if index is not None and len(token) >= _BUCKET:
        hits = [new for old, new in index.get(token[:_BUCKET], ())
                if old.startswith(token)]
    else:
        hits = [new for old, new in mapping.items() if old.startswith(token)]
    settled = (_settled_value(new, mapping) for new in hits)
    return [new for new in settled if new is not None]


def _settled_value(new: str, mapping: dict[str, str]) -> str | None:
    """Where a chain of rewrites ends, or None if it never does.

    A branch rebased twice journals `a b` and then `b c`, and a filter-repo
    run after a rebase does the same across the two records. A hint - or a
    `--sha-map` repair - naming `b` reads as correct and is as dead as `a`,
    which is exactly the wrong-SHA-worse-than-dead-SHA failure the
    ambiguity rule refuses; so the chain is followed here, in the one
    lookup both readers share, to the id that is not itself rewritten. A
    value that is never rewritten again settles in zero steps, which is
    every entry of a plain commit-map. A chain that returns to itself
    cannot come from git and is not settled: None, and no hint.
    """
    steps = 0
    while new in mapping and steps <= len(mapping):
        new = mapping[new]
        steps += 1
    return None if new in mapping else new


def translated_value(token: str, mapping: dict[str, str],
                      index: dict[str, list[tuple[str, str]]] | None = None
                      ) -> str | None:
    """New value for `token` via prefix match, or None if it must stay put.

    GA-6: an AMBIGUOUS prefix - two old SHAs sharing it - is left untranslated
    rather than resolved by dict order. Picking a winner silently would rewrite
    a reference to point at the wrong commit, and a wrong SHA is worse than a
    dead one: the dead one is visibly broken, the wrong one reads as correct.
    Shared by both the backticked and bare translation paths below, so both
    apply the same ambiguity rule.
    """
    hits = _mapped_values(token, mapping, index)
    return hits[0][: len(token)] if len(hits) == 1 else None


def _read_rewrite_map(
    repo: Path,
) -> tuple[dict[str, str], dict[str, list[tuple[str, str]]], str | None]:
    """The repository's commit-map, and why it could not be read if it could not.

    Two answers rather than one, because "no rewrite has happened here" and
    "a rewrite happened and its record is unreadable" are the pair this
    project refuses to conflate. An empty mapping and a None reason is the
    first; an empty mapping and a reason is the second, and the reason travels
    all the way out to the finding a reader sees.
    """
    # TWO records, one reader. The commit-map a `filter-repo` run leaves and
    # the journal the post-rewrite hook keeps of every rebase and amend are
    # read into one mapping, so the hint and `--sha-map` explain a rebase
    # exactly the way they already explained a filter-repo. An old id the two
    # send to DIFFERENT places is dropped rather than resolved by reading
    # order - the ambiguity rule across records, for the reason
    # `translated_value` gives within one.
    records = [("a rewrite map", rewrite_map_path(repo)),
               ("the rewrite journal", rewrite_journal_path(repo))]
    mapping: dict[str, str] = {}
    disputed: set[str] = set()
    for noun, path in records:
        if path is None:
            continue
        try:
            found = load_sha_map(str(path))
        except (OSError, UnicodeDecodeError) as exc:
            # Reported, not swallowed. A record present and unreadable that
            # answered like a record absent would take the one signal that
            # explains this project's largest finding class and hide it
            # behind the finding itself.
            return {}, {}, (f"{noun} at {path.as_posix()} could not be "
                            f"read ({exc.__class__.__name__})")
        for old, new in found.items():
            if old in mapping and mapping[old] != new:
                disputed.add(old)
            mapping[old] = new
    for old in disputed:
        del mapping[old]
    # Indexed here, once, beside the read that produced it. Building it
    # per lookup would reintroduce the walk it exists to remove.
    return mapping, bucket_index(mapping), None


def _rewrite_map(
    ctx: Context,
) -> tuple[dict[str, str], dict[str, list[tuple[str, str]]], str | None]:
    """Cached for the run, like every other answer the disk gave.

    A sweep validates every tracked document in one scope and a commit-map
    carries one line per commit, so reading it once per file is exactly the
    cost `--sweep` took ownership of the directory listings to avoid. The
    lifetime is the run's for the usual reason: a repository rewritten between
    two validations has to be visible to the second.
    """
    key = str(ctx.repo)
    if key not in ctx.run.rewrite_map:
        ctx.run.rewrite_map[key] = _read_rewrite_map(ctx.repo)
    return ctx.run.rewrite_map[key]


def rewrite_hint(ctx: Context, token: str) -> str | None:
    """What this repository's rewrite map says became of a dead SHA.

    Called only for a token already known to be dead, which is what keeps a
    clean document from paying to read the map at all.

    Three answers and a silence:

    * the replacement, when exactly one old SHA carries this prefix;
    * that the commit was REMOVED, when the map sends it to forty zeroes -
      filter-repo's spelling for a commit it dropped, and offering the reader
      forty zeroes to paste would name nothing;
    * that a map is present and unreadable;
    * and nothing at all for an ambiguous prefix, on `translated_value`'s
      reasoning, which does not weaken for being a hint rather than a rewrite:
      a wrong SHA reads as correct.
    """
    mapping, index, problem = _rewrite_map(ctx)
    if problem is not None:
        return problem
    hits = _mapped_values(token, mapping, index)
    if len(hits) != 1:
        return None
    new = hits[0]
    if set(new) == {"0"}:
        return "the rewrite map records that commit as removed"
    return f"the rewrite map records it as `{new[: len(token)]}`"
