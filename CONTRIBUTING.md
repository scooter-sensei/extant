# Contributing

## Running the tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

Python 3.11 or newer (for `tomllib`) and git.

**The tool has no third-party dependencies**, and nothing installed into your
repository needs any. The test suite is a separate question: it needs pytest.
Conflating those two is what put a comment reading "no dependencies to install"
above a CI step that ran `python -m pytest` on a runner without it, and all six
jobs failed identically before a single test ran.

Beyond that the suite touches no network and writes nothing outside `tmp_path`,
apart from reading this repository's own status document.

## Adding a validation rule

Rules live in a registry in `plugin/skills/extant/payload/extant_collect.py`. Each one declares its
scope, whether it survives archiving, and, required, the exact yes-or-no
question it asks:

```python
Rule(
    kind="false-merge-claim",
    check=validate_merge_claims,
    scope="whole-file",
    in_archive=True,
    falsifiable="is the claimed commit an ancestor of trunk?",
)
```

**The admission test.** A rule belongs only if both hold:

1. It can be answered yes or no by git or the filesystem. A test enforces that
   every rule states its `falsifiable` question, so a rule that inspects numbers
   or dates cannot be added quietly.
2. It produces **zero** false positives on a real corpus. This half is on you.
   Measure before you write the pattern. `plugin/skills/extant/references/design.md` records the time
   this was skipped: a rule keyed on what a path looked like would have emitted
   23 findings on its first run, every one of them wrong.

Candidates that would pass: release-tag claims, branch existence, deletion
claims, ordering claims. Candidates that would fail: suite-count consistency and
date validity (numbers, the forbidden class), issue links (needs the network),
"does this summary match the diff" (judgement, not falsifiable).

## Two house rules

**Every check must report its denominator.** "0 findings" and "0 examined"
print identically, so a broken check is indistinguishable from a clean result.
State what was examined. This is not a style preference; the project it came
from hit this exact failure six times, and reading the code caught none of them,
because the defect is an absence.

**Watch a check fail before you trust it.** Mutate the thing it guards and
confirm it goes red. A test that has never failed pins nothing. If a mutation
does not reproduce the bug you meant to reproduce, the green run afterwards
means nothing either.

`tests/harnesses/mutate.py` does this mechanically for the whole suite, and
`tests/harnesses/` holds four more audits that pytest cannot perform: a scenario
matrix over project shapes unlike this one, an adversarial smoke test, a
performance run, and a load test aimed at the known weak points rather than the
comfortable ones. They are slow and run by hand. See `tests/harnesses/README.md`.

They are worth running before a release, because between them they found every
defect fixed in 0.3.0 and the unit suite found none of them. This sentence said
"two more" for as long as it took the last two to be written, which is the drift
the tool cannot catch: no rule inspects a number.

Run the mutation campaign against a **copy**, never the working tree. It
rewrites source in place, and a campaign interrupted part-way once left a
mutation sitting in shipped code. It restores on exit and on a signal now, but
an isolated copy is what makes that irrelevant.

## Style

- ASCII only, everywhere, including prose. Non-ASCII in printed output raises
  `UnicodeEncodeError` on a cp437 console and terminates the process. Three
  tests enforce it: one tokenizes the payload and reads string literals, one
  reads the shell hooks, and one reads every shipped file whole. The third
  exists because the first two never opened a markdown file, and an em dash
  arrives in prose, pasted in with a sentence. Use `-` for an em dash, `...`
  for an ellipsis, `->` for an arrow, and plain quotes.
- `from __future__ import annotations` at the top of every module.
- Narrow exception handlers. Bare `except:` and `except Exception:` hide the
  failures this project exists to surface.
