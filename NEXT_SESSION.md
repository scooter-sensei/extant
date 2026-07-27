# extant - session status

Entries newest first. Everything from the numbered sections down is permanent
reference and is never archived.

This file is not decoration. It is the corpus the test suite validates against,
so the tool is exercised on a real document rather than only on fixtures.

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
