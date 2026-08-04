# Contributing

## Running the tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
python plugin/skills/extant/payload/extant_collect.py --verify --repo .
```

All three before you edit anything, so a failure afterwards is yours rather
than inherited. The third is the tool checking its own documentation, and it
is the one people forget.

Python 3.9 or newer, and git 2.31 or newer. The hook installer calls
`git rev-parse --path-format=absolute`, which older git does not know. `tomllib` is the only thing in the payload
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

**Push `main` and wait for CI to go green BEFORE tagging.** A successful push
says the remote accepted the commits, not that the run passed.

    gh run list --branch main --limit 1     # or open the Actions tab

0.19.0 shipped to PyPI with `tests` failing on the very commit it tagged. The
push succeeded, the tag went up ninety seconds later, and the release was
announced as verified before anyone opened Actions. Nothing about the artifact
was wrong - the failure was two mutation anchors that a refactor had left
pointing at code no longer there - but that was luck rather than process, and
the tag is the one step here that cannot be taken back: PyPI does not allow
replacing a released version.

`publish.yml` now enforces this rather than trusting it. Before building, it
asks the API whether `tests.yml` succeeded for the commit the tag points at,
and refuses otherwise - see `.github/scripts/require_green_tests.py`. The match
is by COMMIT, because `tests.yml` runs on pushes to `main` and on pull requests
and never on a tag. So **tagging before pushing the branch finds no run at all,
and that fails**: a gate that read "nothing found" as "nothing wrong" would pass
hardest in exactly the case its subject was never checked. The waiting is
handled too, up to thirty minutes, so tagging promptly is a delay rather than a
race.

The step above is still worth doing by hand. Learning that a release is blocked
is cheaper before the tag exists than after, since the tag is what triggers the
attempt.

A green `pytest -q` is not the same signal. **The self-check job runs steps the
suite does not**, deliberately: `mutate.py --check-only`, `--selftest`, and a
timing run all live in CI because they are too slow, too platform-specific, or
too self-referential for pytest to carry. Whatever passed locally, the question
before tagging is what the runner said about that SHA.

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

**Pushing the tag publishes to PyPI.** `.github/workflows/publish.yml` runs on
any `v*` tag: it builds, refuses to continue unless the tag matches the version
in `pyproject.toml`, installs the built wheel into a clean environment and runs
it against a repository with a planted fault, and only then uploads.

That middle step is the point. `twine check` reads metadata and runs nothing,
so it cannot tell a working wheel from one that installs and does nothing. The
gate asserts BOTH directions - a broken document exits 1 and a repaired one
exits 0 - because a tool that always fails looks identical to one that works.

Publishing uses Trusted Publishing, so there is no API token in the repository,
in a secret, or in anyone's shell history. It needs one setup step that cannot
be done from a commit: on PyPI, add a pending publisher for project `extant`
with owner `scooter-sensei`, repository `extant`, workflow `publish.yml`, and
environment `pypi`. Until that exists the upload step fails with a permissions
error, which is correct - nothing should be publishable that was not authorised
out of band.

PyPI does not allow replacing a released version. Add a required reviewer to
the `pypi` environment if you want the upload to be a deliberate act rather
than a consequence of pushing a tag.
