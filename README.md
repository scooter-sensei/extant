<div align="center">

# handoff-validator

**Your documentation makes claims. This checks whether they are still true.**

[![tests](https://github.com/scooter-sensei/handoff-validator/actions/workflows/tests.yml/badge.svg)](https://github.com/scooter-sensei/handoff-validator/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![dependencies: none](https://img.shields.io/badge/dependencies-none-success)](#before-you-start)

</div>

---

## The problem

Your README says the project needs Node 18. Your `package.json` says 20. Your
CONTRIBUTING file links to a script that was deleted in March. Somewhere a
document says a rewrite "landed in `8f2a91c`", and that commit no longer exists.

Every one of those sentences was true the day it was written.

Nothing complains, because documentation is just writing. Tests check code. Type
checkers check types. Nothing checks whether your prose is still accurate, so it
drifts quietly until somebody follows it and wastes an afternoon.

This matters more than it used to. AI coding assistants read these files and
treat them as fact. An assistant cannot tell that a line expired, so it plans
around something untrue, and you get confidently wrong work.

## What it looks like when it works

An ordinary project. A README, a `package.json`, a CONTRIBUTING file. **No
special status document, no new habits to adopt.**

```console
$ python tools/handoff_collect.py --verify

line 5:  [dead-sha]                `deadbeef1234567` does not resolve in this repo
line 3:  [dead-md-link]            links to `docs/setup.md`, which does not exist
line 1:  [inconsistent-artifact]   `node_version` disagrees across files:
                                   `18` in README.md; `20` in package.json

checked README.md: dead-sha 1, dead-md-link 1, inconsistent-artifact 2
CONTRIBUTING.md: line 3: [dead-md-link] links to `scripts/gone.sh`
```

Four lies in the docs you already have, found in under a second, with line
numbers. That `checked` line is the count of things it **looked at**, which
matters as much as the problems it found. More on that below.

It also handles the harder case, if you keep one: a running status or handoff
file, where entries make claims about branches and merges that go stale as work
lands. That is where this started, and it is now one use case rather than the
price of entry.

---

## What it checks

| It notices when you wrote | Because it checks |
|:---|:---|
| "released in commit `abc1234`" but that commit is gone | whether the commit really exists |
| "merged into main" when it never was | whether it actually got merged |
| "not merged yet" about something merged last week | whether it is still waiting |
| "see the file at this path" but the file moved | whether the file is there |
| `[a link](to/a/file.md)` whose file is gone | whether the linked file is there |
| a `#jump-to-section` link with no such section | whether the heading exists |
| "work is on branch X" and there is no such branch | whether git has ever seen it |
| "released in v2.1" and there is no such tag | whether the tag exists and shipped |
| a path spelled `Docs/Plan.md` when the file is `docs/plan.md` | whether the spelling matches the real file |
| a password or key pasted in by accident | whether anything looks like a secret |

That fifth-from-last row is not fussiness. Windows and macOS open
`docs/PLAN.md` quite happily when the file is `docs/plan.md`; Linux does not.
Without the check, a document passes on your laptop and fails on the server, or
worse, passes everywhere while misleading every Linux reader.

Examples inside code blocks and backticks are left alone, so a README showing
what a claim looks like is not read as making one. A password inside a code
block is still reported, because that one is about what the file **contains**
rather than what it promises.

When a file has simply moved, it tells you where it went:

```
line 5: [dead-md-link] links to `docs/old-name.md`, which does not exist;
        git shows it renamed to `docs/new-name.md`
```

### What it deliberately ignores

It never judges whether a number or date is *right*. "We had 2238 tests in
March" was true in March. It is not wrong now, just old, and there is nothing to
check it against.

That restraint is the point. **A tool that cries wolf gets ignored**, and an
ignored tool is worse than none. It only reports what it can prove is wrong.

The one thing it will compare is **two files against each other**, which is a
different question with a definite answer. See below.

---

## Is this for you?

| | |
|:---|:---|
| **Probably yes** | Your project uses Git and has documentation: a README, a CONTRIBUTING file, docs, architecture notes. That is enough. It matters more if an AI assistant reads those files, because it cannot tell an expired line from a current one. |
| **Probably not** | Your project does not use Git, or your documentation is a single paragraph that never mentions a file, a commit, or a version. |

Note what is **not** on that list: keeping a status or handoff file. This
started as a tool for those and required one to exist, which turned out to be
the single largest reason people could not use it. The rules were never
specific to that shape - they work on any markdown.

---

## Before you start

You need two things. Open a terminal (Command Prompt or PowerShell on Windows,
Terminal on Mac or Linux) and type these one at a time:

```console
$ git --version
$ python --version
```

Each should print a version number.

| If this is missing | Get it here |
|:---|:---|
| Git | https://git-scm.com |
| Python (needs 3.11 or newer) | https://www.python.org |

On Mac and Linux you may need to type `python3` rather than `python`.

You do not need to know how to program. You do need to be comfortable typing a
few commands.

---

## Install

### Option A: through Claude Code

Two lines, typed into Claude Code:

```
/plugin marketplace add scooter-sensei/handoff-validator
/plugin install handoff@handoff-validator
```

That is the whole installation. Now open the project you want to protect and ask:

> Set up the handoff validator in this project.

It runs the setup, works out the right settings by looking at your project, and
tells you what it found.

### Option B: pre-commit, if you already use it

One block in your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/scooter-sensei/handoff-validator
    rev: v0.5.0
    hooks:
      - id: handoff
```

It runs on every commit, whether or not you touched any documentation. That is
deliberate: merging a branch can make a sentence false without editing a single
line of prose, which is the case this exists for.

### Option C: download it yourself

Works with or without Claude Code.

**1. Get the files.** Either download the ZIP from
[the repository](https://github.com/scooter-sensei/handoff-validator) (green
**Code** button, then **Download ZIP**, then unzip), or if you know Git:

```console
$ git clone https://github.com/scooter-sensei/handoff-validator
```

**2. Preview it.** This changes nothing. Swap in the folder of your own project:

```console
$ python handoff-validator/plugin/skills/handoff/install.py --repo /path/to/your/project --dry-run
```

Read what it prints. If it looks wrong, stop, and nothing has happened.

**3. Do it for real.** Same command, without `--dry-run`.

If you want it configured for you, add a preset:

```console
$ python .../install.py --repo /path/to/your/project --preset readme
```

| Preset | For |
|:---|:---|
| `readme` | any project. Checks your README and CONTRIBUTING. Nothing else needed. |
| `node` | the same, plus `package.json` and `CHANGELOG.md` version agreement |
| `python` | the same, with `pyproject.toml` |
| `rust` | the same, with `Cargo.toml` |
| `handoff` | a running status file with dated entries |

A preset picks the documents and the shape. It never overrides something the
setup measured from your project, because a measurement beats a template, and a
preset that quietly replaced your real branch name would be the copied-config
problem this tool was built around.

Checks whose files are not present are skipped and reported, so a preset never
opens by complaining about a file you do not have.

**4. Turn on the automatic checks.**

```console
$ cd /path/to/your/project
$ sh tools/hooks/install
```

From now on it re-checks your notes file every time you save a change.

These checks only ever **tell you** things. They run after your change is
already saved, print what they found, and never stop you doing anything.

### What lands in your project

| | |
|:---|:---|
| `tools/` | the checker itself |
| `.handoff.toml` | settings, written by reading **your** project |
| git hooks | the automatic checks (they report, they never block) |
| `/handoff` command | only if you use Claude Code, written for your project |

---

## Read the settings it writes

Setup works out your project's habits by reading it, and prints what it found
with how sure it is:

```console
  trunk         [derived ] origin/HEAD -> main
  branch_token  [derived ] 128 branches sampled
  entry_prefix  [guessed ] highest-scoring header '## Release'
  merge_claim   [unknown ] no matching phrasing found
```

Anything it could not work out is left switched **off** rather than guessed.

> **This is the part that matters.** If a setting is wrong, that check quietly
> does nothing, and you get a tool reporting "all clear" forever without looking
> at anything. It is the one way this fails badly. Read what setup prints, and
> see [porting.md](plugin/skills/handoff/references/porting.md) to fill the gaps.

---

## Day to day

Mostly you do nothing. The checks run by themselves when you save changes.

To check on demand, from inside your project:

```console
$ python tools/handoff_collect.py --verify
```

The summary line counts **what it looked at**, not problems found:

```console
checked STATUS.md: dead-sha 36, stale-live-claim 1, false-merge-claim 2,
  dead-path-pointer 5 (907 lines scanned for secrets)
```

If one of those reads `0`, that check found nothing to examine, which usually
means a setting is wrong rather than that your file is spotless. The tool says
so out loud, because "found no problems" and "did not look" are easy to confuse
and only one is good news.

### Prove the checks actually work

The worry above deserves more than a warning, so there is a command for it:

```console
$ python tools/handoff_collect.py --selftest
```

It takes a real claim from your document, deliberately breaks it, and confirms
the matching check notices. Then it puts everything back. Nothing is written.

```console
  dead-sha             FIRED
  stale-live-claim     FIRED
  dead-path-pointer    FIRED
  dead-release-tag     NO PROBE       nothing to corrupt
  possible-secret      FIRED

  4 fired, 1 had nothing to corrupt, 0 stayed silent
```

**A check that stays silent after you break something it should catch is
broken.** That is the one line worth reading. This runs in CI here on every
change, so the tool is not merely tested, it is watched failing.

### Show the problems inside pull requests

By default findings print as plain lines. Two other shapes exist for machines:

```console
$ python tools/handoff_collect.py --verify --format=github
$ python tools/handoff_collect.py --verify --format=sarif
```

**`github`** prints GitHub Actions annotations, so each problem is highlighted
on its own line in the pull request, instead of sitting in a log nobody opens.
Add `--format=github` to the step that runs the check. Nothing else is needed.

**`sarif`** prints the standard format that code-scanning tools exchange. It
writes only JSON, so you can pipe it straight into a file. If you want the
results in GitHub's Security tab, upload that file:

```yaml
      - name: Check the handoff document
        run: python tools/handoff_collect.py --verify --format=sarif > handoff.sarif
        continue-on-error: true

      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: handoff.sarif
```

That upload step needs `permissions: security-events: write` on the job. This
repository does not use it, so treat it as a starting point rather than
something proven here: the annotation route above is what runs on every commit.

### An optional extra: the wrong-branch guard

There is one more check you can switch on. It is **off unless you ask for it**,
because unlike everything else here it can **refuse to save your work**.

```console
$ sh tools/hooks/install --with-trunk-guard
```

**What problem it solves.** Git lets you keep several versions of a project
going at once, called branches. There is usually one "real" version everyone
shares, and side versions where work happens before joining it. If you forget
which one you are looking at, you can save work onto the wrong version. The
work is not lost, but it is filed in the wrong place, and finding that out
later is unpleasant.

This guard notices that situation and stops the save, with a message telling
you where you actually are.

**Why it is off by default.** It has nothing to do with your notes file. You
came here for a tool that checks whether your writing is still true, and a tool
that suddenly refuses to save your work for an unrelated reason is a tool people
uninstall. So you get it only if you want it.

**Should you turn it on?** If you work on one branch and rarely switch, no; it
will never trigger and is just another moving part. If you juggle several
branches, or you have ever pushed work and found it on the wrong one, yes. It is
also worth it if AI assistants make commits in your project, because they are
particularly good at losing track of which branch they are on.

You can remove it later by deleting the `pre-commit` file inside your project's
`.git/hooks` folder, or bypass it once with `git commit --no-verify`.

### Find something you wrote months ago

Old entries get moved out of your notes file into an archive so the live file
stays short. That is helpful until you need to remember why a decision was made
and cannot recall which file it ended up in.

```console
$ python tools/handoff_collect.py --search "checkout"
```

It searches the live file and the archive together, and prints whole entries
rather than single matching lines, so you get the decision and its date rather
than a phrase out of context. Add `--full` for the complete entry.

### Fix moved files without editing by hand

When a file has been renamed, the tool already tells you where it went. It can
also write the correction out for you:

```console
$ python tools/handoff_collect.py --verify --suggest-fixes
```

This prints a **patch** and changes nothing. You can read it, and apply it with
one command if you agree:

```console
$ python tools/handoff_collect.py --verify --suggest-fixes | git apply -
```

It only offers changes for files git actually recorded as renamed. If a file is
simply gone, it says nothing, because guessing where it went would mean writing
something that might not be true, and that is the one thing this tool refuses
to do.

### Catch two files disagreeing with each other

This tool never checks whether a number is *correct* - "we had 2238 tests" has
nothing to check it against. But it can check whether two files in your project
**contradict each other**, which has a definite answer.

This project needed it: three files said the version was 0.1.0 while the
changelog said 0.3.0, and anyone installing was told they were getting the first
release. Add to `.handoff.toml`:

```toml
[handoff.consistency.version]
"package.json" = '"version":\s*"([^"]+)"'
"CHANGELOG.md" = '^## (\d+\.\d+\.\d+)'
```

Each line names a file and how to find the value in it. If they disagree, you
are told which file says what.

### Check your other files too

Your status file is not the only one that rots. A `CLAUDE.md`, an `AGENTS.md`,
a `README` all make the same kinds of claim. Add them:

```toml
extra_docs = ["CLAUDE.md", "AGENTS.md", "README.md"]
```

They get every check that does not depend on dated entries, which is most of
them. This is also how a team that tracks work in Jira or Linear, and keeps no
status file at all, still gets something useful out of this.

---

## What it cannot do

- Only catches sentences that can be **proven** wrong. Vague writing like
  "nearly finished" is beyond it, on purpose.
- Cannot judge whether your summary is a *good* summary.
- Expects consistent headings for each entry. A heading that does not match gets
  skipped silently.
- Assumes one main branch. More elaborate branching is not handled.
- **Checks links to your own files, not links to the web.** Nothing here uses
  the internet. Checking external links would make a passing run depend on
  someone else's uptime and rate limits, turning a definite answer into a
  coin flip. Issue and pull request links go unchecked for the same reason.
- **Does not complain about a branch that was merged and then deleted.** That
  is normal tidying, not a mistake, and the branch is still named in the merge
  commit. Only a name git has never seen at all is reported.
- **Settings are read next to the tool, not next to the folder you point it
  at.** That is right once it is installed in your project, and wrong if you
  run it from somewhere else, where your settings would be skipped. It tells
  you when that happens rather than quietly using the wrong ones.
- If the settings are wrong it checks nothing while appearing to work.
- **It cannot tell a corrected claim from a deleted one.** Removing the sentence
  it complained about makes a document pass. The `/handoff` workflow works
  around this by making the agent report its first-run findings even after
  fixing them, so a deletion is visible in both the report and the diff, but
  the checker on its own has no way to know.
- **A pattern you write yourself can hang it.** The settings take regular
  expressions, and a badly shaped one can take effectively forever on certain
  text. That is your own configuration doing it, and the fix is to simplify the
  pattern, but the failure looks like the tool freezing rather than complaining.

## Works with any language

The checking part does not care what your project is written in. Only the
optional "run the tests" step does, and you tell it the command:

```toml
suite_command = ["npm", "test"]
suite_command = ["cargo", "test"]
```

---

<details>
<summary><b>If something goes wrong</b></summary>

<br>

**"python is not recognised"** on Windows, or **"command not found"** on Mac and
Linux: try `python3` instead of `python`, or reinstall Python and tick the
"add to PATH" box.

**The checks never run.** Make sure you did step 4. Confirm by running the
`--verify` command by hand.

**It flags something you think is fine.** Do not silence it by deleting the
sentence it complained about. Either that sentence really is out of date, or a
setting needs adjusting. Both are worth knowing.

**Everything reports 0.** A setting is almost certainly wrong. See
[Read the settings it writes](#read-the-settings-it-writes).

</details>

<details>
<summary><b>Deeper documentation</b></summary>

<br>

All under `plugin/skills/handoff/`:

| File | What is in it |
|:---|:---|
| `references/porting.md` | Getting the settings right for your project. Read first. |
| `references/config.md` | Every setting explained. |
| `references/design.md` | Why each check works as it does, and the real mistake behind each decision. |
| `SKILL.md` | What Claude reads. |

</details>

<details>
<summary><b>What is in this repository</b></summary>

<br>

```
.claude-plugin/marketplace.json   lets Claude Code install this
plugin/
  .claude-plugin/plugin.json      plugin details
  skills/handoff/
    SKILL.md                      what Claude reads
    install.py, detect.py         the setup program
    payload/                      what gets copied into your project
    references/                   the deeper documentation
tests/                            the test suite
tests/harnesses/                  five slow audits, run by hand
NEXT_SESSION.md                   this project's own notes file
```

That last one is not decoration. This project runs its own tool on its own notes
file, on every change, in CI. If it stopped working, this repository would be
the first to find out.

`tests/harnesses/` holds the checks pytest cannot perform: one that breaks the
code on purpose to see whether any test notices, one that installs into a dozen
unlike projects, one that tries to abuse the tool, and two that measure speed
and load. They found every bug fixed in the most recent release. The unit suite
found none of them, because the unit suite was the thing being audited. See
`tests/harnesses/README.md`.

</details>

<details>
<summary><b>The one idea worth taking elsewhere</b></summary>

<br>

When you write a rule that checks something, **look at your real data first and
shape the rule to fit it**, rather than writing what the rule ought to look like
and hoping. Done the second way, the file-path check produced 23 false alarms on
the very first project it ran against. Done the first way it produced none, and
still caught the real problem.

And always report how many things you looked at. "Found no problems" and "did
not look" print exactly the same otherwise.

</details>

---

<div align="center">

**MIT licensed.** Use it freely, including commercially. See [LICENSE](LICENSE).

</div>
