# handoff-validator - session handoff

Entries newest first. Everything from the numbered sections down is permanent
reference and is never archived.

This file is not decoration. It is the corpus the test suite validates against,
so the tool is exercised on a real document rather than only on fixtures.

## Phase 1 - Extraction and first public release (shipped, 2026-07-22)

**Status.** Extracted from the project this was built and proven on, and made
repository-agnostic. Suite is 115 tests, of which 114 pass and one fails
deliberately: a test refuses to let the placeholder copyright holder in
LICENSE reach a public repository. The package validates its own handoff
document, which is this file.

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
- The extraction work was merged to `main` at `5577bec`.

**Known Issues.**

- `LICENSE` still carries a placeholder copyright holder. A test fails while it
  is present, deliberately. Read `PUBLISHING.md` before publishing.
- No continuous integration configuration ships, by choice rather than omission.
- Repositories using a gitflow-style release branch are not modelled. The
  ancestry checks assume a single trunk.

**Next Tasks.**

- Replace the LICENSE placeholder with a real copyright holder.
- Add a workflow running the suite on push.
- Consider a release-tag rule. The admission test it must pass is in
  `CONTRIBUTING.md`.

**Gotchas.**

- Accepting the default configuration without deriving it gives a validator that
  checks nothing, convincingly. Read `plugin/skills/handoff/references/porting.md` first.
- A rule reporting zero examined is inert, not clean. The exit code cannot tell
  you which, and that distinction is most of the point of this tool.

## 1. Layout

**Design:** `plugin/skills/handoff/references/design.md` records why each rule is scoped as it is,
with the failure that forced each decision. For every configuration key, see
`plugin/skills/handoff/references/config.md`.

The skill lives at `plugin/skills/handoff/`. Inside it, `payload/` holds the
files installed into a target repository as `tools/`, while `install.py` and
`detect.py` stay put and are never copied.

## 2. Conventions

Branches follow the pattern `feature/short-name`. Commit subjects use the
prefixes `feat:`, `fix:`, `docs:`, and `chore:`.

Two rules for anyone editing an entry above: paraphrase a past status rather
than quoting it, because no rule can distinguish a quotation from a claim; and
write a commit range as two separate backticked tokens rather than one, because
a range inside a single pair is not recognised as a reference.
