# Widening the rules: corpora, proposals and refusals

Part of the design rationale; [its core](../design.md) maps every part and
section. The admission test's second clause - zero false positives on a corpus
the rule was not designed on - is expensive, and these are the measurements
that paid for it: what a held-out corpus said, and each pass of proposed
widenings with the numbers that shipped or refused them. The sections are in
the order they were written.

## What a held-out corpus said about detection

Ten repositories the original narrowing never saw - Rails, Laravel, Ktor, Zig,
Docsify, Nextra, Slate, dplyr, Terraform, Symfony - produced 951 findings
across 1,100 files. Two results reordered the work.

**The rules that fire on other people's repositories are the link and anchor
rules, and nothing else.** Of those 951 findings, 943 were `dead-md-link` or
`dead-md-anchor`. `unknown-branch`, `false-merge-claim`, `dead-path-pointer`
and `dead-pinned-ref` fired ZERO times between them. Those rules exist for
plan, spec and status documents, which no public repository corpus contains,
so widening them could only add noise here. The eight coverage candidates
planned for this phase were aimed almost entirely at rules this corpus cannot
exercise.

**And 526 of the 558 link findings were noise the tool already knew how to
suppress**, in projects whose generator it did not recognise. Three changes
followed, each keyed on a measurement.

**A `.html` target is never judged, in any repository.** Measured across 20
repositories in two corpora: 407 markdown links point at a `.html` target and
NOT ONE resolves to a checked-in file. A link to `.html` is a link to a
rendered page. This used to be gated on generator detection, which is why
rails reported 276 of its own guide links dead - its guides compile
`guides/source/*.md` to HTML with a bespoke builder shipping none of the
configs detected here. The gate was protecting nothing, so it is gone.

The other two shapes keep the gate. In a plain repository an extensionless
target can be a real file - `LICENSE`, `Makefile` - so silencing those
everywhere would stop the rule working at all.

**Next.js counts as a generator**, because it routes by file path and a
markdown link inside one is a route. Nextra builds on it and reported 227 of
its own links dead.

**Docsify declares itself inside `index.html`**, having no config of its own,
and keeps it under `docs/`. So the marker search walks the same subdirectories
as the config search rather than looking only at the root - the root-only
version was the shipped bug for jekyll, whose `_config.yml` sits there too.

Held-out findings fell from 951 to 424, and the original corpus was unchanged
in every repository - the point of measuring both.

Its total was recorded at the time as 2,154, and that figure was an artifact.
Those clones were made with `--depth 1`, which leaves every historical SHA
unresolvable, so the SHA rules fired on nearly everything: vite alone supplied
2,094 of them and reports 3 when cloned with its history. The "unchanged"
conclusion holds, because both sides read the same clones. The number did not.

## The coverage phase: eight widenings, none shipped

The eight candidates above were then measured properly, one at a time, against
three corpora - the original ten re-cloned with history, ten more held out for
toolchain novelty, and ten chosen for density of git-checkable claims. Thirty
repositories, 3,821 markdown files, 960 baseline findings.

All eight were rejected. The reason generalises past this tool.

**A rule keyed on a PHRASE has a denominator of zero outside the project whose
phrasing it came from. A rule keyed on a TOKEN SHAPE does not.** `dead-sha`
looks for hex, `dead-md-link` for link syntax, `dead-path-pointer` for a path;
all three fire everywhere. `false-merge-claim` looks for "merged to X at
`sha`", and across 3,821 files it matches nothing at all. Neither does "merged
in `<sha>`", "landed in `<sha>`" or "fixed in `<sha>`". What projects actually
write is "commit `<sha>`" - 890 times - which the shape-keyed rule already
catches without needing the verb.

That was read as "the claim rules cannot be gated by any public corpus", and
**it was wrong.** The method held; the SAMPLING FRAME did not. "Claim density"
had been chosen by picking popular Python and JavaScript tools, which are dense
in changelogs rather than in status claims, so the population these rules
actually serve was never in the sample.

Scanning 229 repositories from the agent-tooling topics - 52,417 documentation
files - finds the shipped merge pattern 35 times, the release pattern 97 times,
the branch token 640 times and the live phrase 117 times. **61 repositories
exercise at least one.** A corpus of fifteen of them gives `false-merge-claim`
a denominator, `dead-release-tag` 74 examinations against 2, and produced this
rule's first true positive on somebody else's repository: neomjs/neo records
work merged to `dev` at a commit that is not an ancestor of `dev`.

The lesson survives the correction, in a sharper form. A phrase-keyed rule is
invisible to any corpus that does not contain the KIND of document it was
written for, and "I sampled 3,821 files and found nothing" is a statement about
the sample. Widening it to a shape-keyed rule is still the robust move; giving
up on measuring it was not.

Where a measurement was possible it was decisive, not marginal. Judging a path
mentioned without an operative marker takes the tool from 960 findings to
3,964. Dropping the letter requirement from the SHA shape admits 7 findings of
which 7 are numbers: a date, two durations in seconds, a timestamp version.
Resolving anchors through site routes changed nothing across 3,821 files - and
a fixture proves that is a real zero rather than a patch that failed to apply,
which is the only way a zero is worth reporting.

**Two rules were wrong on every firing they had.** `dead-release-tag` and
`dead-pinned-ref` produced four findings across the whole 30-repository corpus
and all four were false positives - which is what justifies acting on a sample
that small, because a 100% error rate is not the same situation as a few
mistakes among hundreds of correct results.

That prefix fix also nearly shipped the failure it was written to remove. A
project can configure `release_tag` to capture its whole tag name, and the
installer derives such a pattern for repositories tagging `release-1.2.3`;
trying this repository's prefixes first makes that `release-release-1.2.3` and
reports a shipped release as dead. Eleven unit tests covered the change and
none could see it, every one having used a bare or `v`-prefixed version -
which is the shape the corpus was about. `scenarios.py` caught it. A fix
derived from a corpus inherits that corpus's blind spots, and no repository in
any of the three configures this rule at all.

Every cause was a project habit rather than an author's error. Half the
ecosystem tags `v1.2.3` and half tags `1.2.3`, so the prefix is read from
`git tag -l` now instead of assumed. A claim names a SERIES more often than a
tag - symfony's own triage guide names the 8.0 series while the tags are
`v8.0.0`, `v8.0.1` - so a version that is the stem of a real tag has shipped.
symfony also has no `main` and no `master`, its branches being version numbers,
and the integration-ref list returned the configured trunk whether or not it
resolved: every rule asking "did this reach an integration branch" compared
against a ref that is not there, got "no", and reported every release as
shipped on nothing. 3 of 30 repositories have no conventionally named trunk.
And `rev: ''` is pre-commit's own placeholder rather than a broken pin.

**Two detection fixes came out of it**, both from reading the 38 findings that
blanket route-suppression would have silenced. All 38 were false positives.
A site can be a subdirectory of a subdirectory - aider's Jekyll lives at
`aider/website/_config.yml` - so the config search goes one level deeper,
bounded there. And Mintlify's `mint.json` is a signature; its newer `docs.json`
spelling is not, being too generic a filename to trust.

All of it together: **960 findings to 920, 40 removed, 0 added**, every removal
individually confirmed as a false positive.

Three are left in deliberately, because a known false positive is cheaper than
a guessed rule. A bare-domain link (`[x](kubernetes.io/docs/...)`) is 1
finding, and every rule that would catch it also catches `README.md`. A
relative target climbing out of the repository is 3 findings in one file of one
repository - implemented, then reverted when a scan found no second instance
anywhere, because deriving a rule from a sample of one project is the error
this phase exists to document. And rust-lang/rfcs, which has no tags and
discusses Rust's releases throughout, reads a mention of the 1.75 toolchain as
a claim about itself; skipping untagged repositories fixes that and silences a
never-tagged project making a false claim about its own release, which is the
worse trade.

That last paragraph is worth reading twice, because the first draft of it
tripped the rule it describes. Quoting the offending sentence in order to
explain it REPRODUCED it, here, and `--verify` failed the build. Then the
paragraph written to record THAT did it a second time, for the same reason.

The rule cannot tell a quotation from a claim. `CLAUDE.md` already records the
property for live claims, where the standing instruction is to paraphrase a
past status rather than quote it; it holds for release claims identically, and
the tool proved it twice on the document announcing the fix. Paraphrase, or
the sentence you write about a false positive becomes one.

The 424 that remain are mostly real. Rails links to `#helpers` from a document
with no such heading; dplyr's revdepcheck output links to `failures.md#amt`
where the heading is `# amt (0.3.0.0)`, whose slug is `amt-0300`. Both were
checked by hand rather than assumed to be noise because they were numerous.

## Examined and declined

Recorded so a later reader does not mistake any of these for an oversight.

**Entry-scope burial.** `stale-live-claim` reads the newest entry only, so
moving a live claim into an older entry silences it. Not closed: older entries
are historical record, and re-judging them would fire on every past status in
every project that keeps one. That is a guaranteed false-positive class traded
for a narrow evasion. The authoring constraint below - paraphrase past
statuses, never quote them - is the mitigation.

**The `raw-lfs-blob` size shortcut.** Reading every governed blob rather than
only the small ones changes cost and never a verdict, so it is not a loophole.
It is also why that shortcut has no mutation in `mutate.py`: a mutation nothing
can kill survives every campaign and reads as a gap the tests do not have.

**Symbol-aware line pointers.** `dead-line-pointer` asks whether a cited file
has that many lines, never whether the line still holds the symbol named beside
it. The wider question has been measured and rejected twice, and the full
figures sit in the comment above the pattern in `line_pointer.py`.

The short version: across 39 libraries, 21 applications and 3 heavily
agent-written projects, the citation form barely occurs, and where it does a
symbol sharing a line with a path is not a claim about that path. The 39-repo
pass flagged 10 and none was real. The agent-written pass - the population the
first rejection named as the last hope, since those documents cite code by line
constantly - produced about 16 flagged claims for at most one real finding, and
15 of its 23 pointer sites sat in completed plans, so the rule would have
mostly reported history.

Two things are worth keeping from it. An AST was built rather than assumed
away, and it changed nothing: the document supplies the symbol NAME, so the
check reduces to a string search and never needed a parser. And every narrowing
that removed the false positives also emptied the denominator, which is the
signature of a rule with no population rather than one with bad keying.

## A correct rule can be low-yield, and that is the world rather than the keying

`dead-line-pointer` draws a denominator from very few repositories, and the
first instinct is that its keying is too narrow. Measured across **73
repositories** - 39 libraries, 21 deployable applications, 17 agent-tooling
projects with roughly 21,000 markdown files - **`obra/superpowers` is the only
project that cites line numbers of its own tracked files at any rate.**
`crewAI` alone holds 20,375 documents and does not cite one.

The obvious explanation was a sampling problem: this rule targets agent-written
plan documents, so a corpus of them should exercise it. That corpus was built,
verified to contain the population before any rule ran, and produced **no new
findings**. The hypothesis was wrong and the thin denominator is the base rate.

Where the convention does exist the rule earns its place: **3 of superpowers'
17 resolvable citations are stale, an 18% fault rate.** So the shape to expect
from a rule like this is narrow reach and a high hit rate inside that reach,
and widening it would trade the property it reliably has - zero false positives
across all 73 - for coverage the measurement says is not there.

Before concluding a rule is too narrow, count how often anyone writes the form
it reads. That is cheaper than any widening and it is what the denominator line
exists to make visible.

## The second widening pass: ten proposed, four shipped

A specification arrived on 2026-09-12 proposing widenings for nine of the
thirteen rules, each described as falsifiable and each claiming zero false
positives on the corpora. None of that had been measured, so all ten were
counted first - the form, then the findings - over the visible rows of every
manifest: 132 repositories and 77,401 documents, with the holdout and the 16
reserved benchmark rows left unread. The counting instrument is
`widening_census.py` in the measurement tree, and the before-and-after sweeps
are `widening_sweep.py` beside it. Four widenings were built, each with a
test that was watched failing first and a mutation anchor; the rest were
refused on the numbers below, which is the point of recording them.

### Shipped

**Reference-style link definitions.** `[label]: docs/setup.md` is the same
claim as an inline link and was read by nothing: 3,171 definitions name a
local file across 75 repositories, examined zero times. Two shapes wear the
colon and are not links. A footnote, `[^1]: text`, is refused by its caret. A
destination opening with a parenthesis is read LITERALLY, because CommonMark
keeps balanced parentheses in a destination: golang writes
`[cockroach#10214]:(cockroach10214_test.go)` sixty-three times in one testdata
README, the link is dead on GitHub whether or not the file inside exists, and
there every file has since been renamed to `.go` as well. The first draft
refused that shape as "text the author parenthesised" and would have hidden
sixty-three real findings.

**Raw HTML.** A README centres its logo with an `img` tag and links a sibling
with an anchor tag, and GitHub resolves both against the file exactly as it
resolves a markdown link: 8,488 local `href` and `src` attributes across 86
repositories. One refusal is new and depends on the repository. Inside a tree
a generator builds, a relative HTML `src` is resolved by the BROWSER against
the rendered page's URL, not by the generator against the source file, so
`../../img/x.png` written in a MkDocs `docs/user-guide/` page reaches
`docs/img/x.png` on the site and nothing relative to the file - the image is
there, and mkdocs/mkdocs writes exactly that. A markdown image in the same
position is rewritten by the generator and still names the file. So an HTML
attribute inside a site tree is neither judged nor counted, in the rule's
adapter where `in_site_tree` can be asked. A value holding a brace is a
template expression and names no file.

The two together, swept: **261 findings added, none removed**, and every one
was read. 115 sit in angular/angular's `adev/` tree, a documentation site
built by a bespoke Angular application that no signature here detects and
that already supplies 26 per cent of the benchmark's ordinary findings through
markdown links of the same shape - the widening inherits that concentration
rather than creating it. 63 are the golang testdata definitions above. 25 are
in vendored trees and 9 in test fixtures, both labelled or configurable.
Thirteen were confirmed by hand as broken images and links in ordinary
READMEs: six in OpenBMB/ChatDev, two each in crewAI's nested package README
and MetaGPT's android assistant, one each in mkdocs, sonic-pi and a vendored
synthesiser library. The remaining handful are undetected generators of the
same kind as angular's - an mdBook under `book/`, ExDoc assets, a custom
Astro site.

**A line range is read to its end.** `dead-line-pointer` read
`SKILL.md:211-215` at 211 and recorded widening to the end as "a separate
measurement". Made: 27 ranges name a tracked file, 22 sit inside it, 4 begin
past the end and were already reported, and ONE ends past it - lobehub's
page-agent README citing 32-116 of a 94-line file. One finding, zero false
positives. A colon is not a range separator: 73 citations carry a second
colon-separated number and 69 of them are BELOW the first, which is line and
column as every compiler prints it. A finding names the range only when the
range is what failed; a start already past the end keeps the `path:start`
spelling it always had, because `detail` is the baseline fingerprint.

**A SHA range inside one backtick pair.** The authoring constraint at the end
of this document used to ask for two tokens because `` `a..b` `` escaped both
checking and repair. Three such ranges in 77,401 documents: one is link text
over a compare URL in helix's changelog, whose first commit a rebase left
unreachable while GitHub still serves the page - excluded the way a single
linked SHA already was - and two are an agent's session log recording a
fast-forward whose both ends a later force-push rewrote away, which is the
population this rule exists for. Each end is tested as a token of its own, the
rewriter splits with the same function the scanner does, and the arrow
spelling is left alone: zero occurrences, and it is how a rewrite map is
quoted, left side dead by design.

### Refused

**Own-repository commit permalinks.** `https://github.com/<own>/commit/<sha>`
with the owner matching origin: 85,440 resolve and 1,211 do not, across 31
repositories. 1,180 of the dead are nodejs changelogs, where the link TEXT is
the same abbreviation and is already reported as a bare dead SHA - a second
finding on the same line. The ones written in prose - helix's release notes,
yosys's fuzzing guide - link to commits no local ref reaches and GitHub still
serves, from a rebased branch or a contributor's fork. A URL claims that a
page exists, which git in this repository cannot settle; a backticked SHA
claims membership of this history, which it can. Clause 1, failed in a way the
backticked rule does not fail.

**`dead-path-pointer`, all three halves.** With the current markers and the
proposed extensions, 141 sites and 71 missing, read: "you'll see CMake
configuration and a `main.cpp` file", "the compiler may read `baz.h`" twelve
times across bazel's version snapshots, "see how `print_fortune.go` uses this
package", bare names that live elsewhere in the tree. With the proposed verbs,
197 sites and 136 missing: "check `report.json`", "defined in your
`package.json`", "located at `foo/bar/a.txt`" as a documented default. With a
trailing slash, 80 sites and 47 missing: runtime directories such as `logs/`
and `node_modules/`, a session log saying the directory "does not exist -
no-op", and the English "read" in "read-only" and "cannot read outside". The
existing rule already runs at 191 findings over 654 examined on these corpora,
with the same shapes among them; the widening multiplies a known weakness
three ways.

**`#L` line anchors.** 42 sites; 39 name a file the repository does not
track, and the 3 that do cite lines inside it. No population.

**`.mdx` targets for `dead-md-anchor`.** 3,873 fragments into `.mdx` files
across two repositories, 3,859 of them examined by the widened rule, 16
findings, all 16 false. Every one names a heading that lives in an IMPORTED
partial - `## Tags File {/* #tags-file */}` sits in
`_partial-tags-file-api-ref-section.mdx` and reaches the page through a JSX
component - and the same mechanism already produces that repository's
same-document findings, in both directions. MDX composition makes anchors a
property of the rendered page, and the rule cannot see the render. Built,
measured, reverted.

**GitHub Actions pins for `dead-pinned-ref`.** Zero own-repository `uses:`
lines in the 132, so a corpus of 30 action repositories was cloned for it:
574 pins of the repository's own action resolve and 20 do not, and all 20 are
false. Sixteen pin a BRANCH - `@v3` is `origin/v3` in
marocchino/sticky-pull-request-comment, `@release/v1` is pypa's release
branch - which a clone holds only as a remote-tracking ref and a CI checkout
does not hold at all, so the answer would differ by where one stands. Four
are placeholders such as `@<tag>`. Wrong on every firing.

**JVM, .NET, Swift and version-file floors.** Manifests present: `pom.xml`
in 4 repositories, `build.gradle` in 1, `.csproj` in 3, `Package.swift` in 0,
`.nvmrc` in 11, `.python-version` in 6. Of the JVM and .NET repositories one
states a floor, and it agrees with its manifest. The manifest values need
normalisation nobody has measured - `1.8` against "Java 8", `net10.0`
against ".NET 10", a Maven property against anything - and `.nvmrc` and
`.python-version` are a developer's pin rather than a floor, which is clause
4; the `legacy-web` preset already offers that comparison as a user-asserted
consistency check.

**`unknown-branch` on standing documents, and wider prefixes.** 56 unknown
branch tokens in READMEs, CONTRIBUTING files and agent instructions, and not
one is a claim: `feature/<name>`, `feature/my-new-feature`, `fix/...`, a
table of naming examples, `test/js/bun/` (a directory), `release/blocking`
(a label). `test/` matched 57 tokens and every one was a path; `release/`
matched 51 and none was a branch that exists.

**Merge verbs and live phrases.** "landed on", "integrated into" and
"cherry-picked to" followed by a ref and a commit: zero sites - and zero for
the shipped pattern too, on these corpora; the installer already derives the
verbs a status document actually uses, `landed` among them. The proposed live
phrases match "open on startup", "port 9003 is open on your host", "resize in
progress on pod creation" and "staged on the target": 47 sites, none a merge
status. The four shipped phrases are a small closed set because a validator
that cries wolf stops being read.

## The third widening pass: six proposed, one shipped

A second specification arrived on 2026-09-13, proposing six widenings across
five rules and, as before, describing each as falsifiable with zero false
positives - measured this time on this repository alone, which is the corpus
every rule here was designed on and so settles nothing. All six were counted
first over the same visible population as the pass above, 132 repositories
and 77,401 documents, with the holdout and the sixteen reserved benchmark rows
left unread; the instrument is `widening_census2.py` beside the first one.
One was built, and the refusals below carry the numbers because the next
specification will propose them again.

### Shipped

**CommonMark titles and angle-bracketed destinations.** Two spellings the
format fixes and `MD_LINK` did not read. A title after the destination,
`[guide](docs/a.md "The guide")`, made the whole link invisible to both link
rules because the destination class forbade the space before it: 499 titled
links name a local target across 15 repositories and were examined zero
times. An angle-bracketed destination, `[x](<docs/a b.md>)`, is how the format
spells a target holding a space, and was read WITH its brackets - so a spaced
target was refused, and an external URL holding a parenthesis,
`<https://en.wikipedia.org/wiki/Shebang_(Unix)>`, was cut at the parenthesis,
failed the external test on its leading `<`, and was resolved as a file: 14
findings on the visible corpora, every one false, in bun, OWASP, zed, astro,
angular, llama_index, sonic-pi's vendored libgit2 and axe-core's changelog.
The pattern captures the destination as written, brackets included, because
the patch generator has to find it on the page; `link_destination` takes them
off for every caller that resolves or partitions one, in front of every
refusal. A
bare destination may not open with `<`, because a destination that opens with
one must close with one, so `[x](<docs/a.md)` is not a link rather than a link
to a file named `<docs/a.md>`; and two bare words are still not a link,
because a title must be delimited. Neither spelling gets a repair patch:
`suggest_renames` replaces `](old)` on the page, and a title or a bracket
puts the target elsewhere on it, so the finding stands and no patch is
written - the same silence a reference definition already gets, and a
missing repair over an invented one.

Swept: **14 findings removed and 58 added - 70 counting a message repeated
on several lines of one file - every one read.** Ten of the fourteen were
the false class above and are gone; four are respelled - three
axe-core changelog lines whose destination is literally
`[635445b](https://github.com/...)`, a changelog generator's artefact that is
dead on GitHub whether read to the parenthesis or to the bracket, and a
llama_index README linking to `(https://github.com/nlmatics/llmsherpa)`,
which is the golang testdata shape again. The `detail` of those four changes,
which re-raises them against a baseline; the old spelling was a misread of
the destination rather than a fingerprint anyone chose. Of the 58 added, 38
are angular's `adev/` tree - sixteen images and twenty-two routes - which the
pass above already records as an undetected site supplying a quarter of the
benchmark's ordinary findings; inherited, not created. Five are zstd's
benchmark images in a README vendored into RetroArch without its `doc/`
directory, three are query-graph images in a bazel version snapshot whose
directory the snapshot did not keep, four are documents in fastapi's
translation-fixer test data and two are astro mdx fixtures using the `~/`
alias, which the rule already reports three times unwidened. One is a real
broken image in an ordinary README, qmk's dactyl_manuform schematic, whose
`blackpill_f411/` directory holds five config files and no PNG. One is a
route in seqflow's Vite-built website, which already carries nine of the
same shape. Denominators: `dead-md-link` from 170,360 to 170,844 examined,
`dead-md-anchor` plus three.

Two things the change cost and one it found. The lazy destination class,
left as it was with the title group behind it, tried that group before every
character it extended by, and the 8,000-opener `[a](` line the bounds test
carries went from 1.44s to 2.85s against a five-second margin - still linear,
and too close for a slower runner. Greedy with a lookahead for the space or
parenthesis that must follow, the run is taken once and the group entered
once: 1.09s, the same result on every shape either arm reads, and the timing
test now carries the title and bracket openers too. `text.py` reached 918
lines against a 927-line ceiling, so the link scanner - `MD_LINK`,
`EXTERNAL`, `link_sites`, the HTML walk and `_link_target` - left for
`links.py` the way the anchor machinery left for `anchors.py`: byte for
byte, eighteen mutation anchors following by path alone, and nothing left
behind reading a name that moved. And a mutation was once reported caught by
the wrong test, which is how the range tests in `test_widened_scanners.py`
were found to abbreviate a real SHA to seven characters that `looks_like_sha`
refuses one run in twenty-five, when all seven are digits; they abbreviate to
the shortest prefix carrying a letter and a digit now.

### Refused

**Script invocations inside fenced shell blocks, for `dead-path-pointer`.**
The argument offered was the one `dead-pinned-ref` makes above: an install
snippet is the block a reader copies verbatim, and `python
tests/harnesses/mutate.py` in an agent instruction file is the same kind of
block. Counted from the RAW text, since `prose()` blanks every fence: 2,534
invocations across 81 repositories, 1,485 naming a tracked file and 1,013
not. 869 of the 1,013 are bare names, and 348 of those are typer's
documentation alone - `python main.py`, the file the tutorial has just told
the reader to create - with click's `hello.py`, sonic-pi's
`./linux-build-all.sh` run from a directory the previous line entered, and
z3's `./bootstrap-vcpkg.sh` from another repository beside them. 144 carry a
directory component. 108 name a directory that does not exist either:
`path_to_your_working_directory/`, `dist/index.js`,
`./cross-build/wasm32-emscripten/build/python/python.sh`,
`./node_modules/jest/bin/jest.js`, a vendored README's scripts, and commands
written relative to a package directory that is neither the document's nor
the root. 36 name a directory that exists, 21 distinct, and six of those are
real on inspection - llama_index's `scripts/merge_external_docs.py`, angular's
`integration/run_tests.sh`, node's `tools/gn-gen.py`, agno's
`cookbook/gemini_3/5_grounding.py`, dosbox's `scripts/build.sh` and
openinterpreter's `scripts/write_provider_catalog.py` - beside `scripts/foo.sh`
as a placeholder, `test/repro-XXXX.js`, pdns's `builder/build.sh` inside a
submodule and goose's `scripts/` named relative to `ui/desktop/`. Narrowed to
root-level documents, which is the population the install-snippet argument
is actually about: 65 invocations, 19 not resolving, and none of the 19 real.
Every narrowing that removed the false ones removed the six real ones with
them, which the note on symbol-aware line pointers above names as the
signature of a rule with no population rather than one with bad keying.
Six real findings under a thousand false is worse than the 191-over-654
the existing rule already runs at, not better.

**Table cells under a `Path`, `File` or `Location` header.** 3,170 backticked
cells under a path-shaped header across 49 repositories: 827 resolve, 2,120
do not, 127 are absolute and 96 placeholders. The headers say what the cells
are. `Tool` governs 688 cells and 674 of them are bare tool names, `Package`
158 npm names, `Component` and `Module` 217 more of the same. Under the eight
headers the specification proposes and the three shapes that could be a path
- a slash, an extension, a trailing slash - 951 cells resolve to nothing,
and reading them by repository: 343 are unraid's agent session logs listing
the files each session created and modified, relative to a sub-project the
document is not in; 184 are crewAI's scaffold listing (`crew.py`, `.env`,
`knowledge/`) in twenty version snapshots of one installation page; 70 are
bazel's tutorial layouts; 50 are mem0's workflow filenames relative to
`.github/workflows/`; 47 are agno's cookbook indexes. The smaller subsets read
the same way: every missing `Script` is an acceptance script in an agent
process file, the missing directories are `dist/`, `out/`, `node_modules/`,
`release/` and `.wanta-dev/`, and the slashed files are `packet.h/cc`
shorthand, `scripts/x.py::run_arm_p` citations and plan tables with a
Modify/Delete column. A table names what a file IS, not where it is - the
same finding as the 23-of-88 measurement that keyed this rule on operative
markers in the first place, at a larger scale.

**`manifest-floor-mismatch` in agent and contributor documents, and the
phrase "the floor is".** The phrase first: over every document, 17 sites use
"floor" or "minimum" beside a version, and not one reads "the floor is
<language> <version>" - nine say "a minimum of X" and eight "the minimum
version is X", twelve of them in changelogs, blog posts and third-party
subjects (TypeScript 3.8 for jest's definitions, macOS 10.7, iOS 13.0,
OpenSSL 1.0.2, an ARM cross compiler) and five in vendored READMEs. The
phrase exists in this repository and in none of the 132. The document
widening was measured through the rule's own `_floor_claims` with the wider
`_ENTRY_DOC`, over every AGENTS, CLAUDE, CONTRIBUTING, DEVELOPMENT, SETUP,
ENVIRONMENT and HACKING file: three claims in three repositories - dspy's
CONTRIBUTING "Python 3.10 or later is required", skyvern's CLAUDE.md
"Requires Python 3.11+", openemr's CONTRIBUTING "Requires PHP 8.3+" - and all
three agree with their manifest. Three examined and zero findings is not a
widening. It also carries a clause-4 concern the census could not test: a
contributor guide states what a DEVELOPER needs, and a project whose type
checker wants a newer interpreter than its users do would be the first
repository this shape spoke on, falsely. The two sides name the same fact in
a README and an install guide; they need not in a CONTRIBUTING file.

**Built-in version pairs for `inconsistent-artifact`.** Measured pair by
pair. `pyproject.toml` against a package `__init__.py`: 33 repositories carry
the manifest, 23 have no `__version__` in a package `__init__` at all, 9
declare `dynamic = ["version"]` so the manifest holds nothing to compare, and
one - jztan/pdf-mcp - is comparable and agrees. `package.json` against
`package-lock.json`: 13 repositories carry both, 9 are comparable and agree,
4 state no top-level version in either file. `Cargo.toml` against
`Cargo.lock`: 9 carry both, 8 root manifests declare no package version,
one is comparable and agrees. The Claude plugin pair: two
repositories carry both files and neither is comparable, because
`marketplace.json` states its version per plugin inside a list - as this
repository's does - so the pattern the specification writes matches nothing
in either. Eleven comparisons on 132 repositories, zero disagreements, and
the pattern proposed for this project's own manifests would not have read
them. The note above `"consistency": {}` in `config.py` says a guessed
default "would either match nothing or accuse an innocent repository", and
the measurement found the first half. The presets in `install.py` already
write these pairs at install time, with the files located and the patterns
verified to match before a line is emitted, which is the user-asserted form
the clause-4 argument asks for.

**Nested `.gitattributes` for `raw-lfs-blob`.** The per-file verdict already
composes: it comes from `git check-attr --stdin`, which reads every
`.gitattributes` in the tree with negations and later rules applied, and the
rule's own comment says so. What keys on the root file is the gate, and the
gate is right on every visible repository: 85 track a `.gitattributes`, 4
route anything through LFS at the root, 23 track a nested one, 2 hold an LFS
filter in a nested one - tabby in four sub-projects, autogen in a test images
directory - and both of those beside a root filter. Repositories whose only
LFS filter is nested: zero. The gate exists to spare the 128 repositories
without LFS the `ls-tree -r` that finding a nested file needs, and it would
spend that spawn in every one of them, once per `validate()` and once per
`count_examined()`, against a `--verify` budget with no headroom by design.
`subject_file` naming the root file is a defect only on the population that
does not exist. Refused on population and on cost; the fixture with a
nested file and no root one is the test to write when a repository of that
shape turns up.

### The benchmark reserve, opened and read

Re-recording the corpus report after both passes put a number in it that
nobody had judged: 1,043 of the benchmark's additions sat in its sixteen
reserve repositories, 1,019 of them in tensorflow/tensorflow, and the reserve
is held back precisely so no pass reads it while designing. The report said
so beside the figure. The operator then chose to spend the reserve on a
reading rather than publish an unjudged number - tensorflow first, then the
other four repositories with additions - on 2026-09-13. The manifest rows
record the opening and the date, so nothing measured later mistakes them for
unseen ground; the eleven reserve rows with no additions stay closed. The
readings are recorded beside the recordings, and the report renders them.

**tensorflow, 1,019.** All are the `href` of raw HTML, the arm the second
pass added, and 1,018 live in `tensorflow/lite/g3doc/`, the DevSite tree
`sites.py` already records as deliberately unreached - its `_book.yaml` sits
three levels down, and scoping detection that deep silenced six real defects
in astro and llama_index. 1,003 are routes that resolve the moment `.md` is
appended, the same class as angular's `adev/` findings; 15 are links in a
generated `all_symbols.md` index that the generator wrote one directory too
shallow, routes in the same tree whether or not the site serves them; and 1
is a real broken image in the vendored XLA README under `third_party/`. No
new false-positive shape, one real finding, and the class it multiplied was
already on the record.

**The other 24, and the two things they found.** Five are titled image
links in vscode's copilot scenario and colorize test fixtures, and one is an
HTML link in an npm package's README copied into deno's bench test data
without its `docs/` directory - fixtures, which `exclude_paths` is for. Two
are pages of mdBooks three levels down: clippy's book serves
`continuous_integration/README.md` under the name `index.md`, and the
unstable book generates `impl-trait-in-assoc-type.md` at build time. Two are
real: a rustc-dev-guide page, `generic_arguments.md`, that no longer exists,
and a dead link in clippy's changelog, labelled historical-record. That
leaves two shapes the visible corpora had never shown.

The first is a scanner defect, fixed. `` [`unused_peekable`]: Now respects
`#[allow]` attributes... `` is a changelog line; CommonMark lets a
definition's destination be followed only by an optional title and the end
of the line, so it renders as a paragraph and links nothing, and the pattern
the second pass added stopped reading at the destination and reported a dead
link to a file named `Now`. Measured before it was changed: zero of the
3,171 definitions recorded on the visible corpora carry trailing prose, so
requiring the line to end removes nothing there and cannot remove a real
definition. The recordings were taken again with the fix, so the report
describes the tool it ships with.

The second was built the next day, and the measurement that shaped it is
the interesting part. `` [`float`]: c_float `` in
`library/core/src/ffi/c_double.md`, and `[value-macro]: macro@crate::value`
in turbopack's `vc/README.md`, are rustdoc intra-doc links: the markdown is
pulled into rustdoc by `#[doc = include_str!(...)]` in a sibling `.rs` file,
and the destination is a Rust path, not a file. 13 of the 24 are this shape,
and the visible corpora hold 2 more, in a README zed's `gpui.rs` includes.
Both halves of the refusal are needed - the shape alone is `[x]: LICENSE` in
any README, and the inclusion alone leaves `[guide](docs/guide.md)` a file
rustdoc links to as a file - so `dead-md-link` declines a destination shaped
like a Rust path only inside a document some `.rs` file pulls into rustdoc,
in the adapter where the site-tree refusal already lives, neither judged nor
counted.

**Where to look for the including file was measured, not chosen.** Across
the 132 visible repositories, five pull 176 markdown files into rustdoc.
Finding every one means reading every `.rs` file in the repository: 668
seconds across the corpora, rust alone 419, which is not a question a hook
can ask. Reading only the `.rs` files in the document's own directory and
its `src/` child - a crate keeps its README beside `src/lib.rs`, and rust's
`c_*.md` sit beside `primitives.rs` - takes 1.4 seconds in total and finds
78 of the 176, including every document that carries one of the 15
findings. The 98 it misses have their including file two directories up,
`..` or `../../src`, and hold no link of this shape at all, so the bound
drops no refusal on any corpus measured. A refusal missed reports a finding
somebody can argue with; a search widened without a measurement is how a
suppression grows quietly, and a mutation anchor now bites on exactly that
widening.

Two details keep the inclusion test honest. The literal is resolved against
the source file's directory and compared with the document's path, never
matched by basename, because `docs/src/lib.rs` including the crate's
`../../README.md` would otherwise claim `docs/README.md` too. And the
attribute shape is `#[doc = include_str!`, not a bare `include_str!`, which
also embeds a template or a fixture as a string - and rust's `primitives.rs`
shows why the literal is looked for anywhere in the file rather than inside
the parentheses: it writes `include_str!($Docfile)` and passes `"c_double.md"`
to the macro. The answer is memoised per directory for the run, and asked
only once a link of the shape is on the page, so a document with none pays
for no source read.
