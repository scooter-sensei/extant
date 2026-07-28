# Porting: deriving the config from a real document

**The single way this system fails silently is a config copied rather than
derived.** The patterns shipped as defaults were measured against one specific
repo's documents. Point them at a project that phrases things differently and
they match nothing - the validator exits 0 forever and looks healthy.

That failure is worse than not installing it, because it manufactures false
confidence in a document nobody is checking.

## Does this project even want it?

Two requirements, and two things that unlock extra rules but are not needed
to install:

1. **A document to check.** Any markdown will do - a README, a CONTRIBUTING
   file, an architecture note. Requiring a dedicated status file was the
   single largest barrier to using this and was never a real requirement.
2. **Git**, with a known trunk branch name.

Optional, and only for the features that need them:

- **Entry-structured, newest-first** documents, for archiving and the
   live-claim rule. Without them those two are skipped and the rest still run.
- **A test suite** whose output has a parseable pass/fail count, for
   `--collect`. Nothing else needs it.

A project with a conventional CHANGELOG and no phase cadence gets the
reference-validation and secret-scan and little else. That may still be worth it
- but decide deliberately rather than installing on autopilot.

## The derivation procedure

Run this against the target repo before writing any config. Each step is a
measurement, and each answers one config value.

### 1. Name the documents

```
primary_doc   = "NEXT_SESSION.md"          # what sessions actually read
archive_doc   = "docs/status-archive.md"  # where old entries go
```

### 2. Find the entry header shape

```bash
grep -oE '^#{1,3} [A-Za-z]+' <doc> | sort | uniq -c | sort -rn | head
```

The most frequent repeated header prefix is `entry_prefix`. It must identify
**entries specifically**, not every section - reference sections interleaved
among entries must NOT be classified as entries, or archiving will move
reference material out of the live document.

Then find the boundary where per-entry history stops and stable reference
material begins; that regex is `base_header`. Everything from there down is
never archived.

### 3. Derive the merge-claim pattern - measure, do not guess

```bash
grep -ohiE '.{0,50}(merged|shipped|released|landed)[^.]{0,60}' <doc> \
  | grep -E '`?[0-9a-f]{7,40}`?' | sort -u
```

Read the output. Write a pattern that matches the phrasings actually present,
and **require the SHA to follow the phrase**. In the source corpus, one line
read "branched from main @ `a1fc502` (the docs landed directly on main first)"
- the SHA belongs to a different claim, and requiring it to follow is what
excludes it.

If a claim states no target branch it cannot be falsified against trunk; do not
try to match it.

### 4. Derive the path-pointer markers

First measure the false-positive risk, which is the whole reason this rule is
scoped the way it is:

```bash
# every backticked path-shaped token, and whether it exists
grep -oE '`[\w./-]+\.(py|md|ts|go|rs|java)`' <doc> | tr -d '`' | sort -u \
  | while read -r p; do [ -e "$p" ] || echo "MISSING: $p"; done
```

Expect many missing paths. In the source repo, **23 of 88 did not exist and all
23 were legitimate** - layout of a completed phase, deferred work never built,
files explicitly described as deleted.

So do **not** key on path shape. Key on the markers that introduce a path as a
pointer - `Plan:`, `Design:`, `see`, `read` - and check only those. Confirm your
pattern by running it and getting **zero** findings on a document you believe is
currently correct.

### 5. Derive the live-status phrases

```bash
grep -ohiE '.{0,40}(not yet merged|awaiting|pending|unmerged|in progress).{0,40}' <doc> | sort -u
```

Keep the set **small and closed**. Widening it to anything that sounds like a
status claim reintroduces false positives. Remember older entries legitimately
contain past statuses - that is why the rule is scoped to the newest entry only.

### 6. Branch token and trunk

```
trunk        = "main"
branch_token = '`((?:claude|feature|feat)/[^`]+)`'
```

`branch_token` must match how branches are written **in prose** in that document.

## Validating the derived config

```bash
python tools/extant_collect.py --verify
```

**Exit 0 alone is not good news** - it means the document is clean *or* your
patterns match nothing. So `--verify` prints the denominator behind the verdict:

```
checked NEXT_SESSION.md: dead-sha 36, stale-live-claim 1, false-merge-claim 2,
  dead-path-pointer 5
```

Read those counts before the exit code. A rule that examined zero candidates is
called out on a `NOTE:` line, and is either genuinely absent from that project's
prose or a broken pattern. Know which - an inert rule reports "clean" forever.

Then prove the rules fire: temporarily introduce a false claim - repoint a merge
claim at a commit that is on no integration branch - and confirm it is reported.
A rule never observed failing has not been tested.

**Confirm the edit landed before reading the result.** A substitution that
silently missed leaves the document correct and the run clean, which is
indistinguishable from a rule that noticed nothing. `git diff` the document,
or assert the new text is present, and only then interpret the output. This
project has mistaken a failed setup for a passing check more than once.

## After installing

- `sh tools/hooks/install` - wires `post-commit` and `post-merge`. **Both are
  needed**: git routes merges through `post-merge`, *not* `post-commit`, so a
  post-commit-only hook misses exactly the case where a merge falsifies a claim.
- Add the entry-header contract to the `/extant` command text. An entry with the
  wrong header is silently invisible to archiving and live-claim checking.
- Tell authors: **paraphrase past statuses, never quote or strike them through.**
  The rules cannot distinguish a quotation from a claim.
