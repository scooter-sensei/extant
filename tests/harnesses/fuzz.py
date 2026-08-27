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

# Content shapes that have historically cost something: backtracking bait,
# claims of every kind, fences that do not close, and a line long enough to
# matter.
def _content_shapes(rng: random.Random) -> list[str]:
    return [
        "# Doc\n\nSee `src/gone.py` for detail.\n",
        "# Doc\n\nMerged `feature/x` into main at `deadbeef1234`.\n",
        "# Doc\n\nSee [link](../other/missing.md) and [a](a.md#nope).\n",
        "# Doc\n\nRelease `v9.9.9` shipped.\n",
        "# Doc\n\nRequires Python 3.99+.\n",
        "# Doc\n\n```\nunclosed fence with `src/gone.py` inside\n",
        "# Doc\n\n" + ("a" * rng.choice([200, 5_000, 60_000])) + "\n",
        "# Doc\n\n" + "".join(f"See `f{i}.py`. " for i in range(rng.randint(1, 40))) + "\n",
        "# Doc\n\nPointer at `tools/extant_collect.py:999999`.\n",
        "# Doc\n\n" + "\u202e" * 20 + " reversed prose `x.py`\n",
        "# Doc\n\nnested ``` ` `` ticks `src/gone.py` ``` here\n",
        "# H\n\n# H\n\n# H\n\nRepeated headings and [#h-2](#h-2).\n",
    ]

# Configuration a hostile or careless project might ship. The regexes are the
# backtracking bait the existing smoke probe covers as a single case; here they
# combine with everything else.
CONFIG_SHAPES = [
    'primary_doc = "NEXT_SESSION.md"\n',
    'primary_doc = "NEXT_SESSION.md"\npath_pointer = "(a+)+$"\n',
    'primary_doc = "NEXT_SESSION.md"\nentry_prefix = "## "\n',
    'primary_doc = "NEXT_SESSION.md"\nexclude_paths = ["**", "*.md"]\n',
    'primary_doc = "NEXT_SESSION.md"\nexclude_paths = ["nothing-matches-this"]\n',
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


# --- plumbing ---------------------------------------------------------

def sh(cwd: Path, *args: str, check: bool = False):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          check=check, encoding="utf-8", errors="replace")


class Recipe:
    """Everything needed to rebuild one repository, and what it could not build."""

    def __init__(self, seed: int, index: int) -> None:
        self.seed = seed
        self.index = index
        self.steps: list[str] = []
        self.skipped: list[str] = []

    def did(self, what: str) -> None:
        self.steps.append(what)

    def could_not(self, what: str, why: str) -> None:
        self.skipped.append(f"{what} ({why})")

    def as_dict(self) -> dict:
        return {"seed": self.seed, "index": self.index,
                "built": self.steps, "not_built": self.skipped}


def build_repo(pkg: Path, arena: Path, rng: random.Random,
               seed: int, index: int,
               state: str | None = None) -> tuple[Path, Recipe]:
    """One randomly hostile repository. Returns it and what went into it."""
    recipe = Recipe(seed, index)
    repo = arena / f"fuzz{index:03d}"
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    sh(repo, "git", "init", "-q", "-b", rng.choice(["main", "master", "trunk"]))
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "T")
    shutil.copytree(pkg / "plugin/skills/extant/payload", repo / "tools")

    shapes = _content_shapes(rng)
    (repo / "NEXT_SESSION.md").write_text(rng.choice(shapes), encoding="utf-8")
    # Weighted, not uniform. A config that cannot be parsed and a primary
    # document that does not exist both END the run before any rule executes,
    # so drawing them uniformly spent most of the corpus on the two shapes
    # that test the least. Measured at 2 of 12 repositories reaching the rules
    # before this weighting.
    config = (rng.choice(CONFIG_SHAPES[:5]) if rng.random() < 0.85
              else rng.choice(CONFIG_SHAPES[5:]))
    (repo / ".extant.toml").write_text(config, encoding="utf-8")
    recipe.did("primary document and config")

    # documents at awkward paths, in awkward directories
    made = 0
    for _ in range(rng.randint(1, 6)):
        name = rng.choice(AWKWARD_NAMES)
        parent = repo / rng.choice(["", "docs", "docs/deep/deeper",
                                    rng.choice(AWKWARD_NAMES)])
        try:
            parent.mkdir(parents=True, exist_ok=True)
            (parent / f"{name}.md").write_text(rng.choice(shapes),
                                               encoding="utf-8")
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

    sh(repo, "git", "add", "-A")
    sh(repo, "git", "commit", "-qm", "initial")

    # more commits, so ancestry rules have something to walk
    for i in range(rng.randint(0, 4)):
        (repo / f"f{i}.txt").write_text(f"{i}\n", encoding="utf-8")
        sh(repo, "git", "add", "-A")
        sh(repo, "git", "commit", "-qm", f"c{i}")

    # hostile refs: names that look like options, contain spaces or non-ASCII
    for ref in rng.sample(["-dashed-branch", "--option-branch", "with space",
                           "\u00fcnicode", "a/b/c/deep", "HEAD-ish",
                           "feature/x"], k=rng.randint(0, 4)):
        sh(repo, "git", "branch", "--", ref)
    for tag in rng.sample(["v1.0", "-v2", "tag with space", "\u00fctag",
                           "v9.9.9"], k=rng.randint(0, 3)):
        sh(repo, "git", "tag", "--", tag)
    recipe.did("hostile ref and tag names")

    # a submodule, when the transport allows one
    if rng.random() < 0.35:
        inner = arena / f"sub{index:03d}"
        shutil.rmtree(inner, ignore_errors=True)
        inner.mkdir(parents=True)
        sh(inner, "git", "init", "-q", "-b", "main")
        sh(inner, "git", "config", "user.email", "t@t")
        sh(inner, "git", "config", "user.name", "T")
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
        r = sh(arena, "git", "clone", "-q", "--depth", "1",
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
        sh(bare, "git", "init", "-q", "-b", "main")
        shutil.copytree(pkg / "plugin/skills/extant/payload", bare / "tools")
        (bare / "NEXT_SESSION.md").write_text(rng.choice(shapes),
                                              encoding="utf-8")
        recipe.did("repository with no commits")
        return bare, recipe

    return repo, recipe


# --- the properties ---------------------------------------------------

_EXAMINED = re.compile(r"examined: (.+)$", re.M)


def _rule_counts(text: str) -> dict[str, int]:
    m = _EXAMINED.search(text)
    if not m:
        return {}
    counts = {}
    for part in m.group(1).split(","):
        bits = part.strip().rsplit(" ", 1)
        if len(bits) == 2 and bits[1].isdigit():
            counts[bits[0]] = int(bits[1])
    return counts


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

    for kind, examined in _rule_counts(out).items():
        found = len(re.findall(r"\[" + re.escape(kind) + r"\]", out))
        if found > examined:
            faults.append(("DENOMINATOR",
                           f"{' '.join(mode)}: {kind} reported {found} "
                           f"from {examined} examined"))

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
    refused = (first.returncode != 0 and not (first.stdout or "").strip()
               and (first.stderr or "").strip())
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
        built += 1
        for note in recipe.skipped:
            key = note.split(" (")[0]
            unbuildable[key] = unbuildable.get(key, 0) + 1
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
        if probe is not None and _rule_counts(
                (probe.stdout or "") + (probe.stderr or "")):
            examined_somewhere += 1
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
    print(f"  {len(faults)} property violation(s)")
    print("=" * 70)

    if examined_somewhere == 0 and built:
        print("HARNESS FAULT: extant examined nothing in any repository, so "
              "this run proves nothing. Fix the generator before reading the "
              "result above as clean.")
        return 2
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
