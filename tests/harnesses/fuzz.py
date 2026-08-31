"""Fuzzing: build hostile repositories at random and check what must hold.

    python tests/harnesses/fuzz.py <extracted-package> <scratch-dir> [options]
      --seed N       reproduce one run exactly (printed by every run)
      --repos N      how many repositories to build (default 24)
      --save DIR     write a failing repository's recipe here

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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fuzz_shapes as shapes  # noqa: E402

PY = sys.executable
TIMEOUT = 90

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


def build_repo(pkg: Path, arena: Path, rng: random.Random,
               seed: int, index: int,
               state: str | None = None) -> tuple[Path, Recipe]:
    """One randomly hostile repository. Returns it and what went into it."""
    recipe = Recipe(seed, index)
    repo = arena / f"fuzz{index:03d}"
    shutil.rmtree(repo, ignore_errors=True)
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

    drawn = _draw_features(rng)
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
        shutil.rmtree(inner, ignore_errors=True)
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
        shutil.rmtree(linked, ignore_errors=True)
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
        shutil.rmtree(cloned, ignore_errors=True)
        r = sh(arena, "git", *LONGPATHS, "clone", "-q", "--depth", "1",
               repo.as_uri(), str(cloned))
        if r.returncode == 0 and cloned.exists():
            shutil.copytree(pkg / "plugin/skills/extant/payload",
                            cloned / "tools", dirs_exist_ok=True)
            recipe.did("shallow clone (validated instead of the origin)")
            return cloned, recipe
        recipe.could_not("shallow clone", "git refused")
    elif state == "empty":
        # a repository with no commit at all reaches rules that assume HEAD
        bare = arena / f"empty{index:03d}"
        shutil.rmtree(bare, ignore_errors=True)
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
    try:
        return subprocess.run(
            [PY, str(repo / "tools/extant_collect.py"), *mode,
             "--repo", str(repo)],
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


# --- driver -----------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pkg", type=Path)
    ap.add_argument("arena", type=Path)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--repos", type=int, default=24)
    ap.add_argument("--save", type=Path, default=None)
    args = ap.parse_args()

    seed = args.seed if args.seed is not None else random.randrange(2 ** 31)
    rng = random.Random(seed)
    args.arena.mkdir(parents=True, exist_ok=True)

    print(f"seed {seed}   (reproduce with --seed {seed})")
    print(f"building {args.repos} hostile repositories\n")

    faults: list[tuple[int, str, str]] = []
    unbuildable: dict[str, int] = {}
    reached: dict[str, int] = {}
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
        repo, recipe = build_repo(args.pkg, args.arena, rng, seed, index,
                                  state=state)
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
        found = check(repo, mode)
        if found and found[0][0] == "refused":
            refusals += 1
            found = []
        # Fixed mode on purpose. Asking whether the randomly chosen mode
        # printed rule counts measured the MODE - `--selftest`, `--format=
        # github` and `--deleted-since` never print that line - and read as a
        # generator producing unanalysable repositories when it was not.
        probe = run_mode(repo, ["--sweep"])
        probe_out = ((probe.stdout or "") + (probe.stderr or "")
                     if probe is not None else "")
        probed = _rule_counts(probe_out)
        if probed:
            examined_somewhere += 1
        # The denominator is checked HERE as well as in the planned mode, and
        # this is the run that actually covers it. Features are drawn
        # independently of the mode a repository is assigned, so a repository
        # whose claims expose a denominator bug is as likely as not to draw a
        # mode that cannot show one: `--format=github` emits annotations and no
        # counts, `--selftest` and `--deleted-since` print none either. Seed
        # 20260824 built a repository reporting two `dead-md-anchor` findings
        # against a denominator of one and handed it `--sweep --format=github`,
        # so the violation was real, present, and invisible.
        #
        # This probe is a plain `--sweep`, already spawned for the ledger, and
        # it always prints counts. Checking it costs nothing and gives every
        # repository denominator coverage whatever mode it drew.
        for fault in _denominator_faults(probe_out, probed, "--sweep (probe)"):
            found.append(fault)
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
            if args.save:
                args.save.mkdir(parents=True, exist_ok=True)
                (args.save / f"seed{seed}-{index:03d}.json").write_text(
                    json.dumps(recipe.as_dict(), indent=2), encoding="utf-8")
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
