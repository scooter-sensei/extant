"""Scopes replace the save-and-restore discipline in validate().

Every test here corresponds to a comment in the code being replaced, each of
which records a real bug: a nested call that cleared the caller's caches and
never gave them back, a tag created between two calls resolving to nothing, an
origin added between two calls leaving dead-pinned-ref examining nothing.

The behavioural half of that lives in tests/test_cache_lifetime.py and
tests/test_caching.py, which pin the properties through the RULES. What is
pinned here is the SHAPE that makes those properties structural rather than
guarded: two scopes are two objects, and a fresh one carries nothing.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parent.parent / "plugin" / "skills" / "extant" / "payload"
sys.path.insert(0, str(PAYLOAD))

# The inventory, and where each of the 26 module-level caches went. Written out
# because the count is the denominator of the emptiness test below, and a bare
# number nobody can reconstruct is a denominator that stops meaning anything the
# first time somebody adds a cache.
#
#   22  became RunScope fields (the list in scope.py, in this order)
#    3  stayed MODULE-LEVEL rather than becoming scope fields: _STRIPPED,
#       _BARE_SHAS and _POINTER_SITES. The first two are keyed on the IDENTITY
#       of the text passed in and read nothing else about the repository, so
#       they are pure memos that self-invalidate; giving them a scope would be
#       a lifetime they do not have. _POINTER_SITES is not pure - it reads the
#       filesystem through _line_count - but its consumer, count_examined,
#       runs AFTER validate() returns, so a value tied to the call's scope
#       would be discarded exactly when it is needed. See the comment beside
#       it.
#
#       Module-level, not necessarily in extant_collect.py, and that stopped
#       being the same statement in Task 8: _STRIPPED moved to extant/text.py
#       with the stripping functions that own it. Still a module-level memo,
#       still no lifetime to state, one file over. Task 9 moved the other two
#       the same way - _BARE_SHAS to extant/commits.py with the SHA scanners,
#       _POINTER_SITES to extant/rules/line_pointer.py with the rule and the
#       denominator that share it - and neither gained a lifetime by moving.
#    1  was deleted: _TAGS has been dead since 6c5c29c rewired _tags() through
#       _ref_table, and only the save-and-restore choreography still named it.
#
# Plus ONE field that migrated from nothing, listed separately so the 26 above
# still adds up:
#
#    1  `shas`, new in Task 7. SHA resolution was not cached at all, so two
#       rules asking about overlapping tokens spawned a `cat-file
#       --batch-check` each. It is counted as a cache field below because it is
#       one, and it starts empty like the rest.
CACHE_FIELDS = 23

# Not a cache. `stable` says whether a caller has taken ownership of this
# scope's lifetime for many documents, which is the old `_STABLE_SCOPE` boolean
# moved onto the object it describes. Excluded from the count above so the
# denominator keeps counting what it says it counts.
NOT_A_CACHE = {"stable"}

# Git invocations in the shim that do NOT go through the seam, because they
# need something `run(repo, *args)` cannot express. Named individually so this
# is a list somebody maintains rather than a number that drifts:
#
#   1  `git show`, which must return BYTES: `_git` passes text=True, which
#      makes subprocess decode inside a reader thread, so invalid UTF-8 raises
#      somewhere a caller cannot catch it
#
# Six until Task 8, when the third `cat-file` batch left with the code around
# it: `_batch_shas` backs `resolve_shas`, which moved to extant/refs.py so that
# the merge rule would not have to reach into the SHA rule for it. Five until
# Task 9, which took the other four with the raw-lfs-blob rule - the two
# `cat-file` batches, the `ls-tree -r -z` and the `check-attr -z --stdin`
# paired with it, all now in extant/rules/lfs.py. None of them stopped
# bypassing the seam by moving, so all four are still counted, one file over,
# as PACKAGE_DIRECT_SUBPROCESS_SITES below. Lowering this without raising that
# one would have retired four watched sites by losing track of them.
#
# The seam deliberately did not grow a method for these in Task 7. What it has
# to do is stay visible, because CountingGit cannot see them and neither will
# `--profile`; see test_the_rules_reach_git_only_through_the_seam.
DIRECT_SUBPROCESS_SITES = 1

# extant/git.py is the seam's own implementation, not a consumer of it: it is
# where `_git`/`_git_soft` are DEFINED and where `SubprocessGit` legitimately
# calls them, and it holds the one place in the whole package where
# `subprocess.run(["git", ...])` is correct to write literally. Asking
# whether it "bypasses" a seam it IS is not a coherent question, so it is
# scanned and pinned on its own below rather than lumped into the population
# that must route through `_GIT.run`/`.soft` with nothing left over - and
# rather than excluded from the scan by filename with no number attached.
#
# The direct-pattern regex cannot tell a definition from a call, so it also
# matches `def _git(` and `def _git_soft(` themselves - the one place those
# definitions legitimately exist. PACKAGE_SEAM_DIRECT_SITES is 5, not 3,
# because of that:
#
#   3  real internal calls - SubprocessGit.run -> _git, SubprocessGit.soft ->
#      _git_soft, and _git_soft's own try/except calling _git
#   2  the `def _git(` and `def _git_soft(` lines themselves
PACKAGE_SEAM_DIRECT_SITES = 5
PACKAGE_SEAM_OUTSIDE_SITES = 1

# The package's routed count: 8 in extant/collect.py (6 `run`, 2 `soft`) plus
# 9 in extant/refs.py, which Task 8 filled with the ancestry, ref-table, rename
# and object-resolution helpers the rules used to reach through this module for.
# config.py, finding.py, scope.py and __init__.py ask git nothing.
#
# Pinned as a floor for the same reason the shim's own assertion pins one
# below: a population that stopped reaching git entirely would still pass
# "nothing bypasses", proving nothing. It goes UP as rules move, not down -
# the calls are not disappearing, they are changing file.
PACKAGE_ROUTED_FLOOR = 17

# The package call sites that run git through subprocess directly, for the
# same reason the shim keeps one: they need something `Git.run(repo, *args)`
# cannot express. Named here rather than waved through, so a SIXTH cannot
# appear unnoticed - which is exactly what an `== 0` assertion would have done
# the moment the first one arrived:
#
#   1  `_batch_shas` in extant/refs.py - `cat-file --batch-check` fed on stdin
#   2  the two `cat-file` batches in extant/rules/lfs.py, likewise stdin-fed
#      and wanting bytes, since blob content is arbitrary
#   1  `ls-tree -r -z HEAD` in the same file, whose NUL-separated output pairs
#      with the next one
#   1  `check-attr -z --stdin filter`, also stdin-fed
#
# It was 1 until Task 9 moved raw-lfs-blob into the package; the split is where
# the code is, not a change in how many bypass the seam. DIRECT_SUBPROCESS_SITES
# above came down by exactly the four that arrived here.
PACKAGE_DIRECT_SUBPROCESS_SITES = 5

# The shim's own routed count, and it is a floor for the anti-vacuity reason
# rather than a target. It was 12 when Task 7 wrote this test and every rule
# still lived in extant_collect.py; Task 8 took the nine git-history helpers
# into extant/refs.py and left four (`_own_remote`, `validate_pinned_refs`,
# `_probe_merge`, `_changed_between`). Task 9 took three of those four with
# their rules - the first two to extant/rules/pinned_ref.py, the third to
# extant/rules/merge.py - leaving `_changed_between`, which belongs to
# `--deleted-since` rather than to any rule and goes in Task 10. At that point
# this number reaches zero and the assertion below has to be DELETED rather
# than set to 0 - a floor of zero is satisfied by an empty file, which is the
# shape of broken check this file exists to refuse.
SHIM_ROUTED_FLOOR = 1


def test_a_nested_run_scope_does_not_disturb_the_outer_one() -> None:
    """The bug the save-and-restore block exists to prevent, now structural.

    Written against `ref_table` rather than a tag cache because `_TAGS` was
    dead and is gone; `ref_table` is what actually answers "which tags exist"
    and so is what the tag-lifetime property now rides on.
    """
    from extant.scope import RunScope

    outer = RunScope()
    outer.ref_table["/repo"] = ({}, {"v1.0": "abc1234"})
    inner = RunScope()
    inner.ref_table["/repo"] = ({}, {"v2.0": "def5678"})
    assert outer.ref_table["/repo"] == ({}, {"v1.0": "abc1234"}), (
        "a second scope reached into the first, which is what module globals "
        "did and what objects are supposed to make impossible")


def test_every_cache_is_empty_in_a_fresh_scope() -> None:
    """A scope that carries anything over has the lifetime bug by another name.

    Reports the denominator: a RunScope that grew a field this test does not
    know about would otherwise pass while covering nothing.
    """
    from extant.scope import RunScope

    scope = RunScope()
    caches = [f for f in dataclasses.fields(scope) if f.name not in NOT_A_CACHE]
    assert len(caches) == CACHE_FIELDS, (
        f"{len(caches)} cache fields, expected {CACHE_FIELDS}. A cache was "
        f"added or removed without the inventory at the top of this file being "
        f"updated, and this test would otherwise pass while counting something "
        f"else: {[f.name for f in caches]}")
    nonempty = [f.name for f in caches if getattr(scope, f.name)]
    print(f"checked {len(caches)} cache fields on a fresh RunScope")
    assert not nonempty, f"these start non-empty: {nonempty}"


def test_directory_listings_start_switched_off_rather_than_empty() -> None:
    """`dircache` is the one field whose empty value is not `{}`.

    None means CACHING IS OFF, which is the state whenever a rule is called
    directly rather than through validate(): a caller that creates a file
    between two checks must see the new answer, and a cache with no owner would
    quietly hand back the old one. An empty dict would silently opt every
    direct caller into a cache nobody owns, and the symptom is a stale answer
    rather than a failure.
    """
    from extant.scope import RunScope

    assert RunScope().dircache is None, (
        "a fresh scope has directory caching ON, so a rule called outside "
        "validate() would answer from a listing nothing invalidates")


def test_a_stable_scope_is_off_by_default() -> None:
    """The narrowness is the safety argument, so the default is asserted.

    `--sweep` is the only caller that declares a repository static, and it
    opens no file for writing. Every other caller keeps the per-call promise,
    which only holds while this defaults to False.
    """
    from extant.scope import RunScope

    assert RunScope().stable is False


def test_doc_scope_carries_the_three_per_document_values() -> None:
    from extant.scope import DocScope

    scope = DocScope(link_base=Path("/repo/docs"), doc_format="rst",
                     doc_path="docs/a.rst")
    assert (scope.link_base, scope.doc_format, scope.doc_path) == (
        Path("/repo/docs"), "rst", "docs/a.rst")


def test_an_unset_doc_scope_says_markdown_and_nothing_else() -> None:
    """The defaults are the module globals' import-time values, exactly.

    `doc_format` matters most: `_rule_applies` skips the markdown-only rules
    whenever it is not "markdown", so a default of "md" - a plausible spelling
    that is not this one - would silently switch off `dead-md-link` and
    `dead-md-anchor` for every caller that never sets a format.
    """
    from extant.scope import DocScope

    blank = DocScope()
    assert (blank.link_base, blank.doc_format, blank.doc_path) == (
        None, "markdown", None)


def test_a_doc_scope_cannot_be_edited_in_place() -> None:
    """Frozen, so a caller REPLACES the document rather than mutating one.

    The three values move together. The old code set them one at a time around
    a loop and restored them after it, which left the last swept document's
    directory installed whenever a rule raised part-way through.
    """
    from extant.scope import DocScope

    try:
        DocScope().doc_format = "rst"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("DocScope is no longer frozen")


def test_context_carries_one_run_and_one_document() -> None:
    """What every rule receives from Task 9 onward.

    Built by validate() today and read only to install the two scopes, because
    the shim's rules are still functions taking (repo, text) and cannot be
    handed anything. Asserting the shape now is what keeps Task 9 from having
    to invent it.
    """
    from extant.scope import Context, DocScope, RunScope

    run, doc = RunScope(), DocScope(doc_path="a.md")
    ctx = Context(config=None, run=run, doc=doc, repo=Path("/repo"))
    assert ctx.run is run and ctx.doc is doc
    assert ctx.repo == Path("/repo")
    assert ctx.git is None, (
        "a Context built without a Git must carry None rather than quietly "
        "defaulting to a real one, or a caller that forgot to supply the seam "
        "spawns processes against its checkout instead of failing")


def test_context_carries_the_git_it_was_given() -> None:
    """The seam is a value on the Context, not a name a rule reaches for.

    Trivial today, because the shim's rules still read the installed module
    name rather than this field. It is asserted anyway: Task 9 makes this the
    only route, and a Context that dropped what it was handed would then send
    every rule to whatever the module happened to be holding.
    """
    from extant.git import CountingGit, SubprocessGit
    from extant.scope import Context, DocScope, RunScope

    fake = CountingGit(SubprocessGit())
    ctx = Context(config=None, run=RunScope(), doc=DocScope(),
                  repo=Path("/repo"), git=fake)
    assert ctx.git is fake


def test_the_rules_reach_git_only_through_the_seam() -> None:
    """Nothing outside extant/git.py still calls the raw helpers by name.

    That is what makes the seam substitutable: a call site naming `_git`
    directly is one a swapped implementation cannot see, and a budget or a
    profile reading the seam would report a number quietly missing it.

    Covers the shim (`extant_collect.py`) AND every module under the package
    (`extant/`) except `extant/git.py`, which is scanned and pinned
    separately at the end: see PACKAGE_SEAM_DIRECT_SITES above for why. Before
    this test reached the package, extant/collect.py had no seam gate at all
    - its own comment claimed a monkeypatch trap fixed while
    `hc._GIT is extant.collect._GIT` was False the whole time, and nothing
    here was watching that file to notice either the false claim or a real
    regression.

    NOT a claim that the seam is the only route to git, and the numbers
    printed below are why. Five invocations in the shim and one in the package
    run git through subprocess directly, because they need something
    `run(repo, *args)` cannot express - stdin for the three `cat-file`
    batches, a `-z` listing paired with `check-attr --stdin`, and bytes rather
    than decoded text for `git show`. Those are counted here rather than
    glossed, so the gap is a number somebody chose and can watch, and so a
    seventh cannot appear unnoticed. It was six-and-none until Task 8 moved
    `_batch_shas` into extant/refs.py; the split is where the code is, not a
    change in how many bypass the seam.
    tests/test_spawn_budget.py counts at the subprocess boundary for the same
    reason: it is the only place that sees both populations.
    """
    import ast
    import re

    def _names_git(node: ast.AST, git_vars: set[str]) -> bool:
        """Does this argument expression name a git invocation?

        A string is read as a command line - `"git status"` and `"git"` both
        count, because `os.system` takes one string rather than a list. A list
        or tuple is read positionally, the shape `subprocess.run` and `Popen`
        take: single-quoted or double-quoted makes no difference, since both
        parse to the same `ast.Constant`. A bare name is looked up in
        `git_vars`, the names already known (from a prior assignment anywhere
        in the file) to hold a git-shaped literal - the "built a variable,
        then passed it" case.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            first = node.value.strip().split()[:1]
            return first == ["git"]
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            return _names_git(node.elts[0], git_vars)
        if isinstance(node, ast.Name):
            return node.id in git_vars
        return False

    def _git_subprocess_calls(source: str) -> tuple[int, int]:
        """(git-naming call sites, total candidate call sites) in one file.

        Replaces a regex keyed on one literal spelling,
        `subprocess.run(["git"`, which review found blind to seven other ways
        to write the same call: a single-quoted list, a tuple instead of a
        list, `subprocess.check_output`, `subprocess.Popen`, a variable built
        then passed, `os.system`, and `from subprocess import run`. All seven
        parse to different source text and the same AST shapes below, which is
        what an AST walk buys over a richer regex - it is why relaxing
        pkg_outside from `== 0` to `<= 1` in Task 8 needed a detector that
        cannot be out-spelled, not a longer pattern.

        A CANDIDATE is a call to subprocess.run/check_output/check_call/Popen,
        to a bare name imported directly from subprocess, or to os.system -
        not every call in the file, which would make "examined" a number
        nobody could use to judge the check. Whether a candidate NAMES git is
        decided by its first argument; see `_names_git`. Keyword-only
        invocations (`subprocess.run(args=[...])`) are not covered, matching
        every call site this repository actually writes.
        """
        tree = ast.parse(source)

        bare_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                for alias in node.names:
                    if alias.name in ("run", "Popen", "check_output", "check_call"):
                        bare_names.add(alias.asname or alias.name)

        # Every name assigned a git-shaped literal anywhere in the file,
        # collected in a pass of its own that finishes before any call is
        # judged - so it does not matter whether the assignment is written
        # above or below the call site that reads it.
        git_vars: set[str] = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and _names_git(node.value, git_vars)):
                git_vars.add(node.targets[0].id)

        examined = 0
        naming_git = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_subprocess_attr = (
                isinstance(func, ast.Attribute)
                and func.attr in ("run", "check_output", "check_call", "Popen")
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            )
            is_bare_import = isinstance(func, ast.Name) and func.id in bare_names
            is_os_system = (
                isinstance(func, ast.Attribute) and func.attr == "system"
                and isinstance(func.value, ast.Name) and func.value.id == "os"
            )
            if not (is_subprocess_attr or is_bare_import or is_os_system):
                continue
            examined += 1
            if node.args and _names_git(node.args[0], git_vars):
                naming_git += 1
        return naming_git, examined

    def seam_counts(source: str) -> tuple[int, int, int, int]:
        """(routed, direct, outside, examined) git-reaching call sites in one file.

        TWO routed spellings, and the second is not decoration. The shim
        installs a module-level `_GIT` because a rule taking `(repo, text)` has
        no argument a Git could arrive through; the package takes a Context and
        reaches git as `ctx.git`. Task 8 moved nine call sites to the second
        spelling, and this counter knew only the first - so extant/refs.py
        scanned as 0 routed calls while making nine, and PACKAGE_ROUTED_FLOOR
        went on being satisfied by extant/collect.py alone.

        Nothing would have failed. The floor would simply have stopped
        measuring the population it names, quietly, for the rest of the
        refactor - which is this repository's most-repeated defect and the one
        a denominator is supposed to prevent. Task 9 makes `ctx.git` the only
        spelling, so a counter blind to it would end up watching nothing at
        all.

        `outside` is the AST walk in `_git_subprocess_calls`, not a regex: see
        there for what that bought over `subprocess\\.run\\(\\s*\\n?\\s*\\[\\s*"git"`,
        the single spelling this used to match. `examined` is new too - the
        denominator, so this cannot pass by silently scanning nothing.
        """
        direct = re.findall(r"(?<![.\w])_git_soft\(|(?<![.\w])_git\(", source)
        routed = re.findall(
            r"(?<![.\w])_GIT\.(?:run|soft)\(|(?<![.\w])ctx\.git\.(?:run|soft)\(",
            source)
        outside, examined = _git_subprocess_calls(source)
        return len(routed), len(direct), outside, examined

    # Population 1: the shim.
    source = (PAYLOAD / "extant_collect.py").read_text(encoding="utf-8")
    routed, direct, outside, examined = seam_counts(source)
    print(f"checked extant_collect.py: {routed} call(s) through the seam, "
          f"{direct} still naming a raw helper, {examined} subprocess/"
          f"os.system call site(s) examined, {outside} of them running "
          f"git directly")
    # The denominator. A file where nothing reached git at all would satisfy
    # the assertion below while proving nothing, and that is the exact shape of
    # broken check this project keeps finding.
    assert routed >= SHIM_ROUTED_FLOOR, (
        f"only {routed} seam call site(s) in the shim, below the "
        f"{SHIM_ROUTED_FLOOR} left here after Task 8; this test passes "
        f"vacuously at zero, because it can only prove an ABSENCE. If a task "
        f"moved the rest out, delete this assertion rather than lowering it")
    assert direct == 0, (
        f"{direct} call site(s) still bypass the seam; a swapped Git "
        f"cannot see those calls and a budget reading it would miss them")
    assert outside <= DIRECT_SUBPROCESS_SITES, (
        f"{outside} git invocations now bypass the seam entirely, up from "
        f"{DIRECT_SUBPROCESS_SITES}. Each is invisible to CountingGit and to "
        f"--profile. If the new one genuinely cannot fit run(repo, *args), "
        f"raise the number here and say which one it is")

    # Population 2: the package, minus its own seam implementation.
    package_dir = PAYLOAD / "extant"
    seam_file = package_dir / "git.py"
    # rglob, NOT glob. Task 9 put thirteen rule modules under
    # extant/rules/, and a one-level glob would have gone on scanning
    # ten files while claiming to cover the package - the seam gate
    # would not have failed, it would simply have stopped watching the
    # population that does most of the asking. That is this repository's
    # most-repeated defect and the reason every count here is printed.
    consumers = sorted(p for p in package_dir.rglob("*.py")
                       if p != seam_file and "__pycache__" not in p.parts)
    pkg_routed = pkg_direct = pkg_outside = pkg_examined = 0
    for path in consumers:
        r, d, o, e = seam_counts(path.read_text(encoding="utf-8"))
        pkg_routed += r
        pkg_direct += d
        pkg_outside += o
        pkg_examined += e
    print(f"checked {len(consumers)} package module(s) "
          f"({', '.join(p.name for p in consumers)}): {pkg_routed} call(s) "
          f"through the seam, {pkg_direct} naming a raw helper, "
          f"{pkg_examined} subprocess/os.system call site(s) examined, "
          f"{pkg_outside} of them running git directly")
    assert pkg_routed >= PACKAGE_ROUTED_FLOOR, (
        f"only {pkg_routed} seam call site(s) across the package modules; "
        f"this test passes vacuously below that, because it can only prove "
        f"an ABSENCE")
    assert pkg_direct == 0, (
        f"{pkg_direct} call site(s) in the package name a raw git helper "
        f"directly, outside extant/git.py; a swapped Git cannot see those "
        f"calls")
    assert pkg_outside <= PACKAGE_DIRECT_SUBPROCESS_SITES, (
        f"{pkg_outside} call site(s) in the package run git through "
        f"subprocess directly, outside extant/git.py, up from "
        f"{PACKAGE_DIRECT_SUBPROCESS_SITES}. Each is invisible to CountingGit "
        f"and to --profile. If the new one genuinely cannot fit "
        f"run(repo, *args), raise the number there and say which one it is")

    # extant/git.py, on its own: see PACKAGE_SEAM_DIRECT_SITES above for why
    # it is not folded into population 2, and for what its two pinned numbers
    # are actually made of.
    seam_routed, seam_direct, seam_outside, seam_examined = seam_counts(
        seam_file.read_text(encoding="utf-8"))
    print(f"checked git.py (the seam's own implementation): {seam_routed} "
          f"call(s) through _GIT (expected 0, git.py has no _GIT of its "
          f"own), {seam_direct} internal call(s) naming _git/_git_soft "
          f"directly or as their own definition, {seam_examined} "
          f"subprocess/os.system call site(s) examined, {seam_outside} "
          f"direct subprocess-run-git call(s)")
    assert seam_direct <= PACKAGE_SEAM_DIRECT_SITES, (
        f"{seam_direct} internal call/definition site(s) in git.py naming "
        f"_git/_git_soft, up from {PACKAGE_SEAM_DIRECT_SITES}")
    assert seam_outside <= PACKAGE_SEAM_OUTSIDE_SITES, (
        f"{seam_outside} direct subprocess-git call(s) in git.py, up from "
        f"{PACKAGE_SEAM_OUTSIDE_SITES}")
