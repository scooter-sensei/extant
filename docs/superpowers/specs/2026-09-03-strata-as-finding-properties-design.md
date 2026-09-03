# Strata as a finding property

Design, 2026-09-03. Derived from the Stage 3 benchmark: 50 pinned public
repositories, payload `6bf73926b748ded8`, every figure below recomputed from
the recorded run rather than estimated.

## The problem, measured

A first run of `--sweep` over the benchmark corpus prints **54,790 findings**
across 37,073 documents. **4,431 of them are in ordinary documents.** The other
92 per cent are in four kinds of tree that a reader would not call
documentation-with-claims at all:

| stratum | as swept | share |
|:---|---:|---:|
| version-snapshot | 39,698 | 72.5% |
| historical-record | 4,765 | 8.7% |
| **ordinary** | **4,431** | **8.1%** |
| vendored | 4,175 | 7.6% |
| generated | 1,721 | 3.1% |

**A 12.4x gap between what the tool prints and what a reader would act on.**
Two repositories explain most of it, and neither is doing anything wrong:
`bazelbuild/bazel` keeps a full documentation snapshot per release, so one dead
link written once is counted in twelve directories; `angular/packages/zone.js/`
`CHANGELOG.md` supplies 391 findings on its own, and four of node's
`doc/changelogs/CHANGELOG_V*.md` supply 468 between them.

A changelog entry naming a file that has since moved is not a claim that
rotted. It is an accurate record of what was true at that release.

### Why configuration does not already solve this

`exclude_paths` exists. Stage 3 ran three configuration passes over the same
corpus and the headline did not move:

```
A  as adopted, no configuration          3,468 distinct ordinary findings
B  derived from repository structure     3,470
B  written by this project's install.py  3,438
```

Under one per cent between them. And `install.py` **refuses 35 of the 50
repositories** unaided - "No document to check. Pass `--doc <path>`, or
`--preset readme`" - so the configuration that would fix this is not written
because the tool cannot derive it and the adopter never sees the prompt.

The conclusion is not that adopters are lazy. It is that **a property of the
document should not have to be configured**: whether a tree is vendored, or a
per-release snapshot, or a changelog, is visible from the repository itself.

## What this adds

A new payload module, `extant/strata.py`, answering exactly one question:

```python
def classify(path: str, body: str = "") -> str:
    """vendored | version-snapshot | historical-record | generated | ordinary"""
```

`Located` gains a `stratum` field. `Finding` is **not touched**.

### Why `Located` and not `Finding`

A stratum is a property of the PATH, and `Located` is already the type that
pairs a finding with its path. Three consequences, all of them the reason:

- **The baseline fingerprint is untouched.** It hashes `(path, kind, detail)`
  on `Finding`. A baseline that stops matching does not fail loudly - it
  quietly re-raises findings a project agreed to leave alone, which is how a
  reader learns to stop reading the output. Nothing recorded anywhere is
  invalidated by this change.
- **No rule imports anything.** `test_rules_are_leaves` allows only
  `registry.py` to import a rule module, and shared machinery lives in
  `refs.py`, `commits.py`, `text.py`, `sites.py`, `probes.py`. If rules had to
  stamp the stratum themselves, `strata.py` would become a sixth shared module
  every rule depends on for a fact none of them uses.
- **There are four construction sites, and they all already know the path**:
  `report.py:165` and `sweep.py:350, 387, 644`. The change is four call sites
  and one new module, not thirteen rules.

## The classification rules

Path shape decides, with one content test. Ordered, first match wins, so the
strata partition rather than overlap - a tree can be generated AND
version-snapshotted, and a fixed precedence is what keeps the counts summing
to the total.

| stratum | test | measured justification |
|:---|:---|:---|
| `vendored` | a path segment in `node_modules`, `vendor`, `third_party`, `.venv`, `site-packages`, `bower_components`, `Godeps`, `_vendor` | 4,175 findings. Counting these reports another project's state through this one |
| `version-snapshot` | a segment matching `versioned_docs/version-*`, `versions?/vN*`, or `vN(.N)*` | 39,698. bazel keeps 12 per-release copies of one tree |
| `generated` | a segment in `api`, `reference`, `generated`, `_generated`, `autogen`, `_build`, `_site`, `dist`, `build`; OR a do-not-edit marker in the first 4 KB | 1,721 |
| `historical-record` | filename matching `CHANGELOG`, `CHANGES`, `HISTORY`, `NEWS`, `RELEASES`, `RELEASE-NOTES`, or `*allowlist`/`*denylist`/`*blocklist`/`*whitelist` | 4,765. `babel/scripts/parser-tests/flow/allowlist.md` alone supplies 269, and its entries are test-case paths in an external suite - never document links |
| `ordinary` | everything else | 4,431. This is the headline |

The content test is confined to `generated` deliberately: a generated file that
says so is the only kind identifiable without guessing at intent.

## What changes in the output

**Text.** The sweep summary leads with the ordinary count and breaks the rest
out as a labelled table. The per-rule `examined:` line is unchanged - stratum
and denominator are orthogonal questions and folding one into the other would
multiply that line by five.

**SARIF.** Each result carries `stratum` in its `properties` bag, so code
scanning can filter without the tool deciding for it.

**Exit codes are unchanged.** `--sweep` already reports without gating, which
is where the 12.4x problem lives; `--verify` and `--validate` gate on
configured documents, and a project that has deliberately configured a
CHANGELOG as an `extra_doc` should keep gating on it. Changing that would move
exit codes under existing users for no measured benefit. A flag to gate by
stratum can be added later if anyone asks; nothing here anticipates it.

## What this deliberately does NOT do

- **No de-duplication.** Collapsing bazel's twelve copies of one defect takes
  the corpus from 4,431 to 3,468, a further 1.3x. It needs findings to be
  grouped across documents, which is an analysis-time concern and a much larger
  change. Labelling alone buys 12.4x of the available 15.8x.
- **It does not replace `exclude_paths`.** Excluding HIDES; a stratum LABELS.
  The denominator philosophy already refuses the first: a rule that goes quiet
  because a tree was excluded is indistinguishable from a rule that broke.
  Both mechanisms stay, and they answer different questions.
- **It adds no rule and widens no pattern.** Three candidates were refused
  during design on measured population and are recorded in
  `extant-hardening/specs/2026-09-03-stage3-results.md`: case-only link
  resolution (1 occurrence in 34,169 links, 1 of 50 repositories),
  readthedocs as a generator signature (6 of 8 carriers already recognised via
  Sphinx's `conf.py`; of the rest, node's is a vendored dependency's config),
  and `doc/` in `_SITE_DIRS` (real gap, but zero findings would change, because
  none of the four affected findings is a root-relative link).

## Testing

- **Unit tests for `classify`**, one per stratum plus the precedence order,
  since the ordering is what makes the strata a partition.
- **A partition test**: over a recorded corpus fixture, the per-stratum counts
  sum to the total. This is the property that catches an overlapping rule.
- **A `Located` test** asserting `Finding` is unchanged and the baseline
  fingerprint for a known finding is byte-identical before and after.
- **Module quality**: `strata.py` declares `__all__`, stays inside the 900-line
  ceiling with no function over 303, is ASCII throughout, and imports nothing
  from the package - it takes a path and a string, so it cannot be half of a
  cycle.
- **The full gate before merge**: `pytest`, `mutate.py --check-only`, then
  `smoke.py`, `scenarios.py` and `fuzz.py` against a `git archive` extract,
  then `--verify` and `--selftest`.

## Risk

The classifier is a set of path patterns, and a wrong pattern mislabels a real
finding into a stratum a reader is filtering out - which is the same failure as
a suppression that fires wrongly, and `design.md` is explicit that those are
worse than false positives because they delete signal silently rather than
appearing in the output for somebody to argue with.

Two things bound it. The finding is still **reported and counted**, only
labelled, so nothing disappears. And the patterns are the ones already measured
across 50 repositories in the Stage 3 apparatus, where their effect on every
count is recorded and reproducible.
