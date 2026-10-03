# Design rationale

Why each rule is scoped as it is. Every decision below was forced by a real
failure - reasoning from first principles produced the wrong answer at least
three times, so the incidents are recorded alongside the rules.

## How the rationale is divided

It grew to 5,133 lines in one file, and on 2026-09-29 it was divided by
subject. This file keeps the core - how the tool is built, what every rule
must satisfy, the limits found by probing, and the constraints the rules
put on authors - and the other sections live in eight parts under
`design/`, each in the order it was written. The sections moved verbatim;
the only words changed are four cross-references that would otherwise
have pointed across a file boundary. Read this file before changing a
rule, and the part its subject belongs to before changing anything else.

| part | its subject |
|:--|:--|
| [Rules, strata and the baseline](design/rules.md) | what each rule reads and skips, the strata a document falls into, and what the baseline forgives |
| [Widening the rules](design/widening.md) | the corpora the rules were measured on, and every widening proposed, shipped or refused |
| [History](design/history.md) | trunks and integration branches, the bounded ancestry index, rewrites and rebases |
| [Boundaries](design/boundaries.md) | where bytes are decoded, the environment git inherits, and what the tool may read |
| [Performance](design/performance.md) | run and document scopes, caches, batches, and the indexes measured and refused |
| [Reading a range](design/gates.md) | `--deleted-since`, `--introduced-since`, its replay, and the differential refused |
| [Code blocks](design/code-blocks.md) | indented code and fences, and the renderers they are judged against |
| [Keeping the tool honest](design/quality.md) | the suite's own denominator, the type checker, CI, the review bundles, and what a mutation campaign costs |

Where each section went, by its title:

**Rules, strata and the baseline** (`design/rules.md`):
- `raw-lfs-blob`: Git LFS, and the direction that had to be refused
- The game-engine presets, and the widening that was measured and refused
- The baseline, and the two things it deliberately does not do
- `possible-secret`, removed in 0.14.0
- Generated sites, and the two anchor namespaces
- reStructuredText, skipped rather than tuned
- Strata: a property of the document, not a setting to configure
- The baseline forgives what it recorded, and no more
- A schemeless URL is not a path, and the fix is a suppression
- A declared stratum, measured and refused
- The bare commit-link text: whose commit it is, and a number re-derived

**Widening the rules** (`design/widening.md`):
- What a held-out corpus said about detection
- The coverage phase: eight widenings, none shipped
- Examined and declined
- A correct rule can be low-yield, and that is the world rather than the keying
- The second widening pass: ten proposed, four shipped
- The third widening pass: six proposed, one shipped

**History** (`design/history.md`):
- Integration branches, and why one trunk was not enough
- The ancestry index is bounded, and a batch settles what lies past it
- The post-rewrite journal: the record a rebase leaves, kept
- The four probes: a split only the network can make, a rebase that reaches nothing, a rescue with no population, and the gate's missing listing

**Boundaries** (`design/boundaries.md`):
- Where a decode happens is a decision, not a default
- The conservation check proves a value, not a write
- A configured pattern that will not compile should name itself
- The environment a git process inherits is an answer, and it was the wrong one
- The review of pull request #16: a configured source that could read anything

**Performance** (`design/performance.md`):
- Cache scope: one call, and the one place it widens
- The survey runs in one process or eight, and says which
- Where a sweep's time goes, measured without the profiler
- A path index, measured and refused
- One document scan, measured and refused; its bar all but met without it
- The probe tranche: one batch, one scope, one list, and a matcher read against git

**Reading a range** (`design/gates.md`):
- `--deleted-since`: a report, deliberately not a rule
- `--introduced-since`: a gate with no document to configure
- The diff-scoped gate, replayed; and the debts the shipped items carried
- The differential gate, measured and refused: what a change breaks without writing it

**Code blocks** (`design/code-blocks.md`):
- The other code block: four spaces, and the renderers that disagree about them
- One scanner for both code blocks: a fence ends where its container does

**Keeping the tool honest** (`design/quality.md`):
- The suite's own denominator, and the number the review could not see
- Five correctness items, counted; four changes, and what the counts refused
- The structural tranche: one Config, and two shapes the numbers kept
- The type checker: four measured, the floor none can see, and a gate on the one that enforces the most
- CI honesty: the version the maintainer runs, the surfaces adopters run, and a third order
- The owed bundle: what a zero means, where a patch ends, and what a partial copy cannot answer
- What a zero means: a rule names its vocabulary, and off is a state
- The mutation campaign, made cheaper without moving a verdict
- CI, made cheaper without moving a verdict
- The 2026-10-01 audit: thirteen repairs, two of them measured first
- The gap audit of that audit: five repairs, one of them a deletion
- Six invariants held as properties: two defects, and the generator that decides what a property can find
- The gap audit of the properties: nine findings, and a derandomized run that was not
- mutmut as a cross-check: what the hand-chosen anchors missed

## Architecture: fat script, thin subagent, validator gates the commit

```
/extant
   |  the invoking session writes a friction summary from its own context
   v
subagent
   |
   +- 1. extant_collect.py --collect   -> bundle.json   (facts, no prose)
   +- 2. drafts the entry from the bundle
   +- 3. extant_collect.py --archive   (AFTER drafting; see below)
   +- 4. extant_collect.py --validate  -> exit 0/1
   +- 5. commits ONLY if step 4 exits 0
```

Steps 1, 3 and 4 are deterministic Python. Step 2 is the only LLM step.

**Why archiving is script-side:** asking a model to rewrite a 1,800-line file is
asking it to silently drop content. Splitting on header boundaries is trivial
deterministic text surgery, and it can assert conservation.

**Why the friction summary comes from the parent:** the session that experienced
the friction is the only thing that knows it. Mining transcript files couples the
tool to an undocumented internal format.

## The core guarantee

**No rule inspects numbers or dates.** Historical facts ("the suite was 2238 at
release 3") are true when written and never re-checked. This is structural: no
rule exists that could flag them.

Adding a numeric cross-check is the most tempting available mistake. It looks
helpful, and it reintroduces the false-positive class that makes a validator get
ignored. Every rule must be falsifiable against git or the filesystem.

## Adding a rule

Rules live in `extant/rules/`, one module per rule, collected into a registry
by `extant/registry.py`. Each declares what it emits, its scope, whether it
survives archiving, and - required - the exact yes/no question it asks of git
or the filesystem:

```python
RULE = Rule(
    kind="false-merge-claim",
    sequence=4,
    check=check,
    scope="whole-file",
    in_archive=True,
    falsifiable="is the claimed commit an ancestor of the ref the claim names?",
    probe=probe,
    examined=examined,
    settings=("merge_claim",),
)
```

`settings` names the configuration keys the rule's vocabulary comes from,
and is empty for a rule keyed on a token shape. It is what a zero means:
the run words each rule that examined nothing by it - nothing of that shape
here, a pattern the project set that matched nothing, or the shipped
default, naming the key - and an empty value switches the rule off. A test
reads every rule module and fails when what it reads and what it declares
differ. One limit, stated: "set" means present in `.extant.toml`, not
checked by a person, so an installer's guess counts as set.

**The admission test:** a rule belongs only if it can be answered yes/no by git
or the filesystem, AND produces zero false positives on a corpus it was NOT
designed on, AND names the place the answer lives. A test enforces the first
clause - every rule must state its question - so a rule that inspects numbers
or dates cannot be added quietly. The second is on you: measure before you
write the pattern. The third is free, and predicts the second.

"Not designed on" is load-bearing and was added after it was paid for. Every
rule here had been tuned against 92 repositories until they were quiet. Run
against 40 none of them had seen, the same rules produced 7,658 findings of
which 582 were real, and fourteen distinct false-positive shapes were living
in the gap between "quiet on the corpus that shaped it" and "correct". None of
them was visible by reading the code. Keep a corpus back.

**Read the `falsifiable` line of any rule above and notice what it points at.**
`git cat-file -e <sha>`. *That* ref. *The cited* file. *The configured* files.
*This* document's headings. Every one names a bounded location and asks
something with a definite answer there.

Now compare a candidate that fails: "does this documented environment variable
appear anywhere outside the documentation". No location, just a search of
everything, with a report if nothing turns up. Absence over an unbounded space
has innocent explanations - built by concatenation, read through a prefix scan,
re-exported, mounted under a router prefix, or owned by a dependency - and each
one is a false positive. **A documented token this project does not implement
is usually a token belonging to something else.**

Six candidates have been measured and rejected. Four of them - environment
variables, code symbols, HTTP routes, CLI flags - clear the first clause
cleanly and die on a corpus at 0% to 22% precision. All four violate the third,
which could have been checked in a minute without cloning anything.

**And the third clause is not sufficient.** Two further candidates were chosen
because it endorsed them, and both failed. "Does the compose file publish a
different port than this document states" names its location perfectly, and
means nothing: a development compose file publishes 76 ports while the
documentation mentions 18 others, none of them the same subject. So there is a
fourth requirement - **the two sides must name the same SINGLE fact** - and it
is the one that explains why `inconsistent-artifact` asks the user for
patterns. Only the author knows which two strings in their repository refer to
one thing. That is not overhead around the rule; it is the rule's essential
input, and it is precisely what a port comparison cannot obtain on its own.

Candidates that would pass: release-tag claims (does the tag exist and is it on
trunk?), branch existence (a branch named in prose but absent - currently a real
gap), deletion claims (does the file still exist?), ordering claims (git
ancestry).

Candidates that would fail, and why: suite-count consistency and date validity
are numbers, which is the forbidden class; issue and PR links need the network,
breaking the deterministic-local guarantee; "does this summary match the diff"
is judgement, not falsifiable.

### A falsifiable question is not a sound inference

Every candidate above is refused by inspection, on the FIRST half of the test.
The harder rejection is the one that clears the first half convincingly and
dies on the second, and environment-variable rot is the worked example.

"Does this documented variable appear anywhere outside the documentation" is a
clean filesystem question. It needs no network, inspects no number, exercises
no judgement, and unlike most candidates it is language-agnostic. It measured
at **37 examined, 8 true, 29 false**, and every true positive was in one
repository.

The question was fine. The INFERENCE was wrong: absence of the literal does not
mean absence of the variable. Prefix scanning reads `FLASK_SECRET_KEY` without
that string existing; poetry builds all 32 of its names by concatenating onto
`POETRY_`; minio composes one from a config key; `CARGO_HOME` is documented
precisely because something else reads it. These are not edge cases, they are
the ordinary ways environment configuration is written.

Three further lessons, each of which cost a measurement:

- **A confidence gate can be contaminated by the signal it seeks.** Calibrating
  on "what share of documented variables appear in source" silenced the only
  repository with genuine findings, because having true positives is exactly
  what lowers that score. Any per-project gate needs checking for this shape.
- **Absence in history is not the same as removal.** Asking git when the name
  disappeared finds nothing, because the true positives were never in source at
  any commit. They were never implemented rather than implemented and dropped.
- **Erring safe is not a defence for a wrong answer.** A check that refuses to
  call anything clean trains its reader to overrule it, and the reader then
  overrules it on the occasion it is right.

The full measurement, six approaches and five corpus probes, is kept outside
this repository with the rest of the candidate evaluations. What belongs here
is the shape: a rule can be perfectly falsifiable and still infer something the
evidence does not support.

`validate(repo, text, in_archive=...)` iterates the registry. The caller says
what the document IS and the registry decides which rules follow - replacing a
`check_live_claims` boolean that forced every caller to know the rule list and
would have needed a second boolean for the next rule.

## Rule scoping, and why each answer differs

### Live claims - newest entry only

First version checked the whole file and fired on an entry that honestly stated
its own past status was "retained as written history". That is a false positive
on self-describing prose, and it is how a validator loses trust.

Narrowing to the newest entry is principled, not a patch: a present-tense status
is only meaningful for the current entry. Older entries are historical by
construction.

**Second half of the same fix:** the rule originally required the named branch to
BOTH exist and be merged. Projects that delete branches after merging made the
motivating defect - a false "not yet merged" about shipped work - structurally
undetectable. A claim naming a branch that no longer exists is now flagged too.

### Merge claims - whole file, including the archive

The opposite scope, for a real reason. "Merged at X" is a permanent claim about
the past: it should hold in any entry at any age. A stale "still outstanding"
claim costs a reader redundant work; a false "merged" claim tells them work
landed when it did not, so they build on nothing.

Archiving does not make a false factual claim true, so the archive is checked.

### Path pointers - operative use only

Measured before implementing: **23 of 88 path-shaped tokens did not exist, and
all 23 were legitimate** - completed-phase layout descriptions, deferred work
never built, files explicitly described as deleted. A shape-keyed rule would have
emitted 23 false positives on its first run.

Keyed on operative markers (`Plan:`, `Design:`, `see`, `read`) it emits none, and
still catches the defect that motivated it.

### References - whole file, backticked and bare

A dead reference is worthless regardless of age. Both styles must be checked:
a whole-branch review found 14 dead **bare** SHAs in documents the validator had
already certified clean, because only backticked tokens were being examined.

**Detection and repair must use the same tokenizer.** They did not, once: the
validator scanned per line while the translator scanned whole-text, and because
backticks pair across newlines the two drifted out of phase on **402 tokens**.
The validator reported dead SHAs the repairer was structurally unable to fix.

## Known limits, found by adversarial probing

An adversarial pass, now 18 probes wide, leaves three standing. They are
recorded because an undisclosed limit is indistinguishable from an unknown one:
the harness prints each of these as a flagged observation on every run, and a
flag with nothing written down here would read as a fresh defect every time.

**Claim deletion passes, and no rule will ever catch it.** The validator
compares claims against git. Deleting the offending sentence removes the claim,
so there is nothing left to check and every rule goes quiet.

This is now REPORTED rather than closed, and the distinction is the point. See
`--deleted-since` below: whether a removal was evasion or repair is a question
about intent, which git cannot settle, and a document that deletes a false
claim now tells the truth - which is this tool's entire purpose. A rule that
gated on it would fail a build on the correct remedy. So the mode states the
fact and never affects an exit code, and the workflow-level anti-gaming rules
below still carry the rest.

**A user-supplied regex can hang, unless you ask it not to.** Configuration
accepts patterns and Python's `re` has no timeout, so a catastrophically
backtracking pattern spins. `consistency_timeout_seconds` bounds each search,
and is absent by default.

Three cheaper mechanisms were tried and rejected. A watchdog thread cannot
work: `re` does not release the GIL while matching, so the watchdog is never
scheduled. Nor can `signal.setitimer`, the fourth mechanism and the one a
third reader proposed in the internals review: Python runs a signal handler
only between bytecodes, and one `re` match is one bytecode, so the alarm is
delivered after the match returns - which for the pattern in question is
never. Confirmed by inspection of the interpreter rather than by measurement,
and recorded here so the next reader does not re-derive it. Static rejection
of dangerous constructs is a heuristic whose false
positives reject patterns that work today, which for that user is worse than
the hang. An always-on subprocess costs a spawn per pattern, and `stress.py`
case 11 puts 200 files through this rule.

Process isolation is what remains, so it is opt-in and nobody pays for it
unless they have hit the problem. Left unset, the hang is still possible. That
is a mitigation available on request rather than a cure, and saying so is the
point of recording it here.

**A consistency check naming the same file twice is now caught.** It was not,
and the history is worth keeping. The check rejects a single-file block and
normalises paths, so `docs/x.md` and `docs/./x.md` are caught at config load as
one file under two spellings. That is a STRING comparison and it never touches
the filesystem, so a symlink, a hardlink, or a case variant on a
case-insensitive filesystem reached the same file by a genuinely different
route and the block agreed with itself forever while appearing to compare two
things.

The rule now asks the filesystem instead, comparing `(st_dev, st_ino)` and
counting distinct identities rather than distinct path strings.

The fallback in that identity function matters as much as the mechanism. FAT32
and some network shares report `st_ino` as 0, and keyed naively on it every
file on such a volume compares equal - which would report self-comparison on
every configuration, a false positive on every run and worse than the hole it
closes. A zero inode therefore falls back to the resolved, case-normalised
path, and a test asserts the function distinguishes two known-different files
before anything is built on it.

**Fenced code is exempt from claim rules.** An example in a fence is not a
promise, so claims there are ignored. Inline backticks are treated differently
again: kept for claim rules, because claims are written inside them, and
blanked for link rules, because an example link is written inside them too.

This used to have a counterweight. `possible-secret` read everything including
fences, on the reasoning that a credential in a fence is still committed. That
rule was removed in 0.14.0 - see `design/rules.md` - so the exemption is
now uniform.

**One rule reads inside fences, and the exception is instructive.** The
exemption above cost this project two broken instructions before it was
qualified. A README pinned `rev: v0.5.0` for a fortnight while the repository
had no tags at all, and a Claude Code install line named a plugin id that never
existed. Both sat in fenced blocks. `dead-release-tag` is the rule for the
first and could not see it, by design.

The distinction the exemption was missing: a fence usually holds an EXAMPLE,
which is not a promise, but an install snippet is the one block on a page a
reader copies verbatim. It is closer to a promise than ordinary prose is.

`dead-pinned-ref` therefore reads inside code and asks only the narrowest
answerable question: does the version pinned for THIS repository resolve? The
governing `repo:` line is what keeps it honest, because a project documenting a
third-party hook pins a tag living in somebody else's repository, and checking
that would report a finding on a correct line. Measured before it was written:
three pins in this corpus, all resolving, no false positives.

## Anti-gaming

**The subagent gets at most 2 validation attempts and must report its FIRST-run
findings even if a later attempt cleared them.** Without this, the cheapest way
to pass a validator is to delete the offending claim. With it, claim-deletion is
visible in both the report and the diff.

**A red test suite must not block the status commit.** An entry that can only
describe green states withholds the truth exactly when it matters most.

**The archive must be validated.** Otherwise `--archive` shrinks the validation
surface and the tool passes its own gate by relocating content - the same defect
as a subagent deleting a claim, committed by the tool itself.

## Archive ordering

Archive **after** drafting the new entry, not before. Archiving first means the
new entry does not count toward the retention cap, so the document holds one more
entry than allowed and the archive runs permanently one cycle behind.

That fix immediately exposed the next one: the newly-archived entry then tripped
the live-claim rule, because "newest entry" in the archive is simply the most
recently retired one. Hence the archive's exemption from live-claim checking, and
only that rule.

## Conservation

The archive split is the only irreversible file operation. It asserts line
conservation with **multiset** arithmetic, not set membership - a set check
cannot detect the loss of a duplicated line, because one surviving copy satisfies
it.

The baseline for that check is the raw file bytes, **not** a reassembly of the
splitter's own output. Deriving it from the splitter makes the check circular: a
bug in the splitter corrupts both sides equally and they always agree.

## Authoring constraints these rules impose

- **Paraphrase past statuses in the newest entry; never quote or strike them
  through.** The rules cannot distinguish a quotation from a claim. Measured
  on 2026-09-22 across the agent and autopsy corpus tiers: of 172 distinct
  dead commit ids in ordinary documents, 6 had ever existed in the
  repository's own history and 166 were quoted from a transcript, a grader's
  output or another project - true elsewhere, never here, and read here as
  claims.
- Write a SHA range with git's own dots, `` `a..b` `` or `` `a...b` ``, or as
  two tokens `` `a` `` -> `` `b` ``. Both ends of a dotted range are checked
  and repaired since 2026-09-12; an arrow inside one backtick pair,
  `` `a -> b` ``, is still not recognised, because that is also how a rewrite
  map is quoted, with the left side dead by design.
- Give each entry the exact configured header. A wrong header silently disables
  archiving and live-claim validation for that entry.
