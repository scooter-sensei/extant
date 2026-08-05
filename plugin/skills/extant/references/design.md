# Design rationale

Why each rule is scoped as it is. Every decision below was forced by a real
failure - reasoning from first principles produced the wrong answer at least
three times, so the incidents are recorded alongside the rules.

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

Rules live in a registry in `extant_collect.py`. Each declares what it emits,
its scope, whether it survives archiving, and - required - the exact yes/no
question it asks of git or the filesystem:

```python
Rule(
    kind="false-merge-claim",
    check=validate_merge_claims,
    scope="whole-file",
    in_archive=True,
    falsifiable="is the claimed commit an ancestor of the ref the claim names?",
)
```

**The admission test:** a rule belongs only if it can be answered yes/no by git
or the filesystem, AND produces zero false positives on the real corpus, AND
names the place the answer lives. A test enforces the first clause - every rule
must state its question - so a rule that inspects numbers or dates cannot be
added quietly. The second is on you: measure before you write the pattern. The
third is free, and predicts the second.

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
scheduled. Static rejection of dangerous constructs is a heuristic whose false
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
rule was removed in 0.14.0 - see below - so the exemption is now uniform.

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

## `raw-lfs-blob`: Git LFS, and the direction that had to be refused

`.gitattributes` is a document making a falsifiable claim: files matching these
patterns are stored as LFS pointers. That claim can be false, and when it is,
nothing says so. Git accepts the commit, the engine loads the asset, and the
repository carries a real binary in its history forever.

Two directions look identical and only one is usable.

**A path under an LFS filter stored as a raw blob** is answerable from git
alone: `check-attr` says what the filter governs, and the pointer header says
how it is stored. No network, and the LFS binary is never invoked.

**A pointer whose object is missing locally** cannot be a rule. Measured: a
fresh CI checkout without `git lfs pull` holds ZERO objects, so that check
would report every asset in the project as missing on every run. It is the
false-positive class this project treats as worse than having no validator.

Both of this rule's bugs were invisible in its output, which is why it has more
mutations than any other. Paths were piped to `check-attr` with `text=True`, so
Windows appended a carriage return to each, git read it as a literal path
character, and answered `unspecified` for all but the LAST path. The survey
reported 1 of 4 governed files, and the one that survived happened to be the
one with the finding - so the rule looked perfect. Had the bad file sorted
first it would have printed a clean result over an examined count of zero.

It also read `git ls-files`, the index, which is empty on a repository whose
checkout has not completed. On a real Unity project that meant zero examined
while `.gitattributes` sat there declaring 47 LFS patterns. It reads HEAD's
tree now, which is also the right semantics: this runs after a commit, so the
committed state is what is being judged.

And one subprocess per file cost 40 seconds on a 7802-file project. That is not
a slow hook, it is an uninstalled one. Sizes come from one `cat-file
--batch-check`, contents from one `cat-file --batch`, and only for blobs small
enough to BE a pointer: 262 ms.

## The game-engine presets, and the widening that was measured and refused

The plan was to widen `path_pointer` with asset and source extensions. Measured
against a real Unity project and a real shipped Godot game, that rule examines
ZERO references in either. Game documentation writes paths as markdown links -
`[ART_NOTES.md](Documentation/ART_NOTES.md)` - and `path_pointer` requires a
BACKTICKED path introduced by an operative marker. Widening it would have been
a no-op that looked like a feature. Neither preset touches it.

`dead-md-link` is what carries these projects and needed no change: 257 links
examined across the two, one reported, and that one is a genuine bug - a README
linking to `/doc` with a leading slash, which GitHub resolves to the site root,
while every other link in the same file uses the relative form.

The version checks are keyed on different documents per engine, because that is
where each project actually states it. Unity puts its editor version in a
shields.io badge carrying the exact `6000.0.52f1`, matching
`ProjectVersion.txt`; its prose two paragraphs later says only "6000.0 LTS", so
a check keyed there needs major.minor on both sides and would miss a drift from
`.52f1` to `.61f1`. Thrive's README states no Godot version at all, so that
check reads `doc/setup_instructions.md` instead - keyed on the README it would
have examined nothing forever while exiting 0.

There is no `unreal` preset, deliberately: no corpus was measured for it, and
`EngineAssociation` in a `.uproject` holds a GUID rather than a version for any
studio on a custom engine build, so the obvious check would false-positive on
exactly the teams most likely to want this.

## Integration branches, and why one trunk was not enough

Three rules used to ask "is X an ancestor of trunk", and they meant three
different things by it. On a repository with two integration branches each
answer was wrong, in a different direction, at the same time.

Measured on a gitflow fixture - main and develop, a release branch merged to
both and tagged, a feature merged to develop after that release:

- with `trunk = main`, a FALSE claim about develop was not judged wrong, it was
  never examined. The pattern interpolated the trunk name, so the line did not
  match at all. Two false claims in one document, one about each branch, and
  either setting caught exactly one.
- with `trunk = develop`, a genuinely shipped `v1.0.0` was reported dead. The
  tag sits on main's release merge; develop received the release BRANCH back,
  not that commit.

**A merge claim names its own ref, so that is what is checked.** "Merged to
`X` at `Y`" is self-describing, and asking git whether Y is on X needs no
configuration at all. This is strictly MORE precise than comparing against one
trunk, which is what makes it the right answer rather than a loosening: a
trunk *list* would have made the rule ask "an ancestor of any of these", which
trends toward `dead-sha` wearing another rule's name.

The two rules that cannot name a ref use a measured set: the configured trunk
plus whichever of `main`, `master`, `develop`, `development`, `trunk` exist.

**Not a shape rule.** The first version asked only whether a branch name had a
slash in it, reasoning that topic branches are prefixed and long-lived ones are
bare. That is true of the prefixes and useless in reverse: an existing test
cuts a tag on a branch called `abandoned`, and the shape rule promoted it to an
integration branch and reported the release as shipped. Every `gh-pages`,
`experiment` or `old-master` is the same trap. The narrower list degrades
safely, because the rule this all exists for does not consult it.

**A missing branch is not a false claim.** Gitflow deletes every release and
feature branch on merge, and a squash merge or a custom `-m` erases the name
from history, so neither `rev-parse` nor the merge-message rescue can tell
"deleted" from "invented". Reporting those produced a false positive on the
fixture. The rule asks the substantive question instead: a missing branch plus
an integrated commit is a stale name on a claim that is true, and silence is
right; a missing branch plus a commit on no integration branch is a claim that
work landed when it did not. This also keeps the rule from being defeated by a
typo, since evading it requires the commit to be genuinely integrated - at
which point there is no false claim left to hide.

**Backticks decide whether an unresolvable name is reported.** The pattern no
longer anchors on a known branch name, so it can match a word of prose sitting
where a branch would go. `` merged to `develp` at `abc` `` is a claim about a
specific branch; "merged to production at `abc`" is not necessarily one.
Requiring backticks outright would lose every project that writes the name
bare, so both match and only the backticked form is accused.

**The installer writes its own `merge_claim`, and that is the line that
matters.** The generated pattern overrides the default, so a collector that
supports named refs still ships single-trunk behaviour if the installer
regresses. That is exactly what happened during this change: every unit test
passed, because they exercise the default, and the gitflow scenario caught it
because it runs the real installer.

## The baseline, and the two things it deliberately does not do

A baseline is an amnesty: a list of findings a project has agreed to leave
broken so that NEW ones stay visible. Every design question about it is
whether that amnesty can quietly grow to cover everything, so the constraints
matter more than the suppression does.

It is never written implicitly, the suppressed count is printed on every run,
`--baseline-check` reports entries whose finding no longer occurs, and a
corrupt or missing baseline is an error rather than an empty one. That last
point is the important one: treating a missing file as "suppress nothing"
would let a typo'd path turn a ratcheted run back into an ordinary one without
saying so.

One consequence is accepted rather than fixed, and the smoke harness flags it
on every run so it stays visible rather than becoming folklore.

**One recorded finding forgives every future copy of itself.** The fingerprint
is `(path, kind, detail)` and deliberately excludes the line number, so the
same claim pasted somewhere new in the same file is already forgiven. The
alternative is worse: line-number fingerprints un-suppress the entire baseline
on any reflow, which makes the file useless within a week and teaches people
to regenerate it wholesale, which defeats the point of having one.

## `possible-secret`, removed in 0.14.0

It scanned for four credential shapes: an OpenAI key, a GitHub PAT, an AWS
access key id, and a JWT. It is gone, and the reasoning is worth keeping
because the same argument will be made again for the next rule that looks
useful and answers a different question.

**It found nothing.** Zero findings across 38 repositories and 7,708 markdown
files. The only time it was ever observed firing was on a design document that
contained an `sk-` example, which was a false positive.

**It asked a different question from every other rule.** The rest ask "is this
statement still true", which git or the filesystem settles. This one asked
"does this file contain something dangerous", which is a different job with
different tooling. The core guarantee is stated as falsifiability, and this
rule met that letter while missing the point of it.

**And it was not competitive.** gitleaks ships roughly 150 rules and trufflehog
several hundred with live verification. Four regexes beside them do not add
safety; they add the appearance of it, which is worse, because a project that
believes its documentation is scanned for credentials will not reach for a tool
that actually does it.

Use gitleaks. It is a pre-commit hook away and it is not this project's job.

The cost of removal, stated plainly: `--selftest` could exercise four rules on
this repository and can now exercise three, because the secret probe was
synthetic and therefore always available while the others depend on the
document offering something to corrupt. That is a real loss of signal about
whether the probe machinery works, accepted because a rule kept for the
convenience of its own test is a rule kept for the wrong reason.

## Generated sites, and the two anchor namespaces

A repository that compiles its markdown into a website has links the filesystem
cannot settle. `/reference/config/` is a route, `guide.html` is a built page,
and an extensionless target is whatever the generator decides. None of those is
a file, so none is judged when a generator is declared.

Detection is by configuration file, in the repository root or under `docs`,
`site`, `www` or `website`. The subdirectory search is not speculative:
jekyll/jekyll keeps its own site under `docs/` with `docs/_config.yml`, and a
root-only search reported 138 of its routes as dead. One generator is declared
INSIDE another file rather than in one of its own - Elixir names ExDoc as a
dependency in `mix.exs` - so existence alone is not enough there and the
content decides.

Both directions cost something, which is why both are pinned by tests. Blind,
withastro/starlight reported 235 of its own working links as dead. Universally
on, every genuinely dead link in a plain repository stops being reported.

**The cross-reference namespace is a property of the generator, not a global
choice.** MyST, Sphinx and Antora resolve `#label` against every document at
once, so a target defined in `site-options.md` is reachable as `#site-options`
from anywhere; executablebooks/mystmd relies on that throughout, and 168 of its
findings named a label that existed in another file. MkDocs is per-page.

The temptation is to apply the project-wide union everywhere and be done with
it, and the measurement refused it: on encode/httpx, which is MkDocs, a blanket
union forgave two of its three genuinely dead anchors. Real signal traded for
quiet. So the generator decides, and a repository declaring none keeps the
page as its namespace.

Hugo gets one narrower rule. Its `_`-prefixed content directories are not
routable pages but fragments composed into other pages by a shortcode, so a
term defined in `_common/configuration/locale.md` is an anchor on whatever page
includes it. That is NOT generalised to every `_` directory, and the
measurement is again why: seven of 38 corpus repositories keep markdown under
one and they mean different things. Jekyll's `_posts` are whole pages,
Docusaurus's `__tests__` is fixtures. Treating those as ambient would forgive
real findings in four repositories to fix one.

## What a held-out corpus said about detection

Ten repositories the original narrowing never saw - Rails, Laravel, Ktor, Zig,
Docsify, Nextra, Slate, dplyr, Terraform, Symfony - produced 951 findings
across 1,100 files. Two results reordered the work.

**The rules that fire on other people's repositories are the link and anchor
rules, and nothing else.** Of those 951 findings, 943 were `dead-md-link` or
`dead-md-anchor`. `unknown-branch`, `false-merge-claim`, `dead-path-pointer`
and `dead-pinned-ref` fired ZERO times between them. Those rules exist for
plan, spec and status documents, which no public repository corpus contains,
so widening them could only add noise here. The eight coverage candidates
planned for this phase were aimed almost entirely at rules this corpus cannot
exercise.

**And 526 of the 558 link findings were noise the tool already knew how to
suppress**, in projects whose generator it did not recognise. Three changes
followed, each keyed on a measurement.

**A `.html` target is never judged, in any repository.** Measured across 20
repositories in two corpora: 407 markdown links point at a `.html` target and
NOT ONE resolves to a checked-in file. A link to `.html` is a link to a
rendered page. This used to be gated on generator detection, which is why
rails reported 276 of its own guide links dead - its guides compile
`guides/source/*.md` to HTML with a bespoke builder shipping none of the
configs detected here. The gate was protecting nothing, so it is gone.

The other two shapes keep the gate. In a plain repository an extensionless
target can be a real file - `LICENSE`, `Makefile` - so silencing those
everywhere would stop the rule working at all.

**Next.js counts as a generator**, because it routes by file path and a
markdown link inside one is a route. Nextra builds on it and reported 227 of
its own links dead.

**Docsify declares itself inside `index.html`**, having no config of its own,
and keeps it under `docs/`. So the marker search walks the same subdirectories
as the config search rather than looking only at the root - the root-only
version was the shipped bug for jekyll, whose `_config.yml` sits there too.

Held-out findings fell from 951 to 424, and the original corpus was unchanged
in every repository - the point of measuring both.

Its total was recorded at the time as 2,154, and that figure was an artifact.
Those clones were made with `--depth 1`, which leaves every historical SHA
unresolvable, so the SHA rules fired on nearly everything: vite alone supplied
2,094 of them and reports 3 when cloned with its history. The "unchanged"
conclusion holds, because both sides read the same clones. The number did not.

## The coverage phase: eight widenings, none shipped

The eight candidates above were then measured properly, one at a time, against
three corpora - the original ten re-cloned with history, ten more held out for
toolchain novelty, and ten chosen for density of git-checkable claims. Thirty
repositories, 3,821 markdown files, 960 baseline findings.

All eight were rejected. The reason generalises past this tool.

**A rule keyed on a PHRASE has a denominator of zero outside the project whose
phrasing it came from. A rule keyed on a TOKEN SHAPE does not.** `dead-sha`
looks for hex, `dead-md-link` for link syntax, `dead-path-pointer` for a path;
all three fire everywhere. `false-merge-claim` looks for "merged to X at
`sha`", and across 3,821 files it matches nothing at all. Neither does "merged
in `<sha>`", "landed in `<sha>`" or "fixed in `<sha>`". What projects actually
write is "commit `<sha>`" - 890 times - which the shape-keyed rule already
catches without needing the verb.

That was read as "the claim rules cannot be gated by any public corpus", and
**it was wrong.** The method held; the SAMPLING FRAME did not. "Claim density"
had been chosen by picking popular Python and JavaScript tools, which are dense
in changelogs rather than in status claims, so the population these rules
actually serve was never in the sample.

Scanning 229 repositories from the agent-tooling topics - 52,417 documentation
files - finds the shipped merge pattern 35 times, the release pattern 97 times,
the branch token 640 times and the live phrase 117 times. **61 repositories
exercise at least one.** A corpus of fifteen of them gives `false-merge-claim`
a denominator, `dead-release-tag` 74 examinations against 2, and produced this
rule's first true positive on somebody else's repository: neomjs/neo records
work merged to `dev` at a commit that is not an ancestor of `dev`.

The lesson survives the correction, in a sharper form. A phrase-keyed rule is
invisible to any corpus that does not contain the KIND of document it was
written for, and "I sampled 3,821 files and found nothing" is a statement about
the sample. Widening it to a shape-keyed rule is still the robust move; giving
up on measuring it was not.

Where a measurement was possible it was decisive, not marginal. Judging a path
mentioned without an operative marker takes the tool from 960 findings to
3,964. Dropping the letter requirement from the SHA shape admits 7 findings of
which 7 are numbers: a date, two durations in seconds, a timestamp version.
Resolving anchors through site routes changed nothing across 3,821 files - and
a fixture proves that is a real zero rather than a patch that failed to apply,
which is the only way a zero is worth reporting.

**Two rules were wrong on every firing they had.** `dead-release-tag` and
`dead-pinned-ref` produced four findings across the whole 30-repository corpus
and all four were false positives - which is what justifies acting on a sample
that small, because a 100% error rate is not the same situation as a few
mistakes among hundreds of correct results.

That prefix fix also nearly shipped the failure it was written to remove. A
project can configure `release_tag` to capture its whole tag name, and the
installer derives such a pattern for repositories tagging `release-1.2.3`;
trying this repository's prefixes first makes that `release-release-1.2.3` and
reports a shipped release as dead. Eleven unit tests covered the change and
none could see it, every one having used a bare or `v`-prefixed version -
which is the shape the corpus was about. `scenarios.py` caught it. A fix
derived from a corpus inherits that corpus's blind spots, and no repository in
any of the three configures this rule at all.

Every cause was a project habit rather than an author's error. Half the
ecosystem tags `v1.2.3` and half tags `1.2.3`, so the prefix is read from
`git tag -l` now instead of assumed. A claim names a SERIES more often than a
tag - symfony's own triage guide names the 8.0 series while the tags are
`v8.0.0`, `v8.0.1` - so a version that is the stem of a real tag has shipped.
symfony also has no `main` and no `master`, its branches being version numbers,
and the integration-ref list returned the configured trunk whether or not it
resolved: every rule asking "did this reach an integration branch" compared
against a ref that is not there, got "no", and reported every release as
shipped on nothing. 3 of 30 repositories have no conventionally named trunk.
And `rev: ''` is pre-commit's own placeholder rather than a broken pin.

**Two detection fixes came out of it**, both from reading the 38 findings that
blanket route-suppression would have silenced. All 38 were false positives.
A site can be a subdirectory of a subdirectory - aider's Jekyll lives at
`aider/website/_config.yml` - so the config search goes one level deeper,
bounded there. And Mintlify's `mint.json` is a signature; its newer `docs.json`
spelling is not, being too generic a filename to trust.

All of it together: **960 findings to 920, 40 removed, 0 added**, every removal
individually confirmed as a false positive.

Three are left in deliberately, because a known false positive is cheaper than
a guessed rule. A bare-domain link (`[x](kubernetes.io/docs/...)`) is 1
finding, and every rule that would catch it also catches `README.md`. A
relative target climbing out of the repository is 3 findings in one file of one
repository - implemented, then reverted when a scan found no second instance
anywhere, because deriving a rule from a sample of one project is the error
this phase exists to document. And rust-lang/rfcs, which has no tags and
discusses Rust's releases throughout, reads a mention of the 1.75 toolchain as
a claim about itself; skipping untagged repositories fixes that and silences a
never-tagged project making a false claim about its own release, which is the
worse trade.

That last paragraph is worth reading twice, because the first draft of it
tripped the rule it describes. Quoting the offending sentence in order to
explain it REPRODUCED it, here, and `--verify` failed the build. Then the
paragraph written to record THAT did it a second time, for the same reason.

The rule cannot tell a quotation from a claim. `CLAUDE.md` already records the
property for live claims, where the standing instruction is to paraphrase a
past status rather than quote it; it holds for release claims identically, and
the tool proved it twice on the document announcing the fix. Paraphrase, or
the sentence you write about a false positive becomes one.

The 424 that remain are mostly real. Rails links to `#helpers` from a document
with no such heading; dplyr's revdepcheck output links to `failures.md#amt`
where the heading is `# amt (0.3.0.0)`, whose slug is `amt-0300`. Both were
checked by hand rather than assumed to be noise because they were numerous.

## reStructuredText, skipped rather than tuned

`.rst` is read for claims and never for markdown syntax. The Sphinx ecosystem
is not a small corner - numpy carries 555 `.rst` against 14 `.md`, Sphinx 472
against 3, pytest 298 against 6 - so a markdown-only sweep is blind to most of
what those projects have written down.

Adding the extension alone was not enough, and the corpus said so: sweeping
those repositories produced 84 findings and almost none were real.

`dead-md-link` and `dead-md-anchor` are therefore skipped outside markdown
rather than adapted to rst. That is deliberate. `[text](url)` is markdown's
syntax; in Python it is a subscript followed by a call, and numpy writes
`np.dtype[mp.mpf](dps=100)` in a doctest. Every one of its 23 link findings was
that shape - false by construction, not by accident. There is no version of a
markdown link regex that is correct on a language which has no markdown links,
so the rule does not run rather than running badly.

The claim rules DO run, because a dead SHA in rst prose is as dead as one in
markdown. What changes is what counts as prose: rst literal blocks open with a
line ending in `::` and run until the indentation returns, `>>>` opens a
doctest, and ``` ``inline literals`` ``` are code. Left in place, numpy's
`float64('1e10000')` was read as a commit.

## Cache scope: one call, and the one place it widens

Every answer git or the filesystem gives is held for the duration of ONE
`validate()` call and no longer. Directory listings, ancestry indexes, resolved
refs, LFS state, another document's headings, the origin URL. A caller that
creates a file or adds a remote between two checks must see the new answer, and
a cache with no owner would quietly hand back the old one.

That default is not free. `--sweep` calls `validate()` once per document, so
every one of those answers was being rebuilt per file: measured over 400
documents, one origin lookup per document was 70 percent of the entire run, and
directory listings turned 20 distinct questions into 128,000 Path objects.

So `--sweep` declares the repository static for its duration and takes
ownership of those caches. It can, because it reads every document from one
checkout and writes nothing. The declaration is released in a `finally`, so a
library caller that sweeps and then validates something else gets the per-call
behaviour back even if a rule raised part-way through.

The narrowness is the safety argument. `--verify` was measured for the same
treatment and refused it: 5 ms saved out of 337, on the path that gates
commits, in exchange for relaxing a correctness promise. Not worth it.

The direction of the mistake is worth recording, because it was made. The
origin lookup was first memoised for the whole process on the reasoning that a
remote cannot change while one runs - true of the CLI, false of a library
caller and of the tests. A repository whose origin was added between two
validations kept answering "no origin", so `dead-pinned-ref` examined nothing
and reported clean. A cache that outlives its scope does not produce a wrong
answer anybody sees; it produces silence, which is this project's own failure
mode aimed at itself.

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

## The baseline forgives what it recorded, and no more

The fingerprint excludes the line number so that reflowing a paragraph does not
un-suppress everything. The price was that one recorded finding forgave the
same claim pasted anywhere, forever - listed in `smoke.py` as a by-design
consequence for several releases.

Entries now carry an occurrence count. Suppression covers that many; the
surplus is reported. The line number stays out of the fingerprint, so
churn-immunity is unchanged, and an entry written before counts existed
forgives one - the shape it had when it was written.

Raising the count by re-recording remains possible. That is acceptable: it is
an explicit act and it shows up in the diff, which is what a baseline is for.

## Examined and declined

Recorded so a later reader does not mistake either for an oversight.

**Entry-scope burial.** `stale-live-claim` reads the newest entry only, so
moving a live claim into an older entry silences it. Not closed: older entries
are historical record, and re-judging them would fire on every past status in
every project that keeps one. That is a guaranteed false-positive class traded
for a narrow evasion. The authoring constraint below - paraphrase past
statuses, never quote them - is the mitigation.

**The `raw-lfs-blob` size shortcut.** Reading every governed blob rather than
only the small ones changes cost and never a verdict, so it is not a loophole.
It is also why that shortcut has no mutation in `mutate.py`: a mutation nothing
can kill survives every campaign and reads as a gap the tests do not have.

## A correct rule can be low-yield, and that is the world rather than the keying

`dead-line-pointer` draws a denominator from very few repositories, and the
first instinct is that its keying is too narrow. Measured across **73
repositories** - 39 libraries, 21 deployable applications, 17 agent-tooling
projects with roughly 21,000 markdown files - **`obra/superpowers` is the only
project that cites line numbers of its own tracked files at any rate.**
`crewAI` alone holds 20,375 documents and does not cite one.

The obvious explanation was a sampling problem: this rule targets agent-written
plan documents, so a corpus of them should exercise it. That corpus was built,
verified to contain the population before any rule ran, and produced **no new
findings**. The hypothesis was wrong and the thin denominator is the base rate.

Where the convention does exist the rule earns its place: **3 of superpowers'
17 resolvable citations are stale, an 18% fault rate.** So the shape to expect
from a rule like this is narrow reach and a high hit rate inside that reach,
and widening it would trade the property it reliably has - zero false positives
across all 73 - for coverage the measurement says is not there.

Before concluding a rule is too narrow, count how often anyone writes the form
it reads. That is cheaper than any widening and it is what the denominator line
exists to make visible.

## Authoring constraints these rules impose

- **Paraphrase past statuses in the newest entry; never quote or strike them
  through.** The rules cannot distinguish a quotation from a claim.
- Write SHA ranges as `` `a` `` -> `` `b` ``, not `` `a -> b` ``. A range inside one
  backtick pair is not recognised as a reference and escapes both checking and
  repair.
- Give each entry the exact configured header. A wrong header silently disables
  archiving and live-claim validation for that entry.
