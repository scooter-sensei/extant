"""The axes `fuzz.py` varies BESIDES the claims a document makes - Stage 6.

WHY THIS IS NOT A SECOND fuzz_shapes.py

A FEATURE writes a claim and NAMES THE RULE it wants to make examine something.
All thirteen in `fuzz_shapes.py` are that shape, and the reach ledger checks
each one against what the run actually examined.

An AXIS names no rule. It changes the CONDITIONS every rule reads under - the
encoding the document arrives in, whether a generator compiles the tree into
routes, whether the repository remembers a history rewrite, whether a rule can
run at all. Its target is not a rule; it is the whole rule set.

Putting these in `Feature` was the first attempt and it broke that file's one
contract. `rules` is checked against the run, so a feature claiming a rule it
does not reach is a harness fault - and an encoding axis truthfully claims all
thirteen while reaching none of them by itself. It would have had to declare
`rules=()`, which turns the check off for that entry, and a catalogue entry
exempt from the catalogue's own check is the reassuring zero this project
keeps removing.

WHAT AN AXIS OWES: EVIDENCE, NOT APPLICATION

The measurable thing about a feature is that some rule examined something. The
measurable thing about an axis had to be chosen, and the obvious answer was
wrong: "the file was written" measures that this harness can write a file.

Every axis here answers a sharper question - did the RUN behave as though the
axis were present - and answers it in three states rather than two:

  True   the run shows the axis took effect
  False  the axis was applied and the run does not show it. INTERESTING.
  None   this repository offered no way to tell. Not a failure.

The third state is the whole design. Two states force the undecidable case to
be called something, and either choice is wrong somewhere: counted as
confirmed it hides an axis that has stopped working, counted as failed it
reddens every run over a repository that merely drew no false claims. That is
the same distinction `Recipe.skipped` draws against `Recipe.broken`, and the
same one the "could not build" column exists for.

WHY THE STAGE 6 EXIT CRITERION HAD TO CHANGE

The design document asks each new axis to raise "the reach ledger, the refusal
count, or the count of shapes the platform declined to build". That was written
when the ledger stood at 5 of 13. It is now 13 of 13 and cannot rise, and the
other two are costs rather than achievements - a corpus that mostly refuses is
a corpus mostly testing argument parsing, which that document says itself.

So the criterion is restated, in the form the reach ledger already uses one
level down: an axis earns its place by being DRAWN AND CONFIRMED somewhere in
the corpus. An axis drawn and never once confirmed has stopped working, and
says so, exactly as a feature that fires no rule does.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

__all__ = ["Axis", "AXES", "AxisBuild", "Effect", "axis_by_name",
           "axes_for", "draw_axes", "commit_map_path", "opens_a_fence",
           "PHASES"]


def opens_a_fence(lines) -> bool:
    """Does this text leave a markdown code fence OPEN at its end?

    Asked of the harness's OWN text, and only ever of that. Every fence this
    generator writes is a whole line whose first non-space characters are three
    backticks - the unclosed-fence noise shape, and the balanced ```yaml block
    one feature writes - so counting those lines answers it exactly. This is
    not a markdown parser and must not be used as one.

    WHY NOT IMPORT `strip_code` FROM THE PAYLOAD. The harness could, and
    `perf.py` and `stress.py` already import from `extant`. It would be
    circular in the one direction that matters: a broken `strip_code` would
    then excuse the very axis that a broken `strip_code` had silenced. The
    question here is what the HARNESS wrote, which is a different question from
    what the tool makes of it, and the tool's answer is what the run is for.

    AND GETTING IT WRONG FAILS LOUDLY, which is why a scan this crude is safe.
    It decides WHERE a claim goes, never whether a verdict is softened - so a
    scan that said "closed" over an open fence would put the claim somewhere
    invisible and `_raised` would report the contradiction it always did. No
    reading of this turns a red run green by accident.
    """
    open_fence = False
    for chunk in lines:
        for line in str(chunk).splitlines():
            if line.lstrip().startswith("```"):
                open_fence = not open_fence
    return open_fence


# Where in `build_from_plan` an axis gets its turn. Ordered, and the order is
# a contract: `config` has to land before the document is written because the
# document's config gates it, `document` after the LAST rewrite of the primary
# document or the post-features would overwrite the encoding, and `final`
# after the last `git add -A` for the same reason `Feature.finalize` exists.
#
# THERE WAS A `tree` PHASE AND IT WAS A TRAP. It ran before the first commit,
# as `config` does, so anything it wrote was tracked either way - but only the
# CONFIG phase's return value is read, so an axis contributing document text
# from `tree` had it silently discarded. Two axes did exactly that before the
# gap audit added the guard that now refuses it. A phase that can only be a
# worse `config` is a phase to delete, not to document.
PHASES = ("config", "document", "final")


@dataclass
class AxisBuild:
    """What an axis is handed, and what it may ask about the repository."""

    repo: Path
    rng: random.Random
    sh: Callable[..., object]
    trunk: str
    state: str
    doc: str
    # Feature names this repository drew. The raising axis reads it, and the
    # reason is under `_raise_a_rule`: silencing a rule some feature is aiming
    # at would make the reach ledger report that feature as broken.
    features: frozenset
    facts: dict
    # Whether the text that will precede the NEWEST ENTRY leaves a code fence
    # open. `strip_code` blanks a fence to the END OF THE DOCUMENT, so when
    # this is set every entry line is invisible to every rule - measured
    # directly on one document, `unknown-branch` goes from 1 to 0 with a single
    # unclosed fence above it while a preamble claim placed ahead of the fence
    # survives.
    #
    # Set by `build_from_plan` after the noise is drawn and before the config
    # axes run, which is the only window in which both are known. An axis that
    # wants to put a claim in the entry has to read this or be blamed for a
    # claim the harness itself blanked.
    entry_is_blanked: bool = False

    def git(self, *args: str):
        return self.sh(self.repo, "git", *args)

    def head(self) -> str:
        done = self.git("rev-parse", "HEAD")
        return (getattr(done, "stdout", "") or "").strip()


@dataclass
class Effect:
    """What an axis contributes, beyond whatever it wrote to disk itself."""

    config: tuple = ()      # bare TOML keys, merged the way features' are
    prose: tuple = ()       # lines for the document preamble
    # Lines for the NEWEST phase entry, which is a DIFFERENT POPULATION from
    # the preamble and not a stylistic choice. `stale-live-claim` and
    # `unknown-branch` read only that entry, so a branch claim written into the
    # preamble is invisible to them - which is exactly how the raising axis
    # aimed at `branch_token` silently stopped raising anything.
    entry: tuple = ()
    note: str = ""          # what to print beside the axis in the recipe


# --- encodings and line endings ---------------------------------------

# The four spellings, and what each is for. `text.py` carries two contracts
# that broke on exactly this axis - `strip_code` blanking with spaces so every
# offset survives, and `line_breaks` counting a break in EVERY spelling - and
# until now nothing built a document that natively had one.
#
# The CRLF ORACLE IS NOT THIS. It rewrites a document mid-run and requires the
# answer not to change, which tests the transform. This builds the repository
# that way in the first place, commits it, and lets every mode meet it - which
# is the shape a Windows checkout actually has.
#
# WEIGHTED, because UTF-16 is the one that ENDS THE RUN. extant refuses an
# undecodable status document by name and exits, which is correct - and a
# refusal costs a whole repository and answers almost nothing beyond that one
# message. Drawn uniformly it took a quarter of every encoding draw; the three
# spellings extant must actually READ are where the contracts live.
_ENCODINGS = ("crlf", "bom", "cr-only", "utf16")
_ENCODING_WEIGHTS = (3, 3, 3, 1)


def _encode(build: AxisBuild) -> Optional[Effect]:
    """Rewrite the primary document into one of four byte shapes."""
    path = build.repo / build.doc
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    # Normalise to LF first. Python's text mode already writes CRLF on Windows,
    # so a transform that assumed LF input produced a mixture there - and a
    # mixture is a fifth shape nobody chose, which is how a deliberate axis
    # turns into an accident that varies by platform.
    body = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    spelling = build.rng.choices(_ENCODINGS, weights=_ENCODING_WEIGHTS)[0]
    if spelling == "crlf":
        out = body.replace(b"\n", b"\r\n")
    elif spelling == "bom":
        out = b"\xef\xbb\xbf" + body
    elif spelling == "cr-only":
        out = body.replace(b"\n", b"\r")
    else:
        try:
            out = body.decode("utf-8").encode("utf-16")
        except UnicodeError:
            return None
    try:
        path.write_bytes(out)
    except OSError:
        return None
    build.facts["encoding"] = spelling
    return Effect(note=f"primary document written as {spelling}")


def _encoded(repo: Path, out: str, facts: dict) -> Optional[bool]:
    """Did the run behave as though it met the encoding?

    Three spellings must still be READ: CRLF, a BOM and a bare CR are all
    ordinary text, and a tool that stopped examining a document because of one
    would be broken. Confirmed by a non-zero denominator, which says the rules
    reached the document rather than that a file exists on disk.

    CR-ONLY IS HELD TO MORE, because it is the spelling with a defect on
    record. `line_breaks` counts a break in every spelling precisely because a
    bare `
` contains no newline, so a rule counting newlines reports EVERY
    claim in such a document at line 1. If this document produced findings at
    all, at least one must sit past line 1 - and that is the one thing here
    that can return False rather than merely failing to return True.

    The gap audit is why this exists. Asked whether each axis could ever report
    a contradiction, `encoding` could not: it returned True or None and nothing
    else, so its ledger row said "was exercised" while reading like "held".

    UTF-16 is the one that must NOT be required to parse. Measured: extant
    refuses it by name - "not valid UTF-8 (invalid start byte at byte 0)" - at
    exit 1, which is a correct and useful answer, so demanding a denominator
    here would fault the tool for being right.
    """
    spelling = facts.get("encoding")
    if spelling is None:
        return None
    if spelling == "utf16":
        # Either answer is legitimate; what is not legitimate is silence.
        # A named refusal or a denominator both count, and nothing else does.
        if re.search(r"not valid UTF-8", out):
            return True
        return True if _has_denominator(out) else None
    if not _has_denominator(out):
        return None
    if spelling == "cr-only":
        lines = re.findall(r"^(?:.*: )?line (\d+): \[", out, re.M)
        if not lines:
            # Nothing was reported, so nothing can be said about where.
            return None
        return any(int(n) > 1 for n in lines)
    return True


def _has_denominator(out: str) -> bool:
    for match in re.finditer(r"(?:examined|checked [^:]+): (.+)", out):
        for part in match.group(1).split(","):
            bits = part.strip().rsplit(" ", 1)
            if len(bits) == 2 and bits[1].isdigit() and int(bits[1]) > 0:
                return True
    return False


# --- one config key, three claimants ----------------------------------

# THREE THINGS WANT THIS KEY AND TOML ALLOWS IT ONCE. The `release-tag`
# FEATURE emits it, `raising-rule` emits it when it picks the release site,
# and `annotated-tag` emits it to make its own evidence answerable. A second
# copy is a duplicate TOML key, which is a parse error, which is a REFUSAL -
# and a refusal costs the whole repository and answers nothing beyond the
# message.
#
# WHY `annotated-tag` NEEDS IT AT ALL is a measurement, not a preference. The
# half of `dead-release-tag` that reports a claimed release with NO TAG is off
# by default, and with it off a claim whose tag does not resolve is dropped
# from the DENOMINATOR rather than reported. Measured on one document, `v1.0`
# claimed and no such tag present:
#
#   key off   dead-release-tag 0    no finding
#   key on    dead-release-tag 1    [dead-release-tag] claims release `v1.0`
#
# So with the key off the evidence check reads a broken peeling path as
# "examined nothing, no way to tell" and reports None forever. It could never
# say no - which is the state the gap audit found `encoding` and
# `generated-site` in, arriving in a third axis by a different route.
#
# ROUTED THROUGH ONE FUNCTION rather than a guard at each emitter, because
# three guards are three places to get one condition right and they only have
# to disagree once. Order-independent by construction: the FEATURE set is
# known before any axis runs, and between the two axes the first to ask claims
# the fact.
_RELEASE_GATE = "release_claims_name_our_tags = true"


def _release_gate(build: AxisBuild) -> tuple:
    """The release key, emitted at most once per repository."""
    if "release-tag" in build.features:
        # The feature emits it itself. A copy here is the duplicate.
        return ()
    if build.facts.get("release_gate"):
        return ()
    build.facts["release_gate"] = True
    return (_RELEASE_GATE,)


# --- a rule that raises -----------------------------------------------

# Config keys whose pattern a rule reads with `.group(1)`, and the rule that
# reads it. A pattern with NO capture group therefore raises IndexError inside
# the rule - which is what `ERRORED` has been asserted against and never once
# observed, because nothing the generator built made any rule raise.
#
# THE DESIGN DOCUMENT PROPOSED THE WRONG MECHANISM. It suggested "a config
# naming a consistency pattern that cannot compile". Measured: that is caught
# by `_compile_consistency` at load and the run exits 2 with "cannot read
# configuration" - a REFUSAL, in which no rule runs at all, so it produces the
# opposite of what the axis needs. A pattern that compiles and then misbehaves
# inside the rule is what reaches this.
#
# Each of these is also a mistake a real project makes: a hand-written pattern
# whose author forgot that the rule wants the captured value, not the match.
# THE FOURTH ELEMENT IS THE WHOLE REASON THIS AXIS WORKS, and leaving it out
# was a self-defeating bug the axis ledger caught on its first real run.
#
# `.group(1)` is only reached on a MATCH, so a pattern with no capture group
# raises only if something in the document matches it. The site is chosen from
# rules whose FEATURE was not drawn - which is exactly the condition
# guaranteeing the document contains no claim of that shape. So the axis
# silenced a rule that had nothing to read, no rule ever raised, and the
# ledger reported `raising-rule: applied, and the run contradicts it`.
#
# Each site therefore carries the claim it needs, and writes it itself.
# (config key, rule, a pattern with no capture group, the claim, where it goes)
#
# WHERE IT GOES IS NOT COSMETIC, and getting it wrong cost this axis a second
# silent failure after the first was fixed. `branch_token` feeds the two rules
# that read ONLY THE NEWEST PHASE ENTRY, so a branch claim written into the
# preamble is invisible to them - the pattern matched nothing, no rule raised,
# and the ledger reported `raising-rule: applied, and the run contradicts it`
# for the second time from a different cause. `release_tag` reads the whole
# document, so its claim can live in the preamble.
_RAISE_SITES = (
    ("release_tag", "dead-release-tag",
     '(?:released|shipped|tagged)\\s+(?:in|as|at)\\s+`?v?\\d+\\.\\d+',
     "The parser shipped in `v2.7` on this line.", "prose"),
    ("branch_token", "unknown-branch", '`claude/[a-z-]+`',
     "Handled on `claude/axis-raise` before landing.", "entry"),
)

# Features whose rules each raise site would silence. Kept beside the sites
# rather than derived, because `branch_token` feeds TWO rules and a derivation
# from the site's own `kind` would miss the second.
_SILENCES = {
    "release_tag": ("release-tag",),
    "branch_token": ("branch-token", "live-claim"),
}


def _raise_a_rule(build: AxisBuild) -> Optional[Effect]:
    """A config pattern that compiles and then makes its rule raise.

    IT MUST NOT SILENCE A RULE SOME FEATURE IS AIMING AT, and that constraint
    is not politeness. A rule that raises reports its denominator as 0 - which
    `registry.count_examined` documents and is right to do - so aiming this at
    a rule whose feature was drawn makes the reach ledger report that feature
    as having stopped firing. The harness would then fail with a HARNESS FAULT
    naming a feature that is working perfectly.

    So the site is chosen from those whose features this repository did NOT
    draw. When every candidate is spoken for, the axis declines rather than
    picking one anyway, which is the "could not build" answer and not a pass.

    A SITE IS ALSO UNUSABLE WHEN THE HARNESS IS ABOUT TO BLANK ITS CLAIM, and
    that is the second reason, added after this axis was caught reporting a
    contradiction it had not earned. One noise shape is an UNCLOSED CODE FENCE
    in the preamble, and `strip_code` blanks a fence to the end of the
    document - so an ENTRY claim written under one is correctly invisible, the
    pattern matches nothing, no rule raises, and `_raised` reports
    `raising-rule: applied, and the run contradicts it` over the tool behaving
    exactly as documented. Reproduced deterministically at seed 2002 repository
    034: the fence opens at line 12 and the claim sits inside it at line 18.

    THE FIX IS NOT TO SOFTEN `_raised`, and the gap audit already refused that:
    treating "the rule examined nothing" as no-opportunity would leave the axis
    unable to report the very failure it had twice had, since a misplaced claim
    also examines nothing. The claim is not misplaced here - it is in the only
    population the branch rules read - so the honest answer is that this
    repository cannot carry this site at all, which is the "could not build"
    column and not a verdict.
    """
    free = [site for site in _RAISE_SITES
            if not (set(_SILENCES[site[0]]) & build.features)
            and not (site[4] == "entry" and build.entry_is_blanked)]
    if not free:
        return None
    key, kind, pattern, claim, where = build.rng.choice(free)
    build.facts["raised_rule"] = kind
    # Through `_release_gate` rather than emitted here, because `annotated-tag`
    # now wants the same key and whichever of the two runs second would
    # otherwise write the duplicate. The site guard above keeps the FEATURE off
    # this path; it says nothing about the other axis.
    extra = _release_gate(build) if key == "release_tag" else ()
    # A TOML *LITERAL* STRING, single-quoted, which performs no escape
    # processing. A basic string would process `\s` and `\d` as escapes, and
    # they are not valid ones, so the whole config fails to parse - which is a
    # REFUSAL, and this axis then measured argument handling instead of a
    # raising rule. extant's own error says so when it happens, in as many
    # words; `_consistency` in fuzz_shapes.py already quotes its patterns this
    # way for the same reason.
    return Effect(config=(f"{key} = '{pattern}'",) + extra,
                  prose=(claim,) if where == "prose" else (),
                  entry=(claim,) if where == "entry" else (),
                  note=f"{key} pattern with no capture group, so {kind} raises")


def _raised(repo: Path, out: str, facts: dict) -> Optional[bool]:
    """`ERRORED:` naming the rule this axis aimed at.

    Naming it, rather than merely finding the word, because any rule raising
    for any reason would otherwise confirm this axis - including one raising
    because of a defect the axis had nothing to do with.
    """
    kind = facts.get("raised_rule")
    if kind is None:
        return None
    if re.search(r"ERRORED: " + re.escape(kind) + r" raised", out):
        return True
    # A repository where NO rule examined anything - one git tracks no
    # markdown in, or one whose run declined - cannot show this either way.
    # The evidence is always read from the sweep probe, so the mode this
    # repository drew is not the reason; an empty answer is. Saying so is not
    # the same as the axis having failed.
    return False if _has_denominator(out) else None


# --- a generated site -------------------------------------------------

# One marker per mechanism `sites.py` recognises, so the route-not-path branch
# is reached by each of the three routes it can be reached by: a config
# filename, a config filename in a SUBDIRECTORY, and a marker found by reading
# a file whose name says nothing.
#
# `sites.py` decides whether the link and anchor rules judge at all, and no
# repository this harness has ever built declared itself a site - so that whole
# branch has been dead in the fuzzer for its entire life.
# The two link spellings a generator resolves and the filesystem cannot.
# Distinctive on purpose, so the evidence check below can name them rather than
# matching whatever link some other feature happened to write.
_ROUTES = ("/axis-route/configuration/", "axis-guide/setup")

# ONLY THE ROOT-RELATIVE ONE IS ASSERTED, and the reason is a measurement
# rather than caution. Both spellings are written, because both are what a
# generator resolves and the filesystem cannot - but they are not forgiven
# alike. Measured across all six markers: `/axis-route/configuration/` is
# forgiven by every one of them, while `axis-guide/setup` is forgiven by the
# three declared at the ROOT and reported by the three declared in `docs/`.
#
# That difference is extant's judgement about what a subdirectory site's tree
# contains, and it is not this axis's business to pin it. An evidence check
# that demanded both would have called the tool wrong on half its own marker
# list - which is what the first version did, contradicting itself on 4 of 12
# repositories before this was measured.
_FORGIVEN_ROUTE = _ROUTES[0]

_SITE_MARKERS = (
    ("mkdocs.yml", "site_name: Widget\n"),
    ("docs/_config.yml", "title: Widget\n"),
    ("hugo.toml", "baseURL = 'https://example.invalid/'\n"),
    ("myst.yml", "version: 1\nproject:\n  title: Widget\n"),
    ("docs/docs.json", '{"$schema": "https://mintlify.com/docs.json"}\n'),
    # `sites.py` looks for the SUBSTRING `docsify` in an `index.html`, so the
    # marker is a comment naming it rather than a script tag. A real tag would
    # be a fetchable third-party URL sitting in a test fixture, which is a
    # thing to explain forever and buys nothing: the search never parses HTML.
    ("docs/index.html", "<!-- built with docsify -->\n"),
)


def _generated_site(build: AxisBuild) -> Optional[Effect]:
    """Declare the repository a generated site, AND cite routes inside it.

    THE ROUTES ARE THE HALF THAT WAS MISSING, and the first version of this
    docstring described them while the code wrote only the marker - which made
    this axis decoration, since a marker with no route beside it changes
    nothing any rule reports. Found by the Stage 6 gap audit, which asked
    whether each axis could ever report a contradiction and found that this one
    could not.

    Both spellings a generator resolves and the filesystem cannot: one
    root-relative, one extensionless. Measured on a clean repository - without
    a marker both are reported as dead links against a denominator of 2, and
    with `mkdocs.yml` present the denominator stays 2 and the findings go to 0.
    That is the pairing this axis exists to observe: examined, and declined to
    judge.
    """
    name, body = build.rng.choice(_SITE_MARKERS)
    target = build.repo / name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    except OSError:
        return None
    build.facts["site_marker"] = name
    return Effect(
        prose=(f"Routing note: [the reference]({_ROUTES[0]}) "
               f"and [the guide]({_ROUTES[1]}).",),
        note=f"generated site declared by {name}, with routes to forgive")


def _site_declared(repo: Path, out: str, facts: dict) -> Optional[bool]:
    """The routes were EXAMINED and not reported.

    Both halves, because either alone is satisfiable by the wrong thing. "Not
    reported" alone is true of a run where the link rule never looked;
    "examined" alone is true whether or not the marker did anything. Together
    they say the rule reached these links and declined to judge them, which is
    the whole behaviour `sites.py` exists for - and what stopped 235 of
    Starlight's own links being called dead.

    This is where the real check lives. An earlier version of this docstring
    said it lived in a `SITE` oracle in fuzz_oracles.py; no such oracle was
    ever written, so that sentence pointed at a check that did not exist and
    made weak evidence read as covered. A twin run was considered and refused:
    it costs two more spawns per repository to prove what the pairing above
    already shows, and this harness is spawn-bound.
    """
    if facts.get("site_marker") is None:
        return None
    if not re.search(r"dead-md-link [1-9]", out):
        return None
    for line in out.splitlines():
        if "[dead-md-link]" in line and _FORGIVEN_ROUTE in line:
            return False
    return True


# --- git shapes -------------------------------------------------------

# The states in which the repository extant is finally pointed at still has
# the ORIGIN's refs and object store. Every axis below writes into the origin
# during the build, so in any other state it would be measuring a repository
# that never received the change.
#
# THE SHALLOW CLONE IS THE ONE THAT BITES, and it does not bite by declining -
# it bites by producing a CONFIRMED-LOOKING FALSE FAULT. A depth-1 clone has
# neither `claude/real-work` nor `v1.0`, so a true claim about either is
# CORRECTLY reported dead there; the evidence check below would read that
# correct finding as "the axis was applied and the run does not show it" and
# fail the run over the tool being right. Declining is the honest answer, and
# it lands in the "could not build" column where a shape that was not tested
# belongs.
_KEEPS_ORIGIN_REFS = ("attached", "detached", "worktree")

# Every state except `empty`, which is the default for an axis that does not
# say otherwise.
#
# THE `empty` STATE CARRIES NONE OF THE BUILD, and that is easy to miss because
# the axis still applies without error. `build_from_plan` answers that state by
# creating a SEPARATE repository - `git init`, the payload, and a freshly
# composed document - and returning THAT. It has no `.extant.toml`, none of the
# written files and none of the commits, so an encoding written to the original
# is not the document extant reads, a generator marker is not in the tree it
# walks, and a config key was never written anywhere. The axis would report
# itself applied and have done nothing at all, which is the reassuring answer
# this ledger exists to refuse.
_HAS_A_BUILD = ("attached", "detached", "worktree", "shallow")


# The release claim `annotated-tag` writes for itself, in the spelling
# `release_tag` reads: a trigger word, then `in`, `as` or `at`, then the
# version. Worded differently from the `release-tag` feature's own claim so
# that a document carrying both is readable; two true claims about `v1.0` cost
# nothing and produce no finding.
_ANNOTATED_CLAIM = "The peeling path was tagged at `v1.0` for this axis."


def _annotate_release(build: AxisBuild) -> Optional[Effect]:
    """Claim the release now; `v1.0` is re-cut annotated in `finalize`.

    SPLIT ACROSS TWO PHASES, and the split is forced twice over. The claim has
    to reach the document preamble, which only the CONFIG phase composes - a
    later phase's contribution is discarded, and the guard in `_apply_axes` now
    turns that into a broken build rather than a quiet nothing. And `v1.0` does
    not exist until `_git_scaffold` has run, which is long after the config
    phase, so the tag work cannot happen here. `commit-map` is split for
    exactly this pair of reasons and this is the second axis to need it.

    IT WRITES ITS OWN CLAIM, and the case for that is stronger than "the
    evidence was thin". Depending on the `release-tag` feature being co-drawn
    cost this axis in two directions, only one of which the ledger showed:

      - NO WAY TO TELL when the feature was not drawn. Measured across five
        seeds at 35 repositories: 18 confirmed of 47 judged, 38 per cent.
        `AXIS_FLOOR` fails a run whose axis is judged five or more times and
        never confirmed, so that rate is a live flake as well as weak
        evidence.
      - A SPURIOUS CONFIRMATION when the feature WAS drawn and spelled
        `false`. The document then claims `v9.9.9` and never `v1.0`, so
        `dead-release-tag` has a denominator, no finding names `v1.0`, and
        `_true_claim_survived` returns True - having never once looked at an
        annotated tag. That is this project's recurring defect sitting in the
        ledger built to remove it: a check that cannot reach its subject
        returning the value that means all clear. Writing the claim here is
        what makes a True verdict mean what it says.
    """
    return Effect(config=_release_gate(build),
                  prose=(_ANNOTATED_CLAIM,),
                  note="a true `v1.0` release claim, for an annotated tag to answer")


def _recut_annotated_tag(build: AxisBuild) -> None:
    """Replace the lightweight `v1.0` with an annotated one.

    An annotated tag is a different OBJECT TYPE: `rev-parse v1.0` yields a tag
    object that has to be peeled to reach a commit, where a lightweight tag
    points at the commit directly. Every tag this harness has ever created was
    lightweight, so the peeling path in the release and ref rules was never
    taken.

    `tag -f -a` REPLACES IN ONE OPERATION, rather than a delete followed by a
    create. The two-step version has a window in which `v1.0` does not exist,
    and if the create then failed the repository would be left carrying a
    release claim that is genuinely false - which every other property would
    correctly report, over a shape this harness meant to build and did not.

    Leaves `facts["annotated_tag"]` unset on any failure, exactly as
    `_write_commit_map` does: a claim with no annotated tag beside it is this
    harness failing to build a shape, not extant failing to read one, so the
    evidence check must report NO WAY TO TELL rather than a contradiction.
    """
    done = build.git("rev-parse", "--verify", "-q", "v1.0")
    if not (getattr(done, "stdout", "") or "").strip():
        return
    recut = build.git("tag", "-f", "-a", "v1.0", "-m", "the first release")
    if getattr(recut, "returncode", 1) != 0:
        return
    build.facts["annotated_tag"] = "v1.0"


def _annotated(repo: Path, out: str, facts: dict) -> Optional[bool]:
    """The annotated tag did not read as a DEAD one.

    A real assertion rather than a note that a tag exists. An annotated tag is
    a tag object, and a reader that compares it to a commit without peeling it
    would report the TRUE claim - `tagged at v1.0` - as a dead release tag,
    which is a false positive on the most ordinary tag shape there is.

    Answerable now because the axis writes both halves itself: the claim, in
    `_annotate_release`, and the config key that lets the rule report on it.
    """
    if facts.get("annotated_tag") is None:
        return None
    return _true_claim_survived(out, "dead-release-tag", "v1.0")


# The branch `packed-refs` claims, and it must be one `_git_scaffold` really
# creates. The assertion is that a TRUE claim survived, so a claim about a
# branch that does not exist would be correctly reported and read as the
# contradiction this axis exists to raise.
_PACKED_CLAIM = "Work continued on `claude/real-work` before packing."


def _claim_a_branch(build: AxisBuild) -> Optional[Effect]:
    """Claim the branch now; the refs are packed in `finalize`.

    IN THE NEWEST ENTRY, NOT THE PREAMBLE, and that is not a stylistic choice.
    `unknown-branch` and `stale-live-claim` read only that entry, so a branch
    claim written into the preamble is invisible to both - the trap
    `_RAISE_SITES` records having paid for once already, from the other axis
    that aims at these two rules.

    SPLIT ACROSS TWO PHASES for the reason `_annotate_release` is: only the
    config phase's contribution is read, and `git pack-refs` has to run after
    every ref this repository will ever have exists.

    IT WRITES ITS OWN CLAIM, and as with the annotated tag the old dependency
    was not merely thin but wrong in one direction. Confirmation needed
    `branch-token` or `live-claim` co-drawn - measured across five seeds at 35
    repositories, 24 of 39 judged - and `live-claim` names `claude/still-open`,
    a DIFFERENT BRANCH. So a repository drawing only that feature gave
    `unknown-branch` a denominator, no finding named `claude/real-work`
    because nothing had claimed it, and the check returned True without a
    packed ref ever having been read.

    ONE EXPOSURE REMAINS AND IS DELIBERATE. An entry sits after the preamble,
    and one noise shape is an UNCLOSED CODE FENCE, which `strip_code` blanks to
    the end of the document - measured directly, `unknown-branch` goes from 1
    to 0 with one such fence above it. This claim is then invisible, the rule
    examines nothing, and the check reports NO WAY TO TELL. That is the honest
    answer and not a pass, which is why the entry population is safe to use
    here where the preamble is not available.
    """
    return Effect(entry=(_PACKED_CLAIM,),
                  note="a true `claude/real-work` claim, for packed refs to answer")


def _pack_the_refs(build: AxisBuild) -> None:
    """Move every loose ref into `.git/packed-refs`.

    A ref is readable two ways and this harness has only ever written one of
    them. Packing is what an ordinary `git gc` does, so a repository that has
    been alive for a while is in this state and every generated one was not.

    Runs as a FINALIZER rather than in the `final` phase, which is what the
    claim above forced - and it buys something on the way. Finalizers run in
    catalogue order, after every `final`-phase axis, so `annotated-tag` has
    already re-cut its tag by the time this runs and the annotated tag gets
    PACKED TOO. The two halves of the ref machinery are then read out of one
    file, which is the shape an ordinary `git gc` leaves and no repository
    here has ever had.
    """
    if getattr(build.git("pack-refs", "--all"), "returncode", 1) != 0:
        return
    build.facts["packed_refs"] = True


def _packed(repo: Path, out: str, facts: dict) -> Optional[bool]:
    """A branch that exists, read out of `packed-refs`, was not called unknown.

    The same assertion shape as the annotated tag, against the other half of
    the ref machinery: `claude/real-work` really exists, so a ref lookup that
    consulted only loose files would report the true claim as a branch that
    never existed.
    """
    if not facts.get("packed_refs"):
        return None
    return _true_claim_survived(out, "unknown-branch", "claude/real-work")


def _true_claim_survived(out: str, kind: str, subject: str) -> Optional[bool]:
    """Did `kind` examine anything, and did it leave `subject` alone?

    None when the rule examined nothing - the repository drew no claim of that
    shape, so it offered no way to tell, which is not the same as the axis
    having failed. That distinction is why `confirm` is three-state.

    THE CALLER MUST GUARANTEE THAT `subject` IS CLAIMED, and both callers now
    do by writing the claim themselves. Without that this reads as an
    assertion and is not one: a rule examining some OTHER claim satisfies the
    denominator, no finding names a subject nobody mentioned, and True comes
    back from a run in which the axis was never looked at. Both callers
    depended on another feature's draw for exactly that guarantee, and neither
    got it in every repository.
    """
    if not re.search(re.escape(kind) + r" [1-9]", out):
        return None
    for line in out.splitlines():
        if f"[{kind}]" in line and subject in line:
            return False
    return True


# The dead SHA, padded to a full object name because a commit-map records 40
# hex characters a side. The same token the `sha` feature's false spelling
# writes, deliberately: if both are drawn the document cites it twice, which
# costs nothing, and the map repairs both.
_DEAD_SHA = "deadbeef1234" + "0" * 28


def _commit_map(build: AxisBuild) -> Optional[Effect]:
    """Cite a dead SHA now; the map that repairs it is written in `finalize`.

    SPLIT ACROSS TWO PHASES, and the split is the point. The claim has to reach
    the document preamble, which only the config phase composes; the map has to
    name HEAD, which does not exist until the first commit. Written wholly in
    the late phase - as it first was - the prose was silently discarded,
    because nothing reads a late phase's contribution. That is the fourth time
    in this file that an axis reported itself applied while something
    downstream dropped its effect, and the third that the ledger caught.
    """
    build.facts["commit_map_claimed"] = True
    # IT WRITES ITS OWN CLAIM, for the third time in this file and the same
    # reason both earlier times. The map can only be SEEN to work if some
    # document cites the SHA it maps, and depending on the `sha` feature being
    # co-drawn made confirmation a coin flip - measured at 2 of 8 judged on one
    # corpus and 1 of 2 on another, roughly a quarter. That is not merely thin:
    # `AXIS_FLOOR` fails a run whose axis is applied five or more times and
    # never confirmed, so a 25 per cent rate over 8 draws is about a one in ten
    # chance of reddening a healthy run on a fresh seed.
    #
    # An axis that depends on another draw to be observable is an axis whose
    # ledger row reports the draw rather than the axis.
    return Effect(prose=(f"Recorded at `{_DEAD_SHA[:12]}` in the log.",),
                  note="a dead SHA claim, to be repaired by a commit-map")


def commit_map_path(repo: Path) -> Optional[Path]:
    """Where this repository's `filter-repo` commit-map lives, or None.

    ONE FUNCTION, TWO READERS IN TWO FILES. The `commit-map` axis WRITES the
    map through this, and the `--sha-map` mode in fuzz.py READS its path
    through the same call to build the command line. Two spellings of one path
    is the "one claim, two scanners" shape this project keeps finding, and
    here it would hide especially well: the mode would name a file that is not
    there, extant would refuse exactly as it should, and the run would report
    a refusal that reads like the tool declining rather than like the harness
    pointing at the wrong place.

    A LINKED WORKTREE KEEPS A `.git` FILE pointing at the real directory, so
    `.git/filter-repo/commit-map` is not a path there at all. `common_git_dir`
    resolves that on extant's side, and this has to do the same or the map is
    written - and looked for - somewhere nothing reads.

    THE `commondir` HOP IS THE WHOLE OF THAT, and leaving it out is how the
    first version of this function was refuted by its own docstring. A linked
    worktree's pointer names `.git/worktrees/<name>`, which is the checkout's
    OWN git directory and not the shared one; the shared one is named by the
    `commondir` file sitting inside it. Stopping at the pointer returned a path
    nothing writes, so `--sha-map` refused in every worktree that was really
    built - measured before the fix at 2 maps found of 5 worktree repositories,
    and the two were the ones where `git worktree add` had FAILED and left the
    origin behind.

    That it survived being "the one function both sides call" is the lesson
    worth keeping. The WRITER only ever passes the origin, whose `.git` is a
    directory, so the writer never takes this branch at all; sharing the
    function bought nothing on the single path where the two could disagree,
    because only one of them was ever on it.

    A SUBMODULE also keeps a `.git` file, and has no `commondir` beside it -
    there the pointer IS the shared directory, which is why the hop is
    conditional rather than assumed.
    """
    shared = repo / ".git"
    if shared.is_file():
        try:
            pointer = shared.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not pointer.startswith("gitdir:"):
            return None
        gitdir = Path(pointer.split(":", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = repo / gitdir
        common = gitdir / "commondir"
        if common.is_file():
            try:
                named = Path(common.read_text(encoding="utf-8").strip())
            except OSError:
                return None
            gitdir = named if named.is_absolute() else gitdir / named
        shared = gitdir
    return shared / "filter-repo" / "commit-map"


def _write_commit_map(build: AxisBuild) -> None:
    """The file `git filter-repo` leaves behind, mapping the dead SHA to HEAD.

    Phase 26's finding, and fuzzed nowhere until now: the dominant cause of
    this tool's largest finding class is a history rewrite, and the answer sits
    at a fixed path in the repository. `dead-sha` names the replacement when
    this file records one.

    Written by hand rather than by running `filter-repo`, which is not
    installed and would be a third-party dependency. The FORMAT is all that
    matters - old SHA, whitespace, new SHA - and `load_sha_map` reads it.

    Leaves `facts["commit_map"]` unset on any failure, so the evidence check
    reports NO WAY TO TELL rather than a contradiction: a claim with no map
    beside it is this harness failing to build a shape, not extant failing to
    read one.
    """
    head = build.head()
    if not head:
        return
    target = commit_map_path(build.repo)
    if target is None:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"old new\n{_DEAD_SHA} {head}\n", encoding="utf-8")
    except OSError:
        return
    build.facts["commit_map"] = head[:12]


def _mapped(repo: Path, out: str, facts: dict) -> Optional[bool]:
    """A `dead-sha` finding that names the replacement.

    The distinctive half of the output - "the rewrite map records it as" - so
    this cannot be satisfied by an ordinary dead-sha finding that never read
    the map.
    """
    replacement = facts.get("commit_map")
    if replacement is None:
        return None
    if "the rewrite map records it as" in out:
        return True
    # No dead SHA was claimed in this repository, so there was nothing to
    # repair. The map was still written and still read; there is just no
    # finding for it to annotate.
    return None if "[dead-sha]" not in out else False


@dataclass(frozen=True)
class Axis:
    name: str
    widens: str
    phase: str
    apply: Callable[[AxisBuild], Optional[Effect]]
    confirm: Callable[[Path, str, dict], Optional[bool]]
    # How often the swarm draws it. Not all equal, and the two that are rarer
    # say why beside them.
    odds: float = 0.5
    # The git states this axis can actually take effect in. Declared rather
    # than checked inside `apply`, so the driver can decline it BEFORE it runs
    # and record the decline in the "could not build" column - which is where a
    # shape that was not tested belongs.
    states: tuple = _HAS_A_BUILD
    # Work that must happen AFTER the last `git add -A`, exactly as
    # `Feature.finalize` does and for the same reason. THREE axes need it, and
    # all three for one shape: the axis has to contribute DOCUMENT TEXT, which
    # only the config phase can place, and then touch git state that does not
    # exist until much later - HEAD for `commit-map`, the `v1.0` tag for
    # `annotated-tag`, every ref for `packed-refs`. Splitting across the two is
    # what lets each stop depending on another feature being drawn to be
    # observable at all.
    finalize: Optional[Callable[["AxisBuild"], None]] = None


AXES = (
    Axis("encoding", "the document's bytes: CRLF, a BOM, a bare CR, UTF-16",
         "document", _encode, _encoded),
    # RARE ON PURPOSE. It silences one rule's denominator for the repository
    # that draws it, and while `_raise_a_rule` keeps that off any rule a
    # feature is aiming at, a corpus where most repositories carry a raising
    # rule is a corpus mostly testing the error path.
    Axis("raising-rule", "a rule that raises, so ERRORED has a subject",
         "config", _raise_a_rule, _raised, odds=0.2),
    Axis("generated-site", "a generator marker, so the link rules meet routes",
         "config", _generated_site, _site_declared, odds=0.35),
    # BOTH ARE `config` PHASE AXES WITH A FINALIZER, and neither is a git-shape
    # axis in the phase sense any more. Each writes the claim its own evidence
    # reads - in the preamble for the tag, in the newest entry for the branch -
    # and does its git work afterwards. `packed-refs` is listed after
    # `annotated-tag` so its finalizer packs the annotated tag too.
    Axis("annotated-tag", "a tag object to peel rather than a direct ref",
         "config", _annotate_release, _annotated, odds=0.4,
         states=_KEEPS_ORIGIN_REFS, finalize=_recut_annotated_tag),
    Axis("packed-refs", "refs read from .git/packed-refs, not loose files",
         "config", _claim_a_branch, _packed, odds=0.4,
         states=_KEEPS_ORIGIN_REFS, finalize=_pack_the_refs),
    Axis("commit-map", "a history rewrite the repository still remembers",
         "config", _commit_map, _mapped, odds=0.35,
         states=_KEEPS_ORIGIN_REFS, finalize=_write_commit_map),
)


def axis_by_name(name: str) -> Optional[Axis]:
    for axis in AXES:
        if axis.name == name:
            return axis
    return None


def axes_for(phase: str) -> tuple:
    return tuple(a for a in AXES if a.phase == phase)


def draw_axes(rng: random.Random) -> tuple:
    """Which axes this repository carries.

    Independent inclusion at each axis's own odds, matching how features are
    drawn. Unlike features an axis has no `true`/`false` spelling: there is no
    such thing as a document that is half CRLF, and a repository either
    remembers a rewrite or does not.
    """
    return tuple(axis.name for axis in AXES if rng.random() < axis.odds)
