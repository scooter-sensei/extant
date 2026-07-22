# Changelog

## 0.1.0 (2026-07-22)

First public release, extracted from the project it was built and proven on.

### Features

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
