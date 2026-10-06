"""The project's own thesis, turned on its own documentation.

Every rule here checks a claim the TOOL structurally cannot. `dead-md-link` asks
whether a path exists; nothing asks whether a documented `--flag` exists, or
whether a preset named in the README is one the installer offers. Those are
falsifiable against the code rather than against git, so they belong in the
suite instead of in a rule.

They are also the likeliest documentation to rot. A flag gets renamed and its
prose does not; a preset is added and the table is not. That happened twice in
this repository during one session: SKILL.md said "the nine validation rules"
while eleven existed, and the README's preset table went three releases without
the three newest entries.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PACKAGE_ROOT / "plugin" / "skills" / "extant"
DOCS = [PACKAGE_ROOT / "README.md", SKILL_ROOT / "SKILL.md"]

# Lines that actually invoke this tool. A doc also shows `git commit
# --no-verify`, `pip install`, and the hook installer's --with-trunk-guard,
# none of which argparse has ever heard of. Scoping to our own invocations is
# what keeps this from being a rule that cries wolf.
INVOCATION = re.compile(r"extant_collect\.py|^\s*\$?\s*extant\s|python -m extant")
FLAG = re.compile(r"--[a-z][a-z0-9-]+")


def _parser_flags() -> set[str]:
    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    from extant import cli

    flags: set[str] = set()
    for action in cli.build_parser()._actions:
        flags.update(opt for opt in action.option_strings if opt.startswith("--"))
    return flags


def test_every_documented_flag_exists() -> None:
    """A documented flag that argparse rejects is an instruction that fails.

    Exactly the failure this project exists to surface, in the one place it
    cannot reach: `--verify` is not a path, a commit or a tag, so no rule here
    can tell whether it still works.
    """
    known = _parser_flags()
    offenders: list[str] = []
    checked = 0
    for doc in DOCS:
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if not INVOCATION.search(line):
                continue
            for flag in FLAG.findall(line):
                checked += 1
                if flag not in known:
                    offenders.append(f"{doc.name}:{number}: {flag}")

    assert checked > 10, (
        f"only {checked} flags examined across {len(DOCS)} documents; the "
        f"invocation pattern has stopped matching and this proves nothing"
    )
    assert not offenders, (
        "documented flags the command does not accept:\n  " + "\n  ".join(offenders)
        + f"\n\nargparse offers: {', '.join(sorted(known))}"
    )


def test_every_rule_is_documented() -> None:
    """A shipped rule nobody wrote down is a finding whose reader has no idea
    what fired or why.

    Requires a row in the rules TABLE, not merely a mention. The first version
    accepted the name appearing anywhere, and a probe that deleted
    `dead-pinned-ref`'s row still passed, because the name also appears in a
    paragraph further down. "Mentioned in passing" and "explained where a
    reader looks up rules" are different things, and only the second is
    documentation.
    """
    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    from extant.session import RULES

    kinds = [rule.kind for rule in RULES]
    assert len(kinds) > 5, f"only {len(kinds)} rules found; the import is wrong"

    # BOTH tables. Checking only the README let SKILL.md fall two rules behind
    # while still heading its table "the eleven validation rules": a reader of
    # the installed skill never sees the README, and no test looked.
    for relative in ("README.md", "plugin/skills/extant/SKILL.md"):
        text = (PACKAGE_ROOT / relative).read_text(encoding="utf-8")
        missing = [kind for kind in kinds if f"| `{kind}` |" not in text]
        assert not missing, (
            f"rules that ship but have no row in {relative}'s rules table:\n  "
            + "\n  ".join(missing)
        )


def test_no_document_invents_a_rule() -> None:
    """The other direction: prose naming a rule that does not exist.

    A reader who greps for it finds nothing, and a reader who waits for it to
    fire waits forever. Caught by shape, so a renamed rule leaves its old name
    behind visibly rather than silently.
    """
    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    from extant.session import RULES

    real = {rule.kind for rule in RULES} | {"missing-document", "bare-dead-sha"}
    # Rule names are backticked, lowercase and hyphenated: `dead-md-anchor`.
    shaped = re.compile(r"`((?:dead|stale|false|unknown|possible|inconsistent)-[a-z-]+)`")

    offenders: list[str] = []
    checked = 0
    for doc in DOCS:
        for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for name in shaped.findall(line):
                checked += 1
                if name not in real:
                    offenders.append(f"{doc.name}:{number}: {name}")

    assert checked > 10, f"only {checked} rule mentions found; the shape is wrong"
    assert not offenders, (
        "documents name rules that do not exist:\n  " + "\n  ".join(offenders)
    )


def test_every_documented_preset_exists_and_every_preset_is_documented() -> None:
    """Both directions, because each fails differently.

    A documented preset that does not exist is an install command that errors.
    A preset nobody documented is a feature with no discoverable name - which
    is how the three newest ones sat unmentioned in the README's table.
    """
    sys.path.insert(0, str(SKILL_ROOT))
    from install import PRESETS

    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"--preset ([a-z-]+)", readme))
    documented |= {name for name in PRESETS if f"| `{name}` |" in readme}

    assert len(PRESETS) > 3, f"only {len(PRESETS)} presets found; the import is wrong"
    assert documented, "no preset names found in the README at all"

    invented = documented - set(PRESETS)
    assert not invented, f"README names presets that do not exist: {sorted(invented)}"

    undocumented = set(PRESETS) - documented
    assert not undocumented, (
        f"presets that ship but appear nowhere in the README: {sorted(undocumented)}"
    )


def test_the_python_floor_is_stated_consistently() -> None:
    """One version claim, in four places, that must not drift apart.

    `requires-python` is the machine-readable truth; the badge, the prose and
    the CI matrix are separate assertions of the same fact, and nothing joins
    them. The matrix in particular could quietly stop testing the floor the
    README promises, and the claim would keep reading as verified.

    This is the shape the tool's own `inconsistent-artifact` rule exists for,
    applied where that rule cannot reach: a badge URL is an external link, and
    external links are deliberately never checked.
    """
    try:
        # Arrives in 3.11, past the checker's 3.10 target; extant/config.py
        # says why the suppression stands.
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:      # Python < 3.11, see requirements-test.txt
        import tomli as tomllib

    with open(PACKAGE_ROOT / "pyproject.toml", "rb") as fh:
        declared = tomllib.load(fh)["project"]["requires-python"]
    floor = declared.lstrip(">=").strip()
    assert re.fullmatch(r"3\.\d+", floor), f"unreadable requires-python: {declared!r}"

    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (PACKAGE_ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8")
    classifiers = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    disagree: list[str] = []
    # The badge URL spells it `python-3.9%2B-blue`, so the bare version is enough.
    if f"python-{floor}" not in readme:
        disagree.append(f"README badge does not name {floor}")
    if f"Python {floor} or newer" not in readme:
        disagree.append(f"README prose does not say 'Python {floor} or newer'")
    if f'"{floor}"' not in workflow:
        disagree.append(f"the CI matrix does not run {floor}, so the floor is untested")
    if f"Python :: {floor}" not in classifiers:
        disagree.append(f"pyproject classifiers omit {floor}")

    assert not disagree, (
        f"requires-python says {declared!r}, but:\n  " + "\n  ".join(disagree)
    )


def test_the_classifiers_name_exactly_the_pythons_ci_tests() -> None:
    """The test above joins the BOTTOM of the range; nothing joined the top.

    A version in the `tests` job's matrix and a `Programming Language ::
    Python :: 3.X` classifier are the same claim made twice - "this runs on
    3.X" - once to CI and once to everyone reading the PyPI page. Adding
    3.14 to one and not the other passed every check here, which is the
    shape the test above was written for, one end of the range later. Found
    while planning Phase 56, which adds 3.14 to both.

    The free-threaded job names `3.14t` as a scalar, not in the matrix list,
    and is not a claim the classifiers make; only the list is read, and it
    must be the only list.
    """
    workflow = (PACKAGE_ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8")
    pyproject = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    lists = re.findall(r"^\s*python-version:\s*\[([^\]]*)\]", workflow, re.M)
    assert len(lists) == 1, f"expected one python-version matrix list, found {lists}"
    tested = set(re.findall(r'"(3\.\d+)"', lists[0]))
    classified = set(re.findall(r'"Programming Language :: Python :: (3\.\d+)"',
                                pyproject))
    assert tested, f"read no versions from the matrix list {lists[0]!r}"

    def ordered(versions: set[str]) -> list[str]:
        return sorted(versions, key=lambda v: int(v.split(".")[1]))

    assert tested == classified, (
        f"CI tests {ordered(tested)} but the classifiers claim {ordered(classified)}: "
        f"untested claims {ordered(classified - tested)}, "
        f"unclaimed legs {ordered(tested - classified)}")


def test_every_setting_is_documented_where_users_look() -> None:
    """A config key nobody wrote down is a feature nobody can find.

    The checks above compare documented `--flags` against argparse, which is
    why a documented flag cannot rot. Nothing compared config KEYS against
    anything, and that gap shipped: `release_claims_name_our_tags` changed what
    `dead-release-tag` reports BY DEFAULT, and the rule tables in README.md and
    SKILL.md went on promising the old behaviour while the setting itself
    appeared in no user-facing document at all. It was written down twice, in a
    comment inside `DEFAULTS` and in this repository's own `.extant.toml`,
    neither of which anyone installing the tool reads.

    `references/config.md` is where a user looks. Every default belongs there.
    """
    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    from extant.config import DEFAULTS

    documented = (SKILL_ROOT / "references" / "config.md").read_text(
        encoding="utf-8")
    missing = sorted(key for key in DEFAULTS if key not in documented)
    assert not missing, (
        f"{len(missing)} of {len(DEFAULTS)} settings appear nowhere in "
        f"references/config.md: {missing}"
    )


def test_the_harness_readme_still_counts_the_properties_it_claims() -> None:
    """A count in prose, beside a list that grows, with no reader.

    `tests/harnesses/README.md` said "19 of 19 properties are observed going
    red" while the harness watched 21 and could provoke only 20, and said
    three breakages were contrived while four were. Both numbers were wrong,
    both had been wrong for some time, and neither could fail: no test read
    that file, and a count is the one claim extant deliberately refuses - it
    was true when written and there is nothing in git to compare it against.

    So it is checked here, against the harness's own lists rather than against
    a second copy of the numbers. Every assertion is two-sided: the sentence
    must be FOUND as well as correct. A reworded heading this regex no longer
    matches would otherwise report the silence of a passing check, which is
    the failure the denominators in `registry.py` exist to make visible.
    """
    sys.path.insert(0, str(PACKAGE_ROOT / "tests" / "harnesses"))
    from fuzz_selfcheck import ALL_PROPERTIES, BREAKAGES

    readme = (PACKAGE_ROOT / "tests" / "harnesses" / "README.md").read_text(
        encoding="utf-8")
    watched = len(ALL_PROPERTIES)
    contrived = sum(1 for item in BREAKAGES if item.contrived)

    # Whitespace-tolerant because markdown reflows: both of these sentences
    # already wrap mid-phrase, and a rewrap is not a change to the claim.
    observed_claim = re.search(
        r"\*\*(\d+)\s+of\s+(\d+)\s+properties\s+are\s+observed\s+going\s+red\*\*",
        readme)
    assert observed_claim is not None, (
        "tests/harnesses/README.md no longer says how many properties are "
        "observed going red. Restore the sentence or retarget this test: a "
        "check that cannot find its subject must not pass."
    )
    assert [int(n) for n in observed_claim.groups()] == [watched, watched], (
        f"the harness watches {watched} properties and `--self-check` gates "
        f"on all of them going red, but the README says "
        f"{observed_claim.group(0)}"
    )

    contrived_claim = re.search(
        r"\*\*(\d+)\s+of\s+the\s+(\d+)\s+need\s+contrived\s+breakages\*\*",
        readme)
    assert contrived_claim is not None, (
        "tests/harnesses/README.md no longer says how many breakages are "
        "contrived. Restore the sentence or retarget this test."
    )
    assert [int(n) for n in contrived_claim.groups()] == [contrived, watched], (
        f"{contrived} of {watched} breakages are marked contrived, but the "
        f"README says {contrived_claim.group(0)}"
    )


def test_every_setting_an_empty_value_switches_off_is_documented() -> None:
    """`''` means OFF for eight settings since Phase 59, and default for the
    rest - a difference a reader cannot guess, so each one is named, set
    empty, in the section of `references/config.md` that says so."""
    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    from extant.config import DISABLEABLE

    text = (SKILL_ROOT / "references" / "config.md").read_text(encoding="utf-8")
    start = text.index("## Switching")
    section = text[start:text.index("\n## ", start + 1)]
    missing = sorted(key for key in DISABLEABLE
                     if not re.search(rf"^{key}\s*=\s*''", section, re.M))
    assert not missing, (
        f"references/config.md does not show these switched off: {missing}")
