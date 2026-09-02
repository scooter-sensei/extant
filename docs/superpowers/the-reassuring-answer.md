# The reassuring answer

One defect accounts for most of what has gone wrong in this project's checking
machinery. It has a single shape:

> **A check that cannot reach its subject returns the value that means
> "all clear".**

Not a crash. Not a wrong number. A confident, well-formatted, entirely normal
report of health, produced by something that never looked.

This document exists because knowing about the pattern does not stop anyone
writing it. Every remedy at the end is structural for that reason.

## Why it is worse than a crash

A crash is self-announcing. Somebody sees a traceback, reads the line number,
and fixes it. The cost is bounded by how long the build stays red.

The reassuring answer costs the opposite way. Nobody investigates a green run.
The check goes on being counted as coverage, the thing it was guarding goes on
being unguarded, and the gap is discovered - if ever - by the failure the check
existed to prevent. `extant` exists to remove exactly this in documentation: a
claim that reads as true because nothing checked it. The defect is the tool's
own subject, turned on the tool.

The severe version is not silence but **confident contradiction**: output that
reports a finding and, in the same breath, states that the rule which found it
examined nothing.

```text
line 8: [dead-md-anchor] links to `docs/note.md#no-such-heading` ...
  examined: ... dead-md-anchor 0, ...
  NOTE: these rules examined nothing anywhere here ...: dead-md-anchor
```

Both lines are printed by the same run about the same document. A reader
believes the second.

## The catalogue

Every entry below is a real defect in this repository, found by running
something rather than by reading it. Five are in the shipped tool; the rest are
in the harness built to find them.

### In the product

| Defect | What it printed |
|:---|:---|
| `false-merge-claim` | denominator and check walked the document separately |
| `dead-release-tag` | `examined=1` against 0 findings - "examined and clean" |
| `dead-md-anchor` | a finding against a denominator of zero, plus a note naming that rule as having examined nothing |
| `manifest-floor-mismatch` | sweep printed the finding, printed `0` examined, and named the rule among those that examined nothing anywhere |
| `raw-lfs-blob` | one violation printed twice, against a denominator counting the file once |
| six rules at once | denominators counting sites the rule REFUSES to judge - coverage reported on a run with no findings, which is the direction nobody investigates |
| a CR-only document | `^` in a multiline pattern follows a newline and a bare `CR` is not one, so two rules examined zero candidates and printed `0` beside every other rule's honest count |

All but the first two were found by the rebuilt fuzz harness. Those two were
found earlier and are recorded in `AGENTS.md`, which states the remedy for this
sub-shape: give a rule ONE function returning the sites it can decide, and have
both callers read it.

### In the harness

| Defect | The reassuring answer it gave |
|:---|:---|
| `_rule_counts` matched only the sweep's `examined:` line | the denominator check iterated nothing and passed, in every gating run |
| `build_repo` ignored every git return code | a failed `git add` produced a repository with no commits, which the sweep reports as `git tracks none in this repository` - identical to a repository that is genuinely empty |
| corpus health was a test for ZERO | a corpus 83 per cent dead exited 0 reporting 13 of 13 rules and no violations |
| `shutil.rmtree(ignore_errors=True)` | the directory survived, the rebuild died, and the failure was swallowed by the flag |
| `_still_fails` returned False when a build failed | ddmin concluded no feature could be dropped and reported the unshrunk set as minimal |
| the shrinker judged by `check` while the report also used a probe | every violation the probe found was invisible to shrinking |
| the shrinker matched the PROPERTY and not the rule | a `raw-lfs-blob` fault "shrank" to a feature that merely produces a different fault of the same shape |
| a plan naming a feature the catalogue no longer had | dropped it, built an empty repository, and printed "this plan does not reproduce one" at exit 0 - which reads as "the bug is fixed" |
| `_text(None)` returned `""` on timeout | empty output compares equal to empty output, so four metamorphic oracles passed while nothing ran at all |
| `run_mode` never passed `cwd` | one of seven modes validated the WRONG DOCUMENT for an entire session, reporting `ok` throughout |
| a patch applied with `.replace()` and no assert | the edit silently did not apply, twice |
| `generated-site` wrote a marker and no route | nothing observable changed, so the axis had no evidence to offer - and its docstring described the missing half AND pointed at an oracle nobody had written |
| `encoding` and `generated-site` could not report a contradiction | their `confirm` returned True or None and nothing else, so a ledger row that read as a verdict was an attendance record |
| two axes confirmed through another feature's draw | a document claiming `v9.9.9` and never `v1.0` returned "confirmed" from a run that never looked at an annotated tag |
| `commit_map_path` shared a function whose worktree branch only the READER took | the writer is only ever handed the origin, so "one function, two callers" gave no protection on the single path where they could disagree |
| `fingerprint` held the head repository's PATH | the base build overwrote that directory first, so the guard compared a repository with itself and could only ever answer "the same" |
| the budget instrument wrapped `run_mode` | `run_concurrently` starts its own processes, so part of the spawns was counted and reported as the total |
| a differential quoted at `0 differences` | its 30-repository corpus contained no `--sha-map` pair at all, so it could not have seen the change it was cited for |

## The four shapes it takes

**Two readers of one claim.** A numerator and a denominator that walk the same
pattern separately. They agree on the day they are written and drift after. The
first three product defects above are this, and so are two of the harness ones.

**An error path that returns the success value.** `except: return False`,
`ignore_errors=True`, `if x is None: return ""`. The handler is written while
thinking about robustness and reads as politeness; what it actually says is
"treat not knowing as knowing nothing is wrong".

**Absence that looks like emptiness.** No output, no findings, no documents, no
commits. A tool that examined nothing and a tool that examined everything and
found nothing produce the same bytes unless one of them is made to say which.
This is why every denominator in this project exists.

**A check whose subject moved.** The anchor still matches something, or matches
nothing and says so quietly. `mutate.py` exists because six mutation anchors
once pointed at code that had been replaced, and all six reported success.

**And its mirror, which is rarer and reads as diligence.** A check that cannot
reach its subject and returns the value meaning FAULT. The raising axis aimed a
claim at a rule, one noise shape blanked the entry it sat in, nothing raised,
and the ledger reported `applied, and the run contradicts it` - blaming the tool
for the harness. It is the same defect: the check could not see its subject and
answered anyway. It is easier to catch only because somebody chases a red run.

## The diagnostic question

Before trusting any check, ask it:

> **What do you return when you cannot tell?**

If the answer is the same value you return for "I looked and it was fine", the
check is decorative. There must be a third answer, and it must be reported.

Three that follow from it, in order of how often they catch something here:

1. **What does this print when it examined nothing?** If that is
   indistinguishable from a clean result, add the denominator.
2. **Do the two halves read the same population?** If a numerator and a
   denominator are computed by different code, they will disagree eventually.
   One function, both callers.
3. **Has this check been observed failing?** Not "would it fail" - watched,
   against a deliberately broken copy.

## Why vigilance does not work

This is the part worth being blunt about.

Across one session of work on the fuzz harness, this defect was written eleven
times **by someone actively hunting for it**. The harness being built was a
harness for finding exactly this pattern. `AGENTS.md` documents the pattern. The
session's own notes name it repeatedly.

One instance was written in the same message that contained the sentence
"every new oracle should be asked what it returns when it cannot tell". The
oracle written immediately afterwards returned empty output on a timeout, and
four of them passed silently while nothing ran.

The conclusion is not that more care is needed. It is that care is not the
mechanism. Every one of those eleven was caught by a check - a denominator, a
floor, a ledger, an assert - and none by review.

## What actually works

Each of these is machinery that catches the defect without anyone remembering
to look for it. Each exists because of a specific instance above.

**A denominator that raises rather than answering zero.** A rule that fails to
state what it examined crashes in the commit that added it, instead of
reporting a reassuring zero forever.

**A floor, not a zero test.** "Nothing happened" is easy to check and rarely
the failure. The failure is "almost nothing happened". `CORPUS_FLOOR` fails a
fuzz run reaching the rules in under 35 per cent of the repositories it built,
because the run that reached 6 of 35 exited 0 and read exactly like the run
that reached 25.

**A ledger that fails, not one that reports.** Printing "8 of 13 rules reached"
is not a gate. The reach ledger fails below a floor AND fails outright when a
feature was drawn and reached nothing, because a version that only reported it
printed the broken feature's name and exited 0.

**A third return value.** `DidNotRun`, `None` meaning "could not judge",
`recipe.broke(...)`. The point is not the exception; it is that the caller is
forced to handle a case it would otherwise fold into success.

**One function, two callers.** The remedy `AGENTS.md` states for rules
generalises: any time a thing is measured twice, measure it once and read it
twice.

**An assert on every anchor.** A substitution that silently misses leaves the
code correct, the suite green, and the report clean. `mutate.py` treats a
non-matching anchor as a HARNESS FAULT rather than a skip for this reason, and
the same applies to any script that patches source.

**Watched failing.** A check nobody has seen go red is a hypothesis. Break the
thing on purpose and confirm the check notices - and when it does not, work out
whether the check or the BREAKAGE is at fault. Two breakages written for this
were themselves broken: one left a syntax error so the tool never ran, and one
broke both sides of a comparison identically, so the two agreed. A symmetric
break cannot test a check that compares two things.

## The shortest version

If you remember one line from this document, make it the question:

> **What does this return when it cannot tell?**

And if you remember two, make the second:

> **Has anyone watched it fail?**
