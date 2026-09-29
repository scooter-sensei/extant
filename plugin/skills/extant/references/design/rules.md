# Rules, strata and the baseline

Part of the design rationale; [its core](../design.md) maps every part and
section. Each rule answers one question, and most of what is below is the
record of where a first answer read too much or too little: the formats and
trees a rule skips, the kinds of document it reports but does not gate, and
the baseline a project uses to leave a finding broken on purpose. The sections
are in the order they were written.

## `raw-lfs-blob`: Git LFS, and the direction that had to be refused

`.gitattributes` is a document making a falsifiable claim: files matching these
patterns are stored as LFS pointers. That claim can be false, and when it is,
nothing says so. Git accepts the commit, the engine loads the asset, and the
repository carries a real binary in its history forever.

Two directions look identical and only one is usable.

**A path under an LFS filter stored as a raw blob** is answerable from git
alone: `check-attr` says what the filter governs, and the pointer header says
how it is stored. No network, and the LFS binary is never invoked.

**A pointer whose object is missing locally** cannot be a rule. Measured: a
fresh CI checkout without `git lfs pull` holds ZERO objects, so that check
would report every asset in the project as missing on every run. It is the
false-positive class this project treats as worse than having no validator.

Both of this rule's bugs were invisible in its output, which is why it has more
mutations than any other. Paths were piped to `check-attr` with `text=True`, so
Windows appended a carriage return to each, git read it as a literal path
character, and answered `unspecified` for all but the LAST path. The survey
reported 1 of 4 governed files, and the one that survived happened to be the
one with the finding - so the rule looked perfect. Had the bad file sorted
first it would have printed a clean result over an examined count of zero.

It also read `git ls-files`, the index, which is empty on a repository whose
checkout has not completed. On a real Unity project that meant zero examined
while `.gitattributes` sat there declaring 47 LFS patterns. It reads HEAD's
tree now, which is also the right semantics: this runs after a commit, so the
committed state is what is being judged.

And one subprocess per file cost 40 seconds on a 7802-file project. That is not
a slow hook, it is an uninstalled one. Sizes come from one `cat-file
--batch-check`, contents from one `cat-file --batch`, and only for blobs small
enough to BE a pointer: 262 ms.

## The game-engine presets, and the widening that was measured and refused

The plan was to widen `path_pointer` with asset and source extensions. Measured
against a real Unity project and a real shipped Godot game, that rule examines
ZERO references in either. Game documentation writes paths as markdown links -
`[ART_NOTES.md](Documentation/ART_NOTES.md)` - and `path_pointer` requires a
BACKTICKED path introduced by an operative marker. Widening it would have been
a no-op that looked like a feature. Neither preset touches it.

`dead-md-link` is what carries these projects and needed no change: 257 links
examined across the two, one reported, and that one is a genuine bug - a README
linking to `/doc` with a leading slash, which GitHub resolves to the site root,
while every other link in the same file uses the relative form.

The version checks are keyed on different documents per engine, because that is
where each project actually states it. Unity puts its editor version in a
shields.io badge carrying the exact `6000.0.52f1`, matching
`ProjectVersion.txt`; its prose two paragraphs later says only "6000.0 LTS", so
a check keyed there needs major.minor on both sides and would miss a drift from
`.52f1` to `.61f1`. Thrive's README states no Godot version at all, so that
check reads `doc/setup_instructions.md` instead - keyed on the README it would
have examined nothing forever while exiting 0.

There is no `unreal` preset, deliberately: no corpus was measured for it, and
`EngineAssociation` in a `.uproject` holds a GUID rather than a version for any
studio on a custom engine build, so the obvious check would false-positive on
exactly the teams most likely to want this.

## The baseline, and the two things it deliberately does not do

A baseline is an amnesty: a list of findings a project has agreed to leave
broken so that NEW ones stay visible. Every design question about it is
whether that amnesty can quietly grow to cover everything, so the constraints
matter more than the suppression does.

It is never written implicitly, the suppressed count is printed on every run,
`--baseline-check` reports entries whose finding no longer occurs, and a
corrupt or missing baseline is an error rather than an empty one. That last
point is the important one: treating a missing file as "suppress nothing"
would let a typo'd path turn a ratcheted run back into an ordinary one without
saying so.

One consequence is accepted rather than fixed, and the smoke harness flags it
on every run so it stays visible rather than becoming folklore.

**One recorded finding forgives every future copy of itself.** The fingerprint
is `(path, kind, detail)` and deliberately excludes the line number, so the
same claim pasted somewhere new in the same file is already forgiven. The
alternative is worse: line-number fingerprints un-suppress the entire baseline
on any reflow, which makes the file useless within a week and teaches people
to regenerate it wholesale, which defeats the point of having one.

## `possible-secret`, removed in 0.14.0

It scanned for four credential shapes: an OpenAI key, a GitHub PAT, an AWS
access key id, and a JWT. It is gone, and the reasoning is worth keeping
because the same argument will be made again for the next rule that looks
useful and answers a different question.

**It found nothing.** Zero findings across 38 repositories and 7,708 markdown
files. The only time it was ever observed firing was on a design document that
contained an `sk-` example, which was a false positive.

**It asked a different question from every other rule.** The rest ask "is this
statement still true", which git or the filesystem settles. This one asked
"does this file contain something dangerous", which is a different job with
different tooling. The core guarantee is stated as falsifiability, and this
rule met that letter while missing the point of it.

**And it was not competitive.** gitleaks ships roughly 150 rules and trufflehog
several hundred with live verification. Four regexes beside them do not add
safety; they add the appearance of it, which is worse, because a project that
believes its documentation is scanned for credentials will not reach for a tool
that actually does it.

Use gitleaks. It is a pre-commit hook away and it is not this project's job.

The cost of removal, stated plainly: `--selftest` could exercise four rules on
this repository and can now exercise three, because the secret probe was
synthetic and therefore always available while the others depend on the
document offering something to corrupt. That is a real loss of signal about
whether the probe machinery works, accepted because a rule kept for the
convenience of its own test is a rule kept for the wrong reason.

## Generated sites, and the two anchor namespaces

A repository that compiles its markdown into a website has links the filesystem
cannot settle. `/reference/config/` is a route, `guide.html` is a built page,
and an extensionless target is whatever the generator decides. None of those is
a file, so none is judged when a generator is declared.

Detection is by configuration file, in the repository root or under `docs`,
`site`, `www`, `website`, `docs-website`, `documentation` or `fern`, and one
level either side of those: `*/docs` reaches a site inside a package, and
`docs/*` reaches one inside a documentation directory. Neither is speculative.
jekyll/jekyll keeps its own site under `docs/` with `docs/_config.yml` and a
root-only search reported 138 of its routes as dead; haystack declares
Docusaurus in `docs-website/`, and llama_index declares MkDocs at
`docs/api_reference/mkdocs.yml` while serving pages from
`docs/src/content/docs/` - 1,227 findings, because the search reached `*/docs`
and never `docs/*`. One generator is declared INSIDE another file rather than
in one of its own - Elixir names ExDoc as a dependency in `mix.exs` - so
existence alone is not enough there and the content decides.

**A tree that numbers its documents declares a site by that alone.** Nothing
reads an ordering prefix except something building an ordered site, and the
pages then link to each other by the stripped name. This is the signal for a
project whose site is built from ANOTHER repository, where no config exists
here to find: svelte keeps
`documentation/docs/07-misc/04-custom-elements.md`, links to it as
`custom-elements`, and svelte.dev builds it. Bounded to the same directories
as the config search and to three in one directory, both for the same reason:
unbounded, three numbered fixtures under
`packages/astro/test/fixtures/content/` declared all of `packages/` a
documentation site.

**Detection records WHICH top-level directories a generator governs, not a
yes or no for the repository.** A monorepo builds a site from `docs/` and
still keeps ordinary READMEs in `packages/`, whose relative links really are
files. Answering repository-wide silenced six real defects, among them
`packages/astro/src/core/render/README.md` linking to `../endpoint/`, a
directory that does not exist.

The two shapes are then gated differently, because they fail differently. **A
leading slash is never a path in this repository** wherever the document sits -
GitHub resolves it against github.com and a generator against the site root -
so it needs only that the repository builds a site at all. **An extensionless
target can be a real file** (`LICENSE`, a directory), so that one asks whether
THIS document is a page.

Both directions cost something, which is why both are pinned by tests. Blind,
withastro/starlight reported 235 of its own working links as dead. Universally
on, every genuinely dead link in a plain repository stops being reported. A
blanket skip for root-absolute links was tried once, on the strength of 6,360
findings across 40 repositories of which none was real, and two tests refuse it
in as many words. They are right: the shape was never the problem, detection
was.

**A bare filename resolves within one translation tree.** Where a generator
flattens its namespace, a sibling is reachable by bare name from any depth,
which is why a unique basename is accepted at all. It is counted per language
tree rather than per repository: fastapi builds a separate site per language
and keeps `newsletter.md` only in English, so a repository-wide count made
every translated page's broken link to it resolve against the English file and
hid 68 real defects. A tree is recognised by three or more language-shaped
siblings, so a lone `docs/id/` remains an "id" directory.

**The cross-reference namespace is a property of the generator, not a global
choice.** MyST, Sphinx and Antora resolve `#label` against every document at
once, so a target defined in `site-options.md` is reachable as `#site-options`
from anywhere; executablebooks/mystmd relies on that throughout, and 168 of its
findings named a label that existed in another file. MkDocs is per-page.

The temptation is to apply the project-wide union everywhere and be done with
it, and the measurement refused it: on encode/httpx, which is MkDocs, a blanket
union forgave two of its three genuinely dead anchors. Real signal traded for
quiet. So the generator decides, and a repository declaring none keeps the
page as its namespace.

Hugo gets one narrower rule. Its `_`-prefixed content directories are not
routable pages but fragments composed into other pages by a shortcode, so a
term defined in `_common/configuration/locale.md` is an anchor on whatever page
includes it. That is NOT generalised to every `_` directory, and the
measurement is again why: seven of 38 corpus repositories keep markdown under
one and they mean different things. Jekyll's `_posts` are whole pages,
Docusaurus's `__tests__` is fixtures. Treating those as ambient would forgive
real findings in four repositories to fix one.

## reStructuredText, skipped rather than tuned

`.rst` is read for claims and never for markdown syntax. The Sphinx ecosystem
is not a small corner - numpy carries 555 `.rst` against 14 `.md`, Sphinx 472
against 3, pytest 298 against 6 - so a markdown-only sweep is blind to most of
what those projects have written down.

Adding the extension alone was not enough, and the corpus said so: sweeping
those repositories produced 84 findings and almost none were real.

`dead-md-link` and `dead-md-anchor` are therefore skipped outside markdown
rather than adapted to rst. That is deliberate. `[text](url)` is markdown's
syntax; in Python it is a subscript followed by a call, and numpy writes
`np.dtype[mp.mpf](dps=100)` in a doctest. Every one of its 23 link findings was
that shape - false by construction, not by accident. There is no version of a
markdown link regex that is correct on a language which has no markdown links,
so the rule does not run rather than running badly.

The claim rules DO run, because a dead SHA in rst prose is as dead as one in
markdown. What changes is what counts as prose: rst literal blocks open with a
line ending in `::` and run until the indentation returns, `>>>` opens a
doctest, and ``` ``inline literals`` ``` are code. Left in place, numpy's
`float64('1e10000')` was read as a commit.

## Strata: a property of the document, not a setting to configure

A first sweep over 50 pinned public repositories prints **54,790 findings, of
which 4,431 are in ordinary documents**. The other 92 per cent come from four
kinds of tree - per-release snapshots (39,698), changelogs and machine-written
allowlists (4,765), vendored code (4,175) and generated references (1,721).
`bazelbuild/bazel` keeps twelve per-release copies of one documentation tree,
so one dead link written once is reported twelve times; `angular`'s
`zone.js/CHANGELOG.md` supplies 391 on its own, and `babel`'s two allowlists
343 between them, whose entries are test-case paths in an EXTERNAL suite and
were never document links at all.

**`exclude_paths` already existed and did not close it.** Three configuration
passes over the same corpus moved the headline by under one per cent - 3,468,
3,470, 3,438 - and `install.py` refuses 35 of the 50 repositories unaided, so
the configuration that would fix it is never written and the adopter never sees
the prompt. The conclusion is not that adopters are lazy: whether a tree is
vendored or a per-release snapshot is visible FROM THE REPOSITORY, so it should
not have to be configured at all.

**Labels, not exclusions**, and the distinction is the same one the denominator
is built on. Excluding hides; a stratum labels. A rule that goes quiet because
a tree was excluded is indistinguishable from a rule that broke. Both
mechanisms stay and answer different questions.

**The field is on `Located`, not on `Finding`.** The baseline fingerprint
hashes `(path, kind, detail)` off `Finding`, and a baseline that stops matching
does not fail loudly - it quietly re-raises findings a project agreed to leave
alone, and a reader learns to stop reading the output. A stratum is a property
of the PATH, and `Located` is already the type that pairs a finding with its
path, so it belongs there on the merits too. It also keeps the rules leaves: if
each rule stamped its own, `strata.py` would become a sixth shared module every
rule imports for a fact none of them uses.

**The strata are a PARTITION, so precedence is load-bearing.** A path can be
generated AND version-snapshotted - bazel's `docs/versions/8.6.0/reference/` is
both - and a fixed first-match order is the only thing that stops it being
counted twice. Vendored wins over everything, because a vendored tree is
somebody else's repository whatever shape it has inside.

**Path only, and the alternative is priced rather than guessed at.** Reading
each document for a do-not-edit marker would move 503 further findings from
`ordinary` to `generated` - 11 per cent of that stratum, across 71 documents.
It is not done because the text is not in scope where `Located` is built: the
sweep receives findings back from a worker process, not document text. The
number is recorded because a deferral without one is indistinguishable from an
oversight.

Two failures found after the first version shipped, both worth keeping:

- **The pattern must read every suffix the sweep reads.** It was anchored on
  `.md|.mdx` while `refs.py` gathers `md`, `markdown`, `mdx` and `rst`, so
  reStructuredText changelogs fell through to `ordinary`. That is the dangerous
  direction: a missed vendored tree only fails to shrink the headline, while a
  missed changelog puts a historical record INTO the number a reader acts on.
- **A changelog-shaped DIRECTORY does not make its contents historical.**
  cpython's `Misc/NEWS.d/*.rst` are per-release news fragments and stay
  `ordinary`. Widening to directory names would have been tuned on the corpus
  being measured, which the admission bar refuses, and a directory called
  `news/` is very often a project's live blog - labelling that would be a
  suppression firing wrongly, which deletes signal silently rather than
  appearing in the output for somebody to argue with.

**De-duplication is not here, and the reason is not squeamishness.** Collapsing
bazel's twelve copies needs findings grouped ACROSS documents, which would
change what a finding IS and move exit codes with it. Measured at analysis time
instead: the stripped-path key takes 4,429 ordinary findings to 3,466 and a
content hash takes it to 3,451, so content identity is worth 15 findings on top
of the path pattern rather than the further 1.3x it was expected to be. Content
keying ALONE is worse over all findings - 13,093 distinct against 11,860 -
because a per-release snapshot carries the version string and so is
near-identical rather than byte-identical. Content identity measures
DUPLICATION and the path pattern measures PER-RELEASE SNAPSHOTTING; they are
different questions, and neither subsumes the other.

## The baseline forgives what it recorded, and no more

The fingerprint excludes the line number so that reflowing a paragraph does not
un-suppress everything. The price was that one recorded finding forgave the
same claim pasted anywhere, forever - listed in `smoke.py` as a by-design
consequence for several releases.

Entries now carry an occurrence count. Suppression covers that many; the
surplus is reported. The line number stays out of the fingerprint, so
churn-immunity is unchanged, and an entry written before counts existed
forgives one - the shape it had when it was written.

Raising the count by re-recording remains possible. That is acceptable: it is
an explicit act and it shows up in the diff, which is what a baseline is for.

## A schemeless URL is not a path, and the fix is a suppression

`EXTERNAL` - in `text.py` then, in `links.py` since the link scanner left on
2026-09-13 - decided "not ours to check" for every link rule, and it
recognised a URI scheme or a protocol-relative `//` and nothing else. So
`[docs](www.skyvern.com/docs)` and `[author](github.com/josh-l-wang)` were
joined to the document's directory and reported as dead links.

FOUND BY TWO CORPORA AT ONCE, which is what made it a class rather than a
curiosity: `Skyvern-AI/skyvern` on the 2026-09-05 held-out half, and
`qmk_firmware` 18, `sonic-pi` 2, `RetroArch` 1 and `lean4` 1 on the niche
corpus built the same day. Five repositories, two corpora, neither of which any
rule was designed on - past the "all the true positives are in one repository"
bar that this document uses to refuse candidates.

THE HAZARD IS NOT THE PATTERN, IT IS THE SUPPRESSION. Widening `EXTERNAL`
silences whatever it matches, and a suppression firing wrongly deletes a real
finding where a false positive at least stays in the output for somebody to
argue with. A great many TLDs are also file extensions - `.md` is Moldova,
`.rs` Serbia, `.py` Paraguay, `.sh` Saint Helena - so the obvious `host.tld`
rule would read every markdown link as a URL and silence the link rules
everywhere while every run still looked clean.

So the arm was bounded by measurement before it was written. Across 157 cloned
repositories and 220,990 internal link targets it matches 41 distinct targets,
every one of them a URL, and NOT ONE target that resolves to a file which
exists.

THE TLD LIST IS TWO A PRIORI RULES AND ONE MEASURED EXCLUSION, which is what
keeps it from being tuned on the corpus it was measured against. Admitted: the
generic TLDs a documentation link uses, and the ISO-3166 two-letter codes.
Struck out: every code really used as a file extension in those repositories -
`.py` at 81,121 files, `.rs` 61,737, `.md` 53,611, `.cc` 16,058, `.sh` 4,795,
`.mk` 2,326, `.tf` 1,758, `.pl`, `.in`, `.pm`, `.ai` and the rest, plus generic
`.info` (110), `.page` (83), `.tools` (38) and `.xyz` (22).

THE FIRST VERSION SHIPPED WITH ONLY THE GENERIC HALF, and an audit of it found
three survivors: `anomalykb.co`, `imaginaerraum.de` and `fablab-bayreuth.de`.
A generic-only list is a US-centric list, measured on corpora that are
themselves US-centric, so three is a floor rather than the rate. Adding the
country codes was re-measured the same way and lost nothing.

Two arms, because they fail differently. `www.` is unambiguous: no file is
named `www.a.b`. The hostname arm needs at least one `label.` before a listed
TLD and then a path, query, fragment or end of string, which is what keeps
`README.md` and `script.sh` paths. Requiring a path would have been safer still
and was rejected on measurement rather than taste: it drops the fix from 55
targets to 33, because `webbench.ai`, `hanboards.com` and `stratakb.com` carry
no path at all.

## A declared stratum, measured and refused

The review's item 4.6: ask `git check-attr` for `linguist-vendored`,
`linguist-generated` and `linguist-documentation` and let a project's own
declaration place a document in a stratum, where `strata.classify` today
infers one from the path. The review measured it thin - 51 of 2,519
documents across 10 repositories, 2%, in 2 of them - and set its bar: under
1% and concentrated in one repository is a footnote.

Counted on 2026-09-15 over the 152 visible clones (`m8_attributes.py`, two
spawns per clone through `environment()`, the tranche-7 identity sweep as
the findings): 98 track a `.gitattributes`; 12,697 of 87,191 swept
documents carry one of the attributes, in 9 repositories - and 12,326 of
those carry only `linguist-documentation`, which declares that a document
IS documentation and maps to no stratum. Declared vendored or generated:
340 documents, 304 of them `ordinary` today, 194 of them docusaurus's
`__tests__/__fixtures__` trees declared generated and 104 tabby's vendored
docs. Findings that would move: **17 of 65,360 leave `ordinary`** - 0.026%,
in three repositories, docusaurus 12, tabby 3, lean4 2 - and 5 would enter
it, all bazel's, which declares `linguist-generated=false` on paths the
regex calls generated or snapshotted. Refused on the review's own bar. The
`extant-stratum` attribute it called the better half has zero writers by
construction, and the README's rule about configuration nobody writes
applies: it ships with a skill that writes it, or not at all. Output under
`D:/repo/out-attributes/`.

## The bare commit-link text: whose commit it is, and a number re-derived

The first of the two shapes Phase 51 recorded and did not build, built as
Phase 52 on 2026-09-22 - twice, because the gate on the first build put a
question the design had not asked. The shape: a SHA as the unbackticked
link text of a commit URL, `[<sha>](https://github.com/<owner>/<repo>/commit/...)`,
which is how release-please, standard-version and the changelogs they
generate write every entry. `_URL` has always skipped the hex inside the
parentheses; nothing skipped the copy before `](`, so a token the URL
beside it attributes to another repository was checked against this one.
The backticked spelling of exactly this had been suppressed since the
held-out narrowings, deliberately without comparing owners, and the first
design was the same argument in the bare spelling: one more pattern
beside `_LINKED_SHA` with the same URL tail, its whole-match span the
sixth line of the bare scanner's skip list.

**The count did not reproduce, and the reason is that it was never
persisted.** The Phase 51 record said 1,425 of the 11,191 dead-SHA
findings in the recorded sweep, naming angular, moby and node; no
apparatus script held that count - it was a pass over the sweep outputs
that was not written down. A persisted one (`m15_linktext.py` beside the
other `m14_*` scripts in the extant-hardening checkout) re-derives it by
parsing both dead-SHA kinds back out of every sweep output, reading each
finding's line from its clone, and scanning that line twice with the
tool's own scanner, with and without the new span. Population first: the
after-side of the Phase 51 sweep holds 11,142 dead-SHA occurrences, the
record's 11,191 less exactly the 49 `ed25519` sites that phase removed,
so the two passes read the same documents. Then the count: the pattern
that mirrors `_LINKED_SHA` - any host, `commit`, `commits`, `blob`,
`tree`, `pull` or `compare` - covers 2,866 findings across 15 of the 152
outputs, 2,107 once a repository that sits in two tiers is counted once:
moby's vendored google-cloud-go changelogs 754, node's node-gyp and
corepack changelogs 491, angular's absorbed zone.js changelog 424, and
kubernetes 414, absent from the record entirely - its changelogs pin
every dependency as a short SHA linking to that repository's `/tree/`
page. Restricting the pass to the record's own literal spelling, host
`github.com` and tail `/commit/`, gives moby's 358 exactly and node's 286
against a recorded 290, so the unpersisted pass took its own words
literally; under that reading the total over all 152 outputs is 1,459,
within 34 of the recorded 1,425, and the residual cannot be reconstructed
because nothing was kept.

**The gate on the first build said 29, not 15, and the miss was the
prediction's.** The identity sweep compares outputs byte for byte, and an
output carries the `examined:` denominators as well as the findings. A
bare SHA that is commit-link text and RESOLVES was examined and reported
nothing; the unconditional skip stopped examining it, so the `dead-sha`
denominator moved in every clone that holds one, dead or alive - and the
measurement had counted dead findings only. In the 15 predicted outputs
the findings removed matched the prediction exactly, output by output,
nothing was added, and nothing else moved but the denominators and the
summary lines that follow them; the other 14 outputs moved in the
`examined:` line alone. The script gained a second pass that counts every
site through the tool's own `prose()`, and it predicted 29 outputs and
18,285 sites, each output's count equal to its observed denominator drop.
That pass is what put the question: 15,419 of the 18,285 sites resolved
today - angular's changelogs 7,069 of them, lobe-chat 2,361, openfoodfacts
2,159, vitepress 1,173, axe-core 1,161, sile 862 - and a link text that
resolves in the clone is, by construction, a commit this repository has.
Live, so no finding moved; but a rewrite that kills one of them is
reported today and would not have been with the skip in, which is the
shape of the casualties below at a scale of thousands rather than tens.
The backticked skip had accepted the same exposure in 2026-08 without
measuring it, because that spelling is rare; this one is the common one.

**The decision: the URL's owner is compared with `origin`, in both
spellings.** Split the way that comparison splits them, the 18,285 sites
are 15,257 own and alive, 31 own and dead, 162 foreign and alive (a fork
or a monorepo carrying the other repository's history), 2,835 foreign and
dead, and none in a clone without an origin. So the comparison removes
exactly the 2,835 foreign findings and 162 live foreign sites, and keeps
15,288 own sites examined with their 31 casualties reported: angular 25,
helix 3, axe-core 2, lobe-chat 1 - 27 of them with the URL's full SHA
dead too, and 4 in angular's old changelog whose link text is the LAST
ten characters of a SHA that resolves, a token no abbreviation could ever
satisfy, reported today and still reported, which is the status quo
rather than a verdict this change makes. The reasoning is the tool's own
guarantee, that a rule asks only what git in this repository can settle
about this repository: the URL says which repository the commit belongs
to, `origin` says which repository this is, and when the two agree the
claim is in scope and checkable - the changelog entry whose commit a
squash or a force-push takes away is the one rotting citation the tool
exists to report, in the document type that cites commits more than any
other. When they disagree the claim is about another object store, out of
scope, and reporting it is the false positive by construction that
vendored changelogs and dependency pins produced by the thousand. The
first design's reason for not comparing - "a document does not reliably
state which repository it is in" - was true and beside the point: the
document does not, the repository does, and `dead-pinned-ref` has told a
pin aimed at us from one aimed elsewhere by exactly this comparison since
it was written. Two rules, one notion of "ours", one function.

What the comparison costs, named: a repository renamed on GitHub keeps
old links under the old name, which read as foreign and are skipped -
lost coverage, never a false positive; a clone with no origin cannot
settle "ours" and skips, the caution the unconditional version took, on 0
sites in the corpus; a fork skips upstream's links, which are upstream's
claims. The reduction is `owner/name`, so `www.github.com`,
`api.github.com/repos/...`, an SSH origin and a GitLab mirror all compare
as one repository, and GitLab's `/-/commit/` spelling is allowed for.

**How.** `own_remote` and `normalise_remote` moved from the pinned-ref
rule to `refs.py`, public because a sibling reads them now. The two
scanners take the origin as a zero-argument callable and ask it only on a
line holding one of the two shapes, never before - the same economy
`_pinned_refs` keeps by not asking on a document without a `rev:` line -
so a document with no linked commit costs no question, the spawn budget's
fixture count does not move, and a checkout whose config fast path
answers pays a 0.19 ms file read once per run. Each memo's key carries
the origin the scan compared with, or a sentinel when none was needed and
any origin hits, the discipline `_MERGE_CLAIMS` keeps for its pattern and
trunk; `_document_sha_tokens`, the batch, takes the same callable, so
what is resolved is what is examined. One helper, `_linked_spans`, serves
both spellings: the backticked skip is owner-aware now as well, or the
verdict on one claim would depend on whether the author typed backticks.

**Tests.** Ten pairs in section 3 of `tests/test_held_out_narrowings.py`,
each arm of the comparison with its control: a foreign link skipped with
`examined` at zero, so it is silent because unexamined rather than
examined and found alive; the same link naming `origin` reported, in both
spellings; an SSH origin against a `www.` URL compared as one repository;
a link with no origin to compare against skipped; link text on a page
that names no commit still reported; a bare range as link text skipped
when foreign and reported at both ends when own; the same range unlinked
reported at both ends. The mirror copy of the bare scanner compares at
two origins, None and the `o/r` the generated corpus links, with a
template for each arm - because the plan had promised the agreement test
would go red on the sixth exclusion and it was not going to: the corpus
held the backticked link template only, and this repository's documents
hold no bare commit link. Three mutation anchors: the foreign skip
deleted, the own arm skipped like a foreign one (the first design,
sneaking back), and the backticked skip forgetting whose commit it is;
four retargeted by path with the moved helpers.

**The corpus said the own arm is not a corner.** The same pass, run over
the backticked spelling that had been skipped unconditionally since
2026-08-08, found 81,166 such sites in the 152 clones: 79,978 own and
alive, 1,188 own and DEAD, 199 foreign and alive, 555 foreign and dead.
So the unconditional skip had been hiding 1,188 real rotting citations in
the corpus all along, and node alone holds 1,165 of them - its versioned
changelogs cite ten-character abbreviations, one per entry, of commits
from the io.js era that the repository's own object store no longer
has - and each is written as link text of a link to node's own commit
page, so the unconditional skip silenced every one. astro holds 23 of
the rest, in its packages' changelogs. Neither is a repository with a rewrite in its recent past;
both are what a decade of changelogs looks like. The comparison turns
them back on, and the identity gate's prediction is therefore 24 outputs
and 84,163 sites changing examined status - 2,997 foreign sites of both
spellings switched off, 81,166 own ones switched on - rather than the
2,835-in-15 the first design predicted.

**The gate, as run.** Nine tests red before the code moved - the four own
arms of the comparison in both spellings, the SSH-against-`www` reduction,
the no-origin arm, and the three the first design had written - plus the
mirror's two-origin comparison, which is red until the copy carries the
same owner test. Three anchors written and four retargeted by path with
the moved helpers. The corpus identity sweep against a stated prediction
of 24 of 152 differing: 24 differ, the predicted set exactly, none missing
and none unpredicted. 2,835 findings left, every one a bare SHA linked to
another repository's commit; 1,188 appeared, every one a backticked SHA
linked to this repository's own - node 1,165 and astro 23 - and no other
kind moved anywhere. The `examined:` denominators moved by the net of the
two directions, output by output: node's 62,479 sites changing status show
as a net of +61,497, which is 61,988 switched on less the 491 switched
off, and angular keeps 25 of its 424 because those 25 name angular's own
commits. The pre-push chain ran against a working-tree extract, and the
rebase-journal flake that had reddened CI since PR #15 was diagnosed and
fixed on the way: the fixture cited `cited[:7]`, and a seven-character
prefix that is all digits is no candidate at all, so the rule correctly
found nothing and the test read `[]` where `dead-sha` was due - 3.8 per
cent of runs, one in forty locally and about one red leg in three across
ten CI legs. `_abbrev`, written for exactly this in another file on
2026-09-13, moved to `tests/conftest.py`; 60 of 60 runs green after it,
against 1 failure in 40 before.

**Did it silence anything useful? Audited rather than asserted**
(`m15_audit.py` beside the measurement script; output beside it in the
logs). Every one of the 2,835 findings the comparison removed is read back
out of the two sweeps with its document's stratum and with the URL head
that decided it. Where they sit: 1,933 in vendored trees, 880 in
historical records, and 22 in ordinary documents - the stratum that
gates. All 22 were read by hand, and each cites another project by name in
its own prose: aider's post about a litellm commit (3, in two tiers of the
same clone), a CVE archive's "fix commit" in three upstream projects,
PX4's NuttX upgrade in three translations of one page, tensorflow's
advisory about tflite-micro, uv's vendored copy of pypa/packaging, and
helix's note that its lsp-types crate is a fork of gluon-lang's. There is
no argument for checking any of them against the repository that cites
them.

How foreign was established matters more than where the findings sat, and
it is the question the audit exists to answer: the skip could silence a
real claim only by treating "cannot tell" as foreign. In all 2,835 the
URL head parsed to a real `owner/name`; none was relative, none empty,
none in a clone without an origin. Across the whole corpus there is not
one linked-commit site whose head names no repository, and every one of
the 98,109 sites the comparison calls OURS is on the same host as the
origin it was compared with, so ignoring the host mis-attributed nothing.
891 of the removed sit under the same owner as the origin and a different
repository - `angular/angular` citing `angular/zone.js`,
`tensorflow/tensorflow` citing `tensorflow/tflite-micro` - which is a
sibling project rather than a rename; the shape a rename or fork would
take, the same repository NAME under another owner, occurs zero times. No
document's `dead-sha` denominator fell from nonzero to zero, so the rule
goes silent in no document anywhere, and three clones gained a denominator
they did not have.

The residual risks, stated because the corpus cannot close them: a
repository renamed on its host keeps old links under the old name, which
read as foreign and are skipped - lost coverage, never a false positive,
and indistinguishable from the 891 sibling-project cases above; a clone
with no origin cannot settle whose commit a link names, so both spellings
skip there, which is a loss of the bare spelling's old coverage in that
one case - the corpus holds no such clone, and the one origin-less
repository this project knows of holds 29 documents and not a single
linked-commit site, so the arm is pinned by a test rather than by a
population. And the four angular sites whose link text is the last ten
characters of a resolving SHA are still reported, as they were before:
this change neither makes nor removes them.

**Not done here, and the next measurement.** `_URL`'s hex skip is still
unconditional: `[the fix](https://github.com/<us>/commit/<sha>)`, a commit
URL of this repository with words as its link text, is not examined,
because the hex sits inside a URL. The same argument applies and the
same comparison would settle it; it is a wider verdict change - every own
commit URL in every document becomes a site - and gets its own count
before it is a change.
