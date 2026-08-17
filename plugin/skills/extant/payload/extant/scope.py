"""Per-run and per-document state, with stated lifetimes.

This replaces twenty-six module-level caches, three per-document globals and,
more importantly, the block in validate() that saved thirteen of them and
restored twelve. Every comment in that block recorded a bug caused by getting a
lifetime wrong. A scope object does not guard against that class; it makes it
unrepresentable, because a nested call builds its own object and the outer one
is a different object.

Four of the twenty-six did not become fields here, and the reasons are the
interesting part of the inventory rather than an exception list:

* `_STRIPPED` and `_BARE_SHAS` are keyed on the IDENTITY of the text passed in
  and read nothing else about the repository. They are pure memos that miss the
  moment a different string arrives, so they have no lifetime to state and
  stayed module-level in extant_collect.py.
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
from typing import Any

__all__ = ["Context", "DocScope", "RunScope"]


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
    dircache: dict[Path, Any] | None = None

    # Ancestry indexes and resolved refs. Git state can change between
    # validations, so an index that outlived the call would answer from a
    # repository that no longer exists in that shape.
    #
    # Keyed by (repo, ref), never by ref alone. Keying by name looked sufficient
    # and was not: rules are also called directly, without going through
    # validate(), so nothing reset the cache between two repositories that both
    # have a branch called `main` - and the second one was then answered from
    # the first one's history. The suite caught it as a TRUE merge claim
    # reported false.
    ancestors: dict[Any, Any] = field(default_factory=dict)
    refs: dict[Any, Any] = field(default_factory=dict)
    # The LFS survey walks the whole tree, and BOTH the rule and the denominator
    # need it. Computing it twice doubled the cost of the most expensive rule
    # here for no benefit.
    lfs: dict[Any, Any] = field(default_factory=dict)
    # Another document's headings, read at most once per call and held no longer
    # than the repository state they were read from.
    target_anchors: dict[Any, Any] = field(default_factory=dict)
    # Whether a SHA-shaped token resolves to a commit here, keyed
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
    # had once in the opposite direction.
    shas: dict[Any, Any] = field(default_factory=dict)
    # The origin. Left uncached at first, then cached with no lifetime at all on
    # the reasoning that a remote cannot change while a process runs - true of
    # the CLI, false of a library caller and of the tests, and the failure it
    # produced was the silent kind. A repository whose origin was added between
    # two validate() calls kept answering None, so `dead-pinned-ref` examined
    # nothing and reported clean.
    own_remote: dict[Any, Any] = field(default_factory=dict)
    # The prefix convention the repository puts before a version number, derived
    # from its tags. A tag created between two calls would otherwise keep
    # resolving to nothing.
    tag_prefixes: dict[Any, Any] = field(default_factory=dict)
    # Which branches this repository integrates into. Consulted once per claim,
    # and each miss was a `for-each-ref` SUBPROCESS: measured on a document with
    # 200 release claims and 30 tags, 11.6 seconds before and 1.2 after.
    integration: dict[Any, Any] = field(default_factory=dict)
    # Branches and tags, from one ref scan per call. This is what actually
    # carries the tag-lifetime property now that `_tags()` reads it.
    ref_table: dict[Any, Any] = field(default_factory=dict)
    # Line counts, so a sweep does not re-count the lines of a file once per
    # document that cites it.
    linecount: dict[Any, Any] = field(default_factory=dict)
    # Declared version floors, so a sweep does not re-read every manifest once
    # per document.
    manifest_floors: dict[Any, Any] = field(default_factory=dict)

    # The eleven below are the ones no `global` statement ever named. All were
    # keyed on `str(repo)` and never invalidated, so a process that validated
    # the same repository path twice across a change kept the first answer
    # forever. Making them run-scoped is a behaviour change only for such a
    # process, which no shipped mode is: `--sweep` holds one scope for the whole
    # survey, and `--verify` reads a handful of documents from one checkout.
    site: dict[Any, Any] = field(default_factory=dict)
    renames: dict[Any, Any] = field(default_factory=dict)
    numbered: dict[Any, Any] = field(default_factory=dict)
    changesets: dict[Any, Any] = field(default_factory=dict)
    basenames: dict[Any, Any] = field(default_factory=dict)
    routes: dict[Any, Any] = field(default_factory=dict)
    project_anchors: dict[Any, Any] = field(default_factory=dict)
    partial_ns: dict[Any, Any] = field(default_factory=dict)
    partial_anchors: dict[Any, Any] = field(default_factory=dict)
    global_ns: dict[Any, Any] = field(default_factory=dict)
    language_siblings: dict[Any, Any] = field(default_factory=dict)

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

    config: Any
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
    # against a caller's checkout.
    git: Any = None
