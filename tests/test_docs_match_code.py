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
    from extant_collect import build_parser

    flags: set[str] = set()
    for action in build_parser()._actions:
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
    from extant_collect import RULES

    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    kinds = [rule.kind for rule in RULES]

    assert len(kinds) > 5, f"only {len(kinds)} rules found; the import is wrong"
    missing = [kind for kind in kinds if f"| `{kind}` |" not in readme]
    assert not missing, (
        "rules that ship but have no row in the README's rules table:\n  "
        + "\n  ".join(missing)
    )


def test_no_document_invents_a_rule() -> None:
    """The other direction: prose naming a rule that does not exist.

    A reader who greps for it finds nothing, and a reader who waits for it to
    fire waits forever. Caught by shape, so a renamed rule leaves its old name
    behind visibly rather than silently.
    """
    sys.path.insert(0, str(SKILL_ROOT / "payload"))
    from extant_collect import RULES

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
        import tomllib
    except ModuleNotFoundError:      # Python < 3.11, see requirements-dev.txt
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
    from extant_config import DEFAULTS

    documented = (SKILL_ROOT / "references" / "config.md").read_text(
        encoding="utf-8")
    missing = sorted(key for key in DEFAULTS if key not in documented)
    assert not missing, (
        f"{len(missing)} of {len(DEFAULTS)} settings appear nowhere in "
        f"references/config.md: {missing}"
    )
