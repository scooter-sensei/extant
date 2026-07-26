# Harnesses

Five tools that audit the test suite and the installed product, rather than the
code paths a unit test can reach. They are **not** run by pytest: each takes
minutes, and each answers a question `python -m pytest` structurally cannot.

| Tool | Asks |
|---|---|
| `mutate.py` | does the suite pin anything? |
| `scenarios.py` | does it work on projects unlike this one? |
| `smoke.py` | what happens when someone abuses it? |
| `perf.py` | is it fast enough to leave installed? |
| `stress.py` | where does it fall over? |

Between them they found every defect fixed in 0.3.0. The unit suite found none
of those, because the unit suite was the thing being audited.

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

**Mutations rot alongside the code they point at.** A later run reported
`merge-claim never fires (matched 0x)` after ancestry moved from a per-claim
merge-base call to a batched rev-list: the line it named no longer existed, so
that behaviour had quietly stopped being probed. It surfaced only because a
mismatch is a HARNESS FAULT here rather than a silent skip. Re-run this after
any change to the code it targets, and repair what it reports.

## `scenarios.py` - does it work on projects unlike this one?

```sh
python tests/harnesses/scenarios.py <extracted-package> <scratch-dir>
```

Builds a fresh repository per scenario, installs the tool, and asserts what
should happen: a Node project on `master`, ticket-prefixed branches on
`develop`, release tags, a repo with no status document at all, CRLF files
nested in `docs/`, a linked worktree, an archive round-trip, the git hooks
firing, and a single-commit repository.

Run it against a `git archive HEAD` extract rather than the working tree, so
what is tested is what would actually ship.

It found that the installed slash command named the source project, and that a
file path was being reported as a phantom branch.

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

Adversarial probes rather than confirmation: a repository with no commits, a
detached HEAD, a document that is not valid UTF-8, a 4000-line document, a
catastrophically backtracking user regex, claims inside code fences, wrong-case
paths, symlinks and `../` traversal, an option-shaped branch token, and three
ways of gaming the validator.

Each probe reports what happened, so a loophole appears as a finding rather than
as an absence of noise. It found seven; five were fixed and the rest are
recorded in `references/design.md` as known limits, alongside two more that
later probes turned up. A clean run today is 18 probes, 23 observations, three
of them flagged: the regex hang, deletion-as-repair, and a consistency check
that names one file twice. Flagged is not the same as unknown - each of the
three points at a paragraph in `design.md`, and a fourth appearing would mean
something genuinely new.

## `perf.py` - is it fast enough to leave installed?

```sh
python tests/harnesses/perf.py <extracted-package> <scratch-dir>
```

Four questions in descending order of importance: what the hooks add to every
commit, whether validation scales with document size, whether it scales with
repository size, and which rule spends the time.

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

Twelve cases: 2000 distinct merge claims, a 100,000-line document, 5000 commits
with 500 branches and 200 tags, 3000 links across a deep tree, a 500-entry
archive, 50 extra documents, a 1 MB single line, peak memory, 40 back-to-back
runs, `--search` over a 2000-entry archive, a 200-file consistency check, and
500 renamed references in one document.

This section said "Nine cases" for as long as it took the last three to be
written, which is the same drift the tool exists to catch and cannot: no rule
here inspects a number. The count in the output is derived from the case list;
this sentence is prose, and prose is what rots.

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
