# handoff-validator

Keeps your project's status notes honest, by checking them against what actually
happened.

## The problem, in plain words

Most projects keep a notes file that says where things stand. Something like
"the login feature is finished but not merged yet", or "see the design doc at
this path", or "this was released in commit abc1234".

Every one of those sentences was true on the day it was written. Weeks later,
some of them quietly are not. The login feature did get merged. The design doc
was renamed. The commit was rewritten and no longer exists.

Nothing complains, because the file is just writing. A person reading it has no
way to tell the true sentences from the expired ones without checking each by
hand, which nobody does.

This matters more than it used to, because AI coding assistants read these files
and treat them as fact. An assistant has no way to know a line is out of date,
so it plans around something that is not true, and you get confidently wrong
work.

## What this tool does

It reads your notes file, finds the sentences that can be checked, and checks
them. If a sentence is no longer true, it tells you, and it can stop the change
from being saved until you fix it.

In plain terms, it can answer questions like:

| It notices when you wrote | Because it checks |
|---|---|
| "released in commit abc1234" but that commit does not exist | whether the commit is really there |
| "merged into the main version" but it never was | whether it actually got merged |
| "not merged yet" about something that merged last week | whether it is still waiting |
| "see the file at this path" but the file is gone | whether the file exists |
| a password or key pasted in by accident | whether anything looks like a secret |

### What it deliberately does not check

It never checks numbers or dates. A line like "we had 2238 tests in March" was
true in March and is not wrong now, it is just old news. Flagging that sort of
thing would produce constant false alarms.

That restraint is the whole point. **A tool that cries wolf gets ignored**, and
an ignored tool is worse than no tool. So it only reports things it can prove
are wrong.

## Is this for you?

**Probably yes if:** you keep a running notes, status, or handoff file in your
project, you use Git, and especially if an AI assistant reads that file.

**Probably not if:** you track everything in a task tracker like Jira or Linear
and keep no notes file, or your project does not use Git.

## Before you start

You need two things installed. To check, open a terminal (Command Prompt or
PowerShell on Windows, Terminal on Mac or Linux) and type these, one at a time:

```
git --version
python --version
```

Each should print a version number.

- If Git is missing, get it from https://git-scm.com
- If Python is missing or below 3.11, get it from https://www.python.org
  (on Mac or Linux you may need to type `python3` instead of `python`)

You do not need to know how to program. You do need to be comfortable typing a
few commands.

## How to install

### Option A: through Claude Code (easiest)

If you use Claude Code, type these two lines into it:

```
/plugin marketplace add scooter-sensei/handoff-validator
/plugin install handoff@handoff-validator
```

That is the whole installation. Now open the project you want to protect and
ask Claude something like:

> Set up the handoff validator in this project.

It will run the setup, look at your project to work out the right settings, and
tell you what it found.

### Option B: download it yourself

This works with or without Claude Code.

**Step 1. Get the files.** Either download the ZIP from
https://github.com/scooter-sensei/handoff-validator (click the green "Code"
button, then "Download ZIP", then unzip it), or if you know Git:

```
git clone https://github.com/scooter-sensei/handoff-validator
```

**Step 2. Preview what it would do.** Nothing is changed by this step. Replace
the example path with the folder of the project you want to protect:

```
python handoff-validator/plugin/skills/handoff/install.py --repo /path/to/your/project --dry-run
```

Read what it prints. If it looks wrong, stop here and nothing has happened.

**Step 3. Run it for real.** Same command, without `--dry-run`:

```
python handoff-validator/plugin/skills/handoff/install.py --repo /path/to/your/project
```

**Step 4. Turn on the automatic checks.** Go into your project folder and run:

```
cd /path/to/your/project
sh tools/hooks/install
```

From now on it re-checks your notes file every time you save a change.

## What it puts in your project

- A `tools/` folder holding the checker itself.
- A `.handoff.toml` settings file, written by looking at **your** project rather
  than copied from someone else's.
- Automatic checks that run when you save changes.
- If you use Claude Code, a `/handoff` command written for your project.

## Important: check the settings

The setup tries to work out your project's habits by reading it: which branch is
your main one, how you name things, how your notes file is laid out. It prints
what it found and how confident it is:

```
  trunk         [derived ] origin/HEAD -> main
  branch_token  [derived ] 128 branches sampled
  entry_prefix  [guessed ] highest-scoring header '## Release'
  merge_claim   [unknown ] no matching phrasing found
```

Anything it could not work out is left switched **off** rather than guessed,
and it tells you so.

**This part matters.** If a setting is wrong, that check quietly does nothing,
and you get a tool that reports "all clear" forever without looking at anything.
That is the one way this tool fails badly. Read what the setup prints, and see
`plugin/skills/handoff/references/porting.md` for how to fill in the gaps.

## Using it day to day

Most of the time you do not have to do anything: the checks run by themselves
when you save changes.

To check on demand, from inside your project folder:

```
python tools/handoff_collect.py --verify
```

You will see something like:

```
checked STATUS.md: dead-sha 36, stale-live-claim 1, false-merge-claim 2,
  dead-path-pointer 5 (907 lines scanned for secrets)
```

Those numbers are **how many things it looked at**, not problems found. If it
finds a problem it says so separately.

**Read those numbers.** If one says `0`, that check found nothing to look at,
which usually means a setting is wrong rather than that your file is perfect.
The tool points this out, because "found no problems" and "did not look" are
easy to confuse and only one is good news.

## What it cannot do

Stated plainly, so there are no surprises:

- It only catches sentences that can be proven wrong. Vague writing like "nearly
  finished" is beyond it, on purpose.
- It cannot tell whether your summary of the work is a *good* summary.
- It expects your notes file to use consistent headings for each entry. A heading
  that does not match the pattern gets skipped silently.
- It assumes one main branch. More complicated branching setups are not handled.
- It does not use the internet, so links to issues or pull requests are not
  checked.
- If the settings are wrong, it checks nothing while appearing to work. See the
  section above.

## Works with any language

The checking part does not care what your project is written in. Only the
optional "run the tests" step does, and you tell it what command to use:

```toml
suite_command = ["npm", "test"]
suite_command = ["cargo", "test"]
```

## If something goes wrong

**"python is not recognised"** on Windows, or **"command not found"** on Mac and
Linux: try `python3` instead of `python`, or reinstall Python and tick the "add
to PATH" box.

**The checks never seem to run.** Make sure you did Step 4. You can confirm by
running the `--verify` command above by hand.

**It reports problems you think are fine.** Do not silence it by deleting the
sentence it complained about. Either the sentence is genuinely out of date, or a
setting needs adjusting. Both are worth knowing.

**Everything reports 0.** A setting is almost certainly wrong. See the settings
section above.

## More detail

For anyone who wants it, all under `plugin/skills/handoff/`:

| File | What is in it |
|---|---|
| `references/porting.md` | How to get the settings right for your project. Read this first. |
| `references/config.md` | Every setting explained. |
| `references/design.md` | Why each check works the way it does, and the real mistake behind each decision. |
| `SKILL.md` | What Claude reads. |

## What is in this repository

```
.claude-plugin/marketplace.json   lets Claude Code install this
plugin/
  .claude-plugin/plugin.json      plugin details
  skills/handoff/
    SKILL.md                      what Claude reads
    install.py, detect.py         the setup program
    payload/                      what gets copied into your project
    references/                   the documents listed above
tests/                            115 tests
NEXT_SESSION.md                   this project's own notes file
```

That last one is not decoration. This project uses its own tool on its own notes
file, and the automatic checks run it on every change. If it did not work, this
repository would be the first to know.

## A note for the curious

The one idea here worth taking somewhere else: when you write a rule that checks
something, **look at your real data first and write the rule to fit it**, rather
than writing what the rule ought to look like and hoping. Doing it the second way
produced 23 false alarms on the first project this ran against. Doing it the
first way produced none, and still caught the real problem.

And always report how many things you looked at. "Found no problems" and "did not
look" print exactly the same otherwise.

## License

MIT, which means you can use it freely, including commercially. See `LICENSE`.
