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

## Before you push

The suite is not the whole gate, and treating it as one is how this repository
gets a red `main`. Three of the audits under `tests/harnesses/` run as their
own CI jobs precisely because pytest structurally cannot perform them:

```sh
PKG=$(mktemp -d); ARENA=$(mktemp -d)
python -m pytest
python tests/harnesses/mutate.py --check-only
git archive HEAD | tar -x -C "$PKG"
python tests/harnesses/smoke.py "$PKG" "$ARENA"
python tests/harnesses/scenarios.py "$PKG" "$ARENA"
python tests/harnesses/fuzz.py "$PKG" "$ARENA" --seed 20260824 --repos 35
python plugin/skills/extant/payload/extant_collect.py --verify --repo .
python plugin/skills/extant/payload/extant_collect.py --selftest --repo .
```

On Windows use a native path for those two directories rather than `mktemp -d`,
whose MSYS-style result Python cannot open - it reports an empty run, which
reads exactly like a clean one.

Measured, not hypothetical. A `NOTE:` line worded "this is a shallow clone" put
a word the smoke scan treats as a network operation into the package's
operational source. The suite, `--verify`, `--selftest` and all 152 mutation
anchors were green; smoke was the only thing that saw it, and because it is a
separate slow job it saw it after the push rather than before. The cheap half
of that probe now runs in the suite, which does not make the rest of this list
optional - it makes one failure mode cheaper to catch.

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

**This applies to suppressions too, and more sharply.** Two were refused after
counting: "a path beside a creation verb is a runtime output" is right about 1
of the 6 findings it matches, and "hex in a backslash path is not a SHA"
matches 4 of which 2 are shell line continuations. A suppression that fires
wrongly deletes a real finding silently, where a false positive at least
appears in the output for somebody to argue with.

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
2. It produces zero false positives on a corpus it was NOT designed on.
   Measure first, and keep a corpus back. Every rule here was tuned against 92
   repositories until they were quiet; run against 40 it had never seen, the
   set reported 7,658 findings of which 582 were real. Fourteen false-positive
   shapes lived in the gap between "quiet on the corpus that shaped it" and
   "correct", and reading the code showed none of them.
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
  exists to surface. A broad catch is allowed in exactly one shape: when it
  REPORTS what it caught, so the degraded path names itself instead of printing
  what a healthy one prints. A rule that raises and a worker pool that will not
  start are both handled that way.
- Never commit without being asked.

## Where things are

| Path | What |
|:---|:---|
| `plugin/skills/extant/payload/extant/` | the validator: settings, scopes, the git seam, the three output formats, the modes |
| `plugin/skills/extant/payload/extant/rules/` | one module per rule |
| `plugin/skills/extant/payload/extant_collect.py` | the entry point the hook invokes by path; a version handshake and one import |
| `plugin/skills/extant/install.py` | the installer, detection and presets |
| `plugin/skills/extant/references/design.md` | why each rule works as it does |
| `tests/harnesses/` | the audits pytest cannot perform. `scenarios.py`, `smoke.py` and `fuzz.py` are their own CI jobs; `mutate.py` runs there as `--check-only`; `corpus.py`, `perf.py` and `stress.py` are hand-run |
| `CONTRIBUTING.md` | the same rules, aimed at people |

Read `plugin/skills/extant/references/design.md` before changing a rule. It
records the real mistake behind each decision, which is usually the reason the
obvious simplification is wrong.
