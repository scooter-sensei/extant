"""Which rules there are, and what a run has to say when one of them fails.

The ONE module allowed to import a rule module, which is what
`test_rules_are_leaves` enforces: a rule reaching sideways into another rule is
how rename detection ended up housed inside the live-claim rule and object
resolution inside the SHA rule, and both had to be dug back out.

`Rule` itself lives in extant/contract.py and is re-exported here, so
`registry.Rule` still names the class. That split is not stylistic - see that
file for the circular import it removes.
"""
from __future__ import annotations

from extant.contract import Rule
from extant.rules import line_pointer as _rule_line

__all__ = ["RULES", "RULE_ERRORS", "Rule", "count_examined", "forget_memos"]


def forget_memos() -> None:
    """Drop every memo a rule keeps OUTSIDE a RunScope.

    Exactly one exists: `_POINTER_SITES` in extant/rules/line_pointer.py. Every
    other memoised answer became a RunScope field, and is therefore dropped by
    the scope object going out of scope rather than by anyone remembering to
    call something. That one could not, and extant/scope.py states why at
    length: its consumer, `count_examined`, runs immediately AFTER validate()
    returns, so a value tied to the call's scope would be thrown away exactly
    when it is needed. It is invalidated when a fresh scope OPENS instead.

    Here rather than in extant/session.py, which is the caller, because this
    module is the only one allowed to import a rule - `test_rules_are_leaves`
    enforces that, and session.py reaching into extant/rules/line_pointer.py
    directly is precisely the shape that gate exists to refuse.

    NAMED, not discovered. A loop over the rule modules calling an optional
    `forget()` hook would also work and would pick up a second such memo for
    free, and that is exactly why it is not used: a hook nobody implements
    makes this function a no-op that looks like it is doing something, which is
    the zero-denominator failure this project keeps paying for. A rule that
    grows a memo outside its scope has to be added here, and the ImportError or
    AttributeError from getting that wrong is loud.
    """
    _rule_line._forget_sites()


# Rules that RAISED during this run, as (kind, "ExceptionType: message").
#
# Per-rule isolation is the one behaviour change this refactor makes, and this
# list is the half that makes it safe rather than dangerous. A rule that
# crashes and is quietly skipped reports no findings, which prints exactly like
# a clean document - so isolation that SWALLOWS is strictly worse than letting
# the traceback out. Three things make it safe instead, and none is optional:
# every errored rule is named in the output beside the denominators, an errored
# run never exits 0, and the denominator is still reported so a reader can see
# the rule had candidates and failed on them. Nothing may catch a rule's
# exception without appending here.
#
# MUTATED, never rebound. The shim's `validate()` and `count_examined` below
# both append to it and `main()` clears it at the start of a run; an assignment
# anywhere would hand one caller a different list and the other's entries would
# silently stop being read - which is the same class of failure the list exists
# to report.
RULE_ERRORS: list[tuple[str, str]] = []


def count_examined(ctx: object, text: str) -> dict[str, int]:
    """How many candidates each rule actually LOOKED AT, findings aside.

    The denominator, and the reason it exists: five separate times in one day a
    check reported success while examining nothing - patterns that matched
    nothing on a foreign repo, a hook that found no interpreter, a config value
    nothing read, a worktree survey resolving to the wrong repo, a lint whose
    skip-list excluded every file. Every one printed exactly what success
    prints, because "zero findings" and "zero checked" are the same output.

    Reporting the denominator makes those two states visibly different. A rule
    showing 0 examined is either genuinely absent from this document or broken,
    and the reader needs to know which.

    Asked of each RULE rather than read off one central table. That table
    guarded against forgetting an entry; colocation removes the opportunity,
    because the module that finds a rule's candidates is the module that counts
    them and the two can no longer describe different populations. The SHAPE is
    unchanged - every kind present, every value an int - because `run_sweep`
    sums it per document and seeds it from a repository-scoped pass, and
    `--verify` prints it as one line.

    A rule whose `examined` RAISES is named in `RULE_ERRORS` and reported as 0.
    Letting it out instead would take down the other twelve rules' denominators
    with it; the 0 is safe here only because an ERRORED line naming the rule is
    printed beside it, which is the one thing that stops a zero being read as a
    clean count.
    """
    counts: dict[str, int] = {}
    for rule in RULES:
        try:
            counts[rule.kind] = rule.examined(ctx, text)  # type: ignore[operator]
        except Exception as exc:                       # noqa: BLE001
            # Deliberately broad, and deliberately not silent. See RULE_ERRORS.
            RULE_ERRORS.append((rule.kind, f"{exc.__class__.__name__}: {exc}"))
            counts[rule.kind] = 0
    return counts


def _load_rules() -> tuple[Rule, ...]:
    """Import every rule module and collect its declaration, ordered by `sequence`.

    Eager, and it must stay eager. A lazily imported rule is a rule missing
    from RULES, and everything that iterates RULES - count_examined, the sweep
    denominators, --selftest, the docs test - would report a SMALLER
    denominator that looks exactly like a clean result.

    IMPORTED in module-name order, so that part is the same on every
    platform; `pkgutil.iter_modules` follows directory order otherwise, which
    a reader cannot predict from the source. That only governs which order
    modules are LOADED in, though - it stopped being what RULES is ORDERED BY
    the moment a rule's `sequence` field existed, because module-name order is
    exactly what reshuffled the printed `examined:` line the day this registry
    started assembling RULES from modules instead of from one hand-written
    tuple. Sorting by `sequence` here, on values each rule declares itself,
    reproduces the order every previous reader of a sweep or a `--verify`
    run has always seen.
    """
    import importlib
    import pkgutil

    from extant import rules as package

    found = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        module = importlib.import_module("extant.rules." + info.name)
        found.append(module.RULE)
    if not found:
        # This file's own denominator. A package that shipped without its rule
        # subdirectory - a copy that walked only the top level, an installer
        # that globbed one level deep - would otherwise build an empty registry,
        # and every mode would then report a clean run having checked nothing.
        raise RuntimeError("no rule modules were found; the registry is empty")
    found.sort(key=lambda rule: rule.sequence)
    sequences = [rule.sequence for rule in found]
    if len(set(sequences)) != len(sequences):
        # A tie would otherwise sort by Python's stable-sort tiebreak, which is
        # the position `found` already had - import order again, by the back
        # door, and silently: nothing else here would notice two rules had
        # agreed on a number. That is precisely the arbitrary, undeclared
        # ordering `sequence` exists to replace, so a collision fails the
        # import loudly instead of ordering itself by accident.
        raise RuntimeError(
            f"two or more rules share a `sequence` value: {sorted(sequences)}; "
            "give each rule module's RULE.sequence a distinct integer")
    return tuple(found)


RULES: tuple[Rule, ...] = _load_rules()
