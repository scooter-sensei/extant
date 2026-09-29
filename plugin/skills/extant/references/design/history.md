# History: trunks, ancestry and rewrites

Part of the design rationale; [its core](../design.md) maps every part and
section. Several rules ask git what happened, not what exists: whether a
branch was merged, whether a commit is an ancestor, what a rebase left behind.
These sections record how those questions are asked, how far the answers
reach, and the probes that found a question had no population. The sections
are in the order they were written.

## Integration branches, and why one trunk was not enough

Three rules used to ask "is X an ancestor of trunk", and they meant three
different things by it. On a repository with two integration branches each
answer was wrong, in a different direction, at the same time.

Measured on a gitflow fixture - main and develop, a release branch merged to
both and tagged, a feature merged to develop after that release:

- with `trunk = main`, a FALSE claim about develop was not judged wrong, it was
  never examined. The pattern interpolated the trunk name, so the line did not
  match at all. Two false claims in one document, one about each branch, and
  either setting caught exactly one.
- with `trunk = develop`, a genuinely shipped `v1.0.0` was reported dead. The
  tag sits on main's release merge; develop received the release BRANCH back,
  not that commit.

**A merge claim names its own ref, so that is what is checked.** "Merged to
`X` at `Y`" is self-describing, and asking git whether Y is on X needs no
configuration at all. This is strictly MORE precise than comparing against one
trunk, which is what makes it the right answer rather than a loosening: a
trunk *list* would have made the rule ask "an ancestor of any of these", which
trends toward `dead-sha` wearing another rule's name.

The two rules that cannot name a ref use a measured set: the configured trunk
plus whichever of `main`, `master`, `develop`, `development`, `trunk` exist.

**Not a shape rule.** The first version asked only whether a branch name had a
slash in it, reasoning that topic branches are prefixed and long-lived ones are
bare. That is true of the prefixes and useless in reverse: an existing test
cuts a tag on a branch called `abandoned`, and the shape rule promoted it to an
integration branch and reported the release as shipped. Every `gh-pages`,
`experiment` or `old-master` is the same trap. The narrower list degrades
safely, because the rule this all exists for does not consult it.

**A missing branch is not a false claim.** Gitflow deletes every release and
feature branch on merge, and a squash merge or a custom `-m` erases the name
from history, so neither `rev-parse` nor the merge-message rescue can tell
"deleted" from "invented". Reporting those produced a false positive on the
fixture. The rule asks the substantive question instead: a missing branch plus
an integrated commit is a stale name on a claim that is true, and silence is
right; a missing branch plus a commit on no integration branch is a claim that
work landed when it did not. This also keeps the rule from being defeated by a
typo, since evading it requires the commit to be genuinely integrated - at
which point there is no false claim left to hide.

**Backticks decide whether an unresolvable name is reported.** The pattern no
longer anchors on a known branch name, so it can match a word of prose sitting
where a branch would go. `` merged to `develp` at `abc` `` is a claim about a
specific branch; "merged to production at `abc`" is not necessarily one.
Requiring backticks outright would lose every project that writes the name
bare, so both match and only the backticked form is accused.

**The installer writes its own `merge_claim`, and that is the line that
matters.** The generated pattern overrides the default, so a collector that
supports named refs still ships single-trunk behaviour if the installer
regresses. That is exactly what happened during this change: every unit test
passed, because they exercise the default, and the gitflow scenario caught it
because it runs the real installer.

## The ancestry index is bounded, and a batch settles what lies past it

The review's item 4.1 named the risk correctly and the remedy wrongly. The
risk: `_ancestor_index` ran `git rev-list <ref>` and held every commit
reachable from the ref, so the cost of asking "is this commit on main" once
was the whole history, per integration ref, per worker. Measured on
2026-09-15 on this machine without a commit-graph - the state of every one of
the 195 corpus clones and of every fresh CI checkout - rust's 338,850 commits
cost 10.6 s and 77 MB held per ref per worker, tensorflow's 198,538 cost 6.8 s
and 56 MB, kubernetes' 140,768 cost 4.1 s and 38 MB. A linux-sized history
would be about 300 MB per ref per worker under the old representation, times
eight workers in a survey.

**The remedy the review proposed does not exist.** It offered `rev-list
--no-walk --stdin --not <ref>` as one spawn whose output is "proportional to
the answer", and reported having verified it. On a fixture whose answer is
known by construction - 200 commits on main, a topic branch merged by a second
parent, a side branch never merged - the call printed all five side commits
for three fed in: `--no-walk` has no effect once `--not` makes the arguments
a range, and the output with and without it is byte-identical on git 2.53.
What the call prints is the EXCLUSIVE HISTORY of the inputs, every commit
reachable from an input and not from the ref. That still settles ancestry
exactly - an input that is printed is not an ancestor, one that is not printed
is, and for a document whose claims are all true the output is empty - but
its cost is a walk, not a lookup. Git walks the ref in date order down to the
deepest input, and on rust without a commit-graph fifty inputs cost 7.9 s when
one of them sits near the root, 0.63 s when all fifty are within a thousand
first-parent commits of the tip, against 10.6 s for the whole index. On
ruff's 17,020 commits: 482 ms deep, 353 ms recent, 615 ms for the index. The
review's other half held: one input git cannot resolve fails the whole call
with exit 128 and empty stdout, a tree object on stdin does not, a shallow
boundary does but `cat-file` reports that commit `missing` first.

So replacing the index with the batch would have traded one walk per ref per
worker for a walk per rule, per document, per ref - and on this repository's
`--verify` it would have added two spawns to a budget of four, the merge and
release rules each batching against `main`, to save nothing: the history is
355 commits. Refused as pitched, on those numbers.

**What shipped instead is three pieces in refs.py, one path each.** Full-SHA
membership: `_batch_shas` keeps the full commit id `cat-file --batch-check`
already prints, the `shas` memo holds it instead of a boolean, and
`commit_id` maps any rev - an abbreviated token through that memo, a name
through the ref table - to its full id before the question is asked. The
prefix buckets and the `startswith` scan went with it, and one token has one
resolver: a SHA-shaped rev that no batch has seen goes through `cat-file`,
never through the tag table, where a tag named like a seven-character prefix
would have answered for a commit. A bounded index: `rev-list -n 50001 <ref>`,
a frozenset of full SHAs, and a flag saying whether that was the whole
history. A hit is proof either way; a miss on a complete index is a no with no
spawn. And the batch above, `_settle`, for misses on an incomplete index only,
fed full SHAs this run already resolved as commits - which is what makes the
abort unreachable by construction - issued once per rule and ref by a
`settle_ancestry` call each of the three rules makes before its judging loop,
with the answers memoised on the same scope object as the index. Should the
batch abort anyway, the repository having changed under the run, the fallback
is the one `reachable_from` has always had, a `merge-base --is-ancestor` per
commit, so the answer is the same and only the spawn count is not. The batch
is fed and read as bytes: `subprocess` in text mode writes `\r\n` on Windows,
git tolerates it, and `_batch_shas` has been relying on that tolerance without
knowing.

**The bound is fifty thousand, and the number was measured before it was
chosen.** `-n` bounds the walk linearly on rust: 20,001 commits in 0.68 s,
50,001 in 1.6 s, 100,001 in 3.1 s. The corpus median is 8,076 commits; 179 of
195 clones are under fifty thousand and pay exactly what they paid before,
one spawn per ref per run with only the argv's spelling changed; the sixteen
above pay at most 1.6 s and about 6 MB per ref per worker instead of up to
10.6 s and 77 MB. A frozenset of the seam's own lines rather than the sorted
20-byte blob that was also measured - 6.5 MB against 42 MB on rust's full
history, 321 ms against 131 to build - because the bound is what caps the
memory, and the blob's remaining 5 MB per ref per worker did not buy a custom
binary search and a test for one.

**The docstring that argued against a size switch was right, and the answer
was to exercise the path rather than to leave the walk unbounded.** "A
size-based switch would create a second path that only runs on large inputs,
which is precisely the code that never gets exercised by a test." The bound
is a module constant tests/test_ancestry_bound.py sets to one, so every rule
that asks ancestry runs past the bound on every fixture; each of the three
rules is asserted to answer identically under a bound of one, three and the
default; the mutation campaign holds anchors on both sides of it. And the
corpus gate: thirteen repositories - the nine full-blob autopsy rows, ruff,
kubernetes, kubernetes/website and this one - swept three ways, the
payload as it stood before this change, this payload at the default bound,
and this payload with the bound forced to one so that every question goes
through the batch, with byte-identical output required.

**What it costs, stated.** Above the bound, a document citing only old
commits pays the bounded build and then one deep walk per rule: on rust
without a commit-graph about 1.6 s plus 7.9 s against the old 10.6 s, roughly
even, while a document citing recent commits pays 1.6 s plus 0.63 s. The
population that asks decides which shape matters, and it was counted: across
twelve corpus repositories and 13,043 documents, four documents ask an
ancestry question at all - one in babel and three in kubernetes/website, all
release claims naming old tags - and this repository's status document asks
forty times. The zero for live claims there is structural rather than
evidence: `stale-live-claim` reads only the primary document, and no corpus
repository has one. Status documents are the population, they cite recent
commits, and they live in small histories; the bound is for the day one of
them does not.

**Two things measured here and not built.** The review's 4.2 asked for a note
when a commit-graph is absent and ancestry dominates, earned by a gap above
2x. The gap is 7.5x on the index (10.6 s to 1.4 s on rust), 27x on the batch
(7.9 s to 0.29 s) and 77x on `merge-base` (2.8 s to 36 ms); no corpus clone
has one, and git writes one only after a `gc`. Earned, and not in this
change, because the only deterministic trigger - the index came back
incomplete - is a fact of the run scope, and `report_repository_notes` prints
after that scope has closed in `run_validate`; plumbing the flag out is its
own change. And the name the batching call first had, `prefetch_ancestry`,
failed `test_no_network_shape_appears_in_the_operational_source` in the
suite: the scan that keeps `clone` out of the shallow note reads identifiers
too, and a verb that means retrieval over a network is not one this tool may
carry even as a prefix. It is `settle_ancestry`.

Still owed from before: each survey worker builds its own index (review
5.6), and `--verify` opens a scope per document so the index is rebuilt for
each (5.7) - both now bounded, neither removed.

## The post-rewrite journal: the record a rebase leaves, kept

The review's item 4.7. Phase 26 established that a dead SHA is usually a
rewrite casualty and that the repository already records the mapping - for
`git filter-repo`, in `.git/filter-repo/commit-map`, which `rewrite_hint`
reads and `--sha-map` applies. A rebase or an amend renames commits the
same way and leaves no map. What it leaves is the `<old> <new>` pair per
commit that git writes to the `post-rewrite` hook's stdin and to nothing
else, byte-for-byte the commit-map's spelling - and the shipped hook drained
those into `/dev/null`, with a note in its header saying that persisting
them "would let a finding name the replacement after a rebase the way it
already does after filter-repo. Measure how often a rebase is the cause
before building either."

**The population, stated rather than measured, because no clone can show
it.** Across the 152 visible corpus clones the identity sweep prints 7,418
dead-SHA findings and 0 of them carry a rewrite hint: a clone never holds
the author's `.git/filter-repo/commit-map`, and a journal written by a hook
would live in the same place. So the count the review asked for - hint
coverage of amend and rebase casualties, "structurally zero" today - cannot
come from the corpus, and the tranche-7 handoff said so before this was
designed. Where the journal has value is the AUTHOR'S machine, and the
shape of that value is the finding the hook's own header measured on git
2.53.0: after a local rebase the old ids still resolve through the reflog,
so `dead-sha` is silent there for the 90 days a reflog entry lives, while
every clone and every CI run already sees them dead. That is the one
moment the repair is cheap, and until now nothing offered it.

**What was built, and the four things the audit settled.** The hook
appends each pair it is handed to `extant/rewrites` under the shared git
directory - beside the filter-repo map, because a rewrite belongs to the
repository and a linked worktree shares it - as the two ids only, since
git's line may carry a third field. `git.rewrite_journal_path` finds it
with a stat, like the map; `commits._read_rewrite_map` reads both records
into one mapping, so the `dead-sha` hint and `--sha-map` explain a rebase
exactly the way they explained a filter-repo, through the one lookup they
already shared. (1) *The append lives in the hook, not the installer's
shim.* The shim drained stdin and ran the hook with stdin closed, because a
long rebase left unread while a check ran would fill the pipe and block
git; it hands stdin through now, and the hook reads it FIRST, before the
guards, the interpreter search and the check, at the speed of the shell -
draining itself only where there is no hook to run. Installs made before
this keep the old shim until `tools/hooks/install` is run again, and the
CHANGELOG says so. (2) *A chain is followed to its end.* A branch rebased
twice journals `a b` then `b c`, and a hint naming `b` reads as correct
and is as dead as `a` - the wrong-SHA-worse-than-dead-SHA failure the
ambiguity rule refuses - so `_settled_value` follows the chain in the one
lookup both readers share; a chain that returns to itself, which git
cannot produce, settles nowhere and hints nothing. (3) *A disputed id
offers nothing.* An old id the map and the journal send to different
places is dropped rather than resolved by reading order, the ambiguity
rule across records. (4) *The cited-documents probe is one process.* After
the append the hook runs `git grep -l -I -F -f` over a probe file of
7-character prefixes, across every suffix the sweep reads, and prints one
note naming the documents that cite a renamed commit and the repair -
`--verify --sha-map .git/extant/rewrites` - without making it. A probe file
rather than one `-e` per pair, because a rebase of a few hundred commits
would overrun Windows's 32 KB command line; silent when nothing cites a
renamed commit, which is the ordinary rebase, because a note printed for
every rewrite is how a hook teaches its reader to stop reading it. An
amend is journaled and probed too, before the hook declines the check that
post-commit already ran: the renamed id is a fact only this hook is told.

**The gate is the fixture the design named.** A document cites a commit on
a branch; git itself fires the installed hook on `git rebase`; the journal
holds the pair; `reflog expire --expire=now --expire-unreachable=now` and
`gc --prune=now` do what a fresh clone or a later gc does for free; the
finding names the rebased id where before it said only that the commit
does not resolve. Fourteen tests, nine on the reader and five on the hook,
in `tests/test_rewrite_map.py` and `tests/test_hooks.py`; six mutation
anchors, the first this project has had on the verify hook or on the
rewrite-map reader at all - the journal never found, a chain hinted one
hop short, a disputed id resolved by order, git's third field hiding a
pair, the hook dropping what it is told, and the note printed for a
rewrite nothing cites. The journal only ever grows, at 82 bytes per
rewritten commit, and is not pruned: the id it explains may be cited for
years.

## The four probes: a split only the network can make, a rebase that reaches nothing, a rescue with no population, and the gate's missing listing

Tranche 14 of the internals review, 2026-09-22: the four measurements the
review's 4.9, 3.7, 4.8 and 4.11 asked for, run before anything was designed
and each deciding its item. The apparatus is the `m14_*` scripts in the
extant-hardening checkout, rows under `D:/repo/out-split`,
`D:/repo/out-impact` and `D:/repo/out-branches`; every scanner is the
tool's own (`prose()`, `_document_sha_tokens`, `branch_exists`,
`named_in_merge_history`, `strata.classify`), so "cites" and "names" mean
what the rules mean by them, and only the visible corpus rows were read.
Two items became code, one of them not the item the review named.

**4.9, the split: born false, or rotted?** The population is every
`dead-sha` and `bare-dead-sha` the shipped `--sweep` reports at HEAD on
the 17 agent and 13 autopsy clones, de-duplicated to 9 repositories that
carry any: 2,489 findings, 874 distinct (repository, token) - 1,064 in the
vendored stratum and 1,102 in the generated one, both moby's changelogs and
API documents, 320 ordinary, 3 historical. Cerene validated the instrument
first: 27 findings, 12 tokens, its commit-map settles 27 of 27 and the
introducing commit is found for 27 of 27. On the corpus the offline half
answers exactly what Stage 4's item 9 said it would: the rewrite record - the
commit-map and the post-rewrite journal, read by the tool's own reader -
settles 0 of 2,489, because both are artefacts of the machine the rewrite
ran on and a clone never carries them. What a clone CAN say is when the line
was written. `git log -S<token> -- <document>` under `environment()` found
the introducing commit for 2,488 of 2,489 (the one refusal a blob:none
clone's lazy fetch, refused rather than taken); plain first, because
`--follow` answered nothing for a token the plain walk placed, so the
rename-following pass is the fallback and never the first reading. In the
ordinary stratum 315 of the 319 dated findings were in the document's FIRST
version - written into a new file, not edited into an old one - and the
line's median age at HEAD is 637 days. The 36 tokens that resolve in a clone
with every blob are blob prefixes, which is why the rule asks
`cat-file -e <sha>^{commit}` and this probe peels the same way.

The 320 ordinary findings, read by document: 244 are transcripts of a
session's commits - aider's chat-history test fixture, 215, is aider working
on aider itself, and of its 75 distinct "Commit <id> <subject>" lines 13
subjects exist in the history under another id and 62 do not; aider's 29
website examples are sessions on scratch projects - and superpowers' 23 are
the quoted evaluation output Phase 47's hand-read named; 28 are docker
network and container ids in libnetwork's vagrant walkthrough (see the third
shape found below); 8 cite another project's commit on purpose, five of
them with that project's URL on the same line and one saying "imported
from commit"; 13 are not commits at all (a content hash repeated across
eight translations of one page, a signature scheme's name four times, a
fixture hash); and 4 findings, 3 tokens, were read by hand as this
repository's own commit that no longer resolves - goose's merge notes and
langgraph's generated threat model - with a fifth in fastapi's release
notes in the historical stratum. The network step below moved that line
in both directions: it found three more of the repository's own ids in
superpowers' plan and spec prose that the hand read had counted with the
quoted output, and it refused fastapi's. The review's dichotomy has a
third leg larger than either: a commit id that was true in ANOTHER object
store - a local session's auto-commits, an evaluation workspace, a vendored
project - and never in this one.

The split itself, made by the one instrument that can make it. GitHub's
commits API answers 200 for any commit the repository network's object
store still holds, reachable or not - verified on this repository on
2026-09-22: the tip of the local `backup/pre-rewrite-main`, unreachable from
`main` since the 2026-08-10 rewrite with no branch on GitHub holding it, is
served six weeks later, and so is its tenth ancestor; a never-existed token
answers 422; a 7-character abbreviation resolves. Limits stated: a 200 can
be a fork's commit, a 422 a commit GitHub has since collected, so each is a
lower bound. Run over the 172 distinct tokens of the ordinary and historical
strata (the 705 vendored and generated ones are other projects' changelogs
and would answer 422 for nothing), one read-only call each: **6 existed
once and 166 never did**. The 6 are exactly the class read by hand as the
repository's own - goose's merge notes citing two commits of its own July
history, langgraph's generated threat model citing the commit it was
generated at, three ids in superpowers' own plan and spec prose - every one
a commit of the repository's recent history squashed or rebased away, cited
in a document written in the same season, 2026. The 166: aider's 129 are one
session transcript kept as a test fixture whose auto-commits never reached
the remote in any form; superpowers' 16 are quoted output about another
workspace; moby's 14 are thirteen docker ids and the commit of the project
it imported a package from; ruff's 2, vitepress's 2, pytest's 1 and
goose's 1 are another project's commit or not a commit; fastapi's 1 is an
id its release notes carry that GitHub has never held. Outside the one
fixture, 6 of 43.

What that changes, and what it does not. The finding is right either way -
dead is dead, and the rule never claimed to know why. The advice is what
moves. "Keep your documents fresh" describes 6 tokens in 172, and every one
of those was a squash or a rebase, which the post-rewrite hook already
names at the moment it happens. The rest were never this repository's fact:
an agent quoting a transcript, a grader's output, another workspace's
history, into a plan that the next session reads as a claim about this one.
So the sentence the skill now carries is neither of the review's two. A
commit id is a fact about one object store; written into a document from
anywhere else it is a claim this repository can never check, and the tool
will read it as one - name where it came from, or leave it out. The
"paraphrase, never quote" constraint below is the same instruction with the
number behind it now. `--at <ref>` itself stays unbuilt: the question it
would answer is settled by the network or not at all.

**3.7, `--impact`: documents citing `HEAD~50..HEAD`.** 153 rows over the
152 visible clones and Cerene, 140 clone names, 139 repositories (SWE-agent
is cloned under two owners). "Cites" is the rules' token union resolved by
one `cat-file --batch-check`, tags peeled to their commits; the window is
`rev-list HEAD~50..HEAD`, side branches merged in it included; 7 repositories
younger than fifty first-parent commits used their whole history and are
named in the rows. **9 of 139 have one or more documents citing a commit in
the window, and the median is 0 in every group**: the agent tier 1 of 15 (a
changelog), heldout-ai 1 of 10 (agno's test logs), niche 1 of 38 (a
changelog), control 6 of 25, autopsy 0 of 13, bench 0 of 28, heldout-human
0 of 10, Cerene 0 - it cites 12 tokens and every one is dead. Of the 75
repositories carrying an agent-document signature, 6. Twelve of the
fifteen agent-tier repositories cite no SHA token in prose at all, two
cite only dead ones, and one cites live commits - in its changelog. The
second pass makes the answer robust to the fifty: 50 repositories cite any
live commit, 13,064 citations, and the smallest N at which a rebase of the
last N commits reaches one is 50 or less in 9, 200 or less in 15, 1,000 or
less in 21, median 1,789 first-parent commits (an exact index on the line,
an upper bound off it); of all 13,064 live citations 0.93 per cent sit
within 50 commits and 17.7 per cent within 1,000, median depth 4,523.
Documents cite what shipped long ago. Refused: the dead-SHA problem is a
rewrite problem, not a rebase-of-recent-work problem - the outcome the
review said was worth knowing too - and the moment a rewrite happens is
already the post-rewrite hook's, which greps every tracked document for the
old ids and names the repair.

**4.8, the rescue rate.** `unknown-branch` reads the newest entry of a
primary document, and the review's sentence about a squash merge erasing a
name describes the merge rule's deliberate silence (a missing branch plus an
integrated commit), not this rule, which fires when neither the ref table
nor the merge log holds the name. The two real status documents: this
repository's names no branch in the pattern's shape - its entries cite
pull-request numbers, and its five sites are examples in this document, the
harness README and one entry sentence - and Cerene's newest entry has one
site, rescued. The rule's population today is zero findings. The proxy, so
the number exists: every `branch_token` match in every document of 141
repositories, judged with the rule's own functions - 78 sites in 21
repositories, 32 rescued by merge history, 46 neither. The 46, read one by
one: 22 examples, templates and workflow globs; 2 vendored (one README
absorbed by kubernetes and by moby); and 22 real names in the session, test
and design documents of 6 repositories, one line saying "merged via #47" and
another "Closed PR #4 and deleted" - squash-merged then deleted, or
worktree-only. So the rescue fires on 32 of 54 real-name sites and a
`reference-transaction` journal would settle the other 22, none of which the
shipped rule reads. The structural ceiling, over the last 200 first-parent
commits of 141 repositories: integrations that leave a branch name behind
are a median 1 per cent, 64 of 129 repositories at zero (squash or rebase
only), 15 at one; the agent tier 2 per cent, 7 of 14 at zero. Refused, with
the trigger: the journal earns its place the day the rule reads standing
documents, which Phase 36 measured at 56 tokens and not one a claim, and
which this proxy measures again at 22 examples in 46.

**4.11, the pre-commit hook reads HEAD - and the gate did too.** The
experiment the review asked for, in a scratch repository: a new document
`git add`ed with a dead SHA, a tracked document edited and staged, another
edited and not staged, a fourth never added. `--sweep` reads the edits from
the working tree and cannot see the new document - its listing is HEAD's
tree, the documented decision, since an index that did not complete is
empty. `--verify`, which the pre-commit framework's bare `extant` entry runs,
reads every configured document from the working tree - staged, unstaged,
even untracked - and has no gap. `raw-lfs-blob` examined 0 with the
attributes and pointer staged and 1 once committed: HEAD by design, stays.
And `--introduced-since HEAD` dropped the staged new document and, in a
second run, an uncommitted `git mv` with an edit, printing "examined 0
changed document(s)" and "1 tracked document(s) the range did not change
were not read" of a file the range had moved. The diff named both; the mode
intersected the diff's paths with `tracked_markdown`, which is HEAD's tree,
and the new name fell out. Its own docstring said "the working tree holds
and base does not". A pull-request checkout never showed it, because there
HEAD carries every change; the gate run locally before committing a new plan
document - the agent's most common artefact - showed it every time, as a
clean run. The `--staged` mode the review floated is refused: nothing needs
the index read. The listing is fixed: the changed documents are the diff's
own `+++ b/` side, which the pathspec already restricts to the suffixes
`tracked_markdown` reads; HEAD's tree only counts what the range left alone,
minus both names of a rename, read off the `--- a/` side the same reader
now returns. Two tests red first, the staged document and the moved one.
Adopters wiring the pre-commit hook rather than the post-commit one: not
measurable - no telemetry, and one known install - and stated as such.

**Three shapes found on the way**, each with its count. First, `ed25519`
read as a bare dead SHA in 7 of the 152 visible clones (goose, deno,
kubernetes, node, unraid, PX4-Autopilot, pdns): seven characters, every one
a hex digit, a letter and a digit among them, the exact shape both shape
tests admit, and the only such word the corpus holds. Shipped as a one-word
list beside the shape, `_HEX_WORDS`, refused in both spellings; the cost is
a commit whose abbreviation is exactly that word, one in 268 million
objects; 7 identity outputs predicted to change. Second, a SHA as the link
text of a commit URL WITHOUT backticks - `[<sha>](https://github.com/<owner>/<repo>/commit/...)`,
the conventional-changelog spelling - is 1,425 of the 11,191 dead-SHA
findings in the recorded sweep (12.7 per cent; angular's absorbed zone.js
changelog 379, moby's vendored changelogs 358, node's deps 290), and 28 more
link to the repository's own URL and are real rewrite casualties. The
backticked spelling has been suppressed since the held-out narrowings (192
findings then), deliberately without comparing owners; the bare spelling is
the same shape and the same argument, one skip span in the bare scanner,
and it is recorded here rather than built because the design that was
approved said recorded. Third, a CommonMark indented code block is not
blanked by `prose()`: a five-line document proves it, the fenced token
blanked and the four-space-indented one reported. Corpus: moby 1,139
findings (its generated API documents and the vagrant walkthrough), 76
findings in 16 other repositories, and bazel's 36,321 anchors in version
snapshots. Not built here, on purpose: a four-space-indented continuation
paragraph under a list item is prose, and blanking it is the false negative
this tool refuses, so the change needs its own measurement of what it would
blank before it is a change.

**The gate, as run.** Four tests red before the code moved - the staged
document, the moved document, the hex word in both spellings, and the
control that a hex run one character longer still fires; two direct
callers of `introduced_lines` unpack its third value. Two anchors
retargeted (the listing, the unlistable-tree refusal's sentence) and three
written (the listing from HEAD's tree again, the renamed-away name counted
as unchanged, the emptied word list), each to be applied to a copy and
watched turning the suite red; 287 anchors match exactly once. The corpus
identity sweep against a stated prediction of 7 of 152 differing - the
`ed25519` clones and nothing else, because the gate's listing reaches no
clone's clean working tree - and the pre-push chain against a working-tree
extract, recorded in the Phase 51 entry with their numbers.
