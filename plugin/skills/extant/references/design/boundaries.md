# Boundaries: git, the environment and what the tool may read

Part of the design rationale; [its core](../design.md) maps every part and
section. Where the tool meets something it does not control - a subprocess's
bytes, the environment a hook inherits, a configured path or pattern - and the
failures that fixed where each boundary sits. The sections are in the order
they were written.

## Where a decode happens is a decision, not a default

`plugin/skills/extant/payload/extant/git.py` ran every git command with
`text=True`. That reads as "give me a string" and means "decode this somewhere
I have not named", and where that somewhere is differs by platform:

- On Windows `Popen._communicate` decodes on a reader THREAD. A byte git emits
  that is not valid UTF-8 kills that thread, `communicate()` hands back None,
  and `_git` returns None to callers annotated `-> str`. `_git_soft` cannot
  catch it, because nothing was raised for it to catch.
- On POSIX the decode happens in the caller's own thread at the end of the
  same function and raises `UnicodeDecodeError` - which `_git_soft` does not
  list either, so the path documented to return the empty string rather than
  raise, raises.

One silent wrong answer and one crash, out of one line, chosen by the operating
system. The silent half is the one that matters here: a rule handed None finds
nothing, and finding nothing prints exactly what a clean document prints.

**It was already diagnosed, one call site away.** `_document_at` - in
`plugin/skills/extant/payload/extant/sweep.py` then, in
`plugin/skills/extant/payload/extant/deleted_since.py` since the mode left on
2026-09-14 - carries a paragraph describing
this mechanism exactly, because that mode hit it and was repaired there by
capturing bytes. What a fix in that position cannot do is repair the module
every rule asks its questions through.

**The reachable case is a path, not a commit message.** `tracked_markdown` in
`plugin/skills/extant/payload/extant/refs.py` decides which documents a sweep
looks at AT ALL, and it runs `ls-tree -r -z --name-only`. The `-z` turns OFF
the `core.quotePath` escaping that would otherwise render unusual bytes as
ASCII, so the raw bytes arrive on every platform and under every
configuration. Against a repository holding one tracked file whose path is not
valid UTF-8, `--sweep` - the mode a first-time reader runs - exited with
`AttributeError: 'NoneType' object has no attribute 'split'`. That function's
own docstring calls a listing which comes back short "the worst shape available
- a silent all-clear on a repository nobody checked", and this was the route to
one it did not anticipate.

Pre-UTF-8 history is not exotic. A latin-1 or Shift-JIS commit subject written
before an `encoding` header was routine emits such bytes from `git log`, and
reading other people's repositories is what this tool is for.

**`errors="replace"` is right here and stays wrong one module over,** which is
why this is a decision and not a default to apply wherever the same call shape
appears. `_git` returns git's own METADATA - ref names, object ids, commit
subjects - where a replaced character costs a garbled name inside a message
nobody validates. `_document_at` returns the DOCUMENT, where the same
substitution would have every rule checking text the file does not contain, so
that one decodes strictly and reports what it caught. Same bytes, different
question, different answer. The newline translation is
`subprocess._translate_newlines` verbatim, so a caller splitting on newlines
sees what it saw before.

**Two sites with the same shape were left alone, and the reason is
reachability rather than oversight.** `_batch_shas` in
`plugin/skills/extant/payload/extant/refs.py` feeds `cat-file --batch-check` a
string, so what git echoes back for a missing object is valid UTF-8 by
construction; the `_search_with_limit` child in
`plugin/skills/extant/payload/extant/rules/consistency.py` speaks JSON in both
directions, and `ensure_ascii` keeps that pure ASCII whatever the pattern
holds. A fix neither reachable nor falsifiable is a change nobody can watch
fail, which is the shape this project refuses everywhere else.

## The conservation check proves a value, not a write

`archive()` in `plugin/skills/extant/payload/extant/entries.py` calls itself
the only irreversible file operation in the system and asserts multiset
conservation of every line before writing anything. That assertion is about
two strings in memory. It says nothing about a process that dies between the
two `open(..., "w")` calls that put them on disk, and no ordering of those two
writes changes what the Counter sees.

The primary was truncated first and the archive written second, so the window
between them held the retired entries in NEITHER file - the one outcome the
function exists to make impossible, reached by a route its own guard cannot
observe. Writing the additive file first inverts the failure: the same crash
leaves the entries in both, and a duplicate is something a reader can repair.

The general form is worth keeping: a guard that runs before the writes bounds
the VALUES being written, and ordering is the only thing that bounds the
partial states. Where both matter, both have to be stated.

## A configured pattern that will not compile should name itself

`_compile_consistency` in `plugin/skills/extant/payload/extant/config.py` has
always wrapped a bad consistency pattern into a `ValueError` naming the file
and the setting. The other configured patterns beside it compiled bare, and
`re.error` is NOT a subclass of `ValueError` - so nothing guarding a
configuration load caught it, and what reached the operator was a message about
a character position inside a pattern they never see.

The timing was worse than the wording. Settings load at IMPORT, so the
traceback arrived out of this package before any mode had begun, for a typo in
theirs. All of them route through one helper now, and the test asserts each
setting names itself rather than checking one and trusting the rest - a helper
applied to nine of ten leaves the tenth failing in exactly the way the test was
written to stop.

## The environment a git process inherits is an answer, and it was the wrong one

`_git` in `plugin/skills/extant/payload/extant/git.py` ran `["git", *args]`
with `cwd=repo` and whatever environment the process was started with. Those
two decide different things. `cwd` decides which WORKING TREE git looks at;
`GIT_DIR` - and six variables like it - decides whose HISTORY it answers
about. Git exports `GIT_DIR` and `GIT_WORK_TREE` to every hook it runs, a
pre-commit framework sets them too, and a harness that drives one
repository's hook against another's checkout passes them straight through.

Verified before anything was changed, on this machine: from a second
repository, `GIT_DIR=../r1/.git git log -1` printed the first repository's
subject while `git rev-parse --show-toplevel` still named the second. So a
hook checking any checkout other than the one it fired in - a submodule, a
linked worktree, a sibling in a monorepo - had every git-backed rule
answering about the wrong repository, and the run printed exactly what a
clean one prints. The test that pins it cites one commit from each of two
repositories and asks which is dead; under any of the four leaks that move
that answer, `dead-sha` reported the wrong one, or - with an alternate
object directory - neither.

**Every git process now gets one environment**, built by `environment()` in
the same file: the operator's, minus the seven variables that name a
repository, plus `GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS=`,
`GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C` and `GIT_NO_LAZY_FETCH=1`. Applied at the
seam AND at the six sites that call `subprocess` directly - the `cat-file`
batches, the attribute query, `git show` - because a scrub at the seam alone
would have left the SHA rule, the LFS rule and `--deleted-since` answering
from the leaked location while everything else answered from the right
one. The structural test records every git process three modes start, with
the environment each was handed, and its denominator is that each direct
site was actually reached: nine of fourteen were unscrubbed the first time it
ran.

**`GIT_CONFIG_COUNT`, its keys and values, and `GIT_CONFIG_PARAMETERS` are
deliberately kept.** They carry configuration rather than a location. CI uses
the triplet for `safe.directory`, and `git -c` passes its arguments to every
process it starts through `GIT_CONFIG_PARAMETERS` - verified by reading a
hook's environment under `git -c` - so a child that lost them would fail where
the parent works. What they can do is rewrite a remote URL, and that is
handled where the URL is read, below.

**`core.quotePath=false` rides in the same environment**, appended to the
operator's own `GIT_CONFIG_COUNT` set rather than passed as `-c` in front of
every subcommand, so the argv every test and budget records stays the
question that was asked. On by default, the setting prints a path holding
any byte above ASCII as a quoted, octal-escaped string. Two readers were
caught by it, both verified on the command itself: the rename map read out
of `log --name-status` held `"docs/\303\234bersicht.md"` where a document
writes the umlaut, so the pointer was still reported dead and the "renamed
to" hint silently did not appear; and `--deleted-since` compared such a
document's name against `diff --name-only`, never matched it, and examined
nothing. The `-z` listings were never affected; `-z` turns the quoting off.

**`--repo` below the root is said, not refused.** From a subdirectory git
walks up and answers about the checkout above while every document and path
resolves against `--repo` - `rev-parse --show-toplevel` from `r2/sub/deeper`
prints `r2`, quietly. `repository_root` finds the root the way git does, by
stat rather than by spawn, because the budget in `tests/test_spawn_budget.py`
has no spare margin and a question asked once per run is still a question.
A note rather than a refusal because `--repo <subdir>` has worked since the
flag existed. A directory with no repository above it - a `git archive`
extract - gets a note too, in front of the thirteen rule errors that would
otherwise have to imply the cause.

### The remote guard read one file, and a rewrite can live in five other places

`remote_url` reads the repository's own config file instead of spawning
`remote get-url`, and declines when that file mentions `insteadOf` or an
include. But `url.<base>.insteadOf` is equally effective from `~/.gitconfig`,
the XDG file, `/etc/gitconfig`, a conditional include of any of them, the
`GIT_CONFIG_COUNT` triplet, or the `GIT_CONFIG_PARAMETERS` that `git -c`
exports. The guard read none of those. A sandbox that injects exactly that
found it: the `scp-style-ssh` row of `tests/test_remote_from_disk.py` went
red with `git=https://github.com/acme/widget.git
file=git@github.com:acme/widget.git`.

That rewrite changes only the host and lands on the same `owner/name`, which
is what the guard's comment had reasoned about. **The audit of this fix
found that the obvious counter-example does too.** `_normalise_remote`
compares the LAST TWO path segments, so
`url.https://internal/mirror/.insteadOf = https://github.com/` - git reports
`https://internal/mirror/acme/widget.git`, verified - still reads as
`acme/widget`, and the first end-to-end test, written against that mirror,
failed by finding the rule unmoved. The rewrite the guard is for moves the
repository under another owner: `url.git@internal:widgets/.insteadOf =
https://github.com/acme/`, which git reports as `git@internal:widgets/widget.git`
and the rule reads as `widgets/widget`. Then `dead-pinned-ref` compares a
project's pins against a repository git would not name, silently - and the
end-to-end test asserts the rule now answers `widgets/widget` through the
spawn the guard falls back to.

**Fixed with reads, not a spawn.** `_unsettled_elsewhere` stats and reads
every file git treats as global or system configuration that can be named
without asking git - `GIT_CONFIG_GLOBAL` when set, else `~/.gitconfig` under
every spelling of home the process can see and the XDG file;
`GIT_CONFIG_SYSTEM` when set, else `/etc/gitconfig` and `etc/gitconfig`
under the install prefix of the `git` on PATH, which is where Git for Windows
keeps its system file (`C:/Program Files/Git/etc/gitconfig` here) - and scans
the two environment injections. Any mention of a rewrite, an include, or a
remote of its own declines. A remote SECTION is refused in these scopes and
not in the repository's file where it is expected, because `get-url` reports
the FIRST value and scopes are read system, global, then local: a remote
defined globally wins the lookup.

Seven scopes are each tested with the path-changing rewrite, each asserting
first that git itself reports the mirror - so a fixture that failed to
reproduce the divergence cannot pass by accident - and then that the fast
path declines. The denominator beside them: with every other scope pinned
empty, the plain spelling is still answered from disk, because a guard that
declines everywhere passes the seven rows and buys nothing.

**The walk to the install prefix missed the file in every hook.** The seven
rows name the system file through `GIT_CONFIG_SYSTEM`, so the walk from the
`git` on PATH ran only ambiently - through whatever git the suite found,
against a system file with nothing in it to find - and cutting it from three
parents to two left the whole suite green on a copy. Writing the table that
pins it, with a fake `git` on PATH and the variable unset, turned up the
layout it had never been asked about. git puts its exec path first on PATH
for every hook it runs, so in a real post-commit hook the first `git.exe` was
`C:/Program Files/Git/mingw64/libexec/git-core/git.exe`: three directories
below the prefix holding the system file, one further than the walk reached.
A shell found the file and the hook did not - and a hook is where the
installer runs the shim. git strips `libexec/git-core` and `bin` alike to find
its prefix, so from a `git-core` directory the walk now starts one parent
higher, and the same hook finds it. Measured on 2026-10-01. A Homebrew git
inside a hook is unmeasured, with no macOS here, and by reading is still
missed: its exec path is in the keg under `Cellar`, and its system file in the
`etc` of the prefix the keg is linked into.

**Three costs, stated.** The read went from 0.19 ms to 1.41 ms (median of
200) - ten candidate files, most of them absent, opened and read; the walk
along PATH for git is 0.09 ms of it, and `shutil.which` was not used for it
because importing `shutil` pulls the compression modules in behind it, 14 ms
on a hook that pays every import. Against the 28.92 ms spawn it replaces
that is still a factor of 20. A developer whose global config carries
the ordinary work-and-personal `includeIf` now pays the spawn on every run -
following an include, with its `gitdir:`, `onbranch:` and `hasconfig:`
conditions, would be reimplementing git rather than consulting it, which is
where this technique stops. And a git built with its system directory
somewhere this cannot name is the residual; it is why the repository's own
file stays the guard's first question rather than its only one.

Two tests that asserted an answer FROM DISK now run under a fixture that pins
the other scopes empty. Without it they would fail on the machine of any
developer whose real `~/.gitconfig` carries an include and pass on CI, which
is the shape of failure this whole file is about.

### A partial repository, and a promise the README makes

`git clone --filter=blob:none` keeps every commit and tree and only the blobs
the checkout needed. Any command that then wants another blob retrieves it
from the promisor remote, mid-command, over the network - and the README says
nothing here touches the network. Phase 25 measured it without naming it:
sweeping one such repository stalled for half an hour while rename detection
went blob by blob to the server, and reported fewer findings each time as the
object store warmed.

Verified by hand on git 2.53 before the test was written: in a `blob:none`
copy holding one rename WITH an edit, `git log --diff-filter=R --name-status`
retrieved the old blob and printed `R063`; under `GIT_NO_LAZY_FETCH=1` the
same command exited 128 with "could not fetch ... from promisor remote" and
the blob stayed missing. The edit matters: an exact rename is matched by
object id and needs no blob, so a fixture built with `git mv` alone proves
nothing.

So the guard costs the rename hint for exactly that case, and it is taken
anyway: a stated guarantee outranks a hint, and a hint that arrives by way of
a network stall is not a hint anyone waits for. What replaces it is the note.
`is_partial` reads the shared config for `remote.<name>.promisor = true` -
what git itself checks - or either spelling of the filter key, and the run
prints beside the denominators that objects not present locally were left
missing, where the shallow note already prints. The test of the guarantee
is the set of missing objects before a `--verify` compared with the set
after, on a document pointing at the old name of the renamed file; with the
guard removed, one object was retrieved.

`GIT_NO_LAZY_FETCH` is honoured from git 2.42 and the floor is 2.31. Below
2.42 the retrieval still happens and the note is what remains; the test skips
there and prints the version rather than passing on a git that ignores it.

**Measured a day later, on the bench tier, which is `blob:none` throughout.**
A sequential sweep of ruff with the 0.26.1 payload takes 11.1 s, and 4.6 s
of it is ONE `cat-file --batch-check`: the SHA rule's batch asks about every
hex token the documents hold, a token that is not a local object is one the
promisor remote might have, and git asked GitHub for each. With the guard
the same batch takes 0.03 s and the sweep 7.3 s. That is the mechanism
behind the "fewer findings each time as the object store warmed" that Phase
25 saw without naming: a dead SHA that GitHub happened to hold was fetched
and reported alive, and each run left the clone holding more. It is also a
change in what `dead-sha` answers on a partial clone - about what is here,
as on a shallow one - which is what the note beside the denominators now
says.

**The guard had one new way to be wrong, and the audit of it found that.**
`--deleted-since` reads each configured document as it stood at the ref with
`git show`, and None from that read meant "absent then". In a partial
repository the old version's blob is exactly what the transport left out, so
with retrieval refused the read fails - and "absent" hid the deleted false
claim the mode exists to report. Measured on the fixture: examined 0,
unreadable 0, silence, where the full copy reports the claim. Before the
guard, git would have retrieved the blob and reported it; the guard turned a
network call into a silent wrong answer, which is a worse trade than the one
it was meant to make. `_document_at` now asks a second question when `git
show` fails in a partial repository - did the tree at the ref list this path,
which `ls-tree` answers from the tree alone - and raises `MissingObject` for
a path that was there, landing it in the mode's "could not be read" count
beside the undecodable versions. A copy whose trees are missing too cannot
answer the second question either, and is reported as unreadable rather than
absent: "could not be read" is true of it, "was not there" is not known to
be. The distinction took `sweep.py` from 912 lines to 962 against the
927-line ceiling, so the `--deleted-since` mode moved to
`plugin/skills/extant/payload/extant/deleted_since.py` - the cut the old
module docstring had already drawn as "the two survey modes" - with eight
mutation anchors following by path.

**The shallow note is printed only by `--validate`, `--verify` and
`--check-text`.** `--sweep` never printed it, and the partial note inherits
that gap. Recorded here rather than fixed, because the survey's diagnostics
are a different shape - one summary over many documents - and the shallow
case is the one Phase 25 measured a sweep getting wrong.

## The review of pull request #16: a configured source that could read anything

Pull request #16 carried seven tranches, and before it merged the whole of it
was reviewed as a diff - every payload hunk, every function around one, every
caller of a changed signature - with the question a tranche's own gate does not
ask: what does this let an input it did not choose do. Seven findings, all
fixed, and the largest was older than the pull request it was found in.

**A consistency source was a way to copy any readable file into a log.**
`inconsistent-artifact` joins each configured source onto the repository root
and reads it, and when two sources disagree it PRINTS what each pattern
captured - that is the finding. The names come from `.extant.toml`, which is
the repository's own file, and on a pull request from a fork the repository is
the fork's. So a fork could add a check reading `.git/config`, where
actions/checkout persists the job's credential, or `/etc/anything` - an
absolute name simply replaces the root it is joined onto - and the run printed
the capture into its log and, in the github format, onto the pull request.
Reproduced by the test that now pins it: a secret written with `git config`,
a two-source check, and the old rule printed it in the finding's text. No
symbolic link is needed for that one, which is why it reproduces on every
platform. The pull request is where it became reachable rather than where it
began: the rule arrived with Phase 4 on 2026-07-26, and what this release
adds is the gate for pull requests, which runs whatever configuration the
pull request brings.

**And every other read followed symbolic links wherever they led.** A tracked
`notes.md` that is a link to `/dev/zero` read forever in the survey, in
`md_anchor`'s read of a fragment link's target, in the project-anchor sets of
`sites.py` and in the `.rs` probe beside them; the same link to an outside
regular file was judged as a document, its tokens quoted into findings. The
corpus could not have shown it: this machine checks symlinks out as plain
files (`core.symlinks` is false), and the fuzzer's escaping links are
directories and non-documents. On Linux, where the action runs, they are
real.

**One check, in one module, at every reader.** `extant/files.py` holds
`inside(repo, path)`: the name must resolve to a regular file inside the
resolved checkout and outside `.git` - the git directory sits inside the
checkout's directory, so "under the root" alone would have passed the one
file that mattered most. It raises `OutsideRepository`, an `OSError`, so each
of the twelve readers that already counted a file it could not read counts
this one the same way, by class name, with no second except clause for one of
them to forget. What each reader does with a refusal is what it already did
with an unreadable file: a swept document is named unreadable; a configured
document - the archive, an extra, the primary under `--verify` - is a
`missing-document` finding that says why, and gates, as a missing one does;
a consistency source reports that it was not read; a link target or a
manifest is not judged. A link that stays inside - `CLAUDE.md -> AGENTS.md`,
moby's own - is followed exactly as before. `--validate PATH` is left alone,
because that path is the operator's, and `.extant.toml` itself is found with
`is_file()` already, so a device cannot be one and a parse error quotes no
content. Four tests need a real link and run on Linux - through WSL here,
where all four passed, `/dev/zero` among them - and the three that reproduce
the configured-source leak and the non-link names run everywhere; the
mutation anchors aim at those, because the campaign runs where links cannot
be made.

**The action split `since` on whitespace.** The ref was spliced into a
string the step then expanded unquoted, so `since: "HEAD~1 --sha-map=m"`
reached the CLI as three arguments - watched, by a stub that now prints each
argument in brackets: the old one joined them with spaces, which is why the
existing tests passed - and a ref opening with `-` read as an option. It
travels as one `--introduced-since=<ref>`.

**Four smaller ones.** `blocks.py` split the whole document again at the end
of every indented block, O(lines x blocks): 1.22 s on moby's 5,345-line
v1.24 API document, paid twice per document; split once now, pinned by a
count rather than a timing. An indented `<!--` or `<pre>` - the first line of
an HTML example - was taken as an HTML block opening, so the example left its
code block and, unterminated, swallowed the lines after it; CommonMark opens
an HTML block only below four columns past the container, and the module now
asks that, leaving governed bodies as they were. The gate listed HEAD's tree
and handed the list to nobody, so its scope and each worker listed it again -
the sweep's defect Phase 48 closed, reintroduced beside a docstring saying
the gate lists no tree. And a relative commit link, `../../commit/<sha>`,
normalised to no owner, compared unequal to `origin` and was skipped whole
in the bare spelling; it is this repository's by construction, and it is
read now at one site, its URL's hex - which is how the backticked spelling
was already reading it.

**What the corpus says about all of it: nothing, and that was the
prediction.** `m16_predict_sites.py`, widened to documents holding a relative
link, ran the survey's validator under both payloads and predicted 0 of 152
outputs moving; the identity gate found 0. The guard is inert where links are
text, relative commit links in the bare spelling do not occur in the visible
corpus, and the indented-HTML shape sits on no line a rule reads. The fixes
are to what an input CAN do, which a corpus of repositories nobody wrote to
attack this tool does not exercise - the reason the review read the code
rather than the outputs.

**What the review got wrong and corrected before recording.** It first named
`line_pointer`'s read as a way to hang on `/dev/zero`; that read checks
`is_file()` and a size limit first and cannot. The hang was `md_anchor`'s,
which checks neither. And its first fix for the relative link examined the
link text AND the URL, two sites for one citation; the corpus-agreement
mirror of the bare scan caught the shape once a relative template was added
to its corpus.
