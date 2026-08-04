---
name: extant
description: "Use when documentation cites things git can settle and may have gone stale - a commit SHA, a merge claim like 'merged to main at abc1234', a branch name, a release tag, or a file path. Especially for the plan, spec, design and status documents written during agent sessions, which are dense with commit references and are read back as fact by the next session. Installs a validator that machine-checks every falsifiable claim against git and the filesystem, git hooks that re-check after each commit and merge, and a --sweep mode that surveys every tracked markdown file with no configuration. Also use when asked to port, install, or configure this validator in another repo."
version: 0.17.2
license: MIT
user-invocable: true
argument-hint: "[install|verify|port] [path to repo]"
---

# extant

Documentation cites commits, branches, tags and paths. Those citations decay
silently, and the decay is invisible until somebody acts on one. This installs a
validator that makes it impossible to ignore.

**Where it pays off most is the documents agents write.** Plans, specs, designs
and status files are dense with commit SHAs and merge claims, get written once,
and are read back as fact by the next session - which cannot tell an expired
line from a current one, so it plans around something untrue.

Measured on one real project: 49 tracked markdown files, 43 findings, of which
**42 were dead commit references**, and every located finding sat in the plan and
spec directories rather than in the README or CONTRIBUTING. The human-facing
docs were fine. The machine-facing ones had rotted where nobody looks.

**It needs no special document,** and works on any markdown: a README, a
CONTRIBUTING file, an architecture note. Requiring a dedicated status file was
the largest barrier to using this and was never a real requirement.

It handles that shape too, and was built on one: a real repository whose status
document had rotted to a false "not yet merged" claim about work that shipped
three days earlier, 40 dead commit references after a history rewrite, a pointer
to a plan file that did not exist, and 1,782 lines of unbounded growth that every
session was told to read end to end.

## What it installs

| File | Role |
|---|---|
| `tools/extant_collect.py` | Collector + validator. Modes: `--sweep`, `--validate`, `--verify`, `--deleted-since`, `--search`, `--collect`, `--archive`, `--selftest`. Counted from the parser, never written out here: this line said "Six modes" while listing six and omitting `--search`. |
| `tools/extant_config.py` | All project-specific values; reads `.extant.toml` |
| `tools/hooks/extant-verify` | Re-checks the document after every commit and merge |
| `tools/hooks/main-tree-guard` | OPT-IN pre-commit guard, wired only by `sh tools/hooks/install --with-trunk-guard`. Refuses a commit in the main working tree while it is off trunk. The ONLY component that can block anything, so never enable it on a user's behalf. |
| `tools/hooks/install` | Installs the git hooks |
| `.agents/skills/extant/SKILL.md` | Agent-facing instructions at the Agent Skills standard path, read by Codex, Gemini CLI, Copilot, Cursor and Kimi as well as Claude. Rendered for the repo. |
| `.claude/commands/extant.md` | The `/extant` slash command, rendered for this repo. The ONLY Claude-specific file, and the only one written conditionally: it appears when the repo already has `.claude/` or a `CLAUDE.md`, and `--claude-command` / `--no-claude-command` decide it outright. Everything else above is agent-neutral. |
| `.extant.toml` | Project configuration |

**`--sweep` is the first command to run in an unfamiliar repository.** It needs
no configuration, reads every `.md`, `.markdown`, `.mdx` and `.rst` file git
tracks, and separates documents
the config names from documents it does not. Only the first kind decides the
exit code: measured on this repository, checking every markdown file produced 18
findings and every one was false, because the documents that DOCUMENT the rules
are full of example claims like `abc1234`. So the unreviewed half is surveyed
and reported, never gated on. Promoting a file into `extra_docs` is what turns a
survey into a gate, and is the intended adoption path.

`--deleted-since REF` reports claims that were present at REF, are still
false today, and are no longer written down anywhere. It ALWAYS exits 0.

That is deliberate, not caution. Whether a removal was evasion or repair is a
question about intent and git cannot settle it - a document that deletes a
false claim now tells the truth, which is the whole point of the tool, so a
gating rule would fail a build on the correct fix. Use it in review, not as a
gate.

It defaults to `HEAD~1`, which answers "what did this commit remove" and is
right for a post-commit hook. In CI pass the merge base instead, or a removal
split across two commits hides from it. Relocating an entry to the archive is
not a deletion, because the token stays findable; moving a claim into a code
fence IS one, because a fence exempts it from every other rule.

`--search TEXT` finds past entries in the live document and the archive
together, returning whole entries. `--suggest-fixes` prints a patch repointing
references at files git recorded as renamed; it writes nothing, and stdout
carries only the patch so it can be piped to `git apply`.

`--validate`, `--verify`, `--sweep` and `--deleted-since` take `--format=text` (default), `--format=github`
for Actions annotations, or `--format=sarif`. SARIF puts nothing but JSON on
stdout; every human diagnostic moves to stderr.

**Adopting on an old repository.** `--write-baseline` records every current
finding once; `--baseline` then checks only NEW claims. Use it when the first
run reports a wall of findings on documentation nobody has time to fix today,
which is the normal state of a long-lived project. The suppressed count is
printed on every run, nothing is ever recorded implicitly, and `--baseline-check`
reports entries whose finding no longer occurs so an amnesty cannot outlive it.
Never write a baseline on a user's behalf to make a run pass.

## Installing into a repo

```
python <skill>/install.py --repo /path/to/repo --preset readme
cd /path/to/repo && sh tools/hooks/install
```

Presets: `readme` (any project, no status file needed), `node`, `python`,
`rust`, `go`, `jvm`, `k8s`, `terraform`, `docker`, `monorepo`, `mobile`,
`unity`, `godot`, `agent`, `enterprise`, `ml`, `legacy-web`, and `status` (a
running status document). A preset chooses the documents and the shape; detection still
supplies trunk, branch naming and commit conventions, because those are
measured rather than assumed.

`agent` covers `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and
`copilot-instructions.md` - the files an agent reads as fact, where a dead path
becomes confidently wrong work rather than a puzzled human.

Several presets deliberately carry NO cross-file check, because the two files
that look like they should agree are documented as independent: Helm's
`appVersion` against its chart `version`, Terraform's `required_version`
constraint against a `.terraform-version` pin, Go's minimum `go` directive
against an exact `toolchain`, and a mobile `versionCode` against the marketing
version. Do not add them.

**Most projects want `readme`.** Requiring a status document to exist was the
single largest barrier to using this at all, and it was never a real
requirement: the rules work on any markdown.

Then **derive the configuration from the real document - do not accept the
defaults blindly.** See `references/porting.md`. This is the step that decides
whether the tool works or silently does nothing.

## The eleven validation rules

Each checks a different KIND of statement, and each is scoped differently. The
scoping is not stylistic - getting it wrong produces either silence or noise,
and both destroy the tool's value.

| Rule | What it checks | Scope |
|---|---|---|
| `dead-sha` | every referenced commit still resolves | whole file, backticked **and** bare |
| `stale-live-claim` | "not yet merged" about work that reached an integration branch | **newest entry only** |
| `unknown-branch` | a branch git has never seen, in refs or any merge commit | **newest entry only** |
| `false-merge-claim` | "merged to X at Y" where Y is not an ancestor of **X** | whole file, **including the archive** |
| `dead-release-tag` | "released in v2.1" where the tag is on no integration branch; also where it is missing, when `release_claims_name_our_tags` is set (the installer sets it) | whole file |
| `dead-path-pointer` | "Plan: X" / "see X" where X does not exist | operative references only |
| `dead-md-link` | `[text](path)` whose file is gone | whole file |
| `dead-md-anchor` | `[text](#fragment)` and `[text](other.md#fragment)` with no such heading | this document, and any linked file that resolves |
| `dead-pinned-ref` | an install snippet pinning a version of THIS repo that does not resolve | whole file, **inside code** |
| `raw-lfs-blob` | a file `.gitattributes` routes through LFS, stored as a raw blob | repository |
| `inconsistent-artifact` | configured files that state DIFFERENT values for the same thing | repository |

`inconsistent-artifact` is the one rule that reads no document. It compares
files against EACH OTHER, which is why it does not breach the no-numbers
guarantee: the forbidden question is whether a value is correct, and this asks
whether two artifacts contradict each other. Off unless `[extant.consistency]`
is configured.

**More than one integration branch is normal, and one configured trunk was not
enough.** A merge claim names its own ref - "merged to `develop` at `abc1234`"
says which branch it means - so that is what gets checked, which needs no
configuration and is more precise than comparing against a single trunk. The
two rules that cannot name a ref, `stale-live-claim` and `dead-release-tag`,
ask about the integration branches this repository actually has: the configured
trunk plus whichever of `main`, `master`, `develop`, `development` and `trunk`
exist.

Measured on a gitflow repository, the old single-trunk question was wrong in
both directions at once. With `trunk = main` a FALSE claim about develop was
never examined, because the pattern interpolated the trunk name and did not
match. With `trunk = develop` a genuinely shipped `v1.0.0` was reported dead,
because the tag sits on main's release merge. Neither setting was correct, so
the fix was not a longer trunk list.

Three cross-cutting behaviours worth knowing:

- **Fenced code is exempt from claim rules.** An example in a fence is not a
  promise. Inline backticks are kept for claim rules, because claims are
  written inside them, and blanked for link rules, because example links are
  too. The single exception is `dead-pinned-ref`, which reads inside code
  precisely because an install snippet is copied verbatim rather than read as
  an example, and checks only pins whose `repo:` names the repository being
  validated.
- **Wrong-case paths are reported** even on Windows and macOS, by comparing
  against the real directory entry. Otherwise a document passes on a laptop and
  fails on Linux CI.
- **A dead pointer says where the file went**, when git recorded a rename.

`extra_docs` extends the whole-file rules to a `CLAUDE.md`, `AGENTS.md` or
README. The entry-scoped rules are skipped there, since those files have no
dated entries.

## Proving the rules actually work

```
python tools/extant_collect.py --selftest
```

Corrupts one REAL claim per rule and reports which rules noticed. A rule that
stays silent after its own probe is not working. A rule may instead report
NO PROBE, meaning the repository offered nothing safe to corrupt - no claim of
that kind exists here. That is an expected outcome rather than a failure, but
it is not evidence the rule works either, which is why it is printed rather
than folded into the pass count. Probes mutate the project's
actual prose rather than injecting invented text, so what is exercised is this
configuration against this writing; a synthetic probe written in the default
vocabulary would only prove the defaults match the defaults.

This is the answer to the failure the whole design fears: a pattern that matches
nothing exits 0 forever and looks healthy. `--verify` reports a denominator per
rule; `--selftest` proves the rules fire.

## The core guarantee, and the discipline that protects it

**No rule judges whether a number or date is CORRECT.** A statement like "the
suite was 2238 at release 3" is historical: true when written, never re-checked,
and there is nothing to check it against. This is structural, not a heuristic.

Do not add such a rule. A numeric cross-check looks helpful and reintroduces
false positives, and **a validator that cries wolf stops being read**, which
costs more than having no validator at all.

`inconsistent-artifact` is not an exception, and the distinction is worth
holding precisely. It never asks whether a version is right. It asks whether two
files in the repository state DIFFERENT values for the same thing, which has a
definite answer that needs only the filesystem. Every rule must be falsifiable
against git or the filesystem, or it does not belong.

## Read before changing anything

- `references/design.md` - why each rule is scoped as it is, with the incident
  behind each decision. Read this before adding or widening a rule.
- `references/porting.md` - how to derive the configuration from a real
  document. **Read this before installing into a new repo.**
- `references/config.md` - every configurable value.

## The one rule that generalises beyond this tool

**Derive validation patterns by measuring the real corpus, never from what the
wording "should" be.** Applied three times here, each time producing a different
answer than reasoning would have:

- A path rule keyed on *shape* would have emitted 23 findings on the source
  repo, every one false - historical layout, deferred work, files explicitly
  described as deleted. Keyed on *operative use* it emits none.
- The merge-claim pattern matches that repo's actual phrasing. A different
  project writing "shipped in v2.1 (abc1234)" matches nothing.
- Live-claim scoping had to be narrowed to the newest entry, because older
  entries legitimately record their own past statuses.

Check what a reference is **for**, not what it looks like.
