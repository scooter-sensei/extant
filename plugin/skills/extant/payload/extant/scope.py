"""Per-run and per-document state, with stated lifetimes.

This replaces twenty-six module-level caches, three per-document globals and,
more importantly, the block in validate() that saved thirteen of them and
restored twelve. Every comment in that block recorded a bug caused by getting a
lifetime wrong. A scope object does not guard against that class; it makes it
unrepresentable, because a nested call builds its own object and the outer one
is a different object.

Four of the twenty-six did not become fields here, and the reasons are the
interesting part of the inventory rather than an exception list. Memos added
SINCE the split are listed with them, marked as such, so this stays a census of
what is module-level now rather than of what was module-level then:

* `_BARE_SHAS` is keyed on the IDENTITY of the text passed in and reads
  nothing else about the repository - `find_bare_sha_candidates` (commits.py)
  takes only `text`. It is a pure memo that misses the moment a different
  string arrives, so it has no lifetime to state and stayed module-level in
  extant_collect.py. It has since been joined by two siblings in the same
  module for the same reason - `_SHA_CANDIDATES` and `_MERGE_CLAIMS`, which
  memoise the other two per-document scans the SHA and merge rules each read
  three times. Neither is in the inventory below because neither existed at
  the split; both are listed here so this file stays the census of what is
  module-level rather than a census of what once was.
* `_STRIPPED` is keyed on identity AND on `doc.doc_format`, since
  2026-09-16. The format was missing for months and this paragraph recorded
  it as a latent bug: `_blank_uncached` (extant/text.py) strips markdown and
  reStructuredText differently, so a caller validating one text OBJECT under
  two formats got the first blanking back both times. Counted before it was
  fixed, over a sweep of the 152 visible corpus clones: 868,986 memo hits, 0
  answered under the wrong format, because a sweep reads each document once
  into its own string. Fixed anyway; the key is complete now, so this memo
  is exactly as pure as `_BARE_SHAS` and module-level for the same reason.
* `_PATH_SITES` (added since the split; extant/rules/path_pointer.py) came from
  the same measurement as those two: `dead-path-pointer`'s `check` and its
  `examined` each scanned the document for pointers, so one scan per document
  was being bought twice. Its key carries the text, the pattern AND
  `doc.doc_format` - the last because the scan runs over `prose()`, so it is
  precisely the half of the key `_STRIPPED` above went without for months,
  and copying that omission was the one thing this memo had to avoid; both
  carry it now. Pure given those three, so
  it is not in `registry.forget_memos` and has no lifetime to state.
* `_POINTER_SITES` is not pure - it reads the filesystem through `_line_count`
  and so has to be dropped when that is - but its consumer, `count_examined`,
  runs AFTER validate() returns. A value tied to the call's scope would be
  thrown away exactly when it is needed, which is the version that was written
  first and silently halved nothing. It stayed module-level too, invalidated by
  validate() when a fresh scope opens.
* `_TAGS` was dead. `_tags()` has answered from `_ref_table` since 6c5c29c, and
  nothing has read or written `_TAGS` since; only the save-and-restore
  choreography still named it. Carrying it here would have given a documented
  lifetime to state nobody keeps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from extant.config import Config
from extant.git import Git

__all__ = ["AncestryIndex", "Context", "DocScope", "RunScope"]


class AncestryIndex(Protocol):
    """The shape of what `ancestors` holds, stated here so the field can say
    so without importing the class that builds it.

    The one implementation is `refs._Ancestry`, and it stays private to
    extant/refs.py, which imports this module; naming it here would close a
    cycle the import-cycle test refuses, `TYPE_CHECKING` or not. What this
    scope needs is only the shape: the newest `INDEX_BOUND + 1` commits of a
    ref as full SHAs, whether that was the whole history, and what the batches
    have since settled about commits past the bound. `index_incomplete` below
    reads the second of these, and reads it typed.
    """

    commits: frozenset[str]
    complete: bool
    settled: dict[str, bool]


@dataclass
class RunScope:
    """Answers git and the filesystem gave, held for one validate() call or for
    one sweep, and thrown away after.

    Mutable by design and never shared between runs. Every field is a mapping
    keyed by whatever its one reader keys it by; the lifetime is the OBJECT's,
    not the key's, which is the property the old `str(repo)` keys could not
    express. Twelve of the caches below were keyed that way and were never
    invalidated at all - not because anyone decided they should live forever,
    but because a subscript assignment needs no `global` statement, so no
    census of `global` statements ever listed them.

    The lifetime rule is one sentence and applies to every field: an answer git
    or the filesystem gave is held for ONE call and thrown away after. Held
    longer, a repository that changed between two calls keeps resolving to what
    it used to be. Rebuilt more often, nothing is wrong and everything is
    slower.
    """

    # Directory listings. None means CACHING IS OFF, which is the state whenever
    # a rule is called directly rather than through validate() - the one field
    # here whose empty value is not an empty mapping.
    #
    # That matters: a caller that creates a file between two checks must see the
    # new answer, and a cache with no owner would quietly hand back the old one.
    # Correctness is the default; speed is opted into by the one function that
    # knows the scope.
    #
    # The case check lists a directory per path component, so 3000 links four
    # levels deep cost 12,000 listings and 0.88 of 6.4 seconds. Within one
    # validate() the filesystem is assumed stable, which every rule already
    # assumes.
    dircache: dict[Path, set[str]] | None = None

    # Ancestry indexes and resolved refs. Git state can change between
    # validations, so an index that outlived the call would answer from a
    # repository that no longer exists in that shape.
    #
    # An index is a `refs._Ancestry`, whose shape `AncestryIndex` above
    # states: the newest `INDEX_BOUND + 1` commits of the ref as full SHAs,
    # whether that was the whole history, and what the batches have since
    # settled about commits past the bound. All three on one object because
    # they share this one lifetime and this one key. None is a ref that did
    # not resolve.
    #
    # Keyed by (repo, ref), never by ref alone. Keying by name looked sufficient
    # and was not: rules are also called directly, without going through
    # validate(), so nothing reset the cache between two repositories that both
    # have a branch called `main` - and the second one was then answered from
    # the first one's history. The suite caught it as a TRUE merge claim
    # reported false.
    ancestors: dict[tuple[str, str], AncestryIndex | None] = field(
        default_factory=dict)
    # (repo, ref) -> the full commit id, or None for a ref that does not exist.
    refs: dict[tuple[str, str], str | None] = field(default_factory=dict)
    # The LFS survey walks the whole tree, and BOTH the rule and the denominator
    # need it. Computing it twice doubled the cost of the most expensive rule
    # here for no benefit. repo -> (tracked path, blob id) for every governed
    # file.
    lfs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # Another document's headings, read at most once per call and held no longer
    # than the repository state they were read from. path -> its anchor set,
    # or None for a file that could not be read.
    target_anchors: dict[str, set[str] | None] = field(default_factory=dict)
    # The full commit id a SHA-shaped token resolves to here, or None, keyed
    # (repo, token). Two rules ask - `dead-sha` about the tokens it found and
    # `false-merge-claim` about the commit each claim names - and before this
    # they asked in two separate `cat-file --batch-check` subprocesses, one per
    # rule, with the sets overlapping. Measured on this repository's own
    # document: 29 tokens in one batch, 2 in the other, 1 token in both.
    #
    # Per TOKEN rather than per batch, so the second rule pays nothing for what
    # the first already learned, and so a sweep does not re-resolve the same
    # commit once per document that cites it. The lifetime is the run's, like
    # every field here: a commit created between two validate() calls has to be
    # visible to the second, which is the failure `own_remote` below already
    # had once in the opposite direction. The VALUE is the full id rather than
    # a boolean since 2026-09-15, because the ancestry index answers by
    # full-SHA membership and the batch line already carried it.
    shas: dict[tuple[str, str], str | None] = field(default_factory=dict)
    # The origin. Left uncached at first, then cached with no lifetime at all on
    # the reasoning that a remote cannot change while a process runs - true of
    # the CLI, false of a library caller and of the tests, and the failure it
    # produced was the silent kind. A repository whose origin was added between
    # two validate() calls kept answering None, so `dead-pinned-ref` examined
    # nothing and reported clean. repo -> the normalised origin, or None.
    own_remote: dict[str, str | None] = field(default_factory=dict)
    # The prefix convention the repository puts before a version number, derived
    # from its tags. A tag created between two calls would otherwise keep
    # resolving to nothing. repo -> the distinct prefixes, sorted.
    tag_prefixes: dict[str, list[str]] = field(default_factory=dict)
    # Which branches this repository integrates into. Consulted once per claim,
    # and each miss was a `for-each-ref` SUBPROCESS: measured on a document with
    # 200 release claims and 30 tags, 11.6 seconds before and 1.2 after.
    integration: dict[str, list[str]] = field(default_factory=dict)
    # Branches and tags, from one ref scan per call. This is what actually
    # carries the tag-lifetime property now that `_tags()` reads it.
    # repo -> (heads, tags), each mapping a short name to its commit.
    ref_table: dict[str, tuple[dict[str, str], dict[str, str]]] = field(
        default_factory=dict)
    # Line counts, so a sweep does not re-count the lines of a file once per
    # document that cites it. Keyed "repo\0relative path"; None is a file that
    # could not be read.
    linecount: dict[str, int | None] = field(default_factory=dict)
    # Declared version floors, so a sweep does not re-read every manifest once
    # per document. repo -> language -> (floor, manifest path, enforcement).
    manifest_floors: dict[str, dict[str, tuple[str, str, str]]] = field(
        default_factory=dict)
    # The commit-map a `git filter-repo` run left behind, parsed once, with the
    # reason it could not be read if it could not. Keyed by repository, read
    # only when a document already has a dead SHA to explain - a map carries one
    # line per commit, and a clean document should not pay for one.
    #
    # Run-scoped for the reason every field here is, and the reason bites
    # harder than usual: a rewrite is exactly the event that changes this
    # answer, so a map held past the call that read it would keep explaining
    # dead SHAs with the previous rewrite's mapping. repo -> (old id -> new id,
    # the bucket index `_mapped_values` searches it through, and the reason the
    # map could not be read, or None).
    rewrite_map: dict[str, tuple[dict[str, str], dict[str, list[tuple[str, str]]],
                                 str | None]] = field(default_factory=dict)

    # The eleven below are the ones no `global` statement ever named. All were
    # keyed on `str(repo)` and never invalidated, so a process that validated
    # the same repository path twice across a change kept the first answer
    # forever. Making them run-scoped is a behaviour change only for such a
    # process, which no shipped mode is: `--sweep` holds one scope for the whole
    # survey, and `--verify` reads a handful of documents from one checkout.
    #
    # Each is keyed by `str(repo)` unless its annotation says otherwise, and
    # the value is what the one function that fills it returns: the site
    # scopes and the two anchor namespaces are sets of strings, the numbered
    # docs trees and the routes are counts by name, the rename map is old path
    # -> new path, the basename census is tree -> leaf -> count, and the three
    # booleans are answers to "does this repository declare one".
    site: dict[str, set[str]] = field(default_factory=dict)
    renames: dict[str, dict[str, str]] = field(default_factory=dict)
    numbered: dict[str, dict[str, int]] = field(default_factory=dict)
    changesets: dict[str, bool] = field(default_factory=dict)
    basenames: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    routes: dict[str, dict[str, int]] = field(default_factory=dict)
    project_anchors: dict[str, set[str]] = field(default_factory=dict)
    partial_ns: dict[str, bool] = field(default_factory=dict)
    partial_anchors: dict[str, set[str]] = field(default_factory=dict)
    global_ns: dict[str, bool] = field(default_factory=dict)
    # (repo, directory) -> how many language-coded siblings that directory has.
    language_siblings: dict[tuple[str, str], int] = field(default_factory=dict)

    # Three more of the same kind, added after profiling a sweep: the tracked
    # file list, the site directories, and reference resolution. Each is a
    # question about the CHECKOUT rather than about any document, so a survey
    # asks it once instead of once per file. Scoped exactly as the eleven
    # above are, and read only while `dircache` says the checkout is static.
    tracked_markdown: dict[str, list[str]] = field(default_factory=dict)
    site_dirs: dict[str, list[Path]] = field(default_factory=dict)
    # (base directory, the link as written) -> (resolves, the actual spelling
    # when it differs only in case), which is `sites.resolve_reference`'s
    # answer verbatim.
    reference_resolutions: dict[tuple[str, str], tuple[bool, str | None]] = field(
        default_factory=dict)

    # Whether a `.rs` file beside a document pulls it into rustdoc, keyed by
    # the document's path. A question about the CHECKOUT again - it reads
    # source files - and asked at most once per document per run, only when a
    # link in that document has the shape of a Rust path and resolved to no
    # file, which is rare. Same lifetime as the three above and for the same
    # reason: the source files it reads are part of the checkout `dircache`
    # says is static. directory -> the documents its `.rs` files include.
    rustdoc_includes: dict[str, set[str]] = field(default_factory=dict)

    # NOT a cache, and the one field a fresh scope is asked about rather than
    # read from. True only while a caller reads many documents from one static
    # checkout and writes nothing while doing so; validate() then leaves this
    # scope alone instead of opening a fresh one per document.
    #
    # `run_sweep` (extant/sweep.py) is the whole reason it exists. It validates
    # every tracked file in turn, and each call was re-listing the same
    # directories: profiled over 1600 documents in 20 directories,
    # `_listdir` (extant/sites.py) built 128,000 Path objects to answer 20
    # distinct questions.
    #
    # The narrowness is the safety argument. The default stays False, so the
    # promise `dircache` makes above - a caller that creates a file between two
    # checks sees the new answer - holds for every other caller unchanged.
    # `run_sweep` opens no file for writing and shells out to nothing that
    # could, which is what makes the promise safe to suspend there and nowhere
    # else.
    stable: bool = False

    def index_incomplete(self) -> bool:
        """Did any ancestry index built in this scope reach its bound?

        A fact OF the scope, which is why it is answered here and why the
        note that reports it could not be printed for a year: the modes print
        their repository notes after the scope has closed, and the index is
        gone with it. A None in `ancestors` is a ref that did not resolve,
        which is not an incomplete index.
        """
        return any(index is not None and not index.complete
                   for index in self.ancestors.values())


@dataclass(frozen=True)
class DocScope:
    """The document currently being read.

    Separate from RunScope because a sweep holds one run scope across many
    documents while these three change per file. Conflating them is what made
    the old code save and restore two globals around the sweep loop, and get it
    wrong the first time: restoring them only AFTER the loop left the last swept
    document installed whenever a rule raised, so the next validation in the
    process resolved relative links against a directory it never chose.

    Frozen, so a caller REPLACES the document rather than editing one in place.
    The three values move together and there is no legitimate moment at which
    two of them describe one file and the third describes another.
    """

    # The DIRECTORY the text came from, because a relative markdown link
    # resolves against its own file rather than against the repository root and
    # the rule signature (repo, text) carries no path. None means the caller did
    # not say, and the repository root is used.
    link_base: Path | None = None

    # The markup language, for the same reason and set beside the other two.
    # It matters because `[text](url)` is markdown and nothing else. In
    # reStructuredText that shape occurs in ordinary Python - numpy writes
    # `np.dtype[mp.mpf](dps=100)` in a doctest - so every match is false by
    # construction, not by accident. Twenty-three of numpy's findings and all
    # ten of Sphinx's were exactly that.
    #
    # "markdown", not "md". `rule_applies` in extant/session.py skips the
    # markdown-only rules whenever this is anything else, so a plausible
    # misspelling switches off `dead-md-link` and `dead-md-anchor` for every
    # caller that never sets one.
    doc_format: str = "markdown"

    # The repository-relative path. A rule that keys on WHICH document it is
    # reading needs this; `link_base` gives only the directory. None means the
    # caller did not say, and a rule that needs the path must then stay silent
    # rather than guess.
    doc_path: str | None = None


@dataclass(frozen=True)
class Context:
    """What every rule receives.

    Built by validate() today and read only to install the two scopes, because
    the shim's rules are still functions taking (repo, text) and cannot be
    handed anything. Task 9 gives them this instead, at which point the two
    module-level installs it feeds disappear.
    """

    config: Config
    run: RunScope
    doc: DocScope
    repo: Path
    # The Git interface from git.py, which says the same thing from the other
    # side. validate() fills this with whatever the shim currently has
    # installed, and the shim's rules read that installed name directly,
    # because a rule taking `(repo, text)` has no argument this could arrive
    # through. Task 9 gives them the Context and this becomes the only route.
    #
    # Still defaulting to None, and deliberately: a Context built without one
    # must fail where git is used rather than quietly spawn a real process
    # against a caller's checkout. The declared type is what every reader may
    # assume and what the fifteen `ctx.git.run` sites are checked against; the
    # default violates it on purpose, and the suppression is the sentence
    # above written where the checker reads. tests/test_scope.py pins the
    # None.
    git: Git = None  # type: ignore[assignment]
