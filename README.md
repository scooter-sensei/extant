<div align="center">

# handoff-validator

**Keeps your project's status notes honest, by checking them against what actually happened.**

[![tests](https://github.com/scooter-sensei/handoff-validator/actions/workflows/tests.yml/badge.svg)](https://github.com/scooter-sensei/handoff-validator/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![dependencies: none](https://img.shields.io/badge/dependencies-none-success)](#before-you-start)

</div>

---

## The problem

Most projects keep a notes file that says where things stand. Yours probably has
lines like these:

```markdown
## Phase 3 - Checkout flow (in progress)

**Status.** The checkout work is NOT yet merged.
It lives on `feature/checkout`.

Shipped earlier: merged to `main` at `8f2a91c`.

**Design:** `docs/checkout-plan.md`
```

Every one of those sentences was true the day it was written. Weeks later, some
of them quietly are not. The checkout work did get merged. The commit was
rewritten and no longer exists. The design doc was renamed.

Nothing complains, because the file is just writing.

This matters more than it used to. AI coding assistants read these files and
treat them as fact. An assistant cannot tell that a line expired, so it plans
around something untrue, and you get confidently wrong work.

## What it looks like when it works

Run one command against that exact file:

```console
$ python tools/handoff_collect.py --verify

line 6:  [stale-live-claim]   claims `feature/checkout` unmerged, but that branch
                              no longer exists (merged and cleaned up, or the
                              claim is stale)
line 8:  [dead-sha]           `8f2a91c` does not resolve in this repo
line 10: [dead-path-pointer]  points at `docs/checkout-plan.md`, which does not exist

checked NEXT_SESSION.md: dead-sha 1, stale-live-claim 1, false-merge-claim 1,
  dead-path-pointer 1 (10 lines scanned for secrets)
```

Three lies, found in under a second, with line numbers. That last line is the
count of things it **looked at**, which matters as much as the problems it found.
More on that below.

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

It never checks numbers or dates. "We had 2238 tests in March" was true in March.
It is not wrong now, just old.

That restraint is the point. **A tool that cries wolf gets ignored**, and an
ignored tool is worse than none. It only reports what it can prove is wrong.

---

## Is this for you?

| | |
|:---|:---|
| **Probably yes** | You keep a running notes, status, or handoff file, you use Git, and especially if an AI assistant reads that file. |
| **Probably not** | Everything lives in Jira or Linear and you keep no notes file, or your project does not use Git. |

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

### Option B: download it yourself

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

**4. Turn on the automatic checks.**

```console
$ cd /path/to/your/project
$ sh tools/hooks/install
```

From now on it re-checks your notes file every time you save a change.

### What lands in your project

| | |
|:---|:---|
| `tools/` | the checker itself |
| `.handoff.toml` | settings, written by reading **your** project |
| git hooks | the automatic checks |
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
