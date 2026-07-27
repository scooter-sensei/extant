# Changelog

## 0.9.0 (2026-07-27)

A baseline, so a project with years of existing prose can adopt this without a
week of archaeology first.

### The problem it solves

Point this at a ten-year-old repository and the first run reports everything at
once. That is accurate and useless: CI goes red, nobody has a week for
decade-old documentation, and the tool comes back out. Every linter that
survived enterprise adoption solved this - RuboCop's todo file, mypy's baseline,
Sonar's new-code focus - and it bites this tool harder than most, because the
pitch is "use it on the documentation you already have" and that is precisely
what has accumulated the most rot.

```console
$ extant --verify --write-baseline
recorded 47 finding(s) in .extant-baseline.json

$ extant --verify --baseline
1 new finding(s), 47 suppressed by .extant-baseline.json
```

### Three constraints, which are the actual design

A baseline is a place to hide things, and this tool's authority rests on not
hiding things. The feature is only defensible because of what stops it
loosening, so every one of these is tested and mutation-probed:

**It always states how much it is hiding.** "No findings" and "no new findings,
47 suppressed" are different facts. A baseline that concealed its own size would
be the denominator failure this project exists to surface, reintroduced by one
of its own features.

**Nothing is recorded implicitly.** `--write-baseline` is separate and
deliberate. One that rewrote itself on every run would forgive whatever it had
just found, and the check would decay to nothing while still reporting success.

**An amnesty cannot outlive its finding.** `--baseline-check` reports entries
that no longer occur, because once the claim is fixed its entry forgives
something that is not there - a stale claim, which this project is not entitled
to keep.

A missing baseline file is an error rather than an empty one: treating absence
as "suppress nothing" would turn a ratcheted run back into an ordinary one
without saying so.

### Also in this release: Python 3.9 and 3.10

RHEL 9 and Debian 11 ship Python 3.9; Ubuntu 22.04 LTS ships 3.10. Requiring
3.11 excluded all three, and measuring showed it was for exactly one import.

No syntax was given up. Every module already carries
`from __future__ import annotations`, which makes annotations strings at
runtime, so `str | None` in a signature has worked back to 3.7 the whole time.
There are no `match` statements, no runtime unions, no 3.11 stdlib names.

`tomllib` was the only real floor, and it is imported inside a try/except.
Below 3.11 the tool uses `tomli` - not a substitute parser but the SAME one,
since tomllib was adopted into the standard library from it, so a config file
is read identically on every version. With neither available the tool runs on
its defaults, because a repository with no config file never parses TOML at
all; the failure is raised only when a config file is actually found, naming
the remedy.

`pyproject` declares `tomli` conditionally, so the packaged path that
pre-commit builds from installs it automatically below 3.11 and pulls in
nothing above. The copy-the-files-in path never reads that and degrades on its
own.

Two guards keep the floor where it is claimed to be, because a support claim
decays silently: one parses every module and rejects syntax newer than 3.9, the
other asserts the `__future__` import the first one's exemption depends on. CI
runs 3.9 and 3.10 alongside 3.11, 3.12 and 3.13.

Both of the bugs found here were found by that CI and by nothing else. The
version guard referred to `ast.Match` and `ast.TryStar` by name, which do not
exist before 3.10 and 3.11 - so the check asserting 3.9 support could not run
on 3.9. And `Path.write_text(newline=...)` needs 3.10, with two of its nine
call sites in the shipped installer, so the TOOL raised TypeError on 3.9 rather
than only the suite. A guard for that existed for `read_text` and its own
docstring explained why the write side was safe, which was true when the floor
was 3.11 and stopped being true when it moved.

### Reviewable on purpose

The file is JSON, and each entry carries the path, rule and message alongside
its fingerprint. Fingerprints alone would match correctly and tell a reviewer
nothing about what a colleague just agreed to leave broken. It is a tracked
file; it belongs in review like any other change.

The fingerprint deliberately excludes the line number, which it already did for
GitHub's `partialFingerprints`. An entry therefore survives edits above it,
rather than every recorded finding becoming new the moment text shifts.

## 0.8.0 (2026-07-27)

An eleventh rule: `dead-pinned-ref`, for install snippets pinning a version that
does not exist.

### Why this one had to exist

Fenced code has always been exempt from claim rules, on the sound reasoning that
an example in a fence is not a promise. That exemption cost this project two
broken instructions:

- A README told people to pin `rev: v0.5.0` for a fortnight while the repository
  had **no tags at all**. `dead-release-tag` is the rule for exactly that claim
  and could not see it.
- A Claude Code install line named a plugin id that never existed at any point
  in this project's history.

Both sat in fenced blocks. Both were copied verbatim by anyone following the
instructions, and both failed on first use.

The distinction the exemption was missing: a fence usually holds an example, but
an **install snippet is the one block on a page a reader copies verbatim**. It
is closer to a promise than ordinary prose is.

### What it checks, and what it refuses to

`dead-pinned-ref` reads inside code blocks, fenced and indented alike, and asks
the narrowest answerable question: does the version pinned for **this**
repository resolve?

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0        # ignored: not this repository
  - repo: https://github.com/you/yours
    rev: v9.9.9        # checked: does v9.9.9 exist here?
```

That governing `repo:` line is what keeps the rule honest. A project documenting
somebody else's hook pins a tag living in somebody else's repository, and
checking it would report a finding on a line that is perfectly correct. Only
pins aimed at you are answerable, so only those are asked about. SSH and HTTPS
spellings of the same remote compare equal.

A repository with no `origin` reports **0 examined** rather than a clean run,
because without a remote there is no way to know which pins are yours.

Nothing to configure. `repo:` and `rev:` are pre-commit's fixed syntax rather
than any project's habit, which is the same reason markdown link syntax has no
setting.

### Measured first

Three pins across this corpus, in both fenced and indented blocks, all
resolving, zero false positives. The rule was written to fit that measurement
rather than to a guess about what pins look like, and the third-party case was
found by looking rather than by reasoning.

Six tests, including the two that matter most: a third-party pin must not even
be **counted** as examined, and an SSH origin must match the HTTPS URL a README
shows. A comparison done on the raw URL string passes every other test and
silently checks nothing.

It then caught this repository's own README within minutes of being written.
Bumping the documented pin to `v0.8.0` before that tag existed is precisely the
state it exists to report.

### One thing to know when you release

Between bumping the pin in your documentation and pushing the tag, your
documentation promises a version that does not exist, and this rule will say so.
That is the rule working rather than misfiring: during that window anyone
reading your repository is given an instruction that fails.

If your README is in `extra_docs`, either tag as part of the release or bump the
pin after tagging. The window is real either way; the only question is whether
anything tells you about it.

## 0.7.0 (2026-07-27)

Three more presets, for audiences whose documentation ages hardest.

| Preset | For |
|:---|:---|
| `enterprise` | long-lived projects. Also checks `SECURITY.md`, `SUPPORT.md`, `UPGRADING.md`, `MIGRATION.md` |
| `ml` | data and model projects. Also checks `MODEL_CARD.md` and `DATA_CARD.md`, and that `pyproject.toml` and `environment.yml` pin the same Python |
| `legacy-web` | older web apps. Also checks `INSTALL.md`, `DEPLOY.md`, `UPGRADING.md`, and that `.nvmrc` and `package.json` agree on Node |

### What shaped them

All three lean on **extra documents** rather than on clever patterns. A support
policy, an upgrade guide and a deployment note are where a project's oldest
links and file pointers live, and age is the entire subject here. An LTS project
does not usually have a stale README; it has a `MIGRATION.md` last edited in
2021 pointing at three files that have since moved.

Their consistency checks compare **two machine-readable files**, never prose
against a manifest. Every existing check does the same, and it is why none has
produced a false positive: a JSON version field has one spelling, whereas a
sentence naming a version has as many spellings as it has had authors.

Each check is also a **pair**. A check is only emitted when every file it names
is present, so a third file makes it likelier to be skipped than to catch
anything.

`enterprise` carries no consistency check at all, deliberately. It names an
audience rather than a language, so there is no manifest common to its members,
and a guessed pair would be skipped on most repositories and wrong on the rest.

### Verified

Every pattern was run against real-format samples before shipping, because a
pattern that matches nothing is the failure this project exists to surface: all
eight captured the value they were aimed at.

Both new consistency checks are then tested in both directions - agreeing files
must pass, and one edited file must produce a finding that names the check. A
one-directional test would be satisfied by a pattern that matches nothing.
Proved by breaking the `.nvmrc` pattern and watching it fail, which it did
twice over: the test caught it, and the tool independently reported the pattern
as matching nothing.

### Fixed

- `/plugin install status@extant` in the README and the 0.1.0 entry, a casualty
  of the 0.6.0 rename's catch-all rule. The correct command is
  `/plugin install extant@extant`, and the wrong one was never right at any
  point in this project's history. It sat inside a fenced code block, where no
  rule here can see it.

## 0.6.1 (2026-07-27)

Fixes the `readme` preset, which did not work on the projects it exists for.

### The bug

```
install.py --repo . --preset readme
-> "no status document found in the usual places"   exit 1
```

The preset names `README.md`, which is not one of the status-document names
detection looks for. Detection found nothing and the installer exited **before
the preset was ever consulted**, so a preset documented as "no status file
needed" refused to run without one. Passing `--doc README.md` alongside it
worked, which is what made the cause visible.

### A second defect underneath it

Folding the preset in after detection was wrong even when detection succeeded.
Everything else is derived FROM the chosen document: the archive is placed
beside it, and the recorded evidence quotes its length. Switching the document
afterwards left those describing the previous file, so a repository with
`docs/NEXT_SESSION.md` could end up with `primary_doc = README.md` at the root
while the archive stayed in `docs/`, beside a document no longer being checked.

The document is now settled before anything derives from it.

### Which wins

An explicit preset outranks detection for the **document**. That is not in
tension with the existing rule that a preset never overrides something
MEASURED: that rule is about the trunk name and branch shape, which the
repository owns and a template would only be guessing at. Which file to check
is the user's call, made by passing the flag.

### Why it shipped

Presets had no tests. All five were checked by hand before 0.5.0, every one of
them in a repository that already had a detectable status document - so the
preset whose entire purpose is a project *without* one was never exercised in
the only situation it exists for.

`tests/test_install_presets.py` now runs the installer as a subprocess, because
the exit code and the file it leaves behind are the contract, and pins seven
behaviours including the no-document case and the archive following the chosen
document. Four of them were watched failing with the fix removed.

Found by installing 0.6.0 from the published marketplace and running it the way
a new user would, which was the first time that path had been exercised.

## 0.6.0 (2026-07-27)

Renamed to **extant**. No behaviour changed; every name did.

### Why

"Handoff" named one half of the tool, and after 0.5.0 it was the minority half.
The engine had always worked on an ordinary README and a package manifest, but
anyone arriving at a project called `handoff-validator` reasonably concluded it
wanted a ceremony they do not perform. The name was the last stale claim in a
repository built to find stale claims.

**extant** *(adj.)* - still in existence; surviving. Six of the ten rules ask
exactly that: does this commit, branch, tag, file, or heading still exist? It is
also a word that already belongs to documents, and it promises nothing about
truth, which matters because this tool refuses to judge whether a value is
correct.

### What changed

| | Before | After |
|:---|:---|:---|
| repository, package | `handoff-validator` | `extant` |
| command | `handoff-validate` | `extant` |
| configuration file | `.handoff.toml` | `.extant.toml` |
| configuration table | `[handoff]` | `[extant]` |
| pre-commit hook ids | `handoff`, `handoff-annotate` | `extant`, `extant-annotate` |
| modules | `handoff_collect`, `handoff_config` | `extant_collect`, `extant_config` |
| slash command | `/handoff` | `/extant` |
| primary document setting | `handoff_doc` | `primary_doc` |
| preset for status projects | `handoff` | `status` |

This is a breaking change for anyone who installed 0.5.0: the configuration
file, its table name, one setting, and both hook ids are different. It is made
now precisely because the audience for whom it breaks is small, and it will only
ever grow.

### One word deliberately kept

`HANDOFF.md` survives, in the document-detection list and in the fixtures that
stand in for a user's file. It is not this project's name; it is a filename the
tool LOOKS FOR in other people's repositories. Renaming it would not have
rebranded anything, and a blanket substitution first turned the candidate list
into two identical entries, which is a detection bug wearing a rename's clothes.

### How it was done

746 occurrences across 38 of 41 files, as an ordered substitution with the
most specific rules first, so that a bare `handoff` rule could not eat
`handoff_collect` and leave `extant_collect` unreachable. Every rule reported
its own count, and the total reconciled against an independent count of the
three case variants: 735 replaced plus 11 protected equals 746, with nothing
unaccounted for.

Rehearsed on a throwaway clone before the real tree was touched. That rehearsal
earned its keep: the first attempt renamed a path component written as a
separate string literal, pointed six test files at a directory that did not
exist, and renamed the TOML table to the wrong word in three places.

## 0.5.0 (2026-07-26)

Repositioned, plus presets and a pre-commit hook. The engine barely changed;
what changed is who can use it.

### It never needed a status document

Peer review landed on one point hard: most teams keep no running status file, so
the tool looked useless to them. Testing that claim rather than accepting it
showed the engine already handled an ordinary project - a README, a
package.json, a CONTRIBUTING file - and found a dead commit reference, a dead
link and a Node version disagreement with no code changes at all.

So the barrier was the pitch, not the engine. The README, SKILL.md and
marketplace entry now lead with "your documentation makes claims; this checks
whether they are still true". Status documents are one shape rather than the
price of entry.

The audience table said "probably not for you" to exactly the projects now being
targeted, which is the sort of stale claim this tool exists to catch.

### Presets

    python install.py --repo . --preset readme

`readme`, `node`, `python`, `rust` and `status`. A preset chooses the documents
and the shape; detection still supplies trunk, branch naming and commit
conventions, because those are measured and a template would be a guess.

Checks whose files are absent are skipped and reported, so a preset never opens
by complaining about a file you do not have - a tool whose first act is a false
positive has taught a lesson that is very hard to unteach.

### pre-commit framework

    repos:
      - repo: https://github.com/scooter-sensei/extant
        rev: v0.9.0
        hooks:
          - id: extant

Runs on every commit regardless of which files changed, deliberately: merging a
branch can falsify a sentence without editing a line of prose.

Verified against the real framework rather than written from the documentation.
It built its environment from the repository, read the consumer's config,
validated that project's README rather than a default filename, failed on the
rotted version and passed once the docs were fixed.

That last part needed a real fix. Configuration is read at import relative to
the file, which under pip is site-packages - so the hook would have validated
NEXT_SESSION.md in every project on earth and reported a healthy run for the
ones with no such file. `reload_config` re-reads for the repository being
checked, and a test parses `extant_collect.py` for every `NAME = CONFIG.field`
assignment and fails if one is not reloaded, so a future derived global cannot
quietly keep a stale value.

### Fixed

- The installer emitted `plans_dir = ` with nothing after it when a preset
  switched a feature off. That is not valid TOML, so the installer wrote a file
  the tool then refused to read. An installer that emits a broken config is
  worse than one that emits none.
- `pyproject.toml` exists now, for one reason: pre-commit builds an isolated
  environment and `language: python` needs something installable. Copying files
  into the target repository remains the primary install path, because the hooks
  and slash command have to live there.

### What the pre-release audit changed

All five harnesses were run before tagging. One assertion was genuinely wrong,
and the documentation had drifted in four places.

The hooks scenario asserted that a default install wires a `pre-commit` hook,
which was the contract before the trunk guard became opt-in. The product was
right and the assertion was for the retired shape. Passing the new flag would
have left the DEFAULT untested, which is the half that matters: a documentation
checker silently regaining the power to refuse a commit is the worse failure.
Both directions are asserted now, plus a misspelled flag, which must be refused
rather than quietly installing the advisory set.

That failure only surfaced because a POSIX shell was on PATH. Without one, ten
hook tests skip and the suite still prints green - and the hooks were the part
that had just changed. The unit suite degraded into silence where the scenario
harness crashed, which is the whole argument for keeping both.

A third ASCII test now reads every shipped file whole. The existing two
tokenize Python string literals and read the shell hooks, so neither had ever
opened a markdown file, and prose is where an em dash actually arrives. It is
allowlist-free deliberately: an extension filter is how such a check quietly
stops covering things, which it proved by catching a hand-written scan of my own
that had skipped the three extensionless hooks.

Corrected, none of it catchable by any rule here, because no rule inspects a
number:

- This repository's own status document stopped at Phase 3. Its "Next Tasks"
  listed `--search` and rename autofix, both of which 0.4.0 delivered, and its
  "Known Issues" listed the settings-loading bug that this release fixed.
- `references/config.md` documented every setting except the consistency block,
  the one configuration feature 0.4.0 added. It now covers that, the merge of
  top-level and `[extant]` keys, and the upward search stopping at the
  repository root.
- `CONTRIBUTING.md` named two further audit harnesses beyond the mutation
  campaign where there are four, and described the ASCII rule as applying to
  string literals only.
- The harness README claimed nine stress cases for a run of twelve, and
  `scenarios.py` printed its own denominator as a hardcoded string.

## 0.4.0 (2026-07-26)

Five additions, one of which exists because this project shipped the bug it
catches.

### `inconsistent-artifact`: files that contradict each other

Three manifests advertised version 0.1.0 while the CHANGELOG documented 0.3.0.
Anyone installing was told they were getting the first release, and nothing here
could catch it because no rule inspects numbers.

That restriction stands and this does not weaken it. The forbidden question is
whether a value is CORRECT - "the suite was 2238" has nothing to be checked
against. Whether two files in the repository state different values for the same
thing has a definite answer needing only the filesystem.

    [extant.consistency.version]
    "package.json" = '"version":\s*"([^"]+)"'
    "CHANGELOG.md" = '^## (\d+\.\d+\.\d+)'

Off unless configured, because the files and patterns are per-project and a
guessed default would accuse an innocent repository. A check listing one file is
rejected at load: it could only agree with itself. So is a pattern with no
capture group, which would have nothing to compare. A pattern that matches
nothing is reported rather than passing quietly.

It is the first rule with `scope = "repository"`. It reads no document, so it
runs once on the primary pass rather than repeating the same disagreement for
the archive and every extra document, and its configuration comes from the
repository being checked rather than from the installed copy.

### `--search`: find a decision after it was archived

    python tools/extant_collect.py --search "checkout"

Searches the live document and the archive together, and returns whole ENTRIES
rather than matching lines. That is the only reason it beats grep: a decision
lives in a dated entry with its reasoning, and a line from the middle tells you
a phrase exists rather than what was decided.

### `--suggest-fixes`: a patch, never an edit

Prints a unified diff repointing references at files git recorded as renamed.
It writes nothing, and stdout carries only the patch, so it pipes into
`git apply`.

This tool's authority rests on checking claims and never writing them. A
validator that edits prose can be wrong in a new way - it can author a falsehood
itself - and nothing would be left to catch that. Only recorded renames are
offered; a merely missing file gets no suggestion, because guessing where it
went is exactly the authoring this refuses to do.

Replacement is confined to where a path is USED as a reference. A bare
find-and-replace would also rewrite the sentence explaining the move, which is
often the one a reader most needs intact.

### `mutate.py --check-only`: catch mutation rot in CI

Sub-second, because it runs no tests: it asks only whether every mutation still
matches the code it names. Mutations rot alongside that code - one silently
stopped probing anything when ancestry moved to a batched rev-list, and it went
unnoticed until the next half-hour campaign. Now in CI, so the rot is caught by
the commit that causes it. It caught one during this very release.

### Linux timing in CI

Every performance number in these docs was measured on Windows, and the docs
said so rather than claiming a figure never taken. CI now measures `--verify` on
Linux and prints it as an annotation, so the claim has evidence on the platform
most people run this on.

### Fixed

- Configuration is now found by searching upward from the script to the
  repository root, stopping at `.git`. Looking only beside the script meant this
  project could not configure its own tool: CI invokes it from inside `plugin/`,
  found nothing, and reported a healthy run against default settings. The bound
  prevents a nested checkout from inheriting an outer project's config.
- The "settings came from elsewhere" warning compared paths as strings and could
  report that the file it had just read was not read.

## 0.3.0 (2026-07-22)

### Fixed: one rule was 98 percent of validation time

`false-merge-claim` spawned two git subprocesses per mention. On a 4000-line
document that was 17.7 of 18.0 seconds. `dead-sha` handled identical volume in
0.064s, because it batched existence checks through `git cat-file --batch-check`
- the optimisation existed and had simply never been carried across.

Existence now uses the same batched path, and ancestry is asked once per
DISTINCT commit rather than once per mention, since documents repeat the same
SHA constantly. Scoped to a single call rather than memoised across the process:
git state changes between runs, and a cache outliving the run would answer from
a repository that no longer exists in that shape.

| document | before | after |
|---|---|---|
| 4,000 lines | 16.69s | 0.77s |
| 16,000 lines | 66.68s | 1.59s |
| 2,000 distinct merge claims | 104.8s | 2.1s |

The third row came from a stress case aimed at the fix above: deduplicating by commit buys nothing when every claim names a different
one. Ancestry now comes from a single `git rev-list` rather than one
`merge-base` per commit. Measured on 5000 commits, rev-list costs 125ms
against roughly 100ms for a single merge-base, so the batch pays for
itself at two distinct commits and is used unconditionally: a
size-based switch would create a second path that only runs on large
inputs, which is the code that never gets tested.

A profile of the remaining time found two pieces of duplicated work rather
than any algorithmic problem: nine rules each stripped the same document
independently (1.22 of 6.4 seconds producing nine identical copies), and the
case check listed a directory per path component with no cache (0.88 seconds
across 3000 links). Both are now reused, taking a 5.5 MB document from 5.0s to
4.1s and 3000 deep links from 3.0s to 0.7s.

The two caches are scoped differently on purpose. The stripped text is keyed on
object IDENTITY, so it needs no lifecycle: every rule in one validate() sees the
same object, and anything else misses. Directory listings cannot use that trick,
so they are cached ONLY while validate() has scoped them and are off by default
- a caller that creates a file between two direct checks must see the new
answer. Peak memory rose from 3.1x to 3.9x the document size, which is the
honest price of holding one stripped copy.

Scaling went from linear to sub-linear. The git hooks also now get three paths
from one `git rev-parse` instead of three, saving about 170ms per commit on
Windows, where each subprocess costs roughly 90ms.

A test counts git invocations rather than seconds: a wall-clock assertion would
be flaky on a loaded machine and would not say why it got slow.

### Fixed: a file path reported as a phantom branch

`unknown-branch` reported `docs/arch.md` as "a branch that does not exist and
appears in no merge commit". A branch token and a file path are the same shape,
and the installer's fallback pattern for a repository with no dominant branch
prefix matches both.

It stayed invisible while that pattern fed only `stale-live-claim`, which gates
on a live phrase appearing in the same entry first. `unknown-branch` has no such
gate and inherited the looseness. Both rules now decline a token better
explained as a file, and the denominator counts what the rules inspect rather
than what the pattern matched.

Found by installing into a foreign repository and reading the output, not by any
test. It is the exact failure the path-pointer rule was designed around years of
this project's own advice ago, reintroduced by a new rule that reused an old
pattern without re-reading why the pattern was safe where it already lived.

### Added

- **`--format=github`** emits GitHub Actions annotations, so a false claim is
  highlighted on its own line in the pull request diff rather than sitting in a
  log. Runs on this repository's own document on every push.
- **`--format=sarif`** emits SARIF 2.1.0, the format code-scanning tools
  exchange. Rule descriptors are generated from the registry, so a rule's
  `falsifiable` question becomes its published description: a rule cannot reach
  this output without having stated the exact question it asks.

Neither adds a rule or a false-positive surface. Both are rendering of findings
that already existed, which is why they came first out of the improvement list.

### Notes on the details that are easy to get silently wrong

- Annotation properties escape `,` and `:`, and messages escape newlines. A raw
  comma in a path truncates the workflow command and the annotation lands
  nowhere, with no error.
- In SARIF mode every human diagnostic moves to stderr. The denominator summary
  is useful and is not JSON; leaving it on stdout makes the document unparseable
  at the far end, long after the run.
- `partialFingerprints` deliberately EXCLUDE the line number, so a finding that
  moves keeps its identity instead of being re-reported as new.
- Findings now carry the document they came from. The file previously existed
  only inside the print statement that rendered it, which was enough for a
  human and not enough for a machine.

## 0.2.0 (2026-07-22)

Four new rules, a way to prove any rule actually works, and checking that
reaches beyond the one status document.

### Added

- **Markdown link and anchor checking.** `[text](docs/gone.md)` and
  `[jump](#no-such-heading)` were both invisible: the path rule only sees
  backticked paths after an operative marker. Link syntax is fixed by the
  format, so unlike the prose patterns these need no configuration.
- **`unknown-branch`.** A branch named in the newest entry that git has never
  seen, in refs or in any merge commit.
- **`dead-release-tag`.** "Released in v2.1" where no such tag exists, or it is
  not an ancestor of trunk. For CHANGELOG-keeping projects.
- **`extra_docs`.** Further documents get every whole-file rule: `CLAUDE.md`,
  `AGENTS.md`, a README. Entry-scoped rules are skipped, because those files
  have no dated entries.
- **Rename hints.** A dead pointer now says where git shows the file went.
- **`--selftest`.** Corrupts one real claim per rule and reports which rules
  noticed. Probes mutate actual prose rather than injecting invented text, so
  what is exercised is your configuration against your writing. CI runs it here
  on every push, so the rules are watched failing rather than assumed to work.

### Measured before building, and it changed the plan

- A branch-existence rule keyed on "does this branch exist" would have produced
  **four findings and four false positives** on the first corpus it was measured
  against: every branch named there had been merged and then deleted, which is
  ordinary hygiene. All four were still named in merge commits, and that is what
  the shipped rule keys on.
- Markdown links and release phrases were measured as **entirely absent** from
  the status documents available. They are shipped because they are common in
  the general documentation `extra_docs` now reaches, and their denominators
  report 0 honestly where they do not apply.

### Fixed

- `--repo` now warns when it is pointed at a repository whose `.extant.toml`
  is being ignored. Configuration loads relative to the script, which is right
  when installed but silently wrong when run from elsewhere.

## 0.1.0 (2026-07-22)

First public release, extracted from the project it was built and proven on.

### Features

- Installable as a Claude Code plugin: the repository is its own marketplace,
  so `/plugin marketplace add scooter-sensei/extant` followed by
  `/plugin install extant@extant` is the whole setup. The validator,
  the hooks, and the CLI still work standalone with no Claude Code involved.
- Five validation rules, each falsifiable against git or the filesystem: dead
  commit references (backticked and bare), stale live claims, false merge
  claims, dead path pointers, and credential shapes.
- `--verify` and `--validate` report the **denominator** for every rule, so a
  pattern that matches nothing is visibly different from a clean document.
- `--collect` gathers facts into a JSON bundle: commits since the last status
  grouped by phase or ticket, changed files, TODO markers, suite result, and
  plan checkbox state. Records whether a suite figure was measured or supplied.
- `--archive` rotates old entries into an archive document, asserting multiset
  line conservation against the raw file bytes.
- `--sha-map` repairs dead commit references after a `git filter-repo` rewrite.
- Configuration is **derived by inspecting the target repository**, with a
  confidence level per value. Undetermined values are written commented out
  rather than guessed.
- Works with any language: `suite_command` takes any test runner, and
  `--suite-json` accepts a result from CI instead.
- Git hooks for `post-commit`, `post-merge`, and an optional `pre-commit`
  trunk guard.
- Optional Claude Code `/extant` slash command, rendered per repository.

### Changes made during extraction

These were defects in the original that only became visible when the tool was
installed somewhere else. All are fixed here.

- The slash command was copied verbatim, so every installation named the source
  project, wrote to that project's document paths, and carried its test counts.
  It is now a template rendered per repository.
- The post-commit hook guarded its work with a hardcoded document name while
  the validator it invoked read the configured one. Any repository using a
  different name installed the hook cleanly and validated nothing, silently. It
  now resolves the name from configuration, and distinguishes "no document
  configured" from "the configured document is missing".
- The pre-commit trunk guard was wired by the hook installer but never shipped
  by the file installer, so it never ran. It is now shipped, and reads the trunk
  from configuration rather than assuming `main`.
- String literals are ASCII only. An em dash in printed output raises
  `UnicodeEncodeError` on a cp437 console and killed the installer partway
  through, after it had already copied files.
