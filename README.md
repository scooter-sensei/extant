# handoff-validator

Machine-check the claims in your project's status document against git, before
they go stale and someone acts on one.

Long-lived status documents rot. A line that said "not yet merged" was true when
it was written and is a lie three days later. Nothing notices, because nothing
can: the file is prose. This tool makes the rot impossible to ignore by checking
every falsifiable claim in it against git and the filesystem, and refusing the
commit when one is false.

It was built for handoff documents that AI coding agents read as ground truth
(`NEXT_SESSION.md`, `AGENTS.md`, `STATUS.md`, `CLAUDE.md`), which is where the
cost of a false claim is highest: an agent has no independent way to know the
document is wrong, so it plans against fiction.

## What it checks

| Rule | The question it asks | Where |
|---|---|---|
| Dead commit references | does `git cat-file -e <sha>` succeed? | whole file, backticked and bare |
| Stale live claims | is the branch an ancestor of trunk, or gone? | newest entry only |
| False merge claims | is the claimed commit an ancestor of trunk? | whole file, archive included |
| Dead path pointers | does the referenced file exist? | operative references only |
| Secret shapes | does this look like a credential? | whole file |

### The core guarantee

**No rule inspects numbers or dates.** "The suite was 2238 at release 3" is a
historical fact: true when written, and never re-checked. This is structural
rather than a heuristic, and it is deliberate. Every rule must be answerable
yes or no by git or the filesystem.

The reason matters more than the rule: **a validator that cries wolf stops being
read**, which costs more than having no validator at all. A numeric cross-check
looks helpful and reintroduces exactly that failure.

## Install

### As a Claude Code plugin

```
/plugin marketplace add <GITHUB-USERNAME>/handoff-validator
/plugin install handoff@handoff-validator
```

That makes the `handoff` skill available. Ask Claude to set it up in a
repository and it will run the installer, derive the configuration, wire the
hooks, and render the `/handoff` command for that repo.

### Standalone, without Claude Code

The validator, the hooks, and the CLI have no dependency on Claude Code.

```sh
git clone https://github.com/<GITHUB-USERNAME>/handoff-validator
python handoff-validator/plugin/skills/handoff/install.py --repo /path/to/your/repo
cd /path/to/your/repo
sh tools/hooks/install
```

Either route copies the same files into your repository: `tools/`, the git
hooks, and a `.handoff.toml` derived from your repo rather than copied from
someone else's.

The installer does not copy another project's configuration. It **inspects your
repository** and derives one: trunk branch from `origin/HEAD`, branch naming
from a sample of up to 400 branches, commit grouping from up to 500 subjects,
and the document's own structure from its headers. Every value is reported with
its confidence:

```
  trunk         [derived ] origin/HEAD -> main
  branch_token  [derived ] 128 branches sampled; slash prefixes: feature/ x81
  entry_prefix  [guessed ] highest-scoring header '## Release'
  merge_claim   [unknown ] no 'verb ... target at <sha>' phrasing found
```

Anything it could not determine is written **commented out** rather than
guessed, because a pattern that matches nothing makes the validator exit 0
forever while looking healthy. That failure is the one this project is most
concerned with, and `references/porting.md` walks through deriving the rest by
hand.

## Usage

```sh
python tools/handoff_collect.py --verify              # check the committed doc
python tools/handoff_collect.py --validate DOC.md     # check a specific file
python tools/handoff_collect.py --collect --out b.json # gather facts, no prose
python tools/handoff_collect.py --archive             # rotate old entries out
```

`--verify` reports its **denominator**, not just its verdict:

```
checked STATUS.md: dead-sha 36, stale-live-claim 1, false-merge-claim 2,
  dead-path-pointer 5 (907 lines scanned for secrets)
```

A rule showing `0` examined is named explicitly. Read that as *investigate*,
never as *fine*: it means the pattern found nothing to check, so the rule is
inert whatever the exit code says. Distinguishing "found no problems" from
"never ran" is most of what this tool is for.

## Works with any language

The document validator is language-agnostic. Only the optional suite-collection
step runs your tests, and it takes a command:

```toml
suite_command = ["npm", "test"]     # jest, vitest
suite_command = ["cargo", "test"]
```

If the command does not mention `{python}`, no Python interpreter is needed for
it at all. Or skip running tests entirely and feed a result in from CI with
`--suite-json`.

## Claude Code integration (optional)

If you use Claude Code, the installer also renders a `/handoff` slash command
for your repo. It has a parent session write a friction summary from its own
context, then dispatches a subagent to collect facts, draft the entry, archive
old ones, validate, and **commit only if validation passes**.

Three deliberate constraints, each with a reason:

- **At most 2 validation attempts, and first-run findings must be reported**
  even if a later attempt cleared them. Otherwise the cheapest way to pass a
  validator is to delete the offending claim.
- **A red test suite does not block the commit.** A handoff that can only
  describe green states withholds the truth exactly when it matters most.
- **The archive is validated too.** Otherwise the tool could pass its own gate
  by relocating a false claim.

Everything except the drafting step is deterministic Python. The tool does not
need Claude Code: the validator, the hooks, and the CLI all work standalone.

## Git hooks

```sh
sh tools/hooks/install
```

- `post-commit` and `post-merge` re-check the document. **Both** are needed:
  git routes merges through `post-merge`, not `post-commit`, and a merge is
  precisely the event that turns "not yet merged" into a lie.
- `pre-commit` blocks commits made in the main working tree while it sits on a
  non-trunk branch. Optional, and worth reading before you accept it.

The hooks are advisory except the pre-commit guard, and they announce when they
cannot run instead of skipping quietly.

## Documentation

All under `plugin/skills/handoff/`:

| File | What is in it |
|---|---|
| `references/porting.md` | How to derive the configuration for a new repo. **Read before installing.** |
| `references/config.md` | Every configuration key. |
| `references/design.md` | Why each rule is scoped as it is, with the failure that forced it. |
| `SKILL.md` | The agent-facing entry point. |

## Repository layout

```
.claude-plugin/marketplace.json   makes this repo installable as a marketplace
plugin/
  .claude-plugin/plugin.json      the plugin manifest
  skills/handoff/
    SKILL.md                      what Claude reads
    install.py, detect.py         installer and repo inspection; never copied
    payload/                      what gets copied into your repo as tools/
    references/                   the documentation above
tests/                            115 tests, no network, no dependencies
NEXT_SESSION.md                   this project's own handoff document
```

`NEXT_SESSION.md` is not decoration. It is the corpus the test suite validates
against, and CI runs the tool on it, so the thing is exercised against a real
document rather than only against fixtures.

## Limitations, stated plainly

- It checks **falsifiable** claims. "Nearly finished" is unreachable by design.
- It assumes a **single trunk**. Gitflow with release branches is not modelled.
- It needs your document to have **consistent entry headers**. A wrong header
  silently excludes that entry from archiving and live-claim checking.
- It imposes two authoring rules: paraphrase past statuses rather than quoting
  them (the rules cannot tell a quotation from a claim), and write commit ranges
  as two separate backticked tokens.
- **The configuration must be derived for your repo.** Accept the defaults
  blindly and you get a validator that checks nothing, convincingly.
- No network access, so issue and pull-request links are not verified.

## The idea worth stealing

If you take nothing else: **derive validation patterns by measuring your real
corpus, never from what the wording ought to look like.** Applied three times
here, it gave a different answer than reasoning did every time. A path rule
keyed on what a path *looks like* would have produced 23 findings on the source
repository, every one of them a false positive. Keyed on what the reference is
*for*, it produced none and still caught the real defect.

And always print the denominator. "0 findings" and "0 examined" print
identically, and only one of them is good news.

## License

MIT. See `LICENSE`.
