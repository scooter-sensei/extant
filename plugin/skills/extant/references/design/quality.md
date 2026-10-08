# Keeping the tool honest: the suite, the types, CI and the reviews

Part of the design rationale; [its core](../design.md) maps every part and
section. How the tool's own checks are checked: what the suite counts, what
the type checker can and cannot see, what CI runs and on which surfaces, the
review bundles that closed what earlier tranches owed, and what a mutation
campaign costs and why that cost does not move a verdict. The sections are in
the order they were written.

## The suite's own denominator, and the number the review could not see

The internals review said the suite had no denominator of its own: 87 per
cent line coverage of the package under pytest, gate.py at 54, cli.py at 66,
`run_check_text` untouched - and, honestly, that smoke, scenarios and fuzz
drive those paths as subprocesses coverage cannot see, so "the real number
is unknown, and unknown is the state this project exists to abolish". The
instruction was to run the harnesses under coverage and find out.

**The unknown was the suite's own subprocesses, not the harnesses'.** Most
of the tests that drive a mode run the tool the way a hook does, as a
subprocess, and `pytest --cov` measures none of those processes. Measured
on 2026-09-15 on 4,065 statements with a `sitecustomize` hook starting
coverage in every process that inherits `COVERAGE_PROCESS_START` - the
tool, its survey workers, the hooks it installs - and the arena copies the
harnesses install as `tools/extant` folded back onto the checkout:

| module | suite, subprocesses unmeasured | suite | union with the three harnesses |
|:---|---:|---:|---:|
| gate.py | 56.6% | 95.2% | 95.6% |
| cli.py | 68.1% | 90.4% | 91.2% |
| sweep.py | 86.1% | 96.7% | 97.1% |
| report.py | 83.7% | 97.6% | 98.6% |
| package | 89.1% | 94.3% | 95.0% |

The first column reproduces the review to within two points on every module
it named - its figures were taken on 0.26.1's 3,505 statements - and the
reproduction is honest about one thing: `concurrency = multiprocessing` let
even that run measure the survey's worker processes, so "unmeasured" means
the tool's own spawns, which is exactly what a plain `pytest --cov` misses.
The three harnesses add one line to gate.py and two to cli.py. That number
must not be read as the harnesses being redundant: coverage counts
statements, not inputs, and fuzz's 35 hostile repositories run the same
lines under crash, exit, denominator, format and concurrency properties
that no line count expresses. Measured on Windows; a POSIX-only line counts
as unreached here.

**What 205 unreached statements were, read one by one.** Eleven of 38
modules fully covered. The console-script entry `cli()` - the pip, pipx and
pre-commit path, the one route that reads the checked-out repository's own
`.extant.toml` - executed by nothing, seventeen lines. Both refusals of
`--introduced-since` that exit 2: a diff git cannot produce, and a HEAD tree
it cannot list. The line in each survey mode that carries a rule error out
of a worker into `RULE_ERRORS` - never executed, and deleting it turns a
rule that crashed inside a worker into a clean survey with exit 0, which is
the failure this whole tool exists to refuse. `--check-text` with no usable
stdin (exit 1) and with an unreadable baseline (exit 2). `--selftest` on a
primary document that is not UTF-8 (exit 1). The unresolvable-ref fallback
in `reachable_from`, unreachable from every rule by construction because
`_merge_sites` and `integration_refs` drop such refs first. Those thirteen
are tested in tests/test_unreached_exits.py, each naming the line it
reaches, and the six that decide an exit code are mutation anchors. The
remaining ~130 are degraded paths - a missing git, a config that will not
decode, an LFS blob that cannot be read, a `?` in an exclusion glob - and
are recorded here rather than tested: each is a named branch in the JSON the
measurement writes, and none decides an exit code.

**Honest triggers, and one that could not be.** The diff refusal is reached
for real: a `blob:none` clone whose base version of the changed document
was never transported, under the environment that refuses the lazy fetch.
A rule raising inside a worker cannot be injected, because workers are
spawned and re-import the real rules; what the test pins is the parent's
handling of what a worker reports, which is the line that was never run.
The `ls-tree` refusal has no real state that fails after a diff succeeded,
so `tracked_markdown` is made to raise - and the test says so.

**Two artefacts of measuring.** Two suite tests remove `tomllib` from
`sys.modules` to simulate a Python with no TOML parser; `coverage` has
imported it to read its own configuration before they run, so under the
hook they fail for that reason alone and the documented command deselects
them. And the measurement changes timing - the chain took twenty minutes,
most of it fuzz - so it is a thing run by hand and recorded, in
tests/harnesses/README.md, not a CI job and not a threshold. `coverage` is
in `requirements-dev.txt` on the same side of the line as pytest-xdist: the
tool still has no dependencies.

**After the thirteen tests, and in branches.** Suite alone: gate.py 96.8 per cent, cli.py 98.0, `introduced_since.py` 95.6, the package 95.4; in union with the harnesses 97.2, 98.8 and 95.9, with 165 statements reached by nothing where there were 205. Branch coverage, measured once with the suite alone because the review's figures were line-based and a line cannot see `if index.complete:` taken one way only: 1,381 of 1,496 branches, 92.3 per cent, 113 partial; gate.py 86.8 per cent of its 106, cli.py 92.6 of its 94. Recorded, not gated.

## Five correctness items, counted; four changes, and what the counts refused

The review's section 6, taken together on 2026-09-16 because each ends in a
number: 6.1 the blanking memo's key, 6.3 the rename map's window, 6.4
`branch_exists` resolving tags, 6.5 the `EXTERNAL` list against a path index,
6.6 where settings are read from. Every count is over the 152 visible corpus
clones unless it says otherwise (`m9_probes.py`, `m9_stripped.py` and
`m9_stripped_one.py` in the measurement tree; outputs under
`D:/repo/out-correctness/`).

**6.1, the key that omitted the format: 0 of 868,986, fixed anyway.**
`_STRIPPED` in `text.py` was keyed on the identity of the text object while
`_blank_uncached` also read `doc.doc_format`; text.py, scope.py, commits.py,
line_pointer.py, path_pointer.py and two tests all recorded it as a latent
bug, and two tests cleared the memo by hand to work around it. The review's
probe - make a hit assert the format and run the corpus - was run as a count
instead, so one mismatch could not end a sweep: an instrumented `_blank`
over every visible clone saw 168,774 blankings, 868,986 memo hits and 0 hits
answered under a format other than the one they were blanked under. A sweep
reads each document once, under one format, into its own string object, so
the condition the bug needed does not arise in any shipped mode. The key
carries the format now regardless, on the review's own reasoning that the
two lines cost less than the paragraph explaining their absence; the seven
records of the bug say so, and the two workaround clears are gone, which is
the proof.

**6.3, the rename window: 2 of 501, refused; a spelling defect beside it,
fixed.** The review read `-n 200` as "the last 200 rename commits"; it is the
last 200 COMMITS of HEAD's history, of which the renames are shown - on this
repository all 28 renames sit inside 355 commits. Measured on the nine
autopsy clones, the one tier with the blobs rename detection needs, against
the Phase 45 identity sweep's findings: 501 dead link and pointer findings,
0 of them hinted; 497 name a target renamed nowhere in history; 2 were
renamed beyond the window (0.4%); and 2 were renamed inside it and missed
because the hint is looked up under the target AS WRITTEN while the map's
keys are repository-relative - ruff's mdtest suite linking a sibling as
`./invalid_assignment_details.md`. **The zero hinted had a third cause, and
the gate found it.** The identity sweep after the fix showed 0 outputs
changed where the count had predicted 2. The probe had passed `-M`; the
tool's `git log --name-status` had not, and rename detection there follows
the repository's `diff.renames` - which every one of the 152 visible clones
sets to false, written by the clone script. On this corpus the hint had
never once been able to fire, and a project that sets the same would get
no hint and no note. `_rename_map` passes `-M` now: it costs nothing where
detection was already on (ruff, full clone: 1.38 s against 1.42, 6,795
renames against 0), a partial clone fails the same way with or without it
because detection reads blob content and lazy fetching is refused, and the
tool's answer no longer depends on a setting of the repository it checks -
the stance `environment()` already takes for `core.quotePath`. One of the two beyond the window would
get a WRONG hint if the window grew: a vendored typeshed README citing its
own absent `CONTRIBUTING.md` would be matched to ruff's, which moved to
`.github/` 349 commits back. Raising the bound and the per-finding
denominator line the review offered are both refused on 2 of 501, the walk
being already the largest spawn in a sweep. The spelling defect is fixed,
through one resolver all three readers of the hint share - `dead-md-link`,
`dead-path-pointer` and the `--suggest-fixes` patch: `sites.reference_path`
gives the repository-relative path a reference names from its document,
`renamed_to` is asked under that, and the patch spells the answer back
relative to the page through `sites.relative_spelling`, because a
repository-relative path spliced into `docs/a.md` - `[it](docs/new.md)` -
named `docs/docs/new.md`, a second defect the audit found in the same line.
The pointer rule asks in its own order, from the root as written and then
from beside the document.

**6.4, a tag named like a branch: 23 names in 7 repositories, changed.**
`branch_exists` asked `rev-parse --verify <name>`, which follows git's
tags-before-heads precedence and answered True for a tag; refs.py said so
and asked for a corpus count before it changed. Counted: 23 names in 7 of
152 clones are both a remote branch and a tag - `v1.10.2`, `package-2.1.0`,
`release-2013.1`, release lines tagged at their own name - so the
divergence is real, and the two rules that ask are asking about BRANCHES:
`unknown-branch` wants a branch or a merge commit naming one, and a live
claim about a tag is a claim about nothing. It answers from the ref table's
heads now, with no process; a name that is only a tag is asked once more
for a remote-tracking branch under `refs/remotes/`, where `rev-parse` would
have looked had the tag not been in the way; a spelling neither table holds
- `origin/feature`, `HEAD`, a SHA - is `rev-parse --verify` as before, so
nothing a document names today stops existing. The verdict that moves: a
name existing only as a tag now reads as no branch, which sends
`unknown-branch` to the merge history and `stale-live-claim` to "that
branch no longer exists" - both the honest answer about a branch. The
corpus cannot gate it, because the entry-scoped rules read primary documents
and the clones have none; the fixture in `tests/test_ref_resolution.py` is
the gate.

**6.5, index-first `EXTERNAL`: 0 of 652,705, refused.** The review proposed
asking the path index before the host test, so a URL-shaped target that is
a tracked file is a path whatever it looks like, and named the count that
would decide it. Over 87,189 documents, 652,705 destinations are refused by
`EXTERNAL` and 0 name a tracked file or directory, resolved from the
document or from the root. The list is right on a corpus it was not built
on, which re-validates the measured-exclusion rule it was built by, and the
reordering would move a pure, unconditional refusal (`links._link_target`)
into the three repository-aware callers for no verdict. Refused; the zero
is the record, and a future collision is a suppression a corpus count will
show, which is how the list was built in the first place.

**6.6, where settings are read: 0 of 152 either way, decided by
semantics.** The review asked how many corpus repositories would find a
configuration under each rule; none tracks a `.extant.toml` and none a
`pyproject.toml` with `[tool.extant]`, so the corpus cannot separate them.
What could be settled is the defect the README listed under "what it cannot
do": settings were read once at import, relative to the tool's own file, so
a run pointed at another repository used the tool's settings and printed a
NOTE saying the target's file was NOT read. The console script `cli()` had
learned to re-read from `--repo`; `main()`, which the installed shim and
every hook run, had not. It re-reads now, once, in the one place both pass
through, so an ordinary install finds the file the import found, a run
pointed elsewhere finds that repository's settings or the defaults, and the
NOTE has no condition left to report. `--config PATH`, `--config-from-script`
and `[tool.extant]` are refused: no population, and a second place for one
setting is how a setting nobody reads gets written.

**The gate.** Suite, six anchors written and three retargeted (9 of 9
killed), and the corpus identity sweep run twice: once before `-M`, where
its 0 changed outputs against a predicted 2 was the finding above, and once
after, where 152 outputs compared and exactly 2 differed - the two autopsy
findings 6.3's count said would gain a hint, each gaining precisely it;
then the pre-push chain, green, with one of the fuzzer's own breakage
anchors retargeted at the blanking memo's new hit condition.

## The structural tranche: one Config, and two shapes the numbers kept

Tranche 12 of the internals review, 2026-09-21: the three structural items
the previous handoff ordered - 3.8, then 3.4, then 3.2 - and 3.6, which it
asked to have recorded rather than left open. Each was measured before
anything was written, and the measurements decided them the way they are
supposed to: one built, two refused, one recorded as blocked. The tranche
changes no output anywhere, by construction and by the identity gate at
the end.

**3.8, the dynamic config globals, gone.** `session._apply_config` built
the one `Config` every rule reads through `ctx.config` and then wrote
twenty-one module globals from it - `PRIMARY_DOC`, `TRUNK`,
`_SECTION_HEADER` and the rest - through `globals()[name] = ...`, a second
table kept for the callers that predate `Context`. Counted before
anything moved: 2 of the 21 were still read outside
`plugin/skills/extant/payload/extant/session.py`, at 13 sites in 2 modules
(`cli.py` 9, `gate.py` 4; `sweep.py`, which the review named, reads the raw
`StatusConfig` and none of them), and 9 of the 21 were read by nothing but
the table that built them. mypy 2.3.1 in default mode
- at `--python-version 3.10`, because that release no longer targets the
3.9 floor, which CI checks and mypy now cannot - reported 31 errors in 7
of 39 files, 14 of them `attr-defined` and 13 of those `Module has no
attribute "PRIMARY_DOC"` or `"ARCHIVE_DOC"` at exactly those 13 sites.
Two shapes satisfy the review's decider. Twenty-one annotations beside
the table would tell mypy the names exist and change nothing else - a
third copy of the name list, since `__all__` already carried four, with
the mechanism the review objects to intact. The other is to delete the
surface: the modes read `session.config()`, a function returning the one
built object, the spelling the rules already use; `_ACTIVE` is declared
`Config` and never assigned at module level, so a read before
`_apply_config()` is a `NameError` rather than a `None` every reader has
to explain; the table, the loop, the annotation-only `_CONSISTENCY_TIMEOUT`
and four names in `__all__` leave. A function rather than the attribute,
because the attribute is rebound by `reload_config` and a sibling
importing it by name would hold the import-time object across the reload -
the staleness the single writer exists to prevent, reintroduced at the
import boundary. After: 17 errors, `Module has no attribute` 0 of 0, and
the `Generator has incompatible item type` complaint on `--search`'s
denominator went with them, because it was the unresolved names' type
reaching a `sum`; the 17 that remain belong to the review's mypy item and
were left alone so the delta is attributable - `Context.config` is still
`Any` for the same reason. The suite moved with it, about fifty lines in
eight files, every one `hc.TRUNK` becoming `hc.config().trunk` in kind:
the two conftest fixtures lost their save-and-restore loops over the
table; the bijection test between `Config`'s fields and the table had no
second table to guard and became the narrower property that survives -
`config()` and `context().config` hand out one object, and it equals a
fresh build; the one-place test lost the two assertions about the table
and the exemption for it, its stray scan and both `_apply_config` checks
untouched; and the reload oracle, which compares every module global
between a fresh import inside a project and a reload pointed at it, now
compares eight names where it compared thirty, with the built Config's
twenty-one fields inside one of them - the same information, since the
globals were derived from that object. One structural test was added,
`test_no_module_binds_a_global_through_globals`: a subscript assignment
to `globals()` or `vars()` anywhere in the package fails it, which is what
keeps the shape from coming back; it went red on the one such write in
the package before the change and green after. Two anchors: the one on `--search`'s document
loop retargeted at the new spelling, and one new, `config()` handing out
a second build - a fresh `Config.build(CONFIG)` per call agrees with the
rules on every CLI run and disagrees under the `reconfigure` fixture,
which replaces the built object and not the raw settings, the trap the
globals used to spring - pinned by the identity assertion in the new
test.

**3.4, `contextvars`, refused now and gated on 3.5.** The review's case:
`_SCOPE` and `_DOC` are module globals saved and restored by hand, a
`ContextVar` token restores them with the pairing enforced by the API, and
each thread then gets its own view, which is what makes the thread pool of
3.5 reachable. Four numbers. The package starts no threads: the one pool is
a `ProcessPoolExecutor`, each worker owns its module globals, the
consistency rule bounds a pattern's time by process isolation, and nothing
that runs today can observe the difference between a module global and a
context variable. The review's decider is zero test changes, and a port
that changes the attribute's type touches 89 code lines in 15 files - 67
of them `hc._SCOPE = hc.RunScope()`, 17 attribute reads, one in the corpus
harness - plus the anchor on the scope's restore; none is a lifetime
moving, all are test changes, and the only route to zero is to swap the
module's class for one with properties, so that `hc._SCOPE = x` sets a
context variable while reading as an assignment - the "looks like it
works" shape this project keeps paying for. The `finally` stays: a token
still has to be reset on the failing path, and what the API removes is the
`previous_scope = _SCOPE` line, one of two in `run_scope()`. And the one
consumer, 3.5, had no interpreter when this was measured: CI ran 3.9
through 3.13 with the GIL and this machine runs 3.14.3 with it (Phase 56
added 3.14 to the matrix and a free-threaded job beside it - see "CI
honesty" below); a thread pool also needs each thread
to ENTER its own scope, which is the same initializer the process pool
runs, so 3.4 and 3.5 are one change and are measured together when a
free-threaded build is in the matrix. For whoever ports it then: a
variable set inside `run_scope()`, a generator-based context manager,
binds the caller's context, which is right, and `reset` refuses a token
from another context, which no caller here has.

**3.2, `Rule` as sites and judge, refused on paper.** The review wants
`check` and `examined` replaced by `sites(ctx, text)` and
`judge(ctx, site) -> Finding | None`, with `examined` becoming
`len(sites(...))` in the base class, and its own decider is 13 of 13 rules
porting byte-identical, failing which the AST gate in
tests/test_module_quality.py stays. Read against the thirteen: 11 already
have `examined = len(_x_sites(ctx, text))`, and two sum over grouped sites -
`dead-path-pointer` over `(line, raws)`, which would flatten to one site
per raw with the line's link map carried along, identical by construction,
and `inconsistent-artifact`, which does not fit. One of its sites is a
consistency group, and a group yields up to `len(sources) + 1` findings:
one when the sources are the same file, one per source that is missing,
times out or matches nothing, and one for the group when the values
disagree - five `Finding` constructions at three nesting levels, with the
denominator counting sources. The strict contract holds it only with two
relaxations, a list-valued judge and a per-site weight, and the second
re-admits exactly the drift the gate refuses: a count the judge never
reads. By the review's own rule that is the answer. The handoff's spike -
`unknown-branch` and `dead-path-pointer`, one simple and one with a
`required_literals` gate - could not have produced it, since both port;
it was not spent, and the reading above is the record.

**3.6, recorded as blocked.** A content-addressed result cache keyed on
the document's blob, `HEAD`, the ref table, the configuration and the tool
version is sound, the review says, only once 3.3 removes every claim
resolved against the working tree rather than against git; 3.3 was
refused above on its own numbers, and the 1,022 gitignored-path verdicts
that section counts - dead in every fresh clone, resolving on any machine
that has run the docs build - are precisely the machine-dependent answers
such a cache would freeze and replay as if they were git's. Blocked by
that refusal, not open.

**The gate.** Suite 1,323 passing and 3 skipped: one test added, one
replaced, and about fifty lines in eight files moved to the new spelling,
every one of them red against the unchanged package first. Two anchors -
the retargeted one and the new one - run for real on a copy of the tree,
2 of 2 killed in fourteen minutes with the baseline; 284 anchors match
exactly once. The corpus identity sweep against a stated prediction of
zero of 152 differing, because no output carries a global's name: 152
compared, 0 differ. The pre-push chain against a working-tree extract:
smoke 45 clean of 47 with the two expected flags, scenarios 213 of 213,
fuzz at seed 20260824 over 35 repositories with 0 violations,
`--self-check` 22 of 22, `--verify` clean, `--selftest` 7 fired and 0
silent. mypy on the tree afterwards: 17 errors where there were 31,
`Module has no attribute` 0 where there were 13. The measurements above
were taken before any of it was built.

## The type checker: four measured, the floor none can see, and a gate on the one that enforces the most

Tranche 13 of the internals review, 2026-09-21: the review's mypy item under
9.2, the cheapest of the dev-side tools once 3.8 had made the configuration
visible to a checker at all, and - because it was asked for - a look at
what else a project could gate its types on in 2026. Everything below was
measured on this tree before anything was written, and the first
measurement overturned the argument the design had been going to make.

**Four checkers on one tree.** The shipped package and the shim, 39 files,
each checker at the lowest Python it can be told to assume, best of three
runs: mypy 2.3.1 at 3.10 (it rejects 3.9) reported 17 errors, 10 of them
real, in 2.94 s; Pyrefly 1.3.1 at 3.9 reported 10, 8 real, in 0.64 s;
basedpyright 1.40.1 at 3.9 reported 11, 8 real with one site counted twice,
in 4.35 s. ty was left at its beta and 53-86% conformance, and zuban at its
AGPL; neither is a CI gate for a project that ships to strangers. The three
that were run agree on the same eight sites: `config.py` calling `int()` on
an `object` and passing a `Path | None` where a `Path` was declared,
`collect.py` recording `parse_phase`'s `str | None` in a dict declared to
hold strings, `gate.py` returning the integer mark from a function annotated
`-> bool` and threading it through two more signatures as a boolean,
`cli.py` calling `reconfigure` on a `TextIO` that promises no such method,
and the anchor rule testing membership in a set the tuple said could be
None. mypy's other seven were artefacts of its 3.10 target and of the shim's
`tools.extant` fallback; Pyrefly's flow typing resolved the one site
(`sites.py`'s `result`) that mypy flags only because a first assignment
fixes a variable's type, and Pyrefly missed the one (`config.py:753`) that
sat under a mypy-vocabulary suppression it honoured as blanket. Every one of
the eight was a docstring or an annotation saying something the code did not
do, and one - `report_denominators` - had said it since the split that
made `gate.py` on 2026-08-31, three weeks and one release.

**The floor no checker can see.** The design's first reason for preferring
a Rust checker was going to be that Pyrefly and pyright accept
`python-version = "3.9"` and mypy 2 does not, so only they could check the
floor this project promises. Six 3.10-and-later usages were planted in a
scratch file to see what each would say. Pyrefly at 3.9 caught a `match`
statement and a 3.12 `Path.with_segments`; basedpyright at 3.9 caught those
and a module-level `Callable[[str], None] | None`, which is an import-time
`TypeError` on 3.9; mypy at 3.10 caught `with_segments` and an unguarded
`import tomllib`, the only one of the three to read typeshed's `VERSIONS`.
Neither Rust checker at 3.9 caught `itertools.pairwise`, `zip(strict=True)`
or `int.bit_count()` - mypy at 3.10 cannot be asked, since all three are
legal there - and the reason is in the typeshed mypy bundles:
`bit_count` sits in `builtins.pyi` with no version guard at all. typeshed
dropped Python 3.9 at its end of life in October 2025 and removed the
`>= (3, 10)` guards with it, so whatever `python-version` a checker is told,
a 3.10-only call now reads as always present. The 3.9 leg of the test
matrix is the only check of the floor, and a `python_version` in any
checker's config is a check of everything above it. With that reason gone,
the comparison was cost and enforcement, and it went the other way.

**Why mypy.** Three things the others lack, each with its number. Its
`warn_return_any` is the only rule in any of the three that objects to a
typed function returning a value nobody typed, which is what turned the 28
`dict[Any, Any]` memo fields on `RunScope` into 28 statements of what each
holds - Pyrefly's strict preset raised 41 implicit-`Any` errors of four
kinds on this tree, and none of those kinds looks at an explicit one. It reads `VERSIONS`, so an unguarded 3.11
import is red at the 3.10 target where the others are silent. And it is the
reference implementation with a decade behind it, where Meta retired Pyre
for Pyrefly and Pyrefly went 1.0 to 1.3 between May and September with its
strict preset changing on the way. The costs, also measured: 2.94 s against
0.64, which is nothing in a CI job; an environment marker on the
requirement, because mypy 2 needs 3.10 and the test matrix installs the dev
requirements on 3.9; and five suppressions where Pyrefly would have needed
one, each named below.

**Twenty-two suppressions, seven of them stale.** Before the gate, the
package and `install.py` carried 22 `# type: ignore[code]` comments written
against a mypy nobody ran. Under `warn_unused_ignores`, 7 of them - six in
`install.py`, one in `config.py` - named a code that no longer fired on
their line while a different one did, which is a suppression waiting to
hide a real error of the code it names: the failure this project describes
for its own baselines, in its own source. After: 5, each with its reason on
the line above and one code each. `config.py`'s `import tomllib` is
`import-not-found` at the 3.10 target because the module arrives in 3.11,
which is what the try/except beneath it is for; `scope.py`'s `git: Git =
None` is a sentinel the tests pin, declared as the type every reader may
assume and defaulted to what fails where git is used; `session.py`'s
`replace(_DOC, **changes)` forwards field names it never reads; and the
shim's two fallback imports rebind a name the first arm bound, which is a
redefinition and the one the file exists to make. `tomli` and `tools.*`
are resolved in `[tool.mypy]` rather than on their lines, because whether
either can be found is a fact about the interpreter running the check, and
a per-line suppression that is needed on one machine and unused on the next
would itself go red - measured: with `tomli` installed and without, the
same output.

**What `strict` asked for, and what it found.** Before the work, 17 errors
in default mode and 79 under `--strict` on the package and shim, and 12
and 18 on `install.py` (`detect.py` was clean): 29 and 97 across the 41
files. After it, 0. The `Rule` contract's `check`, `probe` and
`examined` were `object`, which said nothing and needed a suppression at
each of five call sites; they are `Callable[[Context, str], ...]` now, the
two names reached under `TYPE_CHECKING` so the module still imports nothing
at runtime and the cycle it was split to avoid stays impossible, and every
rule's `RULE = Rule(...)` is checked against the contract - all thirteen
matched. `scope` became a `Literal` of its three values, so a rule naming a
fourth is a type error rather than a rule the loops never select. The
ancestry index is declared as a `Protocol` on the scope that holds it
rather than imported from `refs.py`, which imports the scope; the one
consumer that re-read the memo to prove an index it had just built existed
now carries the index beside its misses instead. `md_anchor.py`'s
five-tuple, whose docstring promised two elements were "None together",
carries them as one pair or None, so the promise is the type. `sweep.py`'s
worker result and `survey`'s gathering are named once under `TYPE_CHECKING`,
because a module-level alias holding `str | None` is an expression Python
3.9 evaluates on import and cannot - the one 3.9 hazard the checkers do not
see, and the house style now says so. `run_scope` is a `Generator`, which is
what a `@contextmanager` function is (Pyrefly warned; mypy did not).
`install.py`'s measurements and presets are `TypedDict`s in `detect.py` and
`install.py`, and the two readers that need an observation's value in a
specific shape narrow it and refuse the rest.

**The one behaviour change, and its reach: 0 of 152.** The loader coerced
every setting into the shape it wanted, and mypy refused two of the
coercions - `int(object)` and `tuple(object)` - which was the thread. Pulled:
`suite_command = "pytest"` ran six one-letter arguments, `trunk = ["main"]`
named a branch called `['main']`, a pattern given as an array compiled to
one that matched nothing, and `release_claims_name_our_tags = "false"`
switched the rule ON, because `bool` of a non-empty string is true. Each is
a configuration that looks right and is not, which is the failure
`config.py` names in its own docstring, sitting in the function that
docstring is on. The loader now checks one TOML shape per setting - 20
strings including every pattern, 6 arrays of strings, 1 integer, 1 boolean,
the number-or-absent and the table it already checked - and refuses another
with the setting, the file and the shape named, in TOML's vocabulary
because that is the file the reader is holding. Reach, counted: 0 of the
152 visible corpus rows track an `.extant.toml`; this repository's own uses
native shapes; the installer renders booleans and arrays natively; no test,
harness or preset writes a coerced shape (0 hits). Six tests: five
refusals, red first, and one control that every documented shape still
loads, green before and after; `config.md` states the type of every
setting, which it did not.

**The gate's shape.** `[tool.mypy]` in `pyproject.toml` is the whole
configuration - the four targets, `python_version = "3.10"`, `strict`, the
two missing-import overrides - so `python -m mypy` from the repository root
takes no arguments; the cache lands at the root and is ignored there, and
the docs say not to run it from inside `payload/`, where the cache would
sit beside the shipped source and fail the test that reads every shipped
file whole. It is a step of the self-check CI job, not a test: the suite
runs on 3.9, mypy 2 does not, and a test that skipped there would print as
a pass on the one leg whose floor it cannot see anyway. The step prints the
checker's version before running it, so a verdict that moved between
releases can be told from one that moved with the code. The requirement is
`mypy>=2.3,<3` with a marker for 3.10 and up: bounded above because a
checker's verdicts change at a major - 2.0 moved three defaults - and a gate
that reddens `main` on a release nobody committed is the failure
`mutate.py --check-only` exists to catch for the anchors; the bump is a
deliberate commit with the new count in it.

**Not done, with the number that decided it.** pytest-randomly: the suite
was run once in a seeded random order with tests from different files
interleaved across workers (`--dist load`, seed 20260921) - 1,323 passed, 3
skipped - and the property was already evidenced by the load/loadfile
identity AGENTS.md records; a plugin that shuffles every developer run on
this machine to keep a property that holds is not installed. pytest-timeout
waits on the slowest test being measured first, so the bound is a number
rather than a guess. The tests are not type-checked - 1,329 of them is a
tranche of its own. A `py.typed` marker is refused: nothing imports the
package as a library, so the marker would ship into strangers' `tools/`
directories for nobody.

**The gate, as run.** Five refusal tests red before the loader refused
anything and one control green before and after, and two tests given a
real `Config` where they had handed the field None; the suite 1,329
passing and 3 skipped. `python -m mypy`: no issues in 41 files.
Five anchors retargeted on lines that lost a suppression or gained an
annotation - the probe loop, the parser fallback, the preset's disable
list, the worker's configuration, the absolute-target refusal - each
applied to a copy of this tree and watched turning the suite red: 5 of 5
killed in thirty-one minutes with the baseline; 284 anchors match exactly
once. The corpus identity sweep against a stated prediction of zero of 152
differing, because an annotation changes no output and the loader's
refusals reach no clone: 152 compared, 0 differ. The pre-push chain
against a working-tree extract: smoke 45 clean of 47 with the two expected
flags, scenarios 213 of 213, fuzz at seed 20260824 over 35 repositories
with 0 violations, `--self-check` 22 of 22 with every breakage anchor
matching once, `--verify` clean, `--selftest` 7 fired and 0 silent. The
measurements above were taken before any of it was built, and the first
of them changed what was built.

## CI honesty: the version the maintainer runs, the surfaces adopters run, and a third order

Phase 56. Nothing under `payload/` moved, so the corpus identity gate and the
mutation campaign were not run - there is no tool behaviour for either to
see - and the proof of this tranche is the CI run its changes trigger, read
job by job rather than by colour. Seven items: five from the plan written on
2026-09-22 and two its audits found. Every premise was re-measured on
2026-09-28 before anything was built, and six had moved - five below, and
the `forkserver` corner under 3.14.

**What had moved.** The plan's action pin (`@v0.24.1`) was already bumped by
0.28.0. Its dogfood design exempted release pull requests, which bump
README's pins ahead of the tag; 0.27.0 and 0.28.0 did go through such pull
requests, but releases have been cut straight on `main` since 2026-09-27,
where the dogfood job runs `verify`, which does not read README - so the
exemption has nothing to exempt. The thirty-minute wait for `tests.yml` that
the plan put in `publish.yml`'s `publish` job lives in `build`. The plan's
dogfood job set up a Python first; the README's snippet does not, and
`action.yml` relies on the runner's own, so a job that set one up would test
a workflow no adopter was told to write - and the same snippet needs the
trunk-ref step, because on a pull request `main` is only a remote-tracking
branch, which the plan's shape also left out. And nothing joined the top of
the Python range: the floor test ties `requires-python` to the badge, the
prose, the matrix and the classifiers, but only at 3.9, so 3.14 in the
matrix without its classifier - or the reverse - passed everything.

**3.14 on both platforms.** The matrix gains it, twelve legs; the
classifiers gain it; and a new test in `tests/test_docs_match_code.py`
fails when the matrix list and the classifiers name different versions,
watched red with 3.14 in the matrix alone. The Linux corner the plan named -
the sweep's pool starting under `forkserver`, a method no earlier leg used -
was already exercised: WSL's 3.14.4 runs the suite under it, 1,418 passed
in each of five runs on 2026-09-28. CI's 3.14 is 3.14.7, the newest the setup action's
manifest held on the day, against 3.14.3 here and 3.14.4 in WSL.

**`3.14t`, one run and then a verdict.** `setup-python` accepts the `t`
suffix (its `docs/advanced-usage.md`), and its manifest held 3.14.7
`x64-freethreaded` for ubuntu 22.04, 24.04 and 26.04. The job's first step
FAILS unless `Py_GIL_DISABLED` is 1 and `sys._is_gil_enabled()` is False -
a setup that handed over the ordinary build would otherwise be a second 3.14
leg reporting itself as the free-threaded one - and then runs the suite
serially, where `filterwarnings = error` turns the RuntimeWarning an import
raises when it re-enables the GIL into a failure. `continue-on-error` for
exactly one run: then required if green, removed with the reason recorded
here if red. A leg allowed to stay red is the "one test fails on purpose"
note this workflow removed. The run was green - CPython 3.14.7t,
`Py_GIL_DISABLED=1`, the GIL off, 1,422 passed and 1 skipped in 69
seconds - so the job is required and `continue-on-error` is gone, and the
thread-pool question in the paragraph on 3.4 above has an interpreter.

**`--durations=15` on every leg**, for the pytest-timeout bound the next
tranche sets. That bound takes the slowest test on any leg - likely a
Windows leg under `-n auto`, where workers contend for the cores, an
overstatement on the safe side.

**The action, on this repository's pull requests.** A `dogfood` job:
`fetch-depth: 0`, the README's trunk-ref step, then `uses: ./` - no
`setup-python`. On a pull request `mode: introduced-since` from the event's
base; on a push to `main` the default, `verify`. `uses: ./` installs from
the checkout, so a pull request's own `action.yml` and package run, with one
measured difference from an adopter's run: pip builds in the source tree
and leaves `build/` and `plugin/skills/extant/payload/extant.egg-info/` in
the tree being checked, both ignored by git; a directory that exists can
only make a path pointer resolve, and the one mention of a `build/` in a
checked document names another project's directory. Measured before the job
existed: `--introduced-since` over the Phase 55 pull request's content, 5
documents and 384 introduced lines, reported 0 findings on them; over this
tranche's, measured from the Phase 55 head, 4 documents and 186 introduced
lines at its first push and 245 at its second - the second counted by the
dogfood job itself - with 0 findings each time.

**The hooks, through pre-commit.** A `pre-commit` job runs `pre-commit
try-repo . extant --all-files` and the same for `extant-annotate`, which
install the hooks from the checkout's HEAD into pre-commit's own
environment - the path an adopter's `rev:` pin takes. Measured here first,
pre-commit 4.6.2 in a scratch environment: both passed, 27 and 26 seconds,
about 25 of each building the environment. The trunk-ref step again, since
the hook is `--verify`. Pinned `>=4.6,<5` in the job, on mypy's reasoning
for an upper bound, and in the job rather than `requirements-dev.txt`
because nothing else needs it.

**A timeout on every job.** None was set, so a hung job held a pull
request's verdict for GitHub's six-hour default. One rule: three times the
slowest time in the last five runs, rounded up to a multiple of five
minutes, never under five - three because one leg varied from 5.4 to 9.3
minutes between runs. Measured: Linux tests 1.1-1.9 (10), Windows tests
3.0-5.1 since they went parallel (20, which also covers the 9.8 of the
serial legs twice), Windows fuzz 6.1-7.4 (25), Linux fuzz 1.4-2.0 (10),
self-check 3.6-4.3 (15), smoke 0.9-1.0 (5), scenarios 0.3-0.4 (5). The
three new jobs from their first run: free-threaded 1.5, sized as the
serial Linux legs it mirrors (10); pre-commit 0.3 (5); dogfood 0.1 on its
first green run, the second (5) - its first failed loading the action in
the same 0.1 minutes and timed nothing. `publish.yml`'s
`build` took 0.3-0.4 minutes on each of the last four releases but waits up
to 1800 seconds for `tests.yml`, so it is sized from the wait (40);
`publish` 0.3-0.4 (5).

**A third order, on one leg.** Linux runs the suite in file order and
Windows in each file's order, and the `RULE_ERRORS` leak Phase 55 found was
invisible to both. Measured first, on the Phase 55 tree: `-n auto --dist
load`, which interleaves a file's tests across workers, passed on Windows
(1,412 and 7 skipped, 209 seconds) and on Linux (1,418 and 1, 38 seconds);
three fully shuffled serial runs on Linux passed (1,418 and 1 each, 165-170
seconds against 213 in file order), and one shuffled run under `--dist
load` on Windows (1,412 and 7, 200 seconds). Each seed was checked to have
shuffled: at least 1,416 of the 1,419 tests moved, and consecutive tests
changed file 1,374 to 1,382 times against 74 in file order. So the suite
has no dependency any of those orders can see, and what was built is the
instrument rather than a fix: `--order-seed N` in `tests/conftest.py`,
under thirty lines with its docstring and no dependency, shuffling the collected tests last
among the collection hooks, and `tests/test_suite_order.py` pinning that a
seed moves tests and loses none, that one seed gives one order - xdist
refuses workers that disagree - and that no seed changes nothing. The
ubuntu 3.13 leg runs the suite a second time with a seed written in the
workflow: 3.13 rather than 3.14 so a red there cannot be the new Python's,
and a fixed seed for the fuzz job's reason, so a re-run reproduces and a
red is reproduced locally from its command line. The order still moves -
adding one test reshuffles all of them - so a dependency older than a
commit can surface on it; the pair of tests it names is real either way.
Refused: making the Windows legs `--dist load`, which gives up the
per-file isolation `AGENTS.md` chose `loadfile` for.

**What the first run showed**, on pull request #21, read job by job:
twenty of twenty-one checks green. Both 3.14 legs ran 3.14.7, Linux 1,422
passed and 1 skipped, Windows 1,420 and 3. The `3.14t` verdict is above.
Both hook ids passed, installed from the merge commit, with trunk
denominators that were not zero (`false-merge-claim` 9, `dead-release-tag`
47), so the trunk-ref step did its work. Every leg printed its durations;
the slowest test anywhere was 17.01 seconds,
`test_a_repository_rule_reports_its_one_fault_once` in
`tests/test_fuzz_findings.py` on Windows 3.10 - the next tranche's
pytest-timeout number - against about 4 seconds, the consistency-timeout
test, on every Linux leg. The shuffled step ran on the ubuntu 3.13 leg
alone, 1,422 and 1. Every job finished inside its timeout, the nearest the
Windows 3.9 tests leg at 5.9 of 20. The jobs this tranche left alone said
what they said before: 312 anchors, mypy clean, `--selftest` 7 fired and 0
silent, 23 of 23 fuzz properties, smoke 0 new and 0 missing, scenarios 213
of 213, fuzz 0 violations on both legs.

**And the dogfood job failed, on a defect in the shipped action.** The
runner refused to load `action.yml` - "Unrecognized named-value:
'github'" - at the `since` input's description, which quoted the
pull-request base in expression braces as an example to copy. The runner
evaluates `${{ }}` in the metadata too, a description has no context to
evaluate `github` in, and the whole action was refused before a step ran:
every mode, every caller. `since` arrived with Phase 47 and 0.28.0 is the
release that carries it; 0.26.1's and 0.27.0's actions write no expression
above their steps. Nothing local could see it - the suite reads the
action's script out of the file and runs it under bash, and no harness
loads a manifest the way the runner does - which is the case for the job,
made by its first run. Repaired by naming the value without the braces,
and pinned by `test_the_action_writes_no_expression_above_its_steps` in
`tests/test_packaging.py`, watched red on the one line: no `${{` outside a
comment above `runs:`.

**The second run, after the repair**: twenty-one of twenty-one green, read
job by job. The action loaded and installed from the checkout on the
runner's own Python - no `setup-python`, as the README's snippet has none -
in 3.4 seconds with no warning, which answers what the first run could not
reach; then it gated this pull request's introduced lines from the base the
event named: 4 documents, 245 introduced lines, 0 findings, the local count
exactly. Its `verify` arm runs only on a push to `main`, so the merge is its
first run. The free-threaded job, required now, passed again (1,423 and 1,
81.5 seconds); every leg carried the new packaging test (Linux 1,423 and 1,
Windows 1,421 and 3); the shuffled step ran on ubuntu 3.13 alone. The
slowest test anywhere was 8.88 seconds. The first run's slowest,
`test_a_repository_rule_reports_its_one_fault_once`, took 4.20 seconds on
the same Windows 3.10 leg where it had taken 17.01 - four to one between
two runs of one test on one leg, under `-n auto`. So the next tranche's
per-test timeout starts from 17.01, the larger of the two, and takes that
spread as the reason one run's durations cannot size it alone.

**The Linux 3.9 leg, pinned to Ubuntu 24.04 (2026-10-08).** Pull request
#33's run carried a notice on every Linux job: `ubuntu-latest` becomes
Ubuntu 26.04, rolled out from 2026-10-19 and complete by 2026-11-19
(actions/runner-images issue 14748). Neither image carries CPython 3.9 -
the 24.04 image's tool cache holds 3.10 to 3.14, and the 26.04 image's the
same - so the leg downloads it from setup-python's manifest on every run,
the 24.04 build of 3.9.25 in that run. On 2026-10-08 the manifest held no
3.9 for 26.04: its 3.9 builds stop at 24.04, where 3.10 to 3.14 each have
a 26.04 build too. So from the 19th the leg would have failed in setup,
before a test ran, on every run that landed on 26.04 - red on some runs and
green on others while the rollout lasted, which reads as a flaky runner
rather than as the floor going untested - and on every run after it. The
leg now names its image: an `exclude` of `ubuntu-latest` with 3.9 and an
`include` of `ubuntu-24.04` with 3.9, so the job's title,
`tests (ubuntu-24.04, 3.9)`, says which image ran. Keeping the old title
and routing it to the new image would have left a title naming an image
the leg no longer ran on. 24.04 is the image the leg ran on before, so
nothing it checks moved. The two step conditions that name `ubuntu-latest`
pick out its 3.13 leg, and the others name Windows, so none changes
meaning. Every other Linux leg and job moves with the label: each version
they set up has a 26.04 build, 3.14t's as recorded above.

The pin brings a trap of its own. When the floor rises, "3.9" leaves the
matrix list, the classifiers and the README together, every test above
passes, and the `include` goes on adding a 3.9 leg nobody claims.
`test_every_python_the_workflow_names_is_in_the_matrix_list` in
`tests/test_docs_match_code.py` fails while any `python-version:` in the
workflow names a version the list does not, and was watched red with the
`include` naming 3.8. Refused: pinning every Linux leg, which would stop
the legs that can move from running on the image an adopter's
`ubuntu-latest` gets; and installing 3.9 some other way on 26.04, for the
reason "CI, made cheaper" below refused uv's builds for the Windows leg -
a different build from the one the leg exists to run. Still open: the pin
lasts as long as GitHub keeps the 24.04 image, whose retirement it will
announce the way it announced this move. And the `dogfood` job moves with
the label onto the runner's own Python, as the README's snippet tells
adopters to: 3.14.4 with pip 25.1.1 on 26.04, where 24.04 has 3.12.3 with
pip 24.0. The action's `pip install` into that Python has been seen to
work on 24.04 only, so the first run on 26.04 is its first measurement.

## The owed bundle: what a zero means, where a patch ends, and what a partial copy cannot answer

Phase 57, tranche 19 of the internals review, 2026-09-28. The plan's eleven
owed items, two the review of pull request 13's semantics placed here, and
three that building found. One of the eleven was already done: Phase 54 hands
the diff gate's tree listing to its workers. And one was dropped on the
record's own reasons, below. Every premise was re-measured on the day, and
the audit asked for before building changed six of them. This section keeps
the numbers.

**Two found by reading a log.** The first CI run of the dogfood job's
`verify` arm was judged by its colour, and reading it showed every
`checked <extra>:` line naming `stale-live-claim 0, unknown-branch 0`.
Those two have `in_archive=False`, so `rule_applies` refuses them for a
document with no entries: they never read the document. The line filtered
the repository-scoped rules by hand and nothing else, which is the drift
`rule_applies`' docstring exists to prevent. The sweep reads the one
predicate for both halves, and now so does this line.

Fixing it found the second. `validate` inherits the markup language rather
than deriving it. `--sweep` installs it per document; `--verify` never did,
at any of its three sites (the status document, the archive, each extra).
So an `.rst` document under `--verify` was read as markdown, and the
markdown-only link rule reported `np.dtype[mp.mpf](dps=100)`, a shape that
is not a link in reStructuredText. The two modes disagreed about one file.
Neither moves a corpus output, since the corpus runs sweeps. Both are
pinned by tests watched red, and the three sites by an anchor each.

**The patch `--suggest-fixes` writes.** `difflib` was handed `splitlines()`
and writes no `\ No newline at end of file` marker. So a fix landing on a
last line with no terminator fused `-old` and `+new` onto one line, and
`git apply` refused the whole patch as corrupt, exit 128, in both modes that
emit one. Measured over every tracked document: 17,104 of 94,269 (18.14 per
cent) end that way, in 107 of 176 de-duplicated repositories. That is an
upper bound, because a patch is offered only for a finding with a rename
hint: the corpus carries 2 such findings, and its 139 partial clones can
offer none. So the case for the fix is correctness, not volume. The same
fix cuts lines where git cuts them, at `\n` alone, because `splitlines()`
also breaks at a form feed and at `U+2028`, and the patch's context then
matched no line of the file. Four cases are applied, not inspected.

The generator left `gate.py` for `extant/patches.py`. This was not forced.
`gate.py` stood at 899 lines against the 927-line ceiling in
`tests/test_module_quality.py`; the fix alone would have fitted, and the
"900" quoted in the plan was the ceiling before 2026-09-09. It was made
because tranche 21 has a NOTE to rework in that module, and this was the
cheaper of the two cuts available. The function has callers in both gating
modes, is not a mode itself, and uses none of `gate.py`'s private helpers,
so it moved whole. `--check-text`, the cut planned before, calls four of
them. Seven anchors moved with it, and each was run again.

**A zero from a rule that did not look.** The sweep's NOTE named every rule
with a zero as one that "examined nothing anywhere here - either no
document makes such claims, or the pattern does not match". That is
true only of a rule that read something. The two entry-scoped rules read
only the newest entry of the primary document, and no visible corpus clone
has one, so the NOTE gave both wrong reasons for them in 152 of 152 corpus
outputs. A rule that read no document is now named apart, with the kind of
document it reads, derived from the rule's own declaration. The `examined:`
line keeps its zeros, because they are true. The other half of the NOTE -
a phrase-keyed rule's zero, or an unconfigured one's - is tranche 21's.
Item 13 measured the defaults it needs, from the recorded identity sweep,
de-duplicated to 139 repositories:
- `false-merge-claim` reads every swept document and examines 0 in all 139.
- `dead-path-pointer` examines 705 in 76.
- `dead-release-tag` examines 8 in 7.
- The two entry rules cannot be measured by a sweep at all.

**What a partial copy cannot answer.** The rename search the hint needs
exited 128 ("lazy fetching disabled") on 6 of 6 `blob:none` corpus clones
and found 0 renames, where full clones of the same six found 73 to 6,795.
The seam raises on the exit and what git printed before it stopped is
discarded, so the map is all or nothing. On a copy missing a blob the
search needs there is no hint at all. The note that said a hint "answers
from what is here" now says so. It is worded as a condition, because a
partial copy that has gathered the blobs gets its hints.

`--deleted-since` asked `ls-tree` once per missing previous version to
tell "was not there" from "is not here". On a local `blob:none` copy of
fastapi with 100 changed documents configured that was 102 spawns, and the
100 `ls-tree` calls took 2.74 s of a 3.24 s run. One `ls-tree` over the
same paths took 23 ms, and a full `ls-tree -r` of the ref 26 ms. The
pathspec form is the one taken, because it grows with the documents rather
than the tree. It is chunked at 8,000 characters under Windows' 32,767, and
its path arguments are literal, as the per-document call's were. The
installer's `--wide-docs` configures documents by the hundred, which is why
the count was the one the item feared.

Making that local partial copy needed a workaround.
`git clone --filter=blob:none file://...` silently makes a FULL copy
unless the source's upload-pack allows filtering, and a `-c` never reaches
it: git clears `GIT_CONFIG_PARAMETERS` for a local upload-pack. A
temporary `GIT_CONFIG_GLOBAL` holding `[uploadpack] allowFilter = true`
does. Check that an old blob is really missing before measuring anything on
such a copy.

**Exclusions, named rather than escaped.** A leading `!` and any `[`
became literals and matched nothing. The sweep then called such a pattern
"stale", which sends a reader to look for a directory. Both surveys that
apply `exclude_paths` now name the pattern as unusable and say which of
the two it is. The plan named the sweep alone; `--introduced-since` applies
the same exclusions and prints their counts. Phase 48 counted 0 of the 3
patterns anyone has written using either feature, so neither is supported.

**The installer asked git with the operator's environment.** A `GIT_DIR`
exported by a hook, or by a shell inside another repository, made
`detect._git` describe that repository while the installer wrote
configuration into this one. This was measured in a test before it was
fixed. `detect.py` now loads `git.py` by path, as it already loaded
`strata.py`, and starts git with its `environment()`. That also turns
`core.quotePath` off, so a non-ASCII document name now arrives as itself
and is pinned under it, where before it arrived quoted and was left out
and counted. Two installer tests changed for that reason. The quoted
branch stays for what quoting off still quotes: a double quote, a
backslash, a control character.

**Where a hang is named, and where it is ended.** The plan's
pytest-timeout had lost its premise: tranche 18 put `timeout-minutes` on
every CI job. What was still missing was the NAME of a hung test, and any
bound at all on a mutation campaign, which runs for hours unattended.

pytest's built-in `faulthandler_timeout = 60` gives the name. 60 is three
times the slowest test on any CI leg: 17.01 s on the Windows 3.10 leg under
`-n auto`, the worst of tranche 18's three runs (4.20 and 5.73 s in the
other two), rounded up.

`mutate.py` gives the bound. It times its green baseline and bounds each
mutant's suite at three times that, never under a minute. A suite that
outlives the bound is a kill, because it did not pass, but a weak one,
because no test failed. It is printed as `killed HUNG` and counted on
every campaign, zero included.

The plugin was refused on three counts:
- It is a dependency.
- `--strict-config` makes its ini key an error wherever it is not loaded,
  which includes the WSL recipe.
- Its Windows thread method ends a serial run whole, exit 1 with no
  `FAILED` line, which `mutate.py` would have counted as a kill it could
  not name.

**The line-numbering ledger.** The plan said ten sites and a grep said
nine; the syntax tree says twelve. A grep for `enumerate(...splitlines())`
cannot see `lines = text.splitlines()` a line above `enumerate(lines,
start=1)`, nor a file iterated. The twelve are:
- the eight `line_number_at`'s docstring named, the md-link site now in
  `links.py`;
- Phase 55's pair, the blanking loop and `code_lines`;
- the TODO scan in `collect.py`;
- the SARIF snippet in `report.py`. It iterates a file opened with
  `newline=""`, a third splitting rule, `\n`, `\r` and `\r\n` - LINE_BREAK's
  set.

The docstring counts them, and `tests/test_line_numbering.py` holds the
ledger.

**The replay's hand-read, written down and corrected.** CORPUS.md carried
the instrument's verdict on the 36 findings the diff gate would have
failed on, 0 resolving, but not the hand-read design.md recorded on
2026-09-21, because that read left counts and no labels. It was re-read
finding by finding and saved as one label each, so the figures render it.
Two verdicts did not survive, and 33 of 36 are dead as stated.
- Vitepress's two `[Notices](#notices)` are answered by `> ## Notices`, a
  heading inside the block quote the licence text is copied into. A
  renderer anchors it; `anchors()` reads `^#` and does not.
- One of moby's three vendored findings compares a library README's "Go
  1.23 or newer" with moby's own `go.mod`. The vendored copy has no manifest
  of its own, and the library's floor contradicts nothing.

The split of superpowers' 31 held exactly: 22 quoted, 6 in the document's
own prose about another workspace's commits, 3 the document's own claims.
Counted over the identity sweep, the block-quote class is 1 of 1,540
`dead-md-anchor` findings at HEAD (mkdocs), so it is recorded rather than
put in a tranche. The Precision table has a diff-scoped row now: 36 judged,
3 not dead as stated, 91.7 per cent.

**The 1,022 gitignored-path verdicts, re-counted before being classified.**
The figure was never saved: the path-index rows record `check-ignore` only
for resolved references. It reproduces exactly, 1,022 of 27,710 dead
references, but in 28 CLONES: 665 rows in 24 repositories once
de-duplicated. And the rows are every path a rule ASKED about, including
candidate spellings tried before it settled - a route's `.md` and
`/index.md`, and a root reading of a link that resolves from its own
directory.

Joined to the shipped sweep's own findings by document and line, 460 are
findings, in 18 repositories. 205 are probes: 166 whose citation resolved
elsewhere or was not reported, and 39 with no citing line at all. The 460,
read by class:

| class | findings | where |
|:---|---:|:---|
| build, install or checkout artefacts | 358 | babel 343 (two generated allowlists linking into a test-suite checkout under `build/`), vscode 7, superpowers 4, next.js 2, chatdev 2 |
| pages a docs build generates and a site serves | 38 | ruff 22, go 9, uv 3, autogen 3, OWASP 1 |
| a vendored copy missing its siblings | 46 | bun 32, node 14 |
| a file only on the author's machine, or another project's layout | 16 | lobe-chat 10, spec-kit 4, astro 1, qmk 1 |
| a wrong link an ignore pattern happens to match | 2 | rust 1, metagpt 1 |

The authoritative index would make these 460 read dead on a machine that
has built them as they do in CI. Three quarters of that is one repository's
generated test allowlists, and the population that would decide it is
still the one Phase 43 named: repositories with a docs build, measured on a
checkout that has run it, which pristine clones cannot be. Recorded as the
split, with the proposal left open and not built.

**Dropped, on the record's own reasons.** The `_fragment_sites` memo:
Phase 44 left it because "it reads the disk, its memo would need a
lifetime, and its second walk is 0.057 s". Building it would have added a
second disk-reading memo to `registry.forget_memos`, whose docstring says
exactly one exists, and the plan's `DocScope` form could not have worked:
`validate` builds its own `DocScope` and `count_examined` sees another.
**Carried by decision:** the fuzzer's FENCE oracle disagrees with the
Phase 55 scanner on a dedented closer inside a list item, and no generator
writes one.

**The gate.**
- Suite green here (1,439 and 8 skipped) and on Linux through WSL (1,446
  and 1).
- `python -m mypy`: no issues in 44 files.
- The mutation campaign is 327 anchors, all matching. The 24 this tranche
  wrote, retargeted or moved were each applied to a copy and watched
  turning the suite red.
- One needed a second version. The first no-newline-marker anchor replaced
  the marker's WORDS and survived, because `git apply` reads any line
  beginning `\ ` as the marker without reading the rest - some diff tools
  translate it. That is an equivalent mutant. Aimed at the condition that
  writes the marker, the anchor was killed.
- The corpus identity gate was predicted before the run BYTE FOR BYTE,
  every after-side output written from its before-side. 152 of 152 outputs
  differ: 139 by the partial note, and all by the NOTE split. Observed: 152
  of 152 byte-identical to the prediction. The first check reported 0,
  because the predictor split CRLF outputs on `\n` alone; fixing its line
  handling, and nothing it predicted, gave 152.
- The pre-push chain, from an extract of the working tree:
  - scenarios 25, with 213 of 213 assertions;
  - the fuzzer 0 property violations;
  - `--self-check` 23 of 23;
  - smoke, `--verify` and `--selftest` clean.

**The review of the built tranche, 2026-09-29.** Asked for after CI was
green on the three commits, as a code review and a gap audit against the
handoff's own list. Every figure in the records re-derived from its rows
(33 of 36, 91.7 per cent, 18.14 per cent, 460 in 18, 74.6 per cent, 1,447
tests, 77 files, 327 anchors) and every item traced to its change. Nine
findings, fixed in a fourth commit, each with a test that failed first and
an anchor. What each one teaches is the reason it is here:

- **A bound is only as good as what it waits on.** `mutate.py`'s
  `subprocess.run(timeout=...)` kills one process, and on Windows it then
  reads the pipes to their end - which comes when the LAST holder exits. An
  xdist worker is started with its own stdin and stdout and inherits
  pytest's stderr, so a worker stuck in the hung test held the harness's
  pipe forever, and `--parallel` on Windows - where the campaigns run -
  waited exactly as it had before the bound. The test that passed used a
  stub suite with no grandchildren, the one shape that cannot show it. The
  suite now writes to a file, which has no end to wait for, and the whole
  tree is ended: `taskkill /T` on Windows, a process group elsewhere. The
  red test starts a grandchild the way execnet does; the unbounded version
  took 90.9 s against a 3 s bound.
- **A fix owed to two callers was made in one.** The unusable-exclusion
  item named both surveys; the NOTE split, decided in the same tranche, was
  made in the sweep alone, and `--introduced-since` - the survey adopters
  run on every pull request - kept the sentence the sweep had just stopped
  printing. The reason text moved to `session.py`, beside `rule_applies`,
  and both surveys call it: the predicate and its explanation in one module
  cannot part. Two smaller errors went with it. The reason was keyed on
  `in_archive`, which the repository-scoped rules also declare False, where
  the fact is the rule's scope. And an entry rule that read nothing beside a
  primary document that WAS read means the document holds no dated entry,
  not that it is absent; the sweep's wording for the absent case is byte for
  byte the old one, so no corpus output moves. The sweep module fell from
  917 lines to 897.
- **Changing how a listing is quoted changes how it must be cut.** The
  installer split `ls-files` output with `splitlines()` and `strip()`. With
  quoting on, a name holding U+2028, U+2029 or U+0085 arrived octal-escaped
  and was excluded and counted; with it off, as `environment()` now sets
  it, the name arrived raw and was cut in two, and `--wide-docs` pinned the
  fragment - a `missing-document` finding the installer would have made up.
  git quotes any name holding a control character, so `\n` ends a name and
  nothing else can: the listing is cut there and not stripped.
- **The `.rst` fix had five readers, not three.** `--selftest` installed the
  status document's directory alone, and `--verify --suggest-fixes` built
  the status document's patch after the markdown default had been put back
  - with the last extra document's filename still installed. Both install
  the document as `--verify` does now, and `run_validate` puts back the
  document it was handed rather than a hard-coded markdown one.
- **One claim, one scanner, applies to a probe too.** Installing the right
  format in `--selftest` turned a FIRED into a DID NOT FIRE, and that was
  the finding. The four probes that share `probes.sub_group` took the first
  match in the RAW document, and all four checks read `prose()`. When the
  first match sat in a code block the probe corrupted an example the check
  never reads, and a working rule was reported as broken and failed the run
  - on plain markdown, before this tranche, whenever a document's first such
  claim was inside a fence. It stayed hidden because both halves read the
  same wrong text while the format was wrong. The probe now searches the
  prose and splices at the same offset, which `prose()` keeps by contract.
- **A verdict change is also a behaviour change.** Naming `[` unusable is
  right, and the CHANGELOG described it as a better diagnosis. But the old
  literal MATCHED a directory really named `[locale]` - Next.js and
  SvelteKit route directories are named that way - so a pattern that
  excluded documents now excludes none, and `--introduced-since` gates on
  them. Written down now, in the CHANGELOG and config.md, with `?` for each
  bracket as the spelling that still excludes them. Separately, a comment
  entry was named unusable; `_exclusion_regex` sets comments aside first,
  and the verdict now does the same.
- **A correction the handoff listed as owed was left half made.** design.md
  divided 1,022 by 27,677 in one section and by 27,710 in the next. Re-read
  from the rows: 27,677 is the 27,710 dead less the 33 case mismatches, none
  of the 1,022 is one of them, and the share is 3.69 per cent either way.
  Said beside the sentence now.

The review's gate:
- The suite is 1,455 tests: 1,447 and 8 skipped here, 1,454 and 1 on Linux
  through WSL. mypy is clean on 44 files.
- The nine new anchors were run in a campaign of their own on a copy: 9 of
  9 killed, none by the time bound, none overturned by the serial check.
  The campaign now stands at 336, all matching.
- The corpus identity gate was predicted BEFORE the run to move nothing:
  the corpus sets no `exclude_paths`, no clone has a primary document, and
  the probes, `--selftest`, `--suggest-fixes`, the installer and the diff
  gate are not in a sweep. Observed: 152 outputs compared, 0 differ.
- The pre-push chain, from a fresh extract, as before: smoke with no new or
  missing flag, scenarios 213 of 213, the fuzzer 0 violations,
  `--self-check` 23 of 23.

## What a zero means: a rule names its vocabulary, and off is a state

Phase 59, tranche 21 of the internals review, the scrutiny of pull request 13
placed. Its concern was a rule whose pattern nobody set for the project,
reporting `examined 0` in the voice of a project that makes no such claims.
Phase 57 settled half of it - a rule that read no document is said apart -
and left the other half: which zeros are about a PATTERN at all.

**What was measured, before anything was designed.** Four instruments, each
in extant-hardening (`m21_*.py`), outputs under `D:/repo/out-m21`:

- The current installer's derivation over the 39 visible benchmark rows (the
  11 holdout rows stayed sealed), read-only. All 39 leave at least three of
  the five claim patterns undetermined: `merge_claim` [unknown] in 39,
  `live_phrases` [default] in 39, `path_pointer` never observed in 39,
  `release_tag` [default] in 1. Every one of them ran on the shipped
  default - a commented-out key is an absent key - while the installer
  closed with "Rules with no pattern check nothing", false in 39 of 39.
  `phase_task` was [unknown] in 39 of 39, commented out, so the shipped phase
  pattern grouped every commit as "unknown": the failure DISABLEABLE's own
  comment names.
- The five keyed rules' own `examined`, on each chosen primary document
  under the config the installer renders: 0 in 39 of 39 for four of them,
  `dead-path-pointer` above 0 in 3. Cross-checked through the real CLI on
  three rows, identical. And 25 of the 39 primary documents hold no entry
  at all - 23 because `entry_prefix` was undetermined and the default
  `## Phase ` matched no header - where `--verify` said the entry rules had
  "matched nothing".
- The default live-phrase and branch-token vocabulary on the prose of 77,859
  tracked markdown documents in the 139 de-duplicated repositories: a live
  phrase in 3 documents of 2 repositories, a branch token in 44 of 18, both
  in one document 0 times; the default `merge_claim` 0 times. The agent tier
  alone (15 repositories, 28,573 documents): no live phrase, 8 branch tokens,
  both 0. The 229-repository scan in widening.md ("the live phrase 117
  times") could not be reproduced: that corpus was deleted after Phase 3,
  and it counted pattern hits, not what a rule reads. It was not used.
- The zero NOTE across the Phase 57d corpus sweeps, whose payload was
  byte-identical to main's: printed in 139 of 139, naming 1,115 zeros. 642
  belonged to rules keyed on a TOKEN SHAPE, which read no pattern anybody
  sets, so "the pattern does not match" could not be the reason. 334 were
  phrase-keyed rules on the shipped default, never set. 139 were
  `inconsistent-artifact`, OFF until a check is configured - neither
  explanation was true of it.

And `key = ''` for the five patterns, on one synthetic repository, had no
working meaning: `merge_claim`, `branch_token` and `release_tag` raised
`IndexError: no such group` in their rules on every run (`merge_claim` took
`dead-sha` down too, through the commit batch), `live_phrases` turned every
branch token in the newest entry into a live claim, and `path_pointer`
reported 256 examined on a 14-line document. No working configuration held
one, which is what made OFF safe to give it.

**What changed.**

- `Rule.settings`: the configuration keys a rule's vocabulary comes from.
  Six rules declare them - `false-merge-claim`, `stale-live-claim` (two:
  `live_phrases` and `branch_token`, which is why it is a tuple rather than
  the plan's single name), `unknown-branch`, `dead-path-pointer`,
  `dead-release-tag`, `inconsistent-artifact` - and seven declare none. A
  test reads every rule module and fails when what it reads and what it
  declares differ, and a ledger names the three shared modules that read a
  rule's vocabulary on its behalf (the commit batch, the patch generator,
  the probes).
- Where each setting came from, read off the file: the loaded settings carry
  `configured`, the keys the file sets, and `off`, a disableable key set
  empty or no `consistency` check. No `[extant.provenance]` table: the
  presence of a key and its value already say it, and a second home for one
  fact is how the wrong one gets read.
- Off is a state. `DISABLEABLE` gains the five claim patterns. An off pattern
  holds one that never matches, with the default's group count, because
  shared machinery reads these patterns for the rules and `commits.py`
  branches on the group count; None would have needed a guard at twenty
  sites in eight modules. That is a pattern matching nothing, installed on
  purpose - acceptable only because it cannot be silent: `rule_applies`
  does not run the rule, and every output names it. The sweep's repository
  pass and `--selftest` asked no predicate at all, so both now ask
  `rule_applies`; `--selftest` reports NOT RUN with the reason, which also
  settles the owed item (it probed entry rules on documents holding no entry,
  and would have counted an off rule as SILENT and failed the run).
- One classifier. `session.zero_note` words a zero of a rule that READ
  something by its cause - no pattern to set; a pattern set in .extant.toml
  (the two old explanations, now only where both can be true); the shipped
  default, naming the key - and `session.unrun_note` words the rules that
  read nothing, now including "switched off". `--verify`, `--check-text`,
  `--sweep` and `--introduced-since` print it, and an entry rule on a primary
  holding no entry is named as having read nothing in every one of them. A
  pattern that matches the empty string, or carries the wrong number of
  groups for its rule, is refused when the file loads, naming the key: 0 of
  41 existing configurations are refused (the defaults, this repository's,
  and the 39 installer outputs).
- SARIF says what the text says. It had computed its own list of blind rules
  from every zero, so it never learned Phase 57's split; it now carries the
  NOTE lines word for word, states an off rule as `ruleConfigurationOverrides`
  with `enabled: false` (SARIF 2.1.0, 3.20.5 and 3.50.2), and reports a rule
  that raised as an error notification on that rule with its exception and
  `executionSuccessful: false` - hard-coded true until now, so a consumer
  saw a clean run the exit code refused. GitHub code scanning reads no
  `invocations`, so this is for every other reader of the file.
- The installer tells the truth about what it could not settle. The design
  first proposed the plan's narrow form - "a key the installer marked
  unknown is off" - and a foolproofing pass reversed it, for two reasons.
  The installer derives a pattern from the document as it stands on install
  day and `/extant` writes entries after it, so off would silence every
  claim written later. And off does not fix the scrutiny's own reproduction,
  a false claim that work landed on `master`: it exits 0 whether the rule is
  off or on the default, and only derivation catches it, which the
  installer's detector does for "landed". So an
  undetermined claim pattern stays on the shipped default, and the file,
  the derived table and the closing advice say so - SHIPPED DEFAULT, OFF,
  NOT VERIFIED, LOW CONFIDENCE - with '' named as the way off. A [default]
  value is written commented too, so "set" means measured or hand-written;
  a repository with no branches no longer gets a third branch vocabulary;
  and the phase keys ARE switched off when no convention is found, because
  there the default did visible harm and `parse_phase` already said that was
  the intent. `phase_bare` is kept when the subjects say "Phase N.N".

**A vacuous test, found on the way.** `test_fuzz_findings.py` filtered the
sweep's STDERR for the zero NOTE, which a text-format sweep prints to stdout,
so its negative assertion could never fail. Found because rewording the NOTE
would otherwise have survived it; it reads stdout now and asserts the line
exists first. The new tests find every line by the phrase constants the
session prints them with, and assert it exists before asserting on it.

**Recorded, not built.**

- Installer guesses are not carried into the run: `branch_token` is guessed
  in 11 of the 39, `entry_prefix` in 16, and "set" means present in the
  file. A table that recorded each guessed value's hash, so an edit clears
  the mark, would carry it without drift. Not built: on those 39 primaries
  the rules those guesses feed examine 0 anyway.
- The NOTE as `::notice` annotations: GitHub caps annotations per step and
  at 50 per job, shared with the findings they would crowd out.
- A distinct exit code for a wholly vacuous run, as pytest's 5 is for "no
  tests collected": 0 of 139 sweeps were wholly vacuous, and it would fail
  a fresh install.
- `off` inside the `examined:` line: it would break every parser of that
  line; the NOTE and SARIF carry it.
- `stale-live-claim`'s gate is the whole entry: any live phrase in the
  newest entry makes every branch token in it a claim - seen on a synthetic
  entry naming a second branch "while here". Undocumented until now, and a
  precision question for a later bundle.
- Re-running the 229-repository scan needs clones, a network step.

**The gate.**

- The suite: 1,502 tests across 78 files, of which 1,494 pass and 8 skip on
  this machine. `python -m mypy`: no issues in 44 files.
- 357 mutation anchors match: 21 new, and 2 retargeted when the reasons
  moved into `unread_reason`. All 23 were run for real on a copy. 22 were
  killed in the campaign; one survived - "the did-not-run note keys entry
  scope on in_archive" - because its test used `inconsistent-artifact` as the
  repository-scoped example, and that rule is now off by default, so its
  reason never reached the scope branch the mutation breaks. The test uses
  `raw-lfs-blob` now, which declares no setting, and a rerun killed it.
- Identity: the after-side of the 152 visible corpus clones was predicted
  byte for byte before the run, from the Phase 57d outputs, whose payload is
  byte-identical to main's; 152 of 152 matched. Every output changed in the
  same three lines - the repository-rule count from 2 to 1, the zero NOTE
  split by cause, `inconsistent-artifact` added as switched off - and no
  finding and no `examined:` count moved.
- The pre-push chain, from an extract of the working tree: scenarios 213 of
  213, the fuzzer 0 violations over 35 repositories, `--self-check` 23 of
  23, `--verify` 0, `--selftest` 7 fired and 0 silent. Smoke failed first,
  and was right to: two of its probes had changed meaning under the
  load-time refusal. The "patterns that match nothing" probe wrote patterns
  with no capture group, refused now before any NOTE, so it is two
  observations - a well-formed pattern that matches nothing is named with
  its key, and a malformed one is refused, naming the setting. And the
  backtracking probe's pattern carried two groups, so it was refused before
  it reached a matcher while the probe went on saying "ok": its tolerated
  HANG flag simply stopped being raised, which the harness cannot see,
  because a tolerated flag is allowed to be absent. With one group the flag
  is back. Smoke then: 48 observations, 0 new flags, 0 missing.

**The review of the pull request, 2026-09-30.** A review of the two commits
above found twelve things, and the commit after them fixes all twelve. Five
were defects this tranche brought in, four were records or wording that said
more than the code did, and three were the shape this project keeps paying
for: one fact written in more than one place.

The five defects:

- The group-count refusal was stricter than any rule. `branch_token` and
  `release_tag` are read by group 1 alone, so a pattern with a nested group
  had worked, and refused it stopped every mode at load - `--collect`,
  `--archive` and the hooks, not only its rule. The smoke probe above that
  was rewritten to one group is exactly that shape, and would load again.
  The counts are a range now: `merge_claim` one or two, because its probe
  splices the last group; `path_pointer` exactly one, because the patch
  generator reads it with `findall`, which returns tuples past one; the
  other two at least one.
- The empty-string refusal asked `match("")`, which tries one position of an
  empty string. `\b([\w/.-]*)` passed it and reported 24 examined on a
  7-line document, the failure the refusal exists to stop. It asks the
  pattern's minimum width now, from the standard library's own regex
  parser - private in both of its spellings, `re._parser` from 3.11 and
  `sre_parse` before, chosen by version so the type checker, at its 3.10
  target, reads the second with no suppression. The 41 known configurations
  were loaded again through the new refusals: 0 refused.
- `--verify` and `--check-text` counted every rule and then named the ones
  that had not run, so a markdown rule on an rst primary printed
  `dead-md-link 1` beside a NOTE saying it read nothing. They count only the
  rules that read the document, as the sweep has since 2026-09-15: a rule
  that did not run is 0 in the `examined:` line.
- SARIF named rules it did not describe. The descriptors were built from the
  results, and a switched-off rule has none, so every
  `ruleConfigurationOverrides` entry referred to nothing (SARIF 2.1.0,
  3.52.4), and so did the `associatedRule` of a rule that raised. Both are
  described now and both references carry the index. The visible cost:
  `inconsistent-artifact` is a descriptor in every SARIF file from a
  repository with no consistency check.
- `--deleted-since` handed SARIF no NOTE and no rule errors. SARIF had worked
  out its own zero warning, so when it stopped, this mode lost the one it
  had. It says "no changed document was examined" again, and a rule that
  raised makes `executionSuccessful` false here as well.

The records and wording that said more than the code:

- "SARIF carries the NOTE lines the text printed" held for the zeros only.
  The shallow, partial and ancestry-bound notes, the parallel survey's
  fallback and `--check-text`'s missing path reached the text alone - on a
  shallow checkout, the one note that says what a dead SHA there means.
  Each mode gathers them before SARIF is rendered now, and prints them where
  it always did, so the sentence holds as written.
- `--introduced-since` said "--verify and --sweep run them" of every
  repository rule, `inconsistent-artifact` included, which neither runs
  while it is off. It lists only the rules they would run.
- The NOTE for a primary document holding no entry said "which has none" and
  stopped there. On this tranche's own measurement, 23 of the 25 installs
  with no entry had entries the default `## Phase ` did not match, so when
  `entry_prefix` is not set the NOTE now names it - "headed by the shipped
  default `entry_prefix` '## Phase '" - the lever the rest of this section
  gives every other zero.
- A comment in `--selftest` said its fifth count appears only when something
  is switched off. It appears in most runs, because `inconsistent-artifact`
  is off until a check is configured.

One fact in more than one place:

- `rule_applies` refused a rule, a second function worked out in words which
  clause had refused it, and the off test was written a third time for
  SARIF. `session.why_not_read` holds the clauses and their reasons
  together; `rule_applies` asks whether it returned None, and the off test is
  one function. A NOTE covering a whole run asks it at the one position its
  rules share.
- Three modes carried the same block of zero NOTE lines. `session.zero_notes`
  is that block now, and the three anchors that probed the copies each probe
  the set of rules that ran, which its mode hands in.
- `session.holds_entry` made a fourth reader of the newest entry, beside the
  two entry rules and their probe - one claim, one scanner, broken. The one
  reader is `newest_entry` in extant/entries.py now, and unifying them found
  a defect of the kind Phase 57 fixed in `sub_group`: the branch probe split
  the RAW text, so a first branch token inside a fence was the one
  corrupted, the rule read the prose, and a working rule was reported as
  DID NOT FIRE. The probe finds the entry in the prose and splices at its
  offset.

**The gate of the review.**

- The suite: 1,510 tests across 78 files, of which 1,502 pass and 8 skip on
  this machine; `python -m mypy`: no issues in 44 files. Eight tests are
  new. Five of the defects were reproduced on the tranche's head before they
  were fixed - the group refusal, the zero-width pattern, the rst count, the
  fenced probe and the zero-document SARIF.
- 357 mutation anchors match, 13 of them retargeted at the code that
  replaced what they named, and none added. The 13 were run for real on a
  copy: all 13 killed, none by the hang bound alone. The fuzzer's 23
  breakage anchors match.
- Identity, predicted before the run from the Phase 59 outputs: 0 of 152
  would differ, because the one sweep wording the fixes change is the lever
  after "which has none", and no corpus sweep reads a primary document -
  every one says "and none is here", so the entry rules never ran there and
  `newest_entry` could not differ either. Observed: 152 compared, 0 differ.
- The chain, from an extract of the working tree: smoke 48 observations,
  0 new flags and 0 missing; scenarios 213 of 213; the fuzzer 0 violations
  over 35 repositories; `--self-check` 23 of 23. `--verify` 0, and
  `--selftest` 7 fired and 0 silent.
- extant/config.py stands at the 927-line module ceiling and `run_sweep` at
  the 303-line function ceiling. Both were held by moving work out and by
  shortening comments this tranche had written, not by raising a number.

## The mutation campaign, made cheaper without moving a verdict

Phase 60. Two studies, on 2026-09-30 and 2026-10-01, asked how to run
`tests/harnesses/mutate.py` faster on the Windows machine where campaigns
run, without weakening what a verdict proves. Their throwaway scripts and
every log stay outside the repository, under `D:/repo/internals/Timings` and
`D:/repo/logs`, as the corpus instruments do. Each number below is one
laptop on one day.

**What a verdict needs, and what it does not.** A KILL is proved by one named
test that fails alone against the mutant (pytest exit 1) and passes alone on
the clean tree. Only SURVIVED needs the whole suite. Nearly every anchor is
killed, so trying first the tests a previous campaign recorded as killers -
a ledger - turns most anchors from minutes into seconds. The ledger may
choose the ORDER, never the verdict: a recorded killer that no longer fails
falls through to the whole suite. Reusing an old result without rerunning
it, as PIT's history file and Stryker's incremental mode do, would have
hidden both survivors this project has found. "slug keeps punctuation"
appeared because a different function began producing the same output, and
"the anchor rule resolves a cross-file target itself" (#190, below) because a
guard added 17 days after its test took the test over. In neither did the
mutated line or its killing test change.

A throwaway runner built that way settled all 357 anchors:

| Run | Wall |
|---|---|
| WSL, with no history | 19.0 min |
| Windows, confirming WSL's killers | 14.4 min |
| WSL, from its own ledger | 2.7 min |

Every run gave 356 killed and 1 survived. The harness as it stood, timed on
five anchors, needed 727 s for a serial baseline, 242 s per kill and 736 s
for the survivor: about 24 hours for 357, an extrapolation. That runner is
not in `mutate.py`. Building it in is the open item.

**Windows defines a verdict.** WSL ran the same suite in 27.7-47.7 s against
212-357 s natively, so it may FIND killers. A killer it finds counts only
once it has failed alone on Windows, and an anchor it reports SURVIVED is
re-decided by a Windows whole suite. The two platforms skip different tests:
Windows the symlink ones, Linux the case-folding ones. #190 can be seen only
where the filesystem folds case. 354 of WSL's 356 killers held on Windows,
the other two had Windows killers of their own, and no verdict differed.

**What the first study found in the harness.** Each fix had a test watched
failing first.

- **Stale bytecode.** CPython trusts a cached .pyc while a source keeps its
  size and its whole-second mtime (bpo-31772, still open). 13 anchors keep
  the size. Written and restored inside one second, a mutant was never run
  in 29 cycles of 50, and the restored source ran the mutant in 21. Every
  rewrite now goes through `write_source`, which sets a strictly later
  whole-second mtime. Only minutes-long suites had kept this latent, so
  anything that makes a campaign faster would have exposed it.
- **A carriage return in a node id.** `_FAILED_NODE` kept the `\r` a Windows
  console ends a line with, whenever pytest had no room for the message: 84
  per cent of this suite's ids. The `--parallel` rerun-alone then exited 4,
  not 1, and every such kill paid for a whole serial suite as well. On five
  anchors `--parallel` took 42.4 minutes against 40.5 serially, and 25.0
  after the fix. Its "overturned: 0" was true and said nothing.
- **#190 SURVIVED.** The mutation swaps `resolve_reference` for a bare
  `is_file()` in the anchor rule. Its test, written with it, asked about a
  file outside the repository, and Phase 54's read guard (`inside()` in
  `_target_anchors`) now refuses that file on its own. The guard fixed a
  different defect and quietly took the test over. The mutation still
  changes CASE: on a case-folding filesystem the mutant judges
  `[x](readme.md#nope)` against `README.md`. A test now pins that a
  case-only mismatch is left to `dead-md-link`. It can fail only where the
  filesystem folds case; on Linux it passes against the mutant, as its
  docstring says.

**What the second study found: the cost is per process.** One instrumented
run of the suite started 8,370 git processes:

- 6,042 started directly by the tests or the tool. 4,222 of those built
  fixture repositories (831 s inside git), against 1,820 that asked the
  questions under test (116 s).
- 1,580 more were `git maintenance run --auto` children of `commit`.

On the first study's Windows run, 354 ledger kill checks took 1,198 s, of
which their killing tests took 420 s. The rest, a median of 2.1 s per check,
was pytest starting, collecting, building fixtures and cleaning up. Four
changes take that down, and `mutate.py` makes all four itself
(`child_environment` and `run_suite`):

- **Plugin autoload off.** The suite needs no plugin, and importing the
  operator's cost 0.44 s per pytest start. `--parallel` names
  `xdist.plugin`, because without autoload `-n` is a usage error.
- **No auto-maintenance.** `maintenance.auto=false` is appended to the
  operator's `GIT_CONFIG_COUNT` by the rules `environment()` in
  extant/git.py follows. In a test-sized repository the maintenance child
  never acts (`gc.auto` wants 6,700 loose objects): 60 commits and 60 tags
  leave the same repository shape with or without it. A commit took 95 ms
  with it and 60 ms without. The detached child also writes inside `.git`
  while a fixture is being removed, which other projects disable it for.
- **The real git on Windows.** Git for Windows' `cmd\git.exe` is a launcher
  that sets a few variables and starts `mingw64\bin\git.exe` as a second
  process: 59 ms against 33 ms per call, about 6,000 calls per suite. A
  campaign started from PowerShell got the launcher; Git Bash puts the real
  binary first. When the first `git.exe` on PATH is a launcher, its
  `mingw64\bin` and `usr\bin` now go first, with the `MSYSTEM` and
  `PLINK_PROTOCOL` the launcher sets (from `git-wrapper.c`). That also puts
  `sh` on PATH, so a PowerShell launch no longer reads as an already-red
  suite.
- **A temp root per run.** pytest keeps its three newest `pytest-N`
  directories, and the next process to EXIT deletes the oldest. After a
  whole suite that was 36-65 s, inside whichever run exited next, a single
  kill check included. Each run now gets its own `--basetemp`, removed on a
  thread afterwards. Git writes loose objects read-only and Windows' `rmtree`
  refuses them (WinError 5), so the removal clears the bit and retries. With
  `ignore_errors` the refusal is silent: a measuring script written that way
  left 6,074 files of every whole-suite tree behind, and looked cheaper than
  it was.

Measured together, against the same commit on the same evening:

| Run | Before | After | Change |
|---|---|---|---|
| 60 kill checks, serial | 165 s | 112 s | -32% |
| The whole suite, `-n auto`, mean | 406 s | 281 s | -31% |
| A whole ledger-driven campaign, 357 anchors | 1,700 s | 1,160 s | -32% |

The suite row is the first three changes with longest-first ordering
(below); the campaign row is all four with it, the temp root reaching only
its whole-suite runs; the checks row is autoload, maintenance and git. Both
campaigns gave the same verdicts and the same killers. None of the four
can move a verdict unseen, because the baseline runs in the same
environment. A test that depended on any of them would show as a red
baseline.

**Measured and refused.**

- **More xdist workers.** `-n auto` is 6 here, not 12: with `psutil`
  installed xdist counts physical cores. At `-n 8` every test got slower and
  the wall did not move.
- **Handing out the longest files first.** Under `--dist loadfile` xdist
  orders files by how many TESTS they hold. Replaying its scheduler on
  measured durations, longest-first saves 1-5% at 6 workers and up to 22% at
  12. Not built while campaigns run at 6.
- **An empty git template.** No measurable gain, and the hook tests would run
  on a repository shape no user has.
- **`core.fsync=none` and `GIT_CONFIG_NOSYSTEM`.** No effect.
- **Reusing a result whose dependencies did not change.** File-level test
  selection (Chen and Zhang, ICST 2018) is the one form of reuse that
  survives both counterexamples above. It still lets history decide a
  verdict, so it was refused.

**The next limit is the machine.** Defender used 1.2 to 1.8 cores on
average during every suite run, about a fifth of all the CPU the suite
used. Free
memory fell below 900 MB in 11 runs of 16. Both are the operator's settings,
and neither was changed. Microsoft names a Dev Drive's asynchronous
performance mode as the safer lever than a folder exclusion.

**A killer that reads the checkout is not a stable killer.** #7, "the
ancestry index is unbounded again", was recorded as killed by the
`as-checked-out` arm of the spawn-budget test, which runs `--verify` against
the checkout itself. On a fresh clone it passed against the mutant, and the
whole suite found `test_a_hit_is_proof_and_a_miss_asks_only_past_the_bound`
instead. The ledger ordered the work and the whole suite decided, as
designed, and it cost one whole suite. Three more entries had leaned on the
same test. For each, the suite was run against the mutant without it, and a
killer built on a fixture was found and certified. That also showed one
docstring had outlived its claim: the spawn-budget test is no longer the
only test that sees the run's scope dropped from `--verify`. A ledger should
prefer killers built on fixtures.

**The gate.**
- 1,521 tests across 78 files, of which 1,513 pass and 8 skip on this
  machine; `python -m mypy` reports no issues in 44 files.
- 8 tests are new for the environment, each watched failing first, and 3 for
  the first study's fixes. The harness tests pass on Linux (WSL) with the one
  Windows-only test skipped.
- 357 anchors match, and none was added: the changes are in the harness,
  which no anchor targets.
- `mutate.py --parallel`, launched from PowerShell with nothing prepended to
  PATH, ran a green baseline and killed both anchors it was given, #190
  included. It restored the source and left no temp root behind.

## CI, made cheaper without moving a verdict

Phase 60, the same day as the campaign above and the same question: how much
of a run's time does a verdict actually need? A run took 6 to 7.5 minutes and
50 to 56 job-minutes, and was always exactly as long as its slowest job: the
Windows fuzz job or a Windows test leg. On `a0d85d8` it took 3.1 minutes and
1,913 job-seconds, with every job, matrix leg, Python and check kept.

**Measured before anything changed.** Pull request #24 added only
instruments. Each test leg prints every git on PATH with its size, the cores
and the temp directory; the fuzz legs print theirs under Git Bash and run
the harness with `-u`, so each repository's cost is in the log. They showed:
- The Windows test legs started `Git\bin\git.exe`, a 43,352-byte launcher
  that starts the real git as a second process (59.7 against 33.3 ms a call
  on the development machine). Git Bash already put the real one first for
  the fuzz job.
- Every runner has four cores.
- Windows TEMP was on C:, the image's system drive, while D: holds the
  workspace.
- A Windows fuzz repository cost 2.3 to 18.9 s, and the 35 took 362 s one
  after another.
- `fuzz.py --self-check` spent 181 of its 206 s on the HANG breakage alone.
- Python 3.9 on Windows spent 31 of its 46 s of setup in python.org's
  installer.

**What changed, and why none of it can move a verdict.** Each change is one
commit in pull request #25, and its reasons sit beside it in
`.github/workflows/tests.yml` or in the module it touched.
- **The HANG breakage's red half runs under `red_budget`**, in
  `tests/harnesses/fuzz_selfcheck.py`: three times the clean half of the
  same pair, never under 10 s nor over the corpus's 90.
  - The clean half keeps the full budget, so a slow machine cannot make it
    fire. Only a red half that did NOT hang could be cut short, and the
    margin against that is about six times a healthy run.
  - The step went from 201-206 s to 38-46 s, with 23 of 23 properties still
    going red.
- **`fuzz.py --jobs N` builds and checks repositories side by side.**
  - Every plan is drawn first, in order, from the seed, so the corpus is the
    same however many run at once.
  - Results print in plan order, and everything a worker touches is its own
    index's directories, so the output does not depend on N: 77 identical
    lines locally with one job and with four, and in CI 76 per leg
    identical to the serial run's.
  - The Windows job went from 375 s to 114-154 s.
- **No automatic git maintenance**, in the runner's global config in the six
  jobs that build repositories. In a test-sized repository it never acts.
  Global config rather than `GIT_CONFIG_COUNT`, so the environment the tool
  and its environment tests see is the runner's own. The remote fast path
  was checked not to decline on a `[maintenance]` section.
- **The Windows test legs run with the real git first**, as
  `child_environment` in `tests/harnesses/mutate.py` arranges it - the
  launcher's two directories, MSYSTEM, and PLINK_PROTOCOL when unset - **and
  with TEMP on `RUNNER_TEMP`** rather than C:. The binary is the same; the
  shipped package and the installer read neither MSYSTEM nor TEMP; and every
  Windows leg kept its 4 skips and its pass count.
- **Python 3.9 on Windows comes from python.org's NuGet package**, not its
  installer.
  - 3.9.13 is the last 3.9 python.org built for Windows. Its NuGet binaries
    are byte-identical to python.org's embeddable zip, and the SHA-512 NuGet
    publishes is pinned.
  - The step does everything setup-python's install script does except run
    the installer, and a later step fails unless setup-python used its tree.
  - Setup on that leg went from 44-54 s to 16 s.
- **The 3.13 leg runs its file-order and shuffled suites side by side**,
  both still serial, with separate temp roots: 187 s became 100-104 s.
- **The test legs install `requirements-test.txt`**, which holds what the
  suite needs. `requirements-dev.txt` includes it and adds coverage and
  mypy, which no test imports.
- **Two fixture histories are copied rather than rebuilt.**
  - `tests/test_ancestry_bound.py` built the same history in 18 tests; that
    file went from 52-56 s to 16-18 s serially.
  - `make_repo` in `tests/test_install_presets.py` copies its initialised
    project; its gain is inside that file's noise.
  - A test guards each template by comparing a copy with one built the long
    way. The history is compared as a set of commits, because its branches
    commit within one second and `git log --all` can list two builds of it
    in different orders.

**Decided.** The Windows test legs run in the environment Git Bash gives the
suite - the real git first, MSYSTEM set, temp on D: - and not the one an
adopter's PowerShell gives it. `AGENTS.md` says so, for anyone reproducing a
Windows failure. The system-config walk is pinned for both layouts in
process, by `tests/test_remote_from_disk.py`.

**Measured and refused.**
- **More jobs or shards.** The twenty jobs are the Free plan's concurrent
  limit, so more would queue rather than run.
- **The Linux legs under `-n auto`.** The serial run is the definition of
  correctness.
- **Path filters, or selecting tests by what a change touched.** Either lets
  history decide a verdict.
- **`--dist load` on Windows.** It gives up the per-file isolation
  `AGENTS.md` chose `loadfile` for, which "CI honesty" above already
  refused to trade.
- **`git fast-import` for fixtures.** It writes packs, and two test files
  work on loose objects.
- **A template for the partial-clone fixture.** Its clone writes its
  source's absolute path into its config.
- **uv's standalone builds for 3.9.** They are a different build from the
  one the leg exists to run.
- **Caching the installed 3.9 with actions/cache.** It keeps the exact tree,
  but restores of many small files on Windows runners are reported in tens
  of seconds. It was not measured, since the NuGet route measured about
  10 s.
- **A Dev Drive for TEMP.** pip's own CI measured it slower than plain D:.

**Still open.**
- The maintenance setting's effect in CI is unmeasured, because one
  Windows runner varied more than it can move: an unchanged fuzz step took
  98 s on one run and 132 s on the next.
- No CI leg now starts git through the launcher an adopter's PowerShell
  resolves.
- The Windows legs no longer run under the system drive's long, short-named
  temp path.
- The 3.9 leg depends on nuget.org, and fails on purpose the day the image
  carries 3.9.
- `--jobs` was checked against a serial run on one seed.
- Each job's `timeout-minutes` waits for five runs under the change, by the
  workflow's own rule.

**The gate.**
- Locally: 1,537 tests across 80 files, of which 1,529 pass and 8 skip;
  `python -m mypy` reports no issues in 44 files; 359 anchors match.
- Against a `git archive` extract: smoke clean, scenarios 213 of 213, and
  `fuzz.py --self-check` 23 of 23.
- `--verify` exits 0 on the checkout and on a clone holding only `main` and
  the pull request, and `--selftest` leaves no rule silent.
- CI on `a0d85d8`: 21 of 21 checks green.

## The 2026-10-01 audit: thirteen repairs, two of them measured first

An audit of the whole package on 2026-10-01, Phase 61, covered every shipped
module in full except the code-block, anchor and site-detection readers, and
fuzzed those three instead. Its ledger is outside the repository, beside the
earlier reviews', under `D:\repo\audit-20261001\`. Each repair below was
written against a test that failed first, and each carries a mutation anchor,
except the one line of CI configuration (AUD-11), which only a CI run can
check.

**Two fuzzers found nothing, and that is recorded as a result.** 20,000 random
documents went through the pure readers: fences, lists, quotes, HTML, MDX,
links, CR-only and mixed endings, and the Unicode separators. None raised, and
every blanking kept its length. 400 more went through every rule, its
denominator and its probe, under seven paths. None raised either. The one slow
shape was a line of 20,000 `[a](` openers, at 2.8 s. That is the bounded
quadratic `MD_LINK` already records.

**Nine of the repairs share one root cause.** In each, one reader of a
thing learned a lesson that a sibling reader of the same thing had not. The
other two are crashes found while making them.

- **A configured document `--verify` cannot decode is a finding, not a
  traceback** (AUD-1). The primary document's read reported this. The
  archive's read and every extra document's did not. A UTF-16 CLAUDE.md,
  which is what PowerShell 5.1's `>` writes, ended the run with a traceback.
  So no denominator after it printed, and a machine format emitted nothing.
  Both reads now go through one reader, and an undecodable file gets the
  `missing-document` finding a refused one already got.
- **The post-commit hook stopped calling a failed run "0 unverified
  claims"** (AUD-8). Every non-zero exit was read as findings. An unreadable
  configuration (exit 2) therefore printed "has 0 unverified claim(s)" above
  the first five lines of its error. A crash printed the same sentence above
  its denominators, and the traceback's last line was cut off. That was the
  line naming the cause. Exit 1 with findings is reported as before. Anything
  else is now called a check that could not finish, and the hook shows the
  end of the output instead of the start.
- **The archive pointer sits at the entries' own heading level** (AUD-2).
  It was a fixed `## ` header, and it was recognised by `pointer_prefix`.
  With `### ` entries, which the installer derives from any heading from
  `#` to `####`, the pointer was no section of its own. It stuck to the
  oldest entry kept and rode into the archive with it, one stale block per
  run. A configured `pointer_prefix` was never the header actually written,
  so it was never stripped either, and the pointer stacked in the live
  document. `Config.build` now derives the header, and the default gives the
  same `## Archive pointer` as before.
- **`--deleted-since` reads an old version under its own path** (AUD-4). It
  had installed only the format. A rule keying on which file it reads
  therefore read None for every old version.
  `manifest-floor-mismatch` could report no removed claim at all. This is the
  shape `AGENTS.md` records for `--sweep`, in the third survey mode.
- **`code_suffixes` is read** (AUD-5). It was parsed, type-checked and
  documented, and nothing read it: the TODO scan used a hard-coded copy of
  its default.
- **Two memos carry the document path** (AUD-6). The link and path-pointer
  memos compute over the blanking, and since 2026-09-22 the blanking has read
  the path: `.mdx` has no indented code. One text object read as `.md` and
  then as `.mdx` was answered from the first reading. That cannot happen
  through the CLI, where every document is its own object. It can through the
  library API.
- **The installer escapes the strings it writes** (AUD-7). A `"` in a
  detected header or in a refname wrote a configuration that does not parse.
  A backslash parsed into a different value.
- **The pointer half of the patch invariant has a test and an anchor**
  (AUD-9). This was the third open lead of the 2026-09-12 review.
- **`tests.yml` states `contents: read`** (AUD-11), as `publish.yml` already
  did. The repository's default was read-only when this was written, so
  nothing moved.
- **The target repository's unreadable configuration exits 2, not with a
  traceback** (AUD-13). The shim catches a bad file at IMPORT, which is the
  target's own file only when the tool is installed in it. `main()` re-reads
  the target's file from `--repo`, and nothing caught that read. The console
  script takes that path, and it is what pip, the pre-commit framework and
  the GitHub Action run. So a malformed `.extant.toml` came out as a
  traceback and exit 1, which CI reads as findings.
- **A blank `entry_prefix` is refused by the loader** (AUD-12). The section
  header takes the prefix's first word, so an empty one raised IndexError at
  import, on every run, instead of the ValueError that names the key.

`config.py` was at its 927-line ceiling. The pointer derivation went in only
after the TOML error hints moved out, byte for byte, into
`plugin/skills/extant/payload/extant/config_errors.py`. Their anchor moved
with them.

**Two more were measured over the corpus before they were built**, because
each changes what a user receives. The measurement changed one of the designs.

- **`--sha-map` and what `dead-sha` does not report** (AUD-3). The
  translator skipped only backticked spans. The scanner also skips URL,
  UUID, asset-name, pinned-ref and foreign linked-commit hex, so the
  translator rewrites a population the scanner never reports.
  - **The plan was to stop translating that population.** The measurement
    refused it. `a3_translate.py` in the measurement apparatus classified
    every token the translator considers, over 82,802 documents of the
    visible corpus. It then asked which tokens a full-history map of each
    clone would rewrite. On every document it agreed with the rule's own
    scanner about which tokens are reported.
  - **Most of the wider population is wanted.** 87,585 tokens sit in URLs
    to the repository's own commits. That is the URL behind a changelog
    link whose text the scanner reads, and a repair has to move the two
    together. 5,363 more are in code blocks, and 528 are astro changeset
    ids, which turned out to be commit ids.
  - **No shape the scanner calls "never a commit" lost anything.** Only 1
    asset name was rewritten, and it was axe-core's own permalink, whose
    path ends in `.js`.
  - **Links to other repositories are a mix git cannot separate.** About
    513 tokens name a renamed repository's own commits (node's io.js,
    unraid's old name) or its own source browser. About 169 name an
    absorbed upstream's commits (moveit, rust-clippy, acorn), where the old
    id still works upstream and a rewrite breaks a working link.
  - **What shipped.** A UUID group is never translated, matching the
    scanner: 1,282 in the corpus and none translated. A rewrite inside a
    link, URL or pin that names a repository other than origin is still
    made, as before, and `--sha-map` names its lines for the person
    applying the map. Its regression gate, `a3_identity.py`, ran the old and
    the new translator over all 82,802 documents under that map: 181,562
    rewrites in 1,100 documents, and not one document's result differs.
    677 rewrites were named. 674 are the other-repository tokens the
    measurement predicted. The other 3 are URLs whose repository cannot be
    read off them: two of node's typo'd `/comit/` and `/commi/` links and
    one `raw.githubusercontent.com` permalink.
  - The rewrite-map reading left `commits.py` for
    `plugin/skills/extant/payload/extant/rewrites.py`, byte for byte, when
    this took that module past its ceiling.
- **A SARIF run over 25,000 results is rejected by GitHub code scanning**
  (AUD-10). GitHub's documentation says a file whose objects exceed their
  maximum "is rejected", and it allows 25,000 results per run. The
  2026-09-12 handoff had read that as truncation.
  - **The population.** Over the 152 visible clones, one run exceeds the
    limit: bazel's sweep, at 40,868 results. Every one is a non-gating
    note, and 39,519 are in per-release snapshot copies. Its upload
    reached code scanning with nothing. The run is 0.95 MB gzipped, so the
    10 MB size limit is not the one that binds.
  - **Splitting is no way round it.** Since July 2025 GitHub refuses runs
    in one upload that share a tool and a category. Separate categories
    would move alerts between them as the split shifts.
  - **What shipped.** Past the limit the run keeps the findings that gate,
    then ordinary documents, then the other strata in the reverse of their
    precedence, in the order they were found. It says what it left out, in
    a notification, as `properties.omitted` and on stderr.
  - **bazel after the change.** The run keeps 25,000 results, in their
    original order, at 0.53 MB. All 366 ordinary, 5 historical-record and
    186 generated results are kept. 792 vendored and 15,076 version-snapshot
    results are dropped.
  - **Every other run is unchanged.** The next three largest, PX4 at 4,466,
    node at 3,720 and kubernetes at 2,616, are byte-identical before and
    after.
  - **`sweep.py` is now one line under its 927-line ceiling.** The sweep's
    NOTE travels through `_survey_notes` because `run_sweep` was already at
    its 303-line function ceiling. The next change to that module splits it
    first.

## The gap audit of that audit: five repairs, one of them a deletion

On 2026-10-02 the audit's own work was audited for gaps. It asked three
questions. Was each claim true of the code actually there? Did each repair
reach every reader of the thing it repaired? Did a test or an anchor hold
each changed path? Its write-up is `GAP-AUDIT.md`, beside the ledger outside
the repository. It found eight gaps, and a ninth while repairing the second.

**`--archive` deleted a section a person wrote, and exited 0.** This predates
the audit, and it is the worst defect either pass found, in the one place
this package writes irreversibly.
- **The trigger.** The archive pointer was recognised by its header alone:
  any section starting with `pointer_prefix`. Under the default prefixes
  every `## ` heading is a section, so one headed "## Archive pointer
  format" was the last run's pointer.
- **Why the guard stayed quiet.** The section was stripped from the live
  document and written to neither file. The conservation guard is told to
  subtract the stale pointer's lines from its baseline, so it subtracted
  these too.
- **The repair.** `_is_pointer` in `entries.py` asks for the header AND,
  under it, nothing but the one generated line. That line has been worded
  "Entries older than the newest N live in ..." since the first commit, so
  no pointer this tool ever wrote is missed. One function writes the line
  and one pattern reads it, side by side.
- **The pattern accepts any count but only this archive's name.** A count
  can be negative, which the loader accepts. The name is escaped rather
  than matched by `.*`, because a greedy match took a line a person had
  extended past the generated sentence for the generated sentence. A
  pointer naming an archive since renamed is kept, which is visible.
- **A pointer somebody added a line to** is now kept as their section, and
  the next run writes a fresh pointer beside it. That is visible, and
  stripping it had deleted the line.

**The same reader repaired the gap it was found under.** `split_entries`
classified a section by `entry_prefix` alone. AUD-2 derives the pointer from
the entry prefix's first word, so under a non-heading prefix such as
`Phase ` the pointer is `Phase Archive pointer`, which starts with the entry
prefix. It was counted as an entry by `--search`. After a
`retain_entries = 0` archive it was the newest entry the live-claim rules
read; at HEAD that document had none. A pointer is now "other" before it can
be "phase".

**A third memo of AUD-6's shape.** `_POINTER_SITES` in
`rules/line_pointer.py` blanks through `prose`, which reads the path. Its key
held the text, the repository and the format, and its comment argued those
were everything it read. AUD-6 had given the path to the two memos beside it.
Reachable through the library API only, as theirs were.

**`code_suffixes`, live since AUD-5, is checked.**
- A value without its dot matched no file, so the bundle read as a tree with
  no TODOs. The loader now refuses one, echoing it through `ascii()` for a
  cp437 console.
- A changed code file the scan cannot read is listed under the bundle's
  `todos_unread`, with why, where it used to be passed over in silence.

**Four lines held by nothing.** Each was removed by hand on a clone and the
whole suite run, and all four survived:
- the stderr NOTE of the SARIF limit in `--verify`, `--introduced-since` and
  `--deleted-since`;
- the check that says the cut once in the file.

The behaviour was right when run by hand. One test over the three modes now
holds it, and four anchors name the lines.

**Verification gaps, closed by measuring.**
- **The SARIF corpus check.** It had run before the `--sha-map` code landed.
  Re-run on the final tree, it is identical: the three repositories under
  the limit match HEAD byte for byte, and bazel matches the first
  measurement.
- **CI's orders.** Its Linux legs run serially and once shuffled, where the
  audit had run only in parallel. Both orders are green.
- **Refusals.** Every configuration key was given eight wrong values through
  `main()`. All 240 were refused cleanly or accepted, with no traceback.

**What a release note owes, and an upgrade.**
- **Exit codes moved.** A malformed `.extant.toml` on the console-script
  path, a blank `entry_prefix` and a dotless `code_suffixes` each exit 2;
  the first two were a traceback and exit 1.
- **Upgrading from 0.29.0.** A project whose entries are not `## ` headings,
  and that has archived, holds one `## Archive pointer` block glued inside
  its oldest kept entry. That is where 0.29.0's fixed header landed. The
  next archive run carries it into the archive with that entry, once.
  Nothing is lost.
- Phase 61 in `NEXT_SESSION.md` lists the rest.

## Six invariants held as properties: two defects, and the generator that decides what a property can find

The internals review's 9.2 row named Hypothesis, and the plan gave it the
invariants the package states about every input rather than about the cases
somebody wrote down. Phase 62 holds six of them in `tests/test_properties.py`:

1. `strip_code` and `prose` keep every offset: same length, same breaks, every
   character either the original or a space, and `strip_code` blanks all
   that `prose` does. Markdown with no path, `.md`, `.mdx` and
   reStructuredText.
2. The two line numberings agree: `line_number_at` with `splitlines()` at
   every offset except the `\n` of a CRLF, and with `line_breaks` everywhere,
   the eight breaks only `splitlines()` honours included. The plan expected
   a bare `\r` to need excluding; it does not - both read it as a break.
3. The `exclude_paths` matcher agrees with `git check-ignore`.
4. `percent_decoded` undoes percent-encoding, and leaves a target with no
   escape exactly as written. Mostly the standard library's behaviour; kept
   because it costs a second and rides every Python leg.
5. `group_parallel` is a partition, each group one rule, one stratum, one
   side of `primary`, with one path segment allowed to vary.
6. Every SHA-shaped run in prose is examined by one of the two scanners in
   `extant/commits.py`, or skipped for a NAMED reason - the scrutiny's
   "0 unaccounted".

**Two defects, in the pilot runs, that 1,566 example tests had not found.**
- **A finding grouped with itself.** A path segment that is literally `*`
  made the key wildcarding that segment equal the key keeping it, so the
  finding was filed twice under one key. `*/a.md` printed as "2 occurrences
  in 1 document" over `*/a.md:3, 3`. git tracks such a name wherever a
  filesystem holds one; Windows cannot check one out, and none of the 152
  corpus sweeps names one. Repaired by filing each key once.
- **A `**` that crossed separators where git reads a `*`.** git's wildmatch
  treats a run of stars as "any depth" only where a `/` or an end bounds it
  on both sides - `**/x`, `x/**/y`, `x/**`, and a bounded `***` - and as
  one `*` everywhere else. The matcher let every `**` cross. Asked of git
  2.53 directly, seven of the eleven shapes recorded disagreed: `a/**b` took
  `a/x/b`, `a**b` took `a/b`, `aa**/a` took `aaa` and missed `aa/a`, `/**a`
  took `b/a`, `a**/a` missed `a/a`, and `***/b` and `a/***/b` missed `b` and
  `a/b`. One cause. No configuration
  this project knows of writes any of them. config.md said "`**` spans
  them" and that every row agreed with git; both were true only of the rows.
  The repair needed room `sweep.py` did not have - 926 of 927 lines - so the
  matcher moved first, byte for byte, to `extant/exclusions.py` (sweep.py
  796). A candidate rule was explored against git before it was built: three
  random runs of 400 examples, up to 24,000 patterns, 0 disagreements.
- **One divergence documented, not changed.** The matcher trims spaces from
  both ends of a pattern and git trims only the trailing ones, so `" docs"`
  excludes `docs` here and names a space-prefixed directory to git. The plan
  had called it documented; config.md did not say it, and now does.

**The generator decides what a property can find.** The first generator for
the matcher drew paths independently of each pattern. It ran 300 random
examples without building one defective shape, and as a derandomized,
CI-sized set it stayed green at every budget tried. It found the class only
at 1,000 random examples a run - three runs, three reds - with `x` and `xb`
added to the names it drew paths from, which is how the defect was first
seen. Paths built FROM the pattern - every star run and `?` replaced by a
fill that may or may not cross a separator - found it in a derandomized set
of 25, which a suite can afford. The blanking property met the same thing:
generated as strung-together fragments it never put a `>>> ` at the start of
a line ending in CRLF, so a breakage of the rst loop's terminator handling
stayed green; generated as lines, it went red. So every strategy in the
module says where it aims and why.

**A property was watched failing before it was trusted.** Nineteen
breakages of the code the six guard were tried, each against the property
module alone. Sixteen turned a property red. Of the other three, one was
the rst doctest breakage above, red once the generator built lines; one was
equivalent - `normalise_remote` never answers None for a link's head, so an
unsettled origin cannot read a link as ours; and one changed nothing a
property claims: `prose` blanking inline code as `strip_code` does keeps
every offset, and what `prose` keeps is the example tests' question. The
seventeen red ones then ran against every OTHER test in the suite, the
property module left out, each kill confirmed alone:
- **Six survived, so only a property catches them**, and each is now an
  anchor in `tests/harnesses/mutate.py`: a `?` that crosses a separator; an
  rst doctest line that rebuilds its terminator; a `+` in a link target
  decoded as a space; a group's findings not sorted by line; one document's
  groups not sorted by their first line; a hex run one character longer than
  an object name read as a commit.
- **Eleven were already caught by an example test**, the two repairs'
  reverts among them - pinned since by the two example tests written red
  first beside each repair, and kept as anchors because they are the
  defects. The line-numbering properties have no breakage of their own that
  the example tests miss: `tests/test_line_numbering.py` already soaks every
  offset of 300 seeded texts, and both properties went red against both
  breakages tried there.

**The sixth, over the corpus.** The model the property holds the scanners
to - written from their docstrings, one name per skip the code makes - was
run over the corpus too (m22_sha_reasons.py in the measurement apparatus):
139 repositories de-duplicated, 82,912 documents, 138,175 prose lines with a
run of seven hex characters. The scanners examined 94,918 tokens, 72,368
backticked and 22,550 bare, and every other token had a name - 0
unaccounted. The largest names: inside a URL 102,977; longer than a full
object name 9,925; a bare number 4,715; part of a longer code span 3,953; a
commit link to another repository 2,342; part of a UUID 1,292. The scrutiny
listed five reasons. The corpus run named sixteen; the property names
twenty, telling a relative commit link from one to another repository on
both sides, and adding the two the corpus never showed. One is a backticked
word spelled in hex. The other is a run joined to a non-ASCII word
character: `\w` is Unicode, so a commit id written
against Chinese text with no space between is no token at all - neither
examined nor skipped. Named rather than changed: 0 such lines in 82,912
documents is no evidence for a widening, and a property with one non-ASCII
character in its alphabet finds the class at once, so it is held.

**How they run.** Derandomized and without a database: the `ci` profile
`tests/conftest.py` derives from Hypothesis's own, with a budget of its own.
That is the fuzz job's fixed seed and `--order-seed` again: a red that
moves between runs cannot be handed to whoever must fix it, and a verdict
must depend on the commit and nothing else, as `mutate.py` requires of a
kill. Hypothesis is pinned exactly, because which examples a derandomized
run tries is a function of its version. Derandomizing was not enough on its
own: Hypothesis also mines constants from every module the process has
imported, so the draws moved with import order until `tests/conftest.py`
held that pool empty (the gap audit below). With it held, the examples are
a function of the commit, the pinned version and - for 4a alone, which
draws from `st.characters` - the Python version's Unicode tables.
`--hypothesis-profile=explore` searches ten times as far at random, and what
it finds becomes an `@example`. Hypothesis dropped 3.9 in 6.142.0
(2025-10-16), so the module skips there and says why; on 3.10 and up a
missing install is a collection error, never a skip, and a guard outside
the module fails if the skip is taken. Budgets: 500 examples for each
pure property, 25 for the git one at up to twenty patterns per
`check-ignore`. On this machine the module takes 12 seconds run alone,
its slowest property 3.1 - well inside `faulthandler_timeout`'s 60.

**What the properties cannot see.**
- The sixth checks how the skips COMPOSE - which scanner reads a token,
  which span sets it aside, that nothing falls between. Whether each span's
  pattern is right stays the corpus's question.
- A behaviour no property claims. Making `prose` blank inline code as
  `strip_code` does keeps every offset, so no property here goes red on it.
- The free-threaded leg: no free-threaded interpreter here, and Hypothesis
  declares no free-threading classifier. The pinned version does ship
  free-threaded wheels, so the 3.14t job installs it; whether it runs
  clean there is that job's first answer.

**Gated.** 1,585 tests: on Windows 1,577 pass and 8 skip, on Linux 1,583
and 2, serially and in CI's shuffled order. mypy clean on 47 files. 399
anchors, and the 16 new or moved were killed in one campaign: 0 survived,
0 hung, 0 overturned. The identity gate over the 152 visible clones, main
against this tree: 0 of 152 outputs differ, as predicted in writing
before it ran - none of the 866,696 paths the 152 track has a `*` segment,
and no corpus sweep sets `exclude_paths`, because the identity harness
applies each clone's own configuration and none of the 152 has one. smoke
0 new flags, scenarios 213 of 213, fuzz 0 violations, its self-check 23 of
23.

## The gap audit of the properties: nine findings, and a derandomized run that was not

On 2026-10-02, before anything was committed, the tranche was audited for
gaps with the three questions the 2026-10-01 audit asked: is each claim true
of the code that is there; did each repair reach every reader; does a test
or an anchor hold each changed path. Its write-up is `GAP-AUDIT.md`, outside
the repository. Nine findings, all repaired.

**Derandomized was not deterministic.** The worst finding, because it
falsified the claim the module's settings were chosen to make.
- **The mechanism.** Hypothesis 6.131.1 and later mines the literal constants
  of every local, non-test module in `sys.modules`, and draws one of them
  with probability 0.05 per choice. So a derandomized property drew
  different examples depending on what the process had imported before it.
- **Measured.** One derandomized property, 500 examples, digested:
  `1f686a69...` with no payload module loaded, `f8496e9f...` with all 44,
  each stable on repeat.
- **What it moved.** Under `-n auto` the examples depended on which files a
  worker had run first; `--order-seed` changed them; the module run alone
  tried other examples than the suite did; and `mutate.py`'s confirm-alone
  run tried a property in another import state than the suite run whose
  kill it confirmed - all sixteen were confirmed regardless. In WSL, where
  the packages arrive on `PYTHONPATH`, Hypothesis took them for local code
  as well.
- **The repair.** No setting turns it off: the issue that asked for one,
  HypothesisWorks/hypothesis#4627, was closed by a change that only
  re-attributed its cost. `tests/conftest.py` replaces the private
  `providers._get_local_constants` with one returning an empty pool, and
  stops at import if a Hypothesis has renamed it - which the exact pin makes
  a deliberate bump. Both digests are then `1f686a69...`. A test imports a
  fresh module of constants between two derandomized runs of one property
  and asserts the same draws; with the pool mined, 122 of its 200 moved.
- **What stays.** 4a draws from `st.characters`, which reads the
  interpreter's Unicode tables, and 3.10's differ from 3.14's, so "the same
  examples on every machine" was false across legs even with the pool held.
  The claim now names what the examples depend on: the commit, the pinned
  version, and for 4a the Python version.

**Our `ci` replaced Hypothesis's.** Hypothesis registers a `ci` profile of
its own - derandomized, no database, no deadline, `print_blob`, and the
timing-based `too_slow` health check suppressed - and loads it by itself on
a CI runner. A `ci` registered here replaced it without the suppression,
putting a timing check back on exactly the slow runners it is suppressed
for. Never seen failing; a regression against the library's own CI default
all the same. `ci` now derives from Hypothesis's profile, and `explore` from
`ci`.

**Three lines nothing held.** Run as mutations against the whole suite,
three survived: `ci` registered and never loaded; `ci` drawing at random;
and the module's version bound moved to (3, 99), which skipped every
property on every Python with the suite green - only `-ra`'s SKIPPED line
said so. A guard cannot live inside the module it guards, so
`tests/test_property_settings.py` holds them from outside: the module skips
below 3.10 and imports from 3.10 on, and the loaded profile is `ci` -
derandomized, no database, 500 examples, `too_slow` suppressed - unless a
run asks for another. Five anchors name the lines: the three survivors, the
dropped suppression, and the pool mined again.

**Statements that were wrong.**
- **The release that left 3.9** was 6.142.0 (2025-10-16), not 6.145.0:
  PyPI's `requires_python` reads `>=3.10` from 6.142.0 on, and 6.141.1 is
  the last release for 3.9.
- **Seven shapes, not six.** Under main's matcher seven of the eleven
  patterns `tests/test_exclude_paths.py` records disagree with git,
  `aa**/a` in both directions. The list in the section above always named
  seven; the count beside it said six, and so did five other places.
- **The overstatement config.md lost lived on beside it.** "`*` stops at a
  separator and `**` spans them" was still the comment on `exclude_paths`
  in `config.py` and the sentence in README.md. `SKILL.md` says only
  "gitignore-shaped", which is true.
- **The generator story.** The matcher defect was not found on the first
  run: 300 random examples passed. Three random runs of 1,000 found it with
  paths still drawn apart from the pattern, and paths built from the
  pattern found it in a derandomized set of 25. Six places had said "first
  run", or credited the runs of 1,000 to the pattern-derived generator.
- **The identity prediction's reasons.** The chain script said the corpus
  sweeps run without configuration; the identity harness applies each
  clone's own, and none of the 152 has one. "No corpus path has a `*`
  segment" had been read off the sweep outputs; counted with `git
  ls-files`, it is 0 of 866,696 tracked paths. The audit's own 866,848
  counted the empty field after each clone's last NUL, one per clone.

**Held, and checked.** The star-run repair is held at every part: five
sub-mutations - either bound unasked, a run not collapsed, an unbounded run
dropped, a bounded run keeping its slash - each killed by the example
tests. `_identity_keys` has one reader; `apply_exclusions` serves both
surveys, and the package holds no other gitignore-shaped matcher.
`--hypothesis-profile=explore` overrides `ci`. Every CI job that runs
pytest installs `requirements-test.txt` or `requirements-dev.txt`.
Hypothesis writes its cache by temporary file and rename, and swallows a
failure, so the 3.13 leg's two suites at once are safe; `.hypothesis/`
ignores itself.

**Gated.** 1,588 tests: on Windows 1,580 pass and 8 skip, on Linux 1,586
and 2, serially and in CI's shuffled order. mypy clean on 47 files. 404
anchors match. Thirteen were run for real in one campaign of 35 minutes -
the five above, and the eight Phase 62 anchors again, because an empty pool
changes what a derandomized property draws and their kills had been earned
on other draws: 13 killed, 0 survived, 0 hung, 0 overturned. The payload's
code is unchanged since the identity gate and the harness chain ran: only
comments and docstrings in `config.py` and `exclusions.py` moved, and every
module compares equal as a syntax tree with its docstrings set aside, so
both results stand. `--verify` exits 0, and `--selftest` fires 7 rules with
0 silent.

## mutmut as a cross-check: what the hand-chosen anchors missed

`tests/harnesses/mutate.py` breaks the code in 404 places somebody chose,
and a breakage nobody thought of is not among them. mutmut makes every
mutation it knows of in every function. Run over five modules on
2026-10-02, it asks what the hand selection missed. Phase 63 answers it for
`extant/blocks.py` and `extant/text.py`; `commits.py` and `anchors.py` are
the next tranche's.

**How it ran, and what that cost.** mutmut 3.8.0 refuses native Windows
(it exits, pointing at its issue 397) and forks a process per mutant, so it
ran in WSL. It needed six adaptations, all in a launcher kept outside the
repository with the rest of the apparatus (`m24_*.py` in the measurement
apparatus, rows under `D:/repo/out-mutmut/`):
1. mutmut names a mutant by its file PATH and records a hit under the
   MODULE, `extant.blocks`. The launcher strips the prefix.
2. The shim and the hooks run as subprocesses that inherited the stats
   run's mode and crashed in it. A `sitecustomize` resets it in children,
   and a real mutant's name still reaches them.
3. Two tests that read the SOURCE go red on mutmut's rewritten copy (the
   module ceiling and the line-numbering ledger), and are deselected there.
   The whole-suite confirmation below still runs them.
4. One temporary tree per pytest session, on disk. The first complete run
   lost 118 of 427 workers to a raised exception, which mutmut files as a
   timeout; afterwards, 0. The cause was not established.
5. `forkserver` isolation, chosen and not measured, so that a module memo
   filled by the stats run cannot answer for a mutant.
6. The mutated tree is a git worktree, because two tests read the
   checkout's git state and fail in a plain copy.

**mutmut's "survived" is a lead, not a verdict.** It runs only the tests
its in-process stats tied to the function, so a test that reaches the code
through the shim never meets its mutants. Every survivor was therefore
applied to a clean clone and the WHOLE suite run against it, about 30
seconds each on Linux. Three of 249 died there: `lone_cr_to_lf__mutmut_1`,
to a subprocess test, and two of `commits.py`'s origin-memo mutants, to an
in-process test whose path to them was not established. In blocks.py, 67 of
67 survived the whole suite.

**What it cannot see.** mutmut mutates function bodies only. Of the 67
anchors `mutate.py` holds in blocks.py, text.py, commits.py and anchors.py,
16 sit at MODULE level - patterns - and 4 inside text.py's two `lru_cache`d
functions, which mutmut skips. That is 30 per cent of what `mutate.py`
probes there. Eleven of links.py's 23 anchors are module-level patterns as
well. Its silence on those lines is not coverage.

**The measurement**, every survivor confirmed and read, with one reason
written per row:

| module | mutants | survived the whole suite | equivalent | contrived | cost only | real | shapes |
|:--|--:|--:|--:|--:|--:|--:|--:|
| blocks.py | 427 | 67 | 24 | 5 | 0 | 38 | 16 |
| text.py | 388 | 61 | 26 | 8 | 0 | 27 | 11 |
| commits.py | 469 | 55 | 11 | 12 | 7 | 25 | 9 |
| anchors.py | 237 | 43 | 6 | 2 | 0 | 35 | 8 |
| links.py | 144 | 20 | 9 | 9 | 2 | 0 | 0 |
| **all five** | **1,665** | **246** | **76** | **36** | **9** | **125** | **44** |

Three rows of blocks.py and text.py are counted there as the re-run below
found them: first filed as contrived, they are real, and the new tests kill
them.

links.py also had three mutants that never finished: `_html_references`
restarted its search at 0, looping forever on any line holding a tag. Only
a timeout kills those, and `mutate.py` would print HANG. "No real gap" in
links.py means its function bodies.

- **Equivalent**, by kind. Most are a falsy value swapped for another -
  `None` for `False`, read only by truth value - and the rest a boundary
  that maps one to one, a split whose last piece is the same either way,
  or a memo key that is constant because a run scope holds one repository.
  Five are DEAD code, and stay: `_quote_depth`'s `else 0` (twice), because
  `^(?:\s*>)*` always matches - kept because it narrows an Optional for
  mypy; and `_last_nonblank`'s fallback (three times), because a block
  starts on a non-blank line - kept because it keeps the function total.
  Checked against 4,732 documents from 139 corpus repositories, original
  against mutant through mutmut's own trampolines: 0 of the 57 checkable
  equivalents differ. The other 19 need a repository or a Config, and rest
  on the reading.
- **Contrived** rows are real but need an input no document writes: two
  `</tag` prefixes on one line, a quote marker after a list marker, a
  quote marker indented four or more, a target of only slashes. Recorded,
  no test. blocks.py has 5 and text.py 8.
- **Cost only** rows move no verdict: a memo never hit, a linear lookup.
- No Windows whole-suite run was spent on an equivalent, contrived or
  cost-only row. A killer found only there would move a row to "covered",
  and the hours buy nothing else.

**Nineteen real rows are mutants `mypy --strict` rejects** - a `None`
where a set, a dict or a tuple is declared - and the type check is a
required CI step, so mutmut's own "caught by type check" would count them
killed. They have tests all the same: a test pins the behaviour, and a type
is one annotation from being widened. Thirteen of them are this tranche's,
two of those among the rows the re-run below moved from contrived.

**One test per shape, its expected value the renderer's.** For blocks.py,
markdown-it-py 4.0.0's `commonmark` preset AND micromark (through
`mdast-util-from-markdown`) had to agree with the tree on every input a
test uses. A second oracle was needed: markdown-it ends an HTML comment at
a blank line inside a list item, where the specification and micromark do
not, and the first input chosen for the S9 shape fell on exactly that. For
reStructuredText the oracle is docutils 0.23; for the path shapes, git and
the filesystem. Three divergences the design already records appear in
the inputs, and the tests that meet them say so rather than claim
CommonMark's answer: a fence inside a comment or `<pre>` is still blanked,
an element's indented body is prose, and a list marker followed by five
spaces leaves its own line unread. Each test
was green on the tree and red against every mutant of its shape, applied
from the diff its confirmation recorded: 36 in blocks.py and 25 in
text.py, 61 of 61, and three more once the re-run below named them.

**What the shapes were.** In blocks.py: a closing tag read at the wrong
offset; a tab after other indentation; one to five spaces after a list
marker; the `mdx=` defaults; code on line 1; a fence holding `-->`; a
comment that closed a fence; a fence's opening line; a comment indented
inside an item; one-line comments and `<pre>` blocks, and the code straight
after them or after an HTML opener or a marker-line fence; nested elements;
a closing tag under an HTML opener; a fence on a marker's line; and a
fence closed inside a block quote. In text.py: a backslashed document path;
a dot earlier in a path than its suffix; a line's exact terminator; rst
inline literals and the end of an rst literal block; a root-level
document's basename; the degraded path, where the tracked-file listing
fails; a document directly inside a language directory, a language
directory two levels down, and two language-shaped parents in one run;
the threshold of three siblings; an unprefixed document listed first; and a
numbered route at every depth up to the whole.

**One shape was a defect, not a gap.** `_closing` takes `</pre >` - a
space before the `>` - as closing a `<pre>` block. CommonMark's end
condition is the literal `</pre>`, and markdown-it and micromark both run
the block on, so the renderer shows the lines after it as raw HTML while
the tree can read them as code and blank them: the unsafe direction, a
claim silenced. The mutant that reads the tag wrongly AGREES with the
renderer there. It is recorded as its own item, to be repaired through the
identity gate; no test here pins it, and the half of the shape the tree
gets right - `</pre>` with text after it - has its test. (Repaired in
Phase 65: the last section of `design/code-blocks.md`.)

**One row was misfiled.** `_line_and_terminator__mutmut_8` drops the bare
CR spelling of a line break. Through `strip_code` and `prose` it is
unreachable: `_blank` rewrites every lone CR to LF before the line loop
runs, and the mutant changed none of ten bare-CR documents, in either
language, nor any of the 4,732. It is equivalent at the package's
boundary. Its test holds the function's own contract, and says so, so that
removing the normalisation upstream cannot turn a CR into a blanked space
unnoticed.

**The check that closes it: mutmut again, with the tests in place.** The
survivors had to be exactly the rows the reading left standing - the
equivalent and contrived ones, the `</pre >` defect, and
`lone_cr_to_lf__mutmut_1`, which mutmut's selection cannot reach and the
whole suite kills - and not one real row. Run on 2026-10-03, 815 mutants in
20 minutes, 0 worker exceptions: 65 survived where 68 were expected, every
one confirmed against the whole suite, 64 surviving it and
`lone_cr_to_lf__mutmut_1` killed. No real row survived. The three missing
were filed as contrived and are not:
- `code_lines__mutmut_242` turns an `and` into an `or`. It was filed for
  `- > ````, a quote marker after a list marker. It also opens a fence
  after five or more spaces on a marker's line, which the S15 test feeds,
  and that test kills it.
- `unique_basename__mutmut_54` and `_56` look the citing document's tree up
  with no default. That was filed as "the tree holds no tracked markdown".
  Every tree is empty when the listing fails, which is the degraded path
  the T7 test takes, and both raise there.
A reading that files a mutant by the one input that first came to mind is
how a real row hides as a contrived one, and only running the tests against
it found these three.

**Gated.** 1,635 tests: on Windows 1,627 pass and 8 skip, on Linux 1,633
and 2, serially and in CI's shuffled order. mypy clean on 47 files. 431
anchors match, and the 27 new ones were run for real in one `--parallel`
campaign of 32 minutes on a clone: 27 killed, 0 survived, 0 hung, 0
overturned. From an extract of the tree: smoke with no new or missing flag,
scenarios 213 of 213, fuzz 0 violations, the fuzzer's self-check 23 of 23.
`--verify` exits 0; `--selftest` fires 7 rules with 0 silent;
`--introduced-since main` reads 5 changed documents, 242 introduced lines,
0 findings. The payload did not change, so the identity gate was not run.

**Phase 64: commits.py and anchors.py.** The second half took the 60 real
rows of the other two modules, in 17 shapes. Every test was green on the
tree and red against every mutant of its shape - 60 of 60, and the two
origin-memo rows the whole suite already killed besides.

*`--sha-map`, held whole at last.* It is the one mode that WRITES
documents, and its output had never been compared whole: the tests were
one-line inputs asserted with `in`, and the fuzz oracle reads crash, exit
and denominator, not text. Through the whole suite went: a separator joined
between every line, the same between the pieces of a line holding a bare
rewrite, an all-digit backticked token losing its backticks, an all-digit
range end rewritten, and three `continue`s that became `break`s and left
the later tokens on a line as written. A Hypothesis property now holds
three claims. An empty map is a no-op, byte for byte. A rewrite keeps the
length and changes only whole hex runs the scanners read as commits, each
into exactly its mapped value - `translated_value` truncates to the
token's length, so that can be checked character by character. And no
token the scanners report in the output still has a mapping: what
`dead-sha` reports, `--sha-map` repairs.

The generator is built FROM the map, the matcher property's lesson. The
old ids are fixed. Two share an eight-character prefix, so a short token
is ambiguous and must stay. One opens with seven digits, so an all-digit
range end prefixes it and must stay too. The new ids open with letters no
old id does, so no rewrite is itself rewritable. Each token comes bare,
backticked, as a range, inside a URL, a pin, a commit link, a relative
link, after a `#` or inside a UUID, several to a line, LF or CRLF. Every
one of the seven mutants turns it red, and every one does with its
explicit examples switched off: the generator finds them itself, in 500
derandomized draws. The 3.9 legs skip the property module, so example
tests hold each shape where they run too.

*The rest.* A shared memo that answered across origins; a link to this
repository's commit that ended the line's linked spans; a foreign link
that ended the line's backticked scan; a refused merge claim that ended
the scan; the shared SHA batch gathered without the origin, so a live
commit linked by this repository's own URL was reported dead; and eight
ways `noted` misnamed, or crashed on, the rewrites another repository may
still hold. In anchors.py: each of the definition-term openers and the
setext title openers, frontmatter of more than one line or closed by
`...`, a setext heading on the first line or the last, a plain line taken
for a heading, a heading's edge dashes, and two things no test held at all.
An HTML `name` or `id` attribute was never offered as an anchor in any
test - the explicit spellings tested were pandoc's `{#id}`, Docusaurus'
comment around one, and MyST's targets and labels. And `_disambiguated`,
the definition the inline numbering is checked against, was checked in
one direction only, so four mutations
that made it number nothing passed. Its sets are now pinned against
GitHub's numbering.

*A second defect, found by choosing an input.* A setext title indented one
to three spaces - ` Title` over `=====` - IS a heading: markdown-it and
micromark both say so, and CommonMark allows the indentation. This module
refuses every indented title, so a working link to one is reported dead.
That is the safe direction, a finding somebody can argue with, but it is a
false positive, and it is recorded as its own item beside `</pre >`, not
repaired here. The tests feed four spaces and a tab, where the module and
the renderer agree that the line is code and not a title. (Repaired in
Phase 65, with its converse - an underline at four columns made a heading
- in the last section of `design/code-blocks.md`.)

*A gap wider than the ledger said.* A7 was filed as "an explicit anchor
with capitals". Every fragment is lowered before it is compared, so the
mutant broke every lettered HTML anchor, capitals or not.

*Closed by running mutmut again, and one false kill caught.* 706 mutants
in 11 minutes, 0 worker exceptions. The survivors had to be exactly the 38
equivalent, contrived and cost-only rows, with no real row - and the two
origin-memo rows mutmut's selection missed the first time had to die under
mutmut itself now, since a new test calls the scanner directly. They did. 37
survived, every one confirmed against the whole suite. The 38th,
`spans_overlap__mutmut_5` - a token starting exactly where a skip span ends
counted as inside it, filed contrived - was filed KILLED, with exit 1 and no
duration recorded. No new test kills it on Windows, and the whole suite on
a clean Linux clone lets it through. It is a false kill, the error the
measurement's gap audit bounded at under about 7.5 per cent from 40 of 40
kills re-run, seen here for the first time: one in 706. It runs the safe
way for a cross-check - a gap hidden, not invented - which is why the
closing run confirms survivors against the whole suite. Here it was also
missed by that confirmation, because the confirmation reads only survivors,
and only the expected list caught it.

**Gated, Phase 64.** 1,684 tests: on Windows 1,676 pass and 8 skip, on
Linux 1,682 and 2, serially and in CI's shuffled order. mypy clean on 47
files. 448 anchors match, and the 17 new ones were run for real in one
`--parallel` campaign of 31 minutes on a clone: 17 killed, 0 survived, 0
hung, 0 overturned. From an extract of the tree: smoke with no new or
missing flag, scenarios 213 of 213, fuzz 0 violations, the fuzzer's
self-check 23 of 23. `--verify` exits 0; `--selftest` fires 7 rules with 0
silent; `--introduced-since main` reads 394 introduced lines, Phase 63's
and these, with 0 findings. The payload did not change, so the identity
gate was not run.

## The harnesses typed: 170 errors, and a harness broken for seven weeks

Phase 66, the first half of the type-checking tranche: the harnesses under
`tests/harnesses/` join `[tool.mypy]`, so the self-check job's mypy step
holds them as it holds the package. Harnesses first because they are CI
jobs or hand-run, and a type error in one is a red job, or a crash on the
next run, that pytest cannot see. The tests are the second half.

**Measured first**, `mypy --strict` at the 3.10 target with the search path
conftest.py gives the suite (`m26_typecheck_measure.py` in the measurement
apparatus): 170 errors in 12 of the 13 files. 141 were a missing
annotation, a call into an unannotated function, or a bare generic. The
other 29 were read one by one, because they are where a change beyond an
annotation hides, and the measurement's question was how many there are.

**One real defect.** `corpus.py`'s `examined()` - the per-rule denominator
column the harness exists to provide - raised `NameError` on every call
from 2026-08-17, when the modes moved out of the shim. The refactor imported
the session module as `hc` in this function and as `ec` in `toolchain()`,
and the loop still said `ec`; it also bound `text` to each document while
`text.format_for` still meant the module, so mending the name alone would
have moved the crash one line down. `main()` calls it with no handler, so
`python tests/harnesses/corpus.py <dir-of-clones>` stopped at its first
repository for seven weeks, and nothing noticed: AGENTS.md lists the
harness as hand-run, no job runs it, and no test called it. A test calls it
now - a markdown claim and the same sentence in a reStructuredText literal
block, where the per-document format decides the count - and was watched
red against each of the three ways the function can be broken: the unbound
name, the shadowed module, and a dropped `set_document`.

**Two annotations that stated the wrong thing.** `stress.py`'s
`verdict_for` was declared to take a float and opened with a branch for
None, which every timed-out run passes it; the declaration was the lie, not
the branch. `corpus.py` declared its results `dict[str, dict[str, int]]`
while every entry mixes two counts with three maps; it is a `TypedDict` of
the baseline line `--update` writes, and the comparison loop reads its two
maps by name rather than through a key variable the type cannot follow.

**The other 27**, each an annotation or a rename: a loop variable reused
for a second type (smoke.py, stress.py, corpus.py), a tuple grown from an
inferred three-tuple, a timeout assigned a float into an int-typed global,
an empty tuple fixing a branch's type, a lambda with a default argument no
checker can infer, a signal handler built as a tuple inside a lambda, and
the axes' facts - eight keys, each set only once the step that earns it has
succeeded, so an absent key is the evidence; that is `AxisFacts`, a
`TypedDict` with `total=False`. `Build.facts` holds one flag that is
written and read by nothing; recorded, not removed.

**Three choices, each with its reason.**
- No explicit `Any`, as in the package, where there is none. Parsed JSON
  stays an unannotated local, as `report.py` leaves it; the one parameter
  that received a parsed document, `RepoPlan.from_dict`, became
  `from_json(text)` and parses inside, with its body unchanged; the SARIF
  walk in fuzz_differential.py narrows each level through `_json_object`,
  which is identical on SARIF this tool writes and reads a malformed value
  as absent where the chained `.get` raised.
- Aliases that hold `X | None` - the oracles' `Run`, the driver's `Faults` -
  sit under `if TYPE_CHECKING:`, as AGENTS.md prescribes, because 3.9
  evaluates a module-level alias on import and no checker sees the crash.
  The suite imports these modules on every leg, so the 3.9 leg is where
  that would have shown.
- No `assert` to tell the checker an invariant, since the harnesses have
  none: the driver's guard tests the value `examine` returns, which is None
  exactly when the build broke, three lines into the same function.

**No mutation anchor** for the `corpus.py` repair. `mutate.py` mutates what
ships and what installs it, and the class of this defect - a name bound in
one function and read in another - is what mypy in CI now refuses on every
pull request, which is a stronger guard than one mutant.

**Cost.** A cold `python -m mypy` took 3.0 seconds over 47 files and takes
about 5 over 60; warm, 0.4 either way.

**Gated, Phase 66.** 1,697 tests: on Windows 1,689 pass and 8 skip, on
Linux 1,695 and 2, serially and in CI's shuffled order. mypy clean on 60
files; 452 anchors match. From an extract of the tree: smoke with no new
or missing flag, scenarios 213 of 213, fuzz 0 violations, the fuzzer's
self-check 23 of 23, and its differential against a second extract of
the same tree 0 differences over 58 findings and 130 denominators, so
the rewritten SARIF walk compared something. The three hand-run
harnesses ran once each: `corpus.py` over two clones, its baseline
written and then compared with 0 changed; `perf.py`'s ten sections;
`stress.py` 52 of 52 measurements within expectations. `--verify` exits
0; `--selftest` fires 7 rules with 0 silent; `--introduced-since
origin/main` reads 168 introduced lines with 0 findings. The payload did
not change, so the identity gate was not run.

**The second half.** The tests: 1,779 errors over 84 files at the same
settings, 1,331 of them a missing `-> None` and 269 the calls those make
untyped; 108 beyond an annotation. Sampled, one test asserts on a state the
shipped tool cannot reach - test_prefilters.py hands `path_pointer` two
capture groups, which the configuration loader refuses - and the rest read
so far are idioms: a cached helper redefined over the one that filled the
cache, `append(...) or {}` in a monkeypatched lambda, private names reached
across modules.

## The tests typed: 1,640 errors, and a test of a pattern the tool refuses

Phase 67, the second half of the type-checking tranche: `tests` and
`.github/scripts` join `[tool.mypy]` files, so the self-check job's mypy
step now holds every Python file the project maintains. The release gate
`publish.yml` runs was the last one outside it.

**Measured first**, with the repository's own settings and those two
directories added, under mypy 2.4.0, the version CI's self-check job
installed on the pull request before (2.3.1 here gave the same 1,640, line
for line): 1,640 errors in 79 of 146 files, the tests' 1,637 and the
gate's 3. Of the tests', 1,271 were `no-untyped-def`, 252 calls into
functions those leave untyped, 18 bare generics, and 96 beyond an
annotation - all 96 read in context, not sampled.

**A correction, dated 2026-10-06.** The section above gives the second
half as "1,331 of them a missing `-> None`". The messages say otherwise:
986 were functions whose fixture parameters carried no type, 185 had
nothing annotated, 100 lacked only a return type, and mypy suggested
`-> None` for 56. The figure counted one error code; the sentence
described a different shape inside it.

**By script, then by hand.** Unannotated parameters by where their value
comes from: 874 a project fixture (`git_repo` 768 of them), 471 a pytest
builtin, 182 a helper's own, 66 a `parametrize` argument. So a script
annotated by NAME, only on a test or a fixture, and only a name no
`parametrize` on that function claims: 1,305 parameters and 153 `-> None`
in 69 files, after the eleven fixtures that declared no type were given
one by hand. Its imports follow the house layout, and a second pass
rewrapped the 234 signatures it pushed past 89 columns - the suite's own
width, which 26 signature lines exceeded before - in the suite's own
form. 1,640 became 579; the rest is hand work. conftest.py names the
shapes most tests take: `Commit`, `GitRepo` (`tuple[Path, Commit]`) and
`Reconfigure`. Both scripts are in the measurement apparatus
(`m27_annotate.py`, `m27_rewrap.py`).

**The test outside the domain.**
`test_a_top_level_alternative_without_the_literal_keeps_the_full_scan` set
`path_pointer` to a pattern with a capture group in each alternative. The
loader refuses `path_pointer` with any count but one, and the test
asserted sites holding tuples, which `_path_pointer_sites_uncached` never
returns. Its subject - a literal mandatory in one alternative and absent
from the other gates nothing - holds in the domain, and the obvious
rewrite would have lost it: `(?:see `|read )(...)` has one group, but its
backtick sits inside a group, where `required_literals` never looks, so
the top-level `|` branch would go untested. The test now reads `` see
`([\w./-]+\.md)`|read [\w./-]+\.md ``. The alternation stays top-level;
the second alternative captures nothing, and `findall` hands back `""`
for it, which is a site - what tells a scanned line from a gated one. It
was watched red against `mutate.py`'s "the derivation ignores a top-level
alternation" and green without it.

**Names a module does not export: 14 errors in 9 files, each import
rewritten** to where the name is defined, as decided over a per-module
setting, which would also have admitted every later case unseen.
`Finding` from `extant.finding`; `main` from `extant.cli` (the same
object the shim binds; these tests call it in process); `anchors` and
`project_anchors` from their modules, while the patch still replaces the
rule's own binding; `subprocess` and `time` imported by the test, the
same module objects the rule and the gate call through; Hypothesis's
`Constants` from `constants_ast`.

**Nine suppressions in the tests**, one code each, the reason on the line
above:
- six deliberate violations: two frozen fields assigned to prove they
  raise (`misc`), the wrong config type passed to test the message it
  raises, two `None` contexts a rule must never read, and the one
  replace-by-field-name line (`arg-type` each). That last one was two
  copies; it is one conftest helper, `configured`, which the
  `reconfigure` fixture and a plain helper both call;
- three `import tomllib` (`import-not-found`). A switch on
  `sys.version_info` needs no suppression, and was the design; the suite
  refused it, because test_packaging.py's floor check accepts a `tomllib`
  import only under try/except. So they carry extant/config.py's form and
  its suppression, for its reason.
Three stale suppressions went.

**Seven explicit `Any`**, where the package has none: each where a parsed
document crosses a function boundary and its keys are then read - three
SARIF documents or result lists, corpus_render.py's figures twice, the
installer's TOML twice. A TypedDict per document would restate its
writer here, and a key the writer did not produce raises in the test that
reads it. Every other parsed document stays an unannotated local or is
narrowed with `isinstance` before it is returned; 22 narrowings in all,
`extant.collect`'s `dict[str, object]` bundle among them, since typing
the bundle would have changed the payload.

**Spies** that forward to `subprocess.run`, `open` or a rule function
hold the original as `Callable[..., object]` and return `object`: their
result is read only by the code under test, through `monkeypatch`, which
mypy does not check against the original. An import an annotation alone
needs is taken at run time where that costs nothing - a name from
`typing`, `types`, `re` or `pathlib`, `pytest`, one of conftest's
aliases, or one more name from a module the test already imports - and
under `TYPE_CHECKING` otherwise, as the package's `Config`, `Context`,
`Finding` and `Rule` are in 18 files. So no test imports a module at run
time that it did not import before, beyond the standard library,
`pytest`, conftest and the rewritten imports above (`extant.finding`,
`extant.cli`, `extant.anchors`, Hypothesis's `constants_ast`); every
name taken at run time exists on 3.9, and conftest's aliases are
subscriptions 3.9 evaluates.

**Found on the way:** `_gate` in test_introduced_since.py said it returned
(exit code, stdout, stderr) and returns the exit code. The gate script's
`fetch` returned the API's `workflow_runs` unchecked; anything but a list
now reads as no run found, which fails the gate.

**Cost.** A cold `python -m mypy` took 4 seconds over 60 files and takes 9
over 146; warm, under one either way.

**Gated, Phase 67.** 1,697 tests: on Windows 1,689 pass and 8 skip on
each code commit's own tree and the tip, on Linux 1,695 and 2,
serially and in CI's shuffled order. mypy clean on 60 files for the
first two commits and on 146 for the third; 452 anchors match on every
tree. `--verify` exits 0 on every tree and on a main-only clone with the
branch merged; `--selftest` fires 7 rules with 0 silent;
`--introduced-since origin/main` reads 180 introduced lines with
0 findings. Neither the payload nor a harness changed, so neither the
identity gate nor the chain was run.

## The installer under mutmut: 896 survivors, outputs compared whole, and three defects

D7 measured the rest of the package under mutmut; Phase 68 acted on the
part of it the installer owns, install.py and detect.py, which do not ship.
The apparatus is `m28_*` (D7) and `m29_*` (Phase 68) in the measurement
apparatus, rows under `D:/repo/out-mutmut/d7/` and `D:/repo/out-mutmut/p68/`.

**D7, the measurement (2026-10-06/07).** The cross-check above saw 12 per
cent of the package's mutants. D7 ran the other 41 files, 12,127 mutants,
by tranche 24's method - stage 1 finds, under mutmut 3.8.0 in WSL; stage 2
decides, the whole suite on each non-kill applied to a clean clone - with
three changes, each forced by a measurement:
1. The launcher strips `plugin.skills.extant.` as well as the payload's
   prefix, because the suite imports the installer as `install` and
   `detect`.
2. A compiled-code cache keyed by the source bytes. Under mutmut each
   payload module carries every mutant, so the payload a test installs is
   50 MB, and its first import took 93 seconds against 0.4.
3. 22 tests that read the payload's SOURCE are deselected in stage 1 only.
   On the instrumented tree they fail or take up to 400 seconds, and none
   calls a payload function, so mutmut could never select one; stage 2 runs
   them on every row.

Stage 1, 61 minutes on 6 workers: 8,783 killed, 2,330 survived, 981
reached by no test in process, 31 timeouts, 2 segfaults - 3,344 leads.
Stage 2, 20.2 hours on 10 workers, both controls holding: 2,158 survive
the whole suite, 1,156 killed, 30 hung. So 17.8 per cent of those
mutants outlive everything pytest runs, against 15 in tranche 24; `mypy
--strict` rejects 370 of them. 50 drawn at random and read one by one,
with mypy and CI's other jobs measured on each, project about 1,770
caught by nothing in CI, about 734 of them real and not wording (95 per
cent interval 450-1,017). One pilot row read as real is equivalent:
`merge_claim` taken out of `render_config`'s `regexy` set falls to a branch
that quotes by the same rule, so the file is byte-identical. The plan's
gap audit found it by running a test against it.

The survivors sit where a whole OUTPUT is produced and only pieces of it
were asserted - a key of the config here, a phrase of the output there.
install.py kept 503 of its 1,272 mutants and detect.py 393 of its 747.

**The decisions as taken**, weighed on what each buys the project, three
of them departing from the recommendation:
- D7a: a row `mypy --strict` rejects counts as CAUGHT, because mypy is a
  required step of the self-check job; no test is written for one alone.
- D7b: for the installer, wording is pinned. Its prose states what each
  setting will DO, and `closing_advice` records a sentence that was false
  in 39 of 39 installs. Each fixed paragraph is written once in the test
  file, so a rewording is one edit. argparse's own text is the exception:
  each help sentence is compared, never the page, because argparse titles
  and wraps it differently across 3.9-3.14.
- D7c: whole-output tests, surface by surface, install.py and detect.py
  first, measured again at the close.
- D7d: a Windows-only row is a limit of the Linux verdict, decided on
  Windows wherever a test reaches it.
- D7e: the singular, below - six strings rather than seven, because the
  seventh can never count one.

**The tests.** `tests/test_detect_outputs.py` calls every observer in
process and compares its whole answer: the Observation lists on seven
histories, each built to reach named branches (ticket keys and slash
prefixes past the floor, a detached HEAD, a non-ASCII branch prefix and a
latin-1 subject, five tags under four prefixes, no history at all); every
grouping floor and the branch floor ON a boundary, where `n // 20` and
`n / 20` disagree; the 500-subject sample bound; `find_wide_documents`'
notes on four trees and its three refusals; `find_documents` and
`inspect_document`. The histories are built by one `git fast-import`, not
a `git commit` each - the floors need up to 501 commits.

`tests/test_install_outputs.py` runs install.py as a subprocess - twelve
tests, nine repositories - and compares stdout and the three files it
writes, whole: a status document with everything derived, a second run
and `--force`, a dry run, an undetected entry prefix, the readme preset,
`--wide-docs` nominating a README.rst, a document under `docs/` with
`--claude-command`, the four ways it stops, and `--help`. The command and
the skill are compared against their templates with the values
substituted, and the
payload's file list is read from the payload tree, so what is pinned is
what the installer DECIDES. In process, the steps between: `apply_preset`
on four presets, `_fold_wide_docs`, `choose_document`, `render_config` on
a value of every shape it branches on - parsed back, each value must read
as itself - `render_command`, `closing_advice`, and `copy_payload` on a
skill missing its payload.

The installer runs from OUTSIDE the repository. Every installer test
before ran it from inside, so a git call that dropped `repo` and fell back
to the working directory read the right history anyway: three such
mutants in install.py, killed only from outside.

**Three defects, found reading the residue**, each with a test watched
failing first and a commit of its own:
1. "1 tags", "1 branches", "in 1 subjects", "1 lines" in the evidence the
   installer prints and writes. `detect.counted` takes the plural rather
   than deriving it, since `branch` takes `es`.
2. `git branch -a` lists a detached HEAD as a line of its own, and the
   branch sample counted it: a repository with one branch was reported as
   having two. It asks `for-each-ref` for refs/heads/ and refs/remotes/
   now. A pull request's CI checkout is a detached HEAD.
3. The validator makes its output survivable (`_survivable_output`); the
   installer never did. Piped, as an agent runs it, Windows encodes its
   output as cp1252, and a Japanese branch name raised UnicodeEncodeError
   at the configuration table, before `.extant.toml` was written. The
   test forces cp1252 with no error handler, so the tool copes rather
   than the environment.

**The closing measurement.** `m29_redcheck.sh` applies each of D7's
patches to a clean clone of main with the worktree's files copied over
it - nothing was committed for it - and runs only the new tests; a D7
survivor already passed the whole suite, so a failure means a new test
kills it. CLEAN passed in every run, and a pre-flight with the old
`test_detect.py` killed none of detect's 393. A patch whose lines a repair
moved is retried with no context required, which is safe only because
each line it removes occurs once (`m29_stale.py`); one whose line a repair
REWROTE names a mutant that no longer exists. Tallied by `m29_tally.py`:

| | install.py | detect.py | all |
|:--|--:|--:|--:|
| D7 survivors | 503 | 393 | 896 |
| killed on Linux | 427 | 333 | 760 |
| killed on Windows only | 16 | 4 | 20 |
| equivalent | 51 | 33 | 84 |
| contrived | 8 | 3 | 11 |
| no longer exist | 1 | 20 | 21 |

No real row is left. The plan's fixtures alone killed 252 of detect's 393;
reading what survived, three times over, took the total to 780. Each of
the 20 Windows-only rows was applied on Windows and watched killed - a
dropped `encoding="utf-8"` or `newline=""` on a write, or a path separator.
The 21 that no longer exist mutate the `git branch -a` line (10) and the
six rewritten strings (11). Every residue row carries its class and reason
in `residue_detect.tsv` and `residue_install.tsv`. A full run took about
half an hour on 10 WSL workers, most of it rebuilding each worker's tree.

**Seen and not taken**, because each is a simplification rather than a
gap: `detect_release_tag` counts tags per prefix and reads only the keys;
`inspect_document` returns `merge_targets`, which nothing reads;
`render_config`'s `regexy` set decides nothing the generic string branch
would not; its `plain` set names `pointer_prefix`, which no observation is
called.

**Anchors.** 22 in `mutate.py`'s Phase 68 block, one per surface on its
most specific line, the three repairs reverted, two that only Windows can
kill: 474 in all. The Windows campaign, on a copy, killed all 22 in 42
minutes - none hung, none overturned by the serial check.

**Gated, Phase 68**, on the final tree before any commit. 1,753 tests: on
Windows 1,745 pass and 8 skip, on Linux 1,751 and 2, serially and in CI's
shuffled order. mypy clean on 148 files, about ten seconds cold; 474
anchors match. The installer changed, so smoke and scenarios ran on an
extract of the tree: 0 new and 0 missing, 213 of 213. `--verify` exits 0
here and on a main-only clone; `--selftest` fires 7 rules with 0 silent;
`--introduced-since origin/main` reads 222 introduced lines with 0
findings. The payload did not change, so no identity gate.

## report.py under mutmut: 187 survivors, its outputs compared whole

Phase 69 (2026-10-08) is D7's next surface after the installer, by Phase
68's method and the decisions above. report.py renders what every run
reports - text, GitHub annotations, SARIF - and writes the baseline. D7
found 187 of its 843 mutants alive after the whole suite: 118 in
`format_sarif`, 26 in `write_baseline`, the rest in ten helpers; mypy
rejects 6. The tests had asserted pieces of each output - a level, a URI,
that some notification mentioned the cut - so a renamed key, a changed fixed
value or a column moved at a boundary went unseen.

**The tests.** `tests/test_report_outputs.py`, twelve tests, compares:
- one SARIF run, whole, parsed and as text indented by two. Descriptors from
  the registry and the fallback for a kind it does not hold; a result per
  finding; a cited document whose lines each reach one branch of the snippet
  and its region - the subject twice on its line, at column 1, ending on the
  last column a region may name, starting one past it on a line over the
  cap, absent - beside a line of exactly the cap, trailing spaces, a closing
  capital and a character outside ASCII; then the denominator, a NOTE, a
  rule switched off and one that raised;
- the cut, in each of the three ways `format_sarif` is called past the
  limit - as every mode calls it, with the NOTE among its notes; with the
  denominator and no NOTE; with neither - and the overflow NOTE at GitHub's
  25,000 itself;
- UTF-16 lengths either side of the plane boundary;
- the workflow-command escape, and two annotations, whole;
- the baseline file byte for byte - one entry per (path, kind, detail) with
  its count, sorted, ASCII, LF, indented by two - and read back; a baseline
  edited by hand in UTF-8; and the two errors a baseline that cannot be read
  raises;
- `render_findings` handing each format every argument;
- grouped text, and a sweep's sections with their entry count.

**The closing measurement.** `m30_redcheck.sh`, `m29_redcheck.sh` with the
worktree and output directory as parameters, applies each of D7's 187
patches to a clean clone of main with the new test file over it and runs
only that file; CLEAN passed in every run.

| | report.py |
|:--|--:|
| D7 survivors | 187 |
| killed on Linux | 160 |
| killed on Windows only | 5 |
| equivalent | 22 |

No real row is left, and none of the 187 was a defect, so report.py itself
did not change. The first round killed 142. Reading the 45 left found the
two calls past the limit that only a direct call makes - the denominator
without the NOTE, and neither - which a test already made and never compared
whole; comparing them killed 21 more. The five Windows-only rows - the
cited line and a hand-edited baseline decoded with the locale, the baseline
written with CRLF - were each applied on Windows and watched killed. The
equivalent rows are a codec spelled in capitals (4), encodings of a file
`ensure_ascii` keeps ASCII (2), `ensure_ascii` dropped where its default is
the same (1), newline modes that split lines alike and are stripped alike
(2), the first field of a split whatever the count (2), a title escape no
rule's kind can reach (3), a default no caller uses (1), a fallback rank no
stratum reaches (2), the limit compared with `<` where the list at exactly
the limit comes back the same (1), a condition `split` always satisfies
(1), and the flag beside `render_findings`' lines, which every caller
discards (3). Each carries its reason in `residue_report.tsv`.

**Seen and not taken**, each a simplification rather than a gap:
`render_findings` returns its lines with a `True` no caller reads, since
every mode decides the stream itself; `_baseline_entry`'s `count` default
is never used; `_sarif_kept`'s fallback rank cannot be reached, because the
strata are a partition.

**Anchors.** 16 in `mutate.py`'s Phase 69 block, one per surface on its
most specific line, two that only Windows can kill: 490 in all.
The Windows campaign, on a copy, killed all 16 in 40 minutes - none
hung, none overturned by the serial check.

**Gated, Phase 69**, on the final tree before any commit. 1,766 tests: on
Windows 1,758 pass and 8 skip, on Linux 1,764 and 2, serially and in CI's
shuffled order. mypy clean on 149 files; 490 anchors match. `--verify`
exits 0 here and on a main-only clone; `--selftest` fires 7 rules with 0
silent; `--introduced-since origin/main` reads 391 introduced lines
with 0 findings. The payload did not change, so no identity gate, and no
harness the chain runs changed.

D7 is not done. introduced_since.py (142), sweep.py (140), collect.py
(139), cli.py and gate.py (115 each), deleted_since.py (114) and the rest
remain, a surface each.

## introduced_since.py under mutmut: 142 survivors, and two defects in the gate

Phase 70 (2026-10-08) is D7's third surface. D7 found 142 of
introduced_since.py's 574 mutants alive after the whole suite, 93 of them
in the report `run_introduced_since` prints; mypy rejects 22. The tests
asserted single lines of that report, and nothing about which stream each
went to: in SARIF mode the report goes to stderr and the document alone to
stdout, so a line printed to stdout corrupts the upload while every `in
out` assertion passes.

**Two defects, found reading the survivors**, each with a test watched
failing first:
1. A document whose name holds a backslash - legal on POSIX, and quoted by
   git - was not gated. The mode turned `\` into `/` in three places, on
   paths git writes with `/` on every platform, so it looked the
   document's written lines up under a name the diff never gave: its claim
   was set aside as sitting on an untouched line, its lines went
   uncounted, and it was counted among the documents the range left alone.
   With only that document in the range, the gate exited 0 on a dead claim
   written that day. The three replaces are gone. The same spelling sits
   in deleted_since.py, sweep.py and exclusions.py, on paths of both kinds;
   each is measured with its own D7 surface.
2. A binary document with " and " in its name was misnamed. git reports a
   binary change as one line, `Binary files <old> and <new> differ`, and
   the new side was taken after the LAST " and ", so "cats and dogs.md" was
   reported as "dogs.md" and counted as left alone. Without a rename the two
   sides are one path behind `a/` and `b/`, so the line now splits at its
   middle - exact for any name; an added document follows `/dev/null and `,
   a deleted one ends ` and /dev/null`, and a renamed one is named by git's
   `rename to` header.

**The tests.** `tests/test_introduced_since_outputs.py`, thirteen tests.
One range reaches every branch of the report at once, with two of every
count and every list in it: claims on written and untouched lines, a
document line reading like a diff header between two hunks, a binary
document named with spaces and " and " and a deleted one, an excluded
document beside a pattern that cannot exclude anything, two documents with
a bare carriage return and two that are not UTF-8, one left alone, a
pattern switched off and two repository rules. It is compared whole in
text - with GitHub's SARIF limit at 0, so the text names no cut - and in
SARIF, where the report on stderr is compared whole and the document on
stdout field by field; again from a pool, and from a pool that cannot
start. Beside it: a range changing the primary document, with and without
a dated entry; one changing no markdown; a claim written into a vendored
document; a rule that raised, named once; documents the survey lost, the
reading going on past them; the refusal when git cannot diff; and on Linux
only, a name that is not UTF-8 and a link out of the checkout. A report
line another module words - `session.zero_notes`' NOTE lines, the
unusable-pattern line, the fallback NOTE - is built by that module's
function from the arguments this report must hand it, written out. The
two repairs added two tests to `tests/test_introduced_since.py`.

**The closing measurement.** `m30_redcheck.sh` as for report.py, with
both test files run; CLEAN passed in every run. The repairs rewrote four
lines and moved others, so 24 patches no longer applied; `m30_stale.py` (`m29_stale.py`
with the worktree as a parameter) found 9 whose context had only moved,
retried with no context required, and 15 naming a mutant that no longer
exists.

| | introduced_since.py |
|:--|--:|
| D7 survivors | 142 |
| killed | 83 |
| caught by `mypy --strict` | 9 |
| equivalent | 35 |
| no longer exist | 15 |

No real row is left. Four of the kills come from the two Linux-only tests,
which CI's Linux legs run. The equivalent rows are `unquote_path`'s
branches for input git never writes - an empty quoted path, a trailing
backslash, an escape outside C's, bytes that are not UTF-8 after `_side`
has replaced them - and its codec spellings (16); the failed diff's
`CalledProcessError` arguments, of which the caller reads only the class
(6); starting values git's own output order overwrites (3); `/dev/null`
and prefix handling no diff line reaches (3); a codec spelling in `_side`
(1); a second header test no header line can pass (1); and in text mode,
the text branch's spelling, the stream its lines go to and a default
`Located` already holds (5). Each carries its reason in
`residue_introduced.tsv`. The first round killed 56; reading the rest
found the counts and lists the fixture held only one of, the pool's
fallback, the primary document, a range with no markdown and the stream of
the worker line, and a second and third round took the total to 83.

**Anchors.** 16 in `mutate.py`'s Phase 70 block, one per surface, the two
repairs reverted, two that only Linux can kill: 506 in all. On a copy, the
14 portable ones were killed on Windows in 32 minutes and the two Linux-only
ones in WSL; none hung, none overturned by the serial check.

**Gated, Phase 70**, on the final tree before any commit. 1,781 tests: on
Windows 1,770 pass and 11 skip, on Linux 1,779 and 2, serially and in CI's
shuffled order. mypy clean on 150 files; 506 anchors match. The chain on an
extract: smoke 0 new and 0 missing, scenarios 213 of 213, fuzz 0 violations
at CI's seed, `--self-check` 23 of 23. `--verify` exits 0 here and on a
main-only clone; `--selftest` fires 7 rules with 0 silent;
`--introduced-since origin/main` reads 544 introduced lines with 0
findings.

**Not run: the corpus identity gate.** It compares `--sweep` outputs, and
nothing `--sweep` runs imports introduced_since.py, so its answer is 0 of
152 by construction. The harness chain does run this mode - the fuzzer's
`INTRODUCED` oracle among it - and ran on an extract.

## sweep.py under mutmut: 140 survivors, its report compared whole

Phase 71 (2026-10-08) is D7's fourth surface. D7 found 140 of sweep.py's
667 mutants alive after the whole suite: 88 in the report `run_sweep`
prints, 24 in what it prints for a repository with no markdown, 15 in the
arguments `_survey_notes` hands on, 10 in the per-stratum breakdown; mypy
rejects 30. The tests asserted single lines of the report, and in SARIF
mode, where it moves to stderr, nothing about the stream at all.

**The tests.** `tests/test_sweep_outputs.py`, twelve tests. One
repository reaches every branch of the report: a configured primary
document and extra, each with a claim; two translations sharing a dead
link, which the text groups and counts as one entry; a vendored document
for the breakdown; an excluded document beside a pattern that cannot
exclude and two that match nothing; two documents that are not UTF-8; a
pattern switched off; and two files the consistency rule finds
disagreeing, so a repository finding is reported. Compared whole in text -
with GitHub's SARIF limit at 0, so the text names no cut - and in SARIF,
where stderr is compared whole and stdout result by result, each gating as
its section does; again from a pool and from one that cannot start.
Beside it: documents the survey lost, the reading going on past them; a
rule that raised, named once; an unconfigured repository, told nothing can
fail; one holding only reStructuredText, whose markdown rules read
nothing; exclusions that remove everything; a repository with no markdown,
in text and in SARIF; and a breakdown with no ordinary finding.

**The closing measurement.** `m30_redcheck.sh` with the new file run;
CLEAN passed both times.

| | sweep.py |
|:--|--:|
| D7 survivors | 140 |
| killed | 102 |
| caught by `mypy --strict` | 17 |
| equivalent | 21 |

No real row is left, and none was a defect, so sweep.py did not change.
The first round killed 99; the three left that could be killed needed a
rule to read nothing because no document of its kind was swept, which the
reStructuredText repository supplies. The equivalent rows are the stream of
a line only text mode prints, where it is stdout either way (4); an empty
survey's text branch, which renders nothing in either spelling, and its
`repo`, which no result needs (4); `_survey_notes`' defaults, which its one
caller always overrides (3); what the repository rules are handed or where
their findings are filed, since they read no text and both name ordinary
subject files (5); `swept.get`'s default, never reached because a
repository finding's stratum is ordinary (3); an unborn HEAD's `None` beside
`[]` (1); and the pool's size, which no output shows (1). Each carries its
reason in `residue_sweep.tsv`.

**Measured beside it, for the record Phase 70 made.** sweep.py replaces
`\` with `/` in `apply_exclusions` too, but on both sides of the comparison
it makes - the tracked paths and the configured names - so a document named
with a backslash is matched consistently there, and the conflict check is
right. That is not the gate's defect. Seen and not changed: the summary
says "swept N markdown file(s)" when the documents it swept are
reStructuredText.

**Anchors.** 14 in `mutate.py`'s Phase 71 block, one per surface: 520 in
all. The Windows campaign, on a copy, killed all 14 in 37 minutes - none
hung, none overturned by the serial check.

**Gated, Phase 71**, on the final tree before any commit. 1,793 tests: on
Windows 1,782 pass and 11 skip, on Linux 1,791 and 2, serially and in CI's
shuffled order. mypy clean on 151 files; 520 anchors match. `--verify`
exits 0 here and on a main-only clone; `--selftest` fires 7 rules with 0
silent; `--introduced-since origin/main` reads 648 introduced lines
with 0 findings. The payload did not change, so neither the chain nor the
identity gate ran.
