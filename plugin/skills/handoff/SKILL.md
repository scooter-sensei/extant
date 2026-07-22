---
name: handoff
description: "Use when a project needs its session-handoff or status document to stay TRUE - a doc that says what shipped, what is merged, what is next, and that a fresh session reads as ground truth. Installs a validator that machine-checks every falsifiable claim against git before a commit is allowed, plus a /handoff command that drafts the entry and git hooks that re-check after every commit and merge. Also use when asked to port, install, or configure the handoff system in another repo."
version: 0.1.0
license: MIT
user-invocable: true
argument-hint: "[install|verify|port] [path to repo]"
---

# Handoff system

A status document that a fresh session reads as ground truth will decay, and the
decay is invisible until somebody acts on a false claim. This installs a
validator that makes the decay impossible to ignore.

Built and proven on a real repo where the handoff document had rotted to: a
false "not yet merged" claim about work that shipped three days earlier, 40 dead
commit references after a history rewrite, a pointer to a plan file that did not
exist, and 1,782 lines of unbounded growth that every session was instructed to
read end to end.

## What it installs

| File | Role |
|---|---|
| `tools/handoff_collect.py` | Collector + validator. Four modes: `--collect`, `--archive`, `--validate`, `--verify` |
| `tools/handoff_config.py` | All project-specific values; reads `.handoff.toml` |
| `tools/hooks/handoff-verify` | Re-checks the document after every commit and merge |
| `tools/hooks/install` | Installs the git hooks |
| `.claude/commands/handoff.md` | The `/handoff` slash command |
| `.handoff.toml` | Project configuration |

## Installing into a repo

```
python <skill>/install.py --repo /path/to/repo
cd /path/to/repo && sh tools/hooks/install
```

Then **derive the configuration from the real document - do not accept the
defaults blindly.** See `references/porting.md`. This is the step that decides
whether the tool works or silently does nothing.

## The five validation rules

Each checks a different KIND of statement, and each is scoped differently. The
scoping is not stylistic - getting it wrong produces either silence or noise,
and both destroy the tool's value.

| Rule | What it checks | Scope |
|---|---|---|
| Dead SHA references | every referenced commit still resolves | whole file, backticked **and** bare |
| Stale live claims | "not yet merged" about work that merged | **newest entry only** |
| False merge claims | "merged at X" where X is not an ancestor of trunk | whole file, **including the archive** |
| Dead path pointers | "Plan: X" / "see X" where X does not exist | operative references only |
| Secret shapes | credential-shaped tokens before they are committed | whole file |

## The core guarantee, and the discipline that protects it

**No rule inspects numbers or dates.** A statement like "the suite was 2238 at
release 3" is historical: true when written, never re-checked. This is
structural, not a heuristic - there is no rule that could flag it.

Do not add one. A numeric cross-check looks helpful and reintroduces false
positives, and **a validator that cries wolf stops being read**, which costs more
than having no validator at all. Every rule must be falsifiable against git or
the filesystem, or it does not belong.

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
