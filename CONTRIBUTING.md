# Contributing

## Running the tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

Python 3.9 or newer and git. `tomllib` is the only thing in the payload
newer than 3.9, and it is imported inside a try/except: below 3.11 the tool
falls back to `tomli`, and without either it runs on defaults and says so
when a config file is actually present. Two tests in `test_packaging.py`
keep the floor where it is claimed to be.

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
    falsifiable="is the claimed commit an ancestor of the ref the claim names?",
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

## Cutting a release

Bump the version in four manifests - `.claude-plugin/marketplace.json`,
`plugin/.claude-plugin/plugin.json`, `plugin/skills/extant/SKILL.md`,
`pyproject.toml` - and the `rev:` pin in the two places that are live install
INSTRUCTIONS: `README.md` and `.pre-commit-hooks.yaml`.

**Never bump a `rev:` inside `CHANGELOG.md`.** A changelog entry records what
was true at that release, so a pin in one is history, not instruction. A
first-occurrence replace across the changelog silently rewrote the 0.5.0
entry's pin at every release from 0.6.0 through 0.11.0, so it ended up
promising a version that did not exist when it was written. Caught by reading
the file before tagging, not by any rule here: both the old and new pins
resolve once tagged, so nothing is falsifiable about it.

The changelog's other `rev:` lines are prose about past mistakes and
illustrative examples of `dead-pinned-ref`. Leave those alone too - a pin is
only an instruction when it sits under an install snippet.

**Then create the tag, and confirm it exists before you stop.** Bumping the
`rev:` in the README is a promise that the tag is there; 0.10.0 was bumped,
committed and pushed without ever being tagged, so for as long as that was the
newest release the README told people to pin a version git had never heard of.

    git tag -a vX.Y.Z -m "extant X.Y.Z - <what changed>"
    git push origin vX.Y.Z
    # Exits non-zero when that exact ref is absent, where a grep would
    # also match v0.1.20 while looking for v0.1.2.
    git ls-remote --exit-code --tags origin refs/tags/vX.Y.Z

`dead-pinned-ref` is exactly the rule for this and cannot help here, because
`README.md` is not one of the checked documents - it is made of illustrative
claims, and including it produces four false positives. Confirmed by trying
it. So this is a procedural check on purpose, not an oversight.
