# Changelog

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

`readme`, `node`, `python`, `rust` and `handoff`. A preset chooses the documents
and the shape; detection still supplies trunk, branch naming and commit
conventions, because those are measured and a template would be a guess.

Checks whose files are absent are skipped and reported, so a preset never opens
by complaining about a file you do not have - a tool whose first act is a false
positive has taught a lesson that is very hard to unteach.

### pre-commit framework

    repos:
      - repo: https://github.com/scooter-sensei/handoff-validator
        rev: v0.5.0
        hooks:
          - id: handoff

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
checked, and a test parses this file for every `NAME = CONFIG.field` assignment
and fails if one is not reloaded, so a future derived global cannot quietly keep
a stale value.

### Fixed

- The installer emitted `plans_dir = ` with nothing after it when a preset
  switched a feature off. That is not valid TOML, so the installer wrote a file
  the tool then refused to read. An installer that emits a broken config is
  worse than one that emits none.
- `pyproject.toml` exists now, for one reason: pre-commit builds an isolated
  environment and `language: python` needs something installable. Copying files
  into the target repository remains the primary install path, because the hooks
  and slash command have to live there.

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

    [handoff.consistency.version]
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

    python tools/handoff_collect.py --search "checkout"

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
  the handoff documents available. They are shipped because they are common in
  the general documentation `extra_docs` now reaches, and their denominators
  report 0 honestly where they do not apply.

### Fixed

- `--repo` now warns when it is pointed at a repository whose `.handoff.toml`
  is being ignored. Configuration loads relative to the script, which is right
  when installed but silently wrong when run from elsewhere.

## 0.1.0 (2026-07-22)

First public release, extracted from the project it was built and proven on.

### Features

- Installable as a Claude Code plugin: the repository is its own marketplace,
  so `/plugin marketplace add scooter-sensei/handoff-validator` followed by
  `/plugin install handoff@handoff-validator` is the whole setup. The validator,
  the hooks, and the CLI still work standalone with no Claude Code involved.
- Five validation rules, each falsifiable against git or the filesystem: dead
  commit references (backticked and bare), stale live claims, false merge
  claims, dead path pointers, and credential shapes.
- `--verify` and `--validate` report the **denominator** for every rule, so a
  pattern that matches nothing is visibly different from a clean document.
- `--collect` gathers facts into a JSON bundle: commits since the last handoff
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
- Optional Claude Code `/handoff` slash command, rendered per repository.

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
