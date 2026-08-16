"""Every rule module exposes the same four names.

This replaces the test asserting count_examined's keys match RULES. That test
guarded against FORGETTING an entry in a central dict; colocation removes the
opportunity, and what needs guarding now is that each module is complete.
"""
from __future__ import annotations

import sys
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parent.parent / "plugin" / "skills" / "extant" / "payload"
sys.path.insert(0, str(PAYLOAD))


def test_every_rule_module_is_complete() -> None:
    import importlib
    from extant import registry

    modules = sorted((PAYLOAD / "extant" / "rules").glob("*.py"))
    modules = [m for m in modules if m.stem != "__init__"]
    assert len(modules) == 13, (
        f"found {len(modules)} rule modules, expected 13; a glob that matched "
        f"nothing would otherwise pass this test vacuously")
    print(f"checked {len(modules)} rule modules for the four-name contract")

    for path in modules:
        module = importlib.import_module(f"extant.rules.{path.stem}")
        for name in ("RULE", "check", "examined", "probe"):
            assert hasattr(module, name), f"{path.stem} has no {name}"
        assert module.RULE.falsifiable, (
            f"{path.stem} states no falsifiable question, so it cannot be "
            f"shown to ask something git or the filesystem can settle")

    kinds = {m.stem: importlib.import_module(f"extant.rules.{m.stem}").RULE.kind
             for m in modules}
    assert len(set(kinds.values())) == 13, f"duplicate kinds: {kinds}"
    assert {r.kind for r in registry.RULES} == set(kinds.values())


def test_a_rule_that_raises_is_reported_and_fails_the_run(git_repo, capsys,
                                                          monkeypatch) -> None:
    """The dangerous half of per-rule isolation.

    A rule that crashes and is skipped quietly reports no findings, which reads
    exactly like a clean document. This asserts the opposite of the obvious
    implementation, in all three of the ways that make catching the exception
    safe rather than harmful: the rule is NAMED in the output beside the
    denominators, the run does not exit 0, and the other rules still report.

    Written against `main()` rather than `validate()` deliberately. `validate`
    only records the failure; whether anybody is TOLD, and whether the run
    still claims success, are decisions the mode makes - and those are the two
    that turn isolation from a safety feature into a silent one.
    """
    import extant_collect as hc

    repo, commit = git_repo
    commit("a.md", "nothing here\n", "feat: a")

    def explode(ctx, text):
        raise RuntimeError("deliberate")

    import dataclasses

    broken = dataclasses.replace(hc.RULES[0], check=explode)
    monkeypatch.setattr(hc, "RULES", (broken,) + hc.RULES[1:])

    code = hc.main(["--validate", str(repo / "a.md"), "--repo", str(repo)])
    printed = capsys.readouterr()
    combined = printed.out + printed.err

    assert code != 0, (
        "a run with a crashed rule reported success, which is the failure "
        "this whole project exists to prevent arriving through its own "
        "isolation")
    assert "ERRORED" in combined and broken.kind in combined, (
        f"the crashed rule was not named in the output, so its silence is "
        f"indistinguishable from a clean document:\n{combined}")
    assert "RuntimeError: deliberate" in combined, (
        f"the exception was recorded without saying what it was:\n{combined}")
    # The other twelve still ran, which is the whole reason for isolating
    # rather than letting the traceback out.
    assert "checked a.md:" in combined, combined


def test_a_rule_that_states_no_denominator_refuses_rather_than_answering_zero(
) -> None:
    """The default `examined` raises, and that is the point of having one.

    A rule added without a denominator would otherwise report 0 candidates
    forever, which is the one number this whole tool exists to disambiguate:
    "0 examined" and "0 found" print identically. Raising turns the omission
    into a crash on the first count_examined - and, because `count_examined`
    catches it and records the rule in RULE_ERRORS, into a named failure that
    cannot exit 0 rather than an unhandled traceback.
    """
    from extant.contract import Rule
    from extant.registry import RULE_ERRORS, count_examined

    forgetful = Rule(kind="made-up", check=lambda _c, _t: [], scope="whole-file",
                     in_archive=True, falsifiable="does it?", probe=lambda _c, _t: None)
    try:
        forgetful.examined(None, "")
    except NotImplementedError:
        pass
    else:
        raise AssertionError(
            "a Rule with no `examined` answered instead of refusing, so a rule "
            "added without a denominator would report 0 and read as clean")

    # And the same rule inside a registry fold is NAMED rather than silently
    # counted as zero. Asserted through the real function so the two halves
    # cannot drift: it is `count_examined` that decides whether the refusal
    # above becomes visible or becomes a quiet 0.
    import extant.registry as registry

    before = len(RULE_ERRORS)
    real = registry.RULES
    registry.RULES = (forgetful,)
    try:
        counts = count_examined(None, "")
    finally:
        registry.RULES = real
    assert counts == {"made-up": 0}, counts
    named = [kind for kind, _message in RULE_ERRORS[before:]]
    assert named == ["made-up"], (
        f"the rule with no denominator was counted as 0 and not named, which "
        f"is the reassuring number rather than the honest one: {named}")
    del RULE_ERRORS[before:]
