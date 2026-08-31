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
- **Stage 3**: each oracle is watched failing against a deliberately broken
  copy of the payload - one that miscounts CRLF line numbers for `CRLF` and
  `SHIFT`, one that drops the sarif denominator for `DENOM-AGREE`, one that
  swallows a rule error for `ERRORED`. An oracle that cannot be made to go red
  is removed or rewritten, exactly as two smoke probes were when they turned
  out to be unreachable by construction.
- **Stage 4**: the differential reports zero differences against the previous
  tag on a clean tree, and reports a difference when a rule's behaviour is
  changed on purpose.
- **Stage 5**: `--self-check` reports every property as observable. It is the
  stage that makes the other verifications repeatable rather than one-time.
- **Stage 6**: each new axis raises the reach ledger, the refusal count, or the
  count of shapes the platform declined to build - and if it raises none of the
  three, it added nothing and comes out.

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

## Sequencing

Stage 1 first, because Stage 2 cannot bisect prose and Stage 3's oracles are
worth much more against a corpus that reaches all 13 rules. Stages 3, 4, 5 and
6 are independent of each other and can land in any order.
