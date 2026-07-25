# Harnesses

Three tools that audit the test suite and the installed product, rather than
the code paths a unit test can reach. They are **not** run by pytest: each takes
minutes, and each answers a question `python -m pytest` structurally cannot.

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

## `scenarios.py` - does it work on projects unlike this one?

```sh
python tests/harnesses/scenarios.py <extracted-package> <scratch-dir>
```

Builds a fresh repository per scenario, installs the tool, and asserts what
should happen: a Node project on `master`, ticket-prefixed branches on
`develop`, release tags, a repo with no handoff document at all, CRLF files
nested in `docs/`, a linked worktree, an archive round-trip, the git hooks
firing, and a single-commit repository.

Run it against a `git archive HEAD` extract rather than the working tree, so
what is tested is what would actually ship.

It found that the installed slash command named the source project, and that a
file path was being reported as a phantom branch.

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
as an absence of noise. It found seven; five were fixed and two are recorded in
`references/design.md` as known limits.

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

## Reading the output

All three print a denominator: how many mutations, scenarios, or probes ran.
A run that examined nothing prints the same reassuring nothing as a run that
found nothing wrong, which is the failure this whole project exists to make
visible. If a count looks low, the harness is broken, not the code.
