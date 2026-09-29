# Keeping the tool honest: the suite, the types, CI and the reviews

Part of the design rationale; [its core](../design.md) maps every part and
section. How the tool's own checks are checked: what the suite counts, what
the type checker can and cannot see, what CI runs and on which surfaces, and
the review bundles that closed what earlier tranches owed. The sections are in
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
