"""Config is built in exactly one place, and rebuilding it is total.

The bug this shape prevents, recorded when the one-place build was introduced:
nineteen scattered assignments plus a SECOND list naming which to refresh. The
two diverged, the section header was computed rather than copied, and it went
stale on every reload. The table of module globals that first closed that
gap, `_CONFIG_DERIVED`, is gone in turn - every reader takes the built
`Config` itself now - so the property here is about that one object.
"""
from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

PAYLOAD = Path(__file__).resolve().parent.parent / "plugin" / "skills" / "extant" / "payload"
sys.path.insert(0, str(PAYLOAD))

EXPECTED = {
    "primary_doc", "archive_doc", "retain_entries", "trunk",
    "consistency_timeout", "archive_header", "base_header", "phase_prefix",
    "pointer_prefix", "phase_task", "phase_bare", "todo_marker",
    "live_phrases", "branch_token", "path_pointer", "merge_claim",
    "release_tag", "release_claims_are_ours", "section_header",
    "todo_excluded_files", "todo_excluded_dir_prefix",
}


def _defaults(tmp_path: Path):
    """The default StatusConfig.

    `StatusConfig()` cannot be called bare: every field before `source` is
    required, so a no-argument construction raises TypeError. The supported way
    to obtain the defaults is to load them from a repository that has no
    `.extant.toml`, which is what this does.

    The `.git` marker bounds `load_config`'s upward search. Without it the
    search can climb out of tmp_path and reach this repository's own settings,
    and the assertions below would then compare something other than the
    defaults while looking exactly the same.
    """
    from extant.config import load_config

    (tmp_path / ".git").mkdir(exist_ok=True)
    status = load_config(tmp_path)
    assert status.source == "defaults", (
        f"settings came from {status.source}, not the defaults, so this test "
        f"is measuring the wrong configuration")
    return status


def test_config_carries_every_derived_value(tmp_path) -> None:
    from extant.config import Config

    built = Config.build(_defaults(tmp_path))
    names = {f.name for f in dataclasses.fields(built)}
    assert names == EXPECTED, (
        f"carrying {len(names)} of {len(EXPECTED)} derived values; "
        f"missing {sorted(EXPECTED - names)}, unexpected {sorted(names - EXPECTED)}")


def test_a_rebuilt_config_differs_in_every_value_that_changed(tmp_path) -> None:
    """A rebuild that copies some values and computes others is where the
    forgotten special case lives. `section_header` is COMPUTED from
    entry_prefix, so a rebuild that only copies leaves it stale.
    """
    from extant.config import Config

    status = _defaults(tmp_path)
    first = Config.build(status)
    second = Config.build(dataclasses.replace(status, entry_prefix="Stage"))
    assert first.phase_prefix != second.phase_prefix
    assert first.section_header.pattern != second.section_header.pattern, (
        "section_header is computed from entry_prefix and did not change with "
        "it, which is the exact staleness the one-place build exists to prevent")


def _canonical(value: object) -> object:
    """Compiled patterns compare by identity, so compare what they hold."""
    if isinstance(value, re.Pattern):
        return f"re:{value.pattern}"
    return value


def test_every_reader_is_handed_the_one_built_config(tmp_path) -> None:
    """`config()` and `context(repo).config` hand out ONE object, and it is
    what a fresh build from the current CONFIG gives.

    This replaced a bijection check between `Config`'s fields and a table of
    twenty-one module globals derived from them, `_CONFIG_DERIVED`. That
    table was the second copy of the configuration - one for the rules,
    which read `ctx.config`, and one for the modes, which read
    `session.PRIMARY_DOC` - kept from diverging only because `_apply_config`
    wrote both from one build, and invisible to a type checker because it
    was written through `globals()`. The globals are gone, so there is no
    second table to keep in step. What is left to guard is narrower and
    stated here: whichever door a caller reaches the configuration through,
    it gets the object `_apply_config` last built, and that object is
    current - an `_apply_config` that rebinds CONFIG without rebuilding it
    fails the comparison below.
    """
    from extant import session as hc
    from extant.config import Config

    built = hc.config()
    assert built is hc.context(tmp_path).config, (
        "config() and context().config hand out different objects, so a mode "
        "and a rule could be reading two configurations at once")

    fields = dataclasses.fields(Config)
    rebuilt = Config.build(hc.CONFIG)
    stale = [f.name for f in fields
             if _canonical(getattr(built, f.name))
             != _canonical(getattr(rebuilt, f.name))]
    assert not stale, (
        f"compared {len(fields)} fields; config() disagrees with a fresh "
        f"build from the current CONFIG in: {stale}")
