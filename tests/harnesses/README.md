# Harnesses

Five tools that audit the test suite and the installed product, rather than the
code paths a unit test can reach. They are **not** run by pytest: each takes
minutes, and each answers a question `python -m pytest` structurally cannot.

| Tool | Asks | In CI |
|---|---|---|
| `mutate.py` | does the suite pin anything? | `--check-only` |
| `scenarios.py` | does it work on projects unlike this one? | yes |
| `smoke.py` | what happens when someone abuses it? | yes |
| `corpus.py` | what does it say about somebody else's repository? | no, needs clones |
| `perf.py` | is it fast enough to leave installed? | no, by design |
| `stress.py` | where does it fall over? | no, by design |

The last column is a real distinction, not a backlog. A harness belongs in CI
when its result is a VERDICT: `scenarios.py` and `smoke.py` each answer a
yes-or-no question about behaviour, so a change of answer is a regression and
the job can fail on it. `perf.py` and `stress.py` answer with NUMBERS, and a
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

## `perf.py` - is it fast enough to leave installed?

```sh
python tests/harnesses/perf.py <extracted-package> <scratch-dir>
```

Asked in descending order of importance: what the hooks add to every commit,
whether validation scales with document size, whether it scales with
repository size, which rule spends the time, what a baseline costs on every
run, and what each output format costs.

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
output for 5000 findings, and 500 install snippets pinning this repository.

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
