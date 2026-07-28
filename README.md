<div align="center">

# extant

**Your docs cite commits. Some of those commits no longer exist.**

[![tests](https://github.com/scooter-sensei/extant/actions/workflows/tests.yml/badge.svg)](https://github.com/scooter-sensei/extant/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![dependencies: none on 3.11+](https://img.shields.io/badge/dependencies-none%20on%203.11%2B-success)](#requirements)

*extant (adj.) - still in existence; surviving.*

</div>

---

## The problem

A plan document says the work landed in `8f2a91c`. A spec says its predecessor
merged to `develop` at `abc1234`. A status file says a branch is not merged yet.

Then someone squash-merges, or rebases, or force-pushes a cleanup, and those
sentences quietly stop being true. Nothing complains, because documentation is
just writing. Tests check code. Type checkers check types. **Nothing checks
whether a commit you wrote down still exists.**

This got much worse recently, and not for a subtle reason. Coding agents write
plan documents, spec documents and status files at a volume humans never did,
and those documents are dense with commit SHAs, branch names and file paths.
Then the next agent session reads them back **as fact**. It cannot tell that a
line expired, so it plans around something untrue and hands back confidently
wrong work.

Here is one real project, swept with a single command and no configuration.
49 tracked markdown files, 43 findings, counted by rule:

| Count | Rule | |
|---:|:---|:---|
| 37 | `dead-sha` | a commit that no longer resolves |
| 5 | `bare-dead-sha` | the same, written without backticks |
| 1 | `dead-path-pointer` | a file that moved |

**42 of 43 were dead commit references, and every located finding sat in the
project's plan and spec directories** - the documents written during agent
sessions. Zero in the README. Zero in CONTRIBUTING. The human-facing docs were
fine; the machine-facing ones had rotted where nobody looks.

That is the shape of the problem, and a link checker will not find any of it,
because none of these are links.

## What it looks like

A plan document written during an earlier session. It says the work merged to
`main`. The commit is real, so nothing looks wrong, but it sits on a branch that
was never merged:

```console
$ extant --repo . --sweep

UNREVIEWED - surveyed only, not gated
docs/plans/phase-3.md: line 4: [dead-sha] `8f2a91c` does not resolve in this repo
docs/plans/phase-3.md: line 3: [false-merge-claim] claims work merged to main at `04d559f`, but that commit is not an ancestor of main
docs/plans/phase-3.md: line 6: [dead-path-pointer] points at `docs/plans/phase-2.md`, which does not exist

swept 2 markdown file(s): 0 configured (0 finding(s)), 2 unreviewed (3 finding(s))
```

That is real output, not an illustration. The middle line is the one nothing
else will give you: **the commit exists, and the sentence about it is still
false.** Answering that means asking git for ancestry, which a text linter has
no way to do.

The `swept` line counts what it **looked at**, not what it found. It matters as
much as the findings, and
[there is a section about why](#every-check-reports-its-denominator).

## Try it in one line

Nothing installed, nothing written into your project, no configuration, no file
to name:

```console
$ uvx extant --repo . --sweep
```

That reads every markdown file git tracks and tells you what has rotted. On a
real project it took one command to surface 44 dead commit references across 49
files.

**A sweep cannot fail your build.** Findings in files you have not configured
are surveyed and reported, never gated on, because some of them will be
examples rather than claims. It always prints how many files it looked at, so
"nothing found" is distinguishable from "nothing checked".

The other two modes, once you want them:

| Command | For |
|:---|:---|
| `--sweep` | the survey. No config, exits 0, shows everything |
| `--validate <file>` | one document, exits 1 on findings |
| `--verify` | every document `.extant.toml` names. What the git hooks run |

[Four ways to install properly](#install) are below.

---

## What it covers

Eleven rules. Every one answers a question git or the filesystem can settle.

| Rule | Catches |
|:---|:---|
| `dead-sha` | "released in commit `abc1234`" when that commit does not exist |
| `false-merge-claim` | "merged into `develop` at `abc1234`" when that commit is not on `develop` |
| `stale-live-claim` | "not merged yet" about something merged last week |
| `unknown-branch` | "work is on branch X" when git has never seen that name |
| `dead-release-tag` | "released in v2.1" when no such tag exists, or it never shipped |
| `dead-path-pointer` | "see the file at this path" when the file moved |
| `dead-md-link` | `[a link](to/a/file.md)` whose target is gone |
| `dead-md-anchor` | a `#jump-to-section` link with no such heading, in this file or a linked one |
| `inconsistent-artifact` | two files in your project stating different values for the same thing |
| `dead-pinned-ref` | an install snippet pinning a version of your project that does not exist |
| `raw-lfs-blob` | an asset your `.gitattributes` says is in Git LFS, committed into git as a real binary instead |

Five details that are easy to miss:

**More than one integration branch works.** A merge claim names the branch it
means, so "merged to `develop` at `abc1234`" is checked against `develop` and
"merged to `main` at ..." against `main`. Nothing to configure. Gitflow teams
write both kinds, and against a single configured trunk half of those claims
were never examined at all - not judged and found true, simply not read.

**Case matters, and only on some machines.** Windows and macOS open
`docs/PLAN.md` happily when the file is `docs/plan.md`. Linux does not. Without
the check a document passes on your laptop and fails on the server, or worse,
passes everywhere while misleading every Linux reader. Wrong-case paths are
reported on every platform.

**Examples are left alone.** Claims inside fenced code blocks are not read as
promises, so a README showing what a claim looks like is not accused of making
one. A password inside a fence is still reported, because that one is about what
the file contains rather than what it promises.

**Install snippets are the exception.** `dead-pinned-ref` is the one rule that
reads *inside* code blocks, because an install snippet is the opposite of an
example: it is the block a reader copies verbatim, and a version that does not
exist fails for them on first use. It only checks pins whose `repo:` names your
repository, so documenting somebody else's hook is never flagged.

**Renames are followed.** When a file has moved, you get told where:

```
line 5: [dead-md-link] links to `docs/old-name.md`, which does not exist;
        git shows it renamed to `docs/new-name.md`
```

### What it deliberately ignores

It never judges whether a number or a date is *right*. "We had 2238 tests in
March" was true in March. It is not wrong now, only old, and there is nothing to
check it against.

That restraint is the whole design. A tool that cries wolf gets ignored, and an
ignored tool is worse than none. This one reports only what it can prove.

The single exception proves the rule: it will compare **two files against each
other**, because that has a definite answer. See
[files that contradict each other](#files-that-contradict-each-other).

---

## Is this for you?

| | |
|:---|:---|
| **Strongest fit** | You run coding agents, and sessions leave behind plan, spec, design or status documents. Those cite commits and branches, rot within days, and are read back as fact by the next session. This is where 42 of the 43 findings above came from. |
| **Good fit** | You write ADRs, RFCs, postmortems, migration notes or release notes that reference commits, branches or tags. Same shape, written by hand. |
| **Probably yes** | Your project uses git and has documentation that names files and paths. The link and path rules work on any markdown. |
| **Probably not** | Your documentation is one paragraph that never mentions a file, a commit, or a version. There is nothing here for it to check, and it will honestly tell you so. |

Note what is **not** required: a status file, a changelog, a particular
workflow, or any change to how you work.

**Be clear about the trade.** This checks claims git can settle. It does not
check external URLs, whether a code sample still compiles, or whether a
documented flag still exists. If dead external links are your problem, use
[lychee](https://github.com/lycheeverse/lychee); if committed credentials are,
use [gitleaks](https://github.com/gitleaks/gitleaks). They are better at those
than this will be, and they cannot answer whether `abc1234` is on `main`.

---

## Requirements

Git, and Python 3.9 or newer. Check both:

```console
$ git --version
$ python --version
```

| If missing | Get it |
|:---|:---|
| Git | https://git-scm.com |
| Python 3.9+ | https://www.python.org |

On macOS and Linux you may need `python3` rather than `python`.

**The tool itself has no third-party dependencies.** Standard library and git,
nothing else.

3.9 and 3.10 are supported for the enterprise distributions that ship them:
RHEL 9 and Debian 11 are on 3.9, Ubuntu 22.04 LTS on 3.10. The one thing
newer than 3.9 anywhere in the tool is `tomllib`, which joined the standard
library in 3.11. Below that the tool runs on its defaults with no parser at
all, and reading a `.extant.toml` wants `pip install tomli` - the same
parser under its original name, so a config file is read identically on
every version.

---

## Install

Four ways in. The table picks one for you.

| If you | Use | You get |
|---|---|---|
| already use pre-commit | **A** | validation on every commit, one config block |
| want to look before committing to anything | **B** | the validator as a command, nothing written into your project |
| use Claude Code and want the slash command | **C** | the plugin, plus everything in D |
| want the hooks and agent instructions in-repo | **D** | the full install, no plugin manager |

Options A and B give you the **validator only**. The git hooks and the
`/extant` command have to live inside the repository they check, so C and D are
the routes that install those. A route quietly delivering half the tool would
be worse than no route.

### Option A: pre-commit

If you already use [pre-commit](https://pre-commit.com), this is the whole
setup. Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/scooter-sensei/extant
    rev: v0.14.0
    hooks:
      - id: extant
```

Then `pre-commit install`, and create a `.extant.toml` naming the document to
check:

```toml
primary_doc = "README.md"
extra_docs = ["CONTRIBUTING.md"]
```

It runs on every commit whether or not you touched documentation. That is
deliberate: merging a branch can make a sentence false without editing a line of
prose, and that is the case this exists for.

A second hook id, `extant-annotate`, emits GitHub Actions annotations instead of
plain text.

### Option B: pip, pipx or uv

Installs the validator as a command. Nothing is written into your project, so
this is the quickest way to see what the tool says before deciding anything:

```console
$ uvx extant --repo . --validate README.md
```

`uvx` downloads and runs it without installing. To keep it around:

```console
$ pipx install extant
$ extant --repo . --validate README.md
```

Once a `.extant.toml` names your documents, `--verify` checks all of them at
once and is what you want thereafter. Before that file exists it will report
`no such document: NEXT_SESSION.md`, because that is the default `primary_doc`
and your project has no reason to have one.

`pip install extant` works too, though a tool you run against many projects is
usually happier in its own environment.

This is the VALIDATOR only. The git hooks and the `/extant` command have to
live inside the repository they check, so use Option C or D to install those.
Point it at a document with `--validate`, or create a `.extant.toml` naming
one, exactly as in Option A.

### Option C: Claude Code

Two lines:

```
/plugin marketplace add scooter-sensei/extant
/plugin install extant@extant
```

Then open the project you want to protect and ask:

> Set up extant in this project.

It inspects your repository, works out the settings, and reports what it found
and how confident it is about each value.

### Option D: by hand

Works with or without Claude Code.

**1. Get the files.** Download the ZIP from
[the repository](https://github.com/scooter-sensei/extant) (green **Code**
button, then **Download ZIP**), or clone it:

```console
$ git clone https://github.com/scooter-sensei/extant
```

**2. Preview.** This changes nothing:

```console
$ python extant/plugin/skills/extant/install.py --repo /path/to/your/project --dry-run
```

Read what it prints. If it looks wrong, stop, and nothing has happened.

**3. Do it for real.** The same command without `--dry-run`, plus a preset:

```console
$ python extant/plugin/skills/extant/install.py --repo /path/to/your/project --preset readme
```

**4. Turn on the automatic checks.**

```console
$ cd /path/to/your/project
$ sh tools/hooks/install
```

They run after a commit is already recorded, print what they found, and never
stop you doing anything.

### What actually lands in your repo

Worth being precise about, because "installs a Claude thing" is the usual
assumption and it is wrong:

| File | Needs |
|:---|:---|
| `tools/extant_collect.py`, `tools/extant_config.py` | Python 3.9+ and git |
| `tools/hooks/*` | a POSIX `sh` |
| `.extant.toml` | nothing |
| `.agents/skills/extant/SKILL.md` | nothing. Agent Skills is an open standard, and this is its cross-tool path: read by Codex, Gemini CLI, Copilot, Cursor and Kimi as well as Claude |
| `.claude/commands/extant.md` | Claude Code |

**Only the last line is tool-specific, and it is the only one written
conditionally.** It appears if your repo already has a `.claude/` directory or
a `CLAUDE.md`; otherwise the installer says it skipped it and names the flag.
`--claude-command` and `--no-claude-command` decide it outright.

The validator is standard-library Python and git subprocesses. There is no
agent framework in it, nothing to adapt for one, and no runtime dependency on
any assistant: options A and B do not write an agent file at all.

### Presets

A preset picks the documents and the shape, so you are not deriving
configuration before you have seen the tool work once.

| Preset | For |
|:---|:---|
| `readme` | any project. Your README and CONTRIBUTING. Nothing else needed. |
| `node` | the same, plus `package.json` and `CHANGELOG.md` version agreement |
| `python` | the same, with `pyproject.toml` |
| `rust` | the same, with `Cargo.toml` |
| `enterprise` | long-lived projects. Also `SECURITY.md`, `SUPPORT.md`, `UPGRADING.md`, `MIGRATION.md` |
| `ml` | data and model projects. Also `MODEL_CARD.md` and `DATA_CARD.md`, and that `pyproject.toml` and `environment.yml` pin the same Python |
| `legacy-web` | older web apps. Also `INSTALL.md`, `DEPLOY.md`, `UPGRADING.md`, and that `.nvmrc` and `package.json` agree on Node |
| `go` | a Go module. Also `SECURITY.md`, and that `go.mod` and your `Dockerfile` build with the same Go |
| `jvm` | Gradle or Maven. Also `UPGRADING.md`, `MIGRATION.md`, and `gradle.properties` against the changelog |
| `k8s` | Helm charts. Also `RUNBOOK.md`, and `Chart.yaml`'s chart version against the changelog |
| `terraform` | Terraform modules. Also `UPGRADING.md` and `MIGRATION.md`, beside the terraform-docs README |
| `docker` | images and compose. Also `DEPLOY.md`, `RUNBOOK.md`, `OPERATIONS.md` |
| `monorepo` | a workspace root. Also `ARCHITECTURE.md`, `docs/README.md`, and the root version |
| `mobile` | iOS and Android. Also `RELEASE_NOTES.md`, `PRIVACY.md`, and one marketing version across both stores |
| `unity` | a Unity project. Checks the editor-version badge against `ProjectSettings/ProjectVersion.txt` |
| `godot` | a Godot project. Checks the version in `doc/setup_instructions.md` against `project.godot` |
| `agent` | files AI agents read as fact: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `copilot-instructions.md` |
| `status` | a running status file with dated entries |

**`agent` is worth a note.** [AGENTS.md](https://agents.md) is the cross-tool
standard for instructing AI coding agents, and `CLAUDE.md` and `GEMINI.md` are
the vendor-native equivalents. Those files are mostly paths and commands, and an
agent cannot tell an expired line from a current one. A dead path in a README
wastes somebody's afternoon; a dead path in an `AGENTS.md` becomes confidently
wrong work.

**Where two files look like they should agree and do not, no check is written.**
Helm documents `appVersion` as unrelated to the chart `version`. Terraform's
`required_version` is a constraint (`">= 1.5.0"`) while `.terraform-version` is
an exact pin. Go's `go` directive is a minimum and `toolchain` is exact. A mobile
`versionCode` is a build counter, not the version anyone sees. Every one of those
pairs would report a correct repository, so `docker` and `terraform` carry no
cross-check at all, and the rest compare only what genuinely must match.

The last three exist because long-lived documentation rots in a particular
place. An enterprise project rarely has a stale README. It has a `MIGRATION.md`
last edited in 2021 pointing at three files that have since moved.

Two rules govern every preset:

**A preset never overrides something measured.** Detection reads your repository
for the trunk name, branch naming and commit conventions. A template would be
guessing at those, and a preset that quietly replaced your real branch name
would be the copied-configuration problem this tool was built around. Choosing
the *document* is your call, which is why passing a preset settles that one.

**Checks whose files are absent are skipped and reported.** A preset never opens
by complaining about a file you do not have. A tool whose first act is a false
positive has taught a lesson that is very hard to unteach.

### Works with any coding agent

The checker is Python, git hooks and a pre-commit entry, so it never depended on
a particular assistant. What did was one line deciding where the agent-facing
instructions went.

Setup now writes them to `.agents/skills/extant/SKILL.md`, the location the
[Agent Skills](https://agentskills.io) open standard defines. One file, read by
**OpenAI Codex, Gemini CLI, GitHub Copilot, Cursor, Kimi Code, Claude Code** and
the twenty-odd other tools that adopted it.

It is rendered for your repository rather than copied, so it names your document
and your paths, and it carries the discipline that matters: read the
denominator, never make a document pass by deleting the claim.

Claude Code additionally gets `/extant`, a slash command for the end-to-end
workflow. Both are rendered from the same observations, so they cannot end up
describing different documents.

### What lands in your project

| | |
|:---|:---|
| `tools/` | the checker |
| `.extant.toml` | settings, written by reading **your** project |
| git hooks | the automatic checks. They report, they never block |
| `.agents/skills/extant/SKILL.md` | instructions any agent reads, rendered for your project |
| `/extant` command | Claude Code only, for the full workflow |

---

## Features

### Every check reports its denominator

The summary line counts what was **examined**, not what was found:

```console
checked STATUS.md: dead-sha 36, stale-live-claim 1, false-merge-claim 2,
  dead-path-pointer 5
```

If one of those reads `0`, that check found nothing to look at, which usually
means a setting is wrong rather than that your file is spotless. Any rule that
examined nothing is named on a `NOTE:` line.

This is the single most important line in the output. "Found no problems" and
"did not look" print identically otherwise, and only one of them is good news.

### It can prove its own checks fire

The worry above deserves more than a warning, so there is a command:

```console
$ python tools/extant_collect.py --selftest
```

It takes a real claim from your document, breaks it on purpose, confirms the
matching rule notices, and puts everything back. Nothing is written.

```console
  dead-sha             FIRED
  stale-live-claim     FIRED
  dead-path-pointer    FIRED
  dead-release-tag     NO PROBE       nothing to corrupt

  3 fired, 1 had nothing to corrupt, 0 stayed silent
```

**A check that stays silent after you break something it should catch is
broken.** This runs in CI here on every change, so the tool is not merely
tested, it is watched failing.

### Findings inside pull requests

```console
$ python tools/extant_collect.py --verify --format=github
$ python tools/extant_collect.py --verify --format=sarif
```

**`github`** emits GitHub Actions annotations, so each problem is highlighted on
its own line in the pull request diff rather than buried in a log nobody opens.
Add the flag to your existing step. Nothing else is needed, and it requires no
extra permissions.

**`sarif`** emits the standard format code-scanning tools exchange, as pure JSON
on stdout, so it pipes straight to a file. To get results into GitHub's Security
tab:

```yaml
      - name: Check the documentation
        run: python tools/extant_collect.py --verify --format=sarif > extant.sarif
        continue-on-error: true

      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: extant.sarif
```

That upload needs `permissions: security-events: write`. This repository uses
the annotation route instead, so treat the SARIF upload as a starting point
rather than something proven here.

### Files that contradict each other

The tool never asks whether a number is *correct*. It will ask whether two files
disagree, which has a definite answer needing only the filesystem.

This project shipped the bug that motivated it: three manifests said the version
was 0.1.0 while the changelog said 0.3.0, and everyone installing was told they
were getting the first release.

```toml
[extant.consistency.version]
"package.json" = '"version":\s*"([^"]+)"'
"CHANGELOG.md" = '^## (\d+\.\d+\.\d+)'
```

Each line names a file and how to find the value inside it. Disagree, and you
are told which file says what.

Four shapes are refused when the settings load, because each would produce a
check that can never fail: a check listing one file, a pattern with no capture
group, a pattern with more than one, and the same file named twice under
different spellings. A pattern that matches nothing is reported rather than
passing quietly.

### Corrections as a patch, never an edit

When a file has been renamed, the tool already tells you where it went. It can
also write the correction:

```console
$ python tools/extant_collect.py --verify --suggest-fixes
```

This prints a **patch** and changes nothing. Read it, and apply it if you agree:

```console
$ python tools/extant_collect.py --verify --suggest-fixes | git apply -
```

It only offers corrections for files git actually recorded as renamed. If a file
is simply gone it says nothing, because guessing where it went means writing
something that might not be true, and that is the one thing this refuses to do.
Its authority rests on checking claims and never authoring them.

### Search across the archive

If you keep a status document, old entries get archived so the live file stays
short. That helps until you need to remember why a decision was made.

```console
$ python tools/extant_collect.py --search "checkout"
```

It searches the live document and the archive together and returns whole
**entries** rather than matching lines. That is the only reason it beats grep: a
decision lives in a dated entry with its reasoning, and a line from the middle
tells you a phrase exists rather than what was decided.

### Every other document you keep

Your primary document is not the only one that rots. A `CLAUDE.md`, an
`AGENTS.md`, a `CONTRIBUTING.md` all make the same kinds of claim:

```toml
extra_docs = ["CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md"]
```

They get every rule that does not depend on dated entries, which is most of
them.

### Adopting on a project that already has years of prose

Point this at a ten-year-old repository and the first run reports everything at
once. That is accurate and useless: CI goes red, nobody has a week for
decade-old documentation, and the tool comes back out.

Record what is already there, once:

```console
$ python tools/extant_collect.py --verify --write-baseline
recorded 47 finding(s) in .extant-baseline.json
```

Then every run checks **new** claims and ignores the recorded ones:

```console
$ python tools/extant_collect.py --verify --baseline
1 new finding(s), 47 suppressed by .extant-baseline.json
```

New documentation is held to the standard from day one; the backlog waits.

**It always says how much it is hiding.** "No findings" and "no new findings, 47
suppressed" are different facts, and a baseline that concealed its own size
would be exactly the failure this tool exists to surface, reintroduced by one of
its own features.

**Nothing is ever recorded implicitly.** `--write-baseline` is a separate,
deliberate command. A baseline that rewrote itself on every run would forgive
whatever it had just found, and the check would decay to nothing while still
reporting success.

**An amnesty must not outlive its finding:**

```console
$ python tools/extant_collect.py --verify --baseline-check
baseline: 47 entr(y/ies), 45 still occur, 2 do not
  STALE  docs/setup.md: [dead-md-link] links to `scripts/old.sh`, ...
```

Those two were fixed. Their entries now forgive something that is not there, so
they are reported and should be deleted. A baseline nobody prunes becomes a
permanent exemption, and it is itself a stale claim.

The file is JSON, and deliberately readable: each entry carries the path, the
rule and the message alongside its fingerprint. It is a list of things your
project has agreed to leave broken for now, so it belongs in review like any
other change.

### The optional wrong-branch guard

One check is **off unless you ask for it**, because unlike everything else here
it can refuse to save your work:

```console
$ sh tools/hooks/install --with-trunk-guard
```

**What it solves.** Git lets you keep several versions of a project going at
once. If you lose track of which one you are on, you can commit to the wrong
branch. The work is not lost, but it is filed in the wrong place, and finding
out later is unpleasant.

**Why it is off by default.** It has nothing to do with your documentation. You
came for a tool that checks whether your writing is still true, and a tool that
suddenly refuses to save your work for an unrelated reason is a tool people
uninstall.

**Should you?** If you work on one branch, no. If you juggle several, or have
ever pushed work and found it on the wrong branch, yes. It is also worth it if
AI assistants commit in your project, because they are particularly good at
losing track of which branch they are on.

Remove it by deleting `pre-commit` from your project's `.git/hooks`, or bypass
it once with `git commit --no-verify`.

### Any language

The checking does not care what your project is written in. Only the optional
"run the tests" step does, and you name the command:

```toml
suite_command = ["npm", "test"]
suite_command = ["cargo", "test"]
```

### Fast enough to leave on

A 16,000-line document validates in under a second. A 100,000-line document in
about four. The rules that query git batch their questions, so a document
naming two thousand distinct commits asks git once per commit rather than twice
per claim.

---

## Read the settings it writes

Setup works out your project's habits by reading it, and prints each value with
how confident it is:

```console
  trunk         [derived ] origin/HEAD -> main
  branch_token  [derived ] 128 branches sampled
  entry_prefix  [guessed ] highest-scoring header '## Release'
  merge_claim   [unknown ] no matching phrasing found
```

Anything it could not work out is left **switched off** rather than guessed.

> **This is the part that matters.** If a setting is wrong, that rule quietly
> does nothing and you get a tool reporting "all clear" forever without looking
> at anything. It is the one way this fails badly. Read what setup prints, and
> see [porting.md](plugin/skills/extant/references/porting.md) to fill gaps.

---

## What it cannot do

- Only catches sentences that can be **proven** wrong. "Nearly finished" is
  beyond it, on purpose.
- Cannot judge whether a summary is a *good* summary.
- Expects consistent headings for dated entries. A heading that does not match
  is skipped.
- Assumes one main branch. Gitflow-style release branches are not modelled.
- **Checks links to your own files, not to the web.** Nothing here touches the
  network. Checking external links would make a passing run depend on someone
  else's uptime and rate limits, turning a definite answer into a coin flip.
  Issue and pull request links go unchecked for the same reason.
- **Does not complain about a branch merged and then deleted.** That is normal
  tidying, and the branch is still named in the merge commit. Only a name git
  has never seen is reported.
- **Settings load next to the tool, not next to the folder you point at.**
  Correct once installed in your project, wrong if you run it from elsewhere. It
  says so on stderr rather than quietly using the wrong ones.
- **It cannot tell a corrected claim from a deleted one.** Removing the sentence
  it complained about makes a document pass. The `/extant` workflow works around
  this by reporting first-run findings even after fixing them, so a deletion is
  visible in both the report and the diff. The checker alone cannot know.
- **A pattern you write yourself can hang it.** Settings take regular
  expressions, and a badly shaped one can take effectively forever on some text.
  The fix is to simplify the pattern, but the failure looks like a freeze rather
  than a complaint.

---

<details>
<summary><b>If something goes wrong</b></summary>

<br>

**"python is not recognised"** on Windows, or **"command not found"** on macOS
and Linux: try `python3`, or reinstall Python with the "add to PATH" box ticked.

**The checks never run.** Confirm you did step 4, then run `--verify` by hand.

**It flags something you think is fine.** Do not silence it by deleting the
sentence. Either that sentence really is out of date, or a setting needs
adjusting. Both are worth knowing.

**Everything reports 0.** A setting is almost certainly wrong. See
[Read the settings it writes](#read-the-settings-it-writes).

</details>

<details>
<summary><b>Deeper documentation</b></summary>

<br>

All under `plugin/skills/extant/`:

| File | What is in it |
|:---|:---|
| `references/porting.md` | Getting the settings right for your project. Read first. |
| `references/config.md` | Every setting explained. |
| `references/design.md` | Why each rule works as it does, and the real mistake behind each decision. |
| `SKILL.md` | What Claude reads. |

</details>

<details>
<summary><b>What is in this repository</b></summary>

<br>

```
.claude-plugin/marketplace.json   lets Claude Code install this
.pre-commit-hooks.yaml            lets pre-commit install this
plugin/
  .claude-plugin/plugin.json      plugin details
  skills/extant/
    SKILL.md                      what Claude reads
    install.py, detect.py         the setup program
    payload/                      what gets copied into your project
    references/                   the deeper documentation
tests/                            219 tests
tests/harnesses/                  five slow audits, run by hand
NEXT_SESSION.md                   this project's own status document
```

That last one is not decoration. This project runs its own tool on its own
document, on every change, in CI. If it stopped working, this repository would
be the first to find out.

`tests/harnesses/` holds the audits pytest cannot perform: one that breaks the
code on purpose to see whether any test notices (57 mutations, all caught), one
that installs into twenty unlike projects (20 scenarios, 87 assertions), one
that tries to abuse the tool (18 adversarial probes), and two that measure speed
and load. Between them they found every defect fixed in 0.3.0, and the stale
assertion caught in the audit before 0.6.0. The unit suite found none of them,
because the unit suite was the thing being audited.

The bug fixed in 0.6.1 was found by none of them. It took installing the
published release and using it as a stranger would, which is its own lesson.

</details>

<details>
<summary><b>The one idea worth taking elsewhere</b></summary>

<br>

When you write a rule that checks something, **look at your real data first and
shape the rule to fit it**, rather than writing what the rule ought to look like
and hoping. Done the second way, the file-path rule produced 23 false alarms on
the first project it ran against. Done the first way it produced none, and still
caught the real problem.

And always report how many things you looked at. "Found no problems" and "did
not look" print exactly the same otherwise.

</details>

---

<div align="center">

**MIT licensed.** Use it freely, including commercially. See [LICENSE](LICENSE).

</div>
