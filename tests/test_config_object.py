"""Config is built in exactly one place, and rebuilding it is total.

The bug this shape prevents, recorded when `_CONFIG_DERIVED` was introduced:
nineteen scattered assignments plus a SECOND list naming which to refresh. The
two diverged, `_SECTION_HEADER` was computed rather than copied, and it went
stale on every reload.
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
        "it, which is the exact staleness _CONFIG_DERIVED exists to prevent")


def _canonical(value: object) -> object:
    """Compiled patterns compare by identity, so compare what they hold."""
    if isinstance(value, re.Pattern):
        return f"re:{value.pattern}"
    return value


def test_the_shim_derives_one_global_per_config_field() -> None:
    """`_ACTIVE` and the shim's globals must come from ONE build.

    Two tables that describe the same thing diverge - that is the whole reason
    `Config` exists - and `_ACTIVE` alongside `_CONFIG_DERIVED` is two tables
    unless `_apply_config` derives both from a single Config. A name added to
    one and not the other fails the count; an `_apply_config` that rebinds
    CONFIG without rebuilding `_ACTIVE` fails the comparison.
    """
    import extant_collect as hc
    from extant.config import Config

    fields = dataclasses.fields(Config)
    assert len(hc._CONFIG_DERIVED) == len(fields), (
        f"{len(hc._CONFIG_DERIVED)} derived globals against {len(fields)} "
        f"Config fields; one table gained a value the other did not")

    assert hc._ACTIVE is not None, "_apply_config never set _ACTIVE"
    rebuilt = Config.build(hc.CONFIG)
    stale = [f.name for f in fields
             if _canonical(getattr(hc._ACTIVE, f.name))
             != _canonical(getattr(rebuilt, f.name))]
    assert not stale, (
        f"compared {len(fields)} fields; _ACTIVE disagrees with a fresh build "
        f"from the current CONFIG in: {stale}")

    # WIRING, not just count. Both checks above pass even if an entry reads
    # the WRONG field - `"TRUNK": lambda c: c.primary_doc` still leaves the
    # table at 21 entries, and never touches _ACTIVE, since neither check
    # above ever calls a _CONFIG_DERIVED lambda.
    #
    # Give every field a value no other field shares - its own name - and
    # call each lambda against that Config directly. Built directly rather
    # than through `Config.build`, which maps one fixed StatusConfig and has
    # no way to make 21 fields simultaneously distinct in one call; `Config`
    # itself is a plain `@dataclass(frozen=True)` with no `__post_init__`, so
    # a field typed for a compiled pattern or a bool accepts its own name as
    # a plain string with no validation to fail.
    #
    # A correctly wired table then reads back exactly the 21 field names,
    # each once. A mis-wired entry breaks that bijection from either side:
    # its target field's name is produced twice (once by the entry that
    # rightly reads it, once by the mis-wired one) and its own field's name
    # is not produced at all - caught whether the mistake points at another
    # field or is simply missing. Neither the count nor the full-object
    # comparison above can see this, because both are blind to which
    # specific field each entry's lambda actually reads.
    sentinel = Config(**{f.name: f.name for f in fields})
    produced = sorted(build(sentinel) for build in hc._CONFIG_DERIVED.values())
    expected = sorted(f.name for f in fields)
    assert produced == expected, (
        f"_CONFIG_DERIVED entries do not all read the field their name "
        f"claims - got {produced}, expected {expected}")
