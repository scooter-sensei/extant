# Working on extant

Instructions for any coding agent working in this repository. This is the
cross-tool file: Codex, Gemini CLI, Copilot, Cursor, Kimi and Claude Code all
read it, and Claude Code additionally reads the richer skill under
`plugin/skills/extant/`.

## What this project is

A validator that checks whether the claims in documentation are still true,
against git and the filesystem. It never judges whether a value is correct, only
whether something it names still exists or still holds.

## Before you change anything

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
python plugin/skills/extant/payload/extant_collect.py --verify --repo .
```

The suite must be green and `--verify` must exit 0 before you edit, so a failure
afterwards is yours rather than inherited.

## Four rules that are not style preferences

**Every check must report its denominator.** "0 findings" and "0 examined" print
identically, so a broken check is indistinguishable from a clean result. State
what was examined. This project hit that failure repeatedly, and reading the
code caught none of them, because the defect is an absence.

**Watch a check fail before you trust it.** Mutate the thing it guards and
confirm it goes red. A test that has never failed pins nothing.
`tests/harnesses/mutate.py` does this mechanically.

**Prove the setup applied before believing a negative result.** A probe that
silently did nothing looks exactly like a test that noticed nothing. Assert the
edit landed, then read the outcome.

**Derive patterns from real data.** Look at what a project actually writes
before writing a rule for it. A rule keyed on what a path looked like produced
23 findings on its first real run, every one wrong.

The failure is not always noise. Three designs here were overturned by
measuring a real corpus first, and each would have shipped something that did
NOTHING: widening `path_pointer` for game projects (that rule examines zero
references in real game documentation, which uses markdown links), keying the
Godot version check on the README (a shipped Godot game states its version only
in its setup document), and fixing gitflow with a trunk list (a merge claim
names its own ref, which is strictly more precise). A no-op that looks like a
feature is the expensive kind, because nothing ever reports it.

## The admission test for a new rule

A rule belongs only if all four hold:

1. It can be answered yes or no by git or the filesystem. No network, no
   judgement.
2. It produces zero false positives on a real corpus. Measure first.
3. It names the PLACE the answer lives - this ref, this file, this manifest,
   this document. "Search the repository and report if the token is not found"
   is not a location.
4. The two sides name the same SINGLE fact. One cited line number against one
   file's length; one stated floor against one ecosystem's manifest.

Numbers and dates are the forbidden class: "the suite was 2238" was true when
written and has nothing to check it against. A validator that cries wolf stops
being read, which costs more than having no validator.

**Clauses 3 and 4 are the cheap ones, and they exist because clause 2 is
expensive.** Eight candidates have been measured against two corpora and
refused - environment variables twice, code symbols, HTTP endpoints, CLI flags,
ports, image tags, README versions - at 0% to 22% precision. Six were refusable
in a minute by clauses 3 and 4, without cloning anything.

Clause 3 fails when absence is the question: a documented token this project
does not implement is usually a token belonging to something ELSE, like
`CARGO_HOME`, `git --amend` or `docker --pull`, and the literal is missing by
design. Clause 4 fails when neither side is one value: "does the compose file
publish a different port than this document states" names its location and
still means nothing, because a development compose file publishes 76 ports.
That clause is also why `inconsistent-artifact` asks the user for patterns -
only the author knows which two strings name one fact.

## House style

- ASCII only, everywhere, including prose. Non-ASCII crashes a cp437 console.
  Use `-` for a dash, `...` for an ellipsis, `->` for an arrow.
- `from __future__ import annotations` at the top of every module. The floor is
  Python 3.9, and that import is what keeps `X | Y` annotations legal there.
- Narrow exception handlers. Bare `except:` hides the failures this project
  exists to surface.
- Never commit without being asked.

## Where things are

| Path | What |
|:---|:---|
| `plugin/skills/extant/payload/extant_collect.py` | the validator and every rule |
| `plugin/skills/extant/install.py` | the installer, detection and presets |
| `plugin/skills/extant/references/design.md` | why each rule works as it does |
| `tests/harnesses/` | five audits pytest cannot perform, run by hand |
| `CONTRIBUTING.md` | the same rules, aimed at people |

Read `plugin/skills/extant/references/design.md` before changing a rule. It
records the real mistake behind each decision, which is usually the reason the
obvious simplification is wrong.
