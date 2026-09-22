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
)
```

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
`site`, `www`, `website`, `docs-website`, `documentation` or `fern`, and one
level either side of those: `*/docs` reaches a site inside a package, and
`docs/*` reaches one inside a documentation directory. Neither is speculative.
jekyll/jekyll keeps its own site under `docs/` with `docs/_config.yml` and a
root-only search reported 138 of its routes as dead; haystack declares
Docusaurus in `docs-website/`, and llama_index declares MkDocs at
`docs/api_reference/mkdocs.yml` while serving pages from
`docs/src/content/docs/` - 1,227 findings, because the search reached `*/docs`
and never `docs/*`. One generator is declared INSIDE another file rather than
in one of its own - Elixir names ExDoc as a dependency in `mix.exs` - so
existence alone is not enough there and the content decides.

**A tree that numbers its documents declares a site by that alone.** Nothing
reads an ordering prefix except something building an ordered site, and the
pages then link to each other by the stripped name. This is the signal for a
project whose site is built from ANOTHER repository, where no config exists
here to find: svelte keeps
`documentation/docs/07-misc/04-custom-elements.md`, links to it as
`custom-elements`, and svelte.dev builds it. Bounded to the same directories
as the config search and to three in one directory, both for the same reason:
unbounded, three numbered fixtures under
`packages/astro/test/fixtures/content/` declared all of `packages/` a
documentation site.

**Detection records WHICH top-level directories a generator governs, not a
yes or no for the repository.** A monorepo builds a site from `docs/` and
still keeps ordinary READMEs in `packages/`, whose relative links really are
files. Answering repository-wide silenced six real defects, among them
`packages/astro/src/core/render/README.md` linking to `../endpoint/`, a
directory that does not exist.

The two shapes are then gated differently, because they fail differently. **A
leading slash is never a path in this repository** wherever the document sits -
GitHub resolves it against github.com and a generator against the site root -
so it needs only that the repository builds a site at all. **An extensionless
target can be a real file** (`LICENSE`, a directory), so that one asks whether
THIS document is a page.

Both directions cost something, which is why both are pinned by tests. Blind,
withastro/starlight reported 235 of its own working links as dead. Universally
on, every genuinely dead link in a plain repository stops being reported. A
blanket skip for root-absolute links was tried once, on the strength of 6,360
findings across 40 repositories of which none was real, and two tests refuse it
in as many words. They are right: the shape was never the problem, detection
was.

**A bare filename resolves within one translation tree.** Where a generator
flattens its namespace, a sibling is reachable by bare name from any depth,
which is why a unique basename is accepted at all. It is counted per language
tree rather than per repository: fastapi builds a separate site per language
and keeps `newsletter.md` only in English, so a repository-wide count made
every translated page's broken link to it resolve against the English file and
hid 68 real defects. A tree is recognised by three or more language-shaped
siblings, so a lone `docs/id/` remains an "id" directory.

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

## Strata: a property of the document, not a setting to configure

A first sweep over 50 pinned public repositories prints **54,790 findings, of
which 4,431 are in ordinary documents**. The other 92 per cent come from four
kinds of tree - per-release snapshots (39,698), changelogs and machine-written
allowlists (4,765), vendored code (4,175) and generated references (1,721).
`bazelbuild/bazel` keeps twelve per-release copies of one documentation tree,
so one dead link written once is reported twelve times; `angular`'s
`zone.js/CHANGELOG.md` supplies 391 on its own, and `babel`'s two allowlists
343 between them, whose entries are test-case paths in an EXTERNAL suite and
were never document links at all.

**`exclude_paths` already existed and did not close it.** Three configuration
passes over the same corpus moved the headline by under one per cent - 3,468,
3,470, 3,438 - and `install.py` refuses 35 of the 50 repositories unaided, so
the configuration that would fix it is never written and the adopter never sees
the prompt. The conclusion is not that adopters are lazy: whether a tree is
vendored or a per-release snapshot is visible FROM THE REPOSITORY, so it should
not have to be configured at all.

**Labels, not exclusions**, and the distinction is the same one the denominator
is built on. Excluding hides; a stratum labels. A rule that goes quiet because
a tree was excluded is indistinguishable from a rule that broke. Both
mechanisms stay and answer different questions.

**The field is on `Located`, not on `Finding`.** The baseline fingerprint
hashes `(path, kind, detail)` off `Finding`, and a baseline that stops matching
does not fail loudly - it quietly re-raises findings a project agreed to leave
alone, and a reader learns to stop reading the output. A stratum is a property
of the PATH, and `Located` is already the type that pairs a finding with its
path, so it belongs there on the merits too. It also keeps the rules leaves: if
each rule stamped its own, `strata.py` would become a sixth shared module every
rule imports for a fact none of them uses.

**The strata are a PARTITION, so precedence is load-bearing.** A path can be
generated AND version-snapshotted - bazel's `docs/versions/8.6.0/reference/` is
both - and a fixed first-match order is the only thing that stops it being
counted twice. Vendored wins over everything, because a vendored tree is
somebody else's repository whatever shape it has inside.

**Path only, and the alternative is priced rather than guessed at.** Reading
each document for a do-not-edit marker would move 503 further findings from
`ordinary` to `generated` - 11 per cent of that stratum, across 71 documents.
It is not done because the text is not in scope where `Located` is built: the
sweep receives findings back from a worker process, not document text. The
number is recorded because a deferral without one is indistinguishable from an
oversight.

Two failures found after the first version shipped, both worth keeping:

- **The pattern must read every suffix the sweep reads.** It was anchored on
  `.md|.mdx` while `refs.py` gathers `md`, `markdown`, `mdx` and `rst`, so
  reStructuredText changelogs fell through to `ordinary`. That is the dangerous
  direction: a missed vendored tree only fails to shrink the headline, while a
  missed changelog puts a historical record INTO the number a reader acts on.
- **A changelog-shaped DIRECTORY does not make its contents historical.**
  cpython's `Misc/NEWS.d/*.rst` are per-release news fragments and stay
  `ordinary`. Widening to directory names would have been tuned on the corpus
  being measured, which the admission bar refuses, and a directory called
  `news/` is very often a project's live blog - labelling that would be a
  suppression firing wrongly, which deletes signal silently rather than
  appearing in the output for somebody to argue with.

**De-duplication is not here, and the reason is not squeamishness.** Collapsing
bazel's twelve copies needs findings grouped ACROSS documents, which would
change what a finding IS and move exit codes with it. Measured at analysis time
instead: the stripped-path key takes 4,429 ordinary findings to 3,466 and a
content hash takes it to 3,451, so content identity is worth 15 findings on top
of the path pattern rather than the further 1.3x it was expected to be. Content
keying ALONE is worse over all findings - 13,093 distinct against 11,860 -
because a per-release snapshot carries the version string and so is
near-identical rather than byte-identical. Content identity measures
DUPLICATION and the path pattern measures PER-RELEASE SNAPSHOTTING; they are
different questions, and neither subsumes the other.

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

Three later additions follow the same rule rather than widening it: the tracked
file list, the site directory list, and reference resolution. Each answers a
question about the CHECKOUT rather than about any document - which files git
tracks, which directories a site is built from, whether a path resolves and in
what spelling - so a survey asks it once instead of once per file. All three
are read only while the static declaration is held, which is what makes them
answers with an owner rather than a memo that outlives its truth.

One of them was proposed with the git call wrapped, returning an empty list
when `ls-tree` fails. That was refused. A repository where git fails would then
report zero tracked documents and sweep clean, which is the silence this whole
section is about, produced by the defensiveness meant to prevent a crash.

The direction of the mistake is worth recording, because it was made. The
origin lookup was first memoised for the whole process on the reasoning that a
remote cannot change while one runs - true of the CLI, false of a library
caller and of the tests. A repository whose origin was added between two
validations kept answering "no origin", so `dead-pinned-ref` examined nothing
and reported clean. A cache that outlives its scope does not produce a wrong
answer anybody sees; it produces silence, which is this project's own failure
mode aimed at itself.

## The survey runs in one process or eight, and says which

Above 100 documents `--sweep` spreads the per-document work across up to eight
worker processes. Each worker takes a batch and holds a run scope of its own,
so the static-checkout caches above are built once per process rather than once
per document. Measured on a 200-document corpus across twelve cores, best of
three: 7327 ms in one process, 2919 ms across eight.

**The floor is a measurement, not a guess.** The curve leaves zero long before
it is worth anything: 40 documents buys 4 percent, 60 buys 15, and only at 100
does it reach 1.75x. A process pool brings failure modes a loop does not have -
sandboxes that forbid spawning, state that will not pickle, workers the OS
kills - and 4 percent does not pay for any of them.

**One implementation, two dispatchers.** Reading a document, validating it and
counting its denominator live in a single function that both paths call. The
alternative - a parallel loop beside a serial one - was written first and
rejected: two copies of the work drift, and only one of them is ever exercised
on a given machine, so the drift is found by a user rather than by a test.

**Which path ran is printed.** This is not diagnostic noise. The two paths are
required to produce identical output, and a reader who cannot say which one
produced theirs has no way to report a difference between them. The same
reasoning makes the fallback loud: if the pool cannot start, the survey
finishes in one process and names the reason, because a run that quietly
stopped using the machinery it reports using would go on printing the summary
of a healthy one. Silent degradation is the failure this project exists to
refuse, and it is no more acceptable in the harness than in a rule.

**A document that comes back with no result is named, and gates.** The merge
looks each document up by path, and a missing entry is the one shape that lets
a sweep examine nothing and say nothing. It is counted and named beside the
unreadable ones, for the reason a file that could not be READ is counted:
neither is a file with no findings.

It differs from an unreadable file in one way that matters, and the exit code
follows the difference. A file that cannot be decoded is a fact about the
REPOSITORY - reported, survived, exit code untouched. A document dispatched to
the survey that came back with nothing is a fact about this TOOL, so it exits
non-zero. Reporting a defect in the surveyor while returning the code for a
clean run is the same conflation one level up.

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

Recorded so a later reader does not mistake any of these for an oversight.

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

**Symbol-aware line pointers.** `dead-line-pointer` asks whether a cited file
has that many lines, never whether the line still holds the symbol named beside
it. The wider question has been measured and rejected twice, and the full
figures sit in the comment above the pattern in `line_pointer.py`.

The short version: across 39 libraries, 21 applications and 3 heavily
agent-written projects, the citation form barely occurs, and where it does a
symbol sharing a line with a path is not a claim about that path. The 39-repo
pass flagged 10 and none was real. The agent-written pass - the population the
first rejection named as the last hope, since those documents cite code by line
constantly - produced about 16 flagged claims for at most one real finding, and
15 of its 23 pointer sites sat in completed plans, so the rule would have
mostly reported history.

Two things are worth keeping from it. An AST was built rather than assumed
away, and it changed nothing: the document supplies the symbol NAME, so the
check reduces to a string search and never needed a parser. And every narrowing
that removed the false positives also emptied the denominator, which is the
signature of a rule with no population rather than one with bad keying.

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

## The second widening pass: ten proposed, four shipped

A specification arrived on 2026-09-12 proposing widenings for nine of the
thirteen rules, each described as falsifiable and each claiming zero false
positives on the corpora. None of that had been measured, so all ten were
counted first - the form, then the findings - over the visible rows of every
manifest: 132 repositories and 77,401 documents, with the holdout and the 16
reserved benchmark rows left unread. The counting instrument is
`widening_census.py` in the measurement tree, and the before-and-after sweeps
are `widening_sweep.py` beside it. Four widenings were built, each with a
test that was watched failing first and a mutation anchor; the rest were
refused on the numbers below, which is the point of recording them.

### Shipped

**Reference-style link definitions.** `[label]: docs/setup.md` is the same
claim as an inline link and was read by nothing: 3,171 definitions name a
local file across 75 repositories, examined zero times. Two shapes wear the
colon and are not links. A footnote, `[^1]: text`, is refused by its caret. A
destination opening with a parenthesis is read LITERALLY, because CommonMark
keeps balanced parentheses in a destination: golang writes
`[cockroach#10214]:(cockroach10214_test.go)` sixty-three times in one testdata
README, the link is dead on GitHub whether or not the file inside exists, and
there every file has since been renamed to `.go` as well. The first draft
refused that shape as "text the author parenthesised" and would have hidden
sixty-three real findings.

**Raw HTML.** A README centres its logo with an `img` tag and links a sibling
with an anchor tag, and GitHub resolves both against the file exactly as it
resolves a markdown link: 8,488 local `href` and `src` attributes across 86
repositories. One refusal is new and depends on the repository. Inside a tree
a generator builds, a relative HTML `src` is resolved by the BROWSER against
the rendered page's URL, not by the generator against the source file, so
`../../img/x.png` written in a MkDocs `docs/user-guide/` page reaches
`docs/img/x.png` on the site and nothing relative to the file - the image is
there, and mkdocs/mkdocs writes exactly that. A markdown image in the same
position is rewritten by the generator and still names the file. So an HTML
attribute inside a site tree is neither judged nor counted, in the rule's
adapter where `in_site_tree` can be asked. A value holding a brace is a
template expression and names no file.

The two together, swept: **261 findings added, none removed**, and every one
was read. 115 sit in angular/angular's `adev/` tree, a documentation site
built by a bespoke Angular application that no signature here detects and
that already supplies 26 per cent of the benchmark's ordinary findings through
markdown links of the same shape - the widening inherits that concentration
rather than creating it. 63 are the golang testdata definitions above. 25 are
in vendored trees and 9 in test fixtures, both labelled or configurable.
Thirteen were confirmed by hand as broken images and links in ordinary
READMEs: six in OpenBMB/ChatDev, two each in crewAI's nested package README
and MetaGPT's android assistant, one each in mkdocs, sonic-pi and a vendored
synthesiser library. The remaining handful are undetected generators of the
same kind as angular's - an mdBook under `book/`, ExDoc assets, a custom
Astro site.

**A line range is read to its end.** `dead-line-pointer` read
`SKILL.md:211-215` at 211 and recorded widening to the end as "a separate
measurement". Made: 27 ranges name a tracked file, 22 sit inside it, 4 begin
past the end and were already reported, and ONE ends past it - lobehub's
page-agent README citing 32-116 of a 94-line file. One finding, zero false
positives. A colon is not a range separator: 73 citations carry a second
colon-separated number and 69 of them are BELOW the first, which is line and
column as every compiler prints it. A finding names the range only when the
range is what failed; a start already past the end keeps the `path:start`
spelling it always had, because `detail` is the baseline fingerprint.

**A SHA range inside one backtick pair.** The authoring constraint at the end
of this document used to ask for two tokens because `` `a..b` `` escaped both
checking and repair. Three such ranges in 77,401 documents: one is link text
over a compare URL in helix's changelog, whose first commit a rebase left
unreachable while GitHub still serves the page - excluded the way a single
linked SHA already was - and two are an agent's session log recording a
fast-forward whose both ends a later force-push rewrote away, which is the
population this rule exists for. Each end is tested as a token of its own, the
rewriter splits with the same function the scanner does, and the arrow
spelling is left alone: zero occurrences, and it is how a rewrite map is
quoted, left side dead by design.

### Refused

**Own-repository commit permalinks.** `https://github.com/<own>/commit/<sha>`
with the owner matching origin: 85,440 resolve and 1,211 do not, across 31
repositories. 1,180 of the dead are nodejs changelogs, where the link TEXT is
the same abbreviation and is already reported as a bare dead SHA - a second
finding on the same line. The ones written in prose - helix's release notes,
yosys's fuzzing guide - link to commits no local ref reaches and GitHub still
serves, from a rebased branch or a contributor's fork. A URL claims that a
page exists, which git in this repository cannot settle; a backticked SHA
claims membership of this history, which it can. Clause 1, failed in a way the
backticked rule does not fail.

**`dead-path-pointer`, all three halves.** With the current markers and the
proposed extensions, 141 sites and 71 missing, read: "you'll see CMake
configuration and a `main.cpp` file", "the compiler may read `baz.h`" twelve
times across bazel's version snapshots, "see how `print_fortune.go` uses this
package", bare names that live elsewhere in the tree. With the proposed verbs,
197 sites and 136 missing: "check `report.json`", "defined in your
`package.json`", "located at `foo/bar/a.txt`" as a documented default. With a
trailing slash, 80 sites and 47 missing: runtime directories such as `logs/`
and `node_modules/`, a session log saying the directory "does not exist -
no-op", and the English "read" in "read-only" and "cannot read outside". The
existing rule already runs at 191 findings over 654 examined on these corpora,
with the same shapes among them; the widening multiplies a known weakness
three ways.

**`#L` line anchors.** 42 sites; 39 name a file the repository does not
track, and the 3 that do cite lines inside it. No population.

**`.mdx` targets for `dead-md-anchor`.** 3,873 fragments into `.mdx` files
across two repositories, 3,859 of them examined by the widened rule, 16
findings, all 16 false. Every one names a heading that lives in an IMPORTED
partial - `## Tags File {/* #tags-file */}` sits in
`_partial-tags-file-api-ref-section.mdx` and reaches the page through a JSX
component - and the same mechanism already produces that repository's
same-document findings, in both directions. MDX composition makes anchors a
property of the rendered page, and the rule cannot see the render. Built,
measured, reverted.

**GitHub Actions pins for `dead-pinned-ref`.** Zero own-repository `uses:`
lines in the 132, so a corpus of 30 action repositories was cloned for it:
574 pins of the repository's own action resolve and 20 do not, and all 20 are
false. Sixteen pin a BRANCH - `@v3` is `origin/v3` in
marocchino/sticky-pull-request-comment, `@release/v1` is pypa's release
branch - which a clone holds only as a remote-tracking ref and a CI checkout
does not hold at all, so the answer would differ by where one stands. Four
are placeholders such as `@<tag>`. Wrong on every firing.

**JVM, .NET, Swift and version-file floors.** Manifests present: `pom.xml`
in 4 repositories, `build.gradle` in 1, `.csproj` in 3, `Package.swift` in 0,
`.nvmrc` in 11, `.python-version` in 6. Of the JVM and .NET repositories one
states a floor, and it agrees with its manifest. The manifest values need
normalisation nobody has measured - `1.8` against "Java 8", `net10.0`
against ".NET 10", a Maven property against anything - and `.nvmrc` and
`.python-version` are a developer's pin rather than a floor, which is clause
4; the `legacy-web` preset already offers that comparison as a user-asserted
consistency check.

**`unknown-branch` on standing documents, and wider prefixes.** 56 unknown
branch tokens in READMEs, CONTRIBUTING files and agent instructions, and not
one is a claim: `feature/<name>`, `feature/my-new-feature`, `fix/...`, a
table of naming examples, `test/js/bun/` (a directory), `release/blocking`
(a label). `test/` matched 57 tokens and every one was a path; `release/`
matched 51 and none was a branch that exists.

**Merge verbs and live phrases.** "landed on", "integrated into" and
"cherry-picked to" followed by a ref and a commit: zero sites - and zero for
the shipped pattern too, on these corpora; the installer already derives the
verbs a status document actually uses, `landed` among them. The proposed live
phrases match "open on startup", "port 9003 is open on your host", "resize in
progress on pod creation" and "staged on the target": 47 sites, none a merge
status. The four shipped phrases are a small closed set because a validator
that cries wolf stops being read.

## The third widening pass: six proposed, one shipped

A second specification arrived on 2026-09-13, proposing six widenings across
five rules and, as before, describing each as falsifiable with zero false
positives - measured this time on this repository alone, which is the corpus
every rule here was designed on and so settles nothing. All six were counted
first over the same visible population as the pass above, 132 repositories
and 77,401 documents, with the holdout and the sixteen reserved benchmark rows
left unread; the instrument is `widening_census2.py` beside the first one.
One was built, and the refusals below carry the numbers because the next
specification will propose them again.

### Shipped

**CommonMark titles and angle-bracketed destinations.** Two spellings the
format fixes and `MD_LINK` did not read. A title after the destination,
`[guide](docs/a.md "The guide")`, made the whole link invisible to both link
rules because the destination class forbade the space before it: 499 titled
links name a local target across 15 repositories and were examined zero
times. An angle-bracketed destination, `[x](<docs/a b.md>)`, is how the format
spells a target holding a space, and was read WITH its brackets - so a spaced
target was refused, and an external URL holding a parenthesis,
`<https://en.wikipedia.org/wiki/Shebang_(Unix)>`, was cut at the parenthesis,
failed the external test on its leading `<`, and was resolved as a file: 14
findings on the visible corpora, every one false, in bun, OWASP, zed, astro,
angular, llama_index, sonic-pi's vendored libgit2 and axe-core's changelog.
The pattern captures the destination as written, brackets included, because
the patch generator has to find it on the page; `link_destination` takes them
off for every caller that resolves or partitions one, in front of every
refusal. A
bare destination may not open with `<`, because a destination that opens with
one must close with one, so `[x](<docs/a.md)` is not a link rather than a link
to a file named `<docs/a.md>`; and two bare words are still not a link,
because a title must be delimited. Neither spelling gets a repair patch:
`suggest_renames` replaces `](old)` on the page, and a title or a bracket
puts the target elsewhere on it, so the finding stands and no patch is
written - the same silence a reference definition already gets, and a
missing repair over an invented one.

Swept: **14 findings removed and 58 added - 70 counting a message repeated
on several lines of one file - every one read.** Ten of the fourteen were
the false class above and are gone; four are respelled - three
axe-core changelog lines whose destination is literally
`[635445b](https://github.com/...)`, a changelog generator's artefact that is
dead on GitHub whether read to the parenthesis or to the bracket, and a
llama_index README linking to `(https://github.com/nlmatics/llmsherpa)`,
which is the golang testdata shape again. The `detail` of those four changes,
which re-raises them against a baseline; the old spelling was a misread of
the destination rather than a fingerprint anyone chose. Of the 58 added, 38
are angular's `adev/` tree - sixteen images and twenty-two routes - which the
pass above already records as an undetected site supplying a quarter of the
benchmark's ordinary findings; inherited, not created. Five are zstd's
benchmark images in a README vendored into RetroArch without its `doc/`
directory, three are query-graph images in a bazel version snapshot whose
directory the snapshot did not keep, four are documents in fastapi's
translation-fixer test data and two are astro mdx fixtures using the `~/`
alias, which the rule already reports three times unwidened. One is a real
broken image in an ordinary README, qmk's dactyl_manuform schematic, whose
`blackpill_f411/` directory holds five config files and no PNG. One is a
route in seqflow's Vite-built website, which already carries nine of the
same shape. Denominators: `dead-md-link` from 170,360 to 170,844 examined,
`dead-md-anchor` plus three.

Two things the change cost and one it found. The lazy destination class,
left as it was with the title group behind it, tried that group before every
character it extended by, and the 8,000-opener `[a](` line the bounds test
carries went from 1.44s to 2.85s against a five-second margin - still linear,
and too close for a slower runner. Greedy with a lookahead for the space or
parenthesis that must follow, the run is taken once and the group entered
once: 1.09s, the same result on every shape either arm reads, and the timing
test now carries the title and bracket openers too. `text.py` reached 918
lines against a 927-line ceiling, so the link scanner - `MD_LINK`,
`EXTERNAL`, `link_sites`, the HTML walk and `_link_target` - left for
`links.py` the way the anchor machinery left for `anchors.py`: byte for
byte, eighteen mutation anchors following by path alone, and nothing left
behind reading a name that moved. And a mutation was once reported caught by
the wrong test, which is how the range tests in `test_widened_scanners.py`
were found to abbreviate a real SHA to seven characters that `looks_like_sha`
refuses one run in twenty-five, when all seven are digits; they abbreviate to
the shortest prefix carrying a letter and a digit now.

### Refused

**Script invocations inside fenced shell blocks, for `dead-path-pointer`.**
The argument offered was the one `dead-pinned-ref` makes above: an install
snippet is the block a reader copies verbatim, and `python
tests/harnesses/mutate.py` in an agent instruction file is the same kind of
block. Counted from the RAW text, since `prose()` blanks every fence: 2,534
invocations across 81 repositories, 1,485 naming a tracked file and 1,013
not. 869 of the 1,013 are bare names, and 348 of those are typer's
documentation alone - `python main.py`, the file the tutorial has just told
the reader to create - with click's `hello.py`, sonic-pi's
`./linux-build-all.sh` run from a directory the previous line entered, and
z3's `./bootstrap-vcpkg.sh` from another repository beside them. 144 carry a
directory component. 108 name a directory that does not exist either:
`path_to_your_working_directory/`, `dist/index.js`,
`./cross-build/wasm32-emscripten/build/python/python.sh`,
`./node_modules/jest/bin/jest.js`, a vendored README's scripts, and commands
written relative to a package directory that is neither the document's nor
the root. 36 name a directory that exists, 21 distinct, and six of those are
real on inspection - llama_index's `scripts/merge_external_docs.py`, angular's
`integration/run_tests.sh`, node's `tools/gn-gen.py`, agno's
`cookbook/gemini_3/5_grounding.py`, dosbox's `scripts/build.sh` and
openinterpreter's `scripts/write_provider_catalog.py` - beside `scripts/foo.sh`
as a placeholder, `test/repro-XXXX.js`, pdns's `builder/build.sh` inside a
submodule and goose's `scripts/` named relative to `ui/desktop/`. Narrowed to
root-level documents, which is the population the install-snippet argument
is actually about: 65 invocations, 19 not resolving, and none of the 19 real.
Every narrowing that removed the false ones removed the six real ones with
them, which the note on symbol-aware line pointers above names as the
signature of a rule with no population rather than one with bad keying.
Six real findings under a thousand false is worse than the 191-over-654
the existing rule already runs at, not better.

**Table cells under a `Path`, `File` or `Location` header.** 3,170 backticked
cells under a path-shaped header across 49 repositories: 827 resolve, 2,120
do not, 127 are absolute and 96 placeholders. The headers say what the cells
are. `Tool` governs 688 cells and 674 of them are bare tool names, `Package`
158 npm names, `Component` and `Module` 217 more of the same. Under the eight
headers the specification proposes and the three shapes that could be a path
- a slash, an extension, a trailing slash - 951 cells resolve to nothing,
and reading them by repository: 343 are unraid's agent session logs listing
the files each session created and modified, relative to a sub-project the
document is not in; 184 are crewAI's scaffold listing (`crew.py`, `.env`,
`knowledge/`) in twenty version snapshots of one installation page; 70 are
bazel's tutorial layouts; 50 are mem0's workflow filenames relative to
`.github/workflows/`; 47 are agno's cookbook indexes. The smaller subsets read
the same way: every missing `Script` is an acceptance script in an agent
process file, the missing directories are `dist/`, `out/`, `node_modules/`,
`release/` and `.wanta-dev/`, and the slashed files are `packet.h/cc`
shorthand, `scripts/x.py::run_arm_p` citations and plan tables with a
Modify/Delete column. A table names what a file IS, not where it is - the
same finding as the 23-of-88 measurement that keyed this rule on operative
markers in the first place, at a larger scale.

**`manifest-floor-mismatch` in agent and contributor documents, and the
phrase "the floor is".** The phrase first: over every document, 17 sites use
"floor" or "minimum" beside a version, and not one reads "the floor is
<language> <version>" - nine say "a minimum of X" and eight "the minimum
version is X", twelve of them in changelogs, blog posts and third-party
subjects (TypeScript 3.8 for jest's definitions, macOS 10.7, iOS 13.0,
OpenSSL 1.0.2, an ARM cross compiler) and five in vendored READMEs. The
phrase exists in this repository and in none of the 132. The document
widening was measured through the rule's own `_floor_claims` with the wider
`_ENTRY_DOC`, over every AGENTS, CLAUDE, CONTRIBUTING, DEVELOPMENT, SETUP,
ENVIRONMENT and HACKING file: three claims in three repositories - dspy's
CONTRIBUTING "Python 3.10 or later is required", skyvern's CLAUDE.md
"Requires Python 3.11+", openemr's CONTRIBUTING "Requires PHP 8.3+" - and all
three agree with their manifest. Three examined and zero findings is not a
widening. It also carries a clause-4 concern the census could not test: a
contributor guide states what a DEVELOPER needs, and a project whose type
checker wants a newer interpreter than its users do would be the first
repository this shape spoke on, falsely. The two sides name the same fact in
a README and an install guide; they need not in a CONTRIBUTING file.

**Built-in version pairs for `inconsistent-artifact`.** Measured pair by
pair. `pyproject.toml` against a package `__init__.py`: 33 repositories carry
the manifest, 23 have no `__version__` in a package `__init__` at all, 9
declare `dynamic = ["version"]` so the manifest holds nothing to compare, and
one - jztan/pdf-mcp - is comparable and agrees. `package.json` against
`package-lock.json`: 13 repositories carry both, 9 are comparable and agree,
4 state no top-level version in either file. `Cargo.toml` against
`Cargo.lock`: 9 carry both, 8 root manifests declare no package version,
one is comparable and agrees. The Claude plugin pair: two
repositories carry both files and neither is comparable, because
`marketplace.json` states its version per plugin inside a list - as this
repository's does - so the pattern the specification writes matches nothing
in either. Eleven comparisons on 132 repositories, zero disagreements, and
the pattern proposed for this project's own manifests would not have read
them. The note above `"consistency": {}` in `config.py` says a guessed
default "would either match nothing or accuse an innocent repository", and
the measurement found the first half. The presets in `install.py` already
write these pairs at install time, with the files located and the patterns
verified to match before a line is emitted, which is the user-asserted form
the clause-4 argument asks for.

**Nested `.gitattributes` for `raw-lfs-blob`.** The per-file verdict already
composes: it comes from `git check-attr --stdin`, which reads every
`.gitattributes` in the tree with negations and later rules applied, and the
rule's own comment says so. What keys on the root file is the gate, and the
gate is right on every visible repository: 85 track a `.gitattributes`, 4
route anything through LFS at the root, 23 track a nested one, 2 hold an LFS
filter in a nested one - tabby in four sub-projects, autogen in a test images
directory - and both of those beside a root filter. Repositories whose only
LFS filter is nested: zero. The gate exists to spare the 128 repositories
without LFS the `ls-tree -r` that finding a nested file needs, and it would
spend that spawn in every one of them, once per `validate()` and once per
`count_examined()`, against a `--verify` budget with no headroom by design.
`subject_file` naming the root file is a defect only on the population that
does not exist. Refused on population and on cost; the fixture with a
nested file and no root one is the test to write when a repository of that
shape turns up.

### The benchmark reserve, opened and read

Re-recording the corpus report after both passes put a number in it that
nobody had judged: 1,043 of the benchmark's additions sat in its sixteen
reserve repositories, 1,019 of them in tensorflow/tensorflow, and the reserve
is held back precisely so no pass reads it while designing. The report said
so beside the figure. The operator then chose to spend the reserve on a
reading rather than publish an unjudged number - tensorflow first, then the
other four repositories with additions - on 2026-09-13. The manifest rows
record the opening and the date, so nothing measured later mistakes them for
unseen ground; the eleven reserve rows with no additions stay closed. The
readings are recorded beside the recordings, and the report renders them.

**tensorflow, 1,019.** All are the `href` of raw HTML, the arm the second
pass added, and 1,018 live in `tensorflow/lite/g3doc/`, the DevSite tree
`sites.py` already records as deliberately unreached - its `_book.yaml` sits
three levels down, and scoping detection that deep silenced six real defects
in astro and llama_index. 1,003 are routes that resolve the moment `.md` is
appended, the same class as angular's `adev/` findings; 15 are links in a
generated `all_symbols.md` index that the generator wrote one directory too
shallow, routes in the same tree whether or not the site serves them; and 1
is a real broken image in the vendored XLA README under `third_party/`. No
new false-positive shape, one real finding, and the class it multiplied was
already on the record.

**The other 24, and the two things they found.** Five are titled image
links in vscode's copilot scenario and colorize test fixtures, and one is an
HTML link in an npm package's README copied into deno's bench test data
without its `docs/` directory - fixtures, which `exclude_paths` is for. Two
are pages of mdBooks three levels down: clippy's book serves
`continuous_integration/README.md` under the name `index.md`, and the
unstable book generates `impl-trait-in-assoc-type.md` at build time. Two are
real: a rustc-dev-guide page, `generic_arguments.md`, that no longer exists,
and a dead link in clippy's changelog, labelled historical-record. That
leaves two shapes the visible corpora had never shown.

The first is a scanner defect, fixed. `` [`unused_peekable`]: Now respects
`#[allow]` attributes... `` is a changelog line; CommonMark lets a
definition's destination be followed only by an optional title and the end
of the line, so it renders as a paragraph and links nothing, and the pattern
the second pass added stopped reading at the destination and reported a dead
link to a file named `Now`. Measured before it was changed: zero of the
3,171 definitions recorded on the visible corpora carry trailing prose, so
requiring the line to end removes nothing there and cannot remove a real
definition. The recordings were taken again with the fix, so the report
describes the tool it ships with.

The second was built the next day, and the measurement that shaped it is
the interesting part. `` [`float`]: c_float `` in
`library/core/src/ffi/c_double.md`, and `[value-macro]: macro@crate::value`
in turbopack's `vc/README.md`, are rustdoc intra-doc links: the markdown is
pulled into rustdoc by `#[doc = include_str!(...)]` in a sibling `.rs` file,
and the destination is a Rust path, not a file. 13 of the 24 are this shape,
and the visible corpora hold 2 more, in a README zed's `gpui.rs` includes.
Both halves of the refusal are needed - the shape alone is `[x]: LICENSE` in
any README, and the inclusion alone leaves `[guide](docs/guide.md)` a file
rustdoc links to as a file - so `dead-md-link` declines a destination shaped
like a Rust path only inside a document some `.rs` file pulls into rustdoc,
in the adapter where the site-tree refusal already lives, neither judged nor
counted.

**Where to look for the including file was measured, not chosen.** Across
the 132 visible repositories, five pull 176 markdown files into rustdoc.
Finding every one means reading every `.rs` file in the repository: 668
seconds across the corpora, rust alone 419, which is not a question a hook
can ask. Reading only the `.rs` files in the document's own directory and
its `src/` child - a crate keeps its README beside `src/lib.rs`, and rust's
`c_*.md` sit beside `primitives.rs` - takes 1.4 seconds in total and finds
78 of the 176, including every document that carries one of the 15
findings. The 98 it misses have their including file two directories up,
`..` or `../../src`, and hold no link of this shape at all, so the bound
drops no refusal on any corpus measured. A refusal missed reports a finding
somebody can argue with; a search widened without a measurement is how a
suppression grows quietly, and a mutation anchor now bites on exactly that
widening.

Two details keep the inclusion test honest. The literal is resolved against
the source file's directory and compared with the document's path, never
matched by basename, because `docs/src/lib.rs` including the crate's
`../../README.md` would otherwise claim `docs/README.md` too. And the
attribute shape is `#[doc = include_str!`, not a bare `include_str!`, which
also embeds a template or a fixture as a string - and rust's `primitives.rs`
shows why the literal is looked for anywhere in the file rather than inside
the parentheses: it writes `include_str!($Docfile)` and passes `"c_double.md"`
to the macro. The answer is memoised per directory for the run, and asked
only once a link of the shape is on the page, so a document with none pays
for no source read.

## Where a decode happens is a decision, not a default

`plugin/skills/extant/payload/extant/git.py` ran every git command with
`text=True`. That reads as "give me a string" and means "decode this somewhere
I have not named", and where that somewhere is differs by platform:

- On Windows `Popen._communicate` decodes on a reader THREAD. A byte git emits
  that is not valid UTF-8 kills that thread, `communicate()` hands back None,
  and `_git` returns None to callers annotated `-> str`. `_git_soft` cannot
  catch it, because nothing was raised for it to catch.
- On POSIX the decode happens in the caller's own thread at the end of the
  same function and raises `UnicodeDecodeError` - which `_git_soft` does not
  list either, so the path documented to return the empty string rather than
  raise, raises.

One silent wrong answer and one crash, out of one line, chosen by the operating
system. The silent half is the one that matters here: a rule handed None finds
nothing, and finding nothing prints exactly what a clean document prints.

**It was already diagnosed, one call site away.** `_document_at` - in
`plugin/skills/extant/payload/extant/sweep.py` then, in
`plugin/skills/extant/payload/extant/deleted_since.py` since the mode left on
2026-09-14 - carries a paragraph describing
this mechanism exactly, because that mode hit it and was repaired there by
capturing bytes. What a fix in that position cannot do is repair the module
every rule asks its questions through.

**The reachable case is a path, not a commit message.** `tracked_markdown` in
`plugin/skills/extant/payload/extant/refs.py` decides which documents a sweep
looks at AT ALL, and it runs `ls-tree -r -z --name-only`. The `-z` turns OFF
the `core.quotePath` escaping that would otherwise render unusual bytes as
ASCII, so the raw bytes arrive on every platform and under every
configuration. Against a repository holding one tracked file whose path is not
valid UTF-8, `--sweep` - the mode a first-time reader runs - exited with
`AttributeError: 'NoneType' object has no attribute 'split'`. That function's
own docstring calls a listing which comes back short "the worst shape available
- a silent all-clear on a repository nobody checked", and this was the route to
one it did not anticipate.

Pre-UTF-8 history is not exotic. A latin-1 or Shift-JIS commit subject written
before an `encoding` header was routine emits such bytes from `git log`, and
reading other people's repositories is what this tool is for.

**`errors="replace"` is right here and stays wrong one module over,** which is
why this is a decision and not a default to apply wherever the same call shape
appears. `_git` returns git's own METADATA - ref names, object ids, commit
subjects - where a replaced character costs a garbled name inside a message
nobody validates. `_document_at` returns the DOCUMENT, where the same
substitution would have every rule checking text the file does not contain, so
that one decodes strictly and reports what it caught. Same bytes, different
question, different answer. The newline translation is
`subprocess._translate_newlines` verbatim, so a caller splitting on newlines
sees what it saw before.

**Two sites with the same shape were left alone, and the reason is
reachability rather than oversight.** `_batch_shas` in
`plugin/skills/extant/payload/extant/refs.py` feeds `cat-file --batch-check` a
string, so what git echoes back for a missing object is valid UTF-8 by
construction; the `_search_with_limit` child in
`plugin/skills/extant/payload/extant/rules/consistency.py` speaks JSON in both
directions, and `ensure_ascii` keeps that pure ASCII whatever the pattern
holds. A fix neither reachable nor falsifiable is a change nobody can watch
fail, which is the shape this project refuses everywhere else.

## The conservation check proves a value, not a write

`archive()` in `plugin/skills/extant/payload/extant/entries.py` calls itself
the only irreversible file operation in the system and asserts multiset
conservation of every line before writing anything. That assertion is about
two strings in memory. It says nothing about a process that dies between the
two `open(..., "w")` calls that put them on disk, and no ordering of those two
writes changes what the Counter sees.

The primary was truncated first and the archive written second, so the window
between them held the retired entries in NEITHER file - the one outcome the
function exists to make impossible, reached by a route its own guard cannot
observe. Writing the additive file first inverts the failure: the same crash
leaves the entries in both, and a duplicate is something a reader can repair.

The general form is worth keeping: a guard that runs before the writes bounds
the VALUES being written, and ordering is the only thing that bounds the
partial states. Where both matter, both have to be stated.

## A configured pattern that will not compile should name itself

`_compile_consistency` in `plugin/skills/extant/payload/extant/config.py` has
always wrapped a bad consistency pattern into a `ValueError` naming the file
and the setting. The other configured patterns beside it compiled bare, and
`re.error` is NOT a subclass of `ValueError` - so nothing guarding a
configuration load caught it, and what reached the operator was a message about
a character position inside a pattern they never see.

The timing was worse than the wording. Settings load at IMPORT, so the
traceback arrived out of this package before any mode had begun, for a typo in
theirs. All of them route through one helper now, and the test asserts each
setting names itself rather than checking one and trusting the rest - a helper
applied to nine of ten leaves the tenth failing in exactly the way the test was
written to stop.

## A schemeless URL is not a path, and the fix is a suppression

`EXTERNAL` - in `text.py` then, in `links.py` since the link scanner left on
2026-09-13 - decided "not ours to check" for every link rule, and it
recognised a URI scheme or a protocol-relative `//` and nothing else. So
`[docs](www.skyvern.com/docs)` and `[author](github.com/josh-l-wang)` were
joined to the document's directory and reported as dead links.

FOUND BY TWO CORPORA AT ONCE, which is what made it a class rather than a
curiosity: `Skyvern-AI/skyvern` on the 2026-09-05 held-out half, and
`qmk_firmware` 18, `sonic-pi` 2, `RetroArch` 1 and `lean4` 1 on the niche
corpus built the same day. Five repositories, two corpora, neither of which any
rule was designed on - past the "all the true positives are in one repository"
bar that this document uses to refuse candidates.

THE HAZARD IS NOT THE PATTERN, IT IS THE SUPPRESSION. Widening `EXTERNAL`
silences whatever it matches, and a suppression firing wrongly deletes a real
finding where a false positive at least stays in the output for somebody to
argue with. A great many TLDs are also file extensions - `.md` is Moldova,
`.rs` Serbia, `.py` Paraguay, `.sh` Saint Helena - so the obvious `host.tld`
rule would read every markdown link as a URL and silence the link rules
everywhere while every run still looked clean.

So the arm was bounded by measurement before it was written. Across 157 cloned
repositories and 220,990 internal link targets it matches 41 distinct targets,
every one of them a URL, and NOT ONE target that resolves to a file which
exists.

THE TLD LIST IS TWO A PRIORI RULES AND ONE MEASURED EXCLUSION, which is what
keeps it from being tuned on the corpus it was measured against. Admitted: the
generic TLDs a documentation link uses, and the ISO-3166 two-letter codes.
Struck out: every code really used as a file extension in those repositories -
`.py` at 81,121 files, `.rs` 61,737, `.md` 53,611, `.cc` 16,058, `.sh` 4,795,
`.mk` 2,326, `.tf` 1,758, `.pl`, `.in`, `.pm`, `.ai` and the rest, plus generic
`.info` (110), `.page` (83), `.tools` (38) and `.xyz` (22).

THE FIRST VERSION SHIPPED WITH ONLY THE GENERIC HALF, and an audit of it found
three survivors: `anomalykb.co`, `imaginaerraum.de` and `fablab-bayreuth.de`.
A generic-only list is a US-centric list, measured on corpora that are
themselves US-centric, so three is a floor rather than the rate. Adding the
country codes was re-measured the same way and lost nothing.

Two arms, because they fail differently. `www.` is unambiguous: no file is
named `www.a.b`. The hostname arm needs at least one `label.` before a listed
TLD and then a path, query, fragment or end of string, which is what keeps
`README.md` and `script.sh` paths. Requiring a path would have been safer still
and was rejected on measurement rather than taste: it drops the fix from 55
targets to 33, because `webbench.ai`, `hanboards.com` and `stratakb.com` carry
no path at all.

## The environment a git process inherits is an answer, and it was the wrong one

`_git` in `plugin/skills/extant/payload/extant/git.py` ran `["git", *args]`
with `cwd=repo` and whatever environment the process was started with. Those
two decide different things. `cwd` decides which WORKING TREE git looks at;
`GIT_DIR` - and six variables like it - decides whose HISTORY it answers
about. Git exports `GIT_DIR` and `GIT_WORK_TREE` to every hook it runs, a
pre-commit framework sets them too, and a harness that drives one
repository's hook against another's checkout passes them straight through.

Verified before anything was changed, on this machine: from a second
repository, `GIT_DIR=../r1/.git git log -1` printed the first repository's
subject while `git rev-parse --show-toplevel` still named the second. So a
hook checking any checkout other than the one it fired in - a submodule, a
linked worktree, a sibling in a monorepo - had every git-backed rule
answering about the wrong repository, and the run printed exactly what a
clean one prints. The test that pins it cites one commit from each of two
repositories and asks which is dead; under any of the four leaks that move
that answer, `dead-sha` reported the wrong one, or - with an alternate
object directory - neither.

**Every git process now gets one environment**, built by `environment()` in
the same file: the operator's, minus the seven variables that name a
repository, plus `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=`,
`GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C` and `GIT_NO_LAZY_FETCH=1`. Applied at the
seam AND at the six sites that call `subprocess` directly - the `cat-file`
batches, the attribute query, `git show` - because a scrub at the seam alone
would have left the SHA rule, the LFS rule and `--deleted-since` answering
from the leaked location while everything else answered from the right
one. The structural test records every git process three modes start, with
the environment each was handed, and its denominator is that each direct
site was actually reached: nine of fourteen were unscrubbed the first time it
ran.

**`GIT_CONFIG_COUNT`, its keys and values, and `GIT_CONFIG_PARAMETERS` are
deliberately kept.** They carry configuration rather than a location. CI uses
the triplet for `safe.directory`, and `git -c` passes its arguments to every
process it starts through `GIT_CONFIG_PARAMETERS` - verified by reading a
hook's environment under `git -c` - so a child that lost them would fail where
the parent works. What they can do is rewrite a remote URL, and that is
handled where the URL is read, below.

**`core.quotePath=false` rides in the same environment**, appended to the
operator's own `GIT_CONFIG_COUNT` set rather than passed as `-c` in front of
every subcommand, so the argv every test and budget records stays the
question that was asked. On by default, the setting prints a path holding
any byte above ASCII as a quoted, octal-escaped string. Two readers were
caught by it, both verified on the command itself: the rename map read out
of `log --name-status` held `"docs/\303\234bersicht.md"` where a document
writes the umlaut, so the pointer was still reported dead and the "renamed
to" hint silently did not appear; and `--deleted-since` compared such a
document's name against `diff --name-only`, never matched it, and examined
nothing. The `-z` listings were never affected; `-z` turns the quoting off.

**`--repo` below the root is said, not refused.** From a subdirectory git
walks up and answers about the checkout above while every document and path
resolves against `--repo` - `rev-parse --show-toplevel` from `r2/sub/deeper`
prints `r2`, quietly. `repository_root` finds the root the way git does, by
stat rather than by spawn, because the budget in `tests/test_spawn_budget.py`
has no spare margin and a question asked once per run is still a question.
A note rather than a refusal because `--repo <subdir>` has worked since the
flag existed. A directory with no repository above it - a `git archive`
extract - gets a note too, in front of the thirteen rule errors that would
otherwise have to imply the cause.

### The remote guard read one file, and a rewrite can live in five other places

`remote_url` reads the repository's own config file instead of spawning
`remote get-url`, and declines when that file mentions `insteadOf` or an
include. But `url.<base>.insteadOf` is equally effective from `~/.gitconfig`,
the XDG file, `/etc/gitconfig`, a conditional include of any of them, the
`GIT_CONFIG_COUNT` triplet, or the `GIT_CONFIG_PARAMETERS` that `git -c`
exports. The guard read none of those. A sandbox that injects exactly that
found it: the `scp-style-ssh` row of `tests/test_remote_from_disk.py` went
red with `git=https://github.com/acme/widget.git
file=git@github.com:acme/widget.git`.

That rewrite changes only the host and lands on the same `owner/name`, which
is what the guard's comment had reasoned about. **The audit of this fix
found that the obvious counter-example does too.** `_normalise_remote`
compares the LAST TWO path segments, so
`url.https://internal/mirror/.insteadOf = https://github.com/` - git reports
`https://internal/mirror/acme/widget.git`, verified - still reads as
`acme/widget`, and the first end-to-end test, written against that mirror,
failed by finding the rule unmoved. The rewrite the guard is for moves the
repository under another owner: `url.git@internal:widgets/.insteadOf =
https://github.com/acme/`, which git reports as `git@internal:widgets/widget.git`
and the rule reads as `widgets/widget`. Then `dead-pinned-ref` compares a
project's pins against a repository git would not name, silently - and the
end-to-end test asserts the rule now answers `widgets/widget` through the
spawn the guard falls back to.

**Fixed with reads, not a spawn.** `_unsettled_elsewhere` stats and reads
every file git treats as global or system configuration that can be named
without asking git - `GIT_CONFIG_GLOBAL` when set, else `~/.gitconfig` under
every spelling of home the process can see and the XDG file;
`GIT_CONFIG_SYSTEM` when set, else `/etc/gitconfig` and `etc/gitconfig`
under the install prefix of the `git` on PATH, which is where Git for Windows
keeps its system file (`C:/Program Files/Git/etc/gitconfig` here) - and scans
the two environment injections. Any mention of a rewrite, an include, or a
remote of its own declines. A remote SECTION is refused in these scopes and
not in the repository's file where it is expected, because `get-url` reports
the FIRST value and scopes are read system, global, then local: a remote
defined globally wins the lookup.

Seven scopes are each tested with the path-changing rewrite, each asserting
first that git itself reports the mirror - so a fixture that failed to
reproduce the divergence cannot pass by accident - and then that the fast
path declines. The denominator beside them: with every other scope pinned
empty, the plain spelling is still answered from disk, because a guard that
declines everywhere passes the seven rows and buys nothing.

**Three costs, stated.** The read went from 0.19 ms to 1.41 ms (median of
200) - ten candidate files, most of them absent, opened and read; the walk
along PATH for git is 0.09 ms of it, and `shutil.which` was not used for it
because importing `shutil` pulls the compression modules in behind it, 14 ms
on a hook that pays every import. Against the 28.92 ms spawn it replaces
that is still a factor of 20. A developer whose global config carries
the ordinary work-and-personal `includeIf` now pays the spawn on every run -
following an include, with its `gitdir:`, `onbranch:` and `hasconfig:`
conditions, would be reimplementing git rather than consulting it, which is
where this technique stops. And a git built with its system directory
somewhere this cannot name is the residual; it is why the repository's own
file stays the guard's first question rather than its only one.

Two tests that asserted an answer FROM DISK now run under a fixture that pins
the other scopes empty. Without it they would fail on the machine of any
developer whose real `~/.gitconfig` carries an include and pass on CI, which
is the shape of failure this whole file is about.

### A partial repository, and a promise the README makes

`git clone --filter=blob:none` keeps every commit and tree and only the blobs
the checkout needed. Any command that then wants another blob retrieves it
from the promisor remote, mid-command, over the network - and the README says
nothing here touches the network. Phase 25 measured it without naming it:
sweeping one such repository stalled for half an hour while rename detection
went blob by blob to the server, and reported fewer findings each time as the
object store warmed.

Verified by hand on git 2.53 before the test was written: in a `blob:none`
copy holding one rename WITH an edit, `git log --diff-filter=R --name-status`
retrieved the old blob and printed `R063`; under `GIT_NO_LAZY_FETCH=1` the
same command exited 128 with "could not fetch ... from promisor remote" and
the blob stayed missing. The edit matters: an exact rename is matched by
object id and needs no blob, so a fixture built with `git mv` alone proves
nothing.

So the guard costs the rename hint for exactly that case, and it is taken
anyway: a stated guarantee outranks a hint, and a hint that arrives by way of
a network stall is not a hint anyone waits for. What replaces it is the note.
`is_partial` reads the shared config for `remote.<name>.promisor = true` -
what git itself checks - or either spelling of the filter key, and the run
prints beside the denominators that objects not present locally were left
missing, where the shallow note already prints. The test of the guarantee
is the set of missing objects before a `--verify` compared with the set
after, on a document pointing at the old name of the renamed file; with the
guard removed, one object was retrieved.

`GIT_NO_LAZY_FETCH` is honoured from git 2.42 and the floor is 2.31. Below
2.42 the retrieval still happens and the note is what remains; the test skips
there and prints the version rather than passing on a git that ignores it.

**Measured a day later, on the bench tier, which is `blob:none` throughout.**
A sequential sweep of ruff with the 0.26.1 payload takes 11.1 s, and 4.6 s
of it is ONE `cat-file --batch-check`: the SHA rule's batch asks about every
hex token the documents hold, a token that is not a local object is one the
promisor remote might have, and git asked GitHub for each. With the guard
the same batch takes 0.03 s and the sweep 7.3 s. That is the mechanism
behind the "fewer findings each time as the object store warmed" that Phase
25 saw without naming: a dead SHA that GitHub happened to hold was fetched
and reported alive, and each run left the clone holding more. It is also a
change in what `dead-sha` answers on a partial clone - about what is here,
as on a shallow one - which is what the note beside the denominators now
says.

**The guard had one new way to be wrong, and the audit of it found that.**
`--deleted-since` reads each configured document as it stood at the ref with
`git show`, and None from that read meant "absent then". In a partial
repository the old version's blob is exactly what the transport left out, so
with retrieval refused the read fails - and "absent" hid the deleted false
claim the mode exists to report. Measured on the fixture: examined 0,
unreadable 0, silence, where the full copy reports the claim. Before the
guard, git would have retrieved the blob and reported it; the guard turned a
network call into a silent wrong answer, which is a worse trade than the one
it was meant to make. `_document_at` now asks a second question when `git
show` fails in a partial repository - did the tree at the ref list this path,
which `ls-tree` answers from the tree alone - and raises `MissingObject` for
a path that was there, landing it in the mode's "could not be read" count
beside the undecodable versions. A copy whose trees are missing too cannot
answer the second question either, and is reported as unreadable rather than
absent: "could not be read" is true of it, "was not there" is not known to
be. The distinction took `sweep.py` from 912 lines to 962 against the
927-line ceiling, so the `--deleted-since` mode moved to
`plugin/skills/extant/payload/extant/deleted_since.py` - the cut the old
module docstring had already drawn as "the two survey modes" - with eight
mutation anchors following by path.

**The shallow note is printed only by `--validate`, `--verify` and
`--check-text`.** `--sweep` never printed it, and the partial note inherits
that gap. Recorded here rather than fixed, because the survey's diagnostics
are a different shape - one summary over many documents - and the shallow
case is the one Phase 25 measured a sweep getting wrong.

## Where a sweep's time goes, measured without the profiler

A review of the internals read a cProfile of a sequential ruff sweep and
proposed four changes to the document scan, projecting "the cheapest 2x
available". Two of its premises did not survive measuring the same sweep
wall-clock, on this machine, with nothing instrumented but the clock: 650
documents, 7.1-7.3 s, on the `blob:none` clone the bench tier keeps.

| where the time goes | s | share |
|:---|---:|---:|
| `dead-md-link` - the link scan and the filesystem walk behind it | 1.94 | 27% |
| git, five spawns, `log --diff-filter=R -n 200` and `ls-tree -r` the large ones | 1.51 | 21% |
| `dead-sha` - blanking 0.54, the two SHA candidate scanners 0.76 | 1.38 | 19% |
| `dead-md-anchor` - slugging three spellings per heading | 1.10 | 15% |
| `_release_claims` | 0.71 | 10% |
| `_pinned_refs` / `_merge_claims` | 0.34 / 0.29 | 9% |

Git is a fifth of the run rather than "~0": the review's sandbox had a fast
filesystem and a full clone. And cProfile overweights code that makes many
small calls, so `_line_and_terminator`'s reported 0.45 s of self time is
about 0.1 s real - which decided the first item.

**5.1, the blanking rewrite, refused on the numbers.** Three exact
rewrites of `_blank_uncached` were built against the current 486-497 ms
for both flavours over ruff. The review's region-based one - fence lines
found by one scan, regions blanked by one substitution each, exact to the
`splitlines` segmentation with the eight breakers only that function
honours excluded from the inline class - is byte-identical on all 1,300
(document, flavour) pairs and 1,662 ms: a per-character substitution over
a fenced region costs more than the per-line loop it replaces. A per-line
rewrite with the terminator peel inlined is 383 ms, 1.30x, and a second
copy of the peel this project unified after the CRLF defect, with a
mutation anchor guarding the one copy. A rewrite that keeps the one peel and
appends the 81% of lines that need no work verbatim is 434 ms, 1.12x -
some 50 ms in a sweep whose run-to-run spread is 180 ms. None is worth a
second implementation or a retargeted anchor.

**The two line numberings, item 6.2, answered without changing code.**
Eight sites number lines with `enumerate(splitlines())` and two with
`line_number_at`, and they differ only on a document holding one of the
breakers `splitlines` honours and `LINE_BREAK` does not. Counted across
185 repositories and 108,647 documents read strictly: 15 hold one - 12 a
form feed, 2 `U+2028`, 1 `U+2029` - and 13 of those between backticks on a
line. The numberings can differ on 0.014% of documents; the item closes on
that number.

**5.3 and 5.4, the pre-filters, taken - with the derivation and the fold
that made them more than a substring test.** Both scans run a pattern the
user may configure, so the words a document must hold come from the
pattern itself: `leading_literals` in
`plugin/skills/extant/payload/extant/text.py` reads a leading `(?:a|b|c)`
of plain literals and refuses every shape where the words are not
necessary - a quantifier after the group, a top-level `|` later in the
pattern, a `\b` or inline flag first, a `\w+` inside the alternation -
each of which is a test. A configured pattern of any other shape scans in
full. Deriving the words once onto the built `Config` was the first
design and would have been wrong: tests replace a pattern with
`dataclasses.replace`, and the stored words would have belonged to the
pattern before it.

The comparison is not `lower()` alone. `re.IGNORECASE` folds four
characters onto ASCII letters that `str.lower()` does not - dotted and
dotless capital I, long s, the Kelvin sign - verified: `SH<U+0130>PPED in 1.0`
matches the default release pattern and `lower()` leaves no "shipped" in
it. A text holding any of the four is let through unread. Conservative in
every direction: a wrong True costs a scan that finds nothing, a wrong
False would cost a claim, and the corpus differential below is what says
the second never happened.

Over the corpus the words are rare - release words in 3.6% of 108,647
documents, merge words in 2.9%, `rev:` in 0.1% - which is why a pre-filter
pays: on ruff, 19, 12 and 5 of 650. `_pinned_refs` asks for `rev:` before
it asks for the remote, so on CI, where the remote is a spawn per document
that the config cannot answer, only the documents holding a pin pay it -
three of this repository's five - and `tests/test_spawn_budget.py` counts
them from the files rather than assuming every document.

**5.2, the precompiled slug patterns, kept as a tidy-up.** `anchors()`
went from 892 ms to 826 ms with identical results; the `re` module's cache
made the string spellings a dictionary lookup per call, 232,581 of them,
and not a compile. One mutation anchor followed the spelling.

**The differential.** `scan_differential.py` in the measurement tree
records, per tracked document of the 152 visible manifest rows, digests of
both blanking flavours, the anchor set, and the release, merge and pin
lists, from whichever payload it is pointed at; run against HEAD's payload
and the changed one and compared per document, so a divergence names the
file. Git is never asked - the pin walk is given one fixed remote in both
runs.

**Found on the way, recorded rather than fixed here.** Every bench-tier
clone is `blob:none`, so `GIT_NO_LAZY_FETCH` changed that tier's output:
rename hints no longer appear there, and a `dead-path-pointer` finding
carries its hint INSIDE `detail` - "; git shows it renamed to ..." - which
is the baseline fingerprint. The hint varies with the checkout, shallow or
partial or a rename older than the 200 commits read, and that is the
argument that moved the commit-map hint out of the identity and into a
field of its own. The rename hint should follow it; a CORPUS.md
re-recording on the bench tier would otherwise show a removed-and-added
pair for every hinted dead pointer.

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

## The ancestry index is bounded, and a batch settles what lies past it

The review's item 4.1 named the risk correctly and the remedy wrongly. The
risk: `_ancestor_index` ran `git rev-list <ref>` and held every commit
reachable from the ref, so the cost of asking "is this commit on main" once
was the whole history, per integration ref, per worker. Measured on
2026-09-15 on this machine without a commit-graph - the state of every one of
the 195 corpus clones and of every fresh CI checkout - rust's 338,850 commits
cost 10.6 s and 77 MB held per ref per worker, tensorflow's 198,538 cost 6.8 s
and 56 MB, kubernetes' 140,768 cost 4.1 s and 38 MB. A linux-sized history
would be about 300 MB per ref per worker under the old representation, times
eight workers in a survey.

**The remedy the review proposed does not exist.** It offered `rev-list
--no-walk --stdin --not <ref>` as one spawn whose output is "proportional to
the answer", and reported having verified it. On a fixture whose answer is
known by construction - 200 commits on main, a topic branch merged by a second
parent, a side branch never merged - the call printed all five side commits
for three fed in: `--no-walk` has no effect once `--not` makes the arguments
a range, and the output with and without it is byte-identical on git 2.53.
What the call prints is the EXCLUSIVE HISTORY of the inputs, every commit
reachable from an input and not from the ref. That still settles ancestry
exactly - an input that is printed is not an ancestor, one that is not printed
is, and for a document whose claims are all true the output is empty - but
its cost is a walk, not a lookup. Git walks the ref in date order down to the
deepest input, and on rust without a commit-graph fifty inputs cost 7.9 s when
one of them sits near the root, 0.63 s when all fifty are within a thousand
first-parent commits of the tip, against 10.6 s for the whole index. On
ruff's 17,020 commits: 482 ms deep, 353 ms recent, 615 ms for the index. The
review's other half held: one input git cannot resolve fails the whole call
with exit 128 and empty stdout, a tree object on stdin does not, a shallow
boundary does but `cat-file` reports that commit `missing` first.

So replacing the index with the batch would have traded one walk per ref per
worker for a walk per rule, per document, per ref - and on this repository's
`--verify` it would have added two spawns to a budget of four, the merge and
release rules each batching against `main`, to save nothing: the history is
355 commits. Refused as pitched, on those numbers.

**What shipped instead is three pieces in refs.py, one path each.** Full-SHA
membership: `_batch_shas` keeps the full commit id `cat-file --batch-check`
already prints, the `shas` memo holds it instead of a boolean, and
`commit_id` maps any rev - an abbreviated token through that memo, a name
through the ref table - to its full id before the question is asked. The
prefix buckets and the `startswith` scan went with it, and one token has one
resolver: a SHA-shaped rev that no batch has seen goes through `cat-file`,
never through the tag table, where a tag named like a seven-character prefix
would have answered for a commit. A bounded index: `rev-list -n 50001 <ref>`,
a frozenset of full SHAs, and a flag saying whether that was the whole
history. A hit is proof either way; a miss on a complete index is a no with no
spawn. And the batch above, `_settle`, for misses on an incomplete index only,
fed full SHAs this run already resolved as commits - which is what makes the
abort unreachable by construction - issued once per rule and ref by a
`settle_ancestry` call each of the three rules makes before its judging loop,
with the answers memoised on the same scope object as the index. Should the
batch abort anyway, the repository having changed under the run, the fallback
is the one `reachable_from` has always had, a `merge-base --is-ancestor` per
commit, so the answer is the same and only the spawn count is not. The batch
is fed and read as bytes: `subprocess` in text mode writes `\r\n` on Windows,
git tolerates it, and `_batch_shas` has been relying on that tolerance without
knowing.

**The bound is fifty thousand, and the number was measured before it was
chosen.** `-n` bounds the walk linearly on rust: 20,001 commits in 0.68 s,
50,001 in 1.6 s, 100,001 in 3.1 s. The corpus median is 8,076 commits; 179 of
195 clones are under fifty thousand and pay exactly what they paid before,
one spawn per ref per run with only the argv's spelling changed; the sixteen
above pay at most 1.6 s and about 6 MB per ref per worker instead of up to
10.6 s and 77 MB. A frozenset of the seam's own lines rather than the sorted
20-byte blob that was also measured - 6.5 MB against 42 MB on rust's full
history, 321 ms against 131 to build - because the bound is what caps the
memory, and the blob's remaining 5 MB per ref per worker did not buy a custom
binary search and a test for one.

**The docstring that argued against a size switch was right, and the answer
was to exercise the path rather than to leave the walk unbounded.** "A
size-based switch would create a second path that only runs on large inputs,
which is precisely the code that never gets exercised by a test." The bound
is a module constant tests/test_ancestry_bound.py sets to one, so every rule
that asks ancestry runs past the bound on every fixture; each of the three
rules is asserted to answer identically under a bound of one, three and the
default; the mutation campaign holds anchors on both sides of it. And the
corpus gate: thirteen repositories - the nine full-blob autopsy rows, ruff,
kubernetes, kubernetes/website and this one - swept three ways, the
payload as it stood before this change, this payload at the default bound,
and this payload with the bound forced to one so that every question goes
through the batch, with byte-identical output required.

**What it costs, stated.** Above the bound, a document citing only old
commits pays the bounded build and then one deep walk per rule: on rust
without a commit-graph about 1.6 s plus 7.9 s against the old 10.6 s, roughly
even, while a document citing recent commits pays 1.6 s plus 0.63 s. The
population that asks decides which shape matters, and it was counted: across
twelve corpus repositories and 13,043 documents, four documents ask an
ancestry question at all - one in babel and three in kubernetes/website, all
release claims naming old tags - and this repository's status document asks
forty times. The zero for live claims there is structural rather than
evidence: `stale-live-claim` reads only the primary document, and no corpus
repository has one. Status documents are the population, they cite recent
commits, and they live in small histories; the bound is for the day one of
them does not.

**Two things measured here and not built.** The review's 4.2 asked for a note
when a commit-graph is absent and ancestry dominates, earned by a gap above
2x. The gap is 7.5x on the index (10.6 s to 1.4 s on rust), 27x on the batch
(7.9 s to 0.29 s) and 77x on `merge-base` (2.8 s to 36 ms); no corpus clone
has one, and git writes one only after a `gc`. Earned, and not in this
change, because the only deterministic trigger - the index came back
incomplete - is a fact of the run scope, and `report_repository_notes` prints
after that scope has closed in `run_validate`; plumbing the flag out is its
own change. And the name the batching call first had, `prefetch_ancestry`,
failed `test_no_network_shape_appears_in_the_operational_source` in the
suite: the scan that keeps `clone` out of the shallow note reads identifiers
too, and a verb that means retrieval over a network is not one this tool may
carry even as a prefix. It is `settle_ancestry`.

Still owed from before: each survey worker builds its own index (review
5.6), and `--verify` opens a scope per document so the index is rebuilt for
each (5.7) - both now bounded, neither removed.

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

## A path index, measured and refused

The review's item 3.3: replace `resolve_reference`'s filesystem walk - one
directory listing per path component, memoised on `dircache` - with one set
built from `ls-tree -r HEAD` and a case-folded map, and answer every
`dead-md-link` and `dead-path-pointer` from it. Three things were to fall
out: the case verdict identical on every platform without touching a
filesystem, a tool that works on a bare repository, and `--at <ref>`. The
cost it named: a link to a file that is present but untracked - a build
output - resolves today and would become a finding. Its deciding count:
under about 0.1% of resolved references, switch outright; higher, index as
the fast path and walk on a miss.

**The premise is wrong by two orders of magnitude.** Measured on
2026-09-15, in-process and sequential, with every binding of
`resolve_reference` wrapped in a clock: on ruff the walk costs **0.02 s of a
5.9 s sweep** - 455 calls, 164 directory listings, all memoised on the run
scope; on next.js 0.09 s of 9.0 s (1.0%, 17,242 calls, 2,520 listings); on
kubernetes/website 0.46 s of 129 s (0.4%, 134,147 calls, 10,277 listings).
The 27% the previous section attributes to `dead-md-link` is the whole
rule, and the profile puts it in `link_sites` - 0.49 s wall, called 1,301
times for 650 documents, once by `check` and once by `examined` - and in
`anchors()`'s slugging; the walk is 1% of the rule. Two prototypes stood in
for the walk on ruff, three sweeps each, medians: index-first with the real
walk on a miss, 5.91 s; index-only with a case-folded map for the spelling
verdict, 5.83 s; today, 5.90 s. Both byte-identical to today's output. A
memo of the link scan keyed on text identity saved nothing either: the
second call arrives on a different string object, and the scan is 8% of
the sweep at most.

**The count the review asked for, and why the corpus can only half answer
it.** Every reference the rules resolved during a sweep of the 152 visible
clones (the 43 held-out rows untouched), classified against `ls-tree -r
HEAD`, `ls-files` and the disk: 115,364 distinct references, 49,840
resolved, 27,710 dead, 37,814 absolute or leaving the repository. Resolved
and absent from HEAD's tree: **0 of 49,840**. Not because links to build
outputs do not exist, but because every clone is pristine - nothing built,
nothing staged - so the cost the review named cannot be seen here by
construction. What the corpus does settle: 1,175 resolved targets are
directories, every one implied by a tracked file, so an index needs the
implied directories and nothing more; 33 dead references are case
mismatches against a tracked file, the spelling verdict a folded map
reproduces; 0 resolve through a symlink or into a submodule; the index and
HEAD never disagree.

**The one real argument for an authoritative index is a verdict, not a
speed.** 1,022 of the 27,677 dead references - 3.7%, in 28 repositories -
name gitignored paths: ruff's generated `docs/settings.md` and
`docs/default-rules.md`, babel's `build/`, autogen's generated API pages.
Dead in every fresh clone and in CI, resolving on any machine that has run
the docs build: "true where you are standing is not true", inside the tool
built to catch it. An index that answers from HEAD would make those
verdicts deterministic. It would also make three other changes at once: a
tracked file the checkout could not materialise - MAX_PATH on Windows, a
sparse checkout - would become "exists" where it is "dead" today, which is
the choice `tracked_markdown` already made for documents; a target created
and staged but not yet committed would become dead at pre-commit time,
which is wrong unless the index is HEAD plus `ls-files`, a second spawn;
and none of the three can be counted on pristine clones. A changed verdict
here is admitted on a count, and this one would be argued from principle.
So it is recorded as the case for a separate proposal, with the population
that would decide it named: repositories with a docs build, measured on a
checkout that has run it.

Refused as a performance change; not built as a verdict change; the
apparatus - `m6_probe.py`, `m6_driver.py`, `m6_report.py` and `m6_timing.py` in
the extant-hardening checkout beside this one, outputs under
`D:/repo/out-pathindex/` - is what a later proposal would start from. What the profile says the link
rules actually cost - the scan and the slugging - belongs to the review's
3.1, and its premise is the same inner loop.

## One document scan, measured and refused; its bar all but met without it

The review's item 3.1, the last of its architecture proposals and the one
it called the big one: `prose()` and `strip_code()` are memoised per
document, but each of thirteen rules then runs its own `finditer` over the
result, so make ONE tokenizer pass per document produce a span table -
fence regions, inline code, line breaks, headings, link sites, backticked
tokens, bare hex runs, the newest entry's bounds - and have every rule's
`_sites()` become a filter over it; then extract every claim in every
document first and resolve once per repository. Its own bar: identical
findings on every corpus repository, and a sequential ruff sweep under
3.5 s against the 7.0 s it measured, 5.9 s by the time this was read.

**The scan side, on the clock.** The review's figures - 2.5 million
`re.Pattern.match` calls, 9.1 million Python calls - were cProfile counts
on 0.26.1, and two tranches had moved both since. Measured again on
2026-09-15 with `time.perf_counter` around every scanner, in-process and
sequential, three sweeps of ruff's 650 documents, medians, and EXCLUSIVE
of anything a scanner calls that is itself timed, so the sum counts nothing
twice (`m7_scanners.py` in the measurement tree): 5.87 s in all. The
rule-owned scans - the two SHA candidate scanners, the merge and release
claim scans, `link_sites`, the fragment, path-pointer, line-pointer and
floor scans, the pin walk, `split_entries`, `anchors()` - sum to 3.23 s,
55%, with the shared blanking another 0.52 s. That is above the 2.4 s
the bar needs, and it is not what a span table removes. A shared pass
replaces the DUPLICATE walks and the per-pass line loops; the regex work
inside each scanner still runs, once, over the same characters. The
duplicate walks are the scanners called twice per document, once by
`check` and once by `examined`, and their second call costs 0.45 s across
all of them. The nine per-line passes a document pays - `splitlines()`
plus an `enumerate` loop before any pattern runs - cost 275 ms together
(`m7_overhead.py`), so one loop in place of nine saves about 0.25 s.
**What a span table can remove is 0.7 s of the 2.4 s its bar demands.**
The second half, resolving once per repository, is already there: a
650-document sweep of ruff spawns `cat-file --batch-check` twice, for
0.056 s. And the rewrite would retarget 39 of the 246 mutation anchors,
the ones that sit inside scanner bodies. Refused on that number, the way
3.3 was.

**Where the time actually was.** The same clock, ruff, exclusive seconds:

| | s | share |
|:---|---:|---:|
| `git log --diff-filter=R`, one spawn, the rename map behind 28 repair hints | 1.37 | 23% |
| `anchors()` slugging every document's own headings, eagerly | 0.84 | 14% |
| denominators computed and discarded: the entry-scoped rules' `split_entries` twice per document, the repository rule's configuration load once per document | 0.63 | 11% |
| the path-pointer scan, a three-way alternation the pre-filter cannot derive words from, every line | 0.54 | 9% |
| the blanking, already shared | 0.52 | 9% |
| the two SHA scans, backticked 0.32 ungated and bare 0.41 gated | 0.72 | 12% |
| everything else: the remaining scans (`link_sites` 0.21, release 0.18, line pointer 0.15, fragments 0.11, merge 0.08), the other four spawns, the survey's own listing and reads | 1.25 | 21% |

None of the first four is the shape 3.1 describes. The first is git, and
on next.js it is 3.46 s of 7.8 - a single `log --diff-filter=R -n 200`
walk on a `blob:none` clone, paid only when a dead link or pointer wants
a rename hint; recorded here beside item 6.3 and left alone. The other
three are work nobody read, and one ungated scan.

**Four changes, none of them 3.1, bound at runtime over the shipped
payload first so the working tree stayed untouched, each swept byte for
byte against today's output (`m7_variants.py`):**

| | ruff | next.js |
|:---|---:|---:|
| today | 5.75 | 7.52 |
| A `dead-md-anchor` slugs its own headings on demand | 4.96 | 7.37 |
| B the sweep counts only the denominators it keeps | 5.15 | 6.86 |
| C a mandatory-literal gate on the two ungated line scans | 5.10 | 7.27 |
| D an identity memo on the two pure twice-run scanners | 5.56 | 7.44 |
| all four | 3.59 | 6.00 |

Seconds, medians of three (two for next.js), sequential and in-process.
Identical output on every row. Shipped, uninstrumented, medians of three:
**ruff 3.65 s** (spread 3.65-3.72) and **next.js 6.36 s** (6.13-6.64) -
0.15 s short of the bar 3.1 set for itself, inside the run-to-run spread
of the measurements that set it, and with 1.3 s of it being the one
`log --diff-filter=R` spawn no scan change can reach: the Python side of
the sweep went from 4.4 s to 2.3 s. next.js says the shares differ by
repository: A is worth 0.8 s where 11 documents of 650 hold a
same-document fragment, and 0.15 s where most do.

**A.** `check` computed `own = anchors(text)` before the site loop, for a
value one shape consults - a bare `#fragment` into the document - and 639
of ruff's 650 documents never reach that shape. It is a closure now,
built on first use, the shape `ambient_anchors` beside it has had since
the project-wide anchor set was made lazy for the same reason. `x in own`
is the same test wherever `own` is built.

**B.** `count_examined` computed all thirteen denominators and the sweep
kept the ones `rule_applies` allowed; on a repository with no primary
document the two entry-scoped rules' `split_entries` walk ran on every
document, twice, and `inconsistent-artifact`'s `load_config` once per
document, all of it dropped. `registry.count_examined` takes the
predicate now, as `applies`, and the sweep hands it the same
`functools.partial` of `rule_applies` it filters the answer with, so the
predicate is stated once. A skipped rule is still present at 0 - the
shape every caller reads is unchanged - and `--verify` passes nothing and
gets every count, because for an extra document it prints "examined 0"
deliberately, as a different fact from "not applicable". One consequence
named rather than discovered: a denominator that would have raised for a
skipped rule is no longer recorded in `RULE_ERRORS`, and that is right,
because the rule's `check` never ran and the record would have named the
failure of a rule that did not look.

**C.** Two per-line scans ran their patterns on every line. The
backticked-SHA scan's two patterns each carry a literal backtick, so a
line without one is skipped on the same argument the line-pointer rule
makes for its colon - checkable by reading the patterns. The path-pointer
pattern is the user's to configure, so its gate is DERIVED:
`required_literals` in `text.py`, the companion of `leading_literals`,
walks the pattern at the top level - outside every group and class,
unescaped or escaped as itself - and keeps a character only when no
quantifier follows that could make it optional and no top-level `|`
offers a match without it. Letters are refused, because the pattern
compiles `IGNORECASE`; whitespace is refused; `VERBOSE`, inline `(?x)`
included, refuses the whole pattern, because under it a space in the
source is not a literal. The default yields a backtick and nothing else; a
configured pattern offering no such character scans every line as before.
Every shape that must yield nothing is a test in
`tests/test_prefilters.py`, beside the ones for the words, and the same
file asserts on lines the default pattern matches that the gate never
refuses one.

**D.** `link_sites` and `_release_claims` were the last per-document
scanners with two readers and no memo: 1,301 calls each on 650 documents,
every second one a re-walk. Each keeps the one-entry identity memo
`find_sha_candidates` and `merge_claims` keep, with the half of the key
`_STRIPPED` is recorded as missing present - the document format beside
the text for the link scan, the pattern object beside the prose for the
release scan - and both are complete keys, so neither is in
`registry.forget_memos`. `_fragment_sites` re-walks too and is left
alone: it reads the disk, its memo would need a lifetime, and its second
walk is 0.057 s.

**The gate.** Beyond the suite, the 152 visible corpus clones swept
before and after through the shipped payload, in-process and sequential
so the header names no worker count, one output per clone, diffed byte
for byte (`m7_identity.py`, `m7_sweep_one.py`, outputs under
`D:/repo/out-identity44/`): 152 outputs compared, 0 differ. The mutation
campaign gained ten anchors, one per way a change could become a verdict
rather than a speed-up - the headings never slugged, the predicate
inverted, the predicate dropped, each gate inverted, a letter or a
quantified literal kept by the derivation, the top-level bar ignored, and
each memo's key with its second half removed - and one existing anchor on
the line A edited was retargeted; all eleven were applied to a copy and
watched turning the suite red, 12 of 12 killed with the Phase 39 anchor a
label prefix pulled in, none survived, none unapplied, in 64 minutes.

## The post-rewrite journal: the record a rebase leaves, kept

The review's item 4.7. Phase 26 established that a dead SHA is usually a
rewrite casualty and that the repository already records the mapping - for
`git filter-repo`, in `.git/filter-repo/commit-map`, which `rewrite_hint`
reads and `--sha-map` applies. A rebase or an amend renames commits the
same way and leaves no map. What it leaves is the `<old> <new>` pair per
commit that git writes to the `post-rewrite` hook's stdin and to nothing
else, byte-for-byte the commit-map's spelling - and the shipped hook drained
those into `/dev/null`, with a note in its header saying that persisting
them "would let a finding name the replacement after a rebase the way it
already does after filter-repo. Measure how often a rebase is the cause
before building either."

**The population, stated rather than measured, because no clone can show
it.** Across the 152 visible corpus clones the identity sweep prints 7,418
dead-SHA findings and 0 of them carry a rewrite hint: a clone never holds
the author's `.git/filter-repo/commit-map`, and a journal written by a hook
would live in the same place. So the count the review asked for - hint
coverage of amend and rebase casualties, "structurally zero" today - cannot
come from the corpus, and the tranche-7 handoff said so before this was
designed. Where the journal has value is the AUTHOR'S machine, and the
shape of that value is the finding the hook's own header measured on git
2.53.0: after a local rebase the old ids still resolve through the reflog,
so `dead-sha` is silent there for the 90 days a reflog entry lives, while
every clone and every CI run already sees them dead. That is the one
moment the repair is cheap, and until now nothing offered it.

**What was built, and the four things the audit settled.** The hook
appends each pair it is handed to `extant/rewrites` under the shared git
directory - beside the filter-repo map, because a rewrite belongs to the
repository and a linked worktree shares it - as the two ids only, since
git's line may carry a third field. `git.rewrite_journal_path` finds it
with a stat, like the map; `commits._read_rewrite_map` reads both records
into one mapping, so the `dead-sha` hint and `--sha-map` explain a rebase
exactly the way they explained a filter-repo, through the one lookup they
already shared. (1) *The append lives in the hook, not the installer's
shim.* The shim drained stdin and ran the hook with stdin closed, because a
long rebase left unread while a check ran would fill the pipe and block
git; it hands stdin through now, and the hook reads it FIRST, before the
guards, the interpreter search and the check, at the speed of the shell -
draining itself only where there is no hook to run. Installs made before
this keep the old shim until `tools/hooks/install` is run again, and the
CHANGELOG says so. (2) *A chain is followed to its end.* A branch rebased
twice journals `a b` then `b c`, and a hint naming `b` reads as correct
and is as dead as `a` - the wrong-SHA-worse-than-dead-SHA failure the
ambiguity rule refuses - so `_settled_value` follows the chain in the one
lookup both readers share; a chain that returns to itself, which git
cannot produce, settles nowhere and hints nothing. (3) *A disputed id
offers nothing.* An old id the map and the journal send to different
places is dropped rather than resolved by reading order, the ambiguity
rule across records. (4) *The cited-documents probe is one process.* After
the append the hook runs `git grep -l -I -F -f` over a probe file of
7-character prefixes, across every suffix the sweep reads, and prints one
note naming the documents that cite a renamed commit and the repair -
`--verify --sha-map .git/extant/rewrites` - without making it. A probe file
rather than one `-e` per pair, because a rebase of a few hundred commits
would overrun Windows's 32 KB command line; silent when nothing cites a
renamed commit, which is the ordinary rebase, because a note printed for
every rewrite is how a hook teaches its reader to stop reading it. An
amend is journaled and probed too, before the hook declines the check that
post-commit already ran: the renamed id is a fact only this hook is told.

**The gate is the fixture the design named.** A document cites a commit on
a branch; git itself fires the installed hook on `git rebase`; the journal
holds the pair; `reflog expire --expire=now --expire-unreachable=now` and
`gc --prune=now` do what a fresh clone or a later gc does for free; the
finding names the rebased id where before it said only that the commit
does not resolve. Fourteen tests, nine on the reader and five on the hook,
in `tests/test_rewrite_map.py` and `tests/test_hooks.py`; six mutation
anchors, the first this project has had on the verify hook or on the
rewrite-map reader at all - the journal never found, a chain hinted one
hop short, a disputed id resolved by order, git's third field hiding a
pair, the hook dropping what it is told, and the note printed for a
rewrite nothing cites. The journal only ever grows, at 82 bytes per
rewritten commit, and is not pruned: the id it explains may be cited for
years.

## A declared stratum, measured and refused

The review's item 4.6: ask `git check-attr` for `linguist-vendored`,
`linguist-generated` and `linguist-documentation` and let a project's own
declaration place a document in a stratum, where `strata.classify` today
infers one from the path. The review measured it thin - 51 of 2,519
documents across 10 repositories, 2%, in 2 of them - and set its bar: under
1% and concentrated in one repository is a footnote.

Counted on 2026-09-15 over the 152 visible clones (`m8_attributes.py`, two
spawns per clone through `environment()`, the tranche-7 identity sweep as
the findings): 98 track a `.gitattributes`; 12,697 of 87,191 swept
documents carry one of the attributes, in 9 repositories - and 12,326 of
those carry only `linguist-documentation`, which declares that a document
IS documentation and maps to no stratum. Declared vendored or generated:
340 documents, 304 of them `ordinary` today, 194 of them docusaurus's
`__tests__/__fixtures__` trees declared generated and 104 tabby's vendored
docs. Findings that would move: **17 of 65,360 leave `ordinary`** - 0.026%,
in three repositories, docusaurus 12, tabby 3, lean4 2 - and 5 would enter
it, all bazel's, which declares `linguist-generated=false` on paths the
regex calls generated or snapshotted. Refused on the review's own bar. The
`extant-stratum` attribute it called the better half has zero writers by
construction, and the README's rule about configuration nobody writes
applies: it ships with a skill that writes it, or not at all. Output under
`D:/repo/out-attributes/`.

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
instrument alone. All 36 are dead as stated. Of the 31 in `obra/superpowers`,
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
in the regex-hang record above, confirmed by inspection of the interpreter
rather than by measurement; and the sentence in `scope.py` that still
described `_STRIPPED` as missing the format 6.1 had given it says so no
longer.

**The gate.** Suite, five anchors written and two retargeted on the lines F
and D changed, each applied to a copy and watched turning the suite red; the
corpus identity sweep against the prediction above; the pre-push chain
against a working-tree extract with `--self-check` at 22 of 22. The
replay itself ran from a `git archive` extract of `main` at the merge, so
its numbers are the shipped mode's and not the branch's.

## The probe tranche: one batch, one scope, one list, and a matcher read against git

Tranche 11 of the internals review, 2026-09-20 and 21: the five probes Phase
45 named as "an afternoon with a number each" and nobody had taken - 4.10,
4.5, 5.9, 5.6 and 5.7. Every one was measured before anything was written,
on this machine, and the numbers decided them the way they were supposed to:
two built whole, one built by half, two refused, and a differential that
found a one-line disagreement nothing could reach and closed it anyway. The
whole tranche changes no output on the visible corpus, by construction and
by the identity gate below.

**4.10, one batch and one scope.** `--deleted-since` read each changed
document's previous version in a `git show` of its own, and the review's
decider was the spawn count. Counted on this repository before the change:
`--deleted-since v0.26.1` started TEN git processes for four changed
documents, in 543 ms - the four reads, the `diff --name-only`, one
`cat-file --batch-check`, and the ref table and the trunk `rev-list`
twice each. That second cause was not in the review. `deleted_claims`
opened no run scope, so every `validate()` it called opened a fresh one and
re-asked what the previous document's had learned: the exact deleted
`with session.run_scope():` that tests/test_spawn_budget.py pins for
`--verify`, in a mode nothing pinned. Both closed: `_documents_at` is ONE
`cat-file --batch` fed `<ref>:<path>` per line, its records paired with the
names by position rather than by parsing the echoed name out of a header
that may hold a space, and the loop sits inside one scope. After: five
processes for the same four documents in about 330 ms, five for the five of
`v0.20.0` where there were eleven, `examined` unchanged at 4 and 5. What the
batch answers with `missing` is three facts under one spelling - an absent
path, an object a `blob:none` copy does not hold, or a bad ref - and on such
a copy with `GIT_NO_LAZY_FETCH=1` the missing-object case prints exactly what
the absent-path case prints; `_listed_at`'s `ls-tree` still tells them
apart, so `MissingObject` survives the change and the partial-repository
test that found the guard's gap still passes. One answer changed on purpose:
a configured name that was a DIRECTORY at the ref used to come back from
`git show` as a tree listing and be validated as a document; the batch says
`tree`, which is not a document, and the name counts as absent then. One
capability was given up and is written in the docstring: names are fed on
lines, so a configured document name holding a newline cannot be asked -
`--batch -z` would allow it and arrived in git 2.40, against a floor of
2.31; no configuration anyone has written names such a file. A name holding
a SPACE is fine, and was not for an hour: a `missing` line echoes the name,
so `HEAD~1:docs/my doc.md missing` has four fields, and a parser counting
three from the front read it as a blob record whose size was the word
`missing` and crashed on the integer. The gap audit that closed the tranche
found it; the header is read from its end now, where the type and the size
are, with a test for the absent spaced name and one for the present one,
and an anchor. Population, stated: 0 of the 152 visible corpus clones track
an `.extant.toml`, so this repository is the only measured caller of the
mode, and the direct subprocess ledger in tests/test_scope.py stays at
eight with its eighth site renamed.

**5.7, one scope across `--verify`.** This repository's own `--verify` made
five git processes: the SHA batch, and the ref table with the trunk
`rev-list` TWICE - once for the status document and once for
tests/harnesses/README.md, which carries one release claim - because
`run_validate` opened a scope per document. The pair costs 40 and 61 ms here,
101 ms of a 700 ms run, 14 per cent of the command the post-commit hook runs
after every commit. It holds one scope across the run now, and `--sha-map`
is what decides: with a map the mode translates a document's SHAs and
writes the file back between reads, which is precisely the write a stable
scope promises does not happen, so there the scope stays per document,
opened after each rewrite, exactly as it was. Three spawns for this
repository's five documents. The budget test's invariant moved from "twice,
once per validate() + count_examined() pair" to "once per run", and its
narrative says why; a second test runs the same two-document fixture with
and without a map and asserts one table and two - the assertion the review
asked for beside the change. The shape of the regression is different now
and the test says so: a deleted outer scope shows as one table per asking
document, a deleted inner one as two per document in the arm this checkout
never takes.

**5.6, the list handed down; the rest refused.** The review measured
workers re-asking three `ls-tree` and two `log --diff-filter=R` in one
sweep. Traced here with `GIT_TRACE` over a parallel sweep of ruff's autopsy
clone - 650 documents, 8 workers, 5.1 s - the survey started ten git
processes: `ls-tree -r -z --name-only HEAD` five times (the parent's listing
and four workers re-asking through `sites.py`), the bounded rename log
three times (three workers that needed a hint), and two SHA batches. The
listing costs 46 ms there; the rename log 1,361 ms. And the parent's own
listing is taken before its scope opens, so it was memoised nowhere: on the
sequential path the first document to reach `sites.py` had the parent list
the tree a second time. Built: `run_sweep` keeps the listing it built the
survey from, seeds it into its own scope, and hands it through `initargs`
beside the config so `_worker_init` seeds each worker's; `survey()` takes
it as an optional third argument and `--introduced-since`, whose parent
lists no tree, passes nothing. It is the same list the survey was built
from, so nothing a worker reads can differ from what the parent read - the
identity gate's prediction of zero rests on that sentence. Measured on a
six-document fixture whose documents reach the project-wide anchor set:
seven listings for one parallel survey became one, two for one sequential
survey became one, both counted through `GIT_TRACE` because a worker is a
process a `subprocess.run` counter in the test cannot see. Refused with
the numbers: the rename map, because handing it down means the parent
computing it eagerly - 1,361 ms serial before the pool, on every sweep
including the ones where no worker asks - against three of eight workers
paying it lazily only when a hint is needed; and the ref table and the
trunk index, which no worker asked for on ruff at all and which would cost
28 and 337 ms eagerly to seed. Passing what the parent already has is free;
passing what it would have to go and get is not.

**4.5, the differential run, the swap refused, one line fixed.** The review
proposed `git check-ignore` as the exclusion engine and asked for a
differential first. `m11_checkignore.py` in the extant-hardening checkout
fed every tracked path of the 152 visible clones - 866,696 paths, 793,684
distinct strings, 81,424 of them documents - through `_exclusion_regex` and
through a scratch repository's `check-ignore --stdin --no-index -v
--non-matching`, one pattern at a time, with the operator's global excludes
neutralised (they had ignored `.claude/settings.local.json` under every
pattern on the first run) and `core.ignorecase` pinned false; rows under
`D:/repo/out-checkignore/`. The six shapes config.md documents and
seventeen more a skip-list is likely to be written in: zero disagreements
on documents. Five disagreements on non-document paths, all one class: a
trailing slash names a DIRECTORY in gitignore and the matcher also took a
FILE of that name - `pkg/debian/docs`, `hack/validate/vendor` and three
more Debian packaging files. `excluded_documents` could never reach the
difference, because its input is the document list and a document carries
a suffix; it is closed anyway, one line making the slash mean "something
beneath", with a unit test, an anchor, and a row in config.md's table, so
the matcher agrees with git on every shape that table claims. The review's
gap classes, confirmed with counts rather than asserted: `*.md` with
`!README.md` differs on 4,830 documents and `docs/*` with `!docs/README.md`
on 1, because the negation is a literal that matches nothing; `[Dd]ocs`
differs on 56,866 paths, `docs/[a-c]*.md` on 68, `docs/[!a-c]*.md` on 327,
because a class is a literal too. Not silently, which corrects the review's
premise: a pattern that matches nothing is named by the sweep as one, so a
user who writes `!` or `[a-z]` is told their pattern excluded nothing. A
third class the review did not name: with `core.ignorecase=true`, the
default of every Windows and macOS clone, git additionally excludes 8,508
paths under `**/test/**`, 5,143 under `*test*` and 34 under
`**/fixtures/**`; the regex answers everywhere as git answers on Linux.
Real-world use of the two missing features, the review's other count: this
repository configures no `exclude_paths`, no corpus clone tracks a
configuration, and the documented example and the apparatus's canary use
neither - 0 of the 3 patterns anyone has written. The swap is refused on
three numbers: it adds a spawn and a git dependency to a pure function for
two features 0 patterns use; it would make the skip-list follow
`core.ignorecase`, so that 8,508 documents excluded on a developer's Windows
clone would be read on Linux CI - the "true where you are standing" shape
this tool exists to catch, installed as a setting; and the matcher it would
replace has just been shown to agree with git on every documented shape.
Six rows of the differential matched nothing on either side (`docs/guide.md`,
`docs/**/fixtures`, `test/fixtures/a.md`, `a/b/c` and the two escapes) and
so decided nothing; the middle-`**` arm is exercised by `src/**/*.md` alone,
1,078 paths, exact. `!` and `[...]` would be an afternoon if a user ever
writes one; the sweep will say so when they do.

**5.9, refused.** The review asked for `-X importtime` and then for the
modes `--verify` never reaches to be imported inside the dispatch, with a
bar: `--verify` under about 50 ms of import. Whole-interpreter medians of
fifteen here: a bare interpreter 40 ms, `import extant.cli` 221 ms. The
in-process marginal cost, median of twenty fresh interpreters: the four
deferrable modes - `sweep`, `deleted_since`, `introduced_since`, `collect` -
3.65 ms; `extant.session`, which is the eager registry and its thirteen
rules, 60 ms after the standard library; the standard library the package
needs about 120 ms, of which `dataclasses` through `inspect` is 22,
`argparse` 21, `re` 17, `pathlib` 10, `subprocess` 9 and `tomllib` 7. The
only other lever is `report.py`'s `hashlib` and `urllib.parse` at 12.65 ms,
and `report` is what renders the baseline and the machine formats `--verify`
itself emits. The bar is three times further away than everything
deferrable put together, and the deferral buys 2 per cent of the import and
half a per cent of a 700 ms `--verify` - 5.1 was refused at 1.5 per cent of a
sweep, and this is smaller. Refused; the review's sentence goes here
instead of into a comment on code that did not change: "a lazily imported
rule is a missing rule" protects the registry, which must stay eager, and
says nothing about the modes, which could be deferred any afternoon the
number justified it.

**The gate.** Suite 1,322 passing and 3 skipped, eleven tests added. Ten
anchors written and five retargeted on the lines the batch, the scopes,
the seed and the matcher changed - fourteen run on one copy, 14 of 14
killed in 69 minutes, and the two on the batch header's parse, written
after that campaign had started, on a second copy of the final tree: one
killed, and one SURVIVED - the anchor that turned the header's `rsplit`
into a `split`, which the size-field guard beside it makes equivalent for
every name a `missing` line can echo. An anchor that matches without
biting is the AXIS lesson again; it was retargeted at the guard itself,
which the spaced-name test does catch, and run for real: killed. The corpus identity sweep against a stated prediction of
zero of 152 differing, because the only change a sweep runs through is
which process lists the tree: 152 compared, 0 differ. The pre-push chain
against a working-tree extract: smoke 45 clean of 47 with the two
expected flags, scenarios 213 of 213, fuzz at seed 20260824 over 35
repositories with 0 violations, `--verify` clean, `--selftest` 7 fired
and 0 silent, and `--self-check` 22 of 22 on its second run - the first refused
one of its own breakages, whose anchor at eight spaces of indentation
matched mid-line once `run_validate` put its documents under one scope
at twelve, exactly the refusal the harness's record says it makes. The measurements above were taken before any of it was
built, and the after-numbers in 4.10 and 5.7 on the same repository
afterwards.

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
consumer, 3.5, has no interpreter: CI runs 3.9 through 3.13 with the GIL
and this machine runs 3.14.3 with it; a thread pool also needs each thread
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

## The four probes: a split only the network can make, a rebase that reaches nothing, a rescue with no population, and the gate's missing listing

Tranche 14 of the internals review, 2026-09-22: the four measurements the
review's 4.9, 3.7, 4.8 and 4.11 asked for, run before anything was designed
and each deciding its item. The apparatus is the `m14_*` scripts in the
extant-hardening checkout, rows under `D:/repo/out-split`,
`D:/repo/out-impact` and `D:/repo/out-branches`; every scanner is the
tool's own (`prose()`, `_document_sha_tokens`, `branch_exists`,
`named_in_merge_history`, `strata.classify`), so "cites" and "names" mean
what the rules mean by them, and only the visible corpus rows were read.
Two items became code, one of them not the item the review named.

**4.9, the split: born false, or rotted?** The population is every
`dead-sha` and `bare-dead-sha` the shipped `--sweep` reports at HEAD on
the 17 agent and 13 autopsy clones, de-duplicated to 9 repositories that
carry any: 2,489 findings, 874 distinct (repository, token) - 1,064 in the
vendored stratum and 1,102 in the generated one, both moby's changelogs and
API documents, 320 ordinary, 3 historical. Cerene validated the instrument
first: 27 findings, 12 tokens, its commit-map settles 27 of 27 and the
introducing commit is found for 27 of 27. On the corpus the offline half
answers exactly what Stage 4's item 9 said it would: the rewrite record - the
commit-map and the post-rewrite journal, read by the tool's own reader -
settles 0 of 2,489, because both are artefacts of the machine the rewrite
ran on and a clone never carries them. What a clone CAN say is when the line
was written. `git log -S<token> -- <document>` under `environment()` found
the introducing commit for 2,488 of 2,489 (the one refusal a blob:none
clone's lazy fetch, refused rather than taken); plain first, because
`--follow` answered nothing for a token the plain walk placed, so the
rename-following pass is the fallback and never the first reading. In the
ordinary stratum 315 of the 319 dated findings were in the document's FIRST
version - written into a new file, not edited into an old one - and the
line's median age at HEAD is 637 days. The 36 tokens that resolve in a clone
with every blob are blob prefixes, which is why the rule asks
`cat-file -e <sha>^{commit}` and this probe peels the same way.

The 320 ordinary findings, read by document: 244 are transcripts of a
session's commits - aider's chat-history test fixture, 215, is aider working
on aider itself, and of its 75 distinct "Commit <id> <subject>" lines 13
subjects exist in the history under another id and 62 do not; aider's 29
website examples are sessions on scratch projects - and superpowers' 23 are
the quoted evaluation output Phase 47's hand-read named; 28 are docker
network and container ids in libnetwork's vagrant walkthrough (see the third
shape found below); 8 cite another project's commit on purpose, five of
them with that project's URL on the same line and one saying "imported
from commit"; 13 are not commits at all (a content hash repeated across
eight translations of one page, a signature scheme's name four times, a
fixture hash); and 4 findings, 3 tokens, were read by hand as this
repository's own commit that no longer resolves - goose's merge notes and
langgraph's generated threat model - with a fifth in fastapi's release
notes in the historical stratum. The network step below moved that line
in both directions: it found three more of the repository's own ids in
superpowers' plan and spec prose that the hand read had counted with the
quoted output, and it refused fastapi's. The review's dichotomy has a
third leg larger than either: a commit id that was true in ANOTHER object
store - a local session's auto-commits, an evaluation workspace, a vendored
project - and never in this one.

The split itself, made by the one instrument that can make it. GitHub's
commits API answers 200 for any commit the repository network's object
store still holds, reachable or not - verified on this repository on
2026-09-22: the tip of the local `backup/pre-rewrite-main`, unreachable from
`main` since the 2026-08-10 rewrite with no branch on GitHub holding it, is
served six weeks later, and so is its tenth ancestor; a never-existed token
answers 422; a 7-character abbreviation resolves. Limits stated: a 200 can
be a fork's commit, a 422 a commit GitHub has since collected, so each is a
lower bound. Run over the 172 distinct tokens of the ordinary and historical
strata (the 705 vendored and generated ones are other projects' changelogs
and would answer 422 for nothing), one read-only call each: **6 existed
once and 166 never did**. The 6 are exactly the class read by hand as the
repository's own - goose's merge notes citing two commits of its own July
history, langgraph's generated threat model citing the commit it was
generated at, three ids in superpowers' own plan and spec prose - every one
a commit of the repository's recent history squashed or rebased away, cited
in a document written in the same season, 2026. The 166: aider's 129 are one
session transcript kept as a test fixture whose auto-commits never reached
the remote in any form; superpowers' 16 are quoted output about another
workspace; moby's 14 are thirteen docker ids and the commit of the project
it imported a package from; ruff's 2, vitepress's 2, pytest's 1 and
goose's 1 are another project's commit or not a commit; fastapi's 1 is an
id its release notes carry that GitHub has never held. Outside the one
fixture, 6 of 43.

What that changes, and what it does not. The finding is right either way -
dead is dead, and the rule never claimed to know why. The advice is what
moves. "Keep your documents fresh" describes 6 tokens in 172, and every one
of those was a squash or a rebase, which the post-rewrite hook already
names at the moment it happens. The rest were never this repository's fact:
an agent quoting a transcript, a grader's output, another workspace's
history, into a plan that the next session reads as a claim about this one.
So the sentence the skill now carries is neither of the review's two. A
commit id is a fact about one object store; written into a document from
anywhere else it is a claim this repository can never check, and the tool
will read it as one - name where it came from, or leave it out. The
"paraphrase, never quote" constraint below is the same instruction with the
number behind it now. `--at <ref>` itself stays unbuilt: the question it
would answer is settled by the network or not at all.

**3.7, `--impact`: documents citing `HEAD~50..HEAD`.** 153 rows over the
152 visible clones and Cerene, 140 clone names, 139 repositories (SWE-agent
is cloned under two owners). "Cites" is the rules' token union resolved by
one `cat-file --batch-check`, tags peeled to their commits; the window is
`rev-list HEAD~50..HEAD`, side branches merged in it included; 7 repositories
younger than fifty first-parent commits used their whole history and are
named in the rows. **9 of 139 have one or more documents citing a commit in
the window, and the median is 0 in every group**: the agent tier 1 of 15 (a
changelog), heldout-ai 1 of 10 (agno's test logs), niche 1 of 38 (a
changelog), control 6 of 25, autopsy 0 of 13, bench 0 of 28, heldout-human
0 of 10, Cerene 0 - it cites 12 tokens and every one is dead. Of the 75
repositories carrying an agent-document signature, 6. Twelve of the
fifteen agent-tier repositories cite no SHA token in prose at all, two
cite only dead ones, and one cites live commits - in its changelog. The
second pass makes the answer robust to the fifty: 50 repositories cite any
live commit, 13,064 citations, and the smallest N at which a rebase of the
last N commits reaches one is 50 or less in 9, 200 or less in 15, 1,000 or
less in 21, median 1,789 first-parent commits (an exact index on the line,
an upper bound off it); of all 13,064 live citations 0.93 per cent sit
within 50 commits and 17.7 per cent within 1,000, median depth 4,523.
Documents cite what shipped long ago. Refused: the dead-SHA problem is a
rewrite problem, not a rebase-of-recent-work problem - the outcome the
review said was worth knowing too - and the moment a rewrite happens is
already the post-rewrite hook's, which greps every tracked document for the
old ids and names the repair.

**4.8, the rescue rate.** `unknown-branch` reads the newest entry of a
primary document, and the review's sentence about a squash merge erasing a
name describes the merge rule's deliberate silence (a missing branch plus an
integrated commit), not this rule, which fires when neither the ref table
nor the merge log holds the name. The two real status documents: this
repository's names no branch in the pattern's shape - its entries cite
pull-request numbers, and its five sites are examples in this document, the
harness README and one entry sentence - and Cerene's newest entry has one
site, rescued. The rule's population today is zero findings. The proxy, so
the number exists: every `branch_token` match in every document of 141
repositories, judged with the rule's own functions - 78 sites in 21
repositories, 32 rescued by merge history, 46 neither. The 46, read one by
one: 22 examples, templates and workflow globs; 2 vendored (one README
absorbed by kubernetes and by moby); and 22 real names in the session, test
and design documents of 6 repositories, one line saying "merged via #47" and
another "Closed PR #4 and deleted" - squash-merged then deleted, or
worktree-only. So the rescue fires on 32 of 54 real-name sites and a
`reference-transaction` journal would settle the other 22, none of which the
shipped rule reads. The structural ceiling, over the last 200 first-parent
commits of 141 repositories: integrations that leave a branch name behind
are a median 1 per cent, 64 of 129 repositories at zero (squash or rebase
only), 15 at one; the agent tier 2 per cent, 7 of 14 at zero. Refused, with
the trigger: the journal earns its place the day the rule reads standing
documents, which Phase 36 measured at 56 tokens and not one a claim, and
which this proxy measures again at 22 examples in 46.

**4.11, the pre-commit hook reads HEAD - and the gate did too.** The
experiment the review asked for, in a scratch repository: a new document
`git add`ed with a dead SHA, a tracked document edited and staged, another
edited and not staged, a fourth never added. `--sweep` reads the edits from
the working tree and cannot see the new document - its listing is HEAD's
tree, the documented decision, since an index that did not complete is
empty. `--verify`, which the pre-commit framework's bare `extant` entry runs,
reads every configured document from the working tree - staged, unstaged,
even untracked - and has no gap. `raw-lfs-blob` examined 0 with the
attributes and pointer staged and 1 once committed: HEAD by design, stays.
And `--introduced-since HEAD` dropped the staged new document and, in a
second run, an uncommitted `git mv` with an edit, printing "examined 0
changed document(s)" and "1 tracked document(s) the range did not change
were not read" of a file the range had moved. The diff named both; the mode
intersected the diff's paths with `tracked_markdown`, which is HEAD's tree,
and the new name fell out. Its own docstring said "the working tree holds
and base does not". A pull-request checkout never showed it, because there
HEAD carries every change; the gate run locally before committing a new plan
document - the agent's most common artefact - showed it every time, as a
clean run. The `--staged` mode the review floated is refused: nothing needs
the index read. The listing is fixed: the changed documents are the diff's
own `+++ b/` side, which the pathspec already restricts to the suffixes
`tracked_markdown` reads; HEAD's tree only counts what the range left alone,
minus both names of a rename, read off the `--- a/` side the same reader
now returns. Two tests red first, the staged document and the moved one.
Adopters wiring the pre-commit hook rather than the post-commit one: not
measurable - no telemetry, and one known install - and stated as such.

**Three shapes found on the way**, each with its count. First, `ed25519`
read as a bare dead SHA in 7 of the 152 visible clones (goose, deno,
kubernetes, node, unraid, PX4-Autopilot, pdns): seven characters, every one
a hex digit, a letter and a digit among them, the exact shape both shape
tests admit, and the only such word the corpus holds. Shipped as a one-word
list beside the shape, `_HEX_WORDS`, refused in both spellings; the cost is
a commit whose abbreviation is exactly that word, one in 268 million
objects; 7 identity outputs predicted to change. Second, a SHA as the link
text of a commit URL WITHOUT backticks - `[<sha>](https://github.com/<owner>/<repo>/commit/...)`,
the conventional-changelog spelling - is 1,425 of the 11,191 dead-SHA
findings in the recorded sweep (12.7 per cent; angular's absorbed zone.js
changelog 379, moby's vendored changelogs 358, node's deps 290), and 28 more
link to the repository's own URL and are real rewrite casualties. The
backticked spelling has been suppressed since the held-out narrowings (192
findings then), deliberately without comparing owners; the bare spelling is
the same shape and the same argument, one skip span in the bare scanner,
and it is recorded here rather than built because the design that was
approved said recorded. Third, a CommonMark indented code block is not
blanked by `prose()`: a five-line document proves it, the fenced token
blanked and the four-space-indented one reported. Corpus: moby 1,139
findings (its generated API documents and the vagrant walkthrough), 76
findings in 16 other repositories, and bazel's 36,321 anchors in version
snapshots. Not built here, on purpose: a four-space-indented continuation
paragraph under a list item is prose, and blanking it is the false negative
this tool refuses, so the change needs its own measurement of what it would
blank before it is a change.

**The gate, as run.** Four tests red before the code moved - the staged
document, the moved document, the hex word in both spellings, and the
control that a hex run one character longer still fires; two direct
callers of `introduced_lines` unpack its third value. Two anchors
retargeted (the listing, the unlistable-tree refusal's sentence) and three
written (the listing from HEAD's tree again, the renamed-away name counted
as unchanged, the emptied word list), each to be applied to a copy and
watched turning the suite red; 287 anchors match exactly once. The corpus
identity sweep against a stated prediction of 7 of 152 differing - the
`ed25519` clones and nothing else, because the gate's listing reaches no
clone's clean working tree - and the pre-push chain against a working-tree
extract, recorded in the Phase 51 entry with their numbers.

## The bare commit-link text: whose commit it is, and a number re-derived

The first of the two shapes Phase 51 recorded and did not build, built as
Phase 52 on 2026-09-22 - twice, because the gate on the first build put a
question the design had not asked. The shape: a SHA as the unbackticked
link text of a commit URL, `[<sha>](https://github.com/<owner>/<repo>/commit/...)`,
which is how release-please, standard-version and the changelogs they
generate write every entry. `_URL` has always skipped the hex inside the
parentheses; nothing skipped the copy before `](`, so a token the URL
beside it attributes to another repository was checked against this one.
The backticked spelling of exactly this had been suppressed since the
held-out narrowings, deliberately without comparing owners, and the first
design was the same argument in the bare spelling: one more pattern
beside `_LINKED_SHA` with the same URL tail, its whole-match span the
sixth line of the bare scanner's skip list.

**The count did not reproduce, and the reason is that it was never
persisted.** The Phase 51 record said 1,425 of the 11,191 dead-SHA
findings in the recorded sweep, naming angular, moby and node; no
apparatus script held that count - it was a pass over the sweep outputs
that was not written down. A persisted one (`m15_linktext.py` beside the
other `m14_*` scripts in the extant-hardening checkout) re-derives it by
parsing both dead-SHA kinds back out of every sweep output, reading each
finding's line from its clone, and scanning that line twice with the
tool's own scanner, with and without the new span. Population first: the
after-side of the Phase 51 sweep holds 11,142 dead-SHA occurrences, the
record's 11,191 less exactly the 49 `ed25519` sites that phase removed,
so the two passes read the same documents. Then the count: the pattern
that mirrors `_LINKED_SHA` - any host, `commit`, `commits`, `blob`,
`tree`, `pull` or `compare` - covers 2,866 findings across 15 of the 152
outputs, 2,107 once a repository that sits in two tiers is counted once:
moby's vendored google-cloud-go changelogs 754, node's node-gyp and
corepack changelogs 491, angular's absorbed zone.js changelog 424, and
kubernetes 414, absent from the record entirely - its changelogs pin
every dependency as a short SHA linking to that repository's `/tree/`
page. Restricting the pass to the record's own literal spelling, host
`github.com` and tail `/commit/`, gives moby's 358 exactly and node's 286
against a recorded 290, so the unpersisted pass took its own words
literally; under that reading the total over all 152 outputs is 1,459,
within 34 of the recorded 1,425, and the residual cannot be reconstructed
because nothing was kept.

**The gate on the first build said 29, not 15, and the miss was the
prediction's.** The identity sweep compares outputs byte for byte, and an
output carries the `examined:` denominators as well as the findings. A
bare SHA that is commit-link text and RESOLVES was examined and reported
nothing; the unconditional skip stopped examining it, so the `dead-sha`
denominator moved in every clone that holds one, dead or alive - and the
measurement had counted dead findings only. In the 15 predicted outputs
the findings removed matched the prediction exactly, output by output,
nothing was added, and nothing else moved but the denominators and the
summary lines that follow them; the other 14 outputs moved in the
`examined:` line alone. The script gained a second pass that counts every
site through the tool's own `prose()`, and it predicted 29 outputs and
18,285 sites, each output's count equal to its observed denominator drop.
That pass is what put the question: 15,419 of the 18,285 sites resolved
today - angular's changelogs 7,069 of them, lobe-chat 2,361, openfoodfacts
2,159, vitepress 1,173, axe-core 1,161, sile 862 - and a link text that
resolves in the clone is, by construction, a commit this repository has.
Live, so no finding moved; but a rewrite that kills one of them is
reported today and would not have been with the skip in, which is the
shape of the casualties below at a scale of thousands rather than tens.
The backticked skip had accepted the same exposure in 2026-08 without
measuring it, because that spelling is rare; this one is the common one.

**The decision: the URL's owner is compared with `origin`, in both
spellings.** Split the way that comparison splits them, the 18,285 sites
are 15,257 own and alive, 31 own and dead, 162 foreign and alive (a fork
or a monorepo carrying the other repository's history), 2,835 foreign and
dead, and none in a clone without an origin. So the comparison removes
exactly the 2,835 foreign findings and 162 live foreign sites, and keeps
15,288 own sites examined with their 31 casualties reported: angular 25,
helix 3, axe-core 2, lobe-chat 1 - 27 of them with the URL's full SHA
dead too, and 4 in angular's old changelog whose link text is the LAST
ten characters of a SHA that resolves, a token no abbreviation could ever
satisfy, reported today and still reported, which is the status quo
rather than a verdict this change makes. The reasoning is the tool's own
guarantee, that a rule asks only what git in this repository can settle
about this repository: the URL says which repository the commit belongs
to, `origin` says which repository this is, and when the two agree the
claim is in scope and checkable - the changelog entry whose commit a
squash or a force-push takes away is the one rotting citation the tool
exists to report, in the document type that cites commits more than any
other. When they disagree the claim is about another object store, out of
scope, and reporting it is the false positive by construction that
vendored changelogs and dependency pins produced by the thousand. The
first design's reason for not comparing - "a document does not reliably
state which repository it is in" - was true and beside the point: the
document does not, the repository does, and `dead-pinned-ref` has told a
pin aimed at us from one aimed elsewhere by exactly this comparison since
it was written. Two rules, one notion of "ours", one function.

What the comparison costs, named: a repository renamed on GitHub keeps
old links under the old name, which read as foreign and are skipped -
lost coverage, never a false positive; a clone with no origin cannot
settle "ours" and skips, the caution the unconditional version took, on 0
sites in the corpus; a fork skips upstream's links, which are upstream's
claims. The reduction is `owner/name`, so `www.github.com`,
`api.github.com/repos/...`, an SSH origin and a GitLab mirror all compare
as one repository, and GitLab's `/-/commit/` spelling is allowed for.

**How.** `own_remote` and `normalise_remote` moved from the pinned-ref
rule to `refs.py`, public because a sibling reads them now. The two
scanners take the origin as a zero-argument callable and ask it only on a
line holding one of the two shapes, never before - the same economy
`_pinned_refs` keeps by not asking on a document without a `rev:` line -
so a document with no linked commit costs no question, the spawn budget's
fixture count does not move, and a checkout whose config fast path
answers pays a 0.19 ms file read once per run. Each memo's key carries
the origin the scan compared with, or a sentinel when none was needed and
any origin hits, the discipline `_MERGE_CLAIMS` keeps for its pattern and
trunk; `_document_sha_tokens`, the batch, takes the same callable, so
what is resolved is what is examined. One helper, `_linked_spans`, serves
both spellings: the backticked skip is owner-aware now as well, or the
verdict on one claim would depend on whether the author typed backticks.

**Tests.** Ten pairs in section 3 of `tests/test_held_out_narrowings.py`,
each arm of the comparison with its control: a foreign link skipped with
`examined` at zero, so it is silent because unexamined rather than
examined and found alive; the same link naming `origin` reported, in both
spellings; an SSH origin against a `www.` URL compared as one repository;
a link with no origin to compare against skipped; link text on a page
that names no commit still reported; a bare range as link text skipped
when foreign and reported at both ends when own; the same range unlinked
reported at both ends. The mirror copy of the bare scanner compares at
two origins, None and the `o/r` the generated corpus links, with a
template for each arm - because the plan had promised the agreement test
would go red on the sixth exclusion and it was not going to: the corpus
held the backticked link template only, and this repository's documents
hold no bare commit link. Three mutation anchors: the foreign skip
deleted, the own arm skipped like a foreign one (the first design,
sneaking back), and the backticked skip forgetting whose commit it is;
four retargeted by path with the moved helpers.

**The corpus said the own arm is not a corner.** The same pass, run over
the backticked spelling that had been skipped unconditionally since
2026-08-08, found 81,166 such sites in the 152 clones: 79,978 own and
alive, 1,188 own and DEAD, 199 foreign and alive, 555 foreign and dead.
So the unconditional skip had been hiding 1,188 real rotting citations in
the corpus all along, and node alone holds 1,165 of them - its versioned
changelogs cite ten-character abbreviations, one per entry, of commits
from the io.js era that the repository's own object store no longer
has - and each is written as link text of a link to node's own commit
page, so the unconditional skip silenced every one. astro holds 23 of
the rest, in its packages' changelogs. Neither is a repository with a rewrite in its recent past;
both are what a decade of changelogs looks like. The comparison turns
them back on, and the identity gate's prediction is therefore 24 outputs
and 84,163 sites changing examined status - 2,997 foreign sites of both
spellings switched off, 81,166 own ones switched on - rather than the
2,835-in-15 the first design predicted.

**The gate, as run.** Nine tests red before the code moved - the four own
arms of the comparison in both spellings, the SSH-against-`www` reduction,
the no-origin arm, and the three the first design had written - plus the
mirror's two-origin comparison, which is red until the copy carries the
same owner test. Three anchors written and four retargeted by path with
the moved helpers. The corpus identity sweep against a stated prediction
of 24 of 152 differing: 24 differ, the predicted set exactly, none missing
and none unpredicted. 2,835 findings left, every one a bare SHA linked to
another repository's commit; 1,188 appeared, every one a backticked SHA
linked to this repository's own - node 1,165 and astro 23 - and no other
kind moved anywhere. The `examined:` denominators moved by the net of the
two directions, output by output: node's 62,479 sites changing status show
as a net of +61,497, which is 61,988 switched on less the 491 switched
off, and angular keeps 25 of its 424 because those 25 name angular's own
commits. The pre-push chain ran against a working-tree extract, and the
rebase-journal flake that had reddened CI since PR #15 was diagnosed and
fixed on the way: the fixture cited `cited[:7]`, and a seven-character
prefix that is all digits is no candidate at all, so the rule correctly
found nothing and the test read `[]` where `dead-sha` was due - 3.8 per
cent of runs, one in forty locally and about one red leg in three across
ten CI legs. `_abbrev`, written for exactly this in another file on
2026-09-13, moved to `tests/conftest.py`; 60 of 60 runs green after it,
against 1 failure in 40 before.

**Did it silence anything useful? Audited rather than asserted**
(`m15_audit.py` beside the measurement script; output beside it in the
logs). Every one of the 2,835 findings the comparison removed is read back
out of the two sweeps with its document's stratum and with the URL head
that decided it. Where they sit: 1,933 in vendored trees, 880 in
historical records, and 22 in ordinary documents - the stratum that
gates. All 22 were read by hand, and each cites another project by name in
its own prose: aider's post about a litellm commit (3, in two tiers of the
same clone), a CVE archive's "fix commit" in three upstream projects,
PX4's NuttX upgrade in three translations of one page, tensorflow's
advisory about tflite-micro, uv's vendored copy of pypa/packaging, and
helix's note that its lsp-types crate is a fork of gluon-lang's. There is
no argument for checking any of them against the repository that cites
them.

How foreign was established matters more than where the findings sat, and
it is the question the audit exists to answer: the skip could silence a
real claim only by treating "cannot tell" as foreign. In all 2,835 the
URL head parsed to a real `owner/name`; none was relative, none empty,
none in a clone without an origin. Across the whole corpus there is not
one linked-commit site whose head names no repository, and every one of
the 98,109 sites the comparison calls OURS is on the same host as the
origin it was compared with, so ignoring the host mis-attributed nothing.
891 of the removed sit under the same owner as the origin and a different
repository - `angular/angular` citing `angular/zone.js`,
`tensorflow/tensorflow` citing `tensorflow/tflite-micro` - which is a
sibling project rather than a rename; the shape a rename or fork would
take, the same repository NAME under another owner, occurs zero times. No
document's `dead-sha` denominator fell from nonzero to zero, so the rule
goes silent in no document anywhere, and three clones gained a denominator
they did not have.

The residual risks, stated because the corpus cannot close them: a
repository renamed on its host keeps old links under the old name, which
read as foreign and are skipped - lost coverage, never a false positive,
and indistinguishable from the 891 sibling-project cases above; a clone
with no origin cannot settle whose commit a link names, so both spellings
skip there, which is a loss of the bare spelling's old coverage in that
one case - the corpus holds no such clone, and the one origin-less
repository this project knows of holds 29 documents and not a single
linked-commit site, so the arm is pinned by a test rather than by a
population. And the four angular sites whose link text is the last ten
characters of a resolving SHA are still reported, as they were before:
this change neither makes nor removes them.

**Not done here, and the next measurement.** `_URL`'s hex skip is still
unconditional: `[the fix](https://github.com/<us>/commit/<sha>)`, a commit
URL of this repository with words as its link text, is not examined,
because the hex sits inside a URL. The same argument applies and the
same comparison would settle it; it is a wider verdict change - every own
commit URL in every document becomes a site - and gets its own count
before it is a change.

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
