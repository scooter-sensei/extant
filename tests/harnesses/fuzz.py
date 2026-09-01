"""Fuzzing: build hostile repositories at random and check what must hold.

    python tests/harnesses/fuzz.py <extracted-package> <scratch-dir> [options]
      --seed N       reproduce one run exactly (printed by every run)
      --repos N      how many repositories to build (default 24)
      --save DIR     write a failing repository's PLAN here, replayable
      --replay FILE  rebuild one repository from a saved plan and recheck it
      --no-shrink    report a violation at full size, without ddmin
      --differential [REF|DIR]
                     run the same corpus through this package and another
                     version and diff the findings; defaults to the newest
                     tag. See fuzz_differential.py

Every other harness here checks a case somebody thought of. This one checks the
ones nobody did, which is the only way to cover a list that keeps growing:
fuzzing, malicious repositories, pathological patterns, symlinks, enormous
trees, hostile git states, awkward Unicode paths, shallow clones, detached
HEAD, submodules and worktrees, in combination rather than one at a time.

WHAT IT CHECKS, and why these and not "the right answer"

A fuzzer has no oracle. It cannot know what a generated repository ought to
report, so it checks the properties that hold whatever the answer is:

  crash        no unhandled traceback, ever
  hang         an answer inside the time budget
  exit         0, 1 or 2 - never an interpreter error code
  denominator  a rule cannot report more findings than it examined candidates
  repeat       two runs over an unchanged repository print the same thing
  formats      SARIF parses, and agrees with the text output on the count

The last two are metamorphic: they compare extant against ITSELF under a
change that must not matter. That is what lets a fuzzer find wrong answers
rather than only crashes, and it costs one extra run per repository.

WHAT THE GENERATOR DRAWS, AND WHY IT IS A CATALOGUE

The shapes live in fuzz_shapes.py, one feature per rule, each offering a claim
that is TRUE and one that is FALSE. That file explains why; the short version
is that the twelve hard-coded content strings this harness shipped with reached
5 of the 13 rules, two of them were dead in the way this project keeps warning
about, and every document the generator produced was already wrong - which made
`--selftest` a no-op across the whole corpus, because a probe corrupts a real
match and there were none.

Features are drawn SWARM-STYLE: each repository omits a random subset of them
outright rather than drawing every feature independently at a tuned
probability. That is Groce et al.'s feature-omission diversity (ISSTA 2012),
and it replaces the hand-tuned weighting this generator used to carry. Two
mechanisms it addresses were both present here: features competed for space,
because one content shape was chosen per document, so no repository could hold
a merge claim and an LFS blob at once; and features actively suppressed one
another, because an unparseable config or an unclosed fence silences
everything downstream.

THE REACH LEDGER IS THE DENOMINATOR OF THIS HARNESS

A rule no feature reaches is a rule this gate does not cover, and the old
harness could not say which those were - it counted repositories that produced
any rule counts at all, which was true of a repository exercising one rule and
of one exercising twelve. The ledger records which rules actually EXAMINED
something across the corpus and fails below a floor, for the reason
`registry.py` gives for a denominator that raises rather than answering zero:
an omission should arrive as a red run in the commit that caused it, not as a
reassuring `ok` forever.

WHAT A "COULD NOT BUILD" ROW MEANS

Symlinks need a privilege Windows withholds by default, and submodules need a
transport that some sandboxes refuse. When a shape cannot be constructed, the
case was NOT TESTED, and this harness says so in its own column rather than
counting it as a pass. That distinction is the whole subject of this project,
and a harness that blurred it would be lying in the same way it exists to
catch. The CI job runs on Linux, where both shapes build, so a Windows run
reporting "could not build" is expected rather than alarming - and the count
tells you which coverage you are actually holding.

REPRODUCIBILITY

Randomness that cannot be replayed produces bug reports nobody can act on.
Every run prints its seed; passing it back rebuilds the identical corpus, and
a failing repository is left on disk with `--save` writing its recipe out.

THE SEED IS NOT THE ONLY INPUT. The ARENA PATH is one too, on Windows, and
that went unnoticed long enough to be reported as nondeterminism. Two runs of
the same seed and the same package reached the rules in 25 of 35 repositories
and then 6, and the only difference between them was an arena directory named
`arenaPeer` rather than `arenaPeer2`. One character.

Past roughly 260 characters, git commands start failing individual writes on
Windows, and because nothing here checked a return code the build carried on
and produced repositories with no commits - which the sweep then reports as
`git tracks none in this repository`, indistinguishable from a repository that
is genuinely empty. Measured with the arena path as the ONLY variable: 2 of 12
repositories collapsed at 183 characters and 9 of 12 at 222.

Both halves are fixed. `core.longpaths` is passed to every command that
CREATES a repository, because setting it afterwards is too late - `git init`
fails first, and a config cannot be written into a repository that does not
exist. And `must()` now checks the core git steps, so a repository that fails
to build says so instead of arriving as a quiet zero. The second half matters
more than the first: some paths are still too deep for git whatever is
configured, and what makes that survivable is that the harness now knows.

A PLAN IS A REPOSITORY YOU CAN HAND SOMEBODY

`--save` writes a `RepoPlan`, and `--replay` builds it. That is a change of
kind rather than of detail: what `--save` wrote before was PROSE, a list of
sentences describing what a repository had contained, and CI uploaded it as
the `fuzz-failures` artifact where nothing could consume it. The only route
back to repository 25 was `--seed N`, rebuilding all thirty-five to reach one.

It could not have been otherwise, because deciding and building were the same
loop: a repository was defined by its POSITION IN AN RNG STREAM. `draw_plan`
now makes every choice and writes it down, `build_from_plan` builds and draws
nothing the plan does not fix, and one integer - `repo_seed` - owns every
choice inside a repository, so the file stays small instead of carrying a
60,000-character noise document.

AND THEN IT SHRINKS

A violation arrives attached to whatever the swarm drew, often eight or nine
features with one of them responsible. ddmin bisects the feature set while the
property still holds, which needs no shrinking-specific machinery at all: the
features are the atoms and dropping one is a legal repository. Measured on a
`manifest-floor-mismatch` denominator violation: 9 features to 1 in 7 rebuilds.

It runs only on a violation, so a green run pays nothing, and only on the
DETERMINISTIC properties. `UNSTABLE` exists because a run disagreed with
itself, so a bisect guided by it follows noise and reports a minimal set that
reproduces nothing - which is worse than reporting the unshrunk one, because
it looks like an answer.

A finding does not stay here. It gets reduced to a case in
tests/test_fuzz_findings.py, so it runs in the suite on every commit instead
of waiting for a seed to come up again. This harness discovers; that file
remembers. The accumulation there is the history, which is why this one keeps
no corpus of its own - a second store of regressions that CI does not run is
a store nobody reads.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuzz_differential as differential  # noqa: E402
import fuzz_oracles as oracles  # noqa: E402
import fuzz_shapes as shapes  # noqa: E402

PY = sys.executable
TIMEOUT = 90

# Set from `--no-oracles`. A module-level switch rather than a
# parameter because `all_faults` is called from three places and
# threading a flag through each would be three chances to disagree.
ORACLES_ON = True

# --- the alphabets the generator draws from ---------------------------

# Path names that are legal but awkward. Each has broken something in some
# tool: the first two are the same GLYPH in two normalisations, which compare
# unequal as bytes and equal on a case-folding filesystem.
AWKWARD_NAMES = [
    "cafe\u0301",          # NFD, combining acute
    "caf\u00e9",           # NFC, precomposed - same glyph as above
    "\u0645\u0644\u0641",  # arabic, right-to-left
    "a\u200bb",            # zero-width space
    "\u202egnp",           # right-to-left override
    "emoji\U0001F600",     # astral plane
    "sp ace",
    "d\u00e4sh-\u00fc",
    "UPPER", "upper",      # same name, two cases
    "dot.in.name",
    "-dashed",             # looks like an option
    "--option-like",
    "tab\there" if sys.platform != "win32" else "no-tab-here",
]

# Document shapes that cost something without making a claim: backtracking
# bait, fences that do not close, a line long enough to matter. These are
# NOISE, drawn alongside the catalogue rather than instead of it. They used to
# be the whole alphabet, which is why 8 of 13 rules were never reached.
def _noise_shapes(rng: random.Random) -> list[str]:
    return [
        "```\nunclosed fence with `src/gone.py` inside\n",
        ("a" * rng.choice([200, 5_000, 60_000])),
        "".join(f"See `f{i}.py`. " for i in range(rng.randint(1, 40))),
        "Pointer at `tools/extant_collect.py:999999`.",
        "\u202e" * 20 + " reversed prose `x.py`",
        "nested ``` ` `` ticks `src/gone.py` ``` here",
        "Repeated headings and [#h-2](#h-2).",
    ]

# Configuration a hostile or careless project might ship. The regexes are the
# backtracking bait the existing smoke probe covers as a single case; here they
# combine with everything else.
CONFIG_SHAPES = [
    "",
    'path_pointer = "(a+)+$"\n',
    'entry_prefix = "## "\n',
    'exclude_paths = ["**", "*.md"]\n',
    'exclude_paths = ["nothing-matches-this"]\n',
]

# Weighted, because two of those shapes END the run. `exclude_paths` covering
# every path excludes the document the config gates on, which is a refusal, and
# a refusal costs a whole repository and answers almost nothing. Drawn
# uniformly alongside the 15 per cent broken-config rate below, refusals reached
# 10 of 35 - nearly a third of the budget spent on argument parsing. The
# pathological shapes stay in the draw, because a config that excludes its own
# target is a real mistake a project makes; they are just no longer a third of
# it.
CONFIG_WEIGHTS = [6, 2, 2, 1, 2]

# Configurations that END the run before any rule executes. Drawn rarely and
# deliberately: uniformly, they spent most of the corpus on the two shapes that
# test the least. Measured at 2 of 12 repositories reaching the rules before
# this weighting.
BROKEN_CONFIG_SHAPES = [
    'primary_doc = "missing-on-purpose.md"\n',
    "not valid toml at all [[[\n",
]

# The git states a repository can be in when extant meets it. Named so the
# driver can walk them rather than draw them, for the reason below.
GIT_STATES = ["attached", "detached", "worktree", "shallow", "empty"]

MODES = [
    ["--sweep"],
    ["--verify"],
    ["--validate", "NEXT_SESSION.md"],
    ["--sweep", "--format=sarif"],
    ["--sweep", "--format=github"],
    ["--selftest"],
    ["--deleted-since", "HEAD"],
]

# Modes that MUST print a denominator line. A mode listed here that prints none
# is a harness fault rather than a pass: `_rule_counts` returning nothing makes
# the DENOMINATOR check iterate nothing and succeed, so a tool that stopped
# reporting its denominator would read exactly like a tool with clean counts.
MODES_WITH_DENOMINATOR = ("--sweep", "--verify", "--validate")

# How many of the 13 rules a run must see EXAMINE something before its result
# means anything. Measured, not guessed: seed 20260824 at 35 repositories
# reaches all 13.
#
# THE CEILING WAS 12, and the thirteenth was `manifest-floor-mismatch`. The
# ledger probes with `--sweep`, and the sweep passed the document PATH into
# `validate()` alone - which scopes it to that call - so `count_examined()` ran
# against a document with no path and that rule, which keys on the document
# name, could not register here however well the feature worked. `--verify`
# counted it correctly throughout, which is what kept the defect in the survey
# rather than in the rule. Fixed with the two denominator conflations this
# harness found, so the exemption below went with it and this rises to 13.
#
# AT the measurement now rather than one below it, which is a deliberate loss
# of margin and safe for one reason: the CI job pins the seed, so the draw is
# not a lottery there, and a feature that is drawn and reaches nothing already
# fails the run on its own below. Raise it deliberately and say why, the way
# the spawn budget is raised. Do not lower it to make a red run green: a drop
# means a feature stopped firing, and the release shape sat in this harness
# matching nothing for its entire life because nothing was watching this
# number.
REACH_FLOOR = 13

# What fraction of the repositories built must actually reach the rules before
# this run's verdict means anything.
#
# Set BELOW the healthy measurement rather than at it, deliberately, because
# this number gates whether any other number here can be read. A healthy run
# reaches the rules in about 70 per cent of repositories - 25 of 35 at seed
# 20260824 - and the rest are the refusals and the empty-repository state,
# which are legitimately countless. Half of that is the point at which a run
# has stopped being a sample of anything.
#
# Raise it once the collapse described beside its check is fixed; the healthy
# figure is the ceiling to aim at, not this.
CORPUS_FLOOR = 0.35

# Rules that CANNOT reach the ledger for a reason outside this harness, with
# the reason, so the exemption is readable and removable rather than a silently
# lowered floor.
#
# The floor alone is not enough. A feature that was DRAWN and still reached
# nothing is a defect - it is the release-shape failure exactly - while a
# feature the swarm never drew is only a short run. Those are separated below,
# and the drawn-and-missed case fails. This table is what stops that check
# reddening every run over a defect somebody already knows about.
#
# Delete an entry the moment its defect is fixed. An exemption nobody revisits
# is how a rule stops being exercised for six releases.
# Empty, and kept rather than deleted: the one entry it held was
# `manifest-floor-mismatch`, exempt only because the sweep's denominator could
# not see the document it keys on. That is fixed, so the exemption is gone and
# the floor above covers all 13. An entry here must name a reason OUTSIDE this
# harness, so that it reads as removable rather than as a silently lowered
# floor - which is what this one turned out to be.
KNOWN_UNREACHABLE: dict = {}


# --- plumbing ---------------------------------------------------------

# `core.longpaths` has to be passed ON THE COMMAND LINE for any command that
# CREATES a repository, and that is the whole subtlety. Setting it with
# `git config` afterwards is too late: `git init` itself fails first, with
# `cannot stat '.../.git/hooks/applypatch-msg.sample': Filename too long`, and
# a config cannot be written into a repository that does not exist.
#
# Measured at a 230-character repository path: plain `git init` fails, and
# `git -c core.longpaths=true init` succeeds. Every command below that builds a
# NEW repository - init, clone - needs it; commands run inside an existing one
# inherit it from the config set at build time.
LONGPATHS = ("-c", "core.longpaths=true")

# What every repository this harness creates needs before it checks anything
# out, passed on the command line because a CLONE is a brand new repository
# with default configuration and inherits nothing from its origin.
#
# That omission was residual nondeterminism after the arena-path fix was
# already in: the origin carried `filter.lfs.required=false` and the clone did
# not, so a `shallow` repository holding an LFS pointer smudged it under the
# system-wide `required=true`, git-lfs asked the network for a fabricated oid,
# and the answer depended on timing. Measured: one replay of the same plan in
# four came back clean.
SAFE_GIT = ("-c", "core.longpaths=true", "-c", "filter.lfs.required=false")


def _rmtree(path: Path) -> None:
    """Remove a built repository, including the parts git made read-only.

    `shutil.rmtree(ignore_errors=True)` is not enough on Windows: git marks
    loose objects read-only, rmtree cannot unlink them, `ignore_errors`
    swallows the failure, and the directory survives. Nothing noticed while
    each index was built exactly once - the very next thing to build the same
    index twice was ddmin, and every one of its rebuilds died on
    `FileExistsError` instead. Which `_still_fails` then caught and read as
    "this subset does not reproduce", so the shrink concluded that no feature
    could be dropped.
    """
    if not path.exists():
        return
    for child in path.rglob("*"):
        try:
            child.chmod(stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():
        raise OSError(f"could not remove {path}")


def sh(cwd: Path, *args: str, check: bool = False):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          check=check, encoding="utf-8", errors="replace")


def must(recipe: "Recipe", cwd: Path, *args: str):
    """A git step the repository CANNOT be built without, checked.

    Everything here used to call `sh` and drop the return code, and that is
    the single reason a corpus could collapse in silence. When `git add -A`
    failed, the commit that followed failed too, the build carried on, and what
    came back was a repository with no commits and no tracked markdown - which
    the sweep then reported as `git tracks none in this repository`, and which
    reads exactly like a repository that is simply empty.

    Two whole days of symptoms came from that: a corpus reaching 6 of 35
    repositories instead of 25 looked like nondeterminism, because the thing
    that actually failed never said so. A harness that cannot tell a
    construction failure from a construction is not measuring anything.
    """
    done = sh(cwd, *args)
    if done.returncode == 0:
        return done
    # "nothing to commit" is not a failure, and treating it as one threw away a
    # working repository. The second commit carries the claims that needed a
    # ref or a tag to exist first; when the draw produced no such feature the
    # document is byte-identical to the one already committed, git exits 1, and
    # the repository is exactly as intended.
    #
    # It is invisible on stderr - git says so on STDOUT - which is why the
    # first version of this check reported it as `git commit -qm: exit 1` with
    # no detail at all, and discarded repository 025 of a clean run.
    if "nothing to commit" in (done.stdout or ""):
        return done
    detail = " ".join((done.stderr or "").split())[:120]
    recipe.broke(f"{' '.join(args[:3])}: {detail or 'exit ' + str(done.returncode)}")
    return done


class Recipe:
    """Everything needed to rebuild one repository, and what it could not build."""

    def __init__(self, seed: int, index: int) -> None:
        self.seed = seed
        self.index = index
        self.steps: list[str] = []
        self.skipped: list[str] = []
        self.features: list[str] = []
        # Core construction steps that FAILED. Distinct from `skipped`, which
        # is a shape this platform declines to build and is a legitimate
        # result. A broken step means the repository is not what the recipe
        # says it is, and nothing measured from it can be read.
        self.broken: list[str] = []

    def did(self, what: str) -> None:
        self.steps.append(what)

    def broke(self, what: str) -> None:
        self.broken.append(what)

    def drew(self, name: str, truth: str) -> None:
        self.features.append(f"{name}:{truth}")

    def could_not(self, what: str, why: str) -> None:
        self.skipped.append(f"{what} ({why})")

    def as_dict(self) -> dict:
        return {"seed": self.seed, "index": self.index,
                "features": self.features,
                "built": self.steps, "not_built": self.skipped,
                "broken": self.broken}


def _draw_features(rng: random.Random):
    """A swarm configuration: which features are IN, and how each is spelled.

    Independent inclusion at even odds, which is the plain form of the
    technique. A feature that is in then draws `true`, `false` or `both`;
    `both` is weighted highest because it exercises the examined-and-clean path
    and the reporting path in one repository, and because `--selftest` needs a
    true claim to corrupt.
    """
    drawn = []
    for feature in shapes.FEATURES:
        if rng.random() < 0.5:
            continue
        truth = rng.choices(("both", "true", "false"), weights=(3, 1, 1))[0]
        drawn.append((feature, truth))
    return drawn


@dataclass
class RepoPlan:
    """Everything needed to build ONE repository, without building any other.

    This is the whole of Stage 2, and the reason it needed a type rather than a
    few more fields on `Recipe`. Before it, deciding and building were the same
    loop: `build_repo` drew from the run's shared generator as it went, so a
    repository was defined by its POSITION IN AN RNG STREAM rather than by
    anything writable. `--save` could therefore only ever write prose, CI
    uploaded that prose as the `fuzz-failures` artifact, and nothing could
    consume it - the sole way back to repository 25 was `--seed N`, which
    rebuilds all thirty-five.

    A plan separates the two. `draw_plan` makes every choice and writes it
    down; `build_from_plan` makes the repository and draws nothing the plan
    does not already fix. Replay, and shrinking, both fall out of that: one
    loads a plan, the other edits one.

    `repo_seed` is drawn from the run's generator and then owns every random
    choice INSIDE this repository - the trunk name, the noise, the awkward
    paths, the symlink shapes, the hostile refs. Keeping it to one integer is
    what stops a recipe file having to carry a 60,000-character noise document.
    """

    repo_seed: int
    index: int
    state: str
    mode: tuple
    # (feature name, truth) - the ONLY part of the plan ddmin edits.
    features: tuple = ()
    # WHAT THE PLAN WAS BUILT AGAINST. A plan says how to build a repository
    # and says nothing about the tool that was run over it, so replaying a CI
    # artifact against a locally patched payload silently answers a different
    # question from the one asked. Recorded so `--replay` can SAY the payload
    # differs - a warning rather than a refusal, because replaying against a
    # fixed payload is the point when you are checking whether a fix worked.
    payload: str = ""

    def to_dict(self) -> dict:
        return {"repo_seed": self.repo_seed, "index": self.index,
                "state": self.state, "mode": list(self.mode),
                "features": [list(f) for f in self.features],
                "payload": self.payload}

    @classmethod
    def from_dict(cls, raw: dict) -> "RepoPlan":
        missing = [k for k in ("repo_seed", "index", "state", "mode")
                   if k not in raw]
        if missing:
            # A bare KeyError names one field and no context. This is a file
            # somebody hand-edited or an artifact from an older harness, and
            # either way the useful thing is which fields a plan needs.
            raise ValueError(
                f"not a usable plan: missing {', '.join(missing)}. A plan "
                f"needs repo_seed, index, state and mode, and optionally "
                f"features and payload.")
        return cls(repo_seed=int(raw["repo_seed"]), index=int(raw["index"]),
                   state=str(raw["state"]), mode=tuple(raw["mode"]),
                   features=tuple(tuple(f) for f in raw.get("features", ())),
                   payload=str(raw.get("payload", "")))

    def without(self, names) -> "RepoPlan":
        """The same plan with some features removed. What ddmin bisects over."""
        drop = set(names)
        return RepoPlan(repo_seed=self.repo_seed, index=self.index,
                        state=self.state, mode=self.mode,
                        features=tuple(f for f in self.features
                                       if f[0] not in drop),
                        payload=self.payload)


def payload_digest(pkg: Path) -> str:
    """A short fingerprint of the payload a plan was built against.

    Content rather than version string: two checkouts can both call themselves
    0.25.0 while one carries the fix being tested. Cheap enough to take once
    per run, and only the first 12 hex digits are kept because this exists to
    say SAME or DIFFERENT, never to identify a build.
    """
    import hashlib
    root = pkg / "plugin/skills/extant/payload"
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*.py")
                       if "__pycache__" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _feature_by_name(name: str):
    for feature in shapes.FEATURES:
        if feature.name == name:
            return feature
    return None


def draw_plan(rng: random.Random, index: int, state: str, mode,
              payload: str = "") -> RepoPlan:
    """Decide one repository. Draws from the run generator, builds nothing."""
    repo_seed = rng.randrange(2 ** 31)
    local = random.Random(repo_seed)
    features = tuple((f.name, truth) for f, truth in _draw_features(local))
    return RepoPlan(repo_seed=repo_seed, index=index, state=state,
                    mode=tuple(mode), features=features, payload=payload)


def _apply(build, drawn, phase: str, recipe: Recipe):
    """Run every drawn feature of one phase, recording what would not build."""
    parts = []
    for feature, truth in drawn:
        if feature.phase != phase:
            continue
        try:
            part = feature.build(build, truth)
        except (OSError, UnicodeError, ValueError) as exc:
            recipe.could_not(f"feature {feature.name}", type(exc).__name__)
            continue
        if part is None:
            recipe.could_not(f"feature {feature.name}", "declined")
            continue
        parts.append(part)
    return parts


def _git_scaffold(repo: Path, trunk: str, rng: random.Random) -> None:
    """The refs the post-commit features name.

    Built unconditionally rather than per feature, because two features name
    the same branch and a ref created twice is an error while a ref nobody
    cites is harmless. `claude/already-merged` really is merged and
    `claude/still-open` really is not, so a claim about either has a definite
    answer rather than an accidental one.
    """
    sh(repo, "git", "branch", "claude/real-work")
    sh(repo, "git", "branch", "claude/still-open")
    sh(repo, "git", "checkout", "-q", "-b", "side-work")
    (repo / "side.txt").write_text("side\n", encoding="utf-8")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "side work, off the trunk")
    sh(repo, "git", "checkout", "-q", trunk)
    sh(repo, "git", "checkout", "-q", "-b", "claude/already-merged")
    (repo / "merged.txt").write_text("merged\n", encoding="utf-8")
    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "work that was merged")
    sh(repo, "git", "checkout", "-q", trunk)
    sh(repo, "git", "merge", "-q", "--no-ff", "-m", "merge", "claude/already-merged")
    sh(repo, "git", "tag", "v1.0")
    # more commits, so ancestry rules have something to walk
    for i in range(rng.randint(0, 4)):
        (repo / f"f{i}.txt").write_text(f"{i}\n", encoding="utf-8")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", f"c{i}")


def build_from_plan(pkg: Path, arena: Path,
                    plan: RepoPlan) -> tuple[Path, Recipe]:
    """One hostile repository, built from a plan and drawing nothing new.

    Every random choice comes from `random.Random(plan.repo_seed)`, so the same
    plan yields the same repository no matter what else the run has built. The
    FEATURE SET is the one exception: it is taken from the plan rather than
    from the generator, which is what lets ddmin hand this function a subset.

    THE DISCARDED DRAW BELOW IS LOAD-BEARING. `_draw_features` is still called
    and its result thrown away, purely to advance the generator exactly as far
    as it advanced when the plan was drawn. Skipping it would leave every later
    draw - trunk, noise, awkward paths, symlinks - reading different numbers, so
    a replayed repository would differ from the one being replayed and a shrunk
    one would differ from both. Bisecting on a repository that changes shape
    underneath you reports a minimal feature set that reproduces nothing.
    """
    rng = random.Random(plan.repo_seed)
    _draw_features(rng)
    index = plan.index
    state = plan.state
    recipe = Recipe(plan.repo_seed, index)
    repo = arena / f"fuzz{index:03d}"
    _rmtree(repo)
    repo.mkdir(parents=True)
    trunk = rng.choice(["main", "master", "trunk"])
    sh(repo, "git", *LONGPATHS, "init", "-q", "-b", trunk)
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "T")
    # WINDOWS MAX_PATH, and the reason this harness was unreadable for a while.
    #
    # A generated repository carries `tools/extant/rules/*.py` and a full
    # `.git/objects` tree under an arena path that is already long, because the
    # scratchpad these run in is nested. Past 260 characters git starts failing
    # individual writes - "Filename too long", "cannot write keep file" - and
    # since nothing checked a return code, the build carried on and produced a
    # repository with no commits.
    #
    # Measured rather than reasoned: the same seed and package, with ONLY the
    # arena path length changed, collapsed 2 of 12 repositories at 183
    # characters and 9 of 12 at 222. That is what looked like a fuzzer whose
    # corpus varied run to run - it varied by arena NAME, which nobody was
    # treating as an input.
    sh(repo, "git", "config", "core.longpaths", "true")
    # git-lfs must not reach the network, and by default it does. `lfs-blob`
    # commits a file whose content is a valid LFS pointer with a fabricated
    # oid; any later checkout asks git-lfs to smudge it, git-lfs asks whatever
    # `origin` names for the object - the `pinned-ref` feature helpfully adds a
    # github.com remote - and the answer is a credential error off the machine.
    # `git worktree add` was observed failing exactly that way.
    #
    # `required = false` makes a filter failure a warning and passes the
    # content through, which is what this harness wants: the pointer is data,
    # not something to resolve. The no-network guarantee this project makes
    # about the tool should hold for the harness that tests it.
    sh(repo, "git", "config", "filter.lfs.required", "false")
    shutil.copytree(pkg / "plugin/skills/extant/payload", repo / "tools")

    # A NAME THAT NO LONGER RESOLVES IS A BROKEN BUILD, NOT AN EMPTY ONE.
    #
    # This used to drop the unknown ones and carry on, which made the
    # reproduction path lie in the most damaging direction available: replaying
    # a plan whose feature had been renamed built a repository with NOTHING in
    # it, found no violation, and printed "this plan does not reproduce one" at
    # exit 0. Which reads as "the bug is fixed". It even listed the feature it
    # had just discarded, so the output asserted the opposite of what happened.
    #
    # Plans outlive the catalogue - a CI artifact from last week, a case in a
    # bug report - so this is the normal way for one to go stale, not an exotic
    # one.
    drawn = []
    for name, truth in plan.features:
        feature = _feature_by_name(name)
        if feature is None:
            recipe.broke(f"plan names feature {name!r}, which this catalogue "
                         f"does not have - the plan is stale, not the tool")
            continue
        drawn.append((feature, truth))
    for feature, truth in drawn:
        recipe.drew(feature.name, truth)
    build = shapes.Build(repo=repo, rng=rng, sh=sh, trunk=trunk)

    pre = _apply(build, drawn, "pre", recipe)
    merged_pre = shapes.merge(pre)
    shapes.write_files(repo, merged_pre)

    noise = _noise_shapes(rng)
    preamble = list(merged_pre.prose)
    for _ in range(rng.randint(0, 2)):
        preamble.append(rng.choice(noise))
    # The drawn extra setting joins the BARE KEYS rather than being appended to
    # the rendered config, because `compose_config` emits table blocks last and
    # a key written after a `[table]` header belongs to that table. Appending
    # it put `path_pointer` inside `[extant.consistency.*]`, where it parses as
    # a different setting and reads as the tool ignoring its own configuration.
    extra = rng.choices(CONFIG_SHAPES, weights=CONFIG_WEIGHTS)[0].strip()
    base = ('primary_doc = "NEXT_SESSION.md"', f'trunk = "{trunk}"')
    if extra:
        base = base + (extra,)
    broken = rng.random() < 0.08
    config = (rng.choice(BROKEN_CONFIG_SHAPES) if broken
              else shapes.compose_config(base, merged_pre))
    (repo / ".extant.toml").write_text(config, encoding="utf-8")
    (repo / "NEXT_SESSION.md").write_text(
        shapes.compose_document(preamble, merged_pre.entry), encoding="utf-8")
    recipe.did(f"{len(drawn)} feature(s), config "
               f"{'deliberately broken' if broken else 'valid'}")

    # documents at awkward paths, in awkward directories
    made = 0
    for _ in range(rng.randint(1, 6)):
        name = rng.choice(AWKWARD_NAMES)
        parent = repo / rng.choice(["", "docs", "docs/deep/deeper",
                                    rng.choice(AWKWARD_NAMES)])
        try:
            parent.mkdir(parents=True, exist_ok=True)
            (parent / f"{name}.md").write_text(
                "# Doc\n\n" + rng.choice(noise) + "\n", encoding="utf-8")
            made += 1
        except (OSError, UnicodeError) as exc:
            recipe.could_not(f"path {name!r}", type(exc).__name__)
    recipe.did(f"{made} document(s) at awkward paths")

    # a file that is not valid UTF-8, which a sweep must count rather than skip
    if rng.random() < 0.5:
        (repo / "binary.md").write_bytes(b"\xff\xfe\x00bad utf-8 \xc3\x28")
        recipe.did("undecodable document")

    # symlinks: dangling, looping, escaping. Privilege-gated on Windows.
    if rng.random() < 0.6:
        try:
            (repo / "dangling.md").symlink_to(repo / "nowhere.md")
            recipe.did("dangling symlink")
            if rng.random() < 0.5:
                (repo / "loop_a").symlink_to(repo / "loop_b",
                                             target_is_directory=True)
                (repo / "loop_b").symlink_to(repo / "loop_a",
                                             target_is_directory=True)
                recipe.did("symlink directory loop")
            if rng.random() < 0.5:
                (repo / "escape").symlink_to(arena, target_is_directory=True)
                recipe.did("symlink escaping the repository")
        except (OSError, NotImplementedError) as exc:
            recipe.could_not("symlinks", type(exc).__name__)

    must(recipe, repo, "git", "add", "-A")
    must(recipe, repo, "git", "commit", "-qm", "initial")

    _git_scaffold(repo, trunk, rng)

    # post features: the ones naming a commit, a tag or a branch, which have to
    # exist before the claim about them can be written
    post = _apply(build, drawn, "post", recipe)
    merged = shapes.merge(pre + post)
    shapes.write_files(repo, shapes.merge(post))
    if not broken:
        (repo / ".extant.toml").write_text(
            shapes.compose_config(base, merged), encoding="utf-8")
    (repo / "NEXT_SESSION.md").write_text(
        shapes.compose_document(list(merged.prose) + preamble[len(merged_pre.prose):],
                                merged.entry), encoding="utf-8")
    must(recipe, repo, "git", "add", "-A")
    must(recipe, repo, "git", "commit", "-qm", "the claims")

    # hostile refs: names that look like options, contain spaces or non-ASCII
    for ref in rng.sample(["-dashed-branch", "--option-branch", "with space",
                           "\u00fcnicode", "a/b/c/deep", "HEAD-ish",
                           "feature/x"], k=rng.randint(0, 4)):
        sh(repo, "git", "branch", "--", ref)
    # `v1.0` and `v9.9.9` are NOT in this list, and must not be. The release
    # feature writes a true claim about `v1.0` and a false one about `v9.9.9`,
    # so a hostile tag creating either turns one of those claims into the other
    # and the feature silently stops meaning what it says. The old list carried
    # both, from when no feature named a version at all.
    for tag in rng.sample(["-v2", "tag with space", "\u00fctag",
                           "release-candidate"], k=rng.randint(0, 3)):
        sh(repo, "git", "tag", "--", tag)
    recipe.did("hostile ref and tag names")

    # anything that must land AFTER the last generic `git add -A`
    for feature, truth in drawn:
        if feature.finalize is not None:
            try:
                feature.finalize(build, truth)
            except (OSError, ValueError) as exc:
                recipe.could_not(f"finalize {feature.name}", type(exc).__name__)

    # a submodule, when the transport allows one
    if rng.random() < 0.35:
        inner = arena / f"sub{index:03d}"
        _rmtree(inner)
        inner.mkdir(parents=True)
        sh(inner, "git", *LONGPATHS, "init", "-q", "-b", "main")
        sh(inner, "git", "config", "user.email", "t@t")
        sh(inner, "git", "config", "user.name", "T")
        # The inner repository needs the setting PERSISTED too, not just on its
        # init. `-c` covers the command it is passed to and nothing after it,
        # so this repository's own `git add` was still failing with "unable to
        # create temporary file: Filename too long" once init had been fixed.
        sh(inner, "git", "config", "core.longpaths", "true")
        (inner / "README.md").write_text("# inner\n\nSee `gone.py`.\n",
                                         encoding="utf-8")
        sh(inner, "git", "add", "-A")
        sh(inner, "git", "commit", "-qm", "inner")
        r = sh(repo, "git", "-c", "protocol.file.allow=always",
               "submodule", "add", "-q", inner.as_uri(), "vendor")
        if r.returncode == 0:
            sh(repo, "git", "add", "-A")
            sh(repo, "git", "commit", "-qm", "submodule")
            recipe.did("submodule")
        else:
            recipe.could_not("submodule",
                             (r.stderr or "").strip().splitlines()[-1][:40]
                             if r.stderr else "git refused")

    # git states: detached HEAD, a linked worktree, a shallow copy
    if state is None:
        state = rng.choice(GIT_STATES)
    if state == "detached":
        sh(repo, "git", "checkout", "-q", "--detach", "HEAD")
        recipe.did("detached HEAD")
    elif state == "worktree":
        linked = arena / f"wt{index:03d}"
        _rmtree(linked)
        r = sh(repo, "git", "worktree", "add", "-q", "--detach",
               str(linked), "HEAD")
        if r.returncode == 0 and linked.exists():
            shutil.copytree(pkg / "plugin/skills/extant/payload",
                            linked / "tools", dirs_exist_ok=True)
            recipe.did("linked worktree (validated instead of the origin)")
            return linked, recipe
        recipe.could_not("worktree", "git refused")
    elif state == "shallow":
        cloned = arena / f"sh{index:03d}"
        _rmtree(cloned)
        r = sh(arena, "git", *SAFE_GIT, "clone", "-q", "--depth", "1",
               repo.as_uri(), str(cloned))
        if r.returncode == 0 and cloned.exists():
            # Persisted as well as passed: the clone is checked out again by
            # anything that touches it later, including `--replay` rebuilding
            # over it, and `-c` covers only the command it is given to.
            sh(cloned, "git", "config", "core.longpaths", "true")
            sh(cloned, "git", "config", "filter.lfs.required", "false")
            shutil.copytree(pkg / "plugin/skills/extant/payload",
                            cloned / "tools", dirs_exist_ok=True)
            recipe.did("shallow clone (validated instead of the origin)")
            return cloned, recipe
        recipe.could_not("shallow clone", "git refused")
    elif state == "empty":
        # a repository with no commit at all reaches rules that assume HEAD
        bare = arena / f"empty{index:03d}"
        _rmtree(bare)
        bare.mkdir(parents=True)
        sh(bare, "git", *LONGPATHS, "init", "-q", "-b", "main")
        shutil.copytree(pkg / "plugin/skills/extant/payload", bare / "tools")
        (bare / "NEXT_SESSION.md").write_text(
            shapes.compose_document(preamble, merged.entry), encoding="utf-8")
        recipe.did("repository with no commits")
        return bare, recipe

    return repo, recipe


# --- the properties ---------------------------------------------------

# BOTH spellings of the denominator line, and every occurrence of each.
#
# `--sweep` prints one aggregate `examined: ...`; `--verify` and `--validate`
# print `checked <path>: ...` once PER DOCUMENT, and the old pattern matched
# neither of those. So in the two gating modes `_rule_counts` returned nothing,
# the DENOMINATOR check iterated nothing, and every gating run passed that
# property vacuously - while a `--verify` over `extra_docs` is exactly where a
# per-document denominator can disagree with a whole-run finding count.
#
# Summing across documents rather than reading the first line is what makes the
# comparison meaningful: findings are counted over the whole output, so the
# denominator has to be too.
_EXAMINED = re.compile(r"^(?:  )?(?:examined|checked [^:]+): (.+)$", re.M)


def _rule_counts(text: str) -> dict[str, int]:
    """Summed denominators, or an empty mapping when the output states none.

    An empty mapping is AMBIGUOUS on its own - it means either "this mode
    prints no denominator" or "this mode stopped printing one" - so callers
    must decide against MODES_WITH_DENOMINATOR rather than reading it as clean.
    """
    counts: dict[str, int] = {}
    for match in _EXAMINED.finditer(text):
        for part in match.group(1).split(","):
            bits = part.strip().rsplit(" ", 1)
            if len(bits) == 2 and bits[1].isdigit():
                counts[bits[0]] = counts.get(bits[0], 0) + int(bits[1])
    return counts


def _denominator_faults(out: str, counts: dict, label: str):
    """A rule may not report more findings than it examined candidates."""
    faults = []
    for kind, examined in counts.items():
        found = len(re.findall(r"\[" + re.escape(kind) + r"\]", out))
        if found > examined:
            faults.append(("DENOMINATOR",
                           f"{label}: {kind} reported {found} "
                           f"from {examined} examined"))
    return faults


def refused_early(done) -> bool:
    """Did this run DECLINE to start, rather than run and conclude?

    Recognised structurally rather than by message: nothing on stdout, a
    diagnostic on stderr, a non-zero exit. Extracted so the denominator check
    and the SARIF check agree on what a refusal is - they were two spellings of
    the same test, and a refusal exempted from one but not the other would be
    reported as a fault by whichever had not been updated.
    """
    return bool(done.returncode != 0 and not (done.stdout or "").strip()
                and (done.stderr or "").strip())


def run_mode(repo: Path, mode: list[str]):
    """Run extant against one repository, FROM INSIDE IT.

    `cwd=repo` is not tidiness. `--validate FILE` resolves FILE against the
    working directory, not against `--repo`, so without this the
    `--validate NEXT_SESSION.md` mode read whatever `NEXT_SESSION.md` the
    harness happened to be standing in - which, run from a checkout of this
    project, is THIS PROJECT'S OWN status document. One of the seven modes had
    been validating the wrong file entirely, and reporting `ok` for it: the
    findings were real, the document was not the one under test.

    It surfaced only when a metamorphic oracle compared two runs and the
    difference named `0.25.0` and commit `ec2b918` - a version and a SHA that
    exist in this repository's history and in no generated one.
    """
    try:
        return subprocess.run(
            [PY, str(repo / "tools/extant_collect.py"), *mode,
             "--repo", str(repo)],
            cwd=str(repo),
            capture_output=True, text=True, timeout=TIMEOUT,
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return None


def check(repo: Path, mode: list[str]) -> list[tuple[str, str]]:
    """Every property that must hold, whatever the right answer is."""
    faults: list[tuple[str, str]] = []
    first = run_mode(repo, mode)
    if first is None:
        return [("HANG", f"{' '.join(mode)}: no answer in {TIMEOUT}s")]
    out = (first.stdout or "") + (first.stderr or "")

    if "Traceback (most recent call last)" in out:
        tail = [l for l in out.strip().splitlines() if l.strip()]
        return [("CRASH", f"{' '.join(mode)}: {tail[-1][:110]}")]
    # 0 clean, 1 findings, 2 the configuration is unreadable. The third is
    # deliberate and is the whole point of having it: a broken config must not
    # be reported as either a clean run or a run with findings. This harness
    # first flagged exit 2 as a fault, which was the harness being wrong.
    if first.returncode not in (0, 1, 2):
        faults.append(("EXIT", f"{' '.join(mode)}: exit {first.returncode}"))

    # ERRORED: a run naming a rule that RAISED never exits 0. Stated in
    # `registry.py`, printed by `session.report_rule_errors`, enforced in
    # `gate.py` with the comment that a partial answer reporting success is the
    # failure this whole project exists to prevent - and fuzzed nowhere.
    if "ERRORED:" in out and first.returncode == 0:
        faults.append(("ERRORED",
                       f"{' '.join(mode)}: a rule raised and the run still "
                       f"exited 0"))
    # EXIT: findings and the exit code have to agree. Any of 0, 1 or 2 used to
    # pass for any mode, so a run that printed findings and exited 0 would have
    # gone unremarked. Gating modes only: `--sweep` surveys and reports without
    # gating, which is its documented job.
    if mode[0] in ("--validate", "--verify"):
        printed = bool(re.search(r"^(?:.*: )?line \d+: \[", out, re.M))
        if printed and first.returncode == 0:
            faults.append(("EXIT", f"{' '.join(mode)}: findings printed and "
                                   f"the run exited 0"))
        if not printed and first.returncode == 1:
            faults.append(("EXIT", f"{' '.join(mode)}: exited 1 with no "
                                   f"finding printed"))
    counts = _rule_counts(out)
    faults.extend(_denominator_faults(out, counts, " ".join(mode)))
    # Findings printed against NO denominator at all. Without this the
    # DENOMINATOR loop below iterates nothing and reports success, which is the
    # same fail-open shape `mutate.py` refuses when an anchor stops matching.
    #
    # Deliberately narrower than "this mode owes a denominator". A sweep of a
    # repository git tracks no markdown in prints none and is RIGHT to: it
    # examined no documents, and `tests/test_fuzz_findings.py` pins that
    # behaviour. Faulting on the absence alone reported those runs, which is
    # the harness crying wolf about the case it already agreed was correct.
    # Keyed on findings existing instead, which has no such exemption to make.
    findings_printed = re.search(r"^(?:.*: )?line \d+: \[", out, re.M)
    if findings_printed and not counts and mode[0] in MODES_WITH_DENOMINATOR:
        faults.append(("HARNESS",
                       f"{' '.join(mode)}: findings printed with no "
                       f"denominator line, so DENOMINATOR checked nothing"))

    # metamorphic: nothing changed, so nothing may change
    second = run_mode(repo, mode)
    if second is None:
        faults.append(("HANG", f"{' '.join(mode)}: second run did not finish"))
    elif (second.stdout or "") != (first.stdout or ""):
        faults.append(("UNSTABLE",
                       f"{' '.join(mode)}: two runs, two answers"))

    # metamorphic: SARIF is JSON, and counts what the text output counted
    # A run that REFUSED is exempt, and the distinction is the whole point.
    #
    # Two shapes look alike from outside and are opposites. A sweep of a
    # repository with no tracked markdown RAN, examined nothing and concluded
    # nothing is wrong - that is a result, and a result a machine consumer
    # cannot read is the defect this harness found first. A run that refused,
    # because the config is unparseable or because it excludes the document it
    # is told to gate on, produced NO result; emitting a SARIF document there
    # would assert a clean scan that never happened, which is worse than
    # emitting nothing and is the failure extant exists to refuse.
    #
    # Recognised structurally rather than by message: nothing on stdout, a
    # diagnostic on stderr, a non-zero exit. Refusals are counted and printed
    # so the exemption stays visible instead of quietly widening.
    refused = refused_early(first)
    if refused:
        faults.append(("refused", f"{' '.join(mode)}: declined to run"))
        return [f for f in faults if f[0] != "refused"] or [("refused", "")]
    if "--format=sarif" in mode:
        try:
            doc = json.loads(first.stdout or "")
        except (json.JSONDecodeError, ValueError) as exc:
            faults.append(("SARIF", f"stdout is not JSON: {exc}"))
        else:
            plain = run_mode(repo, [m for m in mode if m != "--format=sarif"])
            if plain is not None:
                n = sum(len(r.get("results", []))
                        for r in doc.get("runs", []))
                # Two shapes, both correct. `format_text` prints a finding
                # in the PRIMARY document bare - "line 3: [kind] ..." - and
                # prefixes everything else with its path, an asymmetry that
                # module documents as deliberate and that its tests pin. A
                # pattern demanding the prefix silently undercounts every
                # configured document, which is how this comparison first
                # accused extant of losing a finding it had reported
                # correctly. The path half also has to tolerate spaces.
                text_findings = len(re.findall(r"^(?:.*: )?line \d+: \[",
                                               plain.stdout or "", re.M))
                if n != text_findings:
                    faults.append(("FORMATS",
                                   f"sarif {n} results, text {text_findings}"))
    return faults


def all_faults(repo: Path, mode):
    """Every fault the run counts, from ONE function, plus the sweep probe.

    The driver and the shrinker have to judge by the same predicate, and the
    first version of Stage 2 did not: `check` was the shrinker's whole
    definition of a violation, while the driver ALSO ran a plain `--sweep`
    probe and reported denominator faults from that. So every DENOMINATOR
    violation the probe found - which is most of them, because it is the run
    that sees every repository whatever mode it drew - was invisible to
    shrinking, `_still_fails` answered False for every subset, and ddmin
    reported that no feature could be dropped.

    That is the defect this project calls "one claim, two scanners", found in
    the harness written to find it. Returns (faults, probed counts, probe
    output) so the driver still gets the ledger numbers it needs.
    """
    found = check(repo, list(mode))
    if found and found[0][0] == "refused":
        return found, {}, "", {}
    probe = run_mode(repo, ["--sweep"])
    probe_out = ((probe.stdout or "") + (probe.stderr or "")
                 if probe is not None else "")
    probed = _rule_counts(probe_out)
    found = list(found) + _denominator_faults(probe_out, probed,
                                              "--sweep (probe)")
    # The metamorphic oracles. They live here rather than in `check` so that
    # the driver, the shrinker and `--replay` all see them through the one
    # predicate - which means a new oracle gets ddmin reduction and replay for
    # free rather than needing its own wiring.
    skipped: dict = {}
    if ORACLES_ON:
        more, skipped = oracles.run_all(run_mode, repo)
        found = found + more
    return found, probed, probe_out, skipped


# --- shrinking --------------------------------------------------------

# Properties ddmin may bisect on, and the omission is the point. `UNSTABLE`
# exists precisely BECAUSE a run disagreed with itself, so a bisect guided by
# it follows noise and reports a minimal feature set that reproduces nothing -
# which is worse than reporting the unshrunk one, because it looks like an
# answer. `HANG` is excluded for the same reason from the other direction: a
# timeout is a measurement of the machine as much as of the repository.
#
# A violation of either is reported at full size, and says so.
SHRINKABLE = ("CRASH", "DENOMINATOR", "EXIT", "FORMATS", "SARIF", "HARNESS",
              "ERRORED", "FENCE", "SHIFT", "CRLF", "RELOCATE", "MONOTONE",
              "BASELINE", "PROCESS", "MODE-AGREE", "DENOM-AGREE", "GITHUB")

# Rebuilds are not free. Each one is a whole repository plus the four or so
# process spawns `all_faults` makes, which is roughly ten seconds on Windows -
# so a ceiling of 60 is ten minutes PER VIOLATION, and a run with several
# violations stops being something anyone waits for. Measured and lowered.
#
# ddmin is O(n^2) in the worst case over a 13-element set, which is small; the
# ceiling is what makes that a promise rather than an expectation.
SHRINK_CEILING = 30


def fault_signature(kind: str, detail: str) -> tuple:
    """What counts as THE SAME violation when shrinking.

    Kind alone is too coarse, and measurably so. `DENOMINATOR` covers every
    rule that reports more than it examined, so a bisect targeting it accepted
    any repository that produced any such violation - and reported that a
    `raw-lfs-blob` fault shrank to the `consistency` feature, which merely
    produces an `inconsistent-artifact` fault of the same shape. A confident,
    checkable, wrong answer: the reduced plan reproduces A violation and not
    THE one.

    Kind plus the rule named in the detail. Faults that name no rule - CRASH,
    EXIT - fall back to kind alone, which is the right granularity for them.
    """
    for rule in shapes.RULE_KINDS:
        if rule in detail:
            return (kind, rule)
    return (kind, "")


def _still_fails(pkg: Path, arena: Path, plan: RepoPlan, signature: tuple):
    """Does this plan still violate the SAME property? None if it did not build.

    Same kind, not same message: a shrunk repository legitimately reports a
    different rule or a different count, and demanding the whole string back
    would refuse every reduction that actually worked.

    THREE ANSWERS, NOT TWO, and the third is why. This returned False on a
    build failure at first, which reads as "that subset does not reproduce" -
    so when every rebuild was dying on a Windows `FileExistsError`, ddmin
    concluded that no feature could be dropped and reported the unshrunk set as
    minimal. A confident wrong answer, from the same fail-open shape this
    harness keeps finding elsewhere. `None` is "I could not tell", and the
    caller counts and prints those rather than folding them into a verdict.
    """
    try:
        repo, recipe = build_from_plan(pkg, arena, plan)
    except (OSError, ValueError):
        return None
    if recipe.broken:
        return None
    found, _probed, _out, _skipped = all_faults(repo, plan.mode)
    for found_kind, found_detail in found:
        if fault_signature(found_kind, found_detail) == signature:
            return True
    return False


def shrink(pkg: Path, arena: Path, plan: RepoPlan,
           signature: tuple):
    """The minimizing delta debugging algorithm over the drawn feature set.

    ddmin bisects a set of atomic units while preserving an interesting
    property, and this harness has had that set of units since the catalogue
    landed - the features are the atoms, and dropping one is a legal
    repository. So the implementation is the standard loop over rebuild and
    recheck, with no shrinking-specific machinery at all.

    Returns (features, rebuilds, exhausted, unbuildable). `exhausted` says the
    ceiling stopped it, so the answer is A smaller reproduction rather than THE
    smallest - a distinction worth printing rather than rounding off.
    `unbuildable` counts the subsets that could not be built at all, which is
    neither a reduction nor a refusal and must not be reported as either.
    """
    items = list(plan.features)
    budget = [SHRINK_CEILING]
    unbuildable = [0]

    # THE BASELINE FIRST. Without it, a plan that does not reproduce at all -
    # a violation that needed the arena in some state, or one of the
    # properties this list should not have admitted - explores the whole
    # lattice, finds nothing, and reports "no smaller feature set reproduces
    # it". Which is exactly what a violation genuinely caused by every feature
    # reports. Two opposite findings, one sentence.
    baseline = _still_fails(pkg, arena, plan, signature)
    if baseline is not True:
        return (tuple(items), 1, False, 1 if baseline is None else 0, False)

    def fails(subset) -> bool:
        if budget[0] <= 0:
            return False
        budget[0] -= 1
        keep = {name for name, _ in subset}
        dropped = [name for name, _ in items if name not in keep]
        answer = _still_fails(pkg, arena, plan.without(dropped),
                              signature)
        if answer is None:
            unbuildable[0] += 1
            return False
        return answer

    granularity = 2
    while len(items) >= 2 and budget[0] > 0:
        size = max(1, len(items) // granularity)
        chunks = [items[i:i + size] for i in range(0, len(items), size)]
        reduced = False
        for chunk in chunks:
            complement = [i for i in items if i not in chunk]
            if not complement:
                continue
            if fails(complement):
                items = complement
                granularity = max(granularity - 1, 2)
                reduced = True
                break
        if reduced:
            continue
        if granularity >= len(items):
            break
        granularity = min(granularity * 2, len(items))
    return (tuple(items), SHRINK_CEILING - budget[0], budget[0] <= 0,
            unbuildable[0], True)


def run_replay(pkg: Path, arena: Path, path: Path) -> int:
    """`--replay FILE`: rebuild exactly one repository and check it again.

    The artifact CI uploads on failure used to be prose - a list of sentences
    describing what a repository had contained, which a human could read and
    nothing could execute. This is the other end of that: the same file, fed
    back, produces the repository.
    """
    try:
        plan = RepoPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"cannot read {path}: {exc}")
        return 2
    arena.mkdir(parents=True, exist_ok=True)
    print(f"replaying repository {plan.index:03d} from {path}")
    here = payload_digest(pkg)
    if plan.payload and plan.payload != here:
        # Said, not enforced. Replaying against a CHANGED payload is the whole
        # point when the question is "did the fix work" - what would be wrong
        # is doing it without knowing.
        print(f"  payload {here}, plan was built against {plan.payload} - "
              f"DIFFERENT, so a clean result here means this payload, not "
              f"this plan, changed")
    elif plan.payload:
        print(f"  payload {here}, same as the plan was built against")
    print(f"  repo_seed {plan.repo_seed}, state {plan.state}, "
          f"mode {' '.join(plan.mode)}")
    print(f"  {len(plan.features)} feature(s): "
          f"{', '.join(n for n, _ in plan.features) or 'none'}")
    repo, recipe = build_from_plan(pkg, arena, plan)
    if recipe.broken:
        print(f"  UNBUILT: {recipe.broken[0]}")
        return 2
    print(f"  built at {repo}")
    found, _probed, _out, _skipped = all_faults(repo, plan.mode)
    found = [f for f in found if f[0] != "refused"]
    if not found:
        print("  no property violation - this plan does not reproduce one")
        return 0
    for kind, detail in found:
        print(f"  {kind:<12} {detail}")
    return 1


def run_differential(pkg: Path, arena: Path, spec: str, seed: int,
                     repos: int) -> int:
    """`--differential [REF|DIR]`: the same corpus through two versions.

    Stage 4. No oracle is required and none is used: this asks whether the
    answer CHANGED, not whether it is right, and a human reads which
    differences were intended. It is the only check here that notices a rule
    going quiet, because a rule reporting nothing is self-consistent under
    every metamorphic comparison the other properties make.

    The corpus is drawn exactly as a normal run draws it - same seed, same
    walk over (git state, mode) pairs - so `--differential --seed N` and
    `--seed N` build the same repositories and a difference can be taken back
    to a plan. Each repository is then built TWICE at one arena path, once per
    version; fuzz_differential.py carries the argument for why it rebuilds
    rather than swapping `tools/` in place.

    Shrinking and the oracles are not run. Both exist to reduce and explain a
    property violation, and a difference is not one: there is nothing to
    bisect toward when the question is which of two versions is right.
    """
    arena.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent.parent.parent
    target = spec or differential.latest_tag(source)
    if not target:
        print("no tag is reachable from HEAD, so there is no previous release "
              "to compare against. Pass a ref or a directory explicitly.")
        return 2
    try:
        base_pkg, base_label = differential.materialise(
            target, source, arena / "_baseline")
    except ValueError as exc:
        print(f"cannot prepare the baseline: {exc}")
        return 2

    head_digest = payload_digest(pkg)
    base_digest = payload_digest(base_pkg)
    print(f"seed {seed}   (reproduce with --seed {seed})")
    print(f"head payload {head_digest}")
    print(f"base payload {base_digest}   ({base_label})")
    if head_digest == base_digest:
        # Said rather than refused. Comparing a payload against itself is the
        # CONTROL - two builds, two sets of commit SHAs, one payload, and a
        # result that must be zero differences - and refusing it would remove
        # the only way to find out that this comparison reports noise.
        print("  IDENTICAL PAYLOADS - this is the control run. Zero "
              "differences is the only correct outcome; anything else is "
              "normalisation reporting noise, not a change in the tool.")
    print(f"building {repos} repository(s) twice each\n")

    rng = random.Random(seed)
    plan: list[tuple[str, list[str]]] = [(s, m) for s in GIT_STATES
                                         for m in MODES]
    rng.shuffle(plan)
    while len(plan) < repos:
        plan.append((rng.choice(GIT_STATES), rng.choice(MODES)))
    plan = plan[:repos]

    differences: list[tuple[int, str, str]] = []
    compared = 0
    unbuilt = 0
    # What the comparison actually had to compare. See `observed`: two
    # silences compare equal, and without this they print as agreement.
    findings_seen = 0
    examined_seen = 0
    mismatched = 0
    for index, (state, planned_mode) in enumerate(plan):
        repo_plan = draw_plan(rng, index, state, planned_mode, head_digest)
        repo, recipe = build_from_plan(pkg, arena, repo_plan)
        if recipe.broken:
            unbuilt += 1
            print(f"  [{index:03d}] UNBUILT head  {recipe.broken[0][:80]}")
            continue
        head_report = differential.observe(repo, planned_mode, run_mode)
        head_repo = repo

        repo, recipe = build_from_plan(base_pkg, arena, repo_plan)
        if recipe.broken:
            unbuilt += 1
            print(f"  [{index:03d}] UNBUILT base  {recipe.broken[0][:80]}")
            continue
        # THE TWO REPOSITORIES BEFORE THE TWO ANSWERS. A build whose
        # non-core git steps lost a race produces a repository missing a ref,
        # and comparing outputs across that pair blames the versions for the
        # build. `fingerprint` carries the instance this was found by.
        if differential.fingerprint(head_repo) != differential.fingerprint(repo):
            mismatched += 1
            print(f"  [{index:03d}] BUILD     the two builds differ as "
                  f"repositories, so this pair was not compared")
            continue
        base_report = differential.observe(repo, planned_mode, run_mode)

        compared += 1
        for report in (head_report, base_report):
            found, counts = differential.observed(report)
            findings_seen += found
            examined_seen += counts
        for kind, detail in differential.compare(head_report, base_report):
            differences.append((index, kind, detail))
            print(f"  [{index:03d}] {kind:<9} {detail}")

    differential.summarise(differences, compared, unbuilt, base_label,
                           (findings_seen, examined_seen), mismatched)
    # A run that compared nothing is a harness fault, not a clean result - the
    # same distinction CORPUS_FLOOR draws for the main driver. Without it an
    # arena the builds cannot use reports "0 differences" and reads as green.
    if not compared:
        return 2
    return 1 if differences else 0


# --- driver -----------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pkg", type=Path)
    ap.add_argument("arena", type=Path)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--repos", type=int, default=24)
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--replay", type=Path, default=None,
                    help="rebuild one repository from a saved plan and recheck")
    ap.add_argument("--no-shrink", action="store_true",
                    help="report a violation at full size, without ddmin")
    ap.add_argument("--no-oracles", action="store_true",
                    help="skip the metamorphic oracles (they cost runs)")
    ap.add_argument("--differential", nargs="?", const="", default=None,
                    metavar="REF|DIR",
                    help="diff this package's findings against another "
                         "version's over one corpus; defaults to the newest "
                         "tag reachable from HEAD")
    args = ap.parse_args()

    global ORACLES_ON
    ORACLES_ON = not args.no_oracles

    if args.replay is not None:
        return run_replay(args.pkg, args.arena, args.replay)

    seed = args.seed if args.seed is not None else random.randrange(2 ** 31)

    if args.differential is not None:
        return run_differential(args.pkg, args.arena, args.differential,
                                seed, args.repos)
    rng = random.Random(seed)
    args.arena.mkdir(parents=True, exist_ok=True)
    payload = payload_digest(args.pkg)

    print(f"seed {seed}   (reproduce with --seed {seed})")
    print(f"payload {payload}")
    print(f"building {args.repos} hostile repositories\n")

    faults: list[tuple[int, str, str]] = []
    unbuildable: dict[str, int] = {}
    reached: dict[str, int] = {}
    oracle_skips: dict = {}
    broken_builds: list = []
    drawn_features: dict[str, int] = {}
    modes_run = 0
    examined_somewhere = 0
    refusals = 0
    built = 0

    # Every (git state, mode) pair once, THEN random draws with whatever
    # budget is left.
    #
    # Purely random selection made the harness's coverage a lottery, and the
    # lottery lost: the first genuine finding here was an empty SARIF document
    # from a repository with no tracked markdown, and the fixed CI seed never
    # drew that state together with that format, so re-running it against the
    # unfixed code reported zero violations. A gate that cannot reach the bug
    # it already found is not evidence of anything.
    #
    # Walking the product also gives this harness a denominator it can print:
    # how many of the pairs it actually exercised, rather than how many
    # repositories it happened to build.
    plan: list[tuple[str, list[str]]] = [(s, m) for s in GIT_STATES
                                         for m in MODES]
    rng.shuffle(plan)
    while len(plan) < args.repos:
        plan.append((rng.choice(GIT_STATES), rng.choice(MODES)))
    plan = plan[:args.repos]
    pairs_possible = len(GIT_STATES) * len(MODES)
    pairs_seen: set[tuple[str, str]] = set()

    for index, (state, planned_mode) in enumerate(plan):
        # Decide, then build. The plan is written down before anything touches
        # the disk, so a repository that fails can be handed back as a file
        # rather than as a position in this loop.
        repo_plan = draw_plan(rng, index, state, planned_mode, payload)
        repo, recipe = build_from_plan(args.pkg, args.arena, repo_plan)
        for note in recipe.skipped:
            key = note.split(" (")[0]
            unbuildable[key] = unbuildable.get(key, 0) + 1
        for note in recipe.features:
            name = note.split(":")[0]
            drawn_features[name] = drawn_features.get(name, 0) + 1
        # A repository whose core git steps failed is NOT a hostile repository
        # the tool survived - it was never built, and every property checked
        # against it would be measuring an empty directory. Excluded from the
        # corpus entirely rather than checked and counted, which is the same
        # treatment a shape this platform cannot construct already gets: NOT
        # TESTED, reported in its own column, never a pass.
        if recipe.broken:
            broken_builds.append((index, recipe.broken[0]))
            print(f"  [{index:03d}] UNBUILT      {recipe.broken[0][:96]}")
            continue
        built += 1
        mode = planned_mode
        pairs_seen.add((state, " ".join(mode)))
        modes_run += 1
        found, probed, _probe_out, skipped = all_faults(repo, mode)
        for name, why in skipped.items():
            oracle_skips[name] = oracle_skips.get(name, 0) + 1
        if found and found[0][0] == "refused":
            refusals += 1
            found = []
        if probed:
            examined_somewhere += 1
        # THE REACH LEDGER. Which rules actually examined a candidate, not how
        # many repositories produced counts of any kind - a repository
        # exercising one rule and one exercising twelve were the same number
        # before this, which is how 8 of 13 rules went unreached without
        # anything saying so.
        for kind, n in probed.items():
            if n:
                reached[kind] = reached.get(kind, 0) + 1
        for kind, detail in found:
            faults.append((index, kind, detail))
            print(f"  [{index:03d}] {kind:<12} {detail}")
            saved = repo_plan
            # SHRINK, then save what shrinking produced. A violation arrives
            # attached to whatever the swarm happened to draw - often eight or
            # nine features, most of them irrelevant - and the reduced plan is
            # what somebody can actually read. Runs only on a violation, so a
            # green run pays nothing for it.
            if kind in SHRINKABLE and not args.no_shrink:
                signature = fault_signature(kind, detail)
                smaller, rebuilds, exhausted, unjudged, reproduced = shrink(
                    args.pkg, args.arena, repo_plan, signature)
                if not reproduced:
                    print(f"           NOT SHRUNK: rebuilding this plan does "
                          f"not reproduce {kind}, so there is nothing to "
                          f"bisect. The violation depends on something the "
                          f"plan does not capture.")
                elif len(smaller) < len(repo_plan.features):
                    saved = repo_plan.without(
                        [n for n, _ in repo_plan.features
                         if n not in {s for s, _ in smaller}])
                    names = ", ".join(n for n, _ in smaller) or "none"
                    print(f"           shrunk {len(repo_plan.features)} -> "
                          f"{len(smaller)} feature(s) in {rebuilds} rebuild(s)"
                          f"{' (ceiling reached)' if exhausted else ''}: "
                          f"{names}")
                else:
                    print(f"           no smaller feature set reproduces it "
                          f"({rebuilds} rebuild(s))")
                if unjudged:
                    print(f"           {unjudged} subset(s) could not be "
                          f"built, so shrinking could not judge them - the "
                          f"reduction above is a floor, not a minimum")
                # The repository on disk is now whichever plan shrinking built
                # last, not the one reported above. Rebuild the saved plan so
                # what is left in the arena matches what the file describes.
                build_from_plan(args.pkg, args.arena, saved)
            elif kind in ("UNSTABLE", "HANG"):
                print(f"           not shrunk: {kind} is not deterministic, "
                      f"and bisecting on it would follow noise")
            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                # Per FAULT, not per repository. Indices 014 and 025 of
                # one measured run each reported two, so a single name meant
                # the second overwrote the first and the surviving file
                # described a different violation from the one above it.
                named = "-".join(x for x in fault_signature(kind, detail) if x)
                slug = re.sub(r"[^a-z0-9]+", "-", named.lower()).strip("-")
                target = (args.save /
                          f"seed{seed}-{index:03d}-{slug}.json")
                target.write_text(json.dumps(saved.to_dict(), indent=2),
                                  encoding="utf-8")
                print(f"           replay with --replay {target}")
        if not found:
            print(f"  [{index:03d}] ok           {' '.join(mode)}")

    print("\n" + "=" * 70)
    print(f"seed {seed}: {built} repositories built, {modes_run} mode run(s)")
    # The denominator for the fuzzer itself. A run where extant examined
    # nothing anywhere is a broken generator printing what a clean one prints.
    print(f"  {examined_somewhere} of {built} repositories produced rule "
          f"counts, so the generator reached the rules")
    print(f"  {len(pairs_seen)} of {pairs_possible} (git state, mode) pairs "
          f"exercised")
    print(f"  {refusals} run(s) declined to start - a config conflict or an "
          f"unreadable config, reported and not counted as a fault")
    if len(pairs_seen) < pairs_possible:
        print(f"    raise --repos to at least {pairs_possible} to cover them "
              f"all; below that the gate is a sample, not a sweep")
    if unbuildable:
        print("  shapes this platform would NOT build, so they were NOT tested:")
        for shape, n in sorted(unbuildable.items()):
            print(f"    {n:3}  {shape}")
        print("  (the CI job runs on Linux, where these build)")
    else:
        print("  every shape built on this platform")
    # The reach ledger, printed whether or not it fails, because the number is
    # the point even on a green run.
    missed = [k for k in shapes.RULE_KINDS if k not in reached]
    claimed = shapes.rules_claimed()
    print(f"  {len(reached)} of {len(shapes.RULE_KINDS)} rules examined "
          f"something somewhere")
    if missed:
        # Two different failures, and the fix is not the same for both. A rule
        # NO feature aims at is a hole in the catalogue. A rule some feature
        # claims and did not reach is a feature that has stopped working - the
        # `Release ... shipped.` case, which matched nothing for as long as
        # this harness has existed.
        unaimed = [k for k in missed if k not in claimed]
        aimed = [k for k in missed if k in claimed]
        if unaimed:
            print(f"    no feature aims at: {', '.join(unaimed)}")
        if aimed:
            print(f"    AIMED AT AND NOT REACHED: {', '.join(aimed)} - a "
                  f"feature exists and did not fire")
        for kind in aimed:
            if kind in KNOWN_UNREACHABLE:
                print(f"      {kind}: exempt - {KNOWN_UNREACHABLE[kind]}")
    undrawn = [f.name for f in shapes.FEATURES if f.name not in drawn_features]
    if undrawn:
        # Separates "the swarm never drew it" from "it was drawn and did not
        # fire", which look identical in the ledger above and want opposite
        # fixes: more repositories, or a repaired feature.
        print(f"    never drawn at this repo count: {', '.join(undrawn)}")
    if ORACLES_ON:
        held = len(oracles.ORACLES) - len(oracle_skips)
        print(f"  {held} of {len(oracles.ORACLES)} metamorphic oracles ran on "
              f"every repository; those that ever stood aside:")
        if not oracle_skips:
            print("    none - all of them applied everywhere")
        for name, n in sorted(oracle_skips.items(), key=lambda kv: -kv[1]):
            print(f"    {n:3}  {name}")
    print(f"  {len(faults)} property violation(s)")
    print("=" * 70)

    if examined_somewhere == 0 and built:
        print("HARNESS FAULT: extant examined nothing in any repository, so "
              "this run proves nothing. Fix the generator before reading the "
              "result above as clean.")
        return 2
    # A corpus that is MOSTLY dead, which the zero test above cannot see.
    #
    # Two identical invocations of this harness - same seed, same package, same
    # machine - produced 25 of 35 repositories reaching the rules on one run
    # and 6 on another, and the 6-repository run exited 0 while reporting 13 of
    # 13 rules and no violations. It read exactly like the healthy run. Only
    # the totally dead run was caught, because the only corpus-health test here
    # was a test for zero.
    #
    # The collapse is real and not yet root-caused: repositories drawing the
    # `lfs-blob` feature end with a single commit and no tracked markdown, so
    # the whole build dies rather than that one feature, and the "could not
    # build" column blames `merge-claim` - a downstream victim that needs a
    # branch the collapsed build never created. Isolated, the shape builds
    # twelve times out of twelve, so it needs the rest of the generator to
    # reproduce.
    #
    # This floor does not fix that. It stops a degraded corpus reporting as a
    # clean one while it is being fixed, which is the difference between a gate
    # and a decoration.
    # Construction failures, reported BEFORE any verdict. A repository whose
    # `git add` failed is not a hostile repository the tool survived, it is a
    # repository that was never built - and every number computed from it is
    # about nothing.
    if broken_builds:
        print(f"  {len(broken_builds)} repositor(y/ies) FAILED TO BUILD - a core "
              f"git step returned non-zero:")
        for index, why in broken_builds[:5]:
            print(f"    [{index:03d}] {why}")
        if len(broken_builds) > 5:
            print(f"    ... and {len(broken_builds) - 5} more")
        print("    On Windows this is usually MAX_PATH: use a SHORT arena path. "
              "The repositories carry tools/extant/rules/ and a full object "
              "store, so a deep arena tips individual writes over 260 "
              "characters.")

    # Fails only when the corpus is mostly unbuilt, for the same reason
    # CORPUS_FLOOR exists: one marginal write failure on a deep path is a shape
    # this platform would not construct, and the run still measured 34 others.
    # A third of them failing means the run is about the filesystem, not the
    # tool.
    if broken_builds and len(broken_builds) > len(plan) * 0.2:
        print(f"HARNESS FAULT: {len(broken_builds)} of {len(plan)} repositories "
              f"did not build. Nothing above describes the tool.")
        return 2
    if built and examined_somewhere < built * CORPUS_FLOOR:
        print(f"HARNESS FAULT: only {examined_somewhere} of {built} "
              f"repositories reached the rules, below the {CORPUS_FLOOR:.0%} "
              f"this gate needs to mean anything. The corpus is degraded, not "
              f"the tool - read no result above as clean.")
        return 2
    # A feature that was DRAWN and still reached nothing fails the run, whatever
    # the floor says. The floor alone did not catch this: restoring the dead
    # merge spelling on purpose left the ledger at 11 of 13, which met the
    # floor, so the run exited 0 while printing the very line that named the
    # broken feature. A number that reports a defect without failing on it is
    # the reassuring zero this project keeps removing.
    silent = sorted(
        kind for feature in shapes.FEATURES if feature.name in drawn_features
        for kind in feature.rules
        if kind not in reached and kind not in KNOWN_UNREACHABLE)
    if silent:
        print(f"HARNESS FAULT: {', '.join(silent)} - a feature aiming at each "
              f"was drawn and none of them examined anything. The feature has "
              f"stopped firing; fix it, or exempt it in KNOWN_UNREACHABLE with "
              f"the reason.")
        return 2
    # Raise REACH_FLOOR deliberately, with a reason, never quietly.
    if len(reached) < REACH_FLOOR:
        print(f"HARNESS FAULT: {len(reached)} rules reached, floor is "
              f"{REACH_FLOOR}. Either a feature stopped firing or the draw was "
              f"unlucky - re-run with more --repos before editing the floor.")
        return 2
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
