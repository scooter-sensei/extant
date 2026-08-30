# extant - session status

Entries newest first. Everything from the numbered sections down is permanent
reference and is never archived.

This file is not decoration. It is the corpus the test suite validates against,
so the tool is exercised on a real document rather than only on fixtures.

## Phase 25 - The two modes nothing was driving, and the probe that proved nothing (shipped, 2026-08-28)

**Status.** Suite is 732 tests, all passing. This work shipped in 0.24.0, from
the commit `d60b822`, and is merged to `main` at `aa005a5`. Phase 24 shipped in
the same release. Two of the four defects below were found after that tag and
shipped in 0.24.1: the release-claim denominator that counted what its check
could not read, and the bound that did not bind on a CR-only document. Each
version is recorded here only after its tag exists:
`release_claims_name_our_tags` is on, so writing it beforehand would have been
a dead release tag in the CI run the release had to wait for.

The wording is "shipped in 0.24.0" and not "is version 0.24.0" for a reason
worth keeping. `release_tag` matches a version only after `released`, `shipped`
or `tagged` followed by `in`, `as` or `at`, so the second phrasing states a
version that no rule reads - a claim that looks checked and is not, which is
the shape this whole file exists to refuse. Phase 23 below carries exactly that
wording and is unchecked today.

**What changed.** `--archive` and `--search` are now driven end to end by the
suite. Neither mode had a test that went through argparse and the config load:
every archive test called `entries.archive()` directly with an explicit
`retain`, so the `retain=None` fallback to the configured value had never run,
and `--full` had no test at all. That is the shape `--search` shipped broken in
- a mode nothing drove end to end, handing the raw `StatusConfig` where the
derived `Config` was needed - and `--archive` reaches the same funnel.

Eleven tests, in [tests/test_archive_mode.py](tests/test_archive_mode.py) and
[tests/test_search_mode.py](tests/test_search_mode.py), each watched failing
before being trusted: the archive mode's counts and the relocation those counts
claim, asserted separately because a mode printing `archived=2` while writing
nothing would satisfy the first alone; the stale-pointer removal; the
`retain=None` fallback; the guard that refuses the wrong config type; and for
search, the excerpt against `--full`, the 96-character cap, the refusal of an
empty query, both directions of the nothing-to-search note, both documents with
the live one first, and the reference sections skipped while still counting
toward the denominator.

**The probe that proved nothing.** The first version of the pointer test ran
`--archive` twice over an unchanged document. That returns early at
`phase_count <= retain`, so the second run wrote nothing and the test passed
against a build with the stale-pointer removal deliberately deleted. Staging a
sixth entry between the runs is what puts the pointer path back in the run. A
mutation run said so; nothing else in the suite could have.

**One defect found and left unfixed.** `--archive` against a repository with no
status document dies with an unhandled `FileNotFoundError` raised at
`plugin/skills/extant/payload/extant/entries.py:89`. `run_selftest` handles the
same case by naming `primary_doc` and its source and returning 1; `run_archive`
has no such guard.

**The harness list stopped carrying a count of itself.** `fuzz.py` was missing
from the table in `tests/harnesses/README.md` while having a section below it,
`AGENTS.md` said "five audits ... run by hand" when there are seven and three
are CI jobs, and `CONTRIBUTING.md` said "four more audits" while naming the
pre-fuzz set. No rule here can catch that, because no rule inspects a number.

**Three defects the new claims exposed, all now fixed.** Each was invisible
until this document made a claim the rule could read, which is the argument for
the paragraph below. The third was found by stopping to ask whether it was safe
to wrap a claim before writing eight of them, rather than by anything failing.

- **`dead-release-tag` counted claims its check could not read. FIXED.** Three
  readers of one pattern ran two different scans: `examined` and `probe`
  searched the whole document while `check` - the only one that decides a
  finding - matched per line. `release_tag` separates its parts with `\s+`, so
  a claim wrapped at the margin was seen by two of the three. That is the
  sharper form of the merge-claim defect below: there a wrapped claim was
  absent from the denominator too, and the count at least said "nothing here";
  here it reported `examined=1, findings=0`, which prints as examined and
  clean. The one number kept to tell "checked and fine" apart from "never
  looked" was reporting the wrong one. `check` and `examined` now read one
  scanner, bounded to a single line break like the merge one, and restructuring
  the check dedented a block that three mutation anchors named - all three
  reported STALE, were retargeted, and were re-run for real rather than assumed.

- **`strip_code` did not preserve offsets on CRLF, and its docstring said it
  did. FIXED.** It blanks code with spaces precisely so "every character offset
  survive", but both blanking loops read `splitlines()` and rejoined with a
  bare newline, which decides the terminator instead of carrying it through:
  every `\r\n` lost a character - 1627 on this file - and a trailing newline
  went even on LF. `md_link` and `md_anchor` build their probes by taking a
  span from the stripped text and splicing it into the original, so on a CRLF
  checkout the splice landed one character earlier per preceding line. The
  probe reported corrupting a real match while the rule read an untouched claim
  and correctly found nothing, which looked like two broken rules and was
  neither. `--selftest` exited 1 on Windows and 0 on Linux for the same commit,
  so CI structurally could not see it - the runners check out LF, where the
  only casualty is the final newline. Both loops now carry the terminator
  through verbatim, the loss on this file is 0, and the contract has tests of
  its own plus a mutation aimed at the CRLF branch, so the next attempt to
  simplify it back fails on the platform the defect reaches.
- **`false-merge-claim` could not see a claim split across a newline. FIXED.**
  `merge_claim` separates its parts with `\s+`, which matches a newline, and
  the rule's probe searches the whole document - so a wrapped claim was found
  there. The scanner the rule actually reads fed the pattern one line at a
  time, so the pattern was never given the chance its own `\s+` describes. Two
  matchers for one claim, and the rule was the blind one. The failure is the
  quiet direction: a false claim went unexamined rather than judged and found
  true, counted by the denominator as absent rather than as passing. Found by
  accident, because the first draft of the status line above wrapped.

Both are fixed. The second widens what a scan matches, which is the change this
project refuses to make on reasoning alone, so it was measured first: across
263 markdown files in four checkouts the widened scanner found **2 claims the
line-based one missed and lost none, with no false positives**. Both recovered
claims are the same real one, in a document nobody here wrote - `MERGED to` at
the end of a line and `main at` a SHA on the next.

Scanning whole text also lets that `\s+` cross anything whitespace-shaped,
including the spaces `prose()` leaves where a fenced block was, so a claim may
now wrap exactly one line break and no more. Without that guard a sentence
ending in a branch name can adopt a SHA from the paragraph after it, or reach
through a blanked fence to one the fence existed to mark as an example. Both
shapes were built, watched being invented, and are refused - inventing a claim
nobody wrote is worse than missing one, because a false positive is what gets a
validator switched off.

**A fourth, from a review rather than from a claim, and it named a third of
itself.** A CodeRabbit run over these commits reported one finding: the
merge-claim bound counts `"\n"`, which is right for LF and for CRLF - `\r\n`
contains one - and silently wrong for a bare `\r`, which contains none. Checked
against the code before being acted on, and true: the bound never tripped on
such a document, so the guard against a claim borrowing a SHA from the next
paragraph was not a guard, and every claim reported line 1.

It named `commits.py`. The release scanner had the identical defect and was not
named, and `entries.py` had a worse relative of it that nobody named: `^` in a
MULTILINE pattern follows a newline and `\r` is not one, so a CR-only status
document is a single line to every entry-header pattern. Nothing splits,
nothing moves, and `--archive` reports a document with no entries in it rather
than failing - the reassuring zero, in the only operation here that writes
irreversibly. Its terminator default would also have rewritten every line
ending in the file as a side effect of retiring two sections.

All three fixed against one `LINE_BREAK` that counts every spelling a line
ending has. Seventeen tests; the corpus is unchanged at 263 files, 50 merge
claims and 60 release claims, because for LF and CRLF this changes nothing. The
archive write-back test PASSED before the fix - the archive was a no-op, so
nothing was rewritten and the file was trivially intact - so `entries.py` was
repaired in two stages to watch that test go red in between. Acting on a review
literally would have fixed one site of three and shipped a test that asserted
nothing.

CR-only line endings are close to extinct, and that is deliberately not the
argument. A bound that does not bind is the failure this package is built to
refuse.

**Why this entry carries the claims it does, said out loud.** `--selftest`
probes a rule by corrupting a real claim, so a rule this document makes no
claim for reports `NO PROBE` and is not shown to work - 3 of 13 fired before
this entry. The merge claim, the two links, the line pointer and the anchor in
this sentence are every one of them true, and they are here so the rules that
read them have something to corrupt. Stating that is the point: a document
arranged to satisfy a check, without saying so, is the same move as deleting a
claim to pass one. See [1. Layout](#1-layout) for where these files sit.

**A branch claim was here too, and the tool was right to kill it.** The entry
named the worktree branch this work was written on. That branch exists in one
local checkout and was never pushed, so `--verify` passed here and
`unknown-branch` fired the moment CI ran it against a clone. The claim was
verified against the machine that wrote it rather than against the repository,
which is the same mistake as a check that passes because it examined nothing -
"true where I am standing" is not true. It is removed rather than repaired by
pushing an ephemeral branch, which would hand the same failure to whoever
deletes it later. `unknown-branch` goes back to having nothing to corrupt, and
that is the honest price.

## Phase 24 - The survey learned to use every core, and an outside branch was mostly refused (shipped, 2026-08-24)

**Status.** Suite is 672 tests, all passing. Thirteen rules, thirty-two
modules, and no new setting. The last release is 0.23.0 at `f6aafc34`;
everything in this entry sits above that tag and is unreleased.

**What changed.** A large `--sweep` spreads across up to eight worker
processes above 100 documents. On a 200-document corpus across twelve cores,
best of three: 7327 ms in one process, 2919 ms across eight. Measured against
0.23.0 on the same corpus, which took 8626 ms, the whole stretch is about 2.9x.

Beside it, a set of scans that cost nothing to narrow: the per-document
candidate scans run once rather than three times, the bare-SHA scan skips a
line with no hex run and the line-pointer scan skips a line with no colon, and
`anchors()` walks each heading once rather than four times. Three answers about
the checkout - tracked files, site directories, reference resolution - are now
held for the length of a survey.

Two rules stopped reporting things that are not wrong: a floor of `3.14`
against a manifest saying `3.14.0` was one floor written two ways, and a link
carrying `?plain=1` was a file plainly present resolving to nothing. A shallow
clone now prints a caveat beside the denominators, because `dead-sha` in a
depth-limited clone answers about the slice that was cloned.

**Where most of this came from, and why most of it was refused.** An outside
branch of 31 changed files arrived claiming 3.8x, 100% precision and a green
suite. Seven changes were kept and eleven discarded. The four that mattered:

- **A disk cache keyed on the document plus `HEAD^{tree}`.** Almost every rule
  reads state in neither. Deleting a file a document pointed at left the false
  claim unreported, with the documented `--no-cache` opt-out engaged, and the
  cache was on by default. A validator that goes quiet about a false claim is
  worse than no validator, because the silence is trusted.
- **`--apply`, writing fixes to disk.** Added by deleting the paragraph that
  argued extant must never write - the one saying a validator that edits prose
  can author a falsehood itself and nothing is left to catch it. Its rewriter
  also crashed on a path containing `\s` and injected page content through a
  `\g<1>` in a replacement template.
- **`--prune-baseline`.** Retained only entries seen in the current run, so
  running it beside `--validate` deleted every amnesty belonging to every other
  document and called them stale.
- **A repo-root fallback for unresolved links.** Silently forgave genuinely
  dead links, and replaced a comment recording that a blanket skip had been
  considered and refused by name.

**What was learned.**

- **A claim sheet written by the author of the change is a list of things to
  measure, not a list of findings.** Every headline number needed re-deriving.
  The suite was red as delivered, because the branch left a 7.6 MB generated
  corpus where this repository's own quality gate walks it; the speedup was
  2.38x rather than 3.8x, and 1.04x at the size where it switched itself on;
  and one optimisation was described in prose that does not match the code that
  was actually written.
- **Tests named after a feature can be blind to it.** Three tests called
  `test_parallel_sweep_*` asserted only on findings, which are identical
  whether or not a worker ever starts. They would have passed against a pool
  that silently fell back - which is the bug the branch shipped. Instrumenting
  the code was what established the pool ran; the tests never could have.
- **Graceful degradation is how a feature stops working quietly.** The
  branch's `except Exception: use_parallel = False` and its `if key not in
  gathered: continue` are the same mistake twice: a survey that lost its
  machinery, or lost a file, still printing the summary of a healthy run. Both
  are now announced, and both announcements are pinned by a mutation.
- **Reinventing on a stale base costs more than it saves.** The branch was cut
  at the release tag and independently rewrote optimisations that already
  existed above it - and its versions were slower: 7817 ms against 7292 ms on
  the same corpus, for identical output.
- **A measurement apparatus confound outlived two conclusions.** Running a
  payload from a scratch directory changes where its configuration loads from,
  which made an unrelated repository's findings appear and disappear and
  briefly looked like a fixed probe. Comparing like with like - each payload
  inside a matching checkout - erased both effects. This is the fifth stretch
  running where the instruments were wrong before the code was.
- **A gap audit of the accepted work found two more of the same defect, this
  time authored here rather than inherited.** `is_shallow` read
  `.git/worktrees/<name>/shallow` for a linked worktree, where git keeps the
  marker in the SHARED directory that `commondir` names - so every worktree of
  a shallow clone answered False while git answered true, and the caveat that
  exists to prevent a silent wrong answer was itself silent. Its test passed
  because the test invented the layout instead of asking git for one; it now
  builds a real shallow clone and a real worktree and uses `git rev-parse
  --is-shallow-repository` as the oracle. Separately, a survey that lost a
  document printed the loss and still exited 0, so a hook or CI job reading
  only the code would have seen a clean run. Both were caught by auditing what
  had already been reviewed and accepted, which is the argument for doing it.
- **A probe cannot tell a message from a call, and should not have to.** The
  smoke harness scans this package's operational source for the shapes a
  network call takes, keeping string literals because a git subcommand only
  ever appears as one. A `NOTE:` line reading "this is a shallow clone" put the
  word `clone` there and read exactly like `_git(repo, "clone", ...)`, so the
  adversarial pass reported a SECURITY finding against a tool that opens no
  sockets. The message now says "shallow repository", which is what `git
  rev-parse --is-shallow-repository` calls it and is truer anyway, since a
  linked worktree of a shallow clone is not itself one.

  It was caught only by CI, after a push, because the harness is a separate
  slow job. The same source scan now also runs in the suite in under a second,
  so the next one is caught before the push instead of after it.

**Verification.** 672 tests. Mutation anchors 152 of 152, with five retargeted
after the code they named moved and every one confirmed killed. `--verify` and
`--selftest` both exit 0, `--selftest` unchanged at 4 fired and 0 silent. Sweep
output is byte-identical to `17a096a` on two real repositories, and the
parallel and serial paths agree line for line over 200 documents. Every kept
change that alters what extant reports was mutated to confirm its test fails
against the wrong implementation: seven for seven.

## Phase 23 - One 6,249-line file became a 32-module package (shipped, 2026-08-18)

**Status.** This work shipped in 0.23.0, tagged at `f6aafc34`. Recorded here
after the fact: the release shipped without an entry, so this file went on
describing 0.22.0 as current. The full account is in CHANGELOG.md; this is the
part that belongs in a session log.

**What shipped.** `plugin/skills/extant/payload/extant_collect.py` is 68 lines
- a version handshake, a config import, an entry-point import and a `__main__`
guard - and the collector is a package of thirty-two modules. A rule is now one
module owning its check, its probe, its denominator and its registry entry, so
adding one is a file and an import rather than four edits in four places.
Fifty-two module-level mutable names became three scope objects with stated
lifetimes.

`--verify` output is byte-identical to 0.22.0 with one deliberate exception:
`inconsistent-artifact` examines seven sources rather than five, because the
package version and the shim version are two new places a version is written.
The one declared behaviour change is that a rule which raises is named beside
the denominators instead of taking the run down.

**What was learned.** Wall-clock was flat, not faster - twelve git processes
instead of fourteen, very nearly cancelled by importing thirty-two modules
instead of two, so `--verify` moved 928 ms to 937 ms. The honest summary is
that the split cost nothing and bought structure.

One bug shipped and was caught by none of the four review layers. `--search`
crashed on every invocation, because the split separated the raw settings
object from the derived one and the search path was handed the wrong kind. It
survived 641 tests, a byte-identical output comparison and ten reviews, because
no test drove the mode at all. The smoke harness found it, at the very end.
A mode nothing exercises is a mode nobody is watching, and the module count
does not change that.

## Phase 22 - The limit 0.21.0 could only name is now configurable (shipped, 2026-08-09)

**Status.** Suite is 606 tests, all passing. Thirteen rules, eighteen presets,
and one new setting. This work shipped in 0.22.0, tagged at `6a27497`.
Thirty-one tags from `v0.5.0`, each carrying a GitHub release. Two changes to
shipped content sit above the tag and are unreleased: a drifted number the gap
audit found (`9931855b`), and the campaign's own repair (`500c6a6`). Everything
else above the tag is this file.

**What shipped.** `exclude_paths`, for documents that are input to a test
rather than a promise to a reader.

The case that decides why this is configuration and not a rule: a renderer's
fixture links to `../assets/does-not-exist.jpg` ON PURPOSE, to exercise the
error path. Nothing git or the filesystem can answer separates that from a
real broken link. Phase 21 measured 18 such findings and shipped naming them
as a limit with no way to act on it.

- **Empty by default.** A skip-list that ships with entries is one nobody
  audits, and this project already shipped a lint whose skip-list excluded
  every file it was meant to scan and passed on an empty scan.
- **The sweep prints what it removed, per pattern, and names any pattern that
  matched nothing.** A skip-list fails silently in both directions.
- **Patterns are gitignore-shaped, not fnmatch.** `*` stops at a separator,
  `**` spans them, a bare name matches a segment at any depth.
- **Excluding a configured document is refused** with a non-zero exit rather
  than resolved.

**What was learned.**

- **The reporting half earned itself immediately.** hugo needs `testdata` and
  its two fixture patterns match nothing; astro needs the fixture patterns and
  `testdata` matches nothing. Neither would have found that out. A skip-list
  entry that matches nothing reads exactly like a working exclusion and
  survives every run until somebody counts.
- **Assert the thing that matters, not the aggregate containing it.** The test
  for attribution checked that excluded plus kept equalled the total. Dropping
  the `break` leaves that sum correct and moves attribution to the LAST
  matching pattern, rewriting the per-pattern report the feature exists to
  print. The mutation survived it.
- **A guard can be unobservable from any document.** The unusable-pattern
  guard changes no verdict on any path, because an empty pattern compiles to a
  regex matching only the empty string. Pinned as a contract on the function,
  which is the rule Phase 21 wrote down and this is its first real use.
- **The index lists a version before pip can install it.** `pypi.org/pypi`
  reported 0.22.0 while `pip install extant==0.22.0` still failed. Two
  different facts, and the release watcher only checked the first.
- **"Latest" is not always pre-selected on a GitHub release form.** It was for
  0.21.0 and was not for 0.22.0. Read the control rather than assuming the
  previous run's layout.
- **A surviving mutation is a claim to investigate, not a verdict to act on.**
  Both survivors here were labelled TEST GAPS by the harness and neither was
  one. The harness cannot tell "no test noticed" from "nothing happened", so
  the tracing is the work and the label is only where it starts.
- **Every measurement failure this stretch produced was in the APPARATUS, not
  the code.** Eight of them: rotted anchors, an anchor pinned to a tuple
  position, a guard covered by its neighbour, fixtures that satisfied their
  assertions regardless, a release watcher naming the previous version, a
  verifier that fetched the objects it was asking about, tests asserting a sum
  where attribution was the point, and two mutations that could not change
  behaviour. Each printed exactly what success prints. The code under test was
  correct every time, which is the argument for auditing the instruments as
  hard as the subject.
- **Run the campaign in the background, never the foreground.** A ten-minute
  tool limit killed a targeted run mid-flight and left a mutation in the copy,
  which made the NEXT run report a bogus "matched 0x". The copy is what kept
  that away from the working tree, and it is the reason the rule says copy.

**Verification.** 606 tests. CI green at `6a27497` before the tag existed, 13
jobs across ten OS and Python combinations. `--verify` and `--selftest` both
exit 0.

The published wheel was installed from the index into a clean environment and
RUN: it excluded `testdata`, kept reporting the finding in `README.md`,
printed the per-pattern count, and named `vendor/**` as matching nothing.
Measured on the two repositories that motivated the feature, hugo went from 10
findings to 4 and astro from 31 to 19.

**The full mutation campaign was run: 154 mutations, 152 killed, 2 survived,
0 not applied.** It takes two hours and CI runs only `--check-only`, so
before this the nine new mutations had been run and the other 145 were known
to MATCH without being known to be CAUGHT.

Both survivors were inert mutations rather than gaps in the suite, and
establishing that took longer than accepting the label would have. `_TAGS`
outliving its call is guaranteed twice - `validate` clears the cache AND
restores it - so removing either alone changes nothing observable.
`_INTEGRATION` memoises over an already-cached ref table, and three attempts
to observe it failed differently, the third by FAILING ON UNMUTATED CODE,
which is the only reason a test that passed while pinning nothing did not
ship. Both are removed with the tracing recorded where they sat; the campaign
is 152, all matching and all killable.

`tests/test_cache_lifetime.py` keeps the one property worth keeping: a tag
created between two `validate` calls is seen by the second, which is what the
comment beside `_TAGS` describes and nothing tested.

**A gap audit found three things no check here can see.** A shipped claim in
`SKILL.md` that a full sweep of this repository produces 18 findings, when it
produces 29 - true when written, false as the documentation grew, and numbers
are the forbidden class for a rule by design. It now carries the date it was
measured. A design note in the measurement repository that still called
`exclude_paths` "the clearest next piece of work" hours after it shipped. And
SARIF stdout purity, which I added prints beside without testing that path; it
holds, but it was confirmed afterwards rather than at the time.

## Phase 21 - The rules did not generalise, and forty unseen repositories said how (shipped, 2026-08-09)

**Status.** Suite is 589 tests, all passing. Thirteen rules, eighteen presets,
unchanged - every fix narrows a rule that already existed. This work
shipped in 0.21.0, tagged at `7e844a3`. Thirty tags from `v0.5.0`, each
carrying a GitHub release.

**Why this was done.** Every rule here was designed against 92 repositories
and tuned until that set was quiet, so re-running there measured the fitting
rather than the rules. Those clones are deleted. A disjoint corpus of 40
replaced them, checked mechanically: 0 of the 40 appear among the 88 distinct
repositories that shaped the rules, and the check was proved able to fail by
planting two of them into the list.

**What it found.** 7,658 findings, of which 582 were real. The rest fell into
ten mechanical shapes the design corpus did not contain, and measuring what
the fixes left behind produced four more. Same corpus, one build apart:

| | before | after |
|---|---|---|
| findings on 40 repositories | 7,578 | 632 |
| hand-audited precision | 11 of 24 | 14 of 18 |
| adjudicated real defects still reported | - | 541 of 573 |

**What shipped.**

- **Generator detection reaches three layouts it did not.** haystack declares
  Docusaurus in `docs-website/`, llama_index declares MkDocs in
  `docs/api_reference/` (the search knew `*/docs` but never `docs/*`), and
  svelte numbers its documents for a site built from another repository.
  Between them, 6,360 route-shaped links were judged as files.
- **Detection records WHICH directories a generator governs.** A monorepo
  builds a site from `docs/` and still keeps ordinary READMEs in `packages/`.
  Suppressing routes across both silenced six real defects.
- **Bare names resolve within one translation tree.** fastapi builds a site
  per language and keeps `newsletter.md` only in English, so every translated
  page's broken link to it resolved against the English file.
- **Five narrowings in the SHA family.** A SHA that is link text for another
  repository's commit URL, a hash prefix inside an asset filename, a changeset
  id, a 32-character digest, and an Actions pin naming another repository.
- **Anchors read Setext headings and keep the dash an emoji leaves.** A
  document written entirely in the underlined style offered no anchors at all.
- **A prose path resolves beside its own document**, as `dead-md-link` always
  did; the inconsistency between the two rules was the bug.

**What was learned.**

- **A held-out corpus is the only thing that can tell a working rule from a
  well-fitted one.** Three of the fixes were wrong in ways only 40 unseen
  repositories revealed, including one that silenced 68 real defects.
- **Measurement refuses as much as it approves.** Two candidate rules were
  killed by counting first: a creation-verb rule for runtime outputs is right
  1 time in 3, and a backslash-path rule matched mostly shell line
  continuations. Both were shape heuristics, which the path rule already
  learned once.
- **A residue recorded as an unavoidable trade is worth re-deriving.** Three
  astro findings were documented as the cost of keeping llama_index quiet. The
  real cause was an unbounded heuristic matching three files in a test
  fixture, and there was no trade.
- **`--check-only` says an anchor matches, never that it is caught.** Six
  anchors were retargeted after CI failed; running them for real then showed
  one still surviving.
- **A guard that another guard covers is a guard nobody is running.** A new
  slug variant stripped punctuation identically to the old one, so breaking
  the old one changed no output and a working check went quiet. Only the
  mutation campaign could see it.
- **An unbounded regex is a hang waiting for a document.** One pattern took
  321,822 ms on a 120,000-character line; the longest line in the earlier
  corpus was 123,427.
- **A release watcher with last release's version hard-coded reports success
  in under a second.** The script watching for 0.21.0 still named 0.20.0. It
  found the previous tag's workflow run, found the previous version already on
  the index, and exited 0. Every number it printed was true and none of them
  was about this release. The version is an argument now, and the script
  refuses to run without one.

**Verification.** 589 tests. Mutation anchors 145 of 145. The nine touched
here were run rather than only checked, and the two slug mutations were run
again after the masking fix. CI green at `fbfea0f` and again at `7e844a3`
before the tag existed, all 13 jobs across ten OS and Python combinations.
`--verify` and `--selftest` both exit 0.

The published wheel was installed from the index into a clean environment and
RUN, rather than confirmed to exist: haystack 5,056 findings to 2, llama_index
1,248 to 18, svelte 211 to 1. The control matters more than any of those - a
plain repository still reports a dead root-absolute link, which is what
distinguishes a narrowing from a rule that stopped working.

**Known residue, so the next measurement does not rediscover it.** Four false
positives survived a hand audit of 18: test fixture data (one target
deliberately names a missing file), a crypto algorithm name that is valid hex,
hashes elided with an ellipsis, and a template naming a file it writes at
runtime. Which directories hold fixtures is a project's convention rather than
a filesystem fact, so it belongs in configuration; `.extant.toml` has no
general path exclusion today, and that is the clearest next piece of work.

## Phase 20 - The machine formats stop contradicting the exit code (shipped, 2026-08-06)

**Status.** Suite is 547 tests, all passing. Thirteen rules, eighteen presets.
This work shipped in 0.20.0. Twenty-nine tags from `v0.5.0`, each carrying a
GitHub release.

**What shipped.**

- **Severity now matches the exit code in both machine formats.** SARIF
  published every finding at `level: error` and GitHub annotations at
  `::error`, including from `--sweep` and `--deleted-since`, which exit 0 by
  design. The README promises a sweep cannot fail your build, the exit code
  honoured it, and the machine formats contradicted both. A gating finding is
  still `error`; a survey finding is `note` / `::notice`, and every result
  carries `properties.gates` so a policy can key on that rather than severity.
- **SARIF was the only output with no denominator.** It now carries
  `properties.examined` plus notifications repeating it and naming any rule
  that examined nothing. Zero results with a full denominator is a clean
  repository; zero results with zeros everywhere is a run that checked
  nothing, and those printed identically before.
- **Alerts show the claim.** `region.snippet` carries the cited line and the
  columns point at the token, so a code-scanning UI underlines the cited SHA
  itself rather than highlighting a line number. Plus `help.markdown`, `helpUri`,
  tags, `precision`, `defaultConfiguration`, `ruleIndex`, `columnKind` and
  `automationDetails.id`.
- **A preset finds its files where the project keeps them.** Not one published
  Helm repository has `Chart.yaml` at the root and neither sampled Unity
  project has `ProjectSettings/` there, so those presets lost their check to a
  path assumption. Resolution is by unique suffix and REFUSES ambiguity: a
  chart collection carries one `Chart.yaml` per chart, and "the chart version"
  is then not one fact.

**What was learned.**

- **When a misrepresentation is found in one output, its siblings are where to
  look next.** Four of the five gaps a self-audit found were the same mistake:
  SARIF was fixed and `format_github` and `--deleted-since` were not.
- **The obvious fix is sometimes the bug.** Passing `repo` to
  `--deleted-since` for snippets would have quoted the CURRENT file against
  line numbers that index the document as it was at the compared ref.
- **A declared property the numbers do not follow is worse than none.** The
  document said `columnKind: utf16CodeUnits` while the code indexed by Python
  code point; 47 corpus files carry 156 non-BMP characters.
- **Uncapped output is an upload hazard.** The longest single markdown line in
  the corpus is 123,427 characters and GitHub rejects a SARIF over 10 MB.
  Snippets are capped at 400.
- **Absent from the failure list is not the same as passed.** A run still in
  progress appears in neither filter, so confirming CI means checking both.

**Verification.** 547 tests. Mutation anchors 141 of 141, checked BEFORE each
commit - the habit added this week, which caught two stale anchors that CI
would otherwise have found after the push. Three SARIF mutations and three
preset-resolver mutations, all killed.

## Phase 19 - Eight candidates refused, and the two clauses that predict it (shipped, 2026-08-05)

**Status.** Suite was 536 tests at the time, all passing. Thirteen rules,
eighteen presets, twelve of which supply a consistency pairing. No code changed
in that work, so it remained released as 0.19.0 against twenty-eight tags from
`v0.5.0`, each carrying a GitHub release.

**What shipped.** Two new clauses in the admission test, in `CONTRIBUTING.md`
and `references/design.md`:

- **Clause 3: a rule must name the PLACE the answer lives.** Every shipped rule
  points at one bounded location - this ref, this file, this manifest, this
  document. "Search the repository and report if the token is not found" is not
  a location, because absence over an open space has innocent explanations:
  built by concatenation, read through a prefix scan, re-exported, mounted
  under a router prefix, or owned by a dependency.
- **Clause 4: the two sides must name the same SINGLE fact.** Clause 3 alone is
  not enough, and this was learned by trusting it: two candidates were chosen
  BECAUSE clause 3 endorsed them, and both failed.

**The eight candidates, all refused.** Two corpora: the existing 39
library-shaped repositories, and a new 21-repository application corpus built
because both earlier rejections had blamed corpus skew.

| candidate | why it failed |
|---|---|
| env vars (2 attempts, 6 approaches) | absence of the literal is not absence of the variable |
| code symbols | the `path:symbol` form does not exist: 5 sites in 39 repos, all placeholders, 0 in 21 apps |
| HTTP endpoints | the measurement could not fail; see below |
| CLI flags | 159 absent, dominated by `git --amend`, `docker --pull`, `celery --pool` |
| ports | names its location, but a dev compose file publishes 76 of them |
| image tags | zero cited in prose; the 316 counted were inside `docker run` fences |
| manifest version vs README | 1 of 23 repos states it, and that README holds six version tokens |

**What was learned.**

- **A falsifiable question is not a sound inference.** Every candidate above
  clears clause 1 cleanly. The admission test had no example of failing its
  second clause, and now has one.
- **Three of the eight died on one sentence:** a documented token this project
  does not implement is usually a token belonging to something else.
  `CARGO_HOME`, `git --amend`, `docker --pull`.
- **A check whose input guarantees the answer prints like a clean pass.** The
  endpoint measurement reported 347 examined and 0 findings across four
  repositories and eight years of history, and was void: `git grep` searched
  the document the claim came from, so every endpoint matched itself. Fixed in
  the apparatus rather than remembered - `corpus_search.appears_outside` takes
  a REQUIRED exclusion argument, and its selftest reproduces the fault before
  demonstrating the fix.
- **Every measurement in the family produced a defect in its own apparatus:**
  config extensions counted as code symbols, a tautological search, markdown
  separators read as CLI flags. The apparatus needs the same scepticism as the
  rules and only gets it by cross-checking one measurement against another.
- **`inconsistent-artifact` requiring configuration is not a usability
  compromise.** Only the author knows which two strings in a repository name
  one fact. It is the rule's essential input, and it is exactly what a port or
  image-tag comparison cannot obtain.
- **Recommendations made without looking are the recurring error.** The
  `path:symbol` form was called viable without counting it; preset expansion
  was proposed without checking that twelve presets already do it.

**Where this leaves the rule family.** Exhausted for now. What remains either
asks about absence over an open space, or cannot say which two values name one
fact. The apparatus is kept: two corpora, a form counter, a recall harness over
history, a match classifier, and a search helper whose defaults are no longer
wrong.

## Phase 18 - Environment-variable rot, refused a second time (shipped, 2026-08-04)

**Status.** Suite was 536 tests at the time, all passing. Thirteen rules,
eighteen presets. No version was cut for that work, because nothing shipped but
documentation, so it remained released as 0.19.0 against twenty-eight tags from
`v0.5.0`, each carrying a GitHub release.

**What shipped.**

- **The admission test gained an example that fails its SECOND half.** Both
  copies of the candidate list refused everything by inspection - numbers, the
  network, judgement - so a reader came away believing that finding a clean
  falsifiable question is the hard part. Env rot is the counterexample: the
  question needs no network, inspects no number, exercises no judgement, and is
  language-agnostic. It still dies. `CONTRIBUTING.md` carries the short form
  and `references/design.md` the long one.
- Nothing links to the measurement. It lives outside this repository with the
  other candidate evaluations, and a pointer to a path that does not exist is
  what `dead-path-pointer` is for.

**What was measured, and refused.**

Six approaches to raising the rejected rule's 22% precision. Five measured,
all dead:

- **Ask git when the literal disappeared.** It never appeared. All three
  sampled true positives were absent from source at every commit, confirmed
  against a positive control because a pickaxe over a blobless clone returns
  the same zero whether the token is missing or the blobs are.
- **Gate on "this project declares literally".** No separation: flask 13
  literal namespace strings, poetry 15, humanlayer 19.
- **Docs against `.env.example`, as an omission.** Ambiguous by design - an
  example file lists what you must set, docs list everything.
- **Docs against a compose file, as a contradiction.** 8 of 39 repositories
  carry such a file, and their values are third-party image settings and dev
  examples rather than documented defaults.
- **Documented default against source default.** The best of the six, because
  it speaks only from a visible read and so never infers from absence. Zero
  sites in four of five sampled repositories.
- **Disqualifier markers** were refused without measurement: a skip-list that
  grows silently, and it would miss poetry's bare string concatenation.

**What was learned.**

- **A falsifiable question is not a sound inference.** This is the distinction
  the admission test was missing, and it is the whole reason the rule fails.
- **A confidence gate can be contaminated by the signal it seeks.** Calibrating
  on "what share of documented variables appear in source" silenced the only
  repository with genuine findings, because having true positives is precisely
  what lowers that score. Worth checking for in any per-project gate.
- **Erring safe is not a defence for a wrong answer.** A check that refuses to
  call anything clean trains its reader to overrule it, and the reader then
  overrules it on the occasion it is right. Met twice today from opposite
  directions: here, and in a worktree survey that called a merged tree
  unmerged.
- **The corpus is library-shaped, and that is not only an env-rot problem.**
  Library projects configure through code, applications through declarative
  files. `dead-line-pointer` draws a denominator from 3 of 39 repositories and
  `manifest-floor-mismatch` examined 7 claims corpus-wide; some of that
  thinness may be corpus skew rather than rule narrowness. Testable, and it
  changes what "widen the rules" should mean.

## Phase 17 - A denominator for the survey, and a gate for the release (shipped, 2026-08-04)

**Status.** Suite was 536 tests at the time, all passing. Thirteen rules,
eighteen presets. That work shipped in 0.19.0, published to PyPI and verified
from the installed wheel rather than from the working tree, and it left all 28
tags from `v0.5.0` carrying a GitHub release with only the newest holding the
Latest badge.

**What shipped.**

- **`--sweep` reports a per-rule denominator**, summed across every document it
  read, with a `NOTE:` naming rules that examined nothing anywhere. It had
  printed how many files it read and how many repository-wide rules ran;
  neither said whether a RULE examined anything. `--verify` has reported this
  since the beginning and the sweep never called `count_examined` at all.
- **One definition of which rules run.** A sweep skips entry-scoped rules
  outside the primary document, markdown-only rules for `.rst`, and runs
  repository-scoped rules once for the survey. The predicate came out of
  `validate` into `_rule_applies`, so the findings loop and the count read the
  same answer instead of two that drift.
- **The denominator had been counting claims inside code blocks.** Six rules
  strip code first, because a claim in a fence is an example rather than a
  promise, while `count_examined` scanned the raw document. `rust-lang/rfcs`
  reported `dead-sha 23` where the rule reads 11. It affects `--verify`
  identically, so any project quoting a SHA inside a fence will see its
  `checked` numbers drop; the old ones were overstated.
- **Sweeps cost 24-33% more**, measured on 651- and 308-document repositories.
  An initial 43-76% was cut by caching the two functions the rules and the
  count both compute, which profiling named precisely.
- The gate harness never set `_DOC_FORMAT`, so it stripped reStructuredText as
  markdown across numpy's 555 rst files. Already wrong for `dead-md-link`
  before this change.

**What the release itself then taught, in the same session.**

- **0.19.0 shipped to PyPI with its own `tests` run red.** The refactor above
  moved two rule-selection guards into `_rule_applies`, so two mutations
  anchored on the old inline text matched nothing. `mutate.py --check-only` is
  a CI step rather than a pytest test, so a green local suite said nothing
  about it, and nobody opened Actions between pushing and tagging ninety
  seconds later. Third time this pair has rotted through an unrelated refactor
  of `validate`; retargeted, and confirmed to KILL rather than merely match.
- **`publish.yml` now refuses a commit the suite has not passed.** The two
  workflows were independent triggers, so a red suite never blocked an upload.
  The build job asks the API whether `tests.yml` succeeded for this commit
  before building anything, matched by COMMIT because `tests.yml` runs on
  pushes to `main` and never on a tag. See
  `.github/scripts/require_green_tests.py`.
- **Finding no run FAILS.** That state is reachable in normal use, by tagging
  before pushing the branch, and a gate reading "nothing found" as "nothing
  wrong" passes hardest exactly when its subject was never checked. Pending
  waits up to thirty minutes; only `success` is green, because a cancelled run
  is not a passing one; a network error or missing configuration blocks rather
  than allows.
- **Proved end to end with a throwaway pre-release tag**, not only with
  fixtures. A tag on a commit that was never pushed to `main` reached the gate
  past the two checks before it and stopped there: `0 run(s) found -> fail`,
  with build, wheel-check and upload all skipped and nothing published. Tag
  deleted afterwards; the tag and release counts are back in step.
- `CONTRIBUTING.md` records the manual check as well, because learning a
  release is blocked is cheaper before the tag exists than after.

**What was learned.**

- **Writing a residual down is what gets it fixed.** This entire release is the
  first residual of the previous one, closed the same day it was recorded. The
  cost of the note was three sentences.
- **A two-part guard hides a weak test twice over.** The mutation for
  "repository rules counted once" survived because the assignment after the
  loop masks the `continue` inside it, and then survived a second time because
  the fixture had no primary document, so the applicability check excluded
  those rules on its own and the wrong implementation gave the right answer.
  Neither masking is visible when reading the test.
- **Checking one field of a config is not checking the config.** A corpus
  comparison reported a rule firing where the code had nothing to do with it.
  The right hypothesis - two payloads configured differently - was raised,
  tested against `CONFIG.release_tag`, which came back identical, and set
  aside. The pattern is shared; `release_claims_name_our_tags` beside it is
  not. A comparison harness that cannot show both sides were configured alike
  will eventually report its own setup as a finding.
- **Symmetry is not correctness.** A new cache was given the save/restore that
  every other cache in `validate` has. Those are dicts mutated in place; this
  one is a rebound tuple, so restoring discarded exactly the entry its caller
  needed. It cached nothing, read as correct, and was found by re-profiling.
- **A green test of a component is not evidence the component runs.** The
  publish gate had eleven passing tests and five killed mutations while its
  workflow step, its `actions: read` permission and its token wiring were all
  unexercised - every one of those drove `decide()` with hand-built
  dictionaries. That is the same shape as the two mutation anchors: passing
  every local check while pointed at nothing. Only a real tag settled it.
- **A local suite is not the gate.** The self-check job runs `--check-only`,
  `--selftest` and a timing run, none of which pytest carries, deliberately.
  So `pytest -q` being green answers a different question from the one a tag
  depends on.

**Verification.** 536 tests. 8 of 8 mutations killed for the denominator work
after the first run killed 7, and 5 of 5 for the publish gate. Corpus: 39
repositories, 2,148 findings, 0 changed, with the harness printing its
configuration-parity check before comparing anything. `mutate.py --check-only`
reports 139 of 139 matching.

## Phase 16 - A thirteenth rule, and the hole between it and an old one (shipped, 2026-08-04)

**Status.** Suite was 512 tests at the time, all passing. Thirteen rules,
eighteen presets. That work shipped in 0.18.1, and it left all 27 tags from
`v0.5.0` carrying a GitHub release with only the newest holding the Latest
badge.

**What shipped.**

- **`dead-line-pointer`, the thirteenth rule.** `core/engine.py:123` where
  that file has 40 lines. It does not ask whether line 123 still holds what
  the document says, which would be judging content; it asks whether the file
  has that many lines.
- **Keyed by what the corpus made obvious.** 7,775 candidate sites, 6,525
  outside a code block, and then a collapse to 51 - the rest name something
  the repository does not track. Three of the 51 cite a line past the end, all
  in `obra/superpowers` plan documents, all real: an implementer told to
  modify line 68 of a 64-line file. The operative-use keying that
  `path_pointer` and the manifest rule both needed proved unnecessary here,
  because resolution to a tracked file does all the work.
- **A dead path wearing a line number was checked by nothing.**
  `dead-path-pointer` required the extension immediately before the closing
  backtick, and the new rule requires the file to resolve before counting, so
  between them neither looked. A trailing suffix is now tolerated and excluded
  from the capture.
- Three defects found by auditing the rule before releasing it: `_LINECOUNT`
  was never cleared by `run_sweep` while every sibling cache was,
  `_LINE_COUNT_LIMIT` was defined after its first use, and two narrowings were
  undocumented and untested.
- **0.18.1 fixed 26 findings from a whole-repository review.** Three crashes a
  user meets on first contact - `--selftest` without the primary document,
  `--sweep` on a repository with no commits, and a relative
  `--write-baseline` - plus `consistency_timeout_seconds`, which was inert
  because a module-level assignment ran after `_apply_config()` and replaced
  the configured value with None. `SKILL.md` had fallen two rules behind, and
  `workflow_dispatch` could publish an untagged version from any branch.

**What was learned.**

- **A whole-repository review finds what a diff review cannot.** Every one of
  those four had been in the tree for releases, past a suite that grew to 507
  tests, because nothing ever changed the lines they lived on. Reviewing
  against the ROOT commit made the diff the entire codebase.
- **"Fix all of them" is not the same as "apply all of them".** Three
  suggestions were rejected on inspection: routing the pre-commit guard
  through the advisory shim would have turned a blocking check into one that
  cannot block; adding `docs.json` as a filename signature would have silently
  stopped link checking for any project with an unrelated file of that name;
  and three flagged "hard-coded counts" were historical measurements, which
  are this project's evidence and do not drift the way a current-state count
  does.
- **The guard that let SKILL.md drift was the shape of the thing it guarded.**
  `test_every_rule_is_documented` checked one table and there were two, so a
  rule could ship documented in the place contributors read and absent from
  the place users read. Proved the widened test works by deleting a row and
  watching it go red.
- **A harness that is less careful than the tool will invent a finding.** The
  harvest reported four beyond-EOF sites and the rule reports three. The extra
  was a pytest transcript inside a reStructuredText literal block:
  **rst code blocks are indentation, not fences**, and the harness knew only
  about fences while `_prose` is format aware. Precision was 3 of 3, not 3 of
  4, and the difference was only visible by checking what the tool does rather
  than trusting the measurement built to check it.
- **The two-part guard is now a recognisable shape rather than a surprise.**
  The first mutation run killed 3 of 7, and all four survivors were it: a test
  input rejected independently by a second guard, so breaking the first
  changed nothing. It has appeared in every rule built this session, and
  isolating it always needs a deliberately awkward fixture.
- **A fix can be right and unmeasurable at the same time.** The path-pointer
  widening adds no finding and moves no denominator across 39 repositories,
  because not one writes an operative pointer with a line suffix. The corpus
  proves it breaks nothing and cannot prove it helps, so it ships on a hole
  demonstrated in a fixture and says so in the code, the tests and the
  changelog.
- **Separating commits after the fact needs the intermediate state rebuilt,
  and rebuilt states have to be run.** `git add -p` was unavailable, so the
  audit changes were removed to recover the tree as it stood when the rule was
  written. Each of the three commits was then checked out in a throwaway
  worktree and the full suite run there - 499, 505, 507 - because the failure
  mode of that technique is a first commit that quietly already contains the
  second one's changes.

## Phase 15 - A twelfth rule, measured before it was written (shipped, 2026-08-04)

**Status.** Suite was 482 tests at the time, all passing. Twelve rules,
eighteen presets. That work shipped in 0.17.2, and it left every tag from
`v0.5.0` carrying a GitHub release, against 19 at its start.

**What shipped.**

- **`manifest-floor-mismatch`, the twelfth rule.** A README saying "requires
  Python 3.8+" against a `pyproject.toml` declaring `>=3.10`. Two statements of
  one fact, both inside the repository, which is the question
  `inconsistent-artifact` already established as legal rather than a judgement
  about whether a number is correct.
- **Keyed from a corpus, not from what the wording ought to be.** Keyed on
  shape it disagreed at 169 of 192 sites, 97 of them in changelogs where the
  claim was true the day it was written. Keyed on entry-point documents, with a
  requirement verb or a bare `Requirements:` label, and no third-party subject,
  it examines 7 sites across 39 repositories and finds 2. Both real:
  datasette's README offers Python 3.8 against a `>=3.10` manifest while its
  own installation guide says 3.10; caddy's offers Go 1.25.0 against `go.mod`'s
  1.25.1.
- **The finding carries the ecosystem's enforcement**, because the same
  contradiction means different things: pip refuses, `engines.node` only warns,
  the `go` directive fetches a newer toolchain. A disjunction and a pair of
  coarse statements are not examined rather than guessed at.
- **`validate` learns which document it is reading**, through a `doc` keyword
  beside the existing `base`. A repository-scoped rule was tried first and
  rejected on evidence: such a rule runs only when `has_entries` holds, which
  in a sweep means the repository carries a configured status document.
- **0.17.1 fixed the same rule being silent in `--verify`.** Both verify call
  sites handed `validate` and `count_examined` a document's text without saying
  which document it was.
- The measurement corpus was given its history back and the full gate run:
  2 findings added, 0 removed, 0 reworded, denominator 0 to 7, and no other
  rule moved.
- **0.17.2 made `inconsistent-artifact` and `raw-lfs-blob` run in a sweep at
  all.** Both are repository-scoped, so `validate` runs them only on the
  primary pass, and in a sweep that means the configured status document,
  which a swept repository usually does not have. They now run once per sweep
  in their own section, outside the per-file totals and not gating, and the
  sweep prints how many repository-wide rules ran.
- **Six GitHub releases**, written from the annotated tag messages and the
  changelog. Five tags were carrying no release, `v0.16.0` through `v0.17.1`;
  `v0.17.2` was released as it was cut. Only the newest holds the Latest
  badge, and the `v0.17.0` notes point at `v0.17.1`, because a release page
  that omits a known defect is the kind of stale claim this project exists to
  catch.

**What was learned.**

- **The denominator found a bug that 477 tests could not.** The first gate run
  reported 2 findings and 0 examined for the same rule on the same run. That is
  impossible, and chasing it was the only reason the `--verify` gap surfaced.
  Every unit test passed throughout, because all of them called `validate`
  directly and supplied the path themselves. Without the denominator the run
  would have shown 2 findings and looked correct.
- **A mutation that breaks SYNTAX proves nothing.** Deleting an assignment left
  the next statement over-indented, so pytest died at collection and the
  mutation scored as killed with zero tests red. Rewritten as an assignment of
  `None`, it survived: the tests covered `extra_docs` and not `primary_doc`.
- **A two-part guard makes a mutation unkillable by accident.** The first
  campaign killed 8 of 14; five survivors were all one shape, where either half
  independently rejected the test input. A Django decoy with no floor suffix,
  a bare mention with no verb, a disjunction with a one-component version. Each
  test had to be rewritten to isolate a single guard.
- **A filter fitted to a corpus must be tested by removing it.** The
  third-party filter carried four hard-coded package names, which would be fair
  grounds to call the whole measurement overfitted. Re-measured with only the
  structural phrases, the keying returned the same 7 examined and the same 2
  findings.
- **Word boundaries were 49% of one rule's harvest.** Without them, and with
  `re.I`, `Go` matches inside "Django", "Mongo", "cargo" and a base64 key;
  `Rust` inside "trust". Nothing in the funnel looked wrong, because a
  plausible number of extra sites is indistinguishable from a corpus that has
  them.
- **A gate can pass with a denominator of zero, and saying so is the
  finding.** The sweep fix showed 2,145 findings before and after with nothing
  added, removed or reworded, which proves no regression and nothing else:
  none of the 39 repositories carries an LFS filter or a consistency block, so
  the corpus never reaches either rule. Checking that, rather than accepting a
  reassuring zero, is the same reflex that made the bug findable.
- **A summarising model answers a leading question the way it was led.** Asked
  "is 0.17.0 present on PyPI", it said yes while pip could not find the
  package; asked to enumerate the index verbatim, it was right. Later it
  reported 25 releases against 24 tags from a truncated page, which enumerating
  three pages in the browser disproved.

## Phase 14 - What the campaign and the profiler found (shipped, 2026-08-03)

**Status.** Suite was 447 tests at the time, all passing. Eleven rules,
eighteen presets. That work shipped in 0.16.2.

**What shipped.**

- **0.16.1's merge-claim fix now reaches installed projects.** It widened the
  collector's DEFAULT; the installer writes its own `merge_claim` which
  OVERRIDES that, so anyone who installed 0.16.1 kept missing exactly the
  claims it was released to catch. The comment beside that line describes the
  same trap from the first time it was sprung, and it was read while making the
  change.
- Branches, tags and ref lookups are one `for-each-ref`. A validate of this
  repository's own status document went from 8 git subprocesses to 6, and from
  261 ms to 214. Byte-identical across 45 repositories.
- `corpus.py --baseline` compares per-rule counts, a digest of each rule's
  finding text, and per-rule denominators. It recorded one total per
  repository, and three kinds of regression walked through that during this
  session alone.

**What was learned.**

- **The first full mutation campaign this project has run - 136 mutations, one
  suite run each - reported two survivors and both were worth having.** One was
  a shipped bug; the other was UNKILLABLE, its mutation breaking half of a
  two-part guard whose other half rejected the same input independently. A
  mutation nothing can kill survives every campaign and reads as a permanent
  test gap.
- **A green check is evidence only once you know what would make it red.**
  Four times in one session a check passed for the wrong reason: a memo
  measured against a PROFILED baseline looked 17% faster and was noise; a test
  written for a survivor passed vacuously because the function emitted nothing
  to loop over; a freshness test failed against correct code because `validate`
  restores caches in `finally`; and a corruption meant to prove one check
  fired changed two things at once, so the check that stayed quiet looked
  broken.
- **Measure the thing you are about to claim, with the method you will quote.**
  The SHA memo was reverted after a controlled A/B in one process measured
  261 ms against 265. It had looked like a clear win against a number taken a
  different way.
- A harness measures the inputs it knows how to build, for the third time. The
  ref-table change moves `perf.py` by 1.5% and a real status document by 18%,
  because its fixtures carry links where real documents carry commit
  references. What gets pinned is the structural claim - four questions about
  refs, one scan - since a spawn count does not vary by a quarter between runs.

## Phase 13 - The corpus that was never sampled (shipped, 2026-08-03)

**Status.** Suite was 440 tests at the time, all passing. Eleven rules,
eighteen presets. That work shipped in 0.16.1. It could not fold into `v0.16.0`: that version was
already on PyPI, which never lets a version number be re-uploaded, so moving
the tag would have left the repository asserting that `v0.16.0` is code PyPI
has never served.

**What shipped.**

- A merge claim may write its commit without backticks. Measured across 45
  repositories: `false-merge-claim` went from 3 claims examined to 35, with no
  finding added, removed or reworded. One repository writes 32 of them as
  `PR #499 merged into main at 6ff1f4ac` and the rule saw none.
- `dead-release-tag` stopped asking whether a version names a tag of THIS
  repository, because nothing in prose says so. That half is now
  `release_claims_name_our_tags`, off by default and set here. 19 findings
  removed across the corpus, none added; the settleable half - the tag exists
  and shipped on nothing - is always checked and was right 7 times out of 7.

**What was learned.**

- **The population a rule serves can exist in public and simply never have
  been sampled.** Phase 12 concluded no public corpus could gate the claim
  rules. 229 repositories from the agent-tooling topics - 52,417 files - carry
  the shipped merge pattern 35 times, the release pattern 97, the branch token
  640 and the live phrase 117. "Claim density" had been chosen by reaching for
  popular Python and JavaScript tools, which are dense in changelogs rather
  than in status claims.
- **Three measurements were corrupted, and each looked like a result.** Shallow
  clones made every historical SHA unresolvable and produced MORE findings;
  lazy fetching in partial clones produced FEWER, drifting as the object store
  warmed; and the gate compared the live payload against copies, which apply
  different configuration because extant reads its config by walking up from
  the SCRIPT rather than from `--repo`. None of the three announced itself. All
  three were caught only by checking a number against a prior expectation.
- **A warning already written down is still a warning you can ignore.**
  `differential.py` had carried "both run from NEUTRAL directories outside any
  repository" in its docstring from the start. It was read, then contradicted
  by checking `load_config(repo)` in isolation and never asking whether the CLI
  calls it for the target. It does not.
- **A mutation campaign rewrites the source in place.** Running one alongside a
  45-repository measurement meant the measurement swept mutated code, and the
  mutation in question restored exactly the behaviour being measured away.

## Phase 12 - Loopholes, and eight widenings that did not survive measurement (shipped, 2026-08-02)

**Status.** Suite was 434 tests at the time, all passing. Eleven rules,
eighteen presets.
`v0.16.0` is tagged, released and on PyPI. Every release from `v0.5.0` is
tagged with no gaps.

**What shipped.**

- `--deleted-since <ref>` reports claims removed while still false. It began as
  a twelfth rule and was demoted to a non-gating report before any of it was
  written: whether a removal was evasion or repair is a question about intent,
  and the common case cuts the wrong way - deleting a false sentence makes the
  document true, so a gating rule would fail the build on the correct fix.
- A consistency block that reaches one file by two routes now asks the
  filesystem rather than comparing strings, with a realpath fallback for the
  filesystems that report `st_ino` as 0. `consistency_timeout_seconds` bounds a
  user-supplied pattern, opt-in because `re` holds the GIL and a watchdog
  thread therefore cannot work.
- Findings carry a `subject`, the bare token a claim is about. A baseline
  forgives the occurrences it recorded rather than every future copy.
- Two more generators are recognised, worth 37 false positives: a site can be a
  subdirectory of a subdirectory, and Mintlify declares itself in `mint.json`.
- Release claims are read against the conventions a project actually uses - the
  tag prefix, a version naming a series rather than a tag, an integration
  branch that is not there, and pre-commit's `rev: ''` placeholder.
- A document full of release claims is an order of magnitude faster: 22.0
  seconds to 1.25 at 400 claims. The cost was in 0.15.0 too.

**What was learned.**

- **A rule keyed on a PHRASE is invisible to any corpus that does not contain
  the KIND of document it was written for.** Across 30 repositories and 3,821
  markdown files, ten of them chosen for claim density, the merge-claim pattern
  matched nothing at all, and that was read here as "no public corpus can gate
  these rules". **The reading was wrong and the sampling frame was why**: claim
  density had been chosen by picking popular Python and JavaScript tools, which
  are dense in changelogs rather than in status claims. 229 repositories from
  the agent-tooling topics - 52,417 files - carry the shipped merge pattern 35
  times, the release pattern 97, the branch token 640, the live phrase 117; 61
  of them exercise at least one. "I sampled 3,821 files and found nothing" is a
  statement about the sample.
- **All eight coverage widenings were still rejected, and the one that shipped
  was not among them.** Measured on the agent-document corpus,
  `false-merge-claim` required the commit in BACKTICKS and so examined zero of
  the 32 claims one repository writes as `PR #499 merged into main at 6ff1f4ac`.
  Making the backticks optional took the corpus from 3 examinations to 35 and
  added no finding anywhere. The spec's own candidate for that rule - a bare
  WORD after the merge verb - changes not one examination on the same corpus.
  A plan guesses at a variant; the corpus has a different one.
- Two corpora were unusable and neither said so. Clones made `--depth 1` leave
  every historical SHA unresolvable, so one repository reported 2,094 findings
  and reports 3 with its history; a partial clone fetches blobs over the
  network mid-sweep to run rename detection, and a single repository stalled
  for half an hour. More findings reads as thoroughness and no output reads as
  slowness.
- A mutation that SURVIVES can mean two mechanisms masking each other rather
  than a missing test. Two survived here; investigating showed one was
  load-bearing and the other was dead code, and the right fix was to delete the
  dead one and test the case only the survivor handles.
- Eleven unit tests could not catch a regression that `scenarios.py` caught on
  its first run. A fix derived from a corpus inherits that corpus's blind
  spots, and no repository in any of the three configures the rule in question.
- **A probe verified on one filesystem has been verified on one filesystem.**
  The `smoke` job went red on Linux and nowhere else, one commit into this
  phase: a case variant is one file on Windows and two on a case-sensitive
  filesystem, and the branch for the second outcome existed as a COMMENT
  describing it rather than as code handling it, so the probe fell through and
  declared a by-design gap. Reading the code showed the case considered, and
  considered is not handled - the same absence-is-invisible shape as a check
  that examines nothing. The run is still in this repository's history as the
  only red one on `main`; it is `7b50a67`, fixed in `81cc1c4`, and it is
  recorded here so nobody has to guess later.
- The tool failed its own build twice on this work. Writing prose to explain a
  false positive reproduced it, and the paragraph recording THAT did it again.
  A rule cannot tell a quotation from a claim - already known for live claims,
  and true of release claims for the same reason. Paraphrase.

## Phase 11 - reStructuredText, and the cost of doing the same work twice (shipped, 2026-07-29)

**Status.** Suite was 382 tests at the time, all passing. Eleven rules,
eighteen presets. `v0.15.0` was tagged and released, with every release from
`v0.5.0` tagged and no gaps.

**What shipped.**

- reStructuredText is swept. The markdown link and anchor rules are skipped
  outside markdown rather than adapted to it, because `[text](url)` in Python
  is a subscript followed by a call and numpy writes exactly that in doctests.
  The claim rules still run, with rst literal blocks and doctests treated as
  code.
- A sweep of 1600 files went from roughly 49 seconds to about 1. Two pieces of
  per-document work were being redone per file, both found by profiling rather
  than by reading: the origin lookup, which is a question about the repository
  and was asked once per document, and the five per-call caches, which a sweep
  can legitimately share because it reads one static checkout and writes
  nothing.
- The project-wide anchor union is built on demand. Eagerly it cost roughly
  400 ms per run at 1600 files on every repository carrying a `conf.py`, for
  documents whose fragments mostly resolve locally.
- `tests/test_caching.py`, and cost contracts in `mutate.py`. A change that
  alters speed and not behaviour regresses silently, so each is pinned by a
  test that was observed failing first.

**What was learned.**

- A harness measures the inputs it knows how to build. `--sweep`, generated
  sites and reStructuredText all shipped while `perf.py` and `stress.py` built
  only generator-free, markdown-only repositories, so none of the new cost was
  visible to the harness whose entire job is finding cost. Re-run those after
  changing what the code READS, not only after changing what it does.
- A stale budget is worse than none. The stress budgets were set from the slow
  numbers and left at 180s and 140s; after the speedup those runs take 33s and
  22s, so a fourfold regression would have fitted inside them unnoticed.
  Re-measure a budget when the thing it watches gets FASTER.
- Reviewing your own work is not review. This phase was self-reviewed and
  reported clean; CodeRabbit then found two real defects in it, one of which
  was a cache outliving its scope so that `dead-pinned-ref` examined nothing
  and reported clean - this project's own failure mode, aimed at itself.
- A scenario's negative assertions are satisfied by a run that never happened.
  Found once in `s25` and fixed there, then found again by review in `s24`,
  where four of eight assertions went green against an empty stdout. Prove the
  run occurred before believing anything it did not say.

## Phase 10 - Run it on somebody else's repository (shipped, 2026-07-29)

**Status.** Suite was 352 tests at the time, all passing. Eleven rules,
eighteen presets. `v0.14.1` was tagged, released, and on PyPI.

Every tag has a release page. The four that did not - `v0.13.0`, `v0.13.1`,
`v0.13.2` and `v0.14.1` - were backfilled from their changelog entries on
2026-07-29. `v0.13.1` is the odd one and its page says so at the top: the tag
exists, no `0.13.1` was ever published to PyPI, and the release gate added in
that very version is what rejected it.

The sentence here used to carry a hand-maintained list of exceptions, and it
decayed twice in the same way. First it read "each has a release page", which
stopped being true three tags later. It was then corrected to name three
exceptions, and stopped being true again when `v0.14.1` shipped without a page
and was never added. No rule can catch either: an enumeration is not a
falsifiable claim about one thing, it is a claim about everything not
mentioned.

So the list is gone rather than corrected a third time. "Every tag has a page"
is checkable by counting two sets, and it is the only form of this sentence
that does not rot.

**What Shipped.**

- `--sweep` at `32ce917`: every tracked markdown file, no configuration, two
  sections, and only the configured one decides the exit code.
- Fifteen false-positive classes across `3c86834`, `884073e`, `a5b791d`,
  `0158059`, `2694601`, `7cb4b03` and `361c1df`, each measured on real
  projects rather than imagined.
- A crash. Every mode died with UnicodeEncodeError writing a finding
  containing non-ASCII to a Windows console, and the test that should have
  caught it was setting `PYTHONIOENCODING=cp437:replace` itself.
- `dead-md-anchor` reaches fragments on other files; `.mdx` is swept; the
  sweep reads HEAD's tree rather than the index.
- `tests/harnesses/corpus.py`, where a repository that cannot be measured is a
  failure rather than an omission.

**What was learned.**

- The central claim had never been tested. Every version before this was
  validated against two repositories written by the same hand, neither of
  which links to another project's source. Pointed at 38 real projects the
  released tool cried wolf about nine times in ten.
- Reasoning about a renderer is not measuring one. Hugo's 101 dead anchors
  were recorded as an irreducible limit caused by shortcode templates; the
  cause was a definition list, visible in the file, and reading it took a
  minute. A limitation is only honest if the diagnosis behind it is.
- Widening a rule is not free even when it looks additive. Unioning anchors
  across a project fixes MyST and forgives two of httpx's three genuinely dead
  anchors, so the namespace has to follow the generator.
- Three throwaway measurement scripts were wrong in one session, each by
  omitting something silently: Git Bash paths Windows Python cannot read,
  clones that failed on MAX_PATH, a checkout that never completed. All three
  printed a confident number. That is what `corpus.py` exists to prevent.
- The audience-specific rules had never met their audience. `raw-lfs-blob` was
  first exercised on a real Unity project this phase, and five of six
  open-source game repositories use no LFS at all.

**Known Issues.**

- Every corpus repository is open source, which biases it. `raw-lfs-blob`
  could be exercised on exactly one, because private Unity and Unreal
  repositories are where game art actually lives.
- `.rst` is not read, so the Sphinx ecosystem is invisible: poetry and pytest
  report zero markdown files.
- A hex token that is really a Windows error code is indistinguishable from a
  short SHA by shape and is still reported. Writing an example of one here
  proved it: the eight-character code quoted in nlohmann/json's changelog was
  flagged as a dead commit in this very entry, so it is described rather than
  written. Inline code is deliberately not exempt from the claim rules,
  because real claims get written inside backticks.
- Detection can guess a wrong `entry_prefix` - it produced `# Boss ` on Unity's
  BossRoom - and says so as LOW CONFIDENCE rather than silently.

**Next Tasks.**

- Stop expanding the corpus. Returns flattened: the last six repositories
  yielded one new class against six from the first nine, and nine of 38 now
  report zero.
- Run a sweep on a private engine repository if one becomes available. That
  would test more than another twenty public clones.

## Phase 9 - A code review, and a way to install it (shipped, 2026-07-28)

**Status.** Suite is 308 tests, all passing. Twelve rules, eighteen presets.
`v0.12.4` is tagged, released, and on PyPI. Every release from `v0.5.0` is
tagged with no gaps, and each has a release page.

**What Shipped.**

- A CodeRabbit review of the whole repository: 35 findings, all addressed
  across `f873a79`, `e160feb` and `d220091`. One critical, ten major.
- The reload staleness class closed twice over, at `26cf385` and `5c6c96a` -
  once with a guard and once by removing the shape that allowed it.
- `v0.10.0` backfilled. It was bumped, committed and pushed without ever being
  tagged, so its own README told people to pin a version git had never heard
  of.
- Published to PyPI at `4bb25d5`, with a workflow that refuses a tag which does
  not match the packaged version, and refuses a wheel that does not work.
- The adversarial harness moved into CI at `de70943`, after being given a
  verdict it did not have. `0.12.3` carries that plus a quickstart command that
  works on a project with no configuration.
- `0.12.4` stops installing anything Claude-specific into a repository that
  shows no sign of Claude, at `a39e74f`. The slash command is the only
  tool-specific file and is now the only conditional one; the open-standard
  skill stays ungated, since that is the half that makes the install portable.

**What was learned.**

- Three guards were written for one bug before one of them was right, and the
  first two were proxies: a table that could not see a COMPUTED value, then a
  substring test that passed because `global X` mentions the name. The check
  that works compares a reloaded module against a fresh import of the same
  project, which is the invariant stated directly rather than approximated.
- That oracle catches DIVERGENCE and not ABSENCE. A global neither path sets
  agrees with itself. Knowing which failure a check cannot see matters more
  than having the check.
- The tool found a false positive in itself, then found this entry describing
  it. `release_tag` swallowed a sentence-ending full stop, so a release claim
  at the end of a sentence searched for a tag with the period attached. Every
  fixture happened to continue the sentence, so nothing caught it. Writing the
  example out here reproduced the match against this very document, which is
  the rule working: it cannot tell an illustration from a claim, and inline
  code is deliberately not exempt because claims get written inside backticks.
- Binary distribution was measured and refused. Two of three install routes
  already handle Python, the payload is standard library only, and PyInstaller
  onefile would add 100-300 ms to every commit.
- A harness can be the thing with no denominator. `smoke.py` ended in an
  unconditional `return 0`, so adding it to CI as it stood would have bought a
  job that could not fail. The fix that mattered was not the exit code but its
  second half: an EXPECTED finding that stops appearing now fails too, which
  turns a green run into evidence that probes ran.
- The first install command a reader meets was broken, and no rule here could
  have found it. It is prose about how to run a tool, and nothing in git or the
  filesystem contradicts it. Installing the released wheel and running it was
  the only thing that would have shown this, which is an argument for doing
  that at each release rather than for another rule.

**Known Issues.**

- A user-supplied regex can still hang, as recorded in the design notes.
- `README.md` is still not self-checked, so `dead-pinned-ref` never sees this
  project's own install snippet. Including it produces four false positives.
- A baseline can suppress a live credential, and one recorded finding forgives
  every future copy of itself. Both are documented in the design notes.

**Next Tasks.**

- Nothing outstanding. The next change should be driven by someone using this
  on a repository that is not this one - now that `pip install extant` is a
  thing they can do.

## Phase 8 - Five releases, and the measurements that overturned three designs (shipped, 2026-07-27)

**Status.** Suite is 305 tests, all passing. Twelve rules, eighteen presets.
`v0.12.0` is tagged and released, and nothing is unreleased on `main`.

**What Shipped.**

- Python 3.9 and 3.10 support, losing no syntax, at `e9e2c71`.
- A baseline, so a long-lived repository can adopt this without fixing every
  finding first, at `343c4b1`. Nothing is ever recorded implicitly and the
  suppressed count prints on every run.
- Eight ecosystem presets, and the four cross-checks the research explicitly
  ruled out, at `addd8c7`.
- Works with any coding agent, not only Claude Code, at `3119b9c`. Agent Skills
  is an open standard, and exactly one line of this codebase was Claude-only.
- Every harness expanded to cover the surfaces added since 0.6.0, at `233cceb`.
- Merge claims now name their own ref, so more than one integration branch
  works, at `121bbe4`. This is what closes the gitflow gap the last entry
  listed as outstanding.
- Game engines: a `raw-lfs-blob` rule and `unity` / `godot` presets, at
  `8ee2339`, released as `v0.12.0`.

**What was learned.** Measuring first repeatedly overturned the design, and in
each case below the plan would have shipped something that did nothing:

- A trunk LIST was the obvious fix for gitflow and the wrong one. A merge claim
  names its own ref, which is strictly more precise and needs no configuration.
- Widening `path_pointer` with asset extensions for game projects was measured
  as a no-op. Game documentation writes paths as markdown links, so the rule
  examines zero references either way.
- Keying the Godot version check on the README would have examined nothing
  forever. A real shipped Godot game states its engine version only in its
  setup document.

**Known Issues.**

- A user-supplied regex can still hang, as recorded in the design notes.
- `README.md` is not self-checked, so `dead-pinned-ref` never sees this
  project's own install snippet. Including it produces four false positives,
  all illustrative examples. The release procedure confirms the tag instead.
- A baseline can suppress a live credential, and one recorded finding forgives
  every future copy of itself. Both are documented in the design notes.

**Next Tasks.**

- `v0.10.0` was never tagged: the version was bumped, committed and pushed, so
  for as long as it was newest the README pinned a tag git had never heard of.
  Backfilling it would make that pin resolve.
- Nothing else outstanding. The next change should still be driven by someone
  using this on a repository that is not this one.

## Phase 7 - Published, and the install path finally walked (shipped, 2026-07-27)

**Status.** Suite is 213 tests, all passing. The repository is renamed on
GitHub, `v0.6.0` is tagged and released, and both documented install paths have
now been exercised from the published repository rather than from a local
checkout.

**What Shipped.**

- The release, and proof that the pre-commit path works: a fresh project, a real
  pre-commit run against the published tag, failing on planted problems and then
  passing once they were fixed. The second half matters as much as the first, as
  a hook that fails on everything looks identical to one that works.
- The marketplace path, exercised end to end for the first time: both manifests
  validated, the marketplace added from GitHub, the plugin installed, and the
  skill delivered with its payload on disk.
- A fix for the `readme` preset, at `4068181`, and the tests that preset never
  had.

**Known Issues.**

- Gitflow-style release branches are still not modelled.
- A user-supplied regex can still hang, as recorded in the design notes.

**Next Tasks.**

- Nothing outstanding. The next change should be driven by someone using this
  on a repository that is not this one.

**Gotchas.**

- A feature verified only where it is incidental is not verified. All five
  presets were checked by hand before 0.5.0, every one in a repository that
  already had a status document, so the preset that exists FOR projects without
  one was never run in that case. It was broken in both releases that followed.
  This is the same shape as the hooks scenario that asserted the retired
  contract: the test exercised the configuration where the feature did not
  matter.
- Installing from the published artifact found what running from a checkout
  could not. Everything passed locally, and the first genuinely new information
  came from walking in as a stranger.

## Phase 6 - Renamed to extant (shipped, 2026-07-27)

**Status.** Suite is 203 tests, all passing. Nothing about the engine changed;
every name did. The old name survives in exactly two places, both deliberate:
the CHANGELOG entry recording the rename, which cannot describe it without
naming it, and `HANDOFF.md` in the document-detection list, which is a filename
in other people's repositories rather than one of ours.

**What Shipped.**

- The rename: repository, package, command, configuration file and table, both
  pre-commit hook ids, both modules, the slash command, the `primary_doc`
  setting, and the preset that used to carry the old name and is now `status`.
- The scenario matrix runs in CI, and three more of this repository's own
  documents are checked.
- A fixture keeping this project's own configuration out of its tests, because
  listing extra documents made a temporary repository inherit them.

**Known Issues.**

- The tag and repository rename are pushed by hand, so the documented
  pre-commit path stays broken for as long as the two disagree. Verify with a
  real install rather than assuming, as with the previous release.
- Gitflow-style release branches are still not modelled.

**Next Tasks.**

- Publish a release from the new tag, and check the marketplace entry installs
  end to end. That path has never been exercised from a published repository.

**Gotchas.**

- A blanket substitution is wrong even when the total reconciles exactly. The
  count matched on the first attempt and the result was still broken: a path
  component written as a separate string literal was renamed to the prose word,
  pointing six test files at a directory that did not exist, and the TOML table
  name went the same way in three places. Identifiers and prose need different
  rules, and only a rehearsal on a throwaway clone showed which was which.
- The same substitution turned a detection candidate into a duplicate of its
  neighbour, silently halving what that list could find. A name that belongs to
  the outside world is not yours to rename, however global the rename.

## Phase 5 - Any documentation, not just a status file (shipped, 2026-07-26)

**Status.** Suite is 202 tests, all passing. The tool no longer asks a project
to keep a status document: a README, a CONTRIBUTING file and a package manifest
are enough, and that was already true before this phase changed a line of the
engine. Five presets, a published pre-commit hook, and a trunk guard that is now
opt-in.

**What Shipped.**

- Repositioning. Peer review made one point hard: most teams keep no running
  status file, so the tool looked useless to them. Testing that rather than
  accepting it showed the engine already handled an ordinary project and found
  a dead commit reference, a dead link and a version disagreement with no code
  changes at all. The barrier was the pitch, so the README, the skill manifest
  and the marketplace entry now lead with the claim-checking question. The
  audience table had been telling exactly the newly-targeted projects "probably
  not for you".
- Presets `readme`, `node`, `python`, `rust` and `status`. A preset chooses the
  documents and the shape; detection still measures trunk and branch naming,
  because a template would be guessing at those.
- A hooks manifest for the pre-commit framework, and the packaging metadata it
  needs to build an isolated environment. Verified by running the real
  framework, not by writing YAML from its documentation.
- The trunk guard became opt-in, wired only by
  `sh tools/hooks/install --with-trunk-guard`. It is the one component that can
  refuse a commit, and it arrives only when asked for.

**Known Issues.**

- No release tags exist in this repository yet, while the README, the CHANGELOG
  and the hooks manifest all pin `rev: v0.5.0` for pre-commit users. That
  instruction cannot resolve until the tag is created and pushed. The rule that
  exists for exactly this claim cannot catch it, because the snippet lives in a
  fenced block and fenced code is exempt from claim rules by design.
- Gitflow-style release branches are still not modelled.

**Next Tasks.**

- Create and push the release tag, so the documented install path resolves.
- An editor or LSP integration. Assessed and deferred: it is a second language,
  a second maintenance surface, and it wants sub-100ms incremental checking
  where a full run is about 400ms.

**Gotchas.**

- Configuration is loaded at import, relative to the file. Installed as a
  package, which the pre-commit framework does, that location is site-packages,
  so the tool must re-read settings for the repository it was pointed at.
  Otherwise the hook validates a filename that belongs to some other project and
  reports a healthy run wherever no such file exists. A test now parses the
  source for every global derived from configuration and fails if one is not
  refreshed.
- A `[extant.*]` sub-table silently discarded every top-level key. The config
  file looked configured and was not, which is this project's own failure mode
  sitting in its own loader. Both sources are merged now, and a key set in both
  places is refused rather than resolved quietly.
- Ten hook tests skip when no POSIX shell is on PATH, and the suite still prints
  green. The hooks were the part that had just changed. What surfaced it was a
  scenario harness that crashed where the unit suite had skipped: degrading
  gracefully turned a gap into silence, and crashing turned it into a report.

## Phase 4 - Files that contradict each other, and a way back to old decisions (shipped, 2026-07-26)

**Status.** Ten rules now, up from nine. The tenth compares files against each
other, which is a different question from the one this tool refuses to answer.

**What Shipped.**

- `inconsistent-artifact`, the tenth rule, and the first with repository scope.
  It exists because this project advertised version 0.1.0 in three manifests
  while the CHANGELOG documented 0.3.0, and nothing here could catch it. No rule
  inspects whether a number is correct, and that restriction stands: whether two
  files state DIFFERENT values for the same thing needs only the filesystem. Off
  unless configured, because a guessed default would accuse an innocent
  repository.
- `--search`, which returns whole entries from the live document and the archive
  together. That is the only reason it beats grep: a decision lives in a dated
  entry with its reasoning, and a matching line tells you a phrase exists rather
  than what was decided.
- `--suggest-fixes`, which emits a patch on stdout and writes nothing. It
  repoints references to files that moved, and touches only link targets and
  backticked paths rather than prose.
- A mutation-freshness check in CI, and a timing run on Linux.

**Known Issues.**

- A consistency check can name the same file by two different routes and then
  always agree with itself. The two-file minimum catches the obvious shape and
  not this one.

**Next Tasks.**

- Reach projects that keep no status document at all, which is most of them.

**Gotchas.**

- Claims live inside inline backticks, so stripping code before checking a
  document turned eight tests red at once. Fenced blocks and inline spans need
  opposite treatment: a fenced example is not a promise, while a claim is
  routinely written inside single backticks. Link rules want the opposite again.
- A rule whose configuration is read from the INSTALLED copy rather than from
  the repository under test passes everywhere and means nothing.

## Phase 3 - Machine-readable output, and a mutation campaign (shipped, 2026-07-22)

**Status.** Suite is 157 tests, all passing. Findings render as GitHub
annotations or SARIF as well as text. A mutation campaign over 31 behaviour
changes found six the suite did not notice; five were real and are now covered.

**What Shipped.**

- `--format=github` and `--format=sarif`, which are rendering of existing
  findings rather than new rules, so they add no false-positive surface.
- Findings now carry the document they came from, which the machine formats
  need and the human one never did.
- Six test gaps closed, each re-checked by re-running the mutation that
  exposed it.

**Known Issues.**

- Settings load relative to the script rather than to `--repo`, and say so.
- Gitflow-style release branches are still not modelled.

**Next Tasks.**

- `--search` over the archive, so a decision can be found after it is retired.
- Rename autofix, emitted as a patch on stdout rather than written in place.

**Gotchas.**

- A rule that reuses an existing pattern inherits its looseness without
  inheriting the gate that made it safe. `unknown-branch` reused `branch_token`,
  which `stale-live-claim` only ever reaches after a live phrase matches, and
  reported a renamed design document as a phantom branch. Found by installing
  into a foreign repository, not by any test.
- Two tests were written that a broken implementation satisfied: one asserted
  a fingerprint helper directly while the defect lived in its caller, and one
  asserted that no rule stayed silent, which a selftest incapable of reporting
  silence satisfies trivially. Assert through the real path, and assert the
  negative case as well as the positive one.
- Mutation testing found what reading could not, but only where a mutation was
  written. Six survivors from 31 attempts is a floor on the gaps, not a ceiling.

## Phase 2 - Four more rules, and a way to prove rules work (shipped, 2026-07-22)

**Status.** Nine rules now, up from five. Suite is 136 tests, all passing. CI
runs both self-checks on every push to the trunk: one asking whether this
document is clean, one asking whether the rules would notice if it were not.

**What Shipped.**

- Markdown link and heading-anchor checking, which needs no configuration
  because link syntax is fixed by the format rather than by a project's habits.
- A rule for branches git has never seen, in refs or in any merge commit.
- A rule for release-tag claims, aimed at projects that keep a CHANGELOG.
- `extra_docs`, so a CLAUDE.md or a README gets every whole-file rule. The
  entry-scoped rules are skipped there, having no entries to scope to.
- Rename hints: a dead pointer now says where git shows the file went.
- `--selftest`, which corrupts one real claim per rule and reports which rules
  noticed.

**Known Issues.**

- Settings load relative to the script rather than to `--repo`. Correct when the
  tool is installed into a repository, wrong when run from outside one, and it
  now says so on stderr instead of disagreeing quietly.
- Repositories using a gitflow-style release branch are still not modelled.

**Next Tasks.**

- Consider whether the archive document should exist from first install rather
  than first archive run.
- A `.pre-commit-hooks.yaml`, so projects already using that framework can adopt
  this by adding three lines to a file they have.

**Gotchas.**

- Measuring first changed what got built, twice. A branch rule keyed on mere
  existence would have emitted four findings and four false positives on the
  first real corpus, because merged branches get deleted. Markdown links and
  release phrases turned out to be entirely absent from the status documents
  available, and are shipped for the general documents `extra_docs` reaches.
- The `--selftest` probe for merge claims first replaced a commit with zeros,
  and reported a working rule as broken: that rule deliberately ignores claims
  whose commit does not resolve, leaving those to the reference check. A probe
  has to corrupt the thing the rule actually inspects.

## Phase 1 - Extraction and first public release (shipped, 2026-07-22)

**Status.** Extracted from the project this was built and proven on, made
repository-agnostic, and packaged as an installable Claude Code plugin. Suite
is 115 tests, all passing. The package validates its own status document,
which is this file, and CI repeats that check on every push to the trunk.

Ready to publish. Nothing is outstanding for the initial release.

**What Shipped.**

- Five validation rules, each answerable yes or no by git or the filesystem:
  dead commit references, stale live claims, false merge claims, dead path
  pointers, and credential shapes.
- Denominator reporting on every rule, so a pattern matching nothing is visibly
  different from a document with no problems.
- Configuration derived by inspecting the target repository rather than copied,
  with a confidence level per value and undetermined values commented out.
- Four extraction fixes, each a defect that was invisible until the tool was
  installed somewhere else. The slash command is rendered per repository instead
  of copied verbatim. The post-commit hook resolves the document name from
  configuration instead of hardcoding one. The pre-commit trunk guard is
  actually shipped, and reads the trunk from configuration. String literals are
  ASCII only, because an em dash in printed output killed the installer on a
  cp437 console.
- Packaging as a plugin marketplace, so installation is two commands rather than
  a clone and a manual copy. The manifest schema was derived by reading the
  plugin manifests installed on the machine this was built on rather than from
  memory, which also corrected the skill frontmatter: it declared a key used by
  2 of 134 installed skills where the conventional one is used by 32.
- Continuous integration across two operating systems and three Python
  versions, plus a job that runs the validator against this document.
- The extraction work was merged to `main` at `5577bec`.

**Known Issues.**

- Repositories using a gitflow-style release branch are not modelled. The
  ancestry checks assume a single trunk.
- The suite runs the shell hooks through a real `sh`, so those tests skip on a
  machine without one. The skip is reported rather than silent, and the
  non-shell checks still cover the same installer defect.

**Next Tasks.**

- Consider a release-tag rule. The admission test it must pass is in
  `CONTRIBUTING.md`.
- Consider whether the archive document should be created on first use rather
  than on first archive run, so a fresh install has both files present.

**Gotchas.**

- Accepting the default configuration without deriving it gives a validator that
  checks nothing, convincingly. Read `plugin/skills/extant/references/porting.md` first.
- A rule reporting zero examined is inert, not clean. The exit code cannot tell
  you which, and that distinction is most of the point of this tool.

## 1. Layout

**Design:** `plugin/skills/extant/references/design.md` records why each rule is scoped as it is,
with the failure that forced each decision. For every configuration key, see
`plugin/skills/extant/references/config.md`.

The skill lives at `plugin/skills/extant/`. Inside it, `payload/` holds the
files installed into a target repository as `tools/`, while `install.py` and
`detect.py` stay put and are never copied.

## 2. Conventions

Branches follow the pattern `feature/short-name`. Commit subjects use the
prefixes `feat:`, `fix:`, `docs:`, and `chore:`.

Two rules for anyone editing an entry above: paraphrase a past status rather
than quoting it, because no rule can distinguish a quotation from a claim; and
write a commit range as two separate backticked tokens rather than one, because
a range inside a single pair is not recognised as a reference.
