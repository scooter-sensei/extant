# Before you push this anywhere

A short checklist. The first item is enforced by a test, so the suite is red
until it is done.

## 1. Put a real name on the LICENSE

`LICENSE` currently reads `Copyright (c) 2026 <GITHUB-USERNAME>`. Replace the
placeholder with the name or handle you want publicly attached to this code.

`tests/test_packaging.py::test_license_names_a_real_copyright_holder` fails
while the placeholder is present. That is deliberate: a placeholder in a legal
notice is exactly the kind of thing that ships unnoticed, and the whole premise
of this project is that unnoticed is the dangerous state.

## 2. Decide what the repository is called

The directory is `handoff-validator`. If you rename it, nothing in the code
depends on the name.

## 3. Check the suite passes on a clean clone

```sh
python -m pytest
```

110 tests, no network, no fixtures outside `tmp_path` except this repository's
own handoff document.

## 4. Consider what this repository reveals

`NEXT_SESSION.md` and `references/design.md` describe real failures from the
project this was extracted from, including dated incidents. They are what make
the design rationale credible, and they are also a record of things going wrong
in a specific codebase. Read them once with publication in mind and decide
whether you are comfortable with that. Nothing in them names a third party, and
no repository paths, hostnames, or credentials appear.

## 5. Optional, if you want adopters

- A short GIF or transcript of `--verify` catching a real false claim does more
  than the README does.
- Topics on the repository: `git`, `documentation`, `validation`,
  `claude-code`, `ai-agents`.

## 6. Expect the first CI run to be red

`.github/workflows/tests.yml` runs the suite on Linux and Windows across Python
3.11 to 3.13, and separately has the tool validate this repository's own handoff
document on pushes to `main`.

It will fail until item 1 is done, because the LICENSE test is part of the
suite. That is the intended behaviour rather than an oversight: a green badge
sitting over an unpublishable license is precisely the reassuring, false signal
this project exists to prevent.

## What is deliberately not here

- **No PyPI packaging.** The tool is installed by copying files into a target
  repository, not by `pip install`, because the hooks and the slash command have
  to live in the target repo anyway.
- **No version pinning or dependencies.** Standard library only, Python 3.11+
  for `tomllib`. The 3.11 floor is asserted by the CI matrix rather than only
  claimed in prose.
- **No release automation or tagging.** Version numbers live in `CHANGELOG.md`
  and nowhere else, so there is nothing to keep in sync.
