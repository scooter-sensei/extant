# Code blocks: what a document quotes rather than claims

Part of the design rationale; [its core](../design.md) maps every part and
section. A claim inside a code block is an example, not a promise, so which
lines are code decides what every rule reads. These sections record how that
is decided, and the renderers the decision is held to. The sections are in the
order they were written.

## The other code block: four spaces, and the renderers that disagree about them

CommonMark has two kinds of code block and this project only ever recognised
one. A fence is unmistakable; four spaces is not, because four spaces means
something different inside a list item, inside a block quote, and inside three
constructs CommonMark has never heard of and most documentation is written
with. Phase 51 counted the findings sitting in an indented block and REFUSED to
act on the count, because a count cannot answer the question that decides the
change: what would it BLANK. This is that measurement, and then the build.

**The oracle, since a pattern cannot be its own judge.** markdown-it-py 4.0.0's
`commonmark` preset is CommonMark 0.31.2, the specification cmark-gfm follows
for indented code. It cannot ship - a third-party runtime dependency is
refused, and the package has none - so it was used the way a corpus is used:
over the 152 visible clones, 81,429 markdown documents, 64,640 of them holding
a fence or an indented line, with the apparatus in `m16_indented.py`,
`m16_variants.py`, `m16_agreement.py` and `m16_predict.py` in the
extant-hardening checkout and the rows under `D:/repo/out-indented`.

**Three designs, priced against each other on the same corpus.** A, the
FAITHFUL rule: blank every block the reference calls indented code. B, the
same minus the constructs whose renderers redefine four spaces. C, a
whitelist: blank only where nothing at all is open above. Counted in lines
carrying findings:

| | lines silenced | ordinary stratum | hand-read as code | hand-read as PROSE |
|:--|--:|--:|--:|--:|
| A faithful | 23,540 | 101 | 70 | **31** |
| B minus the extensions | 2,128 | 70 | 70 | **0** |
| C top level only | 2,128 | 70 | 70 | **0** |

**A is refused, and the 31 are why.** Every ordinary-stratum finding was read
by hand, document by document. The 70 that are genuine code: moby's
`vagrant@net-1` transcript (28), OWASP's `docker pull` transcript (6),
openfoodfacts' notebook output table (6), go's markdown-syntax examples (2),
restic's `restic init` transcript (2), vscode's fixture captioned
`// Indented code` (1), qmk (1), and moby's generated API documents' HTTP
request and response examples (2,202 outside the ordinary stratum). The 31
that are prose: mkdocs-material's admonitions and content tabs, whose body is
the widget's text (uv 6, ruff 1, dosbox-staging 4); MDX and JSX elements,
whose children are indented by convention (bun 21, goose 2); and definition
lists, `:   text`, whose body is the definition - bazel's versioned
command-line reference writes 21,384 lines of them, every one holding anchor
links its site renders, and the faithful rule would have silenced the lot.
That last number is worth stating plainly because the previous record counted
it as the prize.

**B and C select the same findings, and B is what shipped.** The population
where they differ - an indented block inside an ordinary list item or block
quote, holding a finding - is EMPTY on this corpus. So the choice was not
about yield but about which principle to state, and B says the true one:
CommonMark, minus the constructs whose renderers redefine indentation. C would
miss a genuine command under a list bullet the day one appears; B blanks it,
because it keeps the container model. The residual risk B carries is the next
extension nobody has met, and it is stated here so that adding one is a
decision with a number rather than a patch.

**What the corpus corrected in the implementation, five times.** The state
machine in `extant/blocks.py` is hand-written stdlib, so it was measured
against the reference line by line over all 64,640 documents, asking the one
question that decides safety: how many lines do WE call code that the
reference does not - prose blanked on our own authority. It began at 109,293
and ended at 12:

1. an HTML block ends at a BLANK LINE, not at a dedent - a card grid's
   `</div>` dedented past its opener, released the suppression, and was read
   as the start of a block (109,293 lines; SWE-agent's index alone thirty);
2. the measurement itself counted fence content as disagreement, which
   measured the instrument rather than the module (92,867);
3. an HTML comment is a block that ends at `-->`, and its body is indented as
   often as not - a pull-request template is the common case (1,216);
4. a paragraph inside a list item may wrap onto a line indented LESS than the
   item's content, and CommonMark keeps the item open; treating that as a
   dedent closed the item and the bullets below it measured from the margin
   (1,058, kubernetes' `staging/README.md` and moby's API documents);
5. `<pre>`, `<script>`, `<style>` and `<textarea>` run to their OWN closing
   tag, through blank lines and through lines at the margin - bazel's
   output-directory tree has both, so every other state had been released
   (994).

The 12 that remain are whitespace-only lines in one test fixture, counted
twice because that clone sits in two tiers; blanking a line that holds only
spaces changes no character and no finding. NONE of the five was visible to
the twenty-two unit tests; each was visible only against real documents, which
is the argument for the corpus and the reason this is a module with a
measurement rather than a pattern with an opinion.

**What is left unread in the other direction, with its number.** 2,692 lines
the reference calls code and this module leaves as prose, outside the four
exclusions - a false positive left standing rather than prose silenced, which
is the safe direction. Sampled across eight clones: 314 hold content and 59
are blank, and the content is dominated by one shape, a list marker followed
by five or more spaces, which CommonMark turns into an indented code block
INSIDE the item. Recorded rather than built, because closing it means a line
that is both a list item and a code block, and the gain is a false positive
this tool already lives with.

**The fence toggle was wrong about fences, and that is fixed beside it.**
`_FENCE` matched any run of three or more backticks or tildes and TOGGLED.
CommonMark closes a fence only with the same character, at least as long as
the opener; a closing fence carries no info string; and a fence inside a block
quote is still a fence. Measured against the same oracle: 1,498 documents hold
a line the reference calls fence content that the toggle did not blank, and 41
findings sit on those lines - 38 in ordinary documents. Two shapes: a
four-backtick block quoting a three-backtick one, which is how every agent
transcript writes a fenced example inside a fenced example (aider's posts and
superpowers' plans, 16 of the 41), and `> ```' - which `^\s*` never matched at
all, so fxamacker/cbor's quoted hex dump was read as prose in both moby's and
kubernetes' vendored copies. What is deliberately NOT implemented is
CommonMark's rule that an opening fence may be indented at most three spaces:
this stripper has no container model at the fence level, so it cannot tell
four spaces of list indentation from four of code, and applying the rule
absolutely would stop it blanking every fence written under a list item -
claims read out of code, the direction that matters most.

**The first fence fix was not the last, and the gate is what said so.** Its
identity run (2026-09-23) moved 30 outputs, and in one of them the direction
was wrong: aider lost 139 findings, 129 of them in reference PROSE, because a
fence opened inside a block quote stayed open after the quote ended - a pasted
message cut off mid-block. So the measurement changed instrument. Instead of
counting findings, it compared the old stripper with the new over every line
`prose()` empties that the reference calls prose, in three columns: prose the
old toggle silenced and the new code reads (repaired), prose both silence
(pre-existing), and prose the new code silences that the old one read
(regressed). Three more conditions came out of that column, each with the
document that showed it: a fence ends when the block quote it opened in ends
(aider's chat-history fixture); a closer may sit at most three columns deeper
than its opener, since four or more is a fence SHOWN inside a fence
(mini-swe-agent's admonition example, superpowers' reviewer template); and a
backtick run with a backtick later on the line is an inline span, not a fence
(kubernetes' changelogs). Five conditions in all, and the columns after the
last of them:

| | prose lines |
|:--|--:|
| repaired - silenced by the toggle, read now | 98,579 |
| pre-existing - silenced before and after | 76,934 |
| regressed - read by the toggle, silenced now | 1,474 |
| recorded findings on the regressed lines | **0** |

**What is shipped with it, and why it is not a suppression firing wrongly.**
Every rule added to the fence loop moved its errors rather than removing them
- the regressed column went from 1,042 to 1,474 while the repaired one grew -
and the diagnosis is structural: the loop has no container model, so it
cannot tell a fence inside an HTML comment, a JSX element, a list item or a
`<pre>` from one at the margin (deno's regressed document is a test fixture
about exactly that, a fence inside an HTML comment). The indented half
converged because `extant/blocks.py` HAS that model. The house rule weighs a
suppression that fires wrongly above a false positive because it deletes a
real FINDING silently; measured, it deletes none here. The 1,474 regressed
lines sit in eleven outputs - crewAI 740, aider 206 in each of its two tiers,
mem0 189, haystack 88, AdguardTeam 19, bun 15, qmk 4, deno 3, PX4 3, goose 1
- and not one finding of the recorded sweep sits on them. What is left against
them is latent and stated: a claim written into one of those lines later
would be silenced, and denominators can move where they held a passing
claim. The gate bounds that last one. crewAI, mem0 and haystack, three
quarters of the regressed lines, move no output at all, so their regressed
lines hold no examined site; the only sites that could sit on regressed lines
are PX4's 8 and AdguardTeam's 2 link sites, in the two clones whose
denominators fell and which also regressed. The unified scanner - fences
moved into `extant/blocks.py` under the same container model, gated by the
old-against-new measurement until the regressed column is zero or explained -
is the next tranche, and the reason this one does not wait for it is 67 lines
repaired for every line regressed.

**The gate, held to a number rather than a bound.** The first run's
prediction (87 outputs) was an upper bound - a readable-line test,
deliberately wide - and 30 moved. This time the prediction ran the survey's
own per-document validator over every document holding a fence or an
indented line, once with the old payload and once with the new, and counted
an output as moving when its findings or its summed denominators did: 28
predicted, with 2,338 findings lost and 423 gained. The gate: 28 of 152
differ, the predicted set exactly, none missing and none unpredicted, and the
per-clone totals reproduce the prediction's figures. Every lost finding was
then checked against the reference: all 2,338 sit in reference CODE - moby's
generated API documents and vagrant walkthrough 1,140 in each of its two
tiers, the other 58 in eleven outputs, superpowers' plans, aider's posts and
the transcripts read by hand above among them - and all 423 gained sit in
reference PROSE: aider 204 in each tier (the old toggle's desync had silenced
them), bazel 6, zed 5, uv 4. The apparatus is `m16_prose_delta.py`,
`m16_predict_sites.py` and `m16_composition.py` beside the others.

**The memo key took the lesson it had already learned.** `_STRIPPED` is keyed
on the text's identity, and carried the document format since 2026-09-16
because a key missing an input is answerable from the wrong reading. The
suffix is now an input too - `.mdx` has no indented code block - so the key
carries the document's path beside its format.

**A scanner nothing in the fuzzer could reach, until a property did.** The
plan for this tranche said the harnesses generate no four-space shape, so
nothing there would break - and the same fact meant nothing there WATCHED
the new module either. A change that stopped it blanking would have passed
every fuzz run, the property-that-cannot-fire shape the self-check exists
to catch, arriving through an absence rather than a stale anchor. So the
fuzzer gained `INDENTED`, a sibling of `FENCE`: a paragraph at the margin
and then an indented line holding a dead pointer and a dead link, appended
to the primary document, must move no finding. The paragraph is load-bearing
- four spaces after a blank line is code only at the top level, and a list
item, an admonition or an HTML element left open at the end of a document
would make the line prose, where a finding is honest - and where nothing can
close what is open (a fence, a comment or a verbatim tag) the oracle steps
aside and says so. Its breakage is the scanner's own early return widened
from `.mdx` to every document, the state the tool shipped in for fifty-two
phases; watched silent on the clean payload and red on the broken one, the
twenty-third of twenty-three.

## One scanner for both code blocks: a fence ends where its container does

Phase 53 left the two kinds of code block with two scanners. The indented one
in `extant/blocks.py` kept a container model; the fence loop in `text.py` had
none, and every condition added to it moved its errors rather than removing
them - the regressed column went from 1,042 to 1,474 across three rules. The
record said why and named the repair: fences moved under the same container
model, gated by the old-against-new measurement. This is that repair.

**Measured before it was designed.** `m17_fence_causes.py` replays the
shipped loop line by line and asks markdown-it-py's `commonmark` preset why
each disagreement happens, split by suffix and by the renderer the site
config above the document names. Lines the loop blanked that the reference
renders as prose:

| cause | lines | who is right |
|:--|--:|:--|
| a list item's end does not close a fence opened in it | 3,372 GitHub-rendered | CommonMark, which is GitHub: a defect |
| JSX or HTML in `.mdx`, or in `.md` under Docusaurus, Mintlify or Fern | 71,879 | MDX, whose elements' children are markdown |
| a fence inside an HTML comment | 1,014 | neither: commented-out code is not rendered |
| a fence indented 4 or more, continuing a paragraph | 43 GitHub-rendered, 157 on MDX sites | depends on the renderer |

One clone per repository, as every count below is. The table as first
recorded said 3,652, 1,061 and "about 73,400" and set 43 beside 88: the first
two counted aider's and moby's second corpus tiers, the third re-derives from
no single definition of its row, and the 88 was haystack's share of Phase 53's
regressions, a different measurement from the 43 beside it. Corrected by the
audit of the built tranche on 2026-09-28; the decisions each row supports do
not move.

The same classifier over Phase 53's 1,474 regressed lines gives 1,268 once
aider's second corpus tier is folded - the classifier listed ten clones and
the regressions sat in eleven, the eleventh being the other tier's copy of the
same 206: MDX JSX 929 (crewAI 740, mem0 189), the list-item defect 227, `.md`
on an MDX site 89, comments 22, whitespace 1. The list-item row is the one
real defect; the handoff that carried these counts put 433 against it, the
duplicate tier counted under the wrong cause.

**CommonMark is the wrong oracle for MDX, so MDX judged its own.**
@mdx-js/mdx 3.1.1 was installed into a scratch directory beside the corpus -
the tranche's one network step, taken on the user's word - and run offline
from then on (`D:/repo/mdx-oracle/oracle.mjs`: paths in, each fenced block's
line range out, or the parse error). Of the 39,256 MDX-rendered documents
holding a fence, one clone per repository, it parses 96.3 per cent: 34,777 of
35,807 `.mdx` and 3,043 of 3,449 `.md` on MDX sites. The refusals are named,
not guessed - bazel 919 and AdguardTeam 253 of them, 1,176 a `{` MDX 3 reads
as a JavaScript expression and 242 an HTML comment, which MDX 3 rejects. On
the shapes that decide the design it agrees with CommonMark about containers
- a list item's end closes its fence, a fence on the marker's line opens one,
a closer dedented out of its item opens a new fence - and disagrees about
indentation: a fence is a fence at eight spaces, inside a JSX element's
children, and continuing a paragraph at four.

**The design.** One scanner, `code_lines(text, *, mdx)`, returning fenced and
indented lines by kind; `text.py` blanks what it returns and fell from 879
lines to 783. A fence ends when the list item, block quote, HTML comment or
verbatim tag it opened in ends - the block quote was already shipped, the
other three are new - and a fence on a list marker's line opens one. The five
closing conditions moved unchanged. Two divergences are recorded rather than
repaired, each a renderer the reference is not: a fence opens at ANY
indentation, which is MDX's rule and mkdocs' inside an admonition, and a
fence inside a comment or a verbatim tag is still blanked, since nothing in
one is rendered - the terminator's line with it, since it is the comment's.
`mdx` switches off indented code, comments and verbatim tags and nothing
else, because MDX shares CommonMark's list items and block quotes. The comment
half of that switch rests on MDX 3 refusing a comment, and Docusaurus does
not: its `markdown.mdx1Compat.comments` defaults to true, per the corpus's own
copy of its configuration validator. So on Docusaurus's `.mdx` the switch is
wrong in principle; measured by `m17_mdx_comments.py`, no fenced line of any
`.mdx` on the corpus depends on it, and it stays until one does.

**What auditing the design before building it added.** Four things the
design as first written did not say. The list-item rule cuts both ways: a
closer indented less than its item's content is not in the item, so the item
and its fence end on that line and the closer then opens a fence that runs to
the next closing fence - swallowing the author's next opener as content - or
to the end of the document when none follows; GitHub renders it so and MDX 3
does too, and PX4's
ko, uk and zh translations of one page are the shape, bounded on GitHub by the
80 lines the reference calls code and the old loop read. The list model had
never run on an `.mdx` file, because the indented scanner returned before it;
it runs now. `<pre>`, `<script>`, `<style>` and `<textarea>` end at their own
tag by the comment's mechanism, and the scanner already tracked them, so
treating comments and not these would have left one mechanism half applied.
And the indented scanner could not see fences at all: an HTML example's
`<!--` or `<pre>` inside a fence opened a block nothing closed, hiding every
indented block after it, and a fence's closing line read as an open paragraph,
so an indented block straight after one was taken as its continuation. Each
has a red-first test.

**The gate: the new stripper against the SHIPPED one, judged by the
renderer each document has.** `m16_prose_delta.py` compared against the
pre-Phase-53 toggle, which is known wrong; `m17_delta.py` compares two payload
extracts - main as shipped and the working tree - each in a process of its own,
reading only the public `prose`, and judges every line whose verdict moved by
markdown-it for GitHub, mkdocs and mdbook and by the MDX oracle for `.mdx` and
MDX sites. 61 documents moved. One clone per repository:

| column | lines |
|:--|--:|
| prose newly read - the repair | 3,437 |
| code newly blanked - the repair | 399 |
| PROSE NEWLY SILENCED | 19 |
| CODE NEWLY READ | 21 |
| unjudged: MDX 3 refused the document | 137 |

kubernetes' changelogs are 3,087 of the prose newly read - entries after an
unclosed paste, each a pull-request link. The first run of the gate found a
defect in the new scanner itself: to decide whether a line had left its list
item, it stripped every `>` in front of it, and inside a fence a `>` is
content - a `diff` line, a shell prompt, a `>&2` redirect - so node's
root-certificate notes, cpython's mimalloc readme and openfoodfacts' VS Code
page closed their fences early, 5 lines silenced and 15 read. The scanner now
strips only the markers the fence opened under; a test pins it, red before.

**The 19, line by line.** moby 6 and bazel 6 are one shape: a list item's
content dedented to the margin ends the item and its fence, faithfully, and
the real closer - four spaces in, continuing a paragraph, which CommonMark
reads as text - then opens a fence under the refused "at most three spaces"
rule and swallows a list label or a heading. The faithful alternative was
built as a variant and measured the same way rather than argued: CommonMark's
rule for a fence line four past its container while a paragraph is open. It
repairs moby's and bazel's 12 silenced lines and reads 158 more lines of prose
(GitHub 56, MDX sites 88, mkdocs 14) - and in exchange reads 539 more lines of
code as prose (MDX sites 437, mkdocs admonitions 102), and silences 19 lines on
MDX sites the chosen design reads, 26 silenced in all against 19. Refused
again, on those terms. goose 3: its opener is five columns into a list item
while a paragraph is open, so CommonMark sees no fence there at all and reads
the whole run as paragraph text; this scanner opens the fence under the same
refused rule, as MDX does, and after its closer reads `:::info` - four past
the item's content, no paragraph open - as indented code, which MDX does not
have. So it is Phase 53's recorded divergence for `.md` on an MDX site,
reached through the refused opener. aider 4: bare `>` lines at the end of an
indented block inside a quote, which `_last_nonblank` counts as content
because it tests the raw line; they hold no text, so blanking them silences
nothing.

**The 21 code newly read** are aider's: `<source>python` above an indented
edit block is, to CommonMark, the second line of a setext heading, so the
block below is code; to this scanner it is an HTML element whose indented
body is prose - Phase 53's governed-body exclusion, built for `<Step>` and
`<TabItem>`. It shows now because the desynchronised fence that had hidden
the whole region is gone.

**The 137 unjudged** are two shapes. AdguardTeam's 77 are `- ```none` fences
on a marker's line across twenty translations of one page, newly blanked, and
the text after them newly read; CommonMark calls the first code and the second
prose. bazel's 60 are twelve `.mdx` version snapshots of `remote/ci`, the same
list-item shape as its `.md`; MDX 3 refuses the whole file over an expression
elsewhere, and on the region alone the oracle's fenced lines are exactly the
scanner's - which is also the case for the refusal above, since there MDX needs
the four-space opener CommonMark forbids.

**Two readers of one marker, counted.** `_FENCE` counts block-quote markers
with `(?:\s*>)*` and the containers strip them with `^ {0,3}>`, and since this
tranche both sit in one module - the shape "one claim, one scanner" warns
about. They disagree on 96 fence lines in two clones, and in two shapes that
cut opposite ways. haystack's 68 are a doctest's `    >>> ```python` in
generated API reference: the wide reader counts three quotes where CommonMark
sees none, and the fence it opens closes on the next line. bazel's 28 are a
block quote nested in a list item - a `>` four spaces in, a fence after it -
in its completion page and its snapshots: there CommonMark measures the marker
from the item's content and sees a quote, which the wide reader agrees with
and the containers' pattern, counting from the margin, misses. Not one line of
either clone moved. Recorded, not merged: merging them changes the five closing conditions
this tranche promised to move unchanged, and neither reader is the right one
for both shapes.

**The identity gate, held to a number.** `m16_predict_sites.py` ran the
survey's own validator over every document holding a fence or an indented line
under both payloads and predicted, in a log written before the gate ran, 8 of
152 outputs moving with 0 findings lost and 106 gained: kubernetes 94, moby 6
in each of its tiers, and denominators alone in aider, AdguardTeam, PX4 and
qmk. The gate: 8 of 152 differ, the predicted set exactly, and each per-clone
total reproduces - kubernetes 2,522 to 2,616, moby 444 to 450 in both tiers.
Every one of the 106 sits in prose by its renderer's reference, and they are
what the tool finds on such lines everywhere else. kubernetes' are dependency
bumps - a module moving from one pseudo-version's commit to another, compare
links into other repositories - the shape its other changelogs already
report, hidden until now behind an unclosed paste. moby's are a registry token
in a JSON body that its generated API documents indent less than the list item
it belongs to, so GitHub renders it as a paragraph; the token is no commit.
That is the price of reading what the renderer shows, stated rather than
engineered around: the rule reads rendered hex as a SHA claim, and a document
that renders its example as prose has made one.

**A test that left its run's errors behind.** The suite, run with
`-n auto` during this tranche, failed two tests in `--introduced-since`'s file
that passed alone, and they fail the same way on main by naming three tests in
order. What outlived the injecting test's monkeypatch was not the rule it
broke - `RULES` was restored - but `RULE_ERRORS`, the run's list, which
`main()` clears and a mode function called directly never passes through; the
next direct gate run decided its exit from an error it had not raised. No
shipped caller runs two modes in one process - the CLI, the hooks and the
action each run `main()` once, and the identity gate sweeps one clone per
process - so it is test isolation, and it was repaired there: one
`raising_rule()` helper that takes back by mark what the run recorded, used by
the three tests that injected a raising rule without doing so, and an autouse
guard that fails the test that leaves an entry behind and names it - at its
own teardown, in every order - before emptying the list, so the report lands on
the cause rather than on its victims. The guard found the third, which a probe
comparing each test's list before and after had missed: an earlier leak had
left the identical entry, so before and after compared equal.

**What auditing the built tranche corrected, 2026-09-28.** Asked for after
the pull request was open and green, and done claim by claim against probes
rather than by rereading. The record was wrong in seven places, corrected
above in place: two in the cause table - counts that were raw where every
other number is one clone per repository, and a pair of numbers taken from two
different measurements; the refused variant's trade, which the first record gave as
"560 lines of code to repair 12" and was in fact the larger exchange stated in
the 19's paragraph; where a stray closer's fence ends - at the next closing
fence, not at the end of the document; goose's cause; bazel's 28 quote-reader
disagreements, which are a nested quote and not a doctest; and the premise that
a comment is a parse error in MDX, which Docusaurus does not share. Two paths
of the scanner had no mutation anchor, and one of them no test: the
quote-marker limit the delta forced was killed by its test but unwatched by
the campaign, and dropping the paragraph a fence ends - a fence interrupting
a paragraph, then a four-space line after its closer, which markdown-it-py
calls code at the margin and inside an item - survived every test. Both are
anchored now, the second with a test watched red first. Two things are
recorded rather than built. The fuzzer's FENCE oracle calls a document
unclosed by an odd count of backtick fences, and `fuzz_axes` places claims by
the same toggle; a document with a dedented closer has an even count and ends
inside a fence, so the oracle would raise a false alarm on it - latent, since
no generator writes a fence inside a list item. And a list item whose first
line is itself indented code - a marker, five spaces, then a fence - is not
blanked; the marker-line check correctly declines the fence, and the indented
half of that line was a gap before this tranche, on the plan's list of
CommonMark facts not yet needed.

## Two defects the mutmut cross-check found: a spaced closing tag, and how far in a setext heading may sit

Phases 63 and 64 wrote a test for every mutant mutmut found that no test
held, with the expected value taken from the renderer. Twice the renderer
disagreed with the tree, and the mutant agreed with it: those were not
gaps but defects. Each was recorded, and Phase 65 repairs both, test first.

**A verbatim block ends only at its literal closing tag.** CommonMark ends
a `<pre>`, `<script>`, `<style>` or `<textarea>` block at a line CONTAINING
`</pre>` (and so on), in any case. `_closing` also took `</pre >` - a
space or a tab before the `>` - which is an end tag to a browser but not
to the markdown parser: markdown-it-py and micromark both run the block on.
The lines after it are raw HTML to the renderer, and this module read them
as markdown again, so an indented one was blanked as code and its claims
went unread. Now the test is the literal tag, matched without regard to
case.

**Either line of a setext heading may sit up to three columns in, and no
further.** CommonMark lets the title and its underline each be indented one
to three spaces; at four the title is indented code, and an underline at
four is the paragraph's continuation. `_setext_headings` refused EVERY
indented title, so a working link to ` Configuration` over ` -------` was
reported dead. And it read the underline stripped, so an underline at any
depth made a heading no renderer makes, offering an anchor that could
forgive a dead link. Now both lines are measured in columns, a tab reaching
the next stop of four.

**Measured before the gate.** Over the 152 visible clones' 81,433 markdown
documents, old against new (`m25_predict.py` in the measurement apparatus):
- The closing tag changed which lines are code in no document.
- The setext rule changed anchors in 31 clones: 1,121 spellings gained,
  none lost. The underline half removed nothing anywhere.
- Of the newly admitted indented titles, 35 are real headings (OpenSSL's
  NOTES files, vendored into node) and 803 sit inside code blocks - YAML
  examples, two spaces in, then `---`. Those are phantoms, the same class
  `anchors()` already offers for an ATX `#` line inside a fence, because it
  reads the raw text. Its comment states the bargain: a spelling no
  renderer uses costs nothing unless a dead link's fragment happens to
  equal it.
- Here that happened once in the corpus. Every link spelling the rule
  reads was scanned, and exactly one fragment equals a gained spelling: a
  same-document `#requirement-details` in node's NOTES-VMS.md, whose own
  document did not gain it.

The prediction, written before the gate ran, was 0 of 152 outputs
differing, and the gate agreed: 0 of 152. The phantom class stays recorded
and unchanged. Closing it means running the code-block scanner inside
`anchors()` for every document a link reaches, and nothing measured here
would move.
