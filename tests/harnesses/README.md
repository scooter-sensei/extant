# Harnesses

Tools that audit the test suite and the installed product, rather than the
code paths a unit test can reach. They are **not** run by pytest: each takes
minutes, and each answers a question `python -m pytest` structurally cannot.

(The count used to be written out here. It said "Three" for two commits after
the fourth and fifth arrived, and "Five" for a week after the sixth did. The
table below is the list; a numeral in front of it is a second copy that rots.)

| Tool | Asks | In CI |
|---|---|---|
| `mutate.py` | does the suite pin anything? | `--check-only` |
| `scenarios.py` | does it work on projects unlike this one? | yes |
| `smoke.py` | what happens when someone abuses it? | yes |
| `fuzz.py` | what about the cases nobody thought of? | yes, fixed seed |
| `corpus.py` | what does it say about somebody else's repository? | no, needs clones |
| `perf.py` | is it fast enough to leave installed? | no, by design |
| `stress.py` | where does it fall over? | no, by design |

The last column is a real distinction, not a backlog. A harness belongs in CI
when its result is a VERDICT: `scenarios.py`, `smoke.py` and `fuzz.py` each
answer a yes-or-no question about behaviour, so a change of answer is a
regression and the job can fail on it. `fuzz.py` qualifies despite having no
oracle because the properties it checks are yes-or-no whatever the right answer
turns out to be - and it runs on a FIXED seed there, so a failure belongs to
the commit that caused it rather than to whichever corpus the day drew.
Discovery is a hand-run with a fresh seed.

`perf.py` and `stress.py` answer with NUMBERS, and a
number needs a threshold before it can fail a build. Every threshold loose
enough to survive a noisy shared runner is too loose to catch the regressions
worth catching, and every threshold tight enough to catch them flakes - after
which the job gets rerun on red, then ignored, then deleted.

There is a second reason, particular to this project. Failing a build on
"0.454s is too slow" is a check on whether a NUMBER is acceptable, and the core
guarantee is that no rule here judges a number. A perf gate would be the first
thing in the repository to cry wolf, in a tool whose entire argument is that a
validator which cries wolf stops being read.

So those two stay hand-run, and CI takes the one measurement that needs no
threshold: it prints the median `--verify` time as an annotation, where a human
reading a PR sees it and nothing fails on it.

`mutate.py` sits between the two. The full campaign is half an hour, far too
slow per commit, but `--check-only` asks a verdict question in under a second:
does every mutation still match the code it names? That catches mutation rot
at the commit causing it, which is how it is in CI while the campaign is not.

Between them they found every defect fixed in 0.3.0. The unit suite found none
of those, because the unit suite was the thing being audited.

Each grew again for 0.10.0, to cover the surfaces added since: the baseline,
`dead-pinned-ref`, the SARIF and GitHub output formats, every preset,
and the cross-platform agent instructions. The rule applied throughout was the
one this project keeps relearning - a check must be observed FAILING before it
is trusted. Every addition below was verified by breaking the product and
confirming the check went red. Three did not, and all three were repaired:
two smoke probes whose payloads were unreachable by construction, and a
scenario assertion that was reading the denominator line and calling it a
finding.

They grew once more for the multi-trunk and game-engine work, and both times
the harness found what the unit suite structurally could not. The gitflow
scenario caught that the INSTALLER writes its own `merge_claim`, overriding the
default, so a collector that had been taught to check the ref a claim names
would still have shipped single-trunk behaviour to every new project. The
preset matrix caught that a Unity project whose README carries no version badge
got a permanent "the pattern matches nothing" finding, because the installer
verified its consistency FILES existed and never that its patterns matched.

And again for `--sweep`, generated sites and reStructuredText. That round is
worth reading as a warning about harness DRIFT rather than about any of those
features. All three shipped across two releases while `perf.py` and `stress.py`
were untouched, so the tool acquired a whole-repository mode, a rule that reads
every tracked file in the project, and a second markup language without a
single measurement of what any of it cost. Nothing failed. Nothing could have:
every repository those two harnesses build is generator-free and markdown-only,
so the new cost lived entirely outside what they construct.

The lesson generalises past this project. A harness measures the inputs it
knows how to build, so a change to what the code READS is invisible to it in a
way that a change to what the code DOES is not. Re-run these after adding an
input, not only after adding a rule.

## `mutate.py` - does the suite pin anything?

```sh
python tests/harnesses/mutate.py
```

Breaks the code on purpose, one change at a time, and runs the suite after each.
A mutation that **survives** means behaviour changed and no test noticed.

This is what `CONTRIBUTING.md` means by "watch a check fail before you trust
it". Without it, that rule is advice with nothing behind it.

It found six gaps, two of which were tests that a broken implementation
satisfied: one asserted a helper directly while the defect lived in its caller,
and one asserted that "nothing stayed silent", which is trivially true of a
selftest that cannot report silence.

**Every mutation asserts it applied.** A substitution that silently misses
leaves the code correct, the suite green, and reports SURVIVED - a false alarm
indistinguishable from a real gap. Those are reported as HARNESS FAULTS and
must be repaired, never read as results.

Write the indentation out in full when adding one. A shorter string is a
substring of the real line once a block moves inward, so it keeps matching and
mutates something adjacent. That happened when `validate()` gained a
try/finally: one mutation stopped matching outright, and the other kept matching
by accident.

The `raw-lfs-blob` group is the largest for one rule, because both of that
rule's bugs were invisible in its output. Paths were piped to `git check-attr`
with `text=True`, so Windows appended a carriage return to each and git
answered `unspecified` for all but the last: the survey reported 1 of 4
governed files and the survivor happened to be the one carrying the finding, so
the rule looked perfect. Its mutations therefore aim at the plumbing - the NUL
join, the `-z` flag, the tree-versus-index read - rather than at the verdict.

One mutation was deliberately NOT added there. Reading every governed blob
instead of only the small ones changes cost, never behaviour, so it survives
every campaign and reads as a gap the tests do not have.

**Mutations rot alongside the code they point at.** A later run reported
`merge-claim never fires (matched 0x)` after ancestry moved from a per-claim
merge-base call to a batched rev-list: the line it named no longer existed, so
that behaviour had quietly stopped being probed. It surfaced only because a
mismatch is a HARNESS FAULT here rather than a silent skip. Re-run this after
any change to the code it targets, and repair what it reports.

`--check-only` re-verifies every mutation against the current source in
seconds, running no tests. It is cheap enough for CI, which is where that rot
should be caught rather than at the next half-hour campaign.

**It answers "does this anchor match", never "is this anchor caught", and the
difference has bitten.** A refactor of generator detection left six anchors
matching nothing at once - five naming a function body that had been replaced,
one pinned to `mint.json` being the LAST entry of a tuple that gained an entry
after it. All six were retargeted, all mutations matched, and running them for
real then found one still SURVIVING. Retarget with `--only` immediately after,
or the repair is unverified.

**The survivor was a guard another guard had silently covered.** `slug keeps
punctuation` stopped being killed the week a second slug variant was added
that stripped punctuation identically: breaking the original changed no output,
because the newer function still produced the spelling it no longer did. The
code was correct throughout and the suite was green throughout. Nothing except
a campaign can see a check that has quietly stopped meaning anything, which is
the argument for running one when two functions start overlapping.

**Some properties no behavioural test can reach, and they need a contract
test.** The masking above got its own mutation, and that one survived too:
over-producing anchor spellings only ever SUPPRESSES, so it creates no finding
for a test to catch. It is pinned as an assertion on the function's return
value instead. When a mutation survives and you cannot construct a document
that would notice, that is the signal to test the contract rather than the
behaviour.

`--only SUBSTRING[,SUBSTRING...]` runs one group. A campaign is half an hour,
which is long enough that nobody runs it after touching a single rule, so the
group belonging to whatever just changed can be re-verified on its own. It
prints the selection against the total AND a count per pattern, then refuses a
filter that selected nothing: a typo'd substring would otherwise run zero
mutations and report "0 survived", which is the healthiest-looking output this
harness can produce and means precisely nothing.

The sweep group exists for one mutation in particular. Reading git's INDEX
instead of HEAD's tree is a bug this project has now shipped twice - once in
`raw-lfs-blob`, then again in `tracked_markdown` after the first was found,
fixed and written up in the changelog. Knowing about it did not prevent it, so
it is pinned in both places. Its failure mode is the worst available: an
incomplete checkout leaves the index empty while HEAD's tree is full, so the
sweep reports a clean repository having examined nothing.

The generator group breaks detection in BOTH directions on purpose. Blind,
starlight reported 235 of its own working links as dead; universally on, every
genuinely dead link in a plain repository stops being reported. A mutation for
only one of those would leave the other free to ship.

Those 19 mutations found four real gaps on their first campaign, and all four
were the same shape: behaviour that the unit suite reached by a route which
bypassed the thing being changed.

- The sweep's accounting for a file it cannot decode had no test at all,
  because nothing in the suite had ever handed it one.
- Hugo's `_`-prefix guard was unpinned from both sides. One test has no
  `hugo.toml`, so the fragment scan never runs; the other asserts an anchor IS
  found, which only gets easier as more files become ambient. The case the
  guard actually protects - a Hugo repository whose heading sits in an ordinary
  content directory - was missing.
- `_format_for` is the dispatch that chooses rst, and every test in
  `test_rst.py` sets the document's format by hand. The rules were correct for
  a format nothing would ever select.
- `_MARKDOWN_ONLY` looked covered and was not. Two mechanisms suppress a
  markdown link in rst - the format gate, and rst literal-stripping - and the
  existing test put its payload inside a literal, so the stripping alone
  carried it. Moving the payload into bare prose leaves only the gate.

All four now have tests, and the campaign was re-run to confirm each mutation
is killed rather than assumed to be.

The cross-platform group is aimed at the failure that would be least visible:
setup renders agent instructions to two paths from one set of observations, so
the mutation that matters is not either file vanishing but the two of them
describing different documents. This project shipping a document that
contradicts another document, through its own installer, is the exact thing it
exists to catch.

## `scenarios.py` - does it work on projects unlike this one?

```sh
python tests/harnesses/scenarios.py <extracted-package> <scratch-dir>
```

Builds a fresh repository per scenario, installs the tool, and asserts what
should happen: a Node project on `master`, ticket-prefixed branches on
`develop`, release tags, a repo with no status document at all, CRLF files
nested in `docs/`, a linked worktree, an archive round-trip, the git hooks
firing, and a single-commit repository.

A second set covers shapes drawn from how projects are really laid out rather
than from variations on this one, each stressing a different assumption: a
**monorepo**, where a link inside `packages/api/` resolves against that package
and not the repository root; a **docs/adr/** tree, the densest link graph
documentation normally has; community health files under **.github/**, the one
directory a naive walk skips; **develop, trunk and mainline** as the main
branch; **release-1.2.3 and api@2.0.0** tag conventions; a **UTF-8 BOM**, which
sits in front of the first character so anything anchored to the start of a file
stops matching; links climbing **four directories** out of a deep tree; and a
**Maven pom.xml** cross-checked against a CHANGELOG.

That second set earned its place immediately. The tag scenario found that the
default `release_tag` pattern recognised only `v1.2.3` and `1.2.3`, so a project
tagging `release-1.2.3` had a rule examining zero candidates forever while every
run looked healthy. Tag shape is measured from the repository now.

Run it against a `git archive HEAD` extract rather than the working tree, so
what is tested is what would actually ship.

It found that the installed slash command named the source project, and that a
file path was being reported as a phantom branch.

A third set covers what setup PRODUCES rather than what it reads. Every preset
is installed onto a repository shaped like the ecosystem it claims to serve -
a `Chart.yaml` for `k8s`, a `go.mod` and a `Dockerfile` for `go`, an
`ios/App.xcodeproj` and a `build.gradle` for `mobile` - and each is required to
name a document that exists, to examine a nonzero denominator, and to report a
planted fault. A preset naming documents a project does not have installs a
configuration that examines nothing forever while every run exits 0, which is
this project's own core failure mode aimed at its own defaults. The fixtures
are checked against `install.PRESETS` in both directions, so a new preset
without a fixture fails rather than passing unnoticed.

That set found a defect in itself before it found one anywhere else. The
consistency assertion read `"inconsistent-artifact" in stdout`, which is true
on every run: the denominator line names every rule, and so does the NOTE
listing rules that matched nothing. Deleting the preset's entire consistency
block left the scenario green. Findings are now matched as `line N: [kind]`,
and the same mutation turns ten assertions red. An assertion that reads the
denominator and calls it a finding is the most comfortable way to pin nothing.

The cross-platform scenario checks the agent instructions setup writes for
tools other than Claude Code: the file lands at the Agent Skills standard path,
its frontmatter parses as a non-Claude tool would read it, it is rendered
rather than copied, and both agent files name the same document.

A fourth set covers generated sites and the whole-repository sweep. The
generator matrix asserts both directions of every detection rule - a route is a
dead file with no generator and is not judged with one, a config under `docs/`
counts where a root-only search missed jekyll's, a `mix.exs` naming `ex_doc` is
a generator and one without it is not - and then the namespace split, which is
the one pair where being right for MkDocs means being wrong for MyST. Whatever
the namespace, an anchor defined nowhere is still reported: a project-wide
union that forgives everything is the same failure as a baseline that does.

The sweep scenario earned its place by catching itself. Its first draft ran
before `install` had copied the payload, so the tool printed "can't open file"
and the assertion that no markdown rules had invented findings on an `.rst`
file PASSED off the back of that error. Every check in that block is a negative
or a substring test, and all of them are true of a crash. It now proves the run
happened before believing anything it did not say.

That scenario also corrected a belief rather than a bug: deleting `.extant.toml`
does NOT make a repository unconfigured, because the defaults still name
`NEXT_SESSION.md`. The "nothing is configured" hint belongs to a repository
where no vetted document is present at all, which is asserted separately. Its
file-count assertion is derived from `git ls-tree` rather than written as a
literal, since `install` adds markdown of its own and a hand-counted four was
wrong the moment the payload arrived.

It later went red for a better reason: after the trunk guard became opt-in, the
hooks scenario still asserted that a default install wires a `pre-commit` hook.
The product was right and the assertion was for the retired contract. The fix
was not to pass the new flag and move on - that would have left the DEFAULT
untested, which is the half that matters, since a documentation checker
silently regaining the power to refuse a commit is the worse failure. Both
directions are now asserted: the default install must be incapable of blocking,
and `--with-trunk-guard` must actually block. A scenario that has to be edited
after a deliberate change is doing its job; one that does not, is not watching.

## `smoke.py` - what happens when someone abuses it?

```sh
python tests/harnesses/smoke.py <extracted-package> <scratch-dir>
```

Runs in CI, in its own job. Roughly 70 seconds.

It exits 1 on any flag not in its `EXPECTED` ledger, and equally on an
`EXPECTED` flag that STOPS appearing. The second half is the one worth having:
a probe that quietly stops exercising anything prints exactly what a healthy
one prints, so without that check the ledger would decay into a list of things
nobody verifies.

Until 0.12.3 it returned 0 unconditionally, so putting it in CI first meant
giving it a verdict - a job that cannot fail is a job that reports nothing.
Both directions were then confirmed by mutation: planting an `ls-remote` call
made a new flag appear and the run exit 1, and naming a nonexistent probe in
`EXPECTED` made the missing-flag branch fire.

`EXPECTED` holds four entries, every one a design decision documented in
`references/design.md`. It is deliberately not a record of whatever happened to
be failing when CI was wired up. One flag from that first run was a SECURITY
hit on the word "clone" appearing inside a prose comment, against a tool that
opens no sockets; the probe was substring-scanning its own documentation. That
was fixed in the probe rather than listed here, because a ledger entry would
have preserved the bug behind the word "expected" forever.

Adversarial probes rather than confirmation: a repository with no commits, a
detached HEAD, a document that is not valid UTF-8, a 4000-line document, a
catastrophically backtracking user regex, claims inside code fences, wrong-case
paths, symlinks and `../` traversal, an option-shaped branch token, and three
ways of gaming the validator.

Each probe reports what happened, so a loophole appears as a finding rather than
as an absence of noise. It found seven; five were fixed and the rest are
recorded in `references/design.md` as known limits, alongside two more that
later probes turned up. Flagged is not the same as unknown - each points at a
paragraph in `design.md`, and one appearing that does not would mean something
genuinely new.

The baseline gets the most attention here, because it is the only feature that
reports LESS on purpose, and every question worth asking about it is whether
that amnesty can quietly grow to cover everything. Whether suppression works is
the easy half and is already a unit test. These probe the other half: a
credential is recorded truncated rather than in full, so the baseline cannot
become a committed secret store; a corrupt, missing or empty baseline exits
loudly rather than turning a failing document green; and two consequences that
are flagged as by-design rather than fixed - a baseline can suppress a live
credential, and one recorded finding forgives every future copy of itself,
because the fingerprint deliberately excludes the line number.

The other newer surfaces get a probe each. SARIF stdout must stay parseable
JSON with hostile content in the findings, since a stray diagnostic surfaces
days later as a failed CI upload. A document must not be able to forge a
GitHub workflow command. And nothing may touch the network: this runs in a
post-commit hook, so a rule that resolved a pin by asking a remote would hang
behind a proxy and fail on a plane, and `dead-pinned-ref` is exactly the rule
that would be tempting to write that way.

That injection probe is worth reading as a cautionary tale. Its first version
put `%0A` in a markdown link and called that a newline - but that is already
the escaped spelling, so it passed through unchanged and passed just as
happily with the escaper deleted. A markdown link cannot carry a raw newline
at all, so the payload was unreachable by construction. It now asserts that
the escaper demonstrably RAN, by requiring a literal `%` to come out as `%25`.
Every new probe here was checked by breaking the product and confirming the
probe went red; two did not, and both were repaired.

The sweep probes go at the mode's own version of the project's core failure: a
repository with no markdown, where "0 findings" and "0 files examined" both
exit 0; a tracked file that is not valid UTF-8, which must be counted and named
rather than skipped; both directions of the vetted/unvetted gate; SARIF purity
across several documents at once; and a DIRECTORY named `mkdocs.yml`, which
must not be enough to switch route checking off.

All five were confirmed by mutating the product, and getting there took two
corrections worth recording. Four of them first appeared to detect their
mutation while actually crashing: the scratchpad path was long enough that
`<arena>/sweep-empty/tools/extant_collect.py` approached MAX_PATH and git
failed intermittently inside `tracked_markdown`, so the probes went red for a
reason that had nothing to do with what they test. Run that verification under
a SHORT path. The fifth then stayed genuinely green, because it linked to
`docs/gone.md` - a plain file reference, which no generator setting has ever
controlled. Site mode suppresses ROUTES, so the probe had been aimed slightly
beside its target and passed against the very bug it was written to catch.

## `fuzz.py` - what about the cases nobody thought of?

```sh
python tests/harnesses/fuzz.py <extracted-package> <scratch-dir> [--seed N] [--repos N]
```

Every other harness here checks a case somebody wrote down. This one generates
them: hostile repositories combining awkward Unicode paths, symlinks,
submodules, odd ref and tag names, undecodable documents, backtracking-bait
config, unclosed fences, and the git states a checkout can be in - attached,
detached, a linked worktree, a shallow copy, and no commits at all.

**It has no oracle, so it checks properties instead.** A generated repository
has no known right answer, but these hold whatever the answer is: no traceback,
an answer inside the budget, a documented exit code, findings never exceeding
the denominator for their rule, two runs of an unchanged repository printing
the same thing, and SARIF parsing and agreeing with the text output on the
count. The last two are metamorphic - extant compared against ITSELF under a
change that must not matter - and they are what let a fuzzer find wrong answers
rather than only crashes.

**The generator is a catalogue, not a list of strings.** The shapes live in
`tests/harnesses/fuzz_shapes.py`, one feature per rule, each offering a claim
that is TRUE and one that is FALSE. It was twelve hard-coded content strings,
and measuring them against the rules is what forced this rewrite: five of the
twelve reached a rule at all, the corpus exercised 5 of the 13 rules, and two
strings were dead in the way this project keeps warning about. One wrote
`Merged` followed by the branch where `merge_claim` needs `merged` then `to` or
`into`, so `false-merge-claim` had never fired here. The other wrote a release
sentence in the spelling `release_tag` does not read - the same distinction
that left ten status entries unread for six releases. Both had matched nothing
since the day the harness was written, and nothing could say so, because a
shape that stops firing is invisible when shapes are strings.

**True claims are half of it.** Every document the old generator wrote was
already wrong, which cost more than coverage of the clean path: `--selftest`
was a no-op across the entire corpus, reporting `0 fired, 13 had nothing to
corrupt`, because a probe corrupts an ACTUAL match and there were none to
corrupt. A feature therefore offers both spellings and the draw picks `true`,
`false` or `both`.

**Features are drawn swarm-style.** Each repository omits a random subset of
features outright rather than drawing every feature independently at a tuned
probability - Groce et al.'s feature-omission diversity. Both mechanisms that
technique addresses were present here: features competed for space, because one
content shape was chosen per document so no repository could hold a merge claim
and an LFS blob at once, and features suppressed one another, because an
unparseable config silences everything downstream. The hand-tuned weighting
that used to compensate is gone.

**The reach ledger is this harness's own denominator.** It records which rules
actually EXAMINED something across the corpus and fails below a floor. The old
count - how many repositories produced rule counts of any kind - was the same
number for a repository exercising one rule and one exercising twelve, which is
how 8 of 13 rules went unreached with nothing saying so. It separates a rule no
feature aims at from one a feature aims at and misses, because those are
different failures with different fixes.

**Coverage is walked, not drawn.** The five git states times the seven modes
are thirty-five pairs, and the harness covers each once before spending any
remaining budget at random. That is not tidiness. The first genuine finding
here was an empty SARIF document from a repository with no tracked markdown,
and while selection was random the fixed CI seed never drew that state together
with that format - so re-running it against the unfixed code reported zero
violations. A gate that cannot reach the bug it already found is not evidence.
The pair count is printed for the same reason every other number here is.

**"Could not build" is its own column.** Symlinks need a privilege Windows
withholds and submodules need a transport some sandboxes refuse. When a shape
will not construct, the case was NOT TESTED and the harness says so rather than
counting it as a pass. The CI job runs on Linux, where both build, so that job
is the only place that coverage is actually held.

**A refusal is not a fault.** A run that declines to start - an unreadable
config, or one excluding the document it is told to gate on - produces no
result, and emitting a report there would assert a scan that never happened.
Those are counted and printed separately rather than exempted quietly.

**Findings do not stay here.** Each is reduced to a case in
`tests/test_fuzz_findings.py`, which the suite runs on every commit rather than
waiting for a seed to come up again. This harness discovers; that file
remembers, and it is meant to grow.

What it found on its first run: a sweep of a repository git tracked no markdown
in emitted zero bytes of SARIF and exited 0. Empty stdout also describes a tool
that crashed or an upload pointed at the wrong path, and GitHub rejects an
empty SARIF file, so a project whose glob matched nothing got a failed upload
instead of a report reading zero. Six other reports that run produced were the
harness being wrong, each one sharpening a property: exit 2 is a documented
code, a path may contain spaces, a finding in the primary document prints
without its path, and a refusal is not a result.

## `corpus.py` - what does it say about somebody else's repository?

```sh
python tests/harnesses/corpus.py <dir-of-clones> [--baseline FILE] [--update]
```

Every false-positive class this project has fixed came from running against a
real repository that nobody here wrote. Thirty-eight of them, across sixteen
ecosystems, took the corpus from 727 findings to roughly 600 while the true
positives stayed.

It exists because the throwaway shell loops that did that work were wrong three
times in one session, each time by omitting something silently: three
repositories skipped because Git Bash paths are not Windows paths, two clones
that failed on MAX_PATH and reported no documentation, and one whose checkout
never completed and read as clean.

### The column that says whether a corpus can gate anything

`files swept` says the run happened. **`found / examined` per rule** says which
rules it reached, and that is the number that decides whether a corpus can
gate a change to one:

```
  found/examined per rule:
    dead-sha                    284 / 1365  (incl. bare)
    dead-md-link                 75 / 1003
    dead-path-pointer            33 / 81
    false-merge-claim             0 / 0
  CANNOT GATE A CHANGE to these - nothing here exercises them: ...
```

A widening measured where the rule never fires reports no new false positives
from a denominator of zero, and that is indistinguishable from a widening that
is safe. Eight were surveyed against 30 repositories and half of them aimed at
rules examined three times or fewer across all 3,821 files - `false-merge-claim`
and `raw-lfs-blob` never at all, `dead-release-tag` twice, `dead-pinned-ref`
three times. Without this column the survey would have called them harmless.

`bare-dead-sha` is folded into `dead-sha` because `count_examined` counts both
kinds of SHA candidate against one denominator. Reporting 277 findings against
zero examined, or dropping them, would misreport the busiest rule in the
corpus.

### What `--baseline` compares, and why a total is not enough

It recorded one findings count per repository. Three kinds of regression slip
straight through that, and all three occurred while this was being written:

| recorded | catches |
|---|---|
| `by_rule` | findings moving BETWEEN rules. A narrowing removed 19 `dead-release-tag` while other work added elsewhere; a total nets those off |
| `digest` | a verdict changing IN PLACE. One release claim went from "no such tag exists" to "on no integration branch" - a different question about the same line - with identical counts either side |
| `examined` | COVERAGE. Making a merge claim's commit optional took a rule from 3 candidates examined to 35 and added no finding at all. A findings diff calls that "no change", which is the opposite of what happened |

Each was verified by corrupting a recorded baseline in exactly one of those
three ways, leaving the total untouched, and watching the run report it while
the summary line still said `0 changed`. That summary being wrong is the point:
it is what the harness said before, about all three.

A baseline written before this detail existed still compares - by total only -
and the run SAYS SO rather than quietly checking less. `--update` deepens it.

### What was measured, and how to clone it

Recorded as a RECORD of one measurement rather than as a fixed gate, and the
distinction matters. Committing a corpus makes the numbers auditable; treating
the same corpus as the bar to clear one release later makes it a training set,
and this project's own rule is that a measurement over a sample chosen by the
thing being measured is not a measurement. Anyone repeating this work should
add repositories, not re-run these.

Three sets of ten, measured 2026-08-02 at 3,821 markdown files:

| set | chosen for | repositories |
|---|---|---|
| original | the set the current rules were narrowed against | `spf13/cobra` `expressjs/express` `pallets/flask` `helm/helm` `encode/httpx` `python-poetry/poetry` `pytest-dev/pytest` `psf/requests` `rust-lang/rfcs` `vitejs/vite` |
| held out | doc toolchains absent from the original | `docsifyjs/docsify` `tidyverse/dplyr` `laravel/framework` `ktorio/ktor` `shuding/nextra` `rails/rails` `slatedocs/slate` `symfony/symfony` `hashicorp/terraform` `ziglang/zig` |
| claims | density of git-checkable claims | `Aider-AI/aider` `psf/black` `simonw/datasette` `humanlayer/humanlayer` `pre-commit/pre-commit` `astral-sh/ruff` `github/spec-kit` `simonw/sqlite-utils` `obra/superpowers` `astral-sh/uv` |

The third set exists because the second could not gate anything: of its 951
findings, 943 were link or anchor, and four rules fired zero times between
them. A widening measured where the rule never runs reports no new false
positives from a denominator of zero.

**A fourth set exists because the third did not fix that, and the mistake is
the instructive part.** "Claim density" was chosen by picking popular Python
and JavaScript tools, which are dense in CHANGELOGS rather than in status
claims, so `false-merge-claim` still examined nothing across all thirty
repositories - and that got written up as "no public corpus can gate these
rules". It was a statement about the sample.

Scanning 229 repositories from the `agent-handoff`, `session-handoff` and
`claude-code` topics - 52,417 documentation files - finds the shipped merge
pattern 35 times, the release pattern 97, the branch token 640 and the live
phrase 117, with **61 repositories exercising at least one**. Fifteen of them
are the fourth set: `10CG/Aria`, `neomjs/neo`, `basilisk-labs/agentplane`,
`mickeyyaya/evolve-loop`, `Pseudogiant-xr/Pseudolife-MCP`,
`openbkn-ai/bkn-foundry`, `fr1j0/bitacora`, `dfrostar/neuralmind`,
`d-o-hub/rust-self-learning-memory`, `gmickel/flow-next`, `nikzlabs/shipit`,
`ramboz/jig`, `bejranonda/ExternalBrain`, `oomkapwn/enquire-mcp`,
`eugenelim/agent-ready-repo`.

Measuring against them found a coverage hole none of the eight planned
widenings had named, and this rule's first true positive on somebody else's
repository. **Pick a corpus by the KIND OF DOCUMENT a rule reads, not by how
much documentation a project has.**

Clone them like this, because both flags are load-bearing:

```sh
git clone --filter=blob:none https://github.com/<owner>/<repo> <dir>
git -C <dir> config diff.renames false
```

Without the first, the clones are about 20 GB. Without the second, every sweep
fetches blobs from GitHub on demand to run rename detection, and one repository
stalled for over half an hour with `git fetch` running underneath it; the same
sweep takes 5.4 seconds with renames off, and the setting moves no counts
because the rename lookup only appends a clause to a finding's detail.

Do NOT clone `--depth 1`. A shallow clone leaves every historical SHA
unresolvable, so the SHA rules fire on nearly everything: one repository
reported 2,094 findings that way and reports 3 with its history. It is the
worst kind of wrong result, because it looks like a thorough tool.

So a repository that cannot be measured is a FAILURE here, never an omission.
Preconditions are asserted before anything is counted - is it a directory, a
git repository, does HEAD resolve, is HEAD's tree non-empty - and a corpus with
one unusable member exits non-zero however healthy the rest looks. A run that
produces no denominator is refused rather than recorded.

`--baseline` compares per-repository counts and prints the delta, which is how
a fix is shown to have moved what it claimed and nothing else. A repository
that was in the baseline and is missing now fails the run, because dropping out
of the corpus is how a regression hides.

No baseline file is committed. Those counts describe repositories this project
does not control, so a recorded one would be stale within a week - precisely
the kind of claim this tool exists to catch.

Then it made the same mistake it was built to prevent. Findings were counted by
matching `": line "`, which is the PREFIXED shape a sweep uses outside the
primary document, so every finding in the VETTED document counted as zero -
blind to exactly the half that gates. Measured on a one-document repository:
the sweep reported one finding and the harness reported none.

Each run now also reports what would explain a count moving: the generator each
repository declares and the namespace it implies, the split between `.md` and
`.rst`, and the totals per rule. Across 41 repositories 91 percent of findings
were link or anchor and 8 percent git-history, and on agent-written plan
documents that ratio inverts almost exactly - a total alone cannot show which
of those a corpus is made of, and the mix is what says whether a change to one
rule will move anything.

## `perf.py` - is it fast enough to leave installed?

```sh
python tests/harnesses/perf.py <extracted-package> <scratch-dir>
```

Asked in descending order of importance: what the hooks add to every commit,
whether validation scales with document size, whether it scales with
repository size, which rule spends the time, what a baseline costs on every
run, what each output format costs, what `--sweep` costs, and what one
generator config file costs a single `--validate`.

The last of those is the reason to re-run this after a change to what the code
READS rather than only to what it does, and it is the one measurement here that
has already paid for itself.

### The fixtures are claim-SPARSE, and it shows up as a shrug

Batching every branch, tag and ref lookup into one `for-each-ref` took a
validate of this project's own status document from **8 git subprocesses to 6**
and from **261 ms to 214**. The same change moves this harness by 1.5% on the
per-rule total and by an amount indistinguishable from noise on the hook
overhead, which varies about a quarter between runs.

Both numbers are honest. They measure different documents. The documents here
carry links and prose; `NEXT_SESSION.md` carries 24 commit references, merge
claims and branch tokens, which is what makes it touch every ref lookup in the
tool. A per-rule percentage is a statement about the fixture.

That is the third time this has happened - section 8 exists because the anchor
union was invisible for a week, section 10 because a rule cost 11.6 seconds
while reporting 2.6% of a run it never exercised. The structural claim is the
one worth pinning, and `test_caching.py` pins it: four questions about refs,
one scan. A spawn count does not vary by a quarter between runs.

`validate_md_anchors` asks whether the repository declares a project-wide
namespace, and on a hit unions in every anchor from every tracked markdown
file. That is correct - MyST and Sphinx resolve labels project-wide, and 168 of
mystmd's findings named labels that existed - but it used to be built EAGERLY,
before a single link was examined, for documents that may contain no anchor
links at all. The trigger is one file existing, and that file is `conf.py` for
Sphinx, so this was the ordinary shape across a large slice of Python projects
and it was paid on every post-commit hook run.

It was invisible here for a week, because every repository this harness builds
is generator-free and so every other number on the page is the cheap path.
Measuring it is what got it fixed. The union is built on demand now, and the
section reports three columns rather than two:

| | 100 files | 400 files | 1600 files |
|---|---|---|---|
| local fragment | within noise of zero | within noise of zero | within noise of zero |
| cross-file fragment | +50 to +60 ms | +125 to +190 ms | +390 to +500 ms |

The document is held identical and only the config is added, so the delta is
the union and nothing else. The first row is what most documents do, and it is
now free. The second is unchanged, which is the point: laziness did not make
the union cheaper, it made it conditional on a fragment that could not be
resolved locally - the only case where the answer can change a finding.

Reporting only the first row would have replaced one misleading number with
another, which is why the cost that remains is measured beside it.

RANGES, and the ranges are the honest form. This page carried `+406 ms` in one
place and `+495 ms` in another for the same measurement, which a reviewer
caught - and re-measuring to settle it produced 390 ms, which would have made
three. The union reads every tracked file, so it is bound by I/O and varies by
about a quarter between runs on the same machine. A single figure to the
milliseconds implies a precision this measurement does not have, and pinning
one would have been prose rot with a decimal point. The local row is stated the
same way for the same reason: it measures between -13 ms and +5 ms, which is to
say it measures nothing.

The baseline measurement matters more than its size suggests. A baseline is
adopted by big neglected repositories, which are precisely the ones where a
slow hook gets uninstalled, so the cost would land where it is least
affordable. Measured at 1000 findings it is under the noise floor.

The per-rule table also names the rules the probe document never exercised. A
rule with nothing to examine is timed as free, which is true and misleading:
its cost is unmeasured, not zero, and a table that omitted the distinction
would read as full coverage of the rule set.

It found that one rule was 98 percent of total validation time - two git
subprocesses per merge claim, where the reference rule had batched the same
work all along. Fixing that took a 4000-line document from 16.7s to 0.77s.

Measured on Windows, where process spawning is expensive. The remaining hook
cost is mostly interpreter startup and shell spawns rather than the tool's own
work, so numbers on Linux are likely lower - **unverified**, since these were
not measured there.

Measured 2026-07-29: a sweep of 1600 files takes about 1 second, down from 49.
Both halves of that came from profiling this harness's own repositories rather
than from reading the code, and neither was where reading would have looked.

The first was `_own_remote`, which answers a question about the repository and
was being asked once per document - 70 percent of a 400-file run, spent
spawning `git remote get-url` for a string that cannot change. The second was
`validate()` rebuilding its per-call caches for every document in the sweep,
which turned 20 distinct questions about the filesystem into 128,000 Path
objects.

`--verify` was measured for the same scope and deliberately left alone: 5 ms
saved out of 337, which does not justify relaxing a correctness promise on the
path that gates commits. Measuring a candidate and declining it is a result.

`stress.py` measures the anchor union at +29 seconds for 3000 files against
this section's few hundred milliseconds for 1600, which looks like a
contradiction and is not.
That is one COLD run over files written moments earlier; this takes the median
of three, so its later runs read a warm cache. Both are real. The cold number
is the one shaped like a post-commit hook, which happens once and pays whatever
the cache does not.

That case also barely moved while the rest of the sweep got four times faster,
which is the expected shape: the union reads every tracked file, so it is bound
by cold I/O rather than by the per-document work that was hoisted out.

### What this harness could not see, and how that surfaced

Section 4 reported `dead-release-tag` at 8 ms, 2.6% of a run. That is true of
the document this harness builds and says nothing about the rule, because every
document it builds carries almost no release claim. A document with 200 of them
took **11.6 seconds**, and the cause was `_integration_refs` spawning a
`for-each-ref` per claim - memoised for the call, the same document takes
**1.2 seconds**.

Section 10 exists so that is visible without anyone going looking, and its
`ms/claim` column is the whole point. A git call inside a per-claim loop holds
it flat while the count grows; hoisting the call out makes it fall:

| claims | shipped in 0.15.0 | with the call hoisted |
|---|---|---|
| 25 | 2.3s, 94 ms/claim | 1.1s, 44 ms/claim |
| 100 | 6.4s, 64 ms/claim | 1.2s, 12 ms/claim |
| 400 | 22.0s, 55 ms/claim | 1.25s, 3 ms/claim |

The right-hand column flattens in TOTAL and falls per claim; the left grows
x3.45 for x4 claims, which is a per-claim cost stated in the only column that
can show one. A total alone reads as a big number and cannot say which.

Two things are worth carrying away. The first is that the 11.6 seconds was in
the SHIPPED tool, measured against `origin/main` on the same fixture at 11.6
seconds: it was found while checking whether a new call site had made things
worse, and the honest answer was that the new call cost nothing measurable
while the existing one cost 9x. Asking the question is what found it.

The second is the harness's own limit, which its opening docstring already
names: a harness measures the inputs it knows how to build. Section 8 exists
because the anchor union was invisible for a week for exactly this reason, and
this is the same hole in a different rule. A per-rule percentage is a statement
about the fixture, not about the rule, and the fixtures here are documents with
links rather than documents with claims.

## `stress.py` - where does it fall over?

```sh
python tests/harnesses/stress.py <extracted-package> <scratch-dir>
```

Aimed at the WEAK points on purpose, not at comfortable ones. The merge-claim
rule is fast because it asks git once per distinct commit, so the case that
matters is a document naming a different commit every time, where that
deduplication buys nothing. The case-sensitivity check lists a directory per
path component and caches nothing, so the case that matters is thousands of
links in a deep tree. A load test that avoids a tool's known weak spots is
measuring the wrong thing.

The cases: 2000 distinct merge claims, a 100,000-line document, 5000 commits
with 500 branches and 200 tags, 3000 links across a deep tree, a 500-entry
archive, 50 extra documents, a 1 MB single line, peak memory, 40 back-to-back
runs, `--search` over a 2000-entry archive, a 200-file consistency check, 500
renamed references in one document, a 5000-entry baseline, SARIF and GitHub
output for 5000 findings, 500 install snippets pinning this repository, a
3000-file sweep, a small document in a 3000-file tree with a `conf.py`, 2000
anchor links into 2000 distinct files, and 2000 reStructuredText files.

The newest four follow the same rule as the rest, which is to aim where an
optimisation stops helping. `_target_anchors` memoises per PATH, so a document
linking repeatedly into one file costs a single read and proves nothing; two
thousand links into two thousand DIFFERENT files get nothing from that cache.
That is the same shape as the distinct-SHA case, and it is why that one is
here.

The sweep and rst cases each carry a correctness assertion beside the timing,
because both are modes where being fast and being blind look identical. The
sweep case asserts its denominator names every file and that a planted fault
still gates; the rst case plants a markdown link inside an rst literal in all
2000 files, so a rule that strayed out of its own markup language reports two
thousand findings rather than none.

The last three follow the same principle as the rest, aimed at the newer
surfaces. A baseline is read on every run including the hook, so the scale
that matters is the one it exists for; the case also plants one NEW claim
among 5000 forgiven ones, because a ratchet that loses the new finding at
scale is worse than no ratchet, the project having been told it is covered.
SARIF's size is a real limit rather than a curiosity, since GitHub rejects an
upload over 10 MB and the failure arrives long after the run that caused it.
And `dead-pinned-ref` is the one rule that reads INSIDE code fences, so a page
dense with install snippets is its worst case and nothing else here touches
it.

This section said "Nine cases" for as long as it took three of them to be
written, and then "Twelve" while three more were added, which is the same
drift the tool exists to catch and cannot: no rule here inspects a number. The
count in the output is derived from the case list. This sentence is prose, and
prose is what rots - so the literal is gone rather than corrected.

Peak memory is reported alongside time. A tool that is fast because it holds the
whole document and every intermediate list at once has moved the problem rather
than solved it.

Each measurement carries a budget, so "slow" is a stated expectation being
missed rather than a number someone has to judge by eye.

## The hardening pass, and what each harness had to grow

Four loopholes were closed and every harness needed a new fixture to see any of
it, which is the recurring lesson here: a harness measures the inputs it knows
how to build, so a change to what the code READS is invisible until its
fixtures grow.

`perf.py` gained a ninth section timing `--deleted-since` beside a plain
`--verify`, because that mode re-validates the previous version of each CHANGED
document and its cost tracks the commit rather than the repository.

`stress.py` gained a 2000-entry archive with one claim removed from the live
document. Two things are asserted beside the timing: the removal is still found
at that size, and the unchanged archive is NOT re-read - a mode that scanned
every document would be scanning a repository rather than a commit.

`smoke.py` gained probes for the new mode's error paths, and one of them found
a real defect on its first run. A previous version that is not valid UTF-8 was
decoded inside a subprocess READER THREAD, so the traceback printed while the
process carried on and reported "examined 0". A crash and a silent zero at the
same time. Reading bytes and decoding in-place fixed it, and the skip is now
counted and named.

`smoke.py` also lost two EXPECTED entries, and the second departure is the
instructive one. "A check can list the same file under two spellings" was
listed as by-design, and its probe called `note()` UNCONDITIONALLY in an else
branch - it checked only that the tool had not crashed, then declared the
loophole open whether or not it was. It reported identically before and after
the loophole was closed. That is this harness committing the exact defect it
exists to detect, and no amount of running it would have surfaced that; only
reading it did.

## Reading the output

All of them print a denominator: how many mutations, scenarios, probes, cases or
measurements ran. A run that examined nothing prints the same reassuring nothing
as a run that found nothing wrong, which is the failure this whole project
exists to make visible. If a count looks low, the harness is broken, not the
code.

This file said "Three tools" for two commits after the fourth and fifth were
added, and nothing noticed - the count is prose, and no rule here inspects
numbers. That is the documented limit of the validator working exactly as
designed, on its own repository, which is as good a demonstration of it as any.

## The harness needs the same scepticism as the code

A measurement campaign across four corpora produced a defect in its own
apparatus every single time, and not one was visible in the output:

- A form counter swept `toml|yaml|json` into a form meant for CODE, so
  `pyproject.toml:some_key` was counted as a symbol citation. It inflated the
  exact number a rule would have been designed around. Caught only because the
  same quantity had been measured twice by different means.
- A route harvest searched with `git grep`, which reads the whole tree
  including the document the claim came from. Every documented endpoint matched
  itself, so 347 examined and 0 findings was guaranteed rather than earned.
- A flag harvest counted `--dashboard--` and `--header--`, which are markdown
  table separators, and `--prettier-ignore-start`, which is an HTML comment.
- A corpus check run mid-clone reported five repositories as holding zero
  documents, including one that holds 149. The clone was incomplete; the
  repositories were not empty.

Two habits are worth more than any of the individual fixes. **Measure a
quantity twice by different means whenever it is going to justify building
something** - agreement is cheap and disagreement is where the defect is. And
**print what was examined, not just what was found**, which is the same rule
the harnesses already impose on the code.
