# extant - session status

Entries newest first. Everything from the numbered sections down is permanent
reference and is never archived.

This file is not decoration. It is the corpus the test suite validates against,
so the tool is exercised on a real document rather than only on fixtures.

## Phase 12 - Loopholes, and eight widenings that did not survive measurement (shipped, 2026-08-02)

**Status.** Suite is 434 tests, all passing. Eleven rules, eighteen presets.
`v0.16.0` is tagged, released and on PyPI. Every release from `v0.5.0` is
tagged with no gaps.

**What shipped.**

- `--deleted-since <ref>` reports claims removed while still false. It began as
  a twelfth rule and was demoted to a non-gating report before any of it was
  written: whether a removal was evasion or repair is a question about intent,
  and the common case cuts the wrong way - deleting a false sentence makes the
  document true, so a gating rule would fail the build on the correct fix.
- A consistency block that reaches one file by two routes now asks the
  filesystem rather than comparing strings, with a realpath fallback for the
  filesystems that report `st_ino` as 0. `consistency_timeout_seconds` bounds a
  user-supplied pattern, opt-in because `re` holds the GIL and a watchdog
  thread therefore cannot work.
- Findings carry a `subject`, the bare token a claim is about. A baseline
  forgives the occurrences it recorded rather than every future copy.
- Two more generators are recognised, worth 37 false positives: a site can be a
  subdirectory of a subdirectory, and Mintlify declares itself in `mint.json`.
- Release claims are read against the conventions a project actually uses - the
  tag prefix, a version naming a series rather than a tag, an integration
  branch that is not there, and pre-commit's `rev: ''` placeholder.
- A document full of release claims is an order of magnitude faster: 22.0
  seconds to 1.25 at 400 claims. The cost was in 0.15.0 too.

**What was learned.**

- **A rule keyed on a PHRASE has a denominator of zero outside the project
  whose phrasing it came from; a rule keyed on a TOKEN SHAPE does not.** Across
  30 repositories and 3,821 markdown files, ten of them chosen for claim
  density, the merge-claim pattern matches nothing at all. What projects write
  is "commit `<sha>`", 890 times, which a shape-keyed rule already catches. All
  eight coverage widenings were rejected, and saying so is worth more than
  shipping them blind. FOUR of the eight were rejected on real numbers - the
  rules they aim at were examined 89, 1142, 2422 and 6987 times. The other four
  aim at rules examined three times or fewer, two of them never; of those, one
  is unanswerable without the network and one the design already called a
  non-loophole, so exactly TWO are blocked on a corpus that does not exist.
- Two corpora were unusable and neither said so. Clones made `--depth 1` leave
  every historical SHA unresolvable, so one repository reported 2,094 findings
  and reports 3 with its history; a partial clone fetches blobs over the
  network mid-sweep to run rename detection, and a single repository stalled
  for half an hour. More findings reads as thoroughness and no output reads as
  slowness.
- A mutation that SURVIVES can mean two mechanisms masking each other rather
  than a missing test. Two survived here; investigating showed one was
  load-bearing and the other was dead code, and the right fix was to delete the
  dead one and test the case only the survivor handles.
- Eleven unit tests could not catch a regression that `scenarios.py` caught on
  its first run. A fix derived from a corpus inherits that corpus's blind
  spots, and no repository in any of the three configures the rule in question.
- **A probe verified on one filesystem has been verified on one filesystem.**
  The `smoke` job went red on Linux and nowhere else, one commit into this
  phase: a case variant is one file on Windows and two on a case-sensitive
  filesystem, and the branch for the second outcome existed as a COMMENT
  describing it rather than as code handling it, so the probe fell through and
  declared a by-design gap. Reading the code showed the case considered, and
  considered is not handled - the same absence-is-invisible shape as a check
  that examines nothing. The run is still in this repository's history as the
  only red one on `main`; it is `7b50a67`, fixed in `81cc1c4`, and it is
  recorded here so nobody has to guess later.
- The tool failed its own build twice on this work. Writing prose to explain a
  false positive reproduced it, and the paragraph recording THAT did it again.
  A rule cannot tell a quotation from a claim - already known for live claims,
  and true of release claims for the same reason. Paraphrase.

## Phase 11 - reStructuredText, and the cost of doing the same work twice (shipped, 2026-07-29)

**Status.** Suite was 382 tests at the time, all passing. Eleven rules,
eighteen presets. `v0.15.0` was tagged and released, with every release from
`v0.5.0` tagged and no gaps.

**What shipped.**

- reStructuredText is swept. The markdown link and anchor rules are skipped
  outside markdown rather than adapted to it, because `[text](url)` in Python
  is a subscript followed by a call and numpy writes exactly that in doctests.
  The claim rules still run, with rst literal blocks and doctests treated as
  code.
- A sweep of 1600 files went from roughly 49 seconds to about 1. Two pieces of
  per-document work were being redone per file, both found by profiling rather
  than by reading: the origin lookup, which is a question about the repository
  and was asked once per document, and the five per-call caches, which a sweep
  can legitimately share because it reads one static checkout and writes
  nothing.
- The project-wide anchor union is built on demand. Eagerly it cost roughly
  400 ms per run at 1600 files on every repository carrying a `conf.py`, for
  documents whose fragments mostly resolve locally.
- `tests/test_caching.py`, and cost contracts in `mutate.py`. A change that
  alters speed and not behaviour regresses silently, so each is pinned by a
  test that was observed failing first.

**What was learned.**

- A harness measures the inputs it knows how to build. `--sweep`, generated
  sites and reStructuredText all shipped while `perf.py` and `stress.py` built
  only generator-free, markdown-only repositories, so none of the new cost was
  visible to the harness whose entire job is finding cost. Re-run those after
  changing what the code READS, not only after changing what it does.
- A stale budget is worse than none. The stress budgets were set from the slow
  numbers and left at 180s and 140s; after the speedup those runs take 33s and
  22s, so a fourfold regression would have fitted inside them unnoticed.
  Re-measure a budget when the thing it watches gets FASTER.
- Reviewing your own work is not review. This phase was self-reviewed and
  reported clean; CodeRabbit then found two real defects in it, one of which
  was a cache outliving its scope so that `dead-pinned-ref` examined nothing
  and reported clean - this project's own failure mode, aimed at itself.
- A scenario's negative assertions are satisfied by a run that never happened.
  Found once in `s25` and fixed there, then found again by review in `s24`,
  where four of eight assertions went green against an empty stdout. Prove the
  run occurred before believing anything it did not say.

## Phase 10 - Run it on somebody else's repository (shipped, 2026-07-29)

**Status.** Suite was 352 tests at the time, all passing. Eleven rules,
eighteen presets. `v0.14.1` was tagged, released, and on PyPI.

Every tag has a release page. The four that did not - `v0.13.0`, `v0.13.1`,
`v0.13.2` and `v0.14.1` - were backfilled from their changelog entries on
2026-07-29. `v0.13.1` is the odd one and its page says so at the top: the tag
exists, no `0.13.1` was ever published to PyPI, and the release gate added in
that very version is what rejected it.

The sentence here used to carry a hand-maintained list of exceptions, and it
decayed twice in the same way. First it read "each has a release page", which
stopped being true three tags later. It was then corrected to name three
exceptions, and stopped being true again when `v0.14.1` shipped without a page
and was never added. No rule can catch either: an enumeration is not a
falsifiable claim about one thing, it is a claim about everything not
mentioned.

So the list is gone rather than corrected a third time. "Every tag has a page"
is checkable by counting two sets, and it is the only form of this sentence
that does not rot.

**What Shipped.**

- `--sweep` at `32ce917`: every tracked markdown file, no configuration, two
  sections, and only the configured one decides the exit code.
- Fifteen false-positive classes across `3c86834`, `884073e`, `a5b791d`,
  `0158059`, `2694601`, `7cb4b03` and `361c1df`, each measured on real
  projects rather than imagined.
- A crash. Every mode died with UnicodeEncodeError writing a finding
  containing non-ASCII to a Windows console, and the test that should have
  caught it was setting `PYTHONIOENCODING=cp437:replace` itself.
- `dead-md-anchor` reaches fragments on other files; `.mdx` is swept; the
  sweep reads HEAD's tree rather than the index.
- `tests/harnesses/corpus.py`, where a repository that cannot be measured is a
  failure rather than an omission.

**What was learned.**

- The central claim had never been tested. Every version before this was
  validated against two repositories written by the same hand, neither of
  which links to another project's source. Pointed at 38 real projects the
  released tool cried wolf about nine times in ten.
- Reasoning about a renderer is not measuring one. Hugo's 101 dead anchors
  were recorded as an irreducible limit caused by shortcode templates; the
  cause was a definition list, visible in the file, and reading it took a
  minute. A limitation is only honest if the diagnosis behind it is.
- Widening a rule is not free even when it looks additive. Unioning anchors
  across a project fixes MyST and forgives two of httpx's three genuinely dead
  anchors, so the namespace has to follow the generator.
- Three throwaway measurement scripts were wrong in one session, each by
  omitting something silently: Git Bash paths Windows Python cannot read,
  clones that failed on MAX_PATH, a checkout that never completed. All three
  printed a confident number. That is what `corpus.py` exists to prevent.
- The audience-specific rules had never met their audience. `raw-lfs-blob` was
  first exercised on a real Unity project this phase, and five of six
  open-source game repositories use no LFS at all.

**Known Issues.**

- Every corpus repository is open source, which biases it. `raw-lfs-blob`
  could be exercised on exactly one, because private Unity and Unreal
  repositories are where game art actually lives.
- `.rst` is not read, so the Sphinx ecosystem is invisible: poetry and pytest
  report zero markdown files.
- A hex token that is really a Windows error code is indistinguishable from a
  short SHA by shape and is still reported. Writing an example of one here
  proved it: the eight-character code quoted in nlohmann/json's changelog was
  flagged as a dead commit in this very entry, so it is described rather than
  written. Inline code is deliberately not exempt from the claim rules,
  because real claims get written inside backticks.
- Detection can guess a wrong `entry_prefix` - it produced `# Boss ` on Unity's
  BossRoom - and says so as LOW CONFIDENCE rather than silently.

**Next Tasks.**

- Stop expanding the corpus. Returns flattened: the last six repositories
  yielded one new class against six from the first nine, and nine of 38 now
  report zero.
- Run a sweep on a private engine repository if one becomes available. That
  would test more than another twenty public clones.

## Phase 9 - A code review, and a way to install it (shipped, 2026-07-28)

**Status.** Suite is 308 tests, all passing. Twelve rules, eighteen presets.
`v0.12.4` is tagged, released, and on PyPI. Every release from `v0.5.0` is
tagged with no gaps, and each has a release page.

**What Shipped.**

- A CodeRabbit review of the whole repository: 35 findings, all addressed
  across `f873a79`, `e160feb` and `d220091`. One critical, ten major.
- The reload staleness class closed twice over, at `26cf385` and `5c6c96a` -
  once with a guard and once by removing the shape that allowed it.
- `v0.10.0` backfilled. It was bumped, committed and pushed without ever being
  tagged, so its own README told people to pin a version git had never heard
  of.
- Published to PyPI at `4bb25d5`, with a workflow that refuses a tag which does
  not match the packaged version, and refuses a wheel that does not work.
- The adversarial harness moved into CI at `de70943`, after being given a
  verdict it did not have. `0.12.3` carries that plus a quickstart command that
  works on a project with no configuration.
- `0.12.4` stops installing anything Claude-specific into a repository that
  shows no sign of Claude, at `a39e74f`. The slash command is the only
  tool-specific file and is now the only conditional one; the open-standard
  skill stays ungated, since that is the half that makes the install portable.

**What was learned.**

- Three guards were written for one bug before one of them was right, and the
  first two were proxies: a table that could not see a COMPUTED value, then a
  substring test that passed because `global X` mentions the name. The check
  that works compares a reloaded module against a fresh import of the same
  project, which is the invariant stated directly rather than approximated.
- That oracle catches DIVERGENCE and not ABSENCE. A global neither path sets
  agrees with itself. Knowing which failure a check cannot see matters more
  than having the check.
- The tool found a false positive in itself, then found this entry describing
  it. `release_tag` swallowed a sentence-ending full stop, so a release claim
  at the end of a sentence searched for a tag with the period attached. Every
  fixture happened to continue the sentence, so nothing caught it. Writing the
  example out here reproduced the match against this very document, which is
  the rule working: it cannot tell an illustration from a claim, and inline
  code is deliberately not exempt because claims get written inside backticks.
- Binary distribution was measured and refused. Two of three install routes
  already handle Python, the payload is standard library only, and PyInstaller
  onefile would add 100-300 ms to every commit.
- A harness can be the thing with no denominator. `smoke.py` ended in an
  unconditional `return 0`, so adding it to CI as it stood would have bought a
  job that could not fail. The fix that mattered was not the exit code but its
  second half: an EXPECTED finding that stops appearing now fails too, which
  turns a green run into evidence that probes ran.
- The first install command a reader meets was broken, and no rule here could
  have found it. It is prose about how to run a tool, and nothing in git or the
  filesystem contradicts it. Installing the released wheel and running it was
  the only thing that would have shown this, which is an argument for doing
  that at each release rather than for another rule.

**Known Issues.**

- A user-supplied regex can still hang, as recorded in the design notes.
- `README.md` is still not self-checked, so `dead-pinned-ref` never sees this
  project's own install snippet. Including it produces four false positives.
- A baseline can suppress a live credential, and one recorded finding forgives
  every future copy of itself. Both are documented in the design notes.

**Next Tasks.**

- Nothing outstanding. The next change should be driven by someone using this
  on a repository that is not this one - now that `pip install extant` is a
  thing they can do.

## Phase 8 - Five releases, and the measurements that overturned three designs (shipped, 2026-07-27)

**Status.** Suite is 305 tests, all passing. Twelve rules, eighteen presets.
`v0.12.0` is tagged and released, and nothing is unreleased on `main`.

**What Shipped.**

- Python 3.9 and 3.10 support, losing no syntax, at `e9e2c71`.
- A baseline, so a long-lived repository can adopt this without fixing every
  finding first, at `343c4b1`. Nothing is ever recorded implicitly and the
  suppressed count prints on every run.
- Eight ecosystem presets, and the four cross-checks the research explicitly
  ruled out, at `addd8c7`.
- Works with any coding agent, not only Claude Code, at `3119b9c`. Agent Skills
  is an open standard, and exactly one line of this codebase was Claude-only.
- Every harness expanded to cover the surfaces added since 0.6.0, at `233cceb`.
- Merge claims now name their own ref, so more than one integration branch
  works, at `121bbe4`. This is what closes the gitflow gap the last entry
  listed as outstanding.
- Game engines: a `raw-lfs-blob` rule and `unity` / `godot` presets, at
  `8ee2339`, released as `v0.12.0`.

**What was learned.** Measuring first repeatedly overturned the design, and in
each case below the plan would have shipped something that did nothing:

- A trunk LIST was the obvious fix for gitflow and the wrong one. A merge claim
  names its own ref, which is strictly more precise and needs no configuration.
- Widening `path_pointer` with asset extensions for game projects was measured
  as a no-op. Game documentation writes paths as markdown links, so the rule
  examines zero references either way.
- Keying the Godot version check on the README would have examined nothing
  forever. A real shipped Godot game states its engine version only in its
  setup document.

**Known Issues.**

- A user-supplied regex can still hang, as recorded in the design notes.
- `README.md` is not self-checked, so `dead-pinned-ref` never sees this
  project's own install snippet. Including it produces four false positives,
  all illustrative examples. The release procedure confirms the tag instead.
- A baseline can suppress a live credential, and one recorded finding forgives
  every future copy of itself. Both are documented in the design notes.

**Next Tasks.**

- `v0.10.0` was never tagged: the version was bumped, committed and pushed, so
  for as long as it was newest the README pinned a tag git had never heard of.
  Backfilling it would make that pin resolve.
- Nothing else outstanding. The next change should still be driven by someone
  using this on a repository that is not this one.

## Phase 7 - Published, and the install path finally walked (shipped, 2026-07-27)

**Status.** Suite is 213 tests, all passing. The repository is renamed on
GitHub, `v0.6.0` is tagged and released, and both documented install paths have
now been exercised from the published repository rather than from a local
checkout.

**What Shipped.**

- The release, and proof that the pre-commit path works: a fresh project, a real
  pre-commit run against the published tag, failing on planted problems and then
  passing once they were fixed. The second half matters as much as the first, as
  a hook that fails on everything looks identical to one that works.
- The marketplace path, exercised end to end for the first time: both manifests
  validated, the marketplace added from GitHub, the plugin installed, and the
  skill delivered with its payload on disk.
- A fix for the `readme` preset, at `4068181`, and the tests that preset never
  had.

**Known Issues.**

- Gitflow-style release branches are still not modelled.
- A user-supplied regex can still hang, as recorded in the design notes.

**Next Tasks.**

- Nothing outstanding. The next change should be driven by someone using this
  on a repository that is not this one.

**Gotchas.**

- A feature verified only where it is incidental is not verified. All five
  presets were checked by hand before 0.5.0, every one in a repository that
  already had a status document, so the preset that exists FOR projects without
  one was never run in that case. It was broken in both releases that followed.
  This is the same shape as the hooks scenario that asserted the retired
  contract: the test exercised the configuration where the feature did not
  matter.
- Installing from the published artifact found what running from a checkout
  could not. Everything passed locally, and the first genuinely new information
  came from walking in as a stranger.

## Phase 6 - Renamed to extant (shipped, 2026-07-27)

**Status.** Suite is 203 tests, all passing. Nothing about the engine changed;
every name did. The old name survives in exactly two places, both deliberate:
the CHANGELOG entry recording the rename, which cannot describe it without
naming it, and `HANDOFF.md` in the document-detection list, which is a filename
in other people's repositories rather than one of ours.

**What Shipped.**

- The rename: repository, package, command, configuration file and table, both
  pre-commit hook ids, both modules, the slash command, the `primary_doc`
  setting, and the preset that used to carry the old name and is now `status`.
- The scenario matrix runs in CI, and three more of this repository's own
  documents are checked.
- A fixture keeping this project's own configuration out of its tests, because
  listing extra documents made a temporary repository inherit them.

**Known Issues.**

- The tag and repository rename are pushed by hand, so the documented
  pre-commit path stays broken for as long as the two disagree. Verify with a
  real install rather than assuming, as with the previous release.
- Gitflow-style release branches are still not modelled.

**Next Tasks.**

- Publish a release from the new tag, and check the marketplace entry installs
  end to end. That path has never been exercised from a published repository.

**Gotchas.**

- A blanket substitution is wrong even when the total reconciles exactly. The
  count matched on the first attempt and the result was still broken: a path
  component written as a separate string literal was renamed to the prose word,
  pointing six test files at a directory that did not exist, and the TOML table
  name went the same way in three places. Identifiers and prose need different
  rules, and only a rehearsal on a throwaway clone showed which was which.
- The same substitution turned a detection candidate into a duplicate of its
  neighbour, silently halving what that list could find. A name that belongs to
  the outside world is not yours to rename, however global the rename.

## Phase 5 - Any documentation, not just a status file (shipped, 2026-07-26)

**Status.** Suite is 202 tests, all passing. The tool no longer asks a project
to keep a status document: a README, a CONTRIBUTING file and a package manifest
are enough, and that was already true before this phase changed a line of the
engine. Five presets, a published pre-commit hook, and a trunk guard that is now
opt-in.

**What Shipped.**

- Repositioning. Peer review made one point hard: most teams keep no running
  status file, so the tool looked useless to them. Testing that rather than
  accepting it showed the engine already handled an ordinary project and found
  a dead commit reference, a dead link and a version disagreement with no code
  changes at all. The barrier was the pitch, so the README, the skill manifest
  and the marketplace entry now lead with the claim-checking question. The
  audience table had been telling exactly the newly-targeted projects "probably
  not for you".
- Presets `readme`, `node`, `python`, `rust` and `status`. A preset chooses the
  documents and the shape; detection still measures trunk and branch naming,
  because a template would be guessing at those.
- A hooks manifest for the pre-commit framework, and the packaging metadata it
  needs to build an isolated environment. Verified by running the real
  framework, not by writing YAML from its documentation.
- The trunk guard became opt-in, wired only by
  `sh tools/hooks/install --with-trunk-guard`. It is the one component that can
  refuse a commit, and it arrives only when asked for.

**Known Issues.**

- No release tags exist in this repository yet, while the README, the CHANGELOG
  and the hooks manifest all pin `rev: v0.5.0` for pre-commit users. That
  instruction cannot resolve until the tag is created and pushed. The rule that
  exists for exactly this claim cannot catch it, because the snippet lives in a
  fenced block and fenced code is exempt from claim rules by design.
- Gitflow-style release branches are still not modelled.

**Next Tasks.**

- Create and push the release tag, so the documented install path resolves.
- An editor or LSP integration. Assessed and deferred: it is a second language,
  a second maintenance surface, and it wants sub-100ms incremental checking
  where a full run is about 400ms.

**Gotchas.**

- Configuration is loaded at import, relative to the file. Installed as a
  package, which the pre-commit framework does, that location is site-packages,
  so the tool must re-read settings for the repository it was pointed at.
  Otherwise the hook validates a filename that belongs to some other project and
  reports a healthy run wherever no such file exists. A test now parses the
  source for every global derived from configuration and fails if one is not
  refreshed.
- A `[extant.*]` sub-table silently discarded every top-level key. The config
  file looked configured and was not, which is this project's own failure mode
  sitting in its own loader. Both sources are merged now, and a key set in both
  places is refused rather than resolved quietly.
- Ten hook tests skip when no POSIX shell is on PATH, and the suite still prints
  green. The hooks were the part that had just changed. What surfaced it was a
  scenario harness that crashed where the unit suite had skipped: degrading
  gracefully turned a gap into silence, and crashing turned it into a report.

## Phase 4 - Files that contradict each other, and a way back to old decisions (shipped, 2026-07-26)

**Status.** Ten rules now, up from nine. The tenth compares files against each
other, which is a different question from the one this tool refuses to answer.

**What Shipped.**

- `inconsistent-artifact`, the tenth rule, and the first with repository scope.
  It exists because this project advertised version 0.1.0 in three manifests
  while the CHANGELOG documented 0.3.0, and nothing here could catch it. No rule
  inspects whether a number is correct, and that restriction stands: whether two
  files state DIFFERENT values for the same thing needs only the filesystem. Off
  unless configured, because a guessed default would accuse an innocent
  repository.
- `--search`, which returns whole entries from the live document and the archive
  together. That is the only reason it beats grep: a decision lives in a dated
  entry with its reasoning, and a matching line tells you a phrase exists rather
  than what was decided.
- `--suggest-fixes`, which emits a patch on stdout and writes nothing. It
  repoints references to files that moved, and touches only link targets and
  backticked paths rather than prose.
- A mutation-freshness check in CI, and a timing run on Linux.

**Known Issues.**

- A consistency check can name the same file by two different routes and then
  always agree with itself. The two-file minimum catches the obvious shape and
  not this one.

**Next Tasks.**

- Reach projects that keep no status document at all, which is most of them.

**Gotchas.**

- Claims live inside inline backticks, so stripping code before checking a
  document turned eight tests red at once. Fenced blocks and inline spans need
  opposite treatment: a fenced example is not a promise, while a claim is
  routinely written inside single backticks. Link rules want the opposite again.
- A rule whose configuration is read from the INSTALLED copy rather than from
  the repository under test passes everywhere and means nothing.

## Phase 3 - Machine-readable output, and a mutation campaign (shipped, 2026-07-22)

**Status.** Suite is 157 tests, all passing. Findings render as GitHub
annotations or SARIF as well as text. A mutation campaign over 31 behaviour
changes found six the suite did not notice; five were real and are now covered.

**What Shipped.**

- `--format=github` and `--format=sarif`, which are rendering of existing
  findings rather than new rules, so they add no false-positive surface.
- Findings now carry the document they came from, which the machine formats
  need and the human one never did.
- Six test gaps closed, each re-checked by re-running the mutation that
  exposed it.

**Known Issues.**

- Settings load relative to the script rather than to `--repo`, and say so.
- Gitflow-style release branches are still not modelled.

**Next Tasks.**

- `--search` over the archive, so a decision can be found after it is retired.
- Rename autofix, emitted as a patch on stdout rather than written in place.

**Gotchas.**

- A rule that reuses an existing pattern inherits its looseness without
  inheriting the gate that made it safe. `unknown-branch` reused `branch_token`,
  which `stale-live-claim` only ever reaches after a live phrase matches, and
  reported a renamed design document as a phantom branch. Found by installing
  into a foreign repository, not by any test.
- Two tests were written that a broken implementation satisfied: one asserted
  a fingerprint helper directly while the defect lived in its caller, and one
  asserted that no rule stayed silent, which a selftest incapable of reporting
  silence satisfies trivially. Assert through the real path, and assert the
  negative case as well as the positive one.
- Mutation testing found what reading could not, but only where a mutation was
  written. Six survivors from 31 attempts is a floor on the gaps, not a ceiling.

## Phase 2 - Four more rules, and a way to prove rules work (shipped, 2026-07-22)

**Status.** Nine rules now, up from five. Suite is 136 tests, all passing. CI
runs both self-checks on every push to the trunk: one asking whether this
document is clean, one asking whether the rules would notice if it were not.

**What Shipped.**

- Markdown link and heading-anchor checking, which needs no configuration
  because link syntax is fixed by the format rather than by a project's habits.
- A rule for branches git has never seen, in refs or in any merge commit.
- A rule for release-tag claims, aimed at projects that keep a CHANGELOG.
- `extra_docs`, so a CLAUDE.md or a README gets every whole-file rule. The
  entry-scoped rules are skipped there, having no entries to scope to.
- Rename hints: a dead pointer now says where git shows the file went.
- `--selftest`, which corrupts one real claim per rule and reports which rules
  noticed.

**Known Issues.**

- Settings load relative to the script rather than to `--repo`. Correct when the
  tool is installed into a repository, wrong when run from outside one, and it
  now says so on stderr instead of disagreeing quietly.
- Repositories using a gitflow-style release branch are still not modelled.

**Next Tasks.**

- Consider whether the archive document should exist from first install rather
  than first archive run.
- A `.pre-commit-hooks.yaml`, so projects already using that framework can adopt
  this by adding three lines to a file they have.

**Gotchas.**

- Measuring first changed what got built, twice. A branch rule keyed on mere
  existence would have emitted four findings and four false positives on the
  first real corpus, because merged branches get deleted. Markdown links and
  release phrases turned out to be entirely absent from the status documents
  available, and are shipped for the general documents `extra_docs` reaches.
- The `--selftest` probe for merge claims first replaced a commit with zeros,
  and reported a working rule as broken: that rule deliberately ignores claims
  whose commit does not resolve, leaving those to the reference check. A probe
  has to corrupt the thing the rule actually inspects.

## Phase 1 - Extraction and first public release (shipped, 2026-07-22)

**Status.** Extracted from the project this was built and proven on, made
repository-agnostic, and packaged as an installable Claude Code plugin. Suite
is 115 tests, all passing. The package validates its own status document,
which is this file, and CI repeats that check on every push to the trunk.

Ready to publish. Nothing is outstanding for the initial release.

**What Shipped.**

- Five validation rules, each answerable yes or no by git or the filesystem:
  dead commit references, stale live claims, false merge claims, dead path
  pointers, and credential shapes.
- Denominator reporting on every rule, so a pattern matching nothing is visibly
  different from a document with no problems.
- Configuration derived by inspecting the target repository rather than copied,
  with a confidence level per value and undetermined values commented out.
- Four extraction fixes, each a defect that was invisible until the tool was
  installed somewhere else. The slash command is rendered per repository instead
  of copied verbatim. The post-commit hook resolves the document name from
  configuration instead of hardcoding one. The pre-commit trunk guard is
  actually shipped, and reads the trunk from configuration. String literals are
  ASCII only, because an em dash in printed output killed the installer on a
  cp437 console.
- Packaging as a plugin marketplace, so installation is two commands rather than
  a clone and a manual copy. The manifest schema was derived by reading the
  plugin manifests installed on the machine this was built on rather than from
  memory, which also corrected the skill frontmatter: it declared a key used by
  2 of 134 installed skills where the conventional one is used by 32.
- Continuous integration across two operating systems and three Python
  versions, plus a job that runs the validator against this document.
- The extraction work was merged to `main` at `5577bec`.

**Known Issues.**

- Repositories using a gitflow-style release branch are not modelled. The
  ancestry checks assume a single trunk.
- The suite runs the shell hooks through a real `sh`, so those tests skip on a
  machine without one. The skip is reported rather than silent, and the
  non-shell checks still cover the same installer defect.

**Next Tasks.**

- Consider a release-tag rule. The admission test it must pass is in
  `CONTRIBUTING.md`.
- Consider whether the archive document should be created on first use rather
  than on first archive run, so a fresh install has both files present.

**Gotchas.**

- Accepting the default configuration without deriving it gives a validator that
  checks nothing, convincingly. Read `plugin/skills/extant/references/porting.md` first.
- A rule reporting zero examined is inert, not clean. The exit code cannot tell
  you which, and that distinction is most of the point of this tool.

## 1. Layout

**Design:** `plugin/skills/extant/references/design.md` records why each rule is scoped as it is,
with the failure that forced each decision. For every configuration key, see
`plugin/skills/extant/references/config.md`.

The skill lives at `plugin/skills/extant/`. Inside it, `payload/` holds the
files installed into a target repository as `tools/`, while `install.py` and
`detect.py` stay put and are never copied.

## 2. Conventions

Branches follow the pattern `feature/short-name`. Commit subjects use the
prefixes `feat:`, `fix:`, `docs:`, and `chore:`.

Two rules for anyone editing an entry above: paraphrase a past status rather
than quoting it, because no rule can distinguish a quotation from a claim; and
write a commit range as two separate backticked tokens rather than one, because
a range inside a single pair is not recognised as a reference.
