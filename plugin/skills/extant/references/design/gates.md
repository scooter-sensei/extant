# Reading a range: the history reports and the diff gate

Part of the design rationale; [its core](../design.md) maps every part and
section. The modes that read a range of history rather than a tree: the report
of what a range deleted, the gate on what a change wrote, the replay that
measured that gate's reach, and the differential that was measured and
refused. The sections are in the order they were written.

## `--deleted-since`: a report, deliberately not a rule

Claims that were present at a git ref, are false today, and are no longer
written down anywhere.

**It began as a twelfth rule and was demoted, which is the interesting part.**
Every rule here asks a question git or the filesystem can settle. "Was this
claim deleted to hide something, or because it was wrong?" is a question about
intent, and nothing in git answers it. Worse, the common case cuts against a
gating rule: a document claims work was merged, it was not, someone deletes the
sentence, and the document now tells the truth. Gating would fail the build on
the correct fix.

So it reports and always exits 0. A human judges intent, because only a human
can.

**The mechanism is one idea.** Take each configured document as it stood at the
ref, and validate it against TODAY's git. Every finding that survives is a
claim which is false right now, so there is no separate still-false check to
get wrong. A claim is then reported when its subject appears in no configured
document today, AS PROSE.

Those last two words do three jobs. `--archive` stays legitimate, because
relocating an entry keeps the token findable. A claim moved into a code fence
is caught, which matters because fenced code is exempt from every claim rule
and would otherwise silence this one too. And removal is distinguished from
relocation without guessing.

**Findings carry a `subject` for this.** The token lives inside the detail's
English, and scraping backticks out of a sentence is the reason-about-the-
wording trap this project keeps being bitten by. It is optional and populated
rule by rule; the mode skips findings without one and REPORTS how many it
skipped, so partial coverage stays visible in the denominator.

**The ref is a parameter and the default is a tripwire.** `HEAD~1` answers
"what did this commit remove", which is right for a post-commit hook and useless
against a removal split across two commits. CI should pass the merge base,
where splitting within a pull request buys nothing.

**A swapped reference looks the same as a hidden one.** Replacing a dead SHA
with a different token removes the first, and the first is still dead. From
git's side that is indistinguishable from concealment. The mode says so in its
own output rather than guessing, and there is a test asserting it IS reported,
so that nobody later improves it into a heuristic.

## `--introduced-since`: a gate with no document to configure

The measurement in CORPUS.md is the product problem: a default install
gates 7 of the 5,691 ordinary findings the survey sees, 5 of 50 benchmark
repositories report anything under it, and every wider policy in that table
buys reach by pinning paths - 66 for the installed set, 3,305 for
`docs3-ord` - that later move and become findings until somebody edits the
configuration. The cause is document SELECTION, not the rules. This mode
removes the selection: it sweeps the documents a change touched and gates
on the findings that sit on lines the change wrote. Nothing is named,
pinned or baselined, and the row it earns in that table has `paths pinned`
at zero.

**The range is the merge base to the working tree**, and both ends were
decided against a wrong alternative. The working tree rather than HEAD,
because the sweep reads the working tree: diffed against HEAD, a line
inserted above a committed claim shifts every number the diff reports away
from the ones the findings carry - on this checkout the two coincided only
because the uncommitted edit sat below the claim. The merge base rather
than REF, because on a branch that has diverged from REF a plain `diff REF`
shows every line REF has since deleted as a `+` line, which would gate the
branch on claims it never wrote; on a pull-request checkout HEAD already
contains the base and the two are one commit. A ref with no merge base is
a refusal with exit 2, where `--deleted-since` examines nothing and exits
0 - right for a mode that never gates, and wrong here, since a gate that
examined nothing and passed is the failure this project exists to refuse.
The likely first report is a depth-limited CI checkout whose base lies
beyond the depth, and the refusal says so.

**What it does not gate on is stated rather than tuned.** It gates on
claims a change WROTE, never on claims a change BROKE without writing: a
pure rename has no `+` line, so the relative links the move broke are not
on the diff, and neither is another document's anchor into a heading the
change removed. The two repository-scoped rules do not run, because their
findings sit at line 1 of `.gitattributes` or `.extant.toml` - a synthetic
line nothing wrote - and the output names them. And it reads only the
documents the range changed, which `sweep.py`'s docstring forbids a SURVEY
from doing: that promise is about describing the repository, where a claim
dies when the repository changes and not the document, and this mode's
question lives in changed documents by construction. The count of tracked
documents it did not read is printed so the narrowing is visible.

**The diff is read as bytes outside the seam**, which cost a seventh
direct `subprocess` site in tests/test_scope.py's ledger. `_git` translates
every `\r` in a result to `\n` - right for the metadata it returns - and
a patch is written in git's line discipline: a document line holding a
bare `\r` would be cut in two, its second half arriving with no `+` prefix,
and a fragment beginning `@@ -` would then read as a hunk header. The
parser honours a `+++` line only outside a hunk, because inside one every
content line carries a prefix and a document line reading `++ b/x` arrives
as `+++ b/x`; it undoes git's C-style path quoting, which `core.quotePath`
off leaves for quotes, backslashes and control characters; and it pins
every shape a repository's configuration could otherwise change under it -
`diff.noprefix`, `diff.mnemonicPrefix`, `diff.external`, `diff.context`,
`diff.interHunkContext`, a textconv driver. The one bug the parser had
before its tests first ran - a second hunk of the same file arriving in
hunk state and being ignored - was found on reading it back; the test that
would have caught it is now a mutation anchor, so it stays caught.

**Two shapes are named and counted rather than mapped.** A document holding
a bare `\r` is one this tool numbers differently from git - it counts
every spelling of a line break, git counts `\n` - so its findings cannot be
placed on git's lines. Counted across the 114 visible corpus repositories
and 78,878 tracked documents: 1, and it is GDAL's `autotest/gdrivers/data/
rst/byte.rst`, a raster fixture and not prose. Its findings are surveyed,
counted and do not gate. A document git reads as binary - a NUL byte -
prints no hunks and is named as not examined; the same count found 1.

**Measured before it was written, on the only tier that could answer
offline.** The bench, heldout, niche and agent tiers are all `blob:none`
clones - `depth = "full"` in a manifest means full history - so `git diff`
against an older tree there would go to the network for the old blobs, and
the guard from Phase 38 refuses. Only `autopsy/` holds blobs, and 9 of its
13 are visible rows sitting at their bench pin. Recorded bench findings
intersected with `git diff -U0 HEAD~N HEAD` there, on 2026-09-14:

| range | findings on touched lines | ordinary | repositories reporting, of 9 |
|:---|---:|---:|---:|
| last commit | 2 | 2 | 1 |
| last 10 | 8 | 8 | 1 |
| last 30 | 24 | 24 | 1 |
| last 100 | 40 | 37 | 3 |

2,810 findings across the nine. Every hit through thirty commits is in
`obra/superpowers`, the one agent-tooling project of the nine - 18
`bare-dead-sha`, 4 `dead-sha`, 2 `dead-path-pointer` - and only 1
superpowers finding is in any adjudication file, so the precision of
exactly this population is unmeasured. The 3 non-ordinary at a hundred
commits are `vendored`, in moby, where `exclude_paths` is the one-line
answer. On this repository the same intersection at `HEAD~10` is 2 of 31:
a dotted-range example in CHANGELOG.md and the rule-table example in
README.md, the class `.extant.toml` already keeps out of `--verify`.

This is a proxy - false today, on lines written then - and not the mode's
population. The measurement the review asked for is a replay: worktree at
each of the last N first-parent merges, sweep there, keep the findings on
lines that merge added, and adjudicate them. It is runnable offline on the
same nine repositories and nowhere else without a deliberate retrieval of
old blobs, and it is owed, with the CORPUS.md row it would produce.

**Strata gate; they still label.** CORPUS.md restricts every wider policy
to the ordinary stratum because pinning `CHANGELOG.md` gates on its whole
history. A touched line has no history: a changelog line written in this
change is a live claim by the person writing it. So every finding on an
introduced line gates whatever its document's stratum, the stratum is
carried as it is everywhere else, and a vendored tree that a change bumps
is what `exclude_paths` - honoured here, counts printed - is for.

**Owed.** The action's `mode` input takes `verify` or `sweep` and the REF
has nowhere to go, so the README wires the mode as a plain step; a `since`
input is the next change. The replay above. And a fuzz oracle asserting
that every gated finding's line is a `+` line of the same diff, which the
CRLF and encoding axes would exercise on hostile documents; the mode is in
the fuzzer's mode list and its three ledgers, so the crash, exit,
denominator, format and concurrency properties already reach it.

## The diff-scoped gate, replayed; and the debts the shipped items carried

Tranche 10 of the internals review, 2026-09-20, the first after the nine
tranches merged to `main` as pull request 13. Nothing here is a new item of
the review; every piece is a debt one of the shipped items left on its own
record - the probe `--introduced-since` was shipped without, the note the
ancestry bound earned and did not print, the two notes the survey never
printed, the field the rename hint should have moved into when the
commit-map hint did, and the sentences three closed items still owed.

**8.1's probe, run.** The mode shipped in Phase 40 with its measurement
undone: the review said "measure it into the policy table before you believe
me", and the table's rows are sweeps at HEAD, which a gate on lines a change
wrote cannot be read off. Phase 40 substituted a proxy - bench findings at
HEAD intersected with `git diff -U0 HEAD~N` - and said plainly it was not
the mode's population. The population is a replay: the last 50 first-parent
commits of each of the 13 autopsy clones (a merge, a squash and a direct
push are each one integrated change, and `--introduced-since <first
parent>` from a detached worktree at that commit is what the gate would
have said when it landed), 650 changes, every one run rather than only the
ones a pre-filter thought touched documentation, because the tool's own
header says how many changed documents it examined and that number is the
denominator. The apparatus is `m10_replay.py` in the extant-hardening
checkout; one JSON line per commit under `D:/repo/out-replay/`, judged in
place while the worktree stood at the commit, with the instruments the
precision table was built with - `resolution_audit.reading`,
`gated_precision.anchor_resolves`, and for a SHA the two mechanical tests
`groundtruth.py` applies - and the four context annotations that file
keeps beside a verdict, annotated and never a veto, because the 641
hand-labelled findings confirmed placeholder-shaped bare SHAs 64 times in
65. Skew, stated: the tree is the commit's own and the refs and object store
are today's, so a branch deleted since reads dead and a commit merged since
reads merged. The worktrees under `D:/repo/replay/` are linked worktrees;
`common_git_dir` finds the shared `.git` and `environment()` drops what the
parent shell leaks, which the first run confirmed rather than assumed.

The numbers, all rendered into `CORPUS.md` from `CORPUS-figures.json` under
"The diff-scoped gate, replayed", so they cannot go stale in prose: 273 of
the 650 changes touched a document the tool reads, 1,168 document-changes,
24,467 introduced lines; 9 changes would have gone red, 36 findings, 33 of
them ordinary and 3 vendored (moby, where `exclude_paths` is the one-line
answer and the strata label rather than exclude); 3 repositories report in
any stratum, 2 in the ordinary one; 0 paths pinned. Read against the ladder
on the SAME 13 at HEAD, from the same recorded sweep the published table was
aggregated from: `installed` reaches 2, `root+docs-ord` 5, `docs3-ord` 9,
`ordinary` 11. The diff-scoped gate reaches what `installed` reaches, at
zero pinned paths against `installed`'s 66, and not what `docs3-ord`
reaches. **The review's bar - "if it reaches the repositories `docs3-ord`
reaches while pinning nothing, it replaces the default install policy" - is
not met, and the mode stays what Phase 40 shipped it as: the gate for a
pull request, beside the document-scoped default rather than instead of
it.**

What the replay measured instead is the review's other reading, with a
number: at the moment each change landed, the documents it touched held 211
findings, and 36 of them - 17.1 per cent - sat on lines the change wrote.
The other 175 sat on lines the change did not touch, findings the mode
reports as "aside" and does not gate. A document-scoped gate fails on all
211 at that moment; the diff-scoped one on 36, by design. Documentation
claims go false without being edited, and the gate that pins nothing sees
the least of it. This is a lower bound on the "never true when written"
share and says nothing about the rest; splitting the 175 into born-false
and rotted is the review's 4.9, a per-finding question for `git log -S`,
not this replay.

The reach it has is one repository's. `obra/superpowers` carries 31 of the
33 ordinary findings and would have gone red on 6 of its 34 document-touching
changes, every one in a plan or spec document under `docs/superpowers/`
written during an agent session - 23 `bare-dead-sha`, 6 `dead-sha`, 2
`dead-path-pointer` across the six. The shapes are the ones the corpus has
met before: seven-character placeholders in an implementation plan, the
short ids of an evaluation's own workspace, a nine-character citation of a
commit that exists nowhere in this history. Whether that reach is a property
of agent-written documentation is a question about the agent tier, which is
`blob:none` and cannot be replayed without retrieving its history; the
figure names it as a hypothesis with one repository behind it, and the
memory note about pilots applies before anyone scales it. Precision of
exactly these 36: 0 resolve under any reading in the tree at their commit,
7 carry the `future-tense` annotation, 0 sit in a fence, 0 on a
placeholder-shaped line, 0 in a template tree.

Read by hand on 2026-09-21, in the gap audit that closed tranches 10 and
11, because the review asked for the replay's findings to be adjudicated
the way the precision sample was and the paragraph above had judged them by
instrument alone. All 36 are dead as stated. (Corrected 2026-09-28, when
the read was repeated to write it down as labels: 33 are. Vitepress's two
anchors are answered by `> ## Notices`, a heading inside the block quote
the licence is copied into, which the anchor set does not read; and one of
moby's three is a vendored README's floor read against moby's own
manifest. The section "The owed bundle" in `quality.md` has the labels.) Of the 31 in `obra/superpowers`,
22 sit in QUOTED text: ten in blockquoted grader output that cross-checks
five commits of an evaluation workspace against that workspace's `git log`,
six in a list quoting the same output beside a grader's own verdict that
four ledger hashes were "stale/fabricated", six in a bracketed example of a
ledger line whose commit ids are the keyboard's first placeholders (not
quoted here, for the reason this sentence gives) - text the authoring
constraints already say the rules cannot tell from a claim. Six more name two cleanup
commits of the same workspace in the document's own prose. Three are the
document's own claims: one bare seven-character id whose origin the line
does not say, and two path pointers, one of them future-tense. The two in
`vuejs/vitepress` are a licence notice's `[Notices](#notices)`, copied into
a compiled third-party-notices file whose headings are its own. So the
mode's one-repository reach is narrower than the sentence above says: 28
times in 31, what it would have failed a build on is an agent's transcript
of ANOTHER repository's commits, quoted or cited - dead here by
construction, and exactly what an author would want told is unverifiable
here.

Population, stated: `Aider-AI/aider`, `astral-sh/ruff` and `vuejs/vitepress`
are reserved rows in the benchmark manifest, read here through their autopsy
copies, which every identity run since Phase 43 has swept; without the three
the ordinary count is 31 in 1 repository, the same picture. The figure
carries the three names.

**The action, and the oracle.** `action.yml` takes `mode: introduced-since`
with a `since` input - on a pull request,
`${{ github.event.pull_request.base.sha }}` - and refuses the mode without
it, naming the input, rather than passing `--introduced-since ''` to a CLI
whose refusal would then explain merge bases. The three packaging tests that
pin the action's shape (no interpolation into the script, no version of its
own, every mode a CLI flag) still pass, and three more run the step under
bash with a stub `extant` on PATH and read the command line it assembled. The
fuzzer's twenty-second property, `INTRODUCED`, parses `git diff -U0` for
itself - importing the tool's `introduced_lines` would agree with it by
construction - and requires every finding the mode gates to sit on a line
that diff added. It chooses its own range, the parent of the last commit
that changed a document, rather than the mode list's `HEAD~1`: the
self-check's repository ends with a binary under an LFS filter, so a range
of one commit held no document, examined nothing, and no breakage of the
gate could be seen through it - `INTRODUCED` was NOT OBSERVED on its first
run for exactly the mirror image of `AXIS`'s reason, a sound breakage
watched through a window that showed nothing. With the range chosen from
the history, 22 of 22.

**4.2, plumbed.** The commit-graph note was measured in Phase 41 - 7.5x on
the index, 27x on the batch, 77x on `merge-base`, on rust - and not built,
because its only deterministic trigger, an index that came back incomplete,
is a fact of the run scope and every mode prints its repository notes after
that scope has closed. `RunScope.index_incomplete()` answers the question of
the scope; `session.ancestry_incomplete()` asks it of the ambient one;
`run_validate` and `run_check_text` read it inside each `with
session.run_scope():` block before the block closes, `run_validate` OR-ing
the archive's and the extras' scopes into one flag and printing the note
once at the end if only they raised it; the survey's `_validate_one` returns
it as the sixth element of its tuple, because a worker's scope dies with the
worker, and the parent OR-s across every document's outcome;
`--introduced-since` does the same through the same `survey()`.
`git.has_commit_graph` is one stat on the shared git directory, in both
spellings git writes - `objects/info/commit-graph`, and
`commit-graphs/commit-graph-chain` after `--split` - so a linked worktree
answers as its checkout does and the spawn budget is untouched. The note
prints only when both hold - incomplete AND no graph - since a bound the
history merely exceeds is not a cost anyone paid, and a repository holding
the file is already paying nothing; it names `git commit-graph write
--reachable` and writes nothing. The prediction made before the identity
run said the note would change no corpus output: no visible sweep examines
a merge or live claim, and moby, the largest autopsy history at 57,797
commits, carries no release claim either. The prediction forgot the eight
sweeps that examine a release claim, and one of them is cpython, at 132,999
commits with no commit-graph: its sweep examined one release claim, built
the index, hit the bound, and printed the note - the first time it has
fired anywhere, on exactly the repository shape it was written for. The
count of differing outputs matched the prediction; the composition did not,
and that is recorded as the miss it was.

**The survey's notes.** `--sweep` printed neither the shallow nor the
partial note - the shallow one for the five weeks it had existed, since
2026-08-17, and the partial one since Phase 38 four days earlier - on the
mode most often pointed at a repository nobody here had seen. (This
sentence said "for a year" until Phase 50 dated it against the log; the
repository is two months old.) It prints them now through the one implementation the
gating modes share, once, after the `examined:` line; the third note rides
with them. 139 of the 152 visible clones are partial (`blob:none`) and the 13
autopsy clones are full, so the identity gate's prediction was exactly 139
outputs differing, each by that one added line, and the 13 byte-identical.
Observed, against the after-side of Phase 46's second run: 152 compared,
139 differ - 138 by the partial note alone and cpython by the partial note
and the commit-graph note together - and the 13 autopsy outputs
byte-identical, which is also the rename hint's field change holding its
promise that no text output moves. The first diff, run against Phase 46's
FIRST after-side by mistake, showed 141: the two extra were the ruff and
moby findings that gained their hint when `-M` landed, present on the
correct before-side and absent on the stale one - a wrong before-side
reads exactly like a regression, which is why the diff names its inputs.

**The rename hint's field.** Phase 39 recorded the debt: the hint sat inside
`detail`, so inside the baseline fingerprint, although it varies with the
checkout while the dead link does not - the argument that moved the
commit-map hint into `repair` in 0.25.0. It is a `repair` now at both sites,
`dead-md-link` and `dead-path-pointer`; `message()` renders `detail; repair`,
so every human-facing format and every corpus text output is byte-identical,
and only a hinted finding's fingerprint changes, which the changelog says
and a baseline recorded before it will notice once. On the visible corpus
exactly 2 findings carry the hint, the two Phase 46's `-M` fix gave it to.

**The three sentences.** 6.2's closure now sits in the `line_number_at`
docstring beside the divergence it closes (15 of 108,647 documents, 0.014
per cent); the `signal.setitimer` refusal sits beside the watchdog thread's
in the regex-hang record among the known limits in `../design.md`, confirmed by inspection of the interpreter
rather than by measurement; and the sentence in `scope.py` that still
described `_STRIPPED` as missing the format 6.1 had given it says so no
longer.

**The gate.** Suite, five anchors written and two retargeted on the lines F
and D changed, each applied to a copy and watched turning the suite red; the
corpus identity sweep against the prediction above; the pre-push chain
against a working-tree extract with `--self-check` at 22 of 22. The
replay itself ran from a `git archive` extract of `main` at the merge, so
its numbers are the shipped mode's and not the branch's.

## The differential gate, measured and refused: what a change breaks without writing it

Tranche 20 of the internals review, 2026-09-29, and measurement only: no
shipped file changed. It decides D2, whether a gate on claims a change BROKE
is ever built.

**The question.** `--introduced-since` gates on the claims a change wrote,
and its docstring says what it does not do: a heading removed under another
document's anchor, a pure rename that leaves a moved file's relative links
pointing nowhere - those have no `+` line. The scrutiny of pull request 13
proposed catching them with a fingerprint differential, a sweep at the base
against a sweep at the head, sorting every finding into four buckets:
introduced (new, on a line the change wrote - today's gate), broken (new, on
a line it did not write - the proposal), standing, and repaired. Its own
bars: broken should be at least an order of magnitude larger than
introduced, or the differential is not worth its cost; broken precision
below about 95 per cent cannot gate; and any flip the change did not cause
is an instrument defect. Refusal was named in advance as a normal outcome.

**The population and the apparatus.** The Phase 47 replay's 650 changes -
the last 50 first-parent commits of each of the 13 autopsy clones - and so
663 trees, 51 per clone, because each commit's first parent is the next
row's commit. That was checked against the rows rather than assumed, and it
holds because no clone has been fetched since. The instrument is
`m20_buckets.py` in the extant-hardening checkout, beside `m10_replay.py`
and using its worktrees and its `judge`. It sweeps each tree from one
extract of `main`'s package, persists every finding under
`D:/repo/out-buckets/`, and computes the buckets offline, so a killed run
resumes and a changed question does not sweep again. 663 sweeps, 0 errors,
29.8 minutes.

**Six things the first design would have got wrong.** Three premises failed
when checked against the rows before anything ran:
- The fingerprint is not stable for four rules, because `detail` embeds a
  value that moves while the claim does not: `dead-line-pointer` the target
  file's line total, `manifest-floor-mismatch` the manifest's spec,
  `inconsistent-artifact` the disagreeing values, `raw-lfs-blob` the blob's
  size. The buckets are computed twice, on today's fingerprint and on one
  with those four normalised, and the difference is counted as churn.
- A dict of fingerprints loses multiplicity: one dead target cited twice is
  two findings with one fingerprint, and on moby 297 of 450 findings share
  one. The buckets compare multisets - per fingerprint, the smaller of the
  two counts stands, and only the surplus is new or repaired.
- The 377 changes that touched no document were proposed as the false-flip
  probe. They are where a broken finding comes from - the moved target, the
  shortened file - so counting their flips as defects would count the
  finding the tranche was looking for. The probe is a flip whose document
  and target the change both left alone.

Three more were found in the candidate shape before it was built, each now a
rule of the instrument:
- The gate never reads the base. It flags a dead claim on a line the change
  rewrote whether or not the claim stood before, so its gated set is
  introduced plus a fifth bucket, rewritten - stood in the base, sits on a
  written line - and the oracle compares against that sum. Checked against
  introduced alone, the oracle would have failed on correct data.
- A site generator's configuration decides what a link resolves to, so a
  change to it can flip a finding whose document and target it never
  touched. The probe counts every configuration `sites.py` reads as
  touched, matched generously by name - 15 of the 650 changes touch a file
  so named, 8 of them in vitepress.
- When a fingerprint's head count exceeds its base count, the new instances
  are taken from written lines first, so an ambiguous instance is counted
  introduced and never inflates broken.

A synthetic repository broken six known ways - a moved target, a dropped
heading, a shrunk file with a grown one beside it, a renamed document, a new
dead link written beside a rewritten old one, and a repair - was labelled
correctly in all six, in both modes, before the campaign ran.

**The oracle held, and three wider checks with it.** Per commit,
introduced plus rewritten against the gate's own gated findings from the
same package: 30 and 30, 0 changes disagreeing. That checks 30 findings in 8
changes, so the gap audit of the built tranche added three checks the rows
already allowed, over all 650: the findings in changed documents on lines
the change did not write equal the 175 the gate's header counts as set
aside; the changed documents the instrument reads equal the gate's count;
and so do the introduced lines. 0 changes disagree on any of the three.
Rewritten is 0 in this population - no change in 650 rewrote a line holding
a claim that was already dead - so that fix was exercised by the synthetic
repository alone.

**The buckets**, normalised, with today's raw fingerprint in brackets where
it differs:

| bucket | findings | changes |
|:--|--:|--:|
| introduced | 30 | 8 |
| broken | 4 (5) | 1 (2) |
| broken, repository rule | 0 | 0 |
| repaired | 145 (146) | 18 |
| standing | 74,851 (74,850) | - |

Broken against introduced is 4 against 30, a ratio of 0.13. The bar was 10:
it is missed by a factor of 75.

The repository-rule row is empty by construction, not by measurement: both
repository-scoped rules examined 0 claims in all 663 trees, because no clone
configures a consistency check and none holds an LFS claim. So the case the
preparation named - a version bumped in one file of two, a real break the
gate never sees - is unmeasured here. The entry rules, `false-merge-claim`
and `dead-pinned-ref` also examined nothing, and `dead-release-tag` one claim,
in babel. What this population can show is the file-backed rules and the
SHA rules, and a SHA finding can flip only when its document changes, since
both sweeps of a pair read one object store.

**The hand-read: all four.** One change in prometheus/docs, a merge that
moved the contributing sections of its community page into a new guide. The
page had two headings reading "Slack channel", and a renderer gives the
second the duplicate's `-1` suffix. The move took the second heading and
left four links to it, in the mentorship section, on lines the change did
not write. All four are dead as stated, at the commit and at the clone's
HEAD two months later. Four of four is 100 per cent, and a 95 per cent bar
cannot be read off four findings from one change: the lower 95 per cent
Wilson bound is 51.0 per cent.

**Where broken lives, and how often it could have.** All four sit in a
document the change edited, and 0 in a document it did not touch. They were
not invisible to the gate: they are 4 of the findings its header counted as
sitting on lines the range did not touch, in a document it had already
read. The scrutiny's own example - a move leaving ANOTHER document's link
dead - occurred 0 times in 650 changes, and the exposure says why: only 24
changes deleted or renamed any file, 4 of them a document. Resolving every
link and backticked path in the base's documents finds 3 changes that
deleted a file another document named. Two edited that document in the same
change, so nothing was left pointing at the file. The third left a
superpowers plan reading "Create:" before the deleted file's path, an
instruction `dead-path-pointer` does not read by design. For anchors, 48
changes removed at least one - 1,853 anchors in all - and at the head
exactly 4 relative links still targeted one: all 4 reported, and they are
the four above. So `broken` is rare here because authors mend what a change
breaks in the same change, not because the rules miss it. What the rules do
not read is outside the question: a gate built from these rules could not
see it either. The one document rename in the population, in ruff, broke
nothing, and held no finding before or after, so the rename mapping was
exercised by the synthetic repository alone.

Every one of the 145 repairs was checked against the diff rather than
sampled: 138 had their own line removed or rewritten, and 7 sat in a
document the change deleted. Most are three shapes: 120 in one rewrite of
babel's test262 allowlist, one in each of twelve fastapi translations that
dropped the same dead link, and seven SHAs that left superpowers with the
evaluation notes that held them.

**The churn.** 0 flips the change did not touch, in either mode, so no
fingerprint defect beyond the four details named above - and since 0 of
roughly 75,000 standing findings flipped in a document no change touched,
the sweep is also deterministic across trees. The raw churn is one finding:
a superpowers plan's pointer at line 211 of a skill file, dead before and
after, while the file shrank from 202 lines to 167. Today's fingerprint
reads it as one broken and one repaired; normalised, it stands. That is the
count the baseline debt was owed, and it needs its denominator to be read:
the four churning kinds hold only 12 findings in the whole population - 9
`manifest-floor-mismatch` in moby, none of which moved, and 3
`dead-line-pointer` in superpowers, of which that one moved within 50
changes. Once in 650 changes is a statement about how rare the kinds are
here, not about how stable the fingerprint is. A project whose plans cite
code by line would un-suppress a baselined pointer whenever the cited file
changed length. The fix has a precedent - move the moving value from
`detail` into `repair`, as Phase 47 did for the rename hint - and stays
owed, with these numbers, for a later bundle.

**The cost.** Two sweeps per change took 3,182.6 s over the 650, against
the gate's 311.7 s over the same changes: 10.2 times the gate, plus 65.9 s
of checkouts the gate does not need. The two were timed in separate runs on
the same machine and package, the gate's earlier the same day. (The
preparation's figure of about 14 times was two sweeps at HEAD against the
gate's mean; over the replay it is 10.2.) fastapi, the most documents of the
13 at 1,692 tracked, sweeps in a median 3.10 s; aider is the slowest, at
8.58 s. No autopsy clone is near 5,000 documents, and the benchmark tier's
base trees cannot be checked out offline, so that figure is unmeasured.

**Ref attribution is empty here by construction.** The clones' reflogs hold
the replay's own worktree checkouts rather than history, and across the 13
at HEAD the ref-backed rules examine one claim and report none. Both sweeps
of a pair also answer against today's refs and object store, so a
ref-backed flip cannot occur in this instrument at all. In a pull-request
gate the refs cannot move under the change, which was the scrutiny's own
reading; measuring it on this repository's own history remains a separate
item, worth taking only if D2 is ever reopened.

**The population's limit.** Mature projects, their last 50 integrated
changes each. The agent tier, where documents are written and moved fastest,
is `blob:none` and cannot be replayed offline, the limit Phase 47 stated for
the same replay. superpowers, the one agent-written clone with blobs, held 2
of the 3 deletions another document named.

**D2: refused.** Every bar that can be read fails, and the one that cannot
be read rests on four findings. The ratio is 0.13 against 10, the cost is
ten times the gate, and the four it would have added were not the
proposal's shape: they sat in a document the change edited, among the
findings the gate already reads and sets aside. A narrower differential -
the changed documents alone, swept at the base as well as at the head -
would have caught all four. Its cost is unmeasured: estimated from the
gate's own timing, about twice the gate plus a checkout of the base. It is
recorded as the shape to measure first if another population - the agent
tier, once it can be replayed - shows broken approaching introduced, and
not proposed now: at 4 against 30 it misses the same bar.

**The gate.** Measurement only, so no anchors and no identity sweep. The
synthetic six, before the campaign; the oracle and the three wider checks,
per commit; every broken finding read and every repair checked against its
diff; the suite and `--verify` after these records. The hand-read's labels
are in `D:/repo/out-buckets/handread.jsonl`.
