# `.extant.toml` reference

Lives at the repo root. Every key is optional; omitted keys fall back to
defaults that reproduce the source project's behaviour. Keys may sit under a
`[extant]` table or at the top level.

```toml
[extant]
primary_doc = "NEXT_SESSION.md"
trunk = "main"
entry_prefix = "## Phase "
```

An unknown key is **reported as a warning**, not silently ignored - a typo that
quietly does nothing is the same class of failure as a pattern that matches
nothing.

### Both placements are merged, and a key may not use both

The two placements are read together rather than one winning. This mattered
once, badly: writing a sub-table such as `[extant.consistency.version]` makes
TOML create the nested path `extant` -> `consistency` -> `version`, and the
loader used to choose that nested table over the top level. A file like this one kept the consistency block and threw the
other two settings away:

```toml
primary_doc = "README.md"
extra_docs = ["CONTRIBUTING.md"]

[extant.consistency.node_version]
"README.md" = 'Node (\d+)'
"package.json" = '"node": "\D*(\d+)'
```

The file looked configured and was not, which is precisely the failure this
project exists to surface, sitting in its own loader.

Setting the same key in **both** places is now an error rather than a silent
resolution. Two homes for one setting is how the wrong value gets read while the
right one sits there looking correct.

### Where the file is found

The search walks upward from the starting directory and **stops at the
repository root**, so a `.extant.toml` belonging to a parent directory outside
the repository is never inherited.

Settings are re-read for the repository being checked rather than being fixed at
import. That matters when the tool is installed as a package - which the
pre-commit framework does - because the file's own location is then
site-packages, and a tool that read its configuration from there would validate
some other project's filenames and report a healthy run for every repository
that has none of them.

## Documents and layout

| Key | Default | Notes |
|---|---|---|
| `primary_doc` | `NEXT_SESSION.md` | The document sessions read as ground truth. |
| `archive_doc` | `docs/status-archive.md` | Where retired entries go. Validated too. |
| `retain_entries` | `3` | Entries kept in the live document. |
| `plans_dir` | `docs/superpowers/plans` | Scanned for the current plan's checkboxes. |
| `venv_python` | `.venv/Scripts/python.exe` | Interpreter, relative to the main working tree. |
| `consistency_timeout_seconds` | *(unset)* | Bounds each user-supplied consistency pattern, in seconds. Absent leaves them unbounded, which is the historical behaviour. Set it only if a pattern hangs: it costs a process spawn per pattern, because Python's `re` holds the GIL while matching and no in-process mechanism can interrupt it. Left unset, a catastrophically backtracking pattern can still spin. |
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
| `trunk` | `main` | The integration branch. Merge claims check the ref the CLAIM names, so this is no longer interpolated into `merge_claim`; it is the branch `stale-live-claim` and `dead-release-tag` fall back to, alongside whichever of `main`, `master`, `develop`, `development`, `trunk` exist. |

## Quoting: regexes need SINGLE quotes

TOML processes escape sequences inside `"double quoted"` strings, and `\d`,
`\s`, `\(` are not valid ones - so a regex written that way makes the **entire
file fail to parse**, not just that key.

```toml
branch_token = '`((?:feature|fix)/[^`]+)`'     # correct - literal string
branch_token = "`((?:feature|fix)/[^`]+)`"     # fails on any backslash
```

Use `'''triple quotes'''` if the pattern itself contains a single quote.

Plain values (`primary_doc`, `trunk`, `entry_prefix`) have no backslashes, so
double quotes are fine there.

The loader detects this specific failure and explains it, rather than passing
along the bare decoder message that names only a line and column.

## Rules - derive these, do not copy them

Each was measured against one project's real prose. See `porting.md`.

| Key | Checks |
|---|---|
| `live_phrases` | Present-tense "not done yet" claims. Keep the set **small and closed**; widening reintroduces false positives. Checked in the newest entry only. |
| `branch_token` | How branch names appear in prose. |
| `merge_claim` | "merged to `<ref>` at `<sha>`". TWO groups: the ref the claim names, then the commit, which is then checked against THAT ref rather than against `trunk`. A one-group pattern is the older contract and still means (sha) checked against trunk. Requires the SHA to FOLLOW the phrase, so a SHA belonging to a neighbouring clause is not misread. |
| `path_pointer` | Paths introduced by `Plan:`, `Design:`, `see`, `read`. Keyed on operative use, never on path shape. |
| `release_tag` | "released in v2.1". Checks the tag exists AND is on an integration branch. Measured as ABSENT from the corpus this was built on, so its denominator reads 0 here; it is the common shape in CHANGELOG-keeping projects. |
| `todo_markers` | `TODO`/`FIXME`/`XXX`. |
| `code_suffixes` | Extensions scanned for TODOs. Excludes docs deliberately - a spec discussing TODO is not a TODO. |
| `todo_exclude_files` / `todo_exclude_dirs` | Paths exempt from the TODO scan, so the tool does not report its own source. |

Markdown links and heading anchors are checked too, and have no setting. Link
syntax is fixed by the format rather than by any project's habits, so there is
no corpus to measure and nothing to configure.

## Comparing files against each other

`inconsistent-artifact` is the one rule with `scope = "repository"`. It reads no
document at all: it asks whether two files in the repository state different
values for the same thing.

```toml
[extant.consistency.version]
"package.json" = '"version":\s*"([^"]+)"'
"CHANGELOG.md" = '^## (\d+\.\d+\.\d+)'

[extant.consistency.node_version]
"README.md" = 'Node (\d+)'
".nvmrc" = '^v?(\d+)'
```

Each table under `[extant.consistency]` is one named check. Each entry is a
file and a pattern whose **single capture group** is the value to compare. Every
file in a check must produce the same value, or the rule names the check, the
value, and which files hold which.

**This does not weaken the guarantee.** The forbidden question is whether a
value is CORRECT - "the suite was 2238" has nothing to check against. Whether
two files disagree has a definite answer needing only the filesystem.

Off unless configured, deliberately: the files and patterns are per-project, and
a guessed default would accuse an innocent repository.

Four shapes are refused at load rather than passing quietly, because each one
would produce a check that can never fail:

| Refused | Why |
|:---|:---|
| a check listing fewer than two files | it could only agree with itself |
| a pattern with no capture group | nothing to extract, nothing to compare |
| a pattern with more than one group | which group is the value is a guess |
| the same file under two spellings | paths are normalised, so `docs/x.md` and `docs/./x.md` are caught as one file |

A pattern that matches **nothing** is reported rather than treated as agreement.
A file that is missing is reported too. Both would otherwise be a check that
examined nothing and printed what success prints.

The configuration comes from the repository **being checked**, not from the
installed copy of the tool. A rule reading the installed copy's settings would
pass everywhere and mean nothing.

## Verifying a config actually works

`--verify` reports its **denominator** - how many candidates each rule actually
examined - so a clean document and a blind pattern no longer print the same
thing:

```
checked NEXT_SESSION.md: dead-sha 36, stale-live-claim 1, false-merge-claim 2,
  dead-path-pointer 5
```

Any rule that examined **0** is named on a `NOTE:` line. Treat that as
*investigate*, never as *fine*: the pattern found nothing to check, so the rule
is inert regardless of the exit code. Zero is not automatically a bug - a
project may genuinely never phrase a merge claim - but you must know which it
is, and only the denominator tells you.

Then prove the rules fire, which `--selftest` now does for you:

```
python tools/extant_collect.py --selftest
```

It corrupts one REAL match per rule and reports which rules noticed. Probes
mutate your actual prose rather than injecting invented text, so what gets
exercised is your configuration against your writing; a synthetic probe written
in the default vocabulary would only prove that the defaults match the defaults.
A rule reported as DID NOT FIRE has a pattern that does not match what it claims
to check.

The manual version of the same idea: repoint a merge claim at a commit that is
on no integration branch and confirm it is reported. **A rule never observed
failing has not been tested** - this exact gap shipped once, where the config held the
right values and three rules never read them, so a foreign project got a clean
run against another project's vocabulary.
