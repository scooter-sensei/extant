# Changelog

## Unreleased

Nothing here adds a rule or a flag. The first half is correctness - a
denominator that lied, a document shape that lost its rules, a mode that
crashed where its siblings refuse. Most of those were found by the fuzz harness
rather than by a person reading the code; four came the other way, from a
review of the git seam, the settings load and the one irreversible file write -
each then reproduced and watched failing before it was fixed.

The second half, under "What a commit pays", is cost rather than correctness,
with one behaviour change that says so in its own heading.

**Six denominators counted sites their rules refuse to judge.** The quiet
direction of this project's recurring defect, and the worse of the two: a
denominator that overstates reports coverage on a run with no findings at all,
and nobody investigates a clean run. `dead-md-link` counted `@ref` macros and
`.html` targets, both refused whatever is on disk, so a document made only of
them printed `dead-md-link 2` beside no findings. `stale-live-claim` counted
branch tokens in an entry making no live claim, having returned before reading
one. `false-merge-claim` counted claims whose commit does not resolve, which
`dead-sha` owns - 5 over this repository's own status document where the rule
could settle 3. `dead-release-tag` counted unresolvable versions with
`release_claims_name_our_tags` off, which is the default.

**And two printed a finding beside "examined nothing"**, which is the loud
direction of the same thing: the run named a rule that had just spoken among
those that never looked. `dead-md-anchor` judged cross-file fragments while its
denominator counted only bare `#fragment` links, so a document whose one anchor
link pointed at another file reported found=1 against examined=0. The two
passes are one now. `manifest-floor-mismatch` was right and the survey lost the
file's path.

**`--sweep` ran the repository-scoped rules twice.** One raw blob under an LFS
filter printed twice - bare, and again under `.gitattributes:` - against a
denominator that counts the governed file once. `inconsistent-artifact` is the
same shape and did the same. Attributed to the file that answers rather than
de-duplicated, because the two copies were not interchangeable and suppressing
the second would leave the rule running twice and free to disagree with itself.

**A carriage-return-only document lost two rules entirely.** `^` in a multiline
pattern follows a newline, and a bare `CR` is not one, so `split_entries` found
no sections and every rule reading the newest entry examined zero candidates.
Measured on one document written twice: LF reports `stale-live-claim 2,
unknown-branch 2`, and CR-only reports 0 and 0 - printed beside every other
rule's honest count, where a reader takes them to mean the document makes no
such claims. It makes two. The normalisation is length-preserving, because
collapsing `CRLF` as well would shift every offset computed against the result.

**Three modes crashed where every sibling refuses by name.** All three exited
with a traceback instead of a sentence, and all three now print the same one:

- `--archive` on a document that is not UTF-8, which is the one mode that
  rewrites the document. Nothing had been written when it raised, so the file
  was intact either way - but that crash is indistinguishable from one that
  failed halfway through a rewrite.
- `--search` on the same input, out of `codecs`. It names WHICH of the two
  documents it reads failed rather than guessing, since naming the wrong file
  is a false claim about the repository.
- `--sha-map` naming a map that is not there. The invocation in the README
  names a path that does not exist until somebody has run `git filter-repo`,
  so this is the ordinary way to reach the flag rather than an exotic one.
- `--archive` again, by a second route: `primary_doc` naming a document that
  is not there. It reports which setting is wrong and where it was read from,
  because "no such file" alone does not say whether the config or the document
  is the thing to fix.

One encoding now gets one answer across `--validate`, `--verify`, `--archive`
and `--search`.

**Every finding now says what KIND of document it came from.** A first
`--sweep` over 50 pinned public repositories prints 54,790 findings, and 4,431
of them are in ordinary documents. The other 92 per cent come from four kinds
of tree a reader would not call documentation-with-claims: per-release
snapshots, changelogs and machine-written allowlists, vendored code, and
generated API references. `bazelbuild/bazel` keeps twelve per-release copies of
one documentation tree, so a single dead link written once is reported twelve
times.

A new module, `extant/strata.py`, maps a path to one of five names -
`vendored`, `version-snapshot`, `generated`, `historical-record`, `ordinary` -
and `Located` carries the answer. The sweep summary leads with the ordinary
count and breaks the rest out with a denominator on every row; each SARIF
result carries `stratum` in its `properties` bag beside `gates`, so code
scanning can filter without the tool having decided for it.

- **Labels, not exclusions.** `exclude_paths` hides; a stratum labels. A rule
  that goes quiet because a tree was excluded is indistinguishable from a rule
  that broke, which is the ambiguity the denominator exists to remove. Nothing
  disappears from the output: every finding is still reported and still
  counted.
- **Exit codes are unchanged.** `--sweep` already reported without gating,
  which is where the problem lives, and a project that has deliberately
  configured a CHANGELOG as an `extra_doc` should keep gating on it.
- **Baselines are unaffected.** The field is on `Located` and not on `Finding`,
  because the baseline fingerprint hashes `(path, kind, detail)` off `Finding`.
  A baseline that stops matching does not fail loudly; it quietly re-raises
  findings a project agreed to leave alone. Nothing recorded anywhere is
  invalidated.
- **Configuration does not solve this**, which is why it is not left to
  configuration. Three configuration passes over the same corpus moved the
  headline by under one per cent, and `install.py` refuses 35 of those 50
  repositories unaided, so the settings that would fix it never get written.
  Whether a tree is vendored or a per-release snapshot is visible FROM THE
  REPOSITORY.

**The historical-record pattern reads every suffix the sweep reads.** It was
anchored on `.md` and `.mdx` while the sweep gathers `md`, `markdown`, `mdx`
and `rst`, so reStructuredText changelogs were counted as ordinary - the one
stratum that matters most. A changelog-shaped DIRECTORY still does not make its
contents historical: `Misc/NEWS.d/` in cpython stays ordinary on purpose,
because a directory called `news/` is very often a live blog, and a suppression
that fires wrongly deletes signal silently.

**The git seam returned None on Windows and raised on POSIX, out of one line.**
Every git command ran with `text=True`, which decodes inside `subprocess` - and
inside `subprocess` is not one place. Windows decodes on a reader thread, so a
byte that is not valid UTF-8 kills the thread and `communicate()` hands back
None; POSIX decodes in the caller's thread and raises `UnicodeDecodeError`.
Neither is catchable by `soft()`, which is documented to return the empty
string rather than raise. The reachable case is a PATH, not a commit message:
`tracked_markdown` decides which documents a sweep reads AT ALL and runs
`ls-tree -r -z`, whose `-z` turns off the escaping that would otherwise render
unusual bytes as ASCII. Against a repository holding one tracked file whose
path is not valid UTF-8, `--sweep` exited with `AttributeError: 'NoneType'
object has no attribute 'split'`. Bytes are captured and decoded in the caller
now, keeping the newline translation `text=True` performed, verbatim.

**`--collect` lost a suite measurement to the same line.** `suite_command` is
configured, so what it decodes is some other project's test runner writing
whatever its console encoding is - the least predictable text this package
reads. On Windows a runner printing in the console codepage produced None where
the summary should have been.

**A configured pattern that will not compile now names itself.** `re.error` is
not a subclass of `ValueError`, so nothing guarding a configuration load caught
one, and what reached the operator was a character position inside a pattern
they never see. Settings load at import, so the traceback arrived out of the
package before any mode had begun, for a typo in theirs. Ten settings route
through one helper now, beside the consistency block that always did.

**`--archive` wrote the destructive file first.** The conservation check proves
the two output texts hold every input line, which is a property of two strings
in memory; it says nothing about a process that dies between the two writes.
Truncating the primary first left a window in which the retired entries were in
NEITHER file - the outcome that function exists to make impossible, by a route
its own guard cannot see. The additive write goes first now, so the same crash
duplicates them instead, and a duplicate is something a reader can repair.

### What a commit pays

The rest of this release is cost rather than correctness, with one exception
that is marked as one. Every figure below was measured on the development
machine - Windows, git 2.53.0, 12 cores - and says how. None of it was measured
on Linux, where a process spawn is far cheaper and most of this would not
register.

The measurement that started it: a `--verify` over this repository took 1477 ms
and started 24 git processes, where one `git rev-parse` costs 28.27 ms (median
of 20). It now takes 729 ms and starts 5, which is about 39 ms per spawn
removed. That command runs from a git hook after every commit.

**Five is a developer checkout; a CI runner still starts 8.** A GitHub Actions
checkout carries four `[includeIf "gitdir:..."]` sections and a
`config.worktree`, and either alone is enough for the config read below to
decline and fall back to the spawn. Nineteen of the twenty-four go everywhere;
the last five go where the config is one this can read.

**A `--verify` over this repository spawns five git processes, down from 24.**
Fourteen of the nineteen were `rev-parse --verify --quiet refs/tags/vX^{commit}`
asking a question the ref table already held: `resolve_ref` tried that table
first, but it is keyed by SHORT name while `dead-release-tag` asks with a
QUALIFIED one, so every lookup missed by construction. A qualified ref now
resolves from the matching table - `refs/tags/x` from tags, `refs/heads/x` from
heads, never from either, which on a repository carrying both would be a
different commit. A table MISS still falls through to git, because raw SHAs,
`HEAD` and `main~3` are legitimate inputs no table holds. `dead-pinned-ref`
asks `resolve_ref` rather than running its own `rev-parse`, which is the same
question with the same tags-before-heads precedence git uses.

**BEHAVIOUR CHANGE: a tag pointing at a tree or a blob resolves to nothing.**
The ref table's own docstring claimed `%(*objectname)` is "the same dereference
`^{commit}` performs". It is not. A tag may name any object, and for one naming
a tree or a blob `^{commit}` resolves to nothing while the peel yields the
tree's or the blob's id - not a commit, and in no rev-list. The table now reads
`%(objecttype)` too and records a ref only when what it would return IS a
commit. The divergence predates this release and applied to bare names already;
widening the table to qualified refs would have widened it too. Such tags are
legal, rare, and invisible to a generated corpus, so `fuzz --differential`
cannot demonstrate this one and a test builds them with `hash-object` and
`mktree`.

**The remaining five `remote get-url origin` calls became a file read.**
`--verify` opens one RunScope per document, so this repository-level fact was
asked once per file. Sharing one scope across documents would have recovered it
and traded away a lifetime the scope objects exist to state - the same
`own_remote` that once answered None forever and left `dead-pinned-ref`
examining nothing. Reading `remote.origin.url` out of the config costs 0.19 ms
(median of 200) against 28.92 ms to spawn (median of 20), and changes no
lifetime at all. It is read, VALIDATE, or fall
back: `configparser` is not a git config parser and disagrees with git about
quoted values and inline `#` and `;` comments, each disagreement surviving into
a wrong `owner/name`, so any value carrying a quote, a comment character, a
backslash or whitespace falls through to the spawn. So does a config using
`insteadOf` or `include`, or a worktree with a `config.worktree` of its own.

**A line number is a bisection rather than a rescan.** `line_number_at` counted
line breaks from position 0 on every call, and both callers ask once per claim
inside a loop - m claims over n characters is O(m*n), which is why the two
slowest rules on a large document were the two that ask for one. The break
positions are computed once per document and each lookup binary-searches them.
Counting breaks that START before the offset is what makes that equivalent:
`findall(text, 0, offset)` restricts the search region, so an offset landing
between a CR and its LF used to cut the pair in half and match the CR alone.
Measured over this repository's own status document, doubled: at 17,368 lines a
whole `--validate` costs 1399 ms against 5434 ms, and eight times the document
now costs 1.53x rather than 3.51x.

**`--verify` no longer imports a worker pool it cannot use.** `sweep.py`
imported `concurrent.futures` at module scope and `cli.py` imports `sweep`, so
every hook-driven `--verify` paid 20.7 ms for machinery only `--sweep`
reaches - whole-interpreter wall time, median of 9, against a bare interpreter
at 36.3 ms and `extant.cli` at 159.2.
It is imported inside the parallel path's existing `try`, where an ImportError
joins every other reason a pool can fail to start: fall back to the sequential
survey, and say so.

**Four of the hook's five helper processes are gone.** About half of what a
commit pays for the hook is scaffolding rather than validation - measured with
the current hook, median of 7: 57 per cent on a clean document, 49 on one with
findings. The two largest addressable pieces both spawned processes to do work
POSIX shell can do with none. Per call, median of 40 under `sh`: reading
`primary_doc` cost 91.2 ms through `sed` piped to `head` and costs 1.6 ms as a
`while read` loop that sets a variable rather than being read back through a
subshell; formatting findings cost 158.9 ms through `grep -c`, `head` and
`sed`, and costs 69.9 ms with `head` and `sed` replaced by parameter expansion.
End to end the hook goes from 706 ms to 576 on a clean document and from 849 to
643 on one with 40 findings, printing byte-identical output.

**That second one keeps its `grep`, and the reason is the interesting part.**
The first version replaced all three processes by reading the output through a
here-document, which is faster still - and which, under the `dash` that ships
with Git for Windows, silently returns NOTHING above about 4 KB. Measured with
the here-doc inside a shell function: 2691 bytes reads back every line, 5491
bytes reads back none, so the hook would report "0 unverified claim(s)" on a
document full of them while `--verify` had exited 1. Counting every line with
no process at all is correct at every size and quadratic - 2952 ms at 2000
lines, 19 seconds at 5000 - so the work is split by what each half needs: the
listing needs five lines and uses parameter expansion, the count needs every
line and uses the one `grep` process that is correct at any size.

The divergence tables are built from the shipped commands and run under `dash`
as well as Git Bash, and they now span SIZES as well as syntax. Their absence
is what let the above through: every sample was under 600 bytes, so nine cases
reported zero divergences while agreeing only about small inputs.

The hook's own cost model was out by about 3.5x - it priced a Windows
subprocess at "roughly 90 ms" where a bare `sh -c :` measures 28.75 ms and a
`git rev-parse` 28.27
- and that number is corrected beside the decision it justifies, which is still
the right one.

Two changes were measured and REFUSED. Sourcing `extant-verify` with `.`
instead of spawning `sh` saves most of that 28.75 ms, and the installer
APPENDS its block to
whatever hook already exists while `extant-verify` exits early in a dozen
places - sourced, those exits would terminate the parent hook and silently skip
anything another tool installed after it. And `branch_exists` still asks
`rev-parse`, which follows git's tags-before-heads precedence and so answers
True for a tag named like a branch; answering from the heads table would be
arguably more correct and certainly not neutral, which makes it a behaviour
question wearing a performance fix's clothing.

**The suite runs in parallel, and its fixtures are built once.** `pytest-xdist`
is a development dependency now - the tool still has none - and `-n auto --dist
loadfile` takes the suite from 6m26s to 1m58s on 12 cores, over 963 tests. It
is an invocation rather than a default: `pytest.ini` is untouched, so the
serial run stays the definition of correctness. The repository fixtures are
built once per session and copied per test rather than rebuilt - 113.4 ms to
build the base shape against 30.1 ms to copy it (median of 12), and 1358.7 ms
against 80.3 ms for the gitflow one (median of 6).

One alternative was expected to be slower and is not. Building with an
environment dict instead of two `git config` calls measures 53.4 ms, about half
the fixture as written, where handing `subprocess` a large environment on
Windows was supposed to cost more than the spawns it saves. It is still not
what is used, because copying is faster again and removes the last spawn too -
but a claim that did not reproduce is corrected here rather than repeated.

## 0.25.0 (2026-08-31)

Four features, and the one that matters most is not a new rule: **a dead SHA
now tells you what replaced it.**

**`dead-sha` reads the commit-map a history rewrite leaves behind.** Measured on
a real agent-written project held out from every corpus here: it carries 12
distinct dead SHA references, and asked the obvious way - `rev-parse`,
`cat-file`, every reflog, `fsck --unreachable` - all 12 answer "never present
anywhere in this clone", which reads as invented. All 12 are in
`.git/filter-repo/commit-map`, a file git wrote during a trailer purge and left
in place. So the dominant cause of this project's largest finding class is a
history rewrite, the answer was already on disk, and nothing looked:

```
line 14: [dead-sha] `77afb4e` does not resolve in this repo; the rewrite map records it as `d60aac9`
```

Finding the map repairs nothing. `--sha-map` remains the explicit opt-in for
rewriting a document, because a validation run that edited prose on its own is
the authoring this tool refuses. The map is read once per run and only when a
SHA is already dead, so a clean document never opens a file with one line per
commit, and lookups are bucketed on seven characters - unbucketed, a 200,000
entry map cost 4,112 ms for 200 dead SHAs against 704 ms for one.

The replacement rides outside the baseline fingerprint. **No recorded baseline
stops matching**, which it would if this were folded into the finding's detail:
the hint varies with the CHECKOUT rather than the document, so a repository that
acquired a map would otherwise re-report every `dead-sha` a baseline had already
forgiven.

**`--check-text` checks a document that is not on disk yet**, from stdin, with
the same rules, denominators, formats and baseline as `--verify`. It is the
primitive under anything wanting an answer before a file exists. Pass
`--as-path` with it: without a location the filename-keyed rules cannot answer,
relative links resolve against the repository root rather than the document's
own directory, and the markup falls back to markdown. That narrowing is stated
on its own line rather than left to look like a clean pass. It refuses
`--write-baseline` and `--baseline-check`, which judge the whole recorded set
and would wreck it from one document, and `--format=sarif` requires
`--as-path`, because SARIF locates every result by a URI and `<stdin>` is not
one.

**A `post-rewrite` hook**, because a rewrite renames every commit at once and
nothing fired at that moment: `post-commit` is suppressed while a rebase
replays commits and `post-merge` never sees one. It needed its own entry point,
measured on git 2.53.0 rather than assumed - `rebase-merge/` is still present
when `post-rewrite` fires, so the existing rebase-state guard would have skipped
the one hook that exists to catch it. Its limits are recorded beside it: after a
LOCAL rebase the old commits still resolve through the reflog, so the check
correctly reports nothing until a `gc`. Real value for `filter-repo`, deferred
for rebase.

**A published GitHub Action**, over the `github` annotation format that has
existed since 0.20.0. It carries no version of its own - it installs the ref you
pinned - and every input arrives through `env:` rather than being interpolated
into a shell script, which is the documented Actions injection hole.

**Internally**, the gating modes moved to `extant/gate.py`, the counterpart to
`extant/sweep.py`: `run_validate` had reached 295 lines against a 303-line
ceiling and could not be split while a nested closure held four locals
together. Those became `report.Collector`. `extant.cli.suggest_renames` is now
`extant.gate.suggest_renames`, the only importable name that moved. The split
was checked rather than asserted - the payload before and after, one fixture,
nine invocation shapes including the baseline triple and SARIF, byte-identical
output - and nine mutation anchors were retargeted and re-run: 9 killed, 0
survived.

`--sha-map` is documented for the first time. It has existed since 0.14.0 and
was named exactly once in this repository, in a release note.

## 0.24.1 (2026-08-30)

Two fixes, both to checks that reported something other than what they had
actually checked. No feature changes, and no finding changes for a document
written with LF or CRLF line endings.

**`dead-release-tag` now reads a release claim that wraps a line, so you may
get findings you did not get before.** They are claims that were always false
and were never examined. The rule had three readers of one pattern and two
different scans: `examined` and the selftest probe searched the whole document
while the check - the only one that decides a finding - matched line by line.
`release_tag` separates its parts with `\s+`, which matches a newline, so a
claim wrapped at the margin was seen by two of the three.

The denominator is the reason this is worth a release rather than a note. It
reported `examined=1` against `0 findings`, which prints as *examined and
clean* - not as the "0 examined" this project keeps denominators to make
visible. The one number kept to tell "checked and fine" apart from "never
looked" was reporting the wrong one. Check and denominator now read one
scanner, so the count cannot describe a population the check never sees.

Measured before shipping, as a widening must be: 263 markdown files, 57 claims
found by the old scan and 60 by the new, none lost. All three additions are one
wrapped quotation in a changelog, a document kind this project does not check
by default. A project that does check its changelog, has
`release_claims_name_our_tags` on, and quotes a wrapped version matching one of
its own tags could see a new finding. Narrow, not zero.

**A bound that counted newlines did not bind on a CR-only document.** `\r\n`
contains `\n`, so CRLF was never affected; a bare `\r` contains none. Three
places took a newline count as complete: both claim scanners, whose one-line
bound therefore never tripped and whose line numbers were all 1, and `archive`.

The last is the one to read twice. `^` in a multiline pattern follows a
newline, and `\r` is not one, so a CR-only status document is a single line to
every entry-header pattern: nothing splits, nothing moves, and `--archive`
reports a document with no entries in it rather than failing. Its terminator
detection would then have rewritten every line ending in the file as a side
effect of retiring two sections - in the one operation here that writes
irreversibly. Line breaks are now counted in every spelling, and a document is
written back in the terminator it arrived in.

The corpus is unchanged by this one - the same 50 merge claims and 60 release
claims across the same 263 files - because for LF and CRLF it changes nothing.

## 0.24.0 (2026-08-29)

**A large `--sweep` now spreads across worker processes.** Above 100 documents
the survey splits the per-document work across up to eight of them; below that
it stays in one process. On a 200-document corpus across twelve cores, best of
three: 7327 ms in one process, 2919 ms across eight. Against 0.23.0, which took
8626 ms on the same corpus, the whole stretch is about 2.9x.

The floor is measured rather than chosen. Parallelism is worth 4% at 40
documents and 15% at 60, and only reaches 1.75x at 100; a process pool brings
failure modes a loop does not have, and 4% does not pay for them.

Both paths call one implementation of "read a document, validate it, count its
denominator", so there is no second copy to drift. Output is identical between
them, verified line for line over 200 documents.

**The survey says which path produced its numbers,** and a pool that cannot
start is announced rather than absorbed:

```console
swept 200 markdown file(s): 0 configured (0 finding(s)), 200 unreviewed (820 finding(s))
  surveyed across 8 worker process(es)
```

If spawning is forbidden or a worker dies, the run finishes in one process and
prints a `NOTE:` naming the reason. A run that quietly stopped using the
machinery it reports using would go on printing the summary of a healthy one,
which is the failure this tool exists to refuse. A document dispatched to the
survey that returns no result is likewise counted and named beside the
unreadable ones rather than skipped, and unlike an unreadable file it fails the
run: a file that cannot be decoded is a fact about the repository, while a
document the survey lost is a fact about this tool.

**A shallow clone now says so.** `dead-sha` asks whether a commit is reachable,
and in a depth-limited clone it answers about the slice that was cloned rather
than about the repository, so a live SHA can read as dead. Nothing can fix that
without the missing history; the run prints the caveat beside the denominators
instead, which is the only honest thing available. Worktrees and submodules are
covered, where `.git` is a file and the marker lives elsewhere.

**Two rules stop reporting things that are not wrong.**

- `manifest-floor-mismatch` no longer reports `3.14` against a manifest saying
  `3.14.0`. They are one floor written two ways; the parsed tuples were being
  compared without padding, so the shorter one differed from the longer.
- `dead-md-link` no longer reports `[notes](notes.md?plain=1)` as dead. A query
  string is how a forge serves a file, not part of its name, so a file plainly
  present was resolving to nothing.

The wording of that notice is "shallow repository" rather than "shallow
clone", and the suite now enforces it. The adversarial harness scans the
package's source for the shapes a network call takes and keeps string literals,
because a git subcommand only ever appears as one - so the word `clone` in a
message read as a network operation in a tool that opens no sockets.

**Everything else is speed, with output unchanged.** The per-document candidate
scans run once rather than three times; the bare-SHA scan skips a line with no
hex run in it and the line-pointer scan skips a line with no colon; the
path-pointer scan runs once per document instead of twice; `anchors()` walks
each heading once instead of four times, worth 1.32x on a 66-document corpus.
Three more answers about the checkout - the tracked file list, the site
directory list, and reference resolution - are held for the duration of a
survey rather than rebuilt per file.

`main()` is now five named functions rather than five inline modes, with a
function-length ceiling in the suite to stop the sixth hiding inside another.

That performance work leaves sweep and verify output byte-identical to 0.23.0.
The rule fix below deliberately does not, and says so.

**`false-merge-claim` now sees a claim that wraps a line, so you may get
findings you did not get before.** They are claims that were always false and
were never examined: `merge_claim` separates its parts with `\s+`, which matches
a newline, but the scanner fed the pattern one line at a time, so a claim
wrapped at the margin was invisible to the rule while the rule's own probe found
it perfectly well. Two matchers for one claim. The denominator counted such a
claim as absent rather than as passing, which is the quiet direction: a false
"merged at X" told the next reader that work landed when it had not.

Measured before shipping, because this widens what a scan matches. Across 263
markdown files, 0 unreadable: 48 claims found by the old scan and 50 by the new
one, 0 lost and no false positives. A claim may now wrap ONE line break and no
more - whole-text scanning lets that `\s+` cross anything whitespace-shaped,
including the spaces a blanked code fence leaves behind, and without that bound
a sentence ending in a branch name adopts a SHA from the paragraph after it.

**`strip_code` kept its offset promise on CRLF.** Both blanking paths read
`splitlines()` and rejoined with a bare newline, so every `\r\n` lost a
character and a trailing newline went even on LF - 1627 characters on this
project's own status document. The docstrings promise that "every character
offset survive" precisely so a caller may take a span from the stripped text and
use it against the original, which the `dead-md-link` and `dead-md-anchor`
probes do. On a Windows checkout those probes spliced into the wrong place, so
`--selftest` reported both rules as not firing while they worked correctly on
every real document. It exited 1 on Windows and 0 on Linux for the same commit.
The rules themselves were never affected; no finding changes because of this.

**`--archive` and `--search` are now driven end to end by the suite.** Neither
mode had a test that went through argparse and the config load: every archive
test called `entries.archive()` directly with an explicit `retain`, so the
`retain=None` fallback to the configured value had never run, and `--full` had
no test at all. That is the shape `--search` shipped broken in - a mode nothing
drove end to end, handing the raw `StatusConfig` where the derived `Config` was
needed - and `--archive` reaches the same funnel.

Eleven tests, each watched failing before being trusted: the archive mode's
counts and the relocation those counts claim, asserted separately because a
mode printing `archived=2` while writing nothing would satisfy the first alone;
the stale-pointer removal, across two real runs with an entry staged between
them; the `retain=None` fallback; the guard that refuses the wrong config type;
and for search, the excerpt against `--full`, the 96-character cap, the refusal
of an empty query, both directions of the nothing-to-search note, both
documents with the live one first, and the reference sections that are skipped
while still counting toward the denominator.

The first version of the pointer test was worthless and the mutation run said
so: it ran `--archive` twice over an unchanged document, which returns early at
`phase_count <= retain`, so it passed against a build with the stale-pointer
removal deleted. Staging a sixth entry between the runs is what puts the
pointer path back in the run.

**The harness list no longer carries a count of itself.** `fuzz.py` was missing
from the table in `tests/harnesses/README.md` while having a section below it,
`AGENTS.md` said "five audits ... run by hand" when there are seven and three
are CI jobs, and `CONTRIBUTING.md` said "four more audits" while naming the
pre-fuzz set. No rule here can catch that, because no rule inspects a number.

## 0.23.0 (2026-08-18)

**One 6,249-line file became a 32-module package, and nothing else changed.**

`plugin/skills/extant/payload/extant_collect.py` is now 68 lines: a version
handshake, a config import, an entry-point import, and a `__main__` guard. It
survives at that path because the shipped git hook invokes it, and so do the
README and the slash command.

Nothing a user can observe moved. `--verify` output is byte-identical to
0.22.0, with one deliberate exception: `inconsistent-artifact` now examines
seven sources rather than five, because the package version and the shim
version are two new places a version is written and both are now compared
against the other five. Two unguarded copies of a number that must agree is
that rule's own subject matter.

**A rule that raises is now named instead of killing the run.** The only
declared behaviour change. Previously one rule raising took the whole run
down; now it is reported beside the denominators, the other twelve still
report, and the exit code is non-zero. Isolation that swallowed would be
strictly worse than the crash it replaced, because a skipped rule prints
exactly like a clean document - so the errored rule is named in the output
rather than a log, the run never exits 0, and the denominator is still shown.

**What the split bought.** A rule is one module owning its check, its probe,
its denominator and its registry entry, so adding one is a file and an import
rather than four edits in four places. Fifty-two module-level mutable names
became three scope objects with stated lifetimes, which deleted a ninety-line
block inside `validate()` that saved thirteen globals and restored twelve;
every comment in it recorded a real bug, and those bugs are now
unrepresentable rather than guarded. Git reaches the rules through one
injectable seam, which made the first spawn budget possible: `--verify` went
from fourteen git processes to twelve, and two questions it used to ask twice
it now asks once.

Wall-clock is flat, not faster. The saved spawns are very nearly cancelled by
importing thirty-two modules instead of two, so `--verify` moved 928 ms to
937 ms. The honest summary is that the split cost nothing and bought
structure.

**Evidence.** The full mutation campaign still kills every one of its 152
mutations. 649 tests pass. 25 install scenarios and 213 assertions pass
against a shippable extract. `--selftest` fires the same rules it did before.

One bug shipped and was caught by none of that. `--search` crashed on every
invocation, because the split separated the raw settings object from the
derived one and the search path was handed the wrong kind. It survived 641
tests, a byte-identical output comparison and ten reviews, because no test
drove the mode at all. The smoke harness found it. `split_entries` now raises
a `TypeError` naming both types, and three tests drive the mode.

## 0.22.0 (2026-08-09)

**`exclude_paths`, for documents that are input to a test rather than a
promise to a reader.**

```toml
exclude_paths = ["testdata", "**/test/fixtures/**"]
```

The case that settles why this is configuration and not a rule: a renderer's
fixture links to `../assets/does-not-exist.jpg` **on purpose**, to exercise the
error path. Nothing git or the filesystem can answer separates that from a
real broken link. A held-out corpus put 18 findings in such trees, and 0.21.0
shipped naming them as a known limit with no way to act on it.

Which directories hold fixtures is your project's convention rather than a
fact about repositories in general, so hard-coding a list of names would be
the "derive the pattern from what the wording should be" mistake the admission
test exists to prevent.

**Empty by default.** A skip-list that ships with entries is a skip-list
nobody audits, and this project has already shipped a lint whose skip-list
excluded every file it was meant to scan and passed on an empty scan.

**The sweep prints what it removed, per pattern, and names any pattern that
matched nothing.** A skip-list fails silently in both directions, and both
halves cost one line each to report:

```
swept 1013 markdown file(s): 0 configured (0 finding(s)), 1013 unreviewed (4 finding(s))
  excluded 3 of 1016 tracked file(s) via 3 exclude_paths pattern(s)
        0 **/e2e/fixtures/**
        0 **/test/fixtures/**
        3 testdata
  matched nothing, so they exclude nothing and may be stale: **/e2e/fixtures/**, **/test/fixtures/**
```

That second half earned itself immediately. Measured on two repositories:
hugo needs `testdata` and its two fixture patterns match nothing; astro needs
the fixture patterns and `testdata` matches nothing. Each is told which of its
own entries are dead rather than carrying them forever.

**Patterns are gitignore-shaped, not `fnmatch`.** `*` stops at a separator,
`**` spans them, and a bare name matches a segment at any depth so `testdata`
finds it wherever it lives. Under `fnmatch` a `*` crosses `/` silently, so
`docs/*.md` would take the whole tree and the only evidence would be a smaller
number.

**Excluding a document that `primary_doc` or `extra_docs` also names is
refused** with a non-zero exit rather than resolved. One setting says gate on
this file and the other says never read it; the dangerous direction is quietly
dropping a document somebody asked to gate on.

Measured effect on the two repositories that motivated it: hugo 10 findings to
4, astro 31 to 19.

## 0.21.0 (2026-08-09)

**Fourteen ways a rule reported a working claim, found by running against
forty repositories none of them was designed on.** Every rule here was tuned
against 92 repositories until that set was quiet, which measures the fitting
rather than the rules. A disjoint corpus of 40 replaced it - 0 of the 40
appear among the 88 distinct repositories that shaped the rules, checked
mechanically rather than by reading two lists.

It reported 7,658 findings and 582 were real. On the same corpus, one build
apart, that is now 632 findings, with hand-audited precision moving from 11 of
24 to 14 of 18 and 541 of 573 adjudicated real defects still reported.

Nothing here is a new rule. Every change narrows one that already existed, so
a repository that was quiet stays quiet.

**Documentation trees are recognised where projects actually keep them.**
Generator detection now finds a config in `docs-website/` (haystack's
Docusaurus), one level INSIDE a documentation directory (llama_index declares
MkDocs at `docs/api_reference/` while serving `docs/src/content/docs/`), and
`fern/fern.config.json`. A tree that numbers its documents for ordering
declares a site by that alone, which is the case for a project whose pages are
built by another repository. Between them these accounted for 6,499 findings,
every one a working route reported as a missing file.

**Detection now records which directories a generator governs, rather than
answering yes or no.** A monorepo builds a site from `docs/` and still keeps
ordinary READMEs in `packages/`, whose relative links really are files.
Suppressing routes across the whole repository hid six real defects, including
a README linking to a directory that does not exist.

**A bare filename resolves within one translation tree.** fastapi builds a
separate site per language and keeps `newsletter.md` only in English. Counting
that name across the whole repository made every translated page's broken link
to it resolve against the English file, hiding 68 real defects across ten
languages. Trees are recognised by three or more language-shaped siblings, so
a lone `docs/id/` stays an "id" directory.

**Five narrowings in the SHA rules.** A backticked SHA that is the link text
of another repository's commit URL is that repository's claim, not this one's
- the bare-token path already dropped hex inside a link target for the same
reason. A hash prefixing an asset filename (`/img/83f686b-chart.png`) is part
of the filename. A changeset id on a `- <id>: text` line is minted by a tool,
gated on `.changeset/` existing. Exactly 32 hex characters is a digest, not a
commit. `owner/repo@<sha>` names whose commit it is, which is what pinning an
action by SHA looks like.

**Anchors read underlined headings and keep the dash an emoji leaves.** A
document written entirely in Setext style offered no anchors at all, so every
link into it read as dead. A heading opening with an emoji anchors as
`#-component-structure` on GitHub, because the emoji is dropped and the space
after it still becomes a dash.

**A prose path pointer resolves beside its own document**, as markdown links
always have. A nested `SKILL.md` saying "see `references/cli.md`" was reported
dead while the file sat in the next directory entry. A backticked path that is
the link TEXT of a resolving link defers to that link.

**One pattern was a hang rather than a false positive.** The asset-filename
match took 321,822 ms on a single 120,000-character line before it was
anchored and bounded; the longest markdown line in the earlier corpus was
123,427 characters. It is now under 5 ms.

**Two candidate rules were refused on the evidence**, and both looked
reasonable first. A path named beside a creation verb is a runtime output in 1
of the 6 findings that match it. Hex inside a backslash-delimited path matches
4, of which 2 are shell line continuations.

Known false positives that remain, named so they are not rediscovered as new:
test fixture data, a crypto algorithm name that is valid hex, hashes elided
with an ellipsis, and a template naming a file it writes at runtime. Which
directories hold fixtures is a project's own convention rather than something
git can settle, so it belongs in configuration rather than in a rule.

**One change in this release alters no output, and is listed because a reader
diffing the tag will find it.** The slug variant added for emoji headings
stripped punctuation exactly as the original did, which silently disarmed the
mutation that probes the original: breaking it changed nothing, because the
new function still produced the spelling it no longer did. It now contributes
only the spelling trimming would lose. Anchor sets are unchanged either way -
when trimmed and untrimmed agree the duplicate added nothing, and when they
differ both are still offered - so no repository sees a different result.

## 0.20.0 (2026-08-06)

**Machine-format severity now matches the exit code.** Every finding was
published at `level: error` in SARIF and `::error` in GitHub annotations,
including the ones a sweep explicitly cannot fail a build on. The README
promises "a sweep cannot fail your build", the exit code honours it, and both
machine formats contradicted it - so a survey put red marks on a pull request
and a wall of errors in code scanning for advisory findings.

`--deleted-since` was the same story and worse: it "never gates: returns 0" by
its own docstring, and published every result as an error. It now reports
`note` and `::notice`, carries the document count it always printed in text,
and identifies itself as `extant/deleted-since` rather than borrowing
`extant/verify` and replacing a verify upload.

It deliberately does NOT carry snippets. Those findings come from the document
as it was at the compared ref, so a line number indexes the old text; reading
the current file would quote whatever now occupies that line and attribute it
to a claim that is no longer there.

**Read this before upgrading if you filter on severity.** A finding in a
configured document still arrives as `error`. A `--sweep` finding in an
unreviewed file now arrives as `note`, and repository-wide findings likewise.
Anyone alerting on `error` will see fewer alerts, which is the point; anyone
counting all results is unaffected. Every result also carries
`properties.gates`, so a policy can key on that rather than on severity.

**SARIF was the only output with no denominator.** It now carries
`properties.examined` with the per-rule count, and the invocation repeats it as
a notification plus a warning naming any rule that examined nothing. Zero
results with a full denominator is a clean repository; zero results with zeros
everywhere is a run that checked nothing, and those printed identically before.

**Alerts show the claim rather than a line number.** Results carry the cited
line as `region.snippet`, and `startColumn`/`endColumn` point at the token the
claim is about, so a code-scanning UI underlines `abc1234` instead of
highlighting nothing. Columns count UTF-16 code units, which is what the
document's `columnKind` declares: an emoji is one Python character and two
code units, and 47 markdown files in the 39-repository corpus carry 156 such
characters, so indexing by code point was wrong by one per emoji rather than
theoretically wrong.

Snippets are capped at 400 characters. The longest single markdown line in
that corpus is 123,427 characters, GitHub rejects a SARIF upload over 10 MB,
and one cited base64 image would have carried the whole line into the
document.

Also added: `help.markdown` and `helpUri` on every rule so alert pages render
properly, `properties.tags` and `precision` for filtering,
`defaultConfiguration.level`, `ruleIndex`, `columnKind`, and
`automationDetails.id` - `extant/sweep` and `extant/verify` - so uploading both
no longer has one silently replace the other.

**A preset now finds its files where the project actually keeps them.** Presets
name paths from the repository root, and real projects routinely keep the thing
one directory down. Measured 2026-08-05: not one sampled published Helm
repository has `Chart.yaml` at the root, prometheus-community, grafana, argoproj
and bitnami all nesting it under `charts/<name>/`, and neither sampled Unity
project keeps `ProjectSettings/` there either. Every one of them lost its
consistency check to a path assumption rather than to anything about the
project. The installer now locates each source before reading it, and the
emitted config carries the resolved path rather than the preset's guess.

Ambiguity is refused rather than guessed. A chart collection carries one
`Chart.yaml` per chart, so "the chart version" is not one fact and no pairing
can be formed; `argoproj/argo-helm` now reports 6 ambiguous candidates instead
of claiming the file is absent. The diagnosis improves even where the outcome
does not: `Cysharp/UniTask` still skips, but now because its README carries no
Unity badge, where before it named a missing file that was present. Three
preset summaries state the layout they assume - `mobile` is Capacitor's, `k8s`
expects a single chart at the root, `unity` expects the project at the root -
because a user who picks one and silently loses its check has no way to find
out why.

**Publishing refuses a commit the suite has not passed.** `publish.yml` and
`tests.yml` are independent triggers, so a red suite never stopped an upload.
0.19.0 was tagged ninety seconds after a push whose run was already failing,
and published; the artifact was fine, the mechanism was luck, and PyPI does not
allow replacing a released version. The build job now asks the API whether
`tests.yml` succeeded for this commit before it builds anything, matched by
commit rather than by ref, since `tests.yml` never runs on a tag and there is
no run attached to the tag itself. A commit with no run at all fails rather
than passes, only `success` counts as green, and a network error or missing
configuration blocks rather than allows.

## 0.19.0 (2026-08-04)

**A sweep now reports what each rule examined, not just what it found.** It
printed how many files it read and how many repository-wide rules ran. Neither
said whether a RULE examined anything, so a survey of a repository where every
pattern missed printed the same summary as a survey of a clean one. `--verify`
has reported the per-rule count since the beginning; `--sweep` never called it
at all.

```
swept 2 markdown file(s): 0 configured (0 finding(s)), 2 unreviewed (3 finding(s))
  2 repository-wide rule(s) ran once (0 finding(s))
  examined: dead-sha 1, stale-live-claim 0, unknown-branch 0, false-merge-claim 1, ...
  NOTE: these rules examined nothing anywhere here - either no document makes
  such claims, or the pattern does not match how this project writes them: ...
```

Summing the counts was the easy half. A sweep does not run every rule on every
document: entry-scoped rules are skipped outside the primary file, markdown-only
rules for `.rst`, and repository-scoped rules run once for the whole survey.
Counting them anyway would report coverage that was never provided, so the
rule-selection predicate moved into one function that both the findings loop
and the count now read.

**Fixed: the denominator counted claims inside code blocks.** Six rules open by
stripping code, because a claim inside a fence is an example rather than a
promise. The count scanned the raw document, so fenced sample claims were
reported as candidates no rule had read. On `rust-lang/rfcs` that was
`dead-sha 23` where the rule reads 11.

This affects `--verify` as well, and it is the reason to read this entry before
upgrading in CI: **any project that quotes a SHA, a merge claim or a path
pointer inside a code fence will see its `checked <doc>:` numbers drop.** The
old numbers were overstated. Nothing about which findings are reported has
changed - verified across 39 repositories, 2,148 findings, none moved.

Sweeps are 24-33% slower, measured rather than estimated: `rust-lang/rfcs`
13.0s to 16.1s over 651 documents, `pytest` 2.8s to 3.7s over 308. Counting
candidates means a second pass over each document. Profiling cut that from an
initial 43-76% by caching the two functions the rules and the count both
compute.

## 0.18.1 (2026-08-04)

**Three crashes on first contact, and a setting that did nothing.** Found by a
review of the whole codebase, each reproduced before it was believed.

- **`--selftest` crashed** with `UnboundLocalError` on any repository lacking
  the primary document. It called `diag`, which is defined 87 lines further
  down the same function, so the message naming the missing document never
  printed.
- **`--sweep` crashed on a repository with no commits.** `git ls-tree HEAD`
  exits 128 on an unborn HEAD, and a freshly created repository is exactly
  what a first-run survey gets pointed at.
- **`consistency_timeout_seconds` was inert.** `_apply_config()` runs at
  import and set it; a later module-level ASSIGNMENT then replaced it with
  `None`. The config parsed, the value reached `CONFIG`, and the global the
  rule reads never saw it. It is now an annotation, which binds nothing.
- **`--write-baseline` resolved a relative path against the process cwd**
  while the read path resolved against `--repo`, so a git hook wrote a
  baseline the next run could not find.

**`SKILL.md` was two rules behind** and still headed "the eleven validation
rules", because `test_every_rule_is_documented` only read `README.md`. That
test now checks both tables. A reader of the installed skill never sees the
README.

**Publishing now requires a tag ref, including for `workflow_dispatch`.** That
trigger previously skipped the tag-matches-version check entirely - its
condition tested for a tag - so a manual run from any branch could publish a
version with nothing pointing at the code that produced it.

Smaller: Mintlify's renamed `docs.json` is recognised, by its CONTENT rather
than its name, because the name alone is too generic to suppress link checking
on. The installer's emitted `phase_task` pattern matches the one it measures
with. A corpus baseline no longer reports a NEW repository as one recorded
before per-rule detail existed. A stress timeout returns None rather than the
budget. `archive`'s retain default is read at call time so `reload_config`
reaches it. Test fixtures no longer depend on the runner having no global
commit signing. Several hand-maintained counts that had drifted are gone;
recorded historical measurements are kept, because those are evidence and do
not go stale.

No behaviour changed for any rule: across 39 repositories the gate shows 2,148
findings before and after, nothing added, removed or reworded.

## 0.18.0 (2026-08-04)

**A thirteenth rule: a cited line number that is past the end of its file.**
`core/engine.py:123` where that file has 40 lines. It does not ask whether
line 123 still holds what the document says, which would be judging content.
It asks whether the file has that many lines.

Measured on 39 repositories before it was written. 7,775 candidate sites,
6,525 outside a code block, and then a collapse to **51** - the rest name
something the repository does not track. Those are pasted stack traces,
third-party paths and example output, and whether a path exists is already
`dead-path-pointer`'s question; asking it again would report one fault twice
under two names.

Of the 51, three cite a line past the end, all in `obra/superpowers` plan
documents, all real: an implementer told to modify line 68 of a 64-line file.

Coverage is thin and worth saying so. Only 3 of 39 repositories produce any
examined site and 136 of 184 are in one of them. What the corpus does prove is
precision: aider and directus supply 167 resolvable pointers between them and
produce nothing.

**A dead path wearing a line number was checked by nothing.**
`dead-path-pointer` required the extension to sit immediately before the
closing backtick, so ``**Plan:** `docs/gone.md:99` `` matched nothing at all,
and the new rule will not look at it either because it requires the file to
resolve before counting lines. A trailing suffix is now tolerated and excluded
from the capture, so the finding names `docs/gone.md`. Ranges and line:column
are covered.

That fix is unmeasurable on the public corpus: it adds no finding and moves no
denominator across 39 repositories, because not one writes an operative
pointer with a line suffix. It ships on a hole demonstrated in a fixture, and
the corpus proves only that it breaks nothing.

Three smaller things, found by auditing the rule before release rather than by
any failing test: `_LINECOUNT` was never cleared by `run_sweep` while every
sibling cache was; `_LINE_COUNT_LIMIT` was defined after the function reading
it; and two narrowings - a range is judged by its start, six digits is the cap
- were undocumented and untested, which made them accidents rather than
choices.

## 0.17.2 (2026-08-04)

**`inconsistent-artifact` and `raw-lfs-blob` never ran in a `--sweep`.** Both
answer questions about the repository rather than about any document, so
`validate` runs them only on the primary pass, guarded by `has_entries`. In a
sweep that means "this file is the configured primary document", and a swept
repository usually has no such file, because a sweep needs no configuration at
all.

It was invisible, because a rule examining nothing and a rule finding nothing
print the same zero. It showed as `0 / 0` for both rules across all three
Phase 3 corpora and was read as an absence of faults.

The guard was right that one repository-wide disagreement must not be repeated
once per swept document, and wrong about what "once" was tied to. They now run
once per sweep, outside the document loop, in their own section.

**The sweep now prints how many repository-wide rules ran**, which is the
denominator the silence was hiding:

```
swept 37 markdown file(s): 0 configured (0 finding(s)), 37 unreviewed (1 finding(s))
  2 repository-wide rule(s) ran once (0 finding(s))
```

Three constraints held deliberately. The count stays OUT of the per-file
totals, because folding it in would report more findings than there are
documents to hold them. The findings do NOT gate, so a survey command still
cannot fail a build that never opted in. And each is attributed to the file
that declares the claim, through a new `Rule.subject_file` - `.gitattributes`
and `.extant.toml` - because that path feeds baseline fingerprints and had to
be chosen once rather than drift.

The corpus gate shows no regression, 2,145 findings before and after with
nothing added, removed or reworded. It cannot validate the fix: none of the 39
repositories carries an LFS filter or a consistency block, so the corpus never
reaches either rule. That is recorded rather than reported as a pass.

## 0.17.1 (2026-08-04)

**`manifest-floor-mismatch` worked in `--sweep` and did nothing in
`--verify`.** Both verify call sites handed `validate` and `count_examined`
the document's text without saying which document it was, so the rule - which
keys on the filename, because a floor in a README is a promise and the same
sentence in a changelog is history - saw no path and stayed silent. A project
that installed 0.17.0 and listed `README.md` in `extra_docs` got nothing.

The denominator agreed with it, reporting 0 examined beside 0 findings. That
is the precise conflation this rule reports a denominator to prevent, and it
is why the bug was findable at all.

Three call sites now name their document: the primary, the archive, and each
extra. The value is set before `validate` rather than passed into it, because
`validate` restores what it found on entry and `count_examined` runs after it
returns.

Found by gating the release against a 39-repository corpus, which reported
**2 findings and 0 examined on the same run**. Every unit test passed
throughout, because all of them called `validate` directly and supplied the
path themselves. The gate is the only thing that exercised the wiring a real
install uses.

Nothing else moved: across those 39 repositories the gate shows 2 findings
added, 0 removed, 0 reworded, and no other rule changed its findings or the
number of candidates it examined.

## 0.17.0 (2026-08-04)

**A twelfth rule: a documented version floor, read against the manifest that
declares it.** A README saying "requires Python 3.8+" while `pyproject.toml`
declares `>=3.10` is a contradiction between two files in one repository -
the question `inconsistent-artifact` already established as legal, rather than
a judgement about whether a number is correct.

Measured on 39 repositories before it was written, because the obvious version
of this rule is unusable. Keyed on shape it disagreed at 169 of 192 sites, and
97 of those disagreements sat in changelogs and release notes, where the claim
was true the day it was written and the manifest moving on does not make it
false. A linter's own documentation makes it worse: ruff discusses Python
versions constantly and almost none of it is ruff's floor.

Keyed on entry-point documents, with a requirement verb or a bare
`Requirements:` label above the line, and no third-party subject, it examines
7 sites across those 39 repositories and finds 2. Both are real. `datasette`'s
README offers Python 3.8 against a `>=3.10` manifest while its own
installation guide says 3.10; `caddy`'s offers Go 1.25.0 against `go.mod`'s
1.25.1.

The finding carries the ecosystem's own enforcement, because the same
contradiction means different things: pip refuses to install, `engines.node`
only warns unless `engine-strict` is set, and the `go` directive quietly
fetches a newer toolchain.

Two things it deliberately will not do. A disjunction such as
`^20.19.0 || >=22.12.0` is not examined at all rather than guessed at, and
neither is a pair of coarse statements like "Node 18" against `>= 18`, where
there is nothing to compare. Both are counted as not-examined, so the
denominator never claims coverage that does not exist - this rule speaks about
roughly 13% of repositories, which makes silence its normal output.

`validate` now learns which document it is reading, through a `doc` keyword
alongside the existing `base`. The keying needs the filename and a rule's
`check` receives only text. A repository-scoped rule was tried first and
rejected on evidence: such a rule runs only when `has_entries` holds, which in
a sweep means the repository carries a configured status document, so in any
other repository it would never have run at all.

## 0.16.2 (2026-08-03)

**The merge-claim fix below now reaches installed projects.** 0.16.1 widened
the collector's DEFAULT so a bare commit is seen at all, and the installer
went on writing the narrow backticked-only form into `.extant.toml` - which
overrides the default. Anyone who installed 0.16.1 kept missing exactly the
claims it was released to catch. Only a project running the tool without a
generated config got the fix.

This is the second time this trap has been sprung, and the comment beside the
line describes the first: when the rule learned to check a claim against the
branch the claim names, the installer kept emitting `{trunk}` and every fresh
install stayed single-trunk. Both halves now have a mutation and a test.

Found by the first full mutation campaign in this project's history - 136
mutations, one full suite run each. It reported two survivors, both in the
installer; writing a unit test for the first is what surfaced this.

**Branches, tags and ref lookups are one `for-each-ref`.** They were three
separate questions - `tag -l`, a `for-each-ref` of its own, and a
`rev-parse --verify` per ref - each paying a process spawn, which is the
expensive thing on Windows. A validate of this project's own status document
went from **8 git subprocesses to 6**, and from **261 ms to 214**. Verified
byte-identical across 45 repositories: 18,862 findings, none added, removed,
reworded, or examined differently.

Bare names resolve the way git resolves them, tags before heads, so a
repository holding a branch and a tag of the same name agrees with
`rev-parse`. Annotated tags are peeled to the commit they tag - without that
they resolve to the tag object, which is an ancestor of nothing, and every
correctly annotated release would be reported as having shipped on no
integration branch. Nothing in 443 tests noticed that until a mutation
survived, because every fixture in the suite used lightweight tags.

An earlier attempt at the same goal was reverted. Memoising commit resolution
worked exactly as designed - the second rule to ask found 24 of its 25 tokens
already known - and a controlled A/B measured **261 ms against 265**. The cost
is the spawn, not the payload.

## 0.16.1 (2026-08-03)

Both changes here come from a corpus that did not exist when 0.16.0 shipped:
fifteen projects that WRITE prose git claims, found by scanning 229
repositories from the agent-tooling topics. 0.16.0 concluded no such corpus
existed. That was a statement about the sample, and it is corrected below.

**A merge claim may write its commit without backticks.** The rule's largest
blind spot. basilisk-labs/agentplane records 32 claims as
`PR #499 merged into main at 6ff1f4ac`, ref and commit both bare, and
`false-merge-claim` examined ZERO of them across 7,489 documentation files.
Measured across 45 repositories: 3 claims examined before, **35 after**, with
no finding added, removed or reworded anywhere. All 32 are true and all five
distinct commits resolve, so ancestry was really compared rather than skipped.
A trailing guard replaces the boundary the closing backtick provided, without
which a 46-character hex run matches its first 40.

**`dead-release-tag` no longer asks a question git cannot settle.** "No such
tag exists" was wrong **19 times out of 26** on projects that write release
claims: eugenelim/agent-ready-repo tags `credbroker-v0.4.0` and writes "shipped
as 0.27.0", an npm version; 10CG/Aria tags to v1.5.0 and cites its plugin's
v1.17.3 through v1.24.1. A version in prose can name a tag, a package, a
sub-component or somebody else's toolchain, and the sentence does not say
which - `dead-pinned-ref` stays honest on the same problem only because
`repo:` names the owner on the line above.

That half is now `release_claims_name_our_tags`, **off by default**. On, it is
the author asserting what the tool cannot infer, which is right for a project
checking its own status document; this repository sets it. The half that needs
no assertion - the tag is here and it shipped on nothing - is always checked
and was right 7 times out of 7. Measured: 19 findings removed, none added.

A range test was tried first and rejected: two of the false positives sit
inside the repository's own tag range, so it separates nothing.

## 0.16.0 (2026-08-02)

Loopholes, closed where closing them costs nothing and reported where closing
them would cost the truth.

**`--deleted-since <ref>` reports claims removed while still false.** Deleting
the offending sentence has always been a way past every rule, because the rules
compare a document against git and never against its own previous version.

This began as a twelfth rule and was demoted to a report before any of it was
written, which is the part worth reading. Whether a removal was evasion or
repair is a question about intent, and git cannot settle it. Worse, the common
case cuts the wrong way: a document claims work was merged, it was not, someone
deletes the sentence, and the document now tells the truth - so a gating rule
would fail the build on the correct fix. This mode always exits 0.

The mechanism is one idea: validate each document as it stood at `ref` against
TODAY's git. Every finding that survives is a claim false right now, so there is
no separate still-false check. It is reported when its subject appears in no
configured document today, AS PROSE - which keeps `--archive` legitimate,
catches a claim moved into a code fence, and distinguishes removal from
relocation without guessing. `HEAD~1` by default; pass the merge base in CI, or
splitting a removal across two commits hides it.

**A consistency block reaching one file by two routes now says so.** The guard
was a string comparison at config load, so `docs/x.md` and `docs/./x.md` were
caught and a symlink, hardlink or case variant was not. Such a block agreed with
itself forever while appearing to compare two things. It asks the filesystem
now. The fallback matters as much: FAT32 and some network shares report `st_ino`
as 0, and keying naively on it would report self-comparison on every
configuration - a false positive on every run, worse than the hole it closes.

**`consistency_timeout_seconds` bounds a user-supplied pattern.** Absent by
default. A watchdog thread cannot work, because `re` holds the GIL while
matching; static rejection of dangerous constructs breaks patterns that work
today; an always-on subprocess costs a spawn per pattern and the stress suite
puts 200 files through this rule. Process isolation is what remains, so it is
opt-in, and left unset the hang is still possible. A mitigation on request, not
a cure.

**A baseline forgives the occurrences it recorded, not every future copy.**
Entries carry a count. The line number stays out of the fingerprint, so
reflowing a paragraph still does not un-suppress everything.

**Findings carry a `subject`**, the bare token a claim is about, so a consumer
need not scrape backticks out of prose. Optional and populated rule by rule;
`--deleted-since` reports how many findings it skipped for want of one.

**Two more generators are recognised, worth 37 false positives.** A site is
often a subdirectory of a subdirectory: aider keeps Jekyll at
`aider/website/_config.yml`, and a search that tried `website/` but not
`*/website/` judged the whole repository plain and called 29 of its own asset
links dead - each one served out of `aider/website/assets/`, where 203 files
are tracked. The config search now goes one level deeper, bounded there.
Mintlify's `mint.json` is recognised too; humanlayer declares one and reported
8 of its own route links dead. `docs.json`, Mintlify's newer spelling, is not
recognised - it is too generic a filename to be a signature, and no repository
in three corpora carries one.

**Release claims are read against the conventions a project actually uses.**
Four findings from `dead-release-tag` and `dead-pinned-ref` exist across a
30-repository corpus and every one was wrong, each because of a habit rather
than an error.

Half the ecosystem tags `v1.2.3` and half tags `1.2.3`, so the prefix is now
read from `git tag -l` instead of assumed. A claim names a SERIES more often
than a tag - symfony's own guide says work "shipped in 8.0" while the tags are
`v8.0.0`, `v8.0.1` - so a version that is the stem of a real tag counts as
shipped. And symfony has no `main` and no `master` at all: its branches are
version numbers. The integration-ref list returned the configured trunk whether
or not it existed, so every rule asking "did this reach an integration branch"
compared against a ref that does not resolve and reported every release as
shipped on nothing. **3 of 30 repositories have no conventionally named trunk**,
so that is about a tenth of projects, not a corner. Refs that do not resolve
are dropped now, and an empty list means "cannot settle".

`rev: ''` is no longer read as a broken pin. It is pre-commit's own documented
placeholder, the state a snippet ships in for `autoupdate` to fill, and poetry
ships two. Quotes come off a rev for the same reason - `rev: 'v1.2.3'` is the
same pin, and 4 of 75 revs in the corpus are written that way.

**A document full of release claims is an order of magnitude faster.** The
branch list is asked for once per validation rather than once per claim, each
miss having been a `for-each-ref` subprocess. At 400 claims and 30 tags,
**22.0 seconds to 1.25**; at 200, 11.6 to 1.2.

The cost was in 0.15.0 too - the same fixture run against it takes the same
11.6 seconds - and it surfaced only because the work above added a second call
site and prompted the question of whether that had made anything worse. It had
not, by any amount worth measuring; the existing call was the whole cost.
`perf.py` could not answer the question either, every document it builds being
full of links rather than claims, so it has grown a section that can.

**The corpus harness reports which rules a corpus reaches.** `corpus.py` always
refused a findings count without a denominator, and the denominator was files
swept - which says the run happened, not which rules it touched. It prints
found over examined per rule now, and names the rules a corpus cannot speak
for. That is the column the survey below turned on. Its README carries the
thirty repositories and the clone flags, recorded as what was measured once
rather than as a bar to clear again.

### Eight widenings measured, and none of them shipped

A coverage phase surveyed eight ways to make the rules ask more, gated on a
held-out corpus with the original kept as a regression check. All eight were
rejected, and the reason is worth more than any of them would have been.

**A rule keyed on a PHRASE has a denominator of zero outside the project whose
phrasing it came from - as long as you sample the wrong population.** Across 30
repositories and 3,821 markdown files, including ten picked for their density
of git-checkable claims, the pattern behind `false-merge-claim` matched
**nothing**. Neither did "merged in `<sha>`", "landed in `<sha>`", or "fixed in
`<sha>`". What those projects write is "commit `<sha>`", 890 times, already
caught by a rule keyed on the shape of a token rather than on a verb.

**That conclusion was wrong, and this release corrects it.** The sampling frame
was the fault, not the method: "claim density" was chosen by picking popular
Python and JavaScript tools, which are dense in CHANGELOGS rather than in
status claims. Scanning 229 repositories from the agent-tooling topics instead
- 52,417 documentation files - finds the shipped merge pattern 35 times, the
release pattern 97 times, the branch token 640 times and the live phrase 117
times. **61 repositories exercise at least one.** The population these rules
serve exists in public and had simply never been sampled.

Measuring against it immediately found a coverage hole none of the eight
candidates named, which is what the correction is worth: see the merge-claim
entry above. It also found this rule's first true positive in somebody else's
repository - neomjs/neo records work merged to `dev` at a commit that is not an
ancestor of `dev`.

The rejections that could be measured were decisive rather than marginal.
Judging a path mentioned without an operative marker takes the tool from 960
findings to 3,964, nearly all of them CHANGELOG entries describing files that
were deleted on purpose. Dropping the letter requirement from the SHA shape
admits 7 findings of which 7 are numbers - a date, two durations in seconds, a
timestamp version. Resolving anchors through site routes changed nothing at all
across 3,821 files, which a fixture confirms is a real zero and not a patch
that failed to apply.

Two false positives are recorded and deliberately left in, because a known one
is cheaper than a guessed rule. A markdown link to a bare domain
(`[x](kubernetes.io/docs/...)`) is 1 finding, and every rule that would catch
it also catches `README.md`. And rust-lang/rfcs, which has no tags and
discusses Rust's releases throughout, has "(released in 1.75)" read as a claim
about itself - the fix for that silences a never-tagged project making a false
claim about its own release, which is a worse trade.

### Verified

Ten real repositories produced byte-identical output before and after, across
2,163 findings. Fixtures alongside them are required to DIFFER, because a
comparison set that never reaches the changed code proves nothing - this
project has a comparison of seven repositories in its history that came out
identical while the code under test was never executed.

That 2,163 is larger than it should be, and the coverage phase found out why:
those clones were made with `--depth 1`, which leaves every historical SHA
unresolvable, so the SHA rules fired on almost everything. vite alone accounted
for 2,094 of them and reports 3 when cloned with its history. The equivalence
the differential proves is unaffected - both sides read the same clones - but
the count describes an artifact rather than a corpus.

`--deleted-since` cannot be differenced at all, being a mode the old collector
does not have, so it is checked for existence instead: the old binary must
refuse the flag and the new one must run it.

### And a probe that was lying

`smoke.py` listed "a check can list the same file under two spellings" as
by-design. Its probe called `note()` unconditionally in an `else` branch,
checking only that the tool had not crashed, so it declared the loophole open
whether or not it was - and reported identically before and after it was
closed. That is the harness committing the defect it exists to detect.

Rewriting it to actually check the routes then failed CI on Linux, and only on
Linux. A case variant is one file on Windows and two on a case-sensitive
filesystem, where the second is genuinely absent and the rule correctly reports
a missing source. That third outcome was present as a COMMENT describing the
case and not as a branch handling it, so the probe fell through to `note()` -
green on the machine it was written on, red on the one it was not.

The comment is what made it invisible: reading the code showed the case
considered, and considered is not handled. **A probe verified on one filesystem
has been verified on one filesystem.** It checks all three routes now.

Two of the three by-design entries are gone; one remains.

## 0.15.0 (2026-07-29)

**A sweep reads reStructuredText.** The Sphinx ecosystem was invisible to a
markdown-only sweep, and it is not a small corner: numpy carries 555 `.rst`
against 14 `.md`, Sphinx 472 against 3, pytest 298 against 6.

Adding the extension alone was not enough and the corpus said so - those
repositories produced 84 findings and almost none were real. So the two
markdown rules are SKIPPED outside markdown rather than adapted to it.
`[text](url)` is markdown's syntax; in Python it is a subscript followed by a
call, and numpy writes `np.dtype[mp.mpf](dps=100)` in a doctest. All 23 of its
link findings were that shape, false by construction rather than by accident.

The claim rules still run, because a dead SHA in rst prose is as dead as one in
markdown. What changes is what counts as prose: literal blocks opening with
`::`, `>>>` doctests, and inline literals are code. Left in place, numpy's
`float64('1e10000')` was read as a commit.

**A sweep of 1600 files went from 49 seconds to about 1 second.** Two pieces
of per-document work were being redone for every file, and both were found by
profiling rather than by reading the code.

`_own_remote` answers a question about the REPOSITORY - what its origin is -
and the pinned-ref rule asked it once per DOCUMENT. Profiled over 400 files
that was 11.3 of 16.2 seconds, 70 percent of the run spent spawning `git remote
get-url` to receive the same string. It is memoised now, and a remote cannot
change while one short-lived process runs.

`validate()` also rebuilds five caches per call - directory listings, ancestry
indexes, resolved refs, LFS state, other documents' headings - because between
two calls the repository may have moved on. During a sweep it cannot: every
document comes from one checkout and nothing in the loop writes. `--sweep` now
declares that scope for its duration and hands it back afterwards, so 20
distinct questions about the filesystem stop being answered 1600 times. The
default stays off, so every other caller keeps the guarantee unchanged.

`--verify` was measured for the same treatment and left alone. It saves 5 ms
out of 337 ms, which does not justify relaxing a correctness promise on the
path that gates commits.

**The project-wide anchor union is built on demand.** Resolving a `#fragment`
against every document at once is what MyST and Sphinx do, and reading every
tracked markdown file is what that costs. It was being done EAGERLY - before a
single link was examined, for documents that may contain no anchor links at
all - and the trigger is one file existing. That file is `conf.py` for Sphinx,
so the cost landed on an ordinary slice of Python projects, on every
post-commit hook run.

Measured on a document held identical while only the config was added: about
40 ms at 100 files, 130 ms at 400 and 400 ms at 1600. Flat in the document,
linear in the repository. Deferred, the same measurement falls within noise of
zero, while a fragment that genuinely needs the union still pays the same few
hundred milliseconds. Stated as approximations because the union is bound by
I/O and varies by about a quarter between runs. The union did not get cheaper;
it became conditional on the only case where consulting it can change a
finding.

Behaviour is unchanged, and that was verified rather than assumed: both
collectors were run over seven repositories and their output compared byte for
byte across 30 findings. The set covers every ambient path deliberately - no
generator, per-page, project-wide, Hugo partials, two carrying install snippets
pinned against their own remote, and this repository.

That last pair was added after the first comparison, because none of the
original repositories had an origin at all - so "identical" would have been a
confident measurement of something other than the change.

The harnesses grew to cover `--sweep`, generated sites and reStructuredText,
all of which had shipped without any measurement of what they cost. That first
campaign found four gaps where the suite reached a behaviour by a route which
bypassed the thing being changed: the sweep's accounting for a file it cannot
decode, Hugo's `_`-prefix guard, the `_format_for` dispatch that chooses rst,
and the `_MARKDOWN_ONLY` gate - which looked covered because a second mechanism
was quietly carrying its test. All four are pinned now.

## 0.14.1 (2026-07-29)

Three false positives, each found by pointing the tool at a repository nobody
here wrote.

**A UUID is not a commit.** microsoft/vscode-docs carries a `ContentId` in the
frontmatter of every page. Split on the hyphens, a UUID's 8- and 12-character
groups are valid hex with both a letter and a digit, so each was read as a
short SHA that does not resolve. 750 of the 789 bare-SHA findings across 40
repositories were fragments of one. Matched and skipped whole, so a real SHA
sitting beside a hyphen still fires.

**A root-relative route resolves to its document.** `/api/ux-guidelines/views`
is a route and `api/ux-guidelines/views.md` is right there. Settleable without
knowing the generator - append `.md` from the repository root and look - which
matters because that project is built by a custom pipeline and ships none of
the ten generator configs this tool detects. Silenced only where the document
exists: 220 of its own routes resolve to nothing and are still reported.

**An empty file under an LFS filter is correct storage.** git-lfs passes zero
bytes through rather than writing a pointer, because there is nothing to store.
Verified rather than assumed: an empty file and a real one under the same
filter yield a 0-byte blob and a 126-byte pointer.

That last one came from o3de/o3de, the largest public LFS repository this
corpus has reached - 123 filter rules over 2,948 governed files, examined in
two seconds. It reported 45 findings; 44 were empty test fixtures and the
forty-fifth was an asset planted on purpose to check the rule still fires.

vscode-docs 1,804 -> 419. o3de 45 -> 1, and that one is the planted asset.

### Also

Two references to the removed secret scan survived in the README: a claim that
a password inside a code fence is still reported, and a finding count that
included one. Both corrected.

## 0.14.0 (2026-07-29)

`possible-secret` is gone. Use gitleaks.

**It found nothing.** Zero findings across 38 repositories and 7,708 markdown
files. The only time it was ever observed firing was on a design document
containing an `sk-` example, which was a false positive.

**It asked a different question from every other rule.** The rest ask "is this
statement still true", which git or the filesystem settles. This one asked
"does this file contain something dangerous", which is a different job. It met
the letter of the falsifiability guarantee while missing the point of it.

**And four regexes are not a secret scanner.** gitleaks ships roughly 150 rules
and trufflehog several hundred with live verification. Four beside them do not
add safety, they add the appearance of it, which is worse: a project that
believes its documentation is scanned for credentials will not reach for a tool
that actually does it.

Eleven rules now. The `--verify` denominator no longer carries a trailing
`(N lines scanned for secrets)`, and fenced code is uniformly exempt from every
rule rather than exempt from claims but not from the scan.

### The cost, stated

`--selftest` could exercise four rules on this repository and can now exercise
three. The secret probe was synthetic, so it was always available, while every
other probe depends on the document offering something real to corrupt. That is
a genuine loss of signal about whether the probe machinery works, accepted
because a rule kept for the convenience of its own test is kept for the wrong
reason.

### And a blind spot it exposed in the smoke harness

`smoke.py` fails a run when an expected finding stops appearing. It cannot see
one that keeps appearing for a different reason.

The probe behind "a baseline can suppress a live credential" tested
`returncode == 0 and "possible-secret" not in stdout`. With the rule deleted
the second half is trivially true, and the first held because of an unrelated
dead SHA, so the flag went on being raised by a probe that tested nothing. The
ledger reported 0 new and 0 missing and looked healthy.

A surviving flag is weaker evidence than a vanishing one. Recorded beside
EXPECTED so the next person removing a rule deletes its probes rather than
leaving them to keep reporting.

## 0.13.2 (2026-07-29)

Everything 0.13.1 described. That tag exists and never published, because the
gate it added rejected it.

The new step asserted that `extant --sweep` exits 0 against the release
fixture. It exits 1 there, correctly: the fixture plants a dead link in
`README.md` and its `.extant.toml` names that file as `primary_doc`, so the
finding is in a CONFIGURED document and a sweep gates on those. The assertion
was written without reading the fixture it was asserting about.

It now checks both directions, the same way the `--validate` half already did:
broken exits 1, repaired exits 0.

Worth recording plainly, because it is the second mistake in a row from the
same habit. `--sweep` broke in 0.13.0 because a list of modes was kept beside
the parser instead of read from it. The gate for that broke in 0.13.1 because
an expectation was written from memory of the fixture instead of from the
fixture. Both were caught by running the thing rather than reasoning about it,
and the second was caught by the first's own gate - on its first run, which is
the only run that could still have been wrong.

## 0.13.1 (2026-07-29, tagged but never published)

`extant --sweep` works when installed. In 0.13.0 it did not.

```
$ uvx extant --repo . --sweep
extant_collect: error: argument --sweep: not allowed with argument --verify
```

The console script inserts a default mode when none is given, and it decided
what counted as a mode from a list written beside the parser instead of from
the parser. `--sweep` was added to one and not the other, so the entry point
put `--verify` in front of it and argparse rejected the pair.

It reads the parser's own mode group now, so a mode added later cannot leave it
behind.

### Why the release gate did not catch it

It installs the built wheel into a clean environment and runs it against a
planted fault, which is the step that exists to prove the artifact works. It
ran `--validate`. The one command the README leads with was the one nothing
exercised, in the release whose headline feature it is.

The gate now runs the documented command too.

## 0.13.0 (2026-07-29)

Run it on a repository nobody here wrote.

That is the whole release. Every version before this was validated against two
repositories, both written by the same hand, neither of which links to another
project's source. Pointed at 38 real projects across sixteen ecosystems, the
released tool cried wolf roughly nine times in ten.

### `--sweep`

```console
$ uvx extant --repo . --sweep
```

No configuration, no file to name, nothing written. It reads every markdown
file git tracks and reports in two sections: documents the configuration names
decide the exit code, everything else is surveyed and never gated on.

That split is not presentation. Checking every markdown file in THIS repository
produces 18 findings and all 18 are false - `abc1234` and `v2.1` are the example
claims inside the documents that document the rules. A sweep that gated on
those would be the cry-wolf failure this project exists to prevent, shipped as
a headline feature.

### It no longer dies reporting a finding

A finding quotes the document, and a document may be in any language. Written
to the cp1252 console Windows hands you, an unencodable character raised
UnicodeEncodeError and the run died AFTER the analysis, at the moment of
reporting it. Every mode, not just the new one.

A test named `..._does_not_crash_the_printer` existed and passed, because it
set `PYTHONIOENCODING=cp437:replace` in the environment - it was proving the
ENVIRONMENT could cope. Output now degrades instead of raising, and SARIF gets
UTF-8 because it is a file rather than console text.

### Fifteen false-positive classes

Each measured on real projects, each with the repository that exposed it:

- Hex inside a URL is another repository's commit, and this one has no opinion
  about it. 287 findings across rust-lang/rfcs, requests and httpx.
- A markdown tree compiled into a website links by ROUTE. VitePress, MkDocs,
  Astro, Hugo, mdBook, Jekyll, Docusaurus and MyST are detected, including
  configs that live in a subdirectory or inside another file. 331 findings from
  vite alone, 235 from starlight.
- A leading slash means the repository root, which is how GitHub renders it.
- Renderers disagree about slugs, and both spellings are right: GitHub drops a
  dot, VitePress turns it into a dash. Whitespace runs are not collapsed.
- A heading may be a link (`## [5.12.0](...)`), carry inline markup, sit inside
  a list item, or repeat - in which case a renderer numbers the later ones.
- Anchors also come from definition-list terms, `{#id}` attributes, JSX
  comments (`{/* #id */}`), MyST `(target)=` lines, and `:label:` directive
  options. None of those is a heading and all of them are real.
- MyST and Sphinx resolve a label against the whole project; MkDocs does not.
  Applying that union everywhere forgave two of httpx's three genuinely dead
  anchors, so it follows the generator.
- An all-digit run is a number. `9223372036854775807` is INT64_MAX in
  Prometheus's documentation and every character in it is valid hex.
- A `#` prefix is a CSS colour. A `@` opens a generator macro, not a path -
  Documenter.jl's `[text](@ref)` was 1,779 findings in JuliaLang/julia.
- Percent-escapes decode: `operator%5B%5D.md` is `operator[].md`.
- Any URI scheme is external, not an enumerated five.

### Also

`dead-md-anchor` now checks fragments on other files, which found seven real
broken cross-references in the corpus. `.mdx` is swept, which reaches 1,378
files in Docusaurus alone. `--sweep` reads HEAD's tree rather than the index,
so a sparse checkout or a clone that failed on Windows path length cannot
report a clean repository.

### For game developers

`raw-lfs-blob` and the `unity` and `godot` presets had never run against an
engine project. Unity's BossRoom declares 47 LFS filters over 480 files, the
rule examines all of them, and planting a genuinely raw asset makes it fire.

Worth knowing: none of Bevy, raylib, Phaser, OpenRA or godot-demo-projects uses
LFS at all. Open-source game repositories avoid the quotas, so this rule is for
the private repositories where art actually lives.

## 0.12.4 (2026-07-28)

Nothing Claude-specific is installed into a repository that shows no sign of
Claude.

### The one tool-specific file is now the one conditional file

`.claude/commands/extant.md` was written on every install, so setting this up
in a Godot project worked on with Copilot planted a `.claude/` directory its
owner could not use and had no way to decline.

It now appears when the repository already carries `.claude/` or a `CLAUDE.md`.
`--claude-command` writes it regardless and `--no-claude-command` never does -
three states rather than two, because a plain on/off flag cannot tell "left at
the default" from "explicitly declined", and the second has to be possible in
a repository that does carry the evidence.

Skipping it is reported and names the flag. A file that does not appear is
invisible, so a silent skip would leave reading the installer as the only way
to discover the slash command exists at all.

`.agents/skills/extant/SKILL.md` is NOT gated on anything. It is the open
Agent Skills path that Codex, Gemini CLI, Copilot, Cursor and Kimi read, and it
is the half that makes the install tool-agnostic. Gating it would have been the
wrong fix to the right complaint.

### A hook no longer ships advice only one tool's users can follow

`main-tree-guard` suggested `git worktree add .claude/worktrees/<name>` to
whoever it had just blocked, inside a hook installed into every repository.
That is this project's own habit rather than a general one. It now suggests
`../<name>`, which is the ordinary git idiom and better advice regardless: a
worktree placed inside the repository is a known trap, because `git -C` in a
dead one resolves upward and reports the parent as healthy.

### What was measured rather than assumed

The review prompting this called the tool tightly coupled to the Claude plugin
spec. Most of that does not hold, and the parts that did were these two.

The validator is standard-library Python and git subprocesses. The payload is
two `.py` files and three shell scripts. The pre-commit and pip routes write no
agent file at all. `.claude-plugin/marketplace.json` is one optional
distribution channel, living in this repository and never installed into
anyone else's.

### Also

`smoke.py` printed "setup wrote both agent files" while naming a file it never
checked existed, so it would have gone on reporting "both" after that file
stopped being written. Now asserted.

## 0.12.3 (2026-07-28)

A quickstart that works, and a harness that can fail.

### The first command in the README did not work

`uvx extant --repo . --validate README.md` is now the quickstart, above the
fold, with no configuration and nothing written into your project.

It replaces `uvx extant --repo . --verify`, which 0.12.2 offered as the
quickest way to see what the tool says. That command cannot work on a new
project: `--verify` checks whatever `primary_doc` names, which defaults to
`NEXT_SESSION.md`, so a first-time reader got `no such document` and exit 1.
Confirmed by installing 0.12.2 from PyPI into a clean environment rather than
by reading the code - the packaged path does read a local `.extant.toml`
correctly, so only the no-config case was broken, which is precisely the case
a quickstart is for.

`dead-pinned-ref` could not have caught this and no rule here could. The
command is prose about how to run a tool, and nothing in git or the filesystem
disagrees with it.

Install also gained a four-row table that picks a route, so choosing no longer
means reading two hundred lines first.

### The adversarial harness runs in CI, and can now fail

`smoke.py` was hand-run. That is how a deleted guard against overwriting
hand-edited agent files left the whole pytest suite green while only this
harness noticed.

Wiring it in first meant giving it a verdict: it ended in an unconditional
`return 0` and exited 0 whatever it found, so a job running it would have
stayed green while every probe failed. It now holds a ledger of four expected
findings, each a documented design decision, and exits 1 on anything outside
it - and equally on an expected finding that STOPS appearing, because a probe
that quietly stops exercising anything prints what a healthy one prints. Both
directions were confirmed by mutation before the job was added.

That second half has a useful consequence: a green smoke job is now evidence
that work happened rather than only an absence of trouble, since probes that
did not run would leave four findings missing and fail.

`perf.py` and `stress.py` stay hand-run on purpose, and the harness README now
says why. They answer with NUMBERS, and a number cannot fail a build without a
threshold; every threshold loose enough to survive a shared runner is too loose
to catch what matters, and every tighter one flakes until the job is ignored.
Failing a build on "0.454s is too slow" would also be the first check here to
judge whether a number is acceptable, which is the one thing every rule in this
project is forbidden to do.

### A probe that flagged a comment

The network probe reported a security finding against a tool that opens no
sockets. It substring-scanned the source, and `clone` appears once, inside a
prose sentence about commits made from one.

It now strips comments and docstrings through the AST while keeping ordinary
string literals, because `_git(repo, "fetch", ...)` is the only shape a real
network call takes. Stripping every string would leave a scan that is
permanently clean and therefore permanently worthless.

Recording it in the expected-findings ledger would have been the easier fix and
the wrong one: it would have preserved the bug behind the word "expected".

## 0.12.2 (2026-07-28)

Installable from PyPI, and a publish pipeline that proves the artifact works.

### A fourth way in

`uvx extant --repo . --verify` runs the validator against a repository without
installing anything, and `pipx install extant` keeps it. This is the VALIDATOR
only: the git hooks and the `/extant` command have to live inside the
repository they check, so those still need the plugin or `install.py`.

### The publish pipeline refuses two things

A tag that does not match the version in `pyproject.toml`, because publishing
0.12.1 under a tag claiming 0.12.2 is a released artifact contradicting the tag
that produced it.

And a wheel that does not work. `twine check` reads metadata and runs nothing,
so it cannot tell a working wheel from one that installs and does nothing. The
job installs the built wheel into a clean environment, runs it against a
repository with a planted fault, and requires both directions: a broken
document exits 1, a repaired one exits 0. A tool that always fails looks
identical to one that works.

Uploads use Trusted Publishing, so there is no API token in the repository, in
a secret, or in anyone's shell history.

### Also

`python -m build` writes an egg-info directory into the payload, beside the
shipped source, and it was briefly committed. `install.py` copies that
directory into target repositories, so it would have landed in every project
installing the tool. Now ignored, along with `dist/` and `build/`.

## 0.12.1 (2026-07-27)

Everything a code review found, and a bug the tool found in itself.

### The one that mattered

`reload_config` left `_SECTION_HEADER` stale. It is COMPUTED from
`entry_prefix` rather than copied, and the refresh loop only walked a table of
plain copies. That matters on the one path `reload_config` exists for -
installed as a package by the pre-commit framework, where configuration is
re-read for the target repository. A project writing `### Phase ` got the
right prefix everywhere and a section splitter looking for the wrong heading
level.

Configuration is now applied in exactly one place. `_CONFIG_DERIVED` holds
builders for all nineteen derived globals, `_apply_config` is the only writer,
and both import and reload call it, so there is no second list to fall behind
the first.

### A false positive on ordinary English

The tool found this one itself. `release_tag`'s version tail was greedy and
swallowed a sentence-ending period, so "Released in v2.1." searched for a tag
literally named `v2.1.`. Every fixture happened to continue the sentence after
the version, so nothing caught it until `--verify` read this project's own
status document and accused it.

### Correctness

- A relative `--baseline` path resolved against the process cwd rather than
  the repository, so a hook running from elsewhere looked for it in the wrong
  place.
- Extra documents hid rules that examined nothing, because the summary
  filtered zero counts. "Examined 0" and "not applicable" are different facts.
- `detect.py` stripped `remotes/origin/` from branch names, but git emits
  `origin/`, so every remote branch was counted under a phantom prefix.
- `venv_python` defaulted to a Windows-only path on every platform.
- The opt-in trunk guard warned and exited 0 when its guard file was missing.
  Wiring it is a request to be blocked, so it fails closed now.
- `extant --repo` with no value raised IndexError instead of an argparse
  error, and two bare prints could corrupt `--format=sarif` output.
- The installer emitted single-quoted TOML for consistency patterns without
  checking for an apostrophe, which ends the string early.
- `todo_exclude_files` and `todo_exclude_dirs` were accepted, parsed, and read
  by nothing. They are live now.

### Also

The CI self-check ran on pushes only, while the comment beside it justified
GitHub annotations by their appearing on a pull-request diff. No PR was ever
annotated. Documentation was corrected in seven files, including a manifest
description still advertising eleven rules and sixteen presets.

## 0.12.0 (2026-07-27)

Game engines: a Git LFS rule, and `unity` / `godot` presets.

Derived by measuring two real projects - Unity BossRoom and Thrive, a shipped
Godot game - rather than from what those engines are supposed to look like. The
measurement contradicted the design four times, and the corrections are the
interesting part.

### raw-lfs-blob

`.gitattributes` is a document making a falsifiable claim: files matching these
patterns are stored as LFS pointers. When that is false nothing says so. Git
accepts the commit, the engine loads the asset, and the repository carries a
real binary in its history forever, where removing it means rewriting history.

It happens two ways, both ordinary: a binary committed before `.gitattributes`
covered its extension, and a commit made from a clone with no LFS filter
installed.

The opposite direction was refused, on measurement rather than taste: "is the
LFS object present locally" would report every asset in the project as missing
on any CI checkout without `git lfs pull`.

No network, and the LFS binary is never invoked. A repository that does not use
LFS pays nothing behind a one-file gate; a 7802-file project that does costs
262 ms.

### The widening that was measured and refused

The plan was to widen `path_pointer` with asset and source extensions. Against
both real projects that rule examines ZERO references: game documentation
writes paths as markdown links, and `path_pointer` needs a backticked path
after an operative marker. Widening it would have been a no-op that looked like
a feature, so neither preset touches it. `dead-md-link` already carries these
projects unchanged.

### Presets keyed on where the version really is

Unity states its editor version in a shields.io badge carrying the exact
`6000.0.52f1`, matching `ProjectSettings/ProjectVersion.txt`. Thrive's README
states no Godot version at all, so that check reads `doc/setup_instructions.md`
against `project.godot`. Keyed on the README, as originally planned, it would
have examined nothing forever while exiting 0.

There is no `unreal` preset: no corpus was measured for it, and
`EngineAssociation` holds a GUID rather than a version for any studio on a
custom engine build.

### A preset now verifies its patterns match, not only that its files exist

A Unity project whose README has no badge was getting a permanent "the pattern
matches nothing" finding, because both files existed and the file check waved
it through. Present-but-unmatched is the same failure as absent, and now gets
the same treatment: the check is skipped and the reason is printed.

## 0.11.0 (2026-07-27)

More than one integration branch, which is what most enterprises actually run.

### One trunk was answering three different questions

Three rules asked "is X an ancestor of trunk", and they meant different things
by it. On a gitflow repository each answer was wrong, in a different direction,
at the same time. Measured on a real fixture rather than reasoned about:

- with `trunk = main`, a FALSE claim about develop was not judged wrong, it was
  never examined. The pattern interpolated the trunk name, so the line did not
  match at all. Two false claims in one document, one per branch, and either
  setting caught exactly one of them.
- with `trunk = develop`, a genuinely shipped `v1.0.0` was reported dead. The
  tag sits on main's release merge; develop received the release branch back,
  not that commit.

### A merge claim now names its own ref

"Merged to `develop` at `abc1234`" says which branch it means, so that is what
gets checked. This needs no configuration and is strictly MORE precise than
comparing against one configured trunk, which is what makes it the right fix
rather than a loosening. A trunk *list* would have made the rule ask "an
ancestor of any of these", which drifts toward `dead-sha` wearing another
rule's name.

`stale-live-claim` and `dead-release-tag` cannot name a ref, so they ask about
the integration branches the repository actually has: the configured trunk plus
whichever of `main`, `master`, `develop`, `development`, `trunk` exist.

### Faster, not just more correct

Ancestry is indexed per ref and reused across all three rules. Previously every
tag and branch cost its own `merge-base` subprocess. Measured on the fixture,
two `rev-list` calls cost 61 ms together against 29 ms for a single
`merge-base`, so this pays for itself from three examined items onward - and a
document naming branches at all names more than three.

### Nothing to change in your config

`trunk` still means what it meant. A `merge_claim` pattern customised before
this release keeps working: one capture group is the old contract, two means
(ref, sha). Setup writes the two-group form.

### Notes

An unbackticked word where a branch would go is not reported as a missing
branch, so "merged to production at `abc1234`" stays quiet while
`` merged to `develp` at `abc1234` `` does not. A branch that no longer exists
is only reported when the commit is on no integration branch either: gitflow
deletes release branches, and a squash merge erases the name from history, so
"missing" cannot be read as "invented".

## 0.10.0 (2026-07-27)

Works with any coding agent, not only Claude Code.

### What was actually Claude-specific

Almost nothing. The validator is Python, git hooks and a pre-commit entry, and
none of that ever cared which assistant was in the room. Exactly ONE line
decided where the agent-facing instructions were written, and it named
`.claude/commands/`.

### Agent Skills is an open standard

Anthropic released the Agent Skills format as an open standard in December 2025.
One `SKILL.md` with YAML frontmatter is now read by OpenAI Codex, Gemini CLI,
GitHub Copilot, Cursor, Kimi Code, OpenCode and twenty-odd other tools as well
as Claude Code. `.agents/skills/` is the cross-platform location: Codex reads it
natively, and Gemini CLI prefers it over its own `.gemini/skills/` when both
exist.

So setup now writes `.agents/skills/extant/SKILL.md`, rendered for your
repository rather than copied. It names your document and your paths, and it
carries the discipline that matters to an agent: read the denominator, and never
make a document pass by deleting the claim it complained about.

Claude Code still gets `/extant` for the end-to-end workflow. Both files are
rendered from the same observations, so they cannot end up describing different
documents - which is asserted by a test, because two agent files disagreeing
about which document to check would be this project's own failure shipped by its
own installer.

### This repository now has an AGENTS.md

It ships an `agent` preset whose whole premise is that these files must be
checked, and it did not have one. It is in `extra_docs`, so the tool checks its
own agent instructions on every run.

### Nothing moved

The Claude Code plugin, the marketplace entry and the pre-commit hook ids are
unchanged. This release adds a file to what setup writes; it takes nothing away.

## 0.9.0 (2026-07-27)

A baseline, so a project with years of existing prose can adopt this without a
week of archaeology first.

### The problem it solves

Point this at a ten-year-old repository and the first run reports everything at
once. That is accurate and useless: CI goes red, nobody has a week for
decade-old documentation, and the tool comes back out. Every linter that
survived enterprise adoption solved this - RuboCop's todo file, mypy's baseline,
Sonar's new-code focus - and it bites this tool harder than most, because the
pitch is "use it on the documentation you already have" and that is precisely
what has accumulated the most rot.

```console
$ extant --verify --write-baseline
recorded 47 finding(s) in .extant-baseline.json

$ extant --verify --baseline
1 new finding(s), 47 suppressed by .extant-baseline.json
```

### Three constraints, which are the actual design

A baseline is a place to hide things, and this tool's authority rests on not
hiding things. The feature is only defensible because of what stops it
loosening, so every one of these is tested and mutation-probed:

**It always states how much it is hiding.** "No findings" and "no new findings,
47 suppressed" are different facts. A baseline that concealed its own size would
be the denominator failure this project exists to surface, reintroduced by one
of its own features.

**Nothing is recorded implicitly.** `--write-baseline` is separate and
deliberate. One that rewrote itself on every run would forgive whatever it had
just found, and the check would decay to nothing while still reporting success.

**An amnesty cannot outlive its finding.** `--baseline-check` reports entries
that no longer occur, because once the claim is fixed its entry forgives
something that is not there - a stale claim, which this project is not entitled
to keep.

A missing baseline file is an error rather than an empty one: treating absence
as "suppress nothing" would turn a ratcheted run back into an ordinary one
without saying so.

### Also in this release: Python 3.9 and 3.10

RHEL 9 and Debian 11 ship Python 3.9; Ubuntu 22.04 LTS ships 3.10. Requiring
3.11 excluded all three, and measuring showed it was for exactly one import.

No syntax was given up. Every module already carries
`from __future__ import annotations`, which makes annotations strings at
runtime, so `str | None` in a signature has worked back to 3.7 the whole time.
There are no `match` statements, no runtime unions, no 3.11 stdlib names.

`tomllib` was the only real floor, and it is imported inside a try/except.
Below 3.11 the tool uses `tomli` - not a substitute parser but the SAME one,
since tomllib was adopted into the standard library from it, so a config file
is read identically on every version. With neither available the tool runs on
its defaults, because a repository with no config file never parses TOML at
all; the failure is raised only when a config file is actually found, naming
the remedy.

`pyproject` declares `tomli` conditionally, so the packaged path that
pre-commit builds from installs it automatically below 3.11 and pulls in
nothing above. The copy-the-files-in path never reads that and degrades on its
own.

Two guards keep the floor where it is claimed to be, because a support claim
decays silently: one parses every module and rejects syntax newer than 3.9, the
other asserts the `__future__` import the first one's exemption depends on. CI
runs 3.9 and 3.10 alongside 3.11, 3.12 and 3.13.

Both of the bugs found here were found by that CI and by nothing else. The
version guard referred to `ast.Match` and `ast.TryStar` by name, which do not
exist before 3.10 and 3.11 - so the check asserting 3.9 support could not run
on 3.9. And `Path.write_text(newline=...)` needs 3.10, with two of its nine
call sites in the shipped installer, so the TOOL raised TypeError on 3.9 rather
than only the suite. A guard for that existed for `read_text` and its own
docstring explained why the write side was safe, which was true when the floor
was 3.11 and stopped being true when it moved.

### Reviewable on purpose

The file is JSON, and each entry carries the path, rule and message alongside
its fingerprint. Fingerprints alone would match correctly and tell a reviewer
nothing about what a colleague just agreed to leave broken. It is a tracked
file; it belongs in review like any other change.

The fingerprint deliberately excludes the line number, which it already did for
GitHub's `partialFingerprints`. An entry therefore survives edits above it,
rather than every recorded finding becoming new the moment text shifts.

## 0.8.0 (2026-07-27)

An eleventh rule: `dead-pinned-ref`, for install snippets pinning a version that
does not exist.

### Why this one had to exist

Fenced code has always been exempt from claim rules, on the sound reasoning that
an example in a fence is not a promise. That exemption cost this project two
broken instructions:

- A README told people to pin `rev: v0.5.0` for a fortnight while the repository
  had **no tags at all**. `dead-release-tag` is the rule for exactly that claim
  and could not see it.
- A Claude Code install line named a plugin id that never existed at any point
  in this project's history.

Both sat in fenced blocks. Both were copied verbatim by anyone following the
instructions, and both failed on first use.

The distinction the exemption was missing: a fence usually holds an example, but
an **install snippet is the one block on a page a reader copies verbatim**. It
is closer to a promise than ordinary prose is.

### What it checks, and what it refuses to

`dead-pinned-ref` reads inside code blocks, fenced and indented alike, and asks
the narrowest answerable question: does the version pinned for **this**
repository resolve?

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0        # ignored: not this repository
  - repo: https://github.com/you/yours
    rev: v9.9.9        # checked: does v9.9.9 exist here?
```

That governing `repo:` line is what keeps the rule honest. A project documenting
somebody else's hook pins a tag living in somebody else's repository, and
checking it would report a finding on a line that is perfectly correct. Only
pins aimed at you are answerable, so only those are asked about. SSH and HTTPS
spellings of the same remote compare equal.

A repository with no `origin` reports **0 examined** rather than a clean run,
because without a remote there is no way to know which pins are yours.

Nothing to configure. `repo:` and `rev:` are pre-commit's fixed syntax rather
than any project's habit, which is the same reason markdown link syntax has no
setting.

### Measured first

Three pins across this corpus, in both fenced and indented blocks, all
resolving, zero false positives. The rule was written to fit that measurement
rather than to a guess about what pins look like, and the third-party case was
found by looking rather than by reasoning.

Six tests, including the two that matter most: a third-party pin must not even
be **counted** as examined, and an SSH origin must match the HTTPS URL a README
shows. A comparison done on the raw URL string passes every other test and
silently checks nothing.

It then caught this repository's own README within minutes of being written.
Bumping the documented pin to `v0.8.0` before that tag existed is precisely the
state it exists to report.

### One thing to know when you release

Between bumping the pin in your documentation and pushing the tag, your
documentation promises a version that does not exist, and this rule will say so.
That is the rule working rather than misfiring: during that window anyone
reading your repository is given an instruction that fails.

If your README is in `extra_docs`, either tag as part of the release or bump the
pin after tagging. The window is real either way; the only question is whether
anything tells you about it.

## 0.7.0 (2026-07-27)

Three more presets, for audiences whose documentation ages hardest.

| Preset | For |
|:---|:---|
| `enterprise` | long-lived projects. Also checks `SECURITY.md`, `SUPPORT.md`, `UPGRADING.md`, `MIGRATION.md` |
| `ml` | data and model projects. Also checks `MODEL_CARD.md` and `DATA_CARD.md`, and that `pyproject.toml` and `environment.yml` pin the same Python |
| `legacy-web` | older web apps. Also checks `INSTALL.md`, `DEPLOY.md`, `UPGRADING.md`, and that `.nvmrc` and `package.json` agree on Node |

### What shaped them

All three lean on **extra documents** rather than on clever patterns. A support
policy, an upgrade guide and a deployment note are where a project's oldest
links and file pointers live, and age is the entire subject here. An LTS project
does not usually have a stale README; it has a `MIGRATION.md` last edited in
2021 pointing at three files that have since moved.

Their consistency checks compare **two machine-readable files**, never prose
against a manifest. Every existing check does the same, and it is why none has
produced a false positive: a JSON version field has one spelling, whereas a
sentence naming a version has as many spellings as it has had authors.

Each check is also a **pair**. A check is only emitted when every file it names
is present, so a third file makes it likelier to be skipped than to catch
anything.

`enterprise` carries no consistency check at all, deliberately. It names an
audience rather than a language, so there is no manifest common to its members,
and a guessed pair would be skipped on most repositories and wrong on the rest.

### Verified

Every pattern was run against real-format samples before shipping, because a
pattern that matches nothing is the failure this project exists to surface: all
eight captured the value they were aimed at.

Both new consistency checks are then tested in both directions - agreeing files
must pass, and one edited file must produce a finding that names the check. A
one-directional test would be satisfied by a pattern that matches nothing.
Proved by breaking the `.nvmrc` pattern and watching it fail, which it did
twice over: the test caught it, and the tool independently reported the pattern
as matching nothing.

### Fixed

- `/plugin install status@extant` in the README and the 0.1.0 entry, a casualty
  of the 0.6.0 rename's catch-all rule. The correct command is
  `/plugin install extant@extant`, and the wrong one was never right at any
  point in this project's history. It sat inside a fenced code block, where no
  rule here can see it.

## 0.6.1 (2026-07-27)

Fixes the `readme` preset, which did not work on the projects it exists for.

### The bug

```
install.py --repo . --preset readme
-> "no status document found in the usual places"   exit 1
```

The preset names `README.md`, which is not one of the status-document names
detection looks for. Detection found nothing and the installer exited **before
the preset was ever consulted**, so a preset documented as "no status file
needed" refused to run without one. Passing `--doc README.md` alongside it
worked, which is what made the cause visible.

### A second defect underneath it

Folding the preset in after detection was wrong even when detection succeeded.
Everything else is derived FROM the chosen document: the archive is placed
beside it, and the recorded evidence quotes its length. Switching the document
afterwards left those describing the previous file, so a repository with
`docs/NEXT_SESSION.md` could end up with `primary_doc = README.md` at the root
while the archive stayed in `docs/`, beside a document no longer being checked.

The document is now settled before anything derives from it.

### Which wins

An explicit preset outranks detection for the **document**. That is not in
tension with the existing rule that a preset never overrides something
MEASURED: that rule is about the trunk name and branch shape, which the
repository owns and a template would only be guessing at. Which file to check
is the user's call, made by passing the flag.

### Why it shipped

Presets had no tests. All five were checked by hand before 0.5.0, every one of
them in a repository that already had a detectable status document - so the
preset whose entire purpose is a project *without* one was never exercised in
the only situation it exists for.

`tests/test_install_presets.py` now runs the installer as a subprocess, because
the exit code and the file it leaves behind are the contract, and pins seven
behaviours including the no-document case and the archive following the chosen
document. Four of them were watched failing with the fix removed.

Found by installing 0.6.0 from the published marketplace and running it the way
a new user would, which was the first time that path had been exercised.

## 0.6.0 (2026-07-27)

Renamed to **extant**. No behaviour changed; every name did.

### Why

"Handoff" named one half of the tool, and after 0.5.0 it was the minority half.
The engine had always worked on an ordinary README and a package manifest, but
anyone arriving at a project called `handoff-validator` reasonably concluded it
wanted a ceremony they do not perform. The name was the last stale claim in a
repository built to find stale claims.

**extant** *(adj.)* - still in existence; surviving. Six of the ten rules ask
exactly that: does this commit, branch, tag, file, or heading still exist? It is
also a word that already belongs to documents, and it promises nothing about
truth, which matters because this tool refuses to judge whether a value is
correct.

### What changed

| | Before | After |
|:---|:---|:---|
| repository, package | `handoff-validator` | `extant` |
| command | `handoff-validate` | `extant` |
| configuration file | `.handoff.toml` | `.extant.toml` |
| configuration table | `[handoff]` | `[extant]` |
| pre-commit hook ids | `handoff`, `handoff-annotate` | `extant`, `extant-annotate` |
| modules | `handoff_collect`, `handoff_config` | `extant_collect`, `extant_config` |
| slash command | `/handoff` | `/extant` |
| primary document setting | `handoff_doc` | `primary_doc` |
| preset for status projects | `handoff` | `status` |

This is a breaking change for anyone who installed 0.5.0: the configuration
file, its table name, one setting, and both hook ids are different. It is made
now precisely because the audience for whom it breaks is small, and it will only
ever grow.

### One word deliberately kept

`HANDOFF.md` survives, in the document-detection list and in the fixtures that
stand in for a user's file. It is not this project's name; it is a filename the
tool LOOKS FOR in other people's repositories. Renaming it would not have
rebranded anything, and a blanket substitution first turned the candidate list
into two identical entries, which is a detection bug wearing a rename's clothes.

### How it was done

746 occurrences across 38 of 41 files, as an ordered substitution with the
most specific rules first, so that a bare `handoff` rule could not eat
`handoff_collect` and leave `extant_collect` unreachable. Every rule reported
its own count, and the total reconciled against an independent count of the
three case variants: 735 replaced plus 11 protected equals 746, with nothing
unaccounted for.

Rehearsed on a throwaway clone before the real tree was touched. That rehearsal
earned its keep: the first attempt renamed a path component written as a
separate string literal, pointed six test files at a directory that did not
exist, and renamed the TOML table to the wrong word in three places.

## 0.5.0 (2026-07-26)

Repositioned, plus presets and a pre-commit hook. The engine barely changed;
what changed is who can use it.

### It never needed a status document

Peer review landed on one point hard: most teams keep no running status file, so
the tool looked useless to them. Testing that claim rather than accepting it
showed the engine already handled an ordinary project - a README, a
package.json, a CONTRIBUTING file - and found a dead commit reference, a dead
link and a Node version disagreement with no code changes at all.

So the barrier was the pitch, not the engine. The README, SKILL.md and
marketplace entry now lead with "your documentation makes claims; this checks
whether they are still true". Status documents are one shape rather than the
price of entry.

The audience table said "probably not for you" to exactly the projects now being
targeted, which is the sort of stale claim this tool exists to catch.

### Presets

    python install.py --repo . --preset readme

`readme`, `node`, `python`, `rust` and `status`. A preset chooses the documents
and the shape; detection still supplies trunk, branch naming and commit
conventions, because those are measured and a template would be a guess.

Checks whose files are absent are skipped and reported, so a preset never opens
by complaining about a file you do not have - a tool whose first act is a false
positive has taught a lesson that is very hard to unteach.

### pre-commit framework

    repos:
      - repo: https://github.com/scooter-sensei/extant
        rev: v0.5.0
        hooks:
          - id: extant

Runs on every commit regardless of which files changed, deliberately: merging a
branch can falsify a sentence without editing a line of prose.

Verified against the real framework rather than written from the documentation.
It built its environment from the repository, read the consumer's config,
validated that project's README rather than a default filename, failed on the
rotted version and passed once the docs were fixed.

That last part needed a real fix. Configuration is read at import relative to
the file, which under pip is site-packages - so the hook would have validated
NEXT_SESSION.md in every project on earth and reported a healthy run for the
ones with no such file. `reload_config` re-reads for the repository being
checked, and a test parses `extant_collect.py` for every `NAME = CONFIG.field`
assignment and fails if one is not reloaded, so a future derived global cannot
quietly keep a stale value.

### Fixed

- The installer emitted `plans_dir = ` with nothing after it when a preset
  switched a feature off. That is not valid TOML, so the installer wrote a file
  the tool then refused to read. An installer that emits a broken config is
  worse than one that emits none.
- `pyproject.toml` exists now, for one reason: pre-commit builds an isolated
  environment and `language: python` needs something installable. Copying files
  into the target repository remains the primary install path, because the hooks
  and slash command have to live there.

### What the pre-release audit changed

All five harnesses were run before tagging. One assertion was genuinely wrong,
and the documentation had drifted in four places.

The hooks scenario asserted that a default install wires a `pre-commit` hook,
which was the contract before the trunk guard became opt-in. The product was
right and the assertion was for the retired shape. Passing the new flag would
have left the DEFAULT untested, which is the half that matters: a documentation
checker silently regaining the power to refuse a commit is the worse failure.
Both directions are asserted now, plus a misspelled flag, which must be refused
rather than quietly installing the advisory set.

That failure only surfaced because a POSIX shell was on PATH. Without one, ten
hook tests skip and the suite still prints green - and the hooks were the part
that had just changed. The unit suite degraded into silence where the scenario
harness crashed, which is the whole argument for keeping both.

A third ASCII test now reads every shipped file whole. The existing two
tokenize Python string literals and read the shell hooks, so neither had ever
opened a markdown file, and prose is where an em dash actually arrives. It is
allowlist-free deliberately: an extension filter is how such a check quietly
stops covering things, which it proved by catching a hand-written scan of my own
that had skipped the three extensionless hooks.

Corrected, none of it catchable by any rule here, because no rule inspects a
number:

- This repository's own status document stopped at Phase 3. Its "Next Tasks"
  listed `--search` and rename autofix, both of which 0.4.0 delivered, and its
  "Known Issues" listed the settings-loading bug that this release fixed.
- `references/config.md` documented every setting except the consistency block,
  the one configuration feature 0.4.0 added. It now covers that, the merge of
  top-level and `[extant]` keys, and the upward search stopping at the
  repository root.
- `CONTRIBUTING.md` named two further audit harnesses beyond the mutation
  campaign where there are four, and described the ASCII rule as applying to
  string literals only.
- The harness README claimed nine stress cases for a run of twelve, and
  `scenarios.py` printed its own denominator as a hardcoded string.

## 0.4.0 (2026-07-26)

Five additions, one of which exists because this project shipped the bug it
catches.

### `inconsistent-artifact`: files that contradict each other

Three manifests advertised version 0.1.0 while the CHANGELOG documented 0.3.0.
Anyone installing was told they were getting the first release, and nothing here
could catch it because no rule inspects numbers.

That restriction stands and this does not weaken it. The forbidden question is
whether a value is CORRECT - "the suite was 2238" has nothing to be checked
against. Whether two files in the repository state different values for the same
thing has a definite answer needing only the filesystem.

    [extant.consistency.version]
    "package.json" = '"version":\s*"([^"]+)"'
    "CHANGELOG.md" = '^## (\d+\.\d+\.\d+)'

Off unless configured, because the files and patterns are per-project and a
guessed default would accuse an innocent repository. A check listing one file is
rejected at load: it could only agree with itself. So is a pattern with no
capture group, which would have nothing to compare. A pattern that matches
nothing is reported rather than passing quietly.

It is the first rule with `scope = "repository"`. It reads no document, so it
runs once on the primary pass rather than repeating the same disagreement for
the archive and every extra document, and its configuration comes from the
repository being checked rather than from the installed copy.

### `--search`: find a decision after it was archived

    python tools/extant_collect.py --search "checkout"

Searches the live document and the archive together, and returns whole ENTRIES
rather than matching lines. That is the only reason it beats grep: a decision
lives in a dated entry with its reasoning, and a line from the middle tells you
a phrase exists rather than what was decided.

### `--suggest-fixes`: a patch, never an edit

Prints a unified diff repointing references at files git recorded as renamed.
It writes nothing, and stdout carries only the patch, so it pipes into
`git apply`.

This tool's authority rests on checking claims and never writing them. A
validator that edits prose can be wrong in a new way - it can author a falsehood
itself - and nothing would be left to catch that. Only recorded renames are
offered; a merely missing file gets no suggestion, because guessing where it
went is exactly the authoring this refuses to do.

Replacement is confined to where a path is USED as a reference. A bare
find-and-replace would also rewrite the sentence explaining the move, which is
often the one a reader most needs intact.

### `mutate.py --check-only`: catch mutation rot in CI

Sub-second, because it runs no tests: it asks only whether every mutation still
matches the code it names. Mutations rot alongside that code - one silently
stopped probing anything when ancestry moved to a batched rev-list, and it went
unnoticed until the next half-hour campaign. Now in CI, so the rot is caught by
the commit that causes it. It caught one during this very release.

### Linux timing in CI

Every performance number in these docs was measured on Windows, and the docs
said so rather than claiming a figure never taken. CI now measures `--verify` on
Linux and prints it as an annotation, so the claim has evidence on the platform
most people run this on.

### Fixed

- Configuration is now found by searching upward from the script to the
  repository root, stopping at `.git`. Looking only beside the script meant this
  project could not configure its own tool: CI invokes it from inside `plugin/`,
  found nothing, and reported a healthy run against default settings. The bound
  prevents a nested checkout from inheriting an outer project's config.
- The "settings came from elsewhere" warning compared paths as strings and could
  report that the file it had just read was not read.

## 0.3.0 (2026-07-22)

### Fixed: one rule was 98 percent of validation time

`false-merge-claim` spawned two git subprocesses per mention. On a 4000-line
document that was 17.7 of 18.0 seconds. `dead-sha` handled identical volume in
0.064s, because it batched existence checks through `git cat-file --batch-check`
- the optimisation existed and had simply never been carried across.

Existence now uses the same batched path, and ancestry is asked once per
DISTINCT commit rather than once per mention, since documents repeat the same
SHA constantly. Scoped to a single call rather than memoised across the process:
git state changes between runs, and a cache outliving the run would answer from
a repository that no longer exists in that shape.

| document | before | after |
|---|---|---|
| 4,000 lines | 16.69s | 0.77s |
| 16,000 lines | 66.68s | 1.59s |
| 2,000 distinct merge claims | 104.8s | 2.1s |

The third row came from a stress case aimed at the fix above: deduplicating by commit buys nothing when every claim names a different
one. Ancestry now comes from a single `git rev-list` rather than one
`merge-base` per commit. Measured on 5000 commits, rev-list costs 125ms
against roughly 100ms for a single merge-base, so the batch pays for
itself at two distinct commits and is used unconditionally: a
size-based switch would create a second path that only runs on large
inputs, which is the code that never gets tested.

A profile of the remaining time found two pieces of duplicated work rather
than any algorithmic problem: nine rules each stripped the same document
independently (1.22 of 6.4 seconds producing nine identical copies), and the
case check listed a directory per path component with no cache (0.88 seconds
across 3000 links). Both are now reused, taking a 5.5 MB document from 5.0s to
4.1s and 3000 deep links from 3.0s to 0.7s.

The two caches are scoped differently on purpose. The stripped text is keyed on
object IDENTITY, so it needs no lifecycle: every rule in one validate() sees the
same object, and anything else misses. Directory listings cannot use that trick,
so they are cached ONLY while validate() has scoped them and are off by default
- a caller that creates a file between two direct checks must see the new
answer. Peak memory rose from 3.1x to 3.9x the document size, which is the
honest price of holding one stripped copy.

Scaling went from linear to sub-linear. The git hooks also now get three paths
from one `git rev-parse` instead of three, saving about 170ms per commit on
Windows, where each subprocess costs roughly 90ms.

A test counts git invocations rather than seconds: a wall-clock assertion would
be flaky on a loaded machine and would not say why it got slow.

### Fixed: a file path reported as a phantom branch

`unknown-branch` reported `docs/arch.md` as "a branch that does not exist and
appears in no merge commit". A branch token and a file path are the same shape,
and the installer's fallback pattern for a repository with no dominant branch
prefix matches both.

It stayed invisible while that pattern fed only `stale-live-claim`, which gates
on a live phrase appearing in the same entry first. `unknown-branch` has no such
gate and inherited the looseness. Both rules now decline a token better
explained as a file, and the denominator counts what the rules inspect rather
than what the pattern matched.

Found by installing into a foreign repository and reading the output, not by any
test. It is the exact failure the path-pointer rule was designed around years of
this project's own advice ago, reintroduced by a new rule that reused an old
pattern without re-reading why the pattern was safe where it already lived.

### Added

- **`--format=github`** emits GitHub Actions annotations, so a false claim is
  highlighted on its own line in the pull request diff rather than sitting in a
  log. Runs on this repository's own document on every push.
- **`--format=sarif`** emits SARIF 2.1.0, the format code-scanning tools
  exchange. Rule descriptors are generated from the registry, so a rule's
  `falsifiable` question becomes its published description: a rule cannot reach
  this output without having stated the exact question it asks.

Neither adds a rule or a false-positive surface. Both are rendering of findings
that already existed, which is why they came first out of the improvement list.

### Notes on the details that are easy to get silently wrong

- Annotation properties escape `,` and `:`, and messages escape newlines. A raw
  comma in a path truncates the workflow command and the annotation lands
  nowhere, with no error.
- In SARIF mode every human diagnostic moves to stderr. The denominator summary
  is useful and is not JSON; leaving it on stdout makes the document unparseable
  at the far end, long after the run.
- `partialFingerprints` deliberately EXCLUDE the line number, so a finding that
  moves keeps its identity instead of being re-reported as new.
- Findings now carry the document they came from. The file previously existed
  only inside the print statement that rendered it, which was enough for a
  human and not enough for a machine.

## 0.2.0 (2026-07-22)

Four new rules, a way to prove any rule actually works, and checking that
reaches beyond the one status document.

### Added

- **Markdown link and anchor checking.** `[text](docs/gone.md)` and
  `[jump](#no-such-heading)` were both invisible: the path rule only sees
  backticked paths after an operative marker. Link syntax is fixed by the
  format, so unlike the prose patterns these need no configuration.
- **`unknown-branch`.** A branch named in the newest entry that git has never
  seen, in refs or in any merge commit.
- **`dead-release-tag`.** "Released in v2.1" where no such tag exists, or it is
  not an ancestor of trunk. For CHANGELOG-keeping projects.
- **`extra_docs`.** Further documents get every whole-file rule: `CLAUDE.md`,
  `AGENTS.md`, a README. Entry-scoped rules are skipped, because those files
  have no dated entries.
- **Rename hints.** A dead pointer now says where git shows the file went.
- **`--selftest`.** Corrupts one real claim per rule and reports which rules
  noticed. Probes mutate actual prose rather than injecting invented text, so
  what is exercised is your configuration against your writing. CI runs it here
  on every push, so the rules are watched failing rather than assumed to work.

### Measured before building, and it changed the plan

- A branch-existence rule keyed on "does this branch exist" would have produced
  **four findings and four false positives** on the first corpus it was measured
  against: every branch named there had been merged and then deleted, which is
  ordinary hygiene. All four were still named in merge commits, and that is what
  the shipped rule keys on.
- Markdown links and release phrases were measured as **entirely absent** from
  the status documents available. They are shipped because they are common in
  the general documentation `extra_docs` now reaches, and their denominators
  report 0 honestly where they do not apply.

### Fixed

- `--repo` now warns when it is pointed at a repository whose `.extant.toml`
  is being ignored. Configuration loads relative to the script, which is right
  when installed but silently wrong when run from elsewhere.

## 0.1.0 (2026-07-22)

First public release, extracted from the project it was built and proven on.

### Features

- Installable as a Claude Code plugin: the repository is its own marketplace,
  so `/plugin marketplace add scooter-sensei/extant` followed by
  `/plugin install extant@extant` is the whole setup. The validator,
  the hooks, and the CLI still work standalone with no Claude Code involved.
- Five validation rules, each falsifiable against git or the filesystem: dead
  commit references (backticked and bare), stale live claims, false merge
  claims, dead path pointers, and credential shapes.
- `--verify` and `--validate` report the **denominator** for every rule, so a
  pattern that matches nothing is visibly different from a clean document.
- `--collect` gathers facts into a JSON bundle: commits since the last status
  grouped by phase or ticket, changed files, TODO markers, suite result, and
  plan checkbox state. Records whether a suite figure was measured or supplied.
- `--archive` rotates old entries into an archive document, asserting multiset
  line conservation against the raw file bytes.
- `--sha-map` repairs dead commit references after a `git filter-repo` rewrite.
- Configuration is **derived by inspecting the target repository**, with a
  confidence level per value. Undetermined values are written commented out
  rather than guessed.
- Works with any language: `suite_command` takes any test runner, and
  `--suite-json` accepts a result from CI instead.
- Git hooks for `post-commit`, `post-merge`, and an optional `pre-commit`
  trunk guard.
- Optional Claude Code `/extant` slash command, rendered per repository.

### Changes made during extraction

These were defects in the original that only became visible when the tool was
installed somewhere else. All are fixed here.

- The slash command was copied verbatim, so every installation named the source
  project, wrote to that project's document paths, and carried its test counts.
  It is now a template rendered per repository.
- The post-commit hook guarded its work with a hardcoded document name while
  the validator it invoked read the configured one. Any repository using a
  different name installed the hook cleanly and validated nothing, silently. It
  now resolves the name from configuration, and distinguishes "no document
  configured" from "the configured document is missing".
- The pre-commit trunk guard was wired by the hook installer but never shipped
  by the file installer, so it never ran. It is now shipped, and reads the trunk
  from configuration rather than assuming `main`.
- String literals are ASCII only. An em dash in printed output raises
  `UnicodeEncodeError` on a cp437 console and killed the installer partway
  through, after it had already copied files.
