# Expanding the fuzz harness

Design for rebuilding the generator in `tests/harnesses/fuzz.py` and growing
its property set. Written 2026-08-31.

Every claim-shaped example below sits inside a code fence on purpose. `--sweep`
reads every tracked markdown file in this repository, and this document is full
of deliberately dead pointers and version strings. `strip_code` blanks a fence
before any rule reads it, so a fenced example is invisible to the rules and a
bare one would be a false positive in the tool's own report. The same reasoning
is why `README.md` and `CHANGELOG.md` are excluded from `.extant.toml`.

## Why now

The harness has one commit in its history. It was written, it found one defect
on its first run - an empty SARIF document from a repository git tracked no
markdown in - and it has not been touched since. `tests/test_fuzz_findings.py`
holds that one seed's findings and nothing else.

That is not a harness anybody has been running with fresh seeds.

## What was measured

Every number below came from running the thing, not from reading it.

**The generator reaches 5 of 13 rules.** Each content shape was built into its
own clean repository and swept. Shapes that reach a rule:

| Shape | Rule examined |
|:---|:---|
| a `see` pointer at a missing file | `dead-path-pointer` |
| a merge sentence with a hex token | `dead-sha` only |
| two markdown links at missing targets | `dead-md-link` |
| a pointer carrying a line suffix | `dead-line-pointer` |
| repeated headings plus a fragment link | `dead-md-anchor` |

Shapes that reach nothing at all: the release claim, the Python floor claim,
the unclosed fence, the long line, the right-to-left prose, and the nested
backticks. Never reached by any shape: `stale-live-claim`, `unknown-branch`,
`false-merge-claim`, `dead-release-tag`, `dead-pinned-ref`,
`inconsistent-artifact`, `raw-lfs-blob`, `manifest-floor-mismatch`.

**Two shapes are dead in the way this project keeps warning about.** The merge
shape reads:

```text
Merged `feature/x` into main at `deadbeef1234`.
```

`merge_claim` needs `merged` followed by `to` or `into`. Here `merged` is
followed by the branch, so the pattern never matches and `false-merge-claim`
has never fired in this harness. Only `branch_token` matches, which is why the
sweep reports `dead-sha` and nothing else. A spelling the rule reads would be:

```text
Merged into `main` at `deadbeef1234`.
```

The release shape reads:

```text
Release `v9.9.9` shipped.
```

`release_tag` matches a version only after `released`, `shipped` or `tagged`
followed by `in`, `as` or `at`. This is exactly the distinction `AGENTS.md`
records as having left ten status entries unread for six releases, and the fuzz
harness wrote the unreadable spelling.

**`--selftest` is a no-op across the whole corpus.** Run against any built
repository it reports:

```text
0 fired, 13 had nothing to corrupt, 0 could not be run, 0 stayed silent
```

The cause is structural. `extant/probes.py` says a probe "mutates an ACTUAL
match rather than injecting invented prose", so a probe needs a document that
already holds a true claim of that kind. The generator has never produced a
true claim - every document it writes is already wrong. So one of the seven
modes in the rotation spends its share of the budget demonstrating nothing.

**Forty per cent of the corpus reaches no rule.** The fixed CI seed reports 21
of 35 repositories producing rule counts, plus 6 runs that decline to start.

**With the CI arguments it is not a fuzzer.** Five git states times seven modes
is 35 pairs, and CI passes `--repos 35` on a fixed seed, so the plan is
exhausted with zero random draws. The job is a deterministic 35-case scenario
suite. That is a defensible gate, and the README argues for it, but it means
all discovery depends on hand-run fresh seeds.

**Whole axes are absent.** Seven config shapes against 30 settings. Every
document is UTF-8 with LF endings, though `text.py` carries two contracts that
broke on exactly that axis. Git history is always linear: no merges, no
annotated tags, no `.gitattributes` for `raw-lfs-blob` to read, no packed refs,
no rewritten history for `--sha-map`. Of the nine mutually exclusive modes,
five are fuzzed and four are not: `--collect`, `--archive`, `--search` and
`--check-text`. Nine further flags are never passed at all: `--as-path`,
`--full`, `--suggest-fixes`, `--out`, `--suite-json`, `--sha-map`,
`--baseline`, `--write-baseline` and `--baseline-check`. No repository has ever
been a generated site, though `sites.py` decides whether the link rules judge
at all.

**The format axis is bolted only to `--sweep`.** `MODES` pairs sarif and github
with the survey mode and nothing else, so the `FORMATS` property has never once
seen the output of a gating run. `--validate --format=sarif` has never been
executed by this harness.

**Two checks fail open.** `_rule_counts` regexes the `examined:` line and
returns an empty mapping when it does not match, and `DENOMINATOR` then
iterates nothing and passes. A mode that ought to print a denominator and stops
printing one is therefore indistinguishable from a mode with clean counts.
Separately, `UNSTABLE` compares `stdout` between the two runs and never
`stderr`, which is where every diagnostic, the sweep's "git tracks none" line
and every rule error are written.

**Four of six properties have never been observed failing.** `CRASH` and `HANG`
are self-evident. `DENOMINATOR`, `EXIT`, `UNSTABLE` and `FORMATS` have no
evidence they would go red, which is the rule this project keeps relearning.

**CI runs it on Linux only.** The shapes that only matter on Windows - CRLF,
case-insensitive filesystems, path length - are fuzzed nowhere.

## What stays

The property layer is the strong half and is not being replaced. Its three good
decisions carry forward unchanged:

- properties that hold whatever the right answer is, so no oracle is needed
- "could not build" as its own column, never counted as a pass
- walking the (git state, mode) product before drawing randomly

## Non-goals

- No third-party dependency. `requirements-dev.txt` is pytest and tomli.
  Swarm selection and ddmin are a few dozen lines each; Hypothesis is not
  worth a new dev dependency here.
- No network. The differential stage reads git tags, never a package index.
- Not a second store of regressions. Findings still reduce to cases in
  `tests/test_fuzz_findings.py`; this harness discovers and that file
  remembers.
- Not a shared generator for the other harnesses. Stage 1 builds the catalogue
  as an importable module so `smoke.py`, `scenarios.py`, `perf.py` and
  `stress.py` *can* adopt it later, but adopting it is out of scope.

## Stage 1 - a feature catalogue drawn swarm-style

Replace the inline chain of independent draws in `build_repo` with a declared
catalogue. Each feature states what the repository must contain for it to be
reachable and what it writes:

```text
merge-claim      needs a commit          writes one true claim and one false
release-tag      needs a tag             writes one true claim and one false
lfs-blob         needs .gitattributes    ...
manifest-floor   needs a manifest        ...
```

Two claims per rule, one true and one false, is the single change that closes
three holes at once: the eight unreached rules, the two dead shapes above, and
the `--selftest` no-op, which cannot be fixed any other way because probes
corrupt real matches.

Draw a random *subset* of features per repository rather than drawing each one
independently at a tuned probability. This is Groce et al.'s swarm testing
(ISSTA 2012), whose result was 42 per cent more distinct compiler crashes than
a hand-tuned default configuration, and whose stated benefit is removing the
need to hand-tune at all. Both of the paper's mechanisms apply here literally:

- Features compete for space. `rng.choice(shapes)` gives the primary document
  exactly one content shape, so no repository can hold a merge claim and an
  LFS blob at once.
- Features actively suppress. The unclosed fence and the unparseable config
  each silence everything downstream, which is why the `0.85 / 0.15` weighting
  had to be hand-tuned in the first place. That weighting and its "measured at
  2 of 12 repositories" comment are the manual tuning swarm testing replaces.

Documents compose many features rather than choosing one.

**A reach ledger that fails.** Aggregate across the corpus which rules reported
a nonzero denominator, print `rules reached: N of 13`, and fail below a
declared floor. The argument is the one `contract.py` already makes about
denominators: the default `examined` raises rather than answering zero, so an
omission arrives as a crash in the commit that caused it instead of as a
reassuring zero forever. A rule that quietly stops being exercised should turn
this job red, not print `ok`.

The floor is a number in the harness with a reason written beside it, raised
deliberately, in the same spirit as the spawn budget.

**Where it lives.** `tests/harnesses/fuzz_shapes.py`, imported by `fuzz.py`.
Not `corpus.py`: that name is taken by the harness that sweeps a directory of
real cloned repositories, and the two would be confused permanently. The module
is importable rather than inlined so `smoke.py`, `scenarios.py`, `perf.py` and
`stress.py` can adopt it later without this stage touching them.

**Checks must fail closed.** `_rule_counts` returning an empty mapping is
currently indistinguishable from clean counts. Every check that can silently
find nothing to check gets an explicit harness fault instead, reported the way
`mutate.py` reports a non-matching anchor: as the harness declaring itself
broken, never as a result. This applies to the denominator parse, to the reach
ledger, and to any oracle whose twin failed to build.

## Stage 2 - executable recipes, `--replay` and ddmin

`Recipe` today holds prose. `--save` writes it, CI uploads it as the
`fuzz-failures` artifact, and nothing can consume it: there is no `--replay`,
so the only reproduction path is `--seed N`, which rebuilds all 35
repositories.

Make `Recipe` hold the drawn feature set instead. Three things follow:

- `--replay FILE` rebuilds exactly one repository from a saved recipe.
- ddmin over the feature set. The classic minimizing delta debugging algorithm
  bisects a set of atomic units while preserving an interesting property, and
  the feature set *is* that set of units, so the implementation is a bisect
  loop over rebuild-and-recheck. It reports the minimal feature set that still
  violates the property.
- The CI artifact becomes a reproducer rather than a note.

Stage 2 depends on Stage 1: prose steps cannot be bisected.

## Stage 3 - metamorphic oracles

Each is a twin run compared against the original. The technique is the one
behind equivalence modulo inputs (Le, Afshari and Su, PLDI 2014): mutate what
provably cannot affect the answer and require the answer not to change. Extant
has an unusually clean analogue, because `strip_code` blanks code fences with
spaces so that every character offset survives - a contract `AGENTS.md` records
as having broken on CRLF and cost 1627 characters on one document.

| Property | Relation that must hold |
|:---|:---|
| `FENCE` | arbitrary junk inserted inside a code fence changes no finding |
| `SHIFT` | one line inserted at the top moves every line number by one and changes nothing else |
| `CRLF` | rewriting LF to CRLF changes no finding and no line number |
| `RELOCATE` | the same document at another tracked path reports the same findings, relocated |
| `BASELINE` | `--write-baseline` then `--baseline` reports zero, and the suppressed count equals the original finding count |
| `MONOTONE` | an added document never removes a finding; an `exclude_paths` entry never adds one |
| `PROCESS` | two documents in one process agree with the same two in separate processes |
| `EXIT` | exit 1 if and only if at least one finding printed; exit 0 if and only if none |
| `GITHUB` | the github format agrees with the text count, as sarif already does |
| `ERRORED` | a run naming a raised rule never exits 0 |
| `DENOM-AGREE` | the denominator sarif carries equals the one the text run printed |
| `MODE-AGREE` | `--verify` and `--sweep` over one repository report the same finding SET |

Five of these deserve their reason stated.

`BASELINE` covers a suppression mechanism that has no fuzz coverage at all.
`AGENTS.md` is explicit that a suppression firing wrongly deletes a real
finding silently, where a false positive at least appears in the output for
somebody to argue with. That makes it the highest-value untested surface here.

`PROCESS` is the `scope.py` class. That module exists because 26 module-level
caches had lifetimes nobody could state, and the memo rule distinguishes a memo
whose key is complete from one that reads git or the disk and must be dropped
in `registry.forget_memos()`. Nothing currently fuzzes whether that dropping
happens, because the harness runs one mode per process.

`EXIT` tightens a check that is currently vacuous: any of 0, 1 or 2 passes for
any mode, so the harness would not notice a run that printed findings and
exited 0.

`ERRORED` covers a contract stated in three places and fuzzed in none.
`registry.py` catches a rule that raises and appends to `RULE_ERRORS`;
`session.report_rule_errors` prints `ERRORED: <kind> raised ...`; `gate.py`
then forces a non-zero exit with the comment that a partial answer reporting
success "is the failure this whole project exists to prevent". The property
reads that line out of the output and asserts the exit code, and Stage 6 owes
it a feature that makes a rule raise on purpose, since nothing the generator
builds today does.

`MODE-AGREE` exists because the two modes already disagree. Fixing the
repository-scoped duplication left `--sweep` attributing those findings to the
file that declares them - `.gitattributes`, `.extant.toml` - while `--verify`
still attributes them to the primary document. That asymmetry is pre-existing
and harmless today, and reconciling it by hand would only reopen later. A
property that requires the two modes to agree on the finding SET, whatever
attribution each uses, is what keeps them honest permanently.

`DENOM-AGREE` is nearly free and was missed on the first pass. `format_sarif`
emits its denominator as `examined: <kind> <n>, ...` - the same string the text
run prints - so the existing `_rule_counts` parser reads both without change.
`FORMATS` compares only result counts today, which means the two halves of the
conflation this project exists to refuse are checked on one side and not the
other.

## Stage 4 - differential against the last release

Add the previous tag as a git worktree, run the same corpus through both
versions, and diff the findings per repository. No oracle is required: any
difference is either an intended change or a regression, and a human reads
which. Offline by construction, so it does not contradict the `p_offline`
smoke probe or the no-network guarantee.

## Stage 5 - `--self-check`

Inject a known violation of each property and confirm the property goes red.
Four of the six have never been watched failing. This is the same argument
`mutate.py` makes about the suite, applied to the harness that audits it, and
the same reason `mutate.py` reports a non-matching anchor as a HARNESS FAULT
rather than a silent skip.

## Stage 6 - widen the axes

- **Encodings and endings**: CRLF, a BOM, UTF-16, a lone carriage return.
  `line_breaks` and `line_number_at` count a break in every spelling precisely
  because a bare `\r` made every claim report line 1.
- **A rule that raises**, so `ERRORED` has something to observe. A config
  naming a consistency pattern that cannot compile, or a document shaped to
  make one rule throw, is enough; without it that property is asserted against
  a case the corpus never produces.
- **The format axis on the gating modes**, not only on `--sweep`, so `FORMATS`
  and `DENOM-AGREE` see `--validate` and `--verify` output.
- **Concurrency**: two processes against one repository at once. The tool ships
  as git hooks, and `post-commit` and `post-merge` can overlap on a merge, so
  contention on `index.lock` is a shape real installs can reach and this
  harness has never built.
- **Git shapes**: merge commits, annotated as well as lightweight tags,
  `.gitattributes` so `raw-lfs-blob` has something to read, packed refs,
  rewritten history feeding `--sha-map`, bare repositories.
- **Modes**: the eight that are never run, with `--archive` handled carefully
  because `entries.py` holds the only irreversible file write in the product.
- **Generated sites**: a Hugo, mkdocs, Docusaurus or Mintlify marker, so the
  link rules take the route-not-path branch at least sometimes.
- **Windows in CI**: a second matrix leg. The harness already reports which
  shapes a platform will not build, so a Windows leg reports honestly rather
  than pretending to cover symlinks.

## Budget

Hold the wall clock roughly where it is by trading repository count for oracle
depth. The justification is that at `--repos 35` the plan is exhausted
deterministically, so the job is already a fixed scenario suite rather than a
sample; depth per repository buys more than breadth does when the breadth is
not random anyway. Discovery stays a hand-run with a fresh seed, where the
repository count can be whatever the machine will sit through.

The measured baseline is 102 seconds for the CI invocation - seed 20260824,
35 repositories - on a Windows developer machine that skipped 36 shapes it
could not build. That is about 2.9 seconds per repository across three to four
interpreter spawns each, so the cost is dominated by process startup rather
than by anything extant computes. Linux CI builds the symlink, submodule and
shallow-clone shapes this run skipped, and spawns more cheaply, so the two
roughly cancel; the Linux figure needs measuring once rather than assuming.

Held against that, the arithmetic for Stage 3 is direct. Nine oracles at one
twin run each take a repository from three or four spawns to roughly a dozen,
so holding 102 seconds means landing somewhere near 10 to 12 repositories with
every oracle on. Two consequences follow and both are acceptable:

- The (git state, mode) product stops being exhausted, so the harness reverts
  to sampling it and its existing warning about that fires. The reach ledger
  from Stage 1 becomes the coverage number that matters instead, because it
  measures what was actually exercised rather than what was scheduled.
- Reducing spawns is worth more than reducing repositories. A mode that could
  answer about several documents in one process, or a harness that reuses one
  interpreter, buys back repositories directly. Worth measuring before
  accepting the cut.

## Risks

- **The catalogue is a second place that knows about rules.** `AGENTS.md` is
  emphatic that adding a rule module is the whole of adding a rule. The
  catalogue lives in `tests/harnesses/`, never in the payload, and the reach
  ledger failing below its floor is what stops the two drifting apart: a rule
  added without catalogue entries turns the job red.
- **Swarm draws can produce degenerate repositories.** A subset that omits
  every content feature builds a repository with nothing to find. The reach
  ledger is aggregate across the corpus, so this is fine in the large, but the
  floor has to be set against measured runs rather than guessed.
- **ddmin multiplies rebuilds.** It runs only on a violation, so it costs
  nothing on a green run, but a pathological case could bisect for a long time.
  It needs a step ceiling.
- **ddmin assumes the property is deterministic, and one of them is not.**
  `UNSTABLE` exists precisely because a run disagreed with itself, so bisecting
  on it can follow noise and report a minimal set that does not really
  reproduce. Shrinking is restricted to the deterministic properties, and a
  `UNSTABLE` violation is reported unshrunk rather than shrunk unsoundly.
- **Swarm invalidates the pinned CI seed.** Changing what the generator draws
  changes how it consumes the RNG, so seed 20260824 stops producing today's
  corpus, and the coincidence that `--repos 35` exactly exhausts five states
  times seven modes dissolves. Re-pinning the seed and re-measuring the
  baseline is a deliberate step of this stage, not a surprise discovered in CI.
- **The refusals are budget, not signal.** Six of 35 runs decline to start on
  the current seed. Swarm draws over valid configurations should reduce that,
  but the harness prints refusals as their own count and the number wants
  watching: a corpus that mostly refuses is a corpus that mostly tests
  argument parsing.
- **A hang is expensive at twelve spawns.** `TIMEOUT` is 90 seconds per spawn
  and the harness cannot tell slow from hung. A per-repository wall-clock
  budget, and a printed distribution of run times, are worth more than the
  per-spawn timeout alone once Stage 3 multiplies the spawn count.
- **This document is a checked document once committed.** It is full of dead
  pointers and version strings by necessity. They are fenced, which is what
  keeps the tool quiet about them; anyone unfencing an example should expect a
  finding.

## How each stage is known to have worked

This project's standing rule is that a check must be watched failing before it
is trusted, so each stage states what to break and what should go red. A stage
whose verification was not performed is not done.

- **Stage 1**: DONE, with the numbers under "Stage 1 as built" below rather
  than left as targets. The reach ledger reaches 13 of 13 with the three
  defects it found now fixed, the suite is green at 157 of 157 mutations
  matching, and `--selftest` on a generated repository reports 9 fired where it
  reported `0 fired, 13 had nothing to corrupt` before. The ledger was WATCHED
  FAILING: restoring the dead merge spelling on purpose makes it report
  `AIMED AT AND NOT REACHED: false-merge-claim` and exit 2. What is NOT done is
  the corpus reproducibility described below; the harness can still build a
  degraded corpus, and `CORPUS_FLOOR` only stops that being read as a clean
  one.
- **Stage 2**: DONE, and audited afterwards, which found seven gaps and two
  confident wrong answers. ddmin reduces a `raw-lfs-blob` violation to
  `lfs-blob` and a `manifest-floor-mismatch` one to `manifest-floor`; a saved
  plan replays and reproduces at exit 1, six times out of six; and it was
  watched failing - the same plan with the causal feature removed by hand
  builds and reports nothing at exit 0. A plan naming a feature the catalogue
  no longer has is a broken build at exit 2 rather than an empty repository
  reported clean. See "What the Stage 2 audit found" below.
- **Stage 3**: BUILT, with 8 of the 12 oracles watched failing against a
  deliberately broken payload - line numbers pinned to 1 (`SHIFT`), fences no
  longer blanked (`FENCE`), a bogus SARIF denominator (`DENOM-AGREE`), CRLF
  counted as two breaks (`CRLF`), an annotation dropped from the github format
  (`GITHUB`), a baseline suppressing nothing (`BASELINE`), a gate exiting 0
  regardless (`EXIT`), and a rule memoised with no key (`PROCESS`).
  `RELOCATE`, `MONOTONE`, `MODE-AGREE` and `ERRORED` are NOT yet watched
  failing and are therefore not known to hold anything - the outstanding debt
  of this stage. Seed 20260824 over 35 repositories: 13 of 13 rules, no
  property violations, 704 seconds on Windows.
- **Stage 4**: DONE, with the criterion CHANGED and the change argued below.
  `--differential` lives in `tests/harnesses/fuzz_differential.py` behind a
  flag on `fuzz.py`. The control reports 0 differences over 292 findings and
  156 denominators; a deliberately silenced `dead-md-link` is caught at exit 1;
  the real `v0.25.0` comparison reports 16 differences, all of them fixes that
  shipped after the tag. See "Stage 4 as built" below.
- **Stage 5**: DONE. `--self-check` reports 18 of 18 properties observed going
  red, including `RELOCATE`, `MONOTONE`, `MODE-AGREE` and `ERRORED` - the four
  Stage 3 recorded as never watched. Three need contrived breakages and say so;
  `MONOTONE`'s is tautological and says that too. Two of its own breakages were
  themselves broken, which is the fourth time this campaign has found that
  shape in the harness. Audited afterwards, which found three more and took it
  to 19 of 19 - see "Stage 5 as built" and "What the Stage 4 and 5 audit
  found" below.
- **Stage 6**: BUILT, with the criterion CHANGED and the change argued under
  "Stage 6 as built" below. The stated one cannot be met: it asks each axis to
  raise the reach ledger, which was 5 of 13 when that was written and is 13 of
  13 now, or the refusal count, or the count of shapes the platform declined to
  build - and the latter two are costs rather than achievements. What replaced
  it is the reach ledger's own argument one level up: an axis must be DRAWN AND
  CONFIRMED somewhere, and one applied often and never confirmed fails the run.
  Six of six axes are confirmed at the pinned seed, `--self-check` reports 21
  of 21 properties watched going red including the new `AXIS` and `CONCURRENT`,
  and the run is green at 0 violations, in 725 seconds against Stage 3's 704.
  Six defects were found on the way, four of them the shape this project keeps
  refusing - a check that could not reach its subject returning the value that
  means all clear - and three of those four were in machinery written during
  this stage and caught by the ledger written beside it. AUDITED afterwards,
  which found seven more gaps and one product defect - a CR-only document
  losing two rules entirely, reported as a denominator of zero. Four of the
  seven were the reassuring-answer shape again, all four inside the Stage 6
  machinery itself; every fix is in the code and in
  `tests/test_fuzz_findings.py`, and the write-up was deliberately kept out of
  this repository. Bare repositories and `--sha-map` are NOT done and are
  listed under "What is not done" above.

## Stage 1 as built

`tests/harnesses/fuzz_shapes.py` holds 13 features; `tests/harnesses/fuzz.py`
draws them swarm-style and prints the ledger. Measured at seed 20260824, 35
repositories:

| | before | after |
|:---|---:|---:|
| rules reaching a non-zero denominator | 5 of 13 | 13 of 13 |
| `--selftest` on a generated repository | 0 fired | 9 fired |
| repositories reaching any rule | 21 of 35 | 25 of 35 |
| runs that declined to start | 6 | 2 |
| property violations | 0 | 14 against the unfixed tool, 0 once fixed |
| wall clock | 102s | 356s |

The harness went red the moment it worked, and the three defects below are why.
All three are now fixed and merged, and the same seed reports 13 of 13 rules
with no violations. The intermediate numbers are kept because they are the
evidence: 5 of 13 rules and a silent `--selftest` was the state this harness
shipped in, and 12 of 13 with 14 violations was the state that proved the tool
had defects rather than the harness having a bug.

Verified two ways rather than one, because the fixing session's own run turned
out to be degraded - see "The corpus is not reproducible" below. Sweeping a
known-good 37-repository corpus with each payload gives 15 DENOMINATOR
violations before and 0 after, which isolates the fix from how the corpus was
built.

### What it found

Three defects, all the same family: a rule reporting more findings than it
examined candidates, which is the conflation this project exists to refuse.
`AGENTS.md` already names this shape - "the recurring defect here is a pattern
with two readers that scan differently" - and lists `false-merge-claim` and
`dead-release-tag` as its two known instances. These are the third, fourth and
fifth.

`dead-md-anchor` reports **more findings than it examined**. `examined()`
counts only link targets beginning with `#`, while `check()` also judges
cross-file anchors, so `[x](docs/note.md#no-such-heading)` reports
`examined=0, found=1` where the same claim written `[x](#no-such-heading)`
reports `examined=1, found=1`. This is the third instance of the "one claim,
one scanner" defect this repository documents, after `false-merge-claim` and
`dead-release-tag`, and it is the severe direction of it.

`manifest-floor-mismatch` reports a **sweep denominator of zero** while the
sweep prints the finding and names the rule in its own "these rules examined
nothing anywhere here" note. `--verify` counts the same document correctly, so
this is the sweep's aggregation rather than the rule.

`raw-lfs-blob` reports **one violation twice**. `--sweep` emits a
whole-repository rule's finding once per document it scans, so the same raw
blob is printed bare and again prefixed `.gitattributes:`, against a
denominator that counts the governed file once. `inconsistent-artifact` reads
no document either and is likely to share it.

All three are fixed. The second one is worth recording precisely, because the
diagnosis in this document was wrong before the fix: the sweep's aggregation
was not at fault. `_validate_one` passed the document path into `validate()`,
which scopes it to that call and restores the ambient document on the way out,
so `count_examined()` afterwards ran against a document with no path - and
every rule keying on WHICH file it reads counted nothing. `gate.py` had
already been fixed the same way for `--verify`. The third was fixed by
attributing a repository-scoped finding to one file rather than
de-duplicating output, because de-duplicating would leave the rule RUNNING
twice and free to disagree with itself.

That second defect had bounded the ledger, since the ledger probes with
`--sweep`. With it fixed the exemption is gone, `KNOWN_UNREACHABLE` is empty,
and `REACH_FLOOR` is 13 - at the measurement rather than below it, which is a
deliberate loss of margin justified by CI pinning the seed and by the
drawn-but-silent check failing independently.

### The corpus is not reproducible, and that is not fixed

Two identical invocations - same seed, same package, same machine - reached
the rules in 6 of 35 repositories on one run and 0 of 35 on the next, where a
healthy run reaches 25. The harness docstring's REPRODUCIBILITY section claims
a seed rebuilds the identical corpus, and on this platform it does not.

The zero run was caught: the existing "extant examined nothing anywhere" check
exits 2. The 6-repository run was NOT - it exited 0 reporting 13 of 13 rules
and no violations, and read exactly like the healthy run. A corpus 83 per cent
dead reporting as clean is the failure this project exists to remove, sitting
in the harness built to find it.

`CORPUS_FLOOR` now fails a run reaching the rules in under 35 per cent of the
repositories it built, against a healthy 71. It does not fix the collapse; it
stops a degraded corpus being read as a clean one.

The collapse itself is UNDIAGNOSED. Repositories drawing `lfs-blob` end with a
single commit and no tracked markdown, so the whole build dies rather than that
one feature, and the "could not build" column blames `merge-claim` - a
downstream victim needing a branch the collapsed build never created. The
system git config on this machine sets `filter.lfs.required = true`, which
turns any git-lfs failure into a failed `git add` rather than a pass-through,
and that is the leading suspect. Two things it is NOT: it is not the payload,
since the merged tree carrying the fixed payload runs healthy; and it is not
the shape in isolation, which built twelve times out of twelve. It needs the
whole generator to reproduce, and it is intermittent.

### The change that made the harness able to see them

Only one of the three was visible at first, and the reason is worth keeping.
Features are drawn independently of the mode a repository is assigned, so a
repository whose claims expose a denominator bug is as likely as not to draw a
mode that cannot show one - `--format=github` emits annotations and no counts,
and `--selftest` and `--deleted-since` print none either. Seed 20260824 built a
repository reporting two `dead-md-anchor` findings against a denominator of
one and handed it `--sweep --format=github`, so the violation was real,
present, and invisible.

The ledger already spawns a plain `--sweep` on every repository. Checking the
denominator on THAT output as well costs no extra process and gives every
repository denominator coverage whatever mode it drew. Violations went from 2
to 14 and from one defect to three on the same seed.

### What it cost

Wall clock doubled, and that lands on the budget decision rather than beside
it. The plan was to hold 102 seconds by trading repositories for oracles in
Stage 3; the generator alone has now spent that headroom before a single oracle
exists, because a feature-bearing repository does substantially more git work
than the old one did - branches that are really merged, a commit really off the
trunk, a tag, a second commit carrying the claims.

Three options, and the choice belongs with whoever runs Stage 3 rather than
being settled here: cut the CI repository count now, reduce spawns per
repository, or accept a longer fuzz job. The measurement to take first is the
Linux one - this figure is from Windows, which skipped 33 shapes it could not
build and pays more per process than the CI runner does.

### Corrections made during the build

Recorded because each was a silent failure that looked like success, which is
the failure mode this harness exists to surface.

- The LFS feature needed three attempts. Committing a raw binary under an LFS
  filter produces a correct pointer on any machine with git-lfs installed;
  pinning `filter.lfs.clean` does nothing, because git-lfs registers
  `filter.lfs.process` and git prefers it; setting that to empty breaks
  `git add` outright, and the corpus committed nothing at all while reporting
  `git tracks none in this repository`. It now writes the blob with
  `hash-object --no-filters` straight into the index, after the last generic
  `add`.
- The config assembly appended a bare key after the table blocks, which TOML
  reads as part of the last table - the exact mistake `compose_config` was
  written to prevent, made in the caller.
- The hostile tag list contained `v9.9.9`, the version the release feature
  writes its FALSE claim about, so a draw creating that tag silently inverted
  the claim. Both `v1.0` and `v9.9.9` are now excluded, with a note saying why.
- The anchor feature was written to emit a same-document fragment beside the
  dead cross-file anchor, to keep the denominator honest. It kept it honest by
  MASKING the defect: the fragment lifted `examined` to 1, so `found >
  examined` was never true and the harness could no longer see the bug the
  feature existed to expose. The false spelling is cross-file only now.
- The reach ledger reported a broken feature without failing on it. Restoring
  the dead merge spelling on purpose left 11 of 13 reached, which met the
  floor, so the run printed `AIMED AT AND NOT REACHED: false-merge-claim` and
  exited 0. A feature that was DRAWN and reached nothing now fails whatever the
  floor says, with `KNOWN_UNREACHABLE` carrying the one documented exemption
  and its reason.
- Weighting the config draw cut refusals from 10 of 35 to 2 and took
  repositories reaching a rule from 15 to 25. The uniform draw was spending a
  third of the corpus on argument parsing.

## Stage 4 as built

### The stated criterion could not be met, and was wrong

The plan asked for "zero differences against the previous tag on a clean tree".
That is not achievable and would not have meant anything if it were: the tree
has changed behaviour deliberately since `v0.25.0` - three denominator fixes
and one duplicated finding removed - so a differential against that tag MUST
report differences, and a version of this check reporting none would have been
broken. A criterion that only holds on a release day is not a gate.

Replaced by two, which between them say more:

- **The control.** `--differential HEAD` compares the working package against a
  `git archive` of HEAD. Same payload, two builds, so it isolates exactly the
  thing that could make this check useless - normalisation hiding real
  differences - and zero is the only correct outcome. Measured at seed 20260824
  over 6 repositories: 0 differences over 292 findings and 156 denominators.
- **The break.** `dead-md-link`'s `check` made to return `[]` in the baseline
  copy is reported as `only head reports [dead-md-link]` at exit 1.

### Why the break is the interesting half

NO DENOMINATOR MOVED WITH IT. `examined` was untouched, so the rule went on
reporting the same reach while reporting nothing - and every other property in
this harness passes on that repository. It crashes nothing, exceeds no
denominator, prints the same thing twice, and agrees with its own SARIF. A
silent rule is self-consistent under every metamorphic comparison, which is
precisely the class Stage 3 cannot reach and the reason this stage exists.

### What the real comparison found

Against `v0.25.0`, 16 differences over 6 repositories, each traceable to a fix
that shipped after the tag: the duplicated `raw-lfs-blob` and
`inconsistent-artifact` findings the repository pass now attributes to
`.gitattributes`, the widened `dead-md-anchor` denominator,
`manifest-floor-mismatch` counting a document whose path the sweep used to
lose, and - added when this branch was rebased - `stale-live-claim` and
`dead-release-tag` no longer counting sites their rules refuse to judge. The
differential rediscovered every product fix of both releases from a generated
corpus, knowing nothing about any of them.

THIS NUMBER MOVED ONCE ALREADY, and that is the honest argument against
recording it at all. It was 14 before the denominator work merged, and the two
that arrived with it are the only two of that change's SIX rules this corpus
surfaced at seed 20260824 over 6 repositories. A count like this describes one
seed at one size against one baseline; it is evidence that the check reaches
real changes, and it is not a threshold anything should be compared against.

### Three defects in this stage's own machinery, found by running it

Both are the shape this project keeps finding in itself, so they are recorded
rather than quietly fixed.

The first report TRUNCATED FROM THE LEFT at 70 characters. The line it prints
most often is `examined:`, which is long, and two versions disagreeing about
the eleventh rule on it produced two identical strings offered as evidence of a
difference. It showed the reader nothing while claiming to show a difference.
It prints a window around the divergence now.

The second is that "0 differences" had no denominator. A corpus where both
versions reported nothing at all prints exactly like thirty repositories
agreeing, and the control's whole value depends on telling those apart. The run
states how many findings and denominators were on the table, and says so
outright when both are zero.

The third is the one that mattered. THE CONTROL WENT RED ONCE, reporting
FINDING 1, EXAMINED 1, OUTPUT 1 against an identical payload, during a run
concurrent with a 35-repository campaign - and did not reproduce in five clean
runs afterwards. The cause is not the tool and not the normalisation: it is the
BUILD. `build_from_plan` checks return codes on the core git steps only, so the
hostile refs, the tags and the scaffold can lose a race with an index lock on a
busy machine, and the result is two repositories that are not the same
repository. The differential then attributes the difference to the versions.

A differential whose control is intermittently red is worse than one that is
broken outright, because it teaches whoever runs it to discount a red result -
and a red result is the only signal it has. So the two repositories are now
compared to each other before their outputs are: ref and tag NAMES, tracked
paths with `tools/` removed, and the commit count. A pair that disagrees is
reported as BUILD and counted as NOT COMPARED, which is the same treatment a
shape the platform cannot construct already gets.

This is the harness's own version of the defect the tool exists to catch, and
it is the third time this campaign has found it in the harness rather than in
the product.

### What is not done

Corpus size is the sensitivity of this check and it is not free: every
repository is built twice. At 6 repositories only one drew a live
`dead-md-link` case, so the deliberate break was caught once. A clean run over
6 is a much weaker statement than a clean run over 35, and nothing in the
harness currently says how weak - the reach ledger is not computed for this
mode. That is the honest gap, and it is the same shape as `CORPUS_FLOOR`: what
is missing is a floor on how much of the rule set the comparison actually
exercised.

This mode is NOT wired into CI. It needs a baseline ref, it doubles the build
cost, and its output is meant to be read rather than gated on - a difference is
not a failure. It is a release-time check, run by hand before tagging.

## Stage 5 as built

### What it does

One repository, built with every feature drawn both ways so that every rule has
something to read, and only the payload text changing between the two halves of
each experiment:

  silent  the clean payload must NOT produce the property
  red     the broken payload must

The first half is the one that earns its place. A property already firing on the
clean build is "confirmed" by any breakage at all, including one that did
nothing - which is precisely how a breakage that failed to apply reads as a
success. The Stage 3 audit caught two breakages that were themselves broken,
one leaving a SyntaxError so extant never ran, and a run that never ran produces
no finding of any kind.

Each property is judged by the harness's OWN predicate - `check` for the core
properties, `oracles.run_all(only=)` for the oracles - so a property observable
here is observable to the driver and the shrinker. Running the whole of
`all_faults` per breakage was the first attempt and timed out at ten minutes
before reporting anything.

### The result

18 of 18, including all four Stage 3 listed as unproven. `HANG`, `RELOCATE` and
`MONOTONE` need contrived breakages and are marked as such in the output.

`MONOTONE`'s is worse than contrived, it is TAUTOLOGICAL: it keys on the
oracle's own probe file. A count threshold was tried first and observed
nothing, for a reason worth keeping - the maximal repository already carries
more than two markdown files, so the rule was silent before the oracle added
its document as well as after, and a break that changes nothing changes
nothing. What the tautology proves is bounded: MONOTONE's comparison WORKS and
is not structurally inert, which is the failure this stage exists to rule out.
It does not show the oracle guards a defect anybody would write. Stage 3
predicted this one would need contriving; needing a tautology is the sharper
version of that answer.

### Two of its own breakages were broken

`ERRORED` was reported unobservable and the diagnosis was wrong about which
half had failed. The property asserts that a run naming a rule which RAISED
never exits 0 - so a raising rule alone does not provoke it, because the gate
then correctly exits non-zero, which is the property HOLDING. It takes a
raising rule AND a gate that swallows the consequence. The table carries
multi-edit breakages because of this one.

`UNSTABLE`'s anchor was written with four spaces of indentation where the real
statement has eight. Being a SUBSTRING of the real line, it matched exactly
once, applied cleanly, and edited a SARIF-only path that `--verify` never
reaches. The property was reported unobservable - true of the breakage, false
of the property. `check_anchors` now refuses an anchor that begins mid-line;
counting alone cannot catch this, because the count is 1 either way.

That is the fourth time this campaign has found the project's own defect inside
the machinery built to find it: a check that could not reach its subject
returning the value that means all clear.

### What is not done

`--self-check` is not wired into CI. It costs a full timeout to observe `HANG`
- there is no way to watch a deadline missed without missing it - and it
rewrites the installed payload in place, which is safe in a disposable arena
and is not something to run against a tree anybody is holding. It is a
release-time check, run by hand, exactly like `--differential`.

The properties list is written out rather than discovered, so a property added
to the harness and not to that list is not checked and nothing says so. That is
the obvious next gap and the same shape as every other one here.

## What the Stage 4 and 5 audit found

Six gaps, and two guards that turned out to hold. Everything below was settled
by running something. Three of the six are the same defect this project exists
to refuse - a check that cannot reach its subject returning the value that
means all clear - which makes them the fifth, sixth and seventh instances found
inside the machinery built to find it. Two are verbatim repeats of failures
already written down in the Stage 3 audit above.

### The baseline was a mixture of two versions

`materialise` extracted over whatever the directory already held. Extraction is
a merge: `tar` writes the files the archive carries and leaves every other file
alone. Running `--differential v0.25.0` and then `--differential v0.24.0` in one
arena therefore left SIX files the newer tag ships and the older one does not,
`extant/gate.py` among them - so the second run compared HEAD against a payload
that was neither version and labelled the result with the tag.

Measured, then fixed, then measured again: 6 surviving files before, 0 after.
The removal is checked rather than passed `ignore_errors`, because a directory
that survives its own deletion is the case this must not continue past.

### Two timed-out runs compared equal

`observe` gave a timed-out run the same placeholder text, the same empty
findings and the same empty denominators on both sides, so `compare` returned
`[]` and the repository was counted as compared and agreeing. This is the
`_text(None)` defect from the Stage 3 audit - "a hang read as clean", where
four oracles passed while nothing ran - reproduced in the stage written after
it, by the person who had just read it.

A pair where either side did not finish is NOT COMPARED now, and the count is
printed beside the build-mismatch count.

### A hollow breakage satisfied a property

`--self-check` did not check that a breakage left the payload parseable.
Measured: replacing `def format_github(` with `def format_github((` makes the
harness report exactly `['CRASH']` - so the CRASH row was satisfiable by a
breakage that never ran the code it names, and every other property would read
as "not observable" for the same reason.

This is the Stage 3 audit's own lesson verbatim: "the first EXIT breakage left
a paren unclosed, so extant raised a SyntaxError, never ran, and the oracle
looked hollow when the BREAKAGE was hollow." `apply` compiles every edited file
now and rolls back with the syntax error named.

### The property list was hand-written and short

`ALL_PROPERTIES` had no mechanical cross-check, and `HARNESS` was excluded with
a note saying it is a property of the harness rather than of extant. True, and
beside the point: it is a fault kind the driver reports and `SHRINKABLE`
bisects on, and it fires on the fail-open case where the denominator loop
iterates nothing and reports success.

It is checked now, and the list is cross-checked against `SHRINKABLE` and
`ORACLES` DIRECTLY rather than by scraping source. That distinction is not
theoretical: the throwaway regex written to perform this audit reported `CRASH`
as never emitted, a false positive, because `CRASH` is returned rather than
appended. The audit tool had the same defect class as everything it was
auditing.

### The HARNESS breakage then found something about `gate.py`

Dropping the denominator line did not provoke the property, because the
denominator is PRINTED FROM TWO PLACES: `report_denominators` writes it for the
primary document and a separate `diag` writes it per extra document. Removing
one left `checked README.md: ...` behind, `_rule_counts` still parsed eleven
entries, and the property could not fire.

The breakage drops both now. The observation about `gate.py` outlives it: one
claim - what this run examined - emitted by two statements that can be changed
apart. Not a defect today, since both spell it identically, and worth knowing:
if either changed format the harness would silently parse fewer denominators
and DENOMINATOR would cover less without saying so.

### Two guards held, and are now watched rather than assumed

The `BUILD` fingerprint added at the end of Stage 4 had never been observed
firing. Both halves are now measured: a deleted tag changes the fingerprint,
and an untracked payload file does NOT - which is the half that matters, since
a fingerprint including the payload would fire on every differential run.

And the self-check's single repository reaches 13 of 13 rules, so no property
rests on a corpus that fails to exercise it. That concern was unfounded.

### Smaller

`FINDING` output is capped per direction with the remainder counted, because a
silenced rule printed one line per lost finding and buried every other
difference. And `restore` verifies the bytes went back, since a restore that
silently did not take would leave every later property judged against a payload
still carrying the previous breakage.

### What this audit did not close

The reach floor for `--differential` is still missing: corpus size is the
sensitivity of that check and nothing reports how weak a small run is. It
remains the honest gap named under "Stage 4 as built".

## Stage 6 as built

### The stated criterion could not be met, and the replacement is the ledger

"Each new axis raises the reach ledger, the refusal count, or the count of
shapes the platform declined to build." The ledger stood at 5 of 13 when that
was written and stands at 13 of 13 now, so nothing can raise it. The other two
are costs: this document says itself that a corpus which mostly refuses is a
corpus mostly testing argument parsing, and a platform declining more shapes is
worse coverage rather than better.

So the criterion is the one the reach ledger already makes one level down. An
axis is DRAWN, APPLIED and then CONFIRMED - the run has to behave as though the
axis were present - and an axis applied often and never once confirmed fails
the run, exactly as a feature that fires no rule does.

Confirmation is THREE-STATE, and that is the part worth keeping. `True` the run
showed it; `False` the run contradicts it; `None` this repository offered no
way to tell. Two states force the third case to be called something and either
choice is wrong somewhere - counted as confirmed it hides an axis that has
stopped working, counted as failed it reddens the run over a draw that simply
had nothing to show.

### What it added

`tests/harnesses/fuzz_axes.py` holds six axes: the document's encoding (CRLF, a
BOM, a bare CR, UTF-16), a config pattern that makes a rule RAISE, a generator
marker declaring the tree a site, an annotated tag, packed refs, and a
`filter-repo` commit-map. `fuzz.py` draws them beside the features, applies
them at four declared build phases, and prints an axis ledger.

A `CONCURRENT` property joined the core set, taking the properties from 20 to
21. Seven modes joined `MODES`. Three put the format axis on the GATING modes,
which it had never been on - `--validate --format=sarif` had never been
executed by this harness at all. Four are the modes that were never run:
`--collect`, `--search`, `--check-text` and `--archive`. And the fuzz CI job
grew a Windows leg, so the shapes that only matter there are fuzzed somewhere,
and the ones Windows will not build are counted as untested by the platform
that cannot build them rather than assumed by the one that can.

### How it was verified

Every number here is from a run, on Windows, against a `git archive` extract
rather than the working tree.

| | |
|:---|:---|
| `--self-check` | 21 of 21 properties watched going red, `AXIS` and `CONCURRENT` among them |
| reach ledger | 13 of 13 rules examined something |
| axis ledger | 6 of 6 axes applied and confirmed |
| `mutate.py --check-only` | 157 of 157 anchors match exactly once |
| `smoke.py` | 31 probes, 47 observations, 0 new flags and 0 missing |
| `scenarios.py` | 25 scenarios, 213 of 213 assertions |
| `--verify` and `--selftest` on this repo | clean, 7 fired and 0 silent |
| `fuzz.py --seed 20260824 --repos 35` | 0 property violations, exit 0 |

THE PINNED CI SEED IS UNCHANGED, and that was not a given. Drawing axes
consumes the generator differently, so seed 20260824 builds a different corpus
than it did before this stage - the risk this document names under Risks. It
had to be re-run rather than assumed, and it was, three times: the first two
runs found the `MODE-AGREE`, `BASELINE`, `EXIT` and `--archive` defects above.
The third is the one in the table.

At 35 repositories it now covers 35 of 70 (git state, mode) pairs rather than
exhausting them, which is the trade this document predicted under Budget: the
product stops being walked to completion and the harness reverts to sampling
it, with its existing warning firing and the new mode ledger reporting which
modes actually ran. 25 of 35 repositories reached the rules and 3 runs
declined.

WHERE THE TIME ACTUALLY GOES, measured rather than reasoned, because Budget
asks for it and leaves it open: "Reducing spawns is worth more than reducing
repositories ... Worth measuring before accepting the cut."

One repository costs 50 extant spawns and about 31 seconds:

| | spawns | seconds |
|:---|---:|---:|
| core properties, plus the sweep probe | 8 | 5.6 |
| the ten metamorphic oracles | 42 | ~25 |

So the ORACLE LAYER is 84 per cent of the spawns and roughly 80 per cent of the
time, and that is inherent rather than wasteful: an oracle compares extant
against itself under a change that must not matter, so each needs a before run,
an after run, and the runs to restore and cross-check - four apiece, ten of
them, every repository. At 35 repositories that is about 1,750 process starts,
and a Python start plus importing extant is roughly 0.4 seconds on Windows,
which is the whole of the 725.

The lever Budget was looking for is therefore the oracle layer, not the
repository count, and not this stage: `CONCURRENT` is 2 spawns of the 50.
Anything that let one process answer several oracles - a mode that took a list
of documents, or a harness that reused one interpreter - buys back far more
than dropping repositories would, and dropping repositories would cost the
(git state, mode) coverage that is already only half walked.

THE WALL CLOCK HELD, which is what Budget asked for. Stage 3 recorded this
invocation at 704 seconds on Windows; two runs of this stage's code measured
725 and 617. The spread between those two is larger than any difference from
Stage 3, so the honest claim is the weak one: six axes, seven modes and two
extra processes per repository did not multiply the cost, and no repository
count was traded away. A tighter number would need a quiet machine, and this
was not measured on one.

That it did not multiply is explicable rather than lucky: the concurrent pair
runs in PARALLEL, so it costs one process start rather than two, and the added
modes replace drawn ones rather than joining them.

The `AXIS` breakage is worth its own line, because its FIRST version was
aimed at `ref_table`, where `commit = peeled or obj` peels annotated tags and
which reads like the obvious site. It applied cleanly, matched exactly once,
and changed nothing: `ref_table` keys tags by SHORT name while the rule asks
about `refs/tags/v1.0`, which misses that table and falls through to a
`rev-parse`. The property read as unobservable when the BREAKAGE was aimed at
a path the rule does not take - the same mistake Stage 5 made twice and wrote
down both times, made a third time by someone who had just read both.

### Concurrency, and the breakage that had to be specific

`CONCURRENT` starts two runs of one mode AT ONCE and requires each to answer
what the same run answers alone. That is the shape real installs reach rather
than an exotic one: extant ships as git hooks, `post-commit` and `post-merge`
are both installed, and a merge fires both - so two runs contending for
`index.lock` is ordinary operation, and this harness had never built it.

Three decisions in it are worth stating.

It compares against the SOLO run, not the pair against each other. Two
concurrent runs that agree with each other and disagree with the solo answer
are the interesting case, and comparing only the pair would miss it entirely.

It compares stdout AND stderr, where `UNSTABLE` compares stdout alone - which
this document already records as failing open, because every diagnostic, every
denominator on a sarif run and every rule error is written to stderr.

And the breakage is contrived DELIBERATELY rather than conveniently. The easy
one - put a PID in the output - fires the property while proving nothing about
concurrency, because a sequential pair would differ too and `UNSTABLE` already
owns that. The one written instead creates a fixed-name file, holds it, and
removes it inside a single invocation, so a run with the repository to itself
never meets it and only an overlapping run does. Watched failing: silent on the
clean payload, and `CONCURRENT` was the ONLY fault on the broken one, which is
the sharpest form of the two-halves test this campaign uses.

The sleep in that breakage is load-bearing and says so beside itself. Without
it the first run releases the name before the second looks, the breakage does
nothing, and the property reads as unobservable when the BREAKAGE was what
failed - the mistake this stage's own audit records three other instances of.

`CONCURRENT` is NOT shrinkable, alongside `UNSTABLE` and `HANG`, for the reason
this document gives under Risks: ddmin assumes a deterministic property, and
bisecting on a race follows noise and reports a minimal set that reproduces
nothing.

### The design document proposed a mechanism that does not work

For the raising rule it suggested "a config naming a consistency pattern that
cannot compile". Measured: `_compile_consistency` catches that at load and the
run exits 2 with "cannot read configuration", which is a REFUSAL - no rule runs
at all, so it produces the opposite of what the axis needs.

What does work is a pattern that COMPILES and then misbehaves inside the rule.
`release_tag` and `branch_token` are both user-settable and both read with
`.group(1)`, so a pattern with no capture group raises `IndexError: no such
group` from inside the rule, `ERRORED:` is printed and the gate exits 1. It is
also a mistake a real project makes, which a payload edit is not.

### What it found

**`--collect` crashed in every repository, which is why it was never fuzzed.**
An unhandled `RuntimeError` with a carefully written paragraph inside the
traceback. `run_suite`'s own docstring says the point of raising was to replace
"an uncaught FileNotFoundError crashing /extant step 1" with something
actionable; the message became actionable and the crash did not go away,
because nothing caught it. Every generated repository lacks a `.venv`, so this
was not an edge case there - it was the mode's ONLY behaviour. Fixed at the CLI
boundary, reported at exit 2 like every other "this run cannot proceed", with
both halves pinned in `tests/test_fuzz_findings.py`.

**The EXIT property was not exempted for refusals, while the SARIF one was.**
Two properties on either side of one predicate, which is the "one claim, two
scanners" shape this project keeps finding. Latent until the encoding axis
reached it: every refusal the generator could previously build came from an
unreadable config and exited 2, which that test does not look at. A UTF-16
primary document is a refusal that exits 1 - extant declines it by name, "not
valid UTF-8 (invalid start byte at byte 0)", on stderr with nothing on stdout -
so the harness would have reported "exited 1 with no finding printed" and
failed the run over the tool being right.

**The EXIT property could only see findings in one format.** Putting the format
axis on the gating modes produced `EXIT: --verify --format=github: exited 1
with no finding printed` on the first run, against output that had printed its
findings perfectly well as annotations. One finding has three renderings and
the detector knew the text spelling; it now reads whichever format is on, and
parses SARIF from stdout ALONE, because the merged stream the other checks read
never parses as JSON.

**`MODE-AGREE` guarded one side of a two-sided comparison.** It asked whether
`--verify` had actually read the document - a guard added after verify was
caught comparing against a document it never read, and which the Stage 3 audit
recorded `MODE-AGREE` as needing "for the same reason" as `PROCESS`. It got one
half. `--sweep` can decline too: `exclude_paths` covering the very document
`primary_doc` names makes the sweep refuse with a CONFLICT, while verify
proceeds - correctly, because you asked it to gate on that file. The sweep then
reports nothing and every finding verify printed reads as one the sweep LOST.

Reached at seed 20260824, which is the PINNED CI SEED: the shape has been
reachable since `exclude_paths` joined the config shapes, and adding the axes
changed the draw enough to reach it. The guard is now symmetric - a sweep that
ran prints a denominator and one that declined prints a diagnostic - and
`MODE-AGREE` was re-checked as still firing on its own breakage afterwards,
because a guard that silences the property it protects is worse than the gap.

**`--archive` crashed on a document that is not UTF-8**, which is the finding
this stage most deserved: the ONE MODE THAT REWRITES THE DOCUMENT was the one
not checking it. `--validate`, `--verify`, `--selftest` and `--check-text` all
guard that read and refuse with "not valid UTF-8"; `entries.archive` let the
exception out, so a UTF-16 status document met the only irreversible file
write in the product with an unhandled traceback.

Nothing had been written when it raised - the read is the first thing
`archive` does - so the file was intact either way. What is wrong is that a
crash is not an answer, and this mode's crash is indistinguishable from one
that failed halfway through a rewrite. It needed BOTH halves of Stage 6 to
reach: `--archive` was one of the four never-run modes, and no generated
repository had ever carried a document that was not UTF-8. Found at the pinned
CI seed, fixed to refuse at exit 1 like its siblings, and pinned in
`tests/test_fuzz_findings.py` with an assertion that the document is unchanged.

**`core.autocrlf` was an input nobody had declared**, which is the arena-path
lesson again in a place nobody looked. It is `true` at SYSTEM level on a
default Windows git install and on GitHub's Windows runners, and every
generated repository inherited it. Under it a CRLF document becomes LF in the
committed blob and CRLF again on checkout - measured directly, working tree and
HEAD blob differing by exactly that - so `--sweep`, which reads HEAD's tree,
and the gating modes, which read the working tree, would answer about
DIFFERENT BYTES, and the encoding axis would be judged against a document git
had quietly normalised back.

The platform-dependence is the worse half, and it is what makes this a
reproducibility defect rather than a tuning one: Linux leaves the setting off,
so one seed would build two different corpora on the two CI legs and neither
leg would say so. Pinned to `false` on every repository this harness creates,
including clones, which inherit nothing. Measured after: all four encodings now
reach the commit byte-for-byte.

**Two checks assumed zero findings means exit zero.** It does not when a rule
RAISED: `gate.py` forces a non-zero exit there deliberately, with the comment
that a partial answer reporting success "is the failure this whole project
exists to prevent". `BASELINE` reported a baseline that had suppressed
everything correctly as a baseline failure, and `EXIT` reported "exited 1 with
no finding printed" - both accusing the tool of the opposite of what it did.

Neither assumption had ever been TESTABLE. Nothing this generator built had
ever made a rule raise, which is the hole the `raising-rule` axis exists to
fill, so the first corpora drawing both found them one after the other. The
exemptions cost no coverage: `ERRORED` owns exactly this question and asserts
the other direction, that such a run must never exit 0. Only that half of
`EXIT` stands aside - findings printed against exit 0 is still wrong however
many rules raised.

That two independent checks carried the same false assumption is the point
worth keeping. It was not a mistake either author made; it was a fact about
extant that no corpus could contradict, so both encoded it and neither could be
wrong until an axis made the case reachable.

**Two of the axes were themselves broken, and the axis ledger is what said so.**
The raising axis chose a site whose FEATURE was not drawn, to keep it off any
rule the reach ledger was watching - which is exactly the condition
guaranteeing the document held no claim of that shape, so `.group(1)` was never
reached and no rule ever raised. It reported `raising-rule: applied, and the
run contradicts it`. Each site now carries and writes the claim its own pattern
needs. The second was the floor: `runnable-suite` was applied 8 times and
confirmed 0, and the fault was the DENOMINATOR - applications are not
opportunities, because that axis showed only in a `--collect` run. It was
removed in favour of a fixed `suite_command` in the generated config, so
`--collect` reaches the 350 lines of `collect.py` every time rather than one
run in two.

That is the fifth and sixth time this campaign has found a check that could not
reach its subject returning the value that means all clear - both inside the
machinery built to find it, and both caught by a ledger written in the same
stage.

**The `empty` state carries none of the build.** `build_from_plan` answers that
state by creating a SEPARATE repository - `git init`, the payload, a freshly
composed document - and returning that one. It has no `.extant.toml`, none of
the written files and none of the commits, so an encoding written to the
original is not the document extant reads and a config key was never written
anywhere. Every axis applied there reported itself applied and did nothing.
Applicability is DECLARED per axis now and the driver declines before running
it, so the decline lands in the "could not build" column where an untested
shape belongs.

**A hang that was reachable all along.** `path_pointer = "(a+)+$"` against a
5000-character run of `a`s is catastrophic backtracking, and both halves have
been in this generator since Stage 1 - the config shape and the noise shape.
They had simply never been drawn together with a mode slow enough to exceed the
90-second budget. It is not a Stage 6 regression and it is not fixed here:
`consistency.py` records the trade for user-supplied patterns - that process
isolation is the only mechanism that works and costs a spawn per pattern - and
`path_pointer` has the same argument.

It is also already KNOWN AND ACCEPTED, which settles the question rather than
leaving it to judgement: `smoke.py` carries `HANG  pathological user regex` in
its EXPECTED flag ledger, so that harness asserts the behaviour rather than
tolerating it. Worth knowing here only because a pinned CI seed has to be
chosen against it - one that draws the bait together with a slow mode fails on
the clock, and the failure names the budget rather than the cause.

### What is not done

- **Bare repositories**, and the `--sha-map` mode. The commit-map axis builds
  the file `--sha-map` reads, and confirms `dead-sha` names the replacement it
  records, but the flag itself is never passed - it REWRITES documents, so it
  needs the care `--archive` got rather than a line in `MODES`.
- **Nine flags** are still never passed: `--full`, `--suggest-fixes`, `--out`,
  `--suite-json`, `--sha-map`, and the three baseline flags, which the
  `BASELINE` oracle exercises but the mode list does not. `--as-path` is passed
  now, with `--check-text`.
- **The Windows CI leg is written and has never run as a job.** Every number
  in this section came from a Windows developer machine, so the HARNESS is well
  exercised there; what is unverified is the workflow - the matrix, the shared
  `bash` shell, and whether `C:/fzarena` stays under MAX_PATH on a GitHub
  runner. The first push is where that gets answered. The Linux figure this
  stage's cost should be judged against was never measured either, which was
  already named as debt under Budget.

## What the Stage 2 audit found

Seven gaps, every one confirmed by running something rather than by reading.
Five are the same failure - something could not be determined and the code
returned the reassuring answer - which by then was the fifth, sixth and seventh
instance of that shape in this work, three in the product and four in the
harness built to find them. Knowing about the pattern demonstrably does not
prevent writing it.

Two were confident WRONG ANSWERS, which is worse than a crash.

**A plan naming a feature the catalogue no longer has was silently dropped.**
The harness built a repository with nothing in it, found no violation, and
printed "this plan does not reproduce one" at exit 0 - which reads as "the bug
is fixed". It listed the discarded feature while doing so, so the output
asserted the opposite of what happened. Plans outlive the catalogue, so this is
the ordinary way for one to go stale. Now a broken build at exit 2.

**Shrinking matched on the PROPERTY and not the rule**, which was a documented
decision and wrong. `DENOMINATOR` covers every rule that reports more than it
examined, so ddmin accepted the `consistency` feature - which produces an
`inconsistent-artifact` fault of the same shape - as reproducing a
`raw-lfs-blob` fault, and reported it as the minimal cause. The signature is
kind plus the rule named in the detail now.

**Clones inherit none of the origin's git configuration**, which was residual
nondeterminism after the arena-path fix had already been called complete. A
clone is a brand new repository: it got neither `core.longpaths` nor
`filter.lfs.required=false`, so a `shallow` repository holding an LFS pointer
smudged it under the system-wide `required=true`, asked the network for a
fabricated oid, and varied by timing. One replay in four came back clean;
after the fix, six of six reproduce.

That one surfaced only because the shrunk plan was replayed and checked to
actually reproduce, rather than trusting that ddmin had verified it. Verifying
that the shrinker verified something is not the same as verifying it.

The remaining four: the plan did not record which payload it was built against,
so a CI artifact replayed locally silently answered a different question;
`shrink` bisected without first confirming the full plan reproduces, so "no
smaller feature set reproduces it" was indistinguishable from "the violation
needs every feature"; two faults on one repository overwrote a single plan file,
and two measured indices had exactly that; and a malformed plan raised a bare
`KeyError` naming one field.

## What the Stage 3 audit found

Six gaps. The headline one is the same failure this work keeps producing, and
it was written in the same hour as a note saying to watch for it.

**A TIMEOUT MADE AN ORACLE PASS.** `run_mode` returns None when extant exceeds
its budget, and the oracles read that as empty output - which compares equal to
empty output. Measured by handing every oracle a runner that always returns
None: `FENCE`, `CRLF`, `MONOTONE` and `RELOCATE` reported no faults and
recorded no skip. A hang read as clean. `_text` now raises `DidNotRun`, caught
as a skip, and no oracle passes silently.

**`PROCESS` compared two modes when one of them had refused.** The oracle ran
whenever `README.md` existed on disk, but `--verify` gates on `primary_doc`,
and the generator deliberately ships a config naming a file that does not
exist - so verify read nothing while `--validate README.md` read README
perfectly well. It now requires verify to have actually read the document,
the same guard `MODE-AGREE` needed for the same reason.

**Five oracles compared things that are not comparable**, each fixed with a
stated skip: repository-scoped rules report at line 1 and do not move with the
document; `extra_docs` findings appear in a gating run and must not be required
to shift when a different file was edited; SARIF never parses out of merged
stdout and stderr; and `--sweep` reads HEAD's tree while the gating modes read
the working tree, so the two answer about different inputs whenever those
differ.

**Two of the breakages were themselves broken**, which is the part worth
keeping. The first `EXIT` breakage left a paren unclosed, so extant raised a
SyntaxError, never ran, and the oracle looked hollow when the BREAKAGE was
hollow. The first `PROCESS` breakage dropped the document path and broke
`--verify` and `--validate` identically - the two agreed, and a symmetric break
cannot test an oracle that compares two things. Both are now recorded beside
the breakages that replaced them.

**Four oracles remain unproven.** `RELOCATE`, `MONOTONE`, `MODE-AGREE` and
`ERRORED` have not been watched failing. The rule this spec states is that an
oracle which cannot be made to go red is removed or rewritten, so this is debt
rather than polish. `MODE-AGREE` and `ERRORED` have obvious realistic breaks -
make the sweep skip a rule, make a rule raise while the gate still exits 0.
That `RELOCATE` and `MONOTONE` need contrived ones is itself information about
what they are worth.

## Sequencing

Stage 1 first, because Stage 2 cannot bisect prose and Stage 3's oracles are
worth much more against a corpus that reaches all 13 rules. Stages 3, 4, 5 and
6 are independent of each other and can land in any order.
