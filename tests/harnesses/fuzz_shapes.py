"""The feature catalogue `fuzz.py` draws from, one entry per rule it can reach.

WHY THIS IS A MODULE AND NOT A LIST OF STRINGS

The generator used to hold twelve content shapes and pick ONE per document.
Measured against the rules, five of them reached a rule at all and the corpus
exercised 5 of 13 rules; two were dead in the way this project keeps warning
about, writing `Merged \\`feature/x\\` into main at ...` where `merge_claim`
needs `merged` followed by `to` or `into`, and `Release \\`v9.9.9\\` shipped.`
where `release_tag` needs `shipped in`. Both matched nothing and had matched
nothing since the harness was written.

A shape that no longer fires is invisible when shapes are strings. A feature
that NAMES the rules it aims at can be checked against what the run actually
examined, which is what `fuzz.py`'s reach ledger does and why this file exists.

TRUE CLAIMS ARE THE POINT, NOT DECORATION

Every document the old generator wrote was already wrong: every claim in it was
dead. Three things follow from that, and all three were costing coverage.

  - `--selftest` was a no-op. `extant/probes.py` corrupts an ACTUAL match
    rather than injecting invented prose, so a probe needs a document that
    already holds a TRUE claim of its kind. Run against any generated
    repository it reported `0 fired, 13 had nothing to corrupt`, which is one
    of the seven fuzz modes demonstrating nothing.
  - The examined-and-clean path was never taken. A rule that looks and finds
    nothing is a different code path from a rule that looks and reports.
  - Nothing ever exercised a clean exit 0 with a non-zero denominator, which is
    the exact shape this project exists to distinguish from a silent pass.

So every feature offers both spellings, and the caller picks `true`, `false` or
`both`.

WHAT A FEATURE OWES

  name    what the swarm draws and the recipe records
  rules   the rule kinds it aims to make EXAMINE something. Checked against
          the run, never trusted - a feature claiming a rule it does not reach
          is a harness fault, because it reports coverage that is not there
  phase   `pre` runs before the first commit, `post` after, because a merge
          claim needs a real commit to name and a release claim needs a tag
  build   returns a Contribution, or None when this platform cannot build it

ORDERING IS A CONTRACT, NOT A CONVENIENCE

`Contribution.config` holds bare TOML keys and `config_tables` holds table
blocks, because TOML puts every bare key of a document before its first table
header. Merging them in draw order produced a config whose `primary_doc` landed
inside `[extant.consistency.version]`, which parses as a different setting
entirely and reads as the tool ignoring its own configuration.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

__all__ = ["Build", "Contribution", "Feature", "FEATURES", "RULE_KINDS",
           "compose_config", "compose_document", "features_for", "merge",
           "rules_claimed", "write_files"]


# Every rule kind in the package. Kept here so the ledger can report reach as a
# fraction of the real total rather than of the features that happen to exist -
# a denominator drawn from the catalogue itself would always read 100 per cent.
RULE_KINDS = (
    "dead-sha", "stale-live-claim", "unknown-branch", "false-merge-claim",
    "dead-release-tag", "dead-path-pointer", "dead-md-link", "dead-md-anchor",
    "inconsistent-artifact", "dead-pinned-ref", "raw-lfs-blob",
    "manifest-floor-mismatch", "dead-line-pointer",
)


@dataclass
class Contribution:
    """What one feature adds to the repository under construction."""

    # Lines for the document preamble, where the whole-file rules read them.
    prose: tuple[str, ...] = ()
    # Lines for the NEWEST phase entry. `stale-live-claim` and `unknown-branch`
    # read only that entry, so prose placed anywhere else is invisible to them.
    entry: tuple[str, ...] = ()
    config: tuple[str, ...] = ()          # bare TOML keys
    config_tables: tuple[str, ...] = ()   # complete `[table]` blocks
    files: tuple[tuple[str, str], ...] = ()
    binaries: tuple[tuple[str, bytes], ...] = ()


@dataclass
class Build:
    """The repository under construction, and what earlier features learned."""

    repo: Path
    rng: random.Random
    sh: Callable[..., object]
    trunk: str
    facts: dict = field(default_factory=dict)

    def git(self, *args: str):
        return self.sh(self.repo, "git", *args)

    def head(self) -> str:
        done = self.git("rev-parse", "HEAD")
        return (getattr(done, "stdout", "") or "").strip()


@dataclass(frozen=True)
class Feature:
    name: str
    rules: tuple[str, ...]
    phase: str
    build: Callable[[Build, str], Optional[Contribution]]
    # Runs after the LAST generic `git add -A` and commit. Exactly one feature
    # needs it, and it needs it because a later `git add` would undo its work;
    # see `_lfs_finalize`. Kept as a hook rather than special-casing that
    # feature in the driver, so the driver stays ignorant of what any feature
    # is for.
    finalize: Optional[Callable[[Build, str], None]] = None


def _wants(truth: str) -> tuple[bool, bool]:
    """(emit the true claim, emit the false one)."""
    return truth in ("true", "both"), truth in ("false", "both")


# --- pre-commit features ----------------------------------------------

def _path_pointer(b: Build, truth: str) -> Contribution:
    yes, no = _wants(truth)
    prose = []
    if yes:
        prose.append("See `docs/present.py` for the detail.")
    if no:
        prose.append("See `docs/absent.py` for the detail.")
    return Contribution(prose=tuple(prose),
                        files=(("docs/present.py", "value = 1\n"),))


def _md_link(b: Build, truth: str) -> Contribution:
    yes, no = _wants(truth)
    prose = []
    if yes:
        prose.append("Background lives in [the note](docs/note.md).")
    if no:
        prose.append("Background lives in [the gone note](docs/gone.md).")
    return Contribution(prose=tuple(prose),
                        files=(("docs/note.md", "# Note\n\n## Real Heading\n\nBody.\n"),))


def _md_anchor(b: Build, truth: str) -> Contribution:
    """Anchors of BOTH shapes, because the rule reads them differently.

    A same-document fragment - `[x](#heading)` - and a cross-file anchor -
    `[x](other.md#heading)` - are one claim to a reader and two populations to
    this rule: `examined` counts only targets beginning with `#`, while `check`
    judges both. So a dead cross-file anchor is reported against a denominator
    of zero, which is a DENOMINATOR violation the harness must see.

    THE FALSE SPELLING IS CROSS-FILE ONLY, AND THAT IS THE POINT. Emitting a
    fragment beside it was the first attempt, to keep the denominator honest -
    and it masked the defect completely: the fragment lifted `examined` to 1,
    the cross-file anchor supplied the finding, and `found > examined` was
    never true. The harness stopped being able to see the bug that motivated
    the feature. The true spelling carries the fragment instead, so the
    population is still exercised without a live claim propping up a dead
    one's denominator.
    """
    yes, no = _wants(truth)
    prose = []
    if yes:
        prose.append("Jump to [the section](docs/note.md#real-heading).")
        prose.append("Or to [the local one](#status).")
    if no:
        prose.append("Jump to [the section](docs/note.md#no-such-heading).")
    # Same file `_md_link` writes, and written again here on purpose: the two
    # features are drawn independently, so neither may depend on the other
    # having been drawn. Identical content, so writing it twice is harmless.
    return Contribution(prose=tuple(prose),
                        files=(("docs/note.md", "# Note\n\n## Real Heading\n\nBody.\n"),))


def _line_pointer(b: Build, truth: str) -> Contribution:
    yes, no = _wants(truth)
    body = "".join(f"line {i}\n" for i in range(1, 13))
    prose = []
    if yes:
        prose.append("See `docs/lines.py:4` for the detail.")
    if no:
        prose.append("See `docs/lines.py:9999` for the detail.")
    return Contribution(prose=tuple(prose), files=(("docs/lines.py", body),))


_LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:" + "0" * 64 + "\n"
    "size 12\n"
)


def _lfs_blob(b: Build, truth: str) -> Contribution:
    """`.gitattributes` routing a path through LFS, and a file that is or is not
    a pointer. Reads no prose at all, which is why it has none.

    The violating half is written in `_lfs_finalize`, not here, because git
    will not let an ordinary `add` produce it on a machine with git-lfs
    installed. Two attempts to make it do so are recorded there.
    """
    yes, _no = _wants(truth)
    files = [(".gitattributes", "*.bin filter=lfs diff=lfs merge=lfs -text\n")]
    if yes:
        files.append(("asset-pointer.bin", _LFS_POINTER))
    return Contribution(files=tuple(files))


def _lfs_finalize(b: Build, truth: str) -> None:
    """Put a RAW blob in the tree at a path `.gitattributes` routes to LFS.

    This cannot be done with `git add`, and the two obvious ways to try both
    fail quietly, which is why it is written out rather than left to whoever
    edits this next.

    Committing the binary and the attributes together does nothing on a machine
    with git-lfs installed: the clean filter converts the file on the way in
    and a correct 128-byte pointer reaches the tree, so the rule examines two
    files and finds zero. Pinning `filter.lfs.clean` to `cat` does not help
    either, because git-lfs registers `filter.lfs.process` - the long-running
    protocol - and git prefers that whenever it is set. Setting `process` to
    the empty string to force the fallback then breaks `git add` outright, and
    the run commits nothing at all: the sweep reported `git tracks none in this
    repository` and the whole corpus went silent.

    So the blob is hashed with `--no-filters` and written straight into the
    index. It needs no filter configuration, behaves the same whether or not
    git-lfs is installed, and is why this runs last - any later `git add -A`
    would re-stage the path through the filter and undo it.
    """
    _yes, no = _wants(truth)
    if not no:
        return
    raw = b.repo / "asset-raw.bin"
    raw.write_bytes(b"not a pointer, just bytes\n" + b"x" * 300)
    done = b.git("hash-object", "-w", "--no-filters", "--", "asset-raw.bin")
    sha = (getattr(done, "stdout", "") or "").strip()
    if not sha:
        return
    b.git("update-index", "--add", "--cacheinfo",
          f"100644,{sha},asset-raw.bin")
    b.git("commit", "-qm", "chore: a binary stored raw under an LFS filter")


def _manifest_floor(b: Build, truth: str) -> Contribution:
    """A floor claim in an ENTRY document, against a manifest that declares one.

    The claim has to live in a README or an INSTALL page: `manifest_floor`
    keys on the document NAME, so the same sentence in a status document is
    not a promise to an installing reader and is not examined. That is why the
    old `Requires Python 3.99+.` shape reached nothing - it was in
    NEXT_SESSION.md.
    """
    yes, no = _wants(truth)
    lines = ["# Widget", ""]
    if yes:
        lines.append("Requires Python 3.9 or later.")
    if no:
        lines.append("Requires Python 3.7 or later.")
    return Contribution(
        config=('extra_docs = ["README.md"]',),
        files=(("README.md", "\n".join(lines) + "\n"),
               ("pyproject.toml",
                '[project]\nname = "widget"\nrequires-python = ">=3.9"\n')))


def _consistency(b: Build, truth: str) -> Contribution:
    """Two files that must agree, configured to be compared.

    Reads no document, so `--selftest` reports NO PROBE for it by design; the
    rule's own probe says so. What this feature buys is the DENOMINATOR, which
    is zero for any repository with no consistency block.
    """
    yes, no = _wants(truth)
    files, tables = [], []
    if yes:
        files += [("agree/one.txt", "v=1.2.3\n"), ("agree/two.txt", "v=1.2.3\n")]
        tables.append('[extant.consistency.agreed]\n'
                      '"agree/one.txt" = \'v=([0-9.]+)\'\n'
                      '"agree/two.txt" = \'v=([0-9.]+)\'\n')
    if no:
        files += [("clash/one.txt", "v=1.2.3\n"), ("clash/two.txt", "v=9.9.9\n")]
        tables.append('[extant.consistency.clashed]\n'
                      '"clash/one.txt" = \'v=([0-9.]+)\'\n'
                      '"clash/two.txt" = \'v=([0-9.]+)\'\n')
    return Contribution(files=tuple(files), config_tables=tuple(tables))


def _pinned_ref(b: Build, truth: str) -> Contribution:
    """An install snippet pinning a rev, governed by a `repo:` naming us.

    Needs an `origin` remote: the rule answers only for pins aimed at THIS
    repository, and reports zero examined without one rather than judging
    somebody else's hook. The snippet is fenced, which is where install
    snippets really live, and this rule reads raw text rather than prose on
    purpose.
    """
    b.git("remote", "add", "origin", "https://github.com/acme/widget")
    b.facts["has_origin"] = True
    yes, no = _wants(truth)
    lines = ["```yaml"]
    if yes:
        lines += ["-   repo: https://github.com/acme/widget", "    rev: v1.0"]
    if no:
        lines += ["-   repo: https://github.com/acme/widget", "    rev: v0.0.0-never"]
    lines.append("```")
    return Contribution(prose=tuple(lines))


# --- post-commit features ---------------------------------------------

def _sha(b: Build, truth: str) -> Optional[Contribution]:
    yes, no = _wants(truth)
    prose = []
    if yes:
        head = b.head()
        if not head:
            return None
        prose.append(f"Recorded at `{head[:12]}` in the log.")
    if no:
        prose.append("Recorded at `deadbeef1234` in the log.")
    return Contribution(prose=tuple(prose))


def _merge_claim(b: Build, truth: str) -> Optional[Contribution]:
    """A merge claim in the spelling `merge_claim` actually reads.

    `merged` then `to` or `into` then the ref then `at` then the commit. The
    old shape put the branch between `Merged` and `into`, so the pattern never
    matched and this rule has never fired in this harness.

    The false side names a commit that is NOT an ancestor of the trunk, which
    is what makes the claim false rather than merely unresolvable - a SHA that
    does not resolve at all is skipped by the rule and would prove nothing.
    """
    yes, no = _wants(truth)
    prose = []
    if yes:
        head = b.head()
        if not head:
            return None
        prose.append(f"Merged into `{b.trunk}` at `{head[:12]}`.")
    if no:
        done = b.git("rev-parse", "--verify", "-q", "refs/heads/side-work")
        stray = (getattr(done, "stdout", "") or "").strip()
        if not stray:
            return None
        prose.append(f"Merged into `{b.trunk}` at `{stray[:12]}`.")
    return Contribution(prose=tuple(prose))


def _release_tag(b: Build, truth: str) -> Contribution:
    """A release claim in the spelling `release_tag` reads: a trigger word, then
    `in`, `as` or `at`, then the version.

    `release_claims_name_our_tags` is switched on because the half of this rule
    that reports a claimed release with no tag is off by default. Left off, the
    false claim below is correctly ignored and the feature reaches only half
    the rule.
    """
    yes, no = _wants(truth)
    prose = []
    if yes:
        prose.append("The collector shipped in `v1.0` on the trunk.")
    if no:
        prose.append("The collector shipped in `v9.9.9` on the trunk.")
    return Contribution(prose=tuple(prose),
                        config=("release_claims_name_our_tags = true",))


def _branch_token(b: Build, truth: str) -> Contribution:
    """Branch tokens in the NEWEST entry, which is the only place either branch
    rule looks. `unknown-branch` and `stale-live-claim` share this population
    and report the same denominator, so one feature feeds both."""
    yes, no = _wants(truth)
    entry = []
    if yes:
        entry.append("Work continued on `claude/real-work` this phase.")
    if no:
        entry.append("Work continued on `claude/never-existed` this phase.")
    return Contribution(entry=tuple(entry))


def _live_claim(b: Build, truth: str) -> Contribution:
    """A live phrase beside a branch, in the newest entry.

    True: the branch really is unmerged, so the claim stands. False: the branch
    was merged, so `NOT yet merged` is stale - which is the finding.
    """
    yes, no = _wants(truth)
    entry = []
    if yes:
        entry.append("Branch `claude/still-open` is NOT yet merged.")
    if no:
        entry.append("Branch `claude/already-merged` is NOT yet merged.")
    return Contribution(entry=tuple(entry))


FEATURES: tuple[Feature, ...] = (
    Feature("path-pointer", ("dead-path-pointer",), "pre", _path_pointer),
    Feature("md-link", ("dead-md-link",), "pre", _md_link),
    Feature("md-anchor", ("dead-md-anchor",), "pre", _md_anchor),
    Feature("line-pointer", ("dead-line-pointer",), "pre", _line_pointer),
    Feature("lfs-blob", ("raw-lfs-blob",), "pre", _lfs_blob,
            finalize=_lfs_finalize),
    Feature("manifest-floor", ("manifest-floor-mismatch",), "pre", _manifest_floor),
    Feature("consistency", ("inconsistent-artifact",), "pre", _consistency),
    Feature("pinned-ref", ("dead-pinned-ref",), "pre", _pinned_ref),
    Feature("sha", ("dead-sha",), "post", _sha),
    Feature("merge-claim", ("false-merge-claim",), "post", _merge_claim),
    Feature("release-tag", ("dead-release-tag",), "post", _release_tag),
    Feature("branch-token", ("unknown-branch", "stale-live-claim"), "post",
            _branch_token),
    Feature("live-claim", ("stale-live-claim",), "post", _live_claim),
)


def rules_claimed() -> set:
    """Every rule kind some feature says it reaches.

    A kind in RULE_KINDS and not here has NO feature aiming at it, which is a
    coverage hole the ledger must report differently from a feature that aimed
    and missed. The two are not the same failure and the fix is not the same.
    """
    claimed = set()
    for feature in FEATURES:
        claimed.update(feature.rules)
    return claimed


def features_for(phase: str) -> tuple[Feature, ...]:
    return tuple(f for f in FEATURES if f.phase == phase)


# --- assembly ---------------------------------------------------------

def merge(parts) -> Contribution:
    """Fold many contributions into one, preserving order within each field."""
    prose, entry, config, tables, files, binaries = [], [], [], [], [], []
    for part in parts:
        if part is None:
            continue
        prose.extend(part.prose)
        entry.extend(part.entry)
        config.extend(part.config)
        tables.extend(part.config_tables)
        files.extend(part.files)
        binaries.extend(part.binaries)
    return Contribution(tuple(prose), tuple(entry), tuple(config),
                        tuple(tables), tuple(files), tuple(binaries))


def compose_document(prose, entry) -> str:
    """The primary document: a preamble, then phase entries newest first.

    The entry structure is load-bearing rather than decorative. `split_entries`
    finds sections, classifies the ones matching `entry_prefix` as phases, and
    both branch rules read only the NEWEST of those - so an entry line placed
    in the preamble is examined by neither. A document with no phase heading at
    all reports zero examined for both, which is what every document this
    harness used to generate did.

    No `## 1. ` heading anywhere: `base_header` treats that shape as the start
    of the reference base and everything after it stops being an entry.
    """
    lines = ["# Status", ""]
    lines.extend(prose)
    lines.append("")
    lines.append("## Phase 2 - the newest entry")
    lines.append("")
    lines.extend(entry or ["Nothing to record."])
    lines.append("")
    lines.append("## Phase 1 - an older entry")
    lines.append("")
    lines.append("Earlier work, kept so the newest entry is not the only one.")
    lines.append("")
    return "\n".join(lines)


def compose_config(base: tuple, contribution: Contribution) -> str:
    """Bare keys first, then table blocks.

    TOML ends the bare-key section at the first table header, so a key emitted
    after one belongs to that table instead of to the document. Drawing
    features in a random order made that a lottery rather than a bug that shows
    up every time.
    """
    keys = list(base) + list(contribution.config)
    body = "\n".join(keys) + "\n"
    if contribution.config_tables:
        body += "\n" + "\n".join(contribution.config_tables)
    return body


def write_files(repo: Path, contribution: Contribution) -> None:
    for relative, text in contribution.files:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for relative, blob in contribution.binaries:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
