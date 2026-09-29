# Performance: scopes, caches and batches

Part of the design rationale; [its core](../design.md) maps every part and
section. What a run holds and for how long, what it asks git once rather than
per document, and the faster designs that were measured and refused because
the time was not where the proposal said it was. The sections are in the order
they were written.

## Cache scope: one call, and the one place it widens

Every answer git or the filesystem gives is held for the duration of ONE
`validate()` call and no longer. Directory listings, ancestry indexes, resolved
refs, LFS state, another document's headings, the origin URL. A caller that
creates a file or adds a remote between two checks must see the new answer, and
a cache with no owner would quietly hand back the old one.

That default is not free. `--sweep` calls `validate()` once per document, so
every one of those answers was being rebuilt per file: measured over 400
documents, one origin lookup per document was 70 percent of the entire run, and
directory listings turned 20 distinct questions into 128,000 Path objects.

So `--sweep` declares the repository static for its duration and takes
ownership of those caches. It can, because it reads every document from one
checkout and writes nothing. The declaration is released in a `finally`, so a
library caller that sweeps and then validates something else gets the per-call
behaviour back even if a rule raised part-way through.

The narrowness is the safety argument. `--verify` was measured for the same
treatment and refused it: 5 ms saved out of 337, on the path that gates
commits, in exchange for relaxing a correctness promise. Not worth it.

Three later additions follow the same rule rather than widening it: the tracked
file list, the site directory list, and reference resolution. Each answers a
question about the CHECKOUT rather than about any document - which files git
tracks, which directories a site is built from, whether a path resolves and in
what spelling - so a survey asks it once instead of once per file. All three
are read only while the static declaration is held, which is what makes them
answers with an owner rather than a memo that outlives its truth.

One of them was proposed with the git call wrapped, returning an empty list
when `ls-tree` fails. That was refused. A repository where git fails would then
report zero tracked documents and sweep clean, which is the silence this whole
section is about, produced by the defensiveness meant to prevent a crash.

The direction of the mistake is worth recording, because it was made. The
origin lookup was first memoised for the whole process on the reasoning that a
remote cannot change while one runs - true of the CLI, false of a library
caller and of the tests. A repository whose origin was added between two
validations kept answering "no origin", so `dead-pinned-ref` examined nothing
and reported clean. A cache that outlives its scope does not produce a wrong
answer anybody sees; it produces silence, which is this project's own failure
mode aimed at itself.

## The survey runs in one process or eight, and says which

Above 100 documents `--sweep` spreads the per-document work across up to eight
worker processes. Each worker takes a batch and holds a run scope of its own,
so the static-checkout caches above are built once per process rather than once
per document. Measured on a 200-document corpus across twelve cores, best of
three: 7327 ms in one process, 2919 ms across eight.

**The floor is a measurement, not a guess.** The curve leaves zero long before
it is worth anything: 40 documents buys 4 percent, 60 buys 15, and only at 100
does it reach 1.75x. A process pool brings failure modes a loop does not have -
sandboxes that forbid spawning, state that will not pickle, workers the OS
kills - and 4 percent does not pay for any of them.

**One implementation, two dispatchers.** Reading a document, validating it and
counting its denominator live in a single function that both paths call. The
alternative - a parallel loop beside a serial one - was written first and
rejected: two copies of the work drift, and only one of them is ever exercised
on a given machine, so the drift is found by a user rather than by a test.

**Which path ran is printed.** This is not diagnostic noise. The two paths are
required to produce identical output, and a reader who cannot say which one
produced theirs has no way to report a difference between them. The same
reasoning makes the fallback loud: if the pool cannot start, the survey
finishes in one process and names the reason, because a run that quietly
stopped using the machinery it reports using would go on printing the summary
of a healthy one. Silent degradation is the failure this project exists to
refuse, and it is no more acceptable in the harness than in a rule.

**A document that comes back with no result is named, and gates.** The merge
looks each document up by path, and a missing entry is the one shape that lets
a sweep examine nothing and say nothing. It is counted and named beside the
unreadable ones, for the reason a file that could not be READ is counted:
neither is a file with no findings.

It differs from an unreadable file in one way that matters, and the exit code
follows the difference. A file that cannot be decoded is a fact about the
REPOSITORY - reported, survived, exit code untouched. A document dispatched to
the survey that came back with nothing is a fact about this TOOL, so it exits
non-zero. Reporting a defect in the surveyor while returning the code for a
clean run is the same conflation one level up.

## Where a sweep's time goes, measured without the profiler

A review of the internals read a cProfile of a sequential ruff sweep and
proposed four changes to the document scan, projecting "the cheapest 2x
available". Two of its premises did not survive measuring the same sweep
wall-clock, on this machine, with nothing instrumented but the clock: 650
documents, 7.1-7.3 s, on the `blob:none` clone the bench tier keeps.

| where the time goes | s | share |
|:---|---:|---:|
| `dead-md-link` - the link scan and the filesystem walk behind it | 1.94 | 27% |
| git, five spawns, `log --diff-filter=R -n 200` and `ls-tree -r` the large ones | 1.51 | 21% |
| `dead-sha` - blanking 0.54, the two SHA candidate scanners 0.76 | 1.38 | 19% |
| `dead-md-anchor` - slugging three spellings per heading | 1.10 | 15% |
| `_release_claims` | 0.71 | 10% |
| `_pinned_refs` / `_merge_claims` | 0.34 / 0.29 | 9% |

Git is a fifth of the run rather than "~0": the review's sandbox had a fast
filesystem and a full clone. And cProfile overweights code that makes many
small calls, so `_line_and_terminator`'s reported 0.45 s of self time is
about 0.1 s real - which decided the first item.

**5.1, the blanking rewrite, refused on the numbers.** Three exact
rewrites of `_blank_uncached` were built against the current 486-497 ms
for both flavours over ruff. The review's region-based one - fence lines
found by one scan, regions blanked by one substitution each, exact to the
`splitlines` segmentation with the eight breakers only that function
honours excluded from the inline class - is byte-identical on all 1,300
(document, flavour) pairs and 1,662 ms: a per-character substitution over
a fenced region costs more than the per-line loop it replaces. A per-line
rewrite with the terminator peel inlined is 383 ms, 1.30x, and a second
copy of the peel this project unified after the CRLF defect, with a
mutation anchor guarding the one copy. A rewrite that keeps the one peel and
appends the 81% of lines that need no work verbatim is 434 ms, 1.12x -
some 50 ms in a sweep whose run-to-run spread is 180 ms. None is worth a
second implementation or a retargeted anchor.

**The two line numberings, item 6.2, answered without changing code.**
Eight sites number lines with `enumerate(splitlines())` and two with
`line_number_at`, and they differ only on a document holding one of the
breakers `splitlines` honours and `LINE_BREAK` does not. Counted across
185 repositories and 108,647 documents read strictly: 15 hold one - 12 a
form feed, 2 `U+2028`, 1 `U+2029` - and 13 of those between backticks on a
line. The numberings can differ on 0.014% of documents; the item closes on
that number.

**5.3 and 5.4, the pre-filters, taken - with the derivation and the fold
that made them more than a substring test.** Both scans run a pattern the
user may configure, so the words a document must hold come from the
pattern itself: `leading_literals` in
`plugin/skills/extant/payload/extant/text.py` reads a leading `(?:a|b|c)`
of plain literals and refuses every shape where the words are not
necessary - a quantifier after the group, a top-level `|` later in the
pattern, a `\b` or inline flag first, a `\w+` inside the alternation -
each of which is a test. A configured pattern of any other shape scans in
full. Deriving the words once onto the built `Config` was the first
design and would have been wrong: tests replace a pattern with
`dataclasses.replace`, and the stored words would have belonged to the
pattern before it.

The comparison is not `lower()` alone. `re.IGNORECASE` folds four
characters onto ASCII letters that `str.lower()` does not - dotted and
dotless capital I, long s, the Kelvin sign - verified: `SH<U+0130>PPED in 1.0`
matches the default release pattern and `lower()` leaves no "shipped" in
it. A text holding any of the four is let through unread. Conservative in
every direction: a wrong True costs a scan that finds nothing, a wrong
False would cost a claim, and the corpus differential below is what says
the second never happened.

Over the corpus the words are rare - release words in 3.6% of 108,647
documents, merge words in 2.9%, `rev:` in 0.1% - which is why a pre-filter
pays: on ruff, 19, 12 and 5 of 650. `_pinned_refs` asks for `rev:` before
it asks for the remote, so on CI, where the remote is a spawn per document
that the config cannot answer, only the documents holding a pin pay it -
three of this repository's five - and `tests/test_spawn_budget.py` counts
them from the files rather than assuming every document.

**5.2, the precompiled slug patterns, kept as a tidy-up.** `anchors()`
went from 892 ms to 826 ms with identical results; the `re` module's cache
made the string spellings a dictionary lookup per call, 232,581 of them,
and not a compile. One mutation anchor followed the spelling.

**The differential.** `scan_differential.py` in the measurement tree
records, per tracked document of the 152 visible manifest rows, digests of
both blanking flavours, the anchor set, and the release, merge and pin
lists, from whichever payload it is pointed at; run against HEAD's payload
and the changed one and compared per document, so a divergence names the
file. Git is never asked - the pin walk is given one fixed remote in both
runs.

**Found on the way, recorded rather than fixed here.** Every bench-tier
clone is `blob:none`, so `GIT_NO_LAZY_FETCH` changed that tier's output:
rename hints no longer appear there, and a `dead-path-pointer` finding
carries its hint INSIDE `detail` - "; git shows it renamed to ..." - which
is the baseline fingerprint. The hint varies with the checkout, shallow or
partial or a rename older than the 200 commits read, and that is the
argument that moved the commit-map hint out of the identity and into a
field of its own. The rename hint should follow it; a CORPUS.md
re-recording on the bench tier would otherwise show a removed-and-added
pair for every hinted dead pointer.

## A path index, measured and refused

The review's item 3.3: replace `resolve_reference`'s filesystem walk - one
directory listing per path component, memoised on `dircache` - with one set
built from `ls-tree -r HEAD` and a case-folded map, and answer every
`dead-md-link` and `dead-path-pointer` from it. Three things were to fall
out: the case verdict identical on every platform without touching a
filesystem, a tool that works on a bare repository, and `--at <ref>`. The
cost it named: a link to a file that is present but untracked - a build
output - resolves today and would become a finding. Its deciding count:
under about 0.1% of resolved references, switch outright; higher, index as
the fast path and walk on a miss.

**The premise is wrong by two orders of magnitude.** Measured on
2026-09-15, in-process and sequential, with every binding of
`resolve_reference` wrapped in a clock: on ruff the walk costs **0.02 s of a
5.9 s sweep** - 455 calls, 164 directory listings, all memoised on the run
scope; on next.js 0.09 s of 9.0 s (1.0%, 17,242 calls, 2,520 listings); on
kubernetes/website 0.46 s of 129 s (0.4%, 134,147 calls, 10,277 listings).
The 27% the previous section attributes to `dead-md-link` is the whole
rule, and the profile puts it in `link_sites` - 0.49 s wall, called 1,301
times for 650 documents, once by `check` and once by `examined` - and in
`anchors()`'s slugging; the walk is 1% of the rule. Two prototypes stood in
for the walk on ruff, three sweeps each, medians: index-first with the real
walk on a miss, 5.91 s; index-only with a case-folded map for the spelling
verdict, 5.83 s; today, 5.90 s. Both byte-identical to today's output. A
memo of the link scan keyed on text identity saved nothing either: the
second call arrives on a different string object, and the scan is 8% of
the sweep at most.

**The count the review asked for, and why the corpus can only half answer
it.** Every reference the rules resolved during a sweep of the 152 visible
clones (the 43 held-out rows untouched), classified against `ls-tree -r
HEAD`, `ls-files` and the disk: 115,364 distinct references, 49,840
resolved, 27,710 dead, 37,814 absolute or leaving the repository. Resolved
and absent from HEAD's tree: **0 of 49,840**. Not because links to build
outputs do not exist, but because every clone is pristine - nothing built,
nothing staged - so the cost the review named cannot be seen here by
construction. What the corpus does settle: 1,175 resolved targets are
directories, every one implied by a tracked file, so an index needs the
implied directories and nothing more; 33 dead references are case
mismatches against a tracked file, the spelling verdict a folded map
reproduces; 0 resolve through a symlink or into a submodule; the index and
HEAD never disagree.

**The one real argument for an authoritative index is a verdict, not a
speed.** 1,022 of the 27,677 dead references - 3.7%, in 28 repositories -
(corrected 2026-09-28: 28 CLONES, and not all of them findings - 665 rows in
24 repositories de-duplicated, of which 460 are findings in 18 and 205 are
candidate spellings a rule tried before it settled; the section "The owed
bundle" in `quality.md` has the split. And 27,677 is the 27,710 dead above less the
33 case mismatches, whose targets exist under another spelling; none of the
1,022 is one of them, so the share is 3.7% against either, re-checked from
the rows 2026-09-29)
name gitignored paths: ruff's generated `docs/settings.md` and
`docs/default-rules.md`, babel's `build/`, autogen's generated API pages.
Dead in every fresh clone and in CI, resolving on any machine that has run
the docs build: "true where you are standing is not true", inside the tool
built to catch it. An index that answers from HEAD would make those
verdicts deterministic. It would also make three other changes at once: a
tracked file the checkout could not materialise - MAX_PATH on Windows, a
sparse checkout - would become "exists" where it is "dead" today, which is
the choice `tracked_markdown` already made for documents; a target created
and staged but not yet committed would become dead at pre-commit time,
which is wrong unless the index is HEAD plus `ls-files`, a second spawn;
and none of the three can be counted on pristine clones. A changed verdict
here is admitted on a count, and this one would be argued from principle.
So it is recorded as the case for a separate proposal, with the population
that would decide it named: repositories with a docs build, measured on a
checkout that has run it.

Refused as a performance change; not built as a verdict change; the
apparatus - `m6_probe.py`, `m6_driver.py`, `m6_report.py` and `m6_timing.py` in
the extant-hardening checkout beside this one, outputs under
`D:/repo/out-pathindex/` - is what a later proposal would start from. What the profile says the link
rules actually cost - the scan and the slugging - belongs to the review's
3.1, and its premise is the same inner loop.

## One document scan, measured and refused; its bar all but met without it

The review's item 3.1, the last of its architecture proposals and the one
it called the big one: `prose()` and `strip_code()` are memoised per
document, but each of thirteen rules then runs its own `finditer` over the
result, so make ONE tokenizer pass per document produce a span table -
fence regions, inline code, line breaks, headings, link sites, backticked
tokens, bare hex runs, the newest entry's bounds - and have every rule's
`_sites()` become a filter over it; then extract every claim in every
document first and resolve once per repository. Its own bar: identical
findings on every corpus repository, and a sequential ruff sweep under
3.5 s against the 7.0 s it measured, 5.9 s by the time this was read.

**The scan side, on the clock.** The review's figures - 2.5 million
`re.Pattern.match` calls, 9.1 million Python calls - were cProfile counts
on 0.26.1, and two tranches had moved both since. Measured again on
2026-09-15 with `time.perf_counter` around every scanner, in-process and
sequential, three sweeps of ruff's 650 documents, medians, and EXCLUSIVE
of anything a scanner calls that is itself timed, so the sum counts nothing
twice (`m7_scanners.py` in the measurement tree): 5.87 s in all. The
rule-owned scans - the two SHA candidate scanners, the merge and release
claim scans, `link_sites`, the fragment, path-pointer, line-pointer and
floor scans, the pin walk, `split_entries`, `anchors()` - sum to 3.23 s,
55%, with the shared blanking another 0.52 s. That is above the 2.4 s
the bar needs, and it is not what a span table removes. A shared pass
replaces the DUPLICATE walks and the per-pass line loops; the regex work
inside each scanner still runs, once, over the same characters. The
duplicate walks are the scanners called twice per document, once by
`check` and once by `examined`, and their second call costs 0.45 s across
all of them. The nine per-line passes a document pays - `splitlines()`
plus an `enumerate` loop before any pattern runs - cost 275 ms together
(`m7_overhead.py`), so one loop in place of nine saves about 0.25 s.
**What a span table can remove is 0.7 s of the 2.4 s its bar demands.**
The second half, resolving once per repository, is already there: a
650-document sweep of ruff spawns `cat-file --batch-check` twice, for
0.056 s. And the rewrite would retarget 39 of the 246 mutation anchors,
the ones that sit inside scanner bodies. Refused on that number, the way
3.3 was.

**Where the time actually was.** The same clock, ruff, exclusive seconds:

| | s | share |
|:---|---:|---:|
| `git log --diff-filter=R`, one spawn, the rename map behind 28 repair hints | 1.37 | 23% |
| `anchors()` slugging every document's own headings, eagerly | 0.84 | 14% |
| denominators computed and discarded: the entry-scoped rules' `split_entries` twice per document, the repository rule's configuration load once per document | 0.63 | 11% |
| the path-pointer scan, a three-way alternation the pre-filter cannot derive words from, every line | 0.54 | 9% |
| the blanking, already shared | 0.52 | 9% |
| the two SHA scans, backticked 0.32 ungated and bare 0.41 gated | 0.72 | 12% |
| everything else: the remaining scans (`link_sites` 0.21, release 0.18, line pointer 0.15, fragments 0.11, merge 0.08), the other four spawns, the survey's own listing and reads | 1.25 | 21% |

None of the first four is the shape 3.1 describes. The first is git, and
on next.js it is 3.46 s of 7.8 - a single `log --diff-filter=R -n 200`
walk on a `blob:none` clone, paid only when a dead link or pointer wants
a rename hint; recorded here beside item 6.3 and left alone. The other
three are work nobody read, and one ungated scan.

**Four changes, none of them 3.1, bound at runtime over the shipped
payload first so the working tree stayed untouched, each swept byte for
byte against today's output (`m7_variants.py`):**

| | ruff | next.js |
|:---|---:|---:|
| today | 5.75 | 7.52 |
| A `dead-md-anchor` slugs its own headings on demand | 4.96 | 7.37 |
| B the sweep counts only the denominators it keeps | 5.15 | 6.86 |
| C a mandatory-literal gate on the two ungated line scans | 5.10 | 7.27 |
| D an identity memo on the two pure twice-run scanners | 5.56 | 7.44 |
| all four | 3.59 | 6.00 |

Seconds, medians of three (two for next.js), sequential and in-process.
Identical output on every row. Shipped, uninstrumented, medians of three:
**ruff 3.65 s** (spread 3.65-3.72) and **next.js 6.36 s** (6.13-6.64) -
0.15 s short of the bar 3.1 set for itself, inside the run-to-run spread
of the measurements that set it, and with 1.3 s of it being the one
`log --diff-filter=R` spawn no scan change can reach: the Python side of
the sweep went from 4.4 s to 2.3 s. next.js says the shares differ by
repository: A is worth 0.8 s where 11 documents of 650 hold a
same-document fragment, and 0.15 s where most do.

**A.** `check` computed `own = anchors(text)` before the site loop, for a
value one shape consults - a bare `#fragment` into the document - and 639
of ruff's 650 documents never reach that shape. It is a closure now,
built on first use, the shape `ambient_anchors` beside it has had since
the project-wide anchor set was made lazy for the same reason. `x in own`
is the same test wherever `own` is built.

**B.** `count_examined` computed all thirteen denominators and the sweep
kept the ones `rule_applies` allowed; on a repository with no primary
document the two entry-scoped rules' `split_entries` walk ran on every
document, twice, and `inconsistent-artifact`'s `load_config` once per
document, all of it dropped. `registry.count_examined` takes the
predicate now, as `applies`, and the sweep hands it the same
`functools.partial` of `rule_applies` it filters the answer with, so the
predicate is stated once. A skipped rule is still present at 0 - the
shape every caller reads is unchanged - and `--verify` passes nothing and
gets every count, because for an extra document it prints "examined 0"
deliberately, as a different fact from "not applicable". One consequence
named rather than discovered: a denominator that would have raised for a
skipped rule is no longer recorded in `RULE_ERRORS`, and that is right,
because the rule's `check` never ran and the record would have named the
failure of a rule that did not look.

**C.** Two per-line scans ran their patterns on every line. The
backticked-SHA scan's two patterns each carry a literal backtick, so a
line without one is skipped on the same argument the line-pointer rule
makes for its colon - checkable by reading the patterns. The path-pointer
pattern is the user's to configure, so its gate is DERIVED:
`required_literals` in `text.py`, the companion of `leading_literals`,
walks the pattern at the top level - outside every group and class,
unescaped or escaped as itself - and keeps a character only when no
quantifier follows that could make it optional and no top-level `|`
offers a match without it. Letters are refused, because the pattern
compiles `IGNORECASE`; whitespace is refused; `VERBOSE`, inline `(?x)`
included, refuses the whole pattern, because under it a space in the
source is not a literal. The default yields a backtick and nothing else; a
configured pattern offering no such character scans every line as before.
Every shape that must yield nothing is a test in
`tests/test_prefilters.py`, beside the ones for the words, and the same
file asserts on lines the default pattern matches that the gate never
refuses one.

**D.** `link_sites` and `_release_claims` were the last per-document
scanners with two readers and no memo: 1,301 calls each on 650 documents,
every second one a re-walk. Each keeps the one-entry identity memo
`find_sha_candidates` and `merge_claims` keep, with the half of the key
`_STRIPPED` is recorded as missing present - the document format beside
the text for the link scan, the pattern object beside the prose for the
release scan - and both are complete keys, so neither is in
`registry.forget_memos`. `_fragment_sites` re-walks too and is left
alone: it reads the disk, its memo would need a lifetime, and its second
walk is 0.057 s.

**The gate.** Beyond the suite, the 152 visible corpus clones swept
before and after through the shipped payload, in-process and sequential
so the header names no worker count, one output per clone, diffed byte
for byte (`m7_identity.py`, `m7_sweep_one.py`, outputs under
`D:/repo/out-identity44/`): 152 outputs compared, 0 differ. The mutation
campaign gained ten anchors, one per way a change could become a verdict
rather than a speed-up - the headings never slugged, the predicate
inverted, the predicate dropped, each gate inverted, a letter or a
quantified literal kept by the derivation, the top-level bar ignored, and
each memo's key with its second half removed - and one existing anchor on
the line A edited was retargeted; all eleven were applied to a copy and
watched turning the suite red, 12 of 12 killed with the Phase 39 anchor a
label prefix pulled in, none survived, none unapplied, in 64 minutes.

## The probe tranche: one batch, one scope, one list, and a matcher read against git

Tranche 11 of the internals review, 2026-09-20 and 21: the five probes Phase
45 named as "an afternoon with a number each" and nobody had taken - 4.10,
4.5, 5.9, 5.6 and 5.7. Every one was measured before anything was written,
on this machine, and the numbers decided them the way they were supposed to:
two built whole, one built by half, two refused, and a differential that
found a one-line disagreement nothing could reach and closed it anyway. The
whole tranche changes no output on the visible corpus, by construction and
by the identity gate below.

**4.10, one batch and one scope.** `--deleted-since` read each changed
document's previous version in a `git show` of its own, and the review's
decider was the spawn count. Counted on this repository before the change:
`--deleted-since v0.26.1` started TEN git processes for four changed
documents, in 543 ms - the four reads, the `diff --name-only`, one
`cat-file --batch-check`, and the ref table and the trunk `rev-list`
twice each. That second cause was not in the review. `deleted_claims`
opened no run scope, so every `validate()` it called opened a fresh one and
re-asked what the previous document's had learned: the exact deleted
`with session.run_scope():` that tests/test_spawn_budget.py pins for
`--verify`, in a mode nothing pinned. Both closed: `_documents_at` is ONE
`cat-file --batch` fed `<ref>:<path>` per line, its records paired with the
names by position rather than by parsing the echoed name out of a header
that may hold a space, and the loop sits inside one scope. After: five
processes for the same four documents in about 330 ms, five for the five of
`v0.20.0` where there were eleven, `examined` unchanged at 4 and 5. What the
batch answers with `missing` is three facts under one spelling - an absent
path, an object a `blob:none` copy does not hold, or a bad ref - and on such
a copy with `GIT_NO_LAZY_FETCH=1` the missing-object case prints exactly what
the absent-path case prints; `_listed_at`'s `ls-tree` still tells them
apart, so `MissingObject` survives the change and the partial-repository
test that found the guard's gap still passes. One answer changed on purpose:
a configured name that was a DIRECTORY at the ref used to come back from
`git show` as a tree listing and be validated as a document; the batch says
`tree`, which is not a document, and the name counts as absent then. One
capability was given up and is written in the docstring: names are fed on
lines, so a configured document name holding a newline cannot be asked -
`--batch -z` would allow it and arrived in git 2.40, against a floor of
2.31; no configuration anyone has written names such a file. A name holding
a SPACE is fine, and was not for an hour: a `missing` line echoes the name,
so `HEAD~1:docs/my doc.md missing` has four fields, and a parser counting
three from the front read it as a blob record whose size was the word
`missing` and crashed on the integer. The gap audit that closed the tranche
found it; the header is read from its end now, where the type and the size
are, with a test for the absent spaced name and one for the present one,
and an anchor. Population, stated: 0 of the 152 visible corpus clones track
an `.extant.toml`, so this repository is the only measured caller of the
mode, and the direct subprocess ledger in tests/test_scope.py stays at
eight with its eighth site renamed.

**5.7, one scope across `--verify`.** This repository's own `--verify` made
five git processes: the SHA batch, and the ref table with the trunk
`rev-list` TWICE - once for the status document and once for
tests/harnesses/README.md, which carries one release claim - because
`run_validate` opened a scope per document. The pair costs 40 and 61 ms here,
101 ms of a 700 ms run, 14 per cent of the command the post-commit hook runs
after every commit. It holds one scope across the run now, and `--sha-map`
is what decides: with a map the mode translates a document's SHAs and
writes the file back between reads, which is precisely the write a stable
scope promises does not happen, so there the scope stays per document,
opened after each rewrite, exactly as it was. Three spawns for this
repository's five documents. The budget test's invariant moved from "twice,
once per validate() + count_examined() pair" to "once per run", and its
narrative says why; a second test runs the same two-document fixture with
and without a map and asserts one table and two - the assertion the review
asked for beside the change. The shape of the regression is different now
and the test says so: a deleted outer scope shows as one table per asking
document, a deleted inner one as two per document in the arm this checkout
never takes.

**5.6, the list handed down; the rest refused.** The review measured
workers re-asking three `ls-tree` and two `log --diff-filter=R` in one
sweep. Traced here with `GIT_TRACE` over a parallel sweep of ruff's autopsy
clone - 650 documents, 8 workers, 5.1 s - the survey started ten git
processes: `ls-tree -r -z --name-only HEAD` five times (the parent's listing
and four workers re-asking through `sites.py`), the bounded rename log
three times (three workers that needed a hint), and two SHA batches. The
listing costs 46 ms there; the rename log 1,361 ms. And the parent's own
listing is taken before its scope opens, so it was memoised nowhere: on the
sequential path the first document to reach `sites.py` had the parent list
the tree a second time. Built: `run_sweep` keeps the listing it built the
survey from, seeds it into its own scope, and hands it through `initargs`
beside the config so `_worker_init` seeds each worker's; `survey()` takes
it as an optional third argument and `--introduced-since`, whose parent
lists no tree, passes nothing. It is the same list the survey was built
from, so nothing a worker reads can differ from what the parent read - the
identity gate's prediction of zero rests on that sentence. Measured on a
six-document fixture whose documents reach the project-wide anchor set:
seven listings for one parallel survey became one, two for one sequential
survey became one, both counted through `GIT_TRACE` because a worker is a
process a `subprocess.run` counter in the test cannot see. Refused with
the numbers: the rename map, because handing it down means the parent
computing it eagerly - 1,361 ms serial before the pool, on every sweep
including the ones where no worker asks - against three of eight workers
paying it lazily only when a hint is needed; and the ref table and the
trunk index, which no worker asked for on ruff at all and which would cost
28 and 337 ms eagerly to seed. Passing what the parent already has is free;
passing what it would have to go and get is not.

**4.5, the differential run, the swap refused, one line fixed.** The review
proposed `git check-ignore` as the exclusion engine and asked for a
differential first. `m11_checkignore.py` in the extant-hardening checkout
fed every tracked path of the 152 visible clones - 866,696 paths, 793,684
distinct strings, 81,424 of them documents - through `_exclusion_regex` and
through a scratch repository's `check-ignore --stdin --no-index -v
--non-matching`, one pattern at a time, with the operator's global excludes
neutralised (they had ignored `.claude/settings.local.json` under every
pattern on the first run) and `core.ignorecase` pinned false; rows under
`D:/repo/out-checkignore/`. The six shapes config.md documents and
seventeen more a skip-list is likely to be written in: zero disagreements
on documents. Five disagreements on non-document paths, all one class: a
trailing slash names a DIRECTORY in gitignore and the matcher also took a
FILE of that name - `pkg/debian/docs`, `hack/validate/vendor` and three
more Debian packaging files. `excluded_documents` could never reach the
difference, because its input is the document list and a document carries
a suffix; it is closed anyway, one line making the slash mean "something
beneath", with a unit test, an anchor, and a row in config.md's table, so
the matcher agrees with git on every shape that table claims. The review's
gap classes, confirmed with counts rather than asserted: `*.md` with
`!README.md` differs on 4,830 documents and `docs/*` with `!docs/README.md`
on 1, because the negation is a literal that matches nothing; `[Dd]ocs`
differs on 56,866 paths, `docs/[a-c]*.md` on 68, `docs/[!a-c]*.md` on 327,
because a class is a literal too. Not silently, which corrects the review's
premise: a pattern that matches nothing is named by the sweep as one, so a
user who writes `!` or `[a-z]` is told their pattern excluded nothing. A
third class the review did not name: with `core.ignorecase=true`, the
default of every Windows and macOS clone, git additionally excludes 8,508
paths under `**/test/**`, 5,143 under `*test*` and 34 under
`**/fixtures/**`; the regex answers everywhere as git answers on Linux.
Real-world use of the two missing features, the review's other count: this
repository configures no `exclude_paths`, no corpus clone tracks a
configuration, and the documented example and the apparatus's canary use
neither - 0 of the 3 patterns anyone has written. The swap is refused on
three numbers: it adds a spawn and a git dependency to a pure function for
two features 0 patterns use; it would make the skip-list follow
`core.ignorecase`, so that 8,508 documents excluded on a developer's Windows
clone would be read on Linux CI - the "true where you are standing" shape
this tool exists to catch, installed as a setting; and the matcher it would
replace has just been shown to agree with git on every documented shape.
Six rows of the differential matched nothing on either side (`docs/guide.md`,
`docs/**/fixtures`, `test/fixtures/a.md`, `a/b/c` and the two escapes) and
so decided nothing; the middle-`**` arm is exercised by `src/**/*.md` alone,
1,078 paths, exact. `!` and `[...]` would be an afternoon if a user ever
writes one; the sweep will say so when they do.

**5.9, refused.** The review asked for `-X importtime` and then for the
modes `--verify` never reaches to be imported inside the dispatch, with a
bar: `--verify` under about 50 ms of import. Whole-interpreter medians of
fifteen here: a bare interpreter 40 ms, `import extant.cli` 221 ms. The
in-process marginal cost, median of twenty fresh interpreters: the four
deferrable modes - `sweep`, `deleted_since`, `introduced_since`, `collect` -
3.65 ms; `extant.session`, which is the eager registry and its thirteen
rules, 60 ms after the standard library; the standard library the package
needs about 120 ms, of which `dataclasses` through `inspect` is 22,
`argparse` 21, `re` 17, `pathlib` 10, `subprocess` 9 and `tomllib` 7. The
only other lever is `report.py`'s `hashlib` and `urllib.parse` at 12.65 ms,
and `report` is what renders the baseline and the machine formats `--verify`
itself emits. The bar is three times further away than everything
deferrable put together, and the deferral buys 2 per cent of the import and
half a per cent of a 700 ms `--verify` - 5.1 was refused at 1.5 per cent of a
sweep, and this is smaller. Refused; the review's sentence goes here
instead of into a comment on code that did not change: "a lazily imported
rule is a missing rule" protects the registry, which must stay eager, and
says nothing about the modes, which could be deferred any afternoon the
number justified it.

**The gate.** Suite 1,322 passing and 3 skipped, eleven tests added. Ten
anchors written and five retargeted on the lines the batch, the scopes,
the seed and the matcher changed - fourteen run on one copy, 14 of 14
killed in 69 minutes, and the two on the batch header's parse, written
after that campaign had started, on a second copy of the final tree: one
killed, and one SURVIVED - the anchor that turned the header's `rsplit`
into a `split`, which the size-field guard beside it makes equivalent for
every name a `missing` line can echo. An anchor that matches without
biting is the AXIS lesson again; it was retargeted at the guard itself,
which the spaced-name test does catch, and run for real: killed. The corpus identity sweep against a stated prediction of
zero of 152 differing, because the only change a sweep runs through is
which process lists the tree: 152 compared, 0 differ. The pre-push chain
against a working-tree extract: smoke 45 clean of 47 with the two
expected flags, scenarios 213 of 213, fuzz at seed 20260824 over 35
repositories with 0 violations, `--verify` clean, `--selftest` 7 fired
and 0 silent, and `--self-check` 22 of 22 on its second run - the first refused
one of its own breakages, whose anchor at eight spaces of indentation
matched mid-line once `run_validate` put its documents under one scope
at twelve, exactly the refusal the harness's record says it makes. The measurements above were taken before any of it was
built, and the after-numbers in 4.10 and 5.7 on the same repository
afterwards.
