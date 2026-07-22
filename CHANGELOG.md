# Changelog

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
