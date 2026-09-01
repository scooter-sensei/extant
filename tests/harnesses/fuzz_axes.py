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
           "axes_for", "draw_axes", "PHASES"]


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
    """
    free = [site for site in _RAISE_SITES
            if not (set(_SILENCES[site[0]]) & build.features)]
    if not free:
        return None
    key, kind, pattern, claim, where = build.rng.choice(free)
    build.facts["raised_rule"] = kind
    extra = ("release_claims_name_our_tags = true",) if key == "release_tag" else ()
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


def _annotated_tag(build: AxisBuild) -> Optional[Effect]:
    """Replace the lightweight `v1.0` with an annotated one.

    An annotated tag is a different OBJECT TYPE: `rev-parse v1.0` yields a tag
    object that has to be peeled to reach a commit, where a lightweight tag
    points at the commit directly. Every tag this harness has ever created was
    lightweight, so the peeling path in the release and ref rules was never
    taken.
    """
    done = build.git("rev-parse", "--verify", "-q", "v1.0")
    if not (getattr(done, "stdout", "") or "").strip():
        return None
    build.git("tag", "-d", "v1.0")
    build.git("tag", "-a", "v1.0", "-m", "the first release")
    build.facts["annotated_tag"] = "v1.0"
    return Effect(note="v1.0 re-cut as an annotated tag")


def _annotated(repo: Path, out: str, facts: dict) -> Optional[bool]:
    """The annotated tag did not read as a DEAD one.

    A real assertion rather than a note that a tag exists. An annotated tag is
    a tag object, and a reader that compares it to a commit without peeling it
    would report the TRUE claim - `shipped in v1.0` - as a dead release tag,
    which is a false positive on the most ordinary tag shape there is.
    """
    if facts.get("annotated_tag") is None:
        return None
    return _true_claim_survived(out, "dead-release-tag", "v1.0")


def _packed_refs(build: AxisBuild) -> Optional[Effect]:
    """Move every loose ref into `.git/packed-refs`.

    A ref is readable two ways and this harness has only ever written one of
    them. Packing is what an ordinary `git gc` does, so a repository that has
    been alive for a while is in this state and every generated one was not.
    """
    done = build.git("pack-refs", "--all")
    if getattr(done, "returncode", 1) != 0:
        return None
    build.facts["packed_refs"] = True
    return Effect(note="refs packed into .git/packed-refs")


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
    shared = build.repo / ".git"
    if shared.is_file():
        # A linked worktree keeps a `.git` FILE pointing at the real one.
        # `common_git_dir` resolves that on extant's side; this has to do the
        # same or the map lands somewhere nothing reads.
        try:
            pointer = shared.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if not pointer.startswith("gitdir:"):
            return
        shared = Path(pointer.split(":", 1)[1].strip())
    try:
        (shared / "filter-repo").mkdir(parents=True, exist_ok=True)
        (shared / "filter-repo" / "commit-map").write_text(
            f"old new\n{_DEAD_SHA} {head}\n", encoding="utf-8")
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
    # `Feature.finalize` does and for the same reason. One axis needs it:
    # `commit-map` has to contribute PROSE, which only the config phase can
    # place in the document, and write a file that needs HEAD, which only
    # exists later. Splitting it across the two is what lets the axis stop
    # depending on another feature being drawn to be observable at all.
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
    Axis("annotated-tag", "a tag object to peel rather than a direct ref",
         "final", _annotated_tag, _annotated, odds=0.4,
         states=_KEEPS_ORIGIN_REFS),
    Axis("packed-refs", "refs read from .git/packed-refs, not loose files",
         "final", _packed_refs, _packed, odds=0.4,
         states=_KEEPS_ORIGIN_REFS),
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
