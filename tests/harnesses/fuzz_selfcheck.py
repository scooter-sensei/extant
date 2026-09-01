"""Stage 5: break each property on purpose and confirm it goes red.

    python tests/harnesses/fuzz.py PKG ARENA --self-check

WHY A FUZZER NEEDS THIS MORE THAN A SUITE DOES

`mutate.py` makes this argument about the test suite: a check nobody has
watched fail is a hypothesis, not a gate. It applies harder here. A unit test
at least asserts a value somebody chose; a fuzz property asserts that something
did NOT happen, over repositories nobody looked at, and the healthy output of
every one of them is silence. A property that can never fire produces exactly
the output of a property that holds - across the whole corpus, forever.

Eight of these were watched failing once, by hand, against a payload edited in
a scratch directory that no longer exists. That is a measurement, not a gate:
it says the property could fire against THAT payload, and says nothing after
the next refactor moves the code out from under it. This runs the same
experiment on demand, against the real predicate, and fails when a property
cannot be provoked.

WHAT "OBSERVABLE" MEANS HERE, AND THE TWO HALVES IT NEEDS

A property is observable when both of these hold on one repository:

  silent  the clean payload does not produce it, so the fault below is caused
          by the breakage rather than by the repository
  red     the broken payload does produce it

The first half is not ceremony. A property already firing on the clean build
would be "confirmed" by any breakage at all, including one that did nothing -
which is how a breakage that silently failed to apply reads as a success. The
Stage 3 audit caught two breakages that were themselves broken, one leaving a
SyntaxError so extant never ran at all, and a run that never ran produces no
finding of any kind, which looked exactly like the oracle working.

So an anchor that does not match is a HARNESS FAULT, never a skip - the same
rule `mutate.py` states for the same reason. A breakage that cannot be applied
proves nothing, and reporting it as a pass is the defect this project exists
to refuse, committed by the machinery built to refuse it.

WHY IT EDITS THE INSTALLED `tools/`, NOT THE PACKAGE

One repository, built once, with only the payload text changing between the
silent run and the red one. Editing the package instead would mean rebuilding
per breakage, and the two runs would then differ in their commit SHAs and
their build as well as in the payload - three variables where the experiment
needs one. `mutate.py` rewrites source in place and restores it for the same
reason, and this restores from bytes held in memory rather than from git,
because the repository under test is generated and has no clean copy to
recover from.

CONTRIVED BREAKAGES ARE MARKED AS SUCH

Some properties have no realistic defect that provokes them; a breakage for
those has to be invented, and the fact that it had to be is information about
what the property is worth. Those are flagged in the table and named in the
output rather than blended in, because "this property can be made to fire" and
"this property guards something somebody might really write" are different
claims and only the first is being made.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Every property the harness can report, and where it comes from. Written out
# rather than discovered, because a property that disappears from the code
# should fail this list instead of quietly reducing what is checked - the same
# argument `registry.py` makes for a denominator that raises.
#
# `HARNESS` WAS EXCLUDED HERE AND THE EXCLUSION WAS WRONG. The note said it
# is not a property of extant but of this harness - true, and beside the
# point. It is a fault kind the driver reports and `SHRINKABLE` bisects on,
# and it fires on a real shape: findings printed with no denominator line at
# all, which is the fail-open case where the DENOMINATOR loop iterates nothing
# and reports success. A gate nobody has watched fail is a hypothesis whoever
# it belongs to.
#
# `refused` stays out, and that one is genuine: it records that a run declined
# to START, so no breakage to the payload produces it honestly.
CORE_PROPERTIES = ("CRASH", "HANG", "EXIT", "ERRORED", "DENOMINATOR",
                   "UNSTABLE", "SARIF", "FORMATS", "HARNESS", "AXIS",
                   "CONCURRENT")
ORACLE_PROPERTIES = ("FENCE", "SHIFT", "CRLF", "RELOCATE", "MONOTONE",
                     "BASELINE", "PROCESS", "MODE-AGREE", "DENOM-AGREE",
                     "GITHUB")
ALL_PROPERTIES = CORE_PROPERTIES + ORACLE_PROPERTIES

# Names this list is NOT required to carry, each with the reason, so the
# cross-check below stays readable rather than becoming a lowered floor.
EXEMPT = {
    # A run that declined to start. No payload edit produces it honestly.
    "refused",
}


def unlisted_properties(shrinkable, oracle_names) -> list[str]:
    """Fault kinds the harness can report that this file does not check.

    DERIVED FROM THE HARNESS'S OWN DATA, never scraped from its source. The
    ad-hoc regex written to audit this list reported `CRASH` as never emitted -
    a false positive, because `CRASH` is RETURNED rather than appended - which
    is the argument for reading `SHRINKABLE` and `ORACLES` directly instead.

    A hand-written list that silently shrinks to whatever happens to be covered
    is the reassuring number again, one level up from the rules.
    """
    known = set(ALL_PROPERTIES) | EXEMPT
    return sorted((set(shrinkable) | set(oracle_names)) - known)


@dataclass(frozen=True)
class Breakage:
    """One deliberate defect, and the property it must provoke.

    Each path is relative to the installed `tools/` directory, which is the
    payload root as the generated repository carries it.

    SEVERAL EDITS, APPLIED TOGETHER, because one property needs it and the
    reason is worth keeping. `ERRORED` asserts that a run naming a rule which
    RAISED never exits 0 - so making a rule raise does not provoke it, since
    the gate then correctly exits non-zero. It takes a raising rule AND a gate
    that ignores it, which is what the real defect would be: not one mistake
    but a rule failing while something downstream swallows the consequence.
    A single-edit table reported this property as unobservable and was wrong
    about why.
    """

    prop: str
    why: str
    edits: tuple            # ((path, old, new), ...), applied together
    mode: tuple = ("--verify",)
    contrived: bool = False

    @property
    def paths(self) -> str:
        return ", ".join(path for path, _o, _n in self.edits)


BREAKAGES = (
    # --- the Stage 6 axes ---------------------------------------------
    Breakage(
        prop="CONCURRENT",
        why="a fixed-name file in the repository that a second overlapping "
            "run finds already taken, so one of two simultaneous runs answers "
            "differently from the same run alone",
        # CONTRIVED, and specifically so rather than conveniently so. A
        # breakage that merely made output vary - a PID in a finding, say -
        # would fire this property while proving nothing about concurrency,
        # because a SEQUENTIAL pair would differ too and `UNSTABLE` already
        # owns that. This one is invisible to every sequential run: the file is
        # created, held, and removed inside one invocation, so a run that has
        # the repository to itself never meets it. Only an overlapping run
        # does, which is exactly the population this property exists to reach.
        #
        # The sleep is what makes the overlap observable at all. Without it the
        # first run releases the name before the second looks, and the
        # breakage silently does nothing - which would read as the property
        # being unobservable when the breakage was the thing that failed, the
        # mistake this file records three other instances of.
        edits=(("extant/cli.py",
                "    repo = Path(args.repo)",
                "    repo = Path(args.repo)\n"
                "    _race = repo / '.extant-race-probe'\n"
                "    try:\n"
                "        _race.touch(exist_ok=False)\n"
                "    except FileExistsError:\n"
                "        print('another run of extant holds this repository')\n"
                "    else:\n"
                "        import time as _time\n"
                "        _time.sleep(1.5)\n"
                "        try:\n"
                "            _race.unlink()\n"
                "        except OSError:\n"
                "            pass"),),
        contrived=True,
    ),

    Breakage(
        prop="AXIS",
        why="an annotated tag no longer peeled to its commit, so a tag that "
            "exists and is merged reads as one on no integration branch - a "
            "false positive on the most ordinary tag shape there is",
        # `^{commit}` in `resolve_ref`, whose own docstring says what dropping
        # it does: "without it a tag object's own SHA is returned and never
        # appears in any rev-list".
        #
        # THE FIRST ATTEMPT TARGETED `ref_table` INSTEAD - `commit = peeled or
        # obj`, which peels annotated tags there and reads like the obvious
        # site. It applied cleanly, matched exactly once, and changed NOTHING:
        # `ref_table` keys tags by SHORT name, and this rule asks about
        # `refs/tags/v1.0`, which misses that table entirely and falls through
        # to the `rev-parse` below. So the property read as unobservable when
        # the BREAKAGE was aimed at a path the rule does not take - the same
        # mistake Stage 5 made twice and wrote down both times.
        edits=(("extant/refs.py",
                '                                   f"{ref}^{{commit}}").strip() or None',
                '                                   f"{ref}").strip() or None'),),
    ),

    # --- the document scanners ----------------------------------------
    Breakage(
        prop="SHIFT",
        why="every claim reports line 1, which is a number confidently wrong "
            "rather than absent - the CR-only defect this function exists for",
        edits=(("extant/text.py",
                "    return len(LINE_BREAK.findall(text, 0, offset)) + 1",
                "    return 1"),),
    ),
    Breakage(
        prop="CRLF",
        why="a CRLF counted as two breaks, which is what dropping the "
            "alternation from this pattern actually does",
        edits=(("extant/text.py",
                r'LINE_BREAK = re.compile(r"\r\n|[\n\r]")',
                r'LINE_BREAK = re.compile(r"[\n\r]")'),),
    ),
    Breakage(
        prop="FENCE",
        why="fenced blocks no longer blanked, so an example claim inside a "
            "fence is judged as a promise",
        edits=(("extant/text.py",
                "    return _blank(doc, text, inline=True)",
                "    return text"),),
    ),
    Breakage(
        prop="PROCESS",
        why="a memo whose key is incomplete, so the second document in one "
            "process is answered from the first document's stripped text",
        edits=(("extant/text.py",
                "    if cached is not None and cached[0] is text:",
                "    if cached is not None:"),),
    ),

    # --- the output formats -------------------------------------------
    Breakage(
        prop="GITHUB",
        why="one annotation dropped from the github format, the shape that "
            "put a finding on a pull request with no inline mark",
        edits=(("extant/report.py",
                "    lines = []\n    for item in located:\n        level =",
                "    lines = []\n    for item in located[1:]:\n        level ="),),
        mode=("--sweep", "--format=github"),
    ),
    Breakage(
        prop="DENOM-AGREE",
        why="SARIF states a denominator of zero for every rule while the text "
            "run states the real one",
        # NOT `run["properties"]`, which was the first attempt and provoked
        # nothing: the oracle reads the `examined:` NOTIFICATION, because that
        # is the spelling both outputs share and the one a reader compares.
        # Breaking a field nothing reads is a breakage that did not break
        # anything, reported as a property that could not be observed.
        edits=(("extant/report.py",
                '        summary = ", ".join(f"{kind} {n}" for kind, n in examined.items())',
                '        summary = ", ".join(f"{kind} 0" for kind, n in examined.items())'),),
        mode=("--sweep", "--format=sarif"),
    ),
    Breakage(
        prop="SARIF",
        why="stdout is no longer one JSON document, which fails a CI upload "
            "rather than reading as no results",
        edits=(("extant/report.py",
                "    return json.dumps({",
                '    return "#" + json.dumps({'),),
        mode=("--sweep", "--format=sarif"),
    ),
    Breakage(
        prop="FORMATS",
        why="SARIF drops a result the text output printed, so a machine "
            "consumer sees fewer findings than a human does",
        edits=(("extant/report.py",
                "    results = []\n    for item in located:",
                "    results = []\n    for item in located[1:]:"),),
        mode=("--sweep", "--format=sarif"),
    ),
    Breakage(
        prop="UNSTABLE",
        why="the denominator is built from a set, so its order follows string "
            "hashing and two processes print two answers about one repository",
        # `gate.py`, NOT `report.py`. The first attempt anchored on the SARIF
        # summary at four spaces of indentation - which is a SUBSTRING of the
        # real line at eight - so it matched once, applied cleanly, and edited
        # a code path `--verify` never reaches. The property was then reported
        # unobservable, which was true of the breakage and false of the
        # property. `check_anchors` refuses a mid-line match now.
        edits=(("extant/gate.py",
                '    summary = ", ".join(f"{kind} {n}" for kind, n in examined.items())',
                '    summary = ", ".join(f"{kind} {n}" for kind, n in set(examined.items()))'),),
    ),

    # --- the gate -----------------------------------------------------
    Breakage(
        prop="EXIT",
        why="the gate exits 0 whatever it found, which is a hook that passes "
            "every commit while printing the findings it ignored",
        edits=(("extant/gate.py",
                "            exit_code = 1\n\n    return exit_code",
                "            exit_code = 1\n\n    return 0"),),
    ),
    Breakage(
        prop="BASELINE",
        why="the baseline suppresses nothing, so an accepted finding comes "
            "back and the file silently stops meaning anything",
        edits=(("extant/report.py",
                "            if mark in self.baselined:",
                "            if False and mark in self.baselined:"),),
    ),
    Breakage(
        prop="ERRORED",
        why="a rule raises AND the gate exits 0 anyway, so a partial answer is "
            "reported as a clean one",
        # TWO EDITS, and the second is why this was reported unobservable on
        # the first run. A raising rule alone does not provoke this: the gate
        # correctly exits non-zero, which is the property HOLDING. The defect
        # is a rule failing while something downstream swallows the
        # consequence, and it takes both halves to build one.
        edits=(("extant/rules/sha.py",
                "def check(ctx: Context, text: str) -> list[Finding]:",
                "def check(ctx: Context, text: str) -> list[Finding]:\n"
                "    raise ValueError('deliberate')"),
               ("extant/gate.py",
                "            exit_code = 1\n\n    return exit_code",
                "            exit_code = 1\n\n    return 0")),
    ),

    # --- the rules ----------------------------------------------------
    Breakage(
        prop="DENOMINATOR",
        why="a rule reports findings against a denominator of zero, the exact "
            "conflation this project exists to refuse",
        edits=(("extant/rules/sha.py",
                "    return len(_sha_sites(ctx, text))",
                "    return 0"),),
    ),
    Breakage(
        prop="CRASH",
        why="an unhandled traceback reaches the user instead of a diagnostic",
        edits=(("extant/session.py",
                "def count_examined(repo: Path, text: str) -> dict[str, int]:",
                "def count_examined(repo: Path, text: str) -> dict[str, int]:\n"
                "    raise RuntimeError('deliberate')"),),
    ),
    Breakage(
        prop="MODE-AGREE",
        why="the sweep skips a rule the gating modes run, so the survey and "
            "the gate disagree about one document",
        edits=(("extant/sweep.py",
                "    counted = session.count_examined(repo, text)",
                "    counted = session.count_examined(repo, text)\n"
                "    findings = [f for f in findings if f.kind != 'dead-sha']"),),
        mode=("--sweep",),
    ),
    Breakage(
        prop="HANG",
        why="the tool does not answer inside the budget, which is what an "
            "unbounded scan on a large document looks like from outside",
        # SLOWER THAN THE BUDGET ON PURPOSE, so this breakage costs the whole
        # timeout to observe. That is the honest price of watching a timeout
        # property fire: there is no way to see a deadline missed without
        # missing it.
        edits=(("extant/session.py",
                "def count_examined(repo: Path, text: str) -> dict[str, int]:",
                "def count_examined(repo: Path, text: str) -> dict[str, int]:\n"
                "    import time; time.sleep(600)"),),
        contrived=True,
    ),

    Breakage(
        prop="HARNESS",
        why="findings printed with no denominator line at all, so the "
            "DENOMINATOR loop iterates nothing and reports success",
        # The fail-open case, and the one this harness is least able to notice
        # about itself: with no `checked X: ...` line the per-rule loop has
        # nothing to walk, so every denominator comparison passes vacuously
        # while findings print normally.
        #
        # TWO EDITS, because the denominator is PRINTED FROM TWO PLACES.
        # `report_denominators` writes it for the primary document and a
        # separate `diag` writes it per extra document, so dropping one leaves
        # `checked README.md: ...` behind, `_rule_counts` still parses eleven
        # entries, and the property cannot fire. The first attempt at this
        # breakage dropped only the first and was reported NOT OBSERVED.
        #
        # That is the same two-writers shape the rules keep producing, one
        # layer up and in the OUTPUT rather than the counting: one claim -
        # what this run examined - emitted by two statements that can be
        # changed apart. Worth knowing about `gate.py` independently of this
        # breakage needing it.
        edits=(("extant/gate.py",
                '    diag(f"checked {name}: {summary}")',
                '    pass  # denominator line dropped'),
               ("extant/gate.py",
                """        diag(f"checked {relative}: {checked or 'nothing applicable'}")""",
                '        pass  # the extra-document denominator, dropped too'),),
    ),

    # --- the two the Stage 3 audit predicted would need contriving -----
    Breakage(
        prop="RELOCATE",
        why="a rule keyed on the document's FILENAME, so the same bytes under "
            "another name are judged differently",
        # CONTRIVED, and the audit said it would be. A rule may legitimately
        # key on the filename - `manifest-floor-mismatch` reads only
        # entry-point documents - so the shape is not absurd; what is absurd is
        # a link rule doing it. That no realistic defect provokes this oracle
        # is the measurement, not a gap in the table.
        edits=(("extant/rules/md_link.py",
                "    findings: list[Finding] = []\n"
                "    for number, target in _link_sites(ctx, text):",
                "    findings: list[Finding] = []\n"
                "    if (ctx.doc.doc_path or '') != 'NEXT_SESSION.md':\n"
                "        return []\n"
                "    for number, target in _link_sites(ctx, text):"),),
        contrived=True,
    ),
    Breakage(
        prop="MONOTONE",
        why="a rule that goes silent once the repository holds another "
            "markdown file, so an unrelated document removes a finding",
        # CONTRIVED, and TAUTOLOGICAL - the strongest statement this table
        # makes about a property being weak, and it is stated rather than
        # hidden behind a green row.
        #
        # A count threshold was tried first and observed nothing, for a reason
        # worth keeping: the maximal repository already carries more than two
        # markdown files, so the rule was silent BEFORE the oracle added its
        # document as well as after, and a break that changes nothing changes
        # nothing. Nothing in this codebase decides what to report by counting
        # documents, and no plausible edit makes it.
        #
        # So this keys on the oracle's own probe file. What that proves is
        # bounded and worth being exact about: it shows MONOTONE's comparison
        # WORKS - that it can see a finding disappear and is not structurally
        # inert, which is the failure mode this whole file exists to rule out.
        # It does NOT show the oracle guards a defect anybody might write. The
        # Stage 3 audit predicted this one would need contriving, and needing
        # a tautology is the sharper version of that answer.
        edits=(("extant/rules/sha.py",
                "    findings: list[Finding] = []\n"
                "    # The document's tokens rather than only this rule's sites",
                "    findings: list[Finding] = []\n"
                "    if (ctx.repo / 'unrelated-note.md').exists():\n"
                "        return []\n"
                "    # The document's tokens rather than only this rule's sites"),),
        contrived=True,
    ),
)


def payload_root(repo: Path) -> Path:
    """Where the installed payload sits inside a generated repository."""
    return repo / "tools"


def check_anchors(repo: Path) -> list[str]:
    """Every breakage whose anchor does not match the installed payload once.

    A HARNESS FAULT, never a skip. A breakage that cannot be applied proves
    nothing about the property it names, and a run that reported it as a pass
    would be claiming coverage it did not provide - which is the whole subject
    of this project, committed by the machinery built to check for it.

    Matching EXACTLY ONCE rather than at least once, for the reason `mutate.py`
    gives: an anchor matching twice edits a place nobody chose.
    """
    stale = []
    root = payload_root(repo)
    for item in BREAKAGES:
        for path, old, _new in item.edits:
            target = root / path
            if not target.is_file():
                stale.append(f"{item.prop}: {path} is not in the payload")
                continue
            text = target.read_text(encoding="utf-8")
            hits = text.count(old)
            if hits != 1:
                stale.append(f"{item.prop}: anchor in {path} matched "
                             f"{hits} time(s), expected exactly 1")
                continue
            # AND IT MUST BEGIN WHERE IT LOOKS LIKE IT BEGINS. An anchor
            # written with four spaces of indentation is a substring of the
            # same statement indented eight, so it matches exactly once,
            # applies cleanly, and edits a line its author did not name. That
            # happened here: the UNSTABLE breakage silently patched a
            # SARIF-only path and the property was reported unobservable.
            # Counting cannot catch it - the count is 1 either way.
            at = text.index(old)
            if old[:1].isspace() and at > 0 and text[at - 1] != chr(10):
                stale.append(f"{item.prop}: anchor in {path} matches "
                             f"mid-line, so it would edit a statement other "
                             f"than the one it names")
    return stale


def apply(repo: Path, item: Breakage) -> list:
    """Write every edit in, returning what is needed to undo them all.

    Asserts the substitution CHANGED the file. A `.replace()` that silently
    matched nothing leaves the payload correct, the property silent, and the
    report reading "not observable" about a breakage that was never applied -
    which is the wrong diagnosis pointing at the wrong half of the machinery.
    """
    saved = []
    for path, old, new in item.edits:
        target = payload_root(repo) / path
        original = target.read_text(encoding="utf-8")
        patched = original.replace(old, new, 1)
        if patched == original:
            for done, text in saved:
                done.write_text(text, encoding="utf-8")
            raise ValueError(f"{item.prop}: the breakage did not apply to "
                             f"{path}, so nothing was tested")
        target.write_text(patched, encoding="utf-8")
        saved.append((target, original))
    # THE BREAKAGE MUST STILL BE PYTHON. An edit that leaves a SyntaxError
    # stops extant running at all, and a tool that never ran reports a
    # traceback - which satisfies CRASH without the crash path ever executing,
    # and leaves every other property silent so it reads as "not observable".
    # Measured: replacing `def format_github(` with `def format_github((`
    # makes `check` report exactly ['CRASH'].
    #
    # The Stage 3 audit recorded this once already - "the first EXIT breakage
    # left a paren unclosed, so extant raised a SyntaxError, never ran, and the
    # oracle looked hollow when the BREAKAGE was hollow" - and this file
    # reproduced it. A hollow breakage is a harness fault, not a result.
    for target, _original in saved:
        try:
            compile(target.read_text(encoding="utf-8"), str(target), "exec")
        except SyntaxError as exc:
            for done, text in saved:
                done.write_text(text, encoding="utf-8")
            raise ValueError(f"{item.prop}: the breakage left {target.name} "
                             f"unparseable ({exc.msg} at line {exc.lineno}), "
                             f"so extant would not run and no property was "
                             f"tested") from None
    return saved


def restore(saved: list) -> None:
    """Put the payload back, and CONFIRM it went back.

    Verified rather than assumed, because the cost of being wrong compounds:
    a restore that silently did not take leaves every later property judged
    against a payload still carrying the previous breakage, and those results
    would be reported as ordinary rows. The failure would present as several
    unrelated properties behaving oddly rather than as one bad write.
    """
    for target, original in reversed(saved):
        target.write_text(original, encoding="utf-8")
        if target.read_text(encoding="utf-8") != original:
            raise ValueError(f"{target} did not restore, so every property "
                             f"after this one would be measured against a "
                             f"payload that is still broken")


def observed(faults, prop: str) -> bool:
    """Did the harness's own predicate report this property?"""
    return any(kind == prop for kind, _detail in faults)


def summarise(rows: list[tuple[str, str, str]], unwritten: list[str]) -> int:
    """What was observable, and the exit code that follows from it.

    Returns 0 only when every property in `ALL_PROPERTIES` was watched going
    red. A property with no breakage written is reported as debt rather than
    omitted, because a list that silently shrinks to what happens to be covered
    is the reassuring number again.
    """
    print()
    width = max(len(p) for p in ALL_PROPERTIES)
    for prop, verdict, detail in rows:
        print(f"  {prop:<{width}}  {verdict:<14} {detail}")
    for prop in unwritten:
        print(f"  {prop:<{width}}  NO BREAKAGE    nothing here can provoke it, "
              f"so it is not known to hold anything")

    watched = [r for r in rows if r[1] == "observed"]
    print()
    print(f"{len(watched)} of {len(ALL_PROPERTIES)} properties watched going "
          f"red")
    failures = [r for r in rows if r[1] != "observed"]
    if failures or unwritten:
        print()
        print("A property that cannot be made to fire is not a gate. Either "
              "write a\nbreakage that provokes it, or remove the property - "
              "an assertion nobody\nhas seen fail is a hypothesis, and this "
              "harness reports one as coverage.")
        return 1
    return 0
