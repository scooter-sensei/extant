# `.handoff.toml` reference

Lives at the repo root. Every key is optional; omitted keys fall back to
defaults that reproduce the source project's behaviour. Keys may sit under a
`[handoff]` table or at the top level.

```toml
[handoff]
handoff_doc = "NEXT_SESSION.md"
trunk = "main"
entry_prefix = "## Phase "
```

An unknown key is **reported as a warning**, not silently ignored - a typo that
quietly does nothing is the same class of failure as a pattern that matches
nothing.

## Documents and layout

| Key | Default | Notes |
|---|---|---|
| `handoff_doc` | `NEXT_SESSION.md` | The document sessions read as ground truth. |
| `archive_doc` | `docs/handoff-archive.md` | Where retired entries go. Validated too. |
| `retain_entries` | `3` | Entries kept in the live document. |
| `plans_dir` | `docs/superpowers/plans` | Scanned for the current plan's checkboxes. |
| `venv_python` | `.venv/Scripts/python.exe` | Interpreter, relative to the main working tree. |
| `extra_docs` | *(empty)* | Further documents to check: `CLAUDE.md`, `AGENTS.md`, a README. They get every whole-file rule. The entry-scoped rules are skipped, because these have no dated entries and "the newest entry" would name nothing. |

## Running the suite - any ecosystem

`{python}` is replaced with the resolved interpreter. **A command that does not
mention it needs no Python at all**, which is how a non-Python project uses the
measured path.

```toml
suite_command = ["npm", "test"]          # jest / vitest
suite_passed  = '(\d+) passed'
suite_failed  = '(\d+) failed'
```

| Runner | Output it prints | Default patterns work? |
|---|---|---|
| pytest | `2365 passed in 173s` | yes |
| jest / vitest | `Tests: 3 failed, 12 passed, 15 total` | yes |
| cargo test | `test result: ok. 12 passed; 0 failed` | yes |
| dotnet test | `Passed! - Failed: 0, Passed: 25` | needs `'Passed: (\d+)'` |
| go test | prints no totals | **no - use `--suite-json`**, or gotestsum |

`--suite-json` always works and needs no runner at all: supply
`{"passed": N, "failed": N, "duration_s": N}` from CI or a script.

## Switching workflow features off

Three keys accept an empty value to mean **disabled**, rather than falling back
to a default:

```toml
phase_task = ''     # no phase or ticket cadence in commit subjects
phase_bare = ''
plans_dir  = ''     # no checkbox-tracked plan files
```

This matters because the defaults are *this* project's conventions. Left unset,
a repo with no phase cadence silently inherits a phase regex and every commit is
labelled `unknown` - a habit imposed on a project that never had one. With them
empty, `parse_phase` returns `None` and the bundle reports `plan.enabled =
false`, both of which are honest.

The installer leaves these unset when it detects no convention.

## Structure

| Key | Default | Notes |
|---|---|---|
| `entry_prefix` | `## Phase ` | Identifies an ENTRY. Must not match reference sections interleaved among entries, or archiving will move reference material out of the live document. |
| `base_header` | `^## \d+[a-z]?\. ` | Where per-entry history stops and permanent reference begins. Never archived. |
| `pointer_prefix` | `## Archive pointer` | The tool-generated pointer. Stripped and regenerated each run, so it cannot accumulate. |
| `archive_header` | *(project name)* | Header written at the top of the archive. |
| `trunk` | `main` | Branch that merge claims are checked against. Interpolated into `merge_claim` as `{trunk}`. |

## Quoting: regexes need SINGLE quotes

TOML processes escape sequences inside `"double quoted"` strings, and `\d`,
`\s`, `\(` are not valid ones - so a regex written that way makes the **entire
file fail to parse**, not just that key.

```toml
branch_token = '`((?:feature|fix)/[^`]+)`'     # correct - literal string
branch_token = "`((?:feature|fix)/[^`]+)`"     # fails on any backslash
```

Use `'''triple quotes'''` if the pattern itself contains a single quote.

Plain values (`handoff_doc`, `trunk`, `entry_prefix`) have no backslashes, so
double quotes are fine there.

The loader detects this specific failure and explains it, rather than passing
along the bare decoder message that names only a line and column.

## Rules - derive these, do not copy them

Each was measured against one project's real prose. See `porting.md`.

| Key | Checks |
|---|---|
| `live_phrases` | Present-tense "not done yet" claims. Keep the set **small and closed**; widening reintroduces false positives. Checked in the newest entry only. |
| `branch_token` | How branch names appear in prose. |
| `merge_claim` | "merged to `{trunk}` at `<sha>`". Requires the SHA to FOLLOW the phrase, so a SHA belonging to a neighbouring clause is not misread. |
| `path_pointer` | Paths introduced by `Plan:`, `Design:`, `see`, `read`. Keyed on operative use, never on path shape. |
| `release_tag` | "released in v2.1". Checks the tag exists AND is an ancestor of trunk. Measured as ABSENT from the corpus this was built on, so its denominator reads 0 here; it is the common shape in CHANGELOG-keeping projects. |
| `todo_markers` | `TODO`/`FIXME`/`XXX`. |
| `code_suffixes` | Extensions scanned for TODOs. Excludes docs deliberately - a spec discussing TODO is not a TODO. |
| `todo_exclude_files` / `todo_exclude_dirs` | Paths exempt from the TODO scan, so the tool does not report its own source. |

Markdown links and heading anchors are checked too, and have no setting. Link
syntax is fixed by the format rather than by any project's habits, so there is
no corpus to measure and nothing to configure.

## Verifying a config actually works

`--verify` reports its **denominator** - how many candidates each rule actually
examined - so a clean document and a blind pattern no longer print the same
thing:

```
checked NEXT_SESSION.md: dead-sha 36, stale-live-claim 1, false-merge-claim 2,
  dead-path-pointer 5 (907 lines scanned for secrets)
```

Any rule that examined **0** is named on a `NOTE:` line. Treat that as
*investigate*, never as *fine*: the pattern found nothing to check, so the rule
is inert regardless of the exit code. Zero is not automatically a bug - a
project may genuinely never phrase a merge claim - but you must know which it
is, and only the denominator tells you.

Then prove the rules fire, which `--selftest` now does for you:

```
python tools/handoff_collect.py --selftest
```

It corrupts one REAL match per rule and reports which rules noticed. Probes
mutate your actual prose rather than injecting invented text, so what gets
exercised is your configuration against your writing; a synthetic probe written
in the default vocabulary would only prove that the defaults match the defaults.
A rule reported as DID NOT FIRE has a pattern that does not match what it claims
to check.

The manual version of the same idea: repoint a merge claim at a commit that is
not an ancestor of trunk and confirm it is reported. **A rule never observed
failing has not been tested** - this exact gap shipped once, where the config held the
right values and three rules never read them, so a foreign project got a clean
run against another project's vocabulary.
